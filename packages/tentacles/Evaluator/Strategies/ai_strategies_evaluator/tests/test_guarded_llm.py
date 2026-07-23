import asyncio
import datetime
import pathlib
import sqlite3
import tempfile
import unittest
from unittest import mock

import pydantic

from tentacles.Evaluator.Strategies.ai_strategies_evaluator.guarded_llm import (
    DeterministicRiskGuard,
    LLMTradingDecision,
    RiskGuardSettings,
    SQLiteDecisionJournal,
    deterministic_alignment_decision,
    evaluator_signal_bias,
    regime_adaptive_decision,
    regime_adaptive_v2_decision,
    regime_adaptive_v3_decision,
)
from tentacles.Evaluator.Strategies.ai_strategies_evaluator.guarded_llm_strategy import (
    GuardedLLMStrategyEvaluator,
)
from tentacles.Trading.Mode.daily_trading_mode.daily_trading import (
    DailyTradingMode,
)


def _decision(**overrides):
    values = {
        "action": "BUY",
        "confidence": 0.80,
        "signal_strength": 0.45,
        "stop_loss_pct": 2.0,
        "take_profit_pct": 4.0,
        "horizon_minutes": 240,
        "rationale": "Aligned technical signals.",
        "invalidation": "Trend alignment is lost.",
    }
    values.update(overrides)
    return LLMTradingDecision(**values)


class DeterministicRiskGuardTest(unittest.TestCase):
    def test_deterministic_mode_has_no_backtesting_service_requirement(self):
        evaluator = object.__new__(GuardedLLMStrategyEvaluator)
        evaluator.decision_mode = evaluator.DECISION_MODE_DETERMINISTIC_ALIGNMENT

        self.assertEqual(evaluator.get_backtesting_service_requirements(), ())

        evaluator.decision_mode = evaluator.DECISION_MODE_REGIME_ADAPTIVE
        self.assertEqual(evaluator.get_backtesting_service_requirements(), ())

        evaluator.decision_mode = evaluator.DECISION_MODE_REGIME_ADAPTIVE_V2
        self.assertEqual(evaluator.get_backtesting_service_requirements(), ())

        evaluator.decision_mode = evaluator.DECISION_MODE_REGIME_ADAPTIVE_V3
        self.assertEqual(evaluator.get_backtesting_service_requirements(), ())

        evaluator.decision_mode = evaluator.DECISION_MODE_LLM
        self.assertIsNone(evaluator.get_backtesting_service_requirements())

    @staticmethod
    def _regime_data(direction="BULLISH"):
        return {
            "4h": [
                {"evaluator": "trend.EMADivergenceTrendEvaluator", "bias": direction},
                {"evaluator": "trend.DoubleMovingAverageTrendEvaluator", "bias": direction},
                {"evaluator": "momentum.ADXMomentumEvaluator", "bias": direction},
            ],
            "1h": [
                {"evaluator": "trend.EMADivergenceTrendEvaluator", "bias": direction},
                {"evaluator": "trend.DoubleMovingAverageTrendEvaluator", "bias": direction},
                {"evaluator": "momentum.ADXMomentumEvaluator", "bias": direction},
            ],
            "15m": [
                {"evaluator": "momentum.MACDMomentumEvaluator", "bias": direction},
                {"evaluator": "momentum.RSIMomentumEvaluator", "bias": direction},
                {"evaluator": "momentum.BBMomentumEvaluator", "bias": direction},
            ],
        }

    def test_regime_adaptive_approves_a_trend_pullback_entry(self):
        decision = regime_adaptive_decision(
            self._regime_data(), ["15m", "1h", "4h"]
        )

        self.assertEqual(decision.action, "BUY")
        self.assertAlmostEqual(decision.confidence, 0.82)
        self.assertAlmostEqual(decision.signal_strength, 0.42)
        self.assertIn("trend-pullback-bullish", decision.rationale)

    def test_regime_adaptive_supports_bearish_short_entries(self):
        decision = regime_adaptive_decision(
            self._regime_data("BEARISH"), ["15m", "1h", "4h"]
        )

        self.assertEqual(decision.action, "SELL")

    def test_regime_adaptive_holds_when_higher_timeframe_trend_conflicts(self):
        data = self._regime_data()
        data["4h"][1]["bias"] = "BEARISH"

        decision = regime_adaptive_decision(data, ["15m", "1h", "4h"])

        self.assertEqual(decision.action, "HOLD")
        self.assertIn("4h trend evaluators conflict", decision.rationale)

    def test_regime_adaptive_holds_when_pullback_timing_is_not_aligned(self):
        data = self._regime_data()
        data["15m"][2]["bias"] = "BEARISH"

        decision = regime_adaptive_decision(data, ["15m", "1h", "4h"])

        self.assertEqual(decision.action, "HOLD")
        self.assertIn("15m pullback timing", decision.rationale)

    @staticmethod
    def _regime_v2_data(
        direction="BULLISH", *, regime="trend", bb_position=0.35,
        high_volatility=False,
    ):
        def snapshot(time_frame):
            return {
                "schema_version": 1,
                "regime": regime if time_frame in {"4h", "1h"} else "transition",
                "direction": direction,
                "adx": 35.0 if time_frame == "4h" else 30.0,
                "atr_pct": 1.0,
                "ema_spread_pct": 1.2,
                "bb_width_pct": 4.0,
                "bb_width_percentile": 0.5,
                "bb_position": bb_position,
                "high_volatility": high_volatility if time_frame == "15m" else False,
            }

        data = {}
        for time_frame in ("4h", "1h", "15m"):
            data[time_frame] = [{
                "evaluator": "market_regime.MarketRegimeEvaluator",
                "bias": direction,
                "metadata": snapshot(time_frame),
            }]
        data["15m"].extend([
            {"evaluator": "momentum.MACDMomentumEvaluator", "bias": direction},
            {"evaluator": "momentum.RSIMomentumEvaluator", "bias": direction},
        ])
        return data

    def test_regime_adaptive_v2_approves_measured_bullish_pullback(self):
        decision = regime_adaptive_v2_decision(
            self._regime_v2_data(), ["15m", "1h", "4h"]
        )

        self.assertEqual(decision.action, "BUY")
        self.assertGreaterEqual(decision.confidence, 0.76)
        self.assertGreaterEqual(decision.signal_strength, 0.36)
        self.assertIn("ADX 4h=35.00", decision.rationale)

    def test_regime_adaptive_v2_supports_measured_bearish_pullback(self):
        decision = regime_adaptive_v2_decision(
            self._regime_v2_data("BEARISH", bb_position=0.65),
            ["15m", "1h", "4h"],
        )

        self.assertEqual(decision.action, "SELL")

    def test_regime_adaptive_v2_holds_outside_trend_regime(self):
        decision = regime_adaptive_v2_decision(
            self._regime_v2_data(regime="range"), ["15m", "1h", "4h"]
        )

        self.assertEqual(decision.action, "HOLD")
        self.assertIn("not both trending", decision.rationale)

    def test_regime_adaptive_v2_holds_in_high_volatility(self):
        decision = regime_adaptive_v2_decision(
            self._regime_v2_data(high_volatility=True), ["15m", "1h", "4h"]
        )

        self.assertEqual(decision.action, "HOLD")
        self.assertIn("high-volatility", decision.rationale)

    def test_regime_adaptive_v2_holds_outside_pullback_zone(self):
        decision = regime_adaptive_v2_decision(
            self._regime_v2_data(bb_position=0.85), ["15m", "1h", "4h"]
        )

        self.assertEqual(decision.action, "HOLD")
        self.assertIn("outside the bullish pullback zone", decision.rationale)

    def test_regime_adaptive_v3_approves_established_4h_trend(self):
        decision = regime_adaptive_v3_decision(
            self._regime_v2_data(), ["15m", "1h", "4h"]
        )

        self.assertEqual(decision.action, "BUY")
        self.assertIn("Regime V3=", decision.rationale)
        self.assertIn("quality gate is satisfied", decision.rationale)

    def test_regime_adaptive_v3_holds_marginal_4h_trend(self):
        data = self._regime_v2_data()
        data["4h"][0]["metadata"]["adx"] = 34.99

        decision = regime_adaptive_v3_decision(
            data, ["15m", "1h", "4h"]
        )

        self.assertEqual(decision.action, "HOLD")
        self.assertIn("below the 35.00 quality gate", decision.rationale)

    def test_deterministic_alignment_approves_aligned_bullish_timeframes(self):
        decision = deterministic_alignment_decision(
            {
                "15m": [{"bias": "BULLISH"}, {"bias": "BULLISH"}],
                "1h": [{"bias": "BULLISH"}, {"bias": "BULLISH"}],
                "4h": [{"bias": "BULLISH"}, {"bias": "BULLISH"}],
            },
            ["15m", "1h", "4h"],
        )

        self.assertEqual(decision.action, "BUY")
        self.assertAlmostEqual(decision.confidence, 0.90)
        self.assertAlmostEqual(decision.signal_strength, 0.55)
        self.assertEqual(decision.stop_loss_pct, 2.0)
        self.assertEqual(decision.take_profit_pct, 4.0)

    def test_deterministic_alignment_holds_when_timeframes_conflict(self):
        decision = deterministic_alignment_decision(
            {
                "15m": [{"bias": "BULLISH"}],
                "1h": [{"bias": "BEARISH"}],
                "4h": [{"bias": "BULLISH"}],
            },
            ["15m", "1h", "4h"],
        )

        self.assertEqual(decision.action, "HOLD")
        self.assertEqual(decision.signal_strength, 0)

    def test_deterministic_alignment_applies_minimum_agreement_filter(self):
        decision = deterministic_alignment_decision(
            {
                "15m": [{"bias": "BULLISH"}, {"bias": "BULLISH"}, {"bias": "BEARISH"}],
                "1h": [{"bias": "BULLISH"}, {"bias": "BULLISH"}],
                "4h": [{"bias": "BULLISH"}, {"bias": "BULLISH"}],
            },
            ["15m", "1h", "4h"],
            min_timeframe_agreement=0.5,
        )

        self.assertEqual(decision.action, "HOLD")
        self.assertIn("below the required", decision.rationale)

    def test_deterministic_alignment_can_require_4h_trend_evaluator_confirmation(self):
        data = {
            "15m": [{"bias": "BULLISH"}],
            "1h": [{"bias": "BULLISH"}],
            "4h": [
                {"bias": "BULLISH", "evaluator": "EMADivergenceTrendEvaluator"},
                {"bias": "BEARISH", "evaluator": "DoubleMovingAverageTrendEvaluator"},
                {"bias": "BULLISH", "evaluator": "MACDMomentumEvaluator"},
            ],
        }

        baseline = deterministic_alignment_decision(data, ["15m", "1h", "4h"])
        filtered = deterministic_alignment_decision(
            data,
            ["15m", "1h", "4h"],
            require_4h_trend_alignment=True,
        )

        self.assertEqual(baseline.action, "BUY")
        self.assertEqual(filtered.action, "HOLD")
        self.assertIn("DoubleMovingAverageTrendEvaluator", filtered.rationale)

    def test_evaluator_signal_bias_uses_octobot_convention(self):
        self.assertEqual(evaluator_signal_bias(-0.01), "BULLISH")
        self.assertEqual(evaluator_signal_bias(0), "NEUTRAL")
        self.assertEqual(evaluator_signal_bias(0.01), "BEARISH")

    def test_approved_buy_uses_octobot_long_sign(self):
        guarded = DeterministicRiskGuard(RiskGuardSettings()).evaluate(_decision())

        self.assertTrue(guarded.approved)
        self.assertEqual(guarded.eval_note, -0.45)
        self.assertEqual(guarded.reason, "approved")

    def test_approved_sell_uses_octobot_short_sign_when_enabled(self):
        guarded = DeterministicRiskGuard(
            RiskGuardSettings(allow_sell_signals=True)
        ).evaluate(_decision(action="SELL"))

        self.assertTrue(guarded.approved)
        self.assertEqual(guarded.eval_note, 0.45)
        self.assertEqual(guarded.reason, "approved")

    def test_signal_is_clamped_to_deterministic_maximum(self):
        guarded = DeterministicRiskGuard(RiskGuardSettings()).evaluate(
            _decision(signal_strength=0.95)
        )

        self.assertTrue(guarded.approved)
        self.assertEqual(guarded.eval_note, -0.55)

    def test_rejected_decisions_are_neutral(self):
        cases = [
            (
                {"action": "HOLD", "stop_loss_pct": None, "take_profit_pct": None},
                "model_requested_hold",
            ),
            ({"action": "SELL"}, "sell_signals_disabled_in_long_only_mode"),
            ({"confidence": 0.69}, "confidence_below_threshold"),
            ({"signal_strength": 0.29}, "signal_strength_below_threshold"),
            ({"stop_loss_pct": 2.1}, "stop_loss_above_limit"),
            ({"take_profit_pct": 2.5}, "reward_risk_below_threshold"),
            ({"horizon_minutes": 1441}, "horizon_above_limit"),
        ]
        for overrides, reason in cases:
            with self.subTest(reason=reason):
                guarded = DeterministicRiskGuard(RiskGuardSettings()).evaluate(
                    _decision(**overrides)
                )
                self.assertFalse(guarded.approved)
                self.assertEqual(guarded.eval_note, 0)
                self.assertEqual(guarded.reason, reason)

    def test_trade_requires_protective_levels(self):
        with self.assertRaises(pydantic.ValidationError):
            _decision(stop_loss_pct=None)
        with self.assertRaises(pydantic.ValidationError):
            _decision(stop_loss_pct=0)

    def test_hold_accepts_zero_protective_levels(self):
        decision = _decision(
            action="HOLD", stop_loss_pct=0, take_profit_pct=0
        )
        guarded = DeterministicRiskGuard(RiskGuardSettings()).evaluate(decision)

        self.assertFalse(guarded.approved)
        self.assertEqual(guarded.reason, "model_requested_hold")

    def test_action_is_normalized(self):
        self.assertEqual(_decision(action=" buy ").action, "BUY")

    def test_invalid_guard_settings_are_rejected(self):
        with self.assertRaises(ValueError):
            RiskGuardSettings(min_signal_strength=0.8, max_signal_strength=0.5)

    def test_sqlite_journal_records_guard_result(self):
        with tempfile.TemporaryDirectory() as temporary_directory:
            database_path = pathlib.Path(temporary_directory) / "decisions.sqlite"
            decision = _decision()
            guarded = DeterministicRiskGuard(RiskGuardSettings()).evaluate(decision)
            journal = SQLiteDecisionJournal(str(database_path))

            journal.record(
                context={
                    "exchange_name": "kucoin",
                    "cryptocurrency": "Bitcoin",
                    "symbol": "BTC/USDT",
                    "triggered_at": 1_700_000_000,
                },
                model="qwen3:8b",
                prompt_version="test-v1",
                input_data={"15m": [{"eval_note": -0.4}]},
                output_data=decision.model_dump(mode="json"),
                guarded=guarded,
            )

            with sqlite3.connect(database_path) as connection:
                row = connection.execute(
                    "SELECT symbol, action, approved, eval_note, guard_reason "
                    "FROM ai_decisions"
                ).fetchone()

            self.assertEqual(row, ("BTC/USDT", "BUY", 1, -0.45, "approved"))
            self.assertIsNotNone(
                journal.latest_recorded_at(exchange_name="kucoin", symbol="BTC/USDT")
            )
            self.assertIsNone(
                journal.latest_recorded_at(exchange_name="kucoin", symbol="ETH/USDT")
            )
            replayed = journal.replay_decision(
                exchange_name="kucoin",
                symbol="BTC/USDT",
                triggered_at=1_700_000_000,
            )
            self.assertIsNotNone(replayed)
            self.assertTrue(replayed.approved)
            self.assertEqual(replayed.eval_note, -0.45)
            self.assertEqual(replayed.decision.action, "BUY")
            self.assertIsNone(
                journal.replay_decision(
                    exchange_name="kucoin",
                    symbol="BTC/USDT",
                    triggered_at=1_700_000_001,
                )
            )

    def test_sqlite_journal_links_paper_order_and_closed_outcome(self):
        with tempfile.TemporaryDirectory() as temporary_directory:
            database_path = pathlib.Path(temporary_directory) / "decisions.sqlite"
            decision = _decision(action="BUY")
            guarded = DeterministicRiskGuard(
                RiskGuardSettings()
            ).evaluate(decision)
            journal = SQLiteDecisionJournal(str(database_path))
            decision_id = journal.record(
                context={
                    "exchange_name": "kucoin",
                    "cryptocurrency": "Bitcoin",
                    "symbol": "BTC/USDT:USDT",
                    "triggered_at": 1_700_000_000,
                },
                model=None,
                prompt_version="deterministic-v1",
                input_data={"mode": "deterministic_alignment"},
                output_data=decision.model_dump(mode="json"),
                guarded=guarded,
            )
            now = datetime.datetime.now(datetime.timezone.utc)
            entry_event_id = journal.record_order_event(
                exchange_name="kucoin",
                symbol="BTC/USDT:USDT",
                order={
                    "id": "entry-1",
                    "status": "filled",
                    "side": "buy",
                    "type": "market",
                    "amount": 2,
                    "filled": 2,
                    "price": 100,
                    "average": 100,
                    "fee": {"cost": 1, "currency": "USDT"},
                    "reduceOnly": False,
                },
                update_type="update",
                is_from_bot=True,
                occurred_at=now + datetime.timedelta(seconds=1),
            )
            exit_event_id = journal.record_order_event(
                exchange_name="kucoin",
                symbol="BTC/USDT:USDT",
                order={
                    "id": "exit-1",
                    "status": "filled",
                    "side": "sell",
                    "type": "sell_limit",
                    "amount": 2,
                    "filled": 2,
                    "price": 110,
                    "average": 110,
                    "fee": {"cost": 1, "currency": "USDT"},
                    "reduceOnly": True,
                },
                update_type="update",
                is_from_bot=True,
                occurred_at=now + datetime.timedelta(seconds=2),
            )
            duplicate_exit_id = journal.record_order_event(
                exchange_name="kucoin",
                symbol="BTC/USDT:USDT",
                order={
                    "id": "exit-1",
                    "status": "filled",
                    "side": "sell",
                    "type": "sell_limit",
                    "amount": 2,
                    "filled": 2,
                    "price": 110,
                    "average": 110,
                    "fee": {"cost": 1, "currency": "USDT"},
                    "reduceOnly": True,
                },
                update_type="update",
                is_from_bot=True,
                occurred_at=now + datetime.timedelta(seconds=2),
            )

            with sqlite3.connect(database_path) as connection:
                events = connection.execute(
                    "SELECT decision_id, COUNT(*) FROM ai_order_events "
                    "GROUP BY decision_id"
                ).fetchone()
                outcome = connection.execute(
                    """
                    SELECT decision_id, entry_event_id, exit_event_id, side,
                           gross_price_pnl, known_fees,
                           net_pnl_excluding_funding,
                           return_pct_excluding_funding, exit_reason
                    FROM ai_position_outcomes
                    """
                ).fetchone()
                integrity = connection.execute(
                    "PRAGMA integrity_check"
                ).fetchone()[0]

            self.assertEqual(events, (decision_id, 2))
            self.assertEqual(entry_event_id, outcome[1])
            self.assertEqual(exit_event_id, outcome[2])
            self.assertEqual(duplicate_exit_id, exit_event_id)
            self.assertEqual(outcome[0], decision_id)
            self.assertEqual(outcome[3], "long")
            self.assertAlmostEqual(outcome[4], 20)
            self.assertAlmostEqual(outcome[5], 2)
            self.assertAlmostEqual(outcome[6], 18)
            self.assertAlmostEqual(outcome[7], 0.09)
            self.assertEqual(outcome[8], "take_profit")
            self.assertEqual(integrity, "ok")

    def test_guard_rejection_does_not_create_order_event(self):
        with tempfile.TemporaryDirectory() as temporary_directory:
            database_path = pathlib.Path(temporary_directory) / "decisions.sqlite"
            decision = _decision(
                action="HOLD", stop_loss_pct=0, take_profit_pct=0
            )
            guarded = DeterministicRiskGuard(
                RiskGuardSettings()
            ).evaluate(decision)
            journal = SQLiteDecisionJournal(str(database_path))
            journal.record(
                context={
                    "exchange_name": "kucoin",
                    "cryptocurrency": "Bitcoin",
                    "symbol": "BTC/USDT:USDT",
                },
                model=None,
                prompt_version="deterministic-v1",
                input_data={},
                output_data=decision.model_dump(mode="json"),
                guarded=guarded,
            )

            with sqlite3.connect(database_path) as connection:
                self.assertEqual(
                    connection.execute(
                        "SELECT COUNT(*) FROM ai_order_events"
                    ).fetchone()[0],
                    0,
                )

    def test_daily_mode_callback_ignores_external_orders(self):
        mode = mock.Mock()
        mode._ai_decision_journal = mock.Mock()
        mode.exchange_manager.exchange_name = "kucoin"

        asyncio.run(
            DailyTradingMode._ai_order_notification_callback(
                mode,
                "kucoin",
                "exchange-id",
                "Bitcoin",
                "BTC/USDT:USDT",
                {"id": "external-1"},
                "update",
                False,
            )
        )

        mode._ai_decision_journal.record_order_event.assert_not_called()

    def test_daily_mode_callback_forwards_bot_order_to_journal(self):
        mode = mock.Mock()
        mode._ai_decision_journal = mock.Mock()
        mode.exchange_manager.exchange_name = "kucoin"
        order = {"id": "paper-1", "status": "open"}

        asyncio.run(
            DailyTradingMode._ai_order_notification_callback(
                mode,
                "kucoin",
                "exchange-id",
                "Bitcoin",
                "BTC/USDT:USDT",
                order,
                "update",
                True,
            )
        )

        mode._ai_decision_journal.record_order_event.assert_called_once_with(
            exchange_name="kucoin",
            symbol="BTC/USDT:USDT",
            order=order,
            update_type="update",
            is_from_bot=True,
        )


if __name__ == "__main__":
    unittest.main()
