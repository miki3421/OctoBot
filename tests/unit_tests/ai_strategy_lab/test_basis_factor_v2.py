import json

from octobot.ai_strategy_lab import basis_factor_v2 as basis_factor


def test_protocol_is_frozen_result_free_and_cannot_authorize_orders(tmp_path):
    path = tmp_path / "protocol.json"
    protocol = basis_factor.write_or_verify_protocol(path)

    assert protocol["results"] is None
    assert protocol["orders_authorized"] is False
    assert protocol["paper_orders_authorized"] is False
    assert protocol["automatic_promotion"] is False
    assert basis_factor.write_or_verify_protocol(path) == protocol
    assert json.loads(path.read_text()) == protocol


def test_protocol_freezes_the_source_defined_eight_hour_low_basis_trade():
    protocol = basis_factor.frozen_protocol()
    signal = protocol["signal"]

    assert signal["basis"] == "log(perpetual_close)-log(spot_close)"
    assert signal["selected_assets_per_side"] == 3
    assert signal["long_side"] == "lowest log-basis quintile"
    assert signal["short_side"] == "highest log-basis quintile"
    assert signal["holding_blocks"] == 1
    assert signal["holding_hours"] == 8
    assert signal["overlapping_vintages"] is False
    assert protocol["external_hypothesis"]["n_definition"].startswith("one eight-hour")


def test_protocol_keeps_confirmation_and_lock_sequentially_sealed():
    protocol = basis_factor.frozen_protocol()
    validation = protocol["validation"]

    assert validation["development_status"] == "diagnostic_reuse"
    assert validation["confirmation_status"] == "sealed_for_basis_family"
    assert validation["locked_status"] == "sealed_for_basis_family"
    assert protocol["forward_gate"]["minimum_calendar_days"] == 180
