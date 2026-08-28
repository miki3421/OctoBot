import datetime
import gzip
import hashlib
import json
import pathlib

import numpy
import pytest

from octobot.ai_strategy_lab import (
    liquid_market_breadth_forward_runner as runner,
)


UTC = datetime.timezone.utc


def _synthetic_market():
    dates = [
        datetime.date(2025, 1, 1) + datetime.timedelta(days=index)
        for index in range(700)
    ]
    grid = numpy.arange(len(dates), dtype=numpy.float64)
    asset = numpy.arange(30, dtype=numpy.float64)
    log_closes = (
        numpy.log(20.0 + asset)[None, :]
        + 0.000003 * grid[:, None] ** 2
        + 0.00001 * asset[None, :] * grid[:, None]
    )
    closes = numpy.exp(log_closes)
    returns = numpy.zeros_like(closes)
    returns[1:] = closes[1:] / closes[:-1] - 1.0
    quote_volumes = numpy.broadcast_to(
        1_000_000_000.0 - asset[None, :] * 1_000_000.0,
        closes.shape,
    ).copy()
    return {
        "dates": dates,
        "timestamps": numpy.asarray(
            [
                int(datetime.datetime.combine(date, datetime.time(), UTC).timestamp())
                for date in dates
            ],
            dtype=numpy.int64,
        ),
        "symbols": [f"ASSET{index:02d}USDT" for index in range(30)],
        "closes": closes,
        "quote_volumes": quote_volumes,
        "returns": returns,
        "return_complete": numpy.ones_like(closes, dtype=bool),
        "funding": numpy.zeros_like(closes),
        "funding_counts": numpy.ones_like(closes, dtype=numpy.int16),
    }


def _record(date, index):
    return {
        "bar_date": date.isoformat(),
        "record_hash": hashlib.sha256(f"record-{index}".encode()).hexdigest(),
    }


def test_breadth_requires_two_thirds_of_the_current_basket():
    closes = numpy.full((29, 30), 100.0)
    closes[-1, :20] = 101.0
    closes[-1, 20:] = 99.0
    market = {"closes": closes}

    active, audit = runner.breadth_decision(
        market, 28, tuple(range(30)), True
    )
    closes[-1, 19] = 99.0
    inactive, failed_audit = runner.breadth_decision(
        market, 28, tuple(range(30)), True
    )

    assert active is True
    assert audit["positive_assets"] == 20
    assert audit["positive_breadth"] == pytest.approx(2.0 / 3.0)
    assert inactive is False
    assert failed_audit["positive_assets"] == 19
    assert runner.breadth_decision(
        market, 28, tuple(range(30)), False
    )[0] is False


def test_forward_payload_attaches_only_the_previous_mature_outcome():
    market = _synthetic_market()
    dates = [
        runner.protocol.FORWARD_START + datetime.timedelta(days=index)
        for index in range(3)
    ]
    records = [_record(date, index) for index, date in enumerate(dates)]

    payloads = runner.build_decision_payloads(market, records)

    assert [value["bar_date"] for value in payloads] == [
        value.isoformat() for value in dates
    ]
    assert payloads[0]["matured_outcome"] is None
    assert payloads[1]["matured_outcome"]["decision_bar"] == "2026-09-01"
    assert payloads[1]["matured_outcome"]["return_bearing_bar"] == "2026-09-02"
    assert payloads[1]["matured_outcome"]["base"]["parent_v1"][
        "price_return"
    ] > 0
    assert payloads[0]["signal"]["parent_v1_active"] is True
    assert payloads[0]["signal"]["breadth_v2_active"] is True
    assert payloads[0]["orders_authorized"] is False
    assert payloads[0]["paper_orders_authorized"] is False


def test_future_market_changes_cannot_rewrite_prior_payloads():
    market = _synthetic_market()
    dates = [
        runner.protocol.FORWARD_START + datetime.timedelta(days=index)
        for index in range(2)
    ]
    records = [_record(date, index) for index, date in enumerate(dates)]
    expected = runner.build_decision_payloads(market, records)
    changed = {
        **market,
        "closes": market["closes"].copy(),
        "quote_volumes": market["quote_volumes"].copy(),
    }
    future = market["dates"].index(dates[-1]) + 1
    changed["closes"][future:] *= 7.0
    changed["quote_volumes"][future:] = changed["quote_volumes"][future:, ::-1]

    assert runner.build_decision_payloads(changed, records) == expected


def _kline_row(date, close, quote_volume):
    open_ms = int(
        datetime.datetime.combine(date, datetime.time(), UTC).timestamp()
        * 1000
    )
    return [
        open_ms,
        "1",
        "1",
        "1",
        str(close),
        "1",
        open_ms + 86_400_000 - 1,
        str(quote_volume),
    ]


def test_quote_volume_is_recovered_from_hash_verified_raw_klines(tmp_path):
    symbols = ["BTCUSDT", "ETHUSDT"]
    dates = [datetime.date(2026, 9, 1), datetime.date(2026, 9, 2)]
    artifacts = {}
    closes = {"BTCUSDT": [100.0, 101.0], "ETHUSDT": [50.0, 51.0]}
    for symbol_index, symbol in enumerate(symbols):
        payload = json.dumps(
            [
                _kline_row(
                    date,
                    closes[symbol][date_index],
                    1_000.0 + symbol_index * 100 + date_index,
                )
                for date_index, date in enumerate(dates)
            ]
        ).encode()
        key = hashlib.sha256(payload).hexdigest()
        path = tmp_path / f"{key}.json.gz"
        path.write_bytes(gzip.compress(payload, mtime=0))
        artifacts[symbol] = {
            "response_sha256": key,
            "path": path.name,
            "url": (
                "https://fapi.binance.com/fapi/v1/klines?"
                f"symbol={symbol}&interval=1d"
            ),
        }
    records = [
        {
            "bar_date": date.isoformat(),
            "symbols": {
                symbol: {
                    "close": closes[symbol][date_index],
                    "raw": {"daily_klines": artifacts[symbol]},
                }
                for symbol in symbols
            },
        }
        for date_index, date in enumerate(dates)
    ]

    values = runner.quote_volumes_from_records(records, tmp_path, symbols)

    assert values.tolist() == [[1_000.0, 1_100.0], [1_001.0, 1_101.0]]
    records[0]["symbols"]["BTCUSDT"]["close"] = 999.0
    with pytest.raises(runner.DataQualityError, match="closes differ"):
        runner.quote_volumes_from_records(records, tmp_path, symbols)


def test_quote_volume_parser_rejects_non_daily_clock():
    row = _kline_row(datetime.date(2026, 9, 1), 100, 1_000)
    row[6] -= 1
    with pytest.raises(runner.DataQualityError, match="clock differs"):
        runner._parse_kline_quote_volumes(json.dumps([row]).encode())


def test_journal_is_idempotent_and_rejects_rewritten_history(tmp_path):
    market = _synthetic_market()
    dates = [
        runner.protocol.FORWARD_START + datetime.timedelta(days=index)
        for index in range(2)
    ]
    payloads = runner.build_decision_payloads(
        market,
        [_record(date, index) for index, date in enumerate(dates)],
    )
    path = tmp_path / "decisions.jsonl"

    assert runner.append_payloads(path, payloads) == 2
    assert runner.append_payloads(path, payloads) == 0
    changed = json.loads(json.dumps(payloads))
    changed[0]["signal"]["positive_assets"] -= 1
    with pytest.raises(runner.DataQualityError, match="no longer reproduces"):
        runner.append_payloads(path, changed)
    lines = path.read_text(encoding="utf-8").splitlines()
    first = json.loads(lines[0])
    first["journal_record_hash"] = "0" * 64
    path.write_text(
        json.dumps(first) + "\n" + "\n".join(lines[1:]) + "\n",
        encoding="utf-8",
    )
    with pytest.raises(runner.DataQualityError, match="chain differs"):
        runner.load_journal(path)


def test_pre_cutoff_health_contains_counts_but_no_economic_aggregates(tmp_path):
    records = [
        _record(runner.protocol.WARMUP_START + datetime.timedelta(days=index), index)
        for index in range(58)
    ]
    config = type("Config", (), {"journal_path": tmp_path / "journal.jsonl"})
    value = runner._health_payload(
        config,
        {"implementation_lock_sha256": "a" * 64},
        records,
        [],
        0,
        {
            "last_success_at": "2026-08-28T00:10:00+00:00",
            "last_archived_bar": "2026-08-27",
        },
        datetime.datetime(2026, 8, 28, 1, tzinfo=UTC),
    )

    assert value["phase"] == "warmup"
    assert value["warmup_records"] == 58
    assert value["official_market_records"] == 0
    assert value["pre_cutoff_aggregate_metrics_calculated"] is False
    assert value["gate_evaluation_authorized"] is False
    assert value["orders_authorized"] is False


def test_upstream_health_must_match_the_verified_archive_tail(tmp_path):
    now = datetime.datetime(2026, 8, 28, 1, tzinfo=UTC)
    record = _record(datetime.date(2026, 8, 27), 0)
    value = {
        "status": "healthy",
        "observer_type": (
            "diversified_trend_cointegration_forward_observer_v1"
        ),
        "protocol_sha256": runner.protocol.UPSTREAM_PROTOCOL_SHA256,
        "implementation_lock_sha256": (
            runner.protocol.UPSTREAM_IMPLEMENTATION_LOCK_SHA256
        ),
        "last_success_at": "2026-08-28T00:10:00+00:00",
        "daily_records": 1,
        "last_archived_bar": record["bar_date"],
        "last_market_record_hash": record["record_hash"],
        "credentials_used": False,
        "orders_authorized": False,
        "paper_orders_authorized": False,
        "automatic_promotion": False,
    }
    path = tmp_path / "health.json"
    path.write_text(json.dumps(value), encoding="utf-8")
    config = type("Config", (), {"upstream_health_path": path})

    assert runner._verify_upstream_health(config, [record], now) == value
    value["last_market_record_hash"] = "0" * 64
    path.write_text(json.dumps(value), encoding="utf-8")
    with pytest.raises(runner.DataQualityError, match="health differs"):
        runner._verify_upstream_health(config, [record], now)


def test_runner_surface_is_orderless_and_has_no_downloader():
    source = pathlib.Path(runner.__file__).read_text(encoding="utf-8")

    assert "urllib.request" not in source
    assert "create_order" not in source
    assert "paper_orders_authorized\": True" not in source
    assert runner.protocol.frozen_protocol()["historical_evaluation_allowed"] is False
