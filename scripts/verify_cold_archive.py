"""Restore a digest-pinned cold archive privately and check SQLite read-only.

No source path is removed or changed. The restore is retained for inspection.
Only regular files declared in the manifest are materialized; archive links and
path traversal are refused. Existing destinations are never reused.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import sqlite3
import subprocess
import tarfile
import time
import urllib.parse


def digest(path):
    h = hashlib.sha256()
    with Path(path).open('rb') as stream:
        for chunk in iter(lambda:stream.read(8*2**20), b''):
            h.update(chunk)
    return h.hexdigest()


def member_name(value):
    value = value.removeprefix('./')
    path = Path(value)
    if not value or path.is_absolute() or any(p in ('', '.', '..') for p in value.split('/')):
        raise ValueError('unsafe_archive_path')
    return value


def restore(archive, manifest, destination):
    for name in manifest:
        if member_name(name) != name:
            raise ValueError('noncanonical_manifest')
    if destination.exists() or destination.is_symlink():
        raise ValueError('fresh_restore_required')
    total = sum(item['before']['size'] for item in manifest.values())
    fs = os.statvfs(destination.parent)
    if fs.f_bavail*fs.f_frsize < total + max(20*2**30, .15*fs.f_blocks*fs.f_frsize):
        raise ValueError('restore_headroom')
    destination.mkdir(mode=0o700)
    process = subprocess.Popen(['zstd', '--decompress', '--stdout', '--quiet', str(archive)], stdout=subprocess.PIPE)
    seen = set()
    try:
        with tarfile.open(fileobj=process.stdout, mode='r|') as contents:
            for item in contents:
                if item.isdir():
                    continue
                name = member_name(item.name)
                if not item.isfile() or name not in manifest or name in seen:
                    raise ValueError('undeclared_or_linked_member')
                expected = manifest[name]; before = expected['before']
                if (item.size, item.uid, item.gid, item.mode) != (before['size'], before['uid'], before['gid'], before['mode']):
                    raise ValueError('archive_metadata_mismatch')
                path = destination/name
                path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
                with contents.extractfile(item) as source, path.open('xb') as output:
                    shutil.copyfileobj(source, output, length=8*2**20)
                if digest(path) != expected['sha256']:
                    raise ValueError('restored_digest_mismatch')
                os.chown(path, before['uid'], before['gid'])
                path.chmod(before['mode'])
                os.utime(path, ns=(before['mtime_ns'], before['mtime_ns']))
                seen.add(name)
        if process.wait() != 0 or seen != set(manifest):
            raise ValueError('incomplete_archive')
    finally:
        process.stdout.close()
        if process.poll() is None:
            process.terminate();process.wait()
    return total


def check_databases(destination, manifest):
    result = {}
    for name, item in manifest.items():
        if not name.endswith('.sqlite'):
            continue
        if manifest.get(name+'-wal', {}).get('before', {}).get('size', 0):
            raise ValueError('nonempty_wal_needs_separate_restore_review')
        path = destination/name
        uri = 'file:'+urllib.parse.quote(str(path), safe='/')+'?mode=ro&immutable=1'
        connection = sqlite3.connect(uri, uri=True)
        try:
            deadline = time.monotonic()+300
            connection.set_progress_handler(lambda:1 if time.monotonic()>deadline else 0, 10000)
            connection.execute('PRAGMA query_only=ON')
            connection.execute('PRAGMA cache_size=-16384')
            status = [row[0] for row in connection.execute('PRAGMA integrity_check')]
            if status != ['ok']:
                raise ValueError('restored_sqlite_integrity')
            result[name] = status[0]
        finally:
            connection.close()
    for name, item in manifest.items():
        path = destination/name;s = path.stat();old = item['before']
        if (s.st_size, s.st_uid, s.st_gid, s.st_mode&0o777, s.st_mtime_ns) != (old['size'], old['uid'], old['gid'], old['mode'], old['mtime_ns']):
            raise ValueError('restored_metadata_changed')
        if digest(path) != item['sha256']:
            raise ValueError('restore_changed_by_read_only_check')
    return result


def main():
    p = argparse.ArgumentParser()
    p.add_argument('--archive', type=Path, required=True)
    p.add_argument('--archive-sha256', required=True)
    p.add_argument('--manifest', type=Path, required=True)
    p.add_argument('--destination', type=Path, required=True)
    p.add_argument('--result', type=Path, required=True)
    args = p.parse_args();started = time.monotonic()
    if digest(args.archive) != args.archive_sha256:
        raise ValueError('archive_digest_mismatch')
    manifest = json.loads(args.manifest.read_text())
    size = restore(args.archive, manifest, args.destination)
    dbs = check_databases(args.destination, manifest)
    result = dict(passed=True, files=len(manifest), restored_bytes=size,
                  sqlite_integrity=dbs, elapsed_seconds=time.monotonic()-started,
                  archive_sha256=args.archive_sha256, manifest_sha256=digest(args.manifest),
                  restored_files_retained=True, original_files_changed=False)
    args.result.write_text(json.dumps(result, indent=2)+'\n')
    print(json.dumps(result))


if __name__ == '__main__':
    main()
