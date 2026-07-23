#  Drakkar-Software OctoBot-Tentacles
#  Copyright (c) Drakkar-Software, All rights reserved.
#
#  This library is free software; you can redistribute it and/or
#  modify it under the terms of the GNU Lesser General Public
#  License as published by the Free Software Foundation; either
#  version 3.0 of the License, or (at your option) any later version.

"""Validated LLM decisions, deterministic risk checks and SQLite journaling."""

import dataclasses
import datetime
import json
import math
import pathlib
import sqlite3
import typing

import pydantic


def evaluator_signal_bias(value: float) -> str:
    """Return OctoBot's unambiguous directional meaning for an evaluator note."""

    if value < 0:
        return "BULLISH"
    if value > 0:
        return "BEARISH"
    return "NEUTRAL"


def deterministic_alignment_decision(
    technical_data: dict[str, list[dict]],
    required_time_frames: typing.Iterable[typing.Any],
    *,
    min_timeframe_agreement: float = 0.0,
    require_4h_trend_alignment: bool = False,
) -> "LLMTradingDecision":
    """Create a reproducible proposal when all configured timeframes agree.

    This baseline deliberately uses only evaluator notes already available in the
    matrix.  It never derives a price, indicator level, news item or portfolio
    state.  A missing, tied or conflicting timeframe yields HOLD.
    """

    summaries: list[tuple[str, str, float, int, int]] = []
    for configured_time_frame in required_time_frames:
        time_frame = str(getattr(configured_time_frame, "value", configured_time_frame))
        evaluations = technical_data.get(time_frame, [])
        bullish = sum(
            1
            for evaluation in evaluations
            if evaluation.get("bias") == "BULLISH"
        )
        bearish = sum(
            1
            for evaluation in evaluations
            if evaluation.get("bias") == "BEARISH"
        )
        directional_count = bullish + bearish
        if directional_count == 0 or bullish == bearish:
            return LLMTradingDecision(
                action="HOLD",
                confidence=0,
                signal_strength=0,
                horizon_minutes=1,
                rationale=(
                    f"Deterministic baseline: {time_frame} has no unambiguous "
                    "directional evaluator consensus."
                ),
                invalidation="All required timeframes must have an unambiguous common direction.",
            )
        direction = "BULLISH" if bullish > bearish else "BEARISH"
        agreement = abs(bullish - bearish) / directional_count
        summaries.append((time_frame, direction, agreement, bullish, bearish))

    directions = {summary[1] for summary in summaries}
    if len(directions) != 1:
        formatted = ", ".join(
            f"{time_frame}={direction}" for time_frame, direction, *_ in summaries
        )
        return LLMTradingDecision(
            action="HOLD",
            confidence=0,
            signal_strength=0,
            horizon_minutes=1,
            rationale=f"Deterministic baseline: timeframe directions conflict ({formatted}).",
            invalidation="All required timeframes must align before an entry.",
        )

    weakest_agreement = min(summary[2] for summary in summaries)
    direction = summaries[0][1]
    if weakest_agreement < min_timeframe_agreement:
        return LLMTradingDecision(
            action="HOLD",
            confidence=0,
            signal_strength=0,
            horizon_minutes=1,
            rationale=(
                "Deterministic filter: the weakest timeframe agreement "
                f"({weakest_agreement:.2f}) is below the required "
                f"{min_timeframe_agreement:.2f}."
            ),
            invalidation="Every timeframe must meet the configured agreement threshold.",
        )

    if require_4h_trend_alignment:
        required_trend_evaluators = {
            "EMADivergenceTrendEvaluator",
            "DoubleMovingAverageTrendEvaluator",
        }
        four_hour_trends = {
            str(evaluation.get("evaluator", "")).rsplit(".", 1)[-1]: evaluation.get("bias")
            for evaluation in technical_data.get("4h", [])
            if str(evaluation.get("evaluator", "")).rsplit(".", 1)[-1]
            in required_trend_evaluators
        }
        missing = required_trend_evaluators - four_hour_trends.keys()
        misaligned = sorted(
            evaluator
            for evaluator, bias in four_hour_trends.items()
            if bias != direction
        )
        if missing or misaligned:
            details = []
            if missing:
                details.append(f"missing={','.join(sorted(missing))}")
            if misaligned:
                details.append(f"misaligned={','.join(misaligned)}")
            return LLMTradingDecision(
                action="HOLD",
                confidence=0,
                signal_strength=0,
                horizon_minutes=1,
                rationale=(
                    "Deterministic 4h trend filter rejected the entry "
                    f"({'; '.join(details)})."
                ),
                invalidation=(
                    "Both configured 4h trend evaluators must match the common direction."
                ),
            )

    action = "BUY" if direction == "BULLISH" else "SELL"
    formatted = ", ".join(
        f"{time_frame}={time_direction} ({bullish}/{bullish + bearish})"
        for time_frame, time_direction, _, bullish, bearish in summaries
    )
    return LLMTradingDecision(
        action=action,
        confidence=0.70 + 0.20 * weakest_agreement,
        signal_strength=0.30 + 0.25 * weakest_agreement,
        stop_loss_pct=2.0,
        take_profit_pct=4.0,
        horizon_minutes=240,
        rationale=f"Deterministic alignment: {formatted}.",
        invalidation="Any required timeframe loses its common directional consensus.",
    )


def _evaluator_short_name(evaluation: dict) -> str:
    """Return an evaluator class name from OctoBot's matrix representation."""

    return str(evaluation.get("evaluator", "")).rsplit(".", 1)[-1]


def _required_evaluator_biases(
    technical_data: dict[str, list[dict]], time_frame: str, evaluator_names: tuple[str, ...]
) -> tuple[dict[str, str], list[str]]:
    """Get the named directional notes, reporting absent or neutral evaluators."""

    available = {
        _evaluator_short_name(evaluation): evaluation.get("bias")
        for evaluation in technical_data.get(time_frame, [])
    }
    biases = {name: available.get(name) for name in evaluator_names}
    invalid = [
        name for name, bias in biases.items()
        if bias not in {"BULLISH", "BEARISH"}
    ]
    return typing.cast(dict[str, str], biases), invalid


def _regime_hold(rationale: str, invalidation: str) -> "LLMTradingDecision":
    return LLMTradingDecision(
        action="HOLD",
        confidence=0,
        signal_strength=0,
        horizon_minutes=1,
        rationale=rationale,
        invalidation=invalidation,
    )


def regime_adaptive_decision(
    technical_data: dict[str, list[dict]],
    required_time_frames: typing.Iterable[typing.Any],
) -> "LLMTradingDecision":
    """Propose a trend-pullback entry using independent TA evaluator roles.

    This is a research mode, deliberately separate from ``deterministic_alignment``.
    It relies only on evaluator notes already present in the OctoBot matrix:

    * EMA divergence, double moving average and ADX establish a 4h/1h trend;
    * MACD, RSI and Bollinger Bands select a 15m pullback timing in that trend.

    The Bollinger evaluator is intentionally a *timing* signal, not a trend vote:
    its existing OctoBot convention emits a bullish note on a pullback below the
    middle band and a bearish note on a rally above it.  An unconfirmed, ranging
    or conflicting market therefore produces HOLD rather than a forced trade.
    """

    expected_time_frames = {"15m", "1h", "4h"}
    configured_time_frames = {
        str(getattr(time_frame, "value", time_frame))
        for time_frame in required_time_frames
    }
    missing_time_frames = expected_time_frames - configured_time_frames
    if missing_time_frames:
        return _regime_hold(
            "Regime research mode requires 15m, 1h and 4h technical data; "
            f"missing configuration={','.join(sorted(missing_time_frames))}.",
            "The regime classifier is invalid without all three required timeframes.",
        )

    trend_evaluators = (
        "EMADivergenceTrendEvaluator",
        "DoubleMovingAverageTrendEvaluator",
        "ADXMomentumEvaluator",
    )
    timing_evaluators = (
        "MACDMomentumEvaluator",
        "RSIMomentumEvaluator",
        "BBMomentumEvaluator",
    )

    four_hour, invalid_four_hour = _required_evaluator_biases(
        technical_data, "4h", trend_evaluators
    )
    if invalid_four_hour:
        return _regime_hold(
            "Regime=no-trade: 4h trend evidence is missing or neutral "
            f"({','.join(invalid_four_hour)}).",
            "A trend entry requires directional EMA, double-moving-average and ADX evidence on 4h.",
        )
    four_hour_directions = set(four_hour.values())
    if len(four_hour_directions) != 1:
        return _regime_hold(
            "Regime=no-trade: 4h trend evaluators conflict "
            f"({', '.join(f'{name}={bias}' for name, bias in four_hour.items())}).",
            "No position is opened while the higher-timeframe trend is ambiguous.",
        )
    direction = next(iter(four_hour_directions))

    one_hour, invalid_one_hour = _required_evaluator_biases(
        technical_data, "1h", trend_evaluators
    )
    if invalid_one_hour:
        return _regime_hold(
            "Regime=no-trade: 1h trend confirmation is missing or neutral "
            f"({','.join(invalid_one_hour)}).",
            "The 1h trend must confirm the established 4h regime.",
        )
    misaligned_one_hour = [
        name for name, bias in one_hour.items() if bias != direction
    ]
    if misaligned_one_hour:
        return _regime_hold(
            "Regime=no-trade: 1h does not confirm the 4h "
            f"{direction.lower()} trend ({','.join(misaligned_one_hour)}).",
            "The 1h and 4h trend groups must agree before considering an entry.",
        )

    fifteen_minutes, invalid_fifteen_minutes = _required_evaluator_biases(
        technical_data, "15m", timing_evaluators
    )
    if invalid_fifteen_minutes:
        return _regime_hold(
            "Regime=no-trade: 15m entry timing is missing or neutral "
            f"({','.join(invalid_fifteen_minutes)}).",
            "MACD, RSI and Bollinger Bands must provide a directional pullback timing.",
        )
    misaligned_timing = [
        name for name, bias in fifteen_minutes.items() if bias != direction
    ]
    if misaligned_timing:
        return _regime_hold(
            "Regime=no-trade: the 15m pullback timing is not aligned with the "
            f"{direction.lower()} trend ({','.join(misaligned_timing)}).",
            "No entry is made until MACD, RSI and Bollinger Bands all realign with the higher trend.",
        )

    action = "BUY" if direction == "BULLISH" else "SELL"
    return LLMTradingDecision(
        action=action,
        confidence=0.82,
        signal_strength=0.42,
        stop_loss_pct=2.0,
        take_profit_pct=4.0,
        horizon_minutes=240,
        rationale=(
            f"Regime=trend-pullback-{direction.lower()}: 4h and 1h "
            "EMA divergence, double moving average and ADX agree; 15m MACD, RSI and "
            "Bollinger Bands provide aligned entry timing."
        ),
        invalidation=(
            "Close or avoid a new entry when any 4h/1h trend evaluator or 15m timing evaluator "
            "loses alignment with the established regime."
        ),
    )


def _market_regime_metadata(
    technical_data: dict[str, list[dict]], time_frame: str
) -> dict | None:
    for evaluation in technical_data.get(time_frame, []):
        if _evaluator_short_name(evaluation) == "MarketRegimeEvaluator":
            metadata = evaluation.get("metadata")
            if isinstance(metadata, dict) and metadata.get("schema_version") == 1:
                return metadata
    return None


def regime_adaptive_v2_decision(
    technical_data: dict[str, list[dict]],
    required_time_frames: typing.Iterable[typing.Any],
) -> "LLMTradingDecision":
    """Use explicit regime measurements and a lower-timeframe pullback trigger."""

    configured_time_frames = {
        str(getattr(time_frame, "value", time_frame))
        for time_frame in required_time_frames
    }
    missing_time_frames = {"15m", "1h", "4h"} - configured_time_frames
    if missing_time_frames:
        return _regime_hold(
            "Regime V2 requires 15m, 1h and 4h; missing configuration="
            f"{','.join(sorted(missing_time_frames))}.",
            "All V2 timeframes must be configured before a trade is considered.",
        )

    snapshots = {
        time_frame: _market_regime_metadata(technical_data, time_frame)
        for time_frame in ("15m", "1h", "4h")
    }
    missing_snapshots = [
        time_frame for time_frame, snapshot in snapshots.items()
        if snapshot is None
    ]
    if missing_snapshots:
        return _regime_hold(
            "Regime V2 has no valid MarketRegimeEvaluator metadata on "
            f"{','.join(missing_snapshots)}.",
            "No trade is allowed without the quantitative regime snapshot.",
        )

    four_hour = typing.cast(dict, snapshots["4h"])
    one_hour = typing.cast(dict, snapshots["1h"])
    fifteen_minutes = typing.cast(dict, snapshots["15m"])
    if four_hour.get("regime") != "trend" or one_hour.get("regime") != "trend":
        return _regime_hold(
            "Regime V2=no-trade: higher timeframes are not both trending "
            f"(4h={four_hour.get('regime')}, 1h={one_hour.get('regime')}).",
            "Both 4h and 1h must meet the quantitative ADX and EMA-spread trend rules.",
        )

    direction = four_hour.get("direction")
    if direction not in {"BULLISH", "BEARISH"} or one_hour.get("direction") != direction:
        return _regime_hold(
            "Regime V2=no-trade: 4h and 1h quantitative trend directions conflict.",
            "The 4h and 1h fast/slow EMA directions must agree.",
        )

    if one_hour.get("high_volatility") or fifteen_minutes.get("high_volatility"):
        return _regime_hold(
            "Regime V2=no-trade: 1h or 15m Bollinger bandwidth is in the configured high-volatility tail.",
            "Entry resumes only when short-term volatility leaves the high-volatility percentile.",
        )

    timing_evaluators = ("MACDMomentumEvaluator", "RSIMomentumEvaluator")
    timing_biases, invalid_timing = _required_evaluator_biases(
        technical_data, "15m", timing_evaluators
    )
    if invalid_timing:
        return _regime_hold(
            "Regime V2=no-trade: 15m timing is missing or neutral "
            f"({','.join(invalid_timing)}).",
            "Both MACD and RSI must provide a directional timing signal.",
        )
    misaligned_timing = [
        name for name, bias in timing_biases.items() if bias != direction
    ]
    if misaligned_timing:
        return _regime_hold(
            "Regime V2=no-trade: 15m momentum does not confirm the higher-timeframe trend "
            f"({','.join(misaligned_timing)}).",
            "MACD and RSI must realign with the 4h/1h trend before entry.",
        )

    try:
        bb_position = float(fifteen_minutes["bb_position"])
        four_hour_adx = float(four_hour["adx"])
        one_hour_adx = float(one_hour["adx"])
    except (KeyError, TypeError, ValueError):
        return _regime_hold(
            "Regime V2 received incomplete numeric regime metadata.",
            "ADX and Bollinger position must be valid finite numbers.",
        )

    pullback_min, pullback_max = (
        (0.10, 0.55) if direction == "BULLISH" else (0.45, 0.90)
    )
    if not pullback_min <= bb_position <= pullback_max:
        return _regime_hold(
            "Regime V2=no-trade: 15m Bollinger position "
            f"{bb_position:.2f} is outside the {direction.lower()} pullback zone "
            f"[{pullback_min:.2f}, {pullback_max:.2f}].",
            "Wait for a controlled pullback away from both the trend extreme and a band breakdown.",
        )

    trend_quality = min(
        1.0,
        max(0.0, min(four_hour_adx, one_hour_adx) - 25.0) / 25.0,
    )
    action = "BUY" if direction == "BULLISH" else "SELL"
    return LLMTradingDecision(
        action=action,
        confidence=0.76 + 0.14 * trend_quality,
        signal_strength=0.36 + 0.12 * trend_quality,
        stop_loss_pct=2.0,
        take_profit_pct=4.0,
        horizon_minutes=240,
        rationale=(
            f"Regime V2=trend-pullback-{direction.lower()}: ADX 4h={four_hour_adx:.2f}, "
            f"ADX 1h={one_hour_adx:.2f}, 15m Bollinger position={bb_position:.2f}; "
            "MACD and RSI confirm the measured higher-timeframe trend."
        ),
        invalidation=(
            "The setup is invalid when 4h/1h leaves the measured trend regime, their EMA directions "
            "diverge, volatility enters its high tail, or 15m momentum loses alignment."
        ),
    )


def regime_adaptive_v3_decision(
    technical_data: dict[str, list[dict]],
    required_time_frames: typing.Iterable[typing.Any],
) -> "LLMTradingDecision":
    """Apply a higher-quality 4h trend gate to the measured V2 setup."""

    decision = regime_adaptive_v2_decision(technical_data, required_time_frames)
    if decision.action == "HOLD":
        return decision

    four_hour = _market_regime_metadata(technical_data, "4h")
    try:
        four_hour_adx = float(typing.cast(dict, four_hour)["adx"])
    except (KeyError, TypeError, ValueError):
        return _regime_hold(
            "Regime V3 received incomplete 4h trend-quality metadata.",
            "A finite 4h ADX measurement is required before entry.",
        )
    if not math.isfinite(four_hour_adx) or four_hour_adx < 35.0:
        return _regime_hold(
            f"Regime V3=no-trade: 4h ADX {four_hour_adx:.2f} is below the 35.00 quality gate.",
            "Wait until the measured 4h trend is established rather than marginal.",
        )

    return decision.model_copy(
        update={
            "rationale": decision.rationale.replace(
                "Regime V2=", "Regime V3=", 1
            ) + " The 4h ADX quality gate is satisfied."
        }
    )


class LLMTradingDecision(pydantic.BaseModel):
    """Strict output expected from the single-pass trading LLM."""

    model_config = pydantic.ConfigDict(extra="forbid")

    action: typing.Literal["BUY", "SELL", "HOLD"]
    confidence: float = pydantic.Field(ge=0.0, le=1.0)
    signal_strength: float = pydantic.Field(ge=0.0, le=1.0)
    stop_loss_pct: float | None = pydantic.Field(default=None, ge=0.0, le=100.0)
    take_profit_pct: float | None = pydantic.Field(default=None, ge=0.0, le=100.0)
    horizon_minutes: int = pydantic.Field(default=240, ge=1, le=10080)
    rationale: str = pydantic.Field(min_length=1, max_length=1200)
    invalidation: str = pydantic.Field(min_length=1, max_length=600)

    @pydantic.field_validator("action", mode="before")
    @classmethod
    def normalize_action(cls, value):
        return str(value).strip().upper()

    @pydantic.model_validator(mode="after")
    def require_trade_levels(self):
        if self.action != "HOLD" and (
            self.stop_loss_pct is None
            or self.take_profit_pct is None
            or self.stop_loss_pct <= 0
            or self.take_profit_pct <= 0
        ):
            raise ValueError(
                "BUY and SELL decisions require positive stop_loss_pct and take_profit_pct"
            )
        return self


@dataclasses.dataclass(frozen=True)
class RiskGuardSettings:
    min_confidence: float = 0.70
    min_signal_strength: float = 0.30
    max_signal_strength: float = 0.55
    max_stop_loss_pct: float = 2.0
    min_reward_risk_ratio: float = 1.5
    max_horizon_minutes: int = 1440
    allow_sell_signals: bool = False

    def __post_init__(self):
        if not 0 <= self.min_confidence <= 1:
            raise ValueError("min_confidence must be between 0 and 1")
        if not 0 <= self.min_signal_strength <= self.max_signal_strength <= 1:
            raise ValueError(
                "signal strength limits must satisfy 0 <= min <= max <= 1"
            )
        if self.max_stop_loss_pct <= 0 or self.min_reward_risk_ratio <= 0:
            raise ValueError("risk limits must be positive")
        if self.max_horizon_minutes <= 0:
            raise ValueError("max_horizon_minutes must be positive")


@dataclasses.dataclass(frozen=True)
class GuardedDecision:
    approved: bool
    eval_note: float
    reason: str
    decision: LLMTradingDecision


class DeterministicRiskGuard:
    """Turn an LLM proposal into an OctoBot signal without delegating limits."""

    def __init__(self, settings: RiskGuardSettings):
        self.settings = settings

    def evaluate(self, decision: LLMTradingDecision) -> GuardedDecision:
        if decision.action == "HOLD":
            return GuardedDecision(False, 0.0, "model_requested_hold", decision)
        if decision.action == "SELL" and not self.settings.allow_sell_signals:
            return GuardedDecision(False, 0.0, "sell_signals_disabled_in_long_only_mode", decision)
        if decision.confidence < self.settings.min_confidence:
            return GuardedDecision(False, 0.0, "confidence_below_threshold", decision)
        if decision.signal_strength < self.settings.min_signal_strength:
            return GuardedDecision(False, 0.0, "signal_strength_below_threshold", decision)
        if decision.horizon_minutes > self.settings.max_horizon_minutes:
            return GuardedDecision(False, 0.0, "horizon_above_limit", decision)
        if decision.stop_loss_pct is None or decision.take_profit_pct is None:
            return GuardedDecision(False, 0.0, "missing_protective_levels", decision)
        if decision.stop_loss_pct > self.settings.max_stop_loss_pct:
            return GuardedDecision(False, 0.0, "stop_loss_above_limit", decision)
        reward_risk = decision.take_profit_pct / decision.stop_loss_pct
        if reward_risk < self.settings.min_reward_risk_ratio:
            return GuardedDecision(False, 0.0, "reward_risk_below_threshold", decision)

        strength = min(decision.signal_strength, self.settings.max_signal_strength)
        # OctoBot's DailyTradingMode convention is negative=long and positive=short.
        eval_note = -strength if decision.action == "BUY" else strength
        return GuardedDecision(True, eval_note, "approved", decision)


class SQLiteDecisionJournal:
    """Append-only local audit trail for every LLM decision and rejection."""

    SCHEMA_VERSION = 2

    def __init__(self, database_path: str):
        self.database_path = pathlib.Path(database_path)

    def initialize(self) -> None:
        self.database_path.parent.mkdir(parents=True, exist_ok=True)
        with sqlite3.connect(self.database_path, timeout=5) as connection:
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS ai_decisions (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    created_at TEXT NOT NULL,
                    schema_version INTEGER NOT NULL,
                    exchange_name TEXT,
                    cryptocurrency TEXT,
                    symbol TEXT,
                    triggered_at INTEGER,
                    model TEXT,
                    prompt_version TEXT NOT NULL,
                    input_json TEXT NOT NULL,
                    output_json TEXT NOT NULL,
                    action TEXT,
                    confidence REAL,
                    signal_strength REAL,
                    eval_note REAL NOT NULL,
                    approved INTEGER NOT NULL,
                    guard_reason TEXT NOT NULL,
                    rationale TEXT,
                    invalidation TEXT,
                    horizon_minutes INTEGER
                )
                """
            )
            columns = {
                row[1] for row in connection.execute("PRAGMA table_info(ai_decisions)")
            }
            if "triggered_at" not in columns:
                connection.execute("ALTER TABLE ai_decisions ADD COLUMN triggered_at INTEGER")
            connection.execute(
                "CREATE INDEX IF NOT EXISTS idx_ai_decisions_created_at "
                "ON ai_decisions(created_at)"
            )
            connection.execute(
                "CREATE INDEX IF NOT EXISTS idx_ai_decisions_replay "
                "ON ai_decisions(exchange_name, symbol, triggered_at)"
            )

    def record(
        self,
        *,
        context: dict,
        model: str | None,
        prompt_version: str,
        input_data: dict,
        output_data: dict,
        guarded: GuardedDecision,
    ) -> None:
        self.initialize()
        decision = guarded.decision
        with sqlite3.connect(self.database_path, timeout=5) as connection:
            connection.execute(
                """
                INSERT INTO ai_decisions (
                    created_at, schema_version, exchange_name, cryptocurrency,
                    symbol, triggered_at, model, prompt_version, input_json, output_json,
                    action, confidence, signal_strength, eval_note, approved,
                    guard_reason, rationale, invalidation, horizon_minutes
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    datetime.datetime.now(datetime.timezone.utc).isoformat(),
                    self.SCHEMA_VERSION,
                    context.get("exchange_name"),
                    context.get("cryptocurrency"),
                    context.get("symbol"),
                    context.get("triggered_at"),
                    model,
                    prompt_version,
                    json.dumps(input_data, ensure_ascii=False, default=str),
                    json.dumps(output_data, ensure_ascii=False, default=str),
                    decision.action,
                    decision.confidence,
                    decision.signal_strength,
                    guarded.eval_note,
                    int(guarded.approved),
                    guarded.reason,
                    decision.rationale,
                    decision.invalidation,
                    decision.horizon_minutes,
                ),
            )

    def latest_recorded_at(self, *, exchange_name: str, symbol: str) -> datetime.datetime | None:
        """Return the latest journal timestamp for a market, if it is available."""

        self.initialize()
        with sqlite3.connect(self.database_path, timeout=5) as connection:
            row = connection.execute(
                """
                SELECT created_at
                FROM ai_decisions
                WHERE exchange_name = ? AND symbol = ?
                ORDER BY id DESC
                LIMIT 1
                """,
                (exchange_name, symbol),
            ).fetchone()
        return datetime.datetime.fromisoformat(row[0]) if row else None

    def replay_decision(
        self, *, exchange_name: str, symbol: str, triggered_at: int
    ) -> GuardedDecision | None:
        """Load the recorded guarded outcome for an exact candle-close timestamp."""

        self.initialize()
        with sqlite3.connect(self.database_path, timeout=5) as connection:
            connection.row_factory = sqlite3.Row
            row = connection.execute(
                """
                SELECT output_json, action, confidence, signal_strength, eval_note,
                       approved, guard_reason, rationale, invalidation, horizon_minutes
                FROM ai_decisions
                WHERE exchange_name = ? AND symbol = ? AND triggered_at = ?
                ORDER BY id DESC
                LIMIT 1
                """,
                (exchange_name, symbol, triggered_at),
            ).fetchone()
        if row is None:
            return None
        try:
            decision = LLMTradingDecision.model_validate(json.loads(row["output_json"]))
        except (json.JSONDecodeError, pydantic.ValidationError, TypeError):
            decision = LLMTradingDecision(
                action="HOLD",
                confidence=0,
                signal_strength=0,
                horizon_minutes=1,
                rationale=row["rationale"] or "Recorded LLM decision cannot be replayed.",
                invalidation=row["invalidation"] or "No trade is allowed without a valid record.",
            )
        return GuardedDecision(
            bool(row["approved"]),
            float(row["eval_note"]),
            row["guard_reason"],
            decision,
        )
