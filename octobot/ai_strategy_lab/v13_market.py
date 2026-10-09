"""Read-only KuCoin quote adapter for the separately versioned V13 paper account.

Reuses the existing public microstructure collector: no client, network access,
credentials or order adapter. The bounded tail validates the latest record and,
when present, its predecessor, not the entire historical hash chain.

Book quantities are already base-asset quantities. ``step`` uses declared
quantity precision when present; the legacy one-contract fallback is retained
for reductions only. Multiplier alone proves neither entry precision nor minima.
Funding rates are actual archived settlements, but their application to a recent
mark instead of the exact settlement mark remains a paper approximation.
"""

from __future__ import annotations

import datetime
import hashlib
import json
import math
import pathlib
import re


UTC = datetime.timezone.utc
MAX_QUOTE_AGE_SECONDS = 1800
ADVERSE_SLIPPAGE_RATE = 0.0002


def _number(value, name, *, positive=False, nonnegative=False):
    if isinstance(value, bool):
        raise ValueError(f"invalid {name}")
    try:
        value = float(value)
    except (TypeError, ValueError) as error:
        raise ValueError(f"invalid {name}") from error
    if not math.isfinite(value) or (positive and value <= 0) or (
        nonnegative and value < 0
    ):
        raise ValueError(f"invalid {name}")
    return value


def _time(value, name):
    try:
        parsed = datetime.datetime.fromisoformat(value.replace("Z", "+00:00"))
    except (AttributeError, TypeError, ValueError) as error:
        raise ValueError(f"invalid {name}") from error
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ValueError(f"timezone missing from {name}")
    return parsed.astimezone(UTC)


def _millis(value, name):
    number = _number(value, name, positive=True)
    if number != int(number):
        raise ValueError(f"invalid integer {name}")
    return int(number)


def normalize_symbol(value):
    if not isinstance(value, str):
        raise ValueError("invalid market symbol")
    parts = value.upper().split(":")
    if len(parts) > 2 or (len(parts) == 2 and parts[1] != "USDT"):
        raise ValueError("unsupported market settlement")
    symbol = parts[0].replace("/", "")
    if not re.fullmatch(r"[A-Z0-9]+USDT", symbol):
        raise ValueError("unsupported market symbol")
    return symbol


def _verify_hash(record):
    if not isinstance(record, dict):
        raise ValueError("market record must be an object")
    try:
        encoded = json.dumps(
            {key: value for key, value in record.items() if key != "record_hash"},
            sort_keys=True, separators=(",", ":"), allow_nan=False,
        ).encode("utf-8")
    except (TypeError, ValueError) as error:
        raise ValueError("invalid market record encoding") from error
    if record.get("record_hash") != hashlib.sha256(encoded).hexdigest():
        raise ValueError("market record hash mismatch")


def _validate_record(record, now, max_age_seconds):
    _verify_hash(record)
    if (
        record.get("schema_version") not in (1, 2)
        or record.get("mode") != "observation_only"
        or record.get("public_data_only") is not True
        or record.get("credentials_used") is not False
        or record.get("orders_authorized") is not False
        or record.get("paper_orders_authorized", False) is not False
    ):
        raise ValueError("market record safety invariant failed")
    # Legacy records are bound to this KuCoin-only adapter. Explicit provenance
    # must agree; never relabel a record declaring a different venue or market.
    if record.get("market_identity", "kucoin_futures_usdt") != "kucoin_futures_usdt":
        raise ValueError("market identity mismatch")
    if "endpoints" in record:
        endpoints = record["endpoints"]
        if not isinstance(endpoints, dict) or endpoints.get("futures_depth") != "https://api-futures.kucoin.com/api/v1/level2/depth20":
            raise ValueError("market identity endpoint mismatch")
    symbols = record.get("symbols")
    if (
        not isinstance(symbols, dict) or not symbols
        or isinstance(record.get("symbol_count"), bool)
        or record.get("symbol_count") != len(symbols)
        or _number(record.get("completeness"), "completeness") != 1
    ):
        raise ValueError("incomplete market record")
    if not isinstance(now, datetime.datetime) or now.tzinfo is None:
        raise ValueError("now must be timezone-aware")
    start = _time(record.get("observed_at_start"), "observation start")
    end = _time(record.get("observed_at_end"), "observation end")
    if start > end or end > now:
        raise ValueError("future or reversed market observation")
    if (now - start).total_seconds() > max_age_seconds:
        raise ValueError("stale market observation")
    for observation in symbols.values():
        if not isinstance(observation, dict) or not isinstance(
            observation.get("futures"), dict
        ):
            raise ValueError("incomplete futures observation")
        timestamp = _millis(
            observation["futures"].get("book_timestamp_ms"), "book timestamp"
        )
        if timestamp > end.timestamp() * 1000:
            raise ValueError("future book timestamp")
        if now.timestamp() - timestamp / 1000 > max_age_seconds:
            raise ValueError("stale book timestamp")
        if record['schema_version'] == 2:
            future = observation['futures']
            raw = future.get('raw_contract_metadata')
            raw_mark = future.get('raw_mark')
            def digest(payload):
                return hashlib.sha256(json.dumps(payload, sort_keys=True,
                    separators=(',', ':'), allow_nan=False).encode()).hexdigest()
            if (not isinstance(record.get('source_schema_v1_hash'), str)
                or not re.fullmatch(r'[a-f0-9]{64}', record['source_schema_v1_hash'])
                or record.get('metadata_endpoint') != 'https://api-futures.kucoin.com/api/v1/contracts/XBTUSDTM'
                or record.get('metadata_endpoint') != future.get('metadata_source_endpoint')
                or not isinstance(raw, dict)
                or raw.get('symbol') != observation.get('futures_remote_symbol')
                or raw.get('status') != 'Open'
                or future.get('contract_metadata_sha256') != digest(raw)
                or record.get('mark_endpoint') != 'https://api-futures.kucoin.com/api/v1/mark-price/XBTUSDTM/current'
                or record.get('mark_endpoint') != future.get('mark_source_endpoint')
                or not isinstance(raw_mark, dict)
                or raw_mark.get('symbol') != observation.get('futures_remote_symbol')
                or raw_mark.get('granularity') != 1000
                or future.get('mark_sha256') != digest(raw_mark)):
                raise ValueError('schema-2 contract provenance invalid')
            metadata_at = _time(future.get('metadata_observed_at'), 'metadata observation')
            mark_at = _time(future.get('mark_timestamp'), 'mark observation')
            mark_received = _time(future.get('mark_received_at'), 'mark receipt')
            mark_started = _time(record.get('mark_request_started_at'), 'mark request')
            contract_started = _time(record.get('contract_request_started_at'), 'contract request')
            if (record.get('mark_received_at') != future.get('mark_received_at')
                or record.get('metadata_observed_at') != future.get('metadata_observed_at')
                or future.get('mark_timestamp_source') != 'kucoin_timePoint_ms'
                or _millis(raw_mark.get('timePoint'), 'mark timePoint') != int(mark_at.timestamp()*1000)
                or _number(raw_mark.get('value'), 'raw mark', positive=True) != _number(future.get('mark_price'), 'mark price', positive=True)
                or mark_started > mark_received or mark_received > contract_started
                or contract_started > metadata_at or metadata_at > end
                or mark_at > mark_received or mark_received > end
                or metadata_at > now or mark_at > now
                or now-metadata_at > datetime.timedelta(seconds=max_age_seconds)
                or now-mark_at > datetime.timedelta(seconds=max_age_seconds)
                or abs(mark_at.timestamp() - timestamp/1000) > max_age_seconds):
                raise ValueError('schema-2 metadata stale or future')


def load_latest_market(
    path, now, *, max_bytes=4 * 1024 * 1024,
    max_age_seconds=MAX_QUOTE_AGE_SECONDS,
):
    """Read the last newline-terminated record without scanning the large file.

    A concurrent partial append is ignored; a corrupt completed latest record
    is an error, never an invitation to silently use an older quote.
    """
    if isinstance(max_bytes, bool) or not isinstance(max_bytes, int) or max_bytes < 1:
        raise ValueError("invalid maximum tail bytes")
    max_age_seconds = _number(max_age_seconds, "maximum quote age", positive=True)
    with pathlib.Path(path).open("rb") as stream:
        stream.seek(0, 2)
        size = stream.tell()
        start = max(0, size - max_bytes)
        boundary = True
        if start:
            stream.seek(start - 1)
            boundary = stream.read(1) == b"\n"
        stream.seek(start)
        data = stream.read(max_bytes)
    lines = data.split(b"\n")[:-1]
    if start and not boundary:
        lines = lines[1:]
    lines = [line for line in lines if line.strip()]
    if not lines:
        raise ValueError("no complete market record within bounded tail")
    try:
        latest = json.loads(lines[-1])
        previous = json.loads(lines[-2]) if len(lines) > 1 else None
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise ValueError("invalid completed market JSONL record") from error
    _validate_record(latest, now, max_age_seconds)
    if previous is not None:
        _verify_hash(previous)
        if latest.get("previous_record_hash") != previous["record_hash"]:
            raise ValueError("market tail hash chain mismatch")
        if _time(previous.get("observed_at_end"), "previous observation") >= _time(
            latest["observed_at_end"], "observation end"
        ):
            raise ValueError("market tail is not chronological")
    return latest


def _book(levels, side):
    if not isinstance(levels, list) or not levels:
        raise ValueError(f"missing {side} depth")
    result = []
    for level in levels:
        if not isinstance(level, dict):
            raise ValueError(f"invalid {side} level")
        price = _number(level.get("price"), "book price", positive=True)
        quantity = _number(level.get("base_quantity"), "book quantity", positive=True)
        if result and (
            (side == "bids" and price >= result[-1]["price"])
            or (side == "asks" and price <= result[-1]["price"])
        ):
            raise ValueError(f"unordered {side} depth")
        if "quote_quantity" in level and not math.isclose(
            _number(level["quote_quantity"], "quote quantity", positive=True),
            price * quantity, rel_tol=1e-9,
        ):
            raise ValueError("inconsistent book quantity units")
        result.append({"price": price, "base_quantity": quantity})
    return result


def market_quotes(record, symbols):
    """Return requested normalized symbols; missing or invalid markets fail closed."""
    end = _time(record.get("observed_at_end"), "observation end")
    _validate_record(record, end, MAX_QUOTE_AGE_SECONDS)
    observations = {}
    for value in record["symbols"].values():
        symbol = normalize_symbol(value.get("futures_symbol"))
        if symbol in observations:
            raise ValueError("duplicate normalized market symbol")
        observations[symbol] = value
    result = {}
    for requested in symbols:
        symbol = normalize_symbol(requested)
        if symbol not in observations:
            raise ValueError(f"missing market quote for {symbol}")
        observation = observations[symbol]
        future = observation["futures"]
        bids = _book(future.get("normalized_bids"), "bids")
        asks = _book(future.get("normalized_asks"), "asks")
        if bids[0]["price"] > asks[0]["price"]:
            raise ValueError("crossed futures book")
        for field, price in (("best_bid", bids[0]["price"]), ("best_ask", asks[0]["price"])):
            if field in future and _number(future[field], field, positive=True) != price:
                raise ValueError("book top disagrees with depth")
        fee = _number(future.get("conservative_taker_fee_rate"), "taker fee", nonnegative=True)
        if fee >= 1:
            raise ValueError("invalid taker fee")
        funding_meta = observation.get("funding")
        if not isinstance(funding_meta, dict):
            raise ValueError("missing funding metadata")
        funding = funding_meta.get("settled_last_24h")
        if not isinstance(funding, list) or not funding:
            raise ValueError("missing settled funding evidence")
        interval = _millis(funding_meta.get("granularity_ms"), "funding interval")
        time_point = _millis(funding_meta.get("time_point_ms"), "funding time point")
        next_funding = _millis(funding_meta.get("funding_time_ms"), "next funding time")
        if (
            interval > 86400000
            or time_point > end.timestamp() * 1000
            or next_funding <= end.timestamp() * 1000
            or next_funding - time_point != interval
        ):
            raise ValueError("inconsistent or stale funding schedule")
        settlements = []
        previous_timestamp = 0
        for settlement in funding:
            if not isinstance(settlement, dict):
                raise ValueError("invalid funding settlement")
            timestamp = _millis(settlement.get("timestamp_ms"), "funding timestamp")
            if timestamp <= previous_timestamp or timestamp > end.timestamp() * 1000:
                raise ValueError("future or unordered funding settlement")
            if previous_timestamp and timestamp - previous_timestamp != interval:
                raise ValueError("funding history coverage gap")
            rate = _number(settlement.get("rate"), "funding rate")
            previous_timestamp = timestamp
            if timestamp >= (end.timestamp() - 86400) * 1000:
                settlements.append({"timestamp_ms": timestamp, "rate": rate})
        if not settlements:
            raise ValueError("stale funding evidence")
        timestamp = _millis(future["book_timestamp_ms"], "book timestamp")
        eligible = [event for event in settlements if event["timestamp_ms"] <= timestamp]
        # Never let the ledger advance past a settlement not published yet.
        # Otherwise its later arrival could be incorrectly treated as already
        # accounted for merely because last_mark_at is after that settlement.
        if (
            settlements[-1]["timestamp_ms"] != time_point
            or not eligible
            or timestamp >= eligible[-1]["timestamp_ms"] + interval
        ):
            raise ValueError("awaiting complete settled funding coverage")
        result[symbol] = {
            "symbol": symbol,
            "market_identity": "kucoin_futures_usdt",
            "mark_timestamp": future.get("mark_timestamp"),
            "metadata_observed_at": future.get("metadata_observed_at"),
            "mark_price": _number(future.get("mark_price"), "mark price", positive=True),
            "step": _number(future.get("quantity_step", future.get("contract_multiplier")), "quantity step", positive=True),
            "quantity_step": future.get("quantity_step"),
            # Never infer absent order constraints from book levels or multiplier.
            # Existing archives intentionally fail closed for new risk.
            "contract_multiplier": future.get("contract_multiplier"),
            "price_tick": future.get("price_tick"),
            "min_quantity": future.get("min_quantity"),
            "min_notional": future.get("min_notional"),
            "fee_rate": fee,
            "timestamp": datetime.datetime.fromtimestamp(timestamp / 1000, UTC).isoformat(),
            "bids": bids, "asks": asks, "funding": settlements,
            "market_record_hash": record["record_hash"],
        }
    return result


def fill_price(quote, signed_quantity):
    """Full-size book VWAP plus adverse 2 bps; never claim a partial fill."""
    signed_quantity = _number(signed_quantity, "fill quantity")
    if signed_quantity == 0:
        raise ValueError("fill quantity cannot be zero")
    bids = _book(quote.get("bids"), "bids")
    asks = _book(quote.get("asks"), "asks")
    if bids[0]["price"] > asks[0]["price"]:
        raise ValueError("crossed futures book")
    levels = asks if signed_quantity > 0 else bids
    quantity = abs(signed_quantity)
    capacity = math.fsum(level["base_quantity"] for level in levels)
    if capacity < quantity and not math.isclose(capacity, quantity, rel_tol=1e-12):
        raise ValueError("insufficient displayed depth for full paper fill")
    remaining = quantity
    costs = []
    for level in levels:
        filled = min(remaining, level["base_quantity"])
        costs.append(filled * level["price"])
        remaining -= filled
        if remaining <= 0:
            break
    price = math.fsum(costs) / quantity
    adverse = ADVERSE_SLIPPAGE_RATE if signed_quantity > 0 else -ADVERSE_SLIPPAGE_RATE
    return _number(price * (1 + adverse), "paper fill price", positive=True)
