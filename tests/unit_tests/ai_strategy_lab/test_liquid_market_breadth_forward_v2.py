import json

import pytest

from octobot.ai_strategy_lab import liquid_market_breadth_forward_v2 as protocol


def test_protocol_is_forward_only_and_orderless():
    frozen = protocol.frozen_protocol()

    assert frozen["historical_evaluation_allowed"] is False
    assert frozen["results"] is None
    assert frozen["research_only"] is True
    assert frozen["observation_only"] is True
    assert frozen["credentials_used"] is False
    assert frozen["orders_authorized"] is False
    assert frozen["paper_orders_authorized"] is False
    assert frozen["automatic_promotion"] is False
    assert "second independent confirmation" in frozen["promotion_consequence"]


def test_derivation_and_single_breadth_change_are_explicit():
    frozen = protocol.frozen_protocol()
    derivation = frozen["derivation_disclosure"]
    signal = frozen["signal"]

    assert derivation["parent_outcomes_read_before_v2"] is True
    assert derivation["post_hoc_diagnosis_read_before_v2"] is True
    assert derivation["historical_v2_outcome_must_not_be_calculated"] is True
    assert signal["parent_signal_reused_exactly"] is True
    assert signal["minimum_positive_breadth"] == pytest.approx(2.0 / 3.0)
    assert signal["no_other_filter_or_parameter_change"] is True
    assert signal["historical_v2_simulation_forbidden"] is True


def test_timeline_starts_after_new_data_and_requires_full_window():
    frozen = protocol.frozen_protocol()
    timeline = frozen["timeline"]
    gate = frozen["forward_gate"]

    assert timeline["official_first_decision_bar"] == "2026-09-01"
    assert timeline["cutoff_exclusive_bar"] == "2027-02-28"
    assert gate["required_market_records"] == 180
    assert gate["required_decision_records"] == 180
    assert gate["minimum_mature_outcomes"] == 179
    assert gate["all_checks_conjunctive"] is True


def test_multiple_testing_and_two_counterfactuals_are_frozen():
    frozen = protocol.frozen_protocol()
    multiple = frozen["multiple_testing_control"]

    assert multiple["prospective_hypotheses_accounted"] == 4
    assert multiple["bonferroni_per_candidate_alpha"] == pytest.approx(0.0125)
    assert multiple["required_bootstrap_confidence"] == pytest.approx(0.9875)
    assert multiple["bootstrap_simulations"] == 20_000
    assert multiple["circular_block_days"] == 14
    assert set(frozen["counterfactuals"]) >= {
        "parent_v1",
        "continuous_benchmark",
    }


def test_protocol_round_trip_rejects_mutation(tmp_path):
    path = tmp_path / "protocol.json"
    first = protocol.write_or_verify_protocol(path)
    assert protocol.write_or_verify_protocol(path) == first

    changed = json.loads(path.read_text(encoding="utf-8"))
    changed["signal"]["minimum_positive_breadth"] = 0.50
    path.write_text(json.dumps(changed), encoding="utf-8")
    with pytest.raises(ValueError, match="differs"):
        protocol.write_or_verify_protocol(path)
