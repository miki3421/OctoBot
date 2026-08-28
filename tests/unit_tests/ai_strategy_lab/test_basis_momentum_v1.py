import json

from octobot.ai_strategy_lab import basis_momentum_v1 as basis_momentum


def test_protocol_is_frozen_result_free_and_cannot_authorize_orders(tmp_path):
    path = tmp_path / "protocol.json"
    protocol = basis_momentum.write_or_verify_protocol(path)

    assert protocol["results"] is None
    assert protocol["orders_authorized"] is False
    assert protocol["paper_orders_authorized"] is False
    assert protocol["automatic_promotion"] is False
    assert basis_momentum.write_or_verify_protocol(path) == protocol
    assert json.loads(path.read_text()) == protocol


def test_protocol_freezes_source_selected_formation_direction_and_holding():
    protocol = basis_momentum.frozen_protocol()
    signal = protocol["signal"]

    assert signal["formation_blocks"] == 21
    assert signal["selected_assets_per_side"] == 3
    assert signal["long_side"] == "highest basis-momentum quintile"
    assert signal["short_side"] == "lowest basis-momentum quintile"
    assert signal["holding_blocks"] == 1
    assert signal["holding_hours"] == 8
    assert signal["overlapping_vintages"] is False
    assert protocol["external_hypothesis"][
        "source_reported_high_minus_low_weekly_return"
    ] == 0.0188


def test_protocol_keeps_confirmation_and_lock_sequentially_sealed():
    protocol = basis_momentum.frozen_protocol()
    validation = protocol["validation"]

    assert validation["development_status"] == "diagnostic_reuse"
    assert validation["confirmation_status"].startswith("sealed")
    assert validation["locked_status"].startswith("sealed")
    assert protocol["forward_gate"]["minimum_calendar_days"] == 180
