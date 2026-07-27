import datetime
import json

import numpy

from octobot.ai_strategy_lab import price_path_forecaster_v1 as path_model


def _candles(count=480):
    timestamp = 1_700_000_100
    timestamp -= timestamp % path_model.CANDLE_SECONDS
    increments = (
        0.0002
        + 0.0003 * numpy.sin(numpy.arange(count) / 11.0)
    )
    close = 100 * numpy.exp(numpy.cumsum(increments))
    open_price = numpy.concatenate(([close[0]], close[:-1]))
    return numpy.column_stack(
        (
            timestamp
            + numpy.arange(count) * path_model.CANDLE_SECONDS,
            open_price,
            numpy.maximum(open_price, close) * 1.001,
            numpy.minimum(open_price, close) * 0.999,
            close,
            100
            + numpy.arange(count)
            + 20 * numpy.sin(numpy.arange(count) / 5.0),
        )
    )


def _model(feature_count):
    horizon_count = len(path_model.HORIZONS)
    residuals = numpy.column_stack(
        (
            numpy.full(horizon_count, -0.5),
            numpy.zeros(horizon_count),
            numpy.full(horizon_count, 0.5),
        )
    )
    weights = numpy.zeros((feature_count + 1, horizon_count))
    weights[-1] = numpy.linspace(0.1, 0.5, horizon_count)
    return path_model.DirectPathModel(
        asset="BTC",
        feature_mean=numpy.zeros(feature_count),
        feature_scale=numpy.ones(feature_count),
        weights=weights,
        residual_quantiles_pct=residuals,
        prediction_lower_pct=numpy.full(horizon_count, -5.0),
        prediction_upper_pct=numpy.full(horizon_count, 5.0),
        ridge_alpha=0.01,
    )


def test_protocol_is_result_free_and_disables_orders(tmp_path):
    protocol = path_model.frozen_protocol()

    assert protocol["orders_authorized"] is False
    assert protocol["paper_orders_authorized"] is False
    assert protocol["implementation_policy"]["results_in_this_protocol"] is False
    assert protocol["baseline"]["name"] == "unchanged_price"

    path = path_model.write_protocol(tmp_path)
    assert path.is_file()


def test_features_are_causal_before_future_edit():
    candles = _candles()
    original = path_model.causal_features(candles)
    changed = candles.copy()
    changed[360:, 1:6] *= 1.20
    updated = path_model.causal_features(changed)

    numpy.testing.assert_allclose(
        original[:360], updated[:360], equal_nan=True
    )
    assert original.shape[1] == len(path_model.feature_names())


def test_dataset_targets_match_fixed_future_closes():
    candles = _candles()
    dataset = path_model.build_dataset(candles)
    row = 10
    candle_index = dataset.candle_indices[row]

    expected = [
        numpy.log(
            candles[candle_index + horizon_bars, 4]
            / candles[candle_index, 4]
        )
        * 100
        for _name, horizon_bars in path_model.HORIZONS
    ]

    numpy.testing.assert_allclose(
        dataset.targets_pct[row], expected, rtol=1e-6
    )


def test_model_round_trip_is_exact(tmp_path):
    model = _model(len(path_model.feature_names()))
    features = numpy.ones((4, len(path_model.feature_names())))
    original = model.predict(features)

    model.save(tmp_path)
    restored = path_model.DirectPathModel.load(tmp_path)
    replay = restored.predict(features)

    for key in original:
        numpy.testing.assert_array_equal(original[key], replay[key])


def test_live_chart_path_has_independent_horizon_points(
    tmp_path, monkeypatch
):
    candles = _candles()
    model = _model(len(path_model.feature_names()))
    model.save(tmp_path / "models" / "btc")
    report = {
        "assets": {
            "BTC": {
                "diagnostic_reuse_audits": {
                    "kucoin_reused_2026": {"horizons": {}}
                }
            }
        }
    }
    (tmp_path / "report.json").write_text(
        json.dumps(report), encoding="utf-8"
    )
    display = [
        (
            datetime.datetime(2026, 7, 20)
            + datetime.timedelta(minutes=15 * index)
        ).strftime("%y-%m-%d %H:%M:%S")
        for index in range(len(candles))
    ]
    path_model._load_live_model.cache_clear()
    path_model._load_live_report.cache_clear()

    payload = path_model.analyze_chart_path(
        times=candles[:, 0],
        display_times=display,
        opens=candles[:, 1],
        highs=candles[:, 2],
        lows=candles[:, 3],
        closes=candles[:, 4],
        volumes=candles[:, 5],
        symbol="BTC/USDT:USDT",
        artifact_root=tmp_path,
    )

    assert payload["orders_authorized"] is False
    assert payload["forecast_uses_future_outcomes"] is False
    assert len(payload["latest"]["x"]) == 6
    assert tuple(payload["latest"]["endpoints"]) == (
        "1h",
        "2h",
        "4h",
        "6h",
        "8h",
    )
    assert payload["latest"]["predicted_return_pct"]["8h"] == 0.5
