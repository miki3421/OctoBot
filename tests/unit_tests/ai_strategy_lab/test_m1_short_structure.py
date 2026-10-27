"""Causality, recovery discrimination, persistent confirmation and controls."""
import copy
import importlib.util
import json
import math
from pathlib import Path
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[3]
_spec = importlib.util.spec_from_file_location('structure_eval', ROOT/'scripts/qualify_m1_short_structure.py')
E = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(E)
S, B, R = E.S, E.B, E.B.R
P = json.loads((ROOT/'docs/research-protocols/m1-short-risk-exits-candidate-v1.json').read_text())
POLICY = json.loads((ROOT/'docs/research-protocols/m1-short-structural-invalidation-v1.json').read_text())
SLOT = 288*300


def panel(positive=18, slot=SLOT):
    up = set(R.SIGNALS[:positive])
    # BTC must be included in every nonzero positive subset.
    if positive and 'BTCUSDT' not in up:
        up.remove(sorted(up)[-1]); up.add('BTCUSDT')
    return [dict(time=slot-(288-i)*300,
                 prices={s: 100*math.exp((.0005 if s in up else -.0005)*i) for s in R.SIGNALS},
                 source_times={s: slot-(288-i)*300-1 for s in R.SIGNALS}, valid=True) for i in range(289)]


def feature(slot=SLOT):
    return S.features(POLICY, B.history(panel(slot=slot), 288), slot)


def episode():
    return dict(protocol_id=R.PROTOCOL_ID, at=float(SLOT), risk_unit=1., legs={
        'BTCUSDT': dict(quantity=-1., entry=100., opening_fee=.06, funding_anchor=0.)},
        peak=None, armed=False, last_at=float(SLOT), last_market=None,
        recovery_count=0, last_recovery_slot=None, exit_reason=None)


def positions():
    return {'BTCUSDT': dict(quantity=-1., entry_price=100., funding=0.)}


def quotes(price=100.):
    return {s: dict(mark_price=price, quantity_step=.01, fee_rate=.0006,
        asks=[dict(price=price+.01, base_quantity=10000.)],
        bids=[dict(price=price-.01, base_quantity=10000.)],
        funding=[dict(timestamp_ms=SLOT*1000, rate=.0001)], funding_interval_ms=28800000)
        for s in R.SIGNALS}


def step(saved, slot, price=100., value='DEFAULT', offset=1):
    f = feature(slot) if value == 'DEFAULT' else value
    return S.watch(P, POLICY, saved, positions(), quotes(price), at=slot+offset,
                   market_id=str(slot+offset), feature_slot=slot, feature=f)


class StructureTests(unittest.TestCase):
    def test_frozen_policy_rejects_parameter_changes(self):
        p = copy.deepcopy(POLICY); p['rule']['consecutive_distinct_slots'] = 2
        with self.assertRaisesRegex(ValueError, 'policy_identity'): S.validate(p)

    def test_sustained_broad_recovery_qualifies_but_decline_does_not(self):
        f = feature()
        self.assertTrue(f['qualifies']); self.assertEqual(len(f['recovering_symbols']), 18)
        f = S.features(POLICY, B.history(panel(positive=0), 288), SLOT)
        self.assertFalse(f['qualifies']); self.assertEqual(len(f['recovering_symbols']), 0)

    def test_hourly_bounce_below_declining_structure_is_not_reversal(self):
        rows = panel()
        path = [120.]*217+[120.-20.*i/59 for i in range(60)]+[100.+i/12 for i in range(1, 13)]
        self.assertEqual(len(path), 289)
        for row, price in zip(rows, path): row['prices'] = {s: price for s in R.SIGNALS}
        f = S.features(POLICY, B.history(rows, 288), SLOT)
        self.assertGreater(f['btc_60m'], 0)
        self.assertFalse(f['qualifies']); self.assertFalse(f['checks']['btc_rising_slow'])

    def test_twelve_required_even_when_btc_trend_is_positive(self):
        for count, expected in [(11, False), (12, True)]:
            f = S.features(POLICY, B.history(panel(positive=count), 288), SLOT)
            self.assertEqual(len(f['recovering_symbols']), count)
            self.assertEqual(f['qualifies'], expected)

    def test_flat_price_cannot_qualify(self):
        rows = panel()
        for row in rows: row['prices'] = {s: 100. for s in R.SIGNALS}
        self.assertFalse(S.features(POLICY, B.history(rows, 288), SLOT)['qualifies'])

    def test_adaptive_buffer_uses_only_past_sample_sigma(self):
        rows = panel()
        for i, row in enumerate(rows): row['prices']['BTCUSDT'] *= math.exp(.03*math.sin(i*.7))
        f = S.features(POLICY, B.history(rows, 288), SLOT)
        returns = [b['prices']['BTCUSDT']/a['prices']['BTCUSDT']-1 for a, b in zip(rows, rows[1:])]
        mean = sum(returns)/288
        expected = math.sqrt(sum((v-mean)**2 for v in returns)/287*12)
        self.assertAlmostEqual(f['required_gap'], expected*.25)
        self.assertGreater(f['required_gap'], .001)

    def test_future_stale_missing_and_noncontiguous_inputs_rejected(self):
        for kind in ['future', 'stale', 'missing', 'gap']:
            rows = panel()
            if kind == 'future': rows[-1]['source_times']['BTCUSDT'] = SLOT+1
            elif kind == 'stale': rows[-1]['source_times']['BTCUSDT'] = SLOT-121
            elif kind == 'missing': del rows[0]['prices']['BTCUSDT']
            else: rows[0]['time'] += 300
            with self.subTest(kind=kind), self.assertRaises(ValueError):
                S.features(POLICY, B.history(rows, 288), SLOT)

    def test_future_mutation_does_not_change_past_feature(self):
        rows = panel(); future = panel(slot=SLOT+300)[-1]
        before = S.features(POLICY, B.history(rows, 288), SLOT)
        all_rows = rows+[future]
        all_rows[-1]['prices']['BTCUSDT'] = 1e9
        self.assertEqual(before, S.features(POLICY, B.history(all_rows, 288), SLOT))

    def test_three_distinct_slots_and_restart_are_required(self):
        e = episode()
        for i in range(3):
            e, reason = step(e, SLOT+i*300)
            self.assertEqual(e['structure_count'], i+1)
            self.assertEqual(reason, 'STRUCTURAL_REVERSAL' if i == 2 else None)
            e = json.loads(json.dumps(e))
        e, reason = step(e, SLOT+900, value=None)
        self.assertEqual(reason, 'STRUCTURAL_REVERSAL')

    def test_duplicate_market_or_slot_cannot_accelerate_exit(self):
        e, _ = step(episode(), SLOT)
        again, _ = step(e, SLOT)
        self.assertEqual(e, again)
        again, reason = step(e, SLOT, offset=2)
        self.assertEqual(again['structure_count'], 1); self.assertIsNone(reason)

    def test_missing_gap_and_negative_confirmation_reset(self):
        e, _ = step(episode(), SLOT)
        e, _ = step(e, SLOT+300, value=None)
        self.assertEqual(e['structure_count'], 0)
        e, _ = step(e, SLOT+900)
        self.assertEqual(e['structure_count'], 1)
        f = S.features(POLICY, B.history(panel(0, SLOT+1200), 288), SLOT+1200)
        e, reason = step(e, SLOT+1200, value=f)
        self.assertEqual(e['structure_count'], 0); self.assertIsNone(reason)

    def test_loss_and_profit_protection_survive_missing_structure(self):
        e, reason = step(episode(), SLOT, price=102., value=None)
        self.assertEqual(reason, 'LOSS_STOP')
        e, reason = step(episode(), SLOT, price=98., value=None)
        self.assertIsNone(reason); self.assertTrue(e['armed'])
        e, reason = step(e, SLOT+300, price=99., value=None)
        self.assertEqual(reason, 'PROFIT_GIVEBACK')

    def test_conflicting_feature_or_policy_and_future_slot_rejected(self):
        e, _ = step(episode(), SLOT)
        f = feature(); f['qualifies'] = False
        with self.assertRaisesRegex(ValueError, 'feature_identity'): step(e, SLOT, value=f, offset=2)
        e['structural_policy_id'] = 'other'
        with self.assertRaisesRegex(ValueError, 'episode_structural_policy'): step(e, SLOT+300)
        with self.assertRaisesRegex(ValueError, 'not_causal'):
            S.watch(P, POLICY, episode(), positions(), quotes(), at=SLOT+1, market_id='x',
                    feature_slot=SLOT+300, feature=feature(SLOT+300))

    def test_future_labels_cannot_masquerade_as_causal_features(self):
        grid = panel()+panel(slot=SLOT+3600)[-12:]
        for i, row in enumerate(grid[289:], 1):
            row['prices'] = {s: grid[288]['prices'][s]*(1+.001*i) for s in R.SIGNALS}
        f = feature()
        self.assertEqual(E.future_label(POLICY, grid, SLOT+1, f)['label'], 'RECOVERY_CONTINUES')
        altered = copy.deepcopy(grid)
        for i, row in enumerate(altered[289:], 1): row['prices'] = {s: grid[288]['prices'][s]*(1-.001*i) for s in R.SIGNALS}
        self.assertEqual(E.future_label(POLICY, altered, SLOT+1, f)['label'], 'FAILED_REBOUND')
        self.assertEqual(f, S.features(POLICY, B.history(altered, 288), SLOT))
        altered[290]['valid'] = False
        self.assertEqual(E.future_label(POLICY, altered, SLOT+1, f)['label'], 'UNKNOWN')


class FourArmTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.grid = []
        for i in range(385):
            price = 100.*math.exp(-.001*i)
            cls.grid.append(dict(time=i*300, prices={s: price for s in R.SIGNALS},
                source_times={s: i*300-1 for s in R.SIGNALS}, valid=True))
        model = R.model(B.history(cls.grid, 288), SLOT)
        cls.signal = dict(index=288, slot=SLOT, input_hash=model['input_hash'])
        cls.scenario = dict(name='base', latency_seconds=20, fee_multiplier=1, extra_slippage_per_side=0)
        class Books:
            def segment(self, start, end):
                result = []
                for at in range(start, end+1, 60):
                    price = 100.*math.exp(-.001*(at//300))
                    result.append(dict(observed_at_start=B.iso(at-2), observed_at_end=B.iso(at),
                        record_hash=str(at), quotes=quotes(price)))
                return result
        cls.books = Books()

    def test_four_arm_replay_reproduces_legacy_controls_exactly(self):
        old = B.pair(P, self.signal, self.grid, self.books, {}, self.scenario, 10000., {})
        row = E.replay(P, POLICY, self.signal, self.grid, self.books, {}, self.scenario, 10000., {})
        E.reproduce(row, old, 1e-8)
        self.assertEqual(row['decision_errors'], {})
        self.assertEqual(row['arms']['structural'], row['arms']['protection_only'])
        for decision in row['decisions']:
            self.assertLess(B.stamp(decision['at']), B.stamp(row['arms'][decision['arm']]['exit_at']))

    def test_reproduction_rejects_cost_or_position_drift(self):
        old = B.pair(P, self.signal, self.grid, self.books, {}, self.scenario, 10000., {})
        row = E.replay(P, POLICY, self.signal, self.grid, self.books, {}, self.scenario, 10000., {})
        row['arms']['six_hour']['fees'] += .01
        with self.assertRaisesRegex(ValueError, 'reproduction'): E.reproduce(row, old, 1e-8)

    def test_ex_post_labels_do_not_change_any_execution_or_economic_result(self):
        grid = copy.deepcopy(self.grid)
        def price(i):
            return 100.*math.exp(-.001*min(i, 288)+.0005*max(i-288, 0))
        for i, row in enumerate(grid):
            row['prices'] = {s: price(i) for s in R.SIGNALS}
        class Books:
            def segment(self, start, end):
                return [dict(observed_at_start=B.iso(at-2), observed_at_end=B.iso(at),
                    record_hash=str(at), quotes=quotes(price(at//300)))
                    for at in range(start, end+1, 60)]
        a = E.replay(P, POLICY, self.signal, grid, Books(), {}, self.scenario, 10000., {})
        self.assertTrue(any('future_label' in d for d in a['decisions']))
        with patch.object(E, 'future_label', return_value=dict(label='FUTURE_MUTATED')) as labels:
            b = E.replay(P, POLICY, self.signal, grid, Books(), {}, self.scenario, 10000., {})
            self.assertTrue(labels.called)
        self.assertEqual(a['arms'], b['arms'])
        self.assertEqual(a['quantities'], b['quantities'])


if __name__ == '__main__':
    unittest.main()
