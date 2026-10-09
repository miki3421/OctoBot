"""Isolated, orderless qualification collector. Not installed or activated.

Implementation: work-card-a412674a-d488-40fd-81a4-7103db569108.
Only the CLI loads a root-owned activation receipt; tests inject synthetic I/O.
No imports from trading, issuer, credentials or existing runtime collectors.
"""
import argparse
import contextlib
import datetime as dt
import fcntl
import gzip
import hashlib
import json
import math
import os
from pathlib import Path
import sqlite3
import stat
import time
import urllib.error
import urllib.parse
import urllib.request

DAY = 86400
DAYS = 14
ATTEMPT_CAP = 42000
RAW_CAP = 512 * 1024 * 1024
PLAN_HASH = '028dc0690359c8f41e1fcaad7a2e2705ae3fb1d1a876ded1e7cb2139d67be5ec'
PLAN_PATH = 'docs/contracts/v13-universe-qualification-plan-v1.json'
PROPOSAL_HASH = '09f855a5af1b3945bf6bb9e9bca4a1676599d6c0c633da66387af650c460e49d'
BASE = {'books': 'https://api-futures.kucoin.com/api/v1/level2/depth20',
        'daily': 'https://fapi.binance.com/fapi/v1/klines',
        'funding': 'https://api-futures.kucoin.com/api/v1/contract/funding-rates',
        'kucoin_metadata': 'https://api-futures.kucoin.com/api/v1/contracts/active',
        'binance_metadata': 'https://fapi.binance.com/fapi/v1/exchangeInfo'}


def sha(raw):
    return hashlib.sha256(raw).hexdigest()


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(',', ':'), allow_nan=False).encode()


def decode(raw):
    def pairs(items):
        result = {}
        for key, value in items:
            if key in result:
                raise ValueError('duplicate_json_key')
            result[key] = value
        return result
    value = json.loads(raw, object_pairs_hook=pairs)
    canonical(value)
    return value


def utc(value):
    parsed = dt.datetime.fromisoformat(value.replace('Z', '+00:00'))
    if parsed.utcoffset() != dt.timedelta(0):
        raise ValueError('UTC_required')
    return parsed.timestamp()


def load_plan(repo):
    raw = (Path(repo) / PLAN_PATH).read_bytes()
    if sha(raw) != PLAN_HASH:
        raise ValueError('plan_pin_mismatch')
    plan = decode(raw)
    approval = (Path(repo) / 'docs/contracts/v13-universe-comparison-owner-approval-v1.json').read_bytes()
    if sha(approval) != plan['owner_approval_file_sha256']:
        raise ValueError('protocol_approval_pin_mismatch')
    return plan


def schedule(plan, start):
    if start % DAY or len(set(plan['universe'])) != 29:
        raise ValueError('midnight_UTC_and_29_symbols_required')
    jobs = []
    for day in range(DAYS):
        midnight = start + day * DAY
        for kind in BASE:
            symbols = [''] if kind.endswith('metadata') else plan['universe']
            slots = range(96) if kind == 'books' else [0]
            for slot in slots:
                stamp = midnight + (slot * 900 if kind == 'books' else 600 if kind in ('daily', 'funding') else 0)
                for symbol in symbols:
                    remote = plan['symbol_mapping_to_verify_at_collection'].get(symbol)
                    query = {}
                    if kind == 'books':
                        query = {'symbol': remote}
                    elif kind == 'daily':
                        query = {'symbol': symbol, 'interval': '1d', 'startTime': int((midnight-DAY)*1000),
                                 'endTime': int(midnight*1000-1), 'limit': 1}
                    elif kind == 'funding':
                        query = {'symbol': remote, 'from': int((midnight-DAY)*1000), 'to': int(midnight*1000-1)}
                    url = BASE[kind] + ('?' + urllib.parse.urlencode(query) if query else '')
                    key = f'{day}:{kind}:{slot}:{symbol}'
                    jobs.append((key, kind, symbol, stamp, stamp+60, url))
    return sorted(jobs, key=lambda j: (j[3], not j[1].endswith('metadata'), j[0]))


def safe_path(path, owner, directory=False):
    path = Path(path)
    if not path.is_absolute() or '..' in path.parts:
        raise ValueError('absolute_safe_path_required')
    for parent in reversed(path.parents):
        info = parent.lstat()
        if not stat.S_ISDIR(info.st_mode) or info.st_uid != 0 or info.st_mode & 0o022:
            raise ValueError('untrusted_parent')
    info = path.lstat()
    expected = stat.S_ISDIR if directory else stat.S_ISREG
    if not expected(info.st_mode) or info.st_uid != owner or info.st_mode & 0o022:
        raise ValueError('untrusted_path')


def read_activation(path, plan, now):
    """An external operator must author this receipt; protocol approval is insufficient."""
    safe_path(path, 0)
    config = decode(Path(path).read_bytes())
    if (config.get('schema_version') != 1 or config.get('plan_sha256') != PLAN_HASH
            or config.get('collector_sha256') != sha(Path(__file__).read_bytes())
            or config.get('periodic_downloads_authorized') is not True
            or config.get('service_activation_authorized') is not True
            or config.get('orders_authorized') is not False
            or not isinstance(config.get('owner_decision_reference'), str)
            or not config['owner_decision_reference'].strip()):
        raise ValueError('activation_not_authorized')
    if type(config.get('collector_uid')) is not int or config['collector_uid'] <= 0 or os.geteuid() != config['collector_uid']:
        raise ValueError('isolated_nonroot_identity_required')
    start, end = utc(config['start_utc']), utc(config['end_utc'])
    if start % DAY or end != start + DAYS*DAY or now >= end:
        raise ValueError('invalid_or_expired_window')
    if config.get('attempt_cap') != ATTEMPT_CAP or config.get('compressed_raw_bytes_cap') != RAW_CAP:
        raise ValueError('limits_mismatch')
    safe_path(config['storage_root'], config['collector_uid'], directory=True)
    if Path(config['storage_root']).stat().st_mode & 0o077:
        raise ValueError('private_storage_required')
    return config


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *args, **kwargs):
        raise ValueError('redirect_forbidden')


def public_get(url, limit):
    parts = urllib.parse.urlsplit(url)
    if parts.scheme != 'https' or parts.fragment or parts.username or parts.password or (parts.scheme+'://'+parts.netloc+parts.path) not in BASE.values():
        raise ValueError('endpoint_not_allowed')
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}), NoRedirect())
    request = urllib.request.Request(url, headers={'User-Agent': 'V13-Qualification/1', 'Accept-Encoding': 'identity'}, method='GET')
    try:
        response = opener.open(request, timeout=3)
    except urllib.error.HTTPError as error:
        response = error
    with response:
        raw = response.read(limit+1)
        # Preserve HTTP 418/429 even if the body exceeds the allowed size.
        # The caller stores a bounded prefix and marks it incomplete.
        return response.status, raw


def positive(value):
    number = float(value)
    if isinstance(value, bool) or not math.isfinite(number) or number <= 0:
        raise ValueError('invalid_positive_number')
    return number


class Collector:
    """Caller owns authorization. CLI enforces root receipt; direct API is for offline tests."""
    def __init__(self, root, plan, start, binding, fetch, clock=time.time):
        self.root, self.plan, self.start = Path(root), plan, start
        self.binding, self.fetch, self.clock = binding, fetch, clock
        self.jobs = schedule(plan, start)
        self.db_path = self.root / 'qualification.sqlite'

    def initialize(self):
        if self.clock() >= self.start:
            raise ValueError('initialization_must_precede_start')
        # Exclusive creation: missing/corrupt archives are never silently reset on resume.
        fd = os.open(self.db_path, os.O_CREAT | os.O_EXCL | os.O_WRONLY | os.O_NOFOLLOW, 0o600)
        os.close(fd)
        with self.connection() as db:
            db.executescript('''
                CREATE TABLE control (id INTEGER PRIMARY KEY CHECK(id=1), binding TEXT NOT NULL,
                    start REAL NOT NULL, last_clock REAL NOT NULL, stopped TEXT, failures INTEGER NOT NULL);
                CREATE TABLE jobs (id TEXT PRIMARY KEY, kind TEXT, symbol TEXT, slot REAL, deadline REAL,
                    url TEXT, state TEXT NOT NULL DEFAULT 'pending', started REAL, received REAL,
                    status INTEGER, raw_hash TEXT, raw_gzip BLOB, reserved INTEGER NOT NULL DEFAULT 0,
                    error TEXT, metrics TEXT);
            ''')
            db.execute('INSERT INTO control VALUES(1,?,?,?,NULL,0)', (self.binding, self.start, self.clock()))
            db.executemany('INSERT INTO jobs(id,kind,symbol,slot,deadline,url) VALUES(?,?,?,?,?,?)', self.jobs)
        fd = os.open(self.root, os.O_RDONLY | os.O_DIRECTORY)
        try:
            os.fsync(fd)
        finally:
            os.close(fd)

    @contextlib.contextmanager
    def connection(self):
        if self.db_path.is_symlink() or not self.db_path.is_file():
            raise ValueError('archive_missing_or_symlink')
        db = sqlite3.connect(self.db_path.as_uri()+'?mode=rw', uri=True, timeout=0)
        db.row_factory = sqlite3.Row
        try:
            db.execute('PRAGMA synchronous=FULL')
            db.execute('PRAGMA journal_mode=DELETE')
            with db:
                yield db
        finally:
            db.close()

    def check(self, db):
        if db.execute('PRAGMA quick_check').fetchone()[0] != 'ok':
            raise ValueError('storage_integrity')
        state = db.execute('SELECT * FROM control').fetchone()
        if state['binding'] != self.binding or state['start'] != self.start:
            raise ValueError('archive_binding_mismatch')
        actual = [tuple(r) for r in db.execute('SELECT id,kind,symbol,slot,deadline,url FROM jobs ORDER BY id')]
        if actual != sorted(self.jobs):
            raise ValueError('schedule_tampered')
        return state

    def contracts(self, db, slot):
        day = self.start + int((slot-self.start)//DAY)*DAY
        result = {}
        for kind in ('kucoin_metadata', 'binance_metadata'):
            row = db.execute("SELECT * FROM jobs WHERE kind=? AND slot=? AND state='valid'", (kind, day)).fetchone()
            if row is None:
                raise ValueError('same_day_metadata_missing')
            raw = gzip.decompress(row['raw_gzip'])
            if sha(raw) != row['raw_hash']:
                raise ValueError('metadata_tampered')
            result[kind] = decode(raw)
        ku = result['kucoin_metadata']['data']; bn = result['binance_metadata']['symbols']
        contracts = {}
        for symbol in self.plan['universe']:
            remote = self.plan['symbol_mapping_to_verify_at_collection'][symbol]
            k = [r for r in ku if r.get('symbol') == remote]
            b = [r for r in bn if r.get('symbol') == symbol]
            if len(k) != 1 or len(b) != 1:
                raise ValueError('mapping_missing_or_duplicate')
            k, b = k[0], b[0]
            base = symbol[:-4]
            if (k.get('baseCurrency') != ('XBT' if base == 'BTC' else base)
                    or k.get('quoteCurrency') != 'USDT' or k.get('settleCurrency') != 'USDT'
                    or k.get('status') != 'Open' or k.get('isInverse') is not False
                    or k.get('expireDate') is not None
                    or b.get('baseAsset') != base or b.get('quoteAsset') != 'USDT'
                    or b.get('marginAsset') != 'USDT' or b.get('status') != 'TRADING'
                    or b.get('contractType') != 'PERPETUAL'):
                raise ValueError('contract_identity_or_status')
            positive(k['multiplier'])
            contracts[symbol] = k
        return contracts

    def validate(self, job, raw, received, contract):
        value = decode(raw); kind = job['kind']
        if kind in ('kucoin_metadata', 'books', 'funding'):
            if not isinstance(value, dict) or value.get('code') != '200000':
                raise ValueError('kucoin_response_code')
            value = value['data']
        if kind == 'kucoin_metadata':
            if not isinstance(value, list) or not value or any(not isinstance(r, dict) for r in value):
                raise ValueError('metadata_schema')
        elif kind == 'binance_metadata':
            if (not isinstance(value, dict) or not isinstance(value.get('symbols'), list)
                    or not value['symbols'] or any(not isinstance(r, dict) for r in value['symbols'])):
                raise ValueError('metadata_schema')
        elif kind == 'daily':
            end = int(job['slot']//DAY*DAY*1000)
            if (not isinstance(value, list) or len(value) != 1 or len(value[0]) < 7
                    or value[0][0] != end-DAY*1000 or value[0][6] != end-1):
                raise ValueError('closed_previous_day_required')
            for item in value[0][1:5]:
                positive(item)
        elif kind == 'funding':
            end = int(job['slot']//DAY*DAY*1000)
            if not isinstance(value, list) or not value:
                raise ValueError('funding_missing')
            stamps = []
            for item in value:
                stamp = item['timepoint']; rate = float(item['fundingRate'])
                if type(stamp) is not int or not end-DAY*1000 <= stamp < end or not math.isfinite(rate):
                    raise ValueError('funding_window')
                stamps.append(stamp)
            if len(stamps) != len(set(stamps)):
                raise ValueError('duplicate_funding')
            return {'observed_points': len(stamps), 'settlement_coverage_certified': False}
        elif kind == 'books':
            stamp = value['ts']
            if type(stamp) is not int:
                raise ValueError('book_timestamp')
            seconds = stamp/(1e9 if stamp >= 1e17 else 1e6 if stamp >= 1e14 else 1e3)
            if not 0 <= received-seconds <= 60 or received > job['deadline']:
                raise ValueError('stale_future_or_late_book')
            sides = []
            for side, descending in [('bids', True), ('asks', False)]:
                levels = [(positive(p), positive(q)) for p, q in value[side]]
                prices = [p for p, q in levels]
                if not 1 <= len(levels) <= 20 or prices != sorted(set(prices), reverse=descending):
                    raise ValueError('book_levels')
                sides.append(levels)
            bid, ask = sides[0][0][0], sides[1][0][0]
            if bid >= ask:
                raise ValueError('crossed_book')
            mid = (bid+ask)/2; mult = positive(contract['multiplier'])
            result = {'spread_bps': (ask-bid)/mid*10000, 'min_quantity': None, 'min_notional': None}
            for name, levels in zip(('bid', 'ask'), sides):
                result[name+'_depth_usdt'] = math.fsum(p*q*mult for p, q in levels)
                result[name+'_extreme_distance_bps'] = abs(levels[-1][0]-mid)/mid*10000
                remaining = 3150/mid; initial = remaining; cost = 0
                for p, q in levels:
                    amount = min(remaining, q*mult); cost += amount*p; remaining -= amount
                result[name+'_vwap_for_3150_mid_notional'] = cost/initial if remaining <= 1e-12 else None
            canonical(result)
            return result
        return {'schema_valid': True}

    def tick(self):
        lock = os.open(self.root/'collector.lock', os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW, 0o600)
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
            return self._tick()
        finally:
            os.close(lock)

    def _tick(self):
        with self.connection() as db:
            state = self.check(db); now = self.clock()
            if state['stopped']:
                return {'state': 'stopped', 'reason': state['stopped']}
            if now < state['last_clock']:
                db.execute("UPDATE control SET stopped='clock_rollback'")
                return {'state': 'stopped', 'reason': 'clock_rollback'}
            db.execute('UPDATE control SET last_clock=?', (now,))
            # An uncertain claim is never repeated; its reserved bytes remain charged.
            db.execute("UPDATE jobs SET state='uncertain',error='interrupted_attempt' WHERE state='claimed'")
            db.execute("UPDATE jobs SET state='missing',error='window_missed' WHERE state='pending' AND deadline<?", (now,))
            if now >= self.start+DAYS*DAY:
                db.execute("UPDATE control SET stopped='window_complete'")
                return {'state': 'stopped', 'reason': 'window_complete'}
            jobs = list(db.execute("SELECT * FROM jobs WHERE state='pending' AND slot<=? AND deadline>=? ORDER BY slot, CASE WHEN kind LIKE '%metadata' THEN 0 ELSE 1 END,id", (now, now)))
        completed = 0
        for job in jobs:
            now = self.clock()
            with self.connection() as db:
                previous = db.execute('SELECT * FROM control').fetchone()
                if now < previous['last_clock']:
                    db.execute("UPDATE control SET stopped='clock_rollback'")
                    return {'state': 'stopped', 'reason': 'clock_rollback'}
                db.execute('UPDATE control SET last_clock=?', (now,))
                if now > job['deadline']:
                    db.execute("UPDATE jobs SET state='missing',error='window_missed' WHERE id=?", (job['id'],))
                    continue
                contract = None
                if not job['kind'].endswith('metadata'):
                    try:
                        contract = self.contracts(db, job['slot'])[job['symbol']]
                    except (ValueError, KeyError, TypeError) as error:
                        db.execute("UPDATE jobs SET state='missing',error=? WHERE id=?", (str(error)[:100], job['id']))
                        continue
                limit = 4*1024*1024 if job['kind'].endswith('metadata') else 64*1024
                reservation = limit + 2048
                attempts, used = db.execute('SELECT count(started),coalesce(sum(length(raw_gzip)),0) FROM jobs').fetchone()
                if attempts >= ATTEMPT_CAP or used+reservation > RAW_CAP:
                    db.execute("UPDATE control SET stopped='budget_limit'")
                    return {'state': 'stopped', 'reason': 'budget_limit'}
                # Physically allocate archive space and commit BEFORE contacting the source.
                db.execute("UPDATE jobs SET state='claimed',started=?,reserved=?,raw_gzip=zeroblob(?) WHERE id=? AND state='pending'",
                           (now, reservation, reservation, job['id']))
            status = None; raw = b''; error = None; metrics = None
            try:
                request_time = self.clock()
                if not now <= request_time <= job['deadline']:
                    raise ValueError('request_window_expired_or_clock_rollback')
                status, raw = self.fetch(job['url'], limit)
                if not isinstance(raw, bytes) or len(raw) > limit:
                    raw = raw[:limit] if isinstance(raw, bytes) else b''
                    raise ValueError('response_size_limit_incomplete_raw')
                received = self.clock()
                if received < now:
                    raise ValueError('clock_rollback')
                if received > job['deadline']:
                    raise ValueError('late_response')
                if status != 200:
                    raise ValueError('http_'+str(status))
                metrics = self.validate(job, raw, received, contract)
            except Exception as exc:
                received = self.clock()
                # No remote exception text or response fragments in the operational summary.
                error = str(exc)[:100] if isinstance(exc, ValueError) else type(exc).__name__
            compressed = gzip.compress(raw, mtime=0)
            with self.connection() as db:
                db.execute('UPDATE jobs SET state=?,received=?,status=?,raw_hash=?,raw_gzip=?,reserved=0,error=?,metrics=? WHERE id=?',
                           ('invalid' if error else 'valid', received, status, sha(raw), compressed, error,
                            canonical(metrics).decode() if metrics else None, job['id']))
                db.execute('UPDATE control SET failures=CASE WHEN ? THEN failures+1 ELSE 0 END,last_clock=max(last_clock,?)', (bool(error), received))
                failures = db.execute('SELECT failures FROM control').fetchone()[0]
                reason = 'http_rate_limit' if status in (418,429) else 'clock_rollback' if received < now else 'repeated_errors' if failures >= 3 else None
                if reason:
                    db.execute('UPDATE control SET stopped=?', (reason,))
                    return {'state': 'stopped', 'reason': reason}
            completed += 1
        return {'state': 'waiting', 'completed_this_tick': completed, 'orders_authorized': False}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('command', choices=['plan', 'initialize', 'tick'])
    parser.add_argument('--repo', type=Path, required=True)
    parser.add_argument('--activation', type=Path)
    args = parser.parse_args(); plan = load_plan(args.repo)
    if args.command == 'plan':
        print(json.dumps({'jobs': len(schedule(plan, 1790812800)), 'active': False, 'network_calls': 0}))
        return
    if args.activation is None:
        parser.error('external root-owned activation receipt required; none supplied by this release')
    config = read_activation(args.activation, plan, time.time())
    collector = Collector(config['storage_root'], plan, utc(config['start_utc']), sha(canonical(config)), public_get)
    if args.command == 'initialize':
        collector.initialize()
        print(json.dumps({'initialized': True, 'orders_authorized': False}))
    else:
        print(json.dumps(collector.tick()))


if __name__ == '__main__':
    main()
