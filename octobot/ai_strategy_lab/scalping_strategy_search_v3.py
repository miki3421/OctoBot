"""Result-free protocol for event-level BTC queue-flow research V3."""

from __future__ import annotations

import dataclasses
import hashlib
import json
import pathlib
import typing

from octobot.ai_strategy_lab import model as model_module
from octobot.ai_strategy_lab import scalping_strategy_search as v1
from octobot.ai_strategy_lab import scalping_strategy_search_v2 as v2


SCHEMA_VERSION = 1
PROTOCOL_VERSION = "btc_futures_scalping_queue_flow_v3"
PREREGISTRATION_DATE = "2026-08-27"
PARENT_PROTOCOL_VERSION = v2.PROTOCOL_VERSION
PARENT_PROTOCOL_SHA256 = (
    "22d0872fc679f1b9f01110409251a0a8dd792fa4844670f67c3da703c7744a04"
)
PARENT_REPORT_SHA256 = (
    "c298856cf1b42c331bbc34e06bb12c6cb7b059708152746683297401a26243cb"
)
SNAPSHOT_SHA256 = v1.SNAPSHOT_SHA256
SOURCE_START = v1.SOURCE_START
DEVELOPMENT_END = v2.DEVELOPMENT_END
DIAGNOSTIC_CONFIRMATION_END = v2.DIAGNOSTIC_CONFIRMATION_END
LOCKED_TEST_END = v2.LOCKED_TEST_END
QUEUE_WINDOWS_SECONDS = (2, 5, 15, 60)
QUEUE_WINDOW_FEATURES = (
    "directional_normalized_ofi_mean",
    "directional_depletion_asymmetry_mean",
    "directional_refill_asymmetry_mean",
    "directional_depth1_imbalance_mean",
    "directional_depth5_imbalance_mean",
    "directional_microprice_change_bps",
    "directional_quote_move_imbalance",
    "directional_aggressor_to_depth",
    "directional_ofi_trade_divergence",
    "normalized_ofi_abs_mean",
    "update_intensity",
    "depth1_mean",
    "depth5_mean",
    "top_depth_concentration_mean",
)
QUEUE_FEATURE_NAMES = tuple(
    f"q{window}_{name}"
    for window in QUEUE_WINDOWS_SECONDS
    for name in QUEUE_WINDOW_FEATURES
)
FEATURE_NAMES = v1.FEATURE_NAMES + QUEUE_FEATURE_NAMES
REGRESSION_TARGET_CLIP_BPS = 60.0
EXPECTED_RETURN_QUANTILES = (0.90, 0.95)
MINIMUM_DIRECTION_MARGIN_BPS = 2.0
BOOSTING_CONFIG = model_module.BoostingConfig(
    trees=48,
    max_depth=2,
    bins=24,
    learning_rate=0.06,
    l2=100.0,
    minimum_leaf_rows=400,
    minimum_gain=1.0,
    feature_fraction=0.75,
    seed=20260827,
)


def _json_hash(payload: dict) -> str:
    return hashlib.sha256(
        json.dumps(
            payload, sort_keys=True, separators=(",", ":")
        ).encode("utf-8")
    ).hexdigest()


def frozen_protocol() -> dict:
    """Return the immutable, result-free V3 evaluation protocol."""

    return {
        "schema_version": SCHEMA_VERSION,
        "protocol_version": PROTOCOL_VERSION,
        "preregistered_on": PREREGISTRATION_DATE,
        "status": "result_free_evaluation_protocol",
        "research_only": True,
        "public_data_only": True,
        "orders_authorized": False,
        "paper_orders_authorized": False,
        "automatic_promotion": False,
        "parent_rejection": {
            "protocol_version": PARENT_PROTOCOL_VERSION,
            "protocol_sha256": PARENT_PROTOCOL_SHA256,
            "report_sha256": PARENT_REPORT_SHA256,
            "lesson_used": (
                "V2 probability calibration was slightly informative but "
                "selected gross expectancy was far below taker costs"
            ),
            "economic_configurations_unchanged": True,
            "costs_unchanged": True,
            "thresholds_not_retuned_from_parent_results": True,
        },
        "frozen_source": {
            "snapshot_sha256": SNAPSHOT_SHA256,
            "start_inclusive": SOURCE_START,
            "pretest_end_exclusive": DIAGNOSTIC_CONFIRMATION_END,
            "locked_test": [
                DIAGNOSTIC_CONFIRMATION_END,
                LOCKED_TEST_END,
            ],
            "locked_test_not_materialized_at_preregistration": True,
        },
        "candidate_family": {
            "name": "event_level_queue_flow_expected_return",
            "decision_stride_seconds": v2.DECISION_STRIDE_SECONDS,
            "training_stride_seconds": v2.TRAINING_STRIDE_SECONDS,
            "one_trade_at_a_time": True,
            "directions": ["LONG", "SHORT"],
            "entry": "first executable top-of-book after 500ms",
            "primary_latency_ms": v2.PRIMARY_LATENCY_MS,
            "stress_latency_ms": v2.STRESS_LATENCY_MS,
            "configurations": list(v2.CONFIGURATIONS),
            "outcomes_reused_without_change": PARENT_PROTOCOL_VERSION,
            "decision_rule": (
                "choose the side with greater predicted net return only when "
                "it exceeds both zero and a calibration quantile and exceeds "
                "the opposite side by at least 2 bps"
            ),
            "expected_return_quantiles": list(EXPECTED_RETURN_QUANTILES),
            "minimum_direction_margin_bps": MINIMUM_DIRECTION_MARGIN_BPS,
            "selection_candidates": (
                len(v2.CONFIGURATIONS) * len(EXPECTED_RETURN_QUANTILES)
            ),
        },
        "features": {
            "schema": list(FEATURE_NAMES),
            "original_aggregate_features": len(v1.FEATURE_NAMES),
            "new_queue_flow_features": len(QUEUE_FEATURE_NAMES),
            "queue_windows_seconds": list(QUEUE_WINDOWS_SECONDS),
            "raw_event_clock": "received_ts_ns",
            "causal_at_decision_close": True,
            "directional_symmetry": True,
            "session_or_gap_reset_seconds": 5,
            "queue_dynamics": {
                "normalized_ofi": (
                    "Cont-style best-quote order-flow imbalance normalized by "
                    "the adjacent mean top-of-book depth"
                ),
                "depletion_and_refill": (
                    "signed best-quote depletion and refill asymmetry"
                ),
                "depth": (
                    "event-weighted level-1 and level-5 depth, imbalance and "
                    "top-level concentration"
                ),
                "price_response": (
                    "microprice changes and quote direction imbalance"
                ),
                "trade_interaction": (
                    "aggressor volume normalized by displayed depth and its "
                    "divergence from queue flow"
                ),
            },
        },
        "costs": {
            "fee_bps_per_fill": v2.FEE_BPS_PER_FILL,
            "slippage_bps_per_fill": v2.SLIPPAGE_BPS_PER_FILL,
            "fills": 2,
            "position_fraction": v2.POSITION_FRACTION,
            "stress_multiplier": v2.COST_STRESS_MULTIPLIER,
            "maker_fill_assumptions": False,
        },
        "model": {
            "name": "numpy_squared_error_gradient_boosting",
            "config": dataclasses.asdict(BOOSTING_CONFIG),
            "target": "realized primary net instrument return in bps",
            "target_clip_bps": REGRESSION_TARGET_CLIP_BPS,
            "model_families": 1,
            "regression_gate": (
                "out-of-sample MSE must beat a training-mean constant"
            ),
        },
        "validation": {
            "development": [SOURCE_START, DEVELOPMENT_END],
            "development_walk_forward_folds": v2.WALK_FORWARD_FOLDS,
            "purge_embargo_seconds": 900,
            "diagnostic_confirmation": [
                DEVELOPMENT_END,
                DIAGNOSTIC_CONFIRMATION_END,
            ],
            "diagnostic_confirmation_is_not_pristine": True,
            "locked_final_test": [
                DIAGNOSTIC_CONFIRMATION_END,
                LOCKED_TEST_END,
            ],
            "locked_test_policy": (
                "materialize once only if development and diagnostic "
                "confirmation both pass every gate"
            ),
            "no_mid_test_retuning": True,
        },
        "development_gate": {
            "minimum_oos_trades": 500,
            "minimum_net_profit_factor": 1.20,
            "maximum_drawdown_pct": 5.0,
            "minimum_positive_operating_days_pct": 55.0,
            "minimum_positive_folds": 4,
            "long_contribution_non_negative": True,
            "short_contribution_non_negative": True,
            "mse_better_than_training_mean_constant": True,
            "positive_under_doubled_cost_and_latency": True,
        },
        "confirmation_and_locked_gate": {
            "minimum_trades": 100,
            "minimum_net_profit_factor": 1.20,
            "maximum_drawdown_pct": 5.0,
            "minimum_positive_operating_days_pct": 55.0,
            "long_contribution_non_negative": True,
            "short_contribution_non_negative": True,
            "mse_better_than_training_mean_constant": True,
            "positive_under_doubled_cost_and_latency": True,
        },
        "multiple_testing_disclosure": (
            "one model family, two unchanged economic configurations and two "
            "predeclared expected-return quantiles are compared in development; "
            "the August 20-26 block remains the sole untouched test"
        ),
        "promotion_consequence": (
            "even a full pass permits only a manually approved, orderless "
            "shadow; it never authorizes paper or real orders"
        ),
        "results": None,
    }


def write_or_verify_protocol(
    path_value: typing.Union[str, pathlib.Path],
) -> dict:
    path = pathlib.Path(path_value).resolve()
    protocol = frozen_protocol()
    payload = {**protocol, "protocol_sha256": _json_hash(protocol)}
    if path.is_file():
        persisted = json.loads(path.read_text(encoding="utf-8"))
        if persisted != payload:
            raise ValueError("persisted scalping V3 protocol differs")
        return persisted
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(
        json.dumps(payload, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    temporary.replace(path)
    return payload


def _main() -> None:
    import argparse

    parser = argparse.ArgumentParser(
        description="Result-free event-level queue-flow research V3."
    )
    parser.add_argument("command", choices=("write-protocol",))
    parser.add_argument("--output", required=True)
    arguments = parser.parse_args()
    if arguments.command == "write-protocol":
        print(
            json.dumps(
                write_or_verify_protocol(arguments.output),
                indent=2,
                sort_keys=True,
            )
        )


if __name__ == "__main__":
    _main()
