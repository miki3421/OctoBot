"""Synthetic contracts only: these tests do not establish KuCoin admissibility."""
import copy
import datetime as dt
import hashlib
import json
from pathlib import Path
import sqlite3
import tempfile
import unittest
from unittest.mock import patch
from octobot.ai_strategy_lab import v13_fork_runner as f

UTC=dt.timezone.utc
T=dt.datetime(2026,10,13,15,0,tzinfo=UTC)
SYMS=['BTCUSDT','ETHUSDT']

def state():
    return dict(initial_equity=10000.,order_count=2,positions={s:dict(f.paper.new_position(),quantity=10.,entry_price=100.,current_price=100.,funding_cursor=T.isoformat(),last_mark_at=T.isoformat(),generation=2,position_id='inherited') for s in SYMS},risk_policy_state=dict(daily_day='2026-10-13',daily_start=10000.,high_water=10100.,daily_entries=0,last_increase_at=None))

def record(now):
    quotes={s:dict(symbol=s,market_identity='kucoin_futures_usdt',timestamp=now.isoformat(),mark_timestamp=now.isoformat(),metadata_observed_at=now.isoformat(),mark_price=100.,bids=[dict(price=99.99,base_quantity=10000)],asks=[dict(price=100.01,base_quantity=10000)],quantity_step=.01,price_tick=.01,fee_rate=.0006,min_quantity=None,min_notional=None,funding_interval_ms=28800000,funding=[dict(timestamp_ms=int(T.timestamp()*1000),rate=.0001)]) for s in SYMS}
    r=dict(scope=f.source.SCOPE,observed_at_start=now.isoformat(),observed_at_end=now.isoformat(),quotes=quotes);r['record_hash']=f.p.digest(r);return r

def series():
    import math
    return {s:[100+8*math.sin(i*.35+j)+i*.1 for i in range(61)] for j,s in enumerate(SYMS)}

class Tests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.root=Path(self.tmp.name);seed=self.root/'seed.sqlite'
        c=sqlite3.connect(seed);c.executescript('CREATE TABLE state(id INTEGER PRIMARY KEY,payload TEXT); CREATE TABLE marks(bar TEXT,symbol TEXT,price REAL); CREATE TABLE funding_events(symbol TEXT,timestamp_ms INTEGER); CREATE TABLE equity_history(bar TEXT,equity REAL,pnl REAL);')
        c.execute('INSERT INTO state VALUES(1,?)',(json.dumps(state()),));c.executemany('INSERT INTO marks VALUES(?,?,?)',[(T.isoformat(),s,100) for s in SYMS]);c.execute('INSERT INTO equity_history VALUES(?,?,?)',(T.isoformat(),10000.,0));c.commit();c.close()
        protocol=dict(universe=SYMS,activation=dict(t0=T.isoformat(),end_exclusive=(T+dt.timedelta(days=90)).isoformat()),fork=dict(parent_db_sha256=f.sha(seed),account_ids={'FAST':'test-fast','HALF':'test-half'}),source_code_pins={})
        path=self.root/'protocol.json';path.write_text(json.dumps(protocol));(self.root/'market').mkdir()
        self.config=dict(protocol=str(path),seed=str(seed),original=str(seed),repo=str(self.root),db=str(self.root/'paired.sqlite'),derivation=dict(source=str(self.root)))
        self.clock=patch.object(f.source,'now',return_value=T);self.clock.start();self.runner=f.Runner(self.config,initialize=True)
    def tearDown(self):self.runner.close();self.clock.stop();self.tmp.cleanup()
    def test_inheritance_restart_and_identity_refusal(self):
        for s in self.runner.states().values():
            self.assertEqual(s['positions'],state()['positions']);self.assertEqual(s['risk_policy_state'],state()['risk_policy_state'])
        receipt=self.runner.receipt;self.runner.close();self.runner=f.Runner(self.config);self.assertEqual(receipt,self.runner.receipt)
        self.assertGreater(f.p.timestamp(receipt['first_decision_slot']),T)
        protocol=json.loads(Path(self.config['protocol']).read_text());protocol['changed']=True;Path(self.config['protocol']).write_text(json.dumps(protocol))
        with self.assertRaisesRegex(ValueError,'identity_changed'):f.Runner(self.config)
    def test_pair_risk_alignment_and_reduced_no_topup(self):
        states=self.runner.states();prices=series();prices['BTCUSDT']=[200-i for i in range(61)]
        targets={s:.30 for s in SYMS};weights,filters,cov,before,common=f.risk_targets(states,targets,prices,{s:'FULL' for s in SYMS})
        self.assertEqual(filters['BTCUSDT'],'REDUCED');self.assertLessEqual(weights['FAST']['BTCUSDT'],.1)
        import numpy as np
        vols=[(365*np.array(list(weights[a].values()))@cov@np.array(list(weights[a].values())))**.5 for a in f.ARMS]
        self.assertAlmostEqual(*vols,places=12)
    def test_zero_risk_flattens_both(self):
        weights,*_=f.risk_targets(self.runner.states(),{s:.2 for s in SYMS},{s:[100.]*61 for s in SYMS},{s:'FULL' for s in SYMS})
        self.assertTrue(all(v==0 for w in weights.values() for v in w.values()))
    def test_one_arm_risk_veto_blocks_both_increases(self):
        states=self.runner.states();states['FAST']['risk_policy_state']['daily_entries']=1
        _,_,fills,out=f.apply_pair(states,{s:.3 for s in SYMS},series(),{s:'FULL' for s in SYMS},record(T),T,None)
        self.assertTrue(out['blocks']['FAST']);self.assertTrue(all(x['protective'] for x in fills))
    def test_market_veto_suspends_all_pair_increases(self):
        r=record(T);r['quotes']['BTCUSDT']['asks'][0]['price']=105.
        _,_,fills,out=f.apply_pair(self.runner.states(),{s:.3 for s in SYMS},series(),{s:'FULL' for s in SYMS},r,T,None)
        self.assertEqual(out['shared_entry_block'],'paired_market_or_minimum_veto')
        self.assertTrue(all(x['protective'] for x in fills))

    def test_slot_atomicity_and_restart_replay(self):
        slot=f.p.timestamp(self.runner.receipt['first_decision_slot']);at=slot+dt.timedelta(seconds=30);r=record(at)
        # Test fixture funding covers this synthetic day; not exchange evidence.
        for q in r['quotes'].values():q['funding_interval_ms']=86400000;q['funding']=[dict(timestamp_ms=int(T.timestamp()*1000),rate=.0001)]
        r['record_hash']=f.p.digest({k:v for k,v in r.items() if k!='record_hash'});(self.root/'market.json').write_text(json.dumps(r))
        inputs=dict(targets={s:.3 for s in SYMS},prices=series(),proposal_id='fixture',snapshot_id='fixture')
        before=self.runner.states()
        self.runner.db.execute("CREATE TRIGGER fail_half BEFORE UPDATE ON states WHEN new.arm='HALF' BEGIN SELECT RAISE(ABORT,'storage fault'); END;")
        with patch.object(self.runner,'recover_passive_grid'),patch.object(self.runner,'book_for_slot',return_value=r),patch.object(self.runner,'prepare_input',return_value=inputs),patch.object(f.source,'now',return_value=at):
            with self.assertRaises(sqlite3.IntegrityError):self.runner.tick(at)
            self.assertEqual(before,self.runner.states());self.assertEqual(self.runner.db.execute('SELECT COUNT(*) FROM slots').fetchone()[0],0)
            self.runner.db.execute('DROP TRIGGER fail_half');self.runner.tick(at)
            count=self.runner.db.execute('SELECT COUNT(*) FROM fills').fetchone()[0];self.assertGreater(count,0)
            self.runner.tick(at);self.assertEqual(count,self.runner.db.execute('SELECT COUNT(*) FROM fills').fetchone()[0])
        self.runner.close();self.runner=f.Runner(self.config);self.assertEqual(count,self.runner.db.execute('SELECT COUNT(*) FROM fills').fetchone()[0])
    def test_missing_funding_is_not_zero_or_cursor_advance(self):
        states=self.runner.states();r=record(T+dt.timedelta(hours=9));r['quotes']['BTCUSDT']['funding']=[]
        with self.assertRaisesRegex(ValueError,'coverage_missing'):self.runner.fund(states,r)
        self.assertEqual(states,self.runner.states())
    def test_funding_qty_and_causal_mark(self):
        at=T+dt.timedelta(minutes=5);r=record(at);when=int((T+dt.timedelta(minutes=1)).timestamp()*1000)
        for q in r['quotes'].values():q['funding'].append(dict(timestamp_ms=when,rate=.001))
        states,rows=self.runner.fund(self.runner.states(),r)
        self.assertEqual(len(rows),4);self.assertEqual(states['FAST']['positions']['BTCUSDT']['funding'],-1.)
        self.assertTrue(all(x['reference_at']==T.isoformat() for x in rows))
    def test_causal_closes_future_bar_and_missing_day(self):
        slot=T.replace(hour=0,minute=15);day=slot.date()-dt.timedelta(days=1)
        requests=[]
        for symbol in SYMS:
            rows=[]
            for i in range(61):
                ms=int(dt.datetime.combine(day-dt.timedelta(days=60-i),dt.time(),UTC).timestamp()*1000)
                rows.append([ms,'1','1','1',str(100+i),'1',ms+86400000-1])
            raw=json.dumps(rows).encode();requests.append(dict(url='https://fapi.binance.com/fapi/v1/klines?symbol='+symbol+'&interval=1d',raw_hex=raw.hex(),raw_sha256=hashlib.sha256(raw).hexdigest(),received_at=slot.isoformat()))
        snap=dict(day=day.isoformat(),published_at=slot.isoformat(),requests=requests);snap['snapshot_id']=f.p.digest(snap)
        expected=f.closes(snap,SYMS,slot)
        r=snap['requests'][0];rows=json.loads(bytes.fromhex(r['raw_hex']));ms=int(slot.replace(hour=0,minute=0).timestamp()*1000);rows.append([ms,'1','1','1','999999','1',ms+86400000-1])
        raw=json.dumps(rows).encode();r.update(raw_hex=raw.hex(),raw_sha256=hashlib.sha256(raw).hexdigest());snap['snapshot_id']=f.p.digest({k:v for k,v in snap.items() if k!='snapshot_id'})
        self.assertEqual(expected,f.closes(snap,SYMS,slot))
        rows.pop(20);raw=json.dumps(rows).encode();r.update(raw_hex=raw.hex(),raw_sha256=hashlib.sha256(raw).hexdigest());snap['snapshot_id']=f.p.digest({k:v for k,v in snap.items() if k!='snapshot_id'})
        with self.assertRaises(KeyError):f.closes(snap,SYMS,slot)
    def test_lost_continuation_never_resets_to_parent(self):
        config=dict(self.config,db=str(self.root/'missing.sqlite'))
        with self.assertRaisesRegex(ValueError,'missing_no_reset'):f.Runner(config)
        self.assertFalse(Path(config['db']).exists())

    def test_stale_market_and_tampering_rejected(self):
        r=record(T)
        with self.assertRaises(ValueError):f.verified_market(r,SYMS,T+dt.timedelta(hours=1))
        r['quotes']['BTCUSDT']['mark_price']=1
        with self.assertRaisesRegex(ValueError,'market_hash'):f.verified_market(r,SYMS,T)
    def test_missing_slot_never_backfilled(self):
        r=record(T+dt.timedelta(days=1,hours=1));(self.root/'market.json').write_text(json.dumps(r))
        with patch.object(self.runner,'recover_passive_grid'):self.runner.tick(T+dt.timedelta(days=1,hours=1))
        self.assertEqual(self.runner.db.execute('SELECT COUNT(*) FROM fills').fetchone()[0],0)
        self.assertEqual(self.runner.db.execute('SELECT status FROM slots').fetchone()[0],'MISSED')

if __name__=='__main__':unittest.main()
