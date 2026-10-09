"""P0-01: real temporary SQLite failures, no network and no live trader."""

import asyncio
import contextlib
import concurrent.futures
import datetime
import decimal
import pathlib
import sqlite3
import tempfile
import types
import unittest
from unittest import mock

from tentacles.Evaluator.Strategies.ai_strategies_evaluator.guarded_llm import (
    DeterministicRiskGuard, LLMTradingDecision, RiskGuardSettings, SQLiteDecisionJournal,
)
from tentacles.Evaluator.Strategies.ai_strategies_evaluator.guarded_llm_strategy import (
    GuardedLLMStrategyEvaluator,
)
from tentacles.Trading.Mode.daily_trading_mode.daily_trading import (
    DailyTradingMode, DailyTradingModeConsumer, DailyTradingModeProducer,
)
import octobot_trading.enums as enums


SYMBOL = "BTC/USDT:USDT"
KEY = "guarded_entry_authorization"
CONTEXT = dict(exchange_name="kucoin", cryptocurrency="BTC", symbol=SYMBOL, triggered_at=123)


def approved():
    decision = LLMTradingDecision(action="BUY", confidence=.8, signal_strength=.45,
        stop_loss_pct=1, take_profit_pct=2, horizon_minutes=240,
        rationale="test", invalidation="test")
    return DeterministicRiskGuard(RiskGuardSettings()).evaluate(decision)


def record(journal, guarded=None):
    guarded = guarded or approved()
    return journal.record(context=CONTEXT, model="test", prompt_version="test",
        input_data={}, output_data=guarded.decision.model_dump(), guarded=guarded)


def mode(journal):
    value = object.__new__(DailyTradingMode)
    value.trading_config = {"required_strategies": ["GuardedLLMStrategyEvaluator"],
                            "record_ai_trade_events": True, "entry_quarantine": False}
    value.exchange_manager = types.SimpleNamespace(exchange_name="kucoin",
        is_backtesting=False, is_trader_simulated=True, is_future=True)
    value._ai_decision_journal = journal
    value.logger = mock.Mock()
    return value


def consumer(journal):
    value = object.__new__(DailyTradingModeConsumer)
    value.trading_mode = mode(journal)
    value.DISABLE_BUY_ORDERS = value.DISABLE_SELL_ORDERS = False
    value._create_new_orders = mock.AsyncMock(return_value=["paper order"])
    original = value.create_new_orders
    async def isolated_p001_call(*args, **kwargs):
        # Isolate the accepted decision layer. P0-04 integration tests do not use this helper.
        with mock.patch("octobot.ai_strategy_lab.paper_runtime_authorization.entry_scope",
                        return_value=contextlib.nullcontext()):
            return await original(*args, **kwargs)
    value.create_new_orders = isolated_p001_call
    value.logger = mock.Mock()
    return value


def evaluator(journal):
    value = object.__new__(GuardedLLMStrategyEvaluator)
    value.logger = mock.Mock()
    value._journal = journal
    value._risk_guard = DeterministicRiskGuard(RiskGuardSettings())
    value._last_replay_triggered_at = {}
    value._is_in_backtesting = mock.Mock(return_value=False)
    value._has_recent_journal_entry = mock.Mock(return_value=False)
    value._collect_technical_data = mock.Mock(return_value={
        frame: [{"bias": "BULLISH"}] for frame in ("15m", "1h", "4h")})
    value.decision_mode = "deterministic_alignment"
    value.strategy_time_frames = ["15m", "1h", "4h"]
    value.min_timeframe_agreement = 0
    value.require_4h_trend_alignment = False
    value.consumer_instance = None
    value.evaluation_completed = mock.AsyncMock()
    return value


class OriginalFailureTest(unittest.IsolatedAsyncioTestCase):
    async def test_failed_decision_write_must_publish_neutral(self):
        journal = mock.Mock()
        journal.record.side_effect = sqlite3.OperationalError("disk full")
        value = evaluator(journal)
        await value._evaluate_deterministic_mode("matrix", CONTEXT)
        self.assertEqual(value.evaluation_completed.call_args.kwargs["eval_note"], 0)
        self.assertFalse(value.evaluation_completed.call_args.kwargs.get("eval_note_metadata", {}).get(KEY))

    async def test_missing_identity_must_not_enter(self):
        journal = mock.Mock()
        journal.execution_decision_id.return_value = None
        value = consumer(journal)
        result = await value.create_new_orders(SYMBOL, -.45, enums.EvaluatorStates.LONG.value)
        self.assertEqual(result, [])
        value._create_new_orders.assert_not_awaited()

    async def test_audit_failure_must_not_prevent_deterministic_horizon_exit(self):
        value = mode(mock.Mock())
        value.symbol = SYMBOL
        value._ai_decision_journal.record_protected_exit_event.side_effect = sqlite3.OperationalError("disk full")
        position = types.SimpleNamespace(size=decimal.Decimal("1"))
        value.exchange_manager.trader = types.SimpleNamespace(close_position=mock.AsyncMock(return_value=["exit"]))
        now = datetime.datetime.now(datetime.timezone.utc)
        entry = dict(entry_order_id="existing", created_at=now-datetime.timedelta(hours=25))
        with mock.patch("tentacles.Trading.Mode.daily_trading_mode.daily_trading.trading_api.get_open_orders", return_value=[]):
            await value._close_position_at_horizon(position, entry, decimal.Decimal(100), decimal.Decimal(99), 24, now)
        value.exchange_manager.trader.close_position.assert_awaited_once_with(position, emit_trading_signals=False)

    async def test_profit_lock_still_works_with_failed_audit_and_known_position(self):
        value = mode(mock.Mock())
        value.symbol = SYMBOL
        value._protected_exit_lock = asyncio.Lock()
        value._protected_exit_entry_cache = dict(
            entry_order_id="existing", side="buy", entry_price=100, quantity=1,
            created_at=datetime.datetime.now(datetime.timezone.utc),
        )
        value._ai_decision_journal.record_protected_exit_event.side_effect = sqlite3.OperationalError("locked")
        value.exchange_manager.exchange = mock.Mock()
        value.exchange_manager.trader = types.SimpleNamespace(edit_order=mock.AsyncMock(return_value=True))
        position = types.SimpleNamespace(symbol=SYMBOL, size=decimal.Decimal(1),
            quantity=decimal.Decimal(1), entry_price=decimal.Decimal(100), is_idle=lambda:False)
        stop = types.SimpleNamespace(reduce_only=True, order_type="stop_loss", origin_price=decimal.Decimal(99))
        prefix = "tentacles.Trading.Mode.daily_trading_mode.daily_trading."
        with (
            mock.patch(prefix+"trading_api.get_positions", return_value=[position]),
            mock.patch(prefix+"trading_api.get_open_orders", return_value=[stop]),
            mock.patch(prefix+"trading_personal_data.is_stop_order", return_value=True),
            mock.patch(prefix+"trading_personal_data.decimal_adapt_price", return_value=decimal.Decimal(101)),
        ):
            await value._manage_protected_exit(decimal.Decimal("101.2"))
        value.exchange_manager.trader.edit_order.assert_awaited_once()
        value._ai_decision_journal.get_open_position_entry.assert_not_called()
        value.logger.error.assert_called()


class JournalAuthorizationTest(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.path = pathlib.Path(self.directory.name) / "audit.sqlite"
        self.journal = SQLiteDecisionJournal(str(self.path), timeout_seconds=.01)
        self.decision_id = record(self.journal)

    def validate(self, token, *, consume=False, journal=None, **kwargs):
        return (journal or self.journal).validate_entry_authorization(token,
            kwargs.get("exchange", "kucoin"), kwargs.get("symbol", SYMBOL),
            kwargs.get("note", -.45), consume=consume)

    def test_persisted_authorization_and_claim_survive_restart(self):
        token = self.journal.authorize_entry(self.decision_id)
        restarted = SQLiteDecisionJournal(str(self.path))
        self.assertEqual(self.validate(token, journal=restarted), self.decision_id)
        self.assertEqual(self.validate(token, consume=True, journal=restarted), self.decision_id)
        with self.assertRaises(ValueError):
            self.validate(token, consume=True, journal=SQLiteDecisionJournal(str(self.path)))

    def test_duplicate_authorization_never_reissues_a_consumed_identity(self):
        token = self.journal.authorize_entry(self.decision_id)
        self.validate(token, consume=True)
        with self.assertRaises((ValueError, sqlite3.IntegrityError)):
            self.journal.authorize_entry(self.decision_id)

    def test_missing_decision_and_unpersisted_authorization_are_rejected(self):
        with self.assertRaises(ValueError):
            self.journal.authorize_entry(self.decision_id+1)
        with self.assertRaises(ValueError):
            self.validate({"decision_id": self.decision_id, "authorization_id": "not-persisted"})

    def test_exact_identity_not_note_and_time_matching(self):
        first = self.journal.authorize_entry(self.decision_id)
        second_id = record(self.journal)
        second = self.journal.authorize_entry(second_id)
        with self.assertRaises(ValueError):
            self.validate(dict(second, decision_id=self.decision_id))
        with self.assertRaises(ValueError):
            self.validate(first)
        self.assertEqual(self.validate(second), second_id)

    def test_stale_future_and_naive_decision_times_are_rejected(self):
        token = self.journal.authorize_entry(self.decision_id)
        now = datetime.datetime.now(datetime.timezone.utc)
        for value in [(now-datetime.timedelta(seconds=61)).isoformat(),
                      (now+datetime.timedelta(seconds=1)).isoformat(), "2026-09-23T01:00:00"]:
            with self.subTest(value=value), sqlite3.connect(self.path) as db:
                db.execute("UPDATE ai_decisions SET created_at=?", (value,))
            with self.assertRaises(ValueError):
                self.validate(token, consume=True)

    def test_context_and_note_mismatch_are_rejected(self):
        token = self.journal.authorize_entry(self.decision_id)
        for params in [dict(symbol="ETH/USDT:USDT"), dict(exchange="binance"),
                       dict(note=.45), dict(note=float("nan")), dict(note=float("inf"))]:
            with self.subTest(params=params), self.assertRaises(ValueError):
                self.validate(token, consume=True, **params)
        self.assertEqual(self.validate(token), self.decision_id)

    def test_rejected_decision_cannot_authorize(self):
        with sqlite3.connect(self.path) as db:
            db.execute("UPDATE ai_decisions SET approved=0")
        with self.assertRaises(ValueError):
            self.journal.authorize_entry(self.decision_id)

    def test_locked_journal_prevents_authorization_and_claim(self):
        token = self.journal.authorize_entry(self.decision_id)
        with sqlite3.connect(self.path) as locked:
            locked.execute("BEGIN EXCLUSIVE")
            with self.assertRaises(sqlite3.OperationalError):
                self.validate(token, consume=True)
            with self.assertRaises(sqlite3.OperationalError):
                self.journal.authorize_entry(self.decision_id)
        self.assertEqual(self.validate(token), self.decision_id)

    def test_failed_claim_transaction_rolls_back_and_never_reports_success(self):
        token = self.journal.authorize_entry(self.decision_id)
        with sqlite3.connect(self.path) as db:
            db.execute("CREATE TRIGGER fail_claim BEFORE INSERT ON ai_entry_claims BEGIN SELECT RAISE(ABORT, 'disk failure'); END")
        with self.assertRaises(sqlite3.IntegrityError):
            self.validate(token, consume=True)
        with sqlite3.connect(self.path) as db:
            self.assertEqual(db.execute("SELECT COUNT(*) FROM ai_entry_claims").fetchone()[0], 0)

    def test_concurrent_claim_has_exactly_one_winner(self):
        token = self.journal.authorize_entry(self.decision_id)
        def claim():
            try:
                return self.validate(token, consume=True, journal=SQLiteDecisionJournal(str(self.path)))
            except ValueError:
                return None
        with concurrent.futures.ThreadPoolExecutor(max_workers=2) as pool:
            results = list(pool.map(lambda _: claim(), range(2)))
        self.assertEqual(results.count(self.decision_id), 1)
        self.assertEqual(results.count(None), 1)

    def test_additive_migration_does_not_rewrite_old_decisions(self):
        with sqlite3.connect(self.path) as db:
            before = db.execute("SELECT * FROM ai_decisions").fetchall()
            db.execute("DROP TABLE ai_entry_claims")
            db.execute("DROP TABLE ai_entry_authorizations")
        self.journal.initialize()
        with sqlite3.connect(self.path) as db:
            self.assertEqual(db.execute("SELECT * FROM ai_decisions").fetchall(), before)
            self.assertEqual(db.execute("SELECT COUNT(*) FROM ai_entry_authorizations").fetchone()[0], 0)


class ExecutionBoundaryTest(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.path = pathlib.Path(self.directory.name)/"audit.sqlite"
        self.journal = SQLiteDecisionJournal(str(self.path), timeout_seconds=.01)
        self.decision_id = record(self.journal)

    async def enter(self, value, token=None, state=enums.EvaluatorStates.LONG.value):
        return await value.create_new_orders(SYMBOL, -.45, state, data={KEY: token} if token else {})

    async def test_only_one_simulated_entry_after_duplicate_delivery_and_restart(self):
        token = self.journal.authorize_entry(self.decision_id)
        first = consumer(self.journal)
        self.assertEqual(await self.enter(first, token), ["paper order"])
        second = consumer(SQLiteDecisionJournal(str(self.path)))
        self.assertEqual(await self.enter(second, token), [])
        second._create_new_orders.assert_not_awaited()

    async def test_locked_readonly_and_failed_write_produce_zero_entries(self):
        token = self.journal.authorize_entry(self.decision_id)
        value = consumer(self.journal)
        with sqlite3.connect(self.path) as locked:
            locked.execute("BEGIN EXCLUSIVE")
            self.assertEqual(await self.enter(value, token), [])
        self.path.chmod(0o444)
        try:
            self.assertEqual(await self.enter(value, token), [])
        finally:
            self.path.chmod(0o600)
        with sqlite3.connect(self.path) as db:
            db.execute("CREATE TRIGGER fail_claim BEFORE INSERT ON ai_entry_claims BEGIN SELECT RAISE(ABORT, 'disk failure'); END")
        self.assertEqual(await self.enter(value, token), [])
        value._create_new_orders.assert_not_awaited()

    async def test_partial_failure_after_decision_before_authorization_blocks_restart(self):
        value = consumer(SQLiteDecisionJournal(str(self.path)))
        self.assertEqual(await self.enter(value, {"decision_id":self.decision_id,"authorization_id":"missing"}), [])
        value._create_new_orders.assert_not_awaited()

    async def test_partial_failure_after_claim_does_not_retry_uncertain_entry(self):
        token = self.journal.authorize_entry(self.decision_id)
        self.journal.validate_entry_authorization(token, "kucoin", SYMBOL, -.45, consume=True)
        value = consumer(SQLiteDecisionJournal(str(self.path)))
        self.assertEqual(await self.enter(value, token), [])
        value._create_new_orders.assert_not_awaited()

    async def test_stale_token_state_mismatch_and_missing_journal_block(self):
        token = self.journal.authorize_entry(self.decision_id)
        value = consumer(self.journal)
        self.assertEqual(await self.enter(value, token, enums.EvaluatorStates.SHORT.value), [])
        with sqlite3.connect(self.path) as db:
            db.execute("UPDATE ai_decisions SET created_at='2020-01-01T00:00:00+00:00'")
        self.assertEqual(await self.enter(value, token), [])
        del value.trading_mode._ai_decision_journal
        self.assertEqual(await self.enter(value, token), [])
        value._create_new_orders.assert_not_awaited()

    async def test_guarded_path_refuses_non_simulated_trader(self):
        value = consumer(self.journal)
        value.trading_mode.exchange_manager.is_trader_simulated = False
        token = self.journal.authorize_entry(self.decision_id)
        self.assertEqual(await self.enter(value, token), [])
        value._create_new_orders.assert_not_awaited()

    async def test_quarantine_and_disabled_side_do_not_consume_authorization(self):
        token = self.journal.authorize_entry(self.decision_id)
        value = consumer(self.journal)
        value.trading_mode.trading_config["entry_quarantine"] = True
        self.assertEqual(await self.enter(value, token), [])
        value.trading_mode.trading_config["entry_quarantine"] = False
        value.DISABLE_BUY_ORDERS = True
        self.assertEqual(await self.enter(value, token), [])
        self.assertEqual(self.journal.validate_entry_authorization(token,"kucoin",SYMBOL,-.45),self.decision_id)

    async def test_reduce_only_and_stop_only_survive_missing_predictive_audit(self):
        value = consumer(None)
        value.trading_mode.trading_config["entry_quarantine"] = True
        value.trading_mode.execution_decision_id = mock.Mock(side_effect=sqlite3.OperationalError("locked"))
        value.trading_mode.record_execution_attempt = mock.Mock(side_effect=sqlite3.OperationalError("locked"))
        for key in [value.REDUCE_ONLY_KEY, value.STOP_ONLY]:
            with self.subTest(key=key):
                result = await value.create_new_orders(SYMBOL, .45, enums.EvaluatorStates.SHORT.value, data={key:True})
                self.assertEqual(result, ["paper order"])
                self.assertTrue(value._create_new_orders.call_args.kwargs["data"][value.REDUCE_ONLY_KEY])
        value.trading_mode.execution_decision_id.assert_not_called()

    async def test_producer_missing_identity_never_cancels_or_submits(self):
        value = object.__new__(DailyTradingModeProducer)
        value.trading_mode = mode(self.journal)
        value.logger = mock.Mock()
        value.final_eval = decimal.Decimal("-.45")
        value.state = None
        value._on_new_state = mock.AsyncMock()
        await value._set_state("BTC", SYMBOL, enums.EvaluatorStates.LONG)
        value._on_new_state.assert_not_awaited()

    async def test_evaluator_publishes_persisted_identity_in_metadata(self):
        value = evaluator(self.journal)
        await value._evaluate_deterministic_mode("matrix", CONTEXT)
        args = value.evaluation_completed.call_args.kwargs
        token = args["eval_note_metadata"][KEY]
        self.assertEqual(self.journal.validate_entry_authorization(token, "kucoin", SYMBOL, args["eval_note"]), token["decision_id"])

    async def test_evaluator_authorization_failure_publishes_neutral(self):
        value = evaluator(self.journal)
        with mock.patch.object(self.journal, "authorize_entry", side_effect=sqlite3.OperationalError("failed auth write")):
            await value._evaluate_deterministic_mode("matrix", CONTEXT)
        args = value.evaluation_completed.call_args.kwargs
        self.assertEqual(args["eval_note"], 0)
        self.assertNotIn(KEY, args.get("eval_note_metadata", {}))

    async def test_backtest_does_not_write_operational_journal(self):
        value = evaluator(mock.Mock())
        value._is_in_backtesting.return_value = True
        await value._evaluate_deterministic_mode("matrix", CONTEXT)
        value._journal.record.assert_not_called()
        value._journal.authorize_entry.assert_not_called()

    async def test_real_storage_failures_keep_evaluator_neutral(self):
        with sqlite3.connect(self.path) as locked:
            locked.execute("BEGIN EXCLUSIVE")
            value = evaluator(self.journal)
            await value._evaluate_deterministic_mode("matrix", CONTEXT)
            self.assertEqual(value.evaluation_completed.call_args.kwargs["eval_note"], 0)
        self.path.chmod(0o444)
        try:
            value = evaluator(self.journal)
            await value._evaluate_deterministic_mode("matrix", CONTEXT)
            self.assertEqual(value.evaluation_completed.call_args.kwargs["eval_note"], 0)
        finally:
            self.path.chmod(0o600)

    async def test_commit_failure_blocks_entry_even_after_claim_insert(self):
        token = self.journal.authorize_entry(self.decision_id)
        class FailedCommit(sqlite3.Connection):
            def __exit__(self, error_type, error, traceback):
                if error_type is None:
                    self.rollback()
                    raise sqlite3.OperationalError("commit failed")
                return super().__exit__(error_type, error, traceback)
        value = consumer(self.journal)
        original = self.journal._entry_connection
        calls = 0
        def connection():
            nonlocal calls
            calls += 1
            # First check succeeds; the mandatory durable claim cannot commit.
            return original() if calls == 1 else sqlite3.connect(self.path, factory=FailedCommit)
        with mock.patch.object(self.journal, "_entry_connection", side_effect=connection):
            self.assertEqual(await self.enter(value, token), [])
        value._create_new_orders.assert_not_awaited()
        with sqlite3.connect(self.path) as db:
            self.assertEqual(db.execute("SELECT COUNT(*) FROM ai_entry_claims").fetchone()[0], 0)

    async def test_uncertain_execution_failure_remains_consumed(self):
        token = self.journal.authorize_entry(self.decision_id)
        value = consumer(self.journal)
        value._create_new_orders.side_effect = RuntimeError("simulator interrupted")
        with self.assertRaises(RuntimeError):
            await self.enter(value, token)
        restarted = consumer(SQLiteDecisionJournal(str(self.path)))
        self.assertEqual(await self.enter(restarted, token), [])
        restarted._create_new_orders.assert_not_awaited()

    async def test_llm_branch_also_fails_closed_without_calling_any_model(self):
        value = evaluator(self.journal)
        value.model, value.max_tokens, value.temperature, value.llm_timeout_seconds = "fake", 10, 0, 1
        service = mock.Mock()
        service.get_completion = mock.AsyncMock(return_value="local fixture")
        service.parse_completion_response.return_value = approved().decision.model_dump()
        with (
            mock.patch("tentacles.Evaluator.Strategies.ai_strategies_evaluator.guarded_llm_strategy.services_api.get_ai_service", new=mock.AsyncMock(return_value=service)),
            mock.patch.object(self.journal, "record", side_effect=sqlite3.OperationalError("read only")),
        ):
            await value._evaluate_single_pass({}, CONTEXT)
        args = value.evaluation_completed.call_args.kwargs
        self.assertEqual(args["eval_note"], 0)
        self.assertNotIn(KEY, args.get("eval_note_metadata", {}))

    async def test_identity_flows_from_matrix_to_consumer_without_numeric_lookup(self):
        evaluated = evaluator(self.journal)
        await evaluated._evaluate_deterministic_mode("matrix", CONTEXT)
        published = evaluated.evaluation_completed.call_args.kwargs
        executor = consumer(self.journal)
        executor.trading_mode.execution_decision_id = mock.Mock(side_effect=AssertionError("numeric identity lookup forbidden"))
        executor.trading_mode.consumers = []
        producer = object.__new__(DailyTradingModeProducer)
        producer.trading_mode = executor.trading_mode
        producer.exchange_manager = executor.trading_mode.exchange_manager
        producer.exchange_manager.trader = types.SimpleNamespace(is_enabled=True)
        producer.exchange_name = "kucoin"
        producer.logger = mock.Mock()
        producer.state = None
        producer.apply_cancel_policies = mock.AsyncMock(return_value=(False, None))
        producer._send_alert_notification = mock.AsyncMock()
        async def create_state(**kwargs):
            await producer._set_state(kwargs["cryptocurrency"], kwargs["symbol"], enums.EvaluatorStates.LONG)
        producer.create_state = mock.AsyncMock(side_effect=create_state)
        async def submit(**kwargs):
            self.assertEqual(kwargs["data"][KEY], published["eval_note_metadata"][KEY])
            return await executor.create_new_orders(kwargs["symbol"], kwargs["final_note"], kwargs["state"].value, data=kwargs["data"])
        producer.submit_trading_evaluation = mock.AsyncMock(side_effect=submit)
        prefix = "tentacles.Trading.Mode.daily_trading_mode.daily_trading."
        node = {"value": published["eval_note"], "metadata": published["eval_note_metadata"]}
        with (
            mock.patch(prefix+"matrix.get_tentacle_nodes", return_value=[]),
            mock.patch(prefix+"matrix.get_tentacles_value_nodes", return_value=[node]),
            mock.patch(prefix+"evaluators_api.get_value", side_effect=lambda n:n["value"]),
            mock.patch(prefix+"evaluators_api.get_type", return_value=float),
            mock.patch(prefix+"evaluators_api.get_metadata", side_effect=lambda n:n["metadata"]),
            mock.patch(prefix+"evaluators_util.check_valid_eval_note", return_value=True),
        ):
            await producer.set_final_eval("matrix", "BTC", SYMBOL, None, "test")
        executor._create_new_orders.assert_awaited_once()
        executor.trading_mode.execution_decision_id.assert_not_called()
        # A later replay must not cancel protective orders or resubmit.
        producer.apply_cancel_policies.reset_mock()
        await producer._on_new_state("BTC", SYMBOL, enums.EvaluatorStates.LONG)
        producer.apply_cancel_policies.assert_not_awaited()

    async def test_matrix_does_not_reuse_metadata_for_missing_or_mixed_strategy(self):
        token = self.journal.authorize_entry(self.decision_id)
        producer = object.__new__(DailyTradingModeProducer)
        producer.exchange_name = "kucoin"
        producer.trading_mode = mode(self.journal)
        producer._entry_authorization = token
        producer.create_state = mock.AsyncMock()
        prefix = "tentacles.Trading.Mode.daily_trading_mode.daily_trading."
        node = {"value": -.45, "metadata": {KEY:token}}
        for nodes in [[], [dict(node, metadata={})], [node, node]]:
            with (
                mock.patch(prefix+"matrix.get_tentacle_nodes", return_value=[]),
                mock.patch(prefix+"matrix.get_tentacles_value_nodes", return_value=nodes),
                mock.patch(prefix+"evaluators_api.get_value", side_effect=lambda n:n["value"]),
                mock.patch(prefix+"evaluators_api.get_type", return_value=float),
                mock.patch(prefix+"evaluators_api.get_metadata", side_effect=lambda n:n["metadata"]),
                mock.patch(prefix+"evaluators_util.check_valid_eval_note", return_value=True),
            ):
                await producer.set_final_eval("matrix", "BTC", SYMBOL, None, "test")
                self.assertIsNone(producer._entry_authorization)


class LegacyQuarantineNeutralizationTest(unittest.IsolatedAsyncioTestCase):
    """work-card-2882e69d-789a-4bd6-b27a-06fe2c6118a7; fixtures only."""

    def producer(self):
        value = object.__new__(DailyTradingModeProducer)
        value.trading_mode = mode(mock.Mock())
        value.trading_mode.trading_config["entry_quarantine"] = True
        value.trading_mode.trading_config["entry_quarantine_reason"] = "fixture quarantine"
        value.exchange_manager = value.trading_mode.exchange_manager
        value.exchange_manager.trader = types.SimpleNamespace(is_enabled=True)
        value.exchange_name = "kucoin"
        value.logger = mock.Mock()
        value.state = enums.EvaluatorStates.LONG
        value.final_eval = decimal.Decimal("-.45")
        value._entry_authorization = {"decision_id": 1, "authorization_id": "fixture"}
        value.create_state = mock.AsyncMock()
        value.apply_cancel_policies = mock.AsyncMock()
        value.cancel_symbol_open_orders = mock.AsyncMock()
        value.submit_trading_evaluation = mock.AsyncMock()
        value._send_alert_notification = mock.AsyncMock()
        value.trading_mode.entry_decision_id = mock.Mock(side_effect=AssertionError("no entry lookup while quarantined"))
        value.trading_mode.execution_decision_id = mock.Mock(side_effect=AssertionError("no numeric lookup while quarantined"))
        return value

    async def test_quarantine_precedes_matrix_and_reports_only_once(self):
        value = self.producer()
        with mock.patch("tentacles.Trading.Mode.daily_trading_mode.daily_trading.matrix.get_tentacle_nodes") as nodes:
            for _ in range(2):
                await value.set_final_eval("fixture matrix", "BTC", SYMBOL, None, "fixture")
            nodes.assert_not_called()
        self.assertEqual(value.state, enums.EvaluatorStates.NEUTRAL)
        self.assertEqual(value.final_eval, decimal.Decimal("0"))
        self.assertIsNone(value._entry_authorization)
        value.create_state.assert_not_awaited()
        value.trading_mode.entry_decision_id.assert_not_called()
        value.trading_mode.execution_decision_id.assert_not_called()
        value.trading_mode._ai_decision_journal.record_execution_attempt.assert_called_once()
        value.logger.info.assert_called_once()
        value.trading_mode.logger.error.assert_not_called()

    async def test_quarantine_direct_state_never_validates_or_calls_order_callback(self):
        value = self.producer()
        value._on_new_state = mock.AsyncMock()
        for state in (enums.EvaluatorStates.VERY_LONG, enums.EvaluatorStates.VERY_SHORT):
            await value._set_state("BTC", SYMBOL, state)
        self.assertEqual(value.state, enums.EvaluatorStates.NEUTRAL)
        value.trading_mode.entry_decision_id.assert_not_called()
        value._on_new_state.assert_not_awaited()

    async def test_quarantine_direct_order_callback_never_cancels_or_submits(self):
        value = self.producer()
        await value._on_new_state("BTC", SYMBOL, enums.EvaluatorStates.LONG)
        value.trading_mode.entry_decision_id.assert_not_called()
        value.apply_cancel_policies.assert_not_awaited()
        value.cancel_symbol_open_orders.assert_not_awaited()
        value.submit_trading_evaluation.assert_not_awaited()
        value._send_alert_notification.assert_not_awaited()
        self.assertEqual(value.state, enums.EvaluatorStates.NEUTRAL)

    async def test_failed_audit_still_neutral_and_does_not_repeat(self):
        value = self.producer()
        value.trading_mode._ai_decision_journal.record_execution_attempt.side_effect = sqlite3.OperationalError("fixture disk full")
        for _ in range(2):
            await value._set_state("BTC", SYMBOL, enums.EvaluatorStates.LONG)
        self.assertEqual(value.state, enums.EvaluatorStates.NEUTRAL)
        value.trading_mode._ai_decision_journal.record_execution_attempt.assert_called_once()
        value.trading_mode.logger.error.assert_called_once()
        value.submit_trading_evaluation.assert_not_awaited()

    async def test_removing_quarantine_does_not_restore_old_token_or_bypass_gate(self):
        value = self.producer()
        await value._set_state("BTC", SYMBOL, enums.EvaluatorStates.LONG)
        value.trading_mode.trading_config["entry_quarantine"] = False
        value.final_eval = decimal.Decimal("-.45")
        value.trading_mode.entry_decision_id = mock.Mock(return_value=None)
        await value._on_new_state("BTC", SYMBOL, enums.EvaluatorStates.LONG)
        value.trading_mode.entry_decision_id.assert_called_once_with(SYMBOL, decimal.Decimal("-.45"), None)
        value.apply_cancel_policies.assert_not_awaited()
        value.submit_trading_evaluation.assert_not_awaited()

    async def test_historical_backtest_without_quarantine_keeps_existing_path(self):
        value = self.producer()
        value.trading_mode.trading_config["entry_quarantine"] = False
        value.exchange_manager.is_backtesting = True
        value.trading_mode.execution_decision_id = mock.Mock(return_value=123)
        value.state = None
        value._on_new_state = mock.AsyncMock()
        await value._set_state("BTC", SYMBOL, enums.EvaluatorStates.LONG)
        value.trading_mode.entry_decision_id.assert_not_called()
        value._on_new_state.assert_awaited_once()
        self.assertEqual(value.final_eval, decimal.Decimal("-.45"))


if __name__ == "__main__":
    unittest.main()
