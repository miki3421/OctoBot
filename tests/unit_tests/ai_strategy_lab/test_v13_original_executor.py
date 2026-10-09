"""Internal work-card-f914667b-fa10-4ca5-940f-0f48206da56f.

Real issuer/executor code, synthetic authority/metadata only, actual isolated UIDs.
No monkeypatch of issuer, P0-02/03/04 or simulated pricing in positive tests.
"""
import copy
import datetime as dt
import fcntl
import hashlib
import json
import os
from pathlib import Path
import sqlite3
import subprocess
import sys

import pytest

from octobot.ai_strategy_lab import paper_authorization as auth
from octobot.ai_strategy_lab import v13_original_executor as executor
from octobot.ai_strategy_lab import v13_original_portfolio as p
from octobot.ai_strategy_lab import v13_paper_v2 as paper
from tests.unit_tests.ai_strategy_lab.test_v13_original_issuer import (
    sandbox, as_uid, write_json, run as issue, init as init_issuer,
    STRATEGY, ISSUER, VERIFIER, EXECUTOR, NOW, ROOT)
from tests.unit_tests.ai_strategy_lab.test_v13_market import record_at, signed

pytestmark = pytest.mark.skipif(os.geteuid() != 0, reason='UID fixtures need isolated root setup')
EXECUTE_AT = '2026-09-28T00:16:00Z'
SECOND_ISSUE = '2026-09-28T00:16:20Z'
SECOND_RECEIVE = '2026-09-28T00:16:25Z'
SECOND_EXECUTE = '2026-09-28T00:17:00Z'


def seal(value):
    return p.seal_receipt({k:v for k,v in value.items() if k != 'receipt_hash'})


def market_fixture(at, universe):
    value = record_at(p.timestamp(at))
    template = copy.deepcopy(value['symbols']['AAVE'])
    future = template['futures']
    future.update(mark_price=100., contract_multiplier=.01, quantity_step=.01,
        min_quantity=.01, min_notional=1., price_tick=.01,
        metadata_observed_at=value['observed_at_end'], mark_timestamp=value['observed_at_end'],
        normalized_bids=[{'price':99.9,'base_quantity':100000.,'quote_quantity':9990000.}],
        normalized_asks=[{'price':100.1,'base_quantity':100000.,'quote_quantity':10010000.}])
    value['symbols'] = {}
    for symbol in universe:
        observation = copy.deepcopy(template)
        observation['futures_symbol'] = symbol[:-4]+'/USDT:USDT'
        value['symbols'][symbol] = observation
    value['symbol_count'] = len(universe)
    return {'scope':executor.FIXTURE, 'kind':'synthetic_market_snapshot_v1', 'record':signed(value)}


@pytest.fixture
def rig(sandbox):
    s = sandbox
    c = s['config']
    c['fixture_binding']['baseline_bar_date'] = '2026-09-25'
    binding = p.digest(c['fixture_binding'])
    proposals = []
    c['fixture_proofs'] = {}
    for number, day, source, available in [(1,'2026-09-26','d'*64,'2026-09-28T00:12:00Z'),
                                           (2,'2026-09-27','f'*64,'2026-09-28T00:16:00Z')]:
        proposal = copy.deepcopy(s['proposal'])
        proposal.update(source_bar_date=day, source_record_hash=source, execution_binding_ref=binding)
        proposal['targets']['ETHUSDT'] = '0.05'
        if number == 2:
            proposal.update(source_available_at=available, decision_timestamp='2026-09-28T00:16:01Z',
                            proposal_timestamp='2026-09-28T00:16:02Z')
        publication = copy.deepcopy(s['publication'])
        derivation = copy.deepcopy(s['derivation'])
        for receipt in [publication,derivation]:
            receipt.update(source_record_hash=source, source_bar_date=day)
        derivation.update(targets=proposal['targets'], verified_at=available)
        publication.update(completed_at=(p.timestamp(available)-dt.timedelta(seconds=1)).isoformat(),
            dependency_receipts={'1'*64:(p.timestamp(available)-dt.timedelta(seconds=2)).isoformat()})
        proof = {}
        for name,value,owner,directory in [('derivation',seal(derivation),VERIFIER,s['root']/'verifier'),
                                           ('publication',seal(publication),0,s['root'])]:
            path = directory/(name+str(number)+'.json')
            proof[name] = {'path':str(path), 'owner_uid':owner, 'file_sha256':write_json(path,value,owner),
                           'receipt_hash':value['receipt_hash']}
        c['fixture_proofs'][source] = proof
        proposal.update(derivation_receipt_hash=proof['derivation']['receipt_hash'],
                        source_publication_receipt_hash=proof['publication']['receipt_hash'])
        proposal['proposal_id'] = p.proposal_id(proposal)
        proposals.append(proposal)
    s['proposal'] = proposals[0]
    write_json(s['proposal_path'], s['proposal'], STRATEGY)
    s['config_sha'] = write_json(s['config_path'], c)
    private = s['root']/'execution'
    private.mkdir();os.chown(private,EXECUTOR,EXECUTOR);private.chmod(0o700)
    control = s['root']/'control';control.mkdir();control.chmod(0o755)
    (control/'gate.lock').touch();(control/'gate.lock').chmod(0o444)
    state = dict(mode=paper.MODE,initial_equity=10000.,activation_at='2026-09-28T00:10:00Z',
        positions={},order_count=0,last_bar='2026-09-25',last_market_hash=None,executed_targets=None,pending=None)
    baseline = {'scope':executor.FIXTURE,'kind':'synthetic_account_baseline_v1','state':state}
    baseline_path = s['root']/'baseline.json'
    universe = p.load_contract(ROOT)[0]['universe']
    envelopes = {'1'*64:market_fixture('2026-09-28T00:15:30Z',universe),
                 '2'*64:market_fixture('2026-09-28T00:16:55Z',universe)}
    ec = {'schema_version':1, 'mode':'architecture_fixture', 'scope':executor.FIXTURE,
        'sandbox_root':str(s['root']), 'repo_root':str(ROOT), 'executor_uid':EXECUTOR,'executor_gid':EXECUTOR,
        'issuer_config':{'path':str(s['config_path']),'file_sha256':s['config_sha']},
        'execution_db':str(private/'execution.sqlite'), 'account_lock':str(private/'account.lock'),
        'consumer_audit':str(private/'p004-audit.sqlite'), 'control_root':str(control),
        'fixture_baseline':{'path':str(baseline_path),'file_sha256':write_json(baseline_path,baseline)},
        'fixture_markets':{},'default_market_id':'1'*64,
        'store_id':hashlib.sha256((str(s['root'])+'execution').encode()).hexdigest(),
        'component_hashes':{k:hashlib.sha256(v.read_bytes()).hexdigest() for k,v in executor.component_files(ROOT).items()}}
    ep = s['root']/'executor-config.json'
    return {'s':s,'config':ec,'config_path':ep,'config_sha':None,'baseline':baseline,
            'markets':envelopes,'proposals':proposals,'intent_path':s['root']/'strategy/intent.json'}


def start(r):
    s = r['s']
    # Re-pin fixture changes only before creating this isolated store.
    s['config']['fixture_policy']['file_sha256'] = write_json(Path(s['config']['fixture_policy']['path']),s['policy'])
    s['config_sha'] = write_json(s['config_path'],s['config'])
    r['config']['issuer_config']['file_sha256'] = s['config_sha']
    policy = dict(s['policy'],per_asset_exposure=.315,gross_exposure=.9,missing_gates=[])
    identity = auth.Identity('v13-paper-v2','v13-original-portfolio-fixture',s['proposal']['scientific_lineage_ref'],
                            policy['version'],auth.digest(policy),'fixture:portfolio-test')
    r['config']['fixture_identity'] = auth.asdict(identity)
    registry = {'schema_version':1,'revision':1,'global_kill':{'active':False,'changed_at':'2026-09-28T00:10:00Z'},
        'authorizations':{identity.authorization_id:dict(auth.asdict(identity),status='ACTIVE',
            created_at='2026-09-28T00:10:00Z',valid_from='2026-09-28T00:10:00Z',expires_at=None)}}
    write_json(Path(r['config']['control_root'])/'registry.json',registry)
    r['config']['fixture_baseline']['file_sha256'] = write_json(Path(r['config']['fixture_baseline']['path']),r['baseline'])
    for name,value in r['markets'].items():
        value['record'] = signed(value['record'])
        path = s['root']/('market-'+name[0]+'.json')
        r['config']['fixture_markets'][name] = {'path':str(path),'file_sha256':write_json(path,value)}
    r['config_sha'] = write_json(r['config_path'],r['config'])
    init_issuer(s)
    issued = issue(s);assert issued['ok'] and issued['value']['status']=='APPROVE',issued
    r['receipt'] = issued['value']['receipt']
    intent(r,r['receipt'],'a'*64)
    initialized = run(r,'init');assert initialized == {'ok':True,'value':True},initialized
    received = run(r,'receive');assert received['ok'] and received['value']['status']=='RECEIVED',received


def intent(r,receipt,identity):
    proposal = receipt['proposal']
    value = {'schema_version':1,'intent_id':identity,'account':proposal['account'],
        'account_epoch':proposal['account_epoch'],'execution_binding_ref':proposal['execution_binding_ref'],
        'proposal_id':proposal['proposal_id'],'approval_id':receipt['approval_id'],'receipt_hash':receipt['receipt_hash']}
    r['intent'] = value
    write_json(r['intent_path'],value,STRATEGY)
    return value


def run(r,action='execute',at=None,market_id=None):
    def invoke():
        e = executor.Executor(r['config_path'],expected_config_sha256=r['config_sha'])
        if action=='init':e.initialize();return True
        if action=='receive':return e.receive(r['intent_path'],checked_at=at or NOW)
        return e.execute(r['intent']['intent_id'],checked_at=at or EXECUTE_AT,market_id=market_id)
    return as_uid(EXECUTOR,EXECUTOR,invoke)


def counts(r):
    with sqlite3.connect(r['config']['execution_db']) as db:
        result = {name:db.execute('SELECT count(*) FROM '+name).fetchone()[0] for name in
            ['orders','marks','funding_events','market_events','portfolio_claims','portfolio_batches']}
        result['claim_status'] = [x[0] for x in db.execute('SELECT status FROM portfolio_claims ORDER BY source_bar_date')]
        result['state'] = p.read_json(db.execute('SELECT payload FROM state').fetchone()[0])
        return result


def second(r,target='0.1'):
    s = r['s'];proposal = copy.deepcopy(r['proposals'][1])
    proposal['targets']['BTCUSDT'] = target
    # Changing a target must be supported by the pre-pinned derivation. Tests
    # wanting new risk change this proposal/receipt before start instead.
    assert target==r['proposals'][1]['targets']['BTCUSDT']
    write_json(s['proposal_path'],proposal,STRATEGY)
    issued = issue(s,now=SECOND_ISSUE);assert issued['ok'] and issued['value']['status']=='APPROVE',issued
    intent(r,issued['value']['receipt'],'b'*64)
    received = run(r,'receive',at=SECOND_RECEIVE);assert received['ok'] and received['value']['status']=='RECEIVED',received


def change_target(r,number,symbol,value):
    proposal = r['proposals'][number]
    proof = r['s']['config']['fixture_proofs'][proposal['source_record_hash']]['derivation']
    receipt = p.read_json(Path(proof['path']).read_bytes())
    receipt['targets'][symbol] = value;receipt = seal(receipt)
    proof['file_sha256'] = write_json(Path(proof['path']),receipt,VERIFIER)
    proof['receipt_hash'] = receipt['receipt_hash']
    proposal['targets'][symbol] = value;proposal['derivation_receipt_hash'] = receipt['receipt_hash']
    proposal['proposal_id'] = p.proposal_id(proposal)
    if number==0:write_json(r['s']['proposal_path'],proposal,STRATEGY)


def change_second_target(r,value):
    change_target(r,1,'BTCUSDT',value)


def test_positive_real_issuer_to_atomic_portfolio_and_restart(rig):
    start(rig)
    before = hashlib.sha256(Path(rig['s']['config']['approval_db']).read_bytes()).hexdigest()
    outcome = run(rig);assert outcome['ok'] and outcome['value']['status']=='COMMITTED',outcome
    result = counts(rig)
    assert result['orders']==2 and result['marks']==18 and result['portfolio_batches']==1
    assert result['portfolio_claims']==1 and result['claim_status']==['COMMITTED']
    assert result['state']['positions']['BTCUSDT']['quantity']>0 and result['state']['positions']['ETHUSDT']['quantity']>0
    assert len(result['state']['executed_targets'])==18
    assert outcome['value']['operational_execution'] is False and outcome['value']['scope']==executor.FIXTURE
    again = run(rig);assert again['ok'] and again['value']['status']=='ALREADY_COMMITTED'
    assert again['value']['receipt']==outcome['value'] and counts(rig)==result
    assert hashlib.sha256(Path(rig['s']['config']['approval_db']).read_bytes()).hexdigest()==before


@pytest.mark.parametrize('failure',['min_quantity','min_notional','depth','spread','future','missing_quote','old_book'])
def test_one_bad_leg_means_no_economic_commit(rig,failure):
    record = rig['markets']['1'*64]['record'];future = record['symbols']['ETHUSDT']['futures']
    if failure in ('min_quantity','min_notional'):future[failure]=None
    elif failure=='depth':
        future['normalized_asks'][0]['base_quantity']=.01
        future['normalized_asks'][0]['quote_quantity']=.01*future['normalized_asks'][0]['price']
    elif failure=='spread':
        future['normalized_asks'][0]['price']=101.
        future['normalized_asks'][0]['quote_quantity']=101.*future['normalized_asks'][0]['base_quantity']
    elif failure=='future':future['book_timestamp_ms']=int(p.timestamp('2026-09-28T00:17:00Z').timestamp()*1000)
    elif failure=='missing_quote':record['symbols'].pop('ETHUSDT');record['symbol_count']=17
    else:future['book_timestamp_ms']=int(p.timestamp(NOW).timestamp()*1000)
    start(rig);before=counts(rig);outcome=run(rig)
    assert outcome['ok'] and outcome['value']['status']=='DENY',outcome
    after=counts(rig)
    assert after['orders']==after['marks']==after['portfolio_batches']==after['funding_events']==0
    assert after['state']==before['state']
    if failure in ('min_quantity','min_notional','depth','spread'):
        assert after['claim_status']==['DENIED']
        replay=intent(rig,rig['receipt'],'c'*64)
        received=run(rig,'receive',at=EXECUTE_AT)
        assert received['ok'] and received['value']['status']=='RECEIVED',received
        repeated=run(rig);assert repeated['ok'] and repeated['value']['status']=='DENY'
        assert counts(rig)['orders']==0 and replay['intent_id']=='c'*64


def test_global_kill_denies_before_P0_01(rig):
    start(rig);path=Path(rig['config']['control_root'])/'registry.json'
    value=p.read_json(path.read_bytes());value['global_kill']['active']=True;value['revision']+=1;write_json(path,value)
    result=run(rig);assert result['ok'] and result['value']['reason']=='global_kill_active',result
    assert counts(rig)['portfolio_claims']==counts(rig)['orders']==0


@pytest.mark.parametrize('mutation',['targets','symbol','timestamp','epoch','approval','receipt'])
def test_strategy_intent_cannot_override_approved_authority(rig,mutation):
    start(rig);value=copy.deepcopy(rig['intent']);value['intent_id']='c'*64
    if mutation in ('targets','symbol','timestamp'):value[mutation]={'BTCUSDT':1} if mutation=='targets' else 'forged'
    elif mutation=='epoch':value['account_epoch']='e'*64
    else:value[mutation+'_id' if mutation=='approval' else 'receipt_hash']='e'*64
    write_json(rig['intent_path'],value,STRATEGY)
    outcome=run(rig,'receive');assert outcome['ok'] and outcome['value']['status']=='DENY',outcome
    assert counts(rig)['orders']==counts(rig)['portfolio_claims']==0


def test_intent_duplicate_does_not_backdate_or_extend_reception(rig):
    start(rig);one=run(rig,'receive',at='2026-09-28T00:15:10Z')
    assert one['ok'] and one['value']['received_at']==p.timestamp(NOW).isoformat()
    assert counts(rig)['portfolio_claims']==0


def test_expired_approval_and_executor_clock_regression_denied(rig):
    start(rig);outcome=run(rig,at='2026-09-28T00:17:01Z')
    assert outcome['ok'] and outcome['value']['reason']=='portfolio_approval_expired_or_future'
    outcome=run(rig,at='2026-09-28T00:15:30Z')
    assert outcome['ok'] and outcome['value']['reason']=='executor_clock_regression'
    assert counts(rig)['orders']==0


def test_NO_CHANGE_keeps_quantities_and_does_not_consume_another_claim(rig):
    # A different observed mark must not rebalance an unchanged target vector.
    f=rig['markets']['2'*64]['record']['symbols']['BTCUSDT']['futures']
    f['mark_price']=100.2
    start(rig);assert run(rig)['value']['status']=='COMMITTED'
    old=counts(rig);second(rig);outcome=run(rig,at=SECOND_EXECUTE,market_id='2'*64)
    assert outcome['ok'] and outcome['value']['status']=='NO_CHANGE',outcome
    new=counts(rig)
    assert new['orders']==2 and new['portfolio_claims']==1 and new['portfolio_batches']==2
    for symbol in old['state']['positions']:
        assert old['state']['positions'][symbol]['quantity']==new['state']['positions'][symbol]['quantity']


@pytest.mark.parametrize('limit',['frequency','cooldown','daily_loss','drawdown'])
def test_fixture_policy_uses_durable_history_across_restart(rig,limit):
    change_second_target(rig,'0.2')
    if limit=='frequency':rig['s']['policy']['order_frequency']=1
    if limit in ('daily_loss','drawdown'):
        if limit=='drawdown':rig['s']['policy']['daily_loss']=.9
        for future in [rig['markets']['2'*64]['record']['symbols'][s]['futures'] for s in ['BTCUSDT','ETHUSDT']]:
            price=80. if limit=='daily_loss' else 60.
            future['mark_price']=price
            future['normalized_bids'][0]['price']=price-.1;future['normalized_asks'][0]['price']=price+.1
            for level in future['normalized_bids']+future['normalized_asks']:
                level['quote_quantity']=level['price']*level['base_quantity']
    start(rig);assert run(rig)['value']['status']=='COMMITTED'
    second(rig,'0.2');outcome=run(rig,at=SECOND_EXECUTE,market_id='2'*64)
    expected={'frequency':'fixture_batch_frequency_limit','cooldown':'fixture_cooldown_active',
              'daily_loss':'fixture_daily_loss_limit','drawdown':'fixture_drawdown_limit'}[limit]
    assert outcome['ok'] and outcome['value']['reason']==expected,outcome
    assert counts(rig)['orders']==2 and counts(rig)['claim_status']==['COMMITTED','DENIED']


def test_strategy_and_issuer_cannot_write_execution_storage(rig):
    start(rig);run(rig)
    for uid in (STRATEGY,ISSUER,VERIFIER):
        result=as_uid(uid,EXECUTOR,lambda:sqlite3.connect(rig['config']['execution_db']).execute('CREATE TABLE forged(x)'))
        assert not result['ok']
    result=as_uid(EXECUTOR,EXECUTOR,lambda:sqlite3.connect(rig['s']['config']['approval_db']).execute('CREATE TABLE forged(x)'))
    assert not result['ok']


@pytest.mark.parametrize('failure',['missing','corrupt','readonly','namespace','symlink','schema'])
def test_execution_storage_failures_never_commit(rig,failure):
    start(rig);path=Path(rig['config']['execution_db'])
    if failure=='missing':path.unlink()
    elif failure=='corrupt':path.write_bytes(b'not sqlite')
    elif failure=='readonly':path.chmod(0o400)
    elif failure=='symlink':target=path.with_suffix('.other');path.rename(target);path.symlink_to(target)
    else:
        with sqlite3.connect(path) as db:
            if failure=='namespace':db.execute("UPDATE execution_namespace SET value='forged' WHERE key='store_id'")
            else:db.execute('CREATE TABLE forged(x)')
    assert not run(rig)['ok']
    def cli():
        result=subprocess.run([sys.executable,'-m','octobot.ai_strategy_lab.v13_original_executor',
            '--config',str(rig['config_path']),'--config-sha256',rig['config_sha'],
            '--execute-intent',rig['intent']['intent_id']],capture_output=True,text=True)
        return {'code':result.returncode,'result':json.loads(result.stdout)}
    outcome=as_uid(EXECUTOR,EXECUTOR,cli)
    assert outcome['ok'] and outcome['value']['code']==2 and outcome['value']['result']['persisted'] is False


def test_no_operational_mode_or_real_baseline_bootstrap(rig):
    rig['config']['mode']='operational';rig['config_sha']=write_json(rig['config_path'],rig['config'])
    assert not run(rig,'init')['ok']
    rig['config']['mode']='architecture_fixture';rig['baseline']['kind']='copied_account_diagnostic'
    rig['config']['fixture_baseline']['file_sha256']=write_json(Path(rig['config']['fixture_baseline']['path']),rig['baseline'])
    # Completing the other fixture setup must still refuse a real migration.
    with pytest.raises(AssertionError,match='real_account_migration_not_implemented'):start(rig)


@pytest.mark.parametrize('phase',['after_P004','after_reserve','before_economic_commit','after_economic_commit'])
def test_crash_never_rearms_a_consumed_authorization(rig,phase):
    start(rig);pid=os.fork()
    if pid==0:
        os.setgroups([]);os.setgid(EXECUTOR);os.setuid(EXECUTOR)
        original=sqlite3.connect
        class Interrupted(sqlite3.Connection):
            def commit(self):
                tables={x[0] for x in self.execute("SELECT name FROM sqlite_master WHERE type='table'")}
                if 'portfolio_claims' in tables:
                    batches=self.execute('SELECT count(*) FROM portfolio_batches').fetchone()[0]
                    claims=self.execute('SELECT count(*) FROM portfolio_claims').fetchone()[0]
                    if phase=='after_reserve' and claims==1 and batches==0:
                        super().commit();os._exit(42)
                    if batches==1 and phase in ('before_economic_commit','after_economic_commit'):
                        if phase=='after_economic_commit':super().commit()
                        os._exit(42)
                super().commit()
        sqlite3.connect=lambda *a,**k:original(*a,**k,factory=Interrupted)
        if phase=='after_P004':executor.Executor._reserve=lambda *a,**k:os._exit(42)
        executor.Executor(rig['config_path'],expected_config_sha256=rig['config_sha']).execute(rig['intent']['intent_id'],checked_at=EXECUTE_AT)
        os._exit(99)
    _,status=os.waitpid(pid,0);assert os.waitstatus_to_exitcode(status)==42
    restarted=run(rig);assert restarted['ok'],restarted
    if phase=='after_economic_commit':
        assert restarted['value']['status']=='ALREADY_COMMITTED' and counts(rig)['orders']==2
    else:
        assert restarted['value']['status']=='DENY' and counts(rig)['orders']==0
    assert counts(rig)['orders'] in (0,2)


def test_error_after_actual_commit_is_read_back_without_false_zero_fill(rig):
    start(rig)
    def attempt():
        original=sqlite3.connect
        class LostResponse(sqlite3.Connection):
            def commit(self):
                tables={x[0] for x in self.execute("SELECT name FROM sqlite_master WHERE type='table'")}
                economic='portfolio_batches' in tables and self.execute('SELECT count(*) FROM portfolio_batches').fetchone()[0]==1
                super().commit()
                if economic:
                    # Fail only the economic response, allow recovery audit.
                    sqlite3.connect=original
                    raise sqlite3.OperationalError('fixture lost commit response')
        sqlite3.connect=lambda *a,**k:original(*a,**k,factory=LostResponse)
        return executor.Executor(rig['config_path'],expected_config_sha256=rig['config_sha']).execute(rig['intent']['intent_id'],checked_at=EXECUTE_AT)
    result=as_uid(EXECUTOR,EXECUTOR,attempt)
    assert result['ok'] and result['value']['status']=='COMMIT_CONFIRMED' and result['value']['orders']==2,result
    assert counts(rig)['claim_status']==['COMMITTED']


def test_P004_lease_still_held_during_economic_commit(rig):
    start(rig)
    def attempt():
        original=sqlite3.connect
        class CheckLease(sqlite3.Connection):
            def commit(self):
                tables={x[0] for x in self.execute("SELECT name FROM sqlite_master WHERE type='table'")}
                if 'portfolio_batches' in tables and self.execute('SELECT count(*) FROM portfolio_batches').fetchone()[0]==1:
                    with (Path(rig['config']['control_root'])/'gate.lock').open('rb') as gate:
                        try:fcntl.flock(gate,fcntl.LOCK_EX|fcntl.LOCK_NB)
                        except BlockingIOError:pass
                        else:raise AssertionError('P0-04 lease ended before commit')
                super().commit()
        sqlite3.connect=lambda *a,**k:original(*a,**k,factory=CheckLease)
        return executor.Executor(rig['config_path'],expected_config_sha256=rig['config_sha']).execute(rig['intent']['intent_id'],checked_at=EXECUTE_AT)
    result=as_uid(EXECUTOR,EXECUTOR,attempt)
    assert result['ok'] and result['value']['status']=='COMMITTED',result


def test_P002_costs_at_asset_boundary_deny_all_legs(rig):
    change_target(rig,0,'BTCUSDT','0.315')
    start(rig);outcome=run(rig)
    assert outcome['ok'] and outcome['value']['reason']=='projected_exposure_limit',outcome
    assert counts(rig)['orders']==0 and counts(rig)['claim_status']==['DENIED']


def test_proven_strategy_reduction_requires_P001_but_no_new_risk_grant(rig):
    change_target(rig,0,'ETHUSDT','0')
    rig['baseline']['state']['positions']['BTCUSDT']=dict(paper.new_position(),quantity=40.,entry_price=100.,
        current_price=100.,last_mark_at='2026-09-28T00:14:00Z',position_id='fixture-held-btc',position_generation=1)
    start(rig);path=Path(rig['config']['control_root'])/'registry.json'
    registry=p.read_json(path.read_bytes());registry['global_kill']['active']=True;write_json(path,registry)
    outcome=run(rig);assert outcome['ok'] and outcome['value']['status']=='COMMITTED',outcome
    c=counts(rig);assert c['orders']==1 and c['claim_status']==['COMMITTED']
    assert 0<c['state']['positions']['BTCUSDT']['quantity']<40
    with sqlite3.connect(rig['config']['consumer_audit']) as audit:
        assert audit.execute('SELECT count(*) FROM claims').fetchone()[0]==0


def test_uncovered_funding_denies_without_inventing_a_zero_cost(rig):
    rig['baseline']['state']['positions']['BTCUSDT']=dict(paper.new_position(),quantity=10.,entry_price=100.,
        current_price=100.,last_mark_at='2026-09-26T00:14:00Z',position_id='fixture-held-btc',position_generation=1)
    start(rig);outcome=run(rig)
    assert outcome['ok'] and outcome['value']['reason']=='funding_coverage_or_cursor_failure',outcome
    c=counts(rig);assert c['orders']==c['funding_events']==c['marks']==0


def test_disk_failure_during_economy_rolls_back_all_legs_but_not_claim(rig):
    start(rig)
    def attempt():
        original=sqlite3.connect
        class Broken(sqlite3.Connection):
            def commit(self):
                tables={x[0] for x in self.execute("SELECT name FROM sqlite_master WHERE type='table'")}
                if 'portfolio_batches' in tables and self.execute('SELECT count(*) FROM portfolio_batches').fetchone()[0]==1:
                    sqlite3.connect=original
                    raise sqlite3.OperationalError('fixture disk full during commit')
                super().commit()
        sqlite3.connect=lambda *a,**k:original(*a,**k,factory=Broken)
        return executor.Executor(rig['config_path'],expected_config_sha256=rig['config_sha']).execute(rig['intent']['intent_id'],checked_at=EXECUTE_AT)
    outcome=as_uid(EXECUTOR,EXECUTOR,attempt)
    assert outcome['ok'] and outcome['value']['status']=='DENY',outcome
    c=counts(rig);assert c['orders']==c['marks']==c['portfolio_batches']==0 and c['claim_status']==['DENIED']
    again=run(rig);assert again['ok'] and again['value']['reason']=='portfolio_approval_consumed'


def test_concurrent_executors_commit_the_portfolio_only_once(rig):
    start(rig);children=[]
    for _ in range(2):
        reader,writer=os.pipe();pid=os.fork()
        if pid==0:
            os.close(reader);os.setgroups([]);os.setgid(EXECUTOR);os.setuid(EXECUTOR)
            try:
                outcome={'ok':True,'result':executor.Executor(rig['config_path'],expected_config_sha256=rig['config_sha']).execute(rig['intent']['intent_id'],checked_at=EXECUTE_AT)}
            except BaseException as error:outcome={'ok':False,'type':type(error).__name__}
            with os.fdopen(writer,'wb') as stream:stream.write(json.dumps(outcome).encode())
            os._exit(0)
        os.close(writer);children.append((reader,pid))
    outcomes=[]
    for reader,pid in children:
        with os.fdopen(reader,'rb') as stream:outcomes.append(json.load(stream))
        os.waitpid(pid,0)
    assert any(x['ok'] and x['result']['status']=='COMMITTED' for x in outcomes),outcomes
    assert all(x.get('type')=='BlockingIOError' or x['ok'] and x['result']['status'] in ('COMMITTED','ALREADY_COMMITTED') for x in outcomes),outcomes
    c=counts(rig);assert c['orders']==2 and c['portfolio_batches']==c['portfolio_claims']==1


def test_missing_P004_audit_is_not_recreated(rig):
    start(rig);path=Path(rig['config']['consumer_audit']);path.unlink()
    outcome=run(rig);assert not outcome['ok']
    assert not path.exists()
    with sqlite3.connect(rig['config']['execution_db']) as db:
        assert db.execute('SELECT count(*) FROM orders').fetchone()[0]==0


def test_restoring_only_P004_claims_cannot_resume_a_new_batch(rig):
    change_second_target(rig,'0.2');start(rig);assert run(rig)['value']['status']=='COMMITTED'
    with sqlite3.connect(rig['config']['consumer_audit']) as audit:audit.execute('DELETE FROM claims')
    # Even intake of a later proposal is blocked by cross-store inconsistency.
    write_json(rig['s']['proposal_path'],rig['proposals'][1],STRATEGY)
    issued=issue(rig['s'],now=SECOND_ISSUE);assert issued['value']['status']=='APPROVE'
    intent(rig,issued['value']['receipt'],'b'*64)
    outcome=run(rig,'receive',at=SECOND_RECEIVE)
    assert outcome['ok'] and outcome['value']['reason']=='restore_P004_claim_mismatch',outcome
    assert counts(rig)['orders']==2 and counts(rig)['portfolio_batches']==1


@pytest.mark.parametrize('status',['missing','revoked'])
def test_P004_authorization_unavailable_denies_new_risk(rig,status):
    start(rig);path=Path(rig['config']['control_root'])/'registry.json';registry=p.read_json(path.read_bytes())
    if status=='missing':registry['authorizations']={}
    else:next(iter(registry['authorizations'].values()))['status']='REVOKED'
    write_json(path,registry)
    outcome=run(rig)
    assert outcome['ok'] and outcome['value']['reason']==('authorization_missing' if status=='missing' else 'authorization_revoked'),outcome
    assert counts(rig)['orders']==counts(rig)['portfolio_claims']==0


def test_snapshot_tamper_denied_before_claim_or_fill(rig):
    start(rig);path=Path(rig['config']['fixture_markets']['1'*64]['path']);path.write_text('{}')
    outcome=run(rig);assert outcome['ok'] and outcome['value']['reason']=='input_pin_mismatch',outcome
    assert counts(rig)['orders']==counts(rig)['portfolio_claims']==0


def test_newer_issuer_slot_prevents_old_portfolio_execution(rig):
    start(rig)
    write_json(rig['s']['proposal_path'],rig['proposals'][1],STRATEGY)
    issued=issue(rig['s'],now=SECOND_ISSUE);assert issued['value']['status']=='APPROVE'
    outcome=run(rig,at=SECOND_RECEIVE)
    assert outcome['ok'] and outcome['value']['reason']=='source_slot_superseded',outcome
    assert counts(rig)['orders']==counts(rig)['portfolio_claims']==0


def test_actual_SQLITE_FULL_rolls_back_economy_and_preserves_consumption(rig):
    start(rig)
    def attempt():
        original=sqlite3.connect;seen=[]
        class Limited(sqlite3.Connection):
            def execute(self,*args,**kwargs):
                try:return super().execute(*args,**kwargs)
                except sqlite3.Error as error:
                    if getattr(error,'sqlite_errorcode',None)==sqlite3.SQLITE_FULL:seen.append('SQLITE_FULL')
                    raise
        def capped(*args,**kwargs):
            db=original(*args,**kwargs,factory=Limited)
            if 'execution.sqlite' in str(args[0]):
                pages=db.execute('PRAGMA page_count').fetchone()[0]
                db.execute('PRAGMA max_page_count='+str(pages))
            return db
        sqlite3.connect=capped
        result=executor.Executor(rig['config_path'],expected_config_sha256=rig['config_sha']).execute(rig['intent']['intent_id'],checked_at=EXECUTE_AT)
        return {'result':result,'errors_observed':seen}
    outcome=as_uid(EXECUTOR,EXECUTOR,attempt)
    assert outcome['ok'] and outcome['value']['errors_observed'],outcome
    assert outcome['value']['result']['status']=='DENY'
    c=counts(rig);assert c['orders']==c['marks']==c['portfolio_batches']==0 and c['claim_status']==['DENIED']
