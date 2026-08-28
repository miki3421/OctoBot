import datetime
import json

import numpy
import pytest

from octobot.ai_strategy_lab import cointegration_pairs_v1 as parent
from octobot.ai_strategy_lab import cointegration_pairs_v2 as protocol
from octobot.ai_strategy_lab import cointegration_pairs_v2_research as research


def _synthetic_market(days=760, assets=8):
    random = numpy.random.RandomState(31)
    dates = [
        datetime.date(2022, 1, 1) + datetime.timedelta(days=index)
        for index in range(days)
    ]
    common = numpy.cumsum(random.normal(0.0003, 0.018, size=days))
    stationary = numpy.zeros(days)
    for index in range(1, days):
        stationary[index] = (
            0.80 * stationary[index - 1] + random.normal(0, 0.018)
        )
    logs = [common, 0.2 + 1.1 * common + stationary]
    for index in range(2, assets):
        logs.append(
            numpy.cumsum(random.normal(0.0001 * index, 0.02, size=days))
        )
    closes = numpy.exp(numpy.column_stack(logs) + 5.0)
    returns = numpy.zeros_like(closes)
    returns[1:] = closes[1:] / closes[:-1] - 1.0
    return {
        "dates": dates,
        "timestamps": numpy.asarray(
            [
                int(
                    datetime.datetime.combine(
                        date, datetime.time(), datetime.timezone.utc
                    ).timestamp()
                )
                for date in dates
            ],
            dtype=numpy.int64,
        ),
        "symbols": [f"ASSET{index:02d}USDT" for index in range(assets)],
        "closes": closes,
        "returns": returns,
        "return_complete": numpy.ones_like(closes, dtype=bool),
        "funding": numpy.zeros_like(closes),
        "funding_counts": numpy.ones_like(closes, dtype=numpy.int16),
    }


def _small_null():
    return research.monte_carlo_null_t_statistics(
        5000,
        observations=parent.FORMATION_DAYS,
        seed=43,
        chunk_size=500,
    )


def test_protocol_loader_rejects_mutation(tmp_path):
    path = tmp_path / "protocol.json"
    frozen = protocol.write_or_verify_protocol(path)

    assert research._load_protocol(path) == frozen
    changed = json.loads(path.read_text())
    changed["orders_authorized"] = True
    path.write_text(json.dumps(changed))
    with pytest.raises(ValueError, match="not frozen"):
        research._load_protocol(path)


def test_bh_uses_all_eligible_hypotheses_not_prefiltered_candidates():
    assert research._bh_threshold([0.001], total_tests=1) == 0.001
    assert research._bh_threshold([0.001], total_tests=100) is None
    with pytest.raises(ValueError):
        research._bh_threshold([0.01, 0.02], total_tests=1)


def test_formation_fit_is_causal_and_counts_every_eligible_pair():
    market = _synthetic_market()
    null = _small_null()
    index = 500

    first = research.fit_formation(market, index, null)
    changed = {**market, "closes": market["closes"].copy()}
    changed["closes"][index + 1 :] *= 3.0
    second = research.fit_formation(changed, index, null)

    assert first["total_tests"] == 28
    assert first["eligible_columns"] == list(range(8))
    assert first["candidates"] == second["candidates"]


def test_selection_is_non_overlapping_and_exclusion_changes_denominator():
    market = _synthetic_market()
    null = _small_null()
    formation = research.fit_formation(market, 500, null)

    selected, audit = research.select_pairs(formation, market["symbols"])
    excluded, excluded_audit = research.select_pairs(
        formation,
        market["symbols"],
        excluded_symbols={market["symbols"][0]},
    )

    assert selected
    flattened = [column for model in selected for column in model.key]
    assert len(flattened) == len(set(flattened))
    assert audit["tested_pairs"] == 28
    assert excluded_audit["tested_pairs"] == 21
    assert all(0 not in model.key for model in excluded)


def test_period_end_does_not_open_a_target_without_an_outcome():
    market = _synthetic_market(days=220)
    index = market["dates"].index(datetime.date(2022, 7, 1))
    report = research.simulate_period(
        market,
        {index: {}},
        datetime.date(2022, 7, 1),
        datetime.date(2022, 7, 2),
    )

    assert report["days"] == 1
    assert report["closed_trades"] == 0
    assert report["total_turnover"] == 0
    assert report["total_return"] == 0


def test_close_signal_applies_only_to_the_following_daily_return():
    dates = [datetime.date(2024, 1, 1), datetime.date(2024, 1, 2)]
    closes = numpy.asarray([[100.0, 200.0], [110.0, 180.0]])
    model = parent.PairModel(
        first=0,
        second=1,
        alpha=float(numpy.log(200.0) - numpy.log(100.0) - 3.0),
        beta=1.0,
        residual_mean=0.0,
        residual_std=1.0,
        adf_t=-5.0,
        p_value=0.001,
        half_life_days=10.0,
        zero_crossings=10,
    )
    market = {
        "dates": dates,
        "timestamps": numpy.asarray([1, 2]),
        "symbols": ["FIRSTUSDT", "SECONDUSDT"],
        "closes": closes,
        "returns": numpy.asarray([[0.90, 0.90], [0.10, -0.10]]),
        "return_complete": numpy.ones_like(closes, dtype=bool),
        "funding": numpy.zeros_like(closes),
        "funding_counts": numpy.ones_like(closes, dtype=numpy.int16),
    }
    formation = {
        "index": 0,
        "date": dates[0],
        "eligible_columns": [0, 1],
        "total_tests": 1,
        "candidates": [model],
    }

    report = research.simulate_period(
        market,
        {0: formation},
        dates[0],
        datetime.date(2024, 1, 3),
    )

    cost = parent.FEE_PER_TURNOVER + parent.SLIPPAGE_PER_TURNOVER
    expected = (1.0 - 0.25 * cost) * 1.025 * (1.0 - 0.25 * cost) - 1.0
    assert report["total_return"] == pytest.approx(expected)
    assert report["closed_trades"] == 1
    assert report["trades"][0]["gross_return"] == pytest.approx(0.025)
    assert report["trades"][0]["net_return"] == pytest.approx(
        0.025 - 0.50 * cost
    )


def test_simulation_is_causal_and_stress_is_conservative():
    market = _synthetic_market()
    null = _small_null()
    start = datetime.date(2022, 8, 1)
    end = datetime.date(2023, 1, 1)
    cache = research.build_formation_cache(market, start, end, null)

    baseline = research.simulate_period(market, cache, start, end)
    stress = research.simulate_period(
        market,
        cache,
        start,
        end,
        cost_multiplier=parent.STRESS_COST_MULTIPLIER,
    )
    changed = {
        **market,
        "closes": market["closes"].copy(),
        "returns": market["returns"].copy(),
    }
    end_index = market["dates"].index(end)
    changed["closes"][end_index:] *= 10.0
    changed["returns"][end_index:] = 0.5
    repeated = research.simulate_period(changed, cache, start, end)

    assert baseline["closed_trades"] > 0
    assert stress["total_return"] <= baseline["total_return"] + 1e-12
    assert repeated["total_return"] == baseline["total_return"]
    assert repeated["trades"] == baseline["trades"]


def test_open_position_with_missing_funding_fails_closed():
    market = _synthetic_market()
    null = _small_null()
    start = datetime.date(2022, 8, 1)
    end = datetime.date(2023, 1, 1)
    cache = research.build_formation_cache(market, start, end, null)
    baseline = research.simulate_period(market, cache, start, end)
    first_trade = baseline["trades"][0]
    entry = datetime.date.fromisoformat(first_trade["entry_date"])
    outcome_index = market["dates"].index(entry) + 1
    first_symbol = first_trade["pair"].split("|")[0]
    symbol_index = market["symbols"].index(first_symbol)
    market["funding_counts"][outcome_index, symbol_index] = 0

    with pytest.raises(research.DataQualityError, match="incomplete"):
        research.simulate_period(market, cache, start, end)


def test_gate_values_are_plain_booleans():
    report = {
        "closed_trades": 30,
        "total_return": 0.10,
        "annualized_return": 0.05,
        "profit_factor": 1.5,
        "sharpe_zero_rate": 1.0,
        "maximum_drawdown": 0.05,
        "positive_month_ratio": 0.6,
        "by_spread_direction": {
            "-1": {"trades": 5, "additive_net_return": 0.01},
            "1": {"trades": 5, "additive_net_return": 0.01},
        },
        "market_beta": 0.0,
        "maximum_pair_absolute_contribution_share": 0.2,
    }
    gate = research._development_gate(report, report, 4, 1.0)

    assert gate["passed"] is True
    assert all(type(value) is bool for value in gate["checks"].values())
