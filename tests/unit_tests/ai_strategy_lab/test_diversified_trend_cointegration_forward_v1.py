import json

import pytest

from octobot.ai_strategy_lab import (
    diversified_trend_cointegration_forward_v1 as protocol,
)


def test_forward_protocol_is_orderless_causal_and_binds_selected_model():
    value = protocol.frozen_protocol()

    assert value["orders_authorized"] is False
    assert value["paper_orders_authorized"] is False
    assert value["automatic_promotion"] is False
    assert value["lineage"]["selected_configuration_id"] == (
        "trend50_cointegration50"
    )
    assert value["lineage"]["selected_model_sha256"] == (
        protocol.SELECTED_MODEL_SHA256
    )
    assert value["timeline"]["official_first_bar_open_utc"] == (
        "2026-09-01T00:00:00+00:00"
    )
    assert value["timeline"]["official_first_decision_not_before_utc"] == (
        "2026-09-02T00:10:00+00:00"
    )
    assert value["timeline"]["earliest_gate_cutoff_exclusive_bar"] == (
        "2027-02-28"
    )
    assert value["causal_clock"]["target_applies_to_next_daily_price_return"]
    assert value["implementation_lock"][
        "required_before_first_official_record"
    ]


def test_protocol_write_is_idempotent_and_detects_mutation(tmp_path):
    path = tmp_path / "forward-protocol.json"

    first = protocol.write_or_verify_protocol(path)
    second = protocol.write_or_verify_protocol(path)

    assert first == second == protocol.protocol_payload()
    persisted = json.loads(path.read_text(encoding="utf-8"))
    persisted["orders_authorized"] = True
    path.write_text(json.dumps(persisted), encoding="utf-8")
    with pytest.raises(ValueError, match="protocol differs"):
        protocol.write_or_verify_protocol(path)


def test_parent_gate_is_retained_and_strengthened_by_complete_panel():
    value = protocol.frozen_protocol()

    assert value["forward_gate"]["minimum_calendar_days"] == 180
    assert value["forward_gate"]["minimum_observed_days"] == 165
    assert value["data_quality_additions"][
        "complete_contiguous_calendar_panel_required_before_gate"
    ]
    assert value["official_cutoff_accounting"][
        "cointegration_terminal_liquidation_cost_applied_once_at_gate"
    ]
