"""Frozen seven-day basis-momentum factor replication V1.

This module is public-data-only, offline and incapable of creating orders. The
economic evaluator is added only after this result-free protocol is persisted
and committed.
"""

from __future__ import annotations

import argparse
import datetime
import json
import math
import pathlib
import typing

import numpy

from octobot.ai_strategy_lab import basis_factor_v2 as execution_parent
from octobot.ai_strategy_lab import cointegration_pairs_v1 as common


SCHEMA_VERSION = 1
PROTOCOL_VERSION = "crypto_perpetual_basis_momentum_v1"
PREREGISTRATION_DATE = "2026-08-28"
PAPER_MANUSCRIPT_SHA256 = execution_parent.PAPER_MANUSCRIPT_SHA256
EXPECTED_SYMBOLS = execution_parent.EXPECTED_SYMBOLS
BLOCK_SECONDS = execution_parent.BLOCK_SECONDS
FORMATION_BLOCKS = 7 * 3
SELECTION_FRACTION = execution_parent.SELECTION_FRACTION
SELECTED_ASSETS_PER_SIDE = execution_parent.SELECTED_ASSETS_PER_SIDE
SIDE_GROSS_EXPOSURE = execution_parent.SIDE_GROSS_EXPOSURE
FEE_PER_TURNOVER = execution_parent.FEE_PER_TURNOVER
SLIPPAGE_PER_TURNOVER = execution_parent.SLIPPAGE_PER_TURNOVER
STRESS_COST_MULTIPLIER = execution_parent.STRESS_COST_MULTIPLIER
MAXIMUM_ABSOLUTE_MARKET_BETA = (
    execution_parent.MAXIMUM_ABSOLUTE_MARKET_BETA
)
MAXIMUM_SYMBOL_CONTRIBUTION_SHARE = (
    execution_parent.MAXIMUM_SYMBOL_CONTRIBUTION_SHARE
)
UTC = execution_parent.UTC
DEVELOPMENT_START = execution_parent.DEVELOPMENT_START
DEVELOPMENT_END = execution_parent.DEVELOPMENT_END
CONFIRMATION_START = execution_parent.CONFIRMATION_START
CONFIRMATION_END = execution_parent.CONFIRMATION_END
LOCKED_START = execution_parent.LOCKED_START
LOCKED_END = execution_parent.LOCKED_END
DEVELOPMENT_FOLDS = execution_parent.DEVELOPMENT_FOLDS
CONFIRMATION_QUARTERS = execution_parent.CONFIRMATION_QUARTERS
FORWARD_START_UTC = "2026-08-29T00:00:00+00:00"


def frozen_protocol() -> dict:
    """Return the single immutable, result-free basis-momentum protocol."""

    return {
        "schema_version": SCHEMA_VERSION,
        "protocol_version": PROTOCOL_VERSION,
        "preregistered_on": PREREGISTRATION_DATE,
        "status": "result_free_evaluation_protocol",
        "research_only": True,
        "public_data_only": True,
        "credentials_used": False,
        "orders_authorized": False,
        "paper_orders_authorized": False,
        "automatic_promotion": False,
        "external_hypothesis": {
            "title": "Anatomy of Cryptocurrency Perpetual Futures Returns",
            "authors": ["Yi Cao", "Jia Zhai", "Pengfei Luo"],
            "institutional_repository": (
                "https://era.ed.ac.uk/bitstream/handle/1842/43608/"
                "Luo2025.pdf?isAllowed=y&sequence=1"
            ),
            "thesis_doi": "10.7488/era/6141",
            "manuscript_sha256": PAPER_MANUSCRIPT_SHA256,
            "equation": 70,
            "table": 21,
            "source_selected_formation": "7*3 eight-hour intervals",
            "source_reported_high_minus_low_weekly_return": 0.0188,
            "source_reported_t_statistic": 8.50,
            "portfolio": "high-minus-low basis momentum quintiles",
            "holding": "following rolling period t to t+N",
            "n_definition": "one eight-hour Binance funding interval",
        },
        "hypothesis": {
            "name": "seven_day_spot_minus_perpetual_basis_momentum",
            "statement": (
                "assets whose spot outperformed their perpetual over the "
                "preceding seven days outperform the opposite quintile over "
                "the next eight-hour funding interval"
            ),
            "economic_mechanism": (
                "persistent spot premium and term-premium information in the "
                "relative spot/perpetual path"
            ),
            "direction": "long high basis momentum; short low basis momentum",
            "opposite_direction_tested": False,
            "long_only_variant_allowed": False,
            "one_configuration_only": True,
        },
        "signal": {
            "source": "checksummed Binance spot and USD-M 1h collectors",
            "basis_momentum": (
                "(spot_t/spot_t_minus_21-1) - "
                "(perpetual_t/perpetual_t_minus_21-1)"
            ),
            "formation_blocks": FORMATION_BLOCKS,
            "formation_days": 7,
            "formation_must_be_contiguous": True,
            "decision_boundaries_utc": ["00:00", "08:00", "16:00"],
            "completed_candles_only": True,
            "ranking": (
                "ascending basis momentum, deterministic symbol tie-break"
            ),
            "selection_fraction_per_side": SELECTION_FRACTION,
            "selected_assets_per_side": SELECTED_ASSETS_PER_SIDE,
            "long_side": "highest basis-momentum quintile",
            "short_side": "lowest basis-momentum quintile",
            "weighting": "equal weight within each side",
            "side_gross_exposure": SIDE_GROSS_EXPOSURE,
            "nominal_net_exposure": 0.0,
            "rebalance": "every completed eight-hour block",
            "holding_blocks": 1,
            "holding_hours": 8,
            "overlapping_vintages": False,
            "other_lookbacks": None,
            "filters": None,
            "thresholds": None,
            "spot_is_signal_only": True,
            "future_prices_or_funding_used": False,
        },
        "data_quality_policy": {
            "common_completed_blocks_only": True,
            "interpolation_or_forward_fill": False,
            "return_across_gap": False,
            "eligible_decision": (
                "decision and outcome closes must be exactly eight hours apart"
            ),
            "formation_after_gap": (
                "zero target until 21 consecutive historical intervals exist"
            ),
            "gap_boundary": (
                "flatten prior segment with cost and reopen next segment from "
                "flat with cost"
            ),
        },
        "period_boundary": {
            "opening": "open first causal nonzero target from flat with cost",
            "closing": "flatten final target with cost",
            "cross_period_pnl_imported": False,
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
            "maker_fill_assumptions": False,
            "cost_on_netted_weight_change": True,
            "maximum_portfolio_gross": 2.0 * SIDE_GROSS_EXPOSURE,
        },
        "validation": {
            "expected_symbols": EXPECTED_SYMBOLS,
            "development": [
                DEVELOPMENT_START.isoformat(),
                DEVELOPMENT_END.isoformat(),
            ],
            "development_status": "diagnostic_reuse",
            "development_folds": [
                [start.isoformat(), end.isoformat()]
                for start, end in DEVELOPMENT_FOLDS
            ],
            "confirmation": [
                CONFIRMATION_START.isoformat(),
                CONFIRMATION_END.isoformat(),
            ],
            "confirmation_status": "sealed_for_basis_momentum_family",
            "confirmation_quarters": [
                [start.isoformat(), end.isoformat()]
                for start, end in CONFIRMATION_QUARTERS
            ],
            "locked_final_test": [
                LOCKED_START.isoformat(),
                LOCKED_END.isoformat(),
            ],
            "locked_status": "sealed_for_basis_momentum_family",
            "locked_policy": (
                "do not calculate confirmation unless development passes; "
                "do not calculate lock unless confirmation also passes"
            ),
            "survivorship_limitation": (
                "fixed archive of contracts surviving to archive end"
            ),
        },
        "development_gate": {
            "minimum_blocks": 2000,
            "positive_total_return": True,
            "minimum_annualized_return": 0.08,
            "minimum_sharpe": 1.00,
            "maximum_drawdown": 0.15,
            "minimum_positive_month_ratio": 0.55,
            "minimum_positive_folds": 4,
            "required_folds": len(DEVELOPMENT_FOLDS),
            "both_side_contributions_nonnegative": True,
            "maximum_absolute_market_beta": MAXIMUM_ABSOLUTE_MARKET_BETA,
            "minimum_positive_leave_one_symbol_out": 15,
            "required_leave_one_symbol_out": EXPECTED_SYMBOLS,
            "stress_total_return_positive": True,
            "minimum_stress_sharpe": 0.50,
            "minimum_average_gross_exposure": 0.75,
            "maximum_symbol_absolute_contribution_share": (
                MAXIMUM_SYMBOL_CONTRIBUTION_SHARE
            ),
        },
        "confirmation_gate": {
            "minimum_blocks": 1000,
            "positive_total_return": True,
            "minimum_annualized_return": 0.04,
            "minimum_sharpe": 0.75,
            "maximum_drawdown": 0.15,
            "minimum_positive_month_ratio": 0.50,
            "minimum_positive_quarters": 3,
            "required_quarters": len(CONFIRMATION_QUARTERS),
            "both_side_contributions_nonnegative": True,
            "maximum_absolute_market_beta": MAXIMUM_ABSOLUTE_MARKET_BETA,
            "stress_total_return_positive": True,
            "minimum_stress_sharpe": 0.25,
        },
        "locked_gate": {
            "minimum_blocks": 500,
            "positive_total_return": True,
            "minimum_annualized_return": 0.04,
            "minimum_sharpe": 0.50,
            "maximum_drawdown": 0.15,
            "minimum_positive_month_ratio": 0.50,
            "both_side_contributions_nonnegative": True,
            "maximum_absolute_market_beta": MAXIMUM_ABSOLUTE_MARKET_BETA,
            "stress_total_return_positive": True,
        },
        "forward_gate": {
            "start_utc": FORWARD_START_UTC,
            "minimum_calendar_days": 180,
            "minimum_observed_blocks": 500,
            "no_refit": True,
            "same_signal_holding_and_costs": True,
            "required_before_shadow_or_paper": True,
        },
        "multiple_testing_disclosure": (
            "one externally selected seven-day formation, direction, quintile "
            "allocation, eight-hour holding and unchanged cost model"
        ),
        "promotion_consequence": (
            "historical pass identifies only a forward candidate; no shadow, "
            "paper or real order is authorized"
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
            raise ValueError("persisted basis-momentum V1 protocol differs")
        return persisted
    common._atomic_json(path, payload)
    return payload


def basis_momentum_values(market: dict, index: int) -> numpy.ndarray:
    """Return the frozen 21-block spot-minus-perpetual cumulative return."""

    if index < FORMATION_BLOCKS or index >= len(market["timestamps"]):
        raise IndexError("basis-momentum formation window is unavailable")
    if (
        int(market["timestamps"][index])
        - int(market["timestamps"][index - FORMATION_BLOCKS])
        != FORMATION_BLOCKS * BLOCK_SECONDS
    ):
        return numpy.full(len(market["symbols"]), numpy.nan)
    spot_return = (
        market["spot_closes"][index]
        / market["spot_closes"][index - FORMATION_BLOCKS]
        - 1.0
    )
    perpetual_return = (
        market["closes"][index]
        / market["closes"][index - FORMATION_BLOCKS]
        - 1.0
    )
    return numpy.asarray(spot_return - perpetual_return, dtype=numpy.float64)


def target_weights(
    market: dict,
    index: int,
    *,
    enabled_columns: typing.Optional[numpy.ndarray] = None,
) -> numpy.ndarray:
    """Rank only fully formed basis-momentum values observable at ``index``."""

    if index < FORMATION_BLOCKS or index >= len(market["timestamps"]):
        raise IndexError("basis-momentum target lacks its formation window")
    if enabled_columns is None:
        enabled_columns = numpy.ones(len(market["symbols"]), dtype=bool)
    enabled_columns = numpy.asarray(enabled_columns, dtype=bool)
    if enabled_columns.shape != (len(market["symbols"]),):
        raise ValueError("enabled-column mask has the wrong shape")
    momentum = basis_momentum_values(market, index)
    eligible = [
        column
        for column, value in enumerate(momentum)
        if enabled_columns[column] and math.isfinite(float(value))
    ]
    if len(eligible) < 2 * SELECTED_ASSETS_PER_SIDE:
        return numpy.zeros(len(market["symbols"]), dtype=numpy.float64)
    ordered = sorted(
        eligible,
        key=lambda column: (float(momentum[column]), market["symbols"][column]),
    )
    short_columns = ordered[:SELECTED_ASSETS_PER_SIDE]
    long_columns = ordered[-SELECTED_ASSETS_PER_SIDE:]
    target = numpy.zeros(len(market["symbols"]), dtype=numpy.float64)
    target[long_columns] = SIDE_GROSS_EXPOSURE / len(long_columns)
    target[short_columns] = -SIDE_GROSS_EXPOSURE / len(short_columns)
    return target


def build_target_matrix(
    market: dict,
    *,
    enabled_columns: typing.Optional[numpy.ndarray] = None,
) -> numpy.ndarray:
    targets = numpy.zeros(
        (len(market["timestamps"]), len(market["symbols"])),
        dtype=numpy.float64,
    )
    for index in range(FORMATION_BLOCKS, len(market["timestamps"])):
        targets[index] = target_weights(
            market, index, enabled_columns=enabled_columns
        )
    gross = numpy.sum(numpy.abs(targets), axis=1)
    net = numpy.sum(targets, axis=1)
    if numpy.any(gross > 2.0 * SIDE_GROSS_EXPOSURE + 1e-12):
        raise ValueError("basis-momentum target exceeds frozen gross")
    if numpy.any(numpy.abs(net) > 1e-12):
        raise ValueError("basis-momentum target is not nominally neutral")
    return targets


def simulate_period(
    market: dict,
    start: datetime.datetime,
    end: datetime.datetime,
    *,
    cost_multiplier: float = 1.0,
    enabled_columns: typing.Optional[numpy.ndarray] = None,
    target_matrix: typing.Optional[numpy.ndarray] = None,
    include_trajectory: bool = False,
) -> dict:
    if target_matrix is None:
        target_matrix = build_target_matrix(
            market, enabled_columns=enabled_columns
        )
    return execution_parent.simulate_period(
        market,
        start,
        end,
        cost_multiplier=cost_multiplier,
        enabled_columns=enabled_columns,
        target_matrix=target_matrix,
        include_trajectory=include_trajectory,
    )


def _finish_checks(checks: dict) -> dict:
    return execution_parent._finish_checks(checks)


def _base_gate(report: dict, specification: dict) -> dict:
    return execution_parent._base_gate(report, specification)


def evaluate_prelock(
    protocol_value,
    futures_values,
    spot_values,
    funding_values,
    output_root_value,
) -> dict:
    protocol_path = pathlib.Path(protocol_value).resolve()
    protocol = write_or_verify_protocol(protocol_path)
    market, artifacts = execution_parent.load_market(
        futures_values, spot_values, funding_values
    )
    evaluator_path = pathlib.Path(__file__).resolve()
    dependency_path = pathlib.Path(execution_parent.__file__).resolve()
    artifacts["evaluator"] = {
        "path": str(evaluator_path),
        "bytes": evaluator_path.stat().st_size,
        "sha256": common._sha256(evaluator_path),
    }
    artifacts["accounting_dependency"] = {
        "path": str(dependency_path),
        "bytes": dependency_path.stat().st_size,
        "sha256": common._sha256(dependency_path),
    }
    base_targets = build_target_matrix(market)

    development = simulate_period(
        market,
        DEVELOPMENT_START,
        DEVELOPMENT_END,
        target_matrix=base_targets,
        include_trajectory=True,
    )
    development_trajectory = development.pop("_trajectory")
    development_stress = simulate_period(
        market,
        DEVELOPMENT_START,
        DEVELOPMENT_END,
        cost_multiplier=STRESS_COST_MULTIPLIER,
        target_matrix=base_targets,
    )
    development_folds = [
        simulate_period(market, start, end, target_matrix=base_targets)
        for start, end in DEVELOPMENT_FOLDS
    ]
    positive_folds = sum(
        report["total_return"] > 0 for report in development_folds
    )
    leave_one_out = {}
    for column, symbol in enumerate(market["symbols"]):
        enabled = numpy.ones(len(market["symbols"]), dtype=bool)
        enabled[column] = False
        targets = build_target_matrix(market, enabled_columns=enabled)
        leave_one_out[symbol] = simulate_period(
            market,
            DEVELOPMENT_START,
            DEVELOPMENT_END,
            enabled_columns=enabled,
            target_matrix=targets,
        )
    positive_leave_one_out = sum(
        report["total_return"] > 0 for report in leave_one_out.values()
    )
    development_gate = _base_gate(
        development, protocol["development_gate"]
    )
    development_checks = {
        **development_gate["checks"],
        "minimum_positive_folds": (
            positive_folds
            >= protocol["development_gate"]["minimum_positive_folds"]
        ),
        "required_folds_present": (
            len(development_folds)
            == protocol["development_gate"]["required_folds"]
        ),
        "minimum_positive_leave_one_symbol_out": (
            positive_leave_one_out
            >= protocol["development_gate"][
                "minimum_positive_leave_one_symbol_out"
            ]
        ),
        "required_leave_one_symbol_out_present": (
            len(leave_one_out)
            == protocol["development_gate"][
                "required_leave_one_symbol_out"
            ]
        ),
        "stress_total_return_positive": (
            development_stress["total_return"] > 0
        ),
        "minimum_stress_sharpe": (
            development_stress["sharpe_zero_rate"]
            >= protocol["development_gate"]["minimum_stress_sharpe"]
        ),
        "minimum_average_gross_exposure": (
            development["average_gross_exposure"]
            >= protocol["development_gate"]["minimum_average_gross_exposure"]
        ),
        "maximum_symbol_absolute_contribution_share": (
            development["maximum_symbol_absolute_contribution_share"]
            <= protocol["development_gate"][
                "maximum_symbol_absolute_contribution_share"
            ]
        ),
    }
    development_gate = _finish_checks(development_checks)

    confirmation = None
    confirmation_stress = None
    confirmation_quarters = None
    confirmation_gate = {
        "passed": False,
        "not_evaluated": not development_gate["passed"],
        "reason": (
            "development_gate_failed"
            if not development_gate["passed"]
            else None
        ),
    }
    if development_gate["passed"]:
        confirmation = simulate_period(
            market,
            CONFIRMATION_START,
            CONFIRMATION_END,
            target_matrix=base_targets,
        )
        confirmation_stress = simulate_period(
            market,
            CONFIRMATION_START,
            CONFIRMATION_END,
            cost_multiplier=STRESS_COST_MULTIPLIER,
            target_matrix=base_targets,
        )
        confirmation_quarters = [
            simulate_period(market, start, end, target_matrix=base_targets)
            for start, end in CONFIRMATION_QUARTERS
        ]
        positive_quarters = sum(
            report["total_return"] > 0 for report in confirmation_quarters
        )
        confirmation_gate = _base_gate(
            confirmation, protocol["confirmation_gate"]
        )
        confirmation_checks = {
            **confirmation_gate["checks"],
            "minimum_positive_quarters": (
                positive_quarters
                >= protocol["confirmation_gate"]["minimum_positive_quarters"]
            ),
            "required_quarters_present": (
                len(confirmation_quarters)
                == protocol["confirmation_gate"]["required_quarters"]
            ),
            "stress_total_return_positive": (
                confirmation_stress["total_return"] > 0
            ),
            "minimum_stress_sharpe": (
                confirmation_stress["sharpe_zero_rate"]
                >= protocol["confirmation_gate"]["minimum_stress_sharpe"]
            ),
        }
        confirmation_gate = _finish_checks(confirmation_checks)

    locked_authorized = (
        development_gate["passed"] and confirmation_gate["passed"]
    )
    locked = None
    locked_stress = None
    locked_gate = {
        "passed": False,
        "not_evaluated": not locked_authorized,
        "reason": "prelock_gate_failed" if not locked_authorized else None,
    }
    if locked_authorized:
        locked = simulate_period(
            market, LOCKED_START, LOCKED_END, target_matrix=base_targets
        )
        locked_stress = simulate_period(
            market,
            LOCKED_START,
            LOCKED_END,
            cost_multiplier=STRESS_COST_MULTIPLIER,
            target_matrix=base_targets,
        )
        locked_gate = _base_gate(locked, protocol["locked_gate"])
        locked_checks = {
            **locked_gate["checks"],
            "stress_total_return_positive": locked_stress["total_return"] > 0,
        }
        locked_gate = _finish_checks(locked_checks)

    historical_candidate = locked_authorized and locked_gate["passed"]
    source_bundle_sha256 = common._json_hash(artifacts)
    output_root = pathlib.Path(output_root_value).resolve()
    experiment = output_root / (
        "basis-momentum-v1-"
        + protocol["protocol_sha256"][:12]
        + "-"
        + source_bundle_sha256[:12]
    )
    experiment.mkdir(parents=True, exist_ok=False)
    trajectory_path = experiment / "development-trajectory.json"
    common._atomic_json(
        trajectory_path,
        {
            "schema_version": SCHEMA_VERSION,
            "protocol_sha256": protocol["protocol_sha256"],
            "source_bundle_sha256": source_bundle_sha256,
            **development_trajectory,
        },
    )
    report = {
        "schema_version": SCHEMA_VERSION,
        "protocol_version": PROTOCOL_VERSION,
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
        "source_bundle_sha256": source_bundle_sha256,
        "source_artifacts": artifacts,
        "symbols": market["symbols"],
        "development": development,
        "development_stress": development_stress,
        "development_folds": development_folds,
        "development_positive_folds": positive_folds,
        "development_leave_one_symbol_out": leave_one_out,
        "development_positive_leave_one_symbol_out": positive_leave_one_out,
        "development_trajectory": {
            "path": str(trajectory_path),
            "sha256": common._sha256(trajectory_path),
        },
        "development_gate": development_gate,
        "confirmation": confirmation,
        "confirmation_stress": confirmation_stress,
        "confirmation_quarters": confirmation_quarters,
        "confirmation_gate": confirmation_gate,
        "locked_test": {
            "authorized_to_open": locked_authorized,
            "materialized": locked is not None,
            "report": locked,
            "stress_report": locked_stress,
            "gate": locked_gate,
        },
        "historical_candidate": historical_candidate,
        "forward_validation": {
            **protocol["forward_gate"],
            "started": False,
            "passed": False,
            "automatic_promotion": False,
        },
        "verdict": (
            "HISTORICAL_CANDIDATE_REQUIRES_180D_FORWARD"
            if historical_candidate
            else (
                "REJECTED_LOCKED_TEST"
                if locked is not None
                else "REJECTED_PRELOCK_LOCK_REMAINS_SEALED"
            )
        ),
        "results_do_not_authorize_orders": True,
    }
    report_path = experiment / "report.json"
    common._atomic_json(report_path, report)
    manifest = {
        "schema_version": SCHEMA_VERSION,
        "protocol_sha256": protocol["protocol_sha256"],
        "source_bundle_sha256": source_bundle_sha256,
        "report_path": str(report_path),
        "report_sha256": common._sha256(report_path),
        "development_trajectory_path": str(trajectory_path),
        "development_trajectory_sha256": common._sha256(trajectory_path),
        "confirmation_materialized": confirmation is not None,
        "locked_test_materialized": locked is not None,
        "historical_candidate": historical_candidate,
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
    evaluate = subparsers.add_parser("evaluate-prelock")
    evaluate.add_argument("--protocol", required=True)
    evaluate.add_argument("--futures-collector", action="append", required=True)
    evaluate.add_argument("--spot-collector", action="append", required=True)
    evaluate.add_argument("--funding-json", action="append", required=True)
    evaluate.add_argument("--output-root", required=True)
    return parser


def main(argv=None) -> int:
    args = _parser().parse_args(argv)
    if args.command == "write-protocol":
        result = write_or_verify_protocol(args.output)
        print(json.dumps(result, indent=2, sort_keys=True))
        return 0
    result = evaluate_prelock(
        args.protocol,
        args.futures_collector,
        args.spot_collector,
        args.funding_json,
        args.output_root,
    )
    report = result["report"]
    summary = {
        "directory": result["directory"],
        "verdict": report["verdict"],
        "development": report["development"],
        "development_stress": report["development_stress"],
        "development_gate": report["development_gate"],
        "confirmation_materialized": result["manifest"][
            "confirmation_materialized"
        ],
        "locked_test_materialized": result["manifest"][
            "locked_test_materialized"
        ],
        "report_sha256": result["manifest"]["report_sha256"],
        "content_sha256": result["manifest"]["content_sha256"],
    }
    print(json.dumps(summary, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
