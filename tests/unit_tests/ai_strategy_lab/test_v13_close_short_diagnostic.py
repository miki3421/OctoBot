"""Independent identities and failure boundaries for the basket comparison."""
import copy
import importlib.util
import unittest
from pathlib import Path

spec = importlib.util.spec_from_file_location('account', Path(__file__).resolve().parents[3] / 'octobot/ai_strategy_lab/v13_close_short_diagnostic.py')
a = importlib.util.module_from_spec(spec)
spec.loader.exec_module(a)


def quote(depth=10.):
    return dict(mark_price=100., price_tick=.01, quantity_step=.1, fee_rate=.0006,
                min_quantity=None, min_notional=None,
                bids=[dict(price=99., base_quantity=depth)],
                asks=[dict(price=101., base_quantity=depth)])


def state():
    pos=a.new_position()
    a.fill(pos, 1., 80., .048)
    pos['funding']=-.01
    return dict(initial_equity=1000., positions={'A': pos})


class CloseShortTests(unittest.TestCase):
    def test_realizing_profit_does_not_add_profit_twice(self):
        s=state();before=a.totals(s,{'A':100.})['equity']
        a.fill(s['positions']['A'],-1.,100.,.06)
        self.assertAlmostEqual(a.totals(s,{'A':100.})['equity'],before-.06)
        self.assertAlmostEqual(s['positions']['A']['realized_pnl'],20.)

    def test_crossing_cost_basis_and_accounting(self):
        s=state();before=a.totals(s,{'A':100.})['equity']
        a.fill(s['positions']['A'],-2.,100.,.12)
        self.assertEqual(s['positions']['A']['quantity'],-1.)
        self.assertEqual(s['positions']['A']['entry_price'],100.)
        self.assertAlmostEqual(a.totals(s,{'A':100.})['equity'],before-.12)
        self.assertAlmostEqual(a.totals(s,{'A':90.})['equity'],before-.12+10.)

    def test_inversion_preserves_initial_gross_changes_net_and_keeps_seed(self):
        s=state();saved=copy.deepcopy(s)
        child,legs=a.rebalance(s,a.targets_for(s,'SHORT'),{'A':quote()})
        self.assertEqual(s,saved)
        self.assertEqual(a.totals(child,{'A':100.})['gross'],a.totals(s,{'A':100.})['gross'])
        self.assertEqual(a.totals(child,{'A':100.})['net_exposure'],-100.)
        self.assertEqual(legs[0]['quantity'],-2.)

    def test_inversion_must_have_aggregate_depth_for_both_legs(self):
        with self.assertRaisesRegex(ValueError,'insufficient_aggregate_depth'):
            a.rebalance(state(),{'A':-1.},{'A':quote(depth=1.5)})

    def test_failed_second_symbol_is_atomic(self):
        s=state();s['positions']['B']=copy.deepcopy(s['positions']['A']);saved=copy.deepcopy(s)
        with self.assertRaises(ValueError):
            a.rebalance(s,{'A':-1.,'B':-1.},{'A':quote(),'B':quote(depth=.1)})
        self.assertEqual(s,saved)

    def test_tick_rounding_is_adverse_for_each_side(self):
        buy=a.execution(1.,0.,quote());sell=a.execution(-1.,1.,quote())
        self.assertGreaterEqual(buy['price'],101.*1.0002)
        self.assertLessEqual(sell['price'],99.*.9998)
        self.assertAlmostEqual(buy['price']/.01,round(buy['price']/.01))

    def test_simulated_minimum_does_not_invent_exchange_minima(self):
        q=quote();q['mark_price']=1.
        a.execution(-.1,.1,q) # full reduction permitted
        with self.assertRaisesRegex(ValueError,'below_simulated_opening_minimum'):
            a.execution(-.2,.1,q)
        self.assertIsNone(q['min_quantity']);self.assertIsNone(q['min_notional'])

    def test_missing_funding_or_rate_is_unknown(self):
        q=dict(funding_interval_ms=1000,funding=[])
        with self.assertRaises(ValueError):a.settlements(q,500,1500)
        q['funding']=[dict(timestamp_ms=0,rate=.001),dict(timestamp_ms=1000,rate=None)]
        with self.assertRaises(ValueError):a.settlements(q,500,1500)

    def test_gap_and_future_funding_cannot_create_zero_or_earlier_cash(self):
        q=dict(funding_interval_ms=1000,funding=[dict(timestamp_ms=0,rate=0.),dict(timestamp_ms=2000,rate=.001)])
        with self.assertRaises(ValueError):a.settlements(q,500,2500)
        q['funding']=[dict(timestamp_ms=0,rate=.001),dict(timestamp_ms=1000,rate=0.),dict(timestamp_ms=2000,rate=99.)]
        self.assertEqual(a.settlements(q,500,1500),[dict(timestamp_ms=1000,rate=0.)])

    def test_return_to_common_long_charges_more_for_short_on_flat_market(self):
        s=state();equity=a.totals(s,{'A':100.})['equity'];results={}
        for arm in ['CASH','SHORT']:
            child,entry=a.rebalance(s,a.targets_for(s,arm),{'A':quote()})
            restored,exit_=a.rebalance(child,{'A':1.},{'A':quote()})
            self.assertEqual(restored['positions']['A']['quantity'],1.)
            self.assertLess(a.totals(restored,{'A':100.})['equity'],equity)
            results[arm]=a.totals(restored,{'A':100.})['equity']
        self.assertLess(results['SHORT'],results['CASH'])


if __name__=='__main__':
    unittest.main()
