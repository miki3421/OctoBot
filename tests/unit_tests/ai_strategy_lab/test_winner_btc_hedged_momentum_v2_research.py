import datetime
import json

import numpy
import pytest

from octobot.ai_strategy_lab import winner_btc_hedged_momentum_v2 as protocol
from octobot.ai_strategy_lab import (
    winner_btc_hedged_momentum_v2_research as research,
)


UTC = datetime.timezone.utc


def _market(days=500, assets=24):
    first = datetime.date(2022, 1, 1)
    dates = [first + datetime.timedelta(days=index) for index in range(days)]
    slopes = numpy.linspace(-0.0015, 0.0015, assets)
    slopes[0] = 0.0002
    steps = numpy.arange(days, dtype=numpy.float64)[:, None]
    closes = 100.0 * numpy.exp(steps * slopes[None, :])
    returns = numpy.zeros_like(closes)
    returns[1:] = closes[1:] / closes[:-1] - 1.0
    symbols = [protocol.HEDGE_SYMBOL] + [
        f"ASSET{index:02d}USDT" for index in range(1, assets)
    ]
    return {
        "dates": dates,
        "timestamps": numpy.asarray(
            [
                int(datetime.datetime.combine(date, datetime.time(), UTC).timestamp())
                for date in dates
            ],
            dtype=numpy.int64,
        ),
        "symbols": symbols,
        "closes": closes,
        "returns": returns,
        "return_complete": numpy.ones_like(closes, dtype=bool),
        "funding": numpy.zeros_like(closes),
        "funding_counts": numpy.ones_like(closes, dtype=numpy.int16),
    }


def _monday_index(market, minimum=200):
    return next(
        index
        for index, date in enumerate(market["dates"])
        if index >= minimum and date.weekday() == 0
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


def test_target_is_causal_neutral_and_uses_fixed_btc_hedge():
    market = _market()
    index = _monday_index(market)

    target, audit = research.target_weights(market, index)

    assert audit["status"] == "TARGET"
    assert audit["winner_assets"] == int(
        len(market["symbols"]) * protocol.parent.TAIL_FRACTION
    )
    assert target[0] < 0
    assert numpy.isclose(numpy.sum(target), 0.0, atol=1e-12)
    assert numpy.sum(numpy.abs(target)) <= 0.8 + 1e-12
    non_btc_winners = [
        symbol
        for symbol in audit["winner_symbols"]
        if symbol != protocol.HEDGE_SYMBOL
    ]
    assert all(
        target[market["symbols"].index(symbol)] > 0
        for symbol in non_btc_winners
    )

    changed = {**market, "closes": market["closes"].copy()}
    changed["closes"][index + 1 :] *= numpy.linspace(2.0, 0.5, len(target))
    changed_target, changed_audit = research.target_weights(changed, index)
    assert numpy.array_equal(target, changed_target)
    assert audit == changed_audit


def test_btc_winner_is_netted_before_costs():
    market = _market()
    index = _monday_index(market)
    market["closes"][:, 0] = 100.0 * numpy.exp(
        numpy.arange(len(market["dates"])) * 0.01
    )
    market["returns"][1:, 0] = (
        market["closes"][1:, 0] / market["closes"][:-1, 0] - 1.0
    )

    target, audit = research.target_weights(market, index)

    assert audit["btc_is_winner"] is True
    assert target[0] > -protocol.parent.SIDE_GROSS_EXPOSURE
    assert target[0] < 0
    assert audit["post_net_gross"] < 0.8


def test_simulation_uses_next_day_and_stress_costs_are_conservative():
    market = _market(days=260)
    start_index = _monday_index(market)
    start = datetime.datetime.combine(
        market["dates"][start_index], datetime.time(), UTC
    )
    end = start + datetime.timedelta(days=14)

    result = research.simulate_period(market, start, end, include_trajectory=True)
    stress = research.simulate_period(
        market,
        start,
        end,
        cost_multiplier=protocol.parent.STRESS_COST_MULTIPLIER,
    )

    targets = result["_trajectory"]["targets"]
    assert result["outcomes"] == 14
    assert result["rebalances"] == 2
    assert result["btc_hedged_days"] == 14
    assert all(numpy.array_equal(targets[0], value) for value in targets[:7])
    assert stress["total_return"] < result["total_return"]
    assert stress["cost_additive_contribution"] > result["cost_additive_contribution"]


def test_incomplete_btc_outcome_fails_closed():
    market = _market(days=230)
    start_index = _monday_index(market)
    market["funding_counts"][start_index + 1, 0] = 0
    start = datetime.datetime.combine(
        market["dates"][start_index], datetime.time(), UTC
    )

    with pytest.raises(research.DataQualityError, match="incomplete outcome"):
        research.simulate_period(market, start, start + datetime.timedelta(days=2))


def test_parent_verifier_rejects_missing_artifacts(tmp_path):
    with pytest.raises(research.DataQualityError, match="artifacts differ"):
        research._verify_parent(tmp_path)
