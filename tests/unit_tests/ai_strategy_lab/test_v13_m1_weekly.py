"""Synthetic-only accounting, review authority and continuation failure tests."""
import copy
import datetime as dt
import hashlib
import json
import os
from pathlib import Path
import sqlite3
import tempfile
import unittest
from unittest.mock import patch
from octobot.ai_strategy_lab import v13_m1_weekly as w
from octobot.ai_strategy_lab import v13_m1_approval_broker as broker
from octobot.ai_strategy_lab import v13_m1_managed as managed
from octobot.ai_strategy_lab import v13_m1_paper as base
from tests.unit_tests.ai_strategy_lab.test_v13_m1_paper import original,POLICY,T,SYMS
from tests.unit_tests.ai_strategy_lab.test_v13_fork_runner import record


def science(at=T):
    day=at.date()-dt.timedelta(days=1)
    import math
    result=dict(scope='M1_WEEKLY_CAUSAL_DAILY_V1',day=day.isoformat(),published_at=at.isoformat(),bars={})
    for index,s in enumerate(w.POOL):
        result['bars'][s]=[dict(day=(day-dt.timedelta(days=120-i)).isoformat(),close=80+i*(.1+index*.005)+.3*math.sin(i*.7+index),received_at=at.isoformat()) for i in range(121)]
    result['snapshot_id']=w.digest(result);return result


def full_market(at=T):
    r=record(at);q=copy.deepcopy(r['quotes']['BTCUSDT'])
    r['quotes']={s:dict(copy.deepcopy(q),symbol=s) for s in w.POOL};r['capture_ids']=[]
    r['record_hash']=w.digest({k:v for k,v in r.items() if k!='record_hash'});return r


def fixed_proposal(account='fixture-m1',at=T,revision=0):
    caps={s:0. for s in w.POOL};caps['BTCUSDT']=.05
    shorts={s:0. for s in w.POOL};shorts.update(BTCUSDT=.10,ETHUSDT=.10)
    p=dict(version=w.VERSION,scope='M1_RESEARCH_PAPER_WEEKLY_PROPOSAL',account=account,parent_revision=revision,
           week=w.week(at.isoformat()),created_at=at.isoformat(),expires_at=(at+dt.timedelta(hours=48)).isoformat(),
           previous=list(SYMS),selected=['BTCUSDT'],long_caps=caps,short_caps=shorts)
    p['proposal_id']=w.digest(p);return p


class RuleTests(unittest.TestCase):
    def test_real_selector_kernel_runs_with_frozen_causal_bars(self):
        sc=science();p=w.proposal(sc,full_market(),account='fixture-m1',revision=0,previous=SYMS,
                               positions={s:dict(quantity=10,current_price=100) for s in SYMS},equity=10000,at=T.isoformat())
        self.assertLessEqual(len(p['selected']),18)
        self.assertLessEqual(len(set(p['selected'])-set(SYMS)),2)
        self.assertLessEqual(sum(p['long_caps'].values()),.9000001)
        self.assertLessEqual(sum(p['short_caps'].values()),.9000001)
        self.assertFalse(p['execution_authorized']);w.verify(p,'proposal_id')

    def test_missing_incumbent_history_is_not_a_forced_exit(self):
        sc=science();del sc['bars']['ETHUSDT'];sc['snapshot_id']=w.digest({k:v for k,v in sc.items() if k!='snapshot_id'})
        with self.assertRaisesRegex(ValueError,'incumbent_history'):
            w.proposal(sc,full_market(),account='fixture',revision=0,previous=SYMS,positions={},equity=10000,at=T.isoformat())

    def test_unavailable_future_bar_and_changed_snapshot_are_rejected(self):
        sc=science();sc['bars']['BTCUSDT'][-1]['received_at']=(T+dt.timedelta(seconds=1)).isoformat();sc['snapshot_id']=w.digest({k:v for k,v in sc.items() if k!='snapshot_id'})
        with self.assertRaisesRegex(ValueError,'BTC_history'):w.signals(sc,T.isoformat())
        sc=science();sc['day']='2020-01-01'
        with self.assertRaisesRegex(ValueError,'snapshot_id'):w.signals(sc,T.isoformat())

    def test_weekly_anchor_does_not_depend_on_subsequent_prices(self):
        self.assertEqual(w.week('2026-10-23T13:00:00+00:00'),'2026-10-19T00:15:00+00:00')
        self.assertEqual(w.week('2026-10-26T00:14:59+00:00'),'2026-10-19T00:15:00+00:00')


class ApprovalTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.root=Path(self.tmp.name)
        self.store=broker.Store(self.root/'approvals.sqlite','fixture-m1')
    def tearDown(self):self.store.close();self.tmp.cleanup()

    def decision(self,p=None,action='APPROVE',excluded=None,at=T):
        return self.store.record(p or fixed_proposal(),action=action,exclude_short=excluded or [],at=at.isoformat())

    def test_approval_binds_account_revision_expiry_and_short_side_choice(self):
        p=fixed_proposal();d=self.decision(p);policy=w.approved_policy(p,d,0,T.isoformat())
        self.assertEqual(policy['long_caps']['ETHUSDT'],0)
        self.assertEqual(policy['short_caps']['ETHUSDT'],.1)
        for changed in ('account','proposal_id'):
            bad=dict(d);bad[changed]='wrong';bad['decision_id']=w.digest({k:v for k,v in bad.items() if k!='decision_id'})
            with self.assertRaises(ValueError):w.approved_policy(p,bad,0,T.isoformat())
        with self.assertRaises(ValueError):w.approved_policy(p,d,1,T.isoformat())
        with self.assertRaises(ValueError):w.approved_policy(p,d,0,(T+dt.timedelta(days=3)).isoformat())

    def test_replay_is_idempotent_and_conflicting_decision_denied(self):
        d=self.decision();self.assertEqual(d,self.decision(at=T+dt.timedelta(seconds=10)))
        self.assertEqual(self.store.db.execute('SELECT COUNT(*) FROM decisions').fetchone()[0],1)
        with self.assertRaises(ValueError):self.decision(action='REJECT')
        with self.assertRaises(ValueError):self.decision(excluded=['QNTUSDT'])

    def test_explicit_short_exclusion_and_password_verifier(self):
        p=fixed_proposal();d=self.decision(p,excluded=['ETHUSDT']);policy=w.approved_policy(p,d,0,T.isoformat())
        self.assertEqual(policy['short_caps']['ETHUSDT'],0)
        salt=b'synthetic-salt-only';pw='fixture-only-password-123'
        verifier=dict(salt=salt.hex(),scrypt=hashlib.scrypt(pw.encode(),salt=salt,n=16384,r=8,p=1,dklen=32).hex())
        self.assertTrue(broker.password_valid(pw,verifier));self.assertFalse(broker.password_valid('wrong-password',verifier))

    def test_expired_approval_does_not_block_a_later_review_forever(self):
        self.decision();later=T+dt.timedelta(days=7);p=fixed_proposal(at=later)
        decision=self.decision(p,at=later)
        self.assertEqual(decision['parent_revision'],0)
        self.assertEqual(self.store.db.execute('SELECT COUNT(*) FROM decisions').fetchone()[0],2)

    def test_unexpired_conflicting_review_and_malformed_budgets_denied(self):
        self.decision();p=fixed_proposal(at=T+dt.timedelta(seconds=10))
        with self.assertRaises(ValueError):self.decision(p,at=T+dt.timedelta(seconds=20))
        p=fixed_proposal(at=T+dt.timedelta(days=7));p['long_caps']['ETHUSDT']=.1
        p['proposal_id']=w.digest({k:v for k,v in p.items() if k!='proposal_id'})
        with self.assertRaisesRegex(ValueError,'long_cap_outside'):self.decision(p,at=T+dt.timedelta(days=7))


class ManagedTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.root=Path(self.tmp.name);original(self.root/'original.sqlite')
        self.clock=patch.object(base.source,'now',return_value=T);self.clock.start()
        base.prepare_clone(self.root/'original.sqlite',self.root/'clone')
        proto=dict(universe=SYMS,risk_policy=POLICY,permissions=dict(real_orders=False,operational_grants=False,modify_existing=False,issuer_executor_link=False),source_code_pins={})
        (self.root/'protocol.json').write_text(json.dumps(proto));(self.root/'projection').mkdir();(self.root/'source').mkdir()
        self.c=dict(protocol=str(self.root/'protocol.json'),seed=str(self.root/'clone/seed.sqlite'),receipt=str(self.root/'clone/clone-receipt.json'),original=str(self.root/'original.sqlite'),db=str(self.root/'clone/account.sqlite'),repo=str(self.root),derivation=dict(source=str(self.root/'source')),
                    management=dict(scope='M1_WEEKLY_MANAGEMENT_V1',source=str(self.root/'source'),capture_uid=os.geteuid(),approval_uid=os.geteuid(),approvals=str(self.root/'approvals.sqlite'),projection=str(self.root/'projection/management.json'),code_pins={}))
        seed=base.Runner(self.c,initialize=True);self.account=seed.account;seed.close()
        self.store=broker.Store(self.root/'approvals.sqlite',self.account);self.runner=managed.Runner(self.c)
        self.sc=science();(self.root/'source/science.json').write_text(json.dumps(self.sc))
        self.p=fixed_proposal(self.account);self.install(self.p)

    def install(self,p):
        with self.runner.db:self.runner.db.execute('INSERT INTO m1_weekly_reviews VALUES(?,?,?,\'PROPOSED\',NULL)',(p['proposal_id'],p['week'],json.dumps(p)))

    def tearDown(self):self.runner.close();self.store.close();self.clock.stop();self.tmp.cleanup()
    def state(self):return json.loads(self.runner.db.execute('SELECT payload FROM state').fetchone()[0])

    def tick(self,at):
        r=full_market(at);(self.root/'source/market.json').write_text(json.dumps(r))
        def baseline(c,now):c.update(baseline_targets={s:.10 for s in self.runner.universe},baseline_day='fixture')
        with patch.object(base.source,'now',return_value=at),patch.object(self.runner,'baseline',side_effect=baseline),patch.object(base.causal,'read_window',return_value=None):self.runner.tick(at)

    def approve(self):return self.store.record(self.p,action='APPROVE',exclude_short=[],at=T.isoformat())

    def test_approval_changes_existing_account_without_reset_and_exit_is_real(self):
        before=self.state();self.approve();self.tick(T+dt.timedelta(seconds=20));self.tick(T+dt.timedelta(seconds=60))
        state=self.state();self.assertEqual(state['positions']['ETHUSDT']['quantity'],0)
        self.assertLessEqual(state['positions']['BTCUSDT']['quantity'],5)
        self.assertGreater(state['order_count'],before['order_count'])
        self.assertEqual(state['risk_policy_state']['high_water'],before['risk_policy_state']['high_water'])
        self.assertEqual(self.runner.account,self.account)
        self.assertEqual(self.runner.meta('management_policy')['short_caps']['ETHUSDT'],.1)
        self.assertEqual(self.runner.db.execute('SELECT COUNT(*) FROM archived_claims').fetchone()[0],1)

    def test_excluded_long_cannot_be_rebought_after_restart_or_reentry(self):
        self.approve();self.tick(T+dt.timedelta(seconds=20));self.tick(T+dt.timedelta(seconds=60))
        count=self.state()['order_count'];self.runner.close();self.runner=managed.Runner(self.c)
        state=self.state();r=full_market(T+dt.timedelta(seconds=80));control=self.runner.meta('control')
        with self.runner.db:
            control['baseline_targets']={s:.30 for s in self.runner.universe}
            _,q=self.runner.pending_targets(state,control,r,'REENTRY',control['baseline_targets'],None)
            self.assertEqual(q['ETHUSDT'],0)
        self.assertEqual(self.state()['order_count'],count)
        self.assertEqual(self.runner.meta('management_policy')['short_caps']['ETHUSDT'],.1)

    def test_crash_rolls_back_approval_consumption_policy_and_orders(self):
        self.approve();before=self.state()
        self.runner.db.execute("CREATE TRIGGER fault BEFORE UPDATE ON state BEGIN SELECT RAISE(ABORT,'fixture crash'); END")
        with self.assertRaises(sqlite3.IntegrityError):self.tick(T+dt.timedelta(seconds=20))
        self.assertEqual(self.state(),before);self.assertIsNone(self.runner.meta('management_policy'))
        self.assertEqual(self.runner.db.execute('SELECT COUNT(*) FROM m1_management_consumed').fetchone()[0],0)
        self.runner.db.execute('DROP TRIGGER fault');self.tick(T+dt.timedelta(seconds=40))
        self.assertEqual(self.runner.meta('management_policy')['revision'],1)

    def test_no_approval_no_portfolio_change_and_original_never_written(self):
        original_bytes=(self.root/'original.sqlite').read_bytes();before=self.state()['order_count']
        self.tick(T+dt.timedelta(seconds=20));self.assertIsNone(self.runner.meta('management_policy'))
        self.assertEqual(self.state()['order_count'],before)
        self.assertEqual((self.root/'original.sqlite').read_bytes(),original_bytes)

    def test_short_budget_is_usable_after_excluding_the_long(self):
        self.approve();self.tick(T+dt.timedelta(seconds=20));self.tick(T+dt.timedelta(seconds=60))
        state=self.state();control=self.runner.meta('control');control['managed_reference']={s:.1 for s in SYMS}
        self.assertEqual(state['positions']['ETHUSDT']['quantity'],0)
        self.assertTrue(self.runner.has_overlay_budget(state,control))
        entries,overlay=self.runner.entry_plan(state,control)
        self.assertLess(entries['ETHUSDT'],-9.9);self.assertIn('ETHUSDT',overlay)
        at=T+dt.timedelta(seconds=100);r=full_market(at)
        r['quotes']={s:r['quotes'][s] for s in self.runner.universe};r['record_hash']=w.digest({k:v for k,v in r.items() if k!='record_hash'})
        control.update(entry_quantities=entries,overlay_symbols=overlay,episode='fixture-episode',phase='PENDING_ENTRY')
        with self.runner.db:self.runner.db.execute('INSERT INTO m1_episodes VALUES(?,?,?,?,?,?)',('fixture-episode',at.isoformat(),at.isoformat(),(at+dt.timedelta(hours=6)).isoformat(),'PENDING_ENTRY','{}'))
        self.runner.intent(control,'M1_ENTRY',None,T+dt.timedelta(seconds=80),T+dt.timedelta(seconds=80))
        with patch.object(base.source,'now',return_value=at),self.runner.db:
            updated=self.runner.execute_pending(state,control,r,at,None)
        self.assertLess(updated['positions']['ETHUSDT']['quantity'],-9.9)

    def test_actual_daily_after_restart_does_not_buy_an_excluded_coin(self):
        self.approve();self.tick(T+dt.timedelta(seconds=20));self.tick(T+dt.timedelta(seconds=60))
        self.runner.close();self.runner=managed.Runner(self.c)
        at=(T+dt.timedelta(days=1)).replace(hour=0,minute=15,second=30)
        r=full_market(at)
        for q in r['quotes'].values():q['funding_interval_ms']=86400000
        r['quotes']={s:r['quotes'][s] for s in self.runner.universe}
        r['record_hash']=w.digest({k:v for k,v in r.items() if k!='record_hash'})
        state=self.state();control=self.runner.meta('control');control['baseline_targets']={s:.30 for s in SYMS}
        self.runner.intent(control,'DAILY',control['baseline_targets'],at-dt.timedelta(seconds=10),at-dt.timedelta(seconds=10))
        with patch.object(base.source,'now',return_value=at),self.runner.db:
            updated=self.runner.execute_pending(state,control,r,at,None)
        self.assertEqual(updated['positions']['ETHUSDT']['quantity'],0)
        self.assertIsNone(control['last_action']['entry_block'])
        self.assertFalse(any(f['symbol']=='ETHUSDT' and f['quantity']>0 for f in [json.loads(x[0]) for x in self.runner.db.execute('SELECT payload FROM m1_fills')]))

    def test_missing_retired_flat_quote_does_not_block_the_held_basket(self):
        self.store.record(self.p,action='APPROVE',exclude_short=['ETHUSDT'],at=T.isoformat())
        self.tick(T+dt.timedelta(seconds=20));self.tick(T+dt.timedelta(seconds=60))
        r=full_market(T+dt.timedelta(seconds=80));del r['quotes']['ETHUSDT'];r['record_hash']=w.digest({k:v for k,v in r.items() if k!='record_hash'})
        (self.root/'source/market.json').write_text(json.dumps(r))
        with patch.object(base.source,'now',return_value=T+dt.timedelta(seconds=80)):
            projected=self.runner.market_record(T+dt.timedelta(seconds=80))
        self.assertNotIn('ETHUSDT',projected['quotes']);self.assertIn('BTCUSDT',projected['quotes'])

    def test_new_admission_is_flat_until_daily_and_receives_a_real_fill(self):
        with self.runner.db:self.runner.db.execute('DELETE FROM m1_weekly_reviews')
        p=copy.deepcopy(self.p);p['selected'].append('QNTUSDT');p['long_caps']['QNTUSDT']=.05
        p['proposal_id']=w.digest({k:v for k,v in p.items() if k!='proposal_id'});self.p=p;self.install(p)
        self.approve();self.tick(T+dt.timedelta(seconds=20));self.tick(T+dt.timedelta(seconds=60))
        self.assertEqual(self.state()['positions']['QNTUSDT']['quantity'],0)
        self.assertEqual(self.runner.db.execute("SELECT COUNT(*) FROM m1_management_admissions WHERE symbol='QNTUSDT'").fetchone()[0],1)
        self.runner.close();self.runner=managed.Runner(self.c)
        at=(T+dt.timedelta(days=1)).replace(hour=0,minute=15,second=30)
        r=full_market(at);r['quotes']={s:r['quotes'][s] for s in self.runner.universe}
        for q in r['quotes'].values():q['funding_interval_ms']=86400000
        r['record_hash']=w.digest({k:v for k,v in r.items() if k!='record_hash'})
        state=self.state();control=self.runner.meta('control');control['baseline_targets']={s:.10 for s in self.runner.universe}
        self.runner.intent(control,'DAILY',control['baseline_targets'],at-dt.timedelta(seconds=10),at-dt.timedelta(seconds=10))
        with patch.object(base.source,'now',return_value=at),self.runner.db:updated=self.runner.execute_pending(state,control,r,at,None)
        self.assertGreater(updated['positions']['QNTUSDT']['quantity'],0)
        fills=[json.loads(x[0]) for x in self.runner.db.execute("SELECT payload FROM m1_fills WHERE symbol='QNTUSDT'")]
        self.assertTrue(fills);self.assertEqual(fills[0]['maintenance']['proposal_id'],p['proposal_id'])
        events=[json.loads(x[0]) for x in self.runner.db.execute('SELECT payload FROM m1_management_events ORDER BY rowid')]
        previous=None
        for e in events:
            self.assertEqual(e['previous_id'],previous);previous=w.digest(e)

    def test_funding_debt_prevents_a_new_admission_without_consuming_approval(self):
        with self.runner.db:self.runner.db.execute('DELETE FROM m1_weekly_reviews')
        p=copy.deepcopy(self.p);p['selected'].append('QNTUSDT');p['long_caps']['QNTUSDT']=.05
        p['proposal_id']=w.digest({k:v for k,v in p.items() if k!='proposal_id'});self.p=p;self.install(p);self.approve()
        r=full_market(T+dt.timedelta(seconds=20));self.runner.full_market=r
        state=self.state();control=self.runner.meta('control')
        with self.runner.db:self.runner.management_cycle(state,control,r,T+dt.timedelta(seconds=20),'funding_gap')
        self.assertNotIn('QNTUSDT',state['positions']);self.assertIsNone(self.runner.meta('management_policy'))
        self.assertEqual(self.runner.db.execute('SELECT COUNT(*) FROM m1_management_consumed').fetchone()[0],0)
        self.assertEqual(self.runner.db.execute('SELECT status FROM m1_weekly_reviews').fetchone()[0],'APPROVED_WAITING_INPUTS')

    def test_retained_overlay_budget_is_not_an_ordinary_short_admission(self):
        self.approve();self.tick(T+dt.timedelta(seconds=20));control=self.runner.meta('control')
        with patch.object(w,'weights',return_value={'BTCUSDT':.1,'ETHUSDT':0.}) as allocator:
            self.runner.baseline(control,T+dt.timedelta(seconds=30))
        self.assertEqual(allocator.call_args.args[1],['BTCUSDT'])
        self.assertEqual(control['baseline_targets']['ETHUSDT'],0)
        self.assertEqual(control['managed_reference']['ETHUSDT'],.1)

    def test_tampered_saved_policy_is_not_new_authority(self):
        self.approve();self.tick(T+dt.timedelta(seconds=20))
        policy=self.runner.meta('management_policy');policy['long_caps']['ETHUSDT']=.2
        with self.runner.db:self.runner.put('management_policy',policy)
        with self.assertRaisesRegex(ValueError,'approved_policy_changed'):self.runner.managed_policy()


if __name__=='__main__':unittest.main()
