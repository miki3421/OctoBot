import datetime
import json
import pathlib

import numpy
import pytest

from octobot.ai_strategy_lab import (
    liquid_market_timeseries_momentum_v1 as protocol,
)
from octobot.ai_strategy_lab import (
    liquid_market_timeseries_momentum_v1_research as research,
)


UTC = datetime.timezone.utc


def _market(days=560, assets=36):
    first = datetime.date(2022, 1, 1)
    dates = [first + datetime.timedelta(days=index) for index in range(days)]
    steps = numpy.arange(days, dtype=numpy.float64)
    common_returns = (
        0.0002
        + steps * 0.000002
        + 0.0015 * numpy.sin(steps / 19.0)
    )
    asset_offsets = numpy.linspace(-0.00015, 0.00015, assets)
    daily = common_returns[:, None] + asset_offsets[None, :]
    closes = 100.0 * numpy.exp(numpy.cumsum(daily, axis=0))
    returns = numpy.zeros_like(closes)
    returns[1:] = closes[1:] / closes[:-1] - 1.0
    volume_scale = numpy.arange(1, assets + 1, dtype=numpy.float64)
    quote_volumes = numpy.broadcast_to(
        1_000_000.0 * volume_scale[None, :], closes.shape
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


def test_protocol_loader_rejects_mutation(tmp_path):
    path = tmp_path / "protocol.json"
    frozen = protocol.write_or_verify_protocol(path)

    assert research._load_protocol(path) == frozen
    changed = json.loads(path.read_text(encoding="utf-8"))
    changed["orders_authorized"] = True
    path.write_text(json.dumps(changed), encoding="utf-8")
    with pytest.raises(ValueError, match="not frozen"):
        research._load_protocol(path)


def test_liquid_basket_is_causal_and_uses_volume_rank():
    market = _market()
    index = 400
    prepared = research.prepare_market(market)

    basket, audit = research.liquid_basket(
        market, index, prepared=prepared
    )

    expected = tuple(range(35, 5, -1))
    assert audit["status"] == "BASKET"
    assert basket == expected
    excluded, _ = research.liquid_basket(
        market,
        index,
        excluded_symbols={market["symbols"][35]},
        prepared=prepared,
    )
    assert excluded == tuple(range(34, 4, -1))

    changed = {**market}
    changed["closes"] = market["closes"].copy()
    changed["quote_volumes"] = market["quote_volumes"].copy()
    changed["closes"][index + 1 :] *= 10.0
    changed["quote_volumes"][index + 1 :] = changed[
        "quote_volumes"
    ][index + 1 :, ::-1]
    changed_basket, changed_audit = research.liquid_basket(
        changed, index, prepared=research.prepare_market(changed)
    )
    assert changed_basket == basket
    assert changed_audit == audit


def test_missing_trailing_volume_excludes_asset():
    market = _market()
    index = 400
    market["quote_volumes"][index - 3, 35] = numpy.nan

    basket, audit = research.liquid_basket(market, index)

    assert 35 not in basket
    assert audit["eligible_assets"] == len(market["symbols"]) - 1


def test_upper_tercile_is_strict_deterministic_order_statistic():
    priors = [1.0, 2.0, 3.0, 4.0, 5.0, 6.0]

    tied, threshold = research._upper_tercile_signal(4.0, priors)
    above, second_threshold = research._upper_tercile_signal(4.01, priors)

    assert threshold == second_threshold == 4.0
    assert tied is False
    assert above is True


def test_signal_cache_does_not_read_future_data():
    market = _market()
    index = 420
    first = research.build_signal_cache(market)
    changed = {**market}
    changed["closes"] = market["closes"].copy()
    changed["quote_volumes"] = market["quote_volumes"].copy()
    changed["closes"][index + 1 :] *= numpy.linspace(
        0.1, 5.0, len(market["symbols"])
    )
    changed["quote_volumes"][index + 1 :] *= numpy.linspace(
        5.0, 0.1, len(market["symbols"])
    )
    second = research.build_signal_cache(changed)

    assert first["baskets"][index] == second["baskets"][index]
    assert first["scores"][index] == second["scores"][index]
    assert first["thresholds"][index] == second["thresholds"][index]
    assert first["active"][index] == second["active"][index]


def test_vintages_ramp_to_cap_and_replace_epoch_slot():
    vintages = numpy.zeros((protocol.STAGGERED_VINTAGES, 7))
    first = datetime.date(2026, 1, 1)
    aggregates = []
    for offset in range(protocol.STAGGERED_VINTAGES):
        new = numpy.zeros(7)
        new[offset] = protocol.VINTAGE_GROSS_EXPOSURE
        aggregates.append(
            research.update_vintage_targets(
                vintages, first + datetime.timedelta(days=offset), new
            ).copy()
        )

    assert [numpy.sum(value) for value in aggregates] == pytest.approx(
        [0.08, 0.16, 0.24, 0.32, 0.40]
    )
    replacement = numpy.zeros(7)
    replacement[6] = protocol.VINTAGE_GROSS_EXPOSURE
    aggregate = research.update_vintage_targets(
        vintages,
        first + datetime.timedelta(days=protocol.STAGGERED_VINTAGES),
        replacement,
    )
    assert numpy.isclose(numpy.sum(aggregate), 0.40)
    assert numpy.count_nonzero(aggregate) == protocol.STAGGERED_VINTAGES


def test_simulation_uses_costs_and_respects_gross_cap():
    market = _market()
    cache = research.build_signal_cache(market)
    active_indices = numpy.flatnonzero(cache["active"])
    start_index = int(active_indices[active_indices >= 370][0])
    start = datetime.datetime.combine(
        market["dates"][start_index], datetime.time(), UTC
    )
    end = start + datetime.timedelta(days=30)

    result = research.simulate_period(
        market,
        start,
        end,
        include_trajectory=True,
        signal_cache=cache,
    )
    stress = research.simulate_period(
        market,
        start,
        end,
        cost_multiplier=protocol.STRESS_COST_MULTIPLIER,
        signal_cache=cache,
    )

    assert result["outcomes"] == 30
    assert result["invested_days"] > 0
    assert result["maximum_gross_exposure"] <= 0.40 + 1e-12
    assert result["benchmark"]["maximum_gross_exposure"] <= 0.40 + 1e-12
    assert stress["total_return"] < result["total_return"]
    assert stress["cost_additive_contribution"] > result[
        "cost_additive_contribution"
    ]


def test_incomplete_benchmark_or_strategy_outcome_fails_closed():
    market = _market()
    index = 400
    basket, _ = research.liquid_basket(market, index)
    market["funding_counts"][index + 1, basket[0]] = 0
    start = datetime.datetime.combine(
        market["dates"][index], datetime.time(), UTC
    )

    with pytest.raises(research.DataQualityError, match="incomplete outcome"):
        research.simulate_period(
            market, start, start + datetime.timedelta(days=2)
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
