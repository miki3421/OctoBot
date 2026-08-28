import datetime
import json

import numpy

from octobot.ai_strategy_lab import cointegration_pairs_v1 as pairs


def _synthetic_market(days=900, assets=8):
    random = numpy.random.RandomState(11)
    dates = [
        datetime.date(2022, 1, 1) + datetime.timedelta(days=index)
        for index in range(days)
    ]
    common = numpy.cumsum(random.normal(0.0003, 0.018, size=days))
    stationary = numpy.zeros(days)
    for index in range(1, days):
        stationary[index] = (
            0.80 * stationary[index - 1] + random.normal(0, 0.012)
        )
    logs = [common, 0.2 + 1.1 * common + stationary]
    for index in range(2, assets):
        logs.append(
            numpy.cumsum(
                random.normal(0.0001 * index, 0.02, size=days)
            )
        )
    closes = numpy.exp(numpy.column_stack(logs) + 5.0)
    returns = numpy.zeros_like(closes)
    returns[1:] = closes[1:] / closes[:-1] - 1.0
    return {
        "dates": dates,
        "symbols": [f"ASSET{index}/USDT:USDT" for index in range(assets)],
        "closes": closes,
        "returns": returns,
        "funding": numpy.zeros_like(closes),
    }


def _negative_report():
    return {
        "closed_trades": 1,
        "total_return": -0.01,
        "profit_factor": 0.0,
        "sharpe_zero_rate": -1.0,
        "maximum_drawdown": 0.02,
        "positive_month_ratio": 0.0,
        "by_spread_direction": {
            "-1": {"trades": 1, "additive_net_return": -0.01},
            "1": {"trades": 0, "additive_net_return": 0.0},
        },
    }


def test_protocol_is_result_free_and_cannot_authorize_orders(tmp_path):
    output = tmp_path / "protocol.json"
    protocol = pairs.write_or_verify_protocol(output)

    assert protocol["results"] is None
    assert protocol["research_only"] is True
    assert protocol["orders_authorized"] is False
    assert protocol["paper_orders_authorized"] is False
    assert protocol["automatic_promotion"] is False
    assert protocol["protocol_sha256"] == pairs._json_hash(
        {key: value for key, value in protocol.items() if key != "protocol_sha256"}
    )
    assert pairs.write_or_verify_protocol(output) == protocol


def test_monte_carlo_null_is_deterministic():
    first = pairs.monte_carlo_null_t_statistics(
        400, observations=60, seed=17, chunk_size=73
    )
    second = pairs.monte_carlo_null_t_statistics(
        400, observations=60, seed=17, chunk_size=73
    )

    assert numpy.array_equal(first, second)
    assert numpy.all(numpy.diff(first) >= 0)
    assert 0 < pairs._monte_carlo_p_value(first[0], first) <= 1


def test_pair_selection_is_non_overlapping_and_uses_only_past_rows():
    market = _synthetic_market()
    null = pairs.monte_carlo_null_t_statistics(
        3000,
        observations=pairs.FORMATION_DAYS,
        seed=23,
        chunk_size=300,
    )
    index = 500
    selected, _audit = pairs.select_pairs(
        market["closes"], market["symbols"], index, null
    )
    changed = market["closes"].copy()
    changed[index + 1 :] *= numpy.linspace(
        1.0, 3.0, len(changed) - index - 1
    )[:, None]
    repeated, _changed_audit = pairs.select_pairs(
        changed, market["symbols"], index, null
    )

    assert selected
    assert [dataclass.key for dataclass in selected] == [
        dataclass.key for dataclass in repeated
    ]
    flattened = [column for model in selected for column in model.key]
    assert len(flattened) == len(set(flattened))


def test_simulation_is_causal_and_cost_stress_cannot_improve_equity():
    market = _synthetic_market()
    null = pairs.monte_carlo_null_t_statistics(
        3000,
        observations=pairs.FORMATION_DAYS,
        seed=29,
        chunk_size=300,
    )
    start = datetime.date(2022, 8, 1)
    end = datetime.date(2023, 7, 1)
    baseline = pairs.simulate_period(market, start, end, null)
    stress = pairs.simulate_period(
        market, start, end, null, cost_multiplier=3.0
    )
    changed = {
        **market,
        "closes": market["closes"].copy(),
        "returns": market["returns"].copy(),
    }
    end_index = market["dates"].index(end)
    changed["closes"][end_index:] *= 10.0
    changed["returns"][end_index:] = 0.5
    repeated = pairs.simulate_period(changed, start, end, null)

    assert baseline["trajectory_sha256"] == repeated["trajectory_sha256"]
    assert baseline["total_return"] == repeated["total_return"]
    assert stress["total_return"] <= baseline["total_return"] + 1e-12
    assert baseline["total_turnover"] >= 0


def test_failed_development_never_evaluates_confirmation_or_lock(
    tmp_path, monkeypatch
):
    protocol_path = tmp_path / "protocol.json"
    pairs.write_or_verify_protocol(protocol_path)
    market = _synthetic_market(days=1700)
    market["dates"] = [
        datetime.date(2022, 1, 1) + datetime.timedelta(days=index)
        for index in range(len(market["dates"]))
    ]
    monkeypatch.setattr(
        pairs, "load_market", lambda *_args, **_kwargs: (market, {})
    )
    monkeypatch.setattr(
        pairs,
        "monte_carlo_null_t_statistics",
        lambda: numpy.asarray([-4.0, -3.0, -2.0]),
    )
    calls = []

    def fake_simulation(_market, start, end, _null, *, cost_multiplier=1.0):
        calls.append((start, end, cost_multiplier))
        return _negative_report()

    monkeypatch.setattr(pairs, "simulate_period", fake_simulation)
    result = pairs.evaluate_prelock(
        protocol_path,
        [tmp_path / "unused.data"],
        [tmp_path / "unused.json"],
        tmp_path / "experiments",
    )
    report = result["report"]

    assert all(end <= pairs.DEVELOPMENT_END for _start, end, _cost in calls)
    assert report["confirmation"] is None
    assert report["locked_test"]["authorized_to_open"] is False
    assert report["locked_test"]["materialized"] is False
    assert report["orders_authorized"] is False
    saved = json.loads(
        (tmp_path / "experiments" / result["directory"].split("/")[-1] / "report.json").read_text()
    )
    assert saved["verdict"] == "REJECTED_PRELOCK_LOCK_REMAINS_SEALED"
