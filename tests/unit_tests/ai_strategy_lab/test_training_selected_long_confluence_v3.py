import json

import pytest

from octobot.ai_strategy_lab import training_selected_long_confluence_v3 as v3


def test_protocol_freezes_one_training_selected_model_and_no_orders():
    protocol = v3.frozen_protocol()

    assert protocol["status"] == "single_training_selected_model_pre_oos"
    assert protocol["training_selection"]["selected_configuration_id"] == (
        "r3-ew_market_28d_positive"
    )
    assert protocol["training_selection"]["selection_was_defined_after_training"]
    assert protocol["training_selection"]["training_is_promotional_evidence"] is False
    assert protocol["orders_authorized"] is False
    assert protocol["paper_orders_authorized"] is False
    assert protocol["automatic_promotion"] is False
    assert protocol["results"] is None


def test_model_parameters_and_costs_are_identical_to_selected_parent_candidate():
    protocol = v3.frozen_protocol()
    model = protocol["frozen_model"]

    assert model["rebalance_blocks"] == 3
    assert model["regime"] == "ew_market_28d_positive"
    assert model["regime_blocks"] == 84
    assert model["early_exit"] is False
    assert model["alternative_configuration"] is False
    assert protocol["economics"]["fee_per_turnover"] == pytest.approx(0.0006)
    assert protocol["economics"]["slippage_per_turnover"] == pytest.approx(
        0.0002
    )
    assert protocol["economics"]["stress_cost_multiplier"] == 3


def test_2025_and_lock_gates_remain_strict_and_sequential():
    protocol = v3.frozen_protocol()

    assert protocol["confirmation"]["status"] == "sealed_first_oos_for_v3"
    assert protocol["confirmation"]["single_query"] is True
    assert protocol["confirmation"]["gate"]["minimum_sharpe"] == pytest.approx(
        0.75
    )
    assert protocol["locked_test"]["status"].startswith("sealed")
    assert protocol["forward_gate"]["minimum_calendar_days"] == 180


def test_protocol_persistence_is_content_addressed_and_fail_closed(tmp_path):
    path = tmp_path / "protocol.json"
    first = v3.write_or_verify_protocol(path)
    second = v3.write_or_verify_protocol(path)

    assert first == second
    assert first["protocol_sha256"] == v3.common._json_hash(v3.frozen_protocol())

    payload = json.loads(path.read_text(encoding="utf-8"))
    payload["frozen_model"]["rebalance_blocks"] = 9
    path.write_text(json.dumps(payload), encoding="utf-8")
    with pytest.raises(ValueError, match="protocol differs"):
        v3.write_or_verify_protocol(path)
