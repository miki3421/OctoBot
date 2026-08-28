"""Frozen Binance/KuCoin perpetual carry research protocol V1.

This module is offline, public-data-only and incapable of creating orders.
The protocol is intentionally persisted before any local economic outcome is
calculated.
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


SCHEMA_VERSION = 1
PROTOCOL_VERSION = "binance_kucoin_cross_venue_carry_v1"
PREREGISTRATION_DATE = "2026-08-28"
SYMBOLS = (
    "AAVE/USDT:USDT",
    "ADA/USDT:USDT",
    "ATOM/USDT:USDT",
    "AVAX/USDT:USDT",
    "BCH/USDT:USDT",
    "BTC/USDT:USDT",
    "DOGE/USDT:USDT",
    "DOT/USDT:USDT",
    "ETH/USDT:USDT",
    "HBAR/USDT:USDT",
    "LINK/USDT:USDT",
    "LTC/USDT:USDT",
    "NEAR/USDT:USDT",
    "SOL/USDT:USDT",
    "UNI/USDT:USDT",
    "XLM/USDT:USDT",
    "XRP/USDT:USDT",
    "ZEC/USDT:USDT",
)
LOOKBACK_SETTLEMENTS = 90
LOOKBACK_DAYS = 30
MAXIMUM_PAIRS = 3
PAIR_LEG_EXPOSURE = 0.10
FEE_PER_TURNOVER = 0.0006
SLIPPAGE_PER_TURNOVER = 0.0002
STRESS_COST_MULTIPLIER = 3.0
ENTRY_THRESHOLD_ANNUALIZED = (
    2.0
    * (
        FEE_PER_TURNOVER
        + SLIPPAGE_PER_TURNOVER
        + FEE_PER_TURNOVER
        + SLIPPAGE_PER_TURNOVER
    )
    * STRESS_COST_MULTIPLIER
    * 365.0
    / LOOKBACK_DAYS
)
DEVELOPMENT_START = datetime.datetime(
    2025, 8, 25, 1, tzinfo=datetime.timezone.utc
)
DEVELOPMENT_END = datetime.datetime(
    2025, 12, 1, 1, tzinfo=datetime.timezone.utc
)
CONFIRMATION_START = DEVELOPMENT_END
CONFIRMATION_END = datetime.datetime(
    2026, 3, 2, 1, tzinfo=datetime.timezone.utc
)
LOCKED_START = CONFIRMATION_END
LOCKED_END = datetime.datetime(
    2026, 6, 29, 1, tzinfo=datetime.timezone.utc
)
DEVELOPMENT_FOLDS = (
    (
        datetime.datetime(2025, 8, 25, 1, tzinfo=datetime.timezone.utc),
        datetime.datetime(2025, 9, 29, 1, tzinfo=datetime.timezone.utc),
    ),
    (
        datetime.datetime(2025, 9, 29, 1, tzinfo=datetime.timezone.utc),
        datetime.datetime(2025, 11, 3, 1, tzinfo=datetime.timezone.utc),
    ),
    (
        datetime.datetime(2025, 11, 3, 1, tzinfo=datetime.timezone.utc),
        datetime.datetime(2025, 12, 1, 1, tzinfo=datetime.timezone.utc),
    ),
)


def frozen_protocol() -> dict:
    """Return the one immutable, result-free V1 specification."""

    per_venue_cost = FEE_PER_TURNOVER + SLIPPAGE_PER_TURNOVER
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
            "name": "persistent_cross_venue_funding_spread",
            "statement": (
                "the same perpetual can have a persistent Binance/KuCoin "
                "funding difference that survives relative-price risk and "
                "conservative execution costs in a delta-neutral position"
            ),
            "direction": (
                "long the lower trailing-funding venue and short the higher"
            ),
            "one_configuration_only": True,
            "opposite_direction_tested": False,
        },
        "universe": {
            "symbols": list(SYMBOLS),
            "required_symbol_count": len(SYMBOLS),
            "venues": ["Binance USD-M", "KuCoin Futures"],
            "fixed_survivor_universe_limitation": True,
        },
        "signal": {
            "completed_settlement_lookback": LOOKBACK_SETTLEMENTS,
            "lookback_days": LOOKBACK_DAYS,
            "decision_schedule": "Monday 00:00 UTC",
            "entry_schedule": "Monday 01:00 UTC close",
            "causal_delay_hours": 1,
            "annualization": "abs(sum_kucoin-sum_binance)*365/30",
            "minimum_annualized_spread": ENTRY_THRESHOLD_ANNUALIZED,
            "threshold_origin": (
                "3x stressed four-fill taker-plus-slippage round trip "
                "recovered over 30 days"
            ),
            "maximum_pairs": MAXIMUM_PAIRS,
            "ranking": "descending absolute spread, symbol tie-break",
            "pair_leg_exposure": PAIR_LEG_EXPOSURE,
            "maximum_portfolio_gross": (
                2.0 * MAXIMUM_PAIRS * PAIR_LEG_EXPOSURE
            ),
            "nominal_net_exposure": 0.0,
            "rebalance": "weekly full target replacement",
            "future_funding_not_used": True,
        },
        "economics": {
            "price_pnl": "hourly close-to-close on prior venue weights",
            "funding_pnl": (
                "negative venue weight times actual signed settlement"
            ),
            "fee_per_venue_turnover": FEE_PER_TURNOVER,
            "slippage_per_venue_turnover": SLIPPAGE_PER_TURNOVER,
            "per_venue_turnover_cost": per_venue_cost,
            "stress_cost_multiplier": STRESS_COST_MULTIPLIER,
            "maker_fill_assumptions": False,
            "forced_flatten_at_each_evaluation_end": True,
        },
        "data_quality": {
            "hourly_prices": (
                "strict consecutive and aligned Binance/KuCoin closes"
            ),
            "funding": (
                "exactly one finite point per required 8-hour grid"
            ),
            "partial_rows_allowed": False,
            "failure_policy": "fail closed before evaluating outcomes",
        },
        "validation": {
            "development": [
                DEVELOPMENT_START.isoformat(),
                DEVELOPMENT_END.isoformat(),
            ],
            "development_end_exclusive": True,
            "walk_forward_folds": [
                [start.isoformat(), end.isoformat()]
                for start, end in DEVELOPMENT_FOLDS
            ],
            "confirmation": [
                CONFIRMATION_START.isoformat(),
                CONFIRMATION_END.isoformat(),
            ],
            "confirmation_end_exclusive": True,
            "locked_final_test": [
                LOCKED_START.isoformat(),
                LOCKED_END.isoformat(),
            ],
            "locked_end_exclusive": True,
            "locked_policy": (
                "do not calculate confirmation unless development passes; "
                "do not calculate lock unless both prior gates pass"
            ),
            "historical_information_status": "diagnostic_reuse",
        },
        "development_gate": {
            "minimum_hours": 98 * 24,
            "minimum_weekly_decisions": 14,
            "minimum_invested_weeks": 6,
            "positive_total_return": True,
            "minimum_annualized_return": 0.04,
            "minimum_sharpe": 1.0,
            "maximum_drawdown": 0.08,
            "minimum_positive_week_ratio": 0.55,
            "minimum_positive_folds": 2,
            "required_folds": len(DEVELOPMENT_FOLDS),
            "funding_return_positive": True,
            "funding_return_exceeds_cost": True,
            "stress_total_return_positive": True,
            "minimum_stress_sharpe": 0.50,
            "maximum_absolute_market_beta": 0.10,
            "minimum_positive_leave_one_symbol_out": 15,
            "required_leave_one_symbol_out": len(SYMBOLS),
            "maximum_symbol_absolute_contribution_share": 0.50,
        },
        "confirmation_gate": {
            "minimum_hours": 91 * 24,
            "minimum_weekly_decisions": 13,
            "minimum_invested_weeks": 6,
            "positive_total_return": True,
            "minimum_annualized_return": 0.02,
            "minimum_sharpe": 0.50,
            "maximum_drawdown": 0.08,
            "minimum_positive_week_ratio": 0.50,
            "funding_return_positive": True,
            "stress_total_return_positive": True,
            "maximum_absolute_market_beta": 0.10,
        },
        "locked_gate": {
            "minimum_hours": 119 * 24,
            "minimum_weekly_decisions": 17,
            "minimum_invested_weeks": 8,
            "positive_total_return": True,
            "minimum_sharpe": 0.50,
            "maximum_drawdown": 0.08,
            "funding_return_positive": True,
            "stress_total_return_positive": True,
            "maximum_absolute_market_beta": 0.10,
        },
        "multiple_testing_disclosure": (
            "one lookback, threshold, schedule, rank direction, universe, "
            "portfolio size and cost model are evaluated"
        ),
        "forward_requirement": {
            "start_not_before": "2026-08-29T00:00:00+00:00",
            "minimum_calendar_days": 180,
            "minimum_observed_days": 165,
            "matched_point_in_time_books_required": True,
            "refit_allowed": False,
        },
        "promotion_consequence": (
            "a complete historical and new-forward pass permits only "
            "manually approved orderless shadow; paper and real orders "
            "remain unauthorized"
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
            raise ValueError("persisted cross-venue carry V1 protocol differs")
        return persisted
    common._atomic_json(path, payload)
    return payload


FUNDING_INTERVAL_SECONDS = 8 * 3600
HOUR_SECONDS = 3600
WARMUP_START = datetime.datetime(
    2025, 7, 22, 0, tzinfo=datetime.timezone.utc
)


def _timestamp(value: datetime.datetime) -> int:
    return int(value.timestamp())


def _artifact(path: pathlib.Path) -> dict:
    return {
        "path": str(path),
        "bytes": path.stat().st_size,
        "sha256": common._sha256(path),
    }


def _load_funding_inputs(paths: typing.Iterable[pathlib.Path]) -> tuple:
    merged = {}
    artifacts = []
    for path in paths:
        loaded = funding_module.load_funding(path)
        overlap = set(merged) & set(loaded)
        if overlap:
            raise ValueError(
                "funding symbols appear in multiple inputs: "
                f"{sorted(overlap)}"
            )
        merged.update(loaded)
        artifacts.append(_artifact(path))
    return merged, artifacts


def _strict_hourly_closes(series, expected: numpy.ndarray) -> numpy.ndarray:
    timestamps = numpy.asarray(series.close_times, dtype=numpy.int64)
    closes = numpy.asarray(series.values[:, 4], dtype=numpy.float64)
    if len(numpy.unique(timestamps)) != len(timestamps):
        raise ValueError(f"duplicate hourly close for {series.symbol}")
    if numpy.any(closes <= 0) or not numpy.all(numpy.isfinite(closes)):
        raise ValueError(f"invalid hourly close for {series.symbol}")
    by_timestamp = {
        int(timestamp): float(close)
        for timestamp, close in zip(timestamps, closes)
    }
    missing = [int(value) for value in expected if int(value) not in by_timestamp]
    if missing:
        raise ValueError(
            f"hourly close gap for {series.symbol} at {missing[0]}"
        )
    return numpy.asarray(
        [by_timestamp[int(value)] for value in expected],
        dtype=numpy.float64,
    )


def _strict_funding_grid(
    funding: dict,
    symbol: str,
    expected: numpy.ndarray,
) -> numpy.ndarray:
    if symbol not in funding:
        raise ValueError(f"missing funding series for {symbol}")
    timestamps, rates = funding[symbol]
    points = {}
    lower = int(expected[0])
    upper = int(expected[-1])
    for timestamp, rate in zip(timestamps, rates):
        timestamp = int(timestamp)
        if not lower <= timestamp <= upper:
            continue
        if timestamp % FUNDING_INTERVAL_SECONDS:
            raise ValueError(f"off-grid funding timestamp for {symbol}")
        if timestamp in points:
            raise ValueError(f"duplicate funding timestamp for {symbol}")
        value = float(rate)
        if not math.isfinite(value):
            raise ValueError(f"non-finite funding rate for {symbol}")
        points[timestamp] = value
    missing = [int(value) for value in expected if int(value) not in points]
    if missing:
        raise ValueError(
            f"funding grid gap for {symbol} at {missing[0]}"
        )
    return numpy.asarray(
        [points[int(value)] for value in expected],
        dtype=numpy.float64,
    )


def load_market(
    binance_collector_values: typing.Iterable[
        typing.Union[str, pathlib.Path]
    ],
    kucoin_collector_values: typing.Iterable[
        typing.Union[str, pathlib.Path]
    ],
    binance_funding_values: typing.Iterable[
        typing.Union[str, pathlib.Path]
    ],
    kucoin_funding_value: typing.Union[str, pathlib.Path],
) -> tuple[dict, dict]:
    """Load only metadata-complete, aligned public historical inputs."""

    binance_paths = [
        pathlib.Path(value).resolve() for value in binance_collector_values
    ]
    kucoin_paths = [
        pathlib.Path(value).resolve() for value in kucoin_collector_values
    ]
    binance_funding_paths = [
        pathlib.Path(value).resolve() for value in binance_funding_values
    ]
    kucoin_funding_path = pathlib.Path(kucoin_funding_value).resolve()
    if not binance_paths or not kucoin_paths or not binance_funding_paths:
        raise ValueError("both venue collectors and Binance funding are required")

    binance = dataset_module.load_collector_series(
        binance_paths, required_time_frames=("1h",)
    )
    kucoin = dataset_module.load_collector_series(
        kucoin_paths, required_time_frames=("1h",)
    )
    expected_symbols = set(SYMBOLS)
    if set(binance) != expected_symbols:
        raise ValueError("Binance collector does not match frozen universe")
    if set(kucoin) != expected_symbols:
        raise ValueError("KuCoin collectors do not match frozen universe")

    binance_funding, binance_funding_artifacts = _load_funding_inputs(
        binance_funding_paths
    )
    kucoin_funding, kucoin_funding_artifacts = _load_funding_inputs(
        [kucoin_funding_path]
    )
    if not expected_symbols <= set(binance_funding):
        raise ValueError("Binance funding does not cover frozen universe")
    if not expected_symbols <= set(kucoin_funding):
        raise ValueError("KuCoin funding does not cover frozen universe")

    close_times = numpy.arange(
        _timestamp(WARMUP_START) + HOUR_SECONDS,
        _timestamp(LOCKED_END) + HOUR_SECONDS,
        HOUR_SECONDS,
        dtype=numpy.int64,
    )
    funding_times = numpy.arange(
        _timestamp(WARMUP_START),
        _timestamp(LOCKED_END),
        FUNDING_INTERVAL_SECONDS,
        dtype=numpy.int64,
    )
    symbols = list(SYMBOLS)
    binance_closes = numpy.column_stack(
        [
            _strict_hourly_closes(binance[symbol]["1h"], close_times)
            for symbol in symbols
        ]
    )
    kucoin_closes = numpy.column_stack(
        [
            _strict_hourly_closes(kucoin[symbol]["1h"], close_times)
            for symbol in symbols
        ]
    )
    binance_rates = numpy.column_stack(
        [
            _strict_funding_grid(
                binance_funding, symbol, funding_times
            )
            for symbol in symbols
        ]
    )
    kucoin_rates = numpy.column_stack(
        [
            _strict_funding_grid(kucoin_funding, symbol, funding_times)
            for symbol in symbols
        ]
    )
    market = {
        "symbols": symbols,
        "close_times": close_times,
        "binance_closes": binance_closes,
        "kucoin_closes": kucoin_closes,
        "funding_times": funding_times,
        "binance_funding": binance_rates,
        "kucoin_funding": kucoin_rates,
    }
    artifacts = {
        "evaluator": _artifact(pathlib.Path(__file__).resolve()),
        "binance_collectors": [_artifact(path) for path in binance_paths],
        "kucoin_collectors": [_artifact(path) for path in kucoin_paths],
        "binance_funding": binance_funding_artifacts,
        "kucoin_funding": kucoin_funding_artifacts,
    }
    return market, artifacts


def target_weights(
    market: dict,
    signal_timestamp: int,
    *,
    enabled_columns: typing.Optional[numpy.ndarray] = None,
) -> tuple[numpy.ndarray, numpy.ndarray, list[dict]]:
    """Build a target from funding points known at ``signal_timestamp``."""

    funding_times = numpy.asarray(market["funding_times"])
    matches = numpy.flatnonzero(funding_times == int(signal_timestamp))
    if len(matches) != 1:
        raise ValueError("signal timestamp is absent from funding grid")
    index = int(matches[0])
    if index + 1 < LOOKBACK_SETTLEMENTS:
        raise ValueError("signal does not have the frozen funding warmup")
    start = index + 1 - LOOKBACK_SETTLEMENTS
    spread = numpy.sum(
        market["kucoin_funding"][start : index + 1]
        - market["binance_funding"][start : index + 1],
        axis=0,
    )
    annualized = numpy.abs(spread) * 365.0 / LOOKBACK_DAYS
    if enabled_columns is None:
        enabled_columns = numpy.ones(len(market["symbols"]), dtype=bool)
    enabled_columns = numpy.asarray(enabled_columns, dtype=bool)
    if enabled_columns.shape != (len(market["symbols"]),):
        raise ValueError("enabled-column mask has the wrong shape")
    eligible = [
        column
        for column, value in enumerate(annualized)
        if enabled_columns[column]
        and math.isfinite(float(value))
        and value >= ENTRY_THRESHOLD_ANNUALIZED
    ]
    ordered = sorted(
        eligible,
        key=lambda column: (
            -float(annualized[column]),
            market["symbols"][column],
        ),
    )[:MAXIMUM_PAIRS]
    binance = numpy.zeros(len(market["symbols"]), dtype=numpy.float64)
    kucoin = numpy.zeros(len(market["symbols"]), dtype=numpy.float64)
    selected = []
    for column in ordered:
        if spread[column] > 0:
            binance[column] = PAIR_LEG_EXPOSURE
            kucoin[column] = -PAIR_LEG_EXPOSURE
            direction = "long_binance_short_kucoin"
        elif spread[column] < 0:
            binance[column] = -PAIR_LEG_EXPOSURE
            kucoin[column] = PAIR_LEG_EXPOSURE
            direction = "long_kucoin_short_binance"
        else:
            continue
        selected.append(
            {
                "symbol": market["symbols"][column],
                "annualized_absolute_spread": float(annualized[column]),
                "signed_kucoin_minus_binance_30d": float(spread[column]),
                "direction": direction,
            }
        )
    return binance, kucoin, selected


def _strategy_week_key(timestamp: int, start_timestamp: int) -> str:
    elapsed = max(0, int(timestamp) - int(start_timestamp) - 1)
    return f"week-{elapsed // (7 * 24 * 3600):03d}"


def _period_returns(keys, equity) -> dict:
    endpoints = {}
    for key, value in zip(keys, equity):
        endpoints[key] = float(value)
    result = {}
    previous = 1.0
    for key, value in endpoints.items():
        result[key] = value / previous - 1.0
        previous = value
    return result


def _rebalance_costs(previous, target, cost_rate):
    changes = numpy.abs(target - previous)
    by_symbol = changes * cost_rate
    return by_symbol, float(numpy.sum(changes)), float(numpy.sum(by_symbol))


def simulate_period(
    market: dict,
    start: datetime.datetime,
    end: datetime.datetime,
    *,
    cost_multiplier: float = 1.0,
    enabled_columns: typing.Optional[numpy.ndarray] = None,
    include_trajectory: bool = False,
) -> dict:
    if cost_multiplier < 1.0:
        raise ValueError("cost multiplier must be at least one")
    start_timestamp = _timestamp(start)
    end_timestamp = _timestamp(end)
    close_times = numpy.asarray(market["close_times"], dtype=numpy.int64)
    start_matches = numpy.flatnonzero(close_times == start_timestamp)
    end_matches = numpy.flatnonzero(close_times == end_timestamp)
    if len(start_matches) != 1 or len(end_matches) != 1:
        raise ValueError("evaluation boundaries are absent from hourly market")
    first = int(start_matches[0])
    final = int(end_matches[0])
    if final <= first:
        raise ValueError("evaluation end must follow its start")
    if start.weekday() != 0 or start.hour != 1:
        raise ValueError("evaluation must start Monday 01:00 UTC")
    if end.weekday() != 0 or end.hour != 1:
        raise ValueError("evaluation must end Monday 01:00 UTC")

    symbol_count = len(market["symbols"])
    if enabled_columns is None:
        enabled_columns = numpy.ones(symbol_count, dtype=bool)
    enabled_columns = numpy.asarray(enabled_columns, dtype=bool)
    per_turnover_cost = cost_multiplier * (
        FEE_PER_TURNOVER + SLIPPAGE_PER_TURNOVER
    )
    binance_weights, kucoin_weights, selected = target_weights(
        market,
        start_timestamp - HOUR_SECONDS,
        enabled_columns=enabled_columns,
    )
    binance_costs, binance_turnover, binance_cost = _rebalance_costs(
        numpy.zeros(symbol_count), binance_weights, per_turnover_cost
    )
    kucoin_costs, kucoin_turnover, kucoin_cost = _rebalance_costs(
        numpy.zeros(symbol_count), kucoin_weights, per_turnover_cost
    )
    opening_cost = binance_cost + kucoin_cost
    equity = 1.0 - opening_cost
    if equity <= 0:
        raise ValueError("cross-venue carry equity became non-positive")
    contribution = -(binance_costs + kucoin_costs)
    total_cost = opening_cost
    total_turnover = binance_turnover + kucoin_turnover
    total_price = 0.0
    total_funding = 0.0
    weekly_decisions = 1
    rebalance_events = int(total_turnover > 0)
    direction_decisions = {
        "long_binance_short_kucoin": sum(
            value["direction"] == "long_binance_short_kucoin"
            for value in selected
        ),
        "long_kucoin_short_binance": sum(
            value["direction"] == "long_kucoin_short_binance"
            for value in selected
        ),
    }
    funding_index = {
        int(timestamp): index
        for index, timestamp in enumerate(market["funding_times"])
    }
    equities = []
    hourly_returns = []
    market_returns = []
    applied_gross = []
    applied_net = []
    selected_by_decision = [
        {
            "entry_timestamp": start_timestamp,
            "signal_timestamp": start_timestamp - HOUR_SECONDS,
            "selected": selected,
        }
    ]
    invested_week_keys = set()

    for index in range(first + 1, final + 1):
        timestamp = int(close_times[index])
        before = 1.0 if index == first + 1 else equity
        binance_return = (
            market["binance_closes"][index]
            / market["binance_closes"][index - 1]
            - 1.0
        )
        kucoin_return = (
            market["kucoin_closes"][index]
            / market["kucoin_closes"][index - 1]
            - 1.0
        )
        price_by_symbol = (
            binance_weights * binance_return
            + kucoin_weights * kucoin_return
        )
        funding_by_symbol = numpy.zeros(symbol_count, dtype=numpy.float64)
        if timestamp in funding_index:
            funding_row = funding_index[timestamp]
            funding_by_symbol = -(
                binance_weights
                * market["binance_funding"][funding_row]
                + kucoin_weights
                * market["kucoin_funding"][funding_row]
            )
        pnl_by_symbol = price_by_symbol + funding_by_symbol
        equity *= 1.0 + float(numpy.sum(pnl_by_symbol))
        contribution += pnl_by_symbol
        total_price += float(numpy.sum(price_by_symbol))
        total_funding += float(numpy.sum(funding_by_symbol))
        gross = float(
            numpy.sum(numpy.abs(binance_weights))
            + numpy.sum(numpy.abs(kucoin_weights))
        )
        net = float(numpy.sum(binance_weights + kucoin_weights))
        if gross > 0:
            invested_week_keys.add(
                _strategy_week_key(timestamp, start_timestamp)
            )

        current = datetime.datetime.fromtimestamp(
            timestamp, datetime.timezone.utc
        )
        if timestamp < end_timestamp and current.weekday() == 0 and current.hour == 1:
            target_binance, target_kucoin, selected = target_weights(
                market,
                timestamp - HOUR_SECONDS,
                enabled_columns=enabled_columns,
            )
            binance_costs, binance_turnover, binance_cost = _rebalance_costs(
                binance_weights, target_binance, per_turnover_cost
            )
            kucoin_costs, kucoin_turnover, kucoin_cost = _rebalance_costs(
                kucoin_weights, target_kucoin, per_turnover_cost
            )
            cost = binance_cost + kucoin_cost
            turnover = binance_turnover + kucoin_turnover
            equity *= 1.0 - cost
            contribution -= binance_costs + kucoin_costs
            total_cost += cost
            total_turnover += turnover
            weekly_decisions += 1
            if turnover > 0:
                rebalance_events += 1
            binance_weights = target_binance
            kucoin_weights = target_kucoin
            for direction in direction_decisions:
                direction_decisions[direction] += sum(
                    value["direction"] == direction for value in selected
                )
            selected_by_decision.append(
                {
                    "entry_timestamp": timestamp,
                    "signal_timestamp": timestamp - HOUR_SECONDS,
                    "selected": selected,
                }
            )
        if equity <= 0:
            raise ValueError("cross-venue carry equity became non-positive")
        equities.append(equity)
        hourly_returns.append(equity / before - 1.0)
        market_returns.append(
            float(numpy.mean((binance_return + kucoin_return) / 2.0))
        )
        applied_gross.append(gross)
        applied_net.append(net)

    binance_costs, binance_turnover, binance_cost = _rebalance_costs(
        binance_weights, numpy.zeros(symbol_count), per_turnover_cost
    )
    kucoin_costs, kucoin_turnover, kucoin_cost = _rebalance_costs(
        kucoin_weights, numpy.zeros(symbol_count), per_turnover_cost
    )
    closing_cost = binance_cost + kucoin_cost
    closing_turnover = binance_turnover + kucoin_turnover
    if closing_cost:
        previous_equity = equities[-2] if len(equities) > 1 else 1.0
        equity *= 1.0 - closing_cost
        contribution -= binance_costs + kucoin_costs
        total_cost += closing_cost
        total_turnover += closing_turnover
        equities[-1] = equity
        hourly_returns[-1] = equity / previous_equity - 1.0

    values = numpy.asarray(equities, dtype=numpy.float64)
    returns = numpy.asarray(hourly_returns, dtype=numpy.float64)
    benchmark = numpy.asarray(market_returns, dtype=numpy.float64)
    peaks = numpy.maximum.accumulate(
        numpy.concatenate((numpy.ones(1), values))
    )[1:]
    drawdowns = 1.0 - values / peaks
    result_times = close_times[first + 1 : final + 1]
    week_keys = [
        _strategy_week_key(value, start_timestamp) for value in result_times
    ]
    weekly = _period_returns(week_keys, values)
    elapsed_years = len(returns) / (365.25 * 24.0)
    volatility = float(numpy.std(returns))
    benchmark_variance = float(numpy.var(benchmark))
    beta = (
        float(numpy.cov(returns, benchmark, ddof=0)[0, 1])
        / benchmark_variance
        if benchmark_variance > 0
        else 0.0
    )
    positive = float(numpy.sum(returns[returns > 0]))
    negative = float(-numpy.sum(returns[returns < 0]))
    absolute_contribution = numpy.abs(contribution)
    contribution_total = float(numpy.sum(absolute_contribution))
    maximum_share = (
        float(numpy.max(absolute_contribution) / contribution_total)
        if contribution_total > 0
        else 1.0
    )
    trajectory = {
        "timestamps": [int(value) for value in result_times],
        "equity": values.tolist(),
        "hourly_return": returns.tolist(),
        "market_return": benchmark.tolist(),
        "gross_exposure": applied_gross,
        "net_exposure": applied_net,
        "decisions": selected_by_decision,
    }
    report = {
        "start": start.isoformat(),
        "end": end.isoformat(),
        "hours": len(returns),
        "cost_multiplier": cost_multiplier,
        "total_return": float(equity - 1.0),
        "annualized_return": (
            float(equity ** (1.0 / elapsed_years) - 1.0)
            if elapsed_years > 0 and equity > 0
            else 0.0
        ),
        "annualized_volatility": volatility * math.sqrt(365.0 * 24.0),
        "sharpe_zero_rate": (
            float(numpy.mean(returns) / volatility * math.sqrt(365.0 * 24.0))
            if volatility > 0
            else 0.0
        ),
        "maximum_drawdown": float(numpy.max(drawdowns)),
        "profit_factor": positive / negative if negative > 0 else None,
        "positive_week_ratio": (
            sum(value > 0 for value in weekly.values()) / len(weekly)
            if weekly
            else 0.0
        ),
        "weekly_returns": weekly,
        "weekly_decisions": weekly_decisions,
        "invested_weeks": len(invested_week_keys),
        "rebalance_events": rebalance_events,
        "total_turnover": float(total_turnover),
        "total_cost_return": float(total_cost),
        "total_price_return": float(total_price),
        "total_funding_return": float(total_funding),
        "market_beta": beta,
        "average_gross_exposure": float(numpy.mean(applied_gross)),
        "maximum_gross_exposure": float(numpy.max(applied_gross)),
        "maximum_absolute_net_exposure": float(
            numpy.max(numpy.abs(applied_net))
        ),
        "direction_pair_decisions": direction_decisions,
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
        "minimum_hours": report["hours"] >= specification["minimum_hours"],
        "minimum_weekly_decisions": (
            report["weekly_decisions"]
            >= specification["minimum_weekly_decisions"]
        ),
        "minimum_invested_weeks": (
            report["invested_weeks"]
            >= specification["minimum_invested_weeks"]
        ),
        "positive_total_return": report["total_return"] > 0,
        "minimum_sharpe": (
            report["sharpe_zero_rate"] >= specification["minimum_sharpe"]
        ),
        "maximum_drawdown": (
            report["maximum_drawdown"] <= specification["maximum_drawdown"]
        ),
        "funding_return_positive": report["total_funding_return"] > 0,
        "maximum_absolute_market_beta": (
            abs(report["market_beta"])
            <= specification["maximum_absolute_market_beta"]
        ),
    }
    if "minimum_annualized_return" in specification:
        checks["minimum_annualized_return"] = (
            report["annualized_return"]
            >= specification["minimum_annualized_return"]
        )
    if "minimum_positive_week_ratio" in specification:
        checks["minimum_positive_week_ratio"] = (
            report["positive_week_ratio"]
            >= specification["minimum_positive_week_ratio"]
        )
    return _finish_checks(checks)


def evaluate_prelock(
    protocol_value,
    binance_collector_values,
    kucoin_collector_values,
    binance_funding_values,
    kucoin_funding_value,
    output_root_value,
) -> dict:
    protocol_path = pathlib.Path(protocol_value).resolve()
    protocol = write_or_verify_protocol(protocol_path)
    market, artifacts = load_market(
        binance_collector_values,
        kucoin_collector_values,
        binance_funding_values,
        kucoin_funding_value,
    )

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
        report["total_return"] > 0 for report in development_folds
    )
    leave_one_out = {}
    for column, symbol in enumerate(market["symbols"]):
        enabled = numpy.ones(len(market["symbols"]), dtype=bool)
        enabled[column] = False
        leave_one_out[symbol] = simulate_period(
            market,
            DEVELOPMENT_START,
            DEVELOPMENT_END,
            enabled_columns=enabled,
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
        "funding_return_exceeds_cost": (
            development["total_funding_return"]
            > development["total_cost_return"]
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
    development_gate = _finish_checks(development_checks)

    confirmation = None
    confirmation_stress = None
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
        confirmation_gate = _base_gate(
            confirmation, protocol["confirmation_gate"]
        )
        confirmation_checks = {
            **confirmation_gate["checks"],
            "stress_total_return_positive": (
                confirmation_stress["total_return"] > 0
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
        locked = simulate_period(market, LOCKED_START, LOCKED_END)
        locked_stress = simulate_period(
            market,
            LOCKED_START,
            LOCKED_END,
            cost_multiplier=STRESS_COST_MULTIPLIER,
        )
        locked_gate = _base_gate(locked, protocol["locked_gate"])
        locked_checks = {
            **locked_gate["checks"],
            "stress_total_return_positive": locked_stress["total_return"] > 0,
        }
        locked_gate = _finish_checks(locked_checks)

    historical_candidate = locked_authorized and locked_gate["passed"]
    output_root = pathlib.Path(output_root_value).resolve()
    source_bundle_sha256 = common._json_hash(artifacts)
    experiment = output_root / (
        "cross-venue-carry-v1-"
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
            "first_close_timestamp": int(market["close_times"][0]),
            "last_close_timestamp": int(market["close_times"][-1]),
            "hourly_closes": len(market["close_times"]),
            "funding_settlements_per_symbol": len(
                market["funding_times"]
            ),
        },
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
            **protocol["forward_requirement"],
            "started": False,
            "passed": False,
            "automatic_promotion": False,
        },
        "verdict": (
            "HISTORICAL_CANDIDATE_REQUIRES_FORWARD"
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
    evaluate.add_argument(
        "--binance-collector", action="append", required=True
    )
    evaluate.add_argument("--kucoin-collector", action="append", required=True)
    evaluate.add_argument("--binance-funding", action="append", required=True)
    evaluate.add_argument("--kucoin-funding", required=True)
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
        args.binance_collector,
        args.kucoin_collector,
        args.binance_funding,
        args.kucoin_funding,
        args.output_root,
    )
    summary = {
        "directory": result["directory"],
        "verdict": result["report"]["verdict"],
        "development": result["report"]["development"],
        "development_stress": result["report"]["development_stress"],
        "development_gate": result["report"]["development_gate"],
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
