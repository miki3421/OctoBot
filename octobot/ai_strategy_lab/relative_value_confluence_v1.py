"""Frozen three-factor relative-value confluence protocol V1.

The module is public-data-only, offline and incapable of creating orders.  At
preregistration time it can only persist the result-free protocol; the
economic evaluator is added in a later commit.
"""

from __future__ import annotations

import argparse
import datetime
import json
import math
import pathlib
import typing

import numpy

from octobot.ai_strategy_lab import basis_momentum_v1 as parent
from octobot.ai_strategy_lab import signed_flow_factor_v1 as flow_parent
from octobot.ai_strategy_lab import cointegration_pairs_v1 as common


SCHEMA_VERSION = 1
PROTOCOL_VERSION = "crypto_perpetual_relative_value_confluence_v1"
PREREGISTRATION_DATE = "2026-08-28"
PAPER_MANUSCRIPT_SHA256 = parent.PAPER_MANUSCRIPT_SHA256
EXPECTED_SYMBOLS = parent.EXPECTED_SYMBOLS
BLOCK_SECONDS = parent.BLOCK_SECONDS
FORMATION_BLOCKS = 21
TERTILE_DIVISOR = 3
MAXIMUM_ASSETS_PER_SIDE = 3
SIDE_GROSS_EXPOSURE = parent.SIDE_GROSS_EXPOSURE
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


def frozen_protocol() -> dict:
    """Return the only permitted result-free confluence specification."""

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
            "source_tables": [19, 21, 29],
            "source_directions": {
                "log_basis": "long low; short high",
                "basis_momentum": "long high; short low",
                "signed_price_volume_imbalance": "long high; short low",
            },
            "source_selected_formation": "7*3 eight-hour intervals",
        },
        "hypothesis": {
            "name": "three_factor_relative_value_confluence",
            "statement": (
                "the documented gross relative-value effects become tradable "
                "after unchanged costs only when valuation, relative-path "
                "persistence and aggressive flow agree cross-sectionally"
            ),
            "economic_mechanism": (
                "a perpetual lagging spot is entered only when its seven-day "
                "relative path and aggressive order flow confirm convergence"
            ),
            "opposite_direction_tested": False,
            "long_only_variant_allowed": False,
            "one_configuration_only": True,
        },
        "signal": {
            "universe": "18 aligned Binance USD-M perpetual/spot pairs",
            "decision_boundaries_utc": ["00:00", "08:00", "16:00"],
            "completed_candles_only": True,
            "formation_blocks": FORMATION_BLOCKS,
            "formation_days": 7,
            "formation_must_be_contiguous": True,
            "features": {
                "log_basis": "log(perpetual_close_t)-log(spot_close_t)",
                "basis_momentum": (
                    "(spot_t/spot_t_minus_21-1)-"
                    "(perpetual_t/perpetual_t_minus_21-1)"
                ),
                "signed_flow": (
                    "sum over latest 21 blocks of "
                    "2*taker_buy_quote-total_quote_volume"
                ),
            },
            "ranking": (
                "independent ascending ranks with deterministic symbol "
                "tie-break; extreme set size floor(eligible/3)"
            ),
            "long_intersection": (
                "bottom log-basis tertile AND top basis-momentum tertile "
                "AND top signed-flow tertile"
            ),
            "short_intersection": (
                "top log-basis tertile AND bottom basis-momentum tertile "
                "AND bottom signed-flow tertile"
            ),
            "long_extremeness": (
                "(n-1-log_basis_rank)+basis_momentum_rank+signed_flow_rank"
            ),
            "short_extremeness": (
                "log_basis_rank+(n-1-basis_momentum_rank)+"
                "(n-1-signed_flow_rank)"
            ),
            "maximum_assets_per_side": MAXIMUM_ASSETS_PER_SIDE,
            "paired_side_requirement": (
                "flat unless both long and short intersections are nonempty"
            ),
            "weighting": "equal weight independently within each active side",
            "side_gross_exposure": SIDE_GROSS_EXPOSURE,
            "maximum_portfolio_gross": 2.0 * SIDE_GROSS_EXPOSURE,
            "nominal_net_exposure": 0.0,
            "rebalance": "every completed eight-hour block",
            "holding_blocks": 1,
            "overlapping_vintages": False,
            "learned_thresholds": None,
            "hysteresis": None,
            "normalization": None,
            "filters": None,
            "other_lookbacks": None,
            "spot_is_signal_only": True,
            "future_prices_or_funding_used": False,
        },
        "data_quality_policy": {
            "checksummed_raw_flow_archives": True,
            "checksummed_spot_and_perpetual_collectors": True,
            "common_completed_blocks_only": True,
            "interpolation_or_forward_fill": False,
            "return_across_gap": False,
            "eligible_decision": (
                "decision and outcome closes must be exactly eight hours apart"
            ),
            "formation_after_gap": (
                "flat until both 21-block formation windows are contiguous"
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
            "cost_reduction_relative_to_prior_tests": False,
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
            "confirmation_status": "sealed_for_confluence_family",
            "confirmation_quarters": [
                [start.isoformat(), end.isoformat()]
                for start, end in CONFIRMATION_QUARTERS
            ],
            "locked_final_test": [
                LOCKED_START.isoformat(),
                LOCKED_END.isoformat(),
            ],
            "locked_status": "sealed_for_confluence_family",
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
            "minimum_invested_blocks": 250,
            "positive_total_return": True,
            "minimum_annualized_return": 0.08,
            "minimum_sharpe": 1.00,
            "minimum_profit_factor": 1.10,
            "maximum_drawdown": 0.15,
            "minimum_positive_month_ratio": 0.55,
            "minimum_positive_folds": 4,
            "required_folds": len(DEVELOPMENT_FOLDS),
            "both_side_contributions_nonnegative": True,
            "maximum_absolute_market_beta": 0.20,
            "minimum_positive_leave_one_symbol_out": 15,
            "required_leave_one_symbol_out": EXPECTED_SYMBOLS,
            "stress_total_return_positive": True,
            "minimum_stress_sharpe": 0.50,
            "maximum_symbol_absolute_contribution_share": 0.35,
        },
        "confirmation_gate": {
            "minimum_blocks": 1000,
            "minimum_invested_blocks": 100,
            "positive_total_return": True,
            "minimum_annualized_return": 0.04,
            "minimum_sharpe": 0.75,
            "minimum_profit_factor": 1.05,
            "maximum_drawdown": 0.15,
            "minimum_positive_month_ratio": 0.50,
            "minimum_positive_quarters": 3,
            "required_quarters": len(CONFIRMATION_QUARTERS),
            "both_side_contributions_nonnegative": True,
            "maximum_absolute_market_beta": 0.20,
            "stress_total_return_positive": True,
            "minimum_stress_sharpe": 0.25,
        },
        "locked_gate": {
            "minimum_blocks": 500,
            "minimum_invested_blocks": 50,
            "positive_total_return": True,
            "minimum_annualized_return": 0.04,
            "minimum_sharpe": 0.50,
            "minimum_profit_factor": 1.05,
            "maximum_drawdown": 0.15,
            "minimum_positive_month_ratio": 0.50,
            "both_side_contributions_nonnegative": True,
            "maximum_absolute_market_beta": 0.20,
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
            "one fixed intersection of three externally documented factor "
            "directions; no thresholds, weights or holding periods are fitted"
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
    """Persist the immutable protocol or fail if an existing file differs."""

    path = pathlib.Path(path_value).resolve()
    protocol = frozen_protocol()
    payload = {**protocol, "protocol_sha256": common._json_hash(protocol)}
    if path.is_file():
        persisted = json.loads(path.read_text(encoding="utf-8"))
        if persisted != payload:
            raise ValueError("persisted confluence V1 protocol differs")
        return persisted
    common._atomic_json(path, payload)
    return payload


def _artifact(path: pathlib.Path) -> dict:
    return {
        "path": str(path),
        "bytes": path.stat().st_size,
        "sha256": common._sha256(path),
    }


def load_market(
    futures_values: typing.Iterable[typing.Union[str, pathlib.Path]],
    spot_values: typing.Iterable[typing.Union[str, pathlib.Path]],
    flow_manifest_values: typing.Iterable[typing.Union[str, pathlib.Path]],
    flow_cache_value: typing.Union[str, pathlib.Path],
    funding_values: typing.Iterable[typing.Union[str, pathlib.Path]],
) -> tuple[dict, dict]:
    """Align independently checksummed spot/basis and raw-flow inputs."""

    futures_values = list(futures_values)
    spot_values = list(spot_values)
    flow_manifest_values = list(flow_manifest_values)
    funding_values = list(funding_values)
    accounting = parent.execution_parent
    basis_market, basis_artifacts = accounting.load_market(
        futures_values, spot_values, funding_values
    )
    flow_market, flow_artifacts = flow_parent.load_market(
        flow_manifest_values, flow_cache_value, funding_values
    )
    if basis_market["symbols"] != flow_market["symbols"]:
        raise ValueError("basis and raw-flow universes differ")
    symbols = list(basis_market["symbols"])
    if len(symbols) != EXPECTED_SYMBOLS:
        raise ValueError(f"confluence V1 requires {EXPECTED_SYMBOLS} symbols")

    basis_lookup = {
        int(timestamp): index
        for index, timestamp in enumerate(basis_market["timestamps"])
    }
    flow_lookup = {
        int(timestamp): index
        for index, timestamp in enumerate(flow_market["timestamps"])
    }
    timestamps = sorted(set(basis_lookup) & set(flow_lookup))
    if len(timestamps) < 1000:
        raise ValueError("too few aligned basis/raw-flow blocks")
    basis_indices = numpy.asarray(
        [basis_lookup[timestamp] for timestamp in timestamps], dtype=numpy.int64
    )
    flow_indices = numpy.asarray(
        [flow_lookup[timestamp] for timestamp in timestamps], dtype=numpy.int64
    )
    closes = numpy.asarray(
        basis_market["closes"][basis_indices], dtype=numpy.float64
    )
    raw_closes = numpy.asarray(
        flow_market["closes"][flow_indices], dtype=numpy.float64
    )
    if not numpy.allclose(closes, raw_closes, rtol=1e-12, atol=1e-12):
        raise ValueError("collector and raw-flow perpetual closes differ")
    funding = numpy.asarray(
        basis_market["funding"][basis_indices], dtype=numpy.float64
    )
    raw_funding = numpy.asarray(
        flow_market["funding"][flow_indices], dtype=numpy.float64
    )
    if not numpy.allclose(funding, raw_funding, rtol=0.0, atol=1e-15):
        raise ValueError("basis and raw-flow funding matrices differ")

    timestamps_array = numpy.asarray(timestamps, dtype=numpy.int64)
    returns = numpy.full_like(closes, numpy.nan)
    for index in range(1, len(timestamps_array)):
        if timestamps_array[index] - timestamps_array[index - 1] == BLOCK_SECONDS:
            returns[index] = closes[index] / closes[index - 1] - 1.0
    gaps = [
        (previous, current)
        for previous, current in zip(timestamps, timestamps[1:])
        if current - previous != BLOCK_SECONDS
    ]
    artifacts = {
        "basis_inputs": basis_artifacts,
        "raw_flow_inputs": flow_artifacts,
        "alignment": {
            "symbols": len(symbols),
            "blocks": len(timestamps),
            "eligible_adjacent_outcomes": int(
                sum(
                    current - previous == BLOCK_SECONDS
                    for previous, current in zip(timestamps, timestamps[1:])
                )
            ),
            "gap_count": len(gaps),
            "gaps": [
                {
                    "previous_close_utc": datetime.datetime.fromtimestamp(
                        previous, parent.UTC
                    ).isoformat(),
                    "next_close_utc": datetime.datetime.fromtimestamp(
                        current, parent.UTC
                    ).isoformat(),
                    "missing_blocks": (current - previous) // BLOCK_SECONDS - 1,
                }
                for previous, current in gaps
            ],
            "first_close_utc": datetime.datetime.fromtimestamp(
                timestamps[0], parent.UTC
            ).isoformat(),
            "last_close_utc": datetime.datetime.fromtimestamp(
                timestamps[-1], parent.UTC
            ).isoformat(),
            "block_seconds": BLOCK_SECONDS,
            "perpetual_close_crosscheck": True,
            "funding_crosscheck": True,
        },
    }
    return {
        "timestamps": timestamps_array,
        "symbols": symbols,
        "closes": closes,
        "spot_closes": numpy.asarray(
            basis_market["spot_closes"][basis_indices], dtype=numpy.float64
        ),
        "returns": returns,
        "funding": funding,
        "signed_flow": numpy.asarray(
            flow_market["signed_flow"][flow_indices], dtype=numpy.float64
        ),
        "quote_volume": numpy.asarray(
            flow_market["quote_volume"][flow_indices], dtype=numpy.float64
        ),
    }, artifacts


def _ascending_ranks(
    values: numpy.ndarray,
    symbols: list[str],
    eligible: list[int],
) -> numpy.ndarray:
    ranks = numpy.full(len(symbols), -1, dtype=numpy.int64)
    ordered = sorted(
        eligible, key=lambda column: (float(values[column]), symbols[column])
    )
    for rank, column in enumerate(ordered):
        ranks[column] = rank
    return ranks


def target_from_features(
    log_basis: numpy.ndarray,
    basis_momentum: numpy.ndarray,
    signed_flow: numpy.ndarray,
    symbols: list[str],
    *,
    enabled_columns: typing.Optional[numpy.ndarray] = None,
) -> numpy.ndarray:
    """Apply the frozen three-way rank intersection to causal features."""

    feature_values = [
        numpy.asarray(log_basis, dtype=numpy.float64),
        numpy.asarray(basis_momentum, dtype=numpy.float64),
        numpy.asarray(signed_flow, dtype=numpy.float64),
    ]
    expected_shape = (len(symbols),)
    if any(values.shape != expected_shape for values in feature_values):
        raise ValueError("confluence feature shape differs from symbol universe")
    if enabled_columns is None:
        enabled_columns = numpy.ones(len(symbols), dtype=bool)
    enabled_columns = numpy.asarray(enabled_columns, dtype=bool)
    if enabled_columns.shape != expected_shape:
        raise ValueError("enabled-column mask has the wrong shape")
    eligible = [
        column
        for column in range(len(symbols))
        if enabled_columns[column]
        and all(math.isfinite(float(values[column])) for values in feature_values)
    ]
    if len(eligible) < 2 * TERTILE_DIVISOR:
        return numpy.zeros(len(symbols), dtype=numpy.float64)
    extreme_count = len(eligible) // TERTILE_DIVISOR
    if extreme_count < 1:
        return numpy.zeros(len(symbols), dtype=numpy.float64)
    basis_rank = _ascending_ranks(feature_values[0], symbols, eligible)
    momentum_rank = _ascending_ranks(feature_values[1], symbols, eligible)
    flow_rank = _ascending_ranks(feature_values[2], symbols, eligible)
    maximum_rank = len(eligible) - 1
    low = set(range(extreme_count))
    high = set(range(len(eligible) - extreme_count, len(eligible)))
    long_candidates = [
        column
        for column in eligible
        if int(basis_rank[column]) in low
        and int(momentum_rank[column]) in high
        and int(flow_rank[column]) in high
    ]
    short_candidates = [
        column
        for column in eligible
        if int(basis_rank[column]) in high
        and int(momentum_rank[column]) in low
        and int(flow_rank[column]) in low
    ]
    if not long_candidates or not short_candidates:
        return numpy.zeros(len(symbols), dtype=numpy.float64)

    long_columns = sorted(
        long_candidates,
        key=lambda column: (
            -(
                maximum_rank
                - int(basis_rank[column])
                + int(momentum_rank[column])
                + int(flow_rank[column])
            ),
            symbols[column],
        ),
    )[:MAXIMUM_ASSETS_PER_SIDE]
    short_columns = sorted(
        short_candidates,
        key=lambda column: (
            -(
                int(basis_rank[column])
                + maximum_rank
                - int(momentum_rank[column])
                + maximum_rank
                - int(flow_rank[column])
            ),
            symbols[column],
        ),
    )[:MAXIMUM_ASSETS_PER_SIDE]
    target = numpy.zeros(len(symbols), dtype=numpy.float64)
    target[long_columns] = SIDE_GROSS_EXPOSURE / len(long_columns)
    target[short_columns] = -SIDE_GROSS_EXPOSURE / len(short_columns)
    return target


def signal_values(market: dict, index: int) -> tuple[numpy.ndarray, ...]:
    """Return only information observable at the frozen decision boundary."""

    if index < FORMATION_BLOCKS or index >= len(market["timestamps"]):
        raise IndexError("confluence target lacks its formation window")
    if (
        int(market["timestamps"][index])
        - int(market["timestamps"][index - FORMATION_BLOCKS])
        != FORMATION_BLOCKS * BLOCK_SECONDS
    ):
        empty = numpy.full(len(market["symbols"]), numpy.nan)
        return empty.copy(), empty.copy(), empty.copy()
    futures = numpy.asarray(market["closes"][index], dtype=numpy.float64)
    spot = numpy.asarray(market["spot_closes"][index], dtype=numpy.float64)
    log_basis = numpy.log(futures) - numpy.log(spot)
    spot_return = (
        spot / market["spot_closes"][index - FORMATION_BLOCKS] - 1.0
    )
    perpetual_return = (
        futures / market["closes"][index - FORMATION_BLOCKS] - 1.0
    )
    basis_momentum = spot_return - perpetual_return
    signed_flow = numpy.sum(
        market["signed_flow"][index - FORMATION_BLOCKS + 1 : index + 1],
        axis=0,
    )
    return (
        numpy.asarray(log_basis, dtype=numpy.float64),
        numpy.asarray(basis_momentum, dtype=numpy.float64),
        numpy.asarray(signed_flow, dtype=numpy.float64),
    )


def target_weights(
    market: dict,
    index: int,
    *,
    enabled_columns: typing.Optional[numpy.ndarray] = None,
) -> numpy.ndarray:
    values = signal_values(market, index)
    return target_from_features(
        *values,
        market["symbols"],
        enabled_columns=enabled_columns,
    )


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
        raise ValueError("confluence target exceeds frozen gross")
    if numpy.any(numpy.abs(net) > 1e-12):
        raise ValueError("confluence target is not nominally neutral")
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
    report = parent.execution_parent.simulate_period(
        market,
        start,
        end,
        cost_multiplier=cost_multiplier,
        enabled_columns=enabled_columns,
        target_matrix=target_matrix,
        include_trajectory=True,
    )
    trajectory = report.pop("_trajectory")
    report["invested_blocks"] = sum(
        float(gross) > 1e-15 for gross in trajectory["gross_exposure"]
    )
    report["invested_block_ratio"] = report["invested_blocks"] / report["blocks"]
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


def _base_gate(report: dict, specification: dict) -> dict:
    profit_factor = report["profit_factor"]
    profit_factor_pass = (
        report["total_return"] > 0
        if profit_factor is None
        else profit_factor >= specification["minimum_profit_factor"]
    )
    return _finish_checks(
        {
            "minimum_blocks": report["blocks"] >= specification["minimum_blocks"],
            "minimum_invested_blocks": (
                report["invested_blocks"]
                >= specification["minimum_invested_blocks"]
            ),
            "positive_total_return": report["total_return"] > 0,
            "minimum_annualized_return": (
                report["annualized_return"]
                >= specification["minimum_annualized_return"]
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
            "both_side_contributions_nonnegative": (
                report["long_additive_contribution"] >= 0
                and report["short_additive_contribution"] >= 0
            ),
            "maximum_absolute_market_beta": (
                abs(report["market_beta"])
                <= specification["maximum_absolute_market_beta"]
            ),
        }
    )


def evaluate_prelock(
    protocol_value,
    futures_values,
    spot_values,
    flow_manifest_values,
    flow_cache_value,
    funding_values,
    output_root_value,
) -> dict:
    """Run the one official fail-closed historical evaluation."""

    protocol_path = pathlib.Path(protocol_value).resolve()
    protocol = write_or_verify_protocol(protocol_path)
    market, artifacts = load_market(
        futures_values,
        spot_values,
        flow_manifest_values,
        flow_cache_value,
        funding_values,
    )
    dependencies = {
        "accounting": pathlib.Path(parent.execution_parent.__file__).resolve(),
        "basis_momentum": pathlib.Path(parent.__file__).resolve(),
        "raw_flow_loader": pathlib.Path(flow_parent.__file__).resolve(),
    }
    artifacts["evaluator"] = _artifact(pathlib.Path(__file__).resolve())
    artifacts["dependencies"] = {
        name: _artifact(path) for name, path in sorted(dependencies.items())
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
    base_development_gate = _base_gate(
        development, protocol["development_gate"]
    )
    development_gate = _finish_checks(
        {
            **base_development_gate["checks"],
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
            "maximum_symbol_absolute_contribution_share": (
                development["maximum_symbol_absolute_contribution_share"]
                <= protocol["development_gate"][
                    "maximum_symbol_absolute_contribution_share"
                ]
            ),
        }
    )

    confirmation = None
    confirmation_stress = None
    confirmation_quarters = None
    confirmation_gate = {
        "passed": False,
        "not_evaluated": not development_gate["passed"],
        "reason": (
            "development_gate_failed" if not development_gate["passed"] else None
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
        base_confirmation_gate = _base_gate(
            confirmation, protocol["confirmation_gate"]
        )
        confirmation_gate = _finish_checks(
            {
                **base_confirmation_gate["checks"],
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
        )

    locked_authorized = development_gate["passed"] and confirmation_gate["passed"]
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
        base_locked_gate = _base_gate(locked, protocol["locked_gate"])
        locked_gate = _finish_checks(
            {
                **base_locked_gate["checks"],
                "stress_total_return_positive": locked_stress["total_return"] > 0,
            }
        )

    historical_candidate = locked_authorized and locked_gate["passed"]
    source_bundle_sha256 = common._json_hash(artifacts)
    output_root = pathlib.Path(output_root_value).resolve()
    experiment = output_root / (
        "relative-value-confluence-v1-"
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
        "created_at": datetime.datetime.now(parent.UTC).isoformat(),
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
    evaluate.add_argument("--flow-manifest", action="append", required=True)
    evaluate.add_argument("--flow-cache", required=True)
    evaluate.add_argument("--funding", action="append", required=True)
    evaluate.add_argument("--output-root", required=True)
    return parser


def main(argv=None) -> int:
    arguments = _parser().parse_args(argv)
    if arguments.command == "write-protocol":
        print(json.dumps(write_or_verify_protocol(arguments.output), indent=2))
        return 0
    if arguments.command == "evaluate-prelock":
        print(
            json.dumps(
                evaluate_prelock(
                    arguments.protocol,
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
