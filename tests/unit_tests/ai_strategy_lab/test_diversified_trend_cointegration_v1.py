import json

import pytest

from octobot.ai_strategy_lab import diversified_trend_cointegration_v1 as protocol


def test_frozen_protocol_is_result_free_and_orderless():
    value = protocol.frozen_protocol()

    assert value["selected_model"] is None
    assert value["results"] is None
    assert value["orders_authorized"] is False
    assert value["paper_orders_authorized"] is False
    assert value["automatic_promotion"] is False
    assert value["hypothesis"][
        "all_historical_market_paths_seen_by_other_families"
    ]
    assert not value["hypothesis"][
        "cointegration_2025_2026_signal_outcomes_seen_before_protocol"
    ]
    assert not value["pre_outcome_amendment"][
        "combined_trajectories_read_before_change"
    ]


def test_allocations_are_fixed_two_sleeve_budgets():
    values = protocol.frozen_protocol()["portfolio"]["capital_allocations"]

    assert len(values) == 3
    assert len({value["configuration_id"] for value in values}) == 3
    for value in values:
        assert value["trend_capital_weight"] > 0
        assert value["cointegration_capital_weight"] > 0
        assert value["trend_capital_weight"] + value[
            "cointegration_capital_weight"
        ] == pytest.approx(1.0)


def test_training_folds_are_contiguous_and_cover_training():
    assert protocol.TRAINING_FOLDS[0][0] == protocol.TRAINING_START
    assert protocol.TRAINING_FOLDS[-1][1] == protocol.TRAINING_END
    assert all(
        left[1] == right[0]
        for left, right in zip(
            protocol.TRAINING_FOLDS, protocol.TRAINING_FOLDS[1:]
        )
    )


def test_write_or_verify_rejects_mutation(tmp_path):
    path = tmp_path / "protocol.json"
    created = protocol.write_or_verify_protocol(path)

    assert protocol.write_or_verify_protocol(path) == created
    changed = json.loads(path.read_text())
    changed["orders_authorized"] = True
    path.write_text(json.dumps(changed))
    with pytest.raises(ValueError, match="differs"):
        protocol.write_or_verify_protocol(path)
