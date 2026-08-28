import datetime
import json

import numpy
import pytest

from octobot.ai_strategy_lab import cross_venue_carry_v1 as cross_venue


def test_frozen_protocol_is_orderless_and_cost_derived():
    protocol = cross_venue.frozen_protocol()

    assert protocol["public_data_only"] is True
    assert protocol["credentials_used"] is False
    assert protocol["orders_authorized"] is False
    assert protocol["paper_orders_authorized"] is False
    assert protocol["results"] is None
    assert protocol["universe"]["required_symbol_count"] == 18
    expected = 2 * (0.0008 + 0.0008) * 3 * 365 / 30
    assert protocol["signal"][
        "minimum_annualized_spread"
    ] == pytest.approx(expected)


def test_protocol_write_is_content_stable_and_fail_closed(tmp_path):
    path = tmp_path / "protocol.json"

    first = cross_venue.write_or_verify_protocol(path)
    second = cross_venue.write_or_verify_protocol(path)

    assert first == second
    assert first["protocol_sha256"]
    tampered = json.loads(path.read_text(encoding="utf-8"))
    tampered["signal"]["maximum_pairs"] = 4
    path.write_text(json.dumps(tampered), encoding="utf-8")
    with pytest.raises(ValueError, match="protocol differs"):
        cross_venue.write_or_verify_protocol(path)


def _synthetic_market():
    start = datetime.datetime(
        2025, 7, 26, 0, tzinfo=datetime.timezone.utc
    )
    end = datetime.datetime(
        2025, 9, 1, 1, tzinfo=datetime.timezone.utc
    )
    funding_times = numpy.arange(
        int(start.timestamp()),
        int(end.timestamp()),
        8 * 3600,
        dtype=numpy.int64,
    )
    close_times = numpy.arange(
        int(start.timestamp()) + 3600,
        int(end.timestamp()) + 3600,
        3600,
        dtype=numpy.int64,
    )
    symbols = [
        "A/USDT:USDT",
        "B/USDT:USDT",
        "C/USDT:USDT",
        "D/USDT:USDT",
    ]
    kucoin = numpy.tile(
        numpy.asarray([0.00020, 0.00018, 0.00016, 0.00014]),
        (len(funding_times), 1),
    )
    return {
        "symbols": symbols,
        "close_times": close_times,
        "binance_closes": numpy.full((len(close_times), 4), 100.0),
        "kucoin_closes": numpy.full((len(close_times), 4), 100.0),
        "funding_times": funding_times,
        "binance_funding": numpy.zeros_like(kucoin),
        "kucoin_funding": kucoin,
    }


def test_target_uses_trailing_funding_and_correct_venue_direction():
    market = _synthetic_market()
    signal = int(
        datetime.datetime(
            2025, 8, 25, 0, tzinfo=datetime.timezone.utc
        ).timestamp()
    )

    binance, kucoin, selected = cross_venue.target_weights(market, signal)

    assert [value["symbol"] for value in selected] == [
        "A/USDT:USDT",
        "B/USDT:USDT",
        "C/USDT:USDT",
    ]
    assert binance.tolist() == pytest.approx([0.1, 0.1, 0.1, 0.0])
    assert kucoin.tolist() == pytest.approx([-0.1, -0.1, -0.1, 0.0])
    assert all(
        value["direction"] == "long_binance_short_kucoin"
        for value in selected
    )


def test_simulation_accounts_for_both_venue_costs_and_actual_funding():
    market = _synthetic_market()
    start = datetime.datetime(
        2025, 8, 25, 1, tzinfo=datetime.timezone.utc
    )
    end = datetime.datetime(
        2025, 9, 1, 1, tzinfo=datetime.timezone.utc
    )

    report = cross_venue.simulate_period(
        market, start, end, include_trajectory=True
    )

    assert report["hours"] == 7 * 24
    assert report["weekly_decisions"] == 1
    assert report["invested_weeks"] == 1
    assert report["maximum_gross_exposure"] == pytest.approx(0.6)
    assert report["maximum_absolute_net_exposure"] == pytest.approx(0.0)
    assert report["total_turnover"] == pytest.approx(1.2)
    assert report["total_cost_return"] == pytest.approx(1.2 * 0.0008)
    assert report["total_funding_return"] > 0
    assert report["total_price_return"] == pytest.approx(0.0)
    assert report["_trajectory"]["hourly_return"][0] == pytest.approx(
        -0.6 * 0.0008
    )


def test_strict_funding_grid_rejects_missing_settlement():
    expected = numpy.asarray([0, 8 * 3600, 16 * 3600], dtype=numpy.int64)
    funding = {
        "BTC/USDT:USDT": (
            numpy.asarray([0, 16 * 3600], dtype=numpy.int64),
            numpy.asarray([0.0001, 0.0001]),
        )
    }

    with pytest.raises(ValueError, match="funding grid gap"):
        cross_venue._strict_funding_grid(
            funding, "BTC/USDT:USDT", expected
        )
