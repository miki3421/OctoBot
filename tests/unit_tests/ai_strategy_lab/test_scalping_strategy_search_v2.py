import numpy

from octobot.ai_strategy_lab import scalping_strategy_search as v1
from octobot.ai_strategy_lab import scalping_strategy_search_v2


def test_v2_protocol_is_result_free_and_keeps_locked_test_sealed(tmp_path):
    path = tmp_path / "protocol.json"

    protocol = scalping_strategy_search_v2.write_or_verify_protocol(path)

    assert protocol["results"] is None
    assert protocol["orders_authorized"] is False
    assert protocol["paper_orders_authorized"] is False
    assert protocol["automatic_promotion"] is False
    assert protocol["frozen_source"][
        "locked_test_not_materialized_at_preregistration"
    ] is True
    assert protocol["candidate_family"]["configurations"] == [
        {
            "name": "balanced_5m",
            "target_bps": 40,
            "stop_bps": 20,
            "horizon_seconds": 300,
        },
        {
            "name": "wide_15m",
            "target_bps": 60,
            "stop_bps": 30,
            "horizon_seconds": 900,
        },
    ]


def test_v2_declares_diagnostic_reuse_of_the_middle_block():
    protocol = scalping_strategy_search_v2.frozen_protocol()

    assert protocol["validation"][
        "diagnostic_confirmation_is_not_pristine"
    ] is True
    assert protocol["models"]["selection_candidates"] == 16


def _dense_source(length=1_300):
    start = v1._iso_timestamp(v1.SOURCE_START)
    values = v1._empty_dense_values(length)
    values["book_event_count"][:] = 10
    values["raw_book_event_count"][:] = 10
    for name in ("first_mid", "high_mid", "low_mid", "last_mid"):
        values[name][:] = 100.0
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
    return v1.DenseSource(start, start + length - 1, values)


def test_v2_net_positive_label_and_costs():
    source = _dense_source()
    candidate = numpy.asarray([300], dtype=numpy.int64)
    entry = candidate[0] + 1
    source.values["high_bid"][entry + 10] = 100.5

    label, returns, _ = scalping_strategy_search_v2._direction_outcome(
        source,
        candidate,
        direction=1,
        latency_ms=500,
        cost_multiplier=1.0,
        configuration=scalping_strategy_search_v2.CONFIGURATIONS[0],
    )

    assert label.tolist() == [1]
    assert numpy.isclose(returns[0], 0.0026)


def test_v2_dataset_round_trip(tmp_path):
    rows = 3
    configurations = len(scalping_strategy_search_v2.CONFIGURATIONS)
    timestamps = numpy.asarray(
        [v1._iso_timestamp(v1.SOURCE_START) + index * 15 for index in range(rows)]
    )
    returns = numpy.zeros((rows, configurations), dtype=numpy.float32)
    exits = numpy.tile((timestamps + 10)[:, None], (1, configurations))
    labels = numpy.zeros((rows, configurations), dtype=numpy.uint8)
    dataset = scalping_strategy_search_v2.ScalpingV2Dataset(
        timestamps=timestamps,
        features=numpy.zeros((rows, len(v1.FEATURE_NAMES)), dtype=numpy.float32),
        primary_long_label=labels,
        primary_short_label=labels,
        primary_long_return=returns,
        primary_short_return=returns,
        primary_long_exit=exits,
        primary_short_exit=exits,
        stress_long_return=returns,
        stress_short_return=returns,
        stress_long_exit=exits,
        stress_short_exit=exits,
    )
    path = tmp_path / "v2.npz"
    artifact = dataset.save(path)

    loaded = scalping_strategy_search_v2.ScalpingV2Dataset.load(
        path, expected_sha256=artifact["sha256"]
    )

    assert numpy.array_equal(loaded.timestamps, timestamps)
    assert numpy.array_equal(loaded.features, dataset.features)
