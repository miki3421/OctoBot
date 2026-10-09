"""No network, no live trader: regression checks for the legacy audit."""
import decimal
import pathlib
import sqlite3
import tempfile
import types
import unittest
from unittest import mock

from tentacles.Trading.Mode.daily_trading_mode.daily_trading import (
    DailyTradingModeConsumer, DailyTradingModeProducer,
)
from tentacles.Evaluator.Strategies.ai_strategies_evaluator.guarded_llm import (
    SQLiteDecisionJournal, DeterministicRiskGuard, RiskGuardSettings, LLMTradingDecision,
)
import octobot_trading.enums as enums


class ExecutionJournalTest(unittest.TestCase):
    def test_fresh_identity_dedup_and_no_reuse_of_previous_buy(self):
        with tempfile.TemporaryDirectory() as directory:
            journal = SQLiteDecisionJournal(str(pathlib.Path(directory) / "audit.sqlite"))
            decision = LLMTradingDecision(action="BUY", confidence=.8, signal_strength=.45,
                stop_loss_pct=1, take_profit_pct=2, horizon_minutes=1440,
                rationale="test", invalidation="test")
            guarded = DeterministicRiskGuard(RiskGuardSettings()).evaluate(decision)
            def record(value):
                return journal.record(context={"exchange_name": "kucoin", "symbol": "BTC/USDT:USDT"},
                    model="test", prompt_version="test", input_data={}, output_data={}, guarded=value)
            decision_id = record(guarded)
            self.assertEqual(journal.execution_decision_id("kucoin", "BTC/USDT:USDT", guarded.eval_note), decision_id)
            self.assertIsNone(journal.execution_decision_id("kucoin", "ETH/USDT:USDT", guarded.eval_note))
            self.assertIsNone(journal.execution_decision_id("kucoin", "BTC/USDT:USDT", .5))
            journal.record_execution_attempt(decision_id, "strategy_quarantined", "test")
            journal.record_execution_attempt(decision_id, "strategy_quarantined", "test")
            with sqlite3.connect(journal.database_path) as db:
                self.assertEqual(db.execute("SELECT count(*) FROM ai_execution_attempts").fetchone()[0], 1)
                db.execute("UPDATE ai_decisions SET created_at='2020-01-01T00:00:00+00:00'")
            self.assertIsNone(journal.execution_decision_id("kucoin", "BTC/USDT:USDT", guarded.eval_note))
            record(guarded)
            record(DeterministicRiskGuard(RiskGuardSettings()).evaluate(decision.model_copy(update={"action": "HOLD"})))
            self.assertIsNone(journal.execution_decision_id("kucoin", "BTC/USDT:USDT", guarded.eval_note))


class ExecutionPolicyTest(unittest.IsolatedAsyncioTestCase):
    def mode(self, quarantined=True):
        return types.SimpleNamespace(
            trading_config={"entry_quarantine": quarantined, "entry_quarantine_reason": "audit"},
            execution_decision_id=mock.Mock(return_value=123),
            record_execution_attempt=mock.Mock(),
        )

    async def test_quarantine_precedes_cancellation_and_submit_even_on_new_state(self):
        producer = object.__new__(DailyTradingModeProducer)
        producer.trading_mode = self.mode()
        producer.logger = mock.Mock()
        producer.final_eval = decimal.Decimal("-.45")
        producer.state = None
        producer._on_new_state = mock.AsyncMock()
        await producer._set_state("BTC", "BTC/USDT:USDT", enums.EvaluatorStates.LONG)
        producer._on_new_state.assert_not_awaited()
        self.assertEqual(producer.state, enums.EvaluatorStates.NEUTRAL)
        self.assertEqual(producer.final_eval, decimal.Decimal("0"))
        producer.trading_mode.execution_decision_id.assert_not_called()
        producer.trading_mode.record_execution_attempt.assert_called_once_with(None, "strategy_quarantined", "audit")

    async def test_repeated_signal_is_audited_without_creating_duplicate_orders(self):
        producer = object.__new__(DailyTradingModeProducer)
        producer.trading_mode = self.mode(False)
        producer.final_eval = decimal.Decimal("-.45")
        producer.state = enums.EvaluatorStates.LONG
        producer._on_new_state = mock.AsyncMock()
        await producer._set_state("BTC", "BTC/USDT:USDT", enums.EvaluatorStates.LONG)
        producer._on_new_state.assert_not_awaited()
        producer.trading_mode.record_execution_attempt.assert_called_once_with(123, "state_unchanged")

    async def test_consumer_blocks_entries_but_preserves_reduce_only_and_stop_paths(self):
        consumer = object.__new__(DailyTradingModeConsumer)
        consumer.trading_mode = self.mode()
        consumer.DISABLE_BUY_ORDERS = consumer.DISABLE_SELL_ORDERS = False
        consumer._create_new_orders = mock.AsyncMock(return_value=["test order"])
        result = await consumer.create_new_orders("BTC/USDT:USDT", -.45, enums.EvaluatorStates.LONG.value)
        self.assertEqual(result, [])
        consumer._create_new_orders.assert_not_awaited()
        for key in [consumer.REDUCE_ONLY_KEY, consumer.STOP_ONLY]:
            result = await consumer.create_new_orders("BTC/USDT:USDT", .45, enums.EvaluatorStates.SHORT.value,
                **{consumer.CREATE_ORDER_DATA_PARAM: {key: True}})
            self.assertEqual(result, ["test order"])

    async def test_disabled_side_is_not_reported_as_insufficient_funds(self):
        consumer = object.__new__(DailyTradingModeConsumer)
        consumer.trading_mode = self.mode(False)
        consumer.DISABLE_BUY_ORDERS = True
        consumer._create_new_orders = mock.AsyncMock()
        self.assertEqual(await consumer.create_new_orders("BTC/USDT:USDT", -.45, enums.EvaluatorStates.LONG.value), [])
        consumer._create_new_orders.assert_not_awaited()
        consumer.trading_mode.record_execution_attempt.assert_called_once_with(123, "side_disabled", "")

    async def test_execution_failure_is_persisted_and_raised(self):
        consumer = object.__new__(DailyTradingModeConsumer)
        consumer.trading_mode = self.mode(False)
        consumer.DISABLE_BUY_ORDERS = consumer.DISABLE_SELL_ORDERS = False
        consumer._create_new_orders = mock.AsyncMock(side_effect=ValueError("bad volume"))
        with self.assertRaises(ValueError):
            await consumer.create_new_orders("BTC/USDT:USDT", -.45, enums.EvaluatorStates.LONG.value)
        consumer.trading_mode.record_execution_attempt.assert_called_with(123, "execution_error", "ValueError: bad volume")
