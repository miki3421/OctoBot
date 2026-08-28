"""Frozen seven-day overlapping signed-flow factor replication V2.

V2 corrects only the V1 holding horizon to match the external manuscript. It
is public-data-only, offline and incapable of creating orders.
"""

from __future__ import annotations

import argparse
import datetime
import json
import math
import pathlib
import typing

import numpy

from octobot.ai_strategy_lab import cointegration_pairs_v1 as common
from octobot.ai_strategy_lab import signed_flow_factor_v1 as parent


SCHEMA_VERSION = 1
PROTOCOL_VERSION = "crypto_perpetual_signed_price_volume_flow_v2"
PREREGISTRATION_DATE = "2026-08-28"
HOLDING_BLOCKS = 7 * 3
VINTAGE_FRACTION = 1.0 / HOLDING_BLOCKS
MAXIMUM_ABSOLUTE_MARKET_BETA = 0.20
FORWARD_START_UTC = "2026-08-29T00:00:00+00:00"
UTC = datetime.timezone.utc
DEVELOPMENT_START = parent.DEVELOPMENT_START
DEVELOPMENT_END = parent.DEVELOPMENT_END
CONFIRMATION_START = parent.CONFIRMATION_START
CONFIRMATION_END = parent.CONFIRMATION_END
LOCKED_START = parent.LOCKED_START
LOCKED_END = parent.LOCKED_END
DEVELOPMENT_FOLDS = parent.DEVELOPMENT_FOLDS
CONFIRMATION_QUARTERS = parent.CONFIRMATION_QUARTERS


def frozen_protocol() -> dict:
    """Return the one immutable, result-free V2 specification."""

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
        "parent_protocol": {
            "version": parent.PROTOCOL_VERSION,
            "development_result_known": True,
            "confirmation_materialized": False,
            "locked_test_materialized": False,
            "unchanged_elements": [
                "18-symbol Binance USD-M survivor universe",
                "signed aggressive quote-flow definition",
                "seven-day formation",
                "long high flow and short low flow",
                "three assets per side",
                "0.40 gross per side",
                "funding accounting",
                "6-bps fee and 2-bps slippage per turnover",
                "3x cost stress",
            ],
            "single_correction": (
                "replace V1 next-eight-hour holding with the external "
                "manuscript's following weekly holding period"
            ),
        },
        "external_hypothesis": {
            "title": "Anatomy of Cryptocurrency Perpetual Futures Returns",
            "authors": ["Yi Cao", "Jia Zhai", "Pengfei Luo"],
            "institutional_repository": (
                "https://era.ed.ac.uk/bitstream/handle/1842/43608/"
                "Luo2025.pdf?isAllowed=y&sequence=1"
            ),
            "thesis_doi": "10.7488/era/6141",
            "manuscript_sha256": parent.PAPER_MANUSCRIPT_SHA256,
            "table": 29,
            "formation": "7*3 completed eight-hour blocks",
            "holding": "following rolling weekly period t to t+N",
            "portfolio": "high-minus-low signed price-volume imbalance",
        },
        "hypothesis": {
            "name": "overlapping_weekly_signed_flow_continuation",
            "statement": (
                "seven-day signed quote flow predicts the relative return "
                "of the following seven days rather than only the next block"
            ),
            "direction": "long high signed flow; short low signed flow",
            "opposite_direction_tested": False,
            "long_only_variant_allowed": False,
            "one_configuration_only": True,
        },
        "signal": {
            "source": "same checksummed Binance USD-M raw 1h archives",
            "block_flow": (
                "sum(2 * taker_buy_quote_volume - total_quote_volume)"
            ),
            "formation_blocks": parent.FORMATION_BLOCKS,
            "formation_days": 7,
            "ranking": "ascending flow, deterministic symbol tie-break",
            "selected_assets_per_side": 3,
            "long_side": "highest flow quintile",
            "short_side": "lowest flow quintile",
            "weighting": "equal weight within each vintage side",
            "full_portfolio_side_gross": parent.SIDE_GROSS_EXPOSURE,
            "new_vintage_fraction": VINTAGE_FRACTION,
            "new_vintage_side_gross": (
                parent.SIDE_GROSS_EXPOSURE * VINTAGE_FRACTION
            ),
            "vintage_created": "every completed eight-hour block",
            "holding_blocks": HOLDING_BLOCKS,
            "holding_days": 7,
            "active_vintages_at_steady_state": HOLDING_BLOCKS,
            "aggregate_target": "sum of active vintage weights",
            "opposite_orders_netted_before_cost": True,
            "maximum_portfolio_gross": 2.0 * parent.SIDE_GROSS_EXPOSURE,
            "nominal_net_exposure": 0.0,
            "normalization": None,
            "filters": None,
            "future_values_used": False,
        },
        "period_boundary": {
            "opening": (
                "reconstruct 21 live vintages from completed pre-period "
                "signals, then open aggregate target from flat with cost"
            ),
            "closing": "flatten aggregate target with cost",
            "cross_period_pnl_imported": False,
        },
        "economics": {
            "traded_instrument": "perpetual only",
            "price_pnl": "next-block close-to-close on aggregate prior target",
            "funding_pnl": (
                "negative aggregate weight times actual signed settlement"
            ),
            "fee_per_turnover": parent.FEE_PER_TURNOVER,
            "slippage_per_turnover": parent.SLIPPAGE_PER_TURNOVER,
            "stress_cost_multiplier": parent.STRESS_COST_MULTIPLIER,
            "maker_fill_assumptions": False,
            "cost_on_netted_weight_change": True,
        },
        "validation": {
            "expected_symbols": parent.EXPECTED_SYMBOLS,
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
            "confirmation_status": "sealed_for_signed_flow_family",
            "confirmation_quarters": [
                [start.isoformat(), end.isoformat()]
                for start, end in CONFIRMATION_QUARTERS
            ],
            "locked_final_test": [
                LOCKED_START.isoformat(),
                LOCKED_END.isoformat(),
            ],
            "locked_status": "sealed_for_signed_flow_family",
            "locked_policy": (
                "do not calculate confirmation unless V2 development passes; "
                "do not calculate lock unless V2 confirmation passes"
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
            "maximum_absolute_market_beta": (
                MAXIMUM_ABSOLUTE_MARKET_BETA
            ),
            "minimum_positive_leave_one_symbol_out": 15,
            "required_leave_one_symbol_out": parent.EXPECTED_SYMBOLS,
            "stress_total_return_positive": True,
            "minimum_stress_sharpe": 0.50,
            "minimum_average_gross_exposure": 0.50,
            "maximum_symbol_absolute_contribution_share": 0.35,
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
            "maximum_absolute_market_beta": (
                MAXIMUM_ABSOLUTE_MARKET_BETA
            ),
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
            "maximum_absolute_market_beta": (
                MAXIMUM_ABSOLUTE_MARKET_BETA
            ),
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
            "V2 is the second signed-flow implementation; only the externally "
            "specified weekly holding horizon changes, and promotion relies "
            "on the still-sealed 2025 and 2026 periods"
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
            raise ValueError("persisted signed-flow V2 protocol differs")
        return persisted
    common._atomic_json(path, payload)
    return payload


def sleeve_weights(
    market: dict,
    index: int,
    *,
    enabled_columns: typing.Optional[numpy.ndarray] = None,
) -> numpy.ndarray:
    """Return one externally specified high-minus-low vintage."""

    if index < parent.FORMATION_BLOCKS - 1:
        raise IndexError("signed-flow V2 sleeve lacks formation history")
    if index >= len(market["timestamps"]):
        raise IndexError("signed-flow V2 sleeve exceeds market")
    if enabled_columns is None:
        enabled_columns = numpy.ones(len(market["symbols"]), dtype=bool)
    enabled_columns = numpy.asarray(enabled_columns, dtype=bool)
    if enabled_columns.shape != (len(market["symbols"]),):
        raise ValueError("enabled-column mask has the wrong shape")
    flow = numpy.sum(
        market["signed_flow"][
            index - parent.FORMATION_BLOCKS + 1 : index + 1
        ],
        axis=0,
    )
    eligible = [
        column
        for column, value in enumerate(flow)
        if enabled_columns[column] and math.isfinite(float(value))
    ]
    if len(eligible) < 10:
        return numpy.zeros(len(market["symbols"]), dtype=numpy.float64)
    ordered = sorted(
        eligible,
        key=lambda column: (float(flow[column]), market["symbols"][column]),
    )
    count = max(
        1, int(math.floor(len(ordered) * parent.SELECTION_FRACTION))
    )
    short_columns = ordered[:count]
    long_columns = ordered[-count:]
    result = numpy.zeros(len(market["symbols"]), dtype=numpy.float64)
    result[long_columns] = parent.SIDE_GROSS_EXPOSURE / len(long_columns)
    result[short_columns] = -parent.SIDE_GROSS_EXPOSURE / len(short_columns)
    return result


def build_target_matrix(
    market: dict,
    *,
    enabled_columns: typing.Optional[numpy.ndarray] = None,
) -> numpy.ndarray:
    """Net all 21 live weekly vintages before applying execution costs."""

    row_count = len(market["timestamps"])
    column_count = len(market["symbols"])
    sleeves = numpy.zeros((row_count, column_count), dtype=numpy.float64)
    for index in range(parent.FORMATION_BLOCKS - 1, row_count):
        sleeves[index] = sleeve_weights(
            market, index, enabled_columns=enabled_columns
        )
    cumulative = numpy.vstack(
        (
            numpy.zeros((1, column_count), dtype=numpy.float64),
            numpy.cumsum(sleeves, axis=0),
        )
    )
    targets = numpy.zeros_like(sleeves)
    first = parent.FORMATION_BLOCKS - 1 + HOLDING_BLOCKS - 1
    for index in range(first, row_count):
        targets[index] = (
            cumulative[index + 1]
            - cumulative[index + 1 - HOLDING_BLOCKS]
        ) * VINTAGE_FRACTION
    gross = numpy.sum(numpy.abs(targets), axis=1)
    if numpy.any(gross > 2.0 * parent.SIDE_GROSS_EXPOSURE + 1e-12):
        raise ValueError("signed-flow V2 target exceeds frozen gross")
    if numpy.any(numpy.abs(numpy.sum(targets, axis=1)) > 1e-12):
        raise ValueError("signed-flow V2 target is not nominally neutral")
    return targets


def aggregate_target(
    market: dict,
    index: int,
    *,
    enabled_columns: typing.Optional[numpy.ndarray] = None,
) -> numpy.ndarray:
    return build_target_matrix(
        market, enabled_columns=enabled_columns
    )[index]


def _side_costs(previous, target, per_turnover_cost) -> tuple[float, float]:
    return parent._side_costs(previous, target, per_turnover_cost)


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
    if start.tzinfo is None or end.tzinfo is None or start >= end:
        raise ValueError("evaluation interval must be ordered and timezone-aware")
    if cost_multiplier < 1.0:
        raise ValueError("cost multiplier must be at least one")
    if target_matrix is None:
        target_matrix = build_target_matrix(
            market, enabled_columns=enabled_columns
        )
    target_matrix = numpy.asarray(target_matrix, dtype=numpy.float64)
    expected_shape = (
        len(market["timestamps"]),
        len(market["symbols"]),
    )
    if target_matrix.shape != expected_shape:
        raise ValueError("signed-flow V2 target matrix shape differs")
    start_timestamp = int(start.timestamp())
    end_timestamp = int(end.timestamp())
    indices = [
        index
        for index, timestamp in enumerate(market["timestamps"])
        if start_timestamp <= int(timestamp) < end_timestamp
        and index + 1 < len(market["timestamps"])
    ]
    minimum_index = parent.FORMATION_BLOCKS + HOLDING_BLOCKS - 2
    if not indices or indices[0] < minimum_index:
        raise ValueError("evaluation interval or vintage warmup is absent")

    weights = numpy.zeros(len(market["symbols"]), dtype=numpy.float64)
    contribution = numpy.zeros_like(weights)
    equity = 1.0
    per_turnover_cost = cost_multiplier * (
        parent.FEE_PER_TURNOVER + parent.SLIPPAGE_PER_TURNOVER
    )
    total_turnover = 0.0
    total_cost = 0.0
    total_price = 0.0
    total_funding = 0.0
    long_contribution = 0.0
    short_contribution = 0.0
    rebalance_events = 0
    equities = []
    block_returns = []
    market_returns = []
    applied_weights = []
    end_timestamps = []

    for index in indices:
        before = equity
        target = target_matrix[index]
        changes = numpy.abs(target - weights)
        cost_by_symbol = changes * per_turnover_cost
        turnover = float(numpy.sum(changes))
        cost = float(numpy.sum(cost_by_symbol))
        equity *= 1.0 - cost
        contribution -= cost_by_symbol
        long_cost, short_cost = _side_costs(
            weights, target, per_turnover_cost
        )
        long_contribution -= long_cost
        short_contribution -= short_cost
        if turnover > 1e-15:
            rebalance_events += 1
        total_turnover += turnover
        total_cost += cost

        price = target * market["returns"][index + 1]
        funding = -target * market["funding"][index + 1]
        pnl = price + funding
        equity *= 1.0 + float(numpy.sum(pnl))
        if equity <= 0:
            raise ValueError("signed-flow V2 equity became non-positive")
        contribution += pnl
        total_price += float(numpy.sum(price))
        total_funding += float(numpy.sum(funding))
        long_contribution += float(numpy.sum(pnl[target > 0]))
        short_contribution += float(numpy.sum(pnl[target < 0]))
        weights = target.copy()

        equities.append(equity)
        block_returns.append(equity / before - 1.0)
        market_returns.append(float(numpy.mean(market["returns"][index + 1])))
        applied_weights.append(weights.copy())
        end_timestamps.append(int(market["timestamps"][index + 1]))

    closing_cost_by_symbol = numpy.abs(weights) * per_turnover_cost
    closing_turnover = float(numpy.sum(numpy.abs(weights)))
    closing_cost = float(numpy.sum(closing_cost_by_symbol))
    if closing_cost:
        equity *= 1.0 - closing_cost
        contribution -= closing_cost_by_symbol
        long_cost, short_cost = _side_costs(
            weights, numpy.zeros_like(weights), per_turnover_cost
        )
        long_contribution -= long_cost
        short_contribution -= short_cost
        total_turnover += closing_turnover
        total_cost += closing_cost
        previous_equity = equities[-2] if len(equities) > 1 else 1.0
        equities[-1] = equity
        block_returns[-1] = equity / previous_equity - 1.0

    equity_values = numpy.asarray(equities, dtype=numpy.float64)
    return_values = numpy.asarray(block_returns, dtype=numpy.float64)
    market_values = numpy.asarray(market_returns, dtype=numpy.float64)
    weight_values = numpy.asarray(applied_weights, dtype=numpy.float64)
    datetimes = [
        datetime.datetime.fromtimestamp(value, UTC)
        for value in end_timestamps
    ]
    accounting_datetimes = [
        datetime.datetime.fromtimestamp(value - 1, UTC)
        for value in end_timestamps
    ]
    peaks = numpy.maximum.accumulate(
        numpy.concatenate((numpy.ones(1), equity_values))
    )[1:]
    drawdowns = 1.0 - equity_values / peaks
    monthly = parent._period_returns(
        accounting_datetimes, equity_values, "%Y-%m"
    )
    quarterly = parent._quarter_returns(
        accounting_datetimes, equity_values
    )
    elapsed_years = len(indices) / (3.0 * 365.25)
    market_variance = float(numpy.var(market_values))
    market_beta = (
        float(numpy.cov(return_values, market_values, ddof=0)[0, 1])
        / market_variance
        if market_variance > 0
        else 0.0
    )
    positive = float(numpy.sum(return_values[return_values > 0]))
    negative = float(-numpy.sum(return_values[return_values < 0]))
    absolute_contribution = numpy.abs(contribution)
    contribution_total = float(numpy.sum(absolute_contribution))
    maximum_share = (
        float(numpy.max(absolute_contribution) / contribution_total)
        if contribution_total > 0
        else 1.0
    )
    gross_values = numpy.sum(numpy.abs(weight_values), axis=1)
    trajectory = {
        "decision_timestamps": [
            datetime.datetime.fromtimestamp(
                int(market["timestamps"][index]), UTC
            ).isoformat()
            for index in indices
        ],
        "end_timestamps": [value.isoformat() for value in datetimes],
        "equity": equity_values.tolist(),
        "block_return": return_values.tolist(),
        "market_return": market_values.tolist(),
        "gross_exposure": gross_values.tolist(),
        "net_exposure": numpy.sum(weight_values, axis=1).tolist(),
    }
    report = {
        "start_decision_utc": datetime.datetime.fromtimestamp(
            int(market["timestamps"][indices[0]]), UTC
        ).isoformat(),
        "end_outcome_utc": datetimes[-1].isoformat(),
        "blocks": len(indices),
        "cost_multiplier": cost_multiplier,
        "total_return": float(equity - 1.0),
        "annualized_return": (
            float(equity ** (1.0 / elapsed_years) - 1.0)
            if elapsed_years > 0 and equity > 0
            else 0.0
        ),
        "annualized_volatility": float(
            numpy.std(return_values) * math.sqrt(3.0 * 365.0)
        ),
        "sharpe_zero_rate": (
            float(
                numpy.mean(return_values)
                / numpy.std(return_values)
                * math.sqrt(3.0 * 365.0)
            )
            if numpy.std(return_values) > 0
            else 0.0
        ),
        "maximum_drawdown": float(numpy.max(drawdowns)),
        "profit_factor": positive / negative if negative > 0 else None,
        "positive_month_ratio": (
            sum(value > 0 for value in monthly.values()) / len(monthly)
            if monthly
            else 0.0
        ),
        "positive_quarters": sum(value > 0 for value in quarterly.values()),
        "monthly_returns": monthly,
        "quarterly_returns": quarterly,
        "rebalance_events": rebalance_events,
        "total_turnover": float(total_turnover),
        "total_cost_return": float(total_cost),
        "total_price_return": float(total_price),
        "total_funding_return": float(total_funding),
        "long_additive_contribution": float(long_contribution),
        "short_additive_contribution": float(short_contribution),
        "market_beta": market_beta,
        "average_gross_exposure": float(numpy.mean(gross_values)),
        "maximum_gross_exposure": float(numpy.max(gross_values)),
        "maximum_absolute_net_exposure": float(
            numpy.max(numpy.abs(numpy.sum(weight_values, axis=1)))
        ),
        "by_symbol_additive_contribution": {
            symbol: float(value)
            for symbol, value in zip(market["symbols"], contribution)
        },
        "maximum_symbol_absolute_contribution_share": maximum_share,
        "trajectory_sha256": common._json_hash(trajectory),
    }
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
    checks = {
        "minimum_blocks": report["blocks"] >= specification["minimum_blocks"],
        "positive_total_return": report["total_return"] > 0,
        "minimum_annualized_return": (
            report["annualized_return"]
            >= specification["minimum_annualized_return"]
        ),
        "minimum_sharpe": (
            report["sharpe_zero_rate"] >= specification["minimum_sharpe"]
        ),
        "maximum_drawdown": (
            report["maximum_drawdown"] <= specification["maximum_drawdown"]
        ),
        "minimum_positive_month_ratio": (
            report["positive_month_ratio"]
            >= specification["minimum_positive_month_ratio"]
        ),
        "maximum_absolute_market_beta": (
            abs(report["market_beta"])
            <= specification["maximum_absolute_market_beta"]
        ),
    }
    return _finish_checks(checks)


def evaluate_prelock(
    protocol_value,
    manifest_values,
    cache_value,
    funding_values,
    output_root_value,
) -> dict:
    protocol_path = pathlib.Path(protocol_value).resolve()
    protocol = write_or_verify_protocol(protocol_path)
    market, artifacts = parent.load_market(
        manifest_values, cache_value, funding_values
    )
    artifacts["evaluator"] = {
        "path": str(pathlib.Path(__file__).resolve()),
        "bytes": pathlib.Path(__file__).stat().st_size,
        "sha256": common._sha256(pathlib.Path(__file__).resolve()),
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
        cost_multiplier=parent.STRESS_COST_MULTIPLIER,
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
            >= protocol["development_gate"][
                "minimum_average_gross_exposure"
            ]
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
            cost_multiplier=parent.STRESS_COST_MULTIPLIER,
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
                >= protocol["confirmation_gate"][
                    "minimum_positive_quarters"
                ]
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
            cost_multiplier=parent.STRESS_COST_MULTIPLIER,
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
        "signed-flow-v2-"
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
        "development_positive_leave_one_symbol_out": (
            positive_leave_one_out
        ),
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
    evaluate.add_argument("--manifest", action="append", required=True)
    evaluate.add_argument("--archive-cache", required=True)
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
        args.manifest,
        args.archive_cache,
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
