import copy
import datetime
import hashlib
import json

import pytest

from octobot.ai_strategy_lab import v13_market as market


NOW = datetime.datetime(2026, 9, 12, 12, 1, tzinfo=datetime.timezone.utc)


def signed(record):
    record = copy.deepcopy(record)
    raw = {key: value for key, value in record.items() if key != "record_hash"}
    record["record_hash"] = hashlib.sha256(json.dumps(
        raw, sort_keys=True, separators=(",", ":"), allow_nan=False,
    ).encode()).hexdigest()
    return record


def record_at(when=NOW, previous=None):
    timestamp_ms = int((when - datetime.timedelta(seconds=5)).timestamp() * 1000)
    funding_interval = 28800000
    last_funding = timestamp_ms // funding_interval * funding_interval
    return signed({
        "schema_version": 1, "mode": "observation_only", "public_data_only": True,
        "credentials_used": False, "orders_authorized": False,
        "symbol_count": 1, "completeness": 1.0,
        "observed_at_start": (when - datetime.timedelta(seconds=10)).isoformat(),
        "observed_at_end": when.isoformat(), "previous_record_hash": previous,
        "symbols": {"AAVE": {
            "futures_symbol": "AAVE/USDT:USDT",
            "futures": {
                "mark_price": 100.5, "contract_multiplier": 0.01,
                "conservative_taker_fee_rate": 0.0006,
                "book_timestamp_ms": timestamp_ms,
                "normalized_bids": [
                    {"price": 100, "base_quantity": 1, "quote_quantity": 100},
                    {"price": 99, "base_quantity": 2, "quote_quantity": 198},
                ],
                "normalized_asks": [
                    {"price": 101, "base_quantity": 1, "quote_quantity": 101},
                    {"price": 102, "base_quantity": 2, "quote_quantity": 204},
                ],
            },
            "funding": {"granularity_ms": funding_interval,
                "time_point_ms": last_funding,
                "funding_time_ms": last_funding + funding_interval,
                "settled_last_24h": [
                {"timestamp_ms": last_funding - funding_interval, "rate": -0.0001},
                {"timestamp_ms": last_funding, "rate": 0.0002},
            ]},
        }},
    })


def write_record(path, record):
    path.write_bytes(json.dumps(record).encode() + b"\n")


def test_latest_complete_record_ignores_concurrent_partial_append(tmp_path):
    previous = record_at(NOW - datetime.timedelta(minutes=15))
    latest = record_at(previous=previous["record_hash"])
    path = tmp_path / "market.jsonl"
    path.write_bytes(
        json.dumps(previous).encode() + b"\n" + json.dumps(latest).encode()
        + b'\n{"partial": '
    )
    assert market.load_latest_market(path, NOW) == latest


def test_tail_limit_does_not_parse_historical_prefix(tmp_path):
    latest = record_at()
    line = json.dumps(latest).encode() + b"\n"
    path = tmp_path / "market.jsonl"
    path.write_bytes(b"historical prefix not scanned" * 1000 + b"\n" + line)
    assert market.load_latest_market(path, NOW, max_bytes=len(line) + 20) == latest
    with pytest.raises(ValueError, match="bounded tail"):
        market.load_latest_market(path, NOW, max_bytes=20)


def test_corrupt_complete_latest_never_falls_back(tmp_path):
    path = tmp_path / "market.jsonl"
    path.write_bytes(json.dumps(record_at()).encode() + b"\n{broken}\n")
    with pytest.raises(ValueError, match="invalid completed"):
        market.load_latest_market(path, NOW)


def test_latest_hash_and_predecessor_chain_are_verified(tmp_path):
    previous = record_at(NOW - datetime.timedelta(minutes=15))
    latest = record_at(previous="unrelated")
    path = tmp_path / "market.jsonl"
    path.write_text(json.dumps(previous) + "\n" + json.dumps(latest) + "\n")
    with pytest.raises(ValueError, match="tail hash chain"):
        market.load_latest_market(path, NOW)
    latest["completeness"] = 0.5
    write_record(path, latest)
    with pytest.raises(ValueError, match="record hash"):
        market.load_latest_market(path, NOW)


@pytest.mark.parametrize("field,value", [
    ("mode", "paper"), ("orders_authorized", True), ("credentials_used", True),
    ("public_data_only", False), ("paper_orders_authorized", True),
    ("schema_version", 2), ("completeness", 0.9), ("completeness", True),
    ("symbol_count", 2), ("symbol_count", True),
    ("observed_at_start", "2026-09-12T13:00:00+00:00"),
    ("observed_at_end", "2026-09-12T13:00:00+00:00"),
    ("observed_at_end", "2026-09-12T12:01:00"),
])
def test_unsafe_incomplete_or_future_record_rejected(tmp_path, field, value):
    record = record_at()
    record[field] = value
    path = tmp_path / "market.jsonl"
    write_record(path, signed(record))
    with pytest.raises(ValueError):
        market.load_latest_market(path, NOW)


def test_stale_record_and_stale_or_future_book_are_rejected(tmp_path):
    path = tmp_path / "market.jsonl"
    write_record(path, record_at(NOW - datetime.timedelta(minutes=31)))
    with pytest.raises(ValueError, match="stale market"):
        market.load_latest_market(path, NOW)
    for delta, error in ((-1900, "stale book"), (1, "future book")):
        record = record_at()
        record["symbols"]["AAVE"]["futures"]["book_timestamp_ms"] = int(
            (NOW + datetime.timedelta(seconds=delta)).timestamp() * 1000
        )
        write_record(path, signed(record))
        with pytest.raises(ValueError, match=error):
            market.load_latest_market(path, NOW)


def test_normalized_quotes_use_base_quantity_and_actual_settled_rates():
    quote = market.market_quotes(record_at(), ["AAVE/USDT:USDT"])["AAVEUSDT"]
    assert quote["step"] == 0.01
    assert quote["fee_rate"] == 0.0006
    assert quote["mark_price"] == 100.5
    assert quote["bids"][0]["base_quantity"] == 1.0
    assert quote["funding"][0]["rate"] == -0.0001
    assert quote["timestamp"] == "2026-09-12T12:00:55+00:00"
    assert quote["market_record_hash"] == record_at()["record_hash"]


def test_full_depth_vwap_and_adverse_slippage_on_both_sides():
    quote = market.market_quotes(record_at(), ["AAVEUSDT"])["AAVEUSDT"]
    assert market.fill_price(quote, 2) == pytest.approx(101.5 * 1.0002)
    assert market.fill_price(quote, -2) == pytest.approx(99.5 * 0.9998)
    assert market.fill_price(quote, 3) == pytest.approx((101 + 204) / 3 * 1.0002)
    for quantity in (3.1, -3.1):
        with pytest.raises(ValueError, match="insufficient displayed depth"):
            market.fill_price(quote, quantity)
    for quantity in (0, float("nan"), float("inf"), True):
        with pytest.raises(ValueError):
            market.fill_price(quote, quantity)


@pytest.mark.parametrize("mutation", [
    lambda f: f.update(mark_price=0),
    lambda f: f.update(mark_price="NaN"),
    lambda f: f.update(contract_multiplier=-0.01),
    lambda f: f.update(conservative_taker_fee_rate=-0.01),
    lambda f: f.update(conservative_taker_fee_rate=1),
    lambda f: f.update(normalized_bids=[]),
    lambda f: f["normalized_bids"].reverse(),
    lambda f: f["normalized_asks"].reverse(),
    lambda f: f["normalized_bids"][0].update(price=103, quote_quantity=103),
    lambda f: f["normalized_asks"][0].update(base_quantity=0),
    lambda f: f["normalized_asks"][0].update(quote_quantity=999),
    lambda f: f.update(best_ask=500),
])
def test_invalid_books_and_execution_inputs_fail_closed(mutation):
    record = record_at()
    mutation(record["symbols"]["AAVE"]["futures"])
    with pytest.raises(ValueError):
        market.market_quotes(signed(record), ["AAVEUSDT"])


@pytest.mark.parametrize("kind", ["missing", "future", "unordered", "invalid_rate", "old"])
def test_missing_or_invalid_settled_funding_rejected(kind):
    record = record_at()
    funding = record["symbols"]["AAVE"]["funding"]
    values = funding["settled_last_24h"]
    if kind == "missing":
        funding["settled_last_24h"] = []
    elif kind == "future":
        values[-1]["timestamp_ms"] = int(NOW.timestamp() * 1000) + 1000
    elif kind == "unordered":
        values.reverse()
    elif kind == "invalid_rate":
        values[-1]["rate"] = "NaN"
    elif kind == "old":
        for value in values:
            value["timestamp_ms"] -= 86400000
    with pytest.raises(ValueError):
        market.market_quotes(signed(record), ["AAVEUSDT"])


def test_missing_market_and_wrong_settlement_fail_closed():
    with pytest.raises(ValueError, match="missing market quote"):
        market.market_quotes(record_at(), ["BTCUSDT"])
    with pytest.raises(ValueError, match="settlement"):
        market.normalize_symbol("AAVE/USDT:BTC")


def test_single_contract_is_not_multiplier_applied_twice():
    quote = market.market_quotes(record_at(), ["AAVEUSDT"])["AAVEUSDT"]
    assert market.fill_price(quote, quote["step"]) == pytest.approx(101 * 1.0002)


def test_late_settlement_blocks_quote_until_history_catches_up():
    record = record_at()
    funding = record["symbols"]["AAVE"]["funding"]
    latest = funding["settled_last_24h"].pop()
    with pytest.raises(ValueError, match="awaiting complete settled funding"):
        market.market_quotes(signed(record), ["AAVEUSDT"])
    funding["settled_last_24h"].append(latest)
    assert market.market_quotes(signed(record), ["AAVEUSDT"])["AAVEUSDT"]["funding"][-1] == latest


def test_stale_current_funding_api_cannot_hide_an_elapsed_settlement():
    record = record_at()
    funding = record["symbols"]["AAVE"]["funding"]
    funding["settled_last_24h"].pop()
    funding["time_point_ms"] -= funding["granularity_ms"]
    funding["funding_time_ms"] -= funding["granularity_ms"]
    with pytest.raises(ValueError, match="funding schedule"):
        market.market_quotes(signed(record), ["AAVEUSDT"])


def test_missing_internal_funding_interval_is_rejected():
    record = record_at()
    funding = record["symbols"]["AAVE"]["funding"]
    funding["settled_last_24h"][0]["timestamp_ms"] -= funding["granularity_ms"]
    with pytest.raises(ValueError, match="funding history coverage gap"):
        market.market_quotes(signed(record), ["AAVEUSDT"])


def test_future_book_relative_settlement_waits_until_next_quote():
    # Collection may straddle a settlement: the rate is known at observation
    # end although the earlier book must not accrue it until the next tick.
    end = datetime.datetime(2026, 9, 12, 16, 0, 5, tzinfo=datetime.timezone.utc)
    record = record_at(end)
    record["symbols"]["AAVE"]["futures"]["book_timestamp_ms"] -= 1000
    quote = market.market_quotes(signed(record), ["AAVEUSDT"])["AAVEUSDT"]
    assert quote["funding"][-1]["timestamp_ms"] > int(
        datetime.datetime.fromisoformat(quote["timestamp"]).timestamp() * 1000
    )
