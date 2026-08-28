"""Frozen cost-aware long confluence design protocol V2.

Development is explicitly training data.  This initial module can only persist
the result-free six-candidate design protocol; it cannot evaluate outcomes or
create orders.
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
from octobot.ai_strategy_lab import relative_value_confluence_v1 as parent


SCHEMA_VERSION = 1
PROTOCOL_VERSION = "crypto_perpetual_cost_aware_long_confluence_v2"
PREREGISTRATION_DATE = "2026-08-28"
EXPECTED_SYMBOLS = parent.EXPECTED_SYMBOLS
BLOCK_SECONDS = parent.BLOCK_SECONDS
FORMATION_BLOCKS = parent.FORMATION_BLOCKS
REGIME_BLOCKS = 28 * 3
REBALANCE_ANCHOR_UTC = "2022-05-02T00:00:00+00:00"
REBALANCE_BLOCKS = (3, 9, 21)
REGIMES = ("always_on", "ew_market_28d_positive")
MAXIMUM_ASSETS = 3
PORTFOLIO_GROSS_EXPOSURE = parent.SIDE_GROSS_EXPOSURE
FEE_PER_TURNOVER = parent.FEE_PER_TURNOVER
SLIPPAGE_PER_TURNOVER = parent.SLIPPAGE_PER_TURNOVER
STRESS_COST_MULTIPLIER = parent.STRESS_COST_MULTIPLIER
DEVELOPMENT_START = parent.DEVELOPMENT_START
DEVELOPMENT_END = parent.DEVELOPMENT_END
CONFIRMATION_START = parent.CONFIRMATION_START
CONFIRMATION_END = parent.CONFIRMATION_END
LOCKED_START = parent.LOCKED_START
LOCKED_END = parent.LOCKED_END
DEVELOPMENT_FOLDS = parent.DEVELOPMENT_FOLDS
CONFIRMATION_QUARTERS = parent.CONFIRMATION_QUARTERS
FORWARD_START_UTC = "2026-08-29T00:00:00+00:00"
EXPECTED_METRIC_ADDENDUM_SHA256 = (
    "8d49c9f22305eec4aa6aa0db275e36f24effc5fd151343752ebd1e2e3ff34660"
)
ANNUAL_BLOCKS = 3 * 365


def candidate_configurations() -> list[dict]:
    """Return the complete, deterministically ordered training grid."""

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
    """Return the only allowed result-free V2 training/OOS specification."""

    return {
        "schema_version": SCHEMA_VERSION,
        "protocol_version": PROTOCOL_VERSION,
        "preregistered_on": PREREGISTRATION_DATE,
        "status": "result_free_training_and_oos_protocol",
        "research_only": True,
        "public_data_only": True,
        "credentials_used": False,
        "orders_authorized": False,
        "paper_orders_authorized": False,
        "automatic_promotion": False,
        "design_disclosure": {
            "parent_family": parent.PROTOCOL_VERSION,
            "parent_result_used_for_design": (
                "development cost-allocated long contribution was positive "
                "while the short contribution was strongly negative"
            ),
            "development_is_evidence": False,
            "first_promotional_evidence": "sealed calendar year 2025",
            "long_only_is_post_parent_design": True,
            "short_variant_in_v2": None,
        },
        "hypothesis": {
            "name": "cost_aware_long_relative_value_confluence",
            "statement": (
                "slow scheduled reselection can retain the documented long "
                "confluence while raising gross edge per unit turnover"
            ),
            "economic_mechanism": (
                "spot/perpetual convergence confirmed by persistent relative "
                "path and aggressive flow, with turnover controlled by design"
            ),
            "long_only": True,
            "opposite_direction_tested": False,
        },
        "entry_signal": {
            "identical_to_parent_long_intersection": True,
            "log_basis": "bottom cross-sectional third",
            "basis_momentum_7d": "top cross-sectional third",
            "signed_flow_7d": "top cross-sectional third",
            "all_three_required": True,
            "maximum_assets": MAXIMUM_ASSETS,
            "weighting": "equal weight among selected assets",
            "portfolio_gross_exposure": PORTFOLIO_GROSS_EXPOSURE,
            "spot_is_signal_only": True,
            "completed_blocks_only": True,
        },
        "training_grid": {
            "configurations": candidate_configurations(),
            "configuration_count": len(candidate_configurations()),
            "rebalance_anchor_utc": REBALANCE_ANCHOR_UTC,
            "rebalance_policy": (
                "select only on anchored boundaries and keep the target "
                "unchanged until the next boundary"
            ),
            "regime_policy": {
                "always_on": "no market-direction gate",
                "ew_market_28d_positive": (
                    "new target allowed only when the equal-weight cumulative "
                    "return of all 18 perpetuals over the preceding 84 "
                    "contiguous blocks is strictly positive"
                ),
            },
            "regime_blocks": REGIME_BLOCKS,
            "early_exit": False,
            "stops_or_take_profit": False,
            "learned_numeric_thresholds": False,
            "additional_features": False,
            "other_configurations": False,
        },
        "data_quality_policy": {
            "reuse_parent_checksummed_inputs": True,
            "common_completed_blocks_only": True,
            "interpolation_or_forward_fill": False,
            "return_across_gap": False,
            "signal_formation_after_gap": (
                "flat until the 21 confluence intervals are contiguous"
            ),
            "regime_formation_after_gap": (
                "the filtered candidates remain flat until 84 market "
                "intervals are contiguous"
            ),
            "gap_boundary": (
                "flatten prior segment with cost and reopen the next segment "
                "from flat with cost"
            ),
        },
        "economics": {
            "traded_instrument": "perpetual only",
            "price_pnl": "next eight-hour perpetual close-to-close return",
            "funding_pnl": (
                "negative target weight times actual signed next settlement"
            ),
            "fee_per_turnover": FEE_PER_TURNOVER,
            "slippage_per_turnover": SLIPPAGE_PER_TURNOVER,
            "stress_cost_multiplier": STRESS_COST_MULTIPLIER,
            "cost_on_netted_weight_change": True,
            "maker_fill_assumptions": False,
            "cost_reduction_relative_to_parent": False,
        },
        "training": {
            "period": [
                DEVELOPMENT_START.isoformat(),
                DEVELOPMENT_END.isoformat(),
            ],
            "status": "training_reuse_not_promotional_evidence",
            "folds": [
                [start.isoformat(), end.isoformat()]
                for start, end in DEVELOPMENT_FOLDS
            ],
            "candidate_gate": {
                "minimum_invested_blocks": 250,
                "positive_total_return": True,
                "stress_total_return_positive": True,
                "minimum_annualized_return": 0.05,
                "minimum_annualized_market_alpha": 0.05,
                "minimum_sharpe": 0.75,
                "minimum_profit_factor": 1.05,
                "maximum_drawdown": 0.25,
                "minimum_positive_month_ratio": 0.50,
                "minimum_positive_folds": 4,
                "required_folds": len(DEVELOPMENT_FOLDS),
                "maximum_absolute_market_beta": 0.50,
                "maximum_symbol_absolute_contribution_share": 0.40,
            },
            "selection": {
                "eligible_candidates_only": True,
                "order": [
                    "maximum minimum fold total return",
                    "maximum median fold Sharpe",
                    "minimum total turnover",
                    "lexicographically smallest configuration_id",
                ],
                "selection_count": 1,
                "no_eligible_candidate": (
                    "freeze no model and leave confirmation sealed"
                ),
            },
            "design_artifacts_content_addressed": True,
        },
        "confirmation": {
            "period": [
                CONFIRMATION_START.isoformat(),
                CONFIRMATION_END.isoformat(),
            ],
            "status": "sealed_first_oos_for_v2",
            "quarters": [
                [start.isoformat(), end.isoformat()]
                for start, end in CONFIRMATION_QUARTERS
            ],
            "open_policy": (
                "open exactly once only after one immutable training winner"
            ),
            "gate": {
                "minimum_blocks": 1000,
                "minimum_invested_blocks": 200,
                "positive_total_return": True,
                "stress_total_return_positive": True,
                "minimum_annualized_return": 0.05,
                "minimum_annualized_market_alpha": 0.05,
                "minimum_sharpe": 0.75,
                "minimum_profit_factor": 1.10,
                "maximum_drawdown": 0.20,
                "minimum_positive_month_ratio": 0.55,
                "minimum_positive_quarters": 3,
                "required_quarters": len(CONFIRMATION_QUARTERS),
                "maximum_absolute_market_beta": 0.50,
                "maximum_symbol_absolute_contribution_share": 0.50,
            },
        },
        "locked_test": {
            "period": [LOCKED_START.isoformat(), LOCKED_END.isoformat()],
            "status": "sealed_until_confirmation_passes",
            "open_policy": "open exactly once without refit after confirmation pass",
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
            "six development-training configurations; only one frozen winner "
            "may query the untouched 2025 confirmation"
        ),
        "promotion_consequence": (
            "even confirmation and lock passes create only a forward candidate; "
            "no shadow, paper or real order is authorized"
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
            raise ValueError("persisted cost-aware long V2 protocol differs")
        return persisted
    common._atomic_json(path, payload)
    return payload


def _artifact(path: pathlib.Path) -> dict:
    return {
        "path": str(path),
        "bytes": path.stat().st_size,
        "sha256": common._sha256(path),
    }


def _ascending_ranks(
    values: numpy.ndarray,
    symbols: list[str],
    eligible: list[int],
) -> numpy.ndarray:
    ranks = numpy.full(len(symbols), -1, dtype=numpy.int64)
    for rank, column in enumerate(
        sorted(
            eligible,
            key=lambda column: (float(values[column]), symbols[column]),
        )
    ):
        ranks[column] = rank
    return ranks


def long_target_from_features(
    log_basis: numpy.ndarray,
    basis_momentum: numpy.ndarray,
    signed_flow: numpy.ndarray,
    symbols: list[str],
) -> numpy.ndarray:
    """Return the unchanged long intersection without consulting a short leg."""

    feature_values = [
        numpy.asarray(log_basis, dtype=numpy.float64),
        numpy.asarray(basis_momentum, dtype=numpy.float64),
        numpy.asarray(signed_flow, dtype=numpy.float64),
    ]
    shape = (len(symbols),)
    if any(values.shape != shape for values in feature_values):
        raise ValueError("long V2 feature shape differs from symbol universe")
    eligible = [
        column
        for column in range(len(symbols))
        if all(math.isfinite(float(values[column])) for values in feature_values)
    ]
    if len(eligible) < 2 * parent.TERTILE_DIVISOR:
        return numpy.zeros(len(symbols), dtype=numpy.float64)
    extreme_count = len(eligible) // parent.TERTILE_DIVISOR
    basis_rank = _ascending_ranks(feature_values[0], symbols, eligible)
    momentum_rank = _ascending_ranks(feature_values[1], symbols, eligible)
    flow_rank = _ascending_ranks(feature_values[2], symbols, eligible)
    low = set(range(extreme_count))
    high = set(range(len(eligible) - extreme_count, len(eligible)))
    candidates = [
        column
        for column in eligible
        if int(basis_rank[column]) in low
        and int(momentum_rank[column]) in high
        and int(flow_rank[column]) in high
    ]
    if not candidates:
        return numpy.zeros(len(symbols), dtype=numpy.float64)
    maximum_rank = len(eligible) - 1
    selected = sorted(
        candidates,
        key=lambda column: (
            -(
                maximum_rank
                - int(basis_rank[column])
                + int(momentum_rank[column])
                + int(flow_rank[column])
            ),
            symbols[column],
        ),
    )[:MAXIMUM_ASSETS]
    target = numpy.zeros(len(symbols), dtype=numpy.float64)
    target[selected] = PORTFOLIO_GROSS_EXPOSURE / len(selected)
    return target


def _market_regime_is_positive(market: dict, index: int) -> bool:
    if index < REGIME_BLOCKS:
        return False
    if (
        int(market["timestamps"][index])
        - int(market["timestamps"][index - REGIME_BLOCKS])
        != REGIME_BLOCKS * BLOCK_SECONDS
    ):
        return False
    cumulative = (
        market["closes"][index] / market["closes"][index - REGIME_BLOCKS] - 1.0
    )
    return bool(numpy.mean(cumulative) > 0.0)


def _is_rebalance_boundary(timestamp: int, rebalance_blocks: int) -> bool:
    anchor = int(datetime.datetime.fromisoformat(REBALANCE_ANCHOR_UTC).timestamp())
    return (timestamp - anchor) % (rebalance_blocks * BLOCK_SECONDS) == 0


def build_target_matrix(market: dict, configuration: dict) -> numpy.ndarray:
    """Build one of the six frozen slow-reselection target matrices."""

    if configuration not in candidate_configurations():
        raise ValueError("configuration is outside the frozen training grid")
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
            and timestamp - previous_timestamp != BLOCK_SECONDS
        ):
            current = numpy.zeros_like(current)
        if _is_rebalance_boundary(timestamp, configuration["rebalance_blocks"]):
            regime_passes = configuration["regime"] == "always_on" or (
                configuration["regime"] == "ew_market_28d_positive"
                and _market_regime_is_positive(market, index)
            )
            if regime_passes and index >= FORMATION_BLOCKS:
                features = parent.signal_values(market, index)
                current = long_target_from_features(
                    *features, market["symbols"]
                )
            else:
                current = numpy.zeros_like(current)
        targets[index] = current
        previous_timestamp = timestamp
    gross = numpy.sum(numpy.abs(targets), axis=1)
    net = numpy.sum(targets, axis=1)
    if numpy.any(gross > PORTFOLIO_GROSS_EXPOSURE + 1e-12):
        raise ValueError("long V2 target exceeds frozen gross")
    if numpy.any(net < -1e-12) or numpy.any(
        numpy.abs(net - gross) > 1e-12
    ):
        raise ValueError("long V2 target contains a short exposure")
    return targets


def simulate_period(
    market: dict,
    start: datetime.datetime,
    end: datetime.datetime,
    *,
    target_matrix: numpy.ndarray,
    cost_multiplier: float = 1.0,
    include_trajectory: bool = False,
) -> dict:
    """Reuse frozen accounting and append the preregistered Jensen alpha."""

    report = parent.simulate_period(
        market,
        start,
        end,
        cost_multiplier=cost_multiplier,
        target_matrix=target_matrix,
        include_trajectory=True,
    )
    trajectory = report.pop("_trajectory")
    strategy_returns = numpy.asarray(
        trajectory["block_return"], dtype=numpy.float64
    )
    market_returns = numpy.asarray(
        trajectory["market_return"], dtype=numpy.float64
    )
    beta = float(report["market_beta"])
    report["annualized_market_alpha"] = float(
        numpy.mean(strategy_returns - beta * market_returns) * ANNUAL_BLOCKS
    )
    report["market_alpha_definition"] = (
        "mean(strategy_block_return-beta*equal_weight_market_block_return)*1095"
    )
    if include_trajectory:
        report["_trajectory"] = trajectory
    return report


def _finish_checks(checks: dict) -> dict:
    return {
        "checks": checks,
        "passed_checks": sum(checks.values()),
        "total_checks": len(checks),
        "passed": all(checks.values()),
    }


def _candidate_gate(
    report: dict,
    stress_report: dict,
    folds: list[dict],
    specification: dict,
) -> dict:
    profit_factor = report["profit_factor"]
    profit_factor_pass = (
        report["total_return"] > 0
        if profit_factor is None
        else profit_factor >= specification["minimum_profit_factor"]
    )
    positive_folds = sum(fold["total_return"] > 0 for fold in folds)
    return _finish_checks(
        {
            "minimum_invested_blocks": (
                report["invested_blocks"]
                >= specification["minimum_invested_blocks"]
            ),
            "positive_total_return": report["total_return"] > 0,
            "stress_total_return_positive": stress_report["total_return"] > 0,
            "minimum_annualized_return": (
                report["annualized_return"]
                >= specification["minimum_annualized_return"]
            ),
            "minimum_annualized_market_alpha": (
                report["annualized_market_alpha"]
                >= specification["minimum_annualized_market_alpha"]
            ),
            "minimum_sharpe": (
                report["sharpe_zero_rate"] >= specification["minimum_sharpe"]
            ),
            "minimum_profit_factor": profit_factor_pass,
            "maximum_drawdown": (
                report["maximum_drawdown"] <= specification["maximum_drawdown"]
            ),
            "minimum_positive_month_ratio": (
                report["positive_month_ratio"]
                >= specification["minimum_positive_month_ratio"]
            ),
            "minimum_positive_folds": (
                positive_folds >= specification["minimum_positive_folds"]
            ),
            "required_folds_present": (
                len(folds) == specification["required_folds"]
            ),
            "maximum_absolute_market_beta": (
                abs(report["market_beta"])
                <= specification["maximum_absolute_market_beta"]
            ),
            "maximum_symbol_absolute_contribution_share": (
                report["maximum_symbol_absolute_contribution_share"]
                <= specification["maximum_symbol_absolute_contribution_share"]
            ),
        }
    )


def _selection_values(candidate: dict) -> dict:
    folds = candidate["folds"]
    return {
        "minimum_fold_total_return": min(
            fold["total_return"] for fold in folds
        ),
        "median_fold_sharpe": statistics.median(
            fold["sharpe_zero_rate"] for fold in folds
        ),
        "total_turnover": candidate["development"]["total_turnover"],
        "configuration_id": candidate["configuration"]["configuration_id"],
    }


def select_candidate(candidates: list[dict]) -> typing.Optional[dict]:
    """Apply the frozen maximin/median/turnover/id ordering."""

    eligible = [candidate for candidate in candidates if candidate["gate"]["passed"]]
    if not eligible:
        return None
    for candidate in eligible:
        candidate["selection_values"] = _selection_values(candidate)
    return sorted(
        eligible,
        key=lambda candidate: (
            -candidate["selection_values"]["minimum_fold_total_return"],
            -candidate["selection_values"]["median_fold_sharpe"],
            candidate["selection_values"]["total_turnover"],
            candidate["selection_values"]["configuration_id"],
        ),
    )[0]


def train_design(
    protocol_value,
    metric_addendum_value,
    futures_values,
    spot_values,
    flow_manifest_values,
    flow_cache_value,
    funding_values,
    output_root_value,
) -> dict:
    """Train over development only and optionally freeze one winner."""

    protocol_path = pathlib.Path(protocol_value).resolve()
    protocol = write_or_verify_protocol(protocol_path)
    addendum_path = pathlib.Path(metric_addendum_value).resolve()
    if common._sha256(addendum_path) != EXPECTED_METRIC_ADDENDUM_SHA256:
        raise ValueError("pre-training metric addendum hash differs")
    market, artifacts = parent.load_market(
        futures_values,
        spot_values,
        flow_manifest_values,
        flow_cache_value,
        funding_values,
    )
    evaluator_path = pathlib.Path(__file__).resolve()
    parent_path = pathlib.Path(parent.__file__).resolve()
    accounting_path = pathlib.Path(parent.parent.execution_parent.__file__).resolve()
    artifacts["trainer"] = _artifact(evaluator_path)
    artifacts["dependencies"] = {
        "confluence_parent": _artifact(parent_path),
        "accounting": _artifact(accounting_path),
        "metric_addendum": _artifact(addendum_path),
    }
    source_bundle_sha256 = common._json_hash(artifacts)

    candidate_reports = []
    trajectories = {}
    for configuration in candidate_configurations():
        targets = build_target_matrix(market, configuration)
        development = simulate_period(
            market,
            DEVELOPMENT_START,
            DEVELOPMENT_END,
            target_matrix=targets,
            include_trajectory=True,
        )
        trajectories[configuration["configuration_id"]] = development.pop(
            "_trajectory"
        )
        stress = simulate_period(
            market,
            DEVELOPMENT_START,
            DEVELOPMENT_END,
            target_matrix=targets,
            cost_multiplier=STRESS_COST_MULTIPLIER,
        )
        folds = [
            simulate_period(market, start, end, target_matrix=targets)
            for start, end in DEVELOPMENT_FOLDS
        ]
        gate = _candidate_gate(
            development,
            stress,
            folds,
            protocol["training"]["candidate_gate"],
        )
        candidate_reports.append(
            {
                "configuration": configuration,
                "development": development,
                "stress": stress,
                "folds": folds,
                "positive_folds": sum(
                    fold["total_return"] > 0 for fold in folds
                ),
                "gate": gate,
            }
        )
    selected = select_candidate(candidate_reports)

    output_root = pathlib.Path(output_root_value).resolve()
    experiment = output_root / (
        "cost-aware-long-confluence-v2-design-"
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
            "period_end_utc": DEVELOPMENT_END.isoformat(),
            "configurations": trajectories,
        },
    )
    selected_configuration = selected["configuration"] if selected else None
    candidate_summary_sha256 = common._json_hash(candidate_reports)
    model_path = None
    model_sha256 = None
    if selected_configuration is not None:
        model_path = experiment / "selected-model.json"
        model = {
            "schema_version": SCHEMA_VERSION,
            "protocol_sha256": protocol["protocol_sha256"],
            "source_bundle_sha256": source_bundle_sha256,
            "candidate_summary_sha256": candidate_summary_sha256,
            "selected_configuration": selected_configuration,
            "selection_values": selected["selection_values"],
            "training_period_end_utc": DEVELOPMENT_END.isoformat(),
            "confirmation_evaluated": False,
            "locked_test_evaluated": False,
            "orders_authorized": False,
            "paper_orders_authorized": False,
            "automatic_promotion": False,
        }
        model["content_sha256"] = common._json_hash(model)
        common._atomic_json(model_path, model)
        model_sha256 = common._sha256(model_path)
    report = {
        "schema_version": SCHEMA_VERSION,
        "protocol_version": PROTOCOL_VERSION,
        "created_at": datetime.datetime.now(parent.parent.UTC).isoformat(),
        "research_only": True,
        "public_data_only": True,
        "credentials_used": False,
        "orders_authorized": False,
        "paper_orders_authorized": False,
        "automatic_promotion": False,
        "training_only": True,
        "maximum_outcome_utc": DEVELOPMENT_END.isoformat(),
        "confirmation_evaluated": False,
        "locked_test_evaluated": False,
        "protocol_path": str(protocol_path),
        "protocol_file_sha256": common._sha256(protocol_path),
        "protocol_sha256": protocol["protocol_sha256"],
        "source_bundle_sha256": source_bundle_sha256,
        "source_artifacts": artifacts,
        "candidates": candidate_reports,
        "candidate_summary_sha256": candidate_summary_sha256,
        "eligible_candidate_count": sum(
            candidate["gate"]["passed"] for candidate in candidate_reports
        ),
        "selected_configuration": selected_configuration,
        "selected_model_path": str(model_path) if model_path else None,
        "selected_model_sha256": model_sha256,
        "training_trajectories": {
            "path": str(trajectories_path),
            "sha256": common._sha256(trajectories_path),
        },
        "confirmation_access_authorized": selected_configuration is not None,
        "verdict": (
            "TRAINING_WINNER_FROZEN_CONFIRMATION_AUTHORIZED"
            if selected_configuration is not None
            else "NO_ELIGIBLE_TRAINING_CANDIDATE_CONFIRMATION_REMAINS_SEALED"
        ),
        "results_do_not_authorize_orders": True,
    }
    report_path = experiment / "design-report.json"
    common._atomic_json(report_path, report)
    manifest = {
        "schema_version": SCHEMA_VERSION,
        "protocol_sha256": protocol["protocol_sha256"],
        "source_bundle_sha256": source_bundle_sha256,
        "report_path": str(report_path),
        "report_sha256": common._sha256(report_path),
        "training_trajectories_path": str(trajectories_path),
        "training_trajectories_sha256": common._sha256(trajectories_path),
        "selected_model_path": str(model_path) if model_path else None,
        "selected_model_sha256": model_sha256,
        "confirmation_evaluated": False,
        "locked_test_evaluated": False,
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
    train = subparsers.add_parser("train-design")
    train.add_argument("--protocol", required=True)
    train.add_argument("--metric-addendum", required=True)
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
    if arguments.command == "train-design":
        print(
            json.dumps(
                train_design(
                    arguments.protocol,
                    arguments.metric_addendum,
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
    raise AssertionError("unreachable command")


if __name__ == "__main__":
    raise SystemExit(main())
