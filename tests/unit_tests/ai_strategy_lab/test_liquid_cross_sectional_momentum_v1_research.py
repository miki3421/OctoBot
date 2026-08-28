import datetime
import json

import numpy
import pytest

from octobot.ai_strategy_lab import liquid_cross_sectional_momentum_v1 as protocol
from octobot.ai_strategy_lab import (
    liquid_cross_sectional_momentum_v1_research as research,
)


UTC = datetime.timezone.utc


def _market(days=500, assets=24):
    first = datetime.date(2022, 1, 1)
    dates = [first + datetime.timedelta(days=index) for index in range(days)]
    slopes = numpy.linspace(-0.0015, 0.0015, assets)
    steps = numpy.arange(days, dtype=numpy.float64)[:, None]
    closes = 100.0 * numpy.exp(steps * slopes[None, :])
    returns = numpy.zeros_like(closes)
    returns[1:] = closes[1:] / closes[:-1] - 1.0
    return {
        "dates": dates,
        "timestamps": numpy.asarray(
            [
                int(datetime.datetime.combine(date, datetime.time(), UTC).timestamp())
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


def test_target_is_causal_neutral_and_uses_three_week_ranking():
    market = _market()
    index = _monday_index(market)

    target, audit = research.target_weights(market, index)

    count = int(len(market["symbols"]) * protocol.TAIL_FRACTION)
    assert audit["status"] == "TARGET"
    assert audit["tail_assets"] == count
    assert numpy.all(target[:count] < 0)
    assert numpy.all(target[-count:] > 0)
    assert numpy.isclose(numpy.sum(target), 0.0, atol=1e-12)
    assert numpy.isclose(numpy.sum(numpy.abs(target)), 0.8)

    changed = {**market, "closes": market["closes"].copy()}
    changed["closes"][index + 1 :] *= numpy.linspace(2.0, 0.5, len(target))
    changed_target, changed_audit = research.target_weights(changed, index)
    assert numpy.array_equal(target, changed_target)
    assert audit == changed_audit


def test_exactly_180_contiguous_closes_are_required():
    market = _market()

    assert research._eligible_columns(market, 178) == []
    assert len(research._eligible_columns(market, 179)) == 24
    market["closes"][0, 0] = numpy.nan
    assert 0 not in research._eligible_columns(market, 179)
    assert 0 in research._eligible_columns(market, 180)


def test_simulation_holds_target_and_uses_only_following_returns():
    market = _market(days=260)
    start_index = _monday_index(market)
    start = datetime.datetime.combine(
        market["dates"][start_index], datetime.time(), UTC
    )
    end = start + datetime.timedelta(days=14)

    result = research.simulate_period(
        market, start, end, include_trajectory=True
    )
    stress = research.simulate_period(
        market, start, end, cost_multiplier=protocol.STRESS_COST_MULTIPLIER
    )

    targets = result["_trajectory"]["targets"]
    assert result["outcomes"] == 14
    assert result["rebalances"] == 2
    assert all(numpy.array_equal(targets[0], value) for value in targets[:7])
    assert all(numpy.array_equal(targets[7], value) for value in targets[7:])
    assert result["long_additive_contribution"] > 0
    assert result["short_additive_contribution"] > 0
    assert stress["total_return"] < result["total_return"]
    assert stress["cost_additive_contribution"] > result["cost_additive_contribution"]


def test_incomplete_active_outcome_fails_closed():
    market = _market(days=230)
    start_index = _monday_index(market)
    target, _audit = research.target_weights(market, start_index)
    selected = int(numpy.flatnonzero(target)[0])
    market["funding_counts"][start_index + 1, selected] = 0
    start = datetime.datetime.combine(
        market["dates"][start_index], datetime.time(), UTC
    )

    with pytest.raises(research.DataQualityError, match="incomplete outcome"):
        research.simulate_period(market, start, start + datetime.timedelta(days=2))


def test_implementation_lock_binds_sources_and_remains_orderless(tmp_path):
    protocol_path = tmp_path / "protocol.json"
    protocol.write_or_verify_protocol(protocol_path)
    test_path = tmp_path / "evaluator-test.py"
    test_path.write_text("# frozen test\n", encoding="utf-8")
    lock_path = tmp_path / "implementation-lock.json"

    lock = research.write_or_verify_implementation_lock(
        protocol_path, test_path, lock_path
    )

    assert lock["economic_outcomes_read_before_lock"] is False
    assert lock["orders_authorized"] is False
    assert research.write_or_verify_implementation_lock(
        protocol_path, test_path, lock_path
    ) == lock
    test_path.write_text("# changed\n", encoding="utf-8")
    with pytest.raises(research.DataQualityError, match="source hashes"):
        research.write_or_verify_implementation_lock(
            protocol_path, test_path, lock_path
        )
