"""Offline trainer for frozen diversified trend/cointegration V1.

All historical rows are declared training. This module has no exchange client,
credential path, shadow target or order capability. It can select at most one
fixed capital allocation for a later orderless forward observer.
"""

from __future__ import annotations

import argparse
import bisect
import dataclasses
import datetime
import json
import math
import os
import pathlib
import shutil
import tempfile
import typing

import numpy

from octobot.ai_strategy_lab import dataset as dataset_module
from octobot.ai_strategy_lab import (
    diversified_trend_cointegration_v1 as protocol_module,
)
from octobot.ai_strategy_lab import funding as funding_module
from octobot.ai_strategy_lab import trend as trend_module
from octobot.ai_strategy_lab import cointegration_pairs_v1 as common
from octobot.ai_strategy_lab import cointegration_pairs_v2 as cointegration_protocol
from octobot.ai_strategy_lab import cointegration_pairs_v2_research as cointegration


SCHEMA_VERSION = 1
UTC = datetime.timezone.utc


class DataQualityError(ValueError):
    """Raised when a frozen input or reconstructed trajectory is invalid."""


def _load_protocol(path_value: typing.Union[str, pathlib.Path]) -> dict:
    path = pathlib.Path(path_value).resolve()
    persisted = json.loads(path.read_text(encoding="utf-8"))
    frozen = protocol_module.frozen_protocol()
    expected = {**frozen, "protocol_sha256": common._json_hash(frozen)}
    if persisted != expected:
        raise ValueError("diversified protocol is not the frozen version")
    return persisted


def _verify_file(path_value, expected_sha256: str, label: str) -> pathlib.Path:
    path = pathlib.Path(path_value).resolve()
    if not path.is_file() or common._sha256(path) != expected_sha256:
        raise DataQualityError(f"{label} file hash mismatch: {path}")
    return path


def _load_trend_component(
    report_value: typing.Union[str, pathlib.Path],
) -> tuple[dict, trend_module.TrendConfig, dict]:
    """Verify the known V13 report and rebuild its exact public daily market."""

    report_path = _verify_file(
        report_value,
        protocol_module.TREND_REPORT_SHA256,
        "trend V13 report",
    )
    report = json.loads(report_path.read_text(encoding="utf-8"))
    if (
        report.get("research_only") is not True
        or len(report.get("configs", [])) != 1
        or common._json_hash(report["inputs"])
        != protocol_module.TREND_INPUTS_SHA256
        or common._json_hash(report["configs"][0])
        != protocol_module.TREND_CONFIG_SHA256
    ):
        raise DataQualityError("trend V13 report lineage mismatch")
    _verify_file(
        trend_module.__file__,
        protocol_module.TREND_SOURCE_SHA256,
        "trend source",
    )
    futures_paths = []
    for artifact in report["inputs"]["futures_collectors"]:
        futures_paths.append(
            _verify_file(artifact["path"], artifact["sha256"], "trend future")
        )
    funding_paths = []
    for artifact in report["inputs"]["funding"]:
        funding_paths.append(
            _verify_file(artifact["path"], artifact["sha256"], "trend funding")
        )

    series = dataset_module.load_collector_series(
        futures_paths, required_time_frames=("1h",)
    )
    funding = {}
    for path in funding_paths:
        loaded = funding_module.load_funding(path)
        overlap = set(funding) & set(loaded)
        if overlap:
            raise DataQualityError(
                f"trend funding symbols overlap: {sorted(overlap)}"
            )
        funding.update(loaded)
    symbols = sorted(set(series) & set(funding))
    if symbols != report["symbols"]:
        raise DataQualityError("trend reconstructed symbols differ")
    market = trend_module._build_daily_market(
        {symbol: series[symbol]["1h"] for symbol in symbols},
        {symbol: funding[symbol] for symbol in symbols},
    )
    config = trend_module.TrendConfig(**report["configs"][0])
    config.validate()
    if config.name != "risk_budgeted_bear_regime_v13":
        raise DataQualityError("unexpected trend configuration")
    artifacts = {
        "report_path": str(report_path),
        "report_sha256": common._sha256(report_path),
        "source_sha256": common._sha256(
            pathlib.Path(trend_module.__file__).resolve()
        ),
        "futures": [
            {"path": str(path), "sha256": common._sha256(path)}
            for path in futures_paths
        ],
        "funding": [
            {"path": str(path), "sha256": common._sha256(path)}
            for path in funding_paths
        ],
    }
    return market, config, artifacts


def _load_cointegration_component(
    report_value: typing.Union[str, pathlib.Path],
    null_value: typing.Union[str, pathlib.Path],
    snapshot_value: typing.Union[str, pathlib.Path],
    history_value: typing.Union[str, pathlib.Path],
) -> tuple[dict, numpy.ndarray, dict]:
    """Verify V2 lineage and load its immutable public market and null."""

    report_path = _verify_file(
        report_value,
        protocol_module.COINTEGRATION_REPORT_SHA256,
        "cointegration V2 report",
    )
    report = json.loads(report_path.read_text(encoding="utf-8"))
    if (
        report.get("protocol_sha256")
        != protocol_module.COINTEGRATION_PROTOCOL_SHA256
        or report.get("verdict")
        != "REJECTED_DEVELOPMENT_LATER_WINDOWS_UNMATERIALIZED"
        or report.get("orders_authorized") is not False
        or report.get("paper_orders_authorized") is not False
        or report.get("confirmation") is not None
        or report.get("locked_test") is not None
    ):
        raise DataQualityError("cointegration V2 report lineage mismatch")
    _verify_file(
        cointegration.__file__,
        protocol_module.COINTEGRATION_SOURCE_SHA256,
        "cointegration source",
    )
    null_path = _verify_file(
        null_value,
        protocol_module.COINTEGRATION_NULL_SHA256,
        "cointegration null",
    )
    null = numpy.load(null_path, allow_pickle=False)
    if (
        null.shape != (cointegration_protocol.MONTE_CARLO_SIMULATIONS,)
        or numpy.any(~numpy.isfinite(null))
        or numpy.any(numpy.diff(null) < 0)
    ):
        raise DataQualityError("cointegration null is invalid")
    (
        snapshot_root,
        snapshot_manifest,
        history_root,
        history_manifest,
        market,
    ) = cointegration._load_market(snapshot_value, history_value)
    if (
        snapshot_manifest["source_bundle_sha256"]
        != protocol_module.SOURCE_SNAPSHOT_BUNDLE_SHA256
        or history_manifest["history_bundle_sha256"]
        != protocol_module.HISTORY_BUNDLE_SHA256
    ):
        raise DataQualityError("cointegration bundle lineage mismatch")
    artifacts = {
        "report_path": str(report_path),
        "report_sha256": common._sha256(report_path),
        "null_path": str(null_path),
        "null_sha256": common._sha256(null_path),
        "source_sha256": common._sha256(
            pathlib.Path(cointegration.__file__).resolve()
        ),
        "snapshot_path": str(snapshot_root),
        "source_snapshot_bundle_sha256": snapshot_manifest[
            "source_bundle_sha256"
        ],
        "history_path": str(history_root),
        "history_bundle_sha256": history_manifest["history_bundle_sha256"],
    }
    return market, null, artifacts


def _interval_indices(
    dates: list[datetime.date], start: datetime.date, end: datetime.date
) -> tuple[int, int]:
    if end <= start or any(
        right - left != datetime.timedelta(days=1)
        for left, right in zip(dates, dates[1:])
    ):
        raise DataQualityError("component calendar is invalid")
    start_index = bisect.bisect_left(dates, start)
    end_index = bisect.bisect_left(dates, end)
    if start_index >= len(dates) or dates[start_index] != start:
        raise DataQualityError(f"component interval lacks start {start}")
    if end_index < len(dates) and dates[end_index] != end:
        raise DataQualityError(f"component interval lacks end {end}")
    if end_index == len(dates) and dates[-1] + datetime.timedelta(days=1) != end:
        raise DataQualityError(f"component interval lacks exclusive end {end}")
    return start_index, end_index


def _trend_period(
    market: dict,
    config: trend_module.TrendConfig,
    start: datetime.date,
    end: datetime.date,
    cost_multiplier: float,
) -> dict:
    start_index, end_index = _interval_indices(market["dates"], start, end)
    evaluated = (
        config
        if cost_multiplier == 1.0
        else dataclasses.replace(
            config,
            name=f"{config.name}_cost_stress_{cost_multiplier:g}x",
            fee_per_turnover=config.fee_per_turnover * cost_multiplier,
            slippage_per_turnover=config.slippage_per_turnover * cost_multiplier,
        )
    )
    report = trend_module._simulate(
        market,
        evaluated,
        1.0,
        include_trajectory=True,
        evaluation_start_index=start_index,
        evaluation_end_index=end_index,
    )
    equities = numpy.asarray(report["trajectory"]["equity"], dtype=numpy.float64)
    starting_equity = numpy.concatenate((numpy.ones(1), equities))
    daily = numpy.diff(starting_equity) / starting_equity[:-1]
    report["_daily_return"] = daily
    return report


def _cointegration_period(
    market: dict,
    cache: dict[int, dict],
    start: datetime.date,
    end: datetime.date,
    cost_multiplier: float,
) -> dict:
    return cointegration.simulate_period(
        market,
        cache,
        start,
        end,
        cost_multiplier=cost_multiplier,
        include_trajectory=True,
    )


def _period_returns(
    dates: list[datetime.date], values: numpy.ndarray, pattern: str
) -> dict:
    groups: dict[str, list[float]] = {}
    for date, value in zip(dates, values):
        groups.setdefault(date.strftime(pattern), []).append(float(value))
    return {
        key: float(numpy.prod(1.0 + numpy.asarray(group)) - 1.0)
        for key, group in sorted(groups.items())
    }


def combine_trajectories(
    trend_report: dict,
    cointegration_report: dict,
    trend_weight: float,
    cointegration_weight: float,
    *,
    include_trajectory: bool = False,
) -> dict:
    """Combine independently compounded fixed initial sleeve budgets."""

    if (
        trend_weight <= 0
        or cointegration_weight <= 0
        or not math.isclose(trend_weight + cointegration_weight, 1.0)
    ):
        raise ValueError("invalid fixed sleeve allocation")
    trend_dates = trend_report["trajectory"]["dates"]
    cointegration_dates = cointegration_report["_trajectory"]["dates"]
    if trend_dates != cointegration_dates:
        raise DataQualityError("component trajectory dates differ")
    trend_daily = numpy.asarray(
        trend_report["_daily_return"], dtype=numpy.float64
    )
    cointegration_daily = numpy.asarray(
        cointegration_report["_trajectory"]["daily_return"],
        dtype=numpy.float64,
    )
    if (
        trend_daily.shape != cointegration_daily.shape
        or numpy.any(~numpy.isfinite(trend_daily))
        or numpy.any(~numpy.isfinite(cointegration_daily))
    ):
        raise DataQualityError("component daily returns are invalid")
    trend_equity = numpy.cumprod(1.0 + trend_daily)
    cointegration_equity = numpy.cumprod(1.0 + cointegration_daily)
    equity = (
        trend_weight * trend_equity
        + cointegration_weight * cointegration_equity
    )
    starting_equity = numpy.concatenate((numpy.ones(1), equity))
    daily = numpy.diff(starting_equity) / starting_equity[:-1]
    if numpy.any(equity <= 0) or numpy.any(daily <= -1.0):
        raise DataQualityError("combined equity is nonpositive")
    dates = [datetime.date.fromisoformat(value) for value in trend_dates]
    peaks = numpy.maximum.accumulate(numpy.concatenate((numpy.ones(1), equity)))[1:]
    drawdown = 1.0 - equity / peaks
    monthly = _period_returns(dates, daily, "%Y-%m")
    elapsed_years = len(daily) / 365.25
    result = {
        "start": dates[0].isoformat(),
        "end_exclusive": (dates[-1] + datetime.timedelta(days=1)).isoformat(),
        "days": len(daily),
        "trend_capital_weight": trend_weight,
        "cointegration_capital_weight": cointegration_weight,
        "total_return": float(equity[-1] - 1.0),
        "annualized_return": (
            float(equity[-1] ** (1.0 / elapsed_years) - 1.0)
            if elapsed_years > 0 and equity[-1] > 0
            else -1.0
        ),
        "sharpe_zero_rate": (
            float(numpy.mean(daily) / numpy.std(daily) * math.sqrt(365.0))
            if numpy.std(daily) > 0
            else 0.0
        ),
        "maximum_drawdown": float(numpy.max(drawdown)),
        "positive_month_ratio": (
            sum(value > 0 for value in monthly.values()) / len(monthly)
            if monthly
            else 0.0
        ),
        "months": monthly,
        "trend_additive_contribution": float(
            trend_weight * (trend_equity[-1] - 1.0)
        ),
        "cointegration_additive_contribution": float(
            cointegration_weight * (cointegration_equity[-1] - 1.0)
        ),
        "component_daily_correlation": (
            float(numpy.corrcoef(trend_daily, cointegration_daily)[0, 1])
            if numpy.std(trend_daily) > 0 and numpy.std(cointegration_daily) > 0
            else 0.0
        ),
    }
    if include_trajectory:
        result["_trajectory"] = {
            "dates": trend_dates,
            "trend_daily_return": trend_daily.tolist(),
            "cointegration_daily_return": cointegration_daily.tolist(),
            "combined_daily_return": daily.tolist(),
            "equity": equity.tolist(),
        }
    return result


def _without_trajectory(report: dict) -> dict:
    return {
        key: value
        for key, value in report.items()
        if key not in {"_trajectory", "_daily_return", "trajectory"}
    }


def _compact_component(report: dict) -> dict:
    keys = (
        "start",
        "end_exclusive",
        "evaluation_start_date",
        "evaluation_end_date",
        "days",
        "evaluation_days",
        "total_return",
        "annualized_return",
        "sharpe_zero_rate",
        "maximum_drawdown",
        "max_drawdown",
        "positive_month_ratio",
        "total_turnover",
        "total_cost_return",
        "total_funding_return",
        "average_gross_exposure",
        "closed_trades",
        "formations",
        "formations_with_pairs",
        "market_beta",
        "maximum_pair_absolute_contribution_share",
    )
    return {key: report[key] for key in keys if key in report}


def candidate_eligibility(stress: dict, stress_folds: list[dict]) -> dict:
    """Apply frozen structural training eligibility to one allocation."""

    gate = protocol_module.frozen_protocol()["training"]["eligibility"]
    fold_returns = [value["total_return"] for value in stress_folds]
    positive_folds = sum(value > 0 for value in fold_returns)
    worst_fold = min(fold_returns)
    median_fold_sharpe = float(
        numpy.median([value["sharpe_zero_rate"] for value in stress_folds])
    )
    checks = {
        "minimum_observed_days": bool(
            stress["days"] >= gate["minimum_observed_days"]
        ),
        "stress_total_return_positive": bool(stress["total_return"] > 0),
        "minimum_stress_annualized_return": bool(
            stress["annualized_return"]
            >= gate["minimum_stress_annualized_return"]
        ),
        "minimum_stress_sharpe": bool(
            stress["sharpe_zero_rate"] >= gate["minimum_stress_sharpe"]
        ),
        "maximum_stress_drawdown": bool(
            stress["maximum_drawdown"] <= gate["maximum_stress_drawdown"]
        ),
        "minimum_stress_positive_month_ratio": bool(
            stress["positive_month_ratio"]
            >= gate["minimum_stress_positive_month_ratio"]
        ),
        "minimum_positive_stress_folds": bool(
            positive_folds >= gate["minimum_positive_stress_folds"]
        ),
        "maximum_worst_stress_fold_loss": bool(
            worst_fold >= -gate["maximum_worst_stress_fold_loss"]
        ),
        "both_sleeve_additive_contributions_positive": bool(
            stress["trend_additive_contribution"] > 0
            and stress["cointegration_additive_contribution"] > 0
        ),
        "required_folds_present": bool(
            len(stress_folds) == len(protocol_module.TRAINING_FOLDS)
        ),
    }
    return {
        "checks": checks,
        "passed": bool(all(checks.values())),
        "positive_stress_folds": positive_folds,
        "worst_stress_fold_return": worst_fold,
        "median_stress_fold_sharpe": median_fold_sharpe,
    }


def select_candidate(candidates: list[dict]) -> dict | None:
    """Select exactly as preregistered, or return no model."""

    eligible = [value for value in candidates if value["eligibility"]["passed"]]
    if not eligible:
        return None
    return min(
        eligible,
        key=lambda value: (
            -value["eligibility"]["worst_stress_fold_return"],
            -value["eligibility"]["median_stress_fold_sharpe"],
            -value["stress"]["sharpe_zero_rate"],
            value["stress"]["maximum_drawdown"],
            value["configuration_id"],
        ),
    )


def _source_file_artifacts() -> list[dict]:
    paths = [
        pathlib.Path(protocol_module.__file__).resolve(),
        pathlib.Path(__file__).resolve(),
        pathlib.Path(trend_module.__file__).resolve(),
        pathlib.Path(cointegration.__file__).resolve(),
        pathlib.Path(cointegration_protocol.__file__).resolve(),
    ]
    return [
        {
            "name": path.name,
            "bytes": path.stat().st_size,
            "sha256": common._sha256(path),
        }
        for path in paths
    ]


def _require_single_run(output_root: pathlib.Path, protocol_sha256: str) -> None:
    prefix = f"diversified-trend-cointegration-v1-{protocol_sha256[:12]}-*"
    existing = sorted(output_root.glob(prefix))
    if existing:
        raise FileExistsError(
            f"official diversified training already exists: {existing[0]}"
        )


def evaluate(
    protocol_value: typing.Union[str, pathlib.Path],
    trend_report_value: typing.Union[str, pathlib.Path],
    cointegration_report_value: typing.Union[str, pathlib.Path],
    null_value: typing.Union[str, pathlib.Path],
    snapshot_value: typing.Union[str, pathlib.Path],
    history_value: typing.Union[str, pathlib.Path],
    output_root_value: typing.Union[str, pathlib.Path],
) -> dict:
    """Run the one frozen training selection without creating a forward target."""

    protocol_path = pathlib.Path(protocol_value).resolve()
    protocol = _load_protocol(protocol_path)
    output_root = pathlib.Path(output_root_value).resolve()
    output_root.mkdir(parents=True, exist_ok=True)
    _require_single_run(output_root, protocol["protocol_sha256"])
    trend_market, trend_config, trend_artifacts = _load_trend_component(
        trend_report_value
    )
    (
        cointegration_market,
        null,
        cointegration_artifacts,
    ) = _load_cointegration_component(
        cointegration_report_value,
        null_value,
        snapshot_value,
        history_value,
    )

    training_cache = cointegration.build_formation_cache(
        cointegration_market,
        protocol_module.TRAINING_START,
        protocol_module.TRAINING_END,
        null,
    )
    component_full = {}
    component_folds = []
    for cost_multiplier, label in ((1.0, "base"), (3.0, "stress")):
        trend_full = _trend_period(
            trend_market,
            trend_config,
            protocol_module.TRAINING_START,
            protocol_module.TRAINING_END,
            cost_multiplier,
        )
        cointegration_full = _cointegration_period(
            cointegration_market,
            training_cache,
            protocol_module.TRAINING_START,
            protocol_module.TRAINING_END,
            cost_multiplier,
        )
        component_full[label] = {
            "trend": trend_full,
            "cointegration": cointegration_full,
        }

    for start, end in protocol_module.TRAINING_FOLDS:
        values = {"start": start.isoformat(), "end": end.isoformat()}
        for cost_multiplier, label in ((1.0, "base"), (3.0, "stress")):
            values[label] = {
                "trend": _trend_period(
                    trend_market,
                    trend_config,
                    start,
                    end,
                    cost_multiplier,
                ),
                "cointegration": _cointegration_period(
                    cointegration_market,
                    training_cache,
                    start,
                    end,
                    cost_multiplier,
                ),
            }
        component_folds.append(values)

    candidates = []
    trajectory_candidates = {}
    for allocation in protocol_module.ALLOCATIONS:
        identifier = allocation["configuration_id"]
        trend_weight = allocation["trend_capital_weight"]
        cointegration_weight = allocation["cointegration_capital_weight"]
        base_with_trajectory = combine_trajectories(
            component_full["base"]["trend"],
            component_full["base"]["cointegration"],
            trend_weight,
            cointegration_weight,
            include_trajectory=True,
        )
        stress_with_trajectory = combine_trajectories(
            component_full["stress"]["trend"],
            component_full["stress"]["cointegration"],
            trend_weight,
            cointegration_weight,
            include_trajectory=True,
        )
        base = _without_trajectory(base_with_trajectory)
        stress = _without_trajectory(stress_with_trajectory)
        base_folds = []
        stress_folds = []
        for fold in component_folds:
            base_folds.append(
                combine_trajectories(
                    fold["base"]["trend"],
                    fold["base"]["cointegration"],
                    trend_weight,
                    cointegration_weight,
                )
            )
            stress_folds.append(
                combine_trajectories(
                    fold["stress"]["trend"],
                    fold["stress"]["cointegration"],
                    trend_weight,
                    cointegration_weight,
                )
            )
        eligibility = candidate_eligibility(stress, stress_folds)
        candidates.append(
            {
                **allocation,
                "base": base,
                "stress": stress,
                "base_folds": base_folds,
                "stress_folds": stress_folds,
                "eligibility": eligibility,
            }
        )
        trajectory_candidates[identifier] = {
            "base_combined_daily_return": base_with_trajectory["_trajectory"][
                "combined_daily_return"
            ],
            "base_equity": base_with_trajectory["_trajectory"]["equity"],
            "stress_combined_daily_return": stress_with_trajectory[
                "_trajectory"
            ]["combined_daily_return"],
            "stress_equity": stress_with_trajectory["_trajectory"]["equity"],
        }

    selected = select_candidate(candidates)
    source_files = _source_file_artifacts()
    evaluator_sha256 = next(
        value["sha256"]
        for value in source_files
        if value["name"] == pathlib.Path(__file__).name
    )
    experiment_key = common._json_hash(
        {
            "protocol_sha256": protocol["protocol_sha256"],
            "trend_report_sha256": trend_artifacts["report_sha256"],
            "cointegration_report_sha256": cointegration_artifacts[
                "report_sha256"
            ],
            "source_snapshot_bundle_sha256": cointegration_artifacts[
                "source_snapshot_bundle_sha256"
            ],
            "history_bundle_sha256": cointegration_artifacts[
                "history_bundle_sha256"
            ],
            "null_sha256": cointegration_artifacts["null_sha256"],
            "evaluator_sha256": evaluator_sha256,
        }
    )
    experiment = output_root / (
        f"diversified-trend-cointegration-v1-"
        f"{protocol['protocol_sha256'][:12]}-{experiment_key[:12]}"
    )
    temporary = pathlib.Path(
        tempfile.mkdtemp(prefix=".diversified-v1.", dir=str(output_root))
    )
    try:
        trajectory_path = temporary / "training-trajectories.json"
        first_trajectory = component_full["base"]["trend"]["trajectory"]
        common._atomic_json(
            trajectory_path,
            {
                "schema_version": SCHEMA_VERSION,
                "protocol_sha256": protocol["protocol_sha256"],
                "dates": first_trajectory["dates"],
                "component_daily_returns": {
                    "base_trend": component_full["base"]["trend"][
                        "_daily_return"
                    ].tolist(),
                    "base_cointegration": component_full["base"][
                        "cointegration"
                    ]["_trajectory"]["daily_return"],
                    "stress_trend": component_full["stress"]["trend"][
                        "_daily_return"
                    ].tolist(),
                    "stress_cointegration": component_full["stress"][
                        "cointegration"
                    ]["_trajectory"]["daily_return"],
                },
                "candidates": trajectory_candidates,
            },
        )
        selected_model = None
        selected_model_path = None
        if selected is not None:
            selected_model = {
                "schema_version": SCHEMA_VERSION,
                "protocol_sha256": protocol["protocol_sha256"],
                "training_only": True,
                "historical_pass": False,
                "forward_started": False,
                "orders_authorized": False,
                "paper_orders_authorized": False,
                "configuration_id": selected["configuration_id"],
                "trend_capital_weight": selected["trend_capital_weight"],
                "cointegration_capital_weight": selected[
                    "cointegration_capital_weight"
                ],
                "selection_statistics": {
                    "worst_stress_fold_return": selected["eligibility"][
                        "worst_stress_fold_return"
                    ],
                    "median_stress_fold_sharpe": selected["eligibility"][
                        "median_stress_fold_sharpe"
                    ],
                    "full_stress_sharpe": selected["stress"][
                        "sharpe_zero_rate"
                    ],
                    "full_stress_drawdown": selected["stress"][
                        "maximum_drawdown"
                    ],
                },
                "component_lineage": protocol["lineage"],
                "forward_gate": protocol["forward_gate"],
            }
            selected_model["content_sha256"] = common._json_hash(selected_model)
            selected_model_path = temporary / "selected-model.json"
            common._atomic_json(selected_model_path, selected_model)

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
            "protocol_path": str(protocol_path),
            "protocol_file_sha256": common._sha256(protocol_path),
            "protocol_sha256": protocol["protocol_sha256"],
            "source_files": source_files,
            "trend_artifacts": trend_artifacts,
            "cointegration_artifacts": cointegration_artifacts,
            "training": protocol["training"],
            "component_full": {
                label: {
                    name: _compact_component(value)
                    for name, value in components.items()
                }
                for label, components in component_full.items()
            },
            "candidates": candidates,
            "eligible_configurations": [
                value["configuration_id"]
                for value in candidates
                if value["eligibility"]["passed"]
            ],
            "selected_configuration_id": (
                selected["configuration_id"] if selected else None
            ),
            "selected_model": (
                {
                    "path": selected_model_path.name,
                    "sha256": common._sha256(selected_model_path),
                    "content_sha256": selected_model["content_sha256"],
                }
                if selected_model_path is not None
                else None
            ),
            "training_trajectories": {
                "path": trajectory_path.name,
                "sha256": common._sha256(trajectory_path),
            },
            "historical_status": (
                "training_only_all_component_outcomes_previously_observed"
            ),
            "historical_pass": False,
            "forward_validation": {
                **protocol["forward_gate"],
                "started": False,
                "passed": False,
                "automatic_promotion": False,
            },
            "verdict": (
                "TRAINING_MODEL_SELECTED_REQUIRES_180D_FORWARD"
                if selected is not None
                else "REJECTED_TRAINING_NO_ELIGIBLE_ALLOCATION"
            ),
            "results_do_not_authorize_orders": True,
        }
        report_path = temporary / "report.json"
        common._atomic_json(report_path, report)
        manifest = {
            "schema_version": SCHEMA_VERSION,
            "protocol_sha256": protocol["protocol_sha256"],
            "experiment_key": experiment_key,
            "report_sha256": common._sha256(report_path),
            "trajectory_sha256": common._sha256(trajectory_path),
            "selected_model_sha256": (
                common._sha256(selected_model_path)
                if selected_model_path is not None
                else None
            ),
            "selected_configuration_id": (
                selected["configuration_id"] if selected else None
            ),
            "historical_pass": False,
            "forward_started": False,
            "orders_authorized": False,
            "paper_orders_authorized": False,
            "automatic_promotion": False,
        }
        manifest["content_sha256"] = common._json_hash(manifest)
        common._atomic_json(temporary / "manifest.json", manifest)
        if experiment.exists():
            raise FileExistsError(f"official training exists: {experiment}")
        os.replace(temporary, experiment)
        return {
            "directory": str(experiment),
            "report": report,
            "manifest": manifest,
        }
    except Exception:
        if temporary.exists():
            shutil.rmtree(temporary)
        raise


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--protocol", required=True)
    parser.add_argument("--trend-report", required=True)
    parser.add_argument("--cointegration-report", required=True)
    parser.add_argument("--cointegration-null", required=True)
    parser.add_argument("--snapshot", required=True)
    parser.add_argument("--history", required=True)
    parser.add_argument("--output-root", required=True)
    return parser


def main(argv=None) -> int:
    args = _parser().parse_args(argv)
    result = evaluate(
        args.protocol,
        args.trend_report,
        args.cointegration_report,
        args.cointegration_null,
        args.snapshot,
        args.history,
        args.output_root,
    )
    report = result["report"]
    summary = {
        "directory": result["directory"],
        "verdict": report["verdict"],
        "eligible_configurations": report["eligible_configurations"],
        "selected_configuration_id": report["selected_configuration_id"],
        "report_sha256": result["manifest"]["report_sha256"],
        "orders_authorized": False,
    }
    print(json.dumps(common._json_safe(summary), indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
