import json

import numpy
import pytest

from octobot.ai_strategy_lab import microstructure_regime_v1 as v1
from octobot.ai_strategy_lab import microstructure_regime_v2 as regime


def _dataset(rows=4):
    start = v1._iso_timestamp(v1.PRETEST_END) - (rows + 40) * 900
    timestamps = start + numpy.arange(rows, dtype=numpy.int64) * 900
    shape = (rows, len(v1.HORIZONS_SECONDS))
    exits = numpy.tile(
        timestamps[:, None] + numpy.asarray(v1.HORIZONS_SECONDS), (1, 1)
    )
    return v1.RegimeDataset(
        timestamps=timestamps,
        common_features=numpy.zeros(
            (rows, len(v1.COMMON_FEATURE_NAMES)), dtype=numpy.float32
        ),
        price_features=numpy.zeros(
            (rows, len(v1.PRICE_FEATURE_NAMES)), dtype=numpy.float32
        ),
        book_features=numpy.zeros(
            (rows, len(v1.BOOK_FEATURE_NAMES)), dtype=numpy.float32
        ),
        long_label=numpy.zeros(shape, dtype=numpy.uint8),
        short_label=numpy.zeros(shape, dtype=numpy.uint8),
        long_return=numpy.zeros(shape, dtype=numpy.float32),
        short_return=numpy.zeros(shape, dtype=numpy.float32),
        long_stress_return=numpy.zeros(shape, dtype=numpy.float32),
        short_stress_return=numpy.zeros(shape, dtype=numpy.float32),
        long_exit=exits.copy(),
        short_exit=exits.copy(),
        long_mfe_bps=numpy.zeros(shape, dtype=numpy.float32),
        short_mfe_bps=numpy.zeros(shape, dtype=numpy.float32),
        long_mae_bps=numpy.zeros(shape, dtype=numpy.float32),
        short_mae_bps=numpy.zeros(shape, dtype=numpy.float32),
    )


def test_protocol_is_reduced_result_free_and_orderless(tmp_path):
    path = tmp_path / "protocol.json"
    protocol = regime.write_or_verify_protocol(path)

    assert protocol["results"] is None
    assert protocol["orders_authorized"] is False
    assert protocol["paper_orders_authorized"] is False
    assert protocol["automatic_promotion"] is False
    assert protocol["label"]["horizon_seconds"] == 4 * 3600
    assert protocol["architecture"]["raw_book_feature_count"] == 92
    assert protocol["architecture"]["activity_book_feature_count"] == 24
    assert protocol["architecture"]["direction_book_feature_count"] == 18
    assert protocol["architecture"]["book_residual_weight_search"] is False
    assert protocol["protocol_sha256"] == v1._json_hash(
        regime.frozen_protocol()
    )

    protocol["orders_authorized"] = True
    path.write_text(json.dumps(protocol), encoding="utf-8")
    with pytest.raises(ValueError, match="protocol differs"):
        regime.write_or_verify_protocol(path)


def test_activity_features_remove_direction_sign_only():
    dataset = _dataset(2)
    dataset.price_features[0] = -numpy.arange(
        1, len(v1.PRICE_FEATURE_NAMES) + 1, dtype=numpy.float32
    )
    dataset.book_features[0] = -numpy.arange(
        1, len(v1.BOOK_FEATURE_NAMES) + 1, dtype=numpy.float32
    )
    rows = numpy.asarray([0], dtype=numpy.int64)

    price, price_names = regime._activity_price_features(dataset, rows)
    book, book_names = regime._activity_book_features(dataset, rows)

    price_body = price[:, len(v1.COMMON_FEATURE_NAMES) :]
    assert numpy.all(price_body[:, v1.PRICE_DIRECTIONAL_MASK] >= 0)
    assert numpy.all(price_body[:, ~v1.PRICE_DIRECTIONAL_MASK] < 0)
    assert any(name.startswith("abs_") for name in price_names)
    assert numpy.all(book[:, regime.ACTIVITY_BOOK_DIRECTIONAL_MASK] >= 0)
    assert numpy.all(book[:, ~regime.ACTIVITY_BOOK_DIRECTIONAL_MASK] < 0)
    assert len(book_names) == 24


def test_barrier_event_and_conditional_direction_handle_adverse_tie():
    dataset = _dataset(3)
    horizon = v1.HORIZONS_SECONDS.index(regime.PRIMARY_HORIZON_SECONDS)
    target = (regime.TARGET_BPS - regime.ROUND_TRIP_COST_BPS) / 10_000
    stop = (-regime.STOP_BPS - regime.ROUND_TRIP_COST_BPS) / 10_000
    dataset.long_label[0, horizon] = 1
    dataset.long_return[0, horizon] = target
    dataset.short_return[0, horizon] = stop
    dataset.short_label[1, horizon] = 1
    dataset.short_return[1, horizon] = target
    dataset.long_return[1, horizon] = stop
    dataset.long_return[2, horizon] = stop
    dataset.short_return[2, horizon] = stop

    event, known, up = regime._event_direction_labels(dataset)

    assert event.tolist() == [1, 1, 1]
    assert known.tolist() == [True, True, False]
    assert up.tolist() == [1, 0, 0]


def test_centered_book_residual_is_neutral_at_train_base_rate():
    price = numpy.asarray([0.2, 0.5, 0.8])

    neutral = regime._residual_probability(
        price, numpy.full(3, 0.4), 0.4
    )
    positive = regime._residual_probability(
        price, numpy.full(3, 0.8), 0.4
    )

    assert numpy.allclose(neutral, price, rtol=0.0, atol=1e-12)
    assert numpy.all(positive > price)


def test_expected_value_uses_target_stop_timeout_and_no_probability_gate():
    values = regime._expected_values(
        numpy.asarray([1.0, 0.0]), numpy.asarray([1.0, 1.0])
    )

    assert values["long_expected_return"][0] == pytest.approx(0.0086)
    assert values["short_expected_return"][0] == pytest.approx(-0.0114)
    assert values["long_expected_return"][1] == pytest.approx(-0.0014)
    assert values["short_expected_return"][1] == pytest.approx(-0.0014)


def test_trade_simulation_keeps_only_one_overlapping_position():
    dataset = _dataset(20)
    horizon = v1.HORIZONS_SECONDS.index(regime.PRIMARY_HORIZON_SECONDS)
    dataset.long_return[:, horizon] = 0.0086
    dataset.long_stress_return[:, horizon] = 0.0072
    rows = numpy.arange(20, dtype=numpy.int64)
    long_ev = numpy.full(20, 0.001)
    short_ev = numpy.full(20, -0.001)

    trades = regime._simulate_trades(
        dataset, rows, long_ev, short_ev, stress=False
    )

    assert trades["rows"].tolist() == [0, 17]
    assert trades["directions"].tolist() == [1, 1]
    assert numpy.allclose(trades["instrument_returns"], 0.0086)
