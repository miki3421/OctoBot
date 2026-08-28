import json

import pytest

from octobot.ai_strategy_lab import liquid_cross_sectional_momentum_v1 as protocol


def test_protocol_is_single_configuration_orderless_and_forward_only():
    value = protocol.frozen_protocol()

    assert value["hypothesis"]["one_configuration_only"] is True
    assert value["signal"]["formation_days"] == 21
    assert value["signal"]["holding_days"] == 7
    assert value["signal"]["tail_fraction"] == 0.30
    assert value["signal"]["side_gross_exposure"] == 0.40
    assert value["economics"]["maker_fill_assumptions"] is False
    assert value["economics"]["learned_execution_saving_applied_to_backtest"] is False
    assert value["validation"]["historical_pass_is_not_oos_evidence"] is True
    assert value["forward_gate"]["minimum_calendar_days"] == 180
    assert value["orders_authorized"] is False
    assert value["paper_orders_authorized"] is False
    assert value["automatic_promotion"] is False
    assert value["results"] is None


def test_training_folds_are_complete_non_overlapping_half_years():
    folds = protocol.TRAINING_FOLDS

    assert len(folds) == 7
    assert folds[0][0] == protocol.TRAINING_START
    assert folds[-1][1] == protocol.TRAINING_END
    assert all(left[1] == right[0] for left, right in zip(folds, folds[1:]))
    assert all(end > start for start, end in folds)


def test_write_or_verify_is_immutable(tmp_path):
    path = tmp_path / "protocol.json"

    first = protocol.write_or_verify_protocol(path)
    second = protocol.write_or_verify_protocol(path)

    assert first == second
    assert first["protocol_sha256"]
    changed = json.loads(path.read_text(encoding="utf-8"))
    changed["orders_authorized"] = True
    path.write_text(json.dumps(changed), encoding="utf-8")
    with pytest.raises(ValueError, match="differs"):
        protocol.write_or_verify_protocol(path)
