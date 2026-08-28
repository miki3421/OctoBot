import json

import pytest

from octobot.ai_strategy_lab import expanded_training_long_confluence_v4 as v4


def test_protocol_is_result_free_and_cannot_trade():
    protocol = v4.frozen_protocol()

    assert protocol["status"] == "expanded_training_pre_2026_oos"
    assert protocol["results"] is None
    assert protocol["research_only"] is True
    assert protocol["public_data_only"] is True
    assert protocol["credentials_used"] is False
    assert protocol["orders_authorized"] is False
    assert protocol["paper_orders_authorized"] is False
    assert protocol["automatic_promotion"] is False


def test_grid_is_exactly_sixteen_candidates():
    candidates = v4.candidate_configurations()

    assert len(candidates) == 16
    assert {item["rebalance_blocks"] for item in candidates} == {3, 9, 21, 42}
    assert {item["regime"] for item in candidates} == set(v4.REGIMES)
    assert len({item["configuration_id"] for item in candidates}) == 16


def test_training_includes_2025_but_2026_is_single_sealed_oos():
    protocol = v4.frozen_protocol()

    assert protocol["lineage"]["2025_is_oos_for_v4"] is False
    assert protocol["training"]["period"][1].startswith("2026-01-01")
    assert len(protocol["training"]["folds"]) == 7
    assert protocol["oos_test"]["status"] == "sealed_single_query"
    assert protocol["oos_test"]["failed_model_replacement"] is False


def test_selection_and_oos_gate_are_frozen():
    protocol = v4.frozen_protocol()

    assert protocol["training"]["selection"]["selection_count"] == 1
    assert protocol["training"]["selection"]["selection_is_economic_pass"] is False
    assert protocol["oos_test"]["gate"]["minimum_sharpe"] == pytest.approx(0.5)
    assert protocol["oos_test"]["gate"]["stress_total_return_positive"] is True
    assert protocol["forward_gate"]["minimum_calendar_days"] == 180


def test_protocol_persistence_is_content_addressed_and_fail_closed(tmp_path):
    path = tmp_path / "protocol.json"
    first = v4.write_or_verify_protocol(path)
    second = v4.write_or_verify_protocol(path)

    assert first == second
    assert first["protocol_sha256"] == v4.common._json_hash(v4.frozen_protocol())

    payload = json.loads(path.read_text(encoding="utf-8"))
    payload["training_grid"]["configuration_count"] = 15
    path.write_text(json.dumps(payload), encoding="utf-8")
    with pytest.raises(ValueError, match="protocol differs"):
        v4.write_or_verify_protocol(path)
