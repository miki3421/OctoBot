import json

import pytest

from octobot.ai_strategy_lab import relative_value_confluence_v1 as confluence


def test_protocol_is_result_free_and_cannot_trade():
    protocol = confluence.frozen_protocol()

    assert protocol["status"] == "result_free_evaluation_protocol"
    assert protocol["results"] is None
    assert protocol["research_only"] is True
    assert protocol["public_data_only"] is True
    assert protocol["credentials_used"] is False
    assert protocol["orders_authorized"] is False
    assert protocol["paper_orders_authorized"] is False
    assert protocol["automatic_promotion"] is False


def test_protocol_freezes_the_three_way_intersection():
    signal = confluence.frozen_protocol()["signal"]

    assert signal["formation_blocks"] == 21
    assert signal["long_intersection"].startswith("bottom log-basis")
    assert signal["short_intersection"].startswith("top log-basis")
    assert signal["maximum_assets_per_side"] == 3
    assert signal["paired_side_requirement"].startswith("flat unless both")
    assert signal["side_gross_exposure"] == pytest.approx(0.4)
    assert signal["maximum_portfolio_gross"] == pytest.approx(0.8)
    assert signal["learned_thresholds"] is None
    assert signal["filters"] is None
    assert signal["other_lookbacks"] is None


def test_protocol_keeps_costs_and_sealed_periods():
    protocol = confluence.frozen_protocol()

    assert protocol["economics"]["fee_per_turnover"] == pytest.approx(0.0006)
    assert protocol["economics"]["slippage_per_turnover"] == pytest.approx(
        0.0002
    )
    assert protocol["economics"]["stress_cost_multiplier"] == 3
    assert protocol["economics"]["cost_reduction_relative_to_prior_tests"] is False
    assert protocol["validation"]["confirmation_status"] == (
        "sealed_for_confluence_family"
    )
    assert protocol["validation"]["locked_status"] == (
        "sealed_for_confluence_family"
    )


def test_protocol_freezes_strict_activity_and_robustness_gates():
    gate = confluence.frozen_protocol()["development_gate"]

    assert gate["minimum_blocks"] == 2000
    assert gate["minimum_invested_blocks"] == 250
    assert gate["minimum_sharpe"] == pytest.approx(1.0)
    assert gate["minimum_profit_factor"] == pytest.approx(1.1)
    assert gate["minimum_positive_folds"] == 4
    assert gate["minimum_positive_leave_one_symbol_out"] == 15
    assert gate["stress_total_return_positive"] is True
    assert gate["both_side_contributions_nonnegative"] is True


def test_protocol_persistence_is_content_addressed_and_fail_closed(tmp_path):
    path = tmp_path / "protocol.json"
    first = confluence.write_or_verify_protocol(path)
    second = confluence.write_or_verify_protocol(path)

    assert first == second
    assert first["protocol_sha256"] == confluence.common._json_hash(
        confluence.frozen_protocol()
    )

    payload = json.loads(path.read_text(encoding="utf-8"))
    payload["signal"]["formation_blocks"] = 20
    path.write_text(json.dumps(payload), encoding="utf-8")
    with pytest.raises(ValueError, match="protocol differs"):
        confluence.write_or_verify_protocol(path)
