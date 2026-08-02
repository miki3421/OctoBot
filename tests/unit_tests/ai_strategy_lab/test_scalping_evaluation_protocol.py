import json

import pytest

from octobot.ai_strategy_lab import scalping_evaluation_protocol as protocol


def test_protocol_is_result_free_and_cannot_trade(tmp_path):
    path = tmp_path / "protocol.json"

    value = protocol.write_or_verify_protocol(path)

    assert value["orders_authorized"] is False
    assert value["paper_orders_authorized"] is False
    assert value["performance_evaluation_before_gate"] is False
    assert value["results"] is None
    assert json.loads(path.read_text()) == value
    assert protocol.write_or_verify_protocol(path) == value


def test_readiness_requires_freeze_even_after_time_and_coverage():
    waiting = protocol.readiness(
        {
            "span_days": 30,
            "coverage": 0.99,
            "database_operational": True,
        }
    )
    ready = protocol.readiness(
        {
            "span_days": 30,
            "coverage": 0.99,
            "database_operational": True,
        },
        frozen_snapshot_verified=True,
    )

    assert waiting["ready"] is False
    assert waiting["performance_evaluation_authorized"] is False
    assert ready["ready"] is True
    assert ready["orders_authorized"] is False


def test_cost_and_purged_splits_are_deterministic():
    timestamps = list(range(0, 1_200, 10))

    splits = protocol.purged_walk_forward_splits(timestamps, folds=3)

    assert protocol.round_trip_cost_bps(2) == 16
    assert len(splits) == 3
    assert all(
        split["train_end_index_exclusive"]
        < split["test_start_index"]
        for split in splits
    )
    with pytest.raises(ValueError):
        protocol.purged_walk_forward_splits([2, 1], folds=1)
