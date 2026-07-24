import numpy

from octobot.ai_strategy_lab import model
from octobot.ai_strategy_lab import percentage_probability_engine


def _candles(count=400, seconds=300, start=1_700_000_000):
    close = numpy.linspace(100.0, 101.0, count)
    return numpy.column_stack(
        (
            start + numpy.arange(count) * seconds,
            close,
            close + 0.1,
            close - 0.1,
            close,
            numpy.linspace(10.0, 20.0, count),
        )
    )


def test_first_touch_is_conservative_when_stop_and_target_share_candle():
    config = percentage_probability_engine.PercentageProbabilityConfig(
        time_frame="1h", horizon_hours=1
    )
    candles = _candles(count=80, seconds=3600)
    candles[61, 2] = candles[60, 4] * 1.02
    candles[61, 3] = candles[60, 4] * 0.98

    labels, resolved = percentage_probability_engine._first_touch_labels(
        candles[:, 2],
        candles[:, 3],
        candles[:, 4],
        config,
        direction=1,
    )

    assert labels[60] == 0
    assert resolved[60]


def test_first_touch_labels_target_before_stop():
    config = percentage_probability_engine.PercentageProbabilityConfig(
        time_frame="1h", horizon_hours=2
    )
    candles = _candles(count=80, seconds=3600)
    candles[61, 2] = candles[60, 4] * 1.013
    candles[61, 3] = candles[60, 4] * 0.999

    labels, resolved = percentage_probability_engine._first_touch_labels(
        candles[:, 2],
        candles[:, 3],
        candles[:, 4],
        config,
        direction=1,
    )

    assert labels[60] == 1
    assert resolved[60]


def test_build_examples_creates_two_directions_and_rejects_gap_horizons():
    config = percentage_probability_engine.PercentageProbabilityConfig(
        time_frame="5m", horizon_hours=1
    )
    candles = _candles()
    candles[250:, 0] += 300

    examples = percentage_probability_engine.build_examples(candles, config)

    assert examples.features.shape[1] == len(
        percentage_probability_engine.MODEL_FEATURE_NAMES
    )
    assert set(examples.directions) == {-1, 1}
    assert len(examples.labels) == len(examples.features)
    assert not numpy.any(
        (examples.timestamps >= int(candles[238, 0]) + 300)
        & (examples.timestamps <= int(candles[249, 0]) + 300)
    )


def test_break_even_probability_accounts_for_round_trip_cost():
    config = percentage_probability_engine.PercentageProbabilityConfig(
        time_frame="15m"
    )

    assert abs(config.break_even_probability - 0.58) < 1e-12


def test_isotonic_calibration_is_monotonic_and_clamps_unseen_tails():
    scores = numpy.linspace(0.1, 0.9, 800)
    labels = numpy.concatenate(
        (
            numpy.zeros(200),
            numpy.ones(200),
            numpy.zeros(200),
            numpy.ones(200),
        )
    )

    calibrator = (
        percentage_probability_engine.QuantileIsotonicCalibrator.fit(
            scores,
            labels,
            maximum_bins=8,
            minimum_rows_per_bin=100,
        )
    )
    predictions = calibrator.predict(
        numpy.asarray([-1.0, 0.2, 0.5, 0.8, 2.0])
    )

    assert numpy.all(numpy.diff(predictions) >= 0)
    assert predictions[0] == calibrator.values[0]
    assert predictions[-1] == calibrator.values[-1]


def test_calibrated_model_round_trip(tmp_path):
    feature_count = len(percentage_probability_engine.MODEL_FEATURE_NAMES)
    base = model.NumpyLogisticModel(
        feature_names=percentage_probability_engine.MODEL_FEATURE_NAMES,
        mean=numpy.zeros(feature_count),
        scale=numpy.ones(feature_count),
        weights=numpy.linspace(-0.1, 0.1, feature_count),
        intercept=0.2,
        config=model.LogisticConfig(),
    )
    calibrator = percentage_probability_engine.QuantileIsotonicCalibrator(
        upper_score=numpy.asarray([0.4, 0.6]),
        values=numpy.asarray([0.3, 0.5]),
    )
    original = percentage_probability_engine.CalibratedPercentageModel(
        base,
        calibrator,
        percentage_probability_engine.PercentageProbabilityConfig("15m"),
    )
    features = numpy.zeros((3, feature_count))

    original.save(tmp_path)
    loaded = percentage_probability_engine.CalibratedPercentageModel.load(
        tmp_path
    )

    assert numpy.allclose(
        original.predict_proba(features),
        loaded.predict_proba(features),
    )


def test_long_hypothesis_applies_profit_lock_and_ignores_overlapping_signal():
    config = percentage_probability_engine.PercentageProbabilityConfig("15m")
    times = [f"t{index}" for index in range(7)]
    highs = [100.1, 100.1, 101.3, 101.4, 100.1, 100.1, 100.1]
    lows = [99.9, 99.9, 100.0, 100.9, 99.9, 98.9, 99.9]
    closes = [100.0] * 7

    trades, ignored = percentage_probability_engine._simulate_long_hypothesis(
        times=times,
        highs=highs,
        lows=lows,
        closes=closes,
        candidate_indices=numpy.asarray([1, 2, 4]),
        raw_scores_by_index={1: 0.6, 2: 0.7, 4: 0.8},
        probabilities_by_index={1: 0.5, 2: 0.5, 4: 0.5},
        last_closed_index=6,
        config=config,
    )

    assert ignored == 1
    assert [trade["entry_index"] for trade in trades] == [1, 4]
    assert trades[0]["exit_reason"] == "profit_lock"
    assert abs(trades[0]["gross_return_pct"] - 1.0) < 1e-12
    assert abs(trades[0]["net_return_pct"] - 0.84) < 1e-12
    assert trades[1]["exit_reason"] == "initial_stop"
    assert abs(trades[1]["net_return_pct"] + 1.16) < 1e-12


def test_long_hypothesis_keeps_unresolved_trade_open_at_chart_end():
    config = percentage_probability_engine.PercentageProbabilityConfig("15m")

    trades, ignored = percentage_probability_engine._simulate_long_hypothesis(
        times=["t0", "t1", "t2", "t3"],
        highs=[100.1] * 4,
        lows=[99.9] * 4,
        closes=[100.0] * 4,
        candidate_indices=numpy.asarray([1]),
        raw_scores_by_index={1: 0.6},
        probabilities_by_index={1: 0.5},
        last_closed_index=3,
        config=config,
    )

    assert ignored == 0
    assert trades[0]["status"] == "open_at_chart_end"
    assert trades[0]["exit_time"] is None
    assert trades[0]["net_return_pct"] is None


def test_h2_requires_both_early_score_and_volume_confirmation():
    selected = (
        percentage_probability_engine._select_long_hypothesis_candidates(
            numpy.asarray([1, 2, 3, 4]),
            numpy.asarray([0.514, 0.515, 0.53, 0.52]),
            numpy.asarray([0.0, 2.0, 0.9, 1.0, 1.2]),
            score_threshold=0.515,
            minimum_volume_zscore=1.0,
        )
    )

    assert selected.tolist() == [3, 4]


def test_chart_events_are_timestamped_when_the_candle_closes():
    values = percentage_probability_engine._candle_close_display_times(
        numpy.asarray([1_700_000_000, 1_700_000_900]),
        900,
    )

    assert values == ["23-11-14 22:28:20", "23-11-14 22:43:20"]


def test_h2_requires_trade_directions_to_alternate():
    candidates = [
        {"entry_index": index, "direction": direction, "raw_score": 0.6,
         "probability_pct": 50.0}
        for index, direction in (
            (1, "LONG"),
            (3, "LONG"),
            (4, "SHORT"),
            (6, "SHORT"),
            (7, "LONG"),
        )
    ]

    trades, ignored_open, ignored_same = (
        percentage_probability_engine._simulate_alternating_hypothesis(
            times=[f"t{index}" for index in range(9)],
            highs=[100.1, 100.1, 100.1, 100.1, 100.1, 101.1, 100.1, 100.1, 100.1],
            lows=[99.9, 99.9, 98.9, 99.9, 99.9, 99.9, 99.9, 99.9, 98.9],
            closes=[100.0] * 9,
            candidates=candidates,
            last_closed_index=8,
            config=percentage_probability_engine.PercentageProbabilityConfig("15m"),
        )
    )

    assert ignored_open == 0
    assert ignored_same == 2
    assert [trade["entry_index"] for trade in trades] == [1, 4, 7]
    assert [trade["direction"] for trade in trades] == ["LONG", "SHORT", "LONG"]
