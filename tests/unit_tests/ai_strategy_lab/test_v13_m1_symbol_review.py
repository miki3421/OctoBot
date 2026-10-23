"""Accounting expectations from cash flows, not a mirror of the replay code.

Card work-card-3ed5dd7b-b2d4-4791-a643-4e60c20e3bf7. All fixtures synthetic.
"""
import copy
import csv
import json
from pathlib import Path
import sqlite3
import tempfile
import unittest

import v13_m1_symbol_review as r


def fill(i, t, quantity, price, fee=0):
    return dict(id=i, bar=r.iso(t), quantity=quantity, price=price, fee=fee,
                action='BUY' if quantity > 0 else 'SELL', symbol='BTCUSDT')


def quote():
    return dict(step=.01, mark_price=100, bids=[dict(base_quantity=100, price=99)],
                fee_rate=.0006, simulation_min_notional=1,
                simulation_min_quantity=.1, min_quantity='UNKNOWN', min_notional='UNKNOWN')


class AttributionTests(unittest.TestCase):
    def test_inherited_profit_is_not_scored_twice(self):
        # At the boundary: 2 units worth 120, cost 100. Selling at 125 adds 10,
        # not 50. The opening fee paid before the boundary is also inherited.
        result = r.attribution([fill(1, 0, 2, 100, 2), fill(2, 110, -2, 125, 1)],
                               [], [(100, 120), (110, 125)], 100, 120)
        self.assertAlmostEqual(result['net'], 9)
        long = result['sides']['LONG']
        self.assertEqual(long['open_pnl_start'], 40)
        self.assertEqual(long['fees'], 1)
        self.assertEqual(long['carried_episodes'], 1)
        self.assertEqual(long['closed_episodes'], 1)

    def test_reversal_splits_fees_and_funding_and_buy_closes_profitable_short(self):
        # Long 2 closes at 110 (+20); short 1 then closes at 100 (+10).
        # Reversal fee 3: long 2, short 1. Cover fee 1. Funding -2 / +.5.
        fills = [fill(1, 0, 2, 100), fill(2, 110, -3, 110, 3), fill(3, 130, 1, 100, 1)]
        funding = [dict(timestamp_ms=105000, quantity=2, amount=-2),
                   dict(timestamp_ms=120000, quantity=-1, amount=.5)]
        result = r.attribution(fills, funding, [(100, 100), (110, 110), (130, 100)], 100, 140)
        self.assertAlmostEqual(result['sides']['LONG']['net'], 16)
        self.assertAlmostEqual(result['sides']['SHORT']['net'], 8.5)
        self.assertAlmostEqual(result['net'], 24.5)
        self.assertEqual(result['sides']['SHORT']['closed_episodes'], 1)

    def test_daily_increases_partial_closes_are_not_independent_episodes(self):
        fills = [fill(1, 10, 1, 100), fill(2, 20, 1, 100),
                 fill(3, 30, -.5, 100), fill(4, 40, -1.5, 100)]
        result = r.attribution(fills, [], [(0, 100), (50, 100)], 0, 50)
        self.assertEqual(result['sides']['LONG']['new_episodes'], 1)
        self.assertEqual(result['sides']['LONG']['closed_episodes'], 1)

    def test_float_residue_does_not_create_phantom_side(self):
        result = r.attribution([fill(1, 0, .3, 100), fill(2, 110, -.30000000000000004, 100, .1)],
                               [], [(100, 100)], 100, 120)
        self.assertEqual(result['quantity'], 0)
        self.assertAlmostEqual(result['sides']['LONG']['fees'], .1)
        self.assertEqual(result['sides']['SHORT']['new_episodes'], 0)

    def test_exposure_uses_previous_price_with_a_finite_gap_cap(self):
        result = r.attribution([fill(1, 0, 1, 100)], [],
                               [(100, 100), (400, 200)], 100, 500)
        long = result['sides']['LONG']
        self.assertEqual(long['exposure_seconds'], 400)
        self.assertEqual(long['covered_exposure_seconds'], 280)
        self.assertAlmostEqual(long['notional_days'], (180*100+100*200)/86400)
        self.assertAlmostEqual(long['coverage'], .7)
        self.assertEqual(long['observed_drawdown'], 0)

    def test_future_inputs_do_not_change_an_earlier_window(self):
        fills = [fill(1, 0, 1, 100)]
        marks = [(100, 100), (150, 90), (200, 95)]
        before = r.attribution(fills, [], marks, 100, 200)
        after = r.attribution(fills+[fill(2, 201, -1, 1e8)],
                              [dict(timestamp_ms=202000, quantity=1, amount=1e9)],
                              marks+[(201, 1e9)], 100, 200)
        self.assertEqual(before, after)
        self.assertEqual(before['sides']['LONG']['observed_drawdown'], 10)

    def test_missing_boundaries_invalid_prices_or_fill_direction_fail(self):
        for fills, marks in [([fill(1, 0, 1, 100)], []),
                             ([fill(1, 0, 1, 100)], [(100, 0)]),
                             ([dict(fill(1, 110, 1, 100), action='SELL')], [(100, 100)])]:
            with self.subTest(marks=marks), self.assertRaises(ValueError):
                r.attribution(fills, [], marks, 100, 200)

    def test_per_symbol_state_tampering_fails_reconciliation(self):
        position = dict(quantity=1, entry_price=100, current_price=100, last_mark_at=r.iso(100),
                        realized_pnl=0, fees=0, funding=0)
        seed = dict(state=dict(initial_equity=10000, positions={'BTCUSDT':position}))
        account = dict(state=copy.deepcopy(seed['state']), fills=[fill(1, 0, 1, 100)],
                       funding=[], marks={'BTCUSDT':[(100, 100), (200, 100)]})
        self.assertEqual(r.review_account(account, seed, 100, 200)['net_since_clone'], 0)
        account['equity_observation'] = dict(bar=r.iso(200), equity=9999)
        with self.assertRaisesRegex(ValueError, 'equity_history_reconciliation'):
            r.review_account(account, seed, 100, 200)
        account.pop('equity_observation')
        account['state']['positions']['BTCUSDT']['quantity'] = 2
        with self.assertRaisesRegex(ValueError, 'state_replay_mismatch'):
            r.review_account(account, seed, 100, 200)


class ProposalTests(unittest.TestCase):
    def test_fifty_percent_target_rounding_never_opens_a_short(self):
        result = r.reduction_cost(2.61, quote())
        self.assertEqual(result['indicative_quantity_after'], 1.3)
        self.assertEqual(result['quantity_to_sell'], 1.31)
        self.assertGreater(result['estimated_immediate_equity_cost'], 0)
        self.assertEqual(quote()['min_quantity'], 'UNKNOWN')

    def test_insufficient_depth_and_synthetic_minimum_are_explicit(self):
        q = quote();q['bids'][0]['base_quantity'] = .01
        self.assertFalse(r.reduction_cost(2, q)['available'])
        q = quote();q['simulation_min_notional'] = 10000
        self.assertEqual(r.reduction_cost(2, q)['reason'], 'below_simulation_minimum')

    def test_reduction_does_not_force_a_full_close_or_ignore_off_grid_quantity(self):
        self.assertEqual(r.reduction_cost(.01, quote())['reason'], 'cannot_halve_without_full_close')
        self.assertEqual(r.reduction_cost(1.001, quote())['reason'], 'current_quantity_off_grid')

    def test_report_exports_reconcile_and_cannot_overwrite_previous_evidence(self):
        position = dict(quantity=1, entry_price=100, current_price=100, last_mark_at=r.iso(100),
                        realized_pnl=0, fees=0, funding=0)
        seed = dict(state=dict(initial_equity=10000, positions={'BTCUSDT':position}))
        account = dict(state=copy.deepcopy(seed['state']), fills=[fill(1, 0, 1, 100)],
                       funding=[], marks={'BTCUSDT':[(100, 100), (200, 100)]})
        review = r.review_account(account, seed, 100, 200)
        data = dict(start=r.iso(100),end=r.iso(200),days=100/86400,m1=review,
                    original=review,proposals=r.proposals(review, review, {'BTCUSDT':quote()}))
        with tempfile.TemporaryDirectory() as folder:
            p = Path(folder)/'review.json';r.write_reports(data, p)
            with p.with_suffix('.csv').open() as source:
                rows = list(csv.DictReader(source))
            self.assertEqual(len(rows), 12)
            self.assertEqual(sum(float(x['net']) for x in rows), 0)
            self.assertIn('non ordini applicati', p.with_suffix('.md').read_text().replace('**', ''))
            before = p.read_bytes()
            with self.assertRaisesRegex(ValueError, 'new_outputs_required'):r.write_reports(data, p)
            self.assertEqual(before, p.read_bytes())

    def test_no_forced_reductions_when_side_or_coverage_is_unsuitable(self):
        metric = dict(net=-3, active_days=4, coverage=1, net_per_1000_notional_days=-1)
        symbols = {}
        for name in ('A', 'B', 'C', 'D', 'E'):
            windows = {w:dict(sides={'LONG':copy.deepcopy(metric)}) for w in ('since_clone', '48h')}
            symbols[name] = dict(windows=windows, current_quantity=2, current_mark=100, since_clone=5)
        symbols['D']['current_quantity'] = 0
        symbols['E']['windows']['48h']['sides']['LONG']['coverage'] = .5
        account = dict(equity=10000, symbols=symbols)
        result = r.proposals(account, account, {s:quote() for s in symbols})
        selected = [p['symbol'] for p in result if p['action'].startswith('RIDUZIONE')]
        self.assertEqual(selected, ['A', 'B'])
        self.assertTrue(all(not p['applied'] and not p['execution_authorized'] for p in result))

    def test_snapshot_is_read_only_and_missing_database_is_not_created(self):
        with tempfile.TemporaryDirectory() as folder:
            p = Path(folder)/'snapshot.sqlite'
            with self.assertRaises(ValueError):r.load_snapshot(p)
            self.assertFalse(p.exists())
            with sqlite3.connect(p) as db:
                db.executescript('CREATE TABLE state(id,payload); CREATE TABLE orders(id,bar,status); '
                                 'CREATE TABLE funding_events(timestamp_ms,symbol); CREATE TABLE marks(symbol,bar,price); '
                                 'CREATE TABLE equity_history(bar,equity);')
                db.execute('INSERT INTO state VALUES(1,?)', (json.dumps(dict(positions={})),))
            with self.assertRaises(ValueError):r.load_snapshot(p)
            p.chmod(0o440);before=p.read_bytes()
            self.assertEqual(r.load_snapshot(p)['fills'], [])
            self.assertEqual(p.read_bytes(), before)


if __name__ == '__main__':
    unittest.main()
