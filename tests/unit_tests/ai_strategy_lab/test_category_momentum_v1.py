import json

import pytest

from octobot.ai_strategy_lab import category_momentum_v1 as category_momentum


def test_protocol_is_result_free_and_orderless(tmp_path):
    path = tmp_path / "protocol.json"
    protocol = category_momentum.write_or_verify_protocol(path)

    assert protocol["results"] is None
    assert protocol["research_only"] is True
    assert protocol["credentials_used"] is False
    assert protocol["orders_authorized"] is False
    assert protocol["paper_orders_authorized"] is False
    assert protocol["automatic_promotion"] is False
    assert json.loads(path.read_text()) == protocol
    assert category_momentum.write_or_verify_protocol(path) == protocol


def test_protocol_freezes_external_horizon_taxonomy_and_costs():
    protocol = category_momentum.frozen_protocol()

    assert protocol["signal"]["formation_days"] == 7
    assert protocol["signal"]["holding_days"] == 1
    assert protocol["taxonomy_snapshot"]["category_count"] == 30
    assert len(set(category_momentum.COINGECKO_CATEGORY_IDS)) == 30
    assert protocol["economics"]["fee_per_turnover"] == 0.0006
    assert protocol["economics"]["slippage_per_turnover"] == 0.0002
    assert protocol["economics"]["stress_cost_multiplier"] == 3.0
    assert protocol["signal"]["model_fitted"] is False


def test_historical_windows_are_sequential_but_never_promotional():
    protocol = category_momentum.frozen_protocol()
    validation = protocol["validation"]

    assert validation["development"][1] == validation["confirmation"][0]
    assert validation["confirmation"][1] == validation["locked_final_test"][0]
    assert validation["historical_pass_cannot_promote"] is True
    assert protocol["forward_gate"]["minimum_calendar_days"] == 180
    assert protocol["forward_gate"]["required_before_shadow_or_paper"] is True


def test_existing_protocol_cannot_be_silently_changed(tmp_path):
    path = tmp_path / "protocol.json"
    protocol = category_momentum.write_or_verify_protocol(path)
    protocol["signal"]["formation_days"] = 14
    path.write_text(json.dumps(protocol))

    with pytest.raises(ValueError, match="protocol differs"):
        category_momentum.write_or_verify_protocol(path)
