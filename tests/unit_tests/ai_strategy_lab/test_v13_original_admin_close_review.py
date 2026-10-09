"""Internal tests: work-card-0954a079-fe50-4c48-95cb-83115521bfac.

Economic inputs are SYNTHETIC. Peer tests use actual Linux credentials;
privileged primitive tests do not substitute for independent security review.
"""
from contextlib import closing
import copy
import json
import multiprocessing
import os
from pathlib import Path
import shutil
import socket
import sqlite3
import tempfile

import pytest

from octobot.ai_strategy_lab import v13_original_admin_close_review as a
from octobot.ai_strategy_lab import v13_original_migration as m
from octobot.ai_strategy_lab import v13_original_portfolio as p
from octobot.ai_strategy_lab import v13_market_sanity as sanity
from octobot.ai_strategy_lab import v13_paper_v2 as paper
from tests.unit_tests.ai_strategy_lab.test_v13_original_migration import account, prepare

NOW = '2026-09-28T16:00:00Z'
MARK = '2026-09-28T15:59:00Z'


def _as_uid(uid, gid, action):
    receiver, sender = multiprocessing.Pipe(duplex=False)
    def child():
        try:
            os.setgroups([]); os.setgid(gid); os.setuid(uid)
            sender.send(('ok', action()))
        except BaseException as error:
            sender.send(('error', type(error).__name__, str(error)))
    process = multiprocessing.get_context('fork').Process(target=child)
    process.start(); sender.close(); assert receiver.poll(10)
    result = receiver.recv(); process.join(10); assert process.exitcode == 0
    return result


def synthetic_market(symbol='BTCUSDT'):
    quote = {'symbol': symbol, 'market_identity': sanity.POLICY.market_identity,
        'timestamp': MARK, 'mark_timestamp': MARK, 'metadata_observed_at': MARK,
        'mark_price': 101., 'step': .5, 'price_tick': .1, 'fee_rate': .0006,
        'min_quantity': None, 'min_notional': None,
        'bids': [{'price': 100., 'base_quantity': 1000.}],
        'asks': [{'price': 102., 'base_quantity': 1000.}]}
    return {'scope': a.MARKET_SCOPE, 'schema_version': 2, 'credentials_used': False,
        'kucoin_order_admissibility_proven': False, 'observed_at_start': MARK,
        'observed_at_end': '2026-09-28T15:59:10Z', 'quotes': {symbol: quote}}


def save_market(root, value):
    value = copy.deepcopy(value); value.pop('record_hash', None)
    value['record_hash'] = p.digest(value)
    path = root/'market-fixture.json'; path.write_bytes(p.canonical_bytes(value))
    return path, m._hash(path)


def configure(root, manifest, *, executor_uid=0, executor_gid=0, admin_uid=30410, admin_gid=0):
    config = a.review_config('candidate', manifest, m._hash(root/'candidate/manifest.json'),
        executor_uid=executor_uid, executor_gid=executor_gid,
        admin_uid=admin_uid, admin_gid=admin_gid, strategy_uid=30430)
    path = root/'admin-review-config.json'
    if path.exists(): path.chmod(0o644)
    path.write_bytes(p.canonical_bytes(config)); path.chmod(0o444)
    return m._hash(path)


@pytest.fixture
def review(account):
    root, source, _ = account
    result = prepare(account)
    manifest = p.read_json((root/'candidate/manifest.json').read_bytes())
    pin = configure(root, manifest)
    executor = a.ReviewExecutor(root, expected_config_hash=pin)
    head = executor.initialize()
    path, market_hash = save_market(root, synthetic_market())
    pos = executor.initial['positions']['BTCUSDT']
    command = {'schema_version': 1, 'command_id': 'd'*64, 'account': m.ACCOUNT,
        'epoch_candidate': manifest['epoch_candidate'], 'symbol': 'BTCUSDT',
        'position_id': pos['position_id'], 'generation': pos['generation'],
        'issued_at': NOW, 'expires_at': '2026-09-28T16:01:00Z', 'maximum_quantity_to_reduce': 2.}
    return {'root': root, 'source': source, 'executor': executor, 'head': head,
        'pin': pin, 'market_path': path, 'market_hash': market_hash, 'command': command,
        'bundle_pin': result['manifest_sha256']}


def run(r, command=None, **kw):
    args = {'market_path': r['market_path'], 'expected_market_hash': r['market_hash'],
        'expected_head': r['head'], 'now': NOW}; args.update(kw)
    return r['executor']._execute(command or r['command'], **args)


def db_state(r):
    with sqlite3.connect(r['executor'].path) as db:
        return p.read_json(db.execute('SELECT body FROM review_state').fetchone()[0]), db.execute('SELECT * FROM review_claims').fetchall()


def head_at(r):
    with sqlite3.connect(r['executor'].path) as db:
        row = db.execute('SELECT hash FROM review_events ORDER BY seq DESC LIMIT 1').fetchone()
    return row[0] if row else r['head']


def test_full_close_without_strategy_or_issuer_and_with_unknown_minimums(review):
    r = review; before = m._hash(r['source'])
    original = copy.deepcopy(r['executor'].initial)
    result = run(r); state, claims = db_state(r)
    assert result['status'] == 'SIMULATED_REVIEW_CLOSE' and result['readiness'] == 'BLOCKED'
    assert state['positions']['BTCUSDT']['quantity'] == 0
    assert claims[0][2] == 'COMMITTED'
    assert state['order_count'] == original['order_count'] == 1
    assert state['positions']['BTCUSDT']['last_mark_at'] == original['positions']['BTCUSDT']['last_mark_at']
    assert state['positions']['BTCUSDT']['funding'] == original['positions']['BTCUSDT']['funding']
    assert result['detail']['funding_coverage'] == 'UNRESOLVED'
    assert result['detail']['P0_03']['protective'] is True
    assert m._hash(r['source']) == before
    m.verify(r['root'], r['root']/'candidate', expected_manifest_sha256=r['bundle_pin'])
    with pytest.raises(p.Rejected, match='replay'):
        run(r, expected_head=result['head'])
    reopened = a.ReviewExecutor(r['root'], expected_config_hash=r['pin'])
    with closing(reopened._open(result['head'])[0]): pass
    assert not list(r['root'].rglob('approvals.sqlite'))


def test_partial_then_current_quantity_checked_and_tombstone_not_reopened(review):
    r = review; cmd = copy.deepcopy(r['command']); cmd['maximum_quantity_to_reduce'] = .5
    first = run(r, cmd); assert first['detail']['quantity_after'] == 1.5
    cmd['command_id'] = 'e'*64; cmd['maximum_quantity_to_reduce'] = 2.
    with pytest.raises(p.Rejected, match='current_position'): run(r, cmd, expected_head=first['head'])
    assert len(db_state(r)[1]) == 1
    cmd['maximum_quantity_to_reduce'] = 1.5
    second = run(r, cmd, expected_head=first['head'])
    cmd['command_id'] = 'f'*64
    with pytest.raises(p.Rejected, match='flat'): run(r, cmd, expected_head=second['head'])
    assert db_state(r)[0]['positions']['BTCUSDT']['generation'] == 1


def test_short_position_buy_reduction(account):
    root, source, state = account
    position = paper.new_position(); paper.apply_fill(position, -2., 100., .12)
    position.update(current_price=101., last_mark_at=state['positions']['BTCUSDT']['last_mark_at'])
    state['positions']['BTCUSDT'] = position
    totals = paper.totals(state)
    with sqlite3.connect(source) as db:
        db.execute('UPDATE state SET payload=?', (json.dumps(state),))
        db.execute("UPDATE orders SET action='sell',quantity=-2,notional=-200")
        db.execute('UPDATE equity_history SET equity=?,pnl=?', (totals['equity'], totals['pnl']))
    r = review.__wrapped__(account)
    result = run(r); assert result['detail']['delta'] == 2 and result['detail']['quantity_after'] == 0


def test_command_cannot_predate_its_candidate_identity(review):
    cmd = copy.deepcopy(review['command'])
    cmd.update(issued_at='2026-09-28T12:59:00Z', expires_at='2026-09-28T13:00:00Z')
    with pytest.raises(p.Rejected, match='predates_candidate_epoch'):
        run(review, cmd, now='2026-09-28T12:59:00Z')
    assert not db_state(review)[1]


@pytest.mark.parametrize('change', [
    {'account': 'another'}, {'epoch_candidate': 'a'*64}, {'position_id': 'a'*64},
    {'generation': 2}, {'generation': True}, {'symbol': 'ETHUSDT'}, {'schema_version': True},
    {'command_id': 'bad'}, {'maximum_quantity_to_reduce': 3.}, {'maximum_quantity_to_reduce': -2.},
    {'maximum_quantity_to_reduce': 0.}, {'maximum_quantity_to_reduce': True},
    {'maximum_quantity_to_reduce': float('nan')}, {'maximum_quantity_to_reduce': float('inf')},
    {'issued_at': '2026-09-28T16:00:01Z'}, {'expires_at': NOW},
    {'expires_at': '2026-09-28T16:06:00Z'}, {'admin_uid': 30410},
])
def test_command_denied_without_claim_or_fill(review, change):
    cmd = copy.deepcopy(review['command']); cmd.update(change)
    with pytest.raises((p.Rejected, ValueError, TypeError)): run(review, cmd)
    assert db_state(review)[0] == review['executor'].initial and not db_state(review)[1]


@pytest.mark.parametrize('case', ['stale', 'future', 'crossed', 'depth', 'mark_missing', 'metadata_missing',
    'fee_missing', 'symbol', 'record_binding', 'scope', 'min_quantity', 'min_notional', 'fee_one', 'bad_step'])
def test_market_failure_burns_nonce_and_never_fills(review, case):
    r = review; value = synthetic_market(); q = value['quotes']['BTCUSDT']
    if case == 'stale': q['timestamp'] = '2026-09-28T14:00:00Z'
    elif case == 'future': q['timestamp'] = '2026-09-28T16:01:00Z'
    elif case == 'crossed': q['bids'][0]['price'] = 103.
    elif case == 'depth': q['bids'][0]['base_quantity'] = .1
    elif case == 'mark_missing': q['mark_timestamp'] = None
    elif case == 'metadata_missing': q['metadata_observed_at'] = None
    elif case == 'fee_missing': q['fee_rate'] = None
    elif case == 'symbol': q['symbol'] = 'ETHUSDT'
    elif case == 'record_binding': q['market_record_hash'] = 'a'*64
    elif case == 'scope': value['scope'] = 'KUCOIN_REAL'
    elif case == 'min_quantity': q['min_quantity'] = 0
    elif case == 'min_notional': q['min_notional'] = 0
    elif case == 'fee_one': q['fee_rate'] = 1
    elif case == 'bad_step': q['step'] = .3
    r['market_path'], r['market_hash'] = save_market(r['root'], value)
    cmd = copy.deepcopy(r['command'])
    if case == 'bad_step': cmd['maximum_quantity_to_reduce'] = .5
    with pytest.raises((p.Rejected, ValueError)): run(r, cmd)
    state, claims = db_state(r)
    assert state == r['executor'].initial and claims[0][2] == 'RESERVED'
    with pytest.raises(p.Rejected, match='replay'): run(r, cmd, expected_head=head_at(r))
    cmd['command_id'] = 'f'*64
    with pytest.raises(p.Rejected, match='uncertain_reservation'): run(r, cmd, expected_head=head_at(r))


def test_whole_close_does_not_infer_step_and_new_entry_still_denied(review):
    r = review; value = synthetic_market(); q = value['quotes']['BTCUSDT']; q['step'] = None
    r['market_path'], r['market_hash'] = save_market(r['root'], value)
    assert run(r)['detail']['quantity_after'] == 0
    q['step'] = q['quantity_step'] = .5; q['contract_multiplier'] = .5; q['price_tick'] = .1
    q['bids'][0]['price'] = 100.9; q['asks'][0]['price'] = 101.1
    with pytest.raises(sanity.Veto, match='missing_market_metadata'):
        sanity.preflight('BTCUSDT', q, 2, False)


@pytest.mark.parametrize('case', ['state', 'claim', 'event', 'schema', 'config', 'market_pin', 'symlink', 'hardlink'])
def test_storage_and_pin_tampering_denied(review, case):
    r = review
    if case == 'config':
        path = r['root']/'admin-review-config.json'; path.chmod(0o644); path.write_text('{}'); path.chmod(0o444)
    elif case == 'market_pin': r['market_hash'] = 'a'*64
    elif case == 'symlink':
        db = r['executor'].path; db.rename(r['root']/'actual.sqlite'); db.symlink_to(r['root']/'actual.sqlite')
    elif case == 'hardlink': os.link(r['executor'].path, r['root']/'alias.sqlite')
    else:
        with sqlite3.connect(r['executor'].path) as db:
            if case == 'state': db.execute("UPDATE review_state SET body='{}'")
            elif case == 'claim': db.execute("INSERT INTO review_claims VALUES ('x','{}','COMMITTED')")
            elif case == 'event': db.execute("INSERT INTO review_events VALUES (1,'{}','x')")
            else: db.execute('CREATE TABLE foreign_table(x)')
    with pytest.raises((p.Rejected, KeyError)): run(r)


@pytest.mark.parametrize('stage', ['before_reserve_commit', 'after_reserve_commit', 'before_fill_commit', 'after_fill_commit'])
def test_real_process_death_recovery_is_fail_closed(review, stage):
    r = review
    def child():
        def die(point, db):
            if point == stage:
                # Force SQLite dirty pages into a rollback journal before abrupt death.
                if point in ('before_reserve_commit', 'before_fill_commit'):
                    db.execute('PRAGMA cache_size=1')
                    db.execute("CREATE TABLE crash_padding(data)")
                    db.executemany('INSERT INTO crash_padding VALUES (?)', [(b'x'*2048,)]*100)
                os._exit(73)
        run(r, fault=die)
    process = multiprocessing.get_context('fork').Process(target=child)
    process.start(); process.join(5); assert process.exitcode == 73
    # Opening rw recovers actual hot rollback journals before validating schema.
    with sqlite3.connect(r['executor'].path) as db: assert db.execute('PRAGMA integrity_check').fetchone()[0] == 'ok'
    state, claims = db_state(r)
    if stage == 'before_reserve_commit':
        assert state == r['executor'].initial and not claims
        assert run(r)['status'] == 'SIMULATED_REVIEW_CLOSE'
    else:
        with pytest.raises(p.Rejected, match='external_review_head'): run(r)
        assert len(claims) == 1
        assert state['positions']['BTCUSDT']['quantity'] == (0 if stage == 'after_fill_commit' else 2)
        with pytest.raises(p.Rejected, match='replay'): run(r, expected_head=head_at(r))


def test_actual_sqlite_full_has_no_economic_commit(review):
    r = review
    with sqlite3.connect(r['executor'].path) as db:
        pages = db.execute('PRAGMA page_count').fetchone()[0]
    def full(stage, db):
        if stage == 'before_fill_commit':
            db.execute('PRAGMA max_page_count='+str(pages))
            db.execute('CREATE TABLE padding(data)')
            db.execute('INSERT INTO padding VALUES (?)', (b'x'*65536,))
    with pytest.raises(sqlite3.OperationalError, match='full'): run(r, fault=full)
    state, claims = db_state(r)
    assert state == r['executor'].initial and claims[0][2] == 'RESERVED'


def test_sync_failure_does_not_return_acceptance(review, monkeypatch):
    def fail(path): raise OSError('injected fsync failure')
    monkeypatch.setattr(a, '_fsync', fail)
    with pytest.raises(OSError, match='fsync'): run(review)
    state, claims = db_state(review)
    assert state == review['executor'].initial and claims[0][2] == 'RESERVED'


def test_sync_failure_after_sqlite_commit_is_uncertain_and_never_retried(review, monkeypatch):
    real = a._fsync; count = 0
    def fail_after_fill(path):
        nonlocal count
        count += 1
        if count == 3: raise OSError('injected sync after fill commit')
        real(path)
    monkeypatch.setattr(a, '_fsync', fail_after_fill)
    with pytest.raises(OSError, match='after fill'): run(review)
    state, claims = db_state(review)
    assert state['positions']['BTCUSDT']['quantity'] == 0 and claims[0][2] == 'COMMITTED'
    with pytest.raises(p.Rejected, match='external_review_head'): run(review)
    with pytest.raises(p.Rejected, match='replay'): run(review, expected_head=head_at(review))


@pytest.mark.parametrize('stage', ['after_reserve_commit', 'before_fill_commit'])
def test_expiry_during_processing_does_not_fill(review, stage):
    current = NOW
    def expire(point, db):
        nonlocal current
        if point == stage: current = '2026-09-28T16:01:00Z'
    with pytest.raises(p.Rejected, match='expired'):
        run(review, clock=lambda: current, fault=expire)
    state, claims = db_state(review)
    assert state == review['executor'].initial and claims[0][2] == 'RESERVED'


def test_read_only_review_db_denied_before_reservation(review):
    review['executor'].path.chmod(0o444)
    with pytest.raises(p.Rejected, match='executor_private_file'): run(review)
    assert not db_state(review)[1]


def test_wrong_primary_group_cannot_reach_local_channel(review):
    directory = Path(tempfile.mkdtemp(prefix='v13-close-group-')); directory.chmod(0o750)
    path = directory/'unserved.sock'
    try:
        with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as server:
            server.bind(str(path)); path.chmod(0o660); server.listen(1)
            def client():
                with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as client:
                    client.connect(str(path))
            denied = _as_uid(30410, 30499, client)
            assert denied[0] == 'error' and denied[1] == 'PermissionError', denied
        assert not db_state(review)[1]
    finally: shutil.rmtree(directory)


def test_coherent_old_restore_denied_by_external_pin(review):
    r = review; old = r['executor'].path.read_bytes()
    result = run(r); r['executor'].path.write_bytes(old)
    with pytest.raises(p.Rejected, match='external_review_head'): run(r, expected_head=result['head'])
    # Restoring the external witness too is outside this protection; never claim otherwise.


def test_concurrent_executor_lock_denies(review):
    import fcntl
    lock = review['root']/'admin-review.lock'; lock.touch(mode=0o600)
    with lock.open('rb+') as stream:
        fcntl.flock(stream, fcntl.LOCK_EX | fcntl.LOCK_NB)
        with pytest.raises(BlockingIOError): run(review)
    assert not db_state(review)[1]


@pytest.mark.parametrize('uid,gid,spoof', [(30410,0,False), (30430,0,False), (30410,0,True)])
def test_real_socket_peer_authentication_and_payload_spoof(review, uid, gid, spoof):
    r = review; directory = Path(tempfile.mkdtemp(prefix='v13-close-peer-')); directory.chmod(0o750)
    command = copy.deepcopy(r['command'])
    if spoof: command['admin_uid'] = 30410
    sender, receiver = multiprocessing.Pipe()
    def server():
        try:
            result = r['executor'].handle_one(directory, market_path=r['market_path'],
                expected_market_hash=r['market_hash'], expected_head=r['head'], clock=lambda: NOW,
                ready=lambda: sender.send('ready'))
            sender.send(result)
        except BaseException as error: sender.send({'error': str(error)})
    proc = multiprocessing.get_context('fork').Process(target=server); proc.start()
    try:
        assert receiver.poll(5) and receiver.recv() == 'ready'
        def client():
            with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as connection:
                connection.connect(str(directory/'review-close.sock'))
                if uid == 30410: connection.sendall(p.canonical_bytes(command)+b'\n')
                raw = bytearray()
                while not raw.endswith(b'\n'): raw.extend(connection.recv(4096))
                return p.read_json(bytes(raw))
        response = _as_uid(uid, gid, client)
        assert response[0] == 'ok', response
        result = response[1]
        if uid == 30430: assert result['reason'] == 'admin_peer_denied'
        elif spoof: assert result['reason'] == 'admin_command_schema_invalid'
        else: assert result['status'] == 'SIMULATED_REVIEW_CLOSE'
        assert receiver.poll(5); receiver.recv(); proc.join(5); assert proc.exitcode == 0
    finally:
        if proc.is_alive(): proc.terminate(); proc.join(5)
        shutil.rmtree(directory)


def test_actual_nonroot_executor_and_admin_cannot_write_ledger(review):
    r = review; root = r['root']
    for parent in root.parents:
        if str(parent) == '/tmp': break
        parent.chmod(0o755)
    manifest = p.read_json((root/'candidate/manifest.json').read_bytes())
    pin = configure(root, manifest, executor_uid=30420, executor_gid=0)
    (root/'admin-review.sqlite').unlink()
    config = root/'admin-review-config.json'
    for file in sorted(root.rglob('*'), key=lambda path: len(path.parts), reverse=True):
        if file != config: os.chown(file, 30420, 0)
    os.chown(root, 30420, 0)
    def execute():
        ex = a.ReviewExecutor(root, expected_config_hash=pin); head = ex.initialize()
        return ex._execute(r['command'], market_path=r['market_path'], expected_market_hash=r['market_hash'], expected_head=head, now=NOW)
    try:
        result = _as_uid(30420, 0, execute)
        assert result[0] == 'ok' and result[1]['status'] == 'SIMULATED_REVIEW_CLOSE', result
        def read_ledger(): return (root/'admin-review.sqlite').read_bytes()
        for uid in (30410, 30430):
            denied = _as_uid(uid, 0, read_ledger)
            assert denied[0] == 'error' and denied[1] == 'PermissionError', denied
    finally:
        os.chown(root, 0, 0)
        for file in root.rglob('*'): os.chown(file, 0, 0)
