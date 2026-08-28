import csv
import io
import zipfile

import pytest

from octobot.ai_strategy_lab import market_data


def _archive(rows):
    payload = io.StringIO()
    writer = csv.writer(payload)
    writer.writerows(rows)
    output = io.BytesIO()
    with zipfile.ZipFile(output, "w") as zipped:
        zipped.writestr("values.csv", payload.getvalue())
    return output.getvalue()


def test_parse_and_aggregate_binance_klines():
    rows = [["open_time", "open", "high", "low", "close", "volume"]]
    for index in range(4):
        rows.append(
            [
                1_699_999_200_000 + index * 900_000,
                100 + index,
                102 + index,
                99 + index,
                101 + index,
                10 + index,
            ]
        )
    candles = market_data.parse_binance_kline_archive(_archive(rows))
    aggregate = market_data.aggregate_candles(candles, 4)
    assert len(aggregate) == 1
    assert aggregate[0][1:] == [100.0, 105.0, 99.0, 104.0, 46.0]


def test_parse_binance_funding():
    points = market_data.parse_binance_funding_archive(
        _archive(
            [
                ["calc_time", "funding_interval_hours", "last_funding_rate"],
                [1_700_000_000_000, 8, "0.0001"],
                [1_700_028_800_000, 8, "-0.0002"],
            ]
        )
    )
    assert points == [
        (1_700_000_000_000, 0.0001),
        (1_700_028_800_000, -0.0002),
    ]


def test_parse_binance_kline_aggressive_quote_flow():
    archive = _archive(
        [
            [
                "open_time",
                "open",
                "high",
                "low",
                "close",
                "volume",
                "close_time",
                "quote_volume",
                "count",
                "taker_buy_volume",
                "taker_buy_quote_volume",
                "ignore",
            ],
            [
                1_700_000_000_000,
                100,
                102,
                99,
                101,
                10,
                1_700_003_599_999,
                1000,
                42,
                6,
                620,
                0,
            ],
        ]
    )

    assert market_data.parse_binance_kline_flow_archive(archive) == [
        [1_700_000_000, 101.0, 1000.0, 620.0]
    ]


def test_parse_binance_kline_flow_rejects_impossible_buy_volume():
    with pytest.raises(ValueError, match="invalid Binance flow"):
        market_data.parse_binance_kline_flow_archive(
            _archive(
                [
                    [
                        1_700_000_000_000,
                        100,
                        102,
                        99,
                        101,
                        10,
                        1_700_003_599_999,
                        1000,
                        42,
                        11,
                        1001,
                        0,
                    ]
                ]
            )
        )


def test_aggregate_drops_incomplete_bucket():
    candles = [
        [0, 1, 2, 0.5, 1.5, 10],
        [900, 1.5, 2, 1, 1.8, 10],
        [1800, 1.8, 2, 1, 1.9, 10],
    ]
    assert market_data.aggregate_candles(candles, 4) == []


def test_config_rejects_invalid_period():
    config = market_data.BinanceArchiveConfig(
        {"BTC/USDT:USDT": "BTCUSDT"},
        market_data.parse_date("2025-02-01"),
        market_data.parse_date("2025-01-01"),
    )
    with pytest.raises(ValueError, match="start date"):
        config.validate()


def test_five_minute_contiguity_validation():
    candles = [
        [index * 300, 100, 101, 99, 100, 1]
        for index in range(1000)
    ]

    market_data._validate_contiguous_candles(
        "BTC/USDT:USDT",
        candles,
        interval_seconds=300,
        allowed_gaps=0,
        label="5m",
    )

    candles[500][0] += 300
    with pytest.raises(ValueError, match="5m gaps"):
        market_data._validate_contiguous_candles(
            "BTC/USDT:USDT",
            candles,
            interval_seconds=300,
            allowed_gaps=0,
            label="5m",
        )
