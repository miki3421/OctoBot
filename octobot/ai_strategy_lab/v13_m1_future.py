"""Prepared research observation journal. No fills, network or execution link.

Card work-card-17c7410d-e45a-48c3-994a-99afa7980615.
Start is explicit; a late observation cannot authorize a historical episode.
"""
import datetime as dt
import hashlib
import importlib.util
import json
import math
import os
from pathlib import Path
import re
import sqlite3

UTC = dt.timezone.utc
HASH = re.compile(r'^[a-f0-9]{64}$')
spec = importlib.util.spec_from_file_location('m1_detector', Path(__file__).with_name('v13_crash_diagnostic.py'))
detector = importlib.util.module_from_spec(spec)
spec.loader.exec_module(detector)


def encoded(value):
    return json.dumps(value, sort_keys=True, separators=(',', ':'), allow_nan=False)


def digest(value):
    return hashlib.sha256(encoded(value).encode()).hexdigest()


def validate_protocol(p):
    if p['study_id'] != 'v13-m1-short-prospective-v1' or p['scope'] != 'OBSERVATION_AND_OFFLINE_CONDITIONAL_REPLAY_ONLY':
        raise ValueError('study_scope')
    if len(p['universe']) != 18 or len(set(p['universe'])) != 18 or 'BTCUSDT' not in p['universe']:
        raise ValueError('universe')
    expected = dict(btc_return_window_seconds=3600, btc_return_lte=-.01,
                    negative_breadth_gte=2/3, denominator=18, grid_seconds=300,
                    required_contiguous_rows=289, maximum_price_age_seconds=120)
    if p['signal'] != expected or any(p['permissions'].values()):
        raise ValueError('signal_or_permissions_changed')
    if (p['timing']['duration_days'], p['timing']['hold_seconds'], p['timing']['cooldown_seconds_after_exit'],
            p['timing']['decision_deadline_seconds'], p['timing']['entry_delay_slots'], p['timing']['minimum_entry_delay_seconds']) != (90, 21600, 21600, 120, 1, 60):
        raise ValueError('timing_changed')
    if p['costs']['real_min_quantity'] != 'UNKNOWN' or p['costs']['real_min_notional'] != 'UNKNOWN':
        raise ValueError('exchange_minima_changed')
    if hashlib.sha256(Path(detector.__file__).read_bytes()).hexdigest() != p['source_code_pins']['octobot/ai_strategy_lab/v13_crash_diagnostic.py']:
        raise ValueError('detector_pin_changed')


def read_window(path, slot, universe):
    """Only a read-only transaction on the existing original price ledger."""
    connection = sqlite3.connect(Path(path).resolve().as_uri() + '?mode=ro', uri=True)
    connection.execute('PRAGMA query_only=ON')
    try:
        connection.execute('BEGIN')
        account = json.loads(connection.execute('SELECT payload FROM state WHERE id=1').fetchone()[0])
        if set(account['positions']) != set(universe):
            raise ValueError('source_universe')
        lo = dt.datetime.fromtimestamp(slot-86400-120, UTC).isoformat()
        hi = dt.datetime.fromtimestamp(slot, UTC).isoformat()
        records = connection.execute('SELECT bar,symbol,price FROM marks WHERE bar>=? AND bar<=? ORDER BY bar', (lo, hi)).fetchall()
        last, result, i = {}, [], 0
        for grid in range(slot-86400, slot+1, 300):
            while i < len(records):
                bar, symbol, price = records[i]
                at = dt.datetime.fromisoformat(bar).timestamp()
                if at > grid:
                    break
                last[symbol] = (at, price)
                i += 1
            result.append(dict(time=grid, prices={s: v[1] for s, v in last.items()},
                               source_times={s: v[0] for s, v in last.items()}))
        return result
    finally:
        connection.close()


class Journal:
    def __init__(self, path, protocol):
        validate_protocol(protocol)
        self.protocol = protocol
        self.path = Path(path)
        if self.path.is_symlink():
            raise ValueError('journal_symlink')
        self.db = sqlite3.connect(self.path.resolve().as_uri()+'?mode=rw', uri=True)
        self.db.row_factory = sqlite3.Row
        self.db.execute('PRAGMA synchronous=FULL')
        identity = dict(protocol=digest(protocol), journal=hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
                        detector=hashlib.sha256(Path(detector.__file__).read_bytes()).hexdigest())
        if self.meta('identity') != identity:
            self.db.close()
            raise ValueError('journal_identity_changed')

    @classmethod
    def create(cls, path, protocol, now, fixture=False):
        validate_protocol(protocol)
        path = Path(path)
        fd = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
        os.close(fd)
        db = sqlite3.connect(path)
        try:
            db.execute('PRAGMA synchronous=FULL')
            db.executescript('''
            CREATE TABLE meta(key TEXT PRIMARY KEY,payload TEXT NOT NULL);
            CREATE TABLE slots(slot INTEGER PRIMARY KEY,status TEXT NOT NULL,input_hash TEXT,payload TEXT NOT NULL);
            CREATE TABLE episodes(id TEXT PRIMARY KEY,slot INTEGER UNIQUE,entry_slot INTEGER,exit_slot INTEGER,status TEXT);
            CREATE TABLE captures(episode_id TEXT,phase TEXT,payload TEXT NOT NULL,PRIMARY KEY(episode_id,phase));
            CREATE TABLE history(id INTEGER PRIMARY KEY,payload TEXT NOT NULL);
            ''')
            for table in ('slots', 'captures', 'history'):
                for action in ('UPDATE', 'DELETE'):
                    db.execute(f"CREATE TRIGGER keep_{table}_{action} BEFORE {action} ON {table} BEGIN SELECT RAISE(ABORT,'append_only'); END")
            identity = dict(protocol=digest(protocol), journal=hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
                            detector=hashlib.sha256(Path(detector.__file__).read_bytes()).hexdigest())
            with db:
                for key, value in dict(identity=identity, prepared_at=now, fixture=fixture, last_seen=now).items():
                    db.execute('INSERT INTO meta VALUES(?,?)', (key, encoded(value)))
        finally:
            db.close()
        return cls(path, protocol)

    def meta(self, key):
        row = self.db.execute('SELECT payload FROM meta WHERE key=?', (key,)).fetchone()
        return json.loads(row[0]) if row else None

    def put(self, key, value):
        self.db.execute('INSERT OR REPLACE INTO meta VALUES(?,?)', (key, encoded(value)))

    def log(self, value):
        self.db.execute('INSERT INTO history(payload) VALUES(?)', (encoded(value),))

    def clock(self, now):
        if not math.isfinite(now) or now < self.meta('last_seen'):
            raise ValueError('clock_regression')

    def start(self, now):
        self.clock(now)
        if self.meta('activation'):
            return self.meta('activation')
        t0 = int((dt.datetime.fromtimestamp(now, UTC).replace(hour=0, minute=0, second=0, microsecond=0)+dt.timedelta(days=1)).timestamp())
        receipt = dict(recorded_at=now, t0=t0, end_exclusive=t0+90*86400,
                       study=self.protocol['study_id'], protocol_hash=digest(self.protocol), fixture=self.meta('fixture'))
        with self.db:
            self.put('activation', receipt)
            self.put('last_seen', now)
            self.log(dict(type='EXPLICIT_OBSERVATION_START', receipt=receipt))
        return receipt

    def expire(self, now):
        self.clock(now)
        for e in self.db.execute("SELECT * FROM episodes WHERE status IN ('SCHEDULED','ENTRY_RECORDED')").fetchall():
            phase = 'entry' if e['status']=='SCHEDULED' else 'exit'
            if now > e[phase+'_slot']+120:
                status = phase.upper()+'_MISSED'
                self.db.execute('UPDATE episodes SET status=? WHERE id=?', (status, e['id']))
                self.log(dict(type=status, episode=e['id'], at=now))
        self.put('last_seen',now)

    def record(self, slot, rows, now):
        self.clock(now)
        receipt = self.meta('activation')
        if not receipt:
            raise ValueError('prepared_not_started')
        if type(slot)!=int or slot%300 or not receipt['t0']<=slot<receipt['end_exclusive'] or now<slot:
            raise ValueError('slot_outside_future_horizon')
        h = digest(rows)
        old = self.db.execute('SELECT * FROM slots WHERE slot=?', (slot,)).fetchone()
        if old:
            if old['input_hash'] != h:
                raise ValueError('slot_conflict_preserve_original')
            return json.loads(old['payload'])
        previous = self.db.execute('SELECT MAX(slot) FROM slots').fetchone()[0]
        if previous is not None and slot < previous:
            raise ValueError('no_backfill')
        feature, status, episode = None, 'MISSED', None
        if now <= slot+120:
            valid = (len(rows)==289 and [r['time'] for r in rows]==list(range(slot-86400,slot+1,300)))
            if valid:
                for row in rows:
                    if (set(row.get('prices',{}))!=set(self.protocol['universe']) or
                            set(row.get('source_times',{}))!=set(self.protocol['universe']) or
                            any(not math.isfinite(t) or not 0<=row['time']-t<=120 for t in row['source_times'].values())):
                        valid=False
                        break
            feature = detector.features(rows,288) if valid else None
            status = 'NO_SIGNAL' if feature else 'INSUFFICIENT_INPUT'
            if feature and detector.signal(feature,'momentum_breadth'):
                if slot < (self.meta('cooldown_until') or 0):
                    status='COOLDOWN'
                elif slot+300+21600+120 > receipt['end_exclusive']:
                    status='HORIZON_TOO_SHORT'
                else:
                    status='SCHEDULED'
                    episode=dict(id=digest(dict(protocol=digest(self.protocol),slot=slot,input_hash=h)),slot=slot,entry_slot=slot+300,exit_slot=slot+300+21600)
        result=dict(slot=slot,recorded_at=now,status=status,input_hash=h,feature=feature,episode=episode,
                    consumed_rows=rows if episode else None,
                    feature_endpoints=[rows[-13],rows[-1]] if feature else None)
        with self.db:
            self.expire(now)
            for missed in range((previous+300) if previous is not None else receipt['t0'],slot,300):
                value=dict(slot=missed,status='MISSED',reason='observer_not_present')
                self.db.execute('INSERT INTO slots VALUES(?,?,?,?)',(missed,'MISSED',None,encoded(value)))
            self.db.execute('INSERT INTO slots VALUES(?,?,?,?)',(slot,status,h,encoded(result)))
            if episode:
                self.db.execute('INSERT INTO episodes VALUES(?,?,?,?,?)',(episode['id'],slot,episode['entry_slot'],episode['exit_slot'],'SCHEDULED'))
                self.put('cooldown_until',episode['exit_slot']+21600)
            self.put('last_seen',now)
        return result

    def capture(self, episode_id, phase, payload, now):
        self.clock(now)
        if phase not in ('entry','exit'):
            raise ValueError('unknown_phase')
        e=self.db.execute('SELECT * FROM episodes WHERE id=?',(episode_id,)).fetchone()
        if not e:
            raise ValueError('unknown_episode')
        old=self.db.execute('SELECT payload FROM captures WHERE episode_id=? AND phase=?',(episode_id,phase)).fetchone()
        if old:
            if json.loads(old[0])!=payload:
                raise ValueError('capture_conflict')
            return
        scheduled=e[phase+'_slot']
        if not scheduled<=now<=scheduled+120:
            with self.db:
                self.expire(now)
            raise ValueError('capture_window_missed_no_replay')
        if e['status']!=('SCHEDULED' if phase=='entry' else 'ENTRY_RECORDED'):
            raise ValueError('capture_state')
        required={'snapshot_sha256','market_hash','market_observed_at','captured_at'}
        if set(payload)!=required or not all(HASH.fullmatch(payload[k]) for k in ('snapshot_sha256','market_hash')):
            raise ValueError('capture_schema')
        at=payload['market_observed_at']
        if (payload['captured_at']!=now or not scheduled-120<=at<=scheduled or
                (phase=='entry' and at<e['slot']+60)):
            raise ValueError('capture_causality')
        with self.db:
            self.db.execute('INSERT INTO captures VALUES(?,?,?)',(episode_id,phase,encoded(payload)))
            self.db.execute('UPDATE episodes SET status=? WHERE id=?',('ENTRY_RECORDED' if phase=='entry' else 'CAPTURE_COMPLETE_AWAITING_OFFLINE_REPLAY',episode_id))
            self.put('last_seen',now)
            self.log(dict(type='CAPTURE_RECORDED',episode=episode_id,phase=phase,at=now))

    def summary(self):
        receipt=self.meta('activation')
        return dict(state='HORIZON_ENDED_AWAITING_OFFLINE_REPLAY' if self.meta('sealed') else ('OBSERVATION_STARTED' if receipt else 'PREPARED_NOT_STARTED'),activation=receipt,
                    slots=dict(self.db.execute('SELECT status,COUNT(*) FROM slots GROUP BY status')),
                    episodes=dict(self.db.execute('SELECT status,COUNT(*) FROM episodes GROUP BY status')),
                    outcome_assessment='POST_HORIZON_OFFLINE_ONLY_NO_FREE_FORM_PNL_ACCEPTED',fixture=self.meta('fixture'))

    def seal(self, now):
        self.clock(now)
        receipt=self.meta('activation')
        if not receipt or now<receipt['end_exclusive']:
            raise ValueError('horizon_not_ended')
        if self.meta('sealed'):
            return
        previous=self.db.execute('SELECT MAX(slot) FROM slots').fetchone()[0]
        with self.db:
            self.expire(now)
            for slot in range(previous+300 if previous is not None else receipt['t0'],receipt['end_exclusive'],300):
                self.db.execute('INSERT INTO slots VALUES(?,?,?,?)',(slot,'MISSED',None,encoded(dict(slot=slot,status='MISSED',reason='observer_not_present'))))
            self.put('sealed',dict(at=now,end_exclusive=receipt['end_exclusive']))
            self.put('last_seen',now)
            self.log(dict(type='FIXED_HORIZON_ENDED',at=now))

    def close(self):
        self.db.close()
