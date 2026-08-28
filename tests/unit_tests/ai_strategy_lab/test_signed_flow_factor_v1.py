import datetime
import json
import pathlib

import numpy

from octobot.ai_strategy_lab import signed_flow_factor_v1 as signed_flow


def _market(blocks=5000, assets=18):
    start = int(datetime.datetime(2022, 1, 1, tzinfo=signed_flow.UTC).timestamp())
    timestamps = numpy.asarray(
        [start + index * signed_flow.BLOCK_SECONDS for index in range(blocks)],
        dtype=numpy.int64,
    )
    closes = numpy.full((blocks, assets), 100.0, dtype=numpy.float64)
    returns = numpy.zeros_like(closes)
    funding = numpy.zeros_like(closes)
    flow = numpy.linspace(-1_000_000, 1_000_000, assets)
    signed_values = numpy.repeat(flow[None, :], blocks, axis=0)
    return {
        "timestamps": timestamps,
        "symbols": [f"ASSET{index:02d}/USDT:USDT" for index in range(assets)],
        "closes": closes,
        "returns": returns,
        "signed_flow": signed_values,
        "quote_volume": numpy.abs(signed_values),
        "funding": funding,
    }


def _negative_report():
    return {
        "blocks": 2100,
        "annualized_return": -0.10,
        "total_return": -0.10,
        "sharpe_zero_rate": -1.0,
        "maximum_drawdown": 0.10,
        "positive_month_ratio": 0.0,
        "long_additive_contribution": -0.05,
        "short_additive_contribution": -0.05,
        "market_beta": 0.0,
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


def test_protocol_is_frozen_and_cannot_authorize_orders(tmp_path):
    path = tmp_path / "protocol.json"
    protocol = signed_flow.write_or_verify_protocol(path)

    assert protocol["results"] is None
    assert protocol["orders_authorized"] is False
    assert protocol["paper_orders_authorized"] is False
    assert protocol["automatic_promotion"] is False
    assert protocol["signal"]["formation_blocks"] == 21
    assert signed_flow.write_or_verify_protocol(path) == protocol


def test_eight_hour_aggregation_requires_all_hours_and_computes_flow():
    rows = {
        index * 3600: [index * 3600, 100 + index, 1000, 600]
        for index in range(8)
    }

    complete = signed_flow._aggregate_eight_hour(rows)
    incomplete = signed_flow._aggregate_eight_hour(
        {timestamp: row for timestamp, row in rows.items() if timestamp != 3600}
    )

    assert complete == {28_800: (107.0, 1600.0, 8000.0)}
    assert incomplete == {}


def test_target_is_neutral_long_high_flow_and_short_low_flow():
    market = _market()
    target = signed_flow.target_weights(market, 30)

    assert numpy.all(target[:3] < 0)
    assert numpy.all(target[-3:] > 0)
    assert numpy.all(target[3:-3] == 0)
    assert numpy.isclose(numpy.sum(target), 0.0, atol=1e-12)
    assert numpy.isclose(numpy.sum(numpy.abs(target)), 0.8)


def test_target_does_not_use_future_flow_or_returns():
    market = _market()
    original = signed_flow.target_weights(market, 100)
    changed = {
        **market,
        "signed_flow": market["signed_flow"].copy(),
        "returns": market["returns"].copy(),
        "funding": market["funding"].copy(),
    }
    changed["signed_flow"][101:] *= numpy.linspace(2.0, -2.0, 18)
    changed["returns"][101:] = 0.5
    changed["funding"][101:] = 0.1

    assert numpy.array_equal(
        original, signed_flow.target_weights(changed, 100)
    )


def test_simulation_applies_signal_to_next_block_and_stress_is_conservative():
    market = _market()
    market["returns"][:, :3] = -0.001
    market["returns"][:, -3:] = 0.001
    start = datetime.datetime(2022, 2, 1, tzinfo=signed_flow.UTC)
    end = datetime.datetime(2022, 5, 1, tzinfo=signed_flow.UTC)

    baseline = signed_flow.simulate_period(market, start, end)
    stress = signed_flow.simulate_period(
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
    signed_flow.write_or_verify_protocol(protocol_path)
    market = _market()
    monkeypatch.setattr(
        signed_flow,
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

    monkeypatch.setattr(signed_flow, "simulate_period", fake_simulation)
    result = signed_flow.evaluate_prelock(
        protocol_path,
        [tmp_path / f"unused-{index}.json" for index in range(18)],
        tmp_path / "unused-cache",
        [tmp_path / f"unused-{index}.funding" for index in range(18)],
        tmp_path / "experiments",
    )
    report = result["report"]

    assert all(end <= signed_flow.DEVELOPMENT_END for _, end, _ in calls)
    assert report["confirmation"] is None
    assert report["locked_test"]["authorized_to_open"] is False
    assert report["locked_test"]["materialized"] is False
    saved = json.loads(
        (pathlib.Path(result["directory"]) / "report.json").read_text()
    )
    assert saved["verdict"] == "REJECTED_PRELOCK_LOCK_REMAINS_SEALED"
