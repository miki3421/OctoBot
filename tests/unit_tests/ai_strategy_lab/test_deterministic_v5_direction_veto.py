import json

from octobot.ai_strategy_lab import deterministic_v5_direction_veto as veto
from octobot.ai_strategy_lab import perfect_map_student_v5 as v5


def test_protocol_changes_only_relative_veto_and_disables_orders(tmp_path):
    protocol = veto.frozen_protocol()

    assert protocol["orders_authorized"] is False
    assert protocol["paper_orders_authorized"] is False
    assert protocol["automatic_promotion"] is False
    assert protocol["single_change"][
        "absolute_expected_net_threshold_required"
    ] is False
    assert protocol["implementation"]["results_in_this_protocol"] is False

    path = veto.write_protocol(tmp_path)
    persisted = json.loads(path.read_text())
    assert persisted["protocol_sha256"]


def test_relative_veto_can_agree_when_both_values_are_negative():
    result = veto.direction_veto_decision(
        direction=v5.DIRECTIONS[1],
        long_expected_net_pct=-0.18,
        short_expected_net_pct=-0.10,
    )

    assert result[:3] == (True, "allowed", v5.DIRECTIONS[1])
    assert result[3] == -0.10
    assert result[4] > 0.03


def test_relative_veto_still_rejects_small_margin():
    result = veto.direction_veto_decision(
        direction=v5.DIRECTIONS[0],
        long_expected_net_pct=-0.10,
        short_expected_net_pct=-0.12,
    )

    assert result[:2] == (
        False,
        "v5_direction_margin_below_threshold",
    )
