"""Passive local telemetry; never writes a collector or execution store.

work-card-355d630a-dd57-407b-af16-c4b29d82da39.
"""
import argparse
import datetime as dt
import json
import math
import re
import os
from pathlib import Path
import shutil
import sqlite3
import stat
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
    alerts.extend(sample.get('forks', {}).get('issues', []))
    for result in sample.get('paper_accounts', {}).values():
        alerts.extend(result['issues'])
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



def read_forks(item, now=None):
    """Read only the paired projection. No access to trading or approval DBs.

    Current debt/gaps alert; historical incomplete samples are retained as
    information, so a recovered settlement does not create perpetual emails.
    """
    result = dict(accounts={}, issues=[])
    issues = result['issues']
    try:
        path = Path(item['path'])
        if path.is_symlink() or path.stat().st_uid != 30934 or path.stat().st_mode & 0o022:
            raise ValueError('projection_custody')
        with path.open('rb') as stream:
            raw = stream.read(8 * 1024 * 1024 + 1)
        if len(raw) > 8 * 1024 * 1024:
            raise ValueError('projection_size')
        value = json.loads(raw)
        now = time.time() if now is None else now
        def instant(text):
            when = dt.datetime.fromisoformat(text.replace('Z', '+00:00'))
            if when.tzinfo is None:
                raise ValueError('timezone')
            return when.astimezone(dt.timezone.utc)
        def finite(number):
            if isinstance(number, bool) or not isinstance(number, (int, float)) or not math.isfinite(number):
                raise ValueError('nonfinite_accounting')
            return number
        receipt = value['receipt']
        parent = receipt['parent_snapshot_sha256']
        if (value.get('available') is not True or value['schema'] != 1
                or receipt['scope'] != 'RESEARCH_SIMULATION_ONLY_NO_EXECUTOR_LINK'
                or not isinstance(parent, str) or not re.fullmatch('[0-9a-f]{64}', parent)):
            raise ValueError('projection_identity')
        generated, checked = instant(value['generated_at']), instant(value['health']['checked_at'])
        if max(generated.timestamp(), checked.timestamp()) > now:
            raise ValueError('future_heartbeat')
        age = max(now-generated.timestamp(), now-checked.timestamp())
        result.update(generated_at=generated.isoformat(), heartbeat_age_seconds=age,
                      heartbeat_warn_after_seconds=item['heartbeat_warn_after_seconds'])
        if age > item['heartbeat_warn_after_seconds']:
            issues.append('FORK_PROJECTION_STALE')
        first, end = instant(receipt['first_decision_slot']), instant(receipt['end_exclusive'])
        fork = instant(receipt['economic_t0'])
        if not fork < first < end or first.time() != dt.time(0, 15):
            raise ValueError('fork_calendar')
        phase = value['health']['status']
        completed = phase == 'COMPLETED_AWAITING_REVIEW' and now >= end.timestamp()
        if phase not in {'OBSERVING', 'BLOCKED', 'COMPLETED_AWAITING_REVIEW'} or (phase == 'COMPLETED_AWAITING_REVIEW' and not completed):
            raise ValueError('runner_status')
        result['runner_status'] = phase
        if phase == 'BLOCKED':
            issues.append('FORK_RUNNER_BLOCKED')
        if value['funding_debt'] is not None:
            issues.append('FORK_FUNDING_INCOMPLETE')
        if value['valuation_gap'] is not None:
            issues.append('FORK_VALUATION_GAP')
        result['historical_incomplete_funding_observations'] = value['incomplete_funding_observations']
        initial_equity = finite(value['baseline']['equity'])-finite(value['baseline']['pnl'])
        for arm in ('FAST', 'HALF'):
            account = value['variants'][arm]
            expected = 'v13-risk-matched-clone-v2-'+arm.lower()+'-'+parent[:12]
            if receipt['account_ids'][arm] != expected or account['account_id'] != expected:
                raise ValueError('account_identity')
            at = instant(account['observed_at'])
            if not fork <= at <= generated:
                raise ValueError('account_time')
            observation_age = now-at.timestamp()
            entry = dict(observed_at=at.isoformat(), age_seconds=observation_age,
                         warn_after_seconds=item['valuation_warn_after_seconds'],
                         valuation_required=not completed, accounting='VERIFIED')
            result['accounts'][arm] = entry
            if not completed and observation_age > item['valuation_warn_after_seconds']:
                issues.append('FORK_VALUATION_STALE:'+arm)
            metrics = account['metrics']
            try:
                fields = {k:finite(metrics[k]) for k in ('equity', 'pnl', 'realized_pnl', 'unrealized_pnl', 'fees', 'funding')}
                computed = initial_equity+fields['realized_pnl']+fields['unrealized_pnl']-fields['fees']+fields['funding']
                positions = account['positions']
                symbols = [p['symbol'] for p in positions]
                if (not symbols or len(symbols) != len(set(symbols)) or fields['fees'] < 0
                        or not math.isclose(computed,fields['equity'],rel_tol=1e-9,abs_tol=1e-6)
                        or not math.isclose(fields['equity']-initial_equity,fields['pnl'],rel_tol=1e-9,abs_tol=1e-6)
                        or not math.isclose(math.fsum(finite(p['net']) for p in positions),fields['pnl'],rel_tol=1e-9,abs_tol=1e-6)):
                    raise ValueError('accounting_identity')
                if fields['equity'] <= 0:
                    issues.append('FORK_NON_POSITIVE_EQUITY:'+arm)
            except (ValueError, KeyError, TypeError):
                entry['accounting'] = 'INVALID'
                issues.append('FORK_ACCOUNTING_INVALID:'+arm)
        # Only the latest due daily slot alerts; a new successful slot recovers.
        current = dt.datetime.fromtimestamp(now, dt.timezone.utc)
        due = current.replace(hour=0, minute=15, second=0, microsecond=0)
        if now <= due.timestamp()+120:
            due -= dt.timedelta(days=1)
        if not completed and first <= due < end:
            matching = [s for s in value['slots'] if instant(s['slot']) == due]
            result['expected_slot'] = due.isoformat()
            if len(matching) != 1:
                issues.append('FORK_DECISION_MISSING')
            else:
                slot = matching[0]
                status = slot['status']
                result['latest_slot_status'] = status
                if status in {'MISSED', 'DENIED'}:
                    issues.append('FORK_DECISION_'+status)
                elif status in {'EXECUTED', 'OBSERVED_NO_FILL'}:
                    gap = finite(slot['detail']['risk_gap'])
                    if gap < 0 or gap > 1:
                        raise ValueError('risk_gap')
                    result['risk_gap'] = gap
                    if gap > .02:
                        issues.append('FORK_RISK_MISMATCH')
                else:
                    raise ValueError('slot_status')
        result['status'] = 'healthy' if not issues else 'attention'
    except (OSError, ValueError, KeyError, TypeError, AttributeError, OverflowError):
        result['status'] = 'unavailable'
        result['issues'] = ['FORK_PROJECTION_UNAVAILABLE']
    return result

def read_paper_account(name, item, now=None):
    """Bounded read of owned UI projections; never open the execution stores."""
    result = dict(issues=[])
    try:
        started = time.time()
        result['read_started_at'] = dt.datetime.fromtimestamp(started, dt.timezone.utc).isoformat()
        path = Path(item['path'])
        with os.fdopen(os.open(path, os.O_RDONLY | os.O_NOFOLLOW), 'rb') as f:
            info = os.fstat(f.fileno())
            if not stat.S_ISREG(info.st_mode) or info.st_uid != item['uid'] or info.st_mode & 0o022:
                raise ValueError('custody')
            raw = f.read(8*1024*1024+1)
        completed = time.time()
        result['read_completed_at'] = dt.datetime.fromtimestamp(completed, dt.timezone.utc).isoformat()
        if completed < started:
            raise ValueError('read_clock_regression')
        # A producer may publish after collect() starts but before this read.
        # Compare with the completed read, without granting a future-time grace.
        now = completed if now is None else now
        result['validation_at'] = dt.datetime.fromtimestamp(now, dt.timezone.utc).isoformat()
        if len(raw) > 8*1024*1024:
            raise ValueError('size')
        v = json.loads(raw)
        if name == 'm1':
            if v['scope'] != 'AUTONOMOUS_M1_PAPER_RESEARCH_ONLY' or v['arm'] != 'M1':
                raise ValueError('scope')
            at = dt.datetime.fromisoformat(v['health']['checked_at'])
            account = v['variant']; mark = dt.datetime.fromisoformat(account['observed_at'])
            if v['health']['status'] != 'OBSERVING' or v['health'].get('reason'):
                result['issues'].append('PAPER_ACCOUNT_BLOCKED:'+name)
            current = dt.datetime.fromtimestamp(now, dt.timezone.utc)
            due = current.replace(hour=0, minute=15, second=0, microsecond=0)
            if now <= due.timestamp()+120:
                due -= dt.timedelta(days=1)
            first = dt.datetime.fromisoformat(v['activation']['first_signal_slot'])
            if due >= first:
                rows = [s for s in v.get('daily_slots', v['slots']) if s['kind'] == 'DAILY' and dt.datetime.fromisoformat(s['slot']) == due]
                result['daily_status'] = rows[0]['status'] if len(rows) == 1 else 'MISSING'
                if result['daily_status'] in {'MISSED','DENIED','MISSING','PENDING'}:
                    result['issues'].append('PAPER_DAILY_NOT_EXECUTED:'+name)
            equity = account['metrics']['equity']
        elif name == 'intraday':
            if v['scope'] != 'SYNTHETIC_RESEARCH_PAPER_NOT_KUCOIN_ORDER_ADMISSIBILITY':
                raise ValueError('scope')
            at = dt.datetime.fromtimestamp(v['checked_at_ns']/1e9, dt.timezone.utc)
            mark = dt.datetime.fromtimestamp(v['state']['last_market_received']/1e9, dt.timezone.utc)
            equity = v['metrics']['equity']
            if not v['accounting_complete'] or v['state']['integrity_halt'] or v['state']['drawdown_halt']:
                result['issues'].append('PAPER_ACCOUNT_BLOCKED:'+name)
            # A remembered PRICE_MISSING reason is not the current slot outcome.
            result['last_slot_status'] = v['slots'][0]['status'] if v['slots'] else None
        else:
            raise ValueError('unsupported_account')
        if at.tzinfo is None or mark.tzinfo is None:
            raise ValueError('timezone')
        if max(at.timestamp(),mark.timestamp()) > now:
            raise ValueError('future_timestamp')
        if type(equity) not in (float,int) or not math.isfinite(equity) or equity <= 0:
            raise ValueError('equity')
        result.update(heartbeat_age_seconds=now-at.timestamp(), valuation_age_seconds=now-mark.timestamp())
        if result['heartbeat_age_seconds'] > item['heartbeat_warn_after_seconds'] or result['valuation_age_seconds'] > item['valuation_warn_after_seconds']:
            result['issues'].append('PAPER_ACCOUNT_STALE:'+name)
        result['status'] = 'attention' if result['issues'] else 'healthy'
    except (OSError,ValueError,KeyError,TypeError,OverflowError,IndexError) as error:
        # Keep private paths, raw JSON and exception messages out of telemetry.
        reasons = {
            'custody': 'CUSTODY_INVALID', 'size': 'PROJECTION_TOO_LARGE',
            'scope': 'SCOPE_INVALID', 'unsupported_account': 'ACCOUNT_UNSUPPORTED',
            'timezone': 'TIMEZONE_INVALID', 'future_timestamp': 'TIMESTAMP_FUTURE',
            'read_clock_regression': 'READ_CLOCK_REGRESSION', 'equity': 'EQUITY_INVALID',
        }
        if isinstance(error, OSError):
            reason = 'READ_ERROR'
        elif isinstance(error, json.JSONDecodeError):
            reason = 'JSON_INVALID'
        elif isinstance(error, ValueError):
            reason = reasons.get(str(error), 'SCHEMA_INVALID')
        else:
            reason = 'SCHEMA_INVALID'
        result.update(status='unavailable', issues=['PAPER_ACCOUNT_UNAVAILABLE:'+name],
                      error_code=reason)
    return result


def read_intraday_pair(item, now=None):
    """Only the new public projection; reuse existing email alert contracts."""
    result = dict(issues=[], status='healthy')
    try:
        from btc_intraday_pair_view import public
        v = public(item['path'], now_ns=None if now is None else int(now*1e9), uid=item['uid'])
        checked = time.time() if now is None else now
        result.update(phase=v['phase'], heartbeat_age_seconds=v['age_seconds'])
        if v['age_seconds'] > item['heartbeat_warn_after_seconds']:
            result['issues'].append('PAPER_ACCOUNT_STALE:intraday-pair')
        if v['phase'] == 'BLOCKED':
            result['issues'].append('PAPER_ACCOUNT_BLOCKED:intraday-pair')
        else:
            for name, a in v['arms'].items():
                if (a['cursor'] != v['input_seq'] or a['input_sha'] != v['input_sha']
                        or a['integrity_halt'] or not a['complete']):
                    result['issues'].append('PAPER_ACCOUNT_BLOCKED:intraday-pair-'+name)
                if v['phase'] != 'COMPLETED' and any(a[k] is None or
                        checked-a[k]/1e9 > item[limit] for k, limit in
                        (('last_market_ns', 'market_warn_after_seconds'),
                         ('last_book_ns', 'book_warn_after_seconds'))):
                    result['issues'].append('PAPER_ACCOUNT_STALE:intraday-pair-'+name)
        if result['issues']:
            result['status'] = 'attention'
    except (ImportError, OSError, ValueError, KeyError, TypeError, OverflowError):
        result.update(status='unavailable', issues=['PAPER_ACCOUNT_UNAVAILABLE:intraday-pair'])
    return result


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
    if 'forks' in config:
        sample['forks'] = read_forks(config['forks'])
    sample['paper_accounts'] = {name:read_paper_account(name,item) for name,item in config.get('paper_accounts',{}).items()}
    if 'intraday_pair' in config:
        sample['paper_accounts']['intraday_pair'] = read_intraday_pair(config['intraday_pair'])
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
