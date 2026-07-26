import numpy

from octobot.ai_strategy_lab import model as model_module
from octobot.ai_strategy_lab import percentage_probability_engine
from octobot.ai_strategy_lab import perfect_map_student_v4 as v4


def test_softmax_probabilities_sum_to_one_and_round_trip(tmp_path):
    generator = numpy.random.default_rng(7)
    features = generator.normal(size=(120, 4))
    labels = numpy.tile(numpy.asarray([0, 1, 2]), 40)
    config = {
        "epochs": 3,
        "batch_size": 32,
        "learning_rate": 0.01,
        "l2": 0.001,
        "seed": 9,
    }
    model = v4.NumpySoftmaxModel.fit(
        features,
        labels,
        ("a", "b", "c", "d"),
        v4.CLASS_NAMES,
        config,
    )
    probabilities = model.predict_proba(features[:10])
    path = tmp_path / "softmax.npz"
    model.save(path)
    loaded = v4.NumpySoftmaxModel.load(path)

    assert numpy.allclose(numpy.sum(probabilities, axis=1), 1.0)
    assert numpy.allclose(
        probabilities, loaded.predict_proba(features[:10])
    )


def test_v4_model_round_trip_preserves_every_prediction(tmp_path):
    generator = numpy.random.default_rng(19)
    features = generator.normal(size=(120, 4))
    classes = numpy.tile(numpy.asarray([0, 1, 2]), 40)
    softmax_config = {
        "epochs": 3,
        "batch_size": 32,
        "learning_rate": 0.01,
        "l2": 0.001,
        "seed": 20,
    }
    feature_names = ("a", "b", "c", "d")
    primary = v4.NumpySoftmaxModel.fit(
        features,
        classes,
        feature_names,
        v4.CLASS_NAMES,
        softmax_config,
    )
    calibration = v4.NumpySoftmaxModel.fit(
        primary.predict_logits(features),
        classes,
        ("wait_logit", "long_logit", "short_logit"),
        v4.CLASS_NAMES,
        {**softmax_config, "seed": 21},
    )
    auxiliary_models = {}
    auxiliary_calibrators = {}
    auxiliary_base_rates = {}
    for offset, name in enumerate(
        ("long_quality", "short_quality", "long_fast", "short_fast")
    ):
        labels = numpy.roll(classes != 0, offset).astype(numpy.int8)
        auxiliary_models[name] = model_module.NumpyLogisticModel.fit(
            features,
            labels,
            feature_names,
            model_module.LogisticConfig(
                epochs=3,
                batch_size=32,
                learning_rate=0.01,
                l2=0.001,
                seed=22 + offset,
            ),
        )
        auxiliary_calibrators[name] = (
            percentage_probability_engine.QuantileIsotonicCalibrator.fit(
                auxiliary_models[name].predict_proba(features),
                labels,
                maximum_bins=6,
                minimum_rows_per_bin=20,
            )
        )
        auxiliary_base_rates[name] = float(numpy.mean(labels))
    model = v4.V4Model(
        primary_model=primary,
        calibration_model=calibration,
        auxiliary_models=auxiliary_models,
        auxiliary_calibrators=auxiliary_calibrators,
        auxiliary_base_rates=auxiliary_base_rates,
        threshold=0.2,
    )
    directory = tmp_path / "model"
    v4._save_model(model, directory)

    original = model.predict(features)
    restored = v4.V4Model.load(directory)

    assert restored.threshold == model.threshold
    restored_predictions = restored.predict(features)
    for name, values in original.items():
        numpy.testing.assert_allclose(restored_predictions[name], values)


def test_base_rate_normalization_preserves_directional_symmetry():
    primary = numpy.asarray([[0.8, 0.1, 0.1]])
    heads = {
        "long_quality": numpy.asarray([0.4]),
        "short_quality": numpy.asarray([0.5]),
        "long_fast": numpy.asarray([0.1]),
        "short_fast": numpy.asarray([0.2]),
    }
    base_rates = {
        "long_quality": 0.4,
        "short_quality": 0.5,
        "long_fast": 0.1,
        "short_fast": 0.2,
    }

    long_score, short_score = v4.normalized_scores(
        primary, heads, base_rates
    )

    assert numpy.allclose(long_score, short_score)
    assert numpy.allclose(long_score, [0.1])


def test_auxiliary_lift_can_favor_one_direction_without_raw_rate_bias():
    primary = numpy.asarray([[0.8, 0.1, 0.1]])
    heads = {
        "long_quality": numpy.asarray([0.8]),
        "short_quality": numpy.asarray([0.5]),
        "long_fast": numpy.asarray([0.2]),
        "short_fast": numpy.asarray([0.2]),
    }
    base_rates = {
        "long_quality": 0.4,
        "short_quality": 0.5,
        "long_fast": 0.1,
        "short_fast": 0.2,
    }

    long_score, short_score = v4.normalized_scores(
        primary, heads, base_rates
    )

    assert long_score[0] > short_score[0]


def test_protocol_freezes_joint_model_and_requires_both_directions():
    protocol = v4.frozen_protocol()

    assert protocol["target"]["classes"] == list(v4.CLASS_NAMES)
    assert (
        protocol["primary_model"]["joint_calibration"]["type"]
        == "softmax_on_primary_logits"
    )
    assert protocol["decision"]["selection_gate"][
        "at_least_one_trade_per_direction"
    ]
    assert not protocol["evidence_policy"]["promotion_possible"]
