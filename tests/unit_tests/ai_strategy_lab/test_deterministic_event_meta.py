import json

import numpy

from octobot.ai_strategy_lab import deterministic_event_meta as meta
from octobot.ai_strategy_lab import perfect_map_student_v5 as v5


def _candles(count=120):
    timestamp = 1_780_000_000
    timestamp -= timestamp % meta.CANDLE_SECONDS
    close = numpy.full(count, 100.0)
    return numpy.column_stack(
        (
            timestamp + numpy.arange(count) * meta.CANDLE_SECONDS,
            close,
            close + 0.1,
            close - 0.1,
            close,
            numpy.full(count, 1000.0),
        )
    )


def _evaluator_payload():
    return {
        time_frame: [
            {"evaluator": evaluator, "eval_note": -0.5}
            for evaluator in meta.EVALUATORS
        ]
        for time_frame in meta.TIME_FRAMES
    }


def test_protocol_is_result_free_and_disables_orders(tmp_path):
    protocol = meta.frozen_protocol()

    assert protocol["orders_authorized"] is False
    assert protocol["paper_orders_authorized"] is False
    assert protocol["automatic_promotion"] is False
    assert protocol["model"]["probability_threshold"] == 0.58
    assert protocol["implementation"]["results_in_this_protocol"] is False
    assert protocol["features"]["count"] == len(meta.feature_names())

    path = meta.write_protocol(tmp_path)
    persisted = json.loads(path.read_text())
    assert persisted["protocol_sha256"]


def test_evaluator_features_are_aligned_to_proposed_direction():
    payload = _evaluator_payload()

    long_values = meta._evaluator_features(payload, v5.DIRECTIONS[0])
    short_values = meta._evaluator_features(payload, v5.DIRECTIONS[1])

    assert len(long_values) == 18
    assert long_values == [0.5] * 18
    assert short_values == [-0.5] * 18


def test_lock_trade_uses_stop_before_same_candle_activation():
    candles = _candles()
    candles[1, 2] = 102.0
    candles[1, 3] = 98.0

    trade = meta.simulate_lock_trade(
        candles=candles,
        entry_index=0,
        direction=v5.DIRECTIONS[0],
        round_trip_cost_pct=meta.ROUND_TRIP_COST_PCT,
        funding_timestamps=numpy.asarray([], dtype=numpy.int64),
        funding_rates=numpy.asarray([], dtype=float),
    )

    assert trade["label"] == 0
    assert trade["outcome"] == "STOP"
    assert numpy.isclose(trade["net_return_pct"], -1.16)


def test_lock_activates_then_exits_from_following_candle():
    candles = _candles()
    candles[1, 2] = 101.3
    candles[1, 3] = 100.5
    candles[2, 3] = 100.5

    trade = meta.simulate_lock_trade(
        candles=candles,
        entry_index=0,
        direction=v5.DIRECTIONS[0],
        round_trip_cost_pct=meta.ROUND_TRIP_COST_PCT,
        funding_timestamps=numpy.asarray([], dtype=numpy.int64),
        funding_rates=numpy.asarray([], dtype=float),
    )

    assert trade["label"] == 1
    assert trade["activation_index"] == 1
    assert trade["exit_index"] == 2
    assert trade["outcome"] == "PROFIT_LOCK"
    assert numpy.isclose(trade["net_return_pct"], 0.84)


def test_classification_metrics_compare_with_frozen_constant():
    labels = numpy.asarray([0, 0, 1, 1], dtype=numpy.int8)
    predictions = numpy.asarray([0.1, 0.2, 0.8, 0.9])

    metrics = meta.classification_metrics(labels, predictions, 0.5)

    assert metrics["roc_auc"] == 1.0
    assert metrics["brier"] < metrics["constant_brier"]
    assert metrics["brier_skill_vs_constant_pct"] > 0
