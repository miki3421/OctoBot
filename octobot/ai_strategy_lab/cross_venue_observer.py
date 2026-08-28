"""Compressed, append-only Binance/KuCoin public book observer.

The observer records synchronized market evidence only. It has no private API
surface, credentials, signals, positions or order path.
"""

from __future__ import annotations

import argparse
import concurrent.futures
import dataclasses
import datetime
import fcntl
import gzip
import hashlib
import json
import math
import os
import pathlib
import tempfile
import time
import typing
import urllib.parse
import urllib.request

from octobot.ai_strategy_lab import cross_venue_carry_v1 as carry_protocol
from octobot.ai_strategy_lab import microstructure as book_common
from octobot.ai_strategy_lab import shadow_runner


SCHEMA_VERSION = 1
OBSERVER_TYPE = "binance_kucoin_cross_venue_books_v1"
FORWARD_START = datetime.datetime(
    2026, 8, 29, 0, tzinfo=datetime.timezone.utc
)
EXECUTION_QUOTE_TARGETS = (100.0, 500.0, 1_000.0)
MAXIMUM_CLIENT_MIDPOINT_SKEW_SECONDS = 1.0
MAXIMUM_SERVER_BOOK_AGE_SECONDS = 30.0
MAXIMUM_SERVER_FUTURE_SKEW_SECONDS = 5.0
CONSERVATIVE_TAKER_FEE_RATE = 0.0006
KUCOIN_CONTRACTS_URL = (
    "https://api-futures.kucoin.com/api/v1/contracts/active"
)
KUCOIN_DEPTH_URL = (
    "https://api-futures.kucoin.com/api/v1/level2/depth20"
)
BINANCE_PREMIUM_URL = "https://fapi.binance.com/fapi/v1/premiumIndex"
BINANCE_FUNDING_INFO_URL = "https://fapi.binance.com/fapi/v1/fundingInfo"
BINANCE_DEPTH_URL = "https://fapi.binance.com/fapi/v1/depth"
BINANCE_OPEN_INTEREST_URL = (
    "https://fapi.binance.com/fapi/v1/openInterest"
)
FetchJson = typing.Callable[[str, float], typing.Any]


def _default_symbol_mapping() -> dict[str, dict[str, str]]:
    return {
        symbol: {
            "kucoin": shadow_runner.KUCOIN_FUTURES_SYMBOLS[symbol],
            "binance": f"{symbol.split('/', 1)[0]}USDT",
        }
        for symbol in carry_protocol.SYMBOLS
    }


@dataclasses.dataclass(frozen=True)
class CrossVenueObserverConfig:
    archive_root: pathlib.Path
    index_path: pathlib.Path
    health_path: pathlib.Path
    lock_path: pathlib.Path
    interval_minutes: int = 15
    timeout_seconds: float = 20.0
    maximum_collection_seconds: float = 180.0
    maximum_client_midpoint_skew_seconds: float = (
        MAXIMUM_CLIENT_MIDPOINT_SKEW_SECONDS
    )
    maximum_server_book_age_seconds: float = (
        MAXIMUM_SERVER_BOOK_AGE_SECONDS
    )
    maximum_server_future_skew_seconds: float = (
        MAXIMUM_SERVER_FUTURE_SKEW_SECONDS
    )
    symbol_mapping: dict[str, dict[str, str]] = dataclasses.field(
        default_factory=_default_symbol_mapping
    )

    def validate(self) -> None:
        if self.interval_minutes < 1 or 60 % self.interval_minutes:
            raise ValueError("interval minutes must be a positive divisor of 60")
        if self.timeout_seconds <= 0:
            raise ValueError("request timeout must be positive")
        if self.maximum_collection_seconds <= 0:
            raise ValueError("maximum collection duration must be positive")
        if self.maximum_client_midpoint_skew_seconds <= 0:
            raise ValueError("maximum client midpoint skew must be positive")
        if self.maximum_server_book_age_seconds <= 0:
            raise ValueError("maximum server book age must be positive")
        if self.maximum_server_future_skew_seconds < 0:
            raise ValueError("maximum server future skew cannot be negative")
        if not self.symbol_mapping:
            raise ValueError("at least one cross-venue symbol is required")
        for symbol, mapping in self.symbol_mapping.items():
            if set(mapping) != {"binance", "kucoin"}:
                raise ValueError(f"invalid venue mapping for {symbol}")
            if not mapping["binance"] or not mapping["kucoin"]:
                raise ValueError(f"empty venue mapping for {symbol}")


def run_observation_once(
    config: CrossVenueObserverConfig,
    *,
    now: typing.Optional[datetime.datetime] = None,
    fetch_json: FetchJson | None = None,
) -> dict:
    """Append one complete bucket, or fail without a partial record."""

    config.validate()
    observed_at = now or datetime.datetime.now(datetime.timezone.utc)
    if observed_at.tzinfo is None:
        raise ValueError("observation time must be timezone-aware")
    observed_at = observed_at.astimezone(datetime.timezone.utc)
    bucket_start = observed_at.replace(
        minute=observed_at.minute
        - observed_at.minute % config.interval_minutes,
        second=0,
        microsecond=0,
    )
    attempt_at = observed_at.isoformat()
    fetcher = fetch_json or _request_json
    for path in (
        config.archive_root,
        config.index_path.parent,
        config.health_path.parent,
        config.lock_path.parent,
    ):
        path.mkdir(parents=True, exist_ok=True)

    with config.lock_path.open("a+", encoding="utf-8") as lock_stream:
        try:
            fcntl.flock(
                lock_stream.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB
            )
        except BlockingIOError as error:
            raise RuntimeError(
                "cross-venue observer is already active"
            ) from error
        try:
            previous, index_rows = _synchronize_index(config)
            if previous is not None:
                previous_bucket = datetime.datetime.fromisoformat(
                    previous["bucket_start_utc"]
                )
                if previous_bucket > bucket_start:
                    raise ValueError("cross-venue archive contains future bucket")
                if previous_bucket == bucket_start:
                    return _write_success_health(
                        config,
                        previous,
                        index_rows,
                        attempt_at=attempt_at,
                        appended=False,
                        full_audit_performed=False,
                    )

            started = time.monotonic()
            record = _collect_record(
                config,
                bucket_start=bucket_start,
                attempt_at=attempt_at,
                previous_hash=(
                    previous["record_hash"] if previous else None
                ),
                fetcher=fetcher,
            )
            duration = time.monotonic() - started
            if duration > config.maximum_collection_seconds:
                raise RuntimeError(
                    "cross-venue collection exceeded maximum duration"
                )
            record["collection_duration_seconds"] = round(duration, 6)
            record["record_hash"] = _record_hash(record)
            index_row = _archive_record(config.archive_root, record)
            _append_index(config.index_path, index_row)
            index_rows.append(index_row)

            previous_health = _read_json(config.health_path)
            audit_due = _full_audit_due(previous_health, bucket_start)
            if audit_due:
                audit_archive(config)
            return _write_success_health(
                config,
                record,
                index_rows,
                attempt_at=attempt_at,
                appended=True,
                full_audit_performed=audit_due,
            )
        except Exception as error:
            previous_health = _read_json(config.health_path)
            _write_json_atomic(
                config.health_path,
                {
                    "schema_version": SCHEMA_VERSION,
                    "observer_type": OBSERVER_TYPE,
                    "mode": "observation_only",
                    "public_data_only": True,
                    "credentials_used": False,
                    "orders_authorized": False,
                    "paper_orders_authorized": False,
                    "automatic_promotion": False,
                    "status": "failed",
                    "last_attempt_at": attempt_at,
                    "last_success_at": previous_health.get(
                        "last_success_at"
                    ),
                    "last_full_audit_at": previous_health.get(
                        "last_full_audit_at"
                    ),
                    "bucket_start_utc": bucket_start.isoformat(),
                    "error_type": type(error).__name__,
                    "error": str(error),
                },
            )
            raise


def _collect_record(
    config,
    *,
    bucket_start,
    attempt_at,
    previous_hash,
    fetcher,
):
    with concurrent.futures.ThreadPoolExecutor(max_workers=3) as executor:
        kucoin_contracts_future = executor.submit(
            _timed_fetch,
            fetcher,
            KUCOIN_CONTRACTS_URL,
            config.timeout_seconds,
        )
        binance_premium_future = executor.submit(
            _timed_fetch,
            fetcher,
            BINANCE_PREMIUM_URL,
            config.timeout_seconds,
        )
        binance_funding_info_future = executor.submit(
            _timed_fetch,
            fetcher,
            BINANCE_FUNDING_INFO_URL,
            config.timeout_seconds,
        )
        kucoin_payload, kucoin_timing = kucoin_contracts_future.result()
        binance_payload, binance_timing = binance_premium_future.result()
        funding_info_payload, funding_info_timing = (
            binance_funding_info_future.result()
        )
        contracts = _kucoin_contracts(kucoin_payload)
        premiums = _binance_premiums(binance_payload)
        funding_info = _binance_funding_info(funding_info_payload)

        symbols = {}
        for symbol, mapping in sorted(config.symbol_mapping.items()):
            kucoin_remote = mapping["kucoin"]
            binance_remote = mapping["binance"]
            if kucoin_remote not in contracts:
                raise ValueError(f"missing KuCoin contract {kucoin_remote}")
            if binance_remote not in premiums:
                raise ValueError(f"missing Binance premium {binance_remote}")
            if binance_remote not in funding_info:
                raise ValueError(f"missing Binance funding info {binance_remote}")
            kucoin_url = _with_query(
                KUCOIN_DEPTH_URL, {"symbol": kucoin_remote}
            )
            binance_url = _with_query(
                BINANCE_DEPTH_URL,
                {"symbol": binance_remote, "limit": 20},
            )
            open_interest_url = _with_query(
                BINANCE_OPEN_INTEREST_URL,
                {"symbol": binance_remote},
            )
            kucoin_future = executor.submit(
                _timed_fetch,
                fetcher,
                kucoin_url,
                config.timeout_seconds,
            )
            binance_future = executor.submit(
                _timed_fetch,
                fetcher,
                binance_url,
                config.timeout_seconds,
            )
            open_interest_future = executor.submit(
                _timed_fetch,
                fetcher,
                open_interest_url,
                config.timeout_seconds,
            )
            kucoin_depth_payload, kucoin_depth_timing = (
                kucoin_future.result()
            )
            binance_depth_payload, binance_depth_timing = (
                binance_future.result()
            )
            open_interest_payload, open_interest_timing = (
                open_interest_future.result()
            )
            symbols[symbol.split("/", 1)[0]] = _build_symbol_observation(
                symbol=symbol,
                kucoin_remote=kucoin_remote,
                binance_remote=binance_remote,
                contract=contracts[kucoin_remote],
                premium=premiums[binance_remote],
                funding_info=funding_info[binance_remote],
                kucoin_depth=_kucoin_data(kucoin_depth_payload),
                binance_depth=_binance_dict(
                    binance_depth_payload, "Binance depth"
                ),
                open_interest=_binance_dict(
                    open_interest_payload, "Binance open interest"
                ),
                kucoin_depth_timing=kucoin_depth_timing,
                binance_depth_timing=binance_depth_timing,
                open_interest_timing=open_interest_timing,
                maximum_client_skew_seconds=(
                    config.maximum_client_midpoint_skew_seconds
                ),
                maximum_server_age_seconds=(
                    config.maximum_server_book_age_seconds
                ),
                maximum_server_future_seconds=(
                    config.maximum_server_future_skew_seconds
                ),
            )

    if len(symbols) != len(config.symbol_mapping):
        raise ValueError("cross-venue observation is incomplete")
    eligible_count = sum(
        value["timing"]["forward_eligible"] for value in symbols.values()
    )
    bucket_end = bucket_start + datetime.timedelta(
        minutes=config.interval_minutes
    )
    eligible_after_start = bucket_start >= FORWARD_START
    return {
        "schema_version": SCHEMA_VERSION,
        "observer_type": OBSERVER_TYPE,
        "mode": "observation_only",
        "research_only": True,
        "public_data_only": True,
        "credentials_used": False,
        "orders_authorized": False,
        "paper_orders_authorized": False,
        "automatic_promotion": False,
        "signals_generated": False,
        "outcomes_read": False,
        "bucket_start_utc": bucket_start.isoformat(),
        "bucket_end_utc": bucket_end.isoformat(),
        "observed_at_start": attempt_at,
        "observed_at_end": datetime.datetime.now(
            datetime.timezone.utc
        ).isoformat(),
        "interval_minutes": config.interval_minutes,
        "depth_levels_requested": 20,
        "execution_quote_targets": list(EXECUTION_QUOTE_TARGETS),
        "symbol_count": len(symbols),
        "eligible_symbol_count": eligible_count,
        "maximum_client_midpoint_skew_seconds": (
            config.maximum_client_midpoint_skew_seconds
        ),
        "maximum_server_book_age_seconds": (
            config.maximum_server_book_age_seconds
        ),
        "maximum_server_future_skew_seconds": (
            config.maximum_server_future_skew_seconds
        ),
        "forward_start_utc": FORWARD_START.isoformat(),
        "forward_eligible": (
            eligible_after_start and eligible_count == len(symbols)
        ),
        "completeness": 1.0,
        "previous_record_hash": previous_hash,
        "global_requests": {
            "kucoin_contracts": kucoin_timing,
            "binance_premium": binance_timing,
            "binance_funding_info": funding_info_timing,
        },
        "endpoints": {
            "kucoin_contracts": KUCOIN_CONTRACTS_URL,
            "kucoin_depth": KUCOIN_DEPTH_URL,
            "binance_premium": BINANCE_PREMIUM_URL,
            "binance_funding_info": BINANCE_FUNDING_INFO_URL,
            "binance_depth": BINANCE_DEPTH_URL,
            "binance_open_interest": BINANCE_OPEN_INTEREST_URL,
        },
        "symbols": symbols,
    }


def _build_symbol_observation(
    *,
    symbol,
    kucoin_remote,
    binance_remote,
    contract,
    premium,
    funding_info,
    kucoin_depth,
    binance_depth,
    open_interest,
    kucoin_depth_timing,
    binance_depth_timing,
    open_interest_timing,
    maximum_client_skew_seconds,
    maximum_server_age_seconds,
    maximum_server_future_seconds,
):
    if open_interest.get("symbol") != binance_remote:
        raise ValueError(f"Binance open-interest symbol mismatch {symbol}")
    if kucoin_depth.get("symbol") not in (None, kucoin_remote):
        raise ValueError(f"KuCoin depth symbol mismatch {symbol}")
    multiplier = _positive_float(
        contract.get("multiplier"), f"{symbol} KuCoin multiplier"
    )
    kucoin_book = book_common._book_metrics(
        kucoin_depth,
        quantity_multiplier=multiplier,
        label=f"KuCoin {kucoin_remote}",
    )
    binance_book = book_common._book_metrics(
        binance_depth,
        quantity_multiplier=1.0,
        label=f"Binance {binance_remote}",
    )
    kucoin_timestamp_ms = book_common._timestamp_ms(
        kucoin_depth.get("ts")
    )
    binance_timestamp_ms = book_common._timestamp_ms(
        binance_depth.get("T", binance_depth.get("E"))
    )
    midpoint_skew_ms = abs(
        _request_midpoint_ms(kucoin_depth_timing)
        - _request_midpoint_ms(binance_depth_timing)
    )
    server_skew_ms = abs(kucoin_timestamp_ms - binance_timestamp_ms)
    kucoin_book_age_ms = (
        _request_midpoint_ms(kucoin_depth_timing) - kucoin_timestamp_ms
    )
    binance_book_age_ms = (
        _request_midpoint_ms(binance_depth_timing) - binance_timestamp_ms
    )
    timing_eligible = (
        midpoint_skew_ms <= maximum_client_skew_seconds * 1000.0
        and -maximum_server_future_seconds * 1000.0
        <= kucoin_book_age_ms
        <= maximum_server_age_seconds * 1000.0
        and -maximum_server_future_seconds * 1000.0
        <= binance_book_age_ms
        <= maximum_server_age_seconds * 1000.0
    )
    kucoin_mark = _positive_float(
        contract.get("markPrice"), f"{symbol} KuCoin mark"
    )
    kucoin_index = _positive_float(
        contract.get("indexPrice"), f"{symbol} KuCoin index"
    )
    binance_mark = _positive_float(
        premium.get("markPrice"), f"{symbol} Binance mark"
    )
    binance_index = _positive_float(
        premium.get("indexPrice"), f"{symbol} Binance index"
    )
    kucoin_rate = _finite_float(
        contract.get("fundingFeeRate"), f"{symbol} KuCoin funding"
    )
    predicted_value = contract.get("predictedFundingFeeRate")
    kucoin_predicted = (
        None
        if predicted_value is None
        else _finite_float(
            predicted_value, f"{symbol} KuCoin predicted funding"
        )
    )
    kucoin_granularity = int(
        _positive_float(
            contract.get(
                "currentFundingRateGranularity"
            )
            or contract.get("fundingRateGranularity"),
            f"{symbol} KuCoin funding granularity",
        )
    )
    binance_rate = _finite_float(
        premium.get("lastFundingRate"), f"{symbol} Binance funding"
    )
    binance_next_funding_ms = int(
        _positive_float(
            premium.get("nextFundingTime"),
            f"{symbol} Binance next funding",
        )
    )
    binance_observed_ms = int(
        _positive_float(
            premium.get("time"), f"{symbol} Binance premium time"
        )
    )
    binance_interval_hours = int(
        _positive_float(
            funding_info.get("fundingIntervalHours"),
            f"{symbol} Binance funding interval",
        )
    )
    binance_granularity = binance_interval_hours * 3600 * 1000
    kucoin_periods = 365.0 * 24 * 3600 * 1000 / kucoin_granularity
    binance_periods = 365.0 * 24 * 3600 * 1000 / binance_granularity
    execution = _cross_venue_execution(kucoin_book, binance_book)
    return {
        "symbol": symbol,
        "remote_symbols": {
            "kucoin": kucoin_remote,
            "binance": binance_remote,
        },
        "timing": {
            "kucoin_depth_request": kucoin_depth_timing,
            "binance_depth_request": binance_depth_timing,
            "binance_open_interest_request": open_interest_timing,
            "client_request_midpoint_skew_ms": midpoint_skew_ms,
            "server_book_timestamp_skew_ms": server_skew_ms,
            "kucoin_book_age_at_request_midpoint_ms": kucoin_book_age_ms,
            "binance_book_age_at_request_midpoint_ms": binance_book_age_ms,
            "forward_eligible": timing_eligible,
        },
        "kucoin": {
            "book": kucoin_book,
            "book_timestamp_ms": kucoin_timestamp_ms,
            "contract_multiplier": multiplier,
            "published_taker_fee_rate": _nonnegative_float(
                contract.get("takerFeeRate"),
                f"{symbol} KuCoin taker fee",
            ),
            "conservative_taker_fee_rate": max(
                CONSERVATIVE_TAKER_FEE_RATE,
                _nonnegative_float(
                    contract.get("takerFeeRate"),
                    f"{symbol} KuCoin taker fee",
                ),
            ),
            "mark_price": kucoin_mark,
            "index_price": kucoin_index,
            "mark_index_basis_bps": (
                kucoin_mark / kucoin_index - 1.0
            )
            * 10_000.0,
            "open_interest_contracts": _nonnegative_float(
                contract.get("openInterest"),
                f"{symbol} KuCoin open interest",
            ),
            "open_interest_base": _nonnegative_float(
                contract.get("openInterest"),
                f"{symbol} KuCoin open interest",
            )
            * multiplier,
            "funding": {
                "current_rate": kucoin_rate,
                "predicted_rate": kucoin_predicted,
                "granularity_ms": kucoin_granularity,
                "current_simple_annualized": kucoin_rate * kucoin_periods,
                "predicted_simple_annualized": (
                    None
                    if kucoin_predicted is None
                    else kucoin_predicted * kucoin_periods
                ),
                "next_funding_time_ms": int(
                    _positive_float(
                        contract.get("nextFundingRateDateTime"),
                        f"{symbol} KuCoin next funding",
                    )
                ),
            },
        },
        "binance": {
            "book": binance_book,
            "book_timestamp_ms": binance_timestamp_ms,
            "published_taker_fee_rate": None,
            "conservative_taker_fee_rate": (
                CONSERVATIVE_TAKER_FEE_RATE
            ),
            "mark_price": binance_mark,
            "index_price": binance_index,
            "mark_index_basis_bps": (
                binance_mark / binance_index - 1.0
            )
            * 10_000.0,
            "open_interest_base": _nonnegative_float(
                open_interest.get("openInterest"),
                f"{symbol} Binance open interest",
            ),
            "open_interest_timestamp_ms": int(
                _positive_float(
                    open_interest.get("time"),
                    f"{symbol} Binance open-interest time",
                )
            ),
            "funding": {
                "last_rate": binance_rate,
                "granularity_ms_estimate": binance_granularity,
                "last_simple_annualized": binance_rate * binance_periods,
                "next_funding_time_ms": binance_next_funding_ms,
                "premium_snapshot_time_ms": binance_observed_ms,
                "interval_source": "public_funding_info",
                "adjusted_rate_cap": _finite_float(
                    funding_info.get("adjustedFundingRateCap"),
                    f"{symbol} Binance funding cap",
                ),
                "adjusted_rate_floor": _finite_float(
                    funding_info.get("adjustedFundingRateFloor"),
                    f"{symbol} Binance funding floor",
                ),
                "funding_info_update_time_ms": (
                    None
                    if funding_info.get("updateTime") is None
                    else int(
                        _nonnegative_float(
                            funding_info.get("updateTime"),
                            f"{symbol} Binance funding-info time",
                        )
                    )
                ),
            },
        },
        "cross_venue": {
            "kucoin_mark_minus_binance_mark_bps": (
                kucoin_mark / binance_mark - 1.0
            )
            * 10_000.0,
            "current_funding_advantage_long_binance_short_kucoin": (
                kucoin_rate * kucoin_periods
                - binance_rate * binance_periods
            ),
            "execution_by_quote_per_leg": execution,
            "mid_price_fill_assumed": False,
            "same_base_quantity_per_leg": True,
        },
    }


def _cross_venue_execution(kucoin_book: dict, binance_book: dict) -> dict:
    kucoin_mid = (
        kucoin_book["best_bid"] + kucoin_book["best_ask"]
    ) / 2.0
    binance_mid = (
        binance_book["best_bid"] + binance_book["best_ask"]
    ) / 2.0
    reference = (kucoin_mid + binance_mid) / 2.0
    result = {}
    for quote_target in EXECUTION_QUOTE_TARGETS:
        target_base = quote_target / reference
        kucoin_bid = _execute_base(
            kucoin_book["normalized_bids"], target_base
        )
        kucoin_ask = _execute_base(
            kucoin_book["normalized_asks"], target_base
        )
        binance_bid = _execute_base(
            binance_book["normalized_bids"], target_base
        )
        binance_ask = _execute_base(
            binance_book["normalized_asks"], target_base
        )
        result[f"{quote_target:g}"] = {
            "target_quote_per_leg": quote_target,
            "target_base_per_leg": target_base,
            "long_binance_short_kucoin": _execution_direction(
                long_entry=binance_ask,
                long_exit=binance_bid,
                short_entry=kucoin_bid,
                short_exit=kucoin_ask,
            ),
            "long_kucoin_short_binance": _execution_direction(
                long_entry=kucoin_ask,
                long_exit=kucoin_bid,
                short_entry=binance_bid,
                short_exit=binance_ask,
            ),
        }
    return result


def _execute_base(levels: list[dict], target_base: float) -> dict:
    remaining = target_base
    filled_base = 0.0
    filled_quote = 0.0
    last_price = None
    for level in levels:
        take_base = min(remaining, float(level["base_quantity"]))
        if take_base <= 0:
            continue
        price = float(level["price"])
        filled_base += take_base
        filled_quote += take_base * price
        remaining -= take_base
        last_price = price
        if remaining <= 1e-12:
            break
    return {
        "filled_base": filled_base,
        "filled_quote": filled_quote,
        "vwap": filled_quote / filled_base if filled_base > 0 else None,
        "last_price": last_price,
        "sufficient_depth": remaining <= 1e-12,
    }


def _execution_direction(
    *,
    long_entry,
    long_exit,
    short_entry,
    short_exit,
) -> dict:
    executions = (long_entry, long_exit, short_entry, short_exit)
    sufficient = all(value["sufficient_depth"] for value in executions)
    if not sufficient:
        return {
            "sufficient_depth": False,
            "long_entry": long_entry,
            "long_exit": long_exit,
            "short_entry": short_entry,
            "short_exit": short_exit,
            "entry_cross_venue_basis_bps": None,
            "immediate_two_leg_return_bps_before_fee": None,
            "immediate_two_leg_return_bps_after_taker_fee": None,
        }
    long_entry_price = float(long_entry["vwap"])
    long_exit_price = float(long_exit["vwap"])
    short_entry_price = float(short_entry["vwap"])
    short_exit_price = float(short_exit["vwap"])
    before_fee = (
        long_exit_price / long_entry_price - 1.0
        + 1.0
        - short_exit_price / short_entry_price
    ) * 10_000.0
    four_fill_fee_bps = 4.0 * CONSERVATIVE_TAKER_FEE_RATE * 10_000.0
    return {
        "sufficient_depth": True,
        "long_entry": long_entry,
        "long_exit": long_exit,
        "short_entry": short_entry,
        "short_exit": short_exit,
        "entry_cross_venue_basis_bps": (
            short_entry_price / long_entry_price - 1.0
        )
        * 10_000.0,
        "immediate_two_leg_return_bps_before_fee": before_fee,
        "four_fill_conservative_taker_fee_bps": four_fill_fee_bps,
        "immediate_two_leg_return_bps_after_taker_fee": (
            before_fee - four_fill_fee_bps
        ),
    }


def _timed_fetch(fetcher, url, timeout):
    started = datetime.datetime.now(datetime.timezone.utc)
    started_monotonic = time.monotonic()
    payload = fetcher(url, timeout)
    duration = time.monotonic() - started_monotonic
    ended = datetime.datetime.now(datetime.timezone.utc)
    return payload, {
        "url": url,
        "started_at": started.isoformat(),
        "ended_at": ended.isoformat(),
        "started_at_ms": int(started.timestamp() * 1000),
        "ended_at_ms": int(ended.timestamp() * 1000),
        "duration_seconds": round(duration, 6),
    }


def _request_midpoint_ms(timing: dict) -> float:
    return (
        float(timing["started_at_ms"]) + float(timing["ended_at_ms"])
    ) / 2.0


def _kucoin_contracts(payload) -> dict:
    values = _kucoin_data(payload)
    if not isinstance(values, list):
        raise ValueError("KuCoin contracts payload is not a list")
    return {value["symbol"]: value for value in values}


def _kucoin_data(payload):
    if not isinstance(payload, dict) or payload.get("code") != "200000":
        raise RuntimeError("KuCoin public response failed")
    if "data" not in payload:
        raise RuntimeError("KuCoin public response lacks data")
    return payload["data"]


def _binance_premiums(payload) -> dict:
    if not isinstance(payload, list):
        raise RuntimeError("Binance premium response is not a list")
    return {value["symbol"]: value for value in payload}


def _binance_funding_info(payload) -> dict:
    if not isinstance(payload, list):
        raise RuntimeError("Binance funding-info response is not a list")
    return {value["symbol"]: value for value in payload}


def _binance_dict(payload, label):
    if not isinstance(payload, dict):
        raise RuntimeError(f"{label} response is not an object")
    if "code" in payload and int(payload["code"]) < 0:
        raise RuntimeError(f"{label} request failed")
    return payload


def _with_query(url: str, values: dict) -> str:
    return f"{url}?{urllib.parse.urlencode(values)}"


def _finite_float(value, label):
    try:
        number = float(value)
    except (TypeError, ValueError) as error:
        raise ValueError(f"{label} is not numeric") from error
    if not math.isfinite(number):
        raise ValueError(f"{label} is not finite")
    return number


def _positive_float(value, label):
    number = _finite_float(value, label)
    if number <= 0:
        raise ValueError(f"{label} must be positive")
    return number


def _nonnegative_float(value, label):
    number = _finite_float(value, label)
    if number < 0:
        raise ValueError(f"{label} must be nonnegative")
    return number


def _request_json(url: str, timeout_seconds: float):
    request = urllib.request.Request(
        url, headers={"User-Agent": "OctoBot-Cross-Venue-Observer/1"}
    )
    with urllib.request.urlopen(
        request, timeout=timeout_seconds
    ) as response:
        return json.load(response)


def _record_hash(record: dict) -> str:
    value = {
        key: element for key, element in record.items() if key != "record_hash"
    }
    return hashlib.sha256(_canonical_bytes(value)).hexdigest()


def _canonical_bytes(value) -> bytes:
    return json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")


def _validate_record(record: dict, previous_hash=None) -> None:
    if record.get("schema_version") != SCHEMA_VERSION:
        raise ValueError("unsupported cross-venue archive schema")
    if record.get("observer_type") != OBSERVER_TYPE:
        raise ValueError("cross-venue archive observer type differs")
    if (
        record.get("mode") != "observation_only"
        or record.get("public_data_only") is not True
        or record.get("credentials_used") is not False
        or record.get("orders_authorized") is not False
        or record.get("paper_orders_authorized") is not False
        or record.get("automatic_promotion") is not False
    ):
        raise ValueError("cross-venue archive safety invariant failed")
    if record.get("previous_record_hash") != previous_hash:
        raise ValueError("cross-venue archive hash chain is broken")
    if record.get("record_hash") != _record_hash(record):
        raise ValueError("cross-venue archive record hash is invalid")


def _archive_record(archive_root: pathlib.Path, record: dict) -> dict:
    bucket = datetime.datetime.fromisoformat(record["bucket_start_utc"])
    filename = (
        f"{bucket.strftime('%Y%m%dT%H%M%SZ')}-"
        f"{record['record_hash']}.json.gz"
    )
    path = archive_root / filename
    payload = gzip.compress(_canonical_bytes(record), compresslevel=6, mtime=0)
    if path.exists():
        existing = path.read_bytes()
        if existing != payload:
            raise ValueError("cross-venue archive filename collision")
    else:
        _write_bytes_atomic(path, payload)
    return _index_row(record, path, payload)


def _read_archive(path: pathlib.Path) -> tuple[dict, bytes]:
    payload = path.read_bytes()
    try:
        record = json.loads(gzip.decompress(payload))
    except (OSError, json.JSONDecodeError) as error:
        raise ValueError(f"invalid compressed archive {path.name}") from error
    return record, payload


def _index_row(record: dict, path: pathlib.Path, payload: bytes) -> dict:
    return {
        "schema_version": SCHEMA_VERSION,
        "observer_type": OBSERVER_TYPE,
        "bucket_start_utc": record["bucket_start_utc"],
        "record_hash": record["record_hash"],
        "previous_record_hash": record["previous_record_hash"],
        "archive_filename": path.name,
        "archive_sha256": hashlib.sha256(payload).hexdigest(),
        "compressed_bytes": len(payload),
        "symbol_count": record["symbol_count"],
        "eligible_symbol_count": record["eligible_symbol_count"],
        "forward_eligible": record["forward_eligible"],
        "public_data_only": True,
        "orders_authorized": False,
    }


def _read_index(path: pathlib.Path) -> list[dict]:
    if not path.exists():
        return []
    rows = []
    previous_hash = None
    previous_bucket = None
    with path.open("r", encoding="utf-8") as stream:
        for line_number, line in enumerate(stream, start=1):
            if not line.strip():
                continue
            try:
                row = json.loads(line)
            except json.JSONDecodeError as error:
                raise ValueError(
                    f"invalid cross-venue index line {line_number}"
                ) from error
            if row.get("schema_version") != SCHEMA_VERSION:
                raise ValueError("unsupported cross-venue index schema")
            if row.get("observer_type") != OBSERVER_TYPE:
                raise ValueError("cross-venue index observer type differs")
            if row.get("previous_record_hash") != previous_hash:
                raise ValueError("cross-venue index hash chain is broken")
            bucket = datetime.datetime.fromisoformat(
                row["bucket_start_utc"]
            )
            if bucket.tzinfo is None:
                raise ValueError("cross-venue index bucket lacks timezone")
            if previous_bucket is not None and bucket <= previous_bucket:
                raise ValueError("cross-venue index is out of order")
            if (
                row.get("public_data_only") is not True
                or row.get("orders_authorized") is not False
            ):
                raise ValueError("cross-venue index safety invariant failed")
            rows.append(row)
            previous_hash = row["record_hash"]
            previous_bucket = bucket
    return rows


def _synchronize_index(config) -> tuple[typing.Optional[dict], list[dict]]:
    rows = _read_index(config.index_path)
    files = sorted(config.archive_root.glob("*.json.gz"))
    if len(rows) > len(files):
        raise ValueError("cross-venue index is longer than archive")
    for row, path in zip(rows, files):
        if row["archive_filename"] != path.name:
            raise ValueError("cross-venue index is not an archive prefix")
    previous_hash = rows[-1]["record_hash"] if rows else None
    previous_bucket = (
        datetime.datetime.fromisoformat(rows[-1]["bucket_start_utc"])
        if rows
        else None
    )
    previous_record = None
    if rows:
        previous_record, payload = _read_archive(files[len(rows) - 1])
        _validate_record(
            previous_record,
            previous_hash=rows[-1]["previous_record_hash"],
        )
        if hashlib.sha256(payload).hexdigest() != rows[-1]["archive_sha256"]:
            raise ValueError("cross-venue archive tail checksum differs")
        if previous_record["record_hash"] != rows[-1]["record_hash"]:
            raise ValueError("cross-venue archive tail differs from index")
    for path in files[len(rows) :]:
        record, payload = _read_archive(path)
        _validate_record(record, previous_hash=previous_hash)
        bucket = datetime.datetime.fromisoformat(record["bucket_start_utc"])
        if previous_bucket is not None and bucket <= previous_bucket:
            raise ValueError("cross-venue archive is out of order")
        row = _index_row(record, path, payload)
        _append_index(config.index_path, row)
        rows.append(row)
        previous_hash = record["record_hash"]
        previous_bucket = bucket
        previous_record = record
    return previous_record, rows


def audit_archive(config: CrossVenueObserverConfig) -> dict:
    """Fully verify compressed payloads, index and safety invariants."""

    rows = _read_index(config.index_path)
    files = sorted(config.archive_root.glob("*.json.gz"))
    if len(rows) != len(files):
        raise ValueError("cross-venue archive/index length differs")
    previous_hash = None
    previous_bucket = None
    total_bytes = 0
    for row, path in zip(rows, files):
        if row["archive_filename"] != path.name:
            raise ValueError("cross-venue archive/index filename differs")
        record, payload = _read_archive(path)
        _validate_record(record, previous_hash=previous_hash)
        bucket = datetime.datetime.fromisoformat(record["bucket_start_utc"])
        if previous_bucket is not None and bucket <= previous_bucket:
            raise ValueError("cross-venue archive audit order failed")
        expected_row = _index_row(record, path, payload)
        if expected_row != row:
            raise ValueError("cross-venue archive/index content differs")
        previous_hash = record["record_hash"]
        previous_bucket = bucket
        total_bytes += len(payload)
    return {
        "schema_version": SCHEMA_VERSION,
        "observer_type": OBSERVER_TYPE,
        "archive_consistent": True,
        "records": len(rows),
        "compressed_bytes": total_bytes,
        "tail_record_hash": previous_hash,
        "audited_at": datetime.datetime.now(datetime.timezone.utc).isoformat(),
        "orders_authorized": False,
    }


def load_records(config: CrossVenueObserverConfig) -> list[dict]:
    audit_archive(config)
    records = []
    previous_hash = None
    for path in sorted(config.archive_root.glob("*.json.gz")):
        record, _ = _read_archive(path)
        _validate_record(record, previous_hash=previous_hash)
        records.append(record)
        previous_hash = record["record_hash"]
    return records


def _append_index(path: pathlib.Path, row: dict) -> None:
    encoded = _canonical_bytes(row).decode("utf-8")
    with path.open("a", encoding="utf-8") as stream:
        stream.write(encoded)
        stream.write("\n")
        stream.flush()
        os.fsync(stream.fileno())


def _write_success_health(
    config,
    record,
    index_rows,
    *,
    attempt_at,
    appended,
    full_audit_performed,
):
    previous_health = _read_json(config.health_path)
    if full_audit_performed:
        last_full_audit_at = datetime.datetime.now(
            datetime.timezone.utc
        ).isoformat()
    else:
        last_full_audit_at = previous_health.get("last_full_audit_at")
    total_bytes = sum(row["compressed_bytes"] for row in index_rows)
    average_bytes = total_bytes / len(index_rows) if index_rows else 0.0
    index_bytes = (
        config.index_path.stat().st_size
        if config.index_path.exists()
        else 0
    )
    average_index_bytes = index_bytes / len(index_rows) if index_rows else 0.0
    forward_rows = [row for row in index_rows if row["forward_eligible"]]
    observed_days = {
        datetime.datetime.fromisoformat(row["bucket_start_utc"]).date()
        for row in forward_rows
    }
    health = {
        "schema_version": SCHEMA_VERSION,
        "observer_type": OBSERVER_TYPE,
        "mode": "observation_only",
        "public_data_only": True,
        "credentials_used": False,
        "orders_authorized": False,
        "paper_orders_authorized": False,
        "automatic_promotion": False,
        "status": "healthy",
        "last_attempt_at": attempt_at,
        "last_success_at": datetime.datetime.now(
            datetime.timezone.utc
        ).isoformat(),
        "last_full_audit_at": last_full_audit_at,
        "bucket_start_utc": record["bucket_start_utc"],
        "journal_appended": appended,
        "record_hash": record["record_hash"],
        "symbol_count": record["symbol_count"],
        "eligible_symbol_count": record["eligible_symbol_count"],
        "forward_eligible": record["forward_eligible"],
        "forward_start_utc": FORWARD_START.isoformat(),
        "forward_eligible_records": len(forward_rows),
        "forward_observed_days": len(observed_days),
        "archive_root": str(config.archive_root),
        "index_path": str(config.index_path),
        "archived_records": len(index_rows),
        "archive_consistent": True,
        "compressed_archive_bytes": total_bytes,
        "index_bytes": index_bytes,
        "estimated_compressed_bytes_per_day": round(
            (average_bytes + average_index_bytes)
            * 24
            * 60
            / config.interval_minutes
        ),
        "full_payload_duplicate_journal": False,
        "collection_duration_seconds": record[
            "collection_duration_seconds"
        ],
    }
    _write_json_atomic(config.health_path, health)
    return health


def _full_audit_due(previous_health: dict, bucket_start) -> bool:
    value = previous_health.get("last_full_audit_at")
    if not value:
        return True
    try:
        last = datetime.datetime.fromisoformat(value)
    except (TypeError, ValueError):
        return True
    return last.astimezone(datetime.timezone.utc).date() < bucket_start.date()


def _read_json(path: pathlib.Path) -> dict:
    if not path.exists():
        return {}
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return value if isinstance(value, dict) else {}


def _write_bytes_atomic(path: pathlib.Path, payload: bytes) -> None:
    descriptor, temporary_value = tempfile.mkstemp(
        prefix=f".{path.name}.", suffix=".tmp", dir=path.parent
    )
    temporary = pathlib.Path(temporary_value)
    try:
        with os.fdopen(descriptor, "wb") as stream:
            stream.write(payload)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    finally:
        if temporary.exists():
            temporary.unlink()


def _write_json_atomic(path: pathlib.Path, value: dict) -> None:
    descriptor, temporary_value = tempfile.mkstemp(
        prefix=f".{path.name}.", suffix=".tmp", dir=path.parent
    )
    temporary = pathlib.Path(temporary_value)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
            json.dump(value, stream, indent=2, sort_keys=True, allow_nan=False)
            stream.write("\n")
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    finally:
        if temporary.exists():
            temporary.unlink()


def _config_from_args(args) -> CrossVenueObserverConfig:
    return CrossVenueObserverConfig(
        archive_root=pathlib.Path(args.archive_root).resolve(),
        index_path=pathlib.Path(args.index).resolve(),
        health_path=pathlib.Path(args.health).resolve(),
        lock_path=pathlib.Path(args.lock).resolve(),
        interval_minutes=args.interval_minutes,
        timeout_seconds=args.timeout_seconds,
        maximum_collection_seconds=args.maximum_collection_seconds,
        maximum_client_midpoint_skew_seconds=(
            args.maximum_client_midpoint_skew_seconds
        ),
        maximum_server_book_age_seconds=args.maximum_server_book_age_seconds,
        maximum_server_future_skew_seconds=(
            args.maximum_server_future_skew_seconds
        ),
    )


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)
    run = subparsers.add_parser("run-once")
    audit = subparsers.add_parser("audit")
    for command in (run, audit):
        command.add_argument("--archive-root", required=True)
        command.add_argument("--index", required=True)
        command.add_argument("--health", required=True)
        command.add_argument("--lock", required=True)
        command.add_argument("--interval-minutes", type=int, default=15)
        command.add_argument("--timeout-seconds", type=float, default=20.0)
        command.add_argument(
            "--maximum-collection-seconds", type=float, default=180.0
        )
        command.add_argument(
            "--maximum-client-midpoint-skew-seconds",
            type=float,
            default=MAXIMUM_CLIENT_MIDPOINT_SKEW_SECONDS,
        )
        command.add_argument(
            "--maximum-server-book-age-seconds",
            type=float,
            default=MAXIMUM_SERVER_BOOK_AGE_SECONDS,
        )
        command.add_argument(
            "--maximum-server-future-skew-seconds",
            type=float,
            default=MAXIMUM_SERVER_FUTURE_SKEW_SECONDS,
        )
    return parser


def main(argv=None) -> int:
    args = _parser().parse_args(argv)
    config = _config_from_args(args)
    if args.command == "audit":
        result = audit_archive(config)
    else:
        result = run_observation_once(config)
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
