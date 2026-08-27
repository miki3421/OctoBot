import json

import numpy
import pytest

from octobot.ai_strategy_lab import microstructure_regime_v1 as regime
from octobot.ai_strategy_lab import scalping_strategy_search as scalping_v1


def _dataset(rows=4):
    start = regime._iso_timestamp(regime.PRETEST_END) - (rows + 10) * 900
    timestamps = start + numpy.arange(rows, dtype=numpy.int64) * 900
    shape = (rows, len(regime.HORIZONS_SECONDS))
    return regime.RegimeDataset(
        timestamps=timestamps,
        common_features=numpy.zeros(
            (rows, len(regime.COMMON_FEATURE_NAMES)), dtype=numpy.float32
        ),
        price_features=numpy.zeros(
            (rows, len(regime.PRICE_FEATURE_NAMES)), dtype=numpy.float32
        ),
        book_features=numpy.zeros(
            (rows, len(regime.BOOK_FEATURE_NAMES)), dtype=numpy.float32
        ),
        long_label=numpy.zeros(shape, dtype=numpy.uint8),
        short_label=numpy.zeros(shape, dtype=numpy.uint8),
        long_return=numpy.zeros(shape, dtype=numpy.float32),
        short_return=numpy.zeros(shape, dtype=numpy.float32),
        long_stress_return=numpy.zeros(shape, dtype=numpy.float32),
        short_stress_return=numpy.zeros(shape, dtype=numpy.float32),
        long_exit=numpy.tile(
            timestamps[:, None] + numpy.asarray(regime.HORIZONS_SECONDS),
            (1, 1),
        ),
        short_exit=numpy.tile(
            timestamps[:, None] + numpy.asarray(regime.HORIZONS_SECONDS),
            (1, 1),
        ),
        long_mfe_bps=numpy.zeros(shape, dtype=numpy.float32),
        short_mfe_bps=numpy.zeros(shape, dtype=numpy.float32),
        long_mae_bps=numpy.zeros(shape, dtype=numpy.float32),
        short_mae_bps=numpy.zeros(shape, dtype=numpy.float32),
    )


def test_protocol_is_result_free_and_orderless(tmp_path):
    protocol_path = tmp_path / "protocol.json"
    protocol = regime.write_or_verify_protocol(protocol_path)

    assert protocol["results"] is None
    assert protocol["orders_authorized"] is False
    assert protocol["paper_orders_authorized"] is False
    assert protocol["automatic_promotion"] is False
    assert protocol["primary_label"]["horizon_seconds"] == 4 * 3600
    assert protocol["decisions"]["technical_indicators"][
        "parameter_search"
    ] is False
    assert "i15m_rsi_centered" in regime.PRICE_FEATURE_NAMES
    assert protocol["protocol_sha256"] == regime._json_hash(
        regime.frozen_protocol()
    )

    protocol["orders_authorized"] = True
    protocol_path.write_text(json.dumps(protocol), encoding="utf-8")
    with pytest.raises(ValueError, match="protocol differs"):
        regime.write_or_verify_protocol(protocol_path)


def test_directional_feature_groups_flip_only_directional_columns():
    dataset = _dataset(2)
    dataset.price_features[0] = numpy.arange(
        len(regime.PRICE_FEATURE_NAMES), dtype=numpy.float32
    )
    dataset.book_features[0] = numpy.arange(
        len(regime.BOOK_FEATURE_NAMES), dtype=numpy.float32
    )
    indices = numpy.asarray([0], dtype=numpy.int64)

    long_values, long_names = dataset.directional_features(
        indices, 1, "combined"
    )
    short_values, short_names = dataset.directional_features(
        indices, -1, "combined"
    )

    assert long_names == short_names
    assert len(long_names) == (
        len(regime.COMMON_FEATURE_NAMES)
        + len(regime.PRICE_FEATURE_NAMES)
        + len(regime.BOOK_FEATURE_NAMES)
    )
    directional = numpy.concatenate(
        (
            numpy.zeros(len(regime.COMMON_FEATURE_NAMES), dtype=bool),
            regime.PRICE_DIRECTIONAL_MASK,
            regime.BOOK_DIRECTIONAL_MASK,
        )
    )
    assert numpy.array_equal(short_values[:, directional], -long_values[:, directional])
    assert numpy.array_equal(
        short_values[:, ~directional], long_values[:, ~directional]
    )


def test_same_second_target_and_stop_uses_adverse_tie(monkeypatch):
    monkeypatch.setattr(regime, "HORIZONS_SECONDS", (2, 4, 8))
    length = 20
    values = scalping_v1._empty_dense_values(length)
    for name in (
        "last_bid",
        "low_bid",
        "high_bid",
        "prefix_last_bid_500",
        "prefix_low_bid_500",
        "prefix_high_bid_500",
        "suffix_low_bid_500",
        "suffix_high_bid_500",
    ):
        values[name][:] = 99.9
    for name in (
        "last_ask",
        "low_ask",
        "high_ask",
        "prefix_last_ask_500",
        "prefix_low_ask_500",
        "prefix_high_ask_500",
        "suffix_low_ask_500",
        "suffix_high_ask_500",
    ):
        values[name][:] = 100.1
    values["entry_bid_500"][:] = 99.9
    values["entry_ask_500"][:] = 100.1
    values["entry_ns_500"][:] = (
        numpy.arange(length, dtype=numpy.int64) * 1_000_000_000
    )
    candidate = numpy.asarray([1], dtype=numpy.int64)
    first_full_second = candidate[0] + 2
    values["high_bid"][first_full_second] = 101.2
    values["low_bid"][first_full_second] = 99.0
    source = scalping_v1.DenseSource(0, length - 1, values)

    outcomes = regime._direction_outcomes(source, candidate, 1)

    assert outcomes["label"][0, 0] == 0
    assert outcomes["return"][0, 0] == pytest.approx(-0.0114)
    assert outcomes["exit"][0, 0] == 3


def test_probability_metrics_accept_fold_specific_constants():
    labels = numpy.asarray([0, 0, 1, 1], dtype=numpy.uint8)
    probabilities = numpy.asarray([0.1, 0.2, 0.8, 0.9])
    constants = numpy.asarray([0.25, 0.25, 0.75, 0.75])

    metrics = regime._probability_metrics(
        labels, probabilities, constants
    )

    assert metrics["auc"] == pytest.approx(1.0)
    assert metrics["brier"] < metrics["constant_brier"]
    assert metrics["log_loss"] < metrics["constant_log_loss"]


def test_discovery_detects_incremental_synthetic_book_signal(tmp_path):
    rows = 400
    dataset = _dataset(rows)
    signal = numpy.where(numpy.arange(rows) % 2 == 0, 4.0, -4.0)
    directional_index = int(
        numpy.flatnonzero(regime.BOOK_DIRECTIONAL_MASK)[0]
    )
    dataset.book_features[:, directional_index] = signal
    primary = regime.HORIZONS_SECONDS.index(
        regime.PRIMARY_HORIZON_SECONDS
    )
    dataset.long_label[:, primary] = signal > 0
    dataset.short_label[:, primary] = signal < 0
    dataset.long_return[:, primary] = numpy.where(
        signal > 0, 0.0086, -0.0114
    )
    dataset.short_return[:, primary] = numpy.where(
        signal < 0, 0.0086, -0.0114
    )
    dataset.long_stress_return[:, primary] = numpy.where(
        signal > 0, 0.0072, -0.0128
    )
    dataset.short_stress_return[:, primary] = numpy.where(
        signal < 0, 0.0072, -0.0128
    )
    dataset.long_exit[:, primary] = dataset.timestamps + 3600
    dataset.short_exit[:, primary] = dataset.timestamps + 3600
    dataset.validate()

    protocol_path = tmp_path / "protocol.json"
    protocol = regime.write_or_verify_protocol(protocol_path)
    dataset_path = tmp_path / "dataset.npz"
    artifact = dataset.save(dataset_path, protocol["protocol_sha256"])
    manifest_path = tmp_path / "dataset.manifest.json"
    manifest_path.write_text(
        json.dumps(
            {
                "locked_test_materialized": False,
                "protocol_sha256": protocol["protocol_sha256"],
                "artifact": artifact,
            }
        ),
        encoding="utf-8",
    )

    report = regime.evaluate_discovery(
        protocol_value=protocol_path,
        dataset_value=dataset_path,
        dataset_manifest_value=manifest_path,
        output_root_value=tmp_path / "experiments",
    )

    assert report["diagnostic_advancement_gate"]["passed"] is True
    assert report["models"]["combined"]["probability"]["auc"] > 0.99
    assert report["models"]["price_only"]["probability"]["auc"] == pytest.approx(0.5)
    assert report["orders_authorized"] is False
    assert report["locked_historical_block"]["materialized"] is False
