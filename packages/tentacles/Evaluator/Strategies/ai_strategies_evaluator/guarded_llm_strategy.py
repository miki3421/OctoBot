#  Drakkar-Software OctoBot-Tentacles
#  Copyright (c) Drakkar-Software, All rights reserved.
#
#  This library is free software; you can redistribute it and/or
#  modify it under the terms of the GNU Lesser General Public
#  License as published by the Free Software Foundation; either
#  version 3.0 of the License, or (at your option) any later version.

"""Single-pass LLM strategy with deterministic risk enforcement."""

import asyncio
import datetime
import json
import os
import time
import typing

import octobot_commons.enums as commons_enums
import octobot_commons.evaluators_util as evaluators_util
import octobot_evaluators.api as evaluators_api
import octobot_evaluators.constants as evaluators_constants
import octobot_evaluators.enums as evaluators_enums
import octobot_evaluators.matrix as matrix
import octobot_services.api.services as services_api

from .ai_strategies import BaseLLMAIStrategyEvaluator
from .guarded_llm import (
    DeterministicRiskGuard,
    GuardedDecision,
    LLMTradingDecision,
    RiskGuardSettings,
    SQLiteDecisionJournal,
    deterministic_alignment_decision,
    evaluator_signal_bias,
    regime_adaptive_decision,
    regime_adaptive_v2_decision,
    regime_adaptive_v3_decision,
)


class GuardedLLMStrategyEvaluator(BaseLLMAIStrategyEvaluator):
    """Evaluate TA signals once and publish only deterministic, guarded notes."""

    MIN_CONFIDENCE_KEY = "min_confidence"
    MIN_SIGNAL_STRENGTH_KEY = "min_signal_strength"
    MAX_SIGNAL_STRENGTH_KEY = "max_signal_strength"
    MAX_STOP_LOSS_PCT_KEY = "max_stop_loss_pct"
    MIN_REWARD_RISK_KEY = "min_reward_risk_ratio"
    MAX_HORIZON_MINUTES_KEY = "max_horizon_minutes"
    ALLOW_SELL_SIGNALS_KEY = "allow_sell_signals"
    MINIMUM_INTERVAL_SECONDS_KEY = "minimum_interval_seconds"
    JOURNAL_PATH_KEY = "journal_path"
    ENABLE_BACKTESTING_LLM_KEY = "enable_backtesting_llm"
    REPLAY_BACKTESTING_DECISIONS_KEY = "replay_backtesting_decisions"
    LLM_TIMEOUT_SECONDS_KEY = "llm_timeout_seconds"
    DECISION_MODE_KEY = "decision_mode"
    MIN_TIMEFRAME_AGREEMENT_KEY = "min_timeframe_agreement"
    REQUIRE_4H_TREND_ALIGNMENT_KEY = "require_4h_trend_alignment"

    DECISION_MODE_DETERMINISTIC_ALIGNMENT = "deterministic_alignment"
    DECISION_MODE_REGIME_ADAPTIVE = "regime_adaptive"
    DECISION_MODE_REGIME_ADAPTIVE_V2 = "regime_adaptive_v2"
    DECISION_MODE_REGIME_ADAPTIVE_V3 = "regime_adaptive_v3"
    DECISION_MODE_LLM = "llm"

    PROMPT_VERSION = "guarded-ta-v1"
    DETERMINISTIC_PROMPT_VERSION = "deterministic-alignment-v1"
    DETERMINISTIC_MODEL = "deterministic-alignment"
    REGIME_PROMPT_VERSION = "regime-adaptive-v1"
    REGIME_MODEL = "regime-adaptive"
    REGIME_V2_PROMPT_VERSION = "regime-adaptive-v2"
    REGIME_V2_MODEL = "regime-adaptive-v2"
    REGIME_V3_PROMPT_VERSION = "regime-adaptive-v3"
    REGIME_V3_MODEL = "regime-adaptive-v3"
    DEFAULT_JOURNAL_PATH = "/octobot/user/ai_decisions.sqlite"

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.evaluator_types = [evaluators_enums.EvaluatorMatrixTypes.TA.value]
        self.minimum_interval_seconds = 900
        self.llm_timeout_seconds = 120
        self.enable_backtesting_llm = False
        self.replay_backtesting_decisions = True
        self.decision_mode = self.DECISION_MODE_DETERMINISTIC_ALIGNMENT
        self.min_timeframe_agreement = 0.0
        self.require_4h_trend_alignment = False
        self._last_evaluation_monotonic: dict[tuple[str, str], float] = {}
        self._last_replay_triggered_at: dict[tuple[str, str], int] = {}
        self._evaluation_locks: dict[tuple[str, str], asyncio.Lock] = {}
        self._risk_guard = DeterministicRiskGuard(RiskGuardSettings())
        self._journal = SQLiteDecisionJournal(self.DEFAULT_JOURNAL_PATH)

    @classmethod
    def get_default_config(cls, time_frames: typing.Optional[list[str]] = None) -> dict:
        config = super().get_default_config(time_frames)
        config.update(
            {
                cls.MODEL_KEY: "qwen3:8b",
                cls.MAX_TOKENS_KEY: 384,
                cls.TEMPERATURE_KEY: 0.0,
                cls.EVALUATOR_TYPES_KEY: [evaluators_enums.EvaluatorMatrixTypes.TA.value],
                cls.OUTPUT_FORMAT_KEY: "with_confidence",
                cls.USE_DEEP_AGENT_KEY: False,
                cls.MIN_CONFIDENCE_KEY: 0.70,
                cls.MIN_SIGNAL_STRENGTH_KEY: 0.30,
                cls.MAX_SIGNAL_STRENGTH_KEY: 0.55,
                cls.MAX_STOP_LOSS_PCT_KEY: 2.0,
                cls.MIN_REWARD_RISK_KEY: 1.5,
                cls.MAX_HORIZON_MINUTES_KEY: 1440,
                cls.ALLOW_SELL_SIGNALS_KEY: False,
                cls.MINIMUM_INTERVAL_SECONDS_KEY: 900,
                cls.JOURNAL_PATH_KEY: cls.DEFAULT_JOURNAL_PATH,
                cls.ENABLE_BACKTESTING_LLM_KEY: False,
                cls.REPLAY_BACKTESTING_DECISIONS_KEY: True,
                cls.LLM_TIMEOUT_SECONDS_KEY: 60,
                cls.DECISION_MODE_KEY: cls.DECISION_MODE_DETERMINISTIC_ALIGNMENT,
                cls.MIN_TIMEFRAME_AGREEMENT_KEY: 0.0,
                cls.REQUIRE_4H_TREND_ALIGNMENT_KEY: False,
            }
        )
        return config

    def init_user_inputs(self, inputs: dict) -> None:
        super().init_user_inputs(inputs)
        defaults = self.get_default_config()
        min_confidence = self.UI.user_input(
            self.MIN_CONFIDENCE_KEY,
            commons_enums.UserInputTypes.FLOAT,
            defaults[self.MIN_CONFIDENCE_KEY],
            inputs,
            min_val=0.0,
            max_val=1.0,
            title="Minimum confidence required to approve a trade.",
        )
        min_signal_strength = self.UI.user_input(
            self.MIN_SIGNAL_STRENGTH_KEY,
            commons_enums.UserInputTypes.FLOAT,
            defaults[self.MIN_SIGNAL_STRENGTH_KEY],
            inputs,
            min_val=0.0,
            max_val=1.0,
            title="Minimum signal strength required to approve a trade.",
        )
        max_signal_strength = self.UI.user_input(
            self.MAX_SIGNAL_STRENGTH_KEY,
            commons_enums.UserInputTypes.FLOAT,
            defaults[self.MAX_SIGNAL_STRENGTH_KEY],
            inputs,
            min_val=0.0,
            max_val=1.0,
            title="Maximum signal strength forwarded to the trading mode.",
        )
        max_stop_loss_pct = self.UI.user_input(
            self.MAX_STOP_LOSS_PCT_KEY,
            commons_enums.UserInputTypes.FLOAT,
            defaults[self.MAX_STOP_LOSS_PCT_KEY],
            inputs,
            min_val=0.1,
            max_val=100.0,
            title="Maximum stop loss percentage accepted from the decision source.",
        )
        min_reward_risk_ratio = self.UI.user_input(
            self.MIN_REWARD_RISK_KEY,
            commons_enums.UserInputTypes.FLOAT,
            defaults[self.MIN_REWARD_RISK_KEY],
            inputs,
            min_val=0.1,
            title="Minimum take-profit to stop-loss ratio.",
        )
        max_horizon_minutes = self.UI.user_input(
            self.MAX_HORIZON_MINUTES_KEY,
            commons_enums.UserInputTypes.INT,
            defaults[self.MAX_HORIZON_MINUTES_KEY],
            inputs,
            min_val=1,
            title="Maximum decision horizon in minutes.",
        )
        allow_sell_signals = self.UI.user_input(
            self.ALLOW_SELL_SIGNALS_KEY,
            commons_enums.UserInputTypes.BOOLEAN,
            defaults[self.ALLOW_SELL_SIGNALS_KEY],
            inputs,
            title="Allow SELL signals. Keep disabled for the initial long-only profile.",
        )
        self.minimum_interval_seconds = self.UI.user_input(
            self.MINIMUM_INTERVAL_SECONDS_KEY,
            commons_enums.UserInputTypes.INT,
            defaults[self.MINIMUM_INTERVAL_SECONDS_KEY],
            inputs,
            min_val=60,
            title="Minimum delay between live decisions for the same symbol.",
        )
        journal_path = self.UI.user_input(
            self.JOURNAL_PATH_KEY,
            commons_enums.UserInputTypes.TEXT,
            defaults[self.JOURNAL_PATH_KEY],
            inputs,
            title="SQLite path used for the append-only AI decision journal.",
        )
        self.enable_backtesting_llm = self.UI.user_input(
            self.ENABLE_BACKTESTING_LLM_KEY,
            commons_enums.UserInputTypes.BOOLEAN,
            defaults[self.ENABLE_BACKTESTING_LLM_KEY],
            inputs,
            title="Allow live LLM calls during backtesting (disabled by default).",
        )
        self.replay_backtesting_decisions = self.UI.user_input(
            self.REPLAY_BACKTESTING_DECISIONS_KEY,
            commons_enums.UserInputTypes.BOOLEAN,
            defaults[self.REPLAY_BACKTESTING_DECISIONS_KEY],
            inputs,
            title="Replay recorded guarded decisions during backtesting without calling the LLM.",
        )
        self.llm_timeout_seconds = self.UI.user_input(
            self.LLM_TIMEOUT_SECONDS_KEY,
            commons_enums.UserInputTypes.INT,
            defaults[self.LLM_TIMEOUT_SECONDS_KEY],
            inputs,
            min_val=10,
            max_val=600,
            title="Maximum time allowed for a single LLM decision.",
        )
        self.decision_mode = self.UI.user_input(
            self.DECISION_MODE_KEY,
            commons_enums.UserInputTypes.OPTIONS,
            defaults[self.DECISION_MODE_KEY],
            inputs,
            options=[
                self.DECISION_MODE_DETERMINISTIC_ALIGNMENT,
                self.DECISION_MODE_REGIME_ADAPTIVE,
                self.DECISION_MODE_REGIME_ADAPTIVE_V2,
                self.DECISION_MODE_REGIME_ADAPTIVE_V3,
                self.DECISION_MODE_LLM,
            ],
            title=(
                "Decision source. deterministic_alignment uses only the configured "
                "technical evaluators; regime_adaptive, regime_adaptive_v2 and "
                "regime_adaptive_v3 are "
                "research-only trend-pullback models; llm enables the external model."
            ),
        )
        self.min_timeframe_agreement = self.UI.user_input(
            self.MIN_TIMEFRAME_AGREEMENT_KEY,
            commons_enums.UserInputTypes.FLOAT,
            defaults[self.MIN_TIMEFRAME_AGREEMENT_KEY],
            inputs,
            min_val=0.0,
            max_val=1.0,
            title=(
                "Research filter: minimum directional agreement required within "
                "each timeframe. Zero preserves the baseline."
            ),
        )
        self.require_4h_trend_alignment = self.UI.user_input(
            self.REQUIRE_4H_TREND_ALIGNMENT_KEY,
            commons_enums.UserInputTypes.BOOLEAN,
            defaults[self.REQUIRE_4H_TREND_ALIGNMENT_KEY],
            inputs,
            title=(
                "Research filter: require the 4h EMA and double-moving-average "
                "trend evaluators to match the trade direction."
            ),
        )
        self.evaluator_types = [evaluators_enums.EvaluatorMatrixTypes.TA.value]
        self._risk_guard = DeterministicRiskGuard(
            RiskGuardSettings(
                min_confidence=min_confidence,
                min_signal_strength=min_signal_strength,
                max_signal_strength=max_signal_strength,
                max_stop_loss_pct=max_stop_loss_pct,
                min_reward_risk_ratio=min_reward_risk_ratio,
                max_horizon_minutes=max_horizon_minutes,
                allow_sell_signals=allow_sell_signals,
            )
        )
        self._journal = SQLiteDecisionJournal(
            os.getenv("AI_DECISIONS_DB_PATH", journal_path)
        )

    def get_full_cycle_evaluator_types(self) -> tuple:
        return (evaluators_enums.EvaluatorMatrixTypes.TA.value,)

    def get_backtesting_service_requirements(self):
        """Avoid creating an AI service for the zero-inference baseline only."""

        if self.decision_mode in {
            self.DECISION_MODE_DETERMINISTIC_ALIGNMENT,
            self.DECISION_MODE_REGIME_ADAPTIVE,
            self.DECISION_MODE_REGIME_ADAPTIVE_V2,
            self.DECISION_MODE_REGIME_ADAPTIVE_V3,
        }:
            return ()
        return None

    async def matrix_callback(
        self,
        matrix_id,
        evaluator_name,
        evaluator_type,
        eval_note,
        eval_note_type,
        eval_note_description,
        eval_note_metadata,
        exchange_name,
        cryptocurrency,
        symbol,
        time_frame,
        **kwargs,
    ):
        if evaluator_type != evaluators_enums.EvaluatorMatrixTypes.TA.value or not symbol:
            return

        key = (cryptocurrency, symbol)
        lock = self._evaluation_locks.setdefault(key, asyncio.Lock())
        if lock.locked():
            return

        context = {
            "exchange_name": exchange_name,
            "cryptocurrency": cryptocurrency,
            "symbol": symbol,
            "trigger_time_frame": time_frame,
            "triggered_at": self._get_triggered_at(
                matrix_id, exchange_name, cryptocurrency, symbol, time_frame
            ),
        }
        if self.decision_mode in {
            self.DECISION_MODE_DETERMINISTIC_ALIGNMENT,
            self.DECISION_MODE_REGIME_ADAPTIVE,
            self.DECISION_MODE_REGIME_ADAPTIVE_V2,
            self.DECISION_MODE_REGIME_ADAPTIVE_V3,
        }:
            await self._evaluate_deterministic_mode(matrix_id, context)
            return
        if self._is_in_backtesting() and not self.enable_backtesting_llm:
            if not self.replay_backtesting_decisions:
                return
            await self._replay_decision(context, key)
            return
        now = time.monotonic()
        if not self._is_in_backtesting() and (
            now - self._last_evaluation_monotonic.get(key, 0)
            < self.minimum_interval_seconds
        ):
            return

        async with lock:
            if not self._is_in_backtesting() and self._has_recent_journal_entry(context):
                return
            technical_data = self._collect_technical_data(
                matrix_id, exchange_name, cryptocurrency, symbol
            )
            if not technical_data:
                return
            if not self._is_in_backtesting():
                self._last_evaluation_monotonic[key] = time.monotonic()
            await self._evaluate_single_pass(technical_data, context)

    async def _evaluate_deterministic_mode(
        self, matrix_id: str, context: dict
    ) -> None:
        """Publish and journal one of the zero-inference deterministic modes."""

        key = (context["cryptocurrency"], context["symbol"])
        triggered_at = context["triggered_at"]
        if triggered_at is None:
            return
        if self._last_replay_triggered_at.get(key) == triggered_at:
            return
        self._last_replay_triggered_at[key] = triggered_at
        if not self._is_in_backtesting() and self._has_recent_journal_entry(context):
            return

        technical_data = self._collect_technical_data(
            matrix_id,
            context["exchange_name"],
            context["cryptocurrency"],
            context["symbol"],
        )
        if not technical_data:
            return
        if self.decision_mode == self.DECISION_MODE_REGIME_ADAPTIVE_V3:
            decision = regime_adaptive_v3_decision(
                technical_data, self.strategy_time_frames
            )
            model = self.REGIME_V3_MODEL
            prompt_version = self.REGIME_V3_PROMPT_VERSION
        elif self.decision_mode == self.DECISION_MODE_REGIME_ADAPTIVE_V2:
            decision = regime_adaptive_v2_decision(
                technical_data, self.strategy_time_frames
            )
            model = self.REGIME_V2_MODEL
            prompt_version = self.REGIME_V2_PROMPT_VERSION
        elif self.decision_mode == self.DECISION_MODE_REGIME_ADAPTIVE:
            decision = regime_adaptive_decision(
                technical_data, self.strategy_time_frames
            )
            model = self.REGIME_MODEL
            prompt_version = self.REGIME_PROMPT_VERSION
        else:
            decision = deterministic_alignment_decision(
                technical_data,
                self.strategy_time_frames,
                min_timeframe_agreement=self.min_timeframe_agreement,
                require_4h_trend_alignment=self.require_4h_trend_alignment,
            )
            model = self.DETERMINISTIC_MODEL
            prompt_version = self.DETERMINISTIC_PROMPT_VERSION
        guarded = self._risk_guard.evaluate(decision)
        self.eval_note = guarded.eval_note
        if not self._is_in_backtesting():
            try:
                self._journal.record(
                    context=context,
                    model=model,
                    prompt_version=prompt_version,
                    input_data=technical_data,
                    output_data=decision.model_dump(mode="json"),
                    guarded=guarded,
                )
            except Exception as error:
                self.logger.warning(f"Unable to write baseline decision journal: {error}")
        await self.evaluation_completed(
            cryptocurrency=context["cryptocurrency"],
            symbol=context["symbol"],
            time_frame=None,
            eval_note=self.eval_note,
            eval_note_description=self._format_description(guarded),
            eval_time=triggered_at,
            notify=True,
            origin_consumer=self.consumer_instance,
        )

    def _get_triggered_at(
        self,
        matrix_id: str,
        exchange_name: str,
        cryptocurrency: str,
        symbol: str,
        time_frame,
    ) -> int | None:
        time_frame_value = getattr(time_frame, "value", time_frame)
        latest_evaluation_time = matrix.get_latest_eval_time(
            matrix_id,
            exchange_name=exchange_name,
            tentacle_type=evaluators_enums.EvaluatorMatrixTypes.TA.value,
            cryptocurrency=cryptocurrency,
            symbol=symbol,
            time_frame=time_frame_value,
        )
        if latest_evaluation_time:
            return int(latest_evaluation_time)
        try:
            current_exchange_time = self._get_exchange_current_time(
                exchange_name, matrix_id
            )
            time_frame_seconds = (
                commons_enums.TimeFramesMinutes[
                    commons_enums.TimeFrames(time_frame_value)
                ]
                * 60
            )
            return int(current_exchange_time // time_frame_seconds * time_frame_seconds)
        except (KeyError, TypeError, ValueError):
            return None

    async def _replay_decision(self, context: dict, key: tuple[str, str]) -> None:
        triggered_at = context["triggered_at"]
        if triggered_at is None or self._last_replay_triggered_at.get(key) == triggered_at:
            return
        self._last_replay_triggered_at[key] = triggered_at
        try:
            guarded = self._journal.replay_decision(
                exchange_name=context["exchange_name"],
                symbol=context["symbol"],
                triggered_at=triggered_at,
            )
        except Exception as error:
            self.logger.warning(f"Unable to replay AI decision: {error}")
            guarded = None
        if guarded is None:
            decision = LLMTradingDecision(
                action="HOLD",
                confidence=0,
                signal_strength=0,
                horizon_minutes=1,
                rationale="No recorded AI decision matches this candle close.",
                invalidation="No trade is allowed without a recorded decision.",
            )
            guarded = GuardedDecision(False, 0.0, "no_replay_decision", decision)

        self.eval_note = guarded.eval_note
        await self.evaluation_completed(
            cryptocurrency=context["cryptocurrency"],
            symbol=context["symbol"],
            time_frame=None,
            eval_note=self.eval_note,
            eval_note_description=f"Replay: {self._format_description(guarded)}",
            eval_time=triggered_at,
            notify=True,
            origin_consumer=self.consumer_instance,
        )

    def _has_recent_journal_entry(self, context: dict) -> bool:
        try:
            latest = self._journal.latest_recorded_at(
                exchange_name=context["exchange_name"], symbol=context["symbol"]
            )
        except Exception as error:
            self.logger.warning(
                f"Unable to check the AI decision journal rate limit: {error}"
            )
            return True
        if latest is None:
            return False
        elapsed = datetime.datetime.now(datetime.timezone.utc) - latest
        return elapsed.total_seconds() < self.minimum_interval_seconds

    def _collect_technical_data(
        self, matrix_id: str, exchange_name: str, cryptocurrency: str, symbol: str
    ) -> dict:
        technical_data: dict[str, list[dict]] = {}
        for time_frame in self.strategy_time_frames:
            time_frame_value = getattr(time_frame, "value", time_frame)
            evaluations = matrix.get_evaluations_by_evaluator(
                matrix_id,
                exchange_name,
                evaluators_enums.EvaluatorMatrixTypes.TA.value,
                cryptocurrency,
                symbol,
                time_frame_value,
            )
            valid_evaluations = []
            for evaluator_name, evaluation in evaluations.items():
                value = evaluators_api.get_value(evaluation)
                value_type = evaluators_api.get_type(evaluation)
                if evaluators_util.check_valid_eval_note(
                    value,
                    value_type,
                    evaluators_constants.EVALUATOR_EVAL_DEFAULT_TYPE,
                ):
                    technical_evaluation = {
                        "evaluator": str(evaluator_name),
                        "eval_note": value,
                        "bias": evaluator_signal_bias(value),
                        "description": evaluators_api.get_description(evaluation) or "",
                    }
                    metadata = evaluators_api.get_metadata(evaluation)
                    if metadata is not None:
                        technical_evaluation["metadata"] = metadata
                    valid_evaluations.append(technical_evaluation)
            if valid_evaluations:
                technical_data[str(time_frame_value)] = valid_evaluations
        return technical_data

    async def _evaluate_single_pass(self, technical_data: dict, context: dict) -> None:
        ai_service = await services_api.get_ai_service(
            is_backtesting=self._is_in_backtesting()
        )
        messages = [
            ai_service.create_message("system", self._get_guarded_prompt(), self.model),
            ai_service.create_message(
                "user",
                "Technical evaluator data by timeframe:\n"
                f"{json.dumps(technical_data, ensure_ascii=False, default=str)}\n\n"
                "Return exactly one JSON decision matching the requested schema.",
                self.model,
            ),
        ]
        raw_output: dict = {}
        try:
            response = await asyncio.wait_for(
                ai_service.get_completion(
                    messages=messages,
                    model=self.model,
                    max_tokens=self.max_tokens,
                    temperature=self.temperature,
                    json_output=True,
                    response_schema=LLMTradingDecision,
                    reasoning_effort="none",
                ),
                timeout=self.llm_timeout_seconds,
            )
            parsed = ai_service.parse_completion_response(response, json_output=True)
            if not isinstance(parsed, dict) or parsed.get("error"):
                raise ValueError(f"Invalid structured response: {parsed}")
            raw_output = parsed
            decision = LLMTradingDecision.model_validate(parsed)
            guarded = self._risk_guard.evaluate(decision)
        except Exception as error:
            self.logger.error(f"Guarded LLM evaluation failed: {error}")
            decision = LLMTradingDecision(
                action="HOLD",
                confidence=0,
                signal_strength=0,
                horizon_minutes=1,
                rationale=f"LLM evaluation error: {error}",
                invalidation="No trade is allowed when evaluation fails.",
            )
            guarded = GuardedDecision(False, 0.0, "llm_or_schema_error", decision)
            raw_output = {"error": str(error), "response": raw_output}

        self.eval_note = guarded.eval_note
        description = self._format_description(guarded)
        try:
            self._journal.record(
                context=context,
                model=self.model,
                prompt_version=self.PROMPT_VERSION,
                input_data=technical_data,
                output_data=raw_output,
                guarded=guarded,
            )
        except Exception as error:
            self.logger.warning(f"Unable to write AI decision journal: {error}")

        await self.evaluation_completed(
            cryptocurrency=context["cryptocurrency"],
            symbol=context["symbol"],
            time_frame=None,
            eval_note=self.eval_note,
            eval_note_description=description,
            eval_time=0,
            notify=True,
            origin_consumer=self.consumer_instance,
        )

    @staticmethod
    def _format_description(guarded: GuardedDecision) -> str:
        decision = guarded.decision
        status = "APPROVED" if guarded.approved else "REJECTED"
        return (
            f"Risk Guard {status}: {decision.action}; reason={guarded.reason}; "
            f"confidence={decision.confidence:.2f}; strength={decision.signal_strength:.2f}; "
            f"horizon={decision.horizon_minutes}m; rationale={decision.rationale}"
        )

    @classmethod
    def _get_guarded_prompt(cls) -> str:
        return (
            "You are a cautious crypto technical-analysis decision engine operating in paper trading. "
            "Use only the supplied technical evaluator data; do not invent prices, indicators, news, "
            "portfolio data, support/resistance levels, or market events. Each supplied evaluator includes "
            "an authoritative bias field: BULLISH means buy direction, BEARISH means sell direction, and "
            "NEUTRAL means no directional bias. Do not reinterpret or contradict that field. Compare the "
            "15m signal with 1h and 4h context. "
            "Prefer HOLD when signals conflict or data quality is weak. BUY and SELL decisions must include "
            "positive stop_loss_pct and take_profit_pct values. The deterministic application will reject "
            "confidence below 0.70, strength below 0.30, stop loss above 2%, reward/risk below 1.5, or horizon "
            "above 1440 minutes. Calibrate confidence from agreement in the supplied data; do not use a fixed "
            "default. In rationale and invalidation, cite only supplied evaluator names, notes, or bias fields; "
            "never cite unsupported price levels or indicator thresholds. Return JSON only with: action (BUY, "
            "SELL, HOLD), confidence (0..1), signal_strength (0..1), stop_loss_pct, take_profit_pct, "
            "horizon_minutes, rationale, invalidation."
        )
