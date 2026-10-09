"""Internal offline tests: work-card-9cd8bbf3-98ce-4ac4-9b7c-37023da105a3.

Synthetic streams/status/clocks only. No HTTP acquisition or issuer/executor.
"""
from contextlib import closing
import copy
import datetime as dt
import multiprocessing
import os
from pathlib import Path
import sqlite3

import pytest

from octobot.ai_strategy_lab import v13_capture_receipt_review as r
from octobot.ai_strategy_lab import v13_original_portfolio as p
from octobot.ai_strategy_lab import v13_causal_publication_fixture as storage
from tests.unit_tests.ai_strategy_lab.test_v13_causal_publication_fixture import _as_uid

START = '2026-09-28T18:00:00Z'
CHECK = '2026-09-28T19:00:00Z'


def clock(c, *, seconds=0, samples=None):
    number = seconds
    def sample():
        nonlocal number
        if samples is not None: return samples.pop(0)
        instant = p.timestamp(START)+dt.timedelta(seconds=number)
        number += 1
        return {'utc': instant.isoformat(), 'monotonic_ns': number*1000000000,
                'clock_evidence_ref': c['clock_evidence_ref']}
    return sample


@pytest.fixture
def review(tmp_path):
    root = tmp_path/'review'
    pin = r.init_review(root, uids={role: 0 for role in r.ROLES}, fixture_started_at=START)
    return {'root': root, 'pin': pin, 'config': p.read_json((root/'config.json').read_bytes())}


def capture(a, *, nonce='a'*64, key='scientific_daily:BTCUSDT', raw=b'[[1,2,3,4,5,6]]', **kw):
    args = {'expected_config_hash': a['pin'], 'fixture_chunks': [raw], 'http_status': 200,
        'declared_length': len(raw), 'clock': clock(a['config'])}; args.update(kw)
    return r.capture(a['root'], nonce, key, **args)


def attest(a, captured, *, head=None, **kw):
    args = {'expected_config_hash': a['pin'], 'expected_capture_hash': captured['capture_hash'],
        'expected_witness_head': head, 'clock': clock(a['config'], seconds=10)}; args.update(kw)
    return r.attest(a['root'], captured['capture_id'], **args)


def dependency(captured, attested, *, head=None):
    return {'ident': captured['capture_id'], 'expected_capture_hash': captured['capture_hash'],
        'expected_ack_hash': attested['ack_hash'], 'expected_witness_head': head or attested['event_hash']}


def verify(a, captured, attested, **kw):
    args = {'checked_at': CHECK, **dependency(captured, attested)}; args.update(kw)
    return r.verify_dependency(a['root'], expected_config_hash=a['pin'], **args)


def current_head(a):
    with closing(r._db(a['root'], a['config'])) as db: return storage._head(db)


def test_stream_timestamps_sampled_during_consumption_and_ack_after_commit(review):
    a = review; stages = []
    def chunks():
        stages.append('first'); yield b'[[1,'
        stages.append('second'); yield b'2]]'
    times = clock(a['config'])
    def measured():
        stages.append('clock'); return times()
    cap = capture(a, raw=b'[[1,2]]', fixture_chunks=chunks(), clock=measured)
    assert stages == ['clock','first','clock','second','clock','clock']
    receipt, raw = r._capture(a['root'], cap['capture_id'], a['config'])
    assert raw == b'[[1,2]]' and receipt['request_started']['utc'] < receipt['response_completed']['utc']
    assert receipt['receipt_committed_at'] is None
    def witness_clock():
        assert current_head(a) is not None
        return clock(a['config'], seconds=10)()
    ack = attest(a, cap, clock=witness_clock)
    result = verify(a, cap, ack)
    assert result['response_framing_valid_fixture'] is True
    assert result['receipt_sequence'] == 1 and result['previous_receipt_hash'] is None
    assert result['source_available_at_operational'] is None and result['historical_availability'] == 'UNRESOLVED'
    assert ack['ack']['own_ack_commit_time_known'] is False
    assert result['readiness'] == 'BLOCKED' and result['issuable'] is False
    assert receipt['actual_http_request_performed'] is False


@pytest.mark.parametrize('case', ['missing_chunk','timeout','empty_chunk','nonbytes','overlength','oversize_length',
    'bool_length','bool_status','status_out_of_range','url_instead_of_key','nonce_invalid'])
def test_invalid_or_incomplete_capture_never_attested(review, case):
    a = review; kwargs = {}; nonce = 'a'*64; key = 'scientific_daily:BTCUSDT'
    if case == 'missing_chunk': kwargs['declared_length'] = 999
    elif case == 'timeout':
        def partial(): yield b'['; raise TimeoutError('fixture timeout')
        kwargs['fixture_chunks'] = partial()
    elif case == 'empty_chunk': kwargs['fixture_chunks'] = [b'']
    elif case == 'nonbytes': kwargs['fixture_chunks'] = ['plaintext']
    elif case == 'overlength': kwargs['declared_length'] = 1
    elif case == 'oversize_length': kwargs['declared_length'] = r.MAX_RAW+1
    elif case == 'bool_length': kwargs['declared_length'] = True
    elif case == 'bool_status': kwargs['http_status'] = True
    elif case == 'status_out_of_range': kwargs['http_status'] = 999
    elif case == 'url_instead_of_key': key = 'https://another.invalid/?secret=foo'
    elif case == 'nonce_invalid': nonce = 'not-a-hash'
    with pytest.raises((p.Rejected, TimeoutError)): capture(a, nonce=nonce, key=key, **kwargs)
    assert not list((a['root']/'custodian').glob('*/capture.json'))
    assert not (a['root']/'witness/witness.sqlite').exists()


@pytest.mark.parametrize('case', ['wall_reverse','mono_reverse','missing_evidence','negative_mono','bool_mono','before_epoch'])
def test_custodian_clock_invalid_denies_complete_receipt(review, case):
    a = review; timer = clock(a['config']); samples = [timer(),timer(),timer()]
    if case == 'wall_reverse': samples[1]['utc'] = '2026-09-28T17:59:59Z'
    elif case == 'mono_reverse': samples[1]['monotonic_ns'] = 0
    elif case == 'missing_evidence': samples[1]['clock_evidence_ref'] = 'b'*64
    elif case == 'negative_mono': samples[1]['monotonic_ns'] = -1
    elif case == 'bool_mono': samples[1]['monotonic_ns'] = True
    elif case == 'before_epoch': samples[0]['utc'] = '2026-09-28T17:59:59Z'
    with pytest.raises(p.Rejected): capture(a, clock=clock(a['config'], samples=samples))
    assert not list((a['root']/'custodian').glob('*/capture.json'))


@pytest.mark.parametrize('raw,status,reason', [
    (b'{"code":"200000","data":[]}',429,'http_status_invalid'),
    (b'{"code":"500000"}',200,'application_status_invalid'),
    (b'{"code":"200000","code":"200000"}',200,'invalid_json_response'),
    (b'{"value":NaN}',200,'invalid_json_response'),
    (b'not-json',200,'invalid_json_response'),
])
def test_failed_responses_retained_for_forensics_but_not_consumption(review, raw, status, reason):
    a = review; cap = capture(a, key='execution_contracts', raw=raw, http_status=status)
    ack = attest(a, cap); result = verify(a, cap, ack)
    assert result['response_framing_valid_fixture'] is False and result['response_denial_reason'] == reason
    assert r._capture(a['root'], cap['capture_id'], a['config'])[1] == raw
    assert result['execution_approved'] is False


def test_capture_nonce_reuse_and_ack_restart_preserve_first_observation(review):
    a = review; cap = capture(a); ack = attest(a, cap)
    with pytest.raises(FileExistsError): capture(a)
    def should_not_sample(): raise AssertionError('replay must retain first clock')
    repeated = attest(a, cap, head=ack['event_hash'], clock=should_not_sample)
    assert repeated == ack
    assert verify(a, cap, ack)['receipt_sequence'] == 1
    another = capture(a, nonce='b'*64)
    next_ack = attest(a, another, head=ack['event_hash'], clock=clock(a['config'], seconds=20))
    first = verify(a, cap, ack, expected_witness_head=next_ack['event_hash'])
    assert first['receipt_committed_observed_at_fixture'] == ack['ack']['post_commit_observed']['utc']
    assert verify(a, another, next_ack)['receipt_sequence'] == 2


def test_nonce_cannot_be_reused_for_different_request(review):
    a = review; cap = capture(a); ack = attest(a, cap)
    conflict = capture(a, key='execution_book:BTCUSDT', raw=b'{"code":"200000","data":{}}')
    with pytest.raises(p.Rejected, match='nonce_conflict'): attest(a, conflict, head=ack['event_hash'])


@pytest.mark.parametrize('case', ['raw','capture','ack','witness','config','capture_pin','ack_pin','head_pin','symlink','hardlink'])
def test_tamper_or_external_pins_deny(review, case):
    a = review; cap = capture(a); ack = attest(a, cap); options = {}
    base = a['root']/'custodian'/cap['capture_id']; ackpath = a['root']/'witness'/(cap['capture_id']+'-capture.json')
    if case in ('raw','capture','ack','config'):
        path = {'raw':base/'raw.bin','capture':base/'capture.json','ack':ackpath,'config':a['root']/'config.json'}[case]
        path.chmod(0o644); path.write_bytes(b'{}'); path.chmod(0o444)
    elif case == 'witness':
        with sqlite3.connect(a['root']/'witness/witness.sqlite') as db: db.execute("UPDATE attestations SET payload='{}'")
    elif case == 'capture_pin': options['expected_capture_hash'] = 'f'*64
    elif case == 'ack_pin': options['expected_ack_hash'] = 'f'*64
    elif case == 'head_pin': options['expected_witness_head'] = 'f'*64
    elif case == 'symlink':
        path = base/'raw.bin'; path.rename(base/'real.bin'); path.symlink_to(base/'real.bin')
    elif case == 'hardlink': os.link(base/'raw.bin',base/'linked.bin')
    with pytest.raises((p.Rejected, KeyError)): verify(a, cap, ack, **options)


@pytest.mark.parametrize('stage', ['received_chunk','after_raw_fsync','after_capture_fsync'])
def test_actual_capture_process_death_never_self_publishes_availability(review, stage):
    a = review
    def die(point):
        if point == stage: os._exit(73)
    process = multiprocessing.get_context('fork').Process(target=lambda:capture(a,fault=die))
    process.start();process.join(5);assert process.exitcode==73
    assert not list((a['root']/'witness').iterdir())
    if stage != 'after_capture_fsync': assert not list((a['root']/'custodian').glob('*/capture.json'))
    else:
        # Explicit separate witness recovery, never time of the dead writer's future sync.
        ident = next((a['root']/'custodian').iterdir()).name
        receipt, _ = r._capture(a['root'], ident, a['config'])
        cap = {'capture_id':ident,'capture_hash':p.digest(receipt)}
        assert verify(a, cap, attest(a,cap))['source_available_at_operational'] is None


@pytest.mark.parametrize('stage', ['before_witness_commit','after_witness_commit','after_ack_fsync'])
def test_actual_witness_process_death_requires_explicit_pin_reconciliation(review, stage):
    a = review; cap = capture(a)
    def die(point, db):
        if point == stage:
            if point == 'before_witness_commit':
                db.execute('PRAGMA cache_size=1');db.execute('CREATE TABLE padding(x)')
                db.executemany('INSERT INTO padding VALUES (?)',[(b'x'*2048,)]*100)
            os._exit(74)
    process = multiprocessing.get_context('fork').Process(target=lambda:attest(a,cap,fault=die))
    process.start();process.join(5);assert process.exitcode==74
    # Recover a real hot journal as the sole writer, before RO reads.
    with closing(r._db(a['root'],a['config'],write=True)): pass
    head = current_head(a)
    if stage == 'before_witness_commit':
        assert head is None; ack = attest(a,cap)
    else:
        with pytest.raises(p.Rejected,match='external_witness_head'):attest(a,cap)
        # Diagnostic reconciliation in the test, not an installed external witness.
        ack = attest(a,cap,head=head)
    assert verify(a,cap,ack)['readiness']=='BLOCKED'


def test_real_sqlite_full_leaves_no_confirmed_receipt(review):
    a=review;cap=capture(a)
    def full(stage,db):
        if stage=='before_witness_commit':
            pages=db.execute('PRAGMA page_count').fetchone()[0];db.execute('PRAGMA max_page_count='+str(pages))
            db.execute('CREATE TABLE padding(x)');db.execute('INSERT INTO padding VALUES (?)',(b'x'*65536,))
    with pytest.raises(sqlite3.OperationalError,match='full'):attest(a,cap,fault=full)
    assert current_head(a) is None and not list((a['root']/'witness').glob('*-capture.json'))


@pytest.mark.parametrize('point', ['raw','ack'])
def test_fsync_error_returns_no_ack_or_availability(review, monkeypatch, point):
    a=review
    if point=='raw':
        def fail(fd):raise OSError('injected raw fsync')
        monkeypatch.setattr(os,'fsync',fail)
        with pytest.raises(OSError):capture(a)
        assert not list((a['root']/'custodian').glob('*/capture.json'))
    else:
        cap=capture(a);real=storage._write
        def fail(path,raw):
            real(path,raw)
            if path.name.endswith('-capture.json'):raise OSError('injected ack sync')
        monkeypatch.setattr(storage,'_write',fail)
        with pytest.raises(OSError):attest(a,cap)
        assert current_head(a) is not None and not list((a['root']/'witness').glob('*-capture.json'))


def test_witness_regression_and_check_before_confirmation_denied(review):
    a=review;cap=capture(a)
    with pytest.raises(p.Rejected,match='clock_regression'):attest(a,cap,clock=clock(a['config']))
    ack=attest(a,cap,head=current_head(a))
    with pytest.raises(p.Rejected,match='not_available'):verify(a,cap,ack,checked_at=START)


def test_coherent_old_restore_denied_when_external_head_retained(review):
    a=review;first=capture(a);ack=attest(a,first);path=a['root']/'witness/witness.sqlite';old=path.read_bytes()
    second=capture(a,nonce='b'*64);next_ack=attest(a,second,head=ack['event_hash'],clock=clock(a['config'],seconds=20))
    path.write_bytes(old)
    with pytest.raises(p.Rejected,match='external_witness_head'):verify(a,first,ack,expected_witness_head=next_ack['event_hash'])


def contract_raw(c):
    return p.canonical_bytes({'code':'200000','data':[{'symbol':m['exchange_symbol'],'quoteCurrency':'USDT',
        'settleCurrency':'USDT','markPrice':100,'lotSize':1,'multiplier':.001,'minRiskLimit':100} for m in c['mapping']]})


def book_raw():
    return p.canonical_bytes({'code':'200000','data':{'timestamp':int(p.timestamp(START).timestamp()*1000),
        'bids':[['99',100]],'asks':[['101',100]]}})


def test_unknown_mark_and_minima_preserved_and_scientific_source_separate(review):
    a=review;contracts=capture(a,key='execution_contracts',raw=contract_raw(a['config']));ca=attest(a,contracts)
    book=capture(a,nonce='b'*64,key='execution_book:BTCUSDT',raw=book_raw());ba=attest(a,book,head=ca['event_hash'],clock=clock(a['config'],seconds=20))
    kwargs={'expected_config_hash':a['pin'],'contract_dependency':dependency(contracts,ca,head=ba['event_hash']),
        'book_dependency':dependency(book,ba),'checked_at':CHECK}
    view=r.execution_view(a['root'],'BTCUSDT',**kwargs)
    assert view['mark']['measurement_timestamp'] is None and view['mark']['measurement_timestamp_status']=='UNKNOWN'
    assert view['book']['measurement_timestamp_ms']>0 and view['minimums']=={'min_quantity':None,'min_notional':None,'status':'UNKNOWN'}
    assert view['mapping']['exchange_symbol']=='XBTUSDTM' and view['execution_gate']=='DENY_MARK_TIMESTAMP_UNKNOWN'
    assert len(a['config']['mapping'])==18
    assert len(a['config']['requests'])==55
    assert a['config']['requests']['scientific_daily:BTCUSDT']['purpose']=='SCIENTIFIC_BINANCE'
    assert a['config']['requests']['scientific_funding:BTCUSDT']['kind']=='settled_funding'
    assert a['config']['requests']['execution_book:BTCUSDT']['purpose']=='EXECUTION_KUCOIN'
    kwargs['contract_dependency']=kwargs['book_dependency']
    with pytest.raises(p.Rejected,match='purpose'):r.execution_view(a['root'],'BTCUSDT',**kwargs)
    with pytest.raises(p.Rejected,match='foreign'):r.execution_view(a['root'],'PEPEUSDT',**kwargs)


@pytest.mark.parametrize('case', ['metadata_shape','missing_mapping','duplicate_mapping','currency','book_future','book_unknown','book_identity'])
def test_invalid_field_provenance_cannot_become_execution_view(review, case):
    a=review;metadata=p.read_json(contract_raw(a['config']));book=p.read_json(book_raw())
    if case=='metadata_shape':metadata['data']=[42]
    elif case=='missing_mapping':metadata['data']=[row for row in metadata['data'] if row['symbol']!='XBTUSDTM']
    elif case=='duplicate_mapping':metadata['data'].append(next(row for row in metadata['data'] if row['symbol']=='XBTUSDTM'))
    elif case=='currency':next(row for row in metadata['data'] if row['symbol']=='XBTUSDTM')['settleCurrency']='BTC'
    elif case=='book_future':book['data']['timestamp']=int(p.timestamp(CHECK).timestamp()*1000)
    elif case=='book_unknown':book['data']['timestamp']=None
    elif case=='book_identity':book['data']['symbol']='ETHUSDTM'
    contracts=capture(a,key='execution_contracts',raw=p.canonical_bytes(metadata));ca=attest(a,contracts)
    captured=capture(a,nonce='b'*64,key='execution_book:BTCUSDT',raw=p.canonical_bytes(book));ba=attest(a,captured,head=ca['event_hash'],clock=clock(a['config'],seconds=20))
    with pytest.raises(p.Rejected):
        r.execution_view(a['root'],'BTCUSDT',expected_config_hash=a['pin'],contract_dependency=dependency(contracts,ca,head=ba['event_hash']),book_dependency=dependency(captured,ba),checked_at=CHECK)


def test_capture_receipt_cannot_gain_new_authority_fields(review):
    a=review;cap=capture(a);path=a['root']/'custodian'/cap['capture_id']/'capture.json'
    value=p.read_json(path.read_bytes());value['approved']=True
    path.chmod(0o644);path.write_bytes(p.canonical_bytes(value));path.chmod(0o444)
    with pytest.raises(p.Rejected,match='schema_invalid'):attest(a,cap)


def test_actual_distinct_fixture_uids_cannot_write_other_custodies(tmp_path):
    for ancestor in [tmp_path,*tmp_path.parents]:
        if ancestor==Path('/tmp') or ancestor==Path('/'):break
        ancestor.chmod(0o755)
    root=tmp_path/'separated';uids=dict(zip(r.ROLES,[30610,30620,30630,30640]))
    pin=r.init_review(root,uids=uids,fixture_started_at=START)
    a={'root':root,'pin':pin,'config':p.read_json((root/'config.json').read_bytes())}
    got=_as_uid(uids['custodian'],lambda:capture(a));assert got[0]=='ok',got;cap=got[1]
    got=_as_uid(uids['witness'],lambda:attest(a,cap));assert got[0]=='ok',got;ack=got[1]
    got=_as_uid(uids['verifier'],lambda:verify(a,cap,ack));assert got[0]=='ok',got
    assert got[1]['fixture_uids_distinct'] is True and got[1]['independent_custody_operational'] is False
    for uid in (uids['strategy'],uids['verifier']):
        denied=_as_uid(uid,lambda:capture(a,nonce='b'*64))
        assert denied[0]=='error' and denied[2]=='wrong_capture_role'
    trusted=[root/'config.json',root/'custodian'/cap['capture_id']/'raw.bin',root/'witness/witness.sqlite']
    for path in trusted:
        denied=_as_uid(uids['strategy'],lambda:path.write_bytes(b'corruption'))
        assert denied[0]=='error' and denied[1]=='PermissionError',denied
    assert not list(root.rglob('approvals.sqlite')) and not list(root.rglob('execution.sqlite'))
