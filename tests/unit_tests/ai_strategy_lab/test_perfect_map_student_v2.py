import numpy

from octobot.ai_strategy_lab import perfect_map_student as v1
from octobot.ai_strategy_lab import perfect_map_student_v2 as v2


def _candles(count=320, start=1_700_000_100):
    close = 100 + numpy.sin(numpy.arange(count) / 17) * 0.2
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


def test_sparse_oracle_keeps_non_overlapping_profitable_entries():
    candles = _candles()
    # Two separated LONG opportunities, each activates and then locks +1%.
    for entry in (100, 210):
        entry_price = candles[entry, 4]
        candles[entry + 1, 1] = entry_price * 1.006
        candles[entry + 1, 2] = entry_price * 1.013
        candles[entry + 1, 3] = entry_price
        candles[entry + 1, 4] = entry_price * 1.006
        candles[entry + 2, 1] = entry_price * 1.012
        candles[entry + 2, 2] = entry_price * 1.014
        candles[entry + 2, 3] = entry_price * 1.009
        candles[entry + 2, 4] = entry_price * 1.012
    dataset = v1.build_dataset(candles)
    start = v1._timestamp_iso(int(dataset.timestamps[0]))[:10]
    end = v1._timestamp_iso(int(dataset.timestamps[-1]))[:10]

    oracle = v2.sparse_oracle(dataset, (start, end))

    selected_rows = numpy.flatnonzero(oracle.labels != v2.WAIT)
    assert len(selected_rows) >= 2
    assert numpy.all(oracle.labels[selected_rows] == v2.LONG)
    assert all(
        left["exit_index"] < right["entry_index"]
        for left, right in zip(
            oracle.selected_trades, oracle.selected_trades[1:]
        )
    )


def test_training_sample_keeps_all_positives_and_is_deterministic():
    labels = numpy.zeros(100, dtype=numpy.int8)
    labels[[5, 25, 75]] = [v2.LONG, v2.SHORT, v2.LONG]
    capable = numpy.zeros(100, dtype=bool)
    capable[10:40] = True
    capable[labels != v2.WAIT] = True
    oracle = v2.SparseOracle(labels, (), capable)
    mask = numpy.ones(100, dtype=bool)

    first = v2.sample_training_rows(oracle, mask)
    second = v2.sample_training_rows(oracle, mask)

    assert numpy.array_equal(first, second)
    assert set((5, 25, 75)).issubset(set(first))
    assert len(first) <= 3 * (
        1
        + v2.HARD_NEGATIVES_PER_POSITIVE
        + v2.BACKGROUND_NEGATIVES_PER_POSITIVE
    )


def test_v2_prediction_uses_sparse_threshold_and_margin():
    long_values = numpy.asarray([0.04, 0.04, 0.005, 0.08])
    short_values = numpy.asarray([0.01, 0.038, 0.05, 0.01])

    labels = v2.prediction_labels(long_values, short_values, 0.03)

    assert labels.tolist() == [v2.LONG, v2.WAIT, v2.SHORT, v2.LONG]


def test_protocol_freezes_sparse_teacher_and_no_promotion():
    protocol = v2.frozen_protocol()

    assert protocol["teacher"]["future_used_for_labels_only"]
    assert protocol["training"]["negative_sampling"] == {
        "hard_target_capable_per_positive": 3,
        "background_wait_per_positive": 3,
        "seed": 20_260_725,
    }
    assert not protocol["evidence_policy"]["promotion_possible"]
