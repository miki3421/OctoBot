import copy
import json

import pytest

from octobot.ai_strategy_lab import forward_carry_strategy_v1 as v1
from octobot.ai_strategy_lab import forward_carry_strategy_v1_1 as v1_1


def test_v1_1_preserves_parent_and_only_repairs_feasibility():
    parent_before = v1.frozen_protocol()
    corrected = v1_1.frozen_protocol()
    parent_after = v1.frozen_protocol()

    assert parent_before == parent_after
    assert v1._json_hash(parent_before) == v1_1.PARENT_PROTOCOL_SHA256
    assert parent_before["development_gate"]["minimum_closed_pairs"] == 15
    assert corrected["development_gate"]["minimum_closed_pairs"] == 8
    assert corrected["correction"]["economic_outcomes_read"] is False
    assert corrected["correction"]["parent_preserved"] is True
    assert corrected["correction"]["other_candidate_parameters_changed"] is False
    assert corrected["results"] is None
    assert corrected["orders_authorized"] is False

    restored = copy.deepcopy(corrected)
    restored["protocol_version"] = v1.PROTOCOL_VERSION
    restored["status"] = parent_before["status"]
    restored.pop("correction")
    restored["development_gate"]["minimum_closed_pairs"] = 15
    restored_confirmation = restored["validation"]["locked_confirmation"]
    restored_confirmation["entry_end_not_before_utc"] = (
        restored_confirmation.pop("entry_end_exclusive_utc")
    )
    restored_confirmation.pop("entry_window_is_fixed")
    assert restored == parent_before


def test_v1_1_makes_confirmation_window_fixed():
    confirmation = v1_1.frozen_protocol()["validation"][
        "locked_confirmation"
    ]

    assert confirmation["entry_window_is_fixed"] is True
    assert confirmation["entry_end_exclusive_utc"] == (
        "2026-09-26T12:00:00+00:00"
    )
    assert "entry_end_not_before_utc" not in confirmation


def test_v1_1_writer_is_idempotent_and_refuses_mutation(tmp_path):
    path = tmp_path / "protocol.json"
    first = v1_1.write_or_verify_protocol(path)
    second = v1_1.write_or_verify_protocol(path)

    assert first == second
    assert len(first["protocol_sha256"]) == 64
    changed = json.loads(path.read_text(encoding="utf-8"))
    changed["development_gate"]["minimum_closed_pairs"] = 1
    path.write_text(json.dumps(changed), encoding="utf-8")

    with pytest.raises(ValueError, match="protocol differs"):
        v1_1.write_or_verify_protocol(path)
