import numpy

from octobot.ai_strategy_lab import perfect_map_student


def _candles(count=240, start=1_700_000_100):
    close = numpy.linspace(100.0, 101.0, count)
    return numpy.column_stack(
        (
            start + numpy.arange(count) * 900,
            close,
            close + 0.1,
            close - 0.1,
            close,
            numpy.linspace(10.0, 20.0, count),
        )
    )


def test_sequence_feature_at_decision_does_not_change_with_future_candle():
    candles = _candles()
    original, names = perfect_map_student.sequence_features(candles)
    changed = candles.copy()
    changed[150, 1:6] *= 2

    updated, updated_names = perfect_map_student.sequence_features(changed)

    assert names == updated_names == perfect_map_student.student_feature_names()
    assert numpy.allclose(original[149], updated[149], equal_nan=True)
    assert not numpy.allclose(original[150], updated[150], equal_nan=True)


def test_perfect_label_same_candle_stop_beats_activation():
    candles = _candles()
    entry = 100
    entry_price = candles[entry, 4]
    candles[entry + 1, 2] = entry_price * 1.02
    candles[entry + 1, 3] = entry_price * 0.98

    labels = perfect_map_student.perfect_map_labels(candles)

    assert labels[entry] == perfect_map_student.WAIT


def test_perfect_label_uses_first_successful_direction():
    candles = _candles()
    entry = 100
    entry_price = candles[entry, 4]
    candles[entry + 1, 2] = entry_price * 1.013
    candles[entry + 1, 3] = entry_price * 0.999

    labels = perfect_map_student.perfect_map_labels(candles)

    assert labels[entry] == perfect_map_student.LONG


def test_prediction_requires_threshold_and_direction_margin():
    long_values = numpy.asarray([0.5, 0.5, 0.2, 0.6])
    short_values = numpy.asarray([0.2, 0.48, 0.6, 0.2])

    labels = perfect_map_student._prediction_labels(
        long_values, short_values, 0.5
    )

    assert labels.tolist() == [
        perfect_map_student.LONG,
        perfect_map_student.WAIT,
        perfect_map_student.SHORT,
        perfect_map_student.LONG,
    ]


def test_protocol_is_research_only_and_has_locked_split():
    protocol = perfect_map_student.frozen_protocol()

    assert protocol["research_only"]
    assert not protocol["orders_authorized"]
    assert protocol["target"]["future_used_for_labels_only"]
    assert protocol["splits"]["locked_test"] == (
        "2025-07-02",
        "2025-12-30",
    )


def test_dataset_keeps_global_indices_after_gap():
    first = _candles(count=220)
    second = _candles(count=220, start=int(first[-1, 0]) + 1800)
    candles = numpy.concatenate((first, second))

    dataset = perfect_map_student.build_dataset(candles)
    second_rows = dataset.timestamps >= int(second[0, 0]) + 900

    assert numpy.any(second_rows)
    assert numpy.min(dataset.candle_indices[second_rows]) >= len(first)
