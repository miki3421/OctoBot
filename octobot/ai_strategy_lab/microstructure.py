"""Append-only public KuCoin funding, basis and microstructure observer."""

from __future__ import annotations

import dataclasses
import datetime
import fcntl
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

from octobot.ai_strategy_lab import carry_shadow_runner as carry_shadow_runner_module


SCHEMA_VERSION = 1
EXECUTION_QUOTE_TARGETS = (100.0, 500.0, 1_000.0)
MINIMUM_SPOT_TAKER_FEE_RATE = 0.001
MINIMUM_FUTURES_TAKER_FEE_RATE = 0.0006
SPOT_TICKERS_URL = "https://api.kucoin.com/api/v1/market/allTickers"
FUTURES_TICKERS_URL = "https://api-futures.kucoin.com/api/v1/allTickers"
FUTURES_CONTRACTS_URL = (
    "https://api-futures.kucoin.com/api/v1/contracts/active"
)
SPOT_DEPTH_URL = (
    "https://api.kucoin.com/api/v1/market/orderbook/level2_20"
)
FUTURES_DEPTH_URL = (
    "https://api-futures.kucoin.com/api/v1/level2/depth20"
)
CURRENT_FUNDING_URL = (
    "https://api-futures.kucoin.com/api/v1/funding-rate/{symbol}/current"
)
FUNDING_HISTORY_URL = (
    "https://api-futures.kucoin.com/api/v1/contract/funding-rates"
)
DEFAULT_FUTURES_SYMBOLS = (
    carry_shadow_runner_module.KUCOIN_FUTURES_SYMBOLS
)
DEFAULT_SPOT_SYMBOLS = carry_shadow_runner_module.KUCOIN_SPOT_SYMBOLS
FetchJson = typing.Callable[[str, float], dict]


@dataclasses.dataclass(frozen=True)
class MicrostructureConfig:
    journal_path: pathlib.Path
    health_path: pathlib.Path
    lock_path: pathlib.Path
    archive_root: pathlib.Path | None = None
    interval_minutes: int = 15
    timeout_seconds: float = 30.0
    maximum_collection_seconds: float = 300.0
    futures_symbols: dict[str, str] = dataclasses.field(
        default_factory=lambda: dict(DEFAULT_FUTURES_SYMBOLS)
    )
    spot_symbols: dict[str, str] = dataclasses.field(
        default_factory=lambda: dict(DEFAULT_SPOT_SYMBOLS)
    )

    def validate(self) -> None:
        if self.interval_minutes < 1 or 60 % self.interval_minutes:
            raise ValueError("interval minutes must be a positive divisor of 60")
        if self.timeout_seconds <= 0:
            raise ValueError("request timeout must be positive")
        if self.maximum_collection_seconds <= 0:
            raise ValueError("maximum collection duration must be positive")
        if not self.futures_symbols or not self.spot_symbols:
            raise ValueError("spot and futures symbol mappings are required")
        futures_bases = {
            symbol.split("/", 1)[0] for symbol in self.futures_symbols
        }
        spot_bases = {
            symbol.split("/", 1)[0] for symbol in self.spot_symbols
        }
        if futures_bases != spot_bases:
            raise ValueError("spot and futures mappings must have identical bases")
        if len(futures_bases) != len(self.futures_symbols):
            raise ValueError("futures mapping contains duplicate bases")
        if len(spot_bases) != len(self.spot_symbols):
            raise ValueError("spot mapping contains duplicate bases")


def run_observation_once(
    config: MicrostructureConfig,
    *,
    now: typing.Optional[datetime.datetime] = None,
    fetch_json: FetchJson | None = None,
) -> dict:
    """Collect one complete interval or fail without appending a partial row."""
    config.validate()
    observed_at = now or datetime.datetime.now(datetime.timezone.utc)
    if observed_at.tzinfo is None:
        raise ValueError("observation time must be timezone-aware")
    observed_at = observed_at.astimezone(datetime.timezone.utc)
    bucket_start = observed_at.replace(
        minute=(
            observed_at.minute
            - observed_at.minute % config.interval_minutes
        ),
        second=0,
        microsecond=0,
    )
    bucket_id = bucket_start.isoformat()
    fetcher = fetch_json or _request_json
    archive_root = (
        config.archive_root
        if config.archive_root is not None
        else config.journal_path.parent / "records"
    )
    for path in (
        config.journal_path.parent,
        config.health_path.parent,
        config.lock_path.parent,
        archive_root,
    ):
        path.mkdir(parents=True, exist_ok=True)
    attempt_at = observed_at.isoformat()

    with config.lock_path.open("a+", encoding="utf-8") as lock_stream:
        try:
            fcntl.flock(
                lock_stream.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB
            )
        except BlockingIOError as error:
            raise RuntimeError(
                "microstructure observer is already active"
            ) from error
        try:
            records = load_microstructure_records(config.journal_path)
            records = _synchronize_archive(
                config.journal_path, archive_root, records
            )
            previous = records[-1] if records else None
            if previous is not None:
                previous_bucket = datetime.datetime.fromisoformat(
                    previous["bucket_start_utc"]
                )
                if previous_bucket > bucket_start:
                    raise ValueError(
                        "microstructure journal contains a future bucket"
                    )
                if previous_bucket == bucket_start:
                    return _write_success_health(
                        config,
                        previous,
                        attempt_at=attempt_at,
                        appended=False,
                    )
            started = time.monotonic()
            record = _collect_record(
                config,
                fetcher=fetcher,
                bucket_start=bucket_start,
                attempt_at=attempt_at,
                previous_hash=(
                    previous["record_hash"] if previous else None
                ),
            )
            duration = time.monotonic() - started
            if duration > config.maximum_collection_seconds:
                raise RuntimeError(
                    "microstructure collection exceeded maximum duration"
                )
            record["collection_duration_seconds"] = round(duration, 6)
            record["record_hash"] = _record_hash(record)
            _archive_record(archive_root, record)
            _append_jsonl(config.journal_path, record)
            return _write_success_health(
                config,
                record,
                attempt_at=attempt_at,
                appended=True,
            )
        except Exception as error:
            previous_health = _read_json(config.health_path)
            _write_json_atomic(
                config.health_path,
                {
                    "schema_version": SCHEMA_VERSION,
                    "mode": "observation_only",
                    "public_data_only": True,
                    "credentials_used": False,
                    "orders_authorized": False,
                    "status": "failed",
                    "last_attempt_at": attempt_at,
                    "last_success_at": previous_health.get(
                        "last_success_at"
                    ),
                    "bucket_start_utc": bucket_id,
                    "error_type": type(error).__name__,
                    "error": str(error),
                    "archive_root": str(archive_root),
                },
            )
            raise


def load_microstructure_records(
    path_value: str | pathlib.Path,
) -> list[dict]:
    path = pathlib.Path(path_value)
    if not path.exists():
        return []
    records = []
    previous_hash = None
    previous_bucket = None
    with path.open("r", encoding="utf-8") as stream:
        for line_number, line in enumerate(stream, start=1):
            if not line.strip():
                continue
            try:
                record = json.loads(line)
            except json.JSONDecodeError as error:
                raise ValueError(
                    f"invalid microstructure JSONL at line {line_number}"
                ) from error
            if record.get("schema_version") != SCHEMA_VERSION:
                raise ValueError("unsupported microstructure journal schema")
            if record.get("previous_record_hash") != previous_hash:
                raise ValueError(
                    "microstructure journal hash chain is broken"
                )
            expected_hash = _record_hash(record)
            if record.get("record_hash") != expected_hash:
                raise ValueError(
                    "microstructure journal record hash is invalid"
                )
            bucket = datetime.datetime.fromisoformat(
                record["bucket_start_utc"]
            )
            if bucket.tzinfo is None:
                raise ValueError("microstructure bucket is not timezone-aware")
            if previous_bucket is not None and bucket <= previous_bucket:
                raise ValueError(
                    "microstructure journal is duplicate or out of order"
                )
            if (
                record.get("mode") != "observation_only"
                or record.get("public_data_only") is not True
                or record.get("credentials_used") is not False
                or record.get("orders_authorized") is not False
            ):
                raise ValueError(
                    "microstructure journal safety invariant failed"
                )
            records.append(record)
            previous_hash = record["record_hash"]
            previous_bucket = bucket
    return records


def _collect_record(
    config,
    *,
    fetcher,
    bucket_start,
    attempt_at,
    previous_hash,
):
    observation_timestamp_ms = int(
        datetime.datetime.fromisoformat(attempt_at).timestamp() * 1000
    )
    funding_history_start_ms = (
        observation_timestamp_ms - 24 * 3600 * 1000
    )
    spot_payload = _fetch_payload(
        fetcher, SPOT_TICKERS_URL, config.timeout_seconds
    )
    futures_payload = _fetch_payload(
        fetcher, FUTURES_TICKERS_URL, config.timeout_seconds
    )
    contracts_payload = _fetch_payload(
        fetcher, FUTURES_CONTRACTS_URL, config.timeout_seconds
    )
    spot_tickers = {
        value["symbol"]: value
        for value in spot_payload["data"]["ticker"]
    }
    spot_ticker_snapshot_timestamp_ms = int(
        _nonnegative_float(
            spot_payload["data"].get("time"),
            "spot ticker snapshot timestamp",
        )
    )
    futures_tickers = {
        value["symbol"]: value for value in futures_payload["data"]
    }
    contract_values = contracts_payload["data"]
    if isinstance(contract_values, dict):
        contract_values = [contract_values]
    contracts = {value["symbol"]: value for value in contract_values}

    futures_by_base = {
        symbol.split("/", 1)[0]: (symbol, remote)
        for symbol, remote in config.futures_symbols.items()
    }
    spot_by_base = {
        symbol.split("/", 1)[0]: (symbol, remote)
        for symbol, remote in config.spot_symbols.items()
    }
    observations = {}
    for base in sorted(futures_by_base):
        futures_symbol, futures_remote = futures_by_base[base]
        spot_symbol, spot_remote = spot_by_base[base]
        if spot_remote not in spot_tickers:
            raise ValueError(f"missing spot ticker for {spot_remote}")
        if futures_remote not in futures_tickers:
            raise ValueError(f"missing futures ticker for {futures_remote}")
        if futures_remote not in contracts:
            raise ValueError(f"missing contract details for {futures_remote}")

        spot_depth_url = _with_query(
            SPOT_DEPTH_URL, {"symbol": spot_remote}
        )
        futures_depth_url = _with_query(
            FUTURES_DEPTH_URL, {"symbol": futures_remote}
        )
        funding_url = CURRENT_FUNDING_URL.format(
            symbol=urllib.parse.quote(futures_remote, safe="")
        )
        funding_history_url = _with_query(
            FUNDING_HISTORY_URL,
            {
                "symbol": futures_remote,
                "from": funding_history_start_ms,
                "to": observation_timestamp_ms,
            },
        )
        spot_book = _fetch_payload(
            fetcher, spot_depth_url, config.timeout_seconds
        )["data"]
        futures_book = _fetch_payload(
            fetcher, futures_depth_url, config.timeout_seconds
        )["data"]
        funding = _fetch_payload(
            fetcher, funding_url, config.timeout_seconds
        )["data"]
        settled_funding = _fetch_payload(
            fetcher, funding_history_url, config.timeout_seconds
        )["data"]
        observations[base] = _build_symbol_observation(
            base=base,
            spot_symbol=spot_symbol,
            futures_symbol=futures_symbol,
            spot_remote=spot_remote,
            futures_remote=futures_remote,
            spot_ticker=spot_tickers[spot_remote],
            futures_ticker=futures_tickers[futures_remote],
            contract=contracts[futures_remote],
            spot_book=spot_book,
            futures_book=futures_book,
            funding=funding,
            settled_funding=settled_funding,
            spot_ticker_snapshot_timestamp_ms=(
                spot_ticker_snapshot_timestamp_ms
            ),
        )
    if len(observations) != len(config.futures_symbols):
        raise ValueError("microstructure observation is incomplete")

    bucket_end = bucket_start + datetime.timedelta(
        minutes=config.interval_minutes
    )
    return {
        "schema_version": SCHEMA_VERSION,
        "mode": "observation_only",
        "public_data_only": True,
        "credentials_used": False,
        "orders_authorized": False,
        "research_only": True,
        "bucket_start_utc": bucket_start.isoformat(),
        "bucket_end_utc": bucket_end.isoformat(),
        "observed_at_start": attempt_at,
        "observed_at_end": datetime.datetime.now(
            datetime.timezone.utc
        ).isoformat(),
        "interval_minutes": config.interval_minutes,
        "depth_levels_requested": 20,
        "symbol_count": len(observations),
        "completeness": 1.0,
        "previous_record_hash": previous_hash,
        "endpoints": {
            "spot_tickers": SPOT_TICKERS_URL,
            "futures_tickers": FUTURES_TICKERS_URL,
            "futures_contracts": FUTURES_CONTRACTS_URL,
            "spot_depth": SPOT_DEPTH_URL,
            "futures_depth": FUTURES_DEPTH_URL,
            "current_funding": CURRENT_FUNDING_URL,
            "funding_history": FUNDING_HISTORY_URL,
        },
        "spot_ticker_snapshot_timestamp_ms": (
            spot_ticker_snapshot_timestamp_ms
        ),
        "symbols": observations,
    }


def _build_symbol_observation(
    *,
    base,
    spot_symbol,
    futures_symbol,
    spot_remote,
    futures_remote,
    spot_ticker,
    futures_ticker,
    contract,
    spot_book,
    futures_book,
    funding,
    settled_funding,
    spot_ticker_snapshot_timestamp_ms,
):
    multiplier = _positive_float(contract.get("multiplier"), "multiplier")
    open_interest = _nonnegative_float(
        contract.get("openInterest"), "open interest"
    )
    spot = _book_metrics(
        spot_book,
        quantity_multiplier=1.0,
        label=f"spot {spot_remote}",
    )
    futures = _book_metrics(
        futures_book,
        quantity_multiplier=multiplier,
        label=f"futures {futures_remote}",
    )
    entry_basis_bps = (
        futures["best_bid"] / spot["best_ask"] - 1.0
    ) * 10_000.0
    exit_basis_bps = (
        futures["best_ask"] / spot["best_bid"] - 1.0
    ) * 10_000.0
    granularity_ms = int(
        _positive_float(funding.get("granularity"), "funding granularity")
    )
    current_rate = _finite_float(funding.get("value"), "current funding")
    predicted_value = funding.get("predictedValue")
    predicted_rate = (
        None
        if predicted_value is None
        else _finite_float(predicted_value, "predicted funding")
    )
    periods_per_year = 365.0 * 24 * 3600 * 1000 / granularity_ms
    settled_points = _settled_funding_points(
        settled_funding, futures_remote
    )
    mark_price = _positive_float(contract.get("markPrice"), "mark price")
    index_price = _positive_float(
        contract.get("indexPrice"), "index price"
    )
    spot_ticker_bid = _positive_float(spot_ticker.get("buy"), "spot ticker bid")
    spot_ticker_ask = _positive_float(spot_ticker.get("sell"), "spot ticker ask")
    spot_taker_fee_rate = _nonnegative_float(
        spot_ticker.get("takerFeeRate"), "spot taker fee rate"
    ) * _positive_float(
        spot_ticker.get("takerCoefficient", 1),
        "spot taker fee coefficient",
    )
    futures_taker_fee_rate = _nonnegative_float(
        contract.get("takerFeeRate"), "futures taker fee rate"
    )
    futures_ticker_bid = _positive_float(
        futures_ticker.get("bestBidPrice"), "futures ticker bid"
    )
    futures_ticker_ask = _positive_float(
        futures_ticker.get("bestAskPrice"), "futures ticker ask"
    )
    if spot_ticker_bid > spot_ticker_ask:
        raise ValueError(f"crossed spot ticker for {spot_remote}")
    if futures_ticker_bid > futures_ticker_ask:
        raise ValueError(f"crossed futures ticker for {futures_remote}")
    return {
        "base": base,
        "spot_symbol": spot_symbol,
        "futures_symbol": futures_symbol,
        "spot_remote_symbol": spot_remote,
        "futures_remote_symbol": futures_remote,
        "spot": {
            **spot,
            "ticker_bid": spot_ticker_bid,
            "ticker_ask": spot_ticker_ask,
            "published_taker_fee_rate": spot_taker_fee_rate,
            "conservative_taker_fee_rate": max(
                MINIMUM_SPOT_TAKER_FEE_RATE,
                spot_taker_fee_rate,
            ),
            "ticker_snapshot_timestamp_ms": (
                spot_ticker_snapshot_timestamp_ms
            ),
            "book_timestamp_ms": int(
                _nonnegative_float(
                    spot_book.get("time"), "spot book timestamp"
                )
            ),
            # Kept as a schema-1 compatibility alias.
            "ticker_timestamp_ms": int(
                _nonnegative_float(
                    spot_book.get("time"), "spot book timestamp"
                )
            ),
        },
        "futures": {
            **futures,
            "ticker_bid": futures_ticker_bid,
            "ticker_ask": futures_ticker_ask,
            "ticker_timestamp_ms": _timestamp_ms(
                futures_ticker.get("ts")
            ),
            "book_timestamp_ms": _timestamp_ms(futures_book.get("ts")),
            "contract_multiplier": multiplier,
            "published_taker_fee_rate": futures_taker_fee_rate,
            "conservative_taker_fee_rate": max(
                MINIMUM_FUTURES_TAKER_FEE_RATE,
                futures_taker_fee_rate,
            ),
            "open_interest_contracts": open_interest,
            "open_interest_base": open_interest * multiplier,
            "open_interest_quote": (
                open_interest * multiplier * mark_price
            ),
            "mark_price": mark_price,
            "index_price": index_price,
            "mark_index_basis_bps": (
                mark_price / index_price - 1.0
            )
            * 10_000.0,
        },
        "carry_execution": {
            "entry_basis_bps": entry_basis_bps,
            "exit_basis_bps": exit_basis_bps,
            "round_trip_book_width_bps": (
                exit_basis_bps - entry_basis_bps
            ),
            "entry_capacity_usdt_depth20": min(
                spot["ask_depth_quote"],
                futures["bid_depth_quote"],
            ),
            "exit_capacity_usdt_depth20": min(
                spot["bid_depth_quote"],
                futures["ask_depth_quote"],
            ),
            "mid_price_fill_assumed": False,
        },
        "funding": {
            "current_rate": current_rate,
            "predicted_rate": predicted_rate,
            "current_simple_annualized": current_rate * periods_per_year,
            "predicted_simple_annualized": (
                None
                if predicted_rate is None
                else predicted_rate * periods_per_year
            ),
            "granularity_ms": granularity_ms,
            "time_point_ms": int(
                _nonnegative_float(
                    funding.get("timePoint"), "funding time point"
                )
            ),
            "funding_time_ms": int(
                _nonnegative_float(
                    funding.get("fundingTime"), "funding time"
                )
            ),
            "rate_cap": _finite_float(
                funding.get("fundingRateCap"), "funding cap"
            ),
            "rate_floor": _finite_float(
                funding.get("fundingRateFloor"), "funding floor"
            ),
            "settled_last_24h": settled_points,
        },
    }


def _book_metrics(book, *, quantity_multiplier, label):
    bids = sorted(
        _levels(book.get("bids"), f"{label} bids"),
        key=lambda value: value[0],
        reverse=True,
    )
    asks = sorted(
        _levels(book.get("asks"), f"{label} asks"),
        key=lambda value: value[0],
    )
    best_bid = bids[0][0]
    best_ask = asks[0][0]
    if best_bid > best_ask:
        raise ValueError(f"crossed order book for {label}")
    bid_execution = _execution_curve(
        bids, quantity_multiplier=quantity_multiplier
    )
    ask_execution = _execution_curve(
        asks, quantity_multiplier=quantity_multiplier
    )
    return {
        "best_bid": best_bid,
        "best_ask": best_ask,
        "spread_bps": (best_ask / best_bid - 1.0) * 10_000.0,
        "bid_levels": len(bids),
        "ask_levels": len(asks),
        "bid_depth_quote": sum(
            price * quantity * quantity_multiplier
            for price, quantity in bids
        ),
        "ask_depth_quote": sum(
            price * quantity * quantity_multiplier
            for price, quantity in asks
        ),
        "bid_vwap_by_quote": bid_execution,
        "ask_vwap_by_quote": ask_execution,
        "normalized_bids": _normalized_levels(
            bids, quantity_multiplier=quantity_multiplier
        ),
        "normalized_asks": _normalized_levels(
            asks, quantity_multiplier=quantity_multiplier
        ),
    }


def _levels(values, label):
    if not isinstance(values, list) or not values:
        raise ValueError(f"{label} are missing")
    result = []
    for value in values:
        if not isinstance(value, list) or len(value) < 2:
            raise ValueError(f"{label} contain an invalid level")
        result.append(
            (
                _positive_float(value[0], f"{label} price"),
                _positive_float(value[1], f"{label} quantity"),
            )
        )
    return result


def _execution_curve(levels, *, quantity_multiplier):
    curve = {}
    normalized = _normalized_level_tuples(
        levels, quantity_multiplier=quantity_multiplier
    )
    for target in EXECUTION_QUOTE_TARGETS:
        remaining = target
        filled_quote = 0.0
        filled_base = 0.0
        last_price = None
        for price, _, level_quote in normalized:
            take_quote = min(remaining, level_quote)
            if take_quote <= 0:
                continue
            filled_quote += take_quote
            filled_base += take_quote / price
            remaining -= take_quote
            last_price = price
            if remaining <= 1e-9:
                break
        sufficient = remaining <= 1e-9
        curve[f"{target:g}"] = {
            "target_quote": target,
            "filled_quote": filled_quote,
            "filled_base": filled_base,
            "vwap": (
                filled_quote / filled_base
                if filled_base > 0
                else None
            ),
            "last_price": last_price,
            "sufficient_depth": sufficient,
        }
    return curve


def _normalized_level_tuples(levels, *, quantity_multiplier):
    return [
        (
            price,
            quantity * quantity_multiplier,
            price * quantity * quantity_multiplier,
        )
        for price, quantity in levels
    ]


def _normalized_levels(levels, *, quantity_multiplier):
    return [
        {
            "price": price,
            "base_quantity": base_quantity,
            "quote_quantity": quote_quantity,
        }
        for price, base_quantity, quote_quantity in (
            _normalized_level_tuples(
                levels, quantity_multiplier=quantity_multiplier
            )
        )
    ]


def _settled_funding_points(values, symbol):
    if not isinstance(values, list) or not values:
        raise ValueError(f"settled funding is missing for {symbol}")
    points = {}
    for value in values:
        if not isinstance(value, dict):
            raise ValueError(f"settled funding is invalid for {symbol}")
        remote_symbol = value.get("symbol")
        if remote_symbol is not None and remote_symbol != symbol:
            raise ValueError(f"settled funding symbol mismatch for {symbol}")
        timestamp = int(
            _nonnegative_float(
                value.get("timepoint"), "settled funding timestamp"
            )
        )
        points[timestamp] = _finite_float(
            value.get("fundingRate"), "settled funding rate"
        )
    return [
        {"timestamp_ms": timestamp, "rate": points[timestamp]}
        for timestamp in sorted(points)
    ]


def _fetch_payload(fetcher, url, timeout):
    payload = fetcher(url, timeout)
    if not isinstance(payload, dict) or payload.get("code") != "200000":
        raise RuntimeError(f"KuCoin public request failed for {url}")
    if "data" not in payload:
        raise RuntimeError(f"KuCoin public response has no data for {url}")
    return payload


def _request_json(url: str, timeout_seconds: float) -> dict:
    request = urllib.request.Request(
        url, headers={"User-Agent": "OctoBot-Forward-Observer/1"}
    )
    with urllib.request.urlopen(
        request, timeout=timeout_seconds
    ) as response:
        return json.load(response)


def _with_query(url, values):
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


def _timestamp_ms(value):
    timestamp = int(_nonnegative_float(value, "market timestamp"))
    if timestamp > 10**16:
        return timestamp // 1_000_000
    if timestamp > 10**13:
        return timestamp // 1_000
    return timestamp


def _record_hash(record):
    value = {
        key: element
        for key, element in record.items()
        if key != "record_hash"
    }
    encoded = json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _synchronize_archive(journal_path, archive_root, journal_records):
    archive_root.mkdir(parents=True, exist_ok=True)
    for record in journal_records:
        _archive_record(archive_root, record)
    archived = _load_archive_records(archive_root)
    journal_hashes = [
        record["record_hash"] for record in journal_records
    ]
    archive_hashes = [record["record_hash"] for record in archived]
    if archive_hashes[: len(journal_hashes)] != journal_hashes:
        raise ValueError(
            "microstructure archive is not a prefix extension of journal"
        )
    if len(archive_hashes) < len(journal_hashes):
        raise ValueError("microstructure archive is shorter than journal")
    for record in archived[len(journal_hashes) :]:
        _append_jsonl(journal_path, record)
    if len(archived) != len(journal_records):
        recovered = load_microstructure_records(journal_path)
        if [value["record_hash"] for value in recovered] != archive_hashes:
            raise ValueError(
                "microstructure archive recovery verification failed"
            )
        return recovered
    return journal_records


def _archive_record(archive_root, record):
    bucket = datetime.datetime.fromisoformat(record["bucket_start_utc"])
    filename = (
        f"{bucket.strftime('%Y%m%dT%H%M%SZ')}-"
        f"{record['record_hash']}.json"
    )
    path = archive_root / filename
    if path.exists():
        try:
            existing = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as error:
            raise ValueError(
                f"invalid microstructure archive file: {path.name}"
            ) from error
        if existing != record:
            raise ValueError(
                f"microstructure archive record mismatch: {path.name}"
            )
        return path
    _write_json_atomic(path, record)
    return path


def _load_archive_records(archive_root):
    records = []
    for path in archive_root.glob("*.json"):
        try:
            record = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as error:
            raise ValueError(
                f"invalid microstructure archive file: {path.name}"
            ) from error
        if record.get("schema_version") != SCHEMA_VERSION:
            raise ValueError("unsupported microstructure archive schema")
        if record.get("record_hash") != _record_hash(record):
            raise ValueError("microstructure archive record hash is invalid")
        if (
            record.get("mode") != "observation_only"
            or record.get("public_data_only") is not True
            or record.get("credentials_used") is not False
            or record.get("orders_authorized") is not False
        ):
            raise ValueError(
                "microstructure archive safety invariant failed"
            )
        records.append(record)
    records.sort(key=lambda value: value["bucket_start_utc"])
    previous_hash = None
    previous_bucket = None
    for record in records:
        bucket = datetime.datetime.fromisoformat(
            record["bucket_start_utc"]
        )
        if bucket.tzinfo is None:
            raise ValueError(
                "microstructure archive bucket is not timezone-aware"
            )
        if record.get("previous_record_hash") != previous_hash:
            raise ValueError("microstructure archive hash chain is broken")
        if previous_bucket is not None and bucket <= previous_bucket:
            raise ValueError(
                "microstructure archive is duplicate or out of order"
            )
        previous_hash = record["record_hash"]
        previous_bucket = bucket
    return records


def _append_jsonl(path, record):
    encoded = json.dumps(
        record,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    )
    with path.open("a", encoding="utf-8") as stream:
        stream.write(encoded)
        stream.write("\n")
        stream.flush()
        os.fsync(stream.fileno())


def _write_success_health(
    config, record, *, attempt_at, appended
):
    funding_rates = [
        value["funding"]["current_rate"]
        for value in record["symbols"].values()
    ]
    entry_basis = [
        value["carry_execution"]["entry_basis_bps"]
        for value in record["symbols"].values()
    ]
    health = {
        "schema_version": SCHEMA_VERSION,
        "mode": "observation_only",
        "public_data_only": True,
        "credentials_used": False,
        "orders_authorized": False,
        "status": "healthy",
        "last_attempt_at": attempt_at,
        "last_success_at": datetime.datetime.now(
            datetime.timezone.utc
        ).isoformat(),
        "bucket_start_utc": record["bucket_start_utc"],
        "journal_path": str(config.journal_path),
        "journal_appended": appended,
        "record_hash": record["record_hash"],
        "symbol_count": record["symbol_count"],
        "archive_root": str(
            config.archive_root
            if config.archive_root is not None
            else config.journal_path.parent / "records"
        ),
        "archived_records": len(
            list(
                (
                    config.archive_root
                    if config.archive_root is not None
                    else config.journal_path.parent / "records"
                ).glob("*.json")
            )
        ),
        "archive_consistent": True,
        "minimum_current_funding_rate": min(funding_rates),
        "maximum_current_funding_rate": max(funding_rates),
        "minimum_entry_basis_bps": min(entry_basis),
        "maximum_entry_basis_bps": max(entry_basis),
    }
    _write_json_atomic(config.health_path, health)
    return health


def _read_json(path):
    if not path.exists():
        return {}
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return value if isinstance(value, dict) else {}


def _write_json_atomic(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary_value = tempfile.mkstemp(
        prefix=f".{path.name}.", suffix=".tmp", dir=path.parent
    )
    temporary = pathlib.Path(temporary_value)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
            json.dump(
                value,
                stream,
                indent=2,
                sort_keys=True,
                allow_nan=False,
            )
            stream.write("\n")
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    finally:
        if temporary.exists():
            temporary.unlink()
