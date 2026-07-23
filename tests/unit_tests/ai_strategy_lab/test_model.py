import numpy

from octobot.ai_strategy_lab import dataset
from octobot.ai_strategy_lab import model


def _research_dataset(rows=240):
    random = numpy.random.RandomState(7)
    features = random.normal(size=(rows, 3)).astype(numpy.float32)
    label = (features[:, 0] + 0.5 * features[:, 1] > 0).astype(numpy.int8)
    timestamp = numpy.arange(rows, dtype=numpy.int64) * 900 + 100_000
    direction = numpy.where(numpy.arange(rows) % 2, 1, -1).astype(numpy.int8)
    return dataset.ResearchDataset(
        features=features,
        feature_names=("a", "b", "c"),
        label=label,
        outcome=numpy.where(
            label,
            dataset.OUTCOME_TARGET,
            dataset.OUTCOME_STOP,
        ).astype(numpy.int8),
        profitable=label.copy(),
        net_return=numpy.where(label, 0.02, -0.01),
        gross_return=numpy.where(label, 0.021, -0.009),
        timestamp=timestamp,
        exit_timestamp=timestamp + 900,
        event_end_timestamp=timestamp + 3600,
        symbol=numpy.asarray(["BTC/USDT:USDT"] * rows),
        direction=direction,
        entry_price=numpy.full(rows, 100.0),
        stop_price=numpy.full(rows, 99.0),
        target_price=numpy.full(rows, 102.0),
        duration_bars=numpy.ones(rows, dtype=numpy.int16),
        mfe_return=numpy.full(rows, 0.02),
        mae_return=numpy.full(rows, -0.01),
    )


def test_logistic_model_is_deterministic_and_round_trips(tmp_path):
    research_dataset = _research_dataset()
    config = model.LogisticConfig(epochs=8, batch_size=32, seed=19)
    first = model.NumpyLogisticModel.fit(
        research_dataset.features,
        research_dataset.label,
        research_dataset.feature_names,
        config,
    )
    second = model.NumpyLogisticModel.fit(
        research_dataset.features,
        research_dataset.label,
        research_dataset.feature_names,
        config,
    )
    first_predictions = first.predict_proba(research_dataset.features)
    assert numpy.array_equal(first.weights, second.weights)
    assert numpy.array_equal(
        first_predictions, second.predict_proba(research_dataset.features)
    )
    path = tmp_path / "model.npz"
    first.save(path)
    loaded = model.NumpyLogisticModel.load(path)
    assert numpy.allclose(
        first_predictions,
        loaded.predict_proba(research_dataset.features),
        atol=1e-12,
    )


def test_gradient_boosting_learns_nonlinear_interaction_and_round_trips(tmp_path):
    random = numpy.random.RandomState(11)
    features = random.normal(size=(1600, 2)).astype(numpy.float32)
    labels = (
        (features[:, 0] > 0) & (features[:, 1] > 0)
    ).astype(numpy.int8)
    config = model.BoostingConfig(
        trees=24,
        max_depth=2,
        bins=12,
        minimum_leaf_rows=20,
        feature_fraction=1.0,
        seed=3,
    )
    fitted = model.NumpyGradientBoostingModel.fit(
        features, labels, ("first", "second"), config
    )
    probabilities = fitted.predict_proba(features)
    assert numpy.mean((probabilities >= 0.5) == labels) > 0.90
    path = tmp_path / "boosting.npz"
    fitted.save(path)
    loaded = model.NumpyGradientBoostingModel.load(path)
    assert numpy.allclose(
        probabilities,
        loaded.predict_proba(features),
        atol=1e-12,
    )


def test_purged_walk_forward_never_overlaps_label_horizon():
    research_dataset = _research_dataset()
    config = model.ValidationConfig(
        folds=3,
        initial_train_fraction=0.5,
        embargo_seconds=3600,
    )
    splits = model.purged_walk_forward_splits(research_dataset, config)
    assert len(splits) == 3
    for split in splits:
        assert numpy.max(
            research_dataset.event_end_timestamp[split.train_indices]
        ) < split.test_start_timestamp
        assert numpy.max(
            research_dataset.timestamp[split.train_indices]
        ) < split.test_start_timestamp - config.embargo_seconds
        assert numpy.min(
            research_dataset.timestamp[split.test_indices]
        ) >= split.test_start_timestamp


def test_selection_uses_one_direction_and_no_symbol_overlap():
    research_dataset = _research_dataset(6)
    # Two candidates at the same event, then another candidate before the exit.
    timestamps = numpy.asarray([100, 100, 500, 500, 1000, 1000])
    research_dataset = dataset.ResearchDataset(
        **{
            **research_dataset.__dict__,
            "timestamp": timestamps,
            "exit_timestamp": timestamps + 600,
            "event_end_timestamp": timestamps + 600,
        }
    )
    indices = numpy.arange(6)
    probabilities = numpy.asarray([0.6, 0.8, 0.9, 0.7, 0.65, 0.75])
    selected = model.select_non_overlapping(
        research_dataset, indices, probabilities, 0.5
    )
    assert selected.tolist() == [1, 5]


def test_training_subsample_handles_already_strided_dataset():
    research_dataset = _research_dataset(12)
    hourly = numpy.arange(12, dtype=numpy.int64) * 3600 + 900
    research_dataset = dataset.ResearchDataset(
        **{
            **research_dataset.__dict__,
            "timestamp": hourly,
            "exit_timestamp": hourly + 900,
            "event_end_timestamp": hourly + 3600,
        }
    )
    selected = model._training_subsample(
        research_dataset,
        numpy.arange(12),
        model.ValidationConfig(training_stride=2),
    )
    assert selected.tolist() == [0, 2, 4, 6, 8, 10]
