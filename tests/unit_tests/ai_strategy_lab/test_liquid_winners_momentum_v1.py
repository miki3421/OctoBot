import json

import pytest

from octobot.ai_strategy_lab import liquid_winners_momentum_v1 as protocol


def test_protocol_is_result_free_and_orderless():
    frozen = protocol.frozen_protocol()

    assert frozen["results"] is None
    assert frozen["research_only"] is True
    assert frozen["credentials_used"] is False
    assert frozen["orders_authorized"] is False
    assert frozen["paper_orders_authorized"] is False
    assert frozen["automatic_promotion"] is False
    assert frozen["advancement_consequence"].startswith(
        "a complete training eligibility pass permits only"
    )


def test_exact_external_configuration_and_local_disclosure_are_frozen():
    frozen = protocol.frozen_protocol()
    signal = frozen["signal"]
    disclosure = frozen["local_development_disclosure"]

    assert signal["formation_days"] == 14
    assert signal["holding_days"] == 14
    assert signal["liquidity_lookback_days"] == 14
    assert signal["liquid_fraction"] == 0.30
    assert signal["winner_fraction"] == 0.30
    assert signal["rebalance_anchor"] == "1970-01-05"
    assert disclosure["shared_history_has_been_reused"] is True
    assert disclosure["known_prior_result_is_not_oos"] is True
    assert disclosure["exact_14_14_liquidity_bivariate_outcome_seen"] is False
    assert disclosure["parameter_choice_source"].startswith("external")


def test_gate_is_conjunctive_and_compares_same_liquid_benchmark():
    frozen = protocol.frozen_protocol()
    gate = frozen["training_eligibility_gate"]
    benchmark = frozen["benchmark"]

    assert benchmark["name"] == "same_liquid_bucket_equal_weight"
    assert gate["minimum_annualized_excess_return_over_benchmark"] == 0.03
    assert gate["minimum_sharpe_improvement_over_benchmark"] == 0.10
    assert gate["maximum_drawdown_ratio_to_benchmark"] == 0.90
    assert gate["minimum_positive_leave_one_symbol_out_ratio"] == 0.80
    assert frozen["forward_gate"]["all_checks_conjunctive"] is True
    assert frozen["forward_gate"]["no_refit"] is True


def test_protocol_round_trip_rejects_mutation(tmp_path):
    path = tmp_path / "protocol.json"
    first = protocol.write_or_verify_protocol(path)
    assert protocol.write_or_verify_protocol(path) == first

    changed = json.loads(path.read_text(encoding="utf-8"))
    changed["signal"]["formation_days"] = 7
    path.write_text(json.dumps(changed), encoding="utf-8")
    with pytest.raises(ValueError, match="differs"):
        protocol.write_or_verify_protocol(path)
