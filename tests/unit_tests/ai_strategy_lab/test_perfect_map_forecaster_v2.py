import datetime
import json

import numpy

from octobot.ai_strategy_lab import perfect_map_forecaster_v2 as forecaster
from octobot.ai_strategy_lab import perfect_map_student as v1


def _candles(count=420):
    timestamp = 1_700_000_100
    timestamp -= timestamp % forecaster.CANDLE_SECONDS
    close = numpy.full(count, 100.0)
    return numpy.column_stack(
        (
            timestamp
            + numpy.arange(count) * forecaster.CANDLE_SECONDS,
            close,
            close + 0.1,
            close - 0.1,
            close,
            numpy.linspace(100.0, 200.0, count),
        )
    )


def test_protocol_is_result_free_and_disables_orders(tmp_path):
    protocol = forecaster.frozen_protocol()

    assert protocol["orders_authorized"] is False
    assert protocol["paper_orders_authorized"] is False
    assert protocol["automatic_promotion"] is False
    assert protocol["implementation_policy"]["results_in_this_protocol"] is False
    assert protocol["status"] == "preregistered_design_only"
    assert "observed_metrics" not in protocol

    path = forecaster.write_protocol(tmp_path)
    persisted = json.loads(path.read_text())
    assert persisted["protocol_sha256"] == forecaster.protocol_sha256(protocol)


def test_expansion_label_requires_a_useful_future_offset():
    candles = _candles(40)
    candles[2, 2] = 101.0
    candles[13, 2] = 101.0

    labels, directions, offsets = forecaster.expansion_labels(candles)

    assert labels[0] == 0
    assert offsets[0] == 2
    assert labels[10] == 1
    assert directions[10] == v1.LONG
    assert offsets[10] == 3


def test_ambiguous_expansion_has_no_direction():
    candles = _candles(40)
    candles[8, 2] = 101.0
    candles[8, 3] = 99.0

    labels, directions, offsets = forecaster.expansion_labels(candles)

    assert labels[5] == 1
    assert directions[5] == v1.WAIT
    assert offsets[5] == 3


def test_causal_features_do_not_change_before_future_edit():
    candles = _candles()
    original, names = forecaster.precursor.causal_features(candles)
    changed = candles.copy()
    changed[350:, 1:6] *= 1.05
    updated, updated_names = forecaster.precursor.causal_features(changed)

    assert names == updated_names
    numpy.testing.assert_allclose(
        original[:350], updated[:350], equal_nan=True
    )


def test_candidate_labels_require_all_three_stages():
    predictions = {
        "joint_probability": numpy.asarray(
            [[0.30, 0.10], [0.31, 0.11], [0.10, 0.40]]
        ),
        "direction_probability": numpy.asarray(
            [[0.70, 0.30], [0.54, 0.46], [0.20, 0.80]]
        ),
        "expected_net_pct": numpy.asarray(
            [[0.10, 0.00], [0.10, 0.00], [0.00, 0.09]]
        ),
    }

    labels = forecaster.candidate_labels(
        predictions,
        joint_probability_threshold=0.25,
        minimum_direction_probability=0.60,
        minimum_expected_net_pct=0.05,
    )

    assert labels.tolist() == [v1.LONG, v1.WAIT, v1.SHORT]


def test_trade_schema_contains_metrics_duration(monkeypatch):
    candles = _candles(12)
    dataset = forecaster.ForecastDataset(
        features=numpy.zeros((1, 1)),
        base_features=numpy.zeros((1, 1)),
        expansion_labels=numpy.asarray([1], dtype=numpy.int8),
        direction_labels=numpy.asarray([v1.LONG], dtype=numpy.int8),
        touch_offsets=numpy.asarray([3], dtype=numpy.int16),
        timestamps=numpy.asarray(
            [int(candles[0, 0]) + forecaster.CANDLE_SECONDS]
        ),
        candle_indices=numpy.asarray([0]),
        candles=candles,
    )
    predictions = {
        "joint_probability": numpy.asarray([[0.40, 0.10]]),
        "direction_probability": numpy.asarray([[0.80, 0.20]]),
        "expected_net_pct": numpy.asarray([[0.10, 0.00]]),
        "target_index": numpy.asarray([[0, 0]]),
        "horizon_index": numpy.asarray([[0, 0]]),
        "expansion_probability": numpy.asarray([0.50]),
        "target_probability": numpy.asarray([[0.60, 0.20]]),
    }

    monkeypatch.setattr(
        forecaster.percentage_engine,
        "simulate_trade",
        lambda *args, **kwargs: {
            "entry_time": int(candles[0, 0]) + 900,
            "exit_time": int(candles[4, 0]) + 900,
            "entry_price": 100.0,
            "exit_price": 100.5,
            "exit_reason": "time_stop",
            "gross_return_pct": 0.5,
            "maximum_favorable_excursion_pct": 0.7,
            "maximum_adverse_excursion_pct": -0.2,
            "exit_index": 4,
        },
    )

    trades = forecaster.simulate_predictions(
        dataset,
        predictions,
        (numpy.asarray([], dtype=numpy.int64), numpy.asarray([])),
        joint_probability_threshold=0.25,
        minimum_direction_probability=0.60,
        minimum_expected_net_pct=0.05,
    )

    assert trades[0]["duration_hours"] == 1.0


def test_simulated_path_has_mature_4h_and_8h_accuracy_only():
    candles = _candles(450)
    returns = (
        0.0003
        + 0.0002 * numpy.sin(numpy.arange(len(candles)) / 9.0)
    )
    candles[:, 4] = 100 * numpy.exp(numpy.cumsum(returns))
    candles[:, 1] = candles[:, 4]
    candles[:, 2] = candles[:, 4] * 1.001
    candles[:, 3] = candles[:, 4] * 0.999
    valid = numpy.arange(200, len(candles), dtype=numpy.int64)
    predictions = {
        "joint_probability": numpy.tile(
            numpy.asarray([[0.42, 0.12]]), (len(valid), 1)
        ),
    }
    start = datetime.datetime(2026, 7, 20)
    display_values = [
        (start + datetime.timedelta(minutes=15 * index)).strftime(
            "%y-%m-%d %H:%M:%S"
        )
        for index in range(len(candles))
    ]

    payload = forecaster.simulated_path_payload(
        closed=candles,
        display_values=display_values,
        valid=valid,
        predictions=predictions,
    )

    assert len(payload["latest"]["x"]) == 33
    assert set(payload["latest"]["endpoints"]) == {"4h", "8h"}
    assert payload["latest"]["preferred_direction"] == "LONG"
    assert (
        payload["accuracy"]["4h"]["mature_forecasts"]
        == len(valid[valid + 16 < len(candles)])
    )
    assert (
        payload["accuracy"]["8h"]["mature_forecasts"]
        == len(valid[valid + 32 < len(candles)])
    )
    assert (
        payload["accuracy"]["4h"][
            "overall_directional_accuracy_pct"
        ]
        == 100.0
    )
    assert (
        payload["accuracy"]["8h"][
            "rolling_directional_accuracy_pct"
        ]
        == 100.0
    )


def test_path_scenario_does_not_read_candles_after_anchor():
    candles = _candles(420)
    returns = 0.0001 * numpy.sin(numpy.arange(len(candles)) / 7.0)
    candles[:, 4] = 100 * numpy.exp(numpy.cumsum(returns))
    predictions = {
        "joint_probability": numpy.asarray([[0.30, 0.20]])
    }
    original = forecaster._path_scenario_at(
        closed=candles,
        candle_index=350,
        prediction_row=0,
        predictions=predictions,
        horizon_bars=32,
    )
    changed = candles.copy()
    changed[351:, 4] *= 1.50
    updated = forecaster._path_scenario_at(
        closed=changed,
        candle_index=350,
        prediction_row=0,
        predictions=predictions,
        horizon_bars=32,
    )

    assert original == updated
