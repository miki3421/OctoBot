import numpy

from octobot.ai_strategy_lab import perfect_map_student as v1
from octobot.ai_strategy_lab import perfect_map_student_v2 as v2
from octobot.ai_strategy_lab import perfect_map_student_v3 as v3


def test_zone_expands_before_entry_and_stops_after_previous_exit():
    timestamps = 1_700_000_000 + numpy.arange(30) * 900
    dataset = v1.StudentDataset(
        features=numpy.zeros((30, len(v1.student_feature_names()))),
        labels=numpy.zeros(30, dtype=numpy.int8),
        timestamps=timestamps + 900,
        candle_indices=numpy.arange(30),
        candles=numpy.column_stack(
            (
                timestamps,
                numpy.full((30, 4), 100.0),
                numpy.ones(30),
            )
        ),
    )
    trades = (
        {
            "entry_index": 10,
            "exit_index": 15,
            "label_direction": v3.LONG,
        },
        {
            "entry_index": 18,
            "exit_index": 20,
            "label_direction": v3.SHORT,
        },
    )
    oracle = v2.SparseOracle(
        labels=numpy.zeros(30, dtype=numpy.int8),
        selected_trades=trades,
        target_capable=numpy.zeros(30, dtype=bool),
    )
    start = v1._timestamp_iso(int(dataset.timestamps[0]))[:10]
    end = v1._timestamp_iso(int(dataset.timestamps[-1]))[:10]

    labels = v3.anticipatory_zone_labels(dataset, oracle, (start, end))

    assert numpy.all(labels[6:11] == v3.LONG)
    # Nominal SHORT zone starts at 14, but the prior oracle trade exits at 15.
    assert numpy.all(labels[16:19] == v3.SHORT)
    assert labels[14] == v3.WAIT
    assert labels[15] == v3.WAIT


def test_decision_score_uses_frozen_multitask_weights():
    heads = {
        "long_zone": numpy.asarray([0.4]),
        "short_zone": numpy.asarray([0.1]),
        "long_quality": numpy.asarray([0.6]),
        "short_quality": numpy.asarray([0.2]),
        "long_fast": numpy.asarray([0.2]),
        "short_fast": numpy.asarray([0.1]),
    }

    long_score, short_score = v3.decision_scores(heads)

    assert numpy.allclose(long_score, [0.43])
    assert numpy.allclose(short_score, [0.13])


def test_path_targets_distinguish_fast_from_slow_success():
    count = 180
    close = numpy.full(count, 100.0)
    candles = numpy.column_stack(
        (
            1_700_000_000 + numpy.arange(count) * 900,
            close,
            close + 0.1,
            close - 0.1,
            close,
            numpy.ones(count),
        )
    )
    candles[11, 2] = 101.3
    candles[41, 2] = 101.3
    dataset = v1.StudentDataset(
        features=numpy.zeros((2, len(v1.student_feature_names()))),
        labels=numpy.zeros(2, dtype=numpy.int8),
        timestamps=numpy.asarray(
            [candles[10, 0] + 900, candles[20, 0] + 900],
            dtype=numpy.int64,
        ),
        candle_indices=numpy.asarray([10, 20]),
        candles=candles,
    )

    targets = v3.path_targets(dataset)

    assert targets.long_quality.tolist() == [1, 1]
    assert targets.long_fast.tolist() == [1, 0]


def test_protocol_freezes_zone_heads_and_no_promotion():
    protocol = v3.frozen_protocol()

    assert protocol["primary_target"]["zone_lead_minutes"] == 60
    assert protocol["decision"]["weights"] == {
        "zone": 0.55,
        "quality": 0.30,
        "fast": 0.15,
    }
    assert not protocol["evidence_policy"]["promotion_possible"]
