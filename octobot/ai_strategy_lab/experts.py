"""Frozen, interpretable expert rules for regime-specific research."""

from __future__ import annotations

import dataclasses
import datetime
import typing

import numpy

from octobot.ai_strategy_lab import dataset as dataset_module
from octobot.ai_strategy_lab import model as model_module


EXPERT_SCHEMA_VERSION = 1


@dataclasses.dataclass(frozen=True)
class ExpertDefinition:
    name: str
    description: str
    thresholds: dict[str, float]


# These definitions are intentionally constants. Version them instead of tuning
# them in-place after results are observed.
EXPERT_DEFINITIONS = (
    ExpertDefinition(
        "trend_pullback_v1",
        "Both directions: aligned 4h/1h trend, shallow 15m pullback and resumed momentum.",
        {
            "4h_adx_min": 0.22,
            "1h_adx_min": 0.18,
            "15m_directional_bb_min": -0.30,
            "15m_directional_bb_max": 0.15,
            "15m_directional_rsi_min": -0.25,
            "15m_directional_macd_min": 0.0,
        },
    ),
    ExpertDefinition(
        "range_reversion_v1",
        "Both directions: low-trend regime and statistically stretched 15m reversal.",
        {
            "4h_adx_max": 0.18,
            "1h_adx_max": 0.20,
            "15m_directional_bb_max": -0.35,
            "15m_directional_rsi_max": -0.25,
            "15m_directional_return4_max": 0.0,
        },
    ),
    ExpertDefinition(
        "breakout_v1",
        "Both directions: aligned trend, expanding 15m move and volume confirmation.",
        {
            "4h_adx_min": 0.20,
            "15m_directional_return4_min": 0.004,
            "15m_directional_bb_min": 0.35,
            "15m_volume_zscore_min": 1.0,
        },
    ),
    ExpertDefinition(
        "short_momentum_v1",
        "Short only: persistent 4h/1h downside trend with fresh 1h acceleration.",
        {
            "4h_adx_min": 0.25,
            "1h_adx_min": 0.22,
            "1h_directional_return4_min": 0.005,
            "15m_volume_zscore_min": 0.5,
        },
    ),
)


def evaluate_experts(
    dataset: dataset_module.ResearchDataset,
    *,
    position_fraction: float = 0.10,
    folds: int = 6,
) -> dict:
    if not 0 < position_fraction <= 1:
        raise ValueError("position_fraction must be in (0, 1]")
    if folds < 2:
        raise ValueError("folds must be at least two")
    masks = expert_masks(dataset)
    reports = {}
    union_indices = []
    for definition in EXPERT_DEFINITIONS:
        eligible = numpy.flatnonzero(masks[definition.name])
        selected = _select_fixed_candidates(dataset, eligible)
        report = model_module.trading_metrics(
            dataset, selected, position_fraction=position_fraction
        )
        report["calendar"] = _calendar_metrics(
            dataset, selected, position_fraction
        )
        report["temporal_folds"] = _temporal_metrics(
            dataset, eligible, position_fraction, folds
        )
        reports[definition.name] = report
        union_indices.extend(int(value) for value in eligible)
    combined = _select_fixed_candidates(
        dataset, numpy.asarray(sorted(set(union_indices)), dtype=numpy.int64)
    )
    combined_report = model_module.trading_metrics(
        dataset, combined, position_fraction=position_fraction
    )
    combined_report["calendar"] = _calendar_metrics(
        dataset, combined, position_fraction
    )
    combined_report["temporal_folds"] = _temporal_metrics(
        dataset,
        numpy.asarray(sorted(set(union_indices)), dtype=numpy.int64),
        position_fraction,
        folds,
    )
    return {
        "schema_version": EXPERT_SCHEMA_VERSION,
        "definitions": [dataclasses.asdict(value) for value in EXPERT_DEFINITIONS],
        "position_fraction": position_fraction,
        "experts": reports,
        "combined_union": combined_report,
    }


def expert_masks(
    dataset: dataset_module.ResearchDataset,
) -> dict[str, numpy.ndarray]:
    values = {
        name: dataset.features[:, index]
        for index, name in enumerate(dataset.feature_names)
    }
    trend_alignment = (
        (values["directional_4h_ema_spread_pct"] > 0)
        & (values["directional_4h_ema_slope_pct"] > 0)
        & (values["directional_1h_ema_spread_pct"] > 0)
        & (values["directional_1h_ema_slope_pct"] > 0)
    )
    trend_pullback = (
        trend_alignment
        & (values["4h_adx"] >= 0.22)
        & (values["1h_adx"] >= 0.18)
        & (values["directional_15m_bb_position"] >= -0.30)
        & (values["directional_15m_bb_position"] <= 0.15)
        & (values["directional_15m_rsi_centered"] >= -0.25)
        & (values["directional_15m_macd_hist_pct"] > 0)
    )
    range_reversion = (
        (values["4h_adx"] < 0.18)
        & (values["1h_adx"] < 0.20)
        & (values["directional_15m_bb_position"] <= -0.35)
        & (values["directional_15m_rsi_centered"] <= -0.25)
        & (values["directional_15m_return_4"] <= 0)
    )
    breakout = (
        trend_alignment
        & (values["4h_adx"] >= 0.20)
        & (values["directional_15m_return_4"] >= 0.004)
        & (values["directional_15m_bb_position"] >= 0.35)
        & (values["15m_volume_zscore"] >= 1.0)
    )
    short_momentum = (
        (dataset.direction == -1)
        & trend_alignment
        & (values["4h_adx"] >= 0.25)
        & (values["1h_adx"] >= 0.22)
        & (values["directional_1h_return_4"] >= 0.005)
        & (values["15m_volume_zscore"] >= 0.5)
    )
    return {
        "trend_pullback_v1": trend_pullback,
        "range_reversion_v1": range_reversion,
        "breakout_v1": breakout,
        "short_momentum_v1": short_momentum,
    }


def _select_fixed_candidates(
    dataset: dataset_module.ResearchDataset, eligible: numpy.ndarray
) -> numpy.ndarray:
    if not len(eligible):
        return eligible
    # Fixed rules have no fitted score. If two directions collide, choose the
    # candidate with the larger absolute directional 4h EMA spread, then short
    # only as a deterministic final tie-break.
    feature = dataset.feature_names.index("directional_4h_ema_spread_pct")
    best_by_event = {}
    for index in eligible:
        index = int(index)
        key = (str(dataset.symbol[index]), int(dataset.timestamp[index]))
        score = (
            float(dataset.features[index, feature]),
            int(dataset.direction[index] == -1),
        )
        previous = best_by_event.get(key)
        if previous is None or score > previous[1]:
            best_by_event[key] = (index, score)
    ordered = numpy.asarray(
        [
            value[0]
            for value in sorted(
                best_by_event.values(),
                key=lambda value: (
                    int(dataset.timestamp[value[0]]),
                    str(dataset.symbol[value[0]]),
                ),
            )
        ],
        dtype=numpy.int64,
    )
    return model_module.remove_overlaps(dataset, ordered)


def _temporal_metrics(
    dataset: dataset_module.ResearchDataset,
    eligible: numpy.ndarray,
    position_fraction: float,
    folds: int,
) -> list[dict]:
    unique_times = numpy.unique(dataset.timestamp)
    boundaries = numpy.linspace(0, len(unique_times), folds + 1, dtype=int)
    reports = []
    for fold in range(folds):
        start = int(unique_times[boundaries[fold]])
        end = (
            int(unique_times[boundaries[fold + 1]])
            if boundaries[fold + 1] < len(unique_times)
            else int(unique_times[-1] + 1)
        )
        candidates = eligible[
            (dataset.timestamp[eligible] >= start)
            & (dataset.timestamp[eligible] < end)
        ]
        selected = _select_fixed_candidates(dataset, candidates)
        metrics = model_module.trading_metrics(
            dataset, selected, position_fraction=position_fraction
        )
        reports.append(
            {
                "fold": fold + 1,
                "start_timestamp": start,
                "end_timestamp": end,
                **metrics,
            }
        )
    return reports


def _calendar_metrics(
    dataset: dataset_module.ResearchDataset,
    selected: numpy.ndarray,
    position_fraction: float,
) -> dict:
    first = datetime.datetime.fromtimestamp(
        int(numpy.min(dataset.timestamp)), datetime.timezone.utc
    ).date()
    last = datetime.datetime.fromtimestamp(
        int(numpy.max(dataset.timestamp)), datetime.timezone.utc
    ).date()
    months = _month_range(first, last)
    values = {month: [] for month in months}
    for index in selected:
        month = datetime.datetime.fromtimestamp(
            int(dataset.exit_timestamp[index]), datetime.timezone.utc
        ).strftime("%Y-%m")
        values.setdefault(month, []).append(
            float(dataset.net_return[index]) * position_fraction
        )
    returns = {
        month: (
            float(numpy.prod(1 + numpy.asarray(trades)) - 1)
            if trades
            else 0.0
        )
        for month, trades in sorted(values.items())
    }
    ordered = list(returns.values())
    longest_negative = 0
    current_negative = 0
    for value in ordered:
        current_negative = current_negative + 1 if value < 0 else 0
        longest_negative = max(longest_negative, current_negative)
    return {
        "months": len(ordered),
        "positive_months": sum(value > 0 for value in ordered),
        "negative_months": sum(value < 0 for value in ordered),
        "zero_months": sum(value == 0 for value in ordered),
        "positive_month_ratio": (
            sum(value > 0 for value in ordered) / len(ordered)
            if ordered
            else 0.0
        ),
        "median_month_return": float(numpy.median(ordered)) if ordered else 0.0,
        "worst_month_return": min(ordered, default=0.0),
        "best_month_return": max(ordered, default=0.0),
        "longest_negative_month_streak": longest_negative,
        "monthly_returns": returns,
    }


def _month_range(
    start: datetime.date, end: datetime.date
) -> list[str]:
    result = []
    year, month = start.year, start.month
    while (year, month) <= (end.year, end.month):
        result.append(f"{year:04d}-{month:02d}")
        month += 1
        if month == 13:
            year += 1
            month = 1
    return result
