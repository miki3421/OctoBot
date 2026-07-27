import json

import numpy

from octobot.ai_strategy_lab import model as model_module
from octobot.ai_strategy_lab import percentage_probability_engine
from octobot.ai_strategy_lab import perfect_map_precursor


def _candles(count=900, start=1_700_006_400):
    close = numpy.linspace(100.0, 100.5, count)
    return numpy.column_stack(
        (
            start + numpy.arange(count) * 900,
            close,
            close + 0.05,
            close - 0.05,
            close,
            numpy.linspace(10.0, 20.0, count),
        )
    )


def test_protocol_is_result_free_and_freezes_late_long_target():
    protocol = perfect_map_precursor.frozen_protocol()
    encoded = json.dumps(protocol, sort_keys=True)

    assert protocol["status"] == "preregistered_design_only"
    assert protocol["scope"]["direction"] == "LONG_only"
    assert protocol["target"]["minimum_offset"] == 18
    assert protocol["target"]["maximum_offset"] == 22
    assert protocol["target"]["same_candle_policy"] == "stop_wins"
    assert protocol["orders_authorized"] is False
    assert protocol["paper_orders_authorized"] is False
    assert protocol["implementation_policy"]["results_in_this_protocol"] is False
    assert "win_rate_pct" not in encoded


def test_written_protocol_has_matching_hash(tmp_path):
    path = perfect_map_precursor.write_protocol(tmp_path)
    payload = json.loads(path.read_text(encoding="utf-8"))

    assert payload["protocol_sha256"] == (
        perfect_map_precursor.protocol_sha256(
            perfect_map_precursor.frozen_protocol()
        )
    )


def test_late_label_accepts_only_first_target_touch_at_offsets_18_to_22():
    candles = _candles(count=180)
    early_entry = 20
    late_entry = 80
    candles[early_entry + 17, 2] = candles[early_entry, 4] * 1.013
    candles[late_entry + 20, 2] = candles[late_entry, 4] * 1.013

    labels, offsets = perfect_map_precursor.late_long_labels(candles)

    assert labels[early_entry] == 0
    assert offsets[early_entry] == 17
    assert labels[late_entry] == 1
    assert offsets[late_entry] == 20


def test_late_label_same_candle_stop_beats_target():
    candles = _candles(count=180)
    entry = 80
    entry_price = candles[entry, 4]
    candles[entry + 20, 2] = entry_price * 1.013
    candles[entry + 20, 3] = entry_price * 0.989

    labels, offsets = perfect_map_precursor.late_long_labels(candles)

    assert labels[entry] == 0
    assert offsets[entry] == -1


def test_feature_at_decision_does_not_change_when_future_candle_changes():
    candles = _candles()
    original, names = perfect_map_precursor.causal_features(candles)
    changed = candles.copy()
    changed[700, 1:6] *= 2

    updated, updated_names = perfect_map_precursor.causal_features(changed)

    assert names == updated_names == (
        perfect_map_precursor.precursor_feature_names()
    )
    assert numpy.allclose(original[699], updated[699], equal_nan=True)
    assert not numpy.allclose(original[700], updated[700], equal_nan=True)


def test_partial_higher_time_frame_candle_is_not_aggregated():
    candles = _candles(count=5)
    original = perfect_map_precursor._aggregate_complete_candles(
        candles, 3600
    )
    changed = candles.copy()
    changed[4, 1:6] *= 3
    updated = perfect_map_precursor._aggregate_complete_candles(
        changed, 3600
    )

    assert len(original) == len(updated) == 1
    numpy.testing.assert_array_equal(original, updated)


def test_model_round_trip_reproduces_predictions_exactly(tmp_path):
    feature_names = perfect_map_precursor.precursor_feature_names()
    count = len(feature_names)
    base_model = model_module.NumpyLogisticModel(
        feature_names=feature_names,
        mean=numpy.zeros(count),
        scale=numpy.ones(count),
        weights=numpy.linspace(-0.1, 0.1, count),
        intercept=0.2,
        config=model_module.LogisticConfig(seed=7),
    )
    calibrator = percentage_probability_engine.QuantileIsotonicCalibrator(
        upper_score=numpy.asarray([0.4, 0.6, 1.0]),
        values=numpy.asarray([0.1, 0.3, 0.8]),
    )
    model = perfect_map_precursor.PrecursorModel(
        base_model=base_model,
        calibrator=calibrator,
        raw_score_threshold=0.6,
        threshold_quantile=0.99,
    )
    features = numpy.zeros((3, count))

    perfect_map_precursor._save_model(model, tmp_path)
    restored = perfect_map_precursor.load_model(tmp_path)

    original = model.predict(features)
    replayed = restored.predict(features)
    for expected, actual in zip(original, replayed):
        numpy.testing.assert_array_equal(expected, actual)
