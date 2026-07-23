import unittest

import numpy

from tentacles.Evaluator.TA.market_regime_evaluator import MarketRegimeEvaluator


class MarketRegimeEvaluatorTest(unittest.TestCase):
    def test_compute_snapshot_exposes_finite_quantitative_features(self):
        evaluator = object.__new__(MarketRegimeEvaluator)
        for name, value in evaluator.get_default_config().items():
            setattr(evaluator, name, value)

        close = numpy.linspace(100.0, 180.0, 180) + numpy.sin(
            numpy.linspace(0.0, 12.0, 180)
        )
        high = close * 1.005
        low = close * 0.995

        snapshot = evaluator.compute_snapshot(close, high, low)

        self.assertEqual(snapshot["schema_version"], 1)
        self.assertEqual(snapshot["regime"], "trend")
        self.assertEqual(snapshot["direction"], "BULLISH")
        self.assertGreaterEqual(snapshot["adx"], 25)
        self.assertGreater(snapshot["ema_spread_pct"], 0)
        self.assertGreater(snapshot["bb_width_pct"], 0)
        self.assertGreaterEqual(snapshot["bb_width_percentile"], 0)
        self.assertLessEqual(snapshot["bb_width_percentile"], 1)
        self.assertGreater(snapshot["atr_pct"], 0)


if __name__ == "__main__":
    unittest.main()
