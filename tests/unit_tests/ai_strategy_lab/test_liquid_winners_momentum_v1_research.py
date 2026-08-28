import datetime
import json
import pathlib

import numpy
import pytest

from octobot.ai_strategy_lab import liquid_winners_momentum_v1 as protocol
from octobot.ai_strategy_lab import (
    liquid_winners_momentum_v1_research as research,
)


UTC = datetime.timezone.utc


def _market(days=520, assets=40):
    first = datetime.date(2022, 1, 1)
    dates = [first + datetime.timedelta(days=index) for index in range(days)]
    steps = numpy.arange(days, dtype=numpy.float64)
    common = 0.0004 + 0.0003 * numpy.sin(steps / 17.0)
    offsets = numpy.linspace(-0.0001, 0.0003, assets)
    daily = common[:, None] + offsets[None, :]
    closes = 100.0 * numpy.exp(numpy.cumsum(daily, axis=0))
    returns = numpy.zeros_like(closes)
    returns[1:] = closes[1:] / closes[:-1] - 1.0
    volume_scale = numpy.geomspace(1_000_000.0, 1_000_000_000.0, assets)
    quote_volumes = numpy.broadcast_to(
        volume_scale[None, :], closes.shape
    ).copy()
    symbols = [f"ASSET{index:02d}USDT" for index in range(assets)]
    return {
        "dates": dates,
        "timestamps": numpy.asarray(
            [
                int(
                    datetime.datetime.combine(
                        date, datetime.time(), UTC
                    ).timestamp()
                )
                for date in dates
            ],
            dtype=numpy.int64,
        ),
        "symbols": symbols,
        "closes": closes,
        "quote_volumes": quote_volumes,
        "returns": returns,
        "return_complete": numpy.ones_like(closes, dtype=bool),
        "funding": numpy.zeros_like(closes),
        "funding_counts": numpy.ones_like(closes, dtype=numpy.int16),
    }


def _rebalance_index(market, minimum=220):
    return next(
        index
        for index, date in enumerate(market["dates"])
        if index >= minimum and research.is_rebalance_date(date)
    )


def test_protocol_loader_rejects_mutation(tmp_path):
    path = tmp_path / "protocol.json"
    frozen = protocol.write_or_verify_protocol(path)

    assert research._load_protocol(path) == frozen
    changed = json.loads(path.read_text(encoding="utf-8"))
    changed["orders_authorized"] = True
    path.write_text(json.dumps(changed), encoding="utf-8")
    with pytest.raises(ValueError, match="not frozen"):
        research._load_protocol(path)


def test_target_selects_liquid_tail_then_winner_tail_causally():
    market = _market()
    index = _rebalance_index(market)
    prepared = research.prepare_market(market)

    target, benchmark, audit = research.target_weights(
        market, index, prepared=prepared
    )

    assert audit["status"] == "TARGET"
    assert audit["liquid_assets"] == 12
    assert audit["winner_assets"] == 3
    assert audit["liquid_symbols"] == [
        market["symbols"][value] for value in range(39, 27, -1)
    ]
    assert audit["winner_symbols"] == [
        market["symbols"][value] for value in (39, 38, 37)
    ]
    assert numpy.isclose(numpy.sum(target), 0.40)
    assert numpy.isclose(numpy.sum(benchmark), 0.40)
    assert numpy.count_nonzero(target) == 3
    assert numpy.count_nonzero(benchmark) == 12

    changed = {**market}
    changed["closes"] = market["closes"].copy()
    changed["quote_volumes"] = market["quote_volumes"].copy()
    changed["closes"][index + 1 :] *= numpy.linspace(
        5.0, 0.2, len(market["symbols"])
    )
    changed["quote_volumes"][index + 1 :] = changed[
        "quote_volumes"
    ][index + 1 :, ::-1]
    changed_target, changed_benchmark, changed_audit = research.target_weights(
        changed, index, prepared=research.prepare_market(changed)
    )
    assert numpy.array_equal(changed_target, target)
    assert numpy.array_equal(changed_benchmark, benchmark)
    assert changed_audit == audit


def test_zero_trailing_volume_excludes_asset():
    market = _market()
    index = _rebalance_index(market)
    market["quote_volumes"][index - 2, 39] = 0.0

    _, _, audit = research.target_weights(market, index)

    assert audit["eligible_assets"] == len(market["symbols"]) - 1
    assert market["symbols"][39] not in audit["liquid_symbols"]


def test_target_rejects_non_anchored_date():
    market = _market()
    index = _rebalance_index(market) + 1

    with pytest.raises(ValueError, match="anchored rebalance"):
        research.target_weights(market, index)


def test_exclusion_is_applied_before_both_fractional_counts():
    market = _market()
    index = _rebalance_index(market)
    excluded_symbol = market["symbols"][39]

    target, benchmark, audit = research.target_weights(
        market, index, excluded_symbols={excluded_symbol}
    )

    assert audit["eligible_assets"] == 39
    assert audit["liquid_assets"] == 11
    assert audit["winner_assets"] == 3
    assert target[39] == benchmark[39] == 0.0


def test_simulation_holds_fourteen_days_and_stress_is_conservative():
    market = _market()
    start_index = _rebalance_index(market)
    start = datetime.datetime.combine(
        market["dates"][start_index], datetime.time(), UTC
    )
    end = start + datetime.timedelta(days=42)

    result = research.simulate_period(
        market, start, end, include_trajectory=True
    )
    stress = research.simulate_period(
        market,
        start,
        end,
        cost_multiplier=protocol.STRESS_COST_MULTIPLIER,
    )

    targets = result["_trajectory"]["targets"]
    assert result["outcomes"] == 42
    assert result["rebalances"] == 3
    assert result["active_rebalances"] == 3
    assert all(numpy.array_equal(targets[0], value) for value in targets[:14])
    assert result["maximum_gross_exposure"] <= 0.40 + 1e-12
    assert stress["total_return"] < result["total_return"]
    assert stress["cost_additive_contribution"] > result[
        "cost_additive_contribution"
    ]


def test_incomplete_benchmark_or_winner_outcome_fails_closed():
    market = _market()
    index = _rebalance_index(market)
    _, _, audit = research.target_weights(market, index)
    column = market["symbols"].index(audit["liquid_symbols"][0])
    market["funding_counts"][index + 1, column] = 0
    start = datetime.datetime.combine(
        market["dates"][index], datetime.time(), UTC
    )

    with pytest.raises(research.DataQualityError, match="incomplete outcome"):
        research.simulate_period(
            market, start, start + datetime.timedelta(days=2)
        )


def test_training_gate_implements_every_frozen_check():
    report = {
        "outcomes": 1_277,
        "invested_days": 1_250,
        "rebalances": 91,
        "active_rebalances": 91,
        "total_return": 0.50,
        "annualized_return": 0.15,
        "sharpe_zero_rate": 1.20,
        "profit_factor": 1.30,
        "maximum_drawdown": 0.15,
        "positive_month_ratio": 0.70,
        "gross_edge_before_costs": 0.60,
        "cost_additive_contribution": 0.05,
        "market_beta": 0.80,
        "annualized_market_alpha": 0.06,
        "annualized_excess_return_over_benchmark": 0.05,
        "sharpe_improvement_over_benchmark": 0.20,
        "drawdown_ratio_to_benchmark": 0.70,
        "maximum_symbol_absolute_contribution_share": 0.10,
        "total_turnover": 40.0,
        "average_gross_exposure": 0.39,
        "maximum_gross_exposure": 0.40,
    }
    stress = {
        **report,
        "total_return": 0.40,
        "annualized_return": 0.10,
        "sharpe_zero_rate": 0.90,
        "profit_factor": 1.15,
        "maximum_drawdown": 0.20,
        "gross_edge_before_costs": 0.60,
        "cost_additive_contribution": 0.10,
    }
    folds = [{"total_return": 0.02} for _ in protocol.TRAINING_FOLDS]

    gate = research._training_gate(report, stress, folds, folds, 1.0)

    assert gate["passed"] is True
    assert gate["total_checks"] == len(
        protocol.frozen_protocol()["training_eligibility_gate"]
    )


def test_implementation_lock_rejects_mutation(tmp_path):
    protocol_path = tmp_path / "protocol.json"
    protocol.write_or_verify_protocol(protocol_path)
    test_path = pathlib.Path(__file__).resolve()
    lock_path = tmp_path / "implementation-lock.json"
    research.write_or_verify_implementation_lock(
        protocol_path, test_path, lock_path
    )
    changed = json.loads(lock_path.read_text(encoding="utf-8"))
    changed["orders_authorized"] = True
    lock_path.write_text(json.dumps(changed), encoding="utf-8")

    with pytest.raises(research.DataQualityError, match="lock differs"):
        research._verify_implementation_lock(
            lock_path, protocol_path, test_path
        )
