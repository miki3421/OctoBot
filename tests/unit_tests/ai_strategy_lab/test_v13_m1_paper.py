"""Synthetic simulation contracts only. No proof of KuCoin order admissibility."""
import copy
import datetime as dt
import json
from pathlib import Path
import sqlite3
import tempfile
import unittest
from unittest.mock import patch
from octobot.ai_strategy_lab import v13_m1_paper as m
from octobot.ai_strategy_lab import v13_m1_paper_view as view
from tests.unit_tests.ai_strategy_lab.test_v13_fork_runner import record, state, T, SYMS

MODE='M1_DEDICATED_APPROVED'
POLICY=dict(mode=MODE,daily_loss=.02,drawdown=.10,max_asset=.315,max_gross=.90,max_risk_batches_per_UTC_day=3,max_M1_episodes_per_UTC_day=1,normal_cooldown_seconds=79200,normal_risk_rebalances_per_day=1)

def original(path):
    db=sqlite3.connect(path)
    db.executescript('''CREATE TABLE state(id INTEGER PRIMARY KEY,payload TEXT);
    CREATE TABLE orders(id INTEGER PRIMARY KEY,bar TEXT,symbol TEXT,action TEXT,weight REAL,notional REAL,fee REAL,status TEXT,quantity REAL,price REAL,recorded_at TEXT,decision_hash TEXT,market_hash TEXT,realized_pnl REAL);
    CREATE TABLE marks(bar TEXT,symbol TEXT,price REAL,PRIMARY KEY(bar,symbol));
    CREATE TABLE funding_events(symbol TEXT,timestamp_ms INTEGER,rate REAL,quantity REAL,reference_mark REAL,amount REAL,PRIMARY KEY(symbol,timestamp_ms));
    CREATE TABLE equity_history(bar TEXT PRIMARY KEY,equity REAL,pnl REAL);
    CREATE TABLE archived_claims(id TEXT PRIMARY KEY,payload TEXT);''')
    s=state();s['last_success_at']=T.isoformat()
    db.execute('INSERT INTO state VALUES(1,?)',(json.dumps(s),))
    for symbol in SYMS:
        db.execute("INSERT INTO orders VALUES(NULL,?,?, 'BUY',.1,1000,0,'filled',10,100,?,'old-decision','old-market',0)",(T.isoformat(),symbol,T.isoformat()))
        db.execute('INSERT INTO marks VALUES(?,?,100)',(T.isoformat(),symbol))
    db.execute('INSERT INTO equity_history VALUES(?,10000,0)',(T.isoformat(),));db.execute("INSERT INTO archived_claims VALUES('old','never usable')")
    db.commit();db.close()

class M1Tests(unittest.TestCase):
    def test_real_canonical_weights_and_cached_baseline_are_decoded(self):
        weights={s:'0.1' for s in SYMS}
        control={'baseline_day':(T.date()-dt.timedelta(days=1)).isoformat(),'baseline_targets':weights}
        self.runner.baseline(control,T)
        self.assertEqual(control['baseline_targets'],{s:.1 for s in SYMS})
        for invalid in ('NaN','0.10','Infinity'):
            with self.assertRaises(ValueError):self.runner.decode_targets({s:invalid for s in SYMS})

    def test_runtime_upgrade_is_explicit_preserves_initial_identity_and_restarts(self):
        old=self.runner.meta('identity');proto=json.loads(self.proto.read_text());proto['runtime_note']='canonical decoding correction'
        self.proto.write_text(json.dumps(proto));self.runner.close()
        with self.assertRaisesRegex(ValueError,'continuation_identity_changed'):m.Runner(self.config)
        target=dict(seed=old['seed'],protocol=m.shared.sha(self.proto),runner=m.shared.sha(m.__file__))
        upgrade=dict(scope='M1_CANONICAL_WEIGHT_DECODE_CORRECTION',account=self.receipt['account_id'],from_identity=old,to_identity=target,
                     authorized_at=T.isoformat(),owner_reference='synthetic explicit approval fixture',backup_sha256='a'*64)
        f=self.root/'upgrade.json';f.write_text(json.dumps(upgrade));self.config['runtime_upgrade']=str(f)
        self.runner=m.Runner(self.config)
        self.assertEqual(self.runner.meta('identity'),old)
        self.assertEqual(self.runner.db.execute("select count(*) from m1_meta where key like 'runtime_upgrade:%'").fetchone()[0],1)
        self.runner.close();self.runner=m.Runner(self.config)
        self.assertEqual(self.runner.db.execute("select count(*) from m1_meta where key like 'runtime_upgrade:%'").fetchone()[0],1)
        bad=dict(upgrade,account='other-account');f.write_text(json.dumps(bad))
        with self.assertRaisesRegex(ValueError,'runtime_upgrade_binding'):m.Runner(self.config)

    def test_canonical_daily_intent_executes_once_before_deadline(self):
        s=self.current();control=self.runner.meta('control')
        self.runner.intent(control,'DAILY',{s:'0.05' for s in SYMS},T,T,T+dt.timedelta(seconds=120))
        at=T+dt.timedelta(seconds=40)
        r=self.market(at)
        with patch.object(m.source,'now',return_value=at),self.runner.db:
            updated=self.runner.execute_pending(s,control,r,at,None)
        self.assertIsNone(control['pending']);self.assertEqual(control['last_action']['status'],'FILLED')
        n=self.runner.db.execute('select count(*) from m1_fills').fetchone()[0]
        self.runner.execute_pending(updated,control,r,at,None)
        self.assertEqual(self.runner.db.execute('select count(*) from m1_fills').fetchone()[0],n)

    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.root=Path(self.tmp.name);self.original=self.root/'original.sqlite';original(self.original)
        self.clock=patch.object(m.source,'now',return_value=T);self.clock.start()
        self.receipt=m.prepare_clone(self.original,self.root/'clone');self.clone=self.root/'clone'
        proto=dict(universe=SYMS,risk_policy=POLICY,permissions=dict(real_orders=False,operational_grants=False,modify_existing=False,issuer_executor_link=False),source_code_pins={})
        self.proto=self.root/'protocol.json';self.proto.write_text(json.dumps(proto))
        self.config=dict(protocol=str(self.proto),seed=str(self.clone/'seed.sqlite'),receipt=str(self.clone/'clone-receipt.json'),original=str(self.original),db=str(self.clone/'account.sqlite'),repo=str(self.root),derivation=dict(source=str(self.root)))
        self.runner=m.Runner(self.config,initialize=True)
    def tearDown(self):self.runner.close();self.clock.stop();self.tmp.cleanup()
    def current(self):return json.loads(self.runner.db.execute('SELECT payload FROM state').fetchone()[0])
    def market(self,at):
        r=record(at)
        for q in r['quotes'].values():q['funding_interval_ms']=86400000
        r['record_hash']=m.p.digest({k:v for k,v in r.items() if k!='record_hash'})
        return r
    def tick(self,at,features=None):
        r=self.market(at)
        def baseline(c,now):c.update(baseline_targets={s:.1 for s in SYMS},baseline_day='fixture')
        rows=[dict(time=1,prices={s:100 for s in SYMS},source_times={s:1 for s in SYMS})]*289
        with patch.object(m.source,'now',return_value=at),patch.object(m.source,'owned_json',return_value=r),patch.object(self.runner,'baseline',side_effect=baseline),patch.object(m.causal,'read_window',return_value=rows if features else None),patch.object(m.causal.detector,'features',return_value=features):
            self.runner.tick(at)
    def test_full_clone_risk_history_and_no_reset(self):
        self.assertEqual(self.runner.parent,self.current());self.assertEqual(self.runner.db.execute('SELECT * FROM archived_claims').fetchone()[1],'never usable')
        self.assertEqual(self.runner.receipt['tables'],m.describe(self.runner.seed)[0])
        self.assertNotEqual((self.clone/'seed.sqlite').stat().st_ino,(self.clone/'account.sqlite').stat().st_ino)
        self.assertEqual(self.receipt['inherited_risk'],state()['risk_policy_state'])
        before=m.shared.sha(self.original);self.runner.close();self.runner=m.Runner(self.config)
        self.assertEqual(m.shared.sha(self.original),before)
        with self.assertRaisesRegex(ValueError,'missing_no_reset'):m.Runner(dict(self.config,db=str(self.root/'missing')))
        with self.assertRaisesRegex(ValueError,'reset_refused'):m.Runner(self.config,initialize=True)
    def test_reversal_exact_quantity_single_depth_and_fees(self):
        s=state();s['positions']['BTCUSDT']['quantity']=.03;s['positions']['ETHUSDT']['quantity']=0
        before=copy.deepcopy(s);quotes=self.market(T)['quotes'];targets={'BTCUSDT':-.03,'ETHUSDT':0}
        after,fills,out=m.apply_weights(s,quotes,{},T,'M1_ENTRY',MODE,{},exact_targets=targets)
        self.assertEqual(s,before);self.assertAlmostEqual(fills[0]['quantity'],-.06);self.assertAlmostEqual(after['positions']['BTCUSDT']['quantity'],-.03)
        self.assertAlmostEqual(fills[0]['fee'],abs(.06*fills[0]['price'])*.0006)
        self.assertEqual(after['risk_policy_state']['daily_entries'],1)
        quotes['BTCUSDT']['bids'][0]['base_quantity']=.04
        after,fills,out=m.apply_weights(s,quotes,{},T,'M1_ENTRY',MODE,{},exact_targets=targets)
        self.assertEqual(after['positions']['BTCUSDT']['quantity'],0);self.assertTrue(all(f['protective'] for f in fills));self.assertEqual(out['entry_block'],'m1_market_veto')
    def test_three_batches_and_preserved_normal_clock(self):
        s=state();r=s['risk_policy_state'];r.update(daily_entries=1,last_increase_at=T.isoformat());c=dict(normal_day=T.date().isoformat(),last_normal_at=T.isoformat())
        self.assertIsNone(m.risk_gate(s,T,'M1_ENTRY',MODE,c));self.assertTrue(m.risk_gate(s,T,'DAILY',MODE,c))
        r['daily_entries']=3;self.assertTrue(m.risk_gate(s,T,'REENTRY',MODE,c))
        self.assertTrue(m.risk_gate(s,T,'M1_ENTRY','INHERIT_STRICT',c))
        peak=r['high_water'];m.risk_gate(s,T+dt.timedelta(days=1),'STATUS',MODE,c)
        self.assertEqual(r['daily_entries'],0);self.assertEqual(r['high_water'],peak)
    def test_loss_or_funding_veto_still_closes_long(self):
        for debt in ('funding_missing',None):
            s=state()
            if not debt:s['risk_policy_state']['daily_start']=11000
            after,fills,out=m.apply_weights(s,self.market(T)['quotes'],{a:-.1 for a in SYMS},T,'M1_ENTRY',MODE,{},debt,exact_targets={a:-10 for a in SYMS})
            self.assertTrue(out['entry_block']);self.assertTrue(all(x['protective'] for x in fills));self.assertTrue(all(v['quantity']==0 for v in after['positions'].values()))
    def test_future_intent_restart_atomicity_and_expiry(self):
        first=m.p.timestamp(self.runner.activation['first_signal_slot']);feature=dict(btc_60m=-.02,negative_breadth=1.)
        self.tick(first+dt.timedelta(seconds=20),feature)
        self.assertEqual(self.runner.meta('control')['phase'],'PENDING_ENTRY');self.assertEqual(self.runner.db.execute('SELECT COUNT(*) FROM m1_fills').fetchone()[0],0)
        self.runner.close();self.runner=m.Runner(self.config)
        due=first+dt.timedelta(minutes=5,seconds=20);before=self.current()
        self.runner.db.execute("CREATE TRIGGER fail_commit BEFORE UPDATE ON state BEGIN SELECT RAISE(ABORT,'storage fault'); END;")
        with self.assertRaises(sqlite3.IntegrityError):self.tick(due,feature)
        self.assertEqual(self.current(),before);self.assertEqual(self.runner.db.execute('SELECT COUNT(*) FROM m1_fills').fetchone()[0],0)
        self.runner.db.execute('DROP TRIGGER fail_commit');self.tick(due,feature)
        self.assertEqual(self.runner.meta('control')['phase'],'ACTIVE');count=self.runner.db.execute('SELECT COUNT(*) FROM m1_fills').fetchone()[0];self.assertEqual(count,2)
        self.tick(due,feature);self.assertEqual(count,self.runner.db.execute('SELECT COUNT(*) FROM m1_fills').fetchone()[0])
        self.assertTrue(all(v['quantity']==-10 for v in self.current()['positions'].values()))
        late=due+dt.timedelta(hours=6);self.tick(late);self.tick(late+dt.timedelta(seconds=20))
        self.assertEqual(self.runner.meta('control')['phase'],'REENTRY_PENDING');self.assertTrue(all(v['quantity']==0 for v in self.current()['positions'].values()))
        # No stale-basket reentry on the closing book.
        self.assertEqual(self.runner.db.execute('SELECT COUNT(*) FROM m1_fills').fetchone()[0],4)
        self.tick(late+dt.timedelta(seconds=40));self.assertEqual(self.runner.meta('control')['phase'],'NORMAL')
        self.assertEqual(self.current()['risk_policy_state']['daily_entries'],2)
        self.tick(late+dt.timedelta(hours=1),feature)
        self.assertEqual(self.runner.db.execute('SELECT COUNT(*) FROM m1_episodes').fetchone()[0],1)
    def test_expired_entry_never_backfilled(self):
        first=m.p.timestamp(self.runner.activation['first_signal_slot']);feat=dict(btc_60m=-.02,negative_breadth=1.)
        self.tick(first,feat);self.tick(first+dt.timedelta(minutes=8),feat)
        self.assertEqual(self.runner.db.execute('SELECT status FROM m1_episodes').fetchone()[0],'ENTRY_MISSED')
        self.assertEqual(self.runner.db.execute('SELECT COUNT(*) FROM m1_fills').fetchone()[0],0)
    def test_stale_or_altered_book_and_policy_refusal(self):
        r=self.market(T);r['quotes']['BTCUSDT']['mark_price']=1
        with self.assertRaisesRegex(ValueError,'market_hash'):m.shared.verified_market(r,SYMS,T)
        with self.assertRaises(ValueError):m.shared.verified_market(self.market(T),SYMS,T+dt.timedelta(hours=1))
        proto=json.loads(self.proto.read_text());proto['risk_policy']['max_gross']=2;self.proto.write_text(json.dumps(proto))
        with self.assertRaisesRegex(ValueError,'unsupported_policy'):m.Runner(self.config)
    def test_funding_partial_batch_rollback_and_mark_requirement(self):
        s=self.current();r=self.market(T+dt.timedelta(minutes=10))
        for q in r['quotes'].values():q['funding'].append(dict(timestamp_ms=int((T+dt.timedelta(minutes=1)).timestamp()*1000),rate=.001))
        with self.runner.db:
            updated=self.runner.funding(s,r)
        self.assertEqual(updated['positions']['BTCUSDT']['funding'],-1.)
        self.assertEqual(s,self.current());self.assertEqual(self.runner.db.execute('SELECT COUNT(*) FROM funding_events').fetchone()[0],2)
        r['quotes']['ETHUSDT']['funding']=[]
        with self.assertRaisesRegex(ValueError,'coverage'):
            with self.runner.db:self.runner.funding(s,r)
        self.assertEqual(self.runner.db.execute('SELECT COUNT(*) FROM funding_events').fetchone()[0],2)
    def test_one_episode_day_and_slow_derivation_misses_without_trade(self):
        first=m.p.timestamp(self.runner.activation['first_signal_slot']);feat=dict(btc_60m=-.02,negative_breadth=1.)
        control=self.runner.meta('control');control['episode_day']=first.date().isoformat()
        with self.runner.db:self.runner.put('control',control)
        self.tick(first+dt.timedelta(seconds=20),feat)
        self.assertEqual(self.runner.db.execute("SELECT status FROM m1_slots WHERE kind='M1'").fetchone()[0],'DAILY_EPISODE_LIMIT')
        self.assertEqual(self.runner.db.execute('SELECT COUNT(*) FROM m1_episodes').fetchone()[0],0)
        # A derivation that completes after the deadline must not schedule a historical signal.
        nextslot=first+dt.timedelta(minutes=5);r=self.market(nextslot)
        rows=[dict(time=1,prices={s:100 for s in SYMS},source_times={s:1 for s in SYMS})]*289
        with patch.object(m.source,'owned_json',return_value=r),patch.object(self.runner,'baseline'),patch.object(m.causal,'read_window',return_value=rows),patch.object(m.causal.detector,'features',return_value=feat),patch.object(m.source,'now',return_value=nextslot+dt.timedelta(minutes=3)):
            self.runner.tick(nextslot)
        self.assertEqual(self.runner.db.execute("SELECT status FROM m1_slots WHERE kind='M1' ORDER BY slot DESC").fetchone()[0],'MISSED')
        self.assertEqual(self.runner.db.execute('SELECT COUNT(*) FROM m1_fills').fetchone()[0],0)
    def test_projection_custody_scope_and_fixed_common_denominator(self):
        import os
        path=self.root/'projection.json';value=dict(scope='AUTONOMOUS_M1_PAPER_RESEARCH_ONLY',arm='M1',schema=1,generated_at=T.isoformat())
        path.write_text(json.dumps(value));path.chmod(0o640)
        with patch.object(view,'UID',os.geteuid()):
            self.assertFalse(view.public(path,T)['stale'])
            self.assertTrue(view.public(path,T+dt.timedelta(minutes=4))['stale'])
            with self.assertRaisesRegex(ValueError,'future'):view.public(path,T-dt.timedelta(seconds=1))
            value['scope']='EXECUTION';path.write_text(json.dumps(value))
            with self.assertRaisesRegex(ValueError,'scope'):view.public(path,T)
        base=dict(available=True,variants={k:dict(metrics=dict(equity=10100)) for k in ('ORIGINAL','FAST','HALF')},receipt=dict(economic_t0=T.isoformat()))
        fourth=dict(stale=False,variant=dict(metrics=dict(equity=10100)),comparison_reference=dict(points={k:dict(equity=10000,at=T.isoformat()) for k in ('ORIGINAL','FAST','HALF','M1')}))
        with patch.object(view.legacy,'load',return_value=base),patch.object(view,'public',return_value=fourth):result=view.load(now=T)
        for v in result['variants'].values():self.assertAlmostEqual(v['common_change_pct'],1.)
        self.assertNotIn('common_change_pct',base['variants']['FAST'])
    def test_missing_fourth_cannot_break_three_existing(self):
        base=dict(available=True,variants={k:dict(metrics=dict(equity=10000)) for k in ('ORIGINAL','FAST','HALF')},receipt=dict(economic_t0=T.isoformat()))
        with patch.object(view.legacy,'load',return_value=base):
            result=view.load(fourth=str(self.root/'absent'))
        self.assertEqual(set(result['variants']),set(base['variants']));self.assertFalse(result['fourth_available']);self.assertNotIn('fork_at',base['variants']['FAST'])

if __name__=='__main__':unittest.main()
