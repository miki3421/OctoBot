"""Causal, research-only percentage signal candidate for the chart.

Unlike :mod:`percentage_engine`, the entry rule in this module never observes
future candles.  Future candles are used only after an entry to evaluate what
would have happened under the same percentage stop/profit-lock protocol.

The frozen V1 rule was selected on older Binance BTC futures data and validated
on a later Binance block.  KuCoin 2026 data was held out until the rule and its
thresholds were frozen.  The evidence remains insufficient for paper trading:
the module cannot authorize orders and is intended only for chart diagnostics.
"""

from __future__ import annotations

import dataclasses
import math
import typing

import numpy

from octobot.ai_strategy_lab import indicators
from octobot.ai_strategy_lab import percentage_engine


@dataclasses.dataclass(frozen=True)
class PercentageSignalRule:
    """Interpretable V1 conjunction, expressed as ratios rather than percent."""

    maximum_atr_pct: float = 0.004702894155636955
    minimum_directional_ema_spread_pct: float = 0.001487543865021874
    minimum_directional_ema_slope_pct: float = 0.0019416850106557305
    round_trip_cost_pct: float = 0.16

    def validate(self) -> None:
        for name in (
            "maximum_atr_pct",
            "minimum_directional_ema_spread_pct",
            "minimum_directional_ema_slope_pct",
            "round_trip_cost_pct",
        ):
            value = getattr(self, name)
            if not math.isfinite(value) or value < 0:
                raise ValueError(f"{name} must be finite and non-negative")
        if self.maximum_atr_pct <= 0:
            raise ValueError("maximum_atr_pct must be positive")


@dataclasses.dataclass(frozen=True)
class PercentageEvidenceGate:
    """Minimum evidence required even to reconsider this research candidate."""

    minimum_test_trades: int = 50
    minimum_profit_factor: float = 1.20
    minimum_win_rate_pct: float = 50.0
    minimum_trades_per_day: float = 0.50

    def validate(self) -> None:
        if self.minimum_test_trades < 1:
            raise ValueError("minimum_test_trades must be positive")
        if self.minimum_profit_factor <= 0:
            raise ValueError("minimum_profit_factor must be positive")
        if not 0 <= self.minimum_win_rate_pct <= 100:
            raise ValueError("minimum_win_rate_pct must be between zero and 100")
        if self.minimum_trades_per_day <= 0:
            raise ValueError("minimum_trades_per_day must be positive")


FROZEN_V1_EVIDENCE = {
    "candidate": "btc_1h_percentage_conjunction_v1",
    "inputs": {
        "binance_btc_1h_sha256": (
            "d0b97512855a131b2b3a863736d7bfaa710e9588db900fdb639cfc8cffbc17c6"
        ),
        "kucoin_btc_1h_sha256": (
            "91059318738b7b4a43bf9f699a2d9da3959caf0f84a36d38aa3befdc2be77e53"
        ),
    },
    "selection": {
        "discovery": {
            "venue": "Binance USD-M",
            "start": "2022-05-01T00:00:00Z",
            "end_exclusive": "2025-06-30T00:00:00Z",
        },
        "validation": {
            "venue": "Binance USD-M",
            "start": "2025-07-01T00:00:00Z",
            "end_exclusive": "2026-01-01T00:00:00Z",
        },
        "test": {
            "venue": "KuCoin Futures",
            "start": "2026-01-02T00:00:00Z",
            "end_inclusive": "2026-07-21T23:00:00Z",
        },
        "embargo_hours": 24,
        "search": (
            "beam search over one-to-three quantile conditions; selected only "
            "with discovery and validation data"
        ),
    },
    "costs": {
        "round_trip_pct": 0.16,
        "funding_included": False,
        "description": "0.06% taker fee + 0.02% slippage per fill, two fills",
    },
    "discovery_metrics": {
        "trades": 82,
        "win_rate_pct": 56.09756097560976,
        "profit_factor": 1.790,
        "compounded_net_return_pct": 32.596,
    },
    "validation_metrics": {
        "trades": 31,
        "win_rate_pct": 61.29032258064516,
        "profit_factor": 2.054,
        "compounded_net_return_pct": 13.554,
    },
    "test_metrics": {
        "trades": 27,
        "win_rate_pct": 51.85185185185185,
        "profit_factor": 1.232,
        "compounded_net_return_pct": 2.630,
        "trades_per_day": 0.135,
    },
    "warning": (
        "The held-out result is positive but too small and too infrequent. "
        "It is evidence for further research, not a validated strategy."
    ),
}


def _as_non_negative_finite(
    values: typing.Iterable[typing.Any], name: str
) -> list[float]:
    converted = [float(value) for value in values]
    if not converted:
        raise ValueError(f"{name} must not be empty")
    if any(not math.isfinite(value) or value < 0 for value in converted):
        raise ValueError(f"{name} must contain finite non-negative values")
    return converted


def _build_feature_arrays(
    opens: list[float],
    highs: list[float],
    lows: list[float],
    closes: list[float],
    volumes: list[float],
) -> dict[str, numpy.ndarray]:
    candle_count = len(closes)
    candles = numpy.column_stack(
        (
            numpy.arange(candle_count, dtype=numpy.float64),
            numpy.asarray(opens, dtype=numpy.float64),
            numpy.asarray(highs, dtype=numpy.float64),
            numpy.asarray(lows, dtype=numpy.float64),
            numpy.asarray(closes, dtype=numpy.float64),
            numpy.asarray(volumes, dtype=numpy.float64),
        )
    )
    return indicators.compute_feature_arrays(candles)


def _matches_rule(
    feature_arrays: dict[str, numpy.ndarray],
    entry_index: int,
    direction: str,
    rule: PercentageSignalRule,
) -> tuple[bool, dict[str, float]]:
    sign = 1.0 if direction == percentage_engine.LONG else -1.0
    atr_pct = float(feature_arrays["atr_pct"][entry_index])
    directional_ema_spread_pct = (
        float(feature_arrays["ema_spread_pct"][entry_index]) * sign
    )
    directional_ema_slope_pct = (
        float(feature_arrays["ema_slope_pct"][entry_index]) * sign
    )
    values = {
        "atr_pct": atr_pct,
        "directional_ema_spread_pct": directional_ema_spread_pct,
        "directional_ema_slope_pct": directional_ema_slope_pct,
    }
    return (
        all(math.isfinite(value) for value in values.values())
        and atr_pct <= rule.maximum_atr_pct
        and directional_ema_spread_pct
        >= rule.minimum_directional_ema_spread_pct
        and directional_ema_slope_pct
        >= rule.minimum_directional_ema_slope_pct
    ), values


def _maximum_drawdown_pct(net_returns: list[float]) -> float:
    equity = 1.0
    peak = 1.0
    maximum_drawdown = 0.0
    for net_return in net_returns:
        equity *= 1 + net_return / 100
        peak = max(peak, equity)
        maximum_drawdown = max(maximum_drawdown, (peak - equity) / peak)
    return maximum_drawdown * 100


def _summarize_trades(
    trades: list[dict],
    *,
    closed_candles: int,
    candidate_signals: int,
) -> dict:
    net_returns = [float(trade["net_return_pct"]) for trade in trades]
    positive = sum(value for value in net_returns if value > 0)
    negative = -sum(value for value in net_returns if value < 0)
    compound_multiplier = math.prod(1 + value / 100 for value in net_returns)
    days = closed_candles / 24
    return {
        "closed_candles": closed_candles,
        "candidate_signals": candidate_signals,
        "non_overlapping_trades": len(trades),
        "long_trades": sum(
            trade["direction"] == percentage_engine.LONG for trade in trades
        ),
        "short_trades": sum(
            trade["direction"] == percentage_engine.SHORT for trade in trades
        ),
        "win_rate_pct": (
            sum(value > 0 for value in net_returns) * 100 / len(net_returns)
            if net_returns
            else 0.0
        ),
        "profit_factor": (
            positive / negative
            if negative
            else (math.inf if positive else 0.0)
        ),
        "compounded_gross_return_pct": (
            math.prod(
                1 + float(trade["gross_return_pct"]) / 100 for trade in trades
            )
            - 1
        )
        * 100,
        "compounded_net_return_pct": (compound_multiplier - 1) * 100,
        "maximum_drawdown_pct": _maximum_drawdown_pct(net_returns),
        "trades_per_day": len(trades) / days if days else 0.0,
    }


def _frozen_evidence_gate(
    evidence: dict,
    gate: PercentageEvidenceGate,
) -> dict:
    test = evidence["test_metrics"]
    checks = {
        "enough_test_trades": test["trades"] >= gate.minimum_test_trades,
        "profit_factor": test["profit_factor"] >= gate.minimum_profit_factor,
        "win_rate": test["win_rate_pct"] >= gate.minimum_win_rate_pct,
        "frequency": test["trades_per_day"] >= gate.minimum_trades_per_day,
    }
    return {
        "passed": all(checks.values()),
        "checks": checks,
        "requirements": dataclasses.asdict(gate),
        "status": (
            "research_gate_passed_manual_review_still_required"
            if all(checks.values())
            else "rejected_insufficient_evidence_or_frequency"
        ),
    }


def analyze_causal_percentage_signals(
    *,
    times: typing.Iterable[typing.Any],
    opens: typing.Iterable[typing.Any],
    highs: typing.Iterable[typing.Any],
    lows: typing.Iterable[typing.Any],
    closes: typing.Iterable[typing.Any],
    volumes: typing.Iterable[typing.Any],
    rule: PercentageSignalRule | None = None,
    percentage_config: percentage_engine.PercentageEngineConfig | None = None,
    evidence_gate: PercentageEvidenceGate | None = None,
) -> dict:
    """Evaluate the frozen causal rule on fully resolved historical entries."""

    selected_rule = rule or PercentageSignalRule()
    selected_rule.validate()
    selected_gate = evidence_gate or PercentageEvidenceGate()
    selected_gate.validate()
    selected_percentage_config = (
        percentage_config or percentage_engine.PercentageEngineConfig()
    )
    selected_percentage_config.validate()

    time_values, open_values, high_values, low_values, close_values = (
        percentage_engine._validate_inputs(times, opens, highs, lows, closes)
    )
    volume_values = _as_non_negative_finite(volumes, "volumes")
    if len(volume_values) != len(time_values):
        raise ValueError("volume array must match candle arrays")

    last_closed_index = len(time_values) - (
        2 if selected_percentage_config.exclude_last_candle else 1
    )
    last_resolved_entry = (
        last_closed_index - selected_percentage_config.horizon_candles
    )
    if last_resolved_entry < 1:
        raise ValueError("not enough closed candles for resolved signal outcomes")

    feature_arrays = _build_feature_arrays(
        open_values,
        high_values,
        low_values,
        close_values,
        volume_values,
    )
    candidates: list[dict] = []
    for entry_index in range(last_resolved_entry + 1):
        for direction in selected_percentage_config.directions:
            matches, feature_values = _matches_rule(
                feature_arrays,
                entry_index,
                direction,
                selected_rule,
            )
            if not matches:
                continue
            outcome = percentage_engine.simulate_trade(
                time_values,
                high_values,
                low_values,
                close_values,
                entry_index,
                direction,
                last_closed_index,
                selected_percentage_config,
            )
            outcome["net_return_pct"] = (
                float(outcome["gross_return_pct"])
                - selected_rule.round_trip_cost_pct
            )
            outcome["signal_features"] = feature_values
            outcome["signal_uses_future"] = False
            candidates.append(outcome)

    trades: list[dict] = []
    current_exit_index = -1
    ordered_candidates = sorted(
        candidates,
        key=lambda trade: (trade["entry_index"], trade["direction"]),
    )
    candidate_index = 0
    while candidate_index < len(ordered_candidates):
        entry_index = ordered_candidates[candidate_index]["entry_index"]
        same_entry: list[dict] = []
        while (
            candidate_index < len(ordered_candidates)
            and ordered_candidates[candidate_index]["entry_index"] == entry_index
        ):
            same_entry.append(ordered_candidates[candidate_index])
            candidate_index += 1
        if entry_index <= current_exit_index:
            continue
        if len(same_entry) > 1:
            # Conflicting long/short conditions fail closed.
            current_exit_index = entry_index
            continue
        candidate = same_entry[0]
        trades.append(candidate)
        current_exit_index = int(candidate["exit_index"])

    evidence = dict(FROZEN_V1_EVIDENCE)
    return {
        "schema_version": 1,
        "mode": "causal_percentage_candidate_v1",
        "research_only": True,
        "signal_uses_future_outcomes": False,
        "evaluation_uses_future_outcomes": True,
        "orders_authorized": False,
        "automatic_promotion": False,
        "time_frame": "1h",
        "rule": dataclasses.asdict(selected_rule),
        "percentage_config": dataclasses.asdict(selected_percentage_config),
        "frozen_evidence": evidence,
        "evidence_gate": _frozen_evidence_gate(evidence, selected_gate),
        "chart_summary": _summarize_trades(
            trades,
            closed_candles=last_closed_index + 1,
            candidate_signals=len(candidates),
        ),
        "trades": trades,
        "warning": (
            "Entries use only indicators available at the candle close. Future "
            "candles are used only to score completed chart outcomes. The held-"
            "out sample and frequency are insufficient for strategy promotion."
        ),
    }
