import copy
import unittest
from octobot.ai_strategy_lab import v13_m1_portfolio_candidate_v2 as c


class CandidateTests(unittest.TestCase):
    def fixture(self):
        values = {}
        quotes = {}
        for symbol, loss in [('A', -10), ('B', -8), ('C', 1)]:
            side = dict(net=loss, active_days=3, coverage=.99, net_per_1000_notional_days=loss)
            values[symbol] = dict(current_quantity=10., current_mark=100., windows={
                key: dict(sides=dict(LONG=dict(side))) for key in ('since_clone', '48h')})
            quotes[symbol] = dict(mark_price=100., step=1., fee_rate=.0006,
                                  simulation_min_notional=1., simulation_min_quantity=1.,
                                  bids=[dict(price=99.9, base_quantity=100.)])
        market = dict(observed_at_end='2026-10-23T20:00:00+00:00', quotes=quotes)
        market['record_hash'] = c.digest(market)
        attribution = dict(account='synthetic-only', end=market['observed_at_end'], method=c.review.METHOD,
                           source_hashes=dict(market=market['record_hash'], m1='synthetic', seed='synthetic'),
                           m1=dict(equity=10000., symbols=values))
        parent = dict(account='synthetic-only', parent_revision=0, short_caps={'A': .1, 'B': .1, 'C': .1, 'NEW': .2}, selected=['NEW'])
        parent['proposal_id'] = c.digest(parent)
        return parent, attribution, market

    def test_reductions_preserve_survivors_cash_and_short_capacity(self):
        p, a, m = self.fixture(); before = copy.deepcopy((p, a, m))
        value = c.build(p, a, m, phase='NORMAL')
        self.assertEqual((p, a, m), before)
        self.assertEqual(value['maintenance']['target_quantity_ceilings'], {'A': 5., 'B': 5., 'C': 10.})
        self.assertAlmostEqual(value['preview']['freed_mark_notional'], 1000.)
        self.assertEqual(value['short_budget']['reference_caps'], value['short_budget']['proposed_caps'])
        self.assertAlmostEqual(value['short_budget']['proposed_total'], .3)
        self.assertFalse(value['execution_authorized']); self.assertFalse(value['live_activation_ready'])
        self.assertEqual(value['new_symbol_admissions']['admitted'], [])

    def test_missing_coverage_is_not_a_sell_signal(self):
        p, a, m = self.fixture(); a['m1']['symbols']['A']['windows']['48h']['sides']['LONG']['coverage'] = None
        self.assertEqual(c.build(p, a, m, phase='NORMAL')['maintenance']['selected'], ['B'])

    def test_missing_depth_does_not_select_a_replacement(self):
        p, a, m = self.fixture(); m['quotes']['A']['bids'][0]['base_quantity'] = .01
        m['record_hash'] = c.digest({k: v for k, v in m.items() if k != 'record_hash'})
        a['source_hashes']['market'] = m['record_hash']
        v = c.build(p, a, m, phase='NORMAL')
        self.assertEqual(v['maintenance']['target_quantity_ceilings']['A'], 10.)
        self.assertEqual(v['maintenance']['unavailable'][0]['symbol'], 'A')

    def test_future_application_needs_normal_phase_and_bound_snapshot(self):
        p, a, m = self.fixture()
        with self.assertRaisesRegex(ValueError, 'normal_phase'):
            c.build(p, a, m, phase='M1_HOLD')
        a['end'] = '2026-10-23T20:05:00+00:00'
        with self.assertRaisesRegex(ValueError, 'binding'):
            c.build(p, a, m, phase='NORMAL')

    def test_changed_parent_and_method_cannot_reuse_identity(self):
        p, a, m = self.fixture(); p['short_caps']['NEW'] = .3
        with self.assertRaisesRegex(ValueError, 'invalid_parent'):
            c.build(p, a, m, phase='NORMAL')
        p, a, m = self.fixture(); a['method'] = dict(a['method'], maximum_reduction_proposals=18)
        with self.assertRaisesRegex(ValueError, 'advisory_method_changed'):
            c.build(p, a, m, phase='NORMAL')

    def test_content_change_requires_new_candidate_id(self):
        p, a, m = self.fixture(); first = c.build(p, a, m, phase='NORMAL')
        a['m1']['symbols']['A']['windows']['since_clone']['sides']['LONG']['net'] = -11
        second = c.build(p, a, m, phase='NORMAL')
        self.assertNotEqual(first['candidate_id'], second['candidate_id'])


if __name__ == '__main__':
    unittest.main()
