import datetime

import numpy

from octobot.ai_strategy_lab import ensemble
from octobot.ai_strategy_lab import trend


def _market(days=420):
    dates = [
        datetime.date(2025, 1, 1) + datetime.timedelta(days=index)
        for index in range(days)
    ]
    first = 100 * numpy.exp(numpy.arange(days) * 0.001)
    second = 100 * numpy.exp(
        numpy.sin(numpy.arange(days) / 20) * 0.10
    )
    closes = numpy.column_stack((first, second))
    returns = numpy.zeros_like(closes)
    returns[1:] = closes[1:] / closes[:-1] - 1.0
    return {
        "dates": dates,
        "symbols": ["ALT/USDT:USDT", "BTC/USDT:USDT"],
        "closes": closes,
        "returns": returns,
        "funding": numpy.zeros_like(closes),
    }


def test_equal_sleeve_ensemble_respects_shared_gross_cap():
    configs = (
        ensemble._config_by_name(ensemble.SLEEVE_NAMES[0]),
        ensemble._config_by_name(ensemble.SLEEVE_NAMES[1]),
    )
    report = ensemble._simulate_ensemble(
        _market(), configs, initial_capital=10_000, name="test"
    )
    assert report["maximum_observed_gross_exposure"] <= 1.0 + 1e-12
    assert report["sleeve_allocations"] == [0.5, 0.5]
    assert report["evaluation_days"] == 300
    assert set(report["ending_weights"]) == {
        "ALT/USDT:USDT",
        "BTC/USDT:USDT",
    }


def test_rolling_month_return_compounds_twelve_months():
    values = {
        f"2025-{month:02d}": 0.01 for month in range(1, 13)
    }
    result = ensemble._rolling_month_returns(values, 12)
    assert len(result) == 1
    assert numpy.isclose(next(iter(result.values())), 1.01**12 - 1)


def test_registered_sleeves_remain_append_only_trend_configs():
    names = {value.name for value in trend.TREND_CONFIGS}
    assert set(ensemble.SLEEVE_NAMES) <= names
