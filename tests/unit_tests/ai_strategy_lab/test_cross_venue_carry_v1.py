import json

import pytest

from octobot.ai_strategy_lab import cross_venue_carry_v1 as cross_venue


def test_frozen_protocol_is_orderless_and_cost_derived():
    protocol = cross_venue.frozen_protocol()

    assert protocol["public_data_only"] is True
    assert protocol["credentials_used"] is False
    assert protocol["orders_authorized"] is False
    assert protocol["paper_orders_authorized"] is False
    assert protocol["results"] is None
    assert protocol["universe"]["required_symbol_count"] == 18
    expected = 2 * (0.0008 + 0.0008) * 3 * 365 / 30
    assert protocol["signal"][
        "minimum_annualized_spread"
    ] == pytest.approx(expected)


def test_protocol_write_is_content_stable_and_fail_closed(tmp_path):
    path = tmp_path / "protocol.json"

    first = cross_venue.write_or_verify_protocol(path)
    second = cross_venue.write_or_verify_protocol(path)

    assert first == second
    assert first["protocol_sha256"]
    tampered = json.loads(path.read_text(encoding="utf-8"))
    tampered["signal"]["maximum_pairs"] = 4
    path.write_text(json.dumps(tampered), encoding="utf-8")
    with pytest.raises(ValueError, match="protocol differs"):
        cross_venue.write_or_verify_protocol(path)
