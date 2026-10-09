"""Internal tests: work-card-5111d6c5-47ed-4414-8fd0-f227d0a1c23b.

All inputs here are synthetic. A separate frozen-account probe is archival review.
"""
import copy
import datetime as dt
import fcntl
import gzip
import json
import os
from pathlib import Path
import sqlite3
import subprocess
import sys

import pytest

from octobot.ai_strategy_lab import v13_original_funding_review as f
from octobot.ai_strategy_lab import v13_original_migration as m
from octobot.ai_strategy_lab import v13_original_portfolio as p
from octobot.ai_strategy_lab import v13_paper_v2 as paper
from tests.unit_tests.ai_strategy_lab.test_v13_original_migration import account

REPO = Path(__file__).resolve().parents[3]
BASE = dt.datetime(2026, 9, 21, 12, tzinfo=dt.timezone.utc)
FIRST = int((BASE+dt.timedelta(hours=4)).timestamp()*1000)
SECOND = FIRST+8*3600*1000


def write_journal(rig):
    previous = None
    with gzip.open(rig['journal'], 'wb') as stream:
        for record in rig['records']:
            record['previous_record_hash'] = previous
            record.pop('record_hash', None)
            previous = p.digest(record)
            record['record_hash'] = previous
            stream.write(p.canonical_bytes(record)+b'\n')
    rig['journal'].chmod(0o600)
    with gzip.open(rig['journal'], 'rb') as stream:
        prefix = stream.read()
    rig['kwargs']['expected_compressed_sha256'] = f._hash(rig['journal'])
    import hashlib
    rig['kwargs']['expected_prefix_sha256'] = hashlib.sha256(prefix).hexdigest()


@pytest.fixture
def review(account):
    root, source, state = account
    (root/'sandbox.marker').chmod(0o600); source.chmod(0o600)
    contract = p.read_json((REPO/'docs/contracts/v13-original-portfolio-adapter-candidate-v1.json').read_bytes())
    records = []
    for index in range(50):
        at = BASE+dt.timedelta(minutes=15*index)
        symbols = {}
        for mapping in contract['symbol_mapping_candidates']:
            points = []
            if int(at.timestamp()*1000) >= FIRST:
                points.append({'timestamp_ms': FIRST, 'rate': .001})
            if int(at.timestamp()*1000) >= SECOND:
                points.append({'timestamp_ms': SECOND, 'rate': -.002})
            symbols[mapping['symbol'][:-4]] = {
                'futures_symbol': mapping['research_symbol'], 'futures_remote_symbol': mapping['exchange_symbol'],
                'futures': {'mark_price': 100.+index},
                'funding': {'granularity_ms': 8*3600*1000, 'settled_last_24h': points,
                            'current_rate': 900., 'predicted_rate': -900.}}
        records.append({'schema_version': 1, 'mode': 'observation_only', 'public_data_only': True,
            'credentials_used': False, 'orders_authorized': False, 'research_only': True,
            'completeness': 1., 'symbol_count': len(symbols), 'symbols': symbols, 'interval_minutes': 15,
            'bucket_start_utc': at.isoformat(), 'bucket_end_utc': (at+dt.timedelta(minutes=15)).isoformat(),
            'observed_at_start': at.isoformat(), 'observed_at_end': at.isoformat()})
    records[0]['observed_at_end'] = state['last_market_at']
    rig = {'root': root, 'source': source, 'state': state, 'records': records,
           'journal': root/'journal.gz', 'target': root/'candidate.sqlite',
           'kwargs': {'captured_at': '2026-09-22T01:00:00Z', 'method': f.METHOD, 'repo_root': REPO}}
    write_journal(rig)
    state['last_market_hash'] = records[0]['record_hash']
    with sqlite3.connect(source) as db:
        db.execute('UPDATE state SET payload=?', (json.dumps(state),))
        db.execute('UPDATE market_events SET record_hash=?', (records[0]['record_hash'],))
    rig['kwargs']['expected_source_sha256'] = f._hash(source)
    return rig


def run(rig, **extra):
    return f.reconcile(rig['root'], rig['source'], rig['journal'], rig['target'], **(rig['kwargs'] | extra))


def tables(rig):
    with sqlite3.connect(rig['target']) as db:
        return {row[0] for row in db.execute("SELECT name FROM sqlite_master WHERE type='table'")}


def test_signed_settlements_previous_marks_original_history_and_current_rates_ignored(review):
    before = f._hash(review['source']); outcome = run(review); receipt = outcome['receipt']
    assert outcome['status'] == 'REVIEW_COMMITTED' and outcome['readiness'] == 'BLOCKED'
    with sqlite3.connect(review['target']) as db:
        events = [p.read_json(row[0]) for row in db.execute('SELECT payload FROM funding_review_events ORDER BY timestamp_ms')]
        assert [e['reference_mark'] for e in events] == [115., 147.]
        assert [e['amount_usdt_estimate'] for e in events] == [-.23, .588]
        assert [e['held_base_quantity'] for e in events] == [2., 2.]
        candidate = p.read_json(db.execute('SELECT candidate_state FROM funding_review_batches').fetchone()[0])
        assert candidate['positions']['BTCUSDT']['funding'] == pytest.approx(.358)
        assert p.read_json(db.execute('SELECT payload FROM state').fetchone()[0]) == review['state']
        assert db.execute('SELECT count(*) FROM funding_events').fetchone()[0] == 0
        assert db.execute('SELECT count(*) FROM orders').fetchone()[0] == 1
        assert db.execute('SELECT count(*) FROM equity_history').fetchone()[0] == 1
        assert db.execute('SELECT count(*) FROM funding_review_equity').fetchone()[0] == 1
    assert f._hash(review['source']) == before
    assert receipt['method_approved'] is False and receipt['data_quality_approved'] is False
    assert receipt['historical_availability'] == 'UNRESOLVED' and receipt['mark_measurement_timestamp'] is None
    assert receipt['gap_operationally_closed'] is False and receipt['legacy_cursors_unchanged'] is True
    assert all(v is None for v in receipt['policy_values'].values())
    assert receipt['contract_minimums'] == {'min_quantity': None, 'min_notional': None}
    assert all(e['reobservations'] > 0 for e in events)


def test_short_position_reverses_funding_sign(review):
    state = review['state']; state['positions']['BTCUSDT']['quantity'] = -2.
    with sqlite3.connect(review['source']) as db:
        db.execute('UPDATE orders SET quantity=-2.'); db.execute('UPDATE state SET payload=?', (json.dumps(state),))
        t = paper.totals(state); db.execute('UPDATE equity_history SET equity=?,pnl=?', (t['equity'],t['pnl']))
    review['kwargs']['expected_source_sha256'] = f._hash(review['source'])
    receipt = run(review)['receipt']
    assert receipt['funding_delta_usdt_estimate'] == pytest.approx(-.358)


def test_observed_zero_rate_is_allowed_but_missing_never_zero_filled(review):
    for r in review['records']:
        for e in r['symbols']['BTC']['funding']['settled_last_24h']:
            e['rate'] = 0.
    write_journal(review)
    assert run(review)['receipt']['funding_delta_usdt_estimate'] == 0.


def test_replay_across_process_restart_has_one_receipt_and_point(review):
    first = run(review); before = f._hash(review['target'])
    command = cli(review)
    second = json.loads(subprocess.check_output(command))
    assert second['status'] == 'ALREADY_REVIEWED' and second['receipt'] == first['receipt']
    assert f._hash(review['target']) == before


def cli(review):
    command = [sys.executable, '-m', 'octobot.ai_strategy_lab.v13_original_funding_review']
    for key in ('root','source','journal','target'):
        command += ['--'+key, str(review[key])]
    for key,value in review['kwargs'].items():
        command += ['--'+key.replace('_','-'), str(value)]
    return command


@pytest.mark.parametrize('stage', ['after_events','before_commit'])
def test_exception_rolls_back_schema_and_economic_candidate_then_retry(review,stage):
    def fail(at,db):
        if at == stage:
            raise OSError('injected write failure')
    with pytest.raises(OSError): run(review,_fault=fail)
    assert not (tables(review) & set(f.TABLES))
    assert run(review)['receipt']['event_count'] == 2


@pytest.mark.parametrize('stage', ['after_events','before_commit','after_commit'])
def test_process_death_hot_journal_and_post_commit_restart(review,stage):
    script = '''import json,os,sys
from octobot.ai_strategy_lab import v13_original_funding_review as f
a=json.loads(sys.argv[1])
def crash(stage,db):
 if stage==sys.argv[2]: os._exit(73)
f.reconcile(**a,_fault=crash)
'''
    args = {key:str(review[key]) for key in ('root','source','journal','target')}
    args.update({k:str(v) for k,v in review['kwargs'].items()})
    child = subprocess.run([sys.executable,'-c',script,json.dumps(args),stage])
    assert child.returncode == 73
    result = run(review)
    assert result['status'] == ('ALREADY_REVIEWED' if stage=='after_commit' else 'REVIEW_COMMITTED')
    with sqlite3.connect(review['target']) as db:
        assert db.execute('PRAGMA integrity_check').fetchone()[0] == 'ok'
        assert db.execute('SELECT count(*) FROM funding_review_events').fetchone()[0] == 2
        assert db.execute('SELECT count(*) FROM funding_review_equity').fetchone()[0] == 1


def test_actual_sqlite_full_rolls_back_then_retry(review):
    def limit(stage,db):
        if stage == 'before_transaction':
            pages = db.execute('PRAGMA page_count').fetchone()[0]
            assert db.execute('PRAGMA max_page_count='+str(pages)).fetchone()[0] == pages
    with pytest.raises(sqlite3.OperationalError,match='full'):
        run(review,_fault=limit)
    assert not (tables(review) & set(f.TABLES))
    assert run(review)['status'] == 'REVIEW_COMMITTED'


@pytest.mark.parametrize('change', ['rate_conflict','duplicate_settlement','gap','future_settlement','missing_mark','mapping','missing_asset','predicted_only','timing','missing_cursor','nonfinite'])
def test_invalid_archive_denied_before_output_created(review,change):
    records = review['records']
    if change == 'rate_conflict': records[-1]['symbols']['BTC']['funding']['settled_last_24h'][0]['rate'] = .04
    elif change == 'duplicate_settlement':
        points=records[-1]['symbols']['BTC']['funding']['settled_last_24h']; points.insert(1,copy.deepcopy(points[0]))
    elif change == 'gap':
        for r in records:
            r['symbols']['BTC']['funding']['settled_last_24h'] = [e for e in r['symbols']['BTC']['funding']['settled_last_24h'] if e['timestamp_ms'] != SECOND]
    elif change == 'future_settlement': records[-1]['symbols']['BTC']['funding']['settled_last_24h'][-1]['timestamp_ms'] += 86400000
    elif change == 'missing_mark': records[-1]['symbols']['BTC']['futures']['mark_price'] = None
    elif change == 'mapping': records[-1]['symbols']['BTC']['futures_remote_symbol'] = 'BTC-SPOT'
    elif change == 'missing_asset':
        del records[-1]['symbols']['ZEC']; records[-1]['symbol_count'] -= 1
    elif change == 'predicted_only':
        for r in records: r['symbols']['BTC']['funding']['settled_last_24h'] = []
    elif change == 'timing': records[-1]['observed_at_end'] = '2026-10-01T00:00:00Z'
    elif change == 'missing_cursor': records[0]['observed_at_start'] = '2026-09-21T11:59:59Z'
    elif change == 'nonfinite': records[-1]['symbols']['BTC']['funding']['settled_last_24h'][0]['rate'] = True
    write_journal(review)
    with pytest.raises((p.Rejected,ValueError)): run(review)
    assert not review['target'].exists()


@pytest.mark.parametrize('change',['quantity','fee','pending','history'])
def test_inconsistent_source_fill_or_state_denied(review,change):
    with sqlite3.connect(review['source']) as db:
        state = p.read_json(db.execute('SELECT payload FROM state').fetchone()[0])
        if change == 'quantity': state['positions']['BTCUSDT']['quantity'] = 3.
        elif change == 'fee': db.execute('UPDATE orders SET fee=0.4')
        elif change == 'pending': state['pending'] = {'targets':{}}
        else: db.execute('UPDATE equity_history SET equity=42.')
        db.execute('UPDATE state SET payload=?', (json.dumps(state),))
    review['kwargs']['expected_source_sha256'] = f._hash(review['source'])
    with pytest.raises(p.Rejected): run(review)
    assert not review['target'].exists()


@pytest.mark.parametrize('change',['event','receipt','candidate','point','legacy_order','event_key','reapproved_receipt','point_kind','schema','trigger'])
def test_replay_tampered_commit_is_denied(review,change):
    run(review)
    with sqlite3.connect(review['target']) as db:
        if change == 'event': db.execute('DELETE FROM funding_review_events WHERE timestamp_ms=?',(FIRST,))
        elif change == 'receipt': db.execute("UPDATE funding_review_batches SET receipt='{}'")
        elif change == 'candidate': db.execute("UPDATE funding_review_batches SET candidate_state='{}'")
        elif change == 'point': db.execute('UPDATE funding_review_equity SET equity=1.')
        elif change == 'legacy_order': db.execute('UPDATE orders SET quantity=4.')
        elif change == 'event_key': db.execute("UPDATE funding_review_events SET account='wrong'")
        elif change == 'reapproved_receipt':
            receipt=p.read_json(db.execute('SELECT receipt FROM funding_review_batches').fetchone()[0])
            receipt.pop('receipt_hash');receipt['method_approved']=True;receipt=p.seal_receipt(receipt)
            db.execute('UPDATE funding_review_batches SET receipt=?,receipt_hash=?',(json.dumps(receipt),receipt['receipt_hash']))
        elif change == 'point_kind': db.execute("UPDATE funding_review_equity SET point_kind='forward'")
        elif change == 'schema': db.execute('ALTER TABLE funding_review_events ADD COLUMN authority TEXT')
        else: db.execute('CREATE TRIGGER arbitrary_writer AFTER INSERT ON funding_review_events BEGIN UPDATE orders SET quantity=4; END')
    with pytest.raises(p.Rejected): run(review)


@pytest.mark.parametrize('key',['expected_source_sha256','expected_compressed_sha256','expected_prefix_sha256'])
def test_external_input_pin_mismatch_denied(review,key):
    with pytest.raises(p.Rejected): run(review,**{key:'f'*64})
    assert not review['target'].exists()


def test_method_requires_explicit_unapproved_estimate_selection(review):
    with pytest.raises(p.Rejected,match='explicit_candidate_method'): run(review,method='approved')
    assert not review['target'].exists()


def test_writer_lock_paths_symlink_hardlink_wal_and_source_immutable(review):
    lock = review['root']/'funding-review.lock'; lock.write_bytes(b'');lock.chmod(0o600)
    with lock.open('rb') as stream:
        fcntl.flock(stream,fcntl.LOCK_EX|fcntl.LOCK_NB)
        with pytest.raises(p.Rejected,match='writer_busy'): run(review)
    source = review['source']; link=review['root']/'linked.sqlite';link.symlink_to(source)
    with pytest.raises(p.Rejected): f._safe(review['root'],link)
    link.unlink();os.link(source,link)
    with pytest.raises(p.Rejected): run(review)
    link.unlink()
    wal=Path(str(source)+'-wal');wal.write_bytes(b'uncheckpointed');wal.chmod(0o600)
    with pytest.raises(p.Rejected,match='offline_checkpoint_required'): run(review)
    wal.unlink()
    with pytest.raises(p.Rejected,match='operational_path_forbidden'): f._safe(review['root'],review['root']/'octobot-local')
    with pytest.raises(p.Rejected,match='distinct_private_target'): f.reconcile(review['root'],source,review['journal'],source,**review['kwargs'])
    assert not review['target'].exists()


def test_separate_input_bundle_requires_separate_candidate(review):
    run(review)
    review['records'][-1]['symbols']['BTC']['funding']['predicted_rate'] = 901.
    write_journal(review)
    with pytest.raises(p.Rejected,match='different_review_batch'): run(review)
