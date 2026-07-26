import datetime
import pathlib

import numpy

from octobot.ai_strategy_lab import h2_backtest


def test_frozen_protocol_hash_changes_if_protocol_changes():
    protocol = h2_backtest.frozen_protocol()
    original = h2_backtest.protocol_sha256(protocol)
    changed = {**protocol, "protocol_version": "changed"}

    assert h2_backtest.protocol_sha256(changed) != original
    assert protocol["strategy"]["score_threshold"] == 0.515
    assert protocol["strategy"]["minimum_volume_zscore"] == 1.0
    assert not protocol["evaluation"]["threshold_search"]


def test_aggregate_5m_to_15m_drops_incomplete_bucket():
    base = 1_800_000_000
    values = []
    for index in range(5):
        close = 100 + index
        values.append(
            [base + index * 300, close - 1, close + 1, close - 2, close, 10]
        )

    aggregated = h2_backtest._aggregate_5m_to_15m(
        numpy.asarray(values, dtype=float)
    )

    assert aggregated.shape == (1, 6)
    assert aggregated[0].tolist() == [
        float(base),
        99.0,
        103.0,
        98.0,
        102.0,
        30.0,
    ]


def test_split_contiguous_resets_at_gap_without_interpolation():
    values = numpy.zeros((401, 6), dtype=float)
    values[:, 0] = 1_800_000_000 + numpy.arange(401) * 900
    values[201:, 0] += 900

    segments = h2_backtest._split_contiguous(values)

    assert [len(segment) for segment in segments] == [201, 200]
    assert int(segments[1][0, 0] - segments[0][-1, 0]) == 1800


def test_metrics_include_funding_cost_stress_and_direction_breakdown():
    trades = [
        {
            "direction": "LONG",
            "exchange": "binance",
            "entry_time_utc": "2025-01-01T00:00:00+00:00",
            "gross_return_pct": 1.0,
            "funding_cost_pct": 0.1,
            "duration_hours": 4.0,
        },
        {
            "direction": "SHORT",
            "exchange": "binance",
            "entry_time_utc": "2025-01-02T00:00:00+00:00",
            "gross_return_pct": -1.0,
            "funding_cost_pct": -0.1,
            "duration_hours": 2.0,
        },
    ]

    metrics = h2_backtest._metrics(trades, 0.2)

    assert metrics["trades"] == 2
    assert metrics["wins"] == 1
    assert abs(metrics["expectancy_pct_per_trade"] + 0.2) < 1e-12
    assert metrics["by_direction"]["LONG"]["net_return_sum_pct"] == 0.7
    assert abs(
        metrics["by_direction"]["SHORT"]["net_return_sum_pct"] + 1.1
    ) < 1e-12
    assert metrics["total_funding_cost_pct"] == 0.0


def test_write_protocol_contains_no_results(tmp_path):
    path = h2_backtest.write_protocol(tmp_path)

    assert path == pathlib.Path(tmp_path) / "protocol.json"
    text = path.read_text(encoding="utf-8")
    assert '"protocol_sha256"' in text
    assert '"profit_factor"' not in text


def test_parse_block():
    value = (
        "old|/tmp/c.data|15m|2020-02-01|2021-12-30|"
        "/tmp/f.json|binance|h2_unseen"
    )

    block = h2_backtest._parse_block(value)

    assert block.name == "old"
    assert block.entry_start == datetime.date(2020, 2, 1)
    assert block.entry_end == datetime.date(2021, 12, 30)
    assert block.source_time_frame == "15m"
