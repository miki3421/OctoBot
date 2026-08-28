"""Frozen, research-only signed price-volume factor for Binance perpetuals.

The factor ranks seven days of aggressive quote flow at each completed UTC
eight-hour block.  It has no exchange client and cannot place orders.
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
from octobot.ai_strategy_lab import funding as funding_module
from octobot.ai_strategy_lab import market_data


SCHEMA_VERSION = 1
PROTOCOL_VERSION = "crypto_perpetual_signed_price_volume_flow_v1"
PREREGISTRATION_DATE = "2026-08-28"
PAPER_MANUSCRIPT_SHA256 = (
    "759a036f1f0c921d335e2e2567b2d8e5ce3088c5e16d4ed5bf98875983d74521"
)
EXPECTED_SYMBOLS = 18
BLOCK_SECONDS = 8 * 3600
FORMATION_BLOCKS = 7 * 3
SELECTION_FRACTION = 0.20
SIDE_GROSS_EXPOSURE = 0.40
FEE_PER_TURNOVER = 0.0006
SLIPPAGE_PER_TURNOVER = 0.0002
STRESS_COST_MULTIPLIER = 3.0
UTC = datetime.timezone.utc
DEVELOPMENT_START = datetime.datetime(2022, 7, 1, tzinfo=UTC)
DEVELOPMENT_END = datetime.datetime(2025, 1, 1, tzinfo=UTC)
CONFIRMATION_START = DEVELOPMENT_END
CONFIRMATION_END = datetime.datetime(2026, 1, 1, tzinfo=UTC)
LOCKED_START = CONFIRMATION_END
LOCKED_END = datetime.datetime(2026, 6, 30, 16, tzinfo=UTC)
FORWARD_START_UTC = "2026-08-29T00:00:00+00:00"
DEVELOPMENT_FOLDS = (
    (
        datetime.datetime(2022, 7, 1, tzinfo=UTC),
        datetime.datetime(2023, 1, 1, tzinfo=UTC),
    ),
    (
        datetime.datetime(2023, 1, 1, tzinfo=UTC),
        datetime.datetime(2023, 7, 1, tzinfo=UTC),
    ),
    (
        datetime.datetime(2023, 7, 1, tzinfo=UTC),
        datetime.datetime(2024, 1, 1, tzinfo=UTC),
    ),
    (
        datetime.datetime(2024, 1, 1, tzinfo=UTC),
        datetime.datetime(2024, 7, 1, tzinfo=UTC),
    ),
    (
        datetime.datetime(2024, 7, 1, tzinfo=UTC),
        datetime.datetime(2025, 1, 1, tzinfo=UTC),
    ),
)
CONFIRMATION_QUARTERS = (
    (
        datetime.datetime(2025, 1, 1, tzinfo=UTC),
        datetime.datetime(2025, 4, 1, tzinfo=UTC),
    ),
    (
        datetime.datetime(2025, 4, 1, tzinfo=UTC),
        datetime.datetime(2025, 7, 1, tzinfo=UTC),
    ),
    (
        datetime.datetime(2025, 7, 1, tzinfo=UTC),
        datetime.datetime(2025, 10, 1, tzinfo=UTC),
    ),
    (
        datetime.datetime(2025, 10, 1, tzinfo=UTC),
        datetime.datetime(2026, 1, 1, tzinfo=UTC),
    ),
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
        "external_hypothesis": {
            "title": "Anatomy of Cryptocurrency Perpetual Futures Returns",
            "authors": ["Yi Cao", "Jia Zhai", "Pengfei Luo"],
            "institutional_repository": (
                "https://era.ed.ac.uk/bitstream/handle/1842/43608/"
                "Luo2025.pdf?isAllowed=y&sequence=1"
            ),
            "thesis_doi": "10.7488/era/6141",
            "manuscript_sha256": PAPER_MANUSCRIPT_SHA256,
            "local_choice_before_outcomes": (
                "reported seven-day signed price-volume high-minus-low"
            ),
        },
        "hypothesis": {
            "name": "cross_sectional_aggressive_quote_flow_continuation",
            "statement": (
                "perpetuals with the highest seven-day aggressive signed "
                "quote flow outperform those with the lowest flow"
            ),
            "economic_mechanism": (
                "persistent informed demand and gradual price incorporation"
            ),
            "direction": "long high signed flow; short low signed flow",
            "opposite_direction_tested": False,
            "one_configuration_only": True,
            "historical_price_periods_are_diagnostic_reuse": True,
            "signed_flow_is_a_new_local_information_set": True,
        },
        "signal": {
            "source": "checksummed Binance USD-M raw 1h kline archives",
            "eight_hour_alignment": "00:00, 08:00 and 16:00 UTC opens",
            "block_flow": (
                "sum(2 * taker_buy_quote_volume - total_quote_volume)"
            ),
            "formation_blocks": FORMATION_BLOCKS,
            "formation_days": 7,
            "ranking": "ascending flow, deterministic symbol tie-break",
            "selection_fraction_per_side": SELECTION_FRACTION,
            "selected_assets_per_side": 3,
            "long_side": "highest flow quintile",
            "short_side": "lowest flow quintile",
            "weighting": "equal weight within each side",
            "side_gross_exposure": SIDE_GROSS_EXPOSURE,
            "nominal_net_exposure": 0.0,
            "rebalance": "each completed eight-hour block",
            "applies_to": "the immediately following eight-hour block",
            "normalization": None,
            "filters": None,
            "future_values_used": False,
        },
        "economics": {
            "traded_instrument": "perpetual only",
            "price_pnl": "next-block perpetual close-to-close return",
            "funding_pnl": "negative position weight times signed settlement",
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
            "development_decision_end_exclusive": True,
            "development_folds": [
                [start.isoformat(), end.isoformat()]
                for start, end in DEVELOPMENT_FOLDS
            ],
            "confirmation": [
                CONFIRMATION_START.isoformat(),
                CONFIRMATION_END.isoformat(),
            ],
            "confirmation_decision_end_exclusive": True,
            "confirmation_quarters": [
                [start.isoformat(), end.isoformat()]
                for start, end in CONFIRMATION_QUARTERS
            ],
            "locked_final_test": [
                LOCKED_START.isoformat(),
                LOCKED_END.isoformat(),
            ],
            "locked_decision_end_exclusive": True,
            "locked_policy": (
                "do not calculate confirmation unless development passes; "
                "do not calculate the lock unless confirmation also passes"
            ),
            "survivorship_limitation": (
                "fixed archive of 18 contracts surviving to archive end"
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
            "maximum_absolute_market_beta": 0.30,
            "minimum_positive_leave_one_symbol_out": 15,
            "required_leave_one_symbol_out": EXPECTED_SYMBOLS,
            "stress_total_return_positive": True,
        },
        "confirmation_gate": {
            "minimum_blocks": 1000,
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
            "minimum_blocks": 500,
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
            "minimum_observed_blocks": 500,
            "no_refit": True,
            "same_signal_and_costs": True,
            "required_before_shadow_or_paper": True,
        },
        "multiple_testing_disclosure": (
            "one externally selected lookback, direction, rank allocation, "
            "rebalance frequency and cost model are evaluated locally"
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
            raise ValueError("persisted signed-flow V1 protocol differs")
        return persisted
    common._atomic_json(path, payload)
    return payload


def _artifact(path: pathlib.Path) -> dict:
    return {
        "path": str(path),
        "bytes": path.stat().st_size,
        "sha256": common._sha256(path),
    }


def _aggregate_eight_hour(rows: dict[int, list[float]]) -> dict[int, tuple]:
    buckets: dict[int, list[list[float]]] = {}
    for timestamp, row in rows.items():
        bucket = timestamp // BLOCK_SECONDS * BLOCK_SECONDS
        buckets.setdefault(bucket, []).append(row)
    result = {}
    for bucket, values in buckets.items():
        ordered = sorted(values, key=lambda value: int(value[0]))
        expected = [bucket + index * 3600 for index in range(8)]
        if len(ordered) != 8 or [int(value[0]) for value in ordered] != expected:
            continue
        close_timestamp = bucket + BLOCK_SECONDS
        total_quote = sum(float(value[2]) for value in ordered)
        taker_buy_quote = sum(float(value[3]) for value in ordered)
        result[close_timestamp] = (
            float(ordered[-1][1]),
            2.0 * taker_buy_quote - total_quote,
            total_quote,
        )
    return result


def load_market(
    manifest_values: typing.Iterable[typing.Union[str, pathlib.Path]],
    cache_value: typing.Union[str, pathlib.Path],
    funding_values: typing.Iterable[typing.Union[str, pathlib.Path]],
) -> tuple[dict, dict]:
    manifest_paths = [pathlib.Path(value).resolve() for value in manifest_values]
    if len(manifest_paths) != EXPECTED_SYMBOLS:
        raise ValueError(f"signed-flow V1 requires {EXPECTED_SYMBOLS} manifests")
    cache = pathlib.Path(cache_value).resolve()
    market_cache = cache / "futures_um"
    blocks_by_symbol = {}
    manifest_artifacts = []
    raw_artifacts = []
    for manifest_path in manifest_paths:
        payload = json.loads(manifest_path.read_text(encoding="utf-8"))
        config = payload.get("config", {})
        mapping = config.get("symbol_mapping", {})
        if (
            payload.get("schema_version") != market_data.COLLECTOR_SCHEMA_VERSION
            or payload.get("market_type") != "futures_um"
            or config.get("candle_interval") != "1h"
            or len(mapping) != 1
        ):
            raise ValueError(f"invalid raw-flow manifest: {manifest_path}")
        symbol = next(iter(mapping))
        if symbol in blocks_by_symbol:
            raise ValueError(f"duplicate raw-flow symbol: {symbol}")
        hourly = {}
        records = sorted(
            (
                record
                for record in payload.get("archives", [])
                if "/1h/" in str(record.get("relative_path", ""))
            ),
            key=lambda record: record["relative_path"],
        )
        if len(records) < 40:
            raise ValueError(f"too few raw kline archives for {symbol}")
        for record in records:
            archive_path = market_cache / record["relative_path"]
            if (
                not archive_path.is_file()
                or archive_path.stat().st_size != int(record["bytes"])
                or common._sha256(archive_path) != record["sha256"]
            ):
                raise ValueError(f"raw archive verification failed: {archive_path}")
            raw_artifacts.append(
                {
                    "symbol": symbol,
                    "relative_path": record["relative_path"],
                    "bytes": int(record["bytes"]),
                    "sha256": record["sha256"],
                }
            )
            for row in market_data.parse_binance_kline_flow_archive(
                archive_path.read_bytes()
            ):
                timestamp = int(row[0])
                previous = hourly.setdefault(timestamp, row)
                if previous != row:
                    raise ValueError(f"conflicting raw kline at {timestamp}")
        blocks = _aggregate_eight_hour(hourly)
        if len(blocks) < 1000:
            raise ValueError(f"too few complete eight-hour blocks for {symbol}")
        blocks_by_symbol[symbol] = blocks
        manifest_artifacts.append(_artifact(manifest_path))

    symbols = sorted(blocks_by_symbol)
    if len(symbols) != EXPECTED_SYMBOLS:
        raise ValueError("raw-flow universe does not contain 18 unique symbols")
    timestamps = sorted(
        set.intersection(*(set(blocks_by_symbol[symbol]) for symbol in symbols))
    )
    if len(timestamps) < 1000:
        raise ValueError("too few common eight-hour blocks")
    gaps = [
        (previous, current)
        for previous, current in zip(timestamps, timestamps[1:])
        if current - previous != BLOCK_SECONDS
    ]
    if gaps:
        raise ValueError(f"common eight-hour market contains a gap: {gaps[0]}")
    closes = numpy.asarray(
        [
            [blocks_by_symbol[symbol][timestamp][0] for symbol in symbols]
            for timestamp in timestamps
        ],
        dtype=numpy.float64,
    )
    signed_flow = numpy.asarray(
        [
            [blocks_by_symbol[symbol][timestamp][1] for symbol in symbols]
            for timestamp in timestamps
        ],
        dtype=numpy.float64,
    )
    quote_volume = numpy.asarray(
        [
            [blocks_by_symbol[symbol][timestamp][2] for symbol in symbols]
            for timestamp in timestamps
        ],
        dtype=numpy.float64,
    )
    if (
        numpy.any(closes <= 0)
        or numpy.any(quote_volume < 0)
        or not numpy.all(numpy.isfinite(closes))
        or not numpy.all(numpy.isfinite(signed_flow))
        or not numpy.all(numpy.isfinite(quote_volume))
    ):
        raise ValueError("raw-flow block matrices are invalid")
    returns = numpy.zeros_like(closes)
    returns[1:] = closes[1:] / closes[:-1] - 1.0

    funding = {}
    funding_artifacts = []
    for value in funding_values:
        path = pathlib.Path(value).resolve()
        loaded = funding_module.load_funding(path)
        overlap = set(funding) & set(loaded)
        if overlap:
            raise ValueError(f"duplicate funding symbols: {sorted(overlap)}")
        funding.update(loaded)
        funding_artifacts.append(_artifact(path))
    if set(funding) != set(symbols):
        raise ValueError("funding universe differs from raw-flow universe")
    funding_matrix = numpy.zeros_like(closes)
    funding_settlements = numpy.zeros_like(closes, dtype=numpy.int16)
    timestamp_index = {timestamp: index for index, timestamp in enumerate(timestamps)}
    for column, symbol in enumerate(symbols):
        funding_timestamps, rates = funding[symbol]
        for timestamp, rate in zip(funding_timestamps, rates):
            timestamp = int(timestamp)
            if timestamp > 100_000_000_000:
                raise ValueError("funding timestamp is not expressed in seconds")
            block_close = (
                (timestamp + BLOCK_SECONDS - 1) // BLOCK_SECONDS * BLOCK_SECONDS
            )
            index = timestamp_index.get(block_close)
            if index is not None:
                funding_matrix[index, column] += float(rate)
                funding_settlements[index, column] += 1

    required_start = int(DEVELOPMENT_START.timestamp())
    required_end = int(LOCKED_END.timestamp())
    required_indices = [
        index
        for index, timestamp in enumerate(timestamps)
        if required_start < timestamp <= required_end
    ]
    if not required_indices or numpy.any(
        funding_settlements[required_indices] < 1
    ):
        missing = numpy.argwhere(funding_settlements[required_indices] < 1)
        first = missing[0] if len(missing) else None
        raise ValueError(
            "funding settlement coverage is incomplete"
            + (f"; first relative index={first.tolist()}" if first is not None else "")
        )

    raw_artifacts.sort(key=lambda value: (value["symbol"], value["relative_path"]))
    artifacts = {
        "collector_manifests": sorted(
            manifest_artifacts, key=lambda value: value["path"]
        ),
        "raw_archives": {
            "cache_path": str(cache),
            "count": len(raw_artifacts),
            "bytes": sum(value["bytes"] for value in raw_artifacts),
            "bundle_sha256": common._json_hash(raw_artifacts),
        },
        "funding": sorted(funding_artifacts, key=lambda value: value["path"]),
        "funding_coverage": {
            "required_blocks": len(required_indices),
            "minimum_settlements_per_symbol_block": int(
                numpy.min(funding_settlements[required_indices])
            ),
            "maximum_settlements_per_symbol_block": int(
                numpy.max(funding_settlements[required_indices])
            ),
        },
    }
    return {
        "timestamps": numpy.asarray(timestamps, dtype=numpy.int64),
        "symbols": symbols,
        "closes": closes,
        "returns": returns,
        "signed_flow": signed_flow,
        "quote_volume": quote_volume,
        "funding": funding_matrix,
    }, artifacts


def target_weights(market: dict, index: int) -> numpy.ndarray:
    if index < FORMATION_BLOCKS - 1 or index >= len(market["timestamps"]):
        raise IndexError("signed-flow target lacks its frozen formation window")
    flow = numpy.sum(
        market["signed_flow"][index - FORMATION_BLOCKS + 1 : index + 1],
        axis=0,
    )
    eligible = [
        column
        for column, value in enumerate(flow)
        if math.isfinite(float(value))
    ]
    if len(eligible) < 10:
        return numpy.zeros(len(market["symbols"]), dtype=numpy.float64)
    ordered = sorted(
        eligible,
        key=lambda column: (float(flow[column]), market["symbols"][column]),
    )
    count = max(1, int(math.floor(len(ordered) * SELECTION_FRACTION)))
    short_columns = ordered[:count]
    long_columns = ordered[-count:]
    target = numpy.zeros(len(market["symbols"]), dtype=numpy.float64)
    target[long_columns] = SIDE_GROSS_EXPOSURE / len(long_columns)
    target[short_columns] = -SIDE_GROSS_EXPOSURE / len(short_columns)
    return target


def _side_costs(previous, target, per_turnover_cost) -> tuple[float, float]:
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


def _period_returns(datetimes, equity, pattern: str) -> dict:
    endpoints = {}
    for timestamp, value in zip(datetimes, equity):
        endpoints[timestamp.strftime(pattern)] = float(value)
    result = {}
    previous = 1.0
    for period, value in sorted(endpoints.items()):
        result[period] = value / previous - 1.0
        previous = value
    return result


def _quarter_returns(datetimes, equity) -> dict:
    endpoints = {}
    for timestamp, value in zip(datetimes, equity):
        quarter = (timestamp.month - 1) // 3 + 1
        endpoints[f"{timestamp.year}-Q{quarter}"] = float(value)
    result = {}
    previous = 1.0
    for period, value in sorted(endpoints.items()):
        result[period] = value / previous - 1.0
        previous = value
    return result


def simulate_period(
    market: dict,
    start: datetime.datetime,
    end: datetime.datetime,
    *,
    cost_multiplier: float = 1.0,
    include_trajectory: bool = False,
) -> dict:
    if start.tzinfo is None or end.tzinfo is None or start >= end:
        raise ValueError("evaluation interval must be ordered and timezone-aware")
    if cost_multiplier < 1.0:
        raise ValueError("cost multiplier must be at least one")
    start_timestamp = int(start.timestamp())
    end_timestamp = int(end.timestamp())
    indices = [
        index
        for index, timestamp in enumerate(market["timestamps"])
        if start_timestamp <= int(timestamp) < end_timestamp
        and index + 1 < len(market["timestamps"])
    ]
    if not indices or indices[0] < FORMATION_BLOCKS - 1:
        raise ValueError("evaluation interval or signal warmup is absent")

    weights = numpy.zeros(len(market["symbols"]), dtype=numpy.float64)
    contribution = numpy.zeros_like(weights)
    equity = 1.0
    per_turnover_cost = cost_multiplier * (
        FEE_PER_TURNOVER + SLIPPAGE_PER_TURNOVER
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

        price = target * market["returns"][index + 1]
        funding = -target * market["funding"][index + 1]
        pnl = price + funding
        equity *= 1.0 + float(numpy.sum(pnl))
        if equity <= 0:
            raise ValueError("signed-flow factor equity became non-positive")
        contribution += pnl
        total_price += float(numpy.sum(price))
        total_funding += float(numpy.sum(funding))
        long_contribution += float(numpy.sum(pnl[target > 0]))
        short_contribution += float(numpy.sum(pnl[target < 0]))
        weights = target

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
    monthly = _period_returns(accounting_datetimes, equity_values, "%Y-%m")
    quarterly = _quarter_returns(accounting_datetimes, equity_values)
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
        "gross_exposure": numpy.sum(numpy.abs(weight_values), axis=1).tolist(),
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
        "total_turnover": total_turnover,
        "total_cost_return": total_cost,
        "total_price_return": total_price,
        "total_funding_return": total_funding,
        "long_additive_contribution": long_contribution,
        "short_additive_contribution": short_contribution,
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
    keep = [index for index in range(len(market["symbols"])) if index != column]
    return {
        "timestamps": market["timestamps"],
        "symbols": [market["symbols"][index] for index in keep],
        "closes": market["closes"][:, keep],
        "returns": market["returns"][:, keep],
        "signed_flow": market["signed_flow"][:, keep],
        "quote_volume": market["quote_volume"][:, keep],
        "funding": market["funding"][:, keep],
    }


def _finish_checks(checks: dict) -> dict:
    return {
        "checks": checks,
        "passed_checks": sum(checks.values()),
        "total_checks": len(checks),
        "passed": all(checks.values()),
    }


def _gate(report: dict, specification: dict) -> dict:
    return _finish_checks(
        {
            "minimum_blocks": (
                report["blocks"] >= specification["minimum_blocks"]
            ),
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
    )


def evaluate_prelock(
    protocol_value,
    manifest_values,
    cache_value,
    funding_values,
    output_root_value,
) -> dict:
    protocol_path = pathlib.Path(protocol_value).resolve()
    protocol = write_or_verify_protocol(protocol_path)
    market, artifacts = load_market(manifest_values, cache_value, funding_values)
    first_timestamp = int(market["timestamps"][0])
    final_timestamp = int(market["timestamps"][-1])
    if first_timestamp > int(DEVELOPMENT_START.timestamp()) - 7 * 86400:
        raise ValueError("market does not provide the frozen signal warmup")
    if final_timestamp < int(LOCKED_END.timestamp()):
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
        report["total_return"] > 0 for report in development_folds
    )
    leave_one_out = {
        symbol: simulate_period(
            _drop_market_column(market, column),
            DEVELOPMENT_START,
            DEVELOPMENT_END,
        )
        for column, symbol in enumerate(market["symbols"])
    }
    positive_leave_one_out = sum(
        report["total_return"] > 0 for report in leave_one_out.values()
    )
    development_gate = _gate(development, protocol["development_gate"])
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
            "development_gate_failed" if not development_gate["passed"] else None
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
            report["total_return"] > 0 for report in confirmation_quarters
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
    source_bundle_sha256 = common._json_hash(artifacts)
    output_root = pathlib.Path(output_root_value).resolve()
    experiment = output_root / (
        "signed-flow-v1-"
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
        "historical_price_periods_are_diagnostic_reuse": True,
        "protocol_path": str(protocol_path),
        "protocol_file_sha256": common._sha256(protocol_path),
        "protocol_sha256": protocol["protocol_sha256"],
        "source_bundle_sha256": source_bundle_sha256,
        "source_artifacts": artifacts,
        "symbols": market["symbols"],
        "market": {
            "start_utc": datetime.datetime.fromtimestamp(
                first_timestamp, UTC
            ).isoformat(),
            "end_utc": datetime.datetime.fromtimestamp(
                final_timestamp, UTC
            ).isoformat(),
            "blocks": len(market["timestamps"]),
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
    evaluate.add_argument("--collector-manifest", action="append", required=True)
    evaluate.add_argument("--archive-cache", required=True)
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
        args.collector_manifest,
        args.archive_cache,
        args.funding_json,
        args.output_root,
    )
    print(json.dumps(common._json_safe(result), indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
