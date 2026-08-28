import datetime
import json
import pathlib

import numpy

from octobot.ai_strategy_lab import basis_factor_v1 as basis_factor


def _market(days=1700, assets=18):
    dates = [
        datetime.date(2022, 1, 1) + datetime.timedelta(days=index)
        for index in range(days)
    ]
    closes = numpy.full((days, assets), 100.0, dtype=numpy.float64)
    returns = numpy.zeros_like(closes)
    funding = numpy.zeros_like(closes)
    basis = numpy.linspace(-0.02, 0.02, assets)
    spot_closes = closes * (1.0 + basis[None, :])
    return {
        "dates": dates,
        "symbols": [f"ASSET{index:02d}/USDT:USDT" for index in range(assets)],
        "closes": closes,
        "spot_closes": spot_closes,
        "returns": returns,
        "funding": funding,
    }


def _negative_report():
    return {
        "days": 180,
        "annualized_return": -0.10,
        "total_return": -0.10,
        "sharpe_zero_rate": -1.0,
        "maximum_drawdown": 0.10,
        "positive_month_ratio": 0.0,
        "long_additive_contribution": -0.05,
        "short_additive_contribution": -0.05,
        "market_beta": 0.0,
        "_trajectory": {
            "dates": [],
            "equity": [],
            "daily_return": [],
            "market_return": [],
            "gross_exposure": [],
            "net_exposure": [],
        },
    }


def test_protocol_is_frozen_and_cannot_authorize_orders(tmp_path):
    path = tmp_path / "protocol.json"
    protocol = basis_factor.write_or_verify_protocol(path)

    assert protocol["results"] is None
    assert protocol["orders_authorized"] is False
    assert protocol["paper_orders_authorized"] is False
    assert protocol["automatic_promotion"] is False
    assert protocol["hypothesis"]["historical_periods_are_diagnostic_reuse"]
    assert basis_factor.write_or_verify_protocol(path) == protocol


def test_target_is_neutral_long_high_basis_and_short_low_basis():
    market = _market()
    target = basis_factor.target_weights(market, 20)

    assert numpy.all(target[:6] < 0)
    assert numpy.all(target[-6:] > 0)
    assert numpy.all(target[6:-6] == 0)
    assert numpy.isclose(numpy.sum(target), 0.0, atol=1e-12)
    assert numpy.isclose(numpy.sum(numpy.abs(target)), 0.8)


def test_target_does_not_use_future_spot_or_perpetual_prices():
    market = _market()
    original = basis_factor.target_weights(market, 100)
    changed = {
        **market,
        "closes": market["closes"].copy(),
        "spot_closes": market["spot_closes"].copy(),
        "returns": market["returns"].copy(),
        "funding": market["funding"].copy(),
    }
    changed["closes"][101:] *= numpy.linspace(0.5, 2.0, 18)
    changed["spot_closes"][101:] *= numpy.linspace(2.0, 0.5, 18)
    changed["returns"][101:] = 0.5
    changed["funding"][101:] = 0.1

    assert numpy.array_equal(
        original, basis_factor.target_weights(changed, 100)
    )


def test_simulation_uses_previous_signal_and_cost_stress_is_conservative():
    market = _market()
    # The fixed high-basis tercile rises and the low-basis tercile falls.
    market["returns"][:, :6] = -0.001
    market["returns"][:, -6:] = 0.001
    start = datetime.date(2022, 3, 1)
    end = datetime.date(2022, 9, 1)

    baseline = basis_factor.simulate_period(market, start, end)
    stress = basis_factor.simulate_period(
        market, start, end, cost_multiplier=3.0
    )

    assert baseline["total_return"] > 0
    assert stress["total_return"] < baseline["total_return"]
    assert baseline["long_additive_contribution"] > 0
    assert baseline["short_additive_contribution"] > 0
    assert baseline["maximum_absolute_net_exposure"] <= 1e-12
    assert baseline["maximum_gross_exposure"] <= 0.8 + 1e-12


def test_side_costs_split_a_direction_flip_between_both_sides():
    previous = numpy.asarray([0.10, -0.15, 0.05])
    target = numpy.asarray([-0.20, 0.05, 0.0])

    long_cost, short_cost = basis_factor._side_costs(
        previous, target, 0.001
    )

    assert numpy.isclose(long_cost, 0.00020)
    assert numpy.isclose(short_cost, 0.00035)
    assert numpy.isclose(
        long_cost + short_cost,
        numpy.sum(numpy.abs(target - previous)) * 0.001,
    )


def test_failed_development_does_not_read_confirmation_or_lock(
    tmp_path, monkeypatch
):
    protocol_path = tmp_path / "protocol.json"
    basis_factor.write_or_verify_protocol(protocol_path)
    market = _market()
    monkeypatch.setattr(
        basis_factor,
        "load_market",
        lambda *_args, **_kwargs: (market, {"fixture": True}),
    )
    calls = []

    def fake_simulation(
        _market,
        start,
        end,
        *,
        cost_multiplier=1.0,
        include_trajectory=False,
    ):
        calls.append((start, end, cost_multiplier))
        report = _negative_report()
        if not include_trajectory:
            report.pop("_trajectory")
        return report

    monkeypatch.setattr(basis_factor, "simulate_period", fake_simulation)
    result = basis_factor.evaluate_prelock(
        protocol_path,
        [tmp_path / "unused-futures.data"],
        [tmp_path / "unused-spot.data"],
        [tmp_path / "unused-funding.json"],
        tmp_path / "experiments",
    )
    report = result["report"]

    assert all(end <= basis_factor.DEVELOPMENT_END for _, end, _ in calls)
    assert report["confirmation"] is None
    assert report["locked_test"]["authorized_to_open"] is False
    assert report["locked_test"]["materialized"] is False
    saved = json.loads(
        (pathlib.Path(result["directory"]) / "report.json").read_text()
    )
    assert saved["verdict"] == "REJECTED_PRELOCK_LOCK_REMAINS_SEALED"
