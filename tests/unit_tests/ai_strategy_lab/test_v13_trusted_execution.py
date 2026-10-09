"""Isolated candidate tests: no operational grants, files or containers."""
import copy
import datetime as dt
import json
import hashlib
import os
import sqlite3

import pytest

from octobot.ai_strategy_lab import paper_authorization as auth
from octobot.ai_strategy_lab.paper_authorization_admin import Admin
from octobot.ai_strategy_lab import v13_trusted_execution as executor
from octobot.ai_strategy_lab import v13_intent_client
from tests.unit_tests.ai_strategy_lab.test_v13_market import record_at, signed

NOW = dt.datetime(2026,9,24,12,0,tzinfo=dt.timezone.utc)
POLICY = dict(per_asset_exposure=.315,gross_exposure=.90,
    daily_loss=dict(limit_fraction=.5),drawdown=dict(limit_fraction=.5),
    order_frequency=dict(max_orders=10,window_seconds=3600),
    cooldown=dict(seconds=0),missing_gates=[])


def market_v2(now=NOW):
    record = record_at(now)
    obs = record['symbols'].pop('AAVE')
    obs['futures_symbol']='BTC/USDT:USDT'
    obs['futures_remote_symbol']='XBTUSDTM'
    f = obs['futures']
    f['mark_price']=100.5
    f['normalized_bids']=[dict(price=100.4,base_quantity=1000,quote_quantity=100400)]
    f['normalized_asks']=[dict(price=100.6,base_quantity=1000,quote_quantity=100600)]
    f.update(price_tick=.1,contract_multiplier=.01,contract_lot_size=1,
        quantity_step=.01,min_quantity=.01,min_notional=0.,
        metadata_observed_at=now.isoformat(),mark_timestamp=now.isoformat(),
        metadata_source_endpoint='https://api-futures.kucoin.com/api/v1/contracts/XBTUSDTM',
        raw_contract_metadata=dict(symbol='XBTUSDTM',status='Open',multiplier=.01,lotSize=1,tickSize=.1,minNotional=0))
    f['raw_mark']=dict(symbol='XBTUSDTM',value=100.5,timePoint=int(now.timestamp()*1000),granularity=1000)
    digest=lambda value:hashlib.sha256(json.dumps(value,sort_keys=True,separators=(',',':')).encode()).hexdigest()
    f['contract_metadata_sha256']=digest(f['raw_contract_metadata'])
    f['mark_sha256']=digest(f['raw_mark'])
    f['mark_source_endpoint']='https://api-futures.kucoin.com/api/v1/mark-price/XBTUSDTM/current'
    f['mark_received_at']=now.isoformat()
    f['mark_timestamp_source']='kucoin_timePoint_ms'
    record['symbols']={'BTC':obs}
    record['schema_version']=2
    record['source_schema_v1_hash']='f'*64
    record['metadata_endpoint']=f['metadata_source_endpoint']
    record['metadata_observed_at']=now.isoformat()
    record['mark_endpoint']=f['mark_source_endpoint']
    record['mark_received_at']=now.isoformat()
    record['mark_request_started_at']=now.isoformat()
    record['contract_request_started_at']=now.isoformat()
    return signed(record)


@pytest.fixture
def rig(tmp_path,monkeypatch):
    monkeypatch.setenv('V13_ISOLATED_FIXTURE_ISSUER','1')
    for name in ('audit','ledger','decisions','market','policy','intents'):
        (tmp_path/name).mkdir()
    strategy='fixture-v13'
    lineage='a'*64
    identity=auth.Identity(executor.ACCOUNT,strategy,lineage,'fixture-only',auth.digest(POLICY),'fixture-grant')
    (tmp_path/'policy'/'policy.json').write_text(json.dumps(POLICY))
    (tmp_path/'policy'/'identity.json').write_text(json.dumps(auth.asdict(identity)))
    admin=Admin(tmp_path/'control',clock=lambda:NOW)
    admin.initialize()
    admin.grant(identity,valid_from=NOW.isoformat())
    admin.set_kill(False)
    store=executor.DecisionStore(tmp_path/'decisions'/'decisions.sqlite')
    store.initialize()
    intent=dict(schema_version=1,intent_id='intent-1',account=executor.ACCOUNT,
        symbol='BTCUSDT',direction='LONG',target_weight=.1,decision_id='b'*64,
        decision_authorization_id='token-1',strategy=strategy,strategy_lineage_hash=lineage,
        decision_timestamp=(NOW-dt.timedelta(minutes=1)).isoformat(),
        intent_timestamp=(NOW-dt.timedelta(seconds=20)).isoformat())
    approval=dict(decision_id=intent['decision_id'],token=intent['decision_authorization_id'],
        account=intent['account'],strategy=strategy,lineage_hash=lineage,symbol=intent['symbol'],
        direction=intent['direction'],target_weight=intent['target_weight'],
        decision_at=intent['decision_timestamp'],source_hash='b'*64)
    store.issue_fixture_only(approval)
    record=market_v2()
    (tmp_path/'market'/'v2.jsonl').write_text(json.dumps(record)+'\n')
    path=v13_intent_client.submit(intent,tmp_path/'intents',now=NOW)
    def run(path=path,at=NOW):
        return executor.execute(path,decision_db=store.path,
            ledger_path=tmp_path/'ledger'/'v13.sqlite',
            market_journal=tmp_path/'market'/'v2.jsonl',
            control_root=admin.root,consumer_audit=tmp_path/'audit'/'authorization.sqlite',
            policy_path=tmp_path/'policy'/'policy.json',
            identity_path=tmp_path/'policy'/'identity.json',
            lock_path=tmp_path/'ledger'/'executor.lock',now=at)
    return tmp_path,admin,store,intent,path,run


def counts(root):
    db=root/'ledger'/'v13.sqlite'
    if not db.exists(): return 0,0,0,0
    with sqlite3.connect(db) as connection:
        orders=connection.execute('SELECT COUNT(*) FROM orders').fetchone()[0]
        row=connection.execute('SELECT payload FROM state WHERE id=1').fetchone()
        if not row: return orders,0,0,0
        state=json.loads(row[0]);p=state['positions'].get('BTCUSDT',{})
        equity=connection.execute('SELECT equity FROM equity_history ORDER BY bar DESC LIMIT 1').fetchone()[0]
        return orders,p.get('quantity',0),p.get('fees',0),equity


def test_positive_fixture_chain_then_kill_and_replay(rig):
    root,admin,store,intent,path,run=rig
    result=run()
    assert result['accepted'] and result['orders']==1
    assert counts(root)[0]==1 and counts(root)[1]>0
    with pytest.raises(ValueError):run()
    assert counts(root)[0]==1
    admin.set_kill(True)
    modified=dict(intent,intent_id='intent-2',decision_id='c'*64,decision_authorization_id='token-2',target_weight=.2)
    store.issue_fixture_only(dict(decision_id='c'*64,token='token-2',account=executor.ACCOUNT,
        strategy=intent['strategy'],lineage_hash=intent['strategy_lineage_hash'],symbol='BTCUSDT',
        direction='LONG',target_weight=.2,decision_at=intent['decision_timestamp'],source_hash='c'*64))
    second=v13_intent_client.submit(modified,root/'intents',now=NOW)
    later=NOW+dt.timedelta(seconds=10)
    (root/'market'/'v2.jsonl').write_text(json.dumps(market_v2(later))+'\n')
    before=counts(root)
    assert run(second,later)['accepted'] is False
    assert counts(root)==before
    flat=dict(intent,intent_id='intent-flat',decision_id='d'*64,
        decision_authorization_id='token-flat',direction='FLAT',target_weight=0.)
    store.issue_fixture_only(dict(decision_id='d'*64,token='token-flat',
        account=executor.ACCOUNT,strategy=intent['strategy'],
        lineage_hash=intent['strategy_lineage_hash'],symbol='BTCUSDT',
        direction='FLAT',target_weight=0.,decision_at=intent['decision_timestamp'],
        source_hash='d'*64))
    third=v13_intent_client.submit(flat,root/'intents',now=NOW)
    latest=later+dt.timedelta(seconds=10)
    (root/'market'/'v2.jsonl').write_text(json.dumps(market_v2(latest))+'\n')
    reduced=run(third,latest)
    assert reduced['accepted'] and reduced['position']==0
    assert counts(root)[0]==2


def test_kill_with_strategy_and_issuer_unavailable_has_no_autonomous_exit(rig):
    root,admin,store,intent,path,run=rig
    assert run()['accepted'] is True
    opened=counts(root)
    admin.set_kill(True)
    # No strategy process publishes a new intent. An old intent cannot be
    # reinterpreted as a protective close, and no issuer can mint a token.
    with pytest.raises(ValueError,match='consumed'):
        run()
    forged=dict(intent,intent_id='attempt-flat',decision_id='d'*64,
        decision_authorization_id='missing-token',direction='FLAT',target_weight=0.)
    attempted=root/'intents'/'attempt-flat.json'
    attempted.write_text(json.dumps(forged))
    with pytest.raises(ValueError,match='missing'):
        run(attempted)
    assert counts(root)==opened
    assert opened[1]>0


@pytest.mark.parametrize('change', [
    {'decision_id':'other'}, {'decision_authorization_id':'other'}, {'account':'other'},
    {'strategy_lineage_hash':'c'*64}, {'symbol':'ETHUSDT'}, {'direction':'SHORT','target_weight':-.1},
    {'target_weight':.2}, {'decision_timestamp':(NOW+dt.timedelta(seconds=1)).isoformat()},
    {'intent_timestamp':(NOW-dt.timedelta(hours=1)).isoformat()},
])
def test_forgery_and_staleness_zero_effect(rig,change):
    root,_,_,intent,_,run=rig
    path=root/'intents'/'forged.json'
    path.write_text(json.dumps(dict(intent,**change)))
    with pytest.raises(ValueError):run(path)
    assert counts(root)[0]==0


def test_no_grant_no_p001_no_effect(rig):
    root,admin,store,intent,path,run=rig
    admin.revoke('fixture-grant')
    assert run()['accepted'] is False
    assert counts(root)[0]==0
    with sqlite3.connect(store.path) as db:db.execute('DELETE FROM approvals')
    with pytest.raises(ValueError):run()
    assert counts(root)[0]==0


def test_absurd_spread_and_exposure_zero_effect(rig):
    root,_,_,intent,path,run=rig
    record=market_v2()
    record['symbols']['BTC']['futures']['normalized_asks'][0]['price']=150
    record['symbols']['BTC']['futures']['normalized_asks'][0]['quote_quantity']=150000
    record=signed(record)
    (root/'market'/'v2.jsonl').write_text(json.dumps(record)+'\n')
    assert run()['accepted'] is False
    assert counts(root)[0]==0


def test_exposure_limit_zero_effect(rig):
    root,_,store,intent,_,run=rig
    altered=dict(intent,intent_id='intent-exposure',decision_id='e'*64,
        decision_authorization_id='token-exposure',target_weight=.315)
    store.issue_fixture_only(dict(decision_id='e'*64,token='token-exposure',
        account=executor.ACCOUNT,strategy=intent['strategy'],
        lineage_hash=intent['strategy_lineage_hash'],symbol='BTCUSDT',direction='LONG',
        target_weight=.315,decision_at=intent['decision_timestamp'],source_hash='e'*64))
    path=v13_intent_client.submit(altered,root/'intents',now=NOW)
    result=run(path)
    assert result['accepted'] is False
    assert result['reason']=='projected_exposure_limit'
    assert counts(root)[0]==0


def test_crash_after_claim_burns_decision_without_ledger_effect(rig,monkeypatch):
    from octobot.ai_strategy_lab import v13_paper_v2 as paper
    root,_,store,_,_,run=rig
    with monkeypatch.context() as patch:
        patch.setattr(paper,'apply_fill',lambda *args: (_ for _ in ()).throw(RuntimeError('simulated_crash')))
        with pytest.raises(RuntimeError,match='simulated_crash'):
            run()
    assert counts(root)[0]==0
    with sqlite3.connect(store.path) as db:
        assert db.execute('SELECT COUNT(*) FROM claims').fetchone()[0]==1
    with pytest.raises(ValueError,match='consumed'):
        run()
    assert counts(root)[0]==0


def test_crash_before_claim_has_no_ledger_effect(rig,monkeypatch):
    from octobot.ai_strategy_lab import v13_market
    root,_,store,_,_,run=rig
    with monkeypatch.context() as patch:
        patch.setattr(v13_market,'market_quotes',lambda *args: (_ for _ in ()).throw(RuntimeError('before_claim')))
        with pytest.raises(RuntimeError,match='before_claim'):
            run()
    assert counts(root)[0]==0
    with sqlite3.connect(store.path) as db:
        assert db.execute('SELECT COUNT(*) FROM claims').fetchone()[0]==0


def test_collector_missing_notional_stays_null():
    from octobot.ai_strategy_lab import v13_market_v2_collector as collector
    legacy=record_at(NOW)
    observation=legacy['symbols'].pop('AAVE')
    observation['futures_remote_symbol']='XBTUSDTM'
    legacy['symbols']={'BTC':observation}
    legacy=signed(legacy)
    response={'code':'200000','data':{'symbol':'XBTUSDTM','status':'Open',
        'settleCurrency':'USDT','isInverse':False,'multiplier':.01,'lotSize':1,'tickSize':.1,'markPrice':100.5}}
    mark={'code':'200000','data':{'symbol':'XBTUSDTM','granularity':1000,
        'timePoint':int(NOW.timestamp()*1000),'value':100.5}}
    converted=collector.enrich(legacy,response,mark,contract_started_at=NOW,
        contract_received_at=NOW,mark_started_at=NOW,mark_received_at=NOW)
    assert converted['schema_version']==2
    assert converted['symbols']['BTC']['futures']['min_notional'] is None
    assert converted['symbols']['BTC']['futures']['min_quantity'] is None
    assert converted['source_schema_v1_hash']==legacy['record_hash']


def test_schema_v2_append_preserves_v1_and_chains_forward(tmp_path):
    from octobot.ai_strategy_lab import v13_market_v2_collector as collector
    legacy=record_at(NOW)
    observation=legacy['symbols'].pop('AAVE')
    observation['futures_remote_symbol']='XBTUSDTM'
    legacy['symbols']={'BTC':observation}
    legacy=signed(legacy)
    source=tmp_path/'legacy.jsonl'
    destination=tmp_path/'v2.jsonl'
    original=json.dumps(legacy)+'\n'
    source.write_text(original)
    response={'code':'200000','data':{'symbol':'XBTUSDTM','status':'Open',
        'settleCurrency':'USDT','isInverse':False,'multiplier':.01,'lotSize':1,
        'tickSize':.1,'markPrice':100.5}}
    mark={'code':'200000','data':{'symbol':'XBTUSDTM','granularity':1000,
        'timePoint':int(NOW.timestamp()*1000),'value':100.5}}
    first=collector.append_new_record(source,destination,clock=lambda:NOW,
        fetch_contract=lambda:response,fetch_mark=lambda:mark)
    later=NOW+dt.timedelta(seconds=1)
    mark['data']['timePoint']=int(later.timestamp()*1000)
    second=collector.append_new_record(source,destination,clock=lambda:later,
        fetch_contract=lambda:response,fetch_mark=lambda:mark)
    assert source.read_text()==original
    assert second['previous_record_hash']==first['record_hash']


def test_schema_v2_uses_published_mark_time_and_last_receipt():
    from octobot.ai_strategy_lab import v13_market_v2_collector as collector
    legacy=record_at(NOW)
    observation=legacy['symbols'].pop('AAVE')
    observation['futures_remote_symbol']='XBTUSDTM'
    legacy['symbols']={'BTC':observation}
    legacy=signed(legacy)
    contract={'code':'200000','data':{'symbol':'XBTUSDTM','status':'Open',
        'settleCurrency':'USDT','isInverse':False,'multiplier':.01,'lotSize':1,'tickSize':.1}}
    mark_at=NOW+dt.timedelta(seconds=2)
    mark={'code':'200000','data':{'symbol':'XBTUSDTM','granularity':1000,
        'timePoint':int(mark_at.timestamp()*1000),'value':100.5}}
    captured=collector.enrich(legacy,contract,mark,
        mark_started_at=NOW+dt.timedelta(seconds=1),
        mark_received_at=NOW+dt.timedelta(seconds=3),
        contract_started_at=NOW+dt.timedelta(seconds=4),
        contract_received_at=NOW+dt.timedelta(seconds=5))
    assert captured['observed_at_end']==(NOW+dt.timedelta(seconds=5)).isoformat()
    future=captured['symbols']['BTC']['futures']
    assert future['mark_timestamp']==mark_at.isoformat()
    assert future['mark_received_at']==(NOW+dt.timedelta(seconds=3)).isoformat()
    assert future['book_timestamp_ms']==observation['futures']['book_timestamp_ms']
    bad=copy.deepcopy(captured)
    bad['symbols']['BTC']['futures']['mark_timestamp']=(NOW+dt.timedelta(seconds=3)).isoformat()
    from octobot.ai_strategy_lab import v13_market
    with pytest.raises(ValueError,match='schema-2 metadata'):
        v13_market._validate_record(signed(bad),NOW+dt.timedelta(seconds=5),1800)
    mark['data']['timePoint']=int((NOW-dt.timedelta(seconds=1801)).timestamp()*1000)
    with pytest.raises(ValueError,match='stale_mark'):
        collector.enrich(legacy,contract,mark,mark_started_at=NOW,
            mark_received_at=NOW,contract_started_at=NOW,contract_received_at=NOW)
