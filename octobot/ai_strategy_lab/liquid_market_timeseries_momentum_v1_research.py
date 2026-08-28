"""Offline evaluator for liquid-market time-series momentum V1.

The evaluator reads one frozen public Binance daily/funding panel.  It has no
network or exchange client and can create exactly one historical training
diagnostic.  Historical results can never authorize an order.
"""

from __future__ import annotations

import argparse
import datetime
import json
import math
import os
import pathlib
import shutil
import tempfile
import typing

import numpy

from octobot.ai_strategy_lab import cointegration_pairs_v1 as common
from octobot.ai_strategy_lab import (
    liquid_cross_sectional_momentum_v1_research as parent_research,
)
from octobot.ai_strategy_lab import (
    liquid_market_timeseries_momentum_v1 as protocol_module,
)


SCHEMA_VERSION = 1
UTC = datetime.timezone.utc
EPOCH_DATE = datetime.date(1970, 1, 1)


class DataQualityError(ValueError):
    """Raised when frozen inputs or a simulated outcome are invalid."""


def _load_protocol(path_value: typing.Union[str, pathlib.Path]) -> dict:
    path = pathlib.Path(path_value).resolve()
    persisted = json.loads(path.read_text(encoding="utf-8"))
    frozen = protocol_module.frozen_protocol()
    expected = {**frozen, "protocol_sha256": common._json_hash(frozen)}
    if persisted != expected:
        raise ValueError("liquid-market time-series protocol is not frozen")
    return persisted


def _load_market(
    snapshot_value: typing.Union[str, pathlib.Path],
    history_value: typing.Union[str, pathlib.Path],
) -> tuple[pathlib.Path, dict, pathlib.Path, dict, dict]:
    loaded = parent_research._load_market(snapshot_value, history_value)
    snapshot_root, snapshot_manifest, history_root, history_manifest, market = (
        loaded
    )
    panel_path = history_root / "market-panel.npz"
    with numpy.load(panel_path, allow_pickle=False) as values:
        required = {"timestamps", "symbols", "quote_volumes"}
        if not required.issubset(values.files):
            raise DataQualityError("frozen panel lacks quote-volume evidence")
        timestamps = numpy.asarray(values["timestamps"], dtype=numpy.int64)
        symbols = [str(value) for value in values["symbols"]]
        quote_volumes = numpy.asarray(
            values["quote_volumes"], dtype=numpy.float64
        )
    if (
        not numpy.array_equal(timestamps, market["timestamps"])
        or symbols != market["symbols"]
        or quote_volumes.shape != market["closes"].shape
        or numpy.any(numpy.isinf(quote_volumes))
        or numpy.any(numpy.isfinite(quote_volumes) & (quote_volumes < 0))
    ):
        raise DataQualityError("frozen quote-volume panel differs")
    market = {**market, "quote_volumes": quote_volumes}
    return (
        snapshot_root,
        snapshot_manifest,
        history_root,
        history_manifest,
        market,
    )


def _source_artifacts(test_path: pathlib.Path) -> list[dict]:
    values = (
        ("evaluator", pathlib.Path(__file__).resolve()),
        ("protocol", pathlib.Path(protocol_module.__file__).resolve()),
        ("test", test_path.resolve()),
        ("parent_market_loader", pathlib.Path(parent_research.__file__).resolve()),
        (
            "market_loader",
            pathlib.Path(parent_research.market_source.__file__).resolve(),
        ),
        (
            "frozen_source_loader",
            pathlib.Path(parent_research.source.__file__).resolve(),
        ),
    )
    artifacts = []
    for label, path in values:
        if not path.is_file():
            raise DataQualityError(f"implementation artifact is absent: {label}")
        artifacts.append(
            {
                "label": label,
                "path": str(path),
                "bytes": path.stat().st_size,
                "sha256": common._sha256(path),
            }
        )
    return artifacts


def write_or_verify_implementation_lock(
    protocol_value: typing.Union[str, pathlib.Path],
    test_value: typing.Union[str, pathlib.Path],
    output_value: typing.Union[str, pathlib.Path],
) -> dict:
    """Freeze all executable inputs before reading economic outcomes."""

    protocol_path = pathlib.Path(protocol_value).resolve()
    protocol = _load_protocol(protocol_path)
    test_path = pathlib.Path(test_value).resolve()
    output = pathlib.Path(output_value).resolve()
    if output.is_file():
        return _verify_implementation_lock(output, protocol_path, test_path)
    payload = {
        "schema_version": SCHEMA_VERSION,
        "protocol_version": protocol_module.PROTOCOL_VERSION,
        "created_at": datetime.datetime.now(UTC).isoformat(),
        "status": "implementation_frozen_before_outcomes",
        "protocol_sha256": protocol["protocol_sha256"],
        "protocol_file_sha256": common._sha256(protocol_path),
        "source_snapshot_bundle_sha256": (
            protocol_module.data_parent.SOURCE_SNAPSHOT_BUNDLE_SHA256
        ),
        "history_bundle_sha256": (
            protocol_module.data_parent.HISTORY_BUNDLE_SHA256
        ),
        "market_panel_sha256": protocol_module.data_parent.MARKET_PANEL_SHA256,
        "source_artifacts": _source_artifacts(test_path),
        "numpy_version": numpy.__version__,
        "economic_outcomes_read_before_lock": False,
        "results_existing_before_lock": False,
        "research_only": True,
        "credentials_used": False,
        "orders_authorized": False,
        "paper_orders_authorized": False,
        "automatic_promotion": False,
    }
    payload["content_sha256"] = common._json_hash(payload)
    common._atomic_json(output, payload)
    return payload


def _verify_implementation_lock(
    lock_value: typing.Union[str, pathlib.Path],
    protocol_path: pathlib.Path,
    test_path: pathlib.Path,
) -> dict:
    lock_path = pathlib.Path(lock_value).resolve()
    lock = json.loads(lock_path.read_text(encoding="utf-8"))
    content = {key: value for key, value in lock.items() if key != "content_sha256"}
    checks = (
        lock.get("content_sha256") == common._json_hash(content),
        lock.get("status") == "implementation_frozen_before_outcomes",
        lock.get("protocol_sha256")
        == common._json_hash(protocol_module.frozen_protocol()),
        lock.get("protocol_file_sha256") == common._sha256(protocol_path),
        lock.get("source_snapshot_bundle_sha256")
        == protocol_module.data_parent.SOURCE_SNAPSHOT_BUNDLE_SHA256,
        lock.get("history_bundle_sha256")
        == protocol_module.data_parent.HISTORY_BUNDLE_SHA256,
        lock.get("market_panel_sha256")
        == protocol_module.data_parent.MARKET_PANEL_SHA256,
        lock.get("source_artifacts") == _source_artifacts(test_path),
        lock.get("numpy_version") == numpy.__version__,
        lock.get("economic_outcomes_read_before_lock") is False,
        lock.get("results_existing_before_lock") is False,
        lock.get("research_only") is True,
        lock.get("credentials_used") is False,
        lock.get("orders_authorized") is False,
        lock.get("paper_orders_authorized") is False,
        lock.get("automatic_promotion") is False,
    )
    if not all(checks):
        raise DataQualityError("implementation lock differs")
    return lock


def prepare_market(market: dict) -> dict:
    """Precompute causal eligibility and volume rankings without outcomes."""

    closes = numpy.asarray(market["closes"], dtype=numpy.float64)
    volumes = numpy.asarray(market["quote_volumes"], dtype=numpy.float64)
    symbols = [str(value) for value in market["symbols"]]
    if (
        closes.ndim != 2
        or closes.shape != volumes.shape
        or closes.shape[1] != len(symbols)
        or closes.shape[0] != len(market["dates"])
    ):
        raise DataQualityError("unexpected market preparation shape")
    close_valid = numpy.isfinite(closes) & (closes > 0)
    volume_valid = numpy.isfinite(volumes) & (volumes >= 0)
    close_invalid_cumulative = numpy.vstack(
        (
            numpy.zeros((1, closes.shape[1]), dtype=numpy.int64),
            numpy.cumsum(~close_valid, axis=0, dtype=numpy.int64),
        )
    )
    volume_invalid_cumulative = numpy.vstack(
        (
            numpy.zeros((1, closes.shape[1]), dtype=numpy.int64),
            numpy.cumsum(~volume_valid, axis=0, dtype=numpy.int64),
        )
    )
    eligible = numpy.zeros_like(close_valid)
    volume_medians = numpy.full_like(closes, numpy.nan)
    rankings: list[tuple[int, ...]] = [tuple() for _ in market["dates"]]
    history = protocol_module.MINIMUM_CONTIGUOUS_HISTORY_DAYS
    liquidity = protocol_module.LIQUIDITY_LOOKBACK_DAYS
    for index in range(history - 1, len(market["dates"])):
        complete_closes = (
            close_invalid_cumulative[index + 1]
            - close_invalid_cumulative[index + 1 - history]
            == 0
        )
        complete_volumes = (
            volume_invalid_cumulative[index + 1]
            - volume_invalid_cumulative[index + 1 - liquidity]
            == 0
        )
        eligible[index] = complete_closes & complete_volumes
        columns = numpy.flatnonzero(eligible[index])
        if len(columns):
            medians = numpy.median(
                volumes[index + 1 - liquidity : index + 1, columns], axis=0
            )
            volume_medians[index, columns] = medians
            rankings[index] = tuple(
                sorted(
                    (int(value) for value in columns),
                    key=lambda value: (
                        -volume_medians[index, value],
                        symbols[value],
                    ),
                )
            )
    return {
        "eligible": eligible,
        "volume_medians": volume_medians,
        "rankings": rankings,
    }


def liquid_basket(
    market: dict,
    index: int,
    *,
    excluded_symbols: typing.AbstractSet[str] = frozenset(),
    prepared: dict | None = None,
) -> tuple[tuple[int, ...], dict]:
    """Select the causal trailing-volume basket at one completed boundary."""

    prepared = prepare_market(market) if prepared is None else prepared
    symbols = market["symbols"]
    ranked = tuple(
        value
        for value in prepared["rankings"][index]
        if symbols[value] not in excluded_symbols
    )
    selected = (
        ranked[: protocol_module.LIQUID_BASKET_ASSETS]
        if len(ranked) >= protocol_module.MINIMUM_ELIGIBLE_ASSETS
        else tuple()
    )
    return selected, {
        "status": "BASKET" if selected else "INSUFFICIENT_ELIGIBLE_ASSETS",
        "date": market["dates"][index].isoformat(),
        "eligible_assets": len(ranked),
        "basket_assets": len(selected),
        "basket_symbols": [symbols[value] for value in selected],
    }


def _upper_tercile_signal(
    current_score: float, prior_scores: typing.Sequence[float]
) -> tuple[bool, float]:
    if len(prior_scores) < protocol_module.MINIMUM_PRIOR_FORMATION_BLOCKS:
        raise ValueError("upper-tercile signal lacks prior formation blocks")
    ordered = sorted(float(value) for value in prior_scores)
    rank = math.ceil((1.0 - protocol_module.ENTRY_TAIL_FRACTION) * len(ordered))
    threshold = ordered[max(0, rank - 1)]
    return bool(current_score > threshold), float(threshold)


def build_signal_cache(
    market: dict,
    *,
    excluded_symbols: typing.AbstractSet[str] = frozenset(),
    prepared: dict | None = None,
) -> dict:
    """Build all causal scores and daily decisions for one exclusion set."""

    prepared = prepare_market(market) if prepared is None else prepared
    closes = numpy.asarray(market["closes"], dtype=numpy.float64)
    count = len(market["dates"])
    scores = numpy.full(count, numpy.nan, dtype=numpy.float64)
    thresholds = numpy.full(count, numpy.nan, dtype=numpy.float64)
    decision_valid = numpy.zeros(count, dtype=bool)
    active = numpy.zeros(count, dtype=bool)
    eligible_assets = numpy.zeros(count, dtype=numpy.int16)
    baskets: list[tuple[int, ...]] = [tuple() for _ in range(count)]
    for index in range(count):
        basket, audit = liquid_basket(
            market,
            index,
            excluded_symbols=excluded_symbols,
            prepared=prepared,
        )
        eligible_assets[index] = audit["eligible_assets"]
        baskets[index] = basket
        if not basket:
            continue
        formation_index = index - protocol_module.FORMATION_DAYS
        if formation_index < 0:
            continue
        values = closes[index, list(basket)] / closes[
            formation_index, list(basket)
        ] - 1.0
        if not numpy.all(numpy.isfinite(values)):
            raise DataQualityError("liquid basket has invalid formation return")
        scores[index] = float(numpy.mean(values))
    for index, score in enumerate(scores):
        if not math.isfinite(float(score)):
            continue
        prior = []
        prior_index = index - protocol_module.FORMATION_DAYS
        while prior_index >= 0:
            value = float(scores[prior_index])
            if math.isfinite(value):
                prior.append(value)
            prior_index -= protocol_module.FORMATION_DAYS
        if len(prior) < protocol_module.MINIMUM_PRIOR_FORMATION_BLOCKS:
            continue
        active[index], thresholds[index] = _upper_tercile_signal(score, prior)
        decision_valid[index] = True
    return {
        "excluded_symbols": tuple(sorted(excluded_symbols)),
        "scores": scores,
        "thresholds": thresholds,
        "decision_valid": decision_valid,
        "active": active,
        "eligible_assets": eligible_assets,
        "baskets": baskets,
    }


def _target_from_basket(
    asset_count: int, basket: typing.Sequence[int], gross: float
) -> numpy.ndarray:
    target = numpy.zeros(asset_count, dtype=numpy.float64)
    if basket:
        target[list(basket)] = gross / len(basket)
    return target


def update_vintage_targets(
    vintages: numpy.ndarray,
    date: datetime.date,
    new_target: numpy.ndarray,
) -> numpy.ndarray:
    """Replace the epoch-anchored vintage and return the net aggregate."""

    if vintages.shape != (
        protocol_module.STAGGERED_VINTAGES,
        len(new_target),
    ):
        raise ValueError("unexpected vintage target shape")
    slot = (date - EPOCH_DATE).days % protocol_module.STAGGERED_VINTAGES
    vintages[slot] = new_target
    aggregate = numpy.sum(vintages, axis=0)
    if numpy.sum(numpy.abs(aggregate)) > (
        protocol_module.MAXIMUM_GROSS_EXPOSURE + 1e-12
    ):
        raise RuntimeError("aggregate vintage target exceeds gross cap")
    return aggregate


def _period_compound_returns(
    dates: list[datetime.date], values: numpy.ndarray, format_value: str
) -> dict:
    grouped: dict[str, list[float]] = {}
    for date, value in zip(dates, values):
        grouped.setdefault(date.strftime(format_value), []).append(float(value))
    return {
        key: float(numpy.prod(1.0 + numpy.asarray(group)) - 1.0)
        for key, group in sorted(grouped.items())
    }


def _return_metrics(
    daily: numpy.ndarray,
    outcome_dates: list[datetime.date],
) -> tuple[dict, numpy.ndarray]:
    equity = numpy.cumprod(1.0 + daily)
    peaks = numpy.maximum.accumulate(
        numpy.concatenate((numpy.ones(1), equity))
    )[1:]
    drawdown = 1.0 - equity / peaks
    gains = float(numpy.sum(daily[daily > 0]))
    losses = float(-numpy.sum(daily[daily < 0]))
    monthly = _period_compound_returns(outcome_dates, daily, "%Y-%m")
    metrics = {
        "total_return": float(equity[-1] - 1.0),
        "annualized_return": float(
            equity[-1] ** (365.25 / len(daily)) - 1.0
        ),
        "sharpe_zero_rate": (
            float(numpy.mean(daily) / numpy.std(daily) * math.sqrt(365.0))
            if numpy.std(daily) > 0
            else 0.0
        ),
        "profit_factor": (
            gains / losses
            if losses > 0
            else (math.inf if gains > 0 else 0.0)
        ),
        "maximum_drawdown": float(numpy.max(drawdown)),
        "positive_month_ratio": (
            sum(value > 0 for value in monthly.values()) / len(monthly)
            if monthly
            else 0.0
        ),
        "months": monthly,
    }
    return metrics, equity


def _validate_outcome(
    market: dict,
    index: int,
    strategy_target: numpy.ndarray,
    benchmark_target: numpy.ndarray,
) -> None:
    union = numpy.flatnonzero(
        (numpy.abs(strategy_target) > 1e-15)
        | (numpy.abs(benchmark_target) > 1e-15)
    )
    if len(union) and (
        not numpy.all(market["return_complete"][index + 1, union])
        or not numpy.all(market["funding_counts"][index + 1, union] > 0)
        or not numpy.all(numpy.isfinite(market["funding"][index + 1, union]))
    ):
        raise DataQualityError("active liquid-market target has incomplete outcome")


def _portfolio_contribution(
    market: dict,
    index: int,
    previous: numpy.ndarray,
    target: numpy.ndarray,
    cost_rate: float,
) -> tuple[numpy.ndarray, numpy.ndarray, numpy.ndarray, numpy.ndarray]:
    selected = numpy.flatnonzero(numpy.abs(target) > 1e-15)
    price = numpy.zeros_like(target)
    funding = numpy.zeros_like(target)
    price[selected] = target[selected] * market["returns"][index + 1, selected]
    funding[selected] = (
        -target[selected] * market["funding"][index + 1, selected]
    )
    cost = numpy.abs(target - previous) * cost_rate
    return price + funding - cost, price, funding, cost


def simulate_period(
    market: dict,
    start: datetime.datetime,
    end: datetime.datetime,
    *,
    cost_multiplier: float = 1.0,
    excluded_symbols: typing.AbstractSet[str] = frozenset(),
    include_trajectory: bool = False,
    prepared: dict | None = None,
    signal_cache: dict | None = None,
) -> dict:
    """Simulate one half-open interval, independently opened and closed flat."""

    if end <= start or cost_multiplier < 1.0:
        raise ValueError("invalid time-series simulation interval or cost")
    prepared = prepare_market(market) if prepared is None else prepared
    signal_cache = (
        build_signal_cache(
            market,
            excluded_symbols=excluded_symbols,
            prepared=prepared,
        )
        if signal_cache is None
        else signal_cache
    )
    if signal_cache["excluded_symbols"] != tuple(sorted(excluded_symbols)):
        raise ValueError("signal cache exclusion set differs")
    start_date, end_date = start.date(), end.date()
    dates = market["dates"]
    indices = [
        index
        for index in range(len(dates) - 1)
        if dates[index] >= start_date and dates[index + 1] <= end_date
    ]
    if not indices:
        raise DataQualityError("time-series evaluation interval is absent")
    symbols = market["symbols"]
    asset_count = len(symbols)
    strategy_vintages = numpy.zeros(
        (protocol_module.STAGGERED_VINTAGES, asset_count), dtype=numpy.float64
    )
    benchmark_vintages = numpy.zeros_like(strategy_vintages)
    previous = numpy.zeros(asset_count, dtype=numpy.float64)
    benchmark_previous = previous.copy()
    cost_rate = cost_multiplier * (
        protocol_module.FEE_PER_TURNOVER
        + protocol_module.SLIPPAGE_PER_TURNOVER
    )
    daily_returns = []
    benchmark_returns = []
    outcome_dates = []
    gross_exposure = []
    benchmark_gross = []
    targets = []
    benchmark_targets = []
    signal_active_path = []
    symbol_contributions = numpy.zeros(asset_count, dtype=numpy.float64)
    total_price = total_funding = total_cost = total_turnover = 0.0
    benchmark_price = benchmark_funding = benchmark_cost = 0.0
    benchmark_turnover = 0.0
    invested_days = signal_decisions = active_vintage_decisions = 0
    basket_decisions = 0
    ever_targeted: set[str] = set()

    for index in indices:
        basket = signal_cache["baskets"][index]
        decision_valid = bool(signal_cache["decision_valid"][index])
        signal_active = decision_valid and bool(signal_cache["active"][index])
        strategy_new = _target_from_basket(
            asset_count,
            basket if signal_active else (),
            protocol_module.VINTAGE_GROSS_EXPOSURE,
        )
        benchmark_new = _target_from_basket(
            asset_count,
            basket,
            protocol_module.VINTAGE_GROSS_EXPOSURE,
        )
        target = update_vintage_targets(
            strategy_vintages, dates[index], strategy_new
        )
        benchmark_target = update_vintage_targets(
            benchmark_vintages, dates[index], benchmark_new
        )
        signal_decisions += int(decision_valid)
        active_vintage_decisions += int(signal_active)
        basket_decisions += int(bool(basket))
        _validate_outcome(market, index, target, benchmark_target)
        contribution, price, funding, cost = _portfolio_contribution(
            market, index, previous, target, cost_rate
        )
        (
            benchmark_contribution,
            benchmark_day_price,
            benchmark_day_funding,
            benchmark_day_cost,
        ) = _portfolio_contribution(
            market,
            index,
            benchmark_previous,
            benchmark_target,
            cost_rate,
        )
        net = float(numpy.sum(contribution))
        benchmark_net = float(numpy.sum(benchmark_contribution))
        if (
            not math.isfinite(net)
            or not math.isfinite(benchmark_net)
            or net <= -1.0
            or benchmark_net <= -1.0
        ):
            raise DataQualityError("invalid liquid-market portfolio return")
        daily_returns.append(net)
        benchmark_returns.append(benchmark_net)
        outcome_dates.append(dates[index + 1])
        gross = float(numpy.sum(numpy.abs(target)))
        benchmark_day_gross = float(numpy.sum(numpy.abs(benchmark_target)))
        gross_exposure.append(gross)
        benchmark_gross.append(benchmark_day_gross)
        invested_days += int(gross > 1e-15)
        symbol_contributions += contribution
        total_price += float(numpy.sum(price))
        total_funding += float(numpy.sum(funding))
        total_cost += float(numpy.sum(cost))
        total_turnover += float(numpy.sum(numpy.abs(target - previous)))
        benchmark_price += float(numpy.sum(benchmark_day_price))
        benchmark_funding += float(numpy.sum(benchmark_day_funding))
        benchmark_cost += float(numpy.sum(benchmark_day_cost))
        benchmark_turnover += float(
            numpy.sum(numpy.abs(benchmark_target - benchmark_previous))
        )
        targeted = numpy.flatnonzero(numpy.abs(target) > 1e-15)
        ever_targeted.update(symbols[value] for value in targeted)
        previous = target.copy()
        benchmark_previous = benchmark_target.copy()
        if include_trajectory:
            targets.append(target.copy())
            benchmark_targets.append(benchmark_target.copy())
            signal_active_path.append(signal_active)

    closing_cost = numpy.abs(previous) * cost_rate
    benchmark_closing_cost = numpy.abs(benchmark_previous) * cost_rate
    daily_returns[-1] -= float(numpy.sum(closing_cost))
    benchmark_returns[-1] -= float(numpy.sum(benchmark_closing_cost))
    symbol_contributions -= closing_cost
    total_cost += float(numpy.sum(closing_cost))
    total_turnover += float(numpy.sum(numpy.abs(previous)))
    benchmark_cost += float(numpy.sum(benchmark_closing_cost))
    benchmark_turnover += float(numpy.sum(numpy.abs(benchmark_previous)))

    daily = numpy.asarray(daily_returns, dtype=numpy.float64)
    benchmark_daily = numpy.asarray(benchmark_returns, dtype=numpy.float64)
    metrics, equity = _return_metrics(daily, outcome_dates)
    benchmark_metrics, benchmark_equity = _return_metrics(
        benchmark_daily, outcome_dates
    )
    benchmark_variance = float(numpy.var(benchmark_daily))
    beta = (
        float(
            numpy.mean(
                (daily - numpy.mean(daily))
                * (benchmark_daily - numpy.mean(benchmark_daily))
            )
        )
        / benchmark_variance
        if benchmark_variance > 0
        else 0.0
    )
    annualized_alpha = float(
        numpy.mean(daily - beta * benchmark_daily) * 365.0
    )
    drawdown_ratio = (
        metrics["maximum_drawdown"] / benchmark_metrics["maximum_drawdown"]
        if benchmark_metrics["maximum_drawdown"] > 0
        else (0.0 if metrics["maximum_drawdown"] == 0 else math.inf)
    )
    contribution_denominator = float(
        numpy.sum(numpy.abs(symbol_contributions))
    )
    eligible_on_basket_days = [
        int(signal_cache["eligible_assets"][index])
        for index in indices
        if signal_cache["baskets"][index]
    ]
    report = {
        "start": start.isoformat(),
        "end": end.isoformat(),
        "outcomes": len(daily),
        "cost_multiplier": cost_multiplier,
        **metrics,
        "invested_days": invested_days,
        "signal_decisions": signal_decisions,
        "active_vintage_decisions": active_vintage_decisions,
        "basket_decisions": basket_decisions,
        "market_beta": beta,
        "annualized_market_alpha": annualized_alpha,
        "sharpe_improvement_over_benchmark": (
            metrics["sharpe_zero_rate"]
            - benchmark_metrics["sharpe_zero_rate"]
        ),
        "drawdown_ratio_to_benchmark": drawdown_ratio,
        "price_additive_contribution": total_price,
        "funding_additive_contribution": total_funding,
        "cost_additive_contribution": total_cost,
        "gross_edge_before_costs": total_price + total_funding,
        "total_turnover": total_turnover,
        "average_gross_exposure": float(numpy.mean(gross_exposure)),
        "maximum_gross_exposure": float(numpy.max(gross_exposure)),
        "minimum_eligible_assets_at_basket_decision": min(
            eligible_on_basket_days, default=0
        ),
        "maximum_eligible_assets_at_basket_decision": max(
            eligible_on_basket_days, default=0
        ),
        "maximum_symbol_absolute_contribution_share": (
            float(
                numpy.max(numpy.abs(symbol_contributions))
                / contribution_denominator
            )
            if contribution_denominator > 0
            else 0.0
        ),
        "symbol_additive_contributions": {
            symbol: float(symbol_contributions[column])
            for column, symbol in enumerate(symbols)
            if abs(symbol_contributions[column]) > 1e-15
        },
        "ever_targeted_symbols": sorted(ever_targeted),
        "benchmark": {
            **benchmark_metrics,
            "price_additive_contribution": benchmark_price,
            "funding_additive_contribution": benchmark_funding,
            "cost_additive_contribution": benchmark_cost,
            "gross_edge_before_costs": benchmark_price + benchmark_funding,
            "total_turnover": benchmark_turnover,
            "average_gross_exposure": float(numpy.mean(benchmark_gross)),
            "maximum_gross_exposure": float(numpy.max(benchmark_gross)),
        },
    }
    if include_trajectory:
        report["_trajectory"] = {
            "timestamps": numpy.asarray(
                [
                    int(
                        datetime.datetime.combine(
                            date, datetime.time(), UTC
                        ).timestamp()
                    )
                    for date in outcome_dates
                ],
                dtype=numpy.int64,
            ),
            "daily_return": daily,
            "benchmark_daily_return": benchmark_daily,
            "equity": equity,
            "benchmark_equity": benchmark_equity,
            "gross_exposure": numpy.asarray(
                gross_exposure, dtype=numpy.float64
            ),
            "benchmark_gross_exposure": numpy.asarray(
                benchmark_gross, dtype=numpy.float64
            ),
            "targets": numpy.asarray(targets, dtype=numpy.float64),
            "benchmark_targets": numpy.asarray(
                benchmark_targets, dtype=numpy.float64
            ),
            "signal_active": numpy.asarray(signal_active_path, dtype=bool),
            "symbols": numpy.asarray(symbols),
        }
    return report


def _compact(report: dict) -> dict:
    keys = (
        "total_return",
        "annualized_return",
        "sharpe_zero_rate",
        "profit_factor",
        "maximum_drawdown",
        "invested_days",
        "signal_decisions",
        "active_vintage_decisions",
        "market_beta",
        "annualized_market_alpha",
    )
    return {key: report[key] for key in keys}


def _without_trajectory(report: dict) -> dict:
    return {key: value for key, value in report.items() if key != "_trajectory"}


def _training_gate(
    report: dict,
    stress: dict,
    folds: list[dict],
    stress_folds: list[dict],
    positive_loo_ratio: float,
) -> dict:
    gate = protocol_module.frozen_protocol()["training_eligibility_gate"]
    checks = {
        "minimum_outcomes": report["outcomes"] >= gate["minimum_outcomes"],
        "minimum_signal_decisions": (
            report["signal_decisions"] >= gate["minimum_signal_decisions"]
        ),
        "minimum_invested_days": (
            report["invested_days"] >= gate["minimum_invested_days"]
        ),
        "minimum_active_vintage_decisions": (
            report["active_vintage_decisions"]
            >= gate["minimum_active_vintage_decisions"]
        ),
        "positive_total_return": report["total_return"] > 0,
        "stress_total_return_positive": stress["total_return"] > 0,
        "minimum_annualized_return": (
            report["annualized_return"] >= gate["minimum_annualized_return"]
        ),
        "minimum_stress_annualized_return": (
            stress["annualized_return"]
            >= gate["minimum_stress_annualized_return"]
        ),
        "minimum_sharpe": report["sharpe_zero_rate"] >= gate["minimum_sharpe"],
        "minimum_stress_sharpe": (
            stress["sharpe_zero_rate"] >= gate["minimum_stress_sharpe"]
        ),
        "minimum_profit_factor": (
            report["profit_factor"] >= gate["minimum_profit_factor"]
        ),
        "minimum_stress_profit_factor": (
            stress["profit_factor"] >= gate["minimum_stress_profit_factor"]
        ),
        "maximum_drawdown": (
            report["maximum_drawdown"] <= gate["maximum_drawdown"]
        ),
        "maximum_stress_drawdown": (
            stress["maximum_drawdown"] <= gate["maximum_stress_drawdown"]
        ),
        "minimum_positive_month_ratio": (
            report["positive_month_ratio"]
            >= gate["minimum_positive_month_ratio"]
        ),
        "minimum_positive_folds": (
            sum(value["total_return"] > 0 for value in folds)
            >= gate["minimum_positive_folds"]
        ),
        "minimum_positive_stress_folds": (
            sum(value["total_return"] > 0 for value in stress_folds)
            >= gate["minimum_positive_stress_folds"]
        ),
        "required_folds": (
            len(folds) == len(stress_folds) == gate["required_folds"]
        ),
        "minimum_worst_stress_fold_return": (
            min(value["total_return"] for value in stress_folds)
            >= gate["minimum_worst_stress_fold_return"]
        ),
        "gross_edge_exceeds_costs": (
            report["gross_edge_before_costs"] > report["cost_additive_contribution"]
        ),
        "stress_gross_edge_exceeds_costs": (
            stress["gross_edge_before_costs"]
            > stress["cost_additive_contribution"]
        ),
        "maximum_absolute_market_beta": (
            abs(report["market_beta"]) <= gate["maximum_absolute_market_beta"]
        ),
        "minimum_annualized_market_alpha": (
            report["annualized_market_alpha"]
            >= gate["minimum_annualized_market_alpha"]
        ),
        "minimum_sharpe_improvement_over_benchmark": (
            report["sharpe_improvement_over_benchmark"]
            >= gate["minimum_sharpe_improvement_over_benchmark"]
        ),
        "maximum_drawdown_ratio_to_benchmark": (
            report["drawdown_ratio_to_benchmark"]
            <= gate["maximum_drawdown_ratio_to_benchmark"]
        ),
        "maximum_symbol_absolute_contribution_share": (
            report["maximum_symbol_absolute_contribution_share"]
            <= gate["maximum_symbol_absolute_contribution_share"]
        ),
        "minimum_positive_leave_one_symbol_out_ratio": (
            positive_loo_ratio
            >= gate["minimum_positive_leave_one_symbol_out_ratio"]
        ),
        "maximum_total_turnover": (
            report["total_turnover"] <= gate["maximum_total_turnover"]
        ),
        "minimum_average_gross_exposure": (
            report["average_gross_exposure"]
            >= gate["minimum_average_gross_exposure"]
        ),
        "maximum_post_net_gross": (
            report["maximum_gross_exposure"] <= gate["maximum_post_net_gross"]
        ),
    }
    if set(checks) != set(gate):
        raise RuntimeError("training gate implementation differs from protocol")
    return {
        "checks": checks,
        "passed_checks": sum(bool(value) for value in checks.values()),
        "total_checks": len(checks),
        "passed": all(checks.values()),
    }


def _write_trajectory(path: pathlib.Path, trajectory: dict) -> None:
    temporary = path.with_name(f".{path.name}.tmp")
    with temporary.open("wb") as file_handle:
        numpy.savez_compressed(file_handle, **trajectory)
        file_handle.flush()
        os.fsync(file_handle.fileno())
    os.replace(temporary, path)


def _require_no_evaluation(output_root: pathlib.Path, protocol_sha256: str) -> None:
    matches = list(
        output_root.glob(
            f"liquid-market-timeseries-momentum-v1-{protocol_sha256[:12]}-*"
        )
    )
    if matches:
        raise FileExistsError("official time-series evaluation already exists")


def evaluate(
    protocol_value: typing.Union[str, pathlib.Path],
    lock_value: typing.Union[str, pathlib.Path],
    test_value: typing.Union[str, pathlib.Path],
    snapshot_value: typing.Union[str, pathlib.Path],
    history_value: typing.Union[str, pathlib.Path],
    output_root_value: typing.Union[str, pathlib.Path],
) -> dict:
    """Run the sole frozen historical training diagnostic atomically."""

    protocol_path = pathlib.Path(protocol_value).resolve()
    protocol = _load_protocol(protocol_path)
    lock = _verify_implementation_lock(
        lock_value, protocol_path, pathlib.Path(test_value).resolve()
    )
    snapshot_root, snapshot_manifest, history_root, history_manifest, market = (
        _load_market(snapshot_value, history_value)
    )
    prepared = prepare_market(market)
    base_cache = build_signal_cache(market, prepared=prepared)
    full_with_trajectory = simulate_period(
        market,
        protocol_module.TRAINING_START,
        protocol_module.TRAINING_END,
        include_trajectory=True,
        prepared=prepared,
        signal_cache=base_cache,
    )
    full = _without_trajectory(full_with_trajectory)
    stress = simulate_period(
        market,
        protocol_module.TRAINING_START,
        protocol_module.TRAINING_END,
        cost_multiplier=protocol_module.STRESS_COST_MULTIPLIER,
        prepared=prepared,
        signal_cache=base_cache,
    )
    folds = [
        simulate_period(
            market,
            start,
            end,
            prepared=prepared,
            signal_cache=base_cache,
        )
        for start, end in protocol_module.TRAINING_FOLDS
    ]
    stress_folds = [
        simulate_period(
            market,
            start,
            end,
            cost_multiplier=protocol_module.STRESS_COST_MULTIPLIER,
            prepared=prepared,
            signal_cache=base_cache,
        )
        for start, end in protocol_module.TRAINING_FOLDS
    ]
    leave_one_symbol_out = []
    for symbol in full["ever_targeted_symbols"]:
        excluded = frozenset({symbol})
        exclusion_cache = build_signal_cache(
            market,
            excluded_symbols=excluded,
            prepared=prepared,
        )
        result = simulate_period(
            market,
            protocol_module.TRAINING_START,
            protocol_module.TRAINING_END,
            excluded_symbols=excluded,
            prepared=prepared,
            signal_cache=exclusion_cache,
        )
        leave_one_symbol_out.append(
            {"excluded_symbol": symbol, "metrics": _compact(result)}
        )
    positive_loo_ratio = (
        sum(value["metrics"]["total_return"] > 0 for value in leave_one_symbol_out)
        / len(leave_one_symbol_out)
        if leave_one_symbol_out
        else 0.0
    )
    gate = _training_gate(
        full, stress, folds, stress_folds, positive_loo_ratio
    )
    eligible = bool(gate["passed"])
    output_root = pathlib.Path(output_root_value).resolve()
    output_root.mkdir(parents=True, exist_ok=True)
    _require_no_evaluation(output_root, protocol["protocol_sha256"])
    source_sha256 = common._sha256(pathlib.Path(__file__).resolve())
    experiment_key = common._json_hash(
        {
            "protocol_sha256": protocol["protocol_sha256"],
            "implementation_lock_sha256": lock["content_sha256"],
            "source_snapshot_bundle_sha256": snapshot_manifest[
                "source_bundle_sha256"
            ],
            "history_bundle_sha256": history_manifest["history_bundle_sha256"],
            "evaluator_sha256": source_sha256,
        }
    )
    experiment = output_root / (
        "liquid-market-timeseries-momentum-v1-"
        f"{protocol['protocol_sha256'][:12]}-{experiment_key[:12]}"
    )
    temporary = pathlib.Path(
        tempfile.mkdtemp(prefix=".evaluation.", dir=str(output_root))
    )
    try:
        trajectory_path = temporary / "training-trajectory.npz"
        _write_trajectory(trajectory_path, full_with_trajectory["_trajectory"])
        report = {
            "schema_version": SCHEMA_VERSION,
            "protocol_version": protocol_module.PROTOCOL_VERSION,
            "created_at": datetime.datetime.now(UTC).isoformat(),
            "research_only": True,
            "public_data_only": True,
            "credentials_used": False,
            "orders_authorized": False,
            "paper_orders_authorized": False,
            "automatic_promotion": False,
            "protocol_sha256": protocol["protocol_sha256"],
            "protocol_file_sha256": common._sha256(protocol_path),
            "implementation_lock_content_sha256": lock["content_sha256"],
            "evaluator_sha256": source_sha256,
            "source_snapshot_path": str(snapshot_root),
            "source_snapshot_bundle_sha256": snapshot_manifest[
                "source_bundle_sha256"
            ],
            "history_path": str(history_root),
            "history_bundle_sha256": history_manifest["history_bundle_sha256"],
            "historical_status": (
                "training_only_diagnostic_reuse_current_survivor_universe"
            ),
            "training": full,
            "training_stress": stress,
            "training_folds": [_compact(value) for value in folds],
            "training_stress_folds": [
                _compact(value) for value in stress_folds
            ],
            "positive_training_folds": sum(
                value["total_return"] > 0 for value in folds
            ),
            "positive_stress_folds": sum(
                value["total_return"] > 0 for value in stress_folds
            ),
            "leave_one_symbol_out": leave_one_symbol_out,
            "positive_leave_one_symbol_out_ratio": positive_loo_ratio,
            "training_eligibility_gate": gate,
            "historical_candidate": eligible,
            "forward_validation": {
                **protocol["forward_gate"],
                "started": False,
                "passed": False,
                "automatic_promotion": False,
            },
            "training_trajectory": {
                "path": trajectory_path.name,
                "sha256": common._sha256(trajectory_path),
            },
            "verdict": (
                "TRAINING_ELIGIBLE_REQUIRES_180D_FORWARD"
                if eligible
                else "REJECTED_TRAINING_NO_FORWARD"
            ),
            "results_do_not_authorize_orders": True,
        }
        report_path = temporary / "report.json"
        common._atomic_json(report_path, report)
        manifest = {
            "schema_version": SCHEMA_VERSION,
            "protocol_sha256": protocol["protocol_sha256"],
            "experiment_key": experiment_key,
            "implementation_lock_content_sha256": lock["content_sha256"],
            "report_sha256": common._sha256(report_path),
            "trajectory_sha256": common._sha256(trajectory_path),
            "historical_candidate": eligible,
            "orders_authorized": False,
            "paper_orders_authorized": False,
            "automatic_promotion": False,
        }
        manifest["content_sha256"] = common._json_hash(manifest)
        common._atomic_json(temporary / "manifest.json", manifest)
        os.replace(temporary, experiment)
        return {"directory": str(experiment), "report": report, "manifest": manifest}
    except Exception:
        if temporary.exists():
            shutil.rmtree(temporary)
        raise


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)
    locker = subparsers.add_parser("write-lock")
    locker.add_argument("--protocol", required=True)
    locker.add_argument("--test", required=True)
    locker.add_argument("--output", required=True)
    evaluator = subparsers.add_parser("evaluate")
    evaluator.add_argument("--protocol", required=True)
    evaluator.add_argument("--lock", required=True)
    evaluator.add_argument("--test", required=True)
    evaluator.add_argument("--snapshot", required=True)
    evaluator.add_argument("--history", required=True)
    evaluator.add_argument("--output-root", required=True)
    return parser


def main(argv=None) -> int:
    args = _parser().parse_args(argv)
    if args.command == "write-lock":
        result = write_or_verify_implementation_lock(
            args.protocol, args.test, args.output
        )
        summary = {
            "status": result["status"],
            "content_sha256": result["content_sha256"],
            "economic_outcomes_read_before_lock": False,
            "orders_authorized": False,
        }
    else:
        result = evaluate(
            args.protocol,
            args.lock,
            args.test,
            args.snapshot,
            args.history,
            args.output_root,
        )
        summary = {
            "directory": result["directory"],
            "verdict": result["report"]["verdict"],
            "passed_checks": result["report"]["training_eligibility_gate"][
                "passed_checks"
            ],
            "total_checks": result["report"]["training_eligibility_gate"][
                "total_checks"
            ],
            "orders_authorized": False,
        }
    print(json.dumps(summary, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
