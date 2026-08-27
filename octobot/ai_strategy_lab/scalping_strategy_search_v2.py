"""Result-free protocol for cost-aware BTC microstructure search V2."""

from __future__ import annotations

import dataclasses
import hashlib
import json
import pathlib
import typing

from octobot.ai_strategy_lab import model as model_module
from octobot.ai_strategy_lab import scalping_strategy_search as v1


SCHEMA_VERSION = 1
PROTOCOL_VERSION = "btc_futures_scalping_cost_aware_v2"
PREREGISTRATION_DATE = "2026-08-27"
PARENT_PROTOCOL_VERSION = v1.PROTOCOL_VERSION
PARENT_PROTOCOL_SHA256 = (
    "4f97d7acf72482b31d9aae9ddc0b9a01c2a488394ff5b9546e5423fe380d0db7"
)
SNAPSHOT_SHA256 = v1.SNAPSHOT_SHA256
SOURCE_START = v1.SOURCE_START
DEVELOPMENT_END = v1.TRAIN_END
DIAGNOSTIC_CONFIRMATION_END = v1.SELECTION_END
LOCKED_TEST_END = v1.LOCKED_TEST_END
DECISION_STRIDE_SECONDS = 15
TRAINING_STRIDE_SECONDS = 60
FEATURE_LOOKBACK_SECONDS = 300
PRIMARY_LATENCY_MS = 500
STRESS_LATENCY_MS = 1_000
FEE_BPS_PER_FILL = 6.0
SLIPPAGE_BPS_PER_FILL = 1.0
COST_STRESS_MULTIPLIER = 2.0
POSITION_FRACTION = 0.10
WALK_FORWARD_FOLDS = 5
CALIBRATION_FRACTION = 0.20
PROBABILITY_QUANTILES = (0.90, 0.95, 0.975, 0.99)
DIRECTION_MARGIN = 0.02
CONFIGURATIONS = (
    {
        "name": "balanced_5m",
        "target_bps": 40,
        "stop_bps": 20,
        "horizon_seconds": 300,
    },
    {
        "name": "wide_15m",
        "target_bps": 60,
        "stop_bps": 30,
        "horizon_seconds": 900,
    },
)
LOGISTIC_CONFIG = model_module.LogisticConfig(
    epochs=12,
    batch_size=8192,
    learning_rate=0.01,
    l2=0.003,
    seed=20260827,
)
BOOSTING_CONFIG = model_module.BoostingConfig(
    trees=32,
    max_depth=2,
    bins=24,
    learning_rate=0.05,
    l2=3.0,
    minimum_leaf_rows=500,
    minimum_gain=0.001,
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
        "parent_failure": {
            "version": PARENT_PROTOCOL_VERSION,
            "sha256": PARENT_PROTOCOL_SHA256,
            "lesson_used": (
                "40 bps in 120 seconds had no positive fit labels in fold 1"
            ),
            "no_parent_threshold_retuning": True,
        },
        "frozen_source": {
            "snapshot_sha256": SNAPSHOT_SHA256,
            "start_inclusive": SOURCE_START,
            "diagnostic_reuse_end_exclusive": (
                DIAGNOSTIC_CONFIRMATION_END
            ),
            "locked_test": [
                DIAGNOSTIC_CONFIRMATION_END,
                LOCKED_TEST_END,
            ],
            "locked_test_not_materialized_at_preregistration": True,
        },
        "candidate_family": {
            "name": "cost_aware_microstructure_timing",
            "decision_stride_seconds": DECISION_STRIDE_SECONDS,
            "training_stride_seconds": TRAINING_STRIDE_SECONDS,
            "one_trade_at_a_time": True,
            "directions": ["LONG", "SHORT"],
            "entry": "first executable top-of-book after 500ms",
            "primary_latency_ms": PRIMARY_LATENCY_MS,
            "stress_latency_ms": STRESS_LATENCY_MS,
            "configurations": list(CONFIGURATIONS),
            "configuration_reason": (
                "predeclared gross reward/risk of 2:1 with longer horizons "
                "that can amortize a 14 bps primary round trip"
            ),
            "outcome_label": "net instrument return strictly above zero",
            "stop_wins_same_one_second_bucket": True,
            "timeouts_exit_at_executable_quote": True,
        },
        "features": {
            "schema": list(v1.FEATURE_NAMES),
            "lookback_seconds": FEATURE_LOOKBACK_SECONDS,
            "directional_symmetry": True,
            "causal_at_decision_close": True,
            "continuous_lookback_and_future_required": True,
        },
        "costs": {
            "fee_bps_per_fill": FEE_BPS_PER_FILL,
            "slippage_bps_per_fill": SLIPPAGE_BPS_PER_FILL,
            "fills": 2,
            "position_fraction": POSITION_FRACTION,
            "stress_multiplier": COST_STRESS_MULTIPLIER,
            "funding_excluded": (
                "the maximum 15-minute hold cannot cross an eight-hour "
                "funding settlement"
            ),
        },
        "models": {
            "candidates": [
                {
                    "name": "numpy_logistic",
                    "config": dataclasses.asdict(LOGISTIC_CONFIG),
                },
                {
                    "name": "numpy_gradient_boosting",
                    "config": dataclasses.asdict(BOOSTING_CONFIG),
                },
            ],
            "calibration": "quantile_isotonic_latest_training_20pct",
            "calibration_fraction": CALIBRATION_FRACTION,
            "probability_quantiles": list(PROBABILITY_QUANTILES),
            "minimum_direction_margin": DIRECTION_MARGIN,
            "selection_candidates": 16,
        },
        "validation": {
            "development": [SOURCE_START, DEVELOPMENT_END],
            "development_walk_forward_folds": WALK_FORWARD_FOLDS,
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
            "brier_better_than_constant": True,
            "positive_under_doubled_cost_and_latency": True,
        },
        "confirmation_and_locked_gate": {
            "minimum_trades": 100,
            "minimum_net_profit_factor": 1.20,
            "maximum_drawdown_pct": 5.0,
            "minimum_positive_operating_days_pct": 55.0,
            "long_contribution_non_negative": True,
            "short_contribution_non_negative": True,
            "brier_better_than_constant": True,
            "positive_under_doubled_cost_and_latency": True,
        },
        "multiple_testing_disclosure": (
            "two economic configurations, two model families and four "
            "probability quantiles are selected only in development; the "
            "20-26 August block is the sole untouched test"
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
            raise ValueError("persisted scalping V2 protocol differs")
        return persisted
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(
        json.dumps(payload, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    temporary.replace(path)
    return payload

