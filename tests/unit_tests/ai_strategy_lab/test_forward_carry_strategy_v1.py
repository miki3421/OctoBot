import datetime
import json

import pytest

from octobot.ai_strategy_lab import forward_carry_dataset
from octobot.ai_strategy_lab import forward_carry_strategy_v1 as carry_v1


def test_protocol_is_result_free_and_cannot_authorize_orders():
    protocol = carry_v1.frozen_protocol()

    assert protocol["status"] == "result_free_preregistered_design"
    assert protocol["results"] is None
    assert protocol["research_only"] is True
    assert protocol["credentials_used"] is False
    assert protocol["orders_authorized"] is False
    assert protocol["paper_orders_authorized"] is False
    assert protocol["automatic_promotion"] is False
    assert protocol["hypothesis"]["selection_candidates"] == 1
    assert protocol["evidence_policy"]["paper_or_real_trading_consequence"] is False


def test_protocol_is_bound_to_execution_aware_dataset_schema():
    protocol = carry_v1.frozen_protocol()
    dataset = protocol["dataset"]

    assert dataset["schema_version"] == (
        forward_carry_dataset.DATASET_SCHEMA_VERSION
    )
    assert tuple(dataset["feature_names"]) == (
        forward_carry_dataset.FEATURE_NAMES
    )
    assert dataset["primary_horizon_hours"] == 168
    assert dataset["diagnostic_horizons_hours"] == [8, 24]
    assert dataset["diagnostic_horizons_can_select_candidate"] is False
    assert dataset["mid_price_fill_assumed"] is False


def test_temporal_boundaries_preserve_horizon_embargo():
    protocol = carry_v1.frozen_protocol()
    development = protocol["validation"]["development"]
    confirmation = protocol["validation"]["locked_confirmation"]

    development_end = datetime.datetime.fromisoformat(
        development["last_entry_exclusive_utc"]
    )
    cutoff = datetime.datetime.fromisoformat(
        protocol["preregistration_cutoff_utc"]
    )
    confirmation_start = datetime.datetime.fromisoformat(
        confirmation["entry_start_utc"]
    )
    confirmation_end = datetime.datetime.fromisoformat(
        confirmation["entry_end_not_before_utc"]
    )
    confirmation_open = datetime.datetime.fromisoformat(
        confirmation["earliest_open_utc"]
    )

    assert cutoff - development_end == datetime.timedelta(hours=168)
    assert confirmation_start == cutoff
    assert confirmation_end - confirmation_start == datetime.timedelta(
        days=30
    )
    assert confirmation_open - confirmation_end == datetime.timedelta(
        hours=168
    )

    for fold in development["walk_forward_folds"]:
        train_end = datetime.datetime.fromisoformat(
            fold["training_entry_end_exclusive_utc"]
        )
        test_start = datetime.datetime.fromisoformat(
            fold["test_start_utc"]
        )
        assert test_start - train_end == datetime.timedelta(hours=168)


def test_candidate_has_one_fixed_model_and_conservative_stress():
    protocol = carry_v1.frozen_protocol()
    model = protocol["candidate"]["model"]
    stress = protocol["cost_and_execution_stress"]

    assert model["type"] == "ridge_regression"
    assert model["alpha"] == 10.0
    assert model["hyperparameter_search"] is False
    assert model["feature_selection"] is False
    assert model["symbol_identity_feature"] is False
    assert stress["stress_fee_multiplier"] == 2.0
    assert stress["stress_entry_delay_minutes"] == 15
    assert stress["maker_fill_assumptions"] is False


def test_protocol_writer_is_idempotent_and_refuses_mutation(tmp_path):
    path = tmp_path / "protocol.json"
    first = carry_v1.write_or_verify_protocol(path)
    second = carry_v1.write_or_verify_protocol(path)

    assert first == second
    assert len(first["protocol_sha256"]) == 64

    changed = json.loads(path.read_text(encoding="utf-8"))
    changed["candidate"]["model"]["alpha"] = 0.1
    path.write_text(json.dumps(changed), encoding="utf-8")

    with pytest.raises(ValueError, match="protocol differs"):
        carry_v1.write_or_verify_protocol(path)
