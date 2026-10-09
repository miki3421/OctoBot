"""Synthetic contracts prove control behavior only, not KuCoin admissibility.
Work card: work-card-dc791deb-0e2d-415a-9c20-dbec6cde9d29.
"""
import copy
import datetime as dt
import hashlib
import json
import os
from pathlib import Path
import sqlite3
import pytest
from octobot.ai_strategy_lab import v13_research_paper as r
from octobot.ai_strategy_lab import v13_research_source as s
from octobot.ai_strategy_lab import v13_paper_v2 as old
from octobot.ai_strategy_lab import v13_market_sanity as sanity
from octobot.ai_strategy_lab import v13_original_portfolio as p

T=dt.datetime(2026,9,28,20,tzinfo=dt.timezone.utc)

def state(quantity=0):
    v=old.new_position();v.update(quantity=quantity,entry_price=100,current_price=100,generation=1,position_id='fixture',funding_cursor=(T-dt.timedelta(hours=1)).isoformat(),last_mark_at=(T-dt.timedelta(hours=1)).isoformat())
    return dict(mode=old.MODE,initial_equity=10000,positions={'BTCUSDT':v},order_count=0,activation_at=T.isoformat(),last_bar='2026-09-27',risk_policy_state={'daily_day':T.date().isoformat(),'daily_start':10000,'high_water':10000,'daily_entries':0,'last_increase_at':None})

def quote():
    return dict(symbol='BTCUSDT',market_identity='kucoin_futures_usdt',mark_price=100,step=.1,quantity_step=.1,contract_multiplier=.1,price_tick=.1,fee_rate=.0006,min_quantity=None,min_notional=None,bids=[dict(price=99.9,base_quantity=20)],asks=[dict(price=100.1,base_quantity=20)],timestamp=T.isoformat(),mark_timestamp=T.isoformat(),metadata_observed_at=T.isoformat(),funding_interval_ms=28800000,funding=[dict(timestamp_ms=int((T-dt.timedelta(hours=4)).timestamp()*1000),rate=.0001)])

def test_simulation_minima_do_not_change_real_guard():
    q=quote();legs,notes=r.research_plan(state(),{'BTCUSDT':q},{'BTCUSDT':.1},True)
    assert len(legs)==1 and legs[0]['quantity']==10
    assert q['min_quantity'] is None and q['min_notional'] is None
    with pytest.raises(sanity.Veto,match='missing_market_metadata'):sanity.preflight('BTCUSDT',q,1,False)

def test_volume_caps_to_observed_depth():
    q=quote();q['asks'][0]['base_quantity']=1.05
    legs,notes=r.research_plan(state(),{'BTCUSDT':q},{'BTCUSDT':.1},True)
    assert legs[0]['quantity']==1 and notes[0]['reason']=='partial_observed_depth'

def test_volume_below_increment_skips_without_fake_fill():
    q=quote();q['asks'][0]['base_quantity']=.01
    legs,notes=r.research_plan(state(),{'BTCUSDT':q},{'BTCUSDT':.1},True)
    assert not legs and any(n['reason']=='below_simulated_quantity_minimum' for n in notes)

def test_cooldown_does_not_block_reduction():
    legs,notes=r.research_plan(state(10),{'BTCUSDT':quote()},{'BTCUSDT':.05},False)
    assert legs[0]['quantity']==-5 and legs[0]['protective']

def test_suspended_entries_are_not_simulated():
    legs,notes=r.research_plan(state(),{'BTCUSDT':quote()},{'BTCUSDT':.1},False)
    assert not legs and notes[0]['reason']=='new_risk_suspended'

@pytest.mark.parametrize('equity,patch,reason',[(9800,{},'daily_loss_2_percent'),(8999,{'daily_start':8999},'drawdown_10_percent'),(10000,{'daily_entries':1},'one_risk_rebalance_per_UTC_day'),(10000,{'last_increase_at':(T-dt.timedelta(hours=21)).isoformat()},'cooldown_22_hours')])
def test_entry_limits(equity,patch,reason):
    st=state();st['risk_policy_state'].update(patch)
    assert r.risk_gate(st,T,equity)==reason

def test_midnight_does_not_reset_cooldown_or_peak():
    st=state();st['risk_policy_state'].update(last_increase_at=T.isoformat(),high_water=11000,daily_entries=1)
    assert r.risk_gate(st,T+dt.timedelta(hours=5),10500)=='cooldown_22_hours'
    assert st['risk_policy_state']['high_water']==11000

def test_exact_22_hour_boundary():
    st=state();st['risk_policy_state']['last_increase_at']=(T-dt.timedelta(hours=22)).isoformat()
    assert r.risk_gate(st,T,10000) is None

def test_spread_rejected_for_entries():
    q=quote();q['asks'][0]['price']=110
    legs,notes=r.research_plan(state(),{'BTCUSDT':q},{'BTCUSDT':.1},True)
    assert not legs and notes[0]['reason']=='spread_or_mark_divergence'

@pytest.mark.parametrize('event_field,value',[('observed_at_end',(T+dt.timedelta(seconds=1)).isoformat()),('observed_at_start',(T-dt.timedelta(hours=1)).isoformat())])
def test_original_market_time_gate_unchanged(event_field,value):
    record={'observed_at_start':T.isoformat(),'observed_at_end':T.isoformat(),'record_hash':'fixture'};record[event_field]=value
    with pytest.raises(sanity.Veto):sanity.structure_and_time('BTCUSDT',quote(),record,T)

def fixture(croot,monkeypatch,quantity=10):
    croot.mkdir(exist_ok=True);legacy=croot/'legacy.sqlite';conn=old.init_db(legacy)
    st=state(quantity);st['activation_at']=(T-dt.timedelta(days=10)).isoformat()
    with conn:
        conn.execute('INSERT INTO state VALUES (1,?)',(json.dumps(st),));conn.execute('INSERT INTO equity_history VALUES(?,?,?)',((T-dt.timedelta(days=1)).isoformat(),10000,0))
    conn.close()
    c=dict(scope=s.SCOPE,account='v13-paper-v2',epoch='synthetic-test-epoch',legacy_snapshot=str(legacy),legacy_sha256=hashlib.sha256(legacy.read_bytes()).hexdigest(),contract_sha256='a'*64,ledger=str(croot/'execution'),source=str(croot/'source'),approvals=str(croot/'approvals'),uids={'capture':30911,'issuer':30913},identity=dict(account='v13-paper-v2',strategy='original-v13-research',lineage_hash='b'*64,risk_policy='risk-policy-v13-original-research-v1',risk_policy_hash='c'*64,authorization_id='synthetic-only'),control=str(croot/'missing-control'),contract={'risk_policy':{'version':'risk-policy-v13-original-research-v1','controls':dict(daily_loss=.02,drawdown=.10,order_frequency=1,cooldown=79200,per_asset_exposure=.315,gross_exposure=.90)}})
    Path(c['ledger']).mkdir();record=dict(scope=s.SCOPE,observed_at_start=T.isoformat(),observed_at_end=T.isoformat(),quotes={'BTCUSDT':quote()});record['record_hash']=p.digest(record)
    monkeypatch.setattr(s,'owned_json',lambda *a:copy.deepcopy(record));monkeypatch.setattr(s,'now',lambda:T+dt.timedelta(seconds=1))
    return c,r.migrate(c),record

def test_migration_preserves_legacy_rows_and_epoch(tmp_path,monkeypatch):
    c,conn,record=fixture(tmp_path/'sandbox',monkeypatch);conn.close()
    legacy=r.db(c['legacy_snapshot'],True);new=r.db(Path(c['ledger'])/'execution.sqlite',True)
    assert legacy.execute('SELECT * FROM equity_history').fetchall()==new.execute('SELECT * FROM equity_history').fetchall()
    oldstate=json.loads(legacy.execute('SELECT payload FROM state').fetchone()[0]);newstate=json.loads(new.execute('SELECT payload FROM state').fetchone()[0])
    assert oldstate['initial_equity']==newstate['initial_equity'];assert oldstate['positions']['BTCUSDT']['quantity']==newstate['positions']['BTCUSDT']['quantity']
    new.close();legacy.close();c['epoch']='other'
    with pytest.raises(p.Rejected,match='execution_epoch'):r.migrate(c)

def test_admin_close_replay_and_generation(tmp_path,monkeypatch):
    c,conn,record=fixture(tmp_path/'sandbox',monkeypatch)
    st=json.loads(conn.execute('SELECT payload FROM state').fetchone()[0]);pos=st['positions']['BTCUSDT']
    cmd=dict(account=c['account'],symbol='BTCUSDT',position_id=pos['position_id'],generation=pos['generation'],quantity=5,nonce='fixture-close',issued_at=T.isoformat(),expires_at=(T+dt.timedelta(minutes=1)).isoformat())
    h=r.tick(c,conn,cmd);assert h['positions'][0]['quantity']==5
    monkeypatch.setattr(r.source,'now',lambda:T+dt.timedelta(seconds=2))
    with pytest.raises(p.Rejected,match='admin_replay'):r.tick(c,conn,cmd)
    cmd['nonce']='new';cmd['generation']+=1
    with pytest.raises(p.Rejected,match='admin_position_generation'):r.tick(c,conn,cmd)
    assert conn.execute('SELECT COUNT(*) FROM orders').fetchone()[0]==1

def test_negative_equity_keeps_protective_close_and_health_available(tmp_path,monkeypatch):
    from octobot.ai_strategy_lab import v13_paper_view as view
    c,conn,record=fixture(tmp_path/'sandbox',monkeypatch)
    st=json.loads(conn.execute('SELECT payload FROM state').fetchone()[0])
    st['initial_equity']=1
    with conn:conn.execute('UPDATE state SET payload=?',(json.dumps(st),))
    q=record['quotes']['BTCUSDT']
    q.update(mark_price=.1,price_tick=.001,bids=[dict(price=.099,base_quantity=20)],asks=[dict(price=.101,base_quantity=20)])
    record['record_hash']=p.digest({k:v for k,v in record.items() if k!='record_hash'})
    pos=st['positions']['BTCUSDT']
    cmd=dict(account=c['account'],symbol='BTCUSDT',position_id=pos['position_id'],generation=pos['generation'],quantity=5,nonce='negative-equity-close',issued_at=T.isoformat(),expires_at=(T+dt.timedelta(minutes=1)).isoformat())
    h=r.tick(c,conn,cmd)
    assert h['equity']<0 and h['positions'][0]['quantity']==5
    assert h['positions'][0]['weight_pct'] is None
    assert view.summarize_health(h)['available'] is True
    assert conn.execute('SELECT COUNT(*) FROM orders').fetchone()[0]==1
    result=json.loads(conn.execute('SELECT payload FROM state').fetchone()[0])
    legs,notes=r.research_plan(result,record['quotes'],{'BTCUSDT':.1},True)
    assert not legs and notes[0]['reason']=='non_positive_equity'

@pytest.mark.parametrize('quantity,expires,reason',[(11,T+dt.timedelta(minutes=1),'admin_increase_or_reverse'),(5,T-dt.timedelta(seconds=1),'admin_identity_or_expiry'),(5,T+dt.timedelta(minutes=6),'admin_identity_or_expiry')])
def test_admin_invalid_requests_no_fill(tmp_path,monkeypatch,quantity,expires,reason):
    c,conn,record=fixture(tmp_path/'sandbox',monkeypatch);st=json.loads(conn.execute('SELECT payload FROM state').fetchone()[0]);pos=st['positions']['BTCUSDT']
    cmd=dict(account=c['account'],symbol='BTCUSDT',position_id=pos['position_id'],generation=pos['generation'],quantity=quantity,nonce='fixture',issued_at=T.isoformat(),expires_at=expires.isoformat())
    with pytest.raises(p.Rejected,match=reason):r.tick(c,conn,cmd)
    assert conn.execute('SELECT COUNT(*) FROM orders').fetchone()[0]==0

def test_storage_failure_rolls_back_close(tmp_path,monkeypatch):
    c,conn,record=fixture(tmp_path/'sandbox',monkeypatch);st=json.loads(conn.execute('SELECT payload FROM state').fetchone()[0]);pos=st['positions']['BTCUSDT']
    conn.execute('CREATE TRIGGER fail_storage BEFORE INSERT ON orders BEGIN SELECT RAISE(ABORT, \'storage failure\'); END;');conn.commit()
    cmd=dict(account=c['account'],symbol='BTCUSDT',position_id=pos['position_id'],generation=pos['generation'],quantity=5,nonce='fixture',issued_at=T.isoformat(),expires_at=(T+dt.timedelta(minutes=1)).isoformat())
    with pytest.raises(sqlite3.IntegrityError):r.tick(c,conn,cmd)
    assert json.loads(conn.execute('SELECT payload FROM state').fetchone()[0])['positions']['BTCUSDT']['quantity']==10
    assert conn.execute('SELECT COUNT(*) FROM research_claims').fetchone()[0]==0

def test_market_tamper_does_not_write(tmp_path,monkeypatch):
    c,conn,record=fixture(tmp_path/'sandbox',monkeypatch);record['quotes']['BTCUSDT']['mark_price']=200
    monkeypatch.setattr(s,'owned_json',lambda *a:record)
    with pytest.raises(p.Rejected,match='market_tampered'):r.tick(c,conn)
    assert conn.execute('SELECT COUNT(*) FROM orders').fetchone()[0]==0

def test_durable_reservation_survives_restart_without_fill(tmp_path,monkeypatch):
    c,conn,record=fixture(tmp_path/'sandbox',monkeypatch)
    assert r.consume_once(conn,'same-causal-decision') is True
    conn.close();conn=r.migrate(c)
    assert r.consume_once(conn,'same-causal-decision') is False
    assert conn.execute('SELECT COUNT(*) FROM orders').fetchone()[0]==0
    assert conn.execute('SELECT kind FROM research_claims').fetchone()[0]=='issuer-reserved'

def test_gzip_capture_preserves_exact_bytes_and_detects_tamper(tmp_path,monkeypatch):
    (tmp_path/'raw').mkdir();raw=b'{"price":123.45}'
    receipt=dict(kind='LIVE_PUBLIC_HTTPS_CAPTURE',url='https://fapi.binance.com/fapi/v1/klines',started_at=(T-dt.timedelta(seconds=2)).isoformat(),received_at=(T-dt.timedelta(seconds=1)).isoformat(),status=200,raw_sha256=hashlib.sha256(raw).hexdigest(),raw_hex=raw.hex())
    receipt['capture_id']=p.digest(receipt);path=tmp_path/'raw'/(receipt['capture_id']+'.json.gz');s.atomic(path,receipt)
    monkeypatch.setattr(s,'now',lambda:T)
    assert s.captured(tmp_path,receipt,os.geteuid())==raw
    wrong=dict(receipt,raw_hex=b'{"price":0}'.hex());s.atomic(path,wrong)
    with pytest.raises(p.Rejected,match='capture_receipt_mismatch'):s.captured(tmp_path,receipt,os.geteuid())
