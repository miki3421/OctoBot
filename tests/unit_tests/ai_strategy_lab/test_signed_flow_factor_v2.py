import datetime
import json

import numpy
import pytest

from octobot.ai_strategy_lab import signed_flow_factor_v2 as factor


def test_protocol_changes_only_to_external_weekly_holding():
    protocol = factor.frozen_protocol()

    assert protocol["public_data_only"] is True
    assert protocol["credentials_used"] is False
    assert protocol["orders_authorized"] is False
    assert protocol["paper_orders_authorized"] is False
    assert protocol["results"] is None
    assert protocol["signal"]["formation_blocks"] == 21
    assert protocol["signal"]["holding_blocks"] == 21
    assert protocol["signal"]["active_vintages_at_steady_state"] == 21
    assert protocol["signal"]["new_vintage_fraction"] == pytest.approx(
        1 / 21
    )
    assert protocol["hypothesis"]["long_only_variant_allowed"] is False
    assert protocol["validation"]["confirmation_status"].startswith(
        "sealed"
    )


def test_protocol_write_is_stable_and_tampering_fails(tmp_path):
    path = tmp_path / "protocol.json"

    first = factor.write_or_verify_protocol(path)
    second = factor.write_or_verify_protocol(path)

    assert first == second
    tampered = json.loads(path.read_text(encoding="utf-8"))
    tampered["signal"]["holding_blocks"] = 20
    path.write_text(json.dumps(tampered), encoding="utf-8")
    with pytest.raises(ValueError, match="protocol differs"):
        factor.write_or_verify_protocol(path)


def _stable_market():
    symbols = [f"S{index:02d}/USDT:USDT" for index in range(18)]
    row_count = 100
    start = int(
        datetime.datetime(
            2022, 1, 1, tzinfo=datetime.timezone.utc
        ).timestamp()
    )
    timestamps = numpy.arange(
        start,
        start + row_count * 8 * 3600,
        8 * 3600,
        dtype=numpy.int64,
    )
    signed_flow = numpy.tile(
        numpy.arange(18, dtype=numpy.float64), (row_count, 1)
    )
    return {
        "timestamps": timestamps,
        "symbols": symbols,
        "closes": numpy.full((row_count, 18), 100.0),
        "returns": numpy.zeros((row_count, 18), dtype=numpy.float64),
        "signed_flow": signed_flow,
        "quote_volume": numpy.ones((row_count, 18), dtype=numpy.float64),
        "funding": numpy.zeros((row_count, 18), dtype=numpy.float64),
    }


def test_target_is_average_of_twenty_one_live_vintages():
    market = _stable_market()
    targets = factor.build_target_matrix(market)
    index = 60
    expected = numpy.mean(
        [
            factor.sleeve_weights(market, vintage)
            for vintage in range(index - 20, index + 1)
        ],
        axis=0,
    )

    assert targets[index] == pytest.approx(expected)
    assert numpy.sum(numpy.abs(targets[index])) == pytest.approx(0.8)
    assert numpy.sum(targets[index]) == pytest.approx(0.0)
    assert numpy.count_nonzero(targets[index] > 0) == 3
    assert numpy.count_nonzero(targets[index] < 0) == 3


def test_flat_market_charges_only_open_and_close_after_vintage_netting():
    market = _stable_market()
    targets = factor.build_target_matrix(market)
    start_index = 50
    end_index = 70
    start = datetime.datetime.fromtimestamp(
        int(market["timestamps"][start_index]), datetime.timezone.utc
    )
    end = datetime.datetime.fromtimestamp(
        int(market["timestamps"][end_index]), datetime.timezone.utc
    )

    report = factor.simulate_period(
        market, start, end, target_matrix=targets, include_trajectory=True
    )

    assert report["blocks"] == 20
    assert report["average_gross_exposure"] == pytest.approx(0.8)
    assert report["maximum_absolute_net_exposure"] == pytest.approx(0.0)
    assert report["total_turnover"] == pytest.approx(1.6)
    assert report["total_cost_return"] == pytest.approx(1.6 * 0.0008)
    assert report["total_price_return"] == pytest.approx(0.0)
    assert report["total_funding_return"] == pytest.approx(0.0)
    assert report["total_return"] < 0
    assert report["_trajectory"]["block_return"][0] < 0
