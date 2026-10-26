"""Inactive engineering tests; no strategy efficacy or exchange qualification."""
import copy
import datetime as dt
import unittest
from unittest.mock import patch

import numpy as np
from octobot.ai_strategy_lab import v13_discrete_risk_candidate as c

f = c.f
T = dt.datetime(2026, 10, 14, 0, 15, tzinfo=dt.timezone.utc)
SYMS = ['BTCUSDT', 'ETHUSDT']


def fixture():
    state = dict(initial_equity=10000., order_count=0,
                 positions={s:dict(f.paper.new_position(), quantity=0., entry_price=100., current_price=100.) for s in SYMS},
                 risk_policy_state=dict(daily_day=T.date().isoformat(), daily_start=10000.,
                                        high_water=10000., daily_entries=0, last_increase_at=None))
    quotes = {s:dict(symbol=s, market_identity='kucoin_futures_usdt', timestamp=T.isoformat(),
                    mark_timestamp=T.isoformat(), metadata_observed_at=T.isoformat(), mark_price=100.,
                    bids=[dict(price=99.99,base_quantity=1000.)], asks=[dict(price=100.01,base_quantity=1000.)],
                    quantity_step=1.,price_tick=.01,fee_rate=.0006,min_quantity=None,min_notional=None,
                    funding_interval_ms=28800000,
                    funding=[dict(timestamp_ms=int(T.timestamp()*1000),rate=.0001)]) for s in SYMS}
    record = dict(scope=f.source.SCOPE,observed_at_start=T.isoformat(),observed_at_end=T.isoformat(),quotes=quotes)
    seal(record)
    return {a:copy.deepcopy(state) for a in f.ARMS}, {a:{s:0. for s in SYMS} for a in f.ARMS}, np.diag([.0001,.0004]), record


def seal(record):
    record['record_hash'] = f.p.digest({k:v for k,v in record.items() if k!='record_hash'})


class Tests(unittest.TestCase):
    def run_case(self, modify=None, **kwargs):
        states, targets, cov, record = fixture()
        if modify:
            modify(states, targets, record)
        return c.repair(states, targets, cov, record, T, **kwargs)

    def test_post_cost_match_only_trims_higher_arm_and_inputs_unchanged(self):
        states, targets, cov, record = fixture()
        targets['FAST']['BTCUSDT']=2.;targets['HALF']['BTCUSDT']=3.
        before=copy.deepcopy((states,targets,record))
        out=c.repair(states,targets,cov,record,T)
        self.assertEqual(out['status'],'MATCHED');self.assertLessEqual(out['gap'],.02)
        self.assertEqual(out['adjustments'][0]['arm'],'HALF')
        self.assertEqual(out['states']['HALF']['positions']['BTCUSDT']['quantity'],2.)
        self.assertEqual(out['states']['FAST']['positions']['BTCUSDT']['quantity'],2.)
        for arm in f.ARMS:
            fees=sum(p['fees'] for p in out['states'][arm]['positions'].values())
            self.assertAlmostEqual(fees,sum(x['fee'] for x in out['fills'] if x['arm']==arm))
            self.assertLess(f.paper.totals(out['states'][arm])['equity'],10000.)
        self.assertEqual((states,targets,record),before)
        self.assertEqual(c.repair(states,targets,cov,record,T),out)
        self.assertFalse(out['execution_authorized']);self.assertFalse(out['orders_authorized'])

    def test_matched_plan_is_unchanged(self):
        def m(s,q,r):
            for arm in f.ARMS:q[arm]['BTCUSDT']=2.
        out=self.run_case(m)
        self.assertEqual(out['status'],'MATCHED_UNCHANGED');self.assertEqual(out['adjustments'],[])

    def test_indivisible_mismatch_is_not_flattened_or_qualified(self):
        def m(s,q,r):q['FAST']['BTCUSDT']=1.;q['HALF']['ETHUSDT']=1.
        out=self.run_case(m)
        self.assertEqual(out['status'],'UNQUALIFIED_NO_ONE_LOT_IMPROVEMENT')
        self.assertFalse(out['qualified']);self.assertGreater(out['gap'],.02)
        self.assertEqual(out['states']['FAST']['positions']['BTCUSDT']['quantity'],1.)
        self.assertEqual(out['states']['HALF']['positions']['ETHUSDT']['quantity'],1.)

    def test_one_arm_risk_veto_blocks_all_increases_but_keeps_reductions(self):
        for veto in ('daily_loss','drawdown','entry_count','cooldown'):
            with self.subTest(veto=veto):
                def m(s,q,r):
                    for arm in f.ARMS:
                        s[arm]['positions']['BTCUSDT']['quantity']=4.
                        q[arm]['BTCUSDT']=2.;q[arm]['ETHUSDT']=2.
                    risk=s['FAST']['risk_policy_state']
                    if veto=='daily_loss':risk['daily_start']=10300.
                    if veto=='drawdown':risk['high_water']=12000.
                    if veto=='entry_count':risk['daily_entries']=1
                    if veto=='cooldown':risk['last_increase_at']=(T-dt.timedelta(hours=1)).isoformat()
                out=self.run_case(m)
                self.assertTrue(out['blocks']['FAST']);self.assertTrue(out['fills'])
                self.assertTrue(all(x['protective'] for x in out['fills']))
                self.assertTrue(all(out['states'][a]['positions']['ETHUSDT']['quantity']==0 for a in f.ARMS))

    def test_paired_market_veto_cannot_be_reintroduced_by_repair(self):
        def m(s,q,r):
            q['FAST']['BTCUSDT']=2.;q['HALF']['ETHUSDT']=2.
            r['quotes']['ETHUSDT']['asks'][0]['price']=105.;seal(r)
        out=self.run_case(m)
        self.assertTrue(out['paired_entry_veto']);self.assertEqual(out['fills'],[])
        out=self.run_case(lambda s,q,r:q['FAST'].update(BTCUSDT=2.),paired_entry_veto=True)
        self.assertTrue(out['paired_entry_veto']);self.assertEqual(out['fills'],[])

    def test_funding_debt_missing_and_future_are_not_zero(self):
        for mode in ('debt','missing','future','stale','middle_gap'):
            with self.subTest(mode=mode):
                def m(s,q,r):
                    for a in f.ARMS:
                        s[a]['positions']['BTCUSDT']['quantity']=4.;q[a]['BTCUSDT']=2.;q[a]['ETHUSDT']=2.
                    if mode=='missing':r['quotes']['ETHUSDT']['funding']=[]
                    if mode=='future':r['quotes']['ETHUSDT']['funding'][0]['timestamp_ms']+=1
                    if mode=='stale':r['quotes']['ETHUSDT']['funding'][0]['timestamp_ms']-=28800000
                    if mode=='middle_gap':r['quotes']['ETHUSDT']['funding'].insert(0,dict(timestamp_ms=int(T.timestamp()*1000)-57600000,rate=.0001))
                    seal(r)
                out=self.run_case(m,funding_debt='unreconciled' if mode=='debt' else None)
                self.assertEqual(out['status'],'UNQUALIFIED_FUNDING');self.assertIsNone(out['gap'])
                self.assertFalse(out['qualified']);self.assertTrue(all(x['protective'] for x in out['fills']))

    def test_insufficient_depth_is_partial_not_success(self):
        def m(s,q,r):
            for a in f.ARMS:q[a]['BTCUSDT']=3.
            r['quotes']['BTCUSDT']['asks'][0]['base_quantity']=1.;seal(r)
        out=self.run_case(m)
        self.assertEqual(out['status'],'UNQUALIFIED_PARTIAL_EXECUTION');self.assertFalse(out['qualified'])
        self.assertFalse(out['requested_plan_completed'])
        self.assertTrue(all(out['states'][a]['positions']['BTCUSDT']['quantity']==1 for a in f.ARMS))

    def test_minimum_veto_applies_to_entire_pair(self):
        def m(s,q,r):
            q['FAST']['BTCUSDT']=.001;q['HALF']['ETHUSDT']=2.
            r['quotes']['BTCUSDT']['quantity_step']=.001;seal(r)
        out=self.run_case(m)
        self.assertTrue(out['paired_entry_veto']);self.assertEqual(out['fills'],[])

    def test_protective_substep_partial_target_is_unqualified(self):
        def m(s,q,r):
            for arm in f.ARMS:
                s[arm]['positions']['BTCUSDT']['quantity']=1.5
                q[arm]['BTCUSDT']=1.
        out=self.run_case(m)
        self.assertEqual(out['status'],'UNQUALIFIED_PARTIAL_EXECUTION')
        self.assertFalse(out['qualified']);self.assertFalse(out['requested_plan_completed'])

    def test_protective_full_close_preserves_existing_minimum_exception(self):
        def m(s,q,r):
            for arm in f.ARMS:s[arm]['positions']['BTCUSDT']['quantity']=.001
        out=self.run_case(m)
        self.assertEqual(out['status'],'MATCHED_FLAT');self.assertEqual(len(out['fills']),2)
        self.assertTrue(all(x['protective'] for x in out['fills']))

    def test_invalid_or_tampered_inputs_have_no_projected_fills(self):
        for mode in ('hash','stale','covariance','offgrid','negative_covariance','nan'):
            with self.subTest(mode=mode):
                states,q,cov,r=fixture();q['FAST']['BTCUSDT']=2.;instant=T
                if mode=='hash':r['quotes']['BTCUSDT']['mark_price']=101.
                if mode=='stale':instant=T+dt.timedelta(hours=1)
                if mode=='covariance':cov=np.zeros((3,3))
                if mode=='negative_covariance':cov=-cov
                if mode=='offgrid':q['FAST']['BTCUSDT']=.5
                if mode=='nan':cov[0,0]=float('nan')
                before=copy.deepcopy(states);out=c.repair(states,q,cov,r,instant)
                self.assertEqual(out['status'],'INVALID_INPUT');self.assertEqual(out['fills'],[])
                self.assertEqual(out['states'],before);self.assertEqual(states,before)

    def test_nonflat_zero_covariance_and_one_sided_risk_are_unqualified(self):
        s,q,cov,r=fixture()
        for a in f.ARMS:q[a]['BTCUSDT']=2.
        out=c.repair(s,q,np.zeros((2,2)),r,T)
        self.assertEqual(out['status'],'UNQUALIFIED_ZERO_COVARIANCE');self.assertFalse(out['qualified'])
        q['HALF']['BTCUSDT']=0.
        out=c.repair(s,q,cov,r,T)
        self.assertEqual(out['status'],'UNQUALIFIED_ONE_SIDED_ZERO_RISK');self.assertFalse(out['qualified'])

    def test_complete_net_order_is_repriced_from_original_book(self):
        s,q,cov,r=fixture()
        q['FAST']['BTCUSDT']=2.;q['HALF']['BTCUSDT']=4.
        r['quotes']['BTCUSDT']['asks']=[dict(price=100.01,base_quantity=2.),dict(price=100.03,base_quantity=2.)];seal(r)
        out=c.repair(s,q,cov,r,T)
        self.assertTrue(out['qualified'])
        half=[x for x in out['fills'] if x['arm']=='HALF']
        self.assertEqual(len(half),1);self.assertEqual(half[0]['quantity'],2.)
        self.assertEqual(half[0]['price'],f.exposure.execution_price(r['quotes']['BTCUSDT'],2.,f.engine.market.fill_price))

    def test_quantity_sign_and_bound_preserved_for_short_plan(self):
        s,q,cov,r=fixture();q['FAST']['BTCUSDT']=-2.;q['HALF']['BTCUSDT']=-3.
        out=c.repair(s,q,cov,r,T)
        self.assertTrue(out['qualified']);self.assertEqual(out['states']['HALF']['positions']['BTCUSDT']['quantity'],-2.)

    def test_exposure_cap_veto_is_paired(self):
        def m(s,q,r):q['FAST']['BTCUSDT']=40.;q['HALF']['ETHUSDT']=2.
        out=self.run_case(m)
        self.assertTrue(out['paired_entry_veto']);self.assertEqual(out['fills'],[])

    def test_iteration_bound_reports_failure(self):
        with patch.object(c,'MAX_ITERATIONS',1):
            out=self.run_case(lambda s,q,r:(q['FAST'].update(BTCUSDT=2.),q['HALF'].update(BTCUSDT=10.)))
        self.assertEqual(out['status'],'UNQUALIFIED_ITERATION_LIMIT');self.assertFalse(out['qualified'])


if __name__=='__main__':unittest.main()
