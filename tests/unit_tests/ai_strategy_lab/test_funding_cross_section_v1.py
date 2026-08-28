import datetime
import json

import numpy

from octobot.ai_strategy_lab import funding_cross_section_v1 as funding_factor


def _market(days=1200, assets=8):
    dates = [
        datetime.date(2022, 1, 1) + datetime.timedelta(days=index)
        for index in range(days)
    ]
    closes = numpy.full((days, assets), 100.0)
    returns = numpy.zeros_like(closes)
    funding = numpy.zeros_like(closes)
    funding[:, :2] = -0.001
    funding[:, -2:] = 0.001
    return {
        "dates": dates,
        "symbols": [f"ASSET{index}/USDT:USDT" for index in range(assets)],
        "closes": closes,
        "returns": returns,
        "funding": funding,
    }


def _negative_report():
    return {
        "rebalance_events": 1,
        "annualized_return": -0.1,
        "total_return": -0.1,
        "sharpe_zero_rate": -1.0,
        "maximum_drawdown": 0.1,
        "positive_month_ratio": 0.0,
        "total_funding_return": -0.01,
        "total_cost_return": 0.01,
    }


def test_protocol_is_frozen_research_only(tmp_path):
    path = tmp_path / "protocol.json"
    protocol = funding_factor.write_or_verify_protocol(path)

    assert protocol["results"] is None
    assert protocol["orders_authorized"] is False
    assert protocol["paper_orders_authorized"] is False
    assert protocol["automatic_promotion"] is False
    assert funding_factor.write_or_verify_protocol(path) == protocol


def test_target_is_neutral_and_long_low_short_high():
    market = _market()
    # Give every asset non-zero trailing price volatility without changing the
    # funding rank under test.
    random = numpy.random.RandomState(4)
    market["returns"] = random.normal(0, 0.01, market["returns"].shape)
    target = funding_factor.target_weights(market, 100)

    assert numpy.all(target[:2] > 0)
    assert numpy.all(target[-2:] < 0)
    assert numpy.isclose(numpy.sum(target), 0.0, atol=1e-12)
    assert numpy.sum(numpy.abs(target)) <= 0.8 + 1e-12
    assert numpy.max(numpy.abs(target)) <= 0.10 + 1e-12


def test_target_does_not_use_future_funding_or_returns():
    market = _market()
    random = numpy.random.RandomState(5)
    market["returns"] = random.normal(0, 0.01, market["returns"].shape)
    original = funding_factor.target_weights(market, 100)
    changed = {
        **market,
        "returns": market["returns"].copy(),
        "funding": market["funding"].copy(),
    }
    changed["returns"][101:] = 0.5
    changed["funding"][101:] *= -10

    assert numpy.array_equal(
        original, funding_factor.target_weights(changed, 100)
    )


def test_simulation_collects_funding_and_cost_stress_reduces_return():
    market = _market()
    random = numpy.random.RandomState(6)
    market["returns"] = random.normal(0, 0.00001, market["returns"].shape)
    start = datetime.date(2022, 3, 1)
    end = datetime.date(2022, 9, 1)
    baseline = funding_factor.simulate_period(market, start, end)
    stress = funding_factor.simulate_period(
        market, start, end, cost_multiplier=3.0
    )

    assert baseline["total_funding_return"] > 0
    assert baseline["total_return"] > 0
    assert stress["total_return"] < baseline["total_return"]
    assert baseline["maximum_absolute_net_exposure"] <= 1e-12
    assert baseline["maximum_gross_exposure"] <= 0.8 + 1e-12


def test_failed_development_keeps_confirmation_and_lock_closed(
    tmp_path, monkeypatch
):
    protocol_path = tmp_path / "protocol.json"
    funding_factor.write_or_verify_protocol(protocol_path)
    market = _market(days=1700)
    monkeypatch.setattr(
        funding_factor.common,
        "load_market",
        lambda *_args, **_kwargs: (market, {}),
    )
    calls = []

    def fake_simulation(_market, start, end, *, cost_multiplier=1.0):
        calls.append((start, end, cost_multiplier))
        return _negative_report()

    monkeypatch.setattr(funding_factor, "simulate_period", fake_simulation)
    result = funding_factor.evaluate_prelock(
        protocol_path,
        [tmp_path / "unused.data"],
        [tmp_path / "unused.json"],
        tmp_path / "experiments",
    )
    report = result["report"]

    assert all(end <= funding_factor.DEVELOPMENT_END for _, end, _ in calls)
    assert report["confirmation"] is None
    assert report["locked_test"]["authorized_to_open"] is False
    assert report["locked_test"]["materialized"] is False
    saved_path = (
        tmp_path
        / "experiments"
        / result["directory"].split("/")[-1]
        / "report.json"
    )
    saved = json.loads(saved_path.read_text())
    assert saved["verdict"] == "REJECTED_PRELOCK_LOCK_REMAINS_SEALED"
