import datetime

import numpy

from octobot.ai_strategy_lab import trend_meta


def _market(days=900):
    random = numpy.random.RandomState(42)
    dates = [
        datetime.date(2023, 1, 1) + datetime.timedelta(days=index)
        for index in range(days)
    ]
    common = random.normal(0.0003, 0.018, size=days)
    returns = numpy.column_stack(
        (
            common,
            0.8 * common + random.normal(0.0002, 0.012, size=days),
            0.5 * common + random.normal(0.0001, 0.020, size=days),
            -0.2 * common + random.normal(0.0001, 0.022, size=days),
        )
    )
    returns[0] = 0.0
    closes = 100 * numpy.cumprod(1.0 + returns, axis=0)
    return {
        "dates": dates,
        "symbols": [
            "BTC/USDT:USDT",
            "ETH/USDT:USDT",
            "SOL/USDT:USDT",
            "XRP/USDT:USDT",
        ],
        "closes": closes,
        "returns": returns,
        "funding": numpy.zeros_like(closes),
    }


def test_meta_samples_are_finite_and_end_after_each_decision():
    market = _market()
    config = trend_meta._base_config(3.0)

    samples = trend_meta._build_samples(market, config)

    assert samples["features"].shape[1] == len(
        trend_meta.FEATURE_NAMES
    )
    assert numpy.all(numpy.isfinite(samples["features"]))
    assert numpy.all(
        samples["label_end_index"]
        == samples["rebalance_index"] + trend_meta.LABEL_HORIZON_DAYS
    )
    assert set(numpy.unique(samples["labels"])) == {0, 1}


def test_meta_features_do_not_change_when_later_prices_change():
    market = _market()
    config = trend_meta._base_config(3.0)
    original = trend_meta._build_samples(market, config)
    changed = {
        key: value.copy() if isinstance(value, numpy.ndarray) else value
        for key, value in market.items()
    }
    changed["closes"][-20:] *= 3.0
    changed["returns"][-20:] = 0.0
    rebuilt = trend_meta._build_samples(changed, config)
    unaffected = original["label_end_index"] < len(market["dates"]) - 20
    rebuilt_by_key = {
        (int(index), int(column)): features
        for index, column, features in zip(
            rebuilt["rebalance_index"],
            rebuilt["asset_column"],
            rebuilt["features"],
        )
    }
    for index, column, features in zip(
        original["rebalance_index"][unaffected],
        original["asset_column"][unaffected],
        original["features"][unaffected],
    ):
        assert numpy.allclose(
            features, rebuilt_by_key[(int(index), int(column))]
        )


def test_meta_walk_forward_is_research_only_and_same_period_comparison():
    report = trend_meta.evaluate_market(_market())

    assert report["research_only"] is True
    assert report["orders_authorized"] is False
    assert report["automatic_promotion"] is False
    assert len(report["walk_forward"]["fold_reports"]) == 4
    assert report["walk_forward"]["oos_prediction_rows"] > 0
    candidate = report["reports"][f"{trend_meta.META_NAME}_oos"]
    baseline = report["reports"][
        f"{trend_meta.BASE_STRATEGY_NAME}_same_oos_baseline"
    ]
    assert candidate["evaluation_start_date"] == baseline[
        "evaluation_start_date"
    ]
    assert candidate["evaluation_end_date"] == baseline[
        "evaluation_end_date"
    ]
