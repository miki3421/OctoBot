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
import hashlib
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

    SCHEMA_VERSION = 4

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
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS ai_order_events (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    created_at TEXT NOT NULL,
                    schema_version INTEGER NOT NULL,
                    event_key TEXT NOT NULL UNIQUE,
                    decision_id INTEGER,
                    exchange_name TEXT NOT NULL,
                    symbol TEXT NOT NULL,
                    order_id TEXT NOT NULL,
                    update_type TEXT,
                    status TEXT,
                    side TEXT,
                    order_type TEXT,
                    quantity REAL,
                    filled_quantity REAL,
                    price REAL,
                    average_price REAL,
                    fee REAL,
                    fee_currency TEXT,
                    reduce_only INTEGER NOT NULL,
                    is_from_bot INTEGER NOT NULL,
                    raw_json TEXT NOT NULL,
                    FOREIGN KEY(decision_id) REFERENCES ai_decisions(id)
                )
                """
            )
            connection.execute(
                "CREATE INDEX IF NOT EXISTS idx_ai_order_events_order "
                "ON ai_order_events(exchange_name, symbol, order_id)"
            )
            connection.execute(
                "CREATE INDEX IF NOT EXISTS idx_ai_order_events_decision "
                "ON ai_order_events(decision_id, id)"
            )
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS ai_position_outcomes (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    created_at TEXT NOT NULL,
                    schema_version INTEGER NOT NULL,
                    decision_id INTEGER NOT NULL,
                    entry_event_id INTEGER NOT NULL,
                    exit_event_id INTEGER NOT NULL UNIQUE,
                    exchange_name TEXT NOT NULL,
                    symbol TEXT NOT NULL,
                    side TEXT NOT NULL,
                    entry_order_id TEXT NOT NULL,
                    exit_order_id TEXT NOT NULL,
                    entry_at TEXT NOT NULL,
                    exit_at TEXT NOT NULL,
                    quantity REAL NOT NULL,
                    entry_price REAL NOT NULL,
                    exit_price REAL NOT NULL,
                    gross_price_pnl REAL NOT NULL,
                    known_fees REAL NOT NULL,
                    net_pnl_excluding_funding REAL NOT NULL,
                    return_pct_excluding_funding REAL NOT NULL,
                    exit_reason TEXT NOT NULL,
                    FOREIGN KEY(decision_id) REFERENCES ai_decisions(id),
                    FOREIGN KEY(entry_event_id) REFERENCES ai_order_events(id),
                    FOREIGN KEY(exit_event_id) REFERENCES ai_order_events(id)
                )
                """
            )
            connection.execute(
                "CREATE INDEX IF NOT EXISTS idx_ai_position_outcomes_decision "
                "ON ai_position_outcomes(decision_id, exit_at)"
            )
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS ai_protected_exit_events (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    created_at TEXT NOT NULL,
                    schema_version INTEGER NOT NULL,
                    event_key TEXT NOT NULL UNIQUE,
                    exchange_name TEXT NOT NULL,
                    symbol TEXT NOT NULL,
                    entry_order_id TEXT NOT NULL,
                    event_type TEXT NOT NULL,
                    entry_price REAL NOT NULL,
                    observed_price REAL,
                    stop_price REAL,
                    payload_json TEXT NOT NULL
                )
                """
            )
            connection.execute(
                "CREATE INDEX IF NOT EXISTS idx_ai_protected_exit_entry "
                "ON ai_protected_exit_events("
                "exchange_name, symbol, entry_order_id, id)"
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
    ) -> int:
        self.initialize()
        decision = guarded.decision
        with sqlite3.connect(self.database_path, timeout=5) as connection:
            cursor = connection.execute(
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
            return int(cursor.lastrowid)

    def record_order_event(
        self,
        *,
        exchange_name: str,
        symbol: str,
        order: dict,
        update_type: typing.Any = None,
        is_from_bot: bool,
        occurred_at: typing.Optional[datetime.datetime] = None,
    ) -> typing.Optional[int]:
        """Append one simulated order state and derive a closed outcome."""

        self.initialize()
        occurred_at = occurred_at or datetime.datetime.now(
            datetime.timezone.utc
        )
        if occurred_at.tzinfo is None:
            occurred_at = occurred_at.replace(tzinfo=datetime.timezone.utc)
        normalized = self._normalize_order(order)
        order_id = normalized["order_id"]
        if not exchange_name or not symbol or not order_id:
            raise ValueError("exchange, symbol and order id are required")
        normalized_update_type = self._enum_value(update_type)
        event_payload = {
            "exchange_name": exchange_name,
            "symbol": symbol,
            "update_type": normalized_update_type,
            "is_from_bot": bool(is_from_bot),
            **normalized,
        }
        event_key = hashlib.sha256(
            json.dumps(
                event_payload,
                sort_keys=True,
                ensure_ascii=False,
                default=str,
                separators=(",", ":"),
            ).encode("utf-8")
        ).hexdigest()
        with sqlite3.connect(self.database_path, timeout=5) as connection:
            decision_id = self._decision_for_order_event(
                connection,
                exchange_name=exchange_name,
                symbol=symbol,
                normalized=normalized,
                is_from_bot=is_from_bot,
                occurred_at=occurred_at,
            )
            cursor = connection.execute(
                """
                INSERT OR IGNORE INTO ai_order_events (
                    created_at, schema_version, event_key, decision_id,
                    exchange_name, symbol, order_id, update_type, status, side,
                    order_type, quantity, filled_quantity, price, average_price,
                    fee, fee_currency, reduce_only, is_from_bot, raw_json
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    occurred_at.isoformat(),
                    self.SCHEMA_VERSION,
                    event_key,
                    decision_id,
                    exchange_name,
                    symbol,
                    order_id,
                    normalized_update_type,
                    normalized["status"],
                    normalized["side"],
                    normalized["order_type"],
                    normalized["quantity"],
                    normalized["filled_quantity"],
                    normalized["price"],
                    normalized["average_price"],
                    normalized["fee"],
                    normalized["fee_currency"],
                    int(normalized["reduce_only"]),
                    int(bool(is_from_bot)),
                    json.dumps(
                        order, ensure_ascii=False, sort_keys=True, default=str
                    ),
                ),
            )
            if cursor.rowcount == 0:
                row = connection.execute(
                    "SELECT id FROM ai_order_events WHERE event_key = ?",
                    (event_key,),
                ).fetchone()
                return int(row[0]) if row else None
            event_id = int(cursor.lastrowid)
            if (
                normalized["status"] == "filled"
                and normalized["reduce_only"]
                and decision_id is not None
            ):
                self._record_position_outcome(
                    connection,
                    exit_event_id=event_id,
                    decision_id=decision_id,
                    exit_event=normalized,
                    exchange_name=exchange_name,
                    symbol=symbol,
                    occurred_at=occurred_at,
                )
            return event_id

    def reconcile_open_order_events(
        self,
        *,
        exchange_name: str,
        symbol: str,
        active_order_ids: typing.Iterable[str],
        occurred_at: typing.Optional[datetime.datetime] = None,
    ) -> int:
        """Append an interrupted state for journal-open orders absent at startup."""

        self.initialize()
        active_ids = {str(order_id) for order_id in active_order_ids}
        with sqlite3.connect(self.database_path, timeout=5) as connection:
            connection.row_factory = sqlite3.Row
            stale_events = connection.execute(
                """
                SELECT event.*
                FROM ai_order_events AS event
                JOIN (
                    SELECT exchange_name, symbol, order_id, MAX(id) AS latest_id
                    FROM ai_order_events
                    WHERE exchange_name = ? AND symbol = ? AND is_from_bot = 1
                    GROUP BY exchange_name, symbol, order_id
                ) AS latest ON latest.latest_id = event.id
                WHERE LOWER(COALESCE(event.status, '')) IN (
                    'open', 'pending', 'pending_creation'
                )
                ORDER BY event.id
                """,
                (exchange_name, symbol),
            ).fetchall()

        reconciled = 0
        for event in stale_events:
            if str(event["order_id"]) in active_ids:
                continue
            reconciliation_order = {
                "id": event["order_id"],
                "status": "interrupted",
                "side": event["side"],
                "type": event["order_type"],
                "amount": event["quantity"],
                "filled": event["filled_quantity"],
                "price": event["price"],
                "average": event["average_price"],
                "fee": {
                    "cost": event["fee"],
                    "currency": event["fee_currency"],
                },
                "reduceOnly": bool(event["reduce_only"]),
                "reconciliation": {
                    "reason": "missing_from_paper_runtime_at_startup",
                    "previous_event_id": int(event["id"]),
                },
            }
            before_event_id = int(event["id"])
            reconciled_event_id = self.record_order_event(
                exchange_name=exchange_name,
                symbol=symbol,
                order=reconciliation_order,
                update_type="startup_reconciliation",
                is_from_bot=True,
                occurred_at=occurred_at,
            )
            if reconciled_event_id and reconciled_event_id != before_event_id:
                reconciled += 1
        return reconciled

    def get_open_order_restore_candidates(
        self,
        *,
        exchange_name: str,
        symbol: str,
    ) -> list[dict]:
        """Return the latest journal-open paper orders for guarded startup restore.

        The journal remains append-only: callers receive a parsed copy of the
        original order payload and must independently validate it before
        recreating anything in the simulator.
        """

        self.initialize()
        with sqlite3.connect(self.database_path, timeout=5) as connection:
            connection.row_factory = sqlite3.Row
            rows = connection.execute(
                """
                SELECT event.*
                FROM ai_order_events AS event
                JOIN (
                    SELECT exchange_name, symbol, order_id, MAX(id) AS latest_id
                    FROM ai_order_events
                    WHERE exchange_name = ? AND symbol = ? AND is_from_bot = 1
                    GROUP BY exchange_name, symbol, order_id
                ) AS latest ON latest.latest_id = event.id
                WHERE LOWER(COALESCE(event.status, '')) IN (
                    'open', 'pending', 'pending_creation'
                )
                ORDER BY event.id
                """,
                (exchange_name, symbol),
            ).fetchall()

        candidates = []
        for row in rows:
            try:
                raw_order = json.loads(row["raw_json"])
            except (json.JSONDecodeError, TypeError):
                continue
            if not isinstance(raw_order, dict):
                continue
            candidates.append(
                {
                    "event_id": int(row["id"]),
                    "decision_id": (
                        int(row["decision_id"])
                        if row["decision_id"] is not None
                        else None
                    ),
                    "order_id": str(row["order_id"]),
                    "status": str(row["status"] or "").lower(),
                    "side": str(row["side"] or "").lower(),
                    "order_type": str(row["order_type"] or "").lower(),
                    "quantity": self._float_or_none(row["quantity"]),
                    "filled_quantity": self._float_or_none(
                        row["filled_quantity"]
                    ),
                    "price": self._float_or_none(row["price"]),
                    "reduce_only": bool(row["reduce_only"]),
                    "raw_order": raw_order,
                }
            )
        return candidates

    def get_open_position_entry(
        self,
        *,
        exchange_name: str,
        symbol: str,
    ) -> typing.Optional[dict]:
        """Return the latest journal entry that has no recorded position exit."""

        self.initialize()
        with sqlite3.connect(self.database_path, timeout=5) as connection:
            connection.row_factory = sqlite3.Row
            row = connection.execute(
                """
                SELECT event.id, event.created_at, event.decision_id,
                       event.order_id, event.side, event.filled_quantity,
                       event.quantity, event.price, event.average_price,
                       event.raw_json
                FROM ai_order_events AS event
                WHERE event.exchange_name = ? AND event.symbol = ?
                      AND event.status = 'filled'
                      AND event.reduce_only = 0
                      AND NOT EXISTS (
                          SELECT 1 FROM ai_position_outcomes AS outcome
                          WHERE outcome.entry_event_id = event.id
                      )
                ORDER BY event.id DESC
                LIMIT 1
                """,
                (exchange_name, symbol),
            ).fetchone()
        if row is None:
            return None
        try:
            raw_order = json.loads(row["raw_json"])
        except (json.JSONDecodeError, TypeError):
            raw_order = None
        return {
            "event_id": int(row["id"]),
            "created_at": datetime.datetime.fromisoformat(row["created_at"]),
            "decision_id": (
                int(row["decision_id"])
                if row["decision_id"] is not None
                else None
            ),
            "entry_order_id": str(row["order_id"]),
            "side": str(row["side"] or "").lower(),
            "quantity": self._float_or_none(
                row["filled_quantity"] or row["quantity"]
            ),
            "entry_price": self._float_or_none(
                row["average_price"] or row["price"]
            ),
            "raw_order": raw_order if isinstance(raw_order, dict) else None,
        }

    def record_protected_exit_event(
        self,
        *,
        exchange_name: str,
        symbol: str,
        entry_order_id: str,
        event_type: str,
        entry_price: typing.Any,
        observed_price: typing.Any = None,
        stop_price: typing.Any = None,
        payload: typing.Optional[dict] = None,
        occurred_at: typing.Optional[datetime.datetime] = None,
    ) -> typing.Optional[int]:
        """Append an idempotent protected-profit lifecycle event."""

        self.initialize()
        occurred_at = occurred_at or datetime.datetime.now(
            datetime.timezone.utc
        )
        if occurred_at.tzinfo is None:
            occurred_at = occurred_at.replace(tzinfo=datetime.timezone.utc)
        entry_price_value = self._float_or_none(entry_price)
        observed_price_value = self._float_or_none(observed_price)
        stop_price_value = self._float_or_none(stop_price)
        if (
            not exchange_name
            or not symbol
            or not entry_order_id
            or not event_type
            or entry_price_value is None
            or entry_price_value <= 0
        ):
            raise ValueError(
                "protected exit event requires exchange, symbol, entry, "
                "event type and positive entry price"
            )
        normalized_payload = payload or {}
        event_identity = {
            "exchange_name": exchange_name,
            "symbol": symbol,
            "entry_order_id": str(entry_order_id),
            "event_type": str(event_type),
        }
        event_key = hashlib.sha256(
            json.dumps(
                event_identity,
                sort_keys=True,
                ensure_ascii=False,
                default=str,
                separators=(",", ":"),
            ).encode("utf-8")
        ).hexdigest()
        with sqlite3.connect(self.database_path, timeout=5) as connection:
            cursor = connection.execute(
                """
                INSERT OR IGNORE INTO ai_protected_exit_events (
                    created_at, schema_version, event_key, exchange_name,
                    symbol, entry_order_id, event_type, entry_price,
                    observed_price, stop_price, payload_json
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    occurred_at.isoformat(),
                    self.SCHEMA_VERSION,
                    event_key,
                    exchange_name,
                    symbol,
                    str(entry_order_id),
                    str(event_type),
                    entry_price_value,
                    observed_price_value,
                    stop_price_value,
                    json.dumps(
                        normalized_payload,
                        ensure_ascii=False,
                        sort_keys=True,
                        default=str,
                    ),
                ),
            )
            if cursor.rowcount:
                return int(cursor.lastrowid)
            row = connection.execute(
                """
                SELECT id FROM ai_protected_exit_events
                WHERE event_key = ?
                """,
                (event_key,),
            ).fetchone()
            return int(row[0]) if row else None

    def get_protected_exit_event_types(
        self,
        *,
        exchange_name: str,
        symbol: str,
        entry_order_id: str,
    ) -> set[str]:
        """Return recorded lifecycle event types for an open entry."""

        self.initialize()
        with sqlite3.connect(self.database_path, timeout=5) as connection:
            rows = connection.execute(
                """
                SELECT event_type
                FROM ai_protected_exit_events
                WHERE exchange_name = ? AND symbol = ?
                      AND entry_order_id = ?
                """,
                (exchange_name, symbol, str(entry_order_id)),
            ).fetchall()
        return {str(row[0]) for row in rows}

    @classmethod
    def _normalize_order(cls, order):
        fee_value = order.get("fee")
        if isinstance(fee_value, dict):
            fee = cls._float_or_none(
                fee_value.get("cost", fee_value.get("amount"))
            )
            fee_currency = fee_value.get(
                "currency", fee_value.get("code")
            )
        else:
            fee = cls._float_or_none(fee_value)
            fee_currency = order.get("fee_currency")
        return {
            "order_id": str(
                order.get("id")
                or order.get("order_id")
                or order.get("exchange_order_id")
                or ""
            ),
            "status": str(
                cls._enum_value(order.get("status")) or ""
            ).lower(),
            "side": str(
                cls._enum_value(order.get("side")) or ""
            ).lower(),
            "order_type": str(
                cls._enum_value(
                    order.get("type", order.get("order_type"))
                )
                or ""
            ).lower(),
            "quantity": cls._float_or_none(
                order.get("amount", order.get("quantity"))
            ),
            "filled_quantity": cls._float_or_none(
                order.get("filled", order.get("filled_quantity"))
            ),
            "price": cls._float_or_none(order.get("price")),
            "average_price": cls._float_or_none(
                order.get("average", order.get("average_price"))
            ),
            "fee": fee,
            "fee_currency": (
                str(fee_currency) if fee_currency is not None else None
            ),
            "reduce_only": bool(
                order.get("reduceOnly", order.get("reduce_only", False))
            ),
        }

    @staticmethod
    def _float_or_none(value):
        if value is None:
            return None
        try:
            return float(value)
        except (TypeError, ValueError):
            return None

    @staticmethod
    def _enum_value(value):
        return getattr(value, "value", value)

    def _decision_for_order_event(
        self,
        connection,
        *,
        exchange_name,
        symbol,
        normalized,
        is_from_bot,
        occurred_at,
    ):
        if not is_from_bot:
            return None
        existing = connection.execute(
            """
            SELECT decision_id
            FROM ai_order_events
            WHERE exchange_name = ? AND symbol = ? AND order_id = ?
                  AND decision_id IS NOT NULL
            ORDER BY id DESC
            LIMIT 1
            """,
            (exchange_name, symbol, normalized["order_id"]),
        ).fetchone()
        if existing:
            return int(existing[0])
        if normalized["reduce_only"]:
            entry = connection.execute(
                """
                SELECT event.decision_id
                FROM ai_order_events AS event
                WHERE event.exchange_name = ? AND event.symbol = ?
                      AND event.status = 'filled'
                      AND event.reduce_only = 0
                      AND event.decision_id IS NOT NULL
                      AND NOT EXISTS (
                          SELECT 1 FROM ai_position_outcomes AS outcome
                          WHERE outcome.entry_event_id = event.id
                      )
                ORDER BY event.id DESC
                LIMIT 1
                """,
                (exchange_name, symbol),
            ).fetchone()
            return int(entry[0]) if entry else None
        row = connection.execute(
            """
            SELECT id, created_at, action, horizon_minutes
            FROM ai_decisions
            WHERE exchange_name = ? AND symbol = ? AND approved = 1
            ORDER BY id DESC
            LIMIT 1
            """,
            (exchange_name, symbol),
        ).fetchone()
        if row is None:
            return None
        expected_side = "buy" if row[2] == "BUY" else "sell"
        if normalized["side"] and normalized["side"] != expected_side:
            return None
        try:
            decision_at = datetime.datetime.fromisoformat(row[1])
            if decision_at.tzinfo is None:
                decision_at = decision_at.replace(
                    tzinfo=datetime.timezone.utc
                )
            age_seconds = (occurred_at - decision_at).total_seconds()
        except (TypeError, ValueError):
            return None
        max_age_seconds = max(900, int(row[3] or 0) * 60)
        if not 0 <= age_seconds <= max_age_seconds:
            return None
        return int(row[0])

    def _record_position_outcome(
        self,
        connection,
        *,
        exit_event_id,
        decision_id,
        exit_event,
        exchange_name,
        symbol,
        occurred_at,
    ):
        entry = connection.execute(
            """
            SELECT id, created_at, order_id, side, filled_quantity, quantity,
                   price, average_price, fee
            FROM ai_order_events
            WHERE decision_id = ? AND exchange_name = ? AND symbol = ?
                  AND status = 'filled' AND reduce_only = 0
                  AND NOT EXISTS (
                      SELECT 1 FROM ai_position_outcomes AS outcome
                      WHERE outcome.entry_event_id = ai_order_events.id
                  )
            ORDER BY id DESC
            LIMIT 1
            """,
            (decision_id, exchange_name, symbol),
        ).fetchone()
        if entry is None:
            return
        entry_side = str(entry[3] or "").lower()
        if entry_side not in {"buy", "sell"}:
            return
        if exit_event["side"] == entry_side:
            return
        entry_quantity = entry[4] or entry[5]
        exit_quantity = (
            exit_event["filled_quantity"] or exit_event["quantity"]
        )
        entry_price = entry[7] or entry[6]
        exit_price = exit_event["average_price"] or exit_event["price"]
        if not all(
            value is not None and value > 0
            for value in (
                entry_quantity,
                exit_quantity,
                entry_price,
                exit_price,
            )
        ):
            return
        quantity = min(float(entry_quantity), float(exit_quantity))
        direction = 1.0 if entry_side == "buy" else -1.0
        gross_pnl = (
            (float(exit_price) - float(entry_price)) * quantity * direction
        )
        known_fees = float(entry[8] or 0) + float(exit_event["fee"] or 0)
        net_pnl = gross_pnl - known_fees
        entry_notional = float(entry_price) * quantity
        order_type = exit_event["order_type"]
        exit_reason = (
            "stop_loss"
            if "stop" in order_type
            else (
                "take_profit"
                if "limit" in order_type
                else "market_or_other"
            )
        )
        connection.execute(
            """
            INSERT OR IGNORE INTO ai_position_outcomes (
                created_at, schema_version, decision_id, entry_event_id,
                exit_event_id, exchange_name, symbol, side, entry_order_id,
                exit_order_id, entry_at, exit_at, quantity, entry_price,
                exit_price, gross_price_pnl, known_fees,
                net_pnl_excluding_funding, return_pct_excluding_funding,
                exit_reason
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                occurred_at.isoformat(),
                self.SCHEMA_VERSION,
                decision_id,
                int(entry[0]),
                exit_event_id,
                exchange_name,
                symbol,
                "long" if entry_side == "buy" else "short",
                str(entry[2]),
                exit_event["order_id"],
                entry[1],
                occurred_at.isoformat(),
                quantity,
                float(entry_price),
                float(exit_price),
                gross_pnl,
                known_fees,
                net_pnl,
                net_pnl / entry_notional,
                exit_reason,
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
