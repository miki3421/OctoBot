"""Offline evaluator for frozen winner-basket versus BTC momentum V2.

The parent V1 result is verified as training information.  V2 then evaluates
one previously unmeasured fixed BTC hedge against the unchanged winner basket.
The module is offline, research-only and has no order capability.
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
from octobot.ai_strategy_lab import winner_btc_hedged_momentum_v2 as protocol_module


SCHEMA_VERSION = 1
UTC = datetime.timezone.utc


class DataQualityError(ValueError):
    """Raised when frozen lineage, market data or accounting is invalid."""


def _load_protocol(path_value: typing.Union[str, pathlib.Path]) -> dict:
    path = pathlib.Path(path_value).resolve()
    persisted = json.loads(path.read_text(encoding="utf-8"))
    frozen = protocol_module.frozen_protocol()
    expected = {**frozen, "protocol_sha256": common._json_hash(frozen)}
    if persisted != expected:
        raise ValueError("winner/BTC momentum V2 protocol is not frozen")
    return persisted


def _verify_parent(parent_value: typing.Union[str, pathlib.Path]) -> dict:
    root = pathlib.Path(parent_value).resolve()
    report_path = root / "report.json"
    trajectory_path = root / "training-trajectory.npz"
    manifest_path = root / "manifest.json"
    if (
        not report_path.is_file()
        or common._sha256(report_path) != protocol_module.PARENT_REPORT_SHA256
        or not trajectory_path.is_file()
        or common._sha256(trajectory_path)
        != protocol_module.PARENT_TRAJECTORY_SHA256
        or not manifest_path.is_file()
    ):
        raise DataQualityError("parent V1 artifacts differ")
    report = json.loads(report_path.read_text(encoding="utf-8"))
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    content = {
        key: value for key, value in manifest.items() if key != "content_sha256"
    }
    checks = (
        report.get("protocol_sha256") == protocol_module.PARENT_PROTOCOL_SHA256,
        report.get("verdict") == "REJECTED_TRAINING_NO_FORWARD",
        report.get("historical_candidate") is False,
        report.get("orders_authorized") is False,
        report.get("paper_orders_authorized") is False,
        report.get("training_eligibility_gate", {}).get("passed") is False,
        manifest.get("content_sha256")
        == protocol_module.PARENT_MANIFEST_CONTENT_SHA256,
        manifest.get("content_sha256") == common._json_hash(content),
        manifest.get("historical_candidate") is False,
        manifest.get("report_sha256") == protocol_module.PARENT_REPORT_SHA256,
        manifest.get("trajectory_sha256")
        == protocol_module.PARENT_TRAJECTORY_SHA256,
    )
    if not all(checks):
        raise DataQualityError("parent V1 lineage differs")
    return {
        "root": str(root),
        "report_sha256": common._sha256(report_path),
        "trajectory_sha256": common._sha256(trajectory_path),
        "manifest_file_sha256": common._sha256(manifest_path),
        "manifest_content_sha256": manifest["content_sha256"],
    }


def _source_artifacts(test_path: pathlib.Path) -> list[dict]:
    values = (
        ("evaluator", pathlib.Path(__file__).resolve()),
        ("protocol", pathlib.Path(protocol_module.__file__).resolve()),
        ("test", test_path.resolve()),
        ("parent_evaluator", pathlib.Path(parent_research.__file__).resolve()),
    )
    artifacts = []
    for label, path in values:
        if not path.is_file():
            raise DataQualityError(f"V2 implementation artifact absent: {label}")
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
    parent_value: typing.Union[str, pathlib.Path],
    test_value: typing.Union[str, pathlib.Path],
    output_value: typing.Union[str, pathlib.Path],
) -> dict:
    """Freeze V2 code and parent evidence before reading V2 outcomes."""

    protocol_path = pathlib.Path(protocol_value).resolve()
    protocol = _load_protocol(protocol_path)
    parent = _verify_parent(parent_value)
    test_path = pathlib.Path(test_value).resolve()
    output = pathlib.Path(output_value).resolve()
    if output.is_file():
        return _verify_implementation_lock(
            output, protocol_path, pathlib.Path(parent_value), test_path
        )
    payload = {
        "schema_version": SCHEMA_VERSION,
        "protocol_version": protocol_module.PROTOCOL_VERSION,
        "created_at": datetime.datetime.now(UTC).isoformat(),
        "status": "implementation_frozen_before_v2_outcomes",
        "protocol_sha256": protocol["protocol_sha256"],
        "protocol_file_sha256": common._sha256(protocol_path),
        "parent_evidence": parent,
        "source_snapshot_bundle_sha256": (
            protocol_module.parent.SOURCE_SNAPSHOT_BUNDLE_SHA256
        ),
        "history_bundle_sha256": protocol_module.parent.HISTORY_BUNDLE_SHA256,
        "market_panel_sha256": protocol_module.parent.MARKET_PANEL_SHA256,
        "source_artifacts": _source_artifacts(test_path),
        "numpy_version": numpy.__version__,
        "v2_economic_outcomes_read_before_lock": False,
        "v2_results_existing_before_lock": False,
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
    parent_path: pathlib.Path,
    test_path: pathlib.Path,
) -> dict:
    lock_path = pathlib.Path(lock_value).resolve()
    lock = json.loads(lock_path.read_text(encoding="utf-8"))
    content = {key: value for key, value in lock.items() if key != "content_sha256"}
    checks = (
        lock.get("content_sha256") == common._json_hash(content),
        lock.get("status") == "implementation_frozen_before_v2_outcomes",
        lock.get("protocol_sha256")
        == common._json_hash(protocol_module.frozen_protocol()),
        lock.get("protocol_file_sha256") == common._sha256(protocol_path),
        lock.get("parent_evidence") == _verify_parent(parent_path),
        lock.get("source_snapshot_bundle_sha256")
        == protocol_module.parent.SOURCE_SNAPSHOT_BUNDLE_SHA256,
        lock.get("history_bundle_sha256")
        == protocol_module.parent.HISTORY_BUNDLE_SHA256,
        lock.get("market_panel_sha256")
        == protocol_module.parent.MARKET_PANEL_SHA256,
        lock.get("source_artifacts") == _source_artifacts(test_path),
        lock.get("numpy_version") == numpy.__version__,
        lock.get("v2_economic_outcomes_read_before_lock") is False,
        lock.get("v2_results_existing_before_lock") is False,
        lock.get("research_only") is True,
        lock.get("credentials_used") is False,
        lock.get("orders_authorized") is False,
        lock.get("paper_orders_authorized") is False,
        lock.get("automatic_promotion") is False,
    )
    if not all(checks):
        raise DataQualityError("V2 implementation lock differs")
    return lock


def target_weights(
    market: dict,
    index: int,
    *,
    excluded_winner_symbols: typing.AbstractSet[str] = frozenset(),
) -> tuple[numpy.ndarray, dict]:
    """Build one causal winner basket plus the fixed BTC short hedge."""

    date = market["dates"][index]
    if date.weekday() != 0:
        raise ValueError("winner/BTC target requires a Monday boundary")
    symbols = market["symbols"]
    try:
        btc_column = symbols.index(protocol_module.HEDGE_SYMBOL)
    except ValueError as error:
        raise DataQualityError("frozen market lacks BTC hedge") from error
    eligible = parent_research._eligible_columns(
        market, index, excluded_winner_symbols
    )
    target = numpy.zeros(len(symbols), dtype=numpy.float64)
    if (
        len(eligible) < protocol_module.parent.MINIMUM_ELIGIBLE_ASSETS
        or btc_column not in eligible
    ):
        return target, {
            "status": "INSUFFICIENT_ELIGIBLE_ASSETS_OR_BTC",
            "date": date.isoformat(),
            "eligible_assets": len(eligible),
            "winner_assets": 0,
            "winner_symbols": [],
            "btc_column": btc_column,
            "btc_post_net_weight": 0.0,
        }
    closes = numpy.asarray(market["closes"], dtype=numpy.float64)
    formation_index = index - protocol_module.parent.FORMATION_DAYS
    scores = {
        column: float(closes[index, column] / closes[formation_index, column] - 1.0)
        for column in eligible
    }
    count = max(
        1,
        math.floor(len(eligible) * protocol_module.parent.TAIL_FRACTION),
    )
    winners = sorted(
        eligible, key=lambda value: (-scores[value], symbols[value])
    )[:count]
    target[winners] += protocol_module.parent.SIDE_GROSS_EXPOSURE / len(winners)
    target[btc_column] -= protocol_module.parent.SIDE_GROSS_EXPOSURE
    gross = float(numpy.sum(numpy.abs(target)))
    if not numpy.isclose(numpy.sum(target), 0.0, atol=1e-12):
        raise RuntimeError("winner/BTC target is not nominally neutral")
    if gross > 2 * protocol_module.parent.SIDE_GROSS_EXPOSURE + 1e-12:
        raise RuntimeError("winner/BTC target exceeds gross cap")
    return target, {
        "status": "TARGET",
        "date": date.isoformat(),
        "eligible_assets": len(eligible),
        "winner_assets": count,
        "winner_symbols": [symbols[value] for value in winners],
        "winner_scores": [scores[value] for value in winners],
        "btc_column": btc_column,
        "btc_is_winner": btc_column in winners,
        "btc_post_net_weight": float(target[btc_column]),
        "post_net_gross": gross,
    }


def simulate_period(
    market: dict,
    start: datetime.datetime,
    end: datetime.datetime,
    *,
    cost_multiplier: float = 1.0,
    excluded_winner_symbols: typing.AbstractSet[str] = frozenset(),
    include_trajectory: bool = False,
) -> dict:
    """Simulate one independent half-open interval from flat to flat."""

    if end <= start or cost_multiplier < 1.0:
        raise ValueError("invalid V2 simulation interval or cost")
    dates = market["dates"]
    start_date, end_date = start.date(), end.date()
    indices = [
        index
        for index in range(len(dates) - 1)
        if dates[index] >= start_date and dates[index + 1] <= end_date
    ]
    if not indices:
        raise DataQualityError("V2 evaluation interval is absent")
    symbols = market["symbols"]
    btc_column = symbols.index(protocol_module.HEDGE_SYMBOL)
    previous = numpy.zeros(len(symbols), dtype=numpy.float64)
    target = previous.copy()
    cost_rate = cost_multiplier * (
        protocol_module.parent.FEE_PER_TURNOVER
        + protocol_module.parent.SLIPPAGE_PER_TURNOVER
    )
    daily_returns = []
    market_returns = []
    outcome_dates = []
    gross_exposure = []
    targets = []
    symbol_contributions = numpy.zeros(len(symbols), dtype=numpy.float64)
    total_price = total_funding = total_cost = total_turnover = 0.0
    invested_days = btc_hedged_days = rebalances = active_rebalances = 0
    ever_winners = set()
    minimum_eligible = math.inf
    maximum_eligible = 0

    for index in indices:
        if dates[index].weekday() == 0:
            target, audit = target_weights(
                market,
                index,
                excluded_winner_symbols=excluded_winner_symbols,
            )
            rebalances += 1
            active_rebalances += int(audit["status"] == "TARGET")
            minimum_eligible = min(minimum_eligible, audit["eligible_assets"])
            maximum_eligible = max(maximum_eligible, audit["eligible_assets"])
            ever_winners.update(audit["winner_symbols"])
        targeted = numpy.flatnonzero(numpy.abs(target) > 1e-15)
        if len(targeted) and (
            not numpy.all(market["return_complete"][index + 1, targeted])
            or not numpy.all(market["funding_counts"][index + 1, targeted] > 0)
            or not numpy.all(numpy.isfinite(market["funding"][index + 1, targeted]))
        ):
            raise DataQualityError("active V2 target has incomplete outcome")
        returns = numpy.asarray(market["returns"][index + 1], dtype=numpy.float64)
        price = target * returns
        funding = -target * market["funding"][index + 1]
        delta = target - previous
        cost = numpy.abs(delta) * cost_rate
        contribution = price + funding - cost
        net = float(numpy.sum(contribution))
        if not math.isfinite(net) or net <= -1.0:
            raise DataQualityError("invalid V2 portfolio return")
        daily_returns.append(net)
        complete = market["return_complete"][index + 1]
        market_returns.append(
            float(numpy.mean(returns[complete])) if numpy.any(complete) else 0.0
        )
        outcome_dates.append(dates[index + 1])
        gross = float(numpy.sum(numpy.abs(target)))
        gross_exposure.append(gross)
        invested_days += int(gross > 1e-15)
        btc_hedged_days += int(target[btc_column] < -1e-15)
        symbol_contributions += contribution
        total_price += float(numpy.sum(price))
        total_funding += float(numpy.sum(funding))
        total_cost += float(numpy.sum(cost))
        total_turnover += float(numpy.sum(numpy.abs(delta)))
        previous = target.copy()
        if include_trajectory:
            targets.append(target.copy())

    closing_cost = numpy.abs(previous) * cost_rate
    daily_returns[-1] -= float(numpy.sum(closing_cost))
    symbol_contributions -= closing_cost
    total_cost += float(numpy.sum(closing_cost))
    total_turnover += float(numpy.sum(numpy.abs(previous)))

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
    monthly = parent_research._period_compound_returns(
        outcome_dates, daily, "%Y-%m"
    )
    absolute_contributions = numpy.abs(symbol_contributions)
    denominator = float(numpy.sum(absolute_contributions))
    non_hedge = numpy.delete(absolute_contributions, btc_column)
    report = {
        "start": start.isoformat(),
        "end": end.isoformat(),
        "outcomes": len(daily),
        "invested_days": invested_days,
        "btc_hedged_days": btc_hedged_days,
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
        "gross_edge_additive_contribution": total_price + total_funding,
        "cost_additive_contribution": total_cost,
        "total_turnover": total_turnover,
        "average_gross_exposure": float(numpy.mean(gross_exposure)),
        "maximum_gross_exposure": float(numpy.max(gross_exposure)),
        "minimum_eligible_assets_at_rebalance": (
            int(minimum_eligible) if math.isfinite(minimum_eligible) else 0
        ),
        "maximum_eligible_assets_at_rebalance": maximum_eligible,
        "btc_additive_contribution": float(symbol_contributions[btc_column]),
        "btc_absolute_contribution_share": (
            float(absolute_contributions[btc_column] / denominator)
            if denominator > 0
            else 0.0
        ),
        "maximum_non_hedge_symbol_absolute_contribution_share": (
            float(numpy.max(non_hedge) / denominator)
            if denominator > 0 and len(non_hedge)
            else 0.0
        ),
        "symbol_additive_contributions": {
            symbol: float(symbol_contributions[index])
            for index, symbol in enumerate(symbols)
            if abs(symbol_contributions[index]) > 1e-15
        },
        "ever_winner_symbols": sorted(ever_winners),
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
        "btc_hedged_days",
        "rebalances",
        "gross_edge_additive_contribution",
        "cost_additive_contribution",
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
        "minimum_btc_hedged_days": (
            report["btc_hedged_days"] >= gate["minimum_btc_hedged_days"]
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
        "minimum_positive_stress_folds": (
            sum(value["total_return"] > 0 for value in stress_folds)
            >= gate["minimum_positive_stress_folds"]
        ),
        "required_folds": len(folds) == len(stress_folds) == gate["required_folds"],
        "minimum_worst_stress_fold_return": (
            min(value["total_return"] for value in stress_folds)
            >= gate["minimum_worst_stress_fold_return"]
        ),
        "combined_gross_edge_exceeds_costs": (
            report["gross_edge_additive_contribution"]
            > report["cost_additive_contribution"]
        ),
        "stress_combined_gross_edge_exceeds_costs": (
            stress["gross_edge_additive_contribution"]
            > stress["cost_additive_contribution"]
        ),
        "maximum_absolute_market_beta": (
            abs(report["market_beta"]) <= gate["maximum_absolute_market_beta"]
        ),
        "maximum_non_hedge_symbol_absolute_contribution_share": (
            report["maximum_non_hedge_symbol_absolute_contribution_share"]
            <= gate["maximum_non_hedge_symbol_absolute_contribution_share"]
        ),
        "maximum_btc_absolute_contribution_share": (
            report["btc_absolute_contribution_share"]
            <= gate["maximum_btc_absolute_contribution_share"]
        ),
        "minimum_positive_leave_one_winner_symbol_out_ratio": (
            positive_loo_ratio
            >= gate["minimum_positive_leave_one_winner_symbol_out_ratio"]
        ),
        "maximum_total_turnover": (
            report["total_turnover"] <= gate["maximum_total_turnover"]
        ),
        "maximum_post_net_gross": (
            report["maximum_gross_exposure"] <= gate["maximum_post_net_gross"]
        ),
    }
    return {
        "checks": checks,
        "passed_checks": sum(bool(value) for value in checks.values()),
        "total_checks": len(checks),
        "passed": all(checks.values()),
    }


def _require_no_evaluation(output_root: pathlib.Path, protocol_sha256: str) -> None:
    if list(
        output_root.glob(
            f"winner-btc-hedged-momentum-v2-{protocol_sha256[:12]}-*"
        )
    ):
        raise FileExistsError("official winner/BTC V2 evaluation already exists")


def evaluate(
    protocol_value: typing.Union[str, pathlib.Path],
    lock_value: typing.Union[str, pathlib.Path],
    parent_value: typing.Union[str, pathlib.Path],
    test_value: typing.Union[str, pathlib.Path],
    snapshot_value: typing.Union[str, pathlib.Path],
    history_value: typing.Union[str, pathlib.Path],
    output_root_value: typing.Union[str, pathlib.Path],
) -> dict:
    """Run and atomically persist the only frozen V2 training evaluation."""

    protocol_path = pathlib.Path(protocol_value).resolve()
    protocol = _load_protocol(protocol_path)
    parent_path = pathlib.Path(parent_value).resolve()
    test_path = pathlib.Path(test_value).resolve()
    lock = _verify_implementation_lock(
        lock_value, protocol_path, parent_path, test_path
    )
    snapshot_root, snapshot_manifest, history_root, history_manifest, market = (
        parent_research._load_market(snapshot_value, history_value)
    )
    full_with_trajectory = simulate_period(
        market,
        protocol_module.parent.TRAINING_START,
        protocol_module.parent.TRAINING_END,
        include_trajectory=True,
    )
    full = _without_trajectory(full_with_trajectory)
    stress = simulate_period(
        market,
        protocol_module.parent.TRAINING_START,
        protocol_module.parent.TRAINING_END,
        cost_multiplier=protocol_module.parent.STRESS_COST_MULTIPLIER,
    )
    folds = [
        simulate_period(market, start, end)
        for start, end in protocol_module.parent.TRAINING_FOLDS
    ]
    stress_folds = [
        simulate_period(
            market,
            start,
            end,
            cost_multiplier=protocol_module.parent.STRESS_COST_MULTIPLIER,
        )
        for start, end in protocol_module.parent.TRAINING_FOLDS
    ]
    leave_one_winner_out = []
    for symbol in full["ever_winner_symbols"]:
        if symbol == protocol_module.HEDGE_SYMBOL:
            continue
        result = simulate_period(
            market,
            protocol_module.parent.TRAINING_START,
            protocol_module.parent.TRAINING_END,
            excluded_winner_symbols={symbol},
        )
        leave_one_winner_out.append(
            {"excluded_winner_symbol": symbol, "metrics": _compact(result)}
        )
    positive_loo_ratio = (
        sum(value["metrics"]["total_return"] > 0 for value in leave_one_winner_out)
        / len(leave_one_winner_out)
        if leave_one_winner_out
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
            "parent_report_sha256": protocol_module.PARENT_REPORT_SHA256,
            "source_snapshot_bundle_sha256": snapshot_manifest[
                "source_bundle_sha256"
            ],
            "history_bundle_sha256": history_manifest["history_bundle_sha256"],
            "evaluator_sha256": source_sha256,
        }
    )
    experiment = output_root / (
        f"winner-btc-hedged-momentum-v2-{protocol['protocol_sha256'][:12]}-"
        f"{experiment_key[:12]}"
    )
    temporary = pathlib.Path(
        tempfile.mkdtemp(prefix=".evaluation.", dir=str(output_root))
    )
    try:
        trajectory_path = temporary / "training-trajectory.npz"
        parent_research._write_trajectory(
            trajectory_path, full_with_trajectory["_trajectory"]
        )
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
            "parent_v1": _verify_parent(parent_path),
            "source_snapshot_path": str(snapshot_root),
            "source_snapshot_bundle_sha256": snapshot_manifest[
                "source_bundle_sha256"
            ],
            "history_path": str(history_root),
            "history_bundle_sha256": history_manifest["history_bundle_sha256"],
            "historical_status": (
                "training_only_after_parent_v1_current_survivor_universe"
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
            "leave_one_winner_symbol_out": leave_one_winner_out,
            "positive_leave_one_winner_symbol_out_ratio": positive_loo_ratio,
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
            "parent_report_sha256": protocol_module.PARENT_REPORT_SHA256,
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
    locker.add_argument("--parent", required=True)
    locker.add_argument("--test", required=True)
    locker.add_argument("--output", required=True)
    evaluator = subparsers.add_parser("evaluate")
    evaluator.add_argument("--protocol", required=True)
    evaluator.add_argument("--lock", required=True)
    evaluator.add_argument("--parent", required=True)
    evaluator.add_argument("--test", required=True)
    evaluator.add_argument("--snapshot", required=True)
    evaluator.add_argument("--history", required=True)
    evaluator.add_argument("--output-root", required=True)
    return parser


def main(argv=None) -> int:
    args = _parser().parse_args(argv)
    if args.command == "write-lock":
        result = write_or_verify_implementation_lock(
            args.protocol, args.parent, args.test, args.output
        )
        summary = {
            "status": result["status"],
            "content_sha256": result["content_sha256"],
            "v2_economic_outcomes_read_before_lock": False,
            "orders_authorized": False,
        }
    else:
        result = evaluate(
            args.protocol,
            args.lock,
            args.parent,
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
