import json

import pytest

from octobot.ai_strategy_lab import cointegration_pairs_v1 as parent
from octobot.ai_strategy_lab import cointegration_pairs_v2 as pairs


def test_protocol_is_result_free_orderless_and_immutable(tmp_path):
    path = tmp_path / "protocol.json"
    protocol = pairs.write_or_verify_protocol(path)

    assert protocol["results"] is None
    assert protocol["research_only"] is True
    assert protocol["credentials_used"] is False
    assert protocol["orders_authorized"] is False
    assert protocol["paper_orders_authorized"] is False
    assert protocol["automatic_promotion"] is False
    assert json.loads(path.read_text()) == protocol
    assert pairs.write_or_verify_protocol(path) == protocol

    changed = json.loads(path.read_text())
    changed["trading"]["entry_absolute_z"] = 1.5
    path.write_text(json.dumps(changed))
    with pytest.raises(ValueError, match="protocol differs"):
        pairs.write_or_verify_protocol(path)


def test_v2_changes_universe_and_fdr_resolution_not_trading_rule():
    protocol = pairs.frozen_protocol()

    assert protocol["data"]["universe_assets"] == 120
    assert protocol["formation"]["bh_denominator"].startswith("all eligible")
    assert protocol["formation"]["monte_carlo_simulations"] == 1_500_000
    assert protocol["formation"]["resolution_multiple_inside_strictest_bh"] > 10
    assert protocol["formation"]["lookback_days"] == parent.FORMATION_DAYS
    assert protocol["formation"]["maximum_pairs"] == parent.MAXIMUM_PAIRS
    assert protocol["trading"]["entry_absolute_z"] == parent.ENTRY_Z
    assert protocol["trading"]["exit_absolute_z"] == parent.EXIT_Z
    assert protocol["trading"]["stop_absolute_z"] == parent.STOP_Z
    assert protocol["trading"]["fee_per_turnover"] == parent.FEE_PER_TURNOVER
    assert protocol["trading"]["slippage_per_turnover"] == parent.SLIPPAGE_PER_TURNOVER


def test_historical_results_can_only_authorize_forward_observation():
    protocol = pairs.frozen_protocol()

    assert protocol["validation"]["historical_pass_cannot_promote"] is True
    assert protocol["forward_gate"]["minimum_calendar_days"] == 180
    assert protocol["forward_gate"]["required_before_shadow_or_paper"] is True
    assert "orderless" in protocol["promotion_consequence"]
