import numpy

from octobot.ai_strategy_lab import perfect_map_student as v1
from octobot.ai_strategy_lab import perfect_map_student_v5 as v5


def _config(seed=1):
    return {
        "epochs": 3,
        "batch_size": 16,
        "learning_rate": 0.01,
        "l2": 0.001,
        "seed": seed,
    }


def test_grouped_softmax_round_trip(tmp_path):
    generator = numpy.random.default_rng(5)
    features = generator.normal(size=(90, 4))
    base = numpy.tile(numpy.asarray([0, 1, 2]), 30)
    labels = numpy.column_stack((base, numpy.roll(base, 1)))
    model = v5.NumpyGroupedSoftmaxModel.fit(
        features,
        labels,
        ("a", "b", "c", "d"),
        ("first", "second"),
        v5.CLASS_NAMES,
        _config(),
    )
    probabilities = model.predict_proba(features)
    path = tmp_path / "grouped.npz"
    model.save(path)
    restored = v5.NumpyGroupedSoftmaxModel.load(path)

    assert probabilities.shape == (90, 2, 3)
    numpy.testing.assert_allclose(
        numpy.sum(probabilities, axis=2), 1.0
    )
    numpy.testing.assert_allclose(
        restored.predict_proba(features), probabilities
    )


def test_grouped_calibrator_round_trip(tmp_path):
    generator = numpy.random.default_rng(7)
    logits = generator.normal(size=(90, 2, 3))
    base = numpy.tile(numpy.asarray([0, 1, 2]), 30)
    labels = numpy.column_stack((base, numpy.roll(base, 2)))
    calibrator = v5.NumpyGroupedSoftmaxCalibrator.fit(
        logits,
        labels,
        ("first", "second"),
        v5.CLASS_NAMES,
        _config(seed=2),
    )
    path = tmp_path / "calibrator.npz"
    calibrator.save(path)
    restored = v5.NumpyGroupedSoftmaxCalibrator.load(path)

    numpy.testing.assert_allclose(
        restored.predict_proba(logits),
        calibrator.predict_proba(logits),
    )


def test_future_path_outcomes_give_same_candle_stop_precedence():
    candles = numpy.zeros((100, 6), dtype=float)
    candles[:, 0] = numpy.arange(100) * v1.CANDLE_SECONDS
    candles[:, 1:5] = 100.0
    candles[:, 5] = 1.0
    candles[1, 2] = 102.0
    candles[1, 3] = 98.0
    dataset = v1.StudentDataset(
        features=numpy.zeros((1, 1), dtype=numpy.float32),
        labels=numpy.zeros(1, dtype=numpy.int8),
        timestamps=numpy.asarray([v1.CANDLE_SECONDS]),
        candle_indices=numpy.asarray([0]),
        candles=candles,
    )

    outcomes = v5.future_path_outcomes(dataset)

    assert outcomes.shape == (1, len(v5.HEAD_SPECS))
    assert numpy.all(outcomes == v5.STOP_CLASS)


def test_probability_projection_enforces_path_relationships():
    generator = numpy.random.default_rng(11)
    raw = generator.uniform(size=(3, len(v5.HEAD_SPECS), 3))
    raw /= numpy.sum(raw, axis=2, keepdims=True)

    projected = v5.coherent_probability_surface(raw)
    surface = projected.reshape(
        3,
        len(v5.DIRECTIONS),
        len(v5.TARGET_PROFITS_PCT),
        len(v5.HORIZON_HOURS),
        len(v5.CLASS_NAMES),
    )
    target = surface[..., v5.TARGET_CLASS]

    numpy.testing.assert_allclose(numpy.sum(projected, axis=2), 1.0)
    assert numpy.all(numpy.diff(target, axis=2) <= 1e-12)
    assert numpy.all(numpy.diff(target, axis=3) >= -1e-12)


def test_path_decision_maximizes_expected_net_return():
    probabilities = numpy.zeros((1, len(v5.HEAD_SPECS), 3))
    probabilities[..., v5.TIMEOUT_CLASS] = 1.0
    head = next(
        index
        for index, spec in enumerate(v5.HEAD_SPECS)
        if spec.direction == "LONG"
        and spec.target_profit_pct == 1.5
        and spec.horizon_hours == 4
    )
    probabilities[0, head] = [0.1, 0.1, 0.8]

    decisions = v5.path_decisions(probabilities)

    assert decisions["target_index"][0, 0] == 4
    assert decisions["horizon_index"][0, 0] == 2
    assert numpy.isclose(
        decisions["expected_net_pct"][0, 0],
        0.8 * 1.5 - 0.1 - v5.ROUND_TRIP_COST_PCT,
    )


def test_protocol_freezes_dynamic_path_surface_without_promotion():
    protocol = v5.frozen_protocol()

    assert protocol["model"]["heads"] == 50
    assert protocol["prediction_target"]["classes"] == list(
        v5.CLASS_NAMES
    )
    assert protocol["simulation"][
        "dynamic_protected_profit_and_horizon"
    ]
    assert not protocol["evidence_policy"]["promotion_possible"]
