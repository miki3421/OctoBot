"""Apply the operator-approved replacement of exactly four cold audit copies.

Dry-run is the default. The exact catalog flag identifies the reviewed artifact;
it does not itself confer operator permission. Operational use requires the
explicit four-package consent recorded on 26 October. No live path is in scope.
"""
import argparse
import datetime as dt
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import stat
import subprocess
import uuid

spec = importlib.util.spec_from_file_location('dedup', Path(__file__).with_name('deduplicate_cold_audit.py'))
d = importlib.util.module_from_spec(spec);spec.loader.exec_module(d)
APPROVED_SHA = '295b95ea72e3992dfd50b19747b9cac25f5c4ed7abc94a8bf120b2f1b469ba22'


def regular_control(path):
    s = path.lstat()
    if not stat.S_ISREG(s.st_mode) or s.st_uid != 0 or s.st_mode & 0o022:
        raise ValueError('untrusted_archive_control')


def durable_file(path):
    fd = os.open(path, os.O_RDONLY)
    try:os.fsync(fd)
    finally:os.close(fd)


def inventory(root):
    if root.is_symlink() or not root.is_dir() or root.resolve() != root:
        raise ValueError('cold_root_boundary')
    files, directories = set(), []
    for path in root.rglob('*'):
        mode = path.lstat().st_mode
        if stat.S_ISREG(mode):
            files.add(str(path.relative_to(root)))
        elif stat.S_ISDIR(mode):
            directories.append(path)
        else:
            raise ValueError('cold_special_or_linked_path')
    return files, directories


def safe_names(manifest):
    for name in manifest:
        p = Path(name)
        if p.is_absolute() or any(part in ('', '.', '..') for part in name.split('/')):
            raise ValueError('manifest_path_boundary')


def preflight(catalog_path, expected_sha):
    regular_control(catalog_path)
    if d.digest(catalog_path) != expected_sha:
        raise ValueError('catalog_digest')
    catalog = json.loads(catalog_path.read_text())
    entries = catalog['packages']
    if (catalog['scope'] != 'COLD_ARCHIVAL_PREPARATION_ONLY_NO_SOURCE_REMOVAL'
            or len(entries) != len(d.COLD) or {e['package'] for e in entries} != set(d.COLD)):
        raise ValueError('exact_four_package_scope')
    busy = d.opened_inodes();items = []
    for entry in entries:
        root = d.ROOT/entry['package']
        if root.parent != d.ROOT or root.resolve() != root:
            raise ValueError('cold_root_boundary')
        manifest_path = Path(entry['manifest']).resolve()
        archive_path = Path(entry['archive']).resolve()
        for path in (manifest_path, archive_path):
            if path.parent != catalog_path.parent.resolve():
                raise ValueError('archive_path_boundary')
            regular_control(path)
        if d.digest(manifest_path) != entry['manifest_sha256'] or d.digest(archive_path) != entry['archive_sha256']:
            raise ValueError('archive_or_manifest_digest')
        if archive_path.stat().st_size != entry['archive_bytes'] or not entry['byte_metadata_roundtrip']:
            raise ValueError('unqualified_archive')
        manifest = json.loads(manifest_path.read_text());safe_names(manifest)
        names, _ = inventory(root)
        if names != set(manifest) or len(names) != entry['files']:
            raise ValueError('cold_source_membership_changed')
        for name, item in manifest.items():
            path = root/name;before = d.info(path)
            if before != item['before'] or (before['device'], before['inode']) in busy:
                raise ValueError('cold_source_changed_or_open')
            if d.digest(path) != item['sha256'] or d.info(path) != before:
                raise ValueError('cold_source_digest_changed')
        items.append(dict(root=root, manifest=manifest, entry=entry))
    return catalog, items


def refuse_active_mounts(roots):
    ids = subprocess.check_output(['docker', 'ps', '-q'], text=True).split()
    if not ids:
        return
    containers = json.loads(subprocess.check_output(['docker', 'inspect', *ids], text=True))
    for container in containers:
        for mount in container['Mounts']:
            source = Path(mount['Source']).resolve()
            if any(source.is_relative_to(root) or root.is_relative_to(source) for root in roots):
                raise ValueError('active_container_mount_overlap')


def recheck(items):
    busy = d.opened_inodes()
    for item in items:
        names, _ = inventory(item['root'])
        if names != set(item['manifest']):
            raise ValueError('cold_source_membership_changed')
        for name, record in item['manifest'].items():
            s = d.info(item['root']/name)
            if s != record['before'] or (s['device'], s['inode']) in busy:
                raise ValueError('cold_source_changed_or_open')


def apply(items, catalog_path, result_path):
    """Recheck all sources before moving any; unlink only manifest-listed files."""
    recheck(items)
    durable_file(catalog_path)
    for item in items:
        durable_file(Path(item['entry']['archive']))
        durable_file(Path(item['entry']['manifest']))
    staging = result_path.parent/('repack-staging-'+uuid.uuid4().hex)
    staging.mkdir(mode=0o700)
    moved = []
    try:
        for item in items:
            source = item['root'];target = staging/source.name
            os.rename(source, target);moved.append((source, target, item))
        recheck([dict(item, root=target) for _,target,item in moved])
    except Exception:
        for source,target,_ in reversed(moved):
            os.rename(target,source)
        staging.rmdir()
        raise
    # The verified archives and catalog remain outside all staged source roots.
    result = dict(scope='OPERATOR_APPROVED_FOUR_COLD_AUDIT_REPLACEMENT_ONLY',
                  catalog_sha256=d.digest(catalog_path), started_at=dt.datetime.now(dt.timezone.utc).isoformat(),
                  staging=str(staging), phase='SOURCES_STAGED', packages=[])
    result_path.write_text(json.dumps(result,indent=2)+'\n');durable_file(result_path)
    removed_inodes = {}
    for source, target, item in moved:
        source.mkdir(mode=0o700)
        pointer = dict(state='ARCHIVED', archive=item['entry']['archive'],
                       archive_sha256=item['entry']['archive_sha256'],
                       manifest=item['entry']['manifest'], manifest_sha256=item['entry']['manifest_sha256'],
                       catalog=str(catalog_path), catalog_sha256=result['catalog_sha256'],
                       file_count=len(item['manifest']), restore_tool='scripts/verify_cold_archive.py')
        pointer_path = source/'ARCHIVED.json'
        pointer_path.write_text(json.dumps(pointer,indent=2)+'\n');pointer_path.chmod(0o440)
        durable_file(pointer_path)
        fd = os.open(source,os.O_DIRECTORY)
        try:os.fsync(fd)
        finally:os.close(fd)
        # Exact file set only; no recursive deletion and no traversal through links.
        for name in item['manifest']:
            path = target/name
            expected = dict(item['manifest'][name]['before'])
            identity = (expected['device'], expected['inode'])
            expected['links'] -= removed_inodes.get(identity, 0)
            if d.info(path) != expected:
                raise ValueError('staged_identity_changed')
            path.unlink()
            removed_inodes[identity] = removed_inodes.get(identity, 0)+1
        remaining, directories = inventory(target)
        if remaining:
            raise ValueError('unexpected_staged_file_retained')
        for directory in sorted(directories,key=lambda p:len(p.parts),reverse=True):
            directory.rmdir()
        target.rmdir()
        result['packages'].append(dict(package=source.name,files_archived=len(item['manifest']),pointer=str(pointer_path)))
        result_path.write_text(json.dumps(result,indent=2)+'\n');durable_file(result_path)
    staging.rmdir()
    result['completed_at'] = dt.datetime.now(dt.timezone.utc).isoformat()
    result['completed'] = True
    result['phase'] = 'COMPLETE'
    result_path.write_text(json.dumps(result,indent=2)+'\n');durable_file(result_path)
    return result


def main():
    p = argparse.ArgumentParser()
    p.add_argument('--catalog',type=Path,required=True)
    p.add_argument('--result',type=Path,required=True)
    p.add_argument('--apply-catalog-sha256')
    args = p.parse_args();os.umask(0o077)
    if os.geteuid() != 0 or args.result.exists() or args.result.is_symlink():
        raise ValueError('root_fresh_result_required')
    catalog_path = args.catalog.resolve()
    result_path = args.result.resolve()
    if args.catalog.is_symlink() or result_path.parent != catalog_path.parent.parent:
        raise ValueError('control_path_boundary')
    catalog,items = preflight(catalog_path,APPROVED_SHA)
    refuse_active_mounts([item['root'] for item in items])
    if args.apply_catalog_sha256:
        if args.apply_catalog_sha256 != APPROVED_SHA:
            raise ValueError('exact_reviewed_catalog_required')
        result = apply(items,catalog_path,result_path)
    else:
        result = dict(preflight_passed=True,mutated=False,files=sum(len(x['manifest']) for x in items),
                      original_physical_bytes=catalog['original_regular_file_bytes_recoverable'])
        args.result.write_text(json.dumps(result,indent=2)+'\n')
    print(json.dumps(result))


if __name__=='__main__':
    main()
