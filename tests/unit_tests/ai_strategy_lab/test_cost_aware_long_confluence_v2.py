import json

import pytest

from octobot.ai_strategy_lab import cost_aware_long_confluence_v2 as strategy


def test_protocol_is_result_free_public_only_and_cannot_trade():
    protocol = strategy.frozen_protocol()

    assert protocol["status"] == "result_free_training_and_oos_protocol"
    assert protocol["results"] is None
    assert protocol["research_only"] is True
    assert protocol["public_data_only"] is True
    assert protocol["credentials_used"] is False
    assert protocol["orders_authorized"] is False
    assert protocol["paper_orders_authorized"] is False
    assert protocol["automatic_promotion"] is False


def test_training_grid_is_exactly_the_six_frozen_candidates():
    candidates = strategy.candidate_configurations()

    assert len(candidates) == 6
    assert {item["rebalance_blocks"] for item in candidates} == {3, 9, 21}
    assert {item["regime"] for item in candidates} == {
        "always_on",
        "ew_market_28d_positive",
    }
    assert len({item["configuration_id"] for item in candidates}) == 6


def test_protocol_declares_development_as_training_and_2025_as_first_oos():
    protocol = strategy.frozen_protocol()

    assert protocol["design_disclosure"]["development_is_evidence"] is False
    assert protocol["training"]["status"] == (
        "training_reuse_not_promotional_evidence"
    )
    assert protocol["confirmation"]["status"] == "sealed_first_oos_for_v2"
    assert protocol["locked_test"]["status"].startswith("sealed")


def test_protocol_freezes_costs_selection_and_strict_oos_gates():
    protocol = strategy.frozen_protocol()

    assert protocol["economics"]["fee_per_turnover"] == pytest.approx(0.0006)
    assert protocol["economics"]["slippage_per_turnover"] == pytest.approx(
        0.0002
    )
    assert protocol["economics"]["stress_cost_multiplier"] == 3
    assert protocol["training"]["selection"]["selection_count"] == 1
    assert protocol["training"]["candidate_gate"]["minimum_positive_folds"] == 4
    assert protocol["confirmation"]["gate"]["minimum_sharpe"] == pytest.approx(
        0.75
    )
    assert protocol["forward_gate"]["minimum_calendar_days"] == 180


def test_protocol_persistence_is_content_addressed_and_fail_closed(tmp_path):
    path = tmp_path / "protocol.json"
    first = strategy.write_or_verify_protocol(path)
    second = strategy.write_or_verify_protocol(path)

    assert first == second
    assert first["protocol_sha256"] == strategy.common._json_hash(
        strategy.frozen_protocol()
    )

    payload = json.loads(path.read_text(encoding="utf-8"))
    payload["training_grid"]["configurations"][0]["rebalance_blocks"] = 2
    path.write_text(json.dumps(payload), encoding="utf-8")
    with pytest.raises(ValueError, match="protocol differs"):
        strategy.write_or_verify_protocol(path)
