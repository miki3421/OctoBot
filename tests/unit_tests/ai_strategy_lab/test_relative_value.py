import datetime

import numpy

from octobot.ai_strategy_lab import relative_value


def _market(days=520, assets=10):
    random = numpy.random.RandomState(7)
    dates = [
        datetime.date(2024, 1, 1) + datetime.timedelta(days=index)
        for index in range(days)
    ]
    common = random.normal(0.0003, 0.015, size=days)
    columns = [common]
    for index in range(1, assets):
        columns.append(
            (0.4 + 0.05 * index) * common
            + random.normal(
                0.0001 * (index - assets / 2),
                0.012 + 0.001 * index,
                size=days,
            )
        )
    returns = numpy.column_stack(columns)
    returns[0] = 0.0
    closes = 100.0 * numpy.cumprod(1.0 + returns, axis=0)
    return {
        "dates": dates,
        "symbols": ["BTC/USDT:USDT"]
        + [f"ALT{index}/USDT:USDT" for index in range(1, assets)],
        "closes": closes,
        "returns": returns,
        "funding": numpy.zeros_like(closes),
    }


def test_residual_target_is_neutral_capped_and_excludes_btc():
    market = _market()
    target = relative_value._target_weights(
        market["closes"],
        market["returns"],
        200,
        btc_column=0,
    )

    assert target[0] == 0
    assert numpy.isclose(numpy.sum(target), 0.0, atol=1e-12)
    assert numpy.sum(numpy.abs(target)) <= 0.5 + 1e-12
    assert numpy.max(numpy.abs(target)) <= 0.10 + 1e-12
    assert numpy.count_nonzero(target > 0) == 3
    assert numpy.count_nonzero(target < 0) == 3


def test_residual_target_does_not_use_future_prices():
    market = _market()
    original = relative_value._target_weights(
        market["closes"],
        market["returns"],
        200,
        btc_column=0,
    )
    changed_closes = market["closes"].copy()
    changed_returns = market["returns"].copy()
    changed_closes[201:] *= 10
    changed_returns[201:] = 0.5

    changed = relative_value._target_weights(
        changed_closes,
        changed_returns,
        200,
        btc_column=0,
    )

    assert numpy.allclose(original, changed)


def test_relative_value_report_is_research_only_and_gross_bounded():
    report = relative_value.evaluate_market(_market())
    standalone = report["reports"][relative_value.STRATEGY_NAME]
    combined = report["reports"][relative_value.COMBINATION_NAME]

    assert report["research_only"] is True
    assert report["orders_authorized"] is False
    assert report["automatic_promotion"] is False
    assert standalone["maximum_observed_gross_exposure"] <= 0.5 + 1e-12
    assert standalone["maximum_absolute_net_exposure"] <= 1e-12
    assert combined["maximum_conservative_gross_exposure"] == 0.875
    assert set(combined["sleeve_allocations"]) == {
        "v3",
        "relative_value",
    }


def test_reversal_target_is_opposite_of_residual_momentum_ranking():
    market = _market()
    momentum = relative_value._target_weights(
        market["closes"],
        market["returns"],
        200,
        btc_column=0,
    )
    reversal = relative_value._reversal_target_weights(
        market["closes"],
        market["returns"],
        200,
        btc_column=0,
    )

    assert reversal[0] == 0
    assert numpy.isclose(numpy.sum(reversal), 0.0, atol=1e-12)
    assert numpy.sum(numpy.abs(reversal)) <= 0.5 + 1e-12
    assert numpy.max(numpy.abs(reversal)) <= 0.10 + 1e-12
    assert numpy.any(reversal != momentum)


def test_reversal_report_remains_research_only():
    report = relative_value.evaluate_reversal_market(_market())

    assert report["research_only"] is True
    assert report["orders_authorized"] is False
    assert report["automatic_promotion"] is False
    standalone = report["reports"][relative_value.REVERSAL_NAME]
    combined = report["reports"][
        relative_value.REVERSAL_COMBINATION_NAME
    ]
    assert standalone["maximum_observed_gross_exposure"] <= 0.5 + 1e-12
    assert standalone["maximum_absolute_net_exposure"] <= 1e-12
    assert combined["maximum_conservative_gross_exposure"] == 0.875
