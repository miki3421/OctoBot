"""Passive local telemetry; never writes a collector or execution store.

work-card-355d630a-dd57-407b-af16-c4b29d82da39.
"""
import argparse
import datetime as dt
import json
import os
from pathlib import Path
import shutil
import sqlite3
import subprocess
import time


def counters(path):
    result = {}
    for line in Path(path).read_text().splitlines():
        key, *values = line.replace(':', '').split()
        if values and values[0].isdigit():
            result[key] = int(values[0])
    return result


def assess(sample, previous=None):
    alerts = []
    memory = sample['memory']
    if memory['available_bytes'] / memory['total_bytes'] < .10:
        alerts.append('MEMORY_AVAILABLE_BELOW_10_PERCENT')
    if memory['swap_total_bytes'] and memory['swap_free_bytes'] / memory['swap_total_bytes'] < .10:
        alerts.append('SWAP_OCCUPANCY_HIGH_NOT_PROOF_OF_THRASHING')
    if previous and sample['boot_id'] == previous['boot_id']:
        elapsed = sample['uptime_seconds'] - previous['uptime_seconds']
        if elapsed > 0:
            sample['swap_bytes_per_second'] = {
                k: max(0, sample['swap_pages'][k] - previous['swap_pages'][k]) * os.sysconf('SC_PAGE_SIZE') / elapsed
                for k in ('pswpin', 'pswpout')}
            if max(sample['swap_bytes_per_second'].values()) > 1024 * 1024:
                alerts.append('SWAP_ACTIVITY_OVER_1_MIB_PER_SECOND')
    for name, disk in sample['disks'].items():
        if disk['free_bytes'] / disk['total_bytes'] < .15:
            alerts.append('DISK_FREE_BELOW_15_PERCENT:' + name)
        if previous and name in previous.get('disks', {}):
            disk['used_delta_bytes'] = disk['used_bytes'] - previous['disks'][name]['used_bytes']
    for name, health in sample['collectors'].items():
        stale = health.get('error') or health.get('age_seconds', float('inf')) > health['warn_after_seconds']
        health['collection_state'] = 'UNAVAILABLE_OR_STALE' if stale else 'FRESH'
        prior = previous.get('collectors', {}).get(name, {}) if previous else {}
        if not stale and prior.get('collection_state') == 'UNAVAILABLE_OR_STALE':
            health['recovered_since_previous_sample'] = True
        if health.get('last_success_at') and prior.get('last_success_at'):
            health['success_interval_seconds'] = (dt.datetime.fromisoformat(health['last_success_at']) -
                dt.datetime.fromisoformat(prior['last_success_at'])).total_seconds()
        if stale:
            alerts.append('COLLECTOR_STALE_OR_UNREADABLE:' + name)
        if health.get('source_status', 'healthy') != 'healthy':
            alerts.append('COLLECTOR_SOURCE_UNHEALTHY:' + name)
    if sample.get('container_error'):
        sample['container_check_failure_streak'] = (previous or {}).get('container_check_failure_streak', 0) + 1
        alerts.append('CONTAINER_STATE_UNAVAILABLE')
    else:
        sample['container_check_failure_streak'] = 0
        for item in sample['containers']:
            if item['state'] != 'running' or item['health'] != 'healthy':
                alerts.append('CONTAINER_NOT_HEALTHY:' + item['name'])
    sample['alerts'] = alerts
    # Retain immediate raw visibility of failed checks. Only monitor blindness
    # needs two consecutive samples for email; confirmed unhealthy containers
    # and all resource/data alerts remain immediate.
    sample['notification_alerts'] = [a for a in alerts if not (
        a == 'CONTAINER_STATE_UNAVAILABLE' and sample['container_check_failure_streak'] < 2)]
    return sample


def inspect_containers(names, run=subprocess.run):
    template = '{"name":{{json .Name}},"state":{{json .State.Status}},"health":{{if .State.Health}}{{json .State.Health.Status}}{{else}}null{{end}},"restarts":{{.RestartCount}}}'
    failures = []
    for attempt in range(2):
        try:
            result = run(['docker', 'inspect', '--format', template, *names],
                         timeout=15, capture_output=True, text=True)
            if result.returncode:
                if 'pthread_create failed' in result.stderr or 'failed to create new OS thread' in result.stderr:
                    failures.append('DOCKER_CLIENT_THREAD_LIMIT')
                else:
                    failures.append('DOCKER_INSPECT_EXIT_NONZERO')
                continue
            containers = [json.loads(line) for line in result.stdout.splitlines()]
            for item in containers:
                item['name'] = item['name'].lstrip('/')
                if not isinstance(item['state'], str) or item['health'] not in (None, 'healthy', 'unhealthy', 'starting'):
                    raise ValueError('invalid_container_state')
            if len(containers) != len(names) or {i['name'] for i in containers} != set(names):
                raise ValueError('incomplete_container_inventory')
            return dict(containers=containers, container_inspection_attempts=attempt+1,
                        container_inspection_failures=failures)
        except subprocess.TimeoutExpired:
            failures.append('DOCKER_INSPECT_TIMEOUT')
        except (OSError, subprocess.SubprocessError, ValueError, KeyError, TypeError, AttributeError):
            failures.append('DOCKER_INSPECT_UNAVAILABLE_OR_INVALID')
    return dict(containers=[], container_error=failures[-1],
                container_inspection_attempts=2, container_inspection_failures=failures)


def collect(config):
    now = time.time()
    m = counters('/proc/meminfo')
    v = counters('/proc/vmstat')
    sample = dict(scope='PASSIVE_LAB_TELEMETRY_ONLY',
        observed_at=dt.datetime.fromtimestamp(now, dt.timezone.utc).isoformat(),
        boot_id=Path('/proc/sys/kernel/random/boot_id').read_text().strip(),
        uptime_seconds=float(Path('/proc/uptime').read_text().split()[0]),
        memory=dict(total_bytes=m['MemTotal'] * 1024, available_bytes=m['MemAvailable'] * 1024,
                    swap_total_bytes=m['SwapTotal'] * 1024, swap_free_bytes=m['SwapFree'] * 1024),
        swap_pages={k: v[k] for k in ('pswpin', 'pswpout')},
        pressure={k: Path('/proc/pressure/' + k).read_text().strip() for k in ('cpu', 'memory', 'io')},
        disks={}, collectors={}, containers=[])
    for name, path in config['disks'].items():
        usage = shutil.disk_usage(path)
        sample['disks'][name] = dict(total_bytes=usage.total, used_bytes=usage.used, free_bytes=usage.free)
    for name, item in config['collectors'].items():
        result = dict(warn_after_seconds=item['warn_after_seconds'])
        try:
            health = json.loads(Path(item['path']).read_text())
            value = next(health[k] for k in item['timestamp_keys'] if health.get(k))
            at = dt.datetime.fromisoformat(value.replace('Z', '+00:00'))
            if at.tzinfo is None or at.timestamp() > now:
                raise ValueError('invalid_clock')
            result.update(last_success_at=value, age_seconds=now - at.timestamp(),
                          source_status=health.get('status'))
        except (OSError, ValueError, KeyError, StopIteration, TypeError):
            result['error'] = 'HEALTH_UNAVAILABLE_OR_INVALID'
        sample['collectors'][name] = result
    sample.update(inspect_containers(config['containers']))
    return sample


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--config', required=True)
    parser.add_argument('--output', required=True)
    args = parser.parse_args()
    config = json.loads(Path(args.config).read_text())
    output = Path(args.output)
    output.mkdir(exist_ok=True)
    with sqlite3.connect(output / 'telemetry.sqlite', timeout=5) as db:
        db.execute('CREATE TABLE IF NOT EXISTS samples(id INTEGER PRIMARY KEY, payload TEXT NOT NULL)')
        row = db.execute('SELECT payload FROM samples ORDER BY id DESC LIMIT 1').fetchone()
        sample = assess(collect(config), json.loads(row[0]) if row else None)
        raw = json.dumps(sample, allow_nan=False)
        db.execute('INSERT INTO samples(payload) VALUES (?)', (raw,))
        db.commit()
    temporary = output / 'status.tmp'
    temporary.write_text(raw)
    os.replace(temporary, output / 'status.json')
    print(json.dumps(dict(observed_at=sample['observed_at'], alerts=sample['alerts'])))


if __name__ == '__main__':
    main()
