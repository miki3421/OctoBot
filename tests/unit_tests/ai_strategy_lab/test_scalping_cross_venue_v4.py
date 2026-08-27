import json

import numpy
import pytest

from octobot.ai_strategy_lab import scalping_cross_venue_v4 as cross_venue


def _dataset(**overrides):
    rows = 3
    values = {
        "timestamps": numpy.asarray(
            [1_800_000_000, 1_800_000_015, 1_800_000_030],
            dtype=numpy.int64,
        ),
        "binance_return_bps": numpy.asarray([12.0, -14.0, 16.0]),
        "kucoin_return_bps": numpy.asarray([5.0, -6.0, 15.5]),
        "binance_flow_imbalance": numpy.asarray([0.5, -0.6, 0.8]),
        "binance_trade_count": numpy.asarray([10.0, 10.0, 10.0]),
        "delayed_binance_return_bps": numpy.asarray([11.0, -13.0, 15.0]),
        "delayed_binance_flow_imbalance": numpy.asarray([0.4, -0.5, 0.7]),
        "delayed_binance_trade_count": numpy.asarray([9.0, 9.0, 9.0]),
        "primary_long_return": numpy.asarray([0.01, -0.02, 0.03]),
        "primary_short_return": numpy.asarray([-0.01, 0.02, -0.03]),
        "primary_long_exit": numpy.asarray(
            [1_800_000_010, 1_800_000_025, 1_800_000_040]
        ),
        "primary_short_exit": numpy.asarray(
            [1_800_000_010, 1_800_000_025, 1_800_000_040]
        ),
        "stress_long_return": numpy.asarray([0.005, -0.025, 0.02]),
        "stress_short_return": numpy.asarray([-0.015, 0.01, -0.035]),
        "stress_long_exit": numpy.asarray(
            [1_800_000_011, 1_800_000_026, 1_800_000_041]
        ),
        "stress_short_exit": numpy.asarray(
            [1_800_000_011, 1_800_000_026, 1_800_000_041]
        ),
    }
    values.update(overrides)
    return cross_venue.CrossVenueDataset(**values)


def test_frozen_protocol_changes_information_set_without_authorizing_orders():
    protocol = cross_venue.frozen_protocol()

    assert protocol["status"] == "result_free_evaluation_protocol"
    assert protocol["results"] is None
    assert protocol["public_data_only"] is True
    assert protocol["credentials_used"] is False
    assert protocol["orders_authorized"] is False
    assert protocol["paper_orders_authorized"] is False
    assert protocol["signal"]["selection_candidates"] == 1
    assert protocol["source"]["future_or_locked_rows_excluded"] is True


def test_protocol_writer_is_reproducible_and_refuses_mutation(tmp_path):
    path = tmp_path / "protocol.json"
    first = cross_venue.write_or_verify_protocol(path)
    second = cross_venue.write_or_verify_protocol(path)

    assert first == second
    assert len(first["protocol_sha256"]) == 64

    changed = json.loads(path.read_text())
    changed["signal"]["window_seconds"] = 60
    path.write_text(json.dumps(changed))
    with pytest.raises(ValueError, match="protocol differs"):
        cross_venue.write_or_verify_protocol(path)


def test_archive_row_parser_supports_header_and_microsecond_clock():
    header = [
        "agg_trade_id",
        "price",
        "quantity",
        "first_trade_id",
        "last_trade_id",
        "transact_time",
        "is_buyer_maker",
    ]
    indices = cross_venue._header_indices(header)
    value = cross_venue._row_values(
        [
            "1",
            "65000.5",
            "0.25",
            "10",
            "12",
            "1800000000123456",
            "false",
        ],
        indices,
    )

    assert value == (65000.5, 0.25, 1_800_000_000, False)


def test_dense_features_apply_declared_information_delay():
    prices = numpy.asarray([100.0, 101.0, 102.0, 103.0, 104.0, 105.0, 106.0])
    buy = numpy.asarray([1.0, 1.0, 1.0, 1.0, 4.0, 4.0, 4.0])
    sell = numpy.asarray([1.0, 1.0, 1.0, 1.0, 1.0, 1.0, 1.0])
    counts = numpy.ones(7)

    returns, imbalance, trade_count = cross_venue._features_at_delay(
        candidate_seconds=numpy.asarray([7]),
        dense_start=0,
        prices=prices,
        buy_quantity=buy,
        sell_quantity=sell,
        trade_count=counts,
        delay_seconds=1,
    )

    assert returns[0] == pytest.approx(numpy.log(106 / 101) * 10_000)
    assert imbalance[0] == pytest.approx((14 - 5) / (14 + 5))
    assert trade_count[0] == 5


def test_signal_is_direction_symmetric_and_requires_real_lag():
    dataset = _dataset()
    trades = cross_venue._simulate(
        dataset,
        numpy.arange(3, dtype=numpy.int64),
        threshold_bps=10.0,
        stress=False,
    )

    assert trades["rows"].tolist() == [0, 1]
    assert trades["directions"].tolist() == [1, -1]
    assert trades["instrument_returns"].tolist() == [0.01, 0.02]


def test_gate_requires_delay_and_cost_stress_to_remain_positive():
    metrics = {
        "trades": 60,
        "profit_factor": 1.5,
        "max_drawdown": 0.02,
        "positive_operating_days_pct": 60.0,
        "total_return": 0.03,
        "by_direction": {
            "long": {"total_return": 0.01},
            "short": {"total_return": 0.01},
        },
    }
    stress = {**metrics, "trades": 60, "profit_factor": 0.9, "total_return": -0.01}

    gate = cross_venue._gate(
        metrics,
        stress,
        minimum_trades=50,
        positive_folds=5,
        valid_folds=5,
    )

    assert gate["passed"] is False
    assert gate["checks"]["delay_and_cost_stress_positive"] is False
    assert gate["checks"]["delay_and_cost_stress_profit_factor"] is False
