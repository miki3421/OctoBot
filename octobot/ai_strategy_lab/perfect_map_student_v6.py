"""Pre-registered V6 challenger protocol for future-path forecasting.

This module freezes the V6 research design before any V6 result is computed.
It deliberately contains no training or paper-trading runtime and cannot
authorize orders.  In particular, the frozen V5 forward journal is an
explicitly forbidden development input.
"""

from __future__ import annotations

import argparse
import dataclasses
import datetime
import hashlib
import json
import math
import pathlib
import typing

import numpy

from octobot.ai_strategy_lab import h2_backtest
from octobot.ai_strategy_lab import percentage_engine
from octobot.ai_strategy_lab import perfect_map_student as v1
from octobot.ai_strategy_lab import perfect_map_student_v2 as v2
from octobot.ai_strategy_lab import perfect_map_student_v3 as v3
from octobot.ai_strategy_lab import perfect_map_student_v4 as v4
from octobot.ai_strategy_lab import perfect_map_student_v5 as v5


SCHEMA_VERSION = 1
PROTOCOL_VERSION = "btc_future_path_efficiency_ensemble_v6"
PREREGISTRATION_DATE = "2026-07-26"
ENSEMBLE_SEEDS = (
    20_260_801,
    20_260_802,
    20_260_803,
    20_260_804,
    20_260_805,
)
TIME_NORMALIZED_THRESHOLDS = (0.000, 0.0125, 0.025, 0.0375, 0.050)
RAW_EXPECTED_NET_FLOOR_PCT = 0.075
UNCERTAINTY_STANDARD_DEVIATIONS = 1.0
CALIBRATION_CONFIG = {
    **v5.CALIBRATION_CONFIG,
    "seed": 20_260_806,
}


def protocol_sha256(payload: dict) -> str:
    encoded = json.dumps(
        payload, sort_keys=True, separators=(",", ":")
    ).encode()
    return hashlib.sha256(encoded).hexdigest()


def frozen_protocol() -> dict:
    """Return the result-free V6 protocol frozen before implementation."""

    return {
        "schema_version": SCHEMA_VERSION,
        "protocol_version": PROTOCOL_VERSION,
        "preregistered_on": PREREGISTRATION_DATE,
        "status": "preregistered_design_only",
        "research_only": True,
        "orders_authorized": False,
        "paper_orders_authorized": False,
        "automatic_promotion": False,
        "parent": {
            "protocol_version": v5.PROTOCOL_VERSION,
            "immutable": True,
            "v5_threshold_or_weights_may_change": False,
            "motivation": (
                "reduce long-horizon/maximum-target concentration and account "
                "for forecast uncertainty without retuning V5"
            ),
        },
        "data_policy": {
            "allowed_for_fit_and_selection": {
                "train": list(v1.SPLITS["train"]),
                "calibration": list(v1.SPLITS["calibration"]),
                "threshold_selection": list(
                    v1.SPLITS["threshold_selection"]
                ),
            },
            "diagnostic_reuse_only": {
                "binance": list(v1.SPLITS["locked_test"]),
                "kucoin": list(v1.SPLITS["external_reused_kucoin"]),
            },
            "forbidden_for_fit_calibration_and_selection": [
                "/v5-paper/binance/v5-paper.sqlite",
                "/v5-paper/binance/health.json",
                "all V5 forward decisions, events, positions and outcomes",
            ],
            "first_eligible_new_forward_date": "2026-07-27",
            "future_used_for_labels_only": True,
        },
        "prediction_target": v5.frozen_protocol()["prediction_target"],
        "features": {
            "schema": "perfect_map_student_v1_99_causal_features",
            "feature_count": len(v1.student_feature_names()),
            "new_feature_search": False,
        },
        "forecast": {
            "type": "five_member_block_resampled_grouped_softmax_ensemble",
            "members": len(ENSEMBLE_SEEDS),
            "seeds": list(ENSEMBLE_SEEDS),
            "training_block_hours": 168,
            "base_head_schema": "same_50_stop_timeout_target_heads_as_v5",
            "logical_probability_projection": "same_as_v5",
            "calibration": {
                "type": "per_head_joint_softmax_on_ensemble_mean_logits",
                "split": "calibration_only",
            },
            "uncertainty": (
                "sample standard deviation of expected net across members"
            ),
        },
        "decision": {
            "raw_expected_net_pct": (
                "P(TARGET)*protected_profit_pct "
                "- P(STOP)*initial_stop_pct - round_trip_cost_pct"
            ),
            "conservative_expected_net_pct": (
                "ensemble_mean_expected_net_pct "
                "- 1.0*ensemble_standard_deviation_expected_net_pct"
            ),
            "time_normalized_score": (
                "conservative_expected_net_pct / sqrt(horizon_hours)"
            ),
            "choose": (
                "maximum time_normalized_score configuration and direction "
                "per closed candle"
            ),
            "raw_expected_net_floor_pct": RAW_EXPECTED_NET_FLOOR_PCT,
            "time_normalized_threshold_candidates": list(
                TIME_NORMALIZED_THRESHOLDS
            ),
            "minimum_direction_margin_pct": (
                v5.MINIMUM_DIRECTION_MARGIN_PCT
            ),
            "one_trade_at_a_time": True,
            "threshold_selection_objective": (
                "compounded_net_return_pct minus maximum_drawdown_pct"
            ),
            "selection_gate": {
                "minimum_closed_trades": 20,
                "profit_factor": 1.10,
                "positive_compounded_return": True,
                "positive_objective": True,
                "at_least_one_trade_per_direction": True,
                "at_least_two_distinct_targets": True,
                "at_least_two_distinct_horizons": True,
                "maximum_single_target_share": 0.75,
                "maximum_single_horizon_share": 0.75,
            },
            "tie_break_order": [
                "higher conservative expected net",
                "shorter horizon",
                "smaller protected target",
                "LONG before SHORT for exact numeric equality",
            ],
        },
        "simulation": v5.frozen_protocol()["simulation"],
        "evidence_policy": {
            "development_result_can_promote_v5": False,
            "diagnostic_reuse_can_promote_v6": False,
            "new_forward_required": True,
            "minimum_new_forward_days": 90,
            "minimum_new_forward_closed_trades": 30,
            "paper_activation_requires_manual_approval": True,
            "no_mid_test_retuning": True,
        },
        "implementation_policy": {
            "protocol_must_exist_before_training": True,
            "persist_protocol_hash_with_every_artifact": True,
            "persist_dataset_model_prediction_and_report_hashes": True,
            "reloaded_predictions_must_match_exactly": True,
            "results_in_this_protocol": False,
        },
    }


def write_protocol(
    output_value: typing.Union[str, pathlib.Path]
) -> pathlib.Path:
    output = pathlib.Path(output_value).resolve()
    output.mkdir(parents=True, exist_ok=True)
    protocol = frozen_protocol()
    path = output / "protocol.json"
    path.write_text(
        json.dumps(
            {
                **protocol,
                "protocol_sha256": protocol_sha256(protocol),
            },
            indent=2,
            sort_keys=True,
        )
        + "\n",
        encoding="utf-8",
    )
    return path


def main(argv: typing.Optional[list[str]] = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", required=True)
    arguments = parser.parse_args(argv)
    path = write_protocol(arguments.output)
    print(path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
