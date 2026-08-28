import datetime
import gzip
import json
import urllib.parse

import numpy
import pytest

from octobot.ai_strategy_lab import (
    diversified_trend_cointegration_forward_runner as runner,
)
from octobot.ai_strategy_lab import trend as trend_module


UTC = datetime.timezone.utc


def _milliseconds(value):
    return int(value.timestamp() * 1000)


class PublicDailyResponses:
    def __init__(self):
        self.calls = []

    def __call__(self, url):
        self.calls.append(url)
        parsed = urllib.parse.urlparse(url)
        query = urllib.parse.parse_qs(parsed.query)
        symbol = query["symbol"][0]
        start = datetime.datetime.fromtimestamp(
            int(query["startTime"][0]) / 1000, UTC
        )
        end = datetime.datetime.fromtimestamp(
            int(query["endTime"][0]) / 1000, UTC
        )
        offset = 0 if symbol == "BTCUSDT" else 100
        if parsed.path.endswith("/klines"):
            rows = []
            current = start.replace(hour=0, minute=0, second=0, microsecond=0)
            index = 0
            while current <= end:
                open_ms = _milliseconds(current)
                rows.append(
                    [
                        open_ms,
                        "1",
                        "1",
                        "1",
                        str(10 + offset + index),
                        "1",
                        open_ms + runner.DAY_MILLISECONDS - 1,
                        "1",
                    ]
                )
                current += datetime.timedelta(days=1)
                index += 1
            return json.dumps(rows).encode()
        if parsed.path.endswith("/fundingRate"):
            first_day = start.date()
            final_day = end.date()
            rows = []
            current = datetime.datetime.combine(first_day, datetime.time(), UTC)
            while current <= datetime.datetime.combine(final_day, datetime.time(), UTC):
                if current > start and current <= end:
                    rows.append(
                        {
                            "symbol": symbol,
                            "fundingTime": _milliseconds(current),
                            "fundingRate": "0.0001",
                        }
                    )
                current += datetime.timedelta(hours=8)
            return json.dumps(rows).encode()
        raise AssertionError(url)


def test_public_range_uses_only_daily_klines_and_causal_funding_window(tmp_path):
    responses = PublicDailyResponses()
    start = datetime.date(2026, 7, 2)
    end = datetime.date(2026, 7, 4)

    result = runner.fetch_public_daily_range(
        ["BTCUSDT", "ETHUSDT"],
        start,
        end,
        raw_root=tmp_path / "raw",
        maximum_workers=2,
        fetch_bytes=responses,
    )

    assert list(result) == [start, start + datetime.timedelta(days=1)]
    assert result[start]["symbols"]["BTCUSDT"]["close"] == 10
    assert result[start]["symbols"]["ETHUSDT"]["close"] == 110
    assert result[start]["symbols"]["BTCUSDT"][
        "funding_settlement_count"
    ] == 3
    assert result[start]["symbols"]["BTCUSDT"][
        "funding_rate_sum"
    ] == pytest.approx(0.0003)
    assert len(responses.calls) == 4
    assert all(url.startswith("https://fapi.binance.com/fapi/v1/") for url in responses.calls)
    assert len(list((tmp_path / "raw").rglob("*.json.gz"))) == 4


def test_funding_parser_rejects_a_response_for_another_symbol():
    date = datetime.date(2026, 7, 2)
    settlement = datetime.datetime(2026, 7, 2, 8, tzinfo=UTC)
    payload = json.dumps(
        [
            {
                "symbol": "ETHUSDT",
                "fundingTime": _milliseconds(settlement),
                "fundingRate": "0.0001",
            }
        ]
    ).encode()

    with pytest.raises(runner.DataQualityError, match="symbol differs"):
        runner._parse_funding_rows([payload], [date], "BTCUSDT")


def test_daily_archive_is_contiguous_hash_chained_and_raw_auditable(tmp_path):
    responses = PublicDailyResponses()
    symbols = ["BTCUSDT", "ETHUSDT"]
    fetched = runner.fetch_public_daily_range(
        symbols,
        runner.protocol.WARMUP_START,
        runner.protocol.WARMUP_START + datetime.timedelta(days=2),
        raw_root=tmp_path / "raw",
        fetch_bytes=responses,
    )

    appended = runner.append_daily_records(
        tmp_path / "records",
        fetched,
        expected_symbols=symbols,
        collected_at=datetime.datetime(2026, 8, 28, 12, tzinfo=UTC),
    )
    loaded = runner.load_daily_records(
        tmp_path / "records",
        raw_root=tmp_path / "raw",
        expected_symbols=symbols,
    )

    assert len(appended) == len(loaded) == 2
    assert loaded[0]["previous_record_hash"] is None
    assert loaded[1]["previous_record_hash"] == loaded[0]["record_hash"]
    archive = tmp_path / "records" / "2026-07-02.json.gz"
    changed = json.loads(gzip.decompress(archive.read_bytes()))
    changed["symbols"]["BTCUSDT"]["close"] = 999
    archive.write_bytes(gzip.compress(json.dumps(changed).encode(), mtime=0))
    with pytest.raises(runner.DataQualityError, match="record hash"):
        runner.load_daily_records(
            tmp_path / "records", expected_symbols=symbols
        )


def _decision(date, value):
    unsigned = {
        "bar_date": date.isoformat(),
        "orders_authorized": False,
        "value": value,
    }
    return {**unsigned, "decision_payload_sha256": runner._json_hash(unsigned)}


def test_decision_journal_replays_exactly_and_rejects_rewritten_history(tmp_path):
    path = tmp_path / "decisions.jsonl"
    dates = [
        datetime.date(2026, 9, 1),
        datetime.date(2026, 9, 2),
    ]
    payloads = [_decision(dates[0], 1), _decision(dates[1], 2)]

    first = runner.append_decision_payloads(
        path,
        payloads,
        recorded_at=datetime.datetime(2026, 9, 3, 0, 10, tzinfo=UTC),
    )
    second = runner.append_decision_payloads(
        path,
        payloads,
        recorded_at=datetime.datetime(2026, 9, 3, 0, 11, tzinfo=UTC),
    )

    assert first["appended_records"] == 2
    assert second["appended_records"] == 0
    changed = [_decision(dates[0], 9), payloads[1]]
    with pytest.raises(runner.DataQualityError, match="does not reproduce"):
        runner.append_decision_payloads(
            path,
            changed,
            recorded_at=datetime.datetime.now(UTC),
        )


def test_latest_mature_bar_respects_ten_minute_finalization_delay():
    assert runner._latest_mature_bar(
        datetime.datetime(2026, 9, 2, 0, 9, tzinfo=UTC)
    ) == datetime.date(2026, 8, 31)
    assert runner._latest_mature_bar(
        datetime.datetime(2026, 9, 2, 0, 10, tzinfo=UTC)
    ) == datetime.date(2026, 9, 1)


def test_trend_forward_mirror_matches_frozen_v13_reference():
    config = next(
        value
        for value in trend_module.TREND_CONFIGS
        if value.name == "risk_budgeted_bear_regime_v13"
    )
    dates = [
        datetime.date(2025, 1, 1) + datetime.timedelta(days=index)
        for index in range(300)
    ]
    grid = numpy.arange(300, dtype=numpy.float64)
    closes = numpy.column_stack(
        (
            100 * numpy.exp(0.001 * grid + 0.02 * numpy.sin(grid / 9)),
            50 * numpy.exp(-0.0002 * grid + 0.03 * numpy.sin(grid / 13)),
            20 * numpy.exp(0.0005 * grid + 0.01 * numpy.cos(grid / 7)),
        )
    )
    returns = numpy.zeros_like(closes)
    returns[1:] = closes[1:] / closes[:-1] - 1
    market = {
        "dates": dates,
        "symbols": [
            "BTC/USDT:USDT",
            "ETH/USDT:USDT",
            "SOL/USDT:USDT",
        ],
        "closes": closes,
        "returns": returns,
        "funding": numpy.full_like(closes, 0.0001),
    }
    start = dates[150]
    end = dates[280]

    mirrored = runner.simulate_trend_forward(market, config, start, end)
    reference = trend_module._simulate(
        market,
        config,
        1.0,
        include_trajectory=True,
        evaluation_start_index=150,
        evaluation_end_index=280,
    )

    assert mirrored["equity"] == pytest.approx(
        reference["trajectory"]["equity"], abs=1e-14
    )
    assert dict(zip(market["symbols"], mirrored["targets"][-1])) == pytest.approx(
        reference["ending_weights"], abs=1e-14
    )


def test_cointegration_forward_does_not_add_terminal_liquidation(monkeypatch):
    dates = [
        datetime.date(2026, 9, 1) + datetime.timedelta(days=index)
        for index in range(3)
    ]
    closes = numpy.asarray([[10, 20], [11, 19], [12, 18]], dtype=float)
    returns = numpy.zeros_like(closes)
    returns[1:] = closes[1:] / closes[:-1] - 1
    market = {
        "dates": dates,
        "symbols": ["BTCUSDT", "ETHUSDT"],
        "closes": closes,
        "returns": returns,
        "return_complete": numpy.ones_like(closes, dtype=bool),
        "funding": numpy.zeros_like(closes),
        "funding_counts": numpy.ones_like(closes, dtype=numpy.int16),
    }
    monkeypatch.setattr(
        runner.pairs,
        "build_formation_cache",
        lambda *_args, **_kwargs: {
            0: {"date": dates[0], "eligible_columns": [], "candidates": []}
        },
    )
    monkeypatch.setattr(
        runner.pairs,
        "select_pairs",
        lambda *_args, **_kwargs: (
            [],
            {"date": dates[0].isoformat(), "selected_pairs": 0, "pairs": []},
        ),
    )

    result = runner.simulate_cointegration_forward(
        market,
        numpy.zeros(1),
        dates[0],
        dates[-1] + datetime.timedelta(days=1),
        cost_multiplier=1.0,
    )

    assert result["daily_return"] == pytest.approx([0, 0, 0])
    assert result["terminal_gross_exposure"] == 0
    assert len(result["dates"]) == 3


def test_runner_surface_remains_orderless():
    assert runner.OBSERVER_TYPE.endswith("_observer_v1")
    protocol_value = runner.protocol.frozen_protocol()
    assert protocol_value["orders_authorized"] is False
    assert protocol_value["paper_orders_authorized"] is False
