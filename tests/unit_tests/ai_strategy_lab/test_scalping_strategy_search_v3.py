import json

import pytest

from octobot.ai_strategy_lab import scalping_strategy_search as v1
from octobot.ai_strategy_lab import scalping_strategy_search_v2 as v2
from octobot.ai_strategy_lab import scalping_strategy_search_v3 as v3


def test_v3_protocol_is_result_free_and_keeps_locked_test_sealed():
    protocol = v3.frozen_protocol()

    assert protocol["results"] is None
    assert protocol["orders_authorized"] is False
    assert protocol["paper_orders_authorized"] is False
    assert protocol["automatic_promotion"] is False
    assert protocol["frozen_source"]["locked_test"] == [
        v2.DIAGNOSTIC_CONFIRMATION_END,
        v2.LOCKED_TEST_END,
    ]
    assert protocol["features"]["original_aggregate_features"] == len(
        v1.FEATURE_NAMES
    )
    assert protocol["features"]["new_queue_flow_features"] == 56
    assert protocol["candidate_family"]["selection_candidates"] == 4
    assert protocol["costs"]["maker_fill_assumptions"] is False


def test_v3_protocol_write_is_immutable(tmp_path):
    path = tmp_path / "protocol.json"
    first = v3.write_or_verify_protocol(path)

    assert v3.write_or_verify_protocol(path) == first
    persisted = json.loads(path.read_text(encoding="utf-8"))
    assert persisted["protocol_sha256"] == v3._json_hash(
        v3.frozen_protocol()
    )

    persisted["model"]["target_clip_bps"] = 59.0
    path.write_text(json.dumps(persisted), encoding="utf-8")
    with pytest.raises(ValueError, match="differs"):
        v3.write_or_verify_protocol(path)
