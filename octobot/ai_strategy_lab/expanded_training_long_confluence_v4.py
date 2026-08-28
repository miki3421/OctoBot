"""Frozen expanded-training long confluence V4 protocol.

V4 treats July 2022 through December 2025 as training, selects one of exactly
16 cost-aware candidates, and reserves January through June 2026 as its only
historical OOS query.  This initial module persists only the result-free
protocol and cannot create orders.
"""

from __future__ import annotations

import argparse
import datetime
import json
import math
import pathlib
import statistics
import typing

import numpy

from octobot.ai_strategy_lab import cointegration_pairs_v1 as common
from octobot.ai_strategy_lab import cost_aware_long_confluence_v2 as engine


SCHEMA_VERSION = 1
PROTOCOL_VERSION = "crypto_perpetual_expanded_training_long_confluence_v4"
PREREGISTRATION_DATE = "2026-08-28"
TRAINING_START = datetime.datetime(2022, 7, 1, tzinfo=datetime.timezone.utc)
TRAINING_END = datetime.datetime(2026, 1, 1, tzinfo=datetime.timezone.utc)
OOS_START = datetime.datetime(2026, 1, 1, tzinfo=datetime.timezone.utc)
OOS_END = datetime.datetime(2026, 7, 1, tzinfo=datetime.timezone.utc)
TRAINING_FOLDS = tuple(
    (
        datetime.datetime(year, month, 1, tzinfo=datetime.timezone.utc),
        (
            datetime.datetime(year + 1, 1, 1, tzinfo=datetime.timezone.utc)
            if month == 7
            else datetime.datetime(year, 7, 1, tzinfo=datetime.timezone.utc)
        ),
    )
    for year, month in (
        (2022, 7),
        (2023, 1),
        (2023, 7),
        (2024, 1),
        (2024, 7),
        (2025, 1),
        (2025, 7),
    )
)
REBALANCE_BLOCKS = (3, 9, 21, 42)
REGIMES = (
    "always_on",
    "ew_28d_positive",
    "ew_84d_positive",
    "ew_28d_and_84d_positive",
)
REGIME_28D_BLOCKS = 28 * 3
REGIME_84D_BLOCKS = 84 * 3
FORWARD_START_UTC = "2026-08-29T00:00:00+00:00"
EXPECTED_V3_REPORT_SHA256 = (
    "977836cacc3c17c006cfac0b65bb804abb406870b94efe83c3d6e27fe573ee6b"
)


def candidate_configurations() -> list[dict]:
    return [
        {
            "configuration_id": f"r{blocks}-{regime}",
            "rebalance_blocks": blocks,
            "rebalance_hours": blocks * 8,
            "regime": regime,
        }
        for blocks in REBALANCE_BLOCKS
        for regime in REGIMES
    ]


def frozen_protocol() -> dict:
    return {
        "schema_version": SCHEMA_VERSION,
        "protocol_version": PROTOCOL_VERSION,
        "preregistered_on": PREREGISTRATION_DATE,
        "status": "expanded_training_pre_2026_oos",
        "research_only": True,
        "public_data_only": True,
        "credentials_used": False,
        "orders_authorized": False,
        "paper_orders_authorized": False,
        "automatic_promotion": False,
        "lineage": {
            "v3_2025_result_is_training_information": True,
            "v3_report_sha256": (
                "977836cacc3c17c006cfac0b65bb804abb406870b94efe83c3d6e27fe573ee6b"
            ),
            "2025_is_oos_for_v4": False,
            "first_and_only_v4_oos": "2026-01-01 through 2026-07-01",
            "other_models_may_query_2026": False,
        },
        "signal": {
            "entry": "unchanged long three-factor confluence",
            "maximum_assets": engine.MAXIMUM_ASSETS,
            "portfolio_gross_exposure": engine.PORTFOLIO_GROSS_EXPOSURE,
            "weighting": "equal weight",
            "spot_is_signal_only": True,
            "completed_blocks_only": True,
            "early_exit": False,
            "stops_or_take_profit": False,
            "additional_features": False,
        },
        "training_grid": {
            "configurations": candidate_configurations(),
            "configuration_count": len(candidate_configurations()),
            "rebalance_anchor_utc": engine.REBALANCE_ANCHOR_UTC,
            "target_between_boundaries": "unchanged",
            "regimes": {
                "always_on": "no market gate",
                "ew_28d_positive": (
                    "equal-weight 84-block cumulative return strictly positive"
                ),
                "ew_84d_positive": (
                    "equal-weight 252-block cumulative return strictly positive"
                ),
                "ew_28d_and_84d_positive": (
                    "both 84-block and 252-block conditions strictly positive"
                ),
            },
            "regime_28d_blocks": REGIME_28D_BLOCKS,
            "regime_84d_blocks": REGIME_84D_BLOCKS,
            "other_configurations": False,
        },
        "data_quality_policy": {
            "reuse_checksummed_parent_inputs": True,
            "common_completed_blocks_only": True,
            "interpolation_or_forward_fill": False,
            "return_across_gap": False,
            "signal_after_gap": "flat until 21 intervals are contiguous",
            "regime_after_gap": (
                "filtered targets remain flat until their full lookback is contiguous"
            ),
            "gap_boundary": "flatten and reopen with explicit cost",
        },
        "economics": {
            "traded_instrument": "perpetual only",
            "fee_per_turnover": engine.FEE_PER_TURNOVER,
            "slippage_per_turnover": engine.SLIPPAGE_PER_TURNOVER,
            "stress_cost_multiplier": engine.STRESS_COST_MULTIPLIER,
            "cost_on_netted_weight_change": True,
            "maker_fill_assumptions": False,
            "cost_reduction_relative_to_v3": False,
        },
        "metric_definition": {
            "annualized_market_alpha": (
                "mean(strategy_block_return-beta*equal_weight_market_"
                "block_return)*1095"
            ),
            "beta": "population covariance divided by population variance",
            "zero_risk_free_rate": True,
        },
        "training": {
            "period": [TRAINING_START.isoformat(), TRAINING_END.isoformat()],
            "status": "training_only_including_observed_2025",
            "folds": [
                [start.isoformat(), end.isoformat()]
                for start, end in TRAINING_FOLDS
            ],
            "eligibility": {
                "minimum_invested_blocks": 400,
                "minimum_invested_blocks_per_fold": 30,
                "required_folds": len(TRAINING_FOLDS),
                "all_metrics_finite": True,
            },
            "selection": {
                "eligible_candidates_only": True,
                "order": [
                    "maximum positive 3x-cost folds",
                    "maximum minimum 3x-cost fold total return",
                    "maximum median 3x-cost fold Sharpe",
                    "maximum full-training base annualized market alpha",
                    "minimum full-training base turnover",
                    "lexicographically smallest configuration_id",
                ],
                "selection_count": 1,
                "selection_is_economic_pass": False,
            },
        },
        "oos_test": {
            "period": [OOS_START.isoformat(), OOS_END.isoformat()],
            "status": "sealed_single_query",
            "gate": {
                "minimum_blocks": 500,
                "minimum_invested_blocks": 100,
                "positive_total_return": True,
                "stress_total_return_positive": True,
                "minimum_annualized_return": 0.04,
                "minimum_annualized_market_alpha": 0.04,
                "minimum_sharpe": 0.50,
                "minimum_profit_factor": 1.05,
                "maximum_drawdown": 0.20,
                "minimum_positive_month_ratio": 0.50,
                "maximum_absolute_market_beta": 0.50,
                "maximum_symbol_absolute_contribution_share": 0.50,
            },
            "failed_model_replacement": False,
        },
        "forward_gate": {
            "start_utc": FORWARD_START_UTC,
            "minimum_calendar_days": 180,
            "minimum_observed_blocks": 500,
            "no_refit": True,
            "same_frozen_model_and_costs": True,
            "required_before_shadow_or_paper": True,
        },
        "multiple_testing_disclosure": (
            "16 expanded-training candidates; one frozen winner may query "
            "January-June 2026 once"
        ),
        "promotion_consequence": (
            "an OOS pass creates only a forward candidate; no shadow, paper "
            "or real order is authorized"
        ),
        "results": None,
    }


def write_or_verify_protocol(
    path_value: typing.Union[str, pathlib.Path],
) -> dict:
    path = pathlib.Path(path_value).resolve()
    protocol = frozen_protocol()
    payload = {**protocol, "protocol_sha256": common._json_hash(protocol)}
    if path.is_file():
        persisted = json.loads(path.read_text(encoding="utf-8"))
        if persisted != payload:
            raise ValueError("persisted expanded-training V4 protocol differs")
        return persisted
    common._atomic_json(path, payload)
    return payload


def _artifact(path: pathlib.Path) -> dict:
    return {
        "path": str(path),
        "bytes": path.stat().st_size,
        "sha256": common._sha256(path),
    }


def _market_regime_is_positive(market: dict, index: int, blocks: int) -> bool:
    if index < blocks:
        return False
    if (
        int(market["timestamps"][index])
        - int(market["timestamps"][index - blocks])
        != blocks * engine.BLOCK_SECONDS
    ):
        return False
    cumulative = market["closes"][index] / market["closes"][index - blocks] - 1.0
    return bool(numpy.mean(cumulative) > 0.0)


def _regime_passes(market: dict, index: int, regime: str) -> bool:
    if regime == "always_on":
        return True
    short = _market_regime_is_positive(market, index, REGIME_28D_BLOCKS)
    if regime == "ew_28d_positive":
        return short
    long = _market_regime_is_positive(market, index, REGIME_84D_BLOCKS)
    if regime == "ew_84d_positive":
        return long
    if regime == "ew_28d_and_84d_positive":
        return short and long
    raise ValueError("unknown V4 regime")


def build_target_matrix(market: dict, configuration: dict) -> numpy.ndarray:
    if configuration not in candidate_configurations():
        raise ValueError("configuration is outside the frozen V4 grid")
    targets = numpy.zeros(
        (len(market["timestamps"]), len(market["symbols"])),
        dtype=numpy.float64,
    )
    current = numpy.zeros(len(market["symbols"]), dtype=numpy.float64)
    previous_timestamp = None
    for index, timestamp_value in enumerate(market["timestamps"]):
        timestamp = int(timestamp_value)
        if (
            previous_timestamp is not None
            and timestamp - previous_timestamp != engine.BLOCK_SECONDS
        ):
            current = numpy.zeros_like(current)
        if engine._is_rebalance_boundary(
            timestamp, configuration["rebalance_blocks"]
        ):
            if index >= engine.FORMATION_BLOCKS and _regime_passes(
                market, index, configuration["regime"]
            ):
                current = engine.long_target_from_features(
                    *engine.parent.signal_values(market, index),
                    market["symbols"],
                )
            else:
                current = numpy.zeros_like(current)
        targets[index] = current
        previous_timestamp = timestamp
    gross = numpy.sum(numpy.abs(targets), axis=1)
    net = numpy.sum(targets, axis=1)
    if numpy.any(gross > engine.PORTFOLIO_GROSS_EXPOSURE + 1e-12):
        raise ValueError("V4 target exceeds frozen gross")
    if numpy.any(net < -1e-12) or numpy.any(numpy.abs(net - gross) > 1e-12):
        raise ValueError("V4 target contains a short exposure")
    return targets


def _finite_report(report: dict) -> bool:
    values = (
        report["total_return"],
        report["annualized_return"],
        report["annualized_market_alpha"],
        report["sharpe_zero_rate"],
        report["maximum_drawdown"],
        report["market_beta"],
        report["maximum_symbol_absolute_contribution_share"],
        report["total_turnover"],
    )
    return all(math.isfinite(float(value)) for value in values)


def _eligibility(
    development: dict,
    base_folds: list[dict],
    stress_folds: list[dict],
    specification: dict,
) -> dict:
    checks = {
        "minimum_invested_blocks": (
            development["invested_blocks"]
            >= specification["minimum_invested_blocks"]
        ),
        "minimum_invested_blocks_per_fold": all(
            fold["invested_blocks"]
            >= specification["minimum_invested_blocks_per_fold"]
            for fold in base_folds
        ),
        "required_base_folds_present": (
            len(base_folds) == specification["required_folds"]
        ),
        "required_stress_folds_present": (
            len(stress_folds) == specification["required_folds"]
        ),
        "all_metrics_finite": all(
            _finite_report(report)
            for report in [development, *base_folds, *stress_folds]
        ),
    }
    return {
        "checks": checks,
        "passed_checks": sum(checks.values()),
        "total_checks": len(checks),
        "passed": all(checks.values()),
    }


def _selection_values(candidate: dict) -> dict:
    stress_folds = candidate["stress_folds"]
    return {
        "positive_stress_folds": sum(
            fold["total_return"] > 0 for fold in stress_folds
        ),
        "minimum_stress_fold_total_return": min(
            fold["total_return"] for fold in stress_folds
        ),
        "median_stress_fold_sharpe": statistics.median(
            fold["sharpe_zero_rate"] for fold in stress_folds
        ),
        "full_training_annualized_market_alpha": candidate["development"][
            "annualized_market_alpha"
        ],
        "full_training_turnover": candidate["development"]["total_turnover"],
        "configuration_id": candidate["configuration"]["configuration_id"],
    }


def select_candidate(candidates: list[dict]) -> dict:
    eligible = [
        candidate for candidate in candidates if candidate["eligibility"]["passed"]
    ]
    if not eligible:
        raise ValueError("no structurally eligible V4 training candidate")
    for candidate in eligible:
        candidate["selection_values"] = _selection_values(candidate)
    return sorted(
        eligible,
        key=lambda candidate: (
            -candidate["selection_values"]["positive_stress_folds"],
            -candidate["selection_values"][
                "minimum_stress_fold_total_return"
            ],
            -candidate["selection_values"]["median_stress_fold_sharpe"],
            -candidate["selection_values"][
                "full_training_annualized_market_alpha"
            ],
            candidate["selection_values"]["full_training_turnover"],
            candidate["selection_values"]["configuration_id"],
        ),
    )[0]


def train_and_freeze(
    protocol_value,
    v3_report_value,
    futures_values,
    spot_values,
    flow_manifest_values,
    flow_cache_value,
    funding_values,
    output_root_value,
) -> dict:
    """Run expanded training only and freeze exactly one selected model."""

    protocol_path = pathlib.Path(protocol_value).resolve()
    protocol = write_or_verify_protocol(protocol_path)
    v3_report_path = pathlib.Path(v3_report_value).resolve()
    if common._sha256(v3_report_path) != EXPECTED_V3_REPORT_SHA256:
        raise ValueError("V3 report lineage hash differs")
    market, artifacts = engine.parent.load_market(
        futures_values,
        spot_values,
        flow_manifest_values,
        flow_cache_value,
        funding_values,
    )
    dependencies = {
        "v2_training_engine": pathlib.Path(engine.__file__).resolve(),
        "confluence_market_loader": pathlib.Path(engine.parent.__file__).resolve(),
        "accounting": pathlib.Path(
            engine.parent.parent.execution_parent.__file__
        ).resolve(),
    }
    artifacts["trainer"] = _artifact(pathlib.Path(__file__).resolve())
    artifacts["dependencies"] = {
        name: _artifact(path) for name, path in sorted(dependencies.items())
    }
    artifacts["v3_training_lineage"] = _artifact(v3_report_path)
    artifacts["frozen_protocol"] = _artifact(protocol_path)
    source_bundle_sha256 = common._json_hash(artifacts)

    candidate_reports = []
    trajectories = {}
    for configuration in candidate_configurations():
        targets = build_target_matrix(market, configuration)
        development = engine.simulate_period(
            market,
            TRAINING_START,
            TRAINING_END,
            target_matrix=targets,
            include_trajectory=True,
        )
        trajectories[configuration["configuration_id"]] = development.pop(
            "_trajectory"
        )
        stress = engine.simulate_period(
            market,
            TRAINING_START,
            TRAINING_END,
            target_matrix=targets,
            cost_multiplier=engine.STRESS_COST_MULTIPLIER,
        )
        base_folds = [
            engine.simulate_period(market, start, end, target_matrix=targets)
            for start, end in TRAINING_FOLDS
        ]
        stress_folds = [
            engine.simulate_period(
                market,
                start,
                end,
                target_matrix=targets,
                cost_multiplier=engine.STRESS_COST_MULTIPLIER,
            )
            for start, end in TRAINING_FOLDS
        ]
        eligibility = _eligibility(
            development,
            base_folds,
            stress_folds,
            protocol["training"]["eligibility"],
        )
        candidate_reports.append(
            {
                "configuration": configuration,
                "development": development,
                "stress": stress,
                "base_folds": base_folds,
                "stress_folds": stress_folds,
                "eligibility": eligibility,
            }
        )
    selected = select_candidate(candidate_reports)
    candidate_summary_sha256 = common._json_hash(candidate_reports)

    output_root = pathlib.Path(output_root_value).resolve()
    experiment = output_root / (
        "expanded-training-long-confluence-v4-"
        + protocol["protocol_sha256"][:12]
        + "-"
        + source_bundle_sha256[:12]
    )
    experiment.mkdir(parents=True, exist_ok=False)
    trajectories_path = experiment / "training-trajectories.json"
    common._atomic_json(
        trajectories_path,
        {
            "schema_version": SCHEMA_VERSION,
            "protocol_sha256": protocol["protocol_sha256"],
            "source_bundle_sha256": source_bundle_sha256,
            "maximum_outcome_utc": TRAINING_END.isoformat(),
            "configurations": trajectories,
        },
    )
    model_path = experiment / "selected-model.json"
    model = {
        "schema_version": SCHEMA_VERSION,
        "protocol_sha256": protocol["protocol_sha256"],
        "source_bundle_sha256": source_bundle_sha256,
        "candidate_summary_sha256": candidate_summary_sha256,
        "selected_configuration": selected["configuration"],
        "selection_values": selected["selection_values"],
        "maximum_training_outcome_utc": TRAINING_END.isoformat(),
        "training_is_promotional_evidence": False,
        "oos_2026_evaluated": False,
        "orders_authorized": False,
        "paper_orders_authorized": False,
        "automatic_promotion": False,
    }
    model["content_sha256"] = common._json_hash(model)
    common._atomic_json(model_path, model)
    report = {
        "schema_version": SCHEMA_VERSION,
        "protocol_version": PROTOCOL_VERSION,
        "created_at": datetime.datetime.now(engine.parent.parent.UTC).isoformat(),
        "research_only": True,
        "public_data_only": True,
        "credentials_used": False,
        "orders_authorized": False,
        "paper_orders_authorized": False,
        "automatic_promotion": False,
        "training_only": True,
        "maximum_outcome_utc": TRAINING_END.isoformat(),
        "oos_2026_evaluated": False,
        "protocol_path": str(protocol_path),
        "protocol_file_sha256": common._sha256(protocol_path),
        "protocol_sha256": protocol["protocol_sha256"],
        "source_bundle_sha256": source_bundle_sha256,
        "source_artifacts": artifacts,
        "candidates": candidate_reports,
        "candidate_summary_sha256": candidate_summary_sha256,
        "eligible_candidate_count": sum(
            candidate["eligibility"]["passed"] for candidate in candidate_reports
        ),
        "selected_configuration": selected["configuration"],
        "selection_values": selected["selection_values"],
        "selected_model_path": str(model_path),
        "selected_model_sha256": common._sha256(model_path),
        "selected_model_content_sha256": model["content_sha256"],
        "training_trajectories": {
            "path": str(trajectories_path),
            "sha256": common._sha256(trajectories_path),
        },
        "oos_access_authorized": True,
        "verdict": "ONE_TRAINING_MODEL_FROZEN_2026_OOS_AUTHORIZED",
        "results_do_not_authorize_orders": True,
    }
    report_path = experiment / "training-report.json"
    common._atomic_json(report_path, report)
    manifest = {
        "schema_version": SCHEMA_VERSION,
        "protocol_sha256": protocol["protocol_sha256"],
        "source_bundle_sha256": source_bundle_sha256,
        "report_path": str(report_path),
        "report_sha256": common._sha256(report_path),
        "training_trajectories_path": str(trajectories_path),
        "training_trajectories_sha256": common._sha256(trajectories_path),
        "selected_model_path": str(model_path),
        "selected_model_sha256": common._sha256(model_path),
        "oos_2026_evaluated": False,
        "orders_authorized": False,
        "paper_orders_authorized": False,
        "automatic_promotion": False,
    }
    manifest["content_sha256"] = common._json_hash(manifest)
    common._atomic_json(experiment / "manifest.json", manifest)
    return {
        "directory": str(experiment),
        "report": report,
        "manifest": manifest,
    }


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)
    write = subparsers.add_parser("write-protocol")
    write.add_argument("--output", required=True)
    train = subparsers.add_parser("train-and-freeze")
    train.add_argument("--protocol", required=True)
    train.add_argument("--v3-report", required=True)
    train.add_argument("--futures-collector", action="append", required=True)
    train.add_argument("--spot-collector", action="append", required=True)
    train.add_argument("--flow-manifest", action="append", required=True)
    train.add_argument("--flow-cache", required=True)
    train.add_argument("--funding", action="append", required=True)
    train.add_argument("--output-root", required=True)
    return parser


def main(argv=None) -> int:
    arguments = _parser().parse_args(argv)
    if arguments.command == "write-protocol":
        print(json.dumps(write_or_verify_protocol(arguments.output), indent=2))
        return 0
    print(
        json.dumps(
            train_and_freeze(
                arguments.protocol,
                arguments.v3_report,
                arguments.futures_collector,
                arguments.spot_collector,
                arguments.flow_manifest,
                arguments.flow_cache,
                arguments.funding,
                arguments.output_root,
            ),
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
