import json

import numpy

from octobot.ai_strategy_lab import scalping_strategy_search


def test_result_free_protocol_is_atomic_and_reproducible(tmp_path):
    path = tmp_path / "protocol.json"

    first = scalping_strategy_search.write_or_verify_protocol(path)
    second = scalping_strategy_search.write_or_verify_protocol(path)

    assert first == second
    assert first["results"] is None
    assert first["orders_authorized"] is False
    assert first["paper_orders_authorized"] is False
    assert first["automatic_promotion"] is False
    assert first["frozen_source"]["snapshot_sha256"] == (
        scalping_strategy_search.SNAPSHOT_SHA256
    )
    assert len(first["protocol_sha256"]) == 64
    assert json.loads(path.read_text()) == first


def test_locked_test_cannot_be_used_for_model_selection():
    protocol = scalping_strategy_search.frozen_protocol()

    assert protocol["temporal_validation"]["locked_test_policy"].startswith(
        "do not compute labels"
    )
    assert protocol["models"]["candidates"] == [
        {
            "name": "numpy_logistic",
            "config": {
                "epochs": 12,
                "batch_size": 8192,
                "learning_rate": 0.01,
                "l2": 0.003,
                "seed": 20260827,
            },
        },
        {
            "name": "numpy_gradient_boosting",
            "config": {
                "trees": 32,
                "max_depth": 2,
                "bins": 24,
                "learning_rate": 0.05,
                "l2": 3.0,
                "minimum_leaf_rows": 500,
                "minimum_gain": 0.001,
                "feature_fraction": 0.75,
                "seed": 20260827,
            },
        },
    ]


def _dense_source(length=500):
    search = scalping_strategy_search
    start = search._iso_timestamp(search.SOURCE_START)
    values = search._empty_dense_values(length)
    values["book_event_count"][:] = 10
    values["raw_book_event_count"][:] = 10
    values["first_mid"][:] = 100.0
    values["high_mid"][:] = 100.0
    values["low_mid"][:] = 100.0
    values["last_mid"][:] = 100.0
    values["last_bid"][:] = 100.0
    values["last_ask"][:] = 100.0
    values["spread_bps_sum"][:] = 1.0
    values["spread_bps_max"][:] = 0.1
    for offset in (0, 500):
        values[f"entry_bid_{offset}"][:] = 100.0
        values[f"entry_ask_{offset}"][:] = 100.0
        values[f"entry_ns_{offset}"][:] = (
            (start + numpy.arange(length)) * 1_000_000_000
            + offset * 1_000_000
        )
        for side in ("bid", "ask"):
            values[f"suffix_high_{side}_{offset}"][:] = 100.0
            values[f"suffix_low_{side}_{offset}"][:] = 100.0
    for side in ("bid", "ask"):
        values[f"high_{side}"][:] = 100.0
        values[f"low_{side}"][:] = 100.0
        values[f"prefix_high_{side}_500"][:] = 100.0
        values[f"prefix_low_{side}_500"][:] = 100.0
        values[f"prefix_last_{side}_500"][:] = 100.0
    return search.DenseSource(start, start + length - 1, values)


def test_one_second_tie_is_resolved_as_stop():
    source = _dense_source()
    candidate = numpy.asarray([300], dtype=numpy.int64)
    entry_index = candidate[0] + 1
    event_index = entry_index + 10
    source.values["high_bid"][event_index] = 100.5
    source.values["low_bid"][event_index] = 99.8

    labels, returns, exits = scalping_strategy_search._direction_outcome(
        source,
        candidate,
        direction=1,
        latency_ms=500,
        cost_multiplier=1.0,
    )

    assert labels.tolist() == [0]
    assert numpy.isclose(returns[0], -0.0024)
    assert exits[0] == source.start_second + event_index


def test_target_and_timeout_include_frozen_costs():
    source = _dense_source()
    candidates = numpy.asarray([300], dtype=numpy.int64)
    first_entry = candidates[0] + 1
    source.values["high_bid"][first_entry + 10] = 100.5

    target_labels, target_returns, _ = scalping_strategy_search._direction_outcome(
        source,
        candidates,
        direction=1,
        latency_ms=500,
        cost_multiplier=1.0,
    )
    source.values["high_bid"][first_entry + 10] = 100.0
    timeout_labels, timeout_returns, _ = (
        scalping_strategy_search._direction_outcome(
            source,
            candidates,
            direction=1,
            latency_ms=500,
            cost_multiplier=1.0,
        )
    )

    assert target_labels.tolist() == [1]
    assert timeout_labels.tolist() == [0]
    assert numpy.isclose(target_returns[0], 0.0026)
    assert numpy.isclose(timeout_returns[0], -0.0014)


def test_dataset_round_trip_preserves_protocol_and_locked_boundary(tmp_path):
    row_count = 3
    timestamps = numpy.asarray(
        [
            scalping_strategy_search._iso_timestamp(
                scalping_strategy_search.SOURCE_START
            )
            + value * 5
            for value in range(row_count)
        ],
        dtype=numpy.int64,
    )
    zeros = numpy.zeros(row_count, dtype=numpy.float32)
    exits = timestamps + 10
    dataset = scalping_strategy_search.ScalpingResearchDataset(
        timestamps=timestamps,
        features=numpy.zeros(
            (row_count, len(scalping_strategy_search.FEATURE_NAMES)),
            dtype=numpy.float32,
        ),
        primary_long_label=numpy.asarray([0, 1, 0], dtype=numpy.uint8),
        primary_short_label=numpy.asarray([1, 0, 0], dtype=numpy.uint8),
        primary_long_return=zeros,
        primary_short_return=zeros,
        primary_long_exit=exits,
        primary_short_exit=exits,
        stress_long_return=zeros,
        stress_short_return=zeros,
        stress_long_exit=exits,
        stress_short_exit=exits,
    )
    path = tmp_path / "dataset.npz"
    artifact = dataset.save(path)

    loaded = scalping_strategy_search.ScalpingResearchDataset.load(
        path, expected_sha256=artifact["sha256"]
    )

    assert numpy.array_equal(loaded.timestamps, timestamps)
    assert numpy.array_equal(loaded.features, dataset.features)
