"""Prepare and verify exact cold-audit archives. Never remove source data.

Only the four closed audit packages already inventoried on 26 October are in
scope. Material replacement of originals is a separate operator decision.
"""
import argparse
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import subprocess
import tarfile
import time

spec = importlib.util.spec_from_file_location('dedup', Path(__file__).with_name('deduplicate_cold_audit.py'))
d = importlib.util.module_from_spec(spec);spec.loader.exec_module(d)


def archive_one(root, output, floor):
    paths = sorted(root.rglob('*'))
    if any(path.is_symlink() for path in paths):
        raise ValueError('cold_symlink_requires_separate_review')
    files = [p for p in paths if p.is_file()]
    busy = d.opened_inodes();manifest = {}
    for path in files:
        before = d.info(path)
        if (before['device'], before['inode']) in busy:
            raise ValueError('cold_source_open')
        sha = d.digest(path)
        if d.info(path) != before:
            raise ValueError('cold_source_changed')
        manifest[str(path.relative_to(root))] = dict(before=before, sha256=sha)
    manifest_path = output/(root.name+'.manifest.json')
    manifest_path.write_text(json.dumps(manifest, indent=2)+'\n')
    archive = output/(root.name+'.tar.zst')
    tar = subprocess.Popen(['tar','--create','--file=-','--hard-dereference',
                            '--numeric-owner','--directory='+str(root),'.'], stdout=subprocess.PIPE)
    compressor = subprocess.Popen(['zstd','-T1','-3','--quiet','-o',str(archive)], stdin=tar.stdout)
    tar.stdout.close()
    try:
        while compressor.poll() is None:
            fs = os.statvfs(output)
            if fs.f_bavail*fs.f_frsize < floor:
                raise ValueError('archive_headroom_floor')
            time.sleep(1)
        if compressor.returncode or tar.wait():
            raise ValueError('archive_generation_failed')
    finally:
        for proc in (compressor, tar):
            if proc.poll() is None:
                proc.terminate();proc.wait()
    reader = subprocess.Popen(['zstd','--decompress','--stdout','--quiet',str(archive)], stdout=subprocess.PIPE)
    seen = set()
    try:
        with tarfile.open(fileobj=reader.stdout, mode='r|') as contents:
            for member in contents:
                if member.isdir():
                    continue
                name = member.name.removeprefix('./')
                if not member.isfile() or name not in manifest or name in seen:
                    raise ValueError('unexpected_archive_member')
                expected = manifest[name];old = expected['before']
                if (member.size,member.uid,member.gid,member.mode) != (old['size'],old['uid'],old['gid'],old['mode']):
                    raise ValueError('archive_metadata')
                h = hashlib.sha256()
                with contents.extractfile(member) as stream:
                    for chunk in iter(lambda:stream.read(8*2**20),b''):
                        h.update(chunk)
                if h.hexdigest() != expected['sha256']:
                    raise ValueError('archive_digest')
                seen.add(name)
        if reader.wait() or seen != set(manifest):
            raise ValueError('archive_incomplete')
    finally:
        reader.stdout.close()
        if reader.poll() is None:
            reader.terminate();reader.wait()
    for name,item in manifest.items():
        if d.info(root/name) != item['before']:
            raise ValueError('source_changed_during_archive')
    archive.chmod(0o440);manifest_path.chmod(0o440)
    return dict(package=root.name, files=len(manifest),
                logical_bytes=sum(item['before']['size'] for item in manifest.values()),
                archive_bytes=archive.stat().st_size, archive_sha256=d.digest(archive),
                manifest_sha256=d.digest(manifest_path), byte_metadata_roundtrip=True,
                source_files_unchanged=True, archive=str(archive), manifest=str(manifest_path))


def main():
    p = argparse.ArgumentParser();p.add_argument('--output',type=Path,required=True);args=p.parse_args()
    os.umask(0o077);args.output.mkdir(mode=0o700,parents=True,exist_ok=False)
    roots=[d.ROOT/name for name in d.COLD]
    # Account for existing hard links: removing one linked name does not free
    # that inode. Externally linked inodes are not counted as recoverable.
    inodes = {}
    for root in roots:
        for path in root.rglob('*'):
            if path.is_file() and not path.is_symlink():
                s=path.stat();key=(s.st_dev,s.st_ino)
                value=inodes.setdefault(key,dict(paths=0,links=s.st_nlink,bytes=s.st_blocks*512))
                value['paths']+=1
    physical=sum(v['bytes'] for v in inodes.values() if v['paths']==v['links'])
    fs=os.statvfs(args.output);floor=max(.17*fs.f_blocks*fs.f_frsize,30*2**30)
    results=[];started=time.monotonic()
    for root in roots:
        result=archive_one(root,args.output,floor);results.append(result)
        (args.output/'progress.json').write_text(json.dumps(results,indent=2)+'\n')
        print(json.dumps({k:result[k] for k in ('package','files','logical_bytes','archive_bytes','byte_metadata_roundtrip')}),flush=True)
    total_archives=sum(r['archive_bytes'] for r in results)
    result=dict(scope='COLD_ARCHIVAL_PREPARATION_ONLY_NO_SOURCE_REMOVAL',
                packages=results, original_regular_file_bytes_recoverable=physical,
                archive_bytes=total_archives, potential_net_recovery_bytes=physical-total_archives,
                elapsed_seconds=time.monotonic()-started, headroom_floor_bytes=int(floor),
                all_source_paths_retained=True)
    path=args.output/'catalog.json';path.write_text(json.dumps(result,indent=2)+'\n');path.chmod(0o440)
    print(json.dumps(dict(catalog_sha256=d.digest(path),potential_net_recovery_GiB=(physical-total_archives)/2**30)))


if __name__=='__main__':
    main()
