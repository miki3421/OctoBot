import json

import pytest

from octobot.ai_strategy_lab import winner_btc_hedged_momentum_v2 as protocol


def test_v2_is_one_training_informed_orderless_configuration():
    value = protocol.frozen_protocol()

    assert value["parent_v1"]["verdict"] == "REJECTED_TRAINING_NO_FORWARD"
    assert value["parent_v1"]["not_reinterpreted_as_pass"] is True
    assert value["hypothesis"]["one_configuration_only"] is True
    assert value["signal"]["formation_days"] == 21
    assert value["signal"]["holding_days"] == 7
    assert value["signal"]["hedge_symbol"] == "BTCUSDT"
    assert value["signal"]["hedge_direction"] == "short"
    assert value["economics"]["maker_fill_assumptions"] is False
    assert (
        value["economics"]["kucoin_btc_execution_model_transfers_to_binance"]
        is False
    )
    assert value["validation"]["historical_pass_is_not_oos_evidence"] is True
    assert value["orders_authorized"] is False
    assert value["paper_orders_authorized"] is False
    assert value["results"] is None


def test_v2_keeps_parent_signal_data_costs_and_forward_start():
    value = protocol.frozen_protocol()

    assert (
        value["data"]["history_bundle_sha256"]
        == protocol.parent.HISTORY_BUNDLE_SHA256
    )
    assert value["signal"]["winner_fraction"] == protocol.parent.TAIL_FRACTION
    assert value["economics"]["fee_per_turnover"] == protocol.parent.FEE_PER_TURNOVER
    assert (
        value["economics"]["slippage_per_turnover"]
        == protocol.parent.SLIPPAGE_PER_TURNOVER
    )
    assert value["forward_gate"]["start_utc"] == "2026-09-01T00:00:00+00:00"


def test_write_or_verify_is_immutable(tmp_path):
    path = tmp_path / "protocol.json"
    first = protocol.write_or_verify_protocol(path)

    assert protocol.write_or_verify_protocol(path) == first
    changed = json.loads(path.read_text(encoding="utf-8"))
    changed["signal"]["hedge_gross_exposure_before_netting"] = 0.2
    path.write_text(json.dumps(changed), encoding="utf-8")
    with pytest.raises(ValueError, match="differs"):
        protocol.write_or_verify_protocol(path)
