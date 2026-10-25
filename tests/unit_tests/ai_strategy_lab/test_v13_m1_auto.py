"""Delegated approvals: economic vetoes, authority and one-use permissions."""
import copy
import datetime as dt
import sqlite3
import unittest
from unittest.mock import patch
from octobot.ai_strategy_lab import v13_m1_auto as a
from octobot.ai_strategy_lab import v13_m1_weekly as w
from .test_v13_m1_successor import fixture,weak
from .test_v13_m1_weekly import science,full_market
from .test_v13_m1_paper import T


class AutoTests(unittest.TestCase):
    def inputs(self):
        _,p,state,m=fixture();sc=science(T);prior=science(T-dt.timedelta(days=1))
        for q in m['quotes'].values():
            q['fee_rate']=.0001
            q.update(price_tick=.01,step=q['quantity_step'],contract_multiplier=q['quantity_step'],min_quantity=q['quantity_step'],min_notional=1.)
            q['bids'][0]['price']=99.99;q['asks'][0]['price']=100.01
            q['best_bid']=99.99;q['best_ask']=100.01
        m['record_hash']=w.digest({k:v for k,v in m.items() if k!='record_hash'})
        return p,state,m,sc,prior

    def test_positive_confirmed_quality_can_be_approved_without_password(self):
        p,state,m,sc,prior=self.inputs()
        r=a.assessment('QNTUSDT','ENTER',sc,prior,m,state,p,T.isoformat(),quantity=1.)
        self.assertEqual(r['status'],'APPROVED');self.assertGreaterEqual(r['score'],80)
        self.assertAlmostEqual(r['score'],sum(r['components'].values()),places=2)
        self.assertTrue(r['short_budget_unchanged'])

    def test_high_total_cannot_override_budget_veto(self):
        p,state,m,sc,prior=self.inputs()
        r=a.assessment('QNTUSDT','ENTER',sc,prior,m,state,p,T.isoformat(),quantity=1.,room=False)
        self.assertNotEqual(r['status'],'APPROVED');self.assertIn('LONG_BUDGET_OR_WEEKLY_LIMIT',r['reasons'])

    def test_missing_confirmation_is_deferred_not_assumed_positive(self):
        p,state,m,sc,prior=self.inputs()
        r=a.assessment('QNTUSDT','ENTER',sc,None,m,state,p,T.isoformat(),quantity=1.)
        self.assertEqual(r['status'],'DEFERRED');self.assertIn('WAITING_SECOND_POSITIVE_DAY',r['reasons'])
        prior=science(T-dt.timedelta(days=2))
        self.assertNotEqual(a.assessment('QNTUSDT','ENTER',sc,prior,m,state,p,T.isoformat(),quantity=1.)['status'],'APPROVED')

    def test_stale_future_and_altered_science_fail_closed(self):
        p,state,m,sc,prior=self.inputs()
        for bad in (science(T+dt.timedelta(days=1)),science(T-dt.timedelta(days=2))):
            with self.assertRaises(ValueError):a.assessment('QNTUSDT','ENTER',bad,prior,m,state,p,T.isoformat(),quantity=1.)
        sc['bars']['QNTUSDT'][-1]['close']+=10
        with self.assertRaises(ValueError):a.assessment('QNTUSDT','ENTER',sc,prior,m,state,p,T.isoformat(),quantity=1.)

    def test_missing_book_and_depth_cannot_be_free_execution(self):
        p,state,m,sc,prior=self.inputs();m['quotes']['QNTUSDT']['asks'][0]['base_quantity']=0.00001
        m['quotes']['QNTUSDT']['asks']=m['quotes']['QNTUSDT']['asks'][:1]
        m['record_hash']=w.digest({k:v for k,v in m.items() if k!='record_hash'})
        self.assertNotEqual(a.assessment('QNTUSDT','ENTER',sc,prior,m,state,p,T.isoformat(),quantity=1.)['status'],'APPROVED')

    def test_fresh_reduction_approves_but_recovery_stops_it(self):
        p,state,m,sc,prior=self.inputs()
        self.assertEqual(a.assessment('BTCUSDT','REDUCE',weak(),None,m,state,p,T.isoformat(),quantity=5.)['status'],'APPROVED')
        r=a.assessment('BTCUSDT','REDUCE',sc,None,m,state,p,T.isoformat(),quantity=5.)
        self.assertIn('SIGNAL_RECOVERED',r['reasons']);self.assertNotEqual(r['status'],'APPROVED')

    def test_daily_cannot_restore_old_quantity_and_reentry_cannot_consume_permit(self):
        p,state,m,_,_=self.inputs()
        p['automatic_admissions']={'QNTUSDT':dict(quantity=1.,status='PENDING')}
        state['positions']['QNTUSDT']=dict(a.base.paper.new_position(),current_price=100.)
        p['quantity_ceilings']['QNTUSDT']=1.
        for kind in ('DAILY','REENTRY'):
            result,updated=a.targets(state,p,{s:.3 for s in state['positions']},m['quotes'],kind=kind)
            self.assertLessEqual(result['BTCUSDT'],state['positions']['BTCUSDT']['quantity'])
            self.assertEqual(result['QNTUSDT'],1. if kind=='DAILY' else 0.)
            self.assertEqual(updated['short_caps'],p['short_caps'])

    def test_consumed_entry_is_not_reopened_even_when_price_falls(self):
        p,state,m,_,_=self.inputs();p['automatic_admissions']={'QNTUSDT':dict(quantity=1.,status='CONSUMED')}
        state['positions']['QNTUSDT']=dict(a.base.paper.new_position(),current_price=50.)
        p['quantity_ceilings']['QNTUSDT']=1.
        result,_=a.targets(state,p,{s:.3 for s in state['positions']},m['quotes'],kind='DAILY')
        self.assertEqual(result['QNTUSDT'],0.)

    def test_excess_cost_is_rejected_even_with_strong_signal(self):
        p,state,m,sc,prior=self.inputs();m['quotes']['QNTUSDT']['fee_rate']=.01
        m['record_hash']=w.digest({k:v for k,v in m.items() if k!='record_hash'})
        r=a.assessment('QNTUSDT','ENTER',sc,prior,m,state,p,T.isoformat(),quantity=1.)
        self.assertEqual(r['status'],'REJECTED');self.assertIn('COST_LIMIT',r['reasons'])

    def test_funding_outage_is_deferred_and_never_waived_by_score(self):
        p,state,m,sc,prior=self.inputs();m['quotes']['QNTUSDT']['funding']=[]
        m['record_hash']=w.digest({k:v for k,v in m.items() if k!='record_hash'})
        r=a.assessment('QNTUSDT','ENTER',sc,prior,m,state,p,T.isoformat(),quantity=1.)
        self.assertEqual(r['status'],'DEFERRED');self.assertIn('WAITING_VALID_BOOK_COSTS_FUNDING',r['reasons'])


if __name__=='__main__':unittest.main()
