import json

import numpy

from octobot.ai_strategy_lab import perfect_map_student as v1
from octobot.ai_strategy_lab import perfect_map_student_v5 as v5
from octobot.ai_strategy_lab import perfect_map_student_v6 as v6


def test_v6_protocol_is_result_free_and_excludes_v5_forward_data():
    protocol = v6.frozen_protocol()
    encoded = json.dumps(protocol, sort_keys=True)

    assert protocol["status"] == "preregistered_design_only"
    assert protocol["orders_authorized"] is False
    assert protocol["paper_orders_authorized"] is False
    assert protocol["parent"]["immutable"] is True
    assert "/v5-paper/binance/v5-paper.sqlite" in (
        protocol["data_policy"][
            "forbidden_for_fit_calibration_and_selection"
        ]
    )
    assert protocol["decision"]["raw_expected_net_floor_pct"] == 0.075
    assert (
        "sqrt(horizon_hours)"
        in protocol["decision"]["time_normalized_score"]
    )
    assert protocol["implementation_policy"]["results_in_this_protocol"] is False
    assert '"profit_factor": 1.1' in encoded
    assert "win_rate_pct" not in encoded


def test_written_protocol_has_matching_hash(tmp_path):
    path = v6.write_protocol(tmp_path)
    persisted = json.loads(path.read_text(encoding="utf-8"))
    expected = v6.frozen_protocol()

    assert persisted["protocol_sha256"] == v6.protocol_sha256(expected)
    assert path.name == "protocol.json"


def test_implementation_manifest_is_result_free_and_hashable(tmp_path):
    path = v6.write_implementation_manifest(tmp_path)
    persisted = json.loads(path.read_text(encoding="utf-8"))
    expected = v6.frozen_implementation_manifest()

    assert persisted["implementation_sha256"] == v6.protocol_sha256(
        expected
    )
    assert persisted["result_free"] is True
    assert persisted["training"]["resampling"]["block_hours"] == 168


def test_ensemble_prefers_better_time_normalized_configuration():
    probabilities = numpy.zeros(
        (5, 1, len(v5.HEAD_SPECS), len(v5.CLASS_NAMES))
    )
    probabilities[..., v5.TIMEOUT_CLASS] = 1.0
    fast = next(
        index
        for index, spec in enumerate(v5.HEAD_SPECS)
        if spec.direction == "LONG"
        and spec.target_profit_pct == 1.0
        and spec.horizon_hours == 1
    )
    slow = next(
        index
        for index, spec in enumerate(v5.HEAD_SPECS)
        if spec.direction == "LONG"
        and spec.target_profit_pct == 1.5
        and spec.horizon_hours == 24
    )
    probabilities[:, 0, fast] = [0.10, 0.40, 0.50]
    probabilities[:, 0, slow] = [0.05, 0.05, 0.90]

    result = v6.ensemble_path_decisions(probabilities)
    labels = v6.decision_labels(result, 0.025)

    assert result["target_index"][0, 0] == 2
    assert result["horizon_index"][0, 0] == 0
    assert numpy.isclose(
        result["expected_net_pct"][0, 0],
        0.5 - 0.1 - v5.ROUND_TRIP_COST_PCT,
    )
    assert numpy.isclose(
        result["expected_net_standard_deviation_pct"][0, 0], 0
    )
    assert labels[0] == v1.LONG


def test_block_resampling_is_deterministic_and_preserves_row_count():
    rows = numpy.arange(100)
    timestamps = numpy.arange(100) * 3600

    first, block_rows = v6._block_resampled_rows(
        rows, timestamps, seed=11, block_hours=24
    )
    second, _ = v6._block_resampled_rows(
        rows, timestamps, seed=11, block_hours=24
    )

    assert block_rows == 24
    assert len(first) == len(rows)
    numpy.testing.assert_array_equal(first, second)


def test_v6_model_round_trip_reproduces_predictions_exactly(tmp_path):
    head_names = tuple(spec.name for spec in v5.HEAD_SPECS)
    primary = v5.NumpyGroupedSoftmaxModel(
        feature_names=("a", "b"),
        head_names=head_names,
        class_names=v5.CLASS_NAMES,
        mean=numpy.zeros(2),
        scale=numpy.ones(2),
        weights=numpy.zeros((2, len(head_names), len(v5.CLASS_NAMES))),
        intercept=numpy.zeros((len(head_names), len(v5.CLASS_NAMES))),
        config={"seed": 1},
    )
    calibrator = v5.NumpyGroupedSoftmaxCalibrator(
        head_names=head_names,
        class_names=v5.CLASS_NAMES,
        weights=numpy.repeat(
            numpy.eye(len(v5.CLASS_NAMES))[None, :, :],
            len(head_names),
            axis=0,
        ),
        intercept=numpy.zeros((len(head_names), len(v5.CLASS_NAMES))),
        config={"seed": 2},
    )
    model = v6.V6Model(
        members=(primary,) * len(v6.ENSEMBLE_SEEDS),
        calibrator=calibrator,
        time_normalized_threshold=0.025,
    )
    features = numpy.asarray([[0.0, 1.0], [2.0, 3.0]])

    v6._save_model(model, tmp_path)
    restored = v6.V6Model.load(tmp_path)

    original = model.predict(features)
    replayed = restored.predict(features)
    assert v6._prediction_replay_max_difference(original, replayed) == 0
