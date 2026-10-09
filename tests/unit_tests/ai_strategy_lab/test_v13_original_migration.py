"""Internal work-card-6b5c188a-bbcd-4349-a762-51c5a43ffd80.

All unit data synthetic; real copied baseline is exercised by the separate probe.
"""
import copy
import json
from pathlib import Path
import sqlite3

import pytest

from octobot.ai_strategy_lab import v13_original_migration as m
from octobot.ai_strategy_lab import v13_original_portfolio as p
from octobot.ai_strategy_lab import v13_paper_v2 as paper
from tests.unit_tests.ai_strategy_lab.test_v13_original_executor import rig, sandbox, start, run, second, change_second_target

REPO = Path(__file__).resolve().parents[3]
AT = '2026-09-28T13:00:00Z'
MARK_AT = '2026-09-21T12:00:00Z'


@pytest.fixture
def account(tmp_path):
    root = tmp_path/'review'; root.mkdir(mode=0o700)
    (root/'sandbox.marker').write_bytes(m.MARKER)
    source = root/'source.sqlite'
    db = paper.init_db(source)
    pos = paper.new_position(); paper.apply_fill(pos, 2., 100., .12)
    pos.update(current_price=101., last_mark_at=MARK_AT)
    state = dict(mode=paper.MODE, initial_equity=10000., activation_at='2026-09-21T08:00:00Z',
        positions={'BTCUSDT': pos}, order_count=1, pending=None, last_market_at=MARK_AT,
        last_market_hash='a'*64, executed_targets={'BTCUSDT':.02})
    db.execute('INSERT INTO state VALUES (1,?)', (json.dumps(state),))
    db.execute('INSERT INTO orders VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)',
        (1,'2026-09-19','BTCUSDT','buy',.02,200.,.12,'filled',2.,100.,'2026-09-21T09:00:00Z','b'*64,'a'*64,0.))
    db.execute('INSERT INTO marks VALUES (?,?,?)', (MARK_AT,'BTCUSDT',101.))
    totals=paper.totals(state)
    db.execute('INSERT INTO equity_history VALUES (?,?,?)', (MARK_AT,totals['equity'],totals['pnl']))
    db.execute('INSERT INTO market_events VALUES (?,?,?,?)', ('a'*64,MARK_AT,MARK_AT,'{}'))
    db.commit();db.execute('PRAGMA journal_mode=DELETE'); db.close()
    return root, source, state


def prepare(account, name='candidate', nonce='c'*64):
    root, source, state = account
    return m.prepare(root, source, name, checkpoint_at=AT, nonce=nonce, repo_root=REPO)


def change(account, callback):
    with sqlite3.connect(account[1]) as db:
        state = p.read_json(db.execute('SELECT payload FROM state').fetchone()[0])
        callback(db,state)
        db.execute('UPDATE state SET payload=?', (json.dumps(state),))


def test_history_and_original_state_preserved_with_new_identity_only_in_review(account):
    root,source,state = account
    before=m._hash(source); result=prepare(account)
    manifest=m.verify(root,root/'candidate',expected_manifest_sha256=result['manifest_sha256'])
    receipt=p.read_json((root/'candidate/migration-receipt.json').read_bytes())
    with sqlite3.connect(root/'candidate/execution-copy.sqlite') as db:
        assert p.read_json(db.execute('SELECT payload FROM state').fetchone()[0])==state
        current=p.read_json(db.execute('SELECT candidate_state FROM migration_review').fetchone()[0])
        assert db.execute('SELECT count(*) FROM orders').fetchone()[0]==1
        assert db.execute('SELECT count(*) FROM equity_history').fetchone()[0]==1
    assert m._hash(source)==before
    identity=receipt['identities']['BTCUSDT']
    assert current['positions']['BTCUSDT']['position_id']==identity['position_id']
    assert identity['generation']==1 and identity['historical_identity_known'] is False
    assert 'position_id' not in state['positions']['BTCUSDT']
    assert receipt['reconciliation']['funding_cursors']['BTCUSDT']['coverage_after_mark']=='UNKNOWN'
    assert receipt['reconciliation']['funding_cursors']['BTCUSDT']['gap_exceeds_existing_20h_guard'] is True
    assert all(v is None for v in receipt['policy_values'].values())
    assert receipt['authorization_stores']['claims']=='UNINITIALIZED'
    assert manifest['runtime_admission'] is False and result['readiness']=='BLOCKED'


@pytest.mark.parametrize('failure', ['pending','count','quantity','fees','funding','mark','future','mode','identity','symbol','equity','order_price','status','funding_cursor','market_cursor'])
def test_inconsistent_account_is_denied_before_candidate_created(account,failure):
    def mutate(db,s):
        pos=s['positions']['BTCUSDT']
        if failure=='pending':s['pending']={'targets':{}}
        elif failure=='count':s['order_count']=2
        elif failure=='quantity':pos['quantity']=3.
        elif failure=='fees':pos['fees']=1.
        elif failure=='funding':pos['funding']=1.
        elif failure=='mark':pos['current_price']=999.
        elif failure=='future':pos['last_mark_at']='2026-10-01T12:00:00Z'
        elif failure=='mode':s['mode']='wrong'
        elif failure=='identity':pos['generation']=1
        elif failure=='symbol':s['positions']['NOPEUSDT']=copy.deepcopy(pos)
        elif failure=='equity':db.execute('UPDATE equity_history SET equity=42.')
        elif failure=='order_price':db.execute('UPDATE orders SET price=90.')
        elif failure=='status':db.execute("UPDATE orders SET status='pending'")
        elif failure=='funding_cursor':db.execute('INSERT INTO funding_events VALUES (?,?,?,?,?,?)', ('BTCUSDT',1791000000000,.001,2.,101.,-.202))
        elif failure=='market_cursor':s['last_market_hash']='d'*64
    change(account,mutate)
    with pytest.raises(p.Rejected):prepare(account)
    assert not (account[0]/'candidate').exists()


def test_duplicate_attempt_never_overwrites_and_changed_epoch_rejects_old_bundle(account):
    first=prepare(account);root=account[0]
    with pytest.raises(FileExistsError):prepare(account)
    second=prepare(account,'candidate2','d'*64)
    assert first['manifest_sha256']!=second['manifest_sha256']
    with pytest.raises(p.Rejected,match='external_witness_mismatch'):
        m.verify(root,root/'candidate',expected_manifest_sha256=second['manifest_sha256'])


@pytest.mark.parametrize('missing',['original.sqlite','execution-copy.sqlite','migration-receipt.json','manifest.json'])
def test_partial_restore_never_accepted(account,missing):
    result=prepare(account);root=account[0]
    (root/'candidate'/missing).unlink()
    with pytest.raises((p.Rejected,OSError)):
        m.restore_review(root,root/'candidate','restored',expected_manifest_sha256=result['manifest_sha256'])
    assert not (root/'restored').exists()


def test_tampering_denied_and_copy_rollback_preserves_original(account):
    result=prepare(account);root=account[0]
    restored=m.restore_review(root,root/'candidate','restored',expected_manifest_sha256=result['manifest_sha256'])
    assert restored['operational_apply'] is False
    assert m._hash(root/'restored/original.sqlite')==m._hash(root/'candidate/original.sqlite')
    with sqlite3.connect(root/'candidate/execution-copy.sqlite') as db:db.execute('UPDATE orders SET price=123.')
    with pytest.raises(p.Rejected,match='restore_file_hash_mismatch'):
        m.verify(root,root/'candidate',expected_manifest_sha256=result['manifest_sha256'])


def test_wal_source_symlink_escape_and_operational_paths_rejected(account):
    root,source,_=account
    Path(str(source)+'-wal').write_bytes(b'not checkpointed')
    with pytest.raises(p.Rejected,match='offline_checkpoint_required'):prepare(account)
    Path(str(source)+'-wal').unlink()
    link=root/'link.sqlite';link.symlink_to(source)
    with pytest.raises(p.Rejected,match='symlink_forbidden'):m._db(root,link)
    with pytest.raises(p.Rejected,match='parent_path_forbidden'):m._safe(root,root/'../escape')
    with pytest.raises(p.Rejected,match='operational_path_forbidden'):m._safe(root,root/'octobot-local')


def fixture_copies(tmp_path,rig):
    root=tmp_path/'fixture-review';root.mkdir(mode=0o700);(root/'sandbox.marker').write_bytes(m.MARKER)
    files={}
    for name,source in {'approvals.sqlite':rig['s']['config']['approval_db'],
        'execution.sqlite':rig['config']['execution_db'], 'P004-audit.sqlite':rig['config']['consumer_audit']}.items():
        path=root/name;path.write_bytes(Path(source).read_bytes());files[name]=path
    return root,files


def test_synthetic_coherent_restore_with_all_three_stores_and_old_rollback_denied(tmp_path,rig):
    change_second_target(rig,'0.15')
    rig['s']['policy']['cooldown']=1  # synthetic fixture only, before root pin
    start(rig);outcome=run(rig);assert outcome['value']['status']=='COMMITTED'
    root,files=fixture_copies(tmp_path,rig)
    first=m.checkpoint_fixture(root,files,'checkpoint1')
    restored=m.restore_review(root,root/'checkpoint1','restore1',expected_manifest_sha256=first['manifest_sha256'])
    assert restored['runtime_admission'] is False
    second(rig,target='0.15')
    outcome=run(rig,market_id='2'*64,at='2026-09-28T00:17:00Z')
    assert outcome['value']['status']=='COMMITTED',outcome
    for name,source in {'approvals.sqlite':rig['s']['config']['approval_db'],
        'execution.sqlite':rig['config']['execution_db'],'P004-audit.sqlite':rig['config']['consumer_audit']}.items():files[name].write_bytes(Path(source).read_bytes())
    new_checkpoint=m.checkpoint_fixture(root,files,'checkpoint2')
    with pytest.raises(p.Rejected,match='external_witness_mismatch'):
        m.verify(root,root/'checkpoint1',expected_manifest_sha256=new_checkpoint['manifest_sha256'])
    m.verify(root,root/'checkpoint2',expected_manifest_sha256=new_checkpoint['manifest_sha256'])


@pytest.mark.parametrize('failure',['epoch','claim','approval','pending','global_payload','attempt','batch'])
def test_synthetic_incoherent_or_uncertain_restore_denied_before_manifest(tmp_path,rig,failure):
    start(rig);assert run(rig)['value']['status']=='COMMITTED'
    root,files=fixture_copies(tmp_path,rig)
    target='P004-audit.sqlite' if failure in ('epoch','claim','global_payload') else 'approvals.sqlite' if failure=='approval' else 'execution.sqlite'
    with sqlite3.connect(files[target]) as db:
        if failure=='epoch':db.execute("UPDATE audit_namespace SET value=? WHERE key='account_epoch'",('d'*64,))
        elif failure=='claim':db.execute('DELETE FROM claims')
        elif failure=='approval':db.execute('DELETE FROM approvals')
        elif failure=='global_payload':
            payload=p.read_json(db.execute('SELECT payload FROM claims').fetchone()[0]);payload['result']='DENY'
            db.execute('UPDATE claims SET payload=?',(json.dumps(payload),))
        elif failure=='attempt':db.execute('DELETE FROM portfolio_attempts')
        elif failure=='batch':db.execute('DELETE FROM portfolio_batches')
        else:db.execute("UPDATE portfolio_claims SET status='RESERVED'")
    with pytest.raises(p.Rejected):m.checkpoint_fixture(root,files,'invalid')
    assert not (root/'invalid/manifest.json').exists()


def test_interrupted_publish_never_accepted_as_completed_bundle(account,monkeypatch):
    root=account[0]
    def fail(*args):raise OSError('injected disk failure before final manifest')
    monkeypatch.setattr(m,'_publish',fail)
    with pytest.raises(OSError):prepare(account)
    assert (root/'candidate/execution-copy.sqlite').exists()
    assert not (root/'candidate/manifest.json').exists()
    with pytest.raises(OSError):m.verify(root,root/'candidate',expected_manifest_sha256='a'*64)
