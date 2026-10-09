"""Inactive retrospective funding estimate, on private copied accounts only.

work-card-edc2e575-f692-4997-807f-352a1b3c8ba0.
No operational mode, issuer, grants, network, fills or legacy table writes.
The explicitly selected method is an unapproved review simulation.
"""
from __future__ import annotations

import argparse
from bisect import bisect_left
from contextlib import closing, contextmanager
import copy
import datetime as dt
import fcntl
import gzip
import hashlib
import math
import os
from pathlib import Path
import sqlite3
import stat

from octobot.ai_strategy_lab import v13_original_migration as migration
from octobot.ai_strategy_lab import v13_original_portfolio as p
from octobot.ai_strategy_lab import v13_paper_v2 as paper

MARKER = migration.MARKER
SCOPE = 'COPIED_ACCOUNT_ESTIMATE_REVIEW_ONLY'
METHOD = 'UNAPPROVED_LEGACY_PREVIOUS_DECLARED_MARK_ESTIMATE_V1'
TABLES = {
    'funding_review_events': '''CREATE TABLE funding_review_events (
        account TEXT NOT NULL, symbol TEXT NOT NULL, timestamp_ms INTEGER NOT NULL,
        batch_id TEXT NOT NULL, payload TEXT NOT NULL,
        PRIMARY KEY(account,symbol,timestamp_ms))''',
    'funding_review_batches': '''CREATE TABLE funding_review_batches (
        batch_id TEXT PRIMARY KEY, accounted_at TEXT NOT NULL, receipt_hash TEXT NOT NULL,
        receipt TEXT NOT NULL, candidate_state TEXT NOT NULL)''',
    'funding_review_equity': '''CREATE TABLE funding_review_equity (
        batch_id TEXT PRIMARY KEY, accounted_at TEXT NOT NULL, equity REAL NOT NULL,
        pnl REAL NOT NULL, point_kind TEXT NOT NULL)''',
}


def _safe(root, path, *, directory=False):
    path = migration._safe(root, path, directory=directory)
    # Private namespace only. Also refuse symlinks above the root itself.
    for ancestor in (Path(root).absolute(), *Path(root).absolute().parents):
        if stat.S_ISLNK(ancestor.lstat().st_mode):
            raise p.Rejected('symlink_forbidden')
    for item in (Path(root), path, Path(root)/'sandbox.marker'):
        info = item.stat()
        if info.st_uid != os.geteuid() or info.st_mode & 0o077:
            raise p.Rejected('private_owned_review_required')
    return path


def _hash(path):
    digest = hashlib.sha256()
    with Path(path).open('rb') as stream:
        for block in iter(lambda: stream.read(1024*1024), b''):
            digest.update(block)
    return digest.hexdigest()


@contextmanager
def _lock(root):
    _safe(root, root, directory=True)
    path = Path(root)/'funding-review.lock'
    fd = os.open(path, os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW, 0o600)
    try:
        _safe(root, path)
        try:
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as error:
            raise p.Rejected('review_writer_busy') from error
        yield
    finally:
        os.close(fd)


def _ms(value):
    return int(p.timestamp(value).timestamp()*1000)


def _number(value, *, positive=False):
    return migration._number(value, positive=positive)


def _records(path, *, expected_prefix_hash, captured_at):
    digest = hashlib.sha256()
    previous, previous_bucket, previous_end, interval = None, None, None, None
    records = []
    with gzip.open(path, 'rb') as stream:
        for line in stream:
            if not line.endswith(b'\n'):
                raise p.Rejected('partial_journal_line')
            digest.update(line)
            record = p.read_json(line)
            raw_hash = record.get('record_hash')
            if raw_hash != p.digest({k: v for k, v in record.items() if k != 'record_hash'}):
                raise p.Rejected('record_hash_mismatch')
            if record.get('previous_record_hash') != previous:
                raise p.Rejected('journal_chain_mismatch')
            if (type(record.get('schema_version')) is not int or record['schema_version'] != 1
                    or record.get('mode') != 'observation_only'
                    or record.get('public_data_only') is not True
                    or record.get('credentials_used') is not False
                    or record.get('orders_authorized') is not False
                    or record.get('paper_orders_authorized', False) is not False
                    or record.get('research_only') is not True
                    or record.get('completeness') != 1.0
                    or record.get('symbol_count') != len(record.get('symbols', {}))):
                raise p.Rejected('not_legacy_observation_only')
            minutes = record.get('interval_minutes')
            if type(minutes) is not int or minutes <= 0:
                raise p.Rejected('invalid_declared_interval')
            interval = interval or minutes
            bucket = p.timestamp(record['bucket_start_utc'])
            start, end = p.timestamp(record['observed_at_start']), p.timestamp(record['observed_at_end'])
            if (minutes != interval or start > end or end > p.timestamp(captured_at)
                    or (previous_end is not None and end <= previous_end)
                    or p.timestamp(record['bucket_end_utc']) != bucket+dt.timedelta(minutes=minutes)
                    or (previous_bucket is not None and bucket-previous_bucket != dt.timedelta(minutes=interval))):
                raise p.Rejected('noncontiguous_or_invalid_declared_times')
            records.append(record)
            previous, previous_bucket, previous_end = raw_hash, bucket, end
    if not records or digest.hexdigest() != expected_prefix_hash:
        raise p.Rejected('prefix_hash_mismatch')
    return records


def _events(state, orders, records, mapping):
    """Derive events from the sealed journal, never from an inventory of totals."""
    held = {symbol for symbol, pos in state['positions'].items() if pos['quantity']}
    if not held:
        raise p.Rejected('held_positions_required')
    references = {symbol: [] for symbol in held}
    points = {symbol: {} for symbol in held}
    intervals = {symbol: set() for symbol in held}
    for record in records:
        end = record['observed_at_end']
        for symbol, identity in mapping.items():
            obs = record['symbols'].get(symbol[:-4])
            if (obs is None or obs.get('futures_symbol') != identity['research_symbol']
                    or obs.get('futures_remote_symbol') != identity['exchange_symbol']):
                raise p.Rejected('required_mapping_mismatch')
            if symbol not in held:
                continue
            price = _number(obs['futures']['mark_price'], positive=True)
            references[symbol].append((_ms(end), price, record['record_hash'], end))
            funding = obs['funding']
            interval = funding['granularity_ms']
            if type(interval) is not int or interval <= 0:
                raise p.Rejected('invalid_declared_funding_interval')
            intervals[symbol].add(interval)
            previous = None
            for event in funding['settled_last_24h']:
                ms, rate = event['timestamp_ms'], _number(event['rate'])
                if (type(ms) is not int or ms <= 0 or ms > _ms(end)
                        or (previous is not None and ms <= previous)):
                    raise p.Rejected('unordered_or_future_settlement')
                previous = ms
                existing = points[symbol].get(ms)
                if existing and existing['rate'] != rate:
                    raise p.Rejected('settlement_rate_conflict')
                if existing:
                    existing['reobservations'] += 1
                else:
                    points[symbol][ms] = {'rate': rate, 'source_record_hash': record['record_hash'],
                                         'first_seen_at_declared': end, 'reobservations': 0}
    result = []
    for symbol in sorted(held):
        start = _ms(state['positions'][symbol]['last_mark_at'])
        selected = sorted(ms for ms in points[symbol] if ms > start)
        if len(intervals[symbol]) != 1 or not selected:
            raise p.Rejected('settlement_coverage_unresolved')
        interval = next(iter(intervals[symbol]))
        if (selected[0]-start > interval or _ms(records[-1]['observed_at_end'])-selected[-1] >= interval
                or any(b-a != interval for a, b in zip(selected, selected[1:]))):
            raise p.Rejected('declared_settlement_coverage_gap')
        refs = references[symbol]
        for ms in selected:
            index = bisect_left([r[0] for r in refs], ms)-1
            if index < 0:
                raise p.Rejected('previous_observed_mark_missing')
            _, price, mark_hash, mark_end = refs[index]
            quantity = math.fsum(row['quantity'] for row in orders
                                 if row['symbol'] == symbol and _ms(row['recorded_at']) < ms)
            if any(row['symbol'] == symbol and _ms(row['recorded_at']) == ms for row in orders):
                raise p.Rejected('fill_settlement_order_ambiguous')
            migration._same(quantity, state['positions'][symbol]['quantity'])
            point = points[symbol][ms]
            amount = _number(-quantity*price*point['rate'])
            result.append({'account': migration.ACCOUNT, 'symbol': symbol, 'exchange_symbol': mapping[symbol]['exchange_symbol'],
                'timestamp_ms': ms, 'rate': point['rate'], 'held_base_quantity': quantity,
                'quantity_evidence': 'filled_orders_replayed_before_settlement', 'reference_mark': price,
                'amount_usdt_estimate': amount, 'amount_formula': '-held_base_quantity * previous_declared_mark * settled_rate',
                'rate_source_record_hash': point['source_record_hash'],
                'rate_first_seen_at_declared': point['first_seen_at_declared'],
                'mark_source_record_hash': mark_hash, 'mark_record_completed_at_declared': mark_end,
                'mark_measurement_timestamp': None, 'historical_availability': 'UNRESOLVED',
                'reobservations': point['reobservations']})
    return sorted(result, key=lambda item: (item['timestamp_ms'], item['symbol']))


def _connect(root, target):
    _safe(root, target)
    for suffix in ('-journal', '-wal', '-shm'):
        sidecar = Path(str(target)+suffix)
        if sidecar.exists() or sidecar.is_symlink():
            _safe(root, sidecar)
            if suffix != '-journal' and sidecar.stat().st_size:
                raise p.Rejected('wal_review_not_supported')
    db = sqlite3.connect(target, timeout=1)
    db.row_factory = sqlite3.Row
    db.execute('PRAGMA journal_mode=DELETE')
    db.execute('PRAGMA synchronous=FULL')
    db.execute('PRAGMA trusted_schema=OFF')
    return db


def _snapshot(db, tables):
    return {name: migration._table_digest(db, name) for name in sorted(tables)}


def _receipt(identity, events, candidate, before, after, inspection, cutoff, accounted_at):
    p.timestamp(accounted_at)
    return p.seal_receipt({'schema_version': 1, 'kind': 'v13-original-funding-estimate-review-v1',
        'scope': SCOPE, 'batch_id': p.digest(identity), 'identity': identity, 'accounted_at': accounted_at,
        'event_count': len(events), 'events_hash': p.digest(events), 'candidate_state_hash': p.digest(candidate),
        'source_cutoff_at_declared': cutoff, 'totals_before': before, 'totals_candidate': after,
        'funding_delta_usdt_estimate': math.fsum(e['amount_usdt_estimate'] for e in events),
        'method_approved': False, 'data_quality_approved': False, 'historical_availability': 'UNRESOLVED',
        'mark_measurement_timestamp': None, 'operational_approval': False, 'issuable': False,
        'new_orders': 0, 'legacy_tables_unchanged': True, 'legacy_cursors_unchanged': True,
        'gap_operationally_closed': False, 'risk_counters': inspection['risk_counters'],
        'policy_values': {k: None for k in ('daily_loss','drawdown','order_frequency','cooldown')},
        'contract_minimums': {'min_quantity': None, 'min_notional': None},
        'migration': 'NEW_BUNDLE_EPOCH_REQUIRED_AFTER_ACCEPTED_RECONCILIATION_NOT_CREATED'})


def reconcile(root, source, journal, target, *, expected_source_sha256,
              expected_compressed_sha256, expected_prefix_sha256, captured_at,
              method, repo_root, _fault=None):
    """One review batch, idempotent across process death. Never applies to runtime."""
    if method != METHOD:
        raise p.Rejected('explicit_candidate_method_required')
    for value in (expected_source_sha256, expected_compressed_sha256, expected_prefix_sha256):
        p.require_hash(value)
    root, source, journal, target = map(lambda x: Path(x).absolute(), (root, source, journal, target))
    if target.parent != root or target.suffix != '.sqlite' or target in (source, journal):
        raise p.Rejected('distinct_private_target_required')
    with _lock(root):
        _safe(root, source); _safe(root, journal)
        if _hash(source) != expected_source_sha256 or _hash(journal) != expected_compressed_sha256:
            raise p.Rejected('input_hash_mismatch')
        contract_path = Path(repo_root)/'docs/contracts/v13-original-portfolio-adapter-candidate-v1.json'
        if _hash(contract_path) != p.CONTRACT_SHA256:
            raise p.Rejected('adapter_contract_pin_mismatch')
        contract = p.read_json(contract_path.read_bytes())
        state, inspection = migration.inspect_legacy(root, source, checkpoint_at=captured_at, universe=contract['universe'])
        with closing(migration._db(root, source)) as db:
            orders = [dict(row) for row in db.execute('SELECT * FROM orders ORDER BY id')]
        if (any(p.timestamp(o['recorded_at']) > p.timestamp(state['last_market_at']) for o in orders)
                or any(p.timestamp(a['recorded_at']) > p.timestamp(b['recorded_at']) for a, b in zip(orders, orders[1:]))):
            raise p.Rejected('fills_after_baseline_or_nonchronological')
        records = _records(journal, expected_prefix_hash=expected_prefix_sha256, captured_at=captured_at)
        cursor = [r for r in records if r['record_hash'] == state['last_market_hash']]
        if len(cursor) != 1 or cursor[0]['observed_at_end'] != state['last_market_at']:
            raise p.Rejected('baseline_market_record_missing')
        events = _events(state, orders, records, {m['symbol']: m for m in contract['symbol_mapping_candidates']})
        if _hash(source) != expected_source_sha256 or _hash(journal) != expected_compressed_sha256:
            raise p.Rejected('inputs_changed_during_review')
        candidate = copy.deepcopy(state)
        for symbol, pos in candidate['positions'].items():
            pos['funding'] = math.fsum([pos['funding'], *(e['amount_usdt_estimate'] for e in events if e['symbol'] == symbol)])
        before, after = paper.totals(state), paper.totals(candidate, require_positive=False)
        identity = {'scope': SCOPE, 'account': migration.ACCOUNT, 'method': METHOD,
                    'source_ledger_sha256': expected_source_sha256, 'source_state_hash': p.digest(state),
                    'compressed_archive_sha256': expected_compressed_sha256, 'prefix_sha256': expected_prefix_sha256,
                    'captured_at_declared': captured_at, 'events_hash': p.digest(events), 'component_sha256': _hash(__file__)}
        batch_id = p.digest(identity)
        if not target.exists() and not target.is_symlink():
            migration._backup(root, source, target)
            target.chmod(0o600)
        with closing(_connect(root, target)) as db:
            if _fault:
                _fault('before_transaction', db)
            db.execute('BEGIN IMMEDIATE')
            try:
                tables = migration._tables(db)
                legacy = set(inspection['history'])
                if tables not in (legacy, legacy | set(TABLES)) or _snapshot(db, legacy) != inspection['history']:
                    raise p.Rejected('copied_legacy_history_mismatch')
                if tables == legacy:
                    for ddl in TABLES.values():
                        db.execute(ddl)
                if db.execute("SELECT count(*) FROM sqlite_master WHERE type IN ('trigger','view')").fetchone()[0]:
                    raise p.Rejected('unexpected_review_sql_objects')
                for name, ddl in TABLES.items():
                    if db.execute('SELECT sql FROM sqlite_master WHERE name=?', (name,)).fetchone()[0] != ddl:
                        raise p.Rejected('review_schema_mismatch')
                existing = db.execute('SELECT * FROM funding_review_batches').fetchall()
                if existing:
                    if len(existing) != 1 or existing[0]['batch_id'] != batch_id:
                        raise p.Rejected('different_review_batch_requires_new_copy')
                    receipt = p.read_json(existing[0]['receipt'])
                    p.check_receipt(receipt, existing[0]['receipt_hash'])
                    expected_receipt = _receipt(identity, events, candidate, before, after, inspection,
                                               records[-1]['observed_at_end'], existing[0]['accounted_at'])
                    rows = db.execute('SELECT * FROM funding_review_events ORDER BY timestamp_ms,symbol').fetchall()
                    recorded_events = [p.read_json(row['payload']) for row in rows]
                    equity = db.execute('SELECT * FROM funding_review_equity').fetchall()
                    if (recorded_events != events or p.read_json(existing[0]['candidate_state']) != candidate
                            or receipt != expected_receipt
                            or [(r['account'], r['symbol'], r['timestamp_ms'], r['batch_id']) for r in rows]
                               != [(migration.ACCOUNT, e['symbol'], e['timestamp_ms'], batch_id) for e in events]
                            or len(equity) != 1 or equity[0]['batch_id'] != batch_id
                            or equity[0]['accounted_at'] != receipt['accounted_at']
                            or equity[0]['point_kind'] != 'RETROSPECTIVE_ESTIMATE_AT_REVIEW_TIME'
                            or equity[0]['equity'] != after['equity'] or equity[0]['pnl'] != after['pnl']):
                        raise p.Rejected('review_commit_incoherent')
                    db.rollback()
                    return {'status': 'ALREADY_REVIEWED', 'receipt': receipt, 'readiness': 'BLOCKED'}
                if db.execute('SELECT count(*) FROM funding_review_events').fetchone()[0] or db.execute('SELECT count(*) FROM funding_review_equity').fetchone()[0]:
                    raise p.Rejected('orphan_review_rows')
                accounted_at = dt.datetime.now(dt.timezone.utc).isoformat()
                if p.timestamp(captured_at) > p.timestamp(accounted_at):
                    raise p.Rejected('future_capture_time')
                receipt = _receipt(identity, events, candidate, before, after, inspection,
                                   records[-1]['observed_at_end'], accounted_at)
                for event in events:
                    db.execute('INSERT INTO funding_review_events VALUES (?,?,?,?,?)',
                               (migration.ACCOUNT, event['symbol'], event['timestamp_ms'], batch_id, p.canonical_bytes(event).decode()))
                if _fault:
                    _fault('after_events', db)
                db.execute('INSERT INTO funding_review_batches VALUES (?,?,?,?,?)',
                           (batch_id, accounted_at, receipt['receipt_hash'], p.canonical_bytes(receipt).decode(), p.canonical_bytes(candidate).decode()))
                db.execute('INSERT INTO funding_review_equity VALUES (?,?,?,?,?)',
                           (batch_id, accounted_at, after['equity'], after['pnl'], 'RETROSPECTIVE_ESTIMATE_AT_REVIEW_TIME'))
                if _fault:
                    _fault('before_commit', db)
                if _snapshot(db, legacy) != inspection['history']:
                    raise p.Rejected('legacy_history_changed_during_review')
                db.commit()
                if _fault:
                    _fault('after_commit', db)
            except BaseException:
                db.rollback()
                raise
        return {'status': 'REVIEW_COMMITTED', 'receipt': receipt, 'readiness': 'BLOCKED'}


def main():
    cli = argparse.ArgumentParser(description=__doc__)
    for name in ('root', 'source', 'journal', 'target', 'repo-root'):
        cli.add_argument('--'+name, type=Path, required=True)
    for name in ('expected-source-sha256','expected-compressed-sha256','expected-prefix-sha256','captured-at','method'):
        cli.add_argument('--'+name, required=True)
    args = vars(cli.parse_args())
    print(p.canonical_bytes(reconcile(**args)).decode())


if __name__ == '__main__':
    main()
