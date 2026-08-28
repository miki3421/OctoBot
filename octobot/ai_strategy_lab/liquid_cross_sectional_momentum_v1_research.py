"""Offline evaluator for frozen liquid cross-sectional momentum V1.

The evaluator reuses one immutable public Binance daily/funding panel.  It is
research-only, has no network or exchange client, and can produce exactly one
training diagnostic.  Historical results cannot authorize any order.
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

from octobot.ai_strategy_lab import category_momentum_v1_research as source
from octobot.ai_strategy_lab import cointegration_pairs_v1 as common
from octobot.ai_strategy_lab import cointegration_pairs_v2_research as market_source
from octobot.ai_strategy_lab import (
    liquid_cross_sectional_momentum_v1 as protocol_module,
)


SCHEMA_VERSION = 1
UTC = datetime.timezone.utc


class DataQualityError(ValueError):
    """Raised when frozen inputs or a simulated outcome are invalid."""


def _load_protocol(path_value: typing.Union[str, pathlib.Path]) -> dict:
    path = pathlib.Path(path_value).resolve()
    persisted = json.loads(path.read_text(encoding="utf-8"))
    frozen = protocol_module.frozen_protocol()
    expected = {**frozen, "protocol_sha256": common._json_hash(frozen)}
    if persisted != expected:
        raise ValueError("cross-sectional momentum protocol is not frozen")
    return persisted


def _load_market(
    snapshot_value: typing.Union[str, pathlib.Path],
    history_value: typing.Union[str, pathlib.Path],
) -> tuple[pathlib.Path, dict, pathlib.Path, dict, dict]:
    loaded = market_source._load_market(snapshot_value, history_value)
    snapshot_root, snapshot_manifest, history_root, history_manifest, market = loaded
    if (
        snapshot_manifest.get("source_bundle_sha256")
        != protocol_module.SOURCE_SNAPSHOT_BUNDLE_SHA256
        or snapshot_manifest.get("content_sha256")
        != protocol_module.SOURCE_SNAPSHOT_MANIFEST_CONTENT_SHA256
        or history_manifest.get("history_bundle_sha256")
        != protocol_module.HISTORY_BUNDLE_SHA256
        or history_manifest.get("content_sha256")
        != protocol_module.HISTORY_MANIFEST_CONTENT_SHA256
        or common._sha256(history_root / "market-panel.npz")
        != protocol_module.MARKET_PANEL_SHA256
    ):
        raise DataQualityError("cross-sectional momentum input lineage differs")
    if len(market["symbols"]) != protocol_module.UNIVERSE_ASSETS:
        raise DataQualityError("cross-sectional momentum universe size differs")
    return loaded


def _source_artifacts(test_path: pathlib.Path) -> list[dict]:
    values = (
        ("evaluator", pathlib.Path(__file__).resolve()),
        ("protocol", pathlib.Path(protocol_module.__file__).resolve()),
        ("test", test_path.resolve()),
        ("market_loader", pathlib.Path(market_source.__file__).resolve()),
        ("frozen_source_loader", pathlib.Path(source.__file__).resolve()),
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
    """Freeze evaluator and dependency hashes before economic evaluation."""

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
            protocol_module.SOURCE_SNAPSHOT_BUNDLE_SHA256
        ),
        "history_bundle_sha256": protocol_module.HISTORY_BUNDLE_SHA256,
        "market_panel_sha256": protocol_module.MARKET_PANEL_SHA256,
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
        == protocol_module.SOURCE_SNAPSHOT_BUNDLE_SHA256,
        lock.get("history_bundle_sha256")
        == protocol_module.HISTORY_BUNDLE_SHA256,
        lock.get("market_panel_sha256") == protocol_module.MARKET_PANEL_SHA256,
        lock.get("economic_outcomes_read_before_lock") is False,
        lock.get("results_existing_before_lock") is False,
        lock.get("research_only") is True,
        lock.get("credentials_used") is False,
        lock.get("orders_authorized") is False,
        lock.get("paper_orders_authorized") is False,
        lock.get("automatic_promotion") is False,
        lock.get("numpy_version") == numpy.__version__,
    )
    if not all(checks):
        raise DataQualityError("implementation lock metadata differs")
    expected = _source_artifacts(test_path)
    if lock.get("source_artifacts") != expected:
        raise DataQualityError("implementation source hashes differ")
    return lock


def _eligible_columns(
    market: dict,
    index: int,
    excluded_symbols: typing.AbstractSet[str] = frozenset(),
) -> list[int]:
    required = protocol_module.MINIMUM_CONTIGUOUS_HISTORY_DAYS
    if index + 1 < required:
        return []
    closes = numpy.asarray(market["closes"], dtype=numpy.float64)
    window = closes[index - required + 1 : index + 1]
    eligible = numpy.all(numpy.isfinite(window) & (window > 0), axis=0)
    symbols = market["symbols"]
    return [
        int(column)
        for column in numpy.flatnonzero(eligible)
        if symbols[int(column)] not in excluded_symbols
    ]


def target_weights(
    market: dict,
    index: int,
    *,
    excluded_symbols: typing.AbstractSet[str] = frozenset(),
) -> tuple[numpy.ndarray, dict]:
    """Build one causal Monday target from completed data at ``index``."""

    date = market["dates"][index]
    if date.weekday() != 0:
        raise ValueError("cross-sectional target requires a Monday boundary")
    symbols = market["symbols"]
    target = numpy.zeros(len(symbols), dtype=numpy.float64)
    eligible = _eligible_columns(market, index, excluded_symbols)
    if len(eligible) < protocol_module.MINIMUM_ELIGIBLE_ASSETS:
        return target, {
            "status": "INSUFFICIENT_ELIGIBLE_ASSETS",
            "date": date.isoformat(),
            "eligible_assets": len(eligible),
            "tail_assets": 0,
            "long_symbols": [],
            "short_symbols": [],
        }
    closes = numpy.asarray(market["closes"], dtype=numpy.float64)
    formation_index = index - protocol_module.FORMATION_DAYS
    scores = {
        column: float(closes[index, column] / closes[formation_index, column] - 1.0)
        for column in eligible
    }
    count = max(1, math.floor(len(eligible) * protocol_module.TAIL_FRACTION))
    longs = sorted(eligible, key=lambda value: (-scores[value], symbols[value]))[
        :count
    ]
    long_set = set(longs)
    shorts = sorted(
        (value for value in eligible if value not in long_set),
        key=lambda value: (scores[value], symbols[value]),
    )[:count]
    target[longs] = protocol_module.SIDE_GROSS_EXPOSURE / len(longs)
    target[shorts] = -protocol_module.SIDE_GROSS_EXPOSURE / len(shorts)
    if not numpy.isclose(numpy.sum(target), 0.0, atol=1e-12):
        raise RuntimeError("cross-sectional momentum target is not neutral")
    if not numpy.isclose(
        numpy.sum(numpy.abs(target)),
        2 * protocol_module.SIDE_GROSS_EXPOSURE,
        atol=1e-12,
    ):
        raise RuntimeError("cross-sectional momentum target gross differs")
    return target, {
        "status": "TARGET",
        "date": date.isoformat(),
        "eligible_assets": len(eligible),
        "tail_assets": count,
        "long_symbols": [symbols[value] for value in longs],
        "short_symbols": [symbols[value] for value in shorts],
        "long_scores": [scores[value] for value in longs],
        "short_scores": [scores[value] for value in shorts],
    }


def _side_transaction_costs(
    previous: numpy.ndarray,
    target: numpy.ndarray,
    cost_rate: float,
) -> tuple[float, float]:
    long_cost = 0.0
    short_cost = 0.0
    for old, new in zip(previous, target):
        if old >= 0 and new >= 0:
            long_cost += abs(new - old) * cost_rate
        elif old <= 0 and new <= 0:
            short_cost += abs(new - old) * cost_rate
        else:
            if old > 0:
                long_cost += abs(old) * cost_rate
            elif old < 0:
                short_cost += abs(old) * cost_rate
            if new > 0:
                long_cost += abs(new) * cost_rate
            elif new < 0:
                short_cost += abs(new) * cost_rate
    return long_cost, short_cost


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


def simulate_period(
    market: dict,
    start: datetime.datetime,
    end: datetime.datetime,
    *,
    cost_multiplier: float = 1.0,
    excluded_symbols: typing.AbstractSet[str] = frozenset(),
    include_trajectory: bool = False,
) -> dict:
    """Simulate a half-open interval, independently opened and closed flat."""

    if end <= start or cost_multiplier < 1.0:
        raise ValueError("invalid momentum simulation interval or cost")
    start_date, end_date = start.date(), end.date()
    dates = market["dates"]
    indices = [
        index
        for index in range(len(dates) - 1)
        if dates[index] >= start_date and dates[index + 1] <= end_date
    ]
    if not indices:
        raise DataQualityError("momentum evaluation interval is absent")
    symbols = market["symbols"]
    previous = numpy.zeros(len(symbols), dtype=numpy.float64)
    target = previous.copy()
    cost_rate = cost_multiplier * (
        protocol_module.FEE_PER_TURNOVER
        + protocol_module.SLIPPAGE_PER_TURNOVER
    )
    daily_returns = []
    market_returns = []
    outcome_dates = []
    gross_exposure = []
    eligible_assets = []
    targets = []
    symbol_contributions = numpy.zeros(len(symbols), dtype=numpy.float64)
    total_price = total_funding = total_cost = total_turnover = 0.0
    long_contribution = short_contribution = 0.0
    invested_days = rebalances = active_rebalances = 0
    ever_targeted = set()

    for index in indices:
        if dates[index].weekday() == 0:
            target, audit = target_weights(
                market, index, excluded_symbols=excluded_symbols
            )
            rebalances += 1
            active_rebalances += int(audit["status"] == "TARGET")
            eligible_assets.append(audit["eligible_assets"])
        targeted = numpy.flatnonzero(numpy.abs(target) > 1e-15)
        if len(targeted) and (
            not numpy.all(market["return_complete"][index + 1, targeted])
            or not numpy.all(market["funding_counts"][index + 1, targeted] > 0)
            or not numpy.all(numpy.isfinite(market["funding"][index + 1, targeted]))
        ):
            raise DataQualityError("active momentum target has incomplete outcome")
        returns = numpy.asarray(market["returns"][index + 1], dtype=numpy.float64)
        price = target * returns
        funding = -target * market["funding"][index + 1]
        delta = target - previous
        cost = numpy.abs(delta) * cost_rate
        contribution = price + funding - cost
        net = float(numpy.sum(contribution))
        if not math.isfinite(net) or net <= -1.0:
            raise DataQualityError("invalid momentum portfolio return")
        daily_returns.append(net)
        complete = market["return_complete"][index + 1]
        market_returns.append(
            float(numpy.mean(returns[complete])) if numpy.any(complete) else 0.0
        )
        outcome_dates.append(dates[index + 1])
        gross = float(numpy.sum(numpy.abs(target)))
        gross_exposure.append(gross)
        invested_days += int(gross > 1e-15)
        symbol_contributions += contribution
        total_price += float(numpy.sum(price))
        total_funding += float(numpy.sum(funding))
        total_cost += float(numpy.sum(cost))
        total_turnover += float(numpy.sum(numpy.abs(delta)))
        long_cost, short_cost = _side_transaction_costs(previous, target, cost_rate)
        long_contribution += float(numpy.sum((price + funding)[target > 0]))
        long_contribution -= long_cost
        short_contribution += float(numpy.sum((price + funding)[target < 0]))
        short_contribution -= short_cost
        ever_targeted.update(symbols[value] for value in targeted)
        previous = target.copy()
        if include_trajectory:
            targets.append(target.copy())

    closing_cost = numpy.abs(previous) * cost_rate
    daily_returns[-1] -= float(numpy.sum(closing_cost))
    symbol_contributions -= closing_cost
    total_cost += float(numpy.sum(closing_cost))
    total_turnover += float(numpy.sum(numpy.abs(previous)))
    long_contribution -= float(numpy.sum(closing_cost[previous > 0]))
    short_contribution -= float(numpy.sum(closing_cost[previous < 0]))

    daily = numpy.asarray(daily_returns, dtype=numpy.float64)
    benchmark = numpy.asarray(market_returns, dtype=numpy.float64)
    equity = numpy.cumprod(1.0 + daily)
    peaks = numpy.maximum.accumulate(numpy.concatenate((numpy.ones(1), equity)))[1:]
    drawdown = 1.0 - equity / peaks
    gains = float(numpy.sum(daily[daily > 0]))
    losses = float(-numpy.sum(daily[daily < 0]))
    variance = float(numpy.var(benchmark))
    beta = (
        float(
            numpy.mean(
                (daily - numpy.mean(daily))
                * (benchmark - numpy.mean(benchmark))
            )
        )
        / variance
        if variance > 0
        else 0.0
    )
    monthly = _period_compound_returns(outcome_dates, daily, "%Y-%m")
    denominator = float(numpy.sum(numpy.abs(symbol_contributions)))
    report = {
        "start": start.isoformat(),
        "end": end.isoformat(),
        "outcomes": len(daily),
        "invested_days": invested_days,
        "rebalances": rebalances,
        "active_rebalances": active_rebalances,
        "cost_multiplier": cost_multiplier,
        "total_return": float(equity[-1] - 1.0),
        "annualized_return": float(equity[-1] ** (365.25 / len(daily)) - 1.0),
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
        "market_beta": beta,
        "price_additive_contribution": total_price,
        "funding_additive_contribution": total_funding,
        "cost_additive_contribution": total_cost,
        "long_additive_contribution": long_contribution,
        "short_additive_contribution": short_contribution,
        "total_turnover": total_turnover,
        "average_gross_exposure": float(numpy.mean(gross_exposure)),
        "maximum_gross_exposure": float(numpy.max(gross_exposure)),
        "minimum_eligible_assets_at_rebalance": min(eligible_assets, default=0),
        "maximum_eligible_assets_at_rebalance": max(eligible_assets, default=0),
        "maximum_symbol_absolute_contribution_share": (
            float(numpy.max(numpy.abs(symbol_contributions)) / denominator)
            if denominator > 0
            else 0.0
        ),
        "symbol_additive_contributions": {
            symbol: float(symbol_contributions[index])
            for index, symbol in enumerate(symbols)
            if abs(symbol_contributions[index]) > 1e-15
        },
        "ever_targeted_symbols": sorted(ever_targeted),
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
            "market_return": benchmark,
            "equity": equity,
            "gross_exposure": numpy.asarray(gross_exposure, dtype=numpy.float64),
            "targets": numpy.asarray(targets, dtype=numpy.float64),
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
        "rebalances",
        "long_additive_contribution",
        "short_additive_contribution",
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
        "minimum_invested_days": (
            report["invested_days"] >= gate["minimum_invested_days"]
        ),
        "minimum_rebalances": report["rebalances"] >= gate["minimum_rebalances"],
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
        "maximum_drawdown": report["maximum_drawdown"] <= gate["maximum_drawdown"],
        "maximum_stress_drawdown": (
            stress["maximum_drawdown"] <= gate["maximum_stress_drawdown"]
        ),
        "minimum_positive_month_ratio": (
            report["positive_month_ratio"] >= gate["minimum_positive_month_ratio"]
        ),
        "minimum_positive_folds": (
            sum(value["total_return"] > 0 for value in folds)
            >= gate["minimum_positive_folds"]
        ),
        "required_folds": len(folds) == len(stress_folds) == gate["required_folds"],
        "minimum_worst_stress_fold_return": (
            min(value["total_return"] for value in stress_folds)
            >= gate["minimum_worst_stress_fold_return"]
        ),
        "both_side_contributions_nonnegative": (
            report["long_additive_contribution"] >= 0
            and report["short_additive_contribution"] >= 0
        ),
        "stress_both_side_contributions_nonnegative": (
            stress["long_additive_contribution"] >= 0
            and stress["short_additive_contribution"] >= 0
        ),
        "maximum_absolute_market_beta": (
            abs(report["market_beta"]) <= gate["maximum_absolute_market_beta"]
        ),
        "maximum_symbol_absolute_contribution_share": (
            report["maximum_symbol_absolute_contribution_share"]
            <= gate["maximum_symbol_absolute_contribution_share"]
        ),
        "minimum_positive_leave_one_symbol_out_ratio": (
            positive_loo_ratio
            >= gate["minimum_positive_leave_one_symbol_out_ratio"]
        ),
    }
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
            f"liquid-cross-sectional-momentum-v1-{protocol_sha256[:12]}-*"
        )
    )
    if matches:
        raise FileExistsError("official momentum training evaluation already exists")


def evaluate(
    protocol_value: typing.Union[str, pathlib.Path],
    lock_value: typing.Union[str, pathlib.Path],
    test_value: typing.Union[str, pathlib.Path],
    snapshot_value: typing.Union[str, pathlib.Path],
    history_value: typing.Union[str, pathlib.Path],
    output_root_value: typing.Union[str, pathlib.Path],
) -> dict:
    """Run the sole frozen training diagnostic and persist it atomically."""

    protocol_path = pathlib.Path(protocol_value).resolve()
    protocol = _load_protocol(protocol_path)
    lock = _verify_implementation_lock(
        lock_value, protocol_path, pathlib.Path(test_value).resolve()
    )
    snapshot_root, snapshot_manifest, history_root, history_manifest, market = (
        _load_market(snapshot_value, history_value)
    )
    full_with_trajectory = simulate_period(
        market,
        protocol_module.TRAINING_START,
        protocol_module.TRAINING_END,
        include_trajectory=True,
    )
    full = _without_trajectory(full_with_trajectory)
    stress = simulate_period(
        market,
        protocol_module.TRAINING_START,
        protocol_module.TRAINING_END,
        cost_multiplier=protocol_module.STRESS_COST_MULTIPLIER,
    )
    folds = [
        simulate_period(market, start, end)
        for start, end in protocol_module.TRAINING_FOLDS
    ]
    stress_folds = [
        simulate_period(
            market,
            start,
            end,
            cost_multiplier=protocol_module.STRESS_COST_MULTIPLIER,
        )
        for start, end in protocol_module.TRAINING_FOLDS
    ]
    leave_one_symbol_out = []
    for symbol in full["ever_targeted_symbols"]:
        result = simulate_period(
            market,
            protocol_module.TRAINING_START,
            protocol_module.TRAINING_END,
            excluded_symbols={symbol},
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
        f"liquid-cross-sectional-momentum-v1-{protocol['protocol_sha256'][:12]}-"
        f"{experiment_key[:12]}"
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
            "training_stress_folds": [_compact(value) for value in stress_folds],
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
