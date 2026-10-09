"""Offline fixture tests. Card work-card-781b1be7-dab1-4695-b323-5b3db9d5fe67.

No live capture, exchange credentials, orders or operational identities.
"""
import copy
import hashlib
import json
import multiprocessing
import os
from pathlib import Path
import shutil
import sqlite3

import pytest
from octobot.ai_strategy_lab import v13_causal_publication_fixture as f
from octobot.ai_strategy_lab import v13_original_portfolio as p

REPO = Path(__file__).resolve().parents[3]
PUB_TIME = '2026-09-28T00:11:00Z'
DER_TIME = '2026-09-28T00:12:00Z'
CHECK_TIME = '2026-09-28T00:13:00Z'


def fixture_raw(config):
    symbols = {}
    for item in config['mapping']:
        symbols[item['symbol']] = {
            'research_symbol': item['research_symbol'], 'exchange_symbol': item['exchange_symbol'],
            'mark_unit': 'USDT_per_base', 'quantity_unit': 'base',
            'daily': [{'closed_at': '2026-09-27T00:00:00Z', 'close': 99},
                      {'closed_at': '2026-09-28T00:00:00Z', 'close': 100}],
            'settled_funding': [{'timestamp_ms': 1790553600000, 'rate': -.001}],
            'mark': {'measurement_at': '2026-09-28T00:09:00Z',
                     'received_at': '2026-09-28T00:09:15Z', 'price': 100},
            'book': {'measurement_at': '2026-09-28T00:09:05Z', 'bids': [[99, 2]], 'asks': [[101, 2]]},
            'min_quantity': None, 'min_notional': None}
    return {'scope': f.SCOPE, 'schema_version': 1, 'account': config['account'],
        'fixture_epoch': config['fixture_epoch'], 'clock_id': config['clock_id'],
        'credentials_used': False, 'research_only': True, 'orders_authorized': False,
        'paper_orders_authorized': False, 'cutoff_at': '2026-09-28T00:10:00Z',
        'request_started_at': '2026-09-28T00:08:00Z', 'response_completed_at': '2026-09-28T00:09:30Z',
        'source_bar_date': '2026-09-27', 'symbols': symbols}


def setup(tmp, *, uids=None):
    root = tmp/'fixture'
    pin = f.init_fixture(root, REPO, uids=uids or {role: os.geteuid() for role in f.ROLES})
    config = p.read_json((root/'config.json').read_bytes())
    return root, pin, config


def source(root, raw, name='raw.json'):
    path = root/'strategy'/name
    if path.exists(): path.chmod(0o644)
    path.write_bytes(p.canonical_bytes(raw)); path.chmod(0o444)
    return path, hashlib.sha256(path.read_bytes()).hexdigest()


def publish(root, pin, config, raw=None, **kw):
    path, digest = source(root, raw or fixture_raw(config))
    return f.publish(root, path, expected_config_hash=pin, expected_raw_hash=digest, **kw)


def finish(root, pin, pub):
    ident = pub['publication_id']
    a = f.attest(root, ident, stage='publication', expected_config_hash=pin, clock=lambda: PUB_TIME)
    receipt = f.derive(root, ident, expected_config_hash=pin, expected_publication_ack_hash=a['ack_hash'])
    b = f.attest(root, ident, stage='derivation', expected_config_hash=pin, clock=lambda: DER_TIME)
    return a, b, receipt


def verify(root, pin, pub, a, b, **kw):
    args = {'expected_config_hash': pin, 'expected_publication_ack_hash': a['ack_hash'],
        'expected_derivation_ack_hash': b['ack_hash'], 'expected_witness_head': b['event_hash'], 'checked_at': CHECK_TIME}
    args.update(kw)
    return f.verify(root, pub['publication_id'], **args)


def test_positive_only_normalizes_fixture_inputs(tmp_path):
    root, pin, config = setup(tmp_path)
    pub = publish(root, pin, config); a,b,_ = finish(root,pin,pub)
    result = verify(root,pin,pub,a,b)
    assert result['scope'] == f.SCOPE
    assert result['source_available_at_fixture'] == '2026-09-28T00:12:00+00:00'
    assert result['source_available_at_operational'] is None
    for key in ('issuable','execution_approved','kucoin_order_admissibility_proven',
                'original_v13_strategy_recomputed','independent_custody_verified_operational'):
        assert result[key] is False
    assert result['readiness'] == 'BLOCKED'
    assert len(p.read_json((root/'publisher'/pub['publication_id']/'inputs.json').read_bytes())['symbols']) == 18
    assert p.issuance_status(REPO)['issuable'] is False


def test_unused_future_bytes_do_not_change_causal_identity(tmp_path):
    root,pin,config = setup(tmp_path)
    raw = fixture_raw(config); first = publish(root,pin,config,raw)
    changed = copy.deepcopy(raw)
    for value in changed['symbols'].values():
        value['daily'].append({'closed_at':'2026-09-29T00:00:00Z','close':1e100})
        value['settled_funding'].append({'timestamp_ms':1790640000000,'rate':-100})
    path,digest = source(root,changed,'future.json')
    second = f.publish(root,path,expected_config_hash=pin,expected_raw_hash=digest)
    assert first['snapshot_id'] == second['snapshot_id']
    assert first['publication_id'] != second['publication_id']
    one = p.read_json((root/'publisher'/first['publication_id']/'manifest.json').read_bytes())
    two = p.read_json((root/'publisher'/second['publication_id']/'manifest.json').read_bytes())
    assert one['causal_input_hash'] == two['causal_input_hash']
    assert one['raw_sha256'] != two['raw_sha256']
    f.attest(root,first['publication_id'],stage='publication',expected_config_hash=pin,clock=lambda:PUB_TIME)
    with pytest.raises(p.Rejected,match='slot_or_receipt_conflict'):
        f.attest(root,second['publication_id'],stage='publication',expected_config_hash=pin,clock=lambda:PUB_TIME)


@pytest.mark.parametrize('case', ['missing','foreign','mapping','account','epoch','clock','research',
    'orders','credentials','late_response','bad_request','unclosed_bar','no_bars','conflicting_close',
    'equivalent_time_conflict','funding_conflict','mark_unknown','mark_future','mark_stale','mark_price',
    'book_future','book_stale','skew','depth_empty','crossed','units','minimum_quantity','minimum_notional',
    'schema_bool','schema_float'])
def test_adversarial_raw_denied_before_publication(tmp_path,case):
    root,pin,config = setup(tmp_path); raw = fixture_raw(config); v = raw['symbols']['BTCUSDT']
    if case == 'missing': raw['symbols'].pop('ETHUSDT')
    elif case == 'foreign': raw['symbols']['PEPEUSDT'] = copy.deepcopy(v)
    elif case == 'mapping': v['exchange_symbol'] = 'BTCUSDTM'
    elif case == 'account': raw['account'] = 'another-account'
    elif case == 'epoch': raw['fixture_epoch'] = 'b'*64
    elif case == 'clock': raw['clock_id'] = 'unattested'
    elif case == 'research': raw['research_only'] = False
    elif case == 'orders': raw['paper_orders_authorized'] = True
    elif case == 'credentials': raw['credentials_used'] = True
    elif case == 'late_response': raw['response_completed_at'] = '2026-09-28T00:11:00Z'
    elif case == 'bad_request': raw['request_started_at'] = '2026-09-28T00:10:00Z'
    elif case == 'unclosed_bar': raw['source_bar_date'] = '2026-09-28'
    elif case == 'no_bars': v['daily'] = []
    elif case == 'conflicting_close': v['daily'].append({'closed_at':'2026-09-28T00:00:00Z','close':102})
    elif case == 'equivalent_time_conflict': v['daily'].append({'closed_at':'2026-09-28T00:00:00+00:00','close':102})
    elif case == 'funding_conflict': v['settled_funding'].append({'timestamp_ms':1790553600000,'rate':.001})
    elif case == 'mark_unknown': v['mark']['measurement_at'] = None
    elif case == 'mark_future': v['mark']['measurement_at'] = '2026-09-28T00:10:01Z'
    elif case == 'mark_stale': v['mark']['measurement_at'] = '2026-09-27T23:59:59Z'
    elif case == 'mark_price': v['mark']['price'] = 0
    elif case == 'book_future': v['book']['measurement_at'] = '2026-09-28T00:11:00Z'
    elif case == 'book_stale': v['book']['measurement_at'] = '2026-09-27T23:59:59Z'
    elif case == 'skew': v['mark']['measurement_at'] = '2026-09-28T00:07:00Z'
    elif case == 'depth_empty': v['book']['bids'] = []
    elif case == 'crossed': v['book']['bids'] = [[101,2]]
    elif case == 'units': v['quantity_unit'] = 'contracts'
    elif case == 'minimum_quantity': v['min_quantity'] = 0
    elif case == 'minimum_notional': v['min_notional'] = 1
    elif case == 'schema_bool': raw['schema_version'] = True
    elif case == 'schema_float': raw['schema_version'] = 1.0
    with pytest.raises(p.Rejected): publish(root,pin,config,raw)
    assert list((root/'publisher').iterdir()) == []
    assert not (root/'witness'/'witness.sqlite').exists()


def test_duplicate_identical_is_deduplicated_but_raw_json_conflict_denied(tmp_path):
    root,pin,config = setup(tmp_path); raw = fixture_raw(config)
    before = f.normalize(p.canonical_bytes(raw),config)[1]
    v = raw['symbols']['BTCUSDT']; v['settled_funding'] *= 2; v['daily'] *= 2
    assert f.normalize(p.canonical_bytes(raw),config)[1] == before
    conflicting = p.canonical_bytes(raw).replace(b'"schema_version":1',b'"schema_version":1,"schema_version":2')
    with pytest.raises(p.Rejected): f.normalize(conflicting,config)
    nonfinite = p.canonical_bytes(raw).replace(b'"price":100',b'"price":NaN')
    with pytest.raises(p.Rejected): f.normalize(nonfinite,config)


@pytest.mark.parametrize('name',['raw.json','inputs.json','manifest.json'])
def test_partial_publish_restart_and_tamper(tmp_path,name):
    root,pin,config = setup(tmp_path)
    def fail(stage):
        if stage == name: raise OSError('storage failure')
    with pytest.raises(OSError): publish(root,pin,config,_fault=fail)
    assert not (root/'witness'/'witness.sqlite').exists()
    pub = publish(root,pin,config); a,b,_ = finish(root,pin,pub)
    assert verify(root,pin,pub,a,b)['issuable'] is False
    target = root/'publisher'/pub['publication_id']/name
    target.chmod(0o644); target.write_bytes(b'{}'); target.chmod(0o444)
    with pytest.raises((p.Rejected,KeyError)): verify(root,pin,pub,a,b)


@pytest.mark.parametrize('field',['expected_config_hash','expected_publication_ack_hash',
                                 'expected_derivation_ack_hash','expected_witness_head','checked_at'])
def test_external_pins_and_availability(tmp_path,field):
    root,pin,config = setup(tmp_path); pub = publish(root,pin,config); a,b,_ = finish(root,pin,pub)
    wrong = '2026-09-28T00:11:59Z' if field == 'checked_at' else '0'*64
    with pytest.raises(p.Rejected): verify(root,pin,pub,a,b,**{field:wrong})


def test_replay_keeps_two_events_and_same_receipt(tmp_path):
    root,pin,config = setup(tmp_path); pub = publish(root,pin,config); a,b,r = finish(root,pin,pub)
    a2,b2,r2 = finish(root,pin,pub)
    assert (a,b,r) == (a2,b2,r2)
    with sqlite3.connect(root/'witness'/'witness.sqlite') as db:
        assert db.execute('SELECT count(*) FROM attestations').fetchone()[0] == 2
        assert db.execute('PRAGMA integrity_check').fetchone()[0] == 'ok'


def _kill_at(root,pin,pub,stage):
    def kill(where,db):
        if where == stage: os._exit(77)
    f.attest(root,pub['publication_id'],stage='publication',expected_config_hash=pin,
             clock=lambda:PUB_TIME,_fault=kill)


@pytest.mark.parametrize('stage',['before_witness_commit','after_witness_commit'])
def test_real_process_death_and_restart(tmp_path,stage):
    root,pin,config = setup(tmp_path); pub = publish(root,pin,config)
    process = multiprocessing.get_context('fork').Process(target=_kill_at,args=(root,pin,pub,stage))
    process.start(); process.join(10); assert process.exitcode == 77
    assert not (root/'witness'/(pub['publication_id']+'-publication.json')).exists()
    with pytest.raises(FileNotFoundError):
        f.derive(root,pub['publication_id'],expected_config_hash=pin,expected_publication_ack_hash='0'*64)
    a,b,_ = finish(root,pin,pub)
    assert verify(root,pin,pub,a,b)['readiness'] == 'BLOCKED'
    with sqlite3.connect(root/'witness'/'witness.sqlite') as db:
        assert db.execute('SELECT count(*) FROM attestations').fetchone()[0] == 2


def test_clock_is_sampled_after_visible_committed_event(tmp_path):
    root,pin,config = setup(tmp_path); pub = publish(root,pin,config)
    def clock():
        with sqlite3.connect(root/'witness'/'witness.sqlite') as db:
            assert db.execute('SELECT count(*) FROM attestations').fetchone()[0] == 1
        return PUB_TIME
    ack = f.attest(root,pub['publication_id'],stage='publication',expected_config_hash=pin,clock=clock)
    assert ack['ack']['post_commit_observed_at_fixture'] == PUB_TIME


def test_regressing_clock_does_not_emit_receipt(tmp_path):
    root,pin,config = setup(tmp_path); pub = publish(root,pin,config)
    with pytest.raises(p.Rejected,match='clock_regression'):
        f.attest(root,pub['publication_id'],stage='publication',expected_config_hash=pin,
                 clock=lambda:'2026-09-28T00:09:00Z')
    assert not (root/'witness'/(pub['publication_id']+'-publication.json')).exists()
    a,b,_ = finish(root,pin,pub); verify(root,pin,pub,a,b)


def test_fsync_failure_never_returns_ack_pin(tmp_path,monkeypatch):
    root,pin,config = setup(tmp_path); pub = publish(root,pin,config)
    real = f._fsync_dir; calls = []
    def failure(path):
        calls.append(path)
        # Bundle dirs, pre-ack witness dir, then post-ack witness directory.
        if len(calls) == 4: raise OSError('directory fsync failed')
        return real(path)
    monkeypatch.setattr(f,'_fsync_dir',failure)
    with pytest.raises(OSError):
        f.attest(root,pub['publication_id'],stage='publication',expected_config_hash=pin,clock=lambda:PUB_TIME)
    assert not (root/'witness'/(pub['publication_id']+'-publication.json')).exists()
    monkeypatch.setattr(f,'_fsync_dir',real)
    a,b,_ = finish(root,pin,pub); verify(root,pin,pub,a,b)


def test_sqlite_full_rolls_back_without_ack(tmp_path):
    root,pin,config = setup(tmp_path); pub = publish(root,pin,config)
    def fill(stage,db):
        if stage == 'before_witness_commit':
            pages = db.execute('PRAGMA page_count').fetchone()[0]
            db.execute('PRAGMA max_page_count='+str(pages))
            db.execute('INSERT INTO attestations VALUES (99,?,?,?,?,?)',
                       ('filler','filler',pub['publication_id'],'x'*100000,'filler'))
    with pytest.raises(sqlite3.OperationalError,match='full'):
        f.attest(root,pub['publication_id'],stage='publication',expected_config_hash=pin,
                 clock=lambda:PUB_TIME,_fault=fill)
    assert not (root/'witness'/(pub['publication_id']+'-publication.json')).exists()
    with sqlite3.connect(root/'witness'/'witness.sqlite') as db:
        assert db.execute('SELECT count(*) FROM attestations').fetchone()[0] == 0
    a,b,_ = finish(root,pin,pub); verify(root,pin,pub,a,b)


def test_derivation_failure_does_not_create_derivation_ack(tmp_path):
    root,pin,config = setup(tmp_path); pub = publish(root,pin,config)
    a = f.attest(root,pub['publication_id'],stage='publication',expected_config_hash=pin,clock=lambda:PUB_TIME)
    def crash(stage): os._exit(78)
    def child():
        f.derive(root,pub['publication_id'],expected_config_hash=pin,
                 expected_publication_ack_hash=a['ack_hash'],_fault=crash)
    process = multiprocessing.get_context('fork').Process(target=child)
    process.start(); process.join(10); assert process.exitcode == 78
    assert not (root/'witness'/(pub['publication_id']+'-derivation.json')).exists()
    a,b,_ = finish(root,pin,pub); verify(root,pin,pub,a,b)


def test_coherent_restore_requires_external_head(tmp_path):
    root,pin,config = setup(tmp_path); pub = publish(root,pin,config); a,b,_ = finish(root,pin,pub)
    backup = tmp_path/'older-witness'; shutil.copytree(root/'witness',backup)
    raw = fixture_raw(config); raw['source_bar_date'] = '2026-09-26'
    path,digest = source(root,raw,'older-bar.json')
    nextpub = f.publish(root,path,expected_config_hash=pin,expected_raw_hash=digest)
    latest = f.attest(root,nextpub['publication_id'],stage='publication',expected_config_hash=pin,clock=lambda:PUB_TIME)
    shutil.rmtree(root/'witness'); shutil.copytree(backup,root/'witness')
    with pytest.raises(p.Rejected,match='external_witness_head'):
        verify(root,pin,pub,a,b,expected_witness_head=latest['event_hash'])
    # Rewinding the outside pin as well remains undetectable: no installed
    # operational monotonic custodian is claimed by these fixture tests.
    assert verify(root,pin,pub,a,b)['issuable'] is False


@pytest.mark.parametrize('kind',['symlink','hardlink','writable'])
def test_unsafe_source_paths(tmp_path,kind):
    root,pin,config = setup(tmp_path); path,digest = source(root,fixture_raw(config))
    if kind == 'symlink':
        alias = root/'strategy'/'link'; alias.symlink_to(path); path = alias
    elif kind == 'hardlink': os.link(path,root/'strategy'/'another')
    else: path.chmod(0o666)
    with pytest.raises(p.Rejected): f.publish(root,path,expected_config_hash=pin,expected_raw_hash=digest)


def _as_uid(uid,action):
    receiver,sender = multiprocessing.Pipe(duplex=False)
    def child():
        try:
            os.setgroups([]); os.setgid(uid); os.setuid(uid)
            sender.send(('ok',action()))
        except BaseException as error:
            sender.send(('error',type(error).__name__,str(error)))
    process = multiprocessing.get_context('fork').Process(target=child)
    process.start(); sender.close(); assert receiver.poll(10)
    result = receiver.recv(); process.join(10); assert process.exitcode == 0
    return result


def test_distinct_real_fixture_uids_and_strategy_cannot_write_trusted_objects(tmp_path):
    assert os.geteuid() == 0, 'Run isolated cached test container with CHOWN SETUID SETGID'
    for ancestor in [tmp_path,*tmp_path.parents]:
        if ancestor == Path('/tmp') or ancestor == Path('/'): break
        ancestor.chmod(0o755)
    uids = dict(zip(f.ROLES,[30110,30120,30130,30140]))
    root,pin,config = setup(tmp_path,uids=uids)
    created = _as_uid(uids['strategy'],lambda:source(root,fixture_raw(config)))
    assert created[0] == 'ok', created
    path,digest = created[1]
    outcome = _as_uid(uids['publisher'],lambda:f.publish(root,path,expected_config_hash=pin,expected_raw_hash=digest))
    assert outcome[0] == 'ok', outcome
    pub = outcome[1]; ident = pub['publication_id']
    outcome = _as_uid(uids['witness'],lambda:f.attest(root,ident,stage='publication',expected_config_hash=pin,clock=lambda:PUB_TIME))
    assert outcome[0] == 'ok', outcome
    a = outcome[1]
    outcome = _as_uid(uids['verifier'],lambda:f.derive(root,ident,expected_config_hash=pin,expected_publication_ack_hash=a['ack_hash']))
    assert outcome[0] == 'ok', outcome
    outcome = _as_uid(uids['witness'],lambda:f.attest(root,ident,stage='derivation',expected_config_hash=pin,clock=lambda:DER_TIME))
    assert outcome[0] == 'ok', outcome
    b = outcome[1]
    outcome = _as_uid(uids['strategy'],lambda:verify(root,pin,pub,a,b))
    assert outcome[0] == 'ok' and outcome[1]['fixture_roles_distinct'] is True, outcome
    for target in [root/'config.json',root/'publisher'/ident/'manifest.json',
                   root/'verifier'/(ident+'.json'),root/'witness'/'witness.sqlite']:
        outcome = _as_uid(uids['strategy'],lambda:target.write_bytes(b'bad'))
        assert outcome[0:2] == ('error','PermissionError'), outcome
    outcome = _as_uid(uids['strategy'],lambda:f.publish(root,path,expected_config_hash=pin,expected_raw_hash=digest))
    assert outcome[0:2] == ('error','Rejected') and 'wrong_fixture_role' in outcome[2]
    # Restore ownership of sandbox directories for pytest's temp cleanup only.
    for directory in [root,*[x for x in root.rglob('*') if x.is_dir()]]:
        os.chown(directory,0,-1)


@pytest.mark.parametrize('artifact',['derivation','publication_ack','witness_payload','witness_sql_identity'])
def test_tampered_receipts_and_committed_state_denied(tmp_path,artifact):
    root,pin,config = setup(tmp_path); pub = publish(root,pin,config); a,b,_ = finish(root,pin,pub)
    ident = pub['publication_id']
    if artifact in ('derivation','publication_ack'):
        path = (root/'verifier'/(ident+'.json') if artifact == 'derivation'
                else root/'witness'/(ident+'-publication.json'))
        payload = p.read_json(path.read_bytes())
        if artifact == 'derivation': payload['execution_approved'] = True
        else: payload['post_commit_observed_at_fixture'] = '2026-09-28T00:08:00Z'
        path.chmod(0o644); path.write_bytes(p.canonical_bytes(payload)); path.chmod(0o444)
    else:
        with sqlite3.connect(root/'witness'/'witness.sqlite') as db:
            if artifact == 'witness_payload': db.execute("UPDATE attestations SET payload='{}' WHERE sequence=1")
            else: db.execute("UPDATE attestations SET stage='foreign' WHERE sequence=1")
    with pytest.raises((p.Rejected,KeyError)): verify(root,pin,pub,a,b)


def test_raw_pin_and_legacy_source_cannot_be_promoted(tmp_path):
    root,pin,config = setup(tmp_path); path,digest = source(root,fixture_raw(config))
    with pytest.raises(p.Rejected,match='raw_pin_mismatch'):
        f.publish(root,path,expected_config_hash=pin,expected_raw_hash='0'*64)
    legacy = fixture_raw(config); legacy.pop('scope'); legacy.pop('clock_id')
    with pytest.raises(p.Rejected,match='not_pinned_synthetic_input'):
        publish(root,pin,config,legacy)
    assert list((root/'publisher').iterdir()) == []


def test_storage_failure_before_attestation_leaves_no_witness_event(tmp_path,monkeypatch):
    root,pin,config = setup(tmp_path); pub = publish(root,pin,config)
    def fail(path): raise OSError('publication persistence could not be confirmed')
    monkeypatch.setattr(f,'_fsync_dir',fail)
    with pytest.raises(OSError):
        f.attest(root,pub['publication_id'],stage='publication',expected_config_hash=pin,clock=lambda:PUB_TIME)
    assert not (root/'witness'/'witness.sqlite').exists()


def test_operational_path_is_forbidden_without_creating_files(tmp_path):
    oper = tmp_path/'octobot-local'; oper.mkdir()
    with pytest.raises(p.Rejected):
        f.init_fixture(oper/'fixture',REPO,uids={r:0 for r in f.ROLES})
    assert list(oper.iterdir()) == []
