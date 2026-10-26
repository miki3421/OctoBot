"""Coalesce byte-identical cold SQLite copies; keep every named file and byte.

Default creates a plan. Apply needs its exact SHA. No live state directory,
volume, log, dataset or journal path is removed. Shared copies become read-only
so a future recovery must start from a new private copy, not mutate evidence.
"""
import argparse
import collections
import hashlib
import json
import os
from pathlib import Path
import stat
import uuid

ROOT=Path('/root/auto_trading_sys/audit-evidence').resolve()
COLD=('btc-old-source-io-20261023','btc-legacy-retirement-20261024','intraday-pair-latency-20261024','btc-pair-source-io-fix-20261022')


def digest(path):
    h=hashlib.sha256()
    with Path(path).open('rb') as f:
        for chunk in iter(lambda:f.read(8*2**20),b''):h.update(chunk)
    return h.hexdigest()


def info(path):
    s=path.lstat()
    if not stat.S_ISREG(s.st_mode):raise ValueError('regular_file_required')
    return dict(size=s.st_size,uid=s.st_uid,gid=s.st_gid,mode=stat.S_IMODE(s.st_mode),mtime_ns=s.st_mtime_ns,device=s.st_dev,inode=s.st_ino,links=s.st_nlink)


def opened_inodes():
    result=set()
    for folder in Path('/proc').glob('[0-9]*/fd'):
        try:entries=list(folder.iterdir())
        except OSError:continue
        for path in entries:
            try:s=path.stat()
            except OSError:continue
            if stat.S_ISREG(s.st_mode):result.add((s.st_dev,s.st_ino))
    return result


def sample(path):
    with path.open('rb') as f:
        first=f.read(2**20);f.seek(max(0,path.stat().st_size-2**20));last=f.read(2**20)
    return hashlib.sha256(first+last).hexdigest()


def make_plan(roots):
    groups=collections.defaultdict(list)
    for root in roots:
        for path in root.rglob('*.sqlite'):
            if path.is_symlink():continue
            s=info(path)
            if s['size']<10*2**20:continue
            groups[(s['size'],s['uid'],s['gid'],s['mode']&~0o222,s['device'],sample(path))].append(path)
    result=[]
    for paths in groups.values():
        if len(paths)<2:continue
        hashes=collections.defaultdict(list)
        for path in paths:
            before=info(path);sha=digest(path)
            if info(path)!=before:raise ValueError('cold_file_changed_during_hash')
            hashes[sha].append(dict(path=str(path),before=before))
        for sha,files in hashes.items():
            if len({(f['before']['device'],f['before']['inode']) for f in files})>1:
                result.append(dict(sha256=sha,files=files))
    return dict(scope='COLD_AUDIT_BYTE_IDENTICAL_HARDLINK_PLAN_V1',groups=result)


def apply_group(group,allowed):
    files=group['files'];busy=opened_inodes()
    for file in files:
        path=Path(file['path']);s=info(path)
        if path.resolve()!=path or not any(path.is_relative_to(root) for root in allowed):raise ValueError('cold_boundary')
        if s!=file['before'] or (s['device'],s['inode']) in busy:raise ValueError('changed_or_open_file')
        if digest(path)!=group['sha256']:raise ValueError('cold_digest_changed')
    canonical=Path(files[0]['path']);meta=files[0]['before'];mode=meta['mode']&~0o222
    if any((f['before']['uid'],f['before']['gid'],f['before']['mode']&~0o222)!=(meta['uid'],meta['gid'],mode) for f in files):raise ValueError('custody_mismatch')
    for file in files:os.chmod(file['path'],mode)
    retained=canonical.stat();released=set();count=0
    for file in files[1:]:
        path=Path(file['path']);s=path.stat()
        if (s.st_dev,s.st_ino)==(retained.st_dev,retained.st_ino):continue
        # All paths remain present; replace only an identical physical copy.
        temp=path.with_name('.dedup-'+uuid.uuid4().hex)
        os.link(canonical,temp);os.replace(temp,path)
        fd=os.open(path.parent,os.O_DIRECTORY)
        try:os.fsync(fd)
        finally:os.close(fd)
        released.add((s.st_dev,s.st_ino));count+=1
    if digest(canonical)!=group['sha256'] or any(Path(f['path']).stat().st_ino!=retained.st_ino for f in files):raise ValueError('hardlink_readback')
    return dict(sha256=group['sha256'],canonical=str(canonical),paths_retained=[f['path'] for f in files],linked_paths=count,
                byte_size=retained.st_size,estimated_released_bytes=len(released)*retained.st_size,read_only_mode=oct(mode))


def main():
    p=argparse.ArgumentParser();p.add_argument('--plan',type=Path,required=True);p.add_argument('--apply-sha256');p.add_argument('--result',type=Path);a=p.parse_args()
    roots=[ROOT/x for x in COLD]
    if a.apply_sha256:
        if os.geteuid()!=0 or digest(a.plan)!=a.apply_sha256 or not a.result:raise ValueError('exact_root_plan_required')
        plan=json.loads(a.plan.read_text())
        if plan['scope']!='COLD_AUDIT_BYTE_IDENTICAL_HARDLINK_PLAN_V1':raise ValueError('plan_scope')
        result=[]
        for group in plan['groups']:
            result.append(apply_group(group,roots));a.result.write_text(json.dumps(result,indent=2)+'\n')
        print(json.dumps(dict(retained_paths=sum(len(r['paths_retained']) for r in result),estimated_released_GiB=sum(r['estimated_released_bytes'] for r in result)/2**30)))
    else:
        if a.plan.exists():raise ValueError('fresh_plan_required')
        plan=make_plan(roots);a.plan.write_text(json.dumps(plan,indent=2)+'\n');a.plan.chmod(0o440)
        print(json.dumps(dict(groups=len(plan['groups']),plan_sha256=digest(a.plan),potential_GiB=sum((len(g['files'])-1)*g['files'][0]['before']['size'] for g in plan['groups'])/2**30)))


if __name__=='__main__':main()
