"""Bounded read-only capacity/IO attribution; no guest, Docker or SQLite writes.

Physical allocation, filesystem free space and process write traffic are distinct
measurements. The sampled file set is explicit; untracked growth stays a residual.
No process arguments, environment variables or guest data are collected.
"""
import argparse
import datetime as dt
import json
import os
from pathlib import Path
import subprocess
import time


def counters(path, separator=':'):
    result = {}
    for line in Path(path).read_text().splitlines():
        if separator not in line:
            continue
        key, value = line.split(separator, 1)
        parts = value.split()
        if parts and parts[0].isdigit():
            result[key] = int(parts[0]) * (1024 if len(parts) > 1 and parts[1] == 'kB' else 1)
    return result


def file_info(path):
    try:
        s = path.stat()
        return dict(logical_bytes=s.st_size, allocated_bytes=s.st_blocks*512,
                    device=s.st_dev, inode=s.st_ino, mtime_ns=s.st_mtime_ns)
    except OSError:
        return None


def sample(lab, image_root, log_paths):
    at = dt.datetime.now(dt.timezone.utc).isoformat()
    files = {}
    bases = [lab/'octobot-local/scalping', lab/'octobot-local/btc-intraday-pair-v1/state',
             lab/'octobot-local/v13-m1-management-v1', lab/'octobot-local/v13-m1-paper-v1']
    for base in bases:
        for path in base.rglob('*.sqlite*'):
            if path.is_file() and not path.is_symlink():
                item = file_info(path)
                if item:
                    files[str(path)] = dict(group='lab_active', **item)
    for path in image_root.rglob('*.qcow2'):
        if path.is_file() and not path.is_symlink():
            item = file_info(path)
            if item:
                files[str(path)] = dict(group='vm_images', **item)
    for path in log_paths:
        item = file_info(path)
        if item:
            files[str(path)] = dict(group='container_logs', **item)
    processes = {}
    for folder in Path('/proc').glob('[0-9]*'):
        try:
            status = counters(folder/'status')
            io = counters(folder/'io')
            stat = (folder/'stat').read_text()
            start_ticks = int(stat[stat.rfind(')')+2:].split()[19])
            processes[folder.name] = dict(name=(folder/'comm').read_text().strip(),
                start_ticks=start_ticks, io=io, rss=status.get('VmRSS', 0),
                swap=status.get('VmSwap', 0))
        except (OSError, ValueError, IndexError):
            continue
    vmstat = {}
    for line in Path('/proc/vmstat').read_text().splitlines():
        key, value = line.split()
        if key in ('pswpin', 'pswpout'):
            vmstat[key] = int(value)*os.sysconf('SC_PAGE_SIZE')
    fs = os.statvfs(lab)
    return dict(at=at, monotonic=time.monotonic(), files=files, processes=processes,
                memory=counters('/proc/meminfo'), swap_traffic_bytes=vmstat,
                filesystem=dict(device=lab.stat().st_dev, available_bytes=fs.f_bavail*fs.f_frsize,
                    free_bytes=fs.f_bfree*fs.f_frsize, total_bytes=fs.f_blocks*fs.f_frsize),
                pressure={name:Path('/proc/pressure', name).read_text() for name in ('memory', 'io')})


def compare(first, last):
    elapsed = last['monotonic']-first['monotonic']
    growth = {}; details = []; seen = set()
    for path, old in first['files'].items():
        new = last['files'].get(path)
        if not new or (old['device'], old['inode']) != (new['device'], new['inode']):
            continue
        identity = (new['device'], new['inode'])
        if identity in seen or new['device'] != last['filesystem']['device']:
            continue
        seen.add(identity)
        delta = new['allocated_bytes']-old['allocated_bytes']
        growth[new['group']] = growth.get(new['group'], 0)+delta
        details.append(dict(path=path, group=new['group'], allocated_delta=delta))
    writers = []
    for pid, new in last['processes'].items():
        old = first['processes'].get(pid)
        if old and old['start_ticks'] == new['start_ticks']:
            delta = new['io'].get('write_bytes', 0)-old['io'].get('write_bytes', 0)
            writers.append(dict(pid=int(pid), name=new['name'], write_bytes=delta,
                                cancelled_write_bytes=new['io'].get('cancelled_write_bytes', 0)-old['io'].get('cancelled_write_bytes', 0),
                                rss=new['rss'], swap=new['swap']))
    fs_growth = first['filesystem']['free_bytes']-last['filesystem']['free_bytes']
    return dict(start=first['at'], end=last['at'], elapsed_seconds=elapsed,
                filesystem_growth_bytes=fs_growth, allocated_growth_by_sampled_group=growth,
                untracked_or_transient_residual_bytes=fs_growth-sum(growth.values()),
                growing_files=sorted(details, key=lambda x:x['allocated_delta'], reverse=True)[:20],
                top_writers=sorted(writers, key=lambda x:x['write_bytes'], reverse=True)[:20],
                swap_bytes_per_second={key:(last['swap_traffic_bytes'][key]-value)/elapsed
                    for key, value in first['swap_traffic_bytes'].items()},
                interpretation='Process write traffic is not retained growth; sampled attribution excludes changed/new inodes and is not a forecast.')


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--samples', type=int, default=6)
    parser.add_argument('--interval', type=float, default=60)
    args = parser.parse_args()
    if not 2 <= args.samples <= 16 or not 5 <= args.interval <= 300:
        raise ValueError('bounded_sampling_required')
    args.output.mkdir(parents=True, exist_ok=False, mode=0o700)
    lab = Path('/root/auto_trading_sys').resolve()
    ids = subprocess.check_output(['docker', 'ps', '-q'], text=True).split()
    containers = json.loads(subprocess.check_output(['docker', 'inspect', *ids], text=True))
    log_paths = [Path(c['LogPath']) for c in containers if c['Name'].startswith('/octobot-') and c.get('LogPath')]
    records = []
    for i in range(args.samples):
        if i:
            time.sleep(args.interval)
        item = sample(lab, Path('/var/lib/libvirt/images'), log_paths)
        records.append(item)
        (args.output/f'sample-{i}.json').write_text(json.dumps(item, indent=2)+'\n')
        if i:
            report = compare(records[0], item)
            (args.output/'summary.json').write_text(json.dumps(report, indent=2)+'\n')
            print(json.dumps(dict(sample=i, elapsed_seconds=report['elapsed_seconds'], filesystem_growth_bytes=report['filesystem_growth_bytes'], groups=report['allocated_growth_by_sampled_group'])), flush=True)


if __name__ == '__main__':
    main()
