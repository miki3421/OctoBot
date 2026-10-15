"""Read-only M1 collection projection. No execution, outcomes or model imports.

Card work-card-6c8ec0ea-1b93-45d2-bd9e-5d2d0465e306.
The web reads only the allowlisted projection, never the private study journal.
"""
import argparse
import datetime as dt
import hashlib
import json
import math
import os
from pathlib import Path
import sqlite3
import stat
import subprocess
import tempfile
import time

UTC = dt.timezone.utc
STUDY = 'v13-m1-short-prospective-v1'
SCOPE = 'M1_OBSERVATION_MONITOR_ONLY'
PROTOCOL_SHA = '6726b06a5b3b77e224f7f7bfc8598678d39c3486d9635e1fafd953a5da5066c1'
WRITER_UID = 30942
SLOTS = {'NO_SIGNAL', 'INSUFFICIENT_INPUT', 'MISSED', 'COOLDOWN', 'HORIZON_TOO_SHORT', 'SCHEDULED'}
EPISODES = {'SCHEDULED', 'ENTRY_RECORDED', 'ENTRY_MISSED', 'EXIT_MISSED', 'CAPTURE_COMPLETE_AWAITING_OFFLINE_REPLAY'}
PUBLIC_KEYS = {'schema', 'scope', 'study_id', 'generated_at', 'available', 'phase',
               'activation', 'counts', 'coverage', 'last_slot', 'last_feature',
               'signals', 'episodes', 'slots', 'collector', 'issues', 'limit',
               'performance_sealed', 'stale'}
ISSUES = {'MONITOR_READ_FAILURE', 'SCHEDULER_INACTIVE', 'COLLECTOR_FAILURE',
          'COLLECTOR_LATE', 'CLOCK_UNSYNCHRONIZED', 'UNRECORDED_SLOTS',
          'MISSING_INPUT', 'MISSED_CAPTURES', 'MONITOR_STALE'}


def encoded(v):
    return json.dumps(v, sort_keys=True, separators=(',', ':'), allow_nan=False)


def iso(epoch):
    if not isinstance(epoch, (int, float)) or not math.isfinite(epoch):
        raise ValueError('time')
    return dt.datetime.fromtimestamp(epoch, UTC).isoformat()


def timestamp(value):
    t = dt.datetime.fromisoformat(value)
    if t.tzinfo is None or t.utcoffset() != dt.timedelta(0):
        raise ValueError('utc')
    return t.timestamp()


def system_status(now):
    def show(unit, fields):
        p = subprocess.run(['/usr/bin/systemctl', 'show', unit,
                            *['--property=' + f for f in fields]],
                           capture_output=True, text=True, timeout=5, check=True)
        return dict(line.split('=', 1) for line in p.stdout.splitlines() if '=' in line)
    timer = show('v13-m1-short-observer.timer', ['ActiveState', 'UnitFileState'])
    service = show('v13-m1-short-observer.service', ['Result', 'ExecMainStatus', 'ExecMainExitTimestampMonotonic'])
    clock = subprocess.run(['/usr/bin/timedatectl', 'show', '-p', 'NTPSynchronized', '--value'],
                           capture_output=True, text=True, timeout=5, check=True)
    last = int(service['ExecMainExitTimestampMonotonic']) / 1e6
    age = max(0., time.monotonic() - last) if last else None
    return dict(timer_active=timer['ActiveState'] == 'active', enabled=timer['UnitFileState'] == 'enabled',
                result=service['Result'], exit_status=int(service['ExecMainStatus']),
                run_age_seconds=age, last_run_at=iso(now - age) if age is not None else None,
                clock_synchronized=clock.stdout.strip() == 'yes')


def read_journal(path, protocol_path, now):
    raw = protocol_path.read_bytes()
    if hashlib.sha256(raw).hexdigest() != PROTOCOL_SHA:
        raise ValueError('protocol_identity')
    protocol = json.loads(raw)
    identity = dict(protocol=hashlib.sha256(encoded(protocol).encode()).hexdigest(),
                    journal=protocol['source_code_pins']['octobot/ai_strategy_lab/v13_m1_future.py'],
                    detector=protocol['source_code_pins']['octobot/ai_strategy_lab/v13_crash_diagnostic.py'])
    info = path.lstat()
    if not stat.S_ISREG(info.st_mode) or info.st_uid != WRITER_UID or info.st_mode & 0o022:
        raise ValueError('journal_custody')
    db = sqlite3.connect(path.resolve().as_uri() + '?mode=ro', uri=True, timeout=2)
    db.row_factory = sqlite3.Row
    try:
        db.execute('PRAGMA query_only=ON')
        db.execute('BEGIN')
        if db.execute('PRAGMA quick_check').fetchone()[0] != 'ok':
            raise ValueError('journal_integrity')
        meta = {r['key']: json.loads(r['payload']) for r in db.execute('SELECT key,payload FROM meta')}
        if meta['identity'] != identity or meta['fixture'] is not False:
            raise ValueError('journal_identity')
        a = meta['activation']
        t0 = (dt.datetime.fromtimestamp(a['recorded_at'], UTC).replace(hour=0, minute=0, second=0, microsecond=0) + dt.timedelta(days=1)).timestamp()
        if (a['study'] != STUDY or a['fixture'] is not False or a['protocol_hash'] != identity['protocol'] or
                a['t0'] != t0 or a['end_exclusive'] != t0 + 90 * 86400 or a['recorded_at'] > now or meta['last_seen'] > now):
            raise ValueError('activation')
        rows = db.execute("SELECT slot,status,json_extract(payload,'$.recorded_at') AS recorded_at,"
                          "json_extract(payload,'$.feature') AS feature FROM slots ORDER BY slot LIMIT 25921").fetchall()
        episodes = db.execute('SELECT * FROM episodes ORDER BY slot DESC LIMIT 181').fetchall()
        captures = {(r['episode_id'], r['phase']): json.loads(r['payload']) for r in db.execute('SELECT * FROM captures LIMIT 361')}
    finally:
        db.close()
    if len(rows) > 25920 or len(episodes) > 180 or len(captures) > 360:
        raise ValueError('horizon_overflow')
    counters = {s: 0 for s in sorted(SLOTS)}
    episode_counts = {s: 0 for s in sorted(EPISODES)}
    public_slots, signals, features = [], [], {}
    due = min(now - 120, a['end_exclusive'] - 1)
    expected = max(0, min(25920, int((due - t0) // 300) + 1))
    due_recorded = valid = 0
    episode_ids = {e['slot']: e['id'] for e in episodes}
    for r in rows:
        slot, status = r['slot'], r['status']
        if (type(slot) is not int or slot % 300 or not t0 <= slot < a['end_exclusive'] or
                slot > now or status not in SLOTS):
            raise ValueError('slot')
        counters[status] += 1
        if slot <= due:
            due_recorded += 1
            valid += int(status not in {'MISSED', 'INSUFFICIENT_INPUT'})
        recorded = r['recorded_at']
        if recorded is not None and (recorded < slot or recorded > now):
            raise ValueError('recorded_time')
        row = dict(slot=iso(slot), status=status, recorded_at=iso(recorded) if recorded is not None else None)
        public_slots.append(row)
        if r['feature']:
            f = json.loads(r['feature'])
            btc, breadth = f['btc_60m'], f['negative_breadth']
            if (not all(type(v) in (int, float) and math.isfinite(v) for v in (btc, breadth)) or
                    btc <= -1 or not 0 <= breadth <= 1 or abs(breadth * 18 - round(breadth * 18)) > 1e-8):
                raise ValueError('feature')
            feature = dict(observed_at=iso(slot), btc_return_1h=btc, negative_symbols=round(breadth * 18), universe_count=18)
            features[slot] = feature
            if btc <= -.01 and breadth >= 2/3:
                signals.append(dict(**row, btc_return_1h=btc, negative_symbols=round(breadth * 18), episode_id=episode_ids.get(slot)))
    public_episodes = []
    for e in episodes:
        if (e['status'] not in EPISODES or len(e['id']) != 64 or any(c not in '0123456789abcdef' for c in e['id']) or
                e['entry_slot'] != e['slot'] + 300 or e['exit_slot'] != e['entry_slot'] + 21600 or
                e['slot'] not in features or episode_ids.get(e['slot']) != e['id']):
            raise ValueError('episode')
        episode_counts[e['status']] += 1
        row = dict(id=e['id'], signal_at=iso(e['slot']), status=e['status'], entry_due=iso(e['entry_slot']), exit_due=iso(e['exit_slot']))
        for phase in ('entry', 'exit'):
            capture = captures.get((e['id'], phase))
            if capture and not e[phase + '_slot'] <= capture['captured_at'] <= e[phase + '_slot'] + 120:
                raise ValueError('capture_time')
            row[phase + '_captured_at'] = iso(capture['captured_at']) if capture else None
        if ((e['status'] == 'SCHEDULED' and row['entry_captured_at']) or
                (e['status'] in {'ENTRY_RECORDED', 'EXIT_MISSED', 'CAPTURE_COMPLETE_AWAITING_OFFLINE_REPLAY'} and not row['entry_captured_at']) or
                (e['status'] == 'CAPTURE_COMPLETE_AWAITING_OFFLINE_REPLAY' and not row['exit_captured_at'])):
            raise ValueError('capture_state')
        public_episodes.append(row)
    if counters['SCHEDULED'] != len(episodes):
        raise ValueError('episode_count')
    if any(phase not in {'entry', 'exit'} or eid not in episode_ids.values() for eid, phase in captures):
        raise ValueError('orphan_capture')
    last = rows[-1]['slot'] if rows else None
    return dict(activation=dict(recorded_at=iso(a['recorded_at']), t0=iso(t0), end_exclusive=iso(a['end_exclusive'])),
                phase='waiting' if now < t0 else 'collecting' if now < a['end_exclusive'] else 'ended',
                counts=dict(slots=counters, signals=len(signals), episodes=episode_counts),
                coverage=dict(expected=expected, recorded_due=due_recorded, valid=valid,
                              overdue=max(0, expected - due_recorded), valid_fraction=valid / expected if expected else None),
                last_slot=public_slots[-1] if public_slots else None, last_feature=features.get(last),
                signals=list(reversed(signals[-100:])), slots=list(reversed(public_slots[-100:])), episodes=public_episodes)


def unavailable(now):
    return dict(schema=1, scope=SCOPE, study_id=STUDY, generated_at=iso(now), available=False,
                phase='unavailable', activation=None, counts=None, coverage=None, last_slot=None,
                last_feature=None, signals=[], episodes=[], slots=[], collector=None,
                issues=['MONITOR_READ_FAILURE'], limit=100, performance_sealed=True, stale=False)


def build(journal, protocol, now, system=None):
    value = read_journal(journal, protocol, now)
    collector = (system or system_status)(now)
    issues = []
    if not collector['timer_active'] or not collector['enabled']:
        issues.append('SCHEDULER_INACTIVE')
    if collector['result'] != 'success' or collector['exit_status'] != 0:
        issues.append('COLLECTOR_FAILURE')
    if collector['run_age_seconds'] is None or collector['run_age_seconds'] > 180:
        issues.append('COLLECTOR_LATE')
    if not collector['clock_synchronized']:
        issues.append('CLOCK_UNSYNCHRONIZED')
    if value['coverage']['overdue']:
        issues.append('UNRECORDED_SLOTS')
    if value['counts']['slots']['INSUFFICIENT_INPUT'] or value['counts']['slots']['MISSED']:
        issues.append('MISSING_INPUT')
    if value['counts']['episodes']['ENTRY_MISSED'] or value['counts']['episodes']['EXIT_MISSED']:
        issues.append('MISSED_CAPTURES')
    return dict(schema=1, scope=SCOPE, study_id=STUDY, generated_at=iso(now), available=True,
                **value, collector=collector, issues=issues, limit=100, performance_sealed=True, stale=False)


def publish(path, value):
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(dir=path.parent, prefix='.m1-status-', delete=False) as f:
            temporary = Path(f.name)
            f.write((encoded(value) + '\n').encode()); f.flush(); os.fchmod(f.fileno(), 0o640); os.fsync(f.fileno())
        os.replace(temporary, path); temporary = None
        fd = os.open(path.parent, os.O_DIRECTORY | os.O_RDONLY)
        try:
            os.fsync(fd)
        finally:
            os.close(fd)
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)


def public_view(path=Path('/v13-paper/m1-ui/status.json'), now=None):
    now = time.time() if now is None else now
    try:
        fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW)
        try:
            info = os.fstat(fd)
            if info.st_uid != WRITER_UID or info.st_mode & 0o022 or not stat.S_ISREG(info.st_mode) or info.st_size > 512000:
                raise ValueError('projection_custody')
            v = json.loads(os.read(fd, 512001))
        finally:
            os.close(fd)
        if (set(v) != PUBLIC_KEYS or v['schema'] != 1 or v['scope'] != SCOPE or v['study_id'] != STUDY or
                v['phase'] not in {'waiting', 'collecting', 'ended', 'unavailable'} or type(v['available']) is not bool or
                v['performance_sealed'] is not True or v['limit'] != 100 or v['stale'] is not False or
                not isinstance(v['issues'], list) or not set(v['issues']) <= ISSUES):
            raise ValueError('projection_schema')
        schemas = {'slots': {'slot', 'status', 'recorded_at'},
                   'signals': {'slot', 'status', 'recorded_at', 'btc_return_1h', 'negative_symbols', 'episode_id'},
                   'episodes': {'id', 'signal_at', 'status', 'entry_due', 'exit_due', 'entry_captured_at', 'exit_captured_at'}}
        for key, fields in schemas.items():
            if not isinstance(v[key], list) or len(v[key]) > (180 if key == 'episodes' else 100):
                raise ValueError('projection_rows')
            if any(set(row) != fields for row in v[key]):
                raise ValueError('projection_nested_schema')
        if v['available']:
            if (set(v['activation']) != {'recorded_at', 't0', 'end_exclusive'} or
                    set(v['counts']) != {'slots', 'signals', 'episodes'} or set(v['counts']['slots']) != SLOTS or
                    set(v['counts']['episodes']) != EPISODES or
                    set(v['coverage']) != {'expected', 'recorded_due', 'valid', 'overdue', 'valid_fraction'} or
                    set(v['collector']) != {'timer_active', 'enabled', 'result', 'exit_status', 'run_age_seconds', 'last_run_at', 'clock_synchronized'}):
                raise ValueError('projection_summary')
            if v['last_slot'] is not None and set(v['last_slot']) != schemas['slots']:
                raise ValueError('projection_last_slot')
            if v['last_feature'] is not None and set(v['last_feature']) != {'observed_at', 'btc_return_1h', 'negative_symbols', 'universe_count'}:
                raise ValueError('projection_feature')
            def count(value, maximum):
                return type(value) is int and 0 <= value <= maximum
            if (any(not count(n, 25920) for n in v['counts']['slots'].values()) or
                    any(not count(n, 180) for n in v['counts']['episodes'].values()) or
                    not count(v['counts']['signals'], 25920) or
                    any(not count(v['coverage'][k], 25920) for k in ('expected', 'recorded_due', 'valid', 'overdue')) or
                    not v['coverage']['valid'] <= v['coverage']['recorded_due'] <= v['coverage']['expected']):
                raise ValueError('projection_counts')
            for k in ('recorded_at', 't0', 'end_exclusive'):
                timestamp(v['activation'][k])
            if timestamp(v['activation']['end_exclusive']) - timestamp(v['activation']['t0']) != 90 * 86400:
                raise ValueError('projection_horizon')
            for key in ('slots', 'signals'):
                for row in v[key]:
                    timestamp(row['slot'])
                    if row['recorded_at'] is not None:
                        timestamp(row['recorded_at'])
                    if row['status'] not in SLOTS:
                        raise ValueError('projection_slot_state')
            for row in v['signals'] + ([v['last_feature']] if v['last_feature'] else []):
                if (type(row['btc_return_1h']) not in (int, float) or not math.isfinite(row['btc_return_1h']) or
                        not count(row['negative_symbols'], 18)):
                    raise ValueError('projection_signal')
            for row in v['episodes']:
                if row['status'] not in EPISODES or len(row['id']) != 64:
                    raise ValueError('projection_episode')
                for k in ('signal_at', 'entry_due', 'exit_due', 'entry_captured_at', 'exit_captured_at'):
                    if row[k] is not None:
                        timestamp(row[k])
            if v['collector']['result'] not in {'success', 'resources', 'timeout', 'exit-code', 'signal', 'core-dump', 'watchdog', 'start-limit-hit', 'protocol', 'oom-kill'}:
                raise ValueError('projection_service_result')
        elif any(v[k] is not None for k in ('activation', 'counts', 'coverage', 'collector', 'last_slot', 'last_feature')) or any(v[k] for k in schemas):
            raise ValueError('unavailable_not_empty')
        age = now - timestamp(v['generated_at'])
        if age < -5:
            raise ValueError('projection_future')
        if age > 180:
            v['stale'] = True; v['issues'] = list(dict.fromkeys(v['issues'] + ['MONITOR_STALE']))
        return v
    except (OSError, ValueError, KeyError, TypeError, OverflowError):
        return unavailable(now)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--journal', type=Path, required=True)
    parser.add_argument('--protocol', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    now = time.time()
    try:
        result = build(args.journal, args.protocol, now)
    except (OSError, ValueError, KeyError, TypeError, sqlite3.Error, subprocess.SubprocessError):
        result = unavailable(now)
    publish(args.output, result)
    print(encoded(dict(available=result['available'], phase=result['phase'], issues=result['issues'])))


if __name__ == '__main__':
    main()
