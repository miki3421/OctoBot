"""Frozen, research-only perpetual/spot cross-sectional basis factor V1.

The spot market supplies a point-in-time ranking signal.  Only perpetual
returns are traded in the simulation, with signed funding and explicit
turnover costs.  This module has no exchange client and cannot place orders.
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
from octobot.ai_strategy_lab import dataset as dataset_module
from octobot.ai_strategy_lab import funding as funding_module
from octobot.ai_strategy_lab import trend as trend_module


SCHEMA_VERSION = 1
PROTOCOL_VERSION = "crypto_perpetual_spot_basis_factor_v1"
PREREGISTRATION_DATE = "2026-08-28"
EXPECTED_SYMBOLS = 18
SELECTION_FRACTION = 1.0 / 3.0
SIDE_GROSS_EXPOSURE = 0.40
FEE_PER_TURNOVER = 0.0006
SLIPPAGE_PER_TURNOVER = 0.0002
STRESS_COST_MULTIPLIER = 3.0
DEVELOPMENT_START = datetime.date(2022, 7, 1)
DEVELOPMENT_END = datetime.date(2025, 1, 1)
CONFIRMATION_START = DEVELOPMENT_END
CONFIRMATION_END = datetime.date(2026, 1, 1)
LOCKED_START = CONFIRMATION_END
LOCKED_END = datetime.date(2026, 7, 1)
FORWARD_START_UTC = "2026-08-29T00:00:00+00:00"
DEVELOPMENT_FOLDS = (
    (datetime.date(2022, 7, 1), datetime.date(2023, 1, 1)),
    (datetime.date(2023, 1, 1), datetime.date(2023, 7, 1)),
    (datetime.date(2023, 7, 1), datetime.date(2024, 1, 1)),
    (datetime.date(2024, 1, 1), datetime.date(2024, 7, 1)),
    (datetime.date(2024, 7, 1), datetime.date(2025, 1, 1)),
)
CONFIRMATION_QUARTERS = (
    (datetime.date(2025, 1, 1), datetime.date(2025, 4, 1)),
    (datetime.date(2025, 4, 1), datetime.date(2025, 7, 1)),
    (datetime.date(2025, 7, 1), datetime.date(2025, 10, 1)),
    (datetime.date(2025, 10, 1), datetime.date(2026, 1, 1)),
)


def frozen_protocol() -> dict:
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
        "hypothesis": {
            "name": "cross_sectional_perpetual_spot_basis_catch_up",
            "statement": (
                "perpetuals that are cheap relative to same-venue spot can "
                "outperform perpetuals that are rich relative to spot after "
                "signed funding, taker fees and slippage"
            ),
            "economic_mechanism": (
                "cross-sectional spot-to-perpetual information transmission "
                "and compensation for basis risk"
            ),
            "direction": "long high spot/perpetual basis; short low basis",
            "opposite_direction_tested": False,
            "one_configuration_only": True,
            "historical_periods_are_diagnostic_reuse": True,
        },
        "signal": {
            "basis": "spot_close / perpetual_close - 1",
            "ranking": "ascending basis, deterministic symbol tie-break",
            "selection_fraction_per_side": SELECTION_FRACTION,
            "long_side": "highest basis tercile",
            "short_side": "lowest basis tercile",
            "weighting": "equal weight within each side",
            "side_gross_exposure": SIDE_GROSS_EXPOSURE,
            "nominal_net_exposure": 0.0,
            "rebalance": "every UTC daily close; applies to next-day return",
            "spot_is_signal_only": True,
            "future_prices_or_funding_not_used": True,
        },
        "economics": {
            "traded_instrument": "perpetual only",
            "price_pnl": "daily perpetual close-to-close on prior weights",
            "funding_pnl": "negative prior weight times signed settlement",
            "fee_per_turnover": FEE_PER_TURNOVER,
            "slippage_per_turnover": SLIPPAGE_PER_TURNOVER,
            "stress_cost_multiplier": STRESS_COST_MULTIPLIER,
            "maker_fill_assumptions": False,
            "forced_flatten_at_each_evaluation_end": True,
            "maximum_portfolio_gross": 2.0 * SIDE_GROSS_EXPOSURE,
        },
        "validation": {
            "expected_symbols": EXPECTED_SYMBOLS,
            "development": [
                DEVELOPMENT_START.isoformat(),
                DEVELOPMENT_END.isoformat(),
            ],
            "development_end_exclusive": True,
            "development_folds": [
                [start.isoformat(), end.isoformat()]
                for start, end in DEVELOPMENT_FOLDS
            ],
            "confirmation": [
                CONFIRMATION_START.isoformat(),
                CONFIRMATION_END.isoformat(),
            ],
            "confirmation_end_exclusive": True,
            "confirmation_quarters": [
                [start.isoformat(), end.isoformat()]
                for start, end in CONFIRMATION_QUARTERS
            ],
            "locked_final_test": [
                LOCKED_START.isoformat(),
                LOCKED_END.isoformat(),
            ],
            "locked_end_exclusive": True,
            "locked_policy": (
                "do not calculate confirmation unless development passes; "
                "do not calculate the lock unless confirmation also passes"
            ),
            "survivorship_limitation": (
                "fixed archive of contracts surviving to archive end"
            ),
        },
        "development_gate": {
            "minimum_days": 300,
            "positive_total_return": True,
            "minimum_annualized_return": 0.08,
            "minimum_sharpe": 1.00,
            "maximum_drawdown": 0.15,
            "minimum_positive_month_ratio": 0.55,
            "minimum_positive_folds": 4,
            "required_folds": len(DEVELOPMENT_FOLDS),
            "both_side_contributions_nonnegative": True,
            "maximum_absolute_market_beta": 0.30,
            "minimum_positive_leave_one_symbol_out": 15,
            "required_leave_one_symbol_out": EXPECTED_SYMBOLS,
            "stress_total_return_positive": True,
        },
        "confirmation_gate": {
            "minimum_days": 300,
            "positive_total_return": True,
            "minimum_annualized_return": 0.04,
            "minimum_sharpe": 0.50,
            "maximum_drawdown": 0.15,
            "minimum_positive_month_ratio": 0.50,
            "minimum_positive_quarters": 3,
            "required_quarters": len(CONFIRMATION_QUARTERS),
            "both_side_contributions_nonnegative": True,
            "maximum_absolute_market_beta": 0.30,
            "stress_total_return_positive": True,
        },
        "locked_gate": {
            "minimum_days": 150,
            "positive_total_return": True,
            "minimum_annualized_return": 0.04,
            "minimum_sharpe": 0.50,
            "maximum_drawdown": 0.15,
            "minimum_positive_month_ratio": 0.50,
            "both_side_contributions_nonnegative": True,
            "maximum_absolute_market_beta": 0.30,
            "stress_total_return_positive": True,
        },
        "forward_gate": {
            "start_utc": FORWARD_START_UTC,
            "minimum_calendar_days": 180,
            "minimum_observed_days": 165,
            "no_refit": True,
            "same_signal_and_costs": True,
            "required_before_shadow_or_paper": True,
        },
        "multiple_testing_disclosure": (
            "one basis definition, one daily rebalance, one rank direction, "
            "one tercile allocation and one cost model are evaluated"
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
            raise ValueError("persisted basis-factor V1 protocol differs")
        return persisted
    common._atomic_json(path, payload)
    return payload


def load_market(
    futures_collectors: typing.Iterable[typing.Union[str, pathlib.Path]],
    spot_collectors: typing.Iterable[typing.Union[str, pathlib.Path]],
    funding_paths: typing.Iterable[typing.Union[str, pathlib.Path]],
) -> tuple[dict, dict]:
    futures_paths = [
        pathlib.Path(value).resolve() for value in futures_collectors
    ]
    if not futures_paths:
        raise ValueError("at least one futures collector is required")
    spot_paths = [
        pathlib.Path(value).resolve() for value in spot_collectors
    ]
    if not spot_paths:
        raise ValueError("at least one spot collector is required")
    futures = dataset_module.load_collector_series(
        futures_paths, required_time_frames=("1h",)
    )
    spot = dataset_module.load_collector_series(
        spot_paths, required_time_frames=("1h",)
    )
    funding = {}
    funding_artifacts = []
    for value in funding_paths:
        path = pathlib.Path(value).resolve()
        loaded = funding_module.load_funding(path)
        overlap = set(funding) & set(loaded)
        if overlap:
            raise ValueError(
                f"funding symbols appear in multiple inputs: {sorted(overlap)}"
            )
        funding.update(loaded)
        funding_artifacts.append(_artifact(path))

    futures_by_base = {
        symbol.split("/", 1)[0]: symbol for symbol in futures
    }
    spot_by_base = {symbol.split("/", 1)[0]: symbol for symbol in spot}
    bases = sorted(set(futures_by_base) & set(spot_by_base))
    pairs = [
        (base, futures_by_base[base], spot_by_base[base])
        for base in bases
        if futures_by_base[base] in funding
    ]
    if len(pairs) != EXPECTED_SYMBOLS:
        raise ValueError(
            f"basis-factor V1 requires exactly {EXPECTED_SYMBOLS} pairs"
        )

    selected_futures = {future for _, future, _ in pairs}
    market = trend_module._build_daily_market(
        {
            symbol: futures[symbol]["1h"]
            for symbol in selected_futures
        },
        {symbol: funding[symbol] for symbol in selected_futures},
    )
    spot_symbol_by_future = {
        future: spot_symbol for _, future, spot_symbol in pairs
    }
    futures_daily = {
        future: _strict_utc_daily_closes(futures[future]["1h"])
        for future in market["symbols"]
    }
    spot_daily = {
        future: _strict_utc_daily_closes(
            spot[spot_symbol_by_future[future]]["1h"]
        )
        for future in market["symbols"]
    }
    keep = [
        index
        for index, date in enumerate(market["dates"])
        if all(
            date in spot_daily[symbol] and date in futures_daily[symbol]
            for symbol in market["symbols"]
        )
    ]
    if len(keep) < 250:
        raise ValueError("fewer than 250 aligned spot/perpetual days")
    aligned_dates = [market["dates"][index] for index in keep]
    gaps = [
        (previous, current)
        for previous, current in zip(aligned_dates, aligned_dates[1:])
        if current - previous != datetime.timedelta(days=1)
    ]
    if gaps:
        raise ValueError(f"aligned daily market contains a date gap: {gaps[0]}")
    market = {
        "dates": aligned_dates,
        "symbols": market["symbols"],
        "closes": market["closes"][keep],
        "returns": market["returns"][keep],
        "funding": market["funding"][keep],
        "spot_closes": numpy.asarray(
            [
                [
                    spot_daily[symbol][market["dates"][index]]
                    for symbol in market["symbols"]
                ]
                for index in keep
            ],
            dtype=numpy.float64,
        ),
    }
    if (
        numpy.any(market["spot_closes"] <= 0)
        or not numpy.all(numpy.isfinite(market["spot_closes"]))
    ):
        raise ValueError("aligned spot close matrix is invalid")
    artifacts = {
        "futures_collectors": [_artifact(path) for path in futures_paths],
        "spot_collectors": [_artifact(path) for path in spot_paths],
        "funding": funding_artifacts,
        "pair_map": [
            {
                "base": base,
                "futures_symbol": future,
                "spot_symbol": spot_symbol,
            }
            for base, future, spot_symbol in pairs
        ],
    }
    return market, artifacts


def _strict_utc_daily_closes(series) -> dict:
    """Return only completed 23:00--24:00 UTC hourly candles."""

    result = {}
    for candle, close_timestamp in zip(series.values, series.close_times):
        closed_at = datetime.datetime.fromtimestamp(
            int(close_timestamp), datetime.timezone.utc
        )
        if closed_at.time() != datetime.time.min:
            continue
        date = closed_at.date() - datetime.timedelta(days=1)
        result[date] = float(candle[4])
    return result


def _artifact(path: pathlib.Path) -> dict:
    return {
        "path": str(path),
        "bytes": path.stat().st_size,
        "sha256": common._sha256(path),
    }


def target_weights(market: dict, index: int) -> numpy.ndarray:
    """Rank only spot and perpetual closes known at ``index``."""

    if index < 0 or index >= len(market["dates"]):
        raise IndexError("basis target index is outside the market")
    futures = numpy.asarray(market["closes"][index], dtype=numpy.float64)
    spot = numpy.asarray(market["spot_closes"][index], dtype=numpy.float64)
    basis = spot / futures - 1.0
    eligible = [
        column
        for column, value in enumerate(basis)
        if futures[column] > 0
        and spot[column] > 0
        and math.isfinite(float(value))
    ]
    if len(eligible) < 6:
        return numpy.zeros(len(market["symbols"]), dtype=numpy.float64)
    ordered = sorted(
        eligible,
        key=lambda column: (float(basis[column]), market["symbols"][column]),
    )
    count = max(1, int(math.floor(len(ordered) * SELECTION_FRACTION)))
    short_columns = ordered[:count]
    long_columns = ordered[-count:]
    target = numpy.zeros(len(market["symbols"]), dtype=numpy.float64)
    target[long_columns] = SIDE_GROSS_EXPOSURE / len(long_columns)
    target[short_columns] = -SIDE_GROSS_EXPOSURE / len(short_columns)
    return target


def _period_returns(dates, equity, pattern: str) -> dict:
    endpoints = {}
    for date, value in zip(dates, equity):
        endpoints[date.strftime(pattern)] = float(value)
    result = {}
    previous = 1.0
    for period, value in sorted(endpoints.items()):
        result[period] = value / previous - 1.0
        previous = value
    return result


def _quarter_returns(dates, equity) -> dict:
    endpoints = {}
    for date, value in zip(dates, equity):
        quarter = (date.month - 1) // 3 + 1
        endpoints[f"{date.year}-Q{quarter}"] = float(value)
    result = {}
    previous = 1.0
    for period, value in sorted(endpoints.items()):
        result[period] = value / previous - 1.0
        previous = value
    return result


def _side_costs(
    previous: numpy.ndarray,
    target: numpy.ndarray,
    per_turnover_cost: float,
) -> tuple[float, float]:
    """Allocate turnover costs to the side whose exposure is traded."""

    long_cost = 0.0
    short_cost = 0.0
    for old, new in zip(previous, target):
        if old * new < 0:
            if old > 0:
                long_cost += abs(float(old)) * per_turnover_cost
                short_cost += abs(float(new)) * per_turnover_cost
            else:
                short_cost += abs(float(old)) * per_turnover_cost
                long_cost += abs(float(new)) * per_turnover_cost
            continue
        cost = abs(float(new - old)) * per_turnover_cost
        direction = new if new else old
        if direction > 0:
            long_cost += cost
        elif direction < 0:
            short_cost += cost
    return long_cost, short_cost


def simulate_period(
    market: dict,
    start: datetime.date,
    end: datetime.date,
    *,
    cost_multiplier: float = 1.0,
    include_trajectory: bool = False,
) -> dict:
    if cost_multiplier < 1.0:
        raise ValueError("cost multiplier must be at least one")
    indices = [
        index
        for index, date in enumerate(market["dates"])
        if start <= date < end
    ]
    if not indices:
        raise ValueError("evaluation interval is absent from the market")
    first_index, final_index = indices[0], indices[-1]
    if first_index < 1:
        raise ValueError("evaluation lacks a prior signal day")

    weights = target_weights(market, first_index - 1)
    opening_turnover = float(numpy.sum(numpy.abs(weights)))
    per_turnover_cost = cost_multiplier * (
        FEE_PER_TURNOVER + SLIPPAGE_PER_TURNOVER
    )
    opening_cost = opening_turnover * per_turnover_cost
    equity = 1.0 - opening_cost
    if equity <= 0:
        raise ValueError("basis-factor equity became non-positive")
    contribution = -numpy.abs(weights) * per_turnover_cost
    opening_long_cost, opening_short_cost = _side_costs(
        numpy.zeros_like(weights), weights, per_turnover_cost
    )
    long_contribution = -opening_long_cost
    short_contribution = -opening_short_cost
    total_cost = opening_cost
    total_turnover = opening_turnover
    total_funding = 0.0
    total_price = 0.0
    rebalance_events = int(opening_turnover > 0)
    equities = []
    daily_returns = []
    market_returns = []
    applied_weights = []

    for index in range(first_index, final_index + 1):
        before = 1.0 if index == first_index else equity
        realized_weights = weights.copy()
        price = weights * market["returns"][index]
        funding = -weights * market["funding"][index]
        pnl = price + funding
        equity *= 1.0 + float(numpy.sum(pnl))
        contribution += pnl
        total_price += float(numpy.sum(price))
        total_funding += float(numpy.sum(funding))
        long_contribution += float(numpy.sum(pnl[weights > 0]))
        short_contribution += float(numpy.sum(pnl[weights < 0]))

        target = target_weights(market, index)
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
        if turnover > 0:
            rebalance_events += 1
        total_turnover += turnover
        total_cost += cost
        weights = target
        if equity <= 0:
            raise ValueError("basis-factor equity became non-positive")
        equities.append(equity)
        daily_returns.append(equity / before - 1.0)
        market_returns.append(float(numpy.mean(market["returns"][index])))
        applied_weights.append(realized_weights)

    closing_changes = numpy.abs(weights)
    closing_cost_by_symbol = closing_changes * per_turnover_cost
    closing_turnover = float(numpy.sum(closing_changes))
    closing_cost = float(numpy.sum(closing_cost_by_symbol))
    if closing_cost:
        equity *= 1.0 - closing_cost
        contribution -= closing_cost_by_symbol
        long_contribution -= float(
            numpy.sum(closing_cost_by_symbol[weights > 0])
        )
        short_contribution -= float(
            numpy.sum(closing_cost_by_symbol[weights < 0])
        )
        total_turnover += closing_turnover
        total_cost += closing_cost
        previous_equity = equities[-2] if len(equities) > 1 else 1.0
        equities[-1] = equity
        daily_returns[-1] = equity / previous_equity - 1.0

    dates = market["dates"][first_index : final_index + 1]
    equity_values = numpy.asarray(equities, dtype=numpy.float64)
    daily_values = numpy.asarray(daily_returns, dtype=numpy.float64)
    market_values = numpy.asarray(market_returns, dtype=numpy.float64)
    weight_values = numpy.asarray(applied_weights, dtype=numpy.float64)
    peaks = numpy.maximum.accumulate(
        numpy.concatenate((numpy.ones(1), equity_values))
    )[1:]
    drawdowns = 1.0 - equity_values / peaks
    monthly = _period_returns(dates, equity_values, "%Y-%m")
    quarterly = _quarter_returns(dates, equity_values)
    elapsed_years = len(dates) / 365.25
    market_variance = float(numpy.var(market_values))
    market_beta = (
        float(numpy.cov(daily_values, market_values, ddof=0)[0, 1])
        / market_variance
        if market_variance > 0
        else 0.0
    )
    positive = float(numpy.sum(daily_values[daily_values > 0]))
    negative = float(-numpy.sum(daily_values[daily_values < 0]))
    trajectory = {
        "dates": [date.isoformat() for date in dates],
        "equity": equity_values.tolist(),
        "daily_return": daily_values.tolist(),
        "market_return": market_values.tolist(),
        "gross_exposure": numpy.sum(numpy.abs(weight_values), axis=1).tolist(),
        "net_exposure": numpy.sum(weight_values, axis=1).tolist(),
    }
    report = {
        "start_date": dates[0].isoformat(),
        "end_date": dates[-1].isoformat(),
        "days": len(dates),
        "cost_multiplier": cost_multiplier,
        "total_return": float(equity - 1.0),
        "annualized_return": (
            float(equity ** (1.0 / elapsed_years) - 1.0)
            if elapsed_years > 0 and equity > 0
            else 0.0
        ),
        "annualized_volatility": float(
            numpy.std(daily_values) * math.sqrt(365.0)
        ),
        "sharpe_zero_rate": (
            float(
                numpy.mean(daily_values)
                / numpy.std(daily_values)
                * math.sqrt(365.0)
            )
            if numpy.std(daily_values) > 0
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
        "average_gross_exposure": float(
            numpy.mean(numpy.sum(numpy.abs(weight_values), axis=1))
        ),
        "maximum_gross_exposure": float(
            numpy.max(numpy.sum(numpy.abs(weight_values), axis=1))
        ),
        "maximum_absolute_net_exposure": float(
            numpy.max(numpy.abs(numpy.sum(weight_values, axis=1)))
        ),
        "by_symbol_additive_contribution": {
            symbol: float(value)
            for symbol, value in zip(market["symbols"], contribution)
        },
        "trajectory_sha256": common._json_hash(trajectory),
    }
    if include_trajectory:
        report["_trajectory"] = trajectory
    return report


def _drop_market_column(market: dict, column: int) -> dict:
    keep = [
        index
        for index in range(len(market["symbols"]))
        if index != column
    ]
    return {
        "dates": market["dates"],
        "symbols": [market["symbols"][index] for index in keep],
        "closes": market["closes"][:, keep],
        "spot_closes": market["spot_closes"][:, keep],
        "returns": market["returns"][:, keep],
        "funding": market["funding"][:, keep],
    }


def _gate(report: dict, specification: dict) -> dict:
    checks = {
        "minimum_days": report["days"] >= specification["minimum_days"],
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
        "both_side_contributions_nonnegative": (
            report["long_additive_contribution"] >= 0
            and report["short_additive_contribution"] >= 0
        ),
        "maximum_absolute_market_beta": (
            abs(report["market_beta"])
            <= specification["maximum_absolute_market_beta"]
        ),
    }
    return _finish_checks(checks)


def _finish_checks(checks: dict) -> dict:
    return {
        "checks": checks,
        "passed_checks": sum(checks.values()),
        "total_checks": len(checks),
        "passed": all(checks.values()),
    }


def evaluate_prelock(
    protocol_value,
    futures_collectors,
    spot_collectors,
    funding_paths,
    output_root_value,
) -> dict:
    protocol_path = pathlib.Path(protocol_value).resolve()
    protocol = write_or_verify_protocol(protocol_path)
    market, artifacts = load_market(
        futures_collectors, spot_collectors, funding_paths
    )
    if market["dates"][0] > DEVELOPMENT_START - datetime.timedelta(days=1):
        raise ValueError("market does not provide the frozen signal warmup")
    if market["dates"][-1] < LOCKED_END - datetime.timedelta(days=1):
        raise ValueError("market does not contain the declared locked interval")

    development = simulate_period(
        market,
        DEVELOPMENT_START,
        DEVELOPMENT_END,
        include_trajectory=True,
    )
    development_trajectory = development.pop("_trajectory")
    development_stress = simulate_period(
        market,
        DEVELOPMENT_START,
        DEVELOPMENT_END,
        cost_multiplier=STRESS_COST_MULTIPLIER,
    )
    development_folds = [
        simulate_period(market, start, end)
        for start, end in DEVELOPMENT_FOLDS
    ]
    positive_folds = sum(
        value["total_return"] > 0 for value in development_folds
    )
    leave_one_out = {}
    for column, symbol in enumerate(market["symbols"]):
        leave_one_out[symbol] = simulate_period(
            _drop_market_column(market, column),
            DEVELOPMENT_START,
            DEVELOPMENT_END,
        )
    positive_leave_one_out = sum(
        value["total_return"] > 0 for value in leave_one_out.values()
    )
    development_gate = _gate(
        development, protocol["development_gate"]
    )
    development_gate["checks"].update(
        {
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
        }
    )
    development_gate = _finish_checks(development_gate["checks"])

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
            market, CONFIRMATION_START, CONFIRMATION_END
        )
        confirmation_stress = simulate_period(
            market,
            CONFIRMATION_START,
            CONFIRMATION_END,
            cost_multiplier=STRESS_COST_MULTIPLIER,
        )
        confirmation_quarters = [
            simulate_period(market, start, end)
            for start, end in CONFIRMATION_QUARTERS
        ]
        positive_quarters = sum(
            value["total_return"] > 0 for value in confirmation_quarters
        )
        confirmation_gate = _gate(
            confirmation, protocol["confirmation_gate"]
        )
        confirmation_gate["checks"].update(
            {
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
            }
        )
        confirmation_gate = _finish_checks(confirmation_gate["checks"])

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
        locked = simulate_period(market, LOCKED_START, LOCKED_END)
        locked_stress = simulate_period(
            market,
            LOCKED_START,
            LOCKED_END,
            cost_multiplier=STRESS_COST_MULTIPLIER,
        )
        locked_gate = _gate(locked, protocol["locked_gate"])
        locked_gate["checks"]["stress_total_return_positive"] = (
            locked_stress["total_return"] > 0
        )
        locked_gate = _finish_checks(locked_gate["checks"])

    historical_pass = locked_authorized and locked_gate["passed"]
    output_root = pathlib.Path(output_root_value).resolve()
    source_bundle_sha256 = common._json_hash(artifacts)
    experiment = output_root / (
        "basis-factor-v1-"
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
        "created_at": datetime.datetime.now(datetime.timezone.utc).isoformat(),
        "research_only": True,
        "public_data_only": True,
        "credentials_used": False,
        "orders_authorized": False,
        "paper_orders_authorized": False,
        "automatic_promotion": False,
        "historical_periods_are_diagnostic_reuse": True,
        "protocol_path": str(protocol_path),
        "protocol_file_sha256": common._sha256(protocol_path),
        "protocol_sha256": protocol["protocol_sha256"],
        "source_bundle_sha256": source_bundle_sha256,
        "source_artifacts": artifacts,
        "symbols": market["symbols"],
        "market": {
            "start_date": market["dates"][0].isoformat(),
            "end_date": market["dates"][-1].isoformat(),
            "days": len(market["dates"]),
        },
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
        "historical_candidate": historical_pass,
        "forward_validation": {
            **protocol["forward_gate"],
            "started": False,
            "passed": False,
            "automatic_promotion": False,
        },
        "verdict": (
            "HISTORICAL_CANDIDATE_REQUIRES_180D_FORWARD"
            if historical_pass
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
        "historical_candidate": historical_pass,
        "orders_authorized": False,
        "paper_orders_authorized": False,
        "automatic_promotion": False,
    }
    manifest["content_sha256"] = common._json_hash(manifest)
    common._atomic_json(experiment / "manifest.json", manifest)
    return {
        "report": report,
        "manifest": manifest,
        "directory": str(experiment),
    }


def _parser():
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


def main(argv=None):
    args = _parser().parse_args(argv)
    if args.command == "write-protocol":
        print(
            json.dumps(
                write_or_verify_protocol(args.output),
                indent=2,
                sort_keys=True,
            )
        )
        return 0
    result = evaluate_prelock(
        args.protocol,
        args.futures_collector,
        args.spot_collector,
        args.funding_json,
        args.output_root,
    )
    print(json.dumps(common._json_safe(result), indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
