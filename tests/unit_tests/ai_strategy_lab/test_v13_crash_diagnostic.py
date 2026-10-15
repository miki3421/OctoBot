"""Causal boundaries and cash accounting of the offline diagnostic."""
import importlib.util
from pathlib import Path
import unittest

spec = importlib.util.spec_from_file_location('diagnostic', Path(__file__).resolve().parents[3] / 'octobot/ai_strategy_lab/v13_crash_diagnostic.py')
m = importlib.util.module_from_spec(spec)
spec.loader.exec_module(m)


def rows(n=500):
    symbols = ['BTCUSDT'] + ['S' + str(i) for i in range(17)]
    return [dict(time=i * 300, prices={s: 100 - i * .1 for s in symbols}) for i in range(n)]


class CrashDiagnosticTests(unittest.TestCase):
    def test_future_poisoning_does_not_change_past_feature(self):
        data = rows()
        before = m.features(data[:301], 300)
        for r in data[301:]:
            r['prices']['BTCUSDT'] = 1e9
        self.assertEqual(before, m.features(data, 300))
        self.assertTrue(m.signal(before, 'breakout_breadth'))

    def test_gaps_and_invalid_prices_deny_features(self):
        data = rows()
        data[100]['time'] += 1
        self.assertIsNone(m.features(data, 300))
        data = rows()
        data[200]['prices']['BTCUSDT'] = float('nan')
        self.assertIsNone(m.features(data, 300))

    def test_previous_low_excludes_current_price_and_equal_is_not_break(self):
        data = rows()
        self.assertTrue(m.features(data, 300)['new_24h_low'])
        data[300]['prices']['BTCUSDT'] = data[299]['prices']['BTCUSDT']
        self.assertFalse(m.features(data, 300)['new_24h_low'])

    def test_delayed_execution_cooldown_and_censored_outcome(self):
        data = rows(500)
        episodes = m.episodes(data, 'breakout_breadth')
        self.assertGreaterEqual(len(episodes), 2)
        for episode in episodes:
            self.assertGreaterEqual(data[episode['entry_index']]['time'] - data[episode['signal_index']]['time'], 60)
        self.assertIsNone(episodes[-1]['exit_index'])
        self.assertGreaterEqual(data[episodes[1]['signal_index']]['time'] - data[episodes[0]['entry_index']]['time'], 43200)

    def test_missing_future_entry_cannot_be_executed_across_gap(self):
        data = rows(320)
        data = data[:289] + data[301:]
        self.assertFalse(any(e['signal_index'] == 288 for e in m.episodes(data, 'breakout_breadth')))

    def test_short_and_long_both_pay_fees_on_flat_market(self):
        book = dict(bids=[(99., 2.)], asks=[(101., 2.)], fee_rate=.0006)
        for side in [-1, 1]:
            result = m.trade_pnl(side, 1., book, book, 0.)
            self.assertLess(result['net'], 0)
            self.assertGreater(result['fee'], 0)
        with self.assertRaises(ValueError):
            m.trade_pnl(-1, 1., book, book, None)

    def test_insufficient_depth_cannot_create_fill(self):
        with self.assertRaises(ValueError):
            m.vwap([(100., .5)], 1.)


if __name__ == '__main__':
    unittest.main()
