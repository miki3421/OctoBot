"""Synthetic approval and same-ledger continuation tests for v2 only."""
import copy
import datetime as dt
import json
import unittest
from unittest.mock import patch
from octobot.ai_strategy_lab import v13_m1_transition as tr, v13_m1_weekly as w, v13_m1_paper as base
from tests.unit_tests.ai_strategy_lab import test_v13_m1_weekly as fixtures
full_market=fixtures.full_market
from tests.unit_tests.ai_strategy_lab.test_v13_m1_paper import T


class TransitionTests(unittest.TestCase):
    state=fixtures.ManagedTests.state
    tearDown=fixtures.ManagedTests.tearDown

    def setUp(self):
        fixtures.ManagedTests.setUp(self)
        parent=copy.deepcopy(self.p);parent['rows']={s:dict(signal=1,score=1.) for s in w.POOL}
        parent['proposal_id']=w.digest({k:v for k,v in parent.items() if k!='proposal_id'})
        with self.runner.db:
            self.runner.db.execute('DELETE FROM m1_weekly_reviews')
            self.install(parent)
        state=self.state();market=full_market(T)
        caps={s:.1 for s in state['positions']}
        c=dict(scope='OFFLINE_DESIGN_CANDIDATE_NOT_APPROVABLE_NOT_APPLIED',account=self.account,
               parent_proposal_id=parent['proposal_id'],as_of=T.isoformat(),
               maintenance=dict(reductions=[dict(symbol=s) for s in state['positions']],target_quantity_ceilings={s:5. for s in state['positions']}),
               short_budget=dict(reference_caps=caps,proposed_caps=dict(caps)))
        c['candidate_id']=w.digest(c)
        self.p=tr.proposal(c,parent,state,market,T.isoformat())
        path=self.root/'transition.json';path.write_text(json.dumps(self.p));path.chmod(0o440)
        self.runner.mc.update(transition_proposal=str(path),transition_sha256=base.shared.sha(path))

    install=fixtures.ManagedTests.install

    def tick(self,at):
        r=full_market(at);(self.root/'source/market.json').write_text(json.dumps(r))
        def baseline(instance,control,now):
            control.update(baseline_targets={s:.1 for s in instance.universe},baseline_day='fixture')
        with patch.object(base.source,'now',return_value=at),patch.object(base.Runner,'baseline',autospec=True,side_effect=baseline),patch.object(base.causal,'read_window',return_value=None):
            self.runner.tick(at)

    def approve(self,components=None):
        return self.store.record(self.p,action='APPROVE',exclude_short=[],components=components,at=T.isoformat())

    def test_no_approval_preserves_positions_and_original(self):
        before=self.state();raw=(self.root/'original.sqlite').read_bytes();self.tick(T+dt.timedelta(seconds=20))
        self.assertIsNone(self.runner.managed_policy());self.assertEqual(self.state()['order_count'],before['order_count'])
        self.assertEqual(self.runner.db.execute('SELECT COUNT(*) FROM m1_transition_reviews').fetchone()[0],1)
        self.assertEqual((self.root/'original.sqlite').read_bytes(),raw)

    def test_component_and_proposal_identity_are_mandatory(self):
        for choices in (None,[],['LONG_MAINTENANCE','ADMISSIONS']):
            with self.assertRaises(ValueError):self.approve(choices)
        d=self.approve(list(tr.COMPONENTS));self.assertEqual(d,self.approve(list(tr.COMPONENTS)))
        bad=dict(d,proposal_id='0'*64);bad['decision_id']=w.digest({k:v for k,v in bad.items() if k!='decision_id'})
        with self.assertRaises(ValueError):w.approved_policy(self.p,bad,0,T.isoformat())

    def test_actual_reduction_keeps_short_budget_and_original_cadence(self):
        self.approve(list(tr.COMPONENTS))
        with patch.object(w,'weights',side_effect=AssertionError('Extra managed daily recalculation forbidden')):
            self.tick(T+dt.timedelta(seconds=20));self.tick(T+dt.timedelta(seconds=60))
        state=self.state();policy=self.runner.managed_policy()
        self.assertEqual(policy['short_caps'],self.p['short_caps'])
        self.assertTrue(all(v['quantity']<=5 for v in state['positions'].values()))
        self.assertEqual(policy['cadence'],'ORIGINAL_PUBLISHED_BASELINE')
        self.assertTrue(self.runner.db.execute('SELECT COUNT(*) FROM m1_fills').fetchone()[0]>0)

    def test_restart_and_price_fall_cannot_rebuy_or_restore_long(self):
        self.approve(list(tr.COMPONENTS));self.tick(T+dt.timedelta(seconds=20));self.tick(T+dt.timedelta(seconds=60))
        from octobot.ai_strategy_lab.v13_m1_managed import Runner
        self.runner.close();self.runner=Runner(self.c)
        state=self.state();policy=self.runner.managed_policy();q=full_market(T+dt.timedelta(seconds=80))['quotes']
        for quote in q.values():quote['mark_price']=50.
        quantities,updated=w.targets(state,policy,{s:.3 for s in state['positions']},q,kind='REENTRY')
        self.assertTrue(all(v<=5 for v in quantities.values()))
        zero,updated=w.targets(state,updated,{s:0. for s in state['positions']},q,kind='DAILY')
        restored,_=w.targets(state,updated,{s:.3 for s in state['positions']},q,kind='REENTRY')
        self.assertTrue(all(v==0 for v in restored.values()))
        shorts,_=w.targets(state,updated,{},q,kind='M1_ENTRY')
        self.assertTrue(all(v<0 for v in shorts.values()))

    def test_ceiling_tampering_rejected_after_restart(self):
        self.approve(list(tr.COMPONENTS));self.tick(T+dt.timedelta(seconds=20))
        policy=self.runner.managed_policy();symbol=next(iter(policy['quantity_ceilings']));policy['quantity_ceilings'][symbol]=99.
        with self.runner.db:self.runner.put('management_policy',policy)
        with self.assertRaisesRegex(ValueError,'ceiling_increased'):self.runner.managed_policy()

    def test_next_day_original_canonical_string_weights_are_decoded(self):
        self.approve(list(tr.COMPONENTS));self.tick(T+dt.timedelta(seconds=20))
        control=self.runner.meta('control');at=T+dt.timedelta(days=1)
        with patch.object(self.runner,'prepare_input',return_value=dict(targets={s:base.p.encode_weight(.1) for s in self.runner.universe},proposal_id='fixture-original-published')):
            self.runner.baseline(control,at)
        self.assertTrue(all(v==.1 for v in control['baseline_targets'].values()))
        self.assertEqual(control['proposal_id'],'fixture-original-published')
        self.assertEqual(control['managed_reference'],self.p['short_caps'])

    def test_crash_rolls_back_policy_decision_consumption_and_orders(self):
        self.approve(list(tr.COMPONENTS));before=self.state()
        self.runner.db.execute("CREATE TRIGGER fault BEFORE UPDATE ON state BEGIN SELECT RAISE(ABORT,'fixture crash'); END")
        import sqlite3
        with self.assertRaises(sqlite3.IntegrityError):self.tick(T+dt.timedelta(seconds=20))
        self.assertEqual(self.state(),before);self.assertIsNone(self.runner.managed_policy())
        self.assertEqual(self.runner.db.execute('SELECT COUNT(*) FROM m1_management_consumed').fetchone()[0],0)


if __name__=='__main__':unittest.main()
