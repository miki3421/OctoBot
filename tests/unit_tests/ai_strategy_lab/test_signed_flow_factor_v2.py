import json

import pytest

from octobot.ai_strategy_lab import signed_flow_factor_v2 as factor


def test_protocol_changes_only_to_external_weekly_holding():
    protocol = factor.frozen_protocol()

    assert protocol["public_data_only"] is True
    assert protocol["credentials_used"] is False
    assert protocol["orders_authorized"] is False
    assert protocol["paper_orders_authorized"] is False
    assert protocol["results"] is None
    assert protocol["signal"]["formation_blocks"] == 21
    assert protocol["signal"]["holding_blocks"] == 21
    assert protocol["signal"]["active_vintages_at_steady_state"] == 21
    assert protocol["signal"]["new_vintage_fraction"] == pytest.approx(
        1 / 21
    )
    assert protocol["hypothesis"]["long_only_variant_allowed"] is False
    assert protocol["validation"]["confirmation_status"].startswith(
        "sealed"
    )


def test_protocol_write_is_stable_and_tampering_fails(tmp_path):
    path = tmp_path / "protocol.json"

    first = factor.write_or_verify_protocol(path)
    second = factor.write_or_verify_protocol(path)

    assert first == second
    tampered = json.loads(path.read_text(encoding="utf-8"))
    tampered["signal"]["holding_blocks"] = 20
    path.write_text(json.dumps(tampered), encoding="utf-8")
    with pytest.raises(ValueError, match="protocol differs"):
        factor.write_or_verify_protocol(path)
