import datetime
import json
import pathlib

import numpy

from octobot.ai_strategy_lab import basis_momentum_v1 as basis_momentum


def _market(blocks=3200, assets=18):
    first = datetime.datetime(2022, 1, 1, tzinfo=datetime.timezone.utc)
    timestamps = numpy.asarray(
        [
            int((first + datetime.timedelta(hours=8 * index)).timestamp())
            for index in range(blocks)
        ],
        dtype=numpy.int64,
    )
    asset_trend = numpy.linspace(0.001, -0.001, assets)
    indices = numpy.arange(blocks, dtype=numpy.float64)[:, None]
    closes = numpy.full((blocks, assets), 100.0, dtype=numpy.float64)
    spot_closes = 100.0 * numpy.exp(indices * asset_trend[None, :])
    returns = numpy.zeros_like(closes)
    funding = numpy.zeros_like(closes)
    return {
        "timestamps": timestamps,
        "symbols": [f"ASSET{index:02d}/USDT:USDT" for index in range(assets)],
        "closes": closes,
        "spot_closes": spot_closes,
        "returns": returns,
        "funding": funding,
    }


def _negative_report():
    return {
        "blocks": 2200,
        "annualized_return": -0.10,
        "total_return": -0.10,
        "sharpe_zero_rate": -1.0,
        "maximum_drawdown": 0.10,
        "positive_month_ratio": 0.0,
        "long_additive_contribution": -0.05,
        "short_additive_contribution": -0.05,
        "market_beta": 0.0,
        "average_gross_exposure": 0.8,
        "maximum_symbol_absolute_contribution_share": 0.10,
        "_trajectory": {
            "decision_timestamps": [],
            "end_timestamps": [],
            "equity": [],
            "block_return": [],
            "market_return": [],
            "gross_exposure": [],
            "net_exposure": [],
        },
    }


def test_protocol_is_frozen_result_free_and_cannot_authorize_orders(tmp_path):
    path = tmp_path / "protocol.json"
    protocol = basis_momentum.write_or_verify_protocol(path)

    assert protocol["results"] is None
    assert protocol["orders_authorized"] is False
    assert protocol["paper_orders_authorized"] is False
    assert protocol["automatic_promotion"] is False
    assert basis_momentum.write_or_verify_protocol(path) == protocol
    assert json.loads(path.read_text()) == protocol


def test_protocol_freezes_source_selected_formation_direction_and_holding():
    protocol = basis_momentum.frozen_protocol()
    signal = protocol["signal"]

    assert signal["formation_blocks"] == 21
    assert signal["selected_assets_per_side"] == 3
    assert signal["long_side"] == "highest basis-momentum quintile"
    assert signal["short_side"] == "lowest basis-momentum quintile"
    assert signal["holding_blocks"] == 1
    assert signal["holding_hours"] == 8
    assert signal["overlapping_vintages"] is False
    assert protocol["external_hypothesis"][
        "source_reported_high_minus_low_weekly_return"
    ] == 0.0188


def test_protocol_keeps_confirmation_and_lock_sequentially_sealed():
    protocol = basis_momentum.frozen_protocol()
    validation = protocol["validation"]

    assert validation["development_status"] == "diagnostic_reuse"
    assert validation["confirmation_status"].startswith("sealed")
    assert validation["locked_status"].startswith("sealed")
    assert protocol["forward_gate"]["minimum_calendar_days"] == 180


def test_target_is_neutral_long_high_momentum_and_short_low_momentum():
    market = _market()
    target = basis_momentum.target_weights(market, 40)

    assert numpy.all(target[:3] > 0)
    assert numpy.all(target[-3:] < 0)
    assert numpy.all(target[3:-3] == 0)
    assert numpy.isclose(numpy.sum(target), 0.0, atol=1e-12)
    assert numpy.isclose(numpy.sum(numpy.abs(target)), 0.8)


def test_target_does_not_use_future_prices_returns_or_funding():
    market = _market()
    original = basis_momentum.target_weights(market, 100)
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
        original, basis_momentum.target_weights(changed, 100)
    )


def test_formation_crossing_a_gap_produces_no_target():
    market = _market()
    market["timestamps"][30:] += basis_momentum.BLOCK_SECONDS

    assert not numpy.any(basis_momentum.target_weights(market, 40))
    assert numpy.any(basis_momentum.target_weights(market, 52))


def test_simulation_uses_next_block_and_cost_stress_is_conservative():
    market = _market()
    market["returns"][:, :3] = 0.001
    market["returns"][:, -3:] = -0.001
    start = datetime.datetime(2022, 3, 1, tzinfo=datetime.timezone.utc)
    end = datetime.datetime(2022, 9, 1, tzinfo=datetime.timezone.utc)

    baseline = basis_momentum.simulate_period(market, start, end)
    stress = basis_momentum.simulate_period(
        market, start, end, cost_multiplier=3.0
    )

    assert baseline["total_return"] > 0
    assert stress["total_return"] < baseline["total_return"]
    assert baseline["long_additive_contribution"] > 0
    assert baseline["short_additive_contribution"] > 0
    assert baseline["maximum_absolute_net_exposure"] <= 1e-12
    assert baseline["maximum_gross_exposure"] <= 0.8 + 1e-12


def test_failed_development_does_not_read_confirmation_or_lock(
    tmp_path, monkeypatch
):
    protocol_path = tmp_path / "protocol.json"
    basis_momentum.write_or_verify_protocol(protocol_path)
    market = _market()
    monkeypatch.setattr(
        basis_momentum.execution_parent,
        "load_market",
        lambda *_args, **_kwargs: (market, {"fixture": True}),
    )
    calls = []

    def fake_simulation(_market, start, end, **kwargs):
        calls.append((start, end, kwargs.get("cost_multiplier", 1.0)))
        report = _negative_report()
        if not kwargs.get("include_trajectory", False):
            report.pop("_trajectory")
        return report

    monkeypatch.setattr(basis_momentum, "simulate_period", fake_simulation)
    result = basis_momentum.evaluate_prelock(
        protocol_path,
        [tmp_path / "unused-futures.data"],
        [tmp_path / "unused-spot.data"],
        [tmp_path / "unused-funding.json"],
        tmp_path / "experiments",
    )
    report = result["report"]

    assert all(end <= basis_momentum.DEVELOPMENT_END for _, end, _ in calls)
    assert report["confirmation"] is None
    assert report["locked_test"]["authorized_to_open"] is False
    assert report["locked_test"]["materialized"] is False
    saved = json.loads(
        (pathlib.Path(result["directory"]) / "report.json").read_text()
    )
    assert saved["verdict"] == "REJECTED_PRELOCK_LOCK_REMAINS_SEALED"
