"""Leakage-resistant evaluation of the frozen BTC Level 5 dataset.

The module is deliberately research-only.  It has no exchange client, order
API, paper broker integration, or automatic promotion path.  The result-free
implementation protocol is persisted and hashed before any economic label is
computed.
"""

from __future__ import annotations

import dataclasses
import hashlib
import json
import pathlib
import typing

from octobot.ai_strategy_lab import model as model_module


SCHEMA_VERSION = 1
PROTOCOL_VERSION = "btc_futures_scalping_micro_momentum_v1_eval1"
PREREGISTRATION_DATE = "2026-08-27"
PARENT_PROTOCOL_VERSION = "btc_futures_scalping_micro_momentum_v1"
PARENT_PROTOCOL_SHA256 = (
    "8a1e290680bed79e71a97e1012c04c4e5f6ee36bd5107f85a095c2152a9aa065"
)
SNAPSHOT_SHA256 = (
    "96020bbf554b87e6433748fa3586c4d9d07c819cddeeab2e6e90f24475f64bce"
)
SNAPSHOT_MANIFEST_SHA256 = (
    "9900ead58a9f6cad252d12c90c24944df75e4b968c40d858878792f182c4631c"
)
SOURCE_START = "2026-07-23T14:01:49+00:00"
SOURCE_END = "2026-08-26T14:10:57+00:00"
TRAIN_END = "2026-08-13T00:00:00+00:00"
SELECTION_END = "2026-08-20T00:00:00+00:00"
LOCKED_TEST_END = "2026-08-26T14:10:58+00:00"
DECISION_STRIDE_SECONDS = 5
TRAINING_STRIDE_SECONDS = 20
MAXIMUM_FEATURE_LOOKBACK_SECONDS = 300
PRIMARY_LATENCY_MS = 500
STRESS_LATENCY_MS = 1_000
TARGET_BPS = 40
STOP_BPS = 10
HORIZON_SECONDS = 120
FEE_BPS_PER_FILL = 6.0
SLIPPAGE_BPS_PER_FILL = 1.0
COST_STRESS_MULTIPLIER = 2.0
WALK_FORWARD_FOLDS = 5
EMBARGO_SECONDS = HORIZON_SECONDS
CALIBRATION_FRACTION = 0.20
PROBABILITY_QUANTILES = (0.90, 0.95, 0.975, 0.99)
DIRECTION_MARGIN = 0.02

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
    """Return the complete result-free implementation protocol."""

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
        "parent_protocol": {
            "version": PARENT_PROTOCOL_VERSION,
            "sha256": PARENT_PROTOCOL_SHA256,
        },
        "frozen_source": {
            "snapshot_sha256": SNAPSHOT_SHA256,
            "snapshot_manifest_sha256": SNAPSHOT_MANIFEST_SHA256,
            "start_inclusive": SOURCE_START,
            "end_inclusive": SOURCE_END,
            "exchange": "kucoin_futures",
            "symbol": "XBTUSDTM",
            "known_development_event": (
                "the 2026-07-27 sell-off was inspected previously and lies "
                "inside the development block only"
            ),
        },
        "candidate": {
            "family": "symmetric_directional_micro_momentum",
            "decision_stride_seconds": DECISION_STRIDE_SECONDS,
            "one_trade_at_a_time": True,
            "long_and_short": True,
            "entry": "first recorded top-of-book quote after latency",
            "exit": "executable opposite top-of-book or conservative barrier",
            "primary_latency_ms": PRIMARY_LATENCY_MS,
            "target_bps": TARGET_BPS,
            "stop_bps": STOP_BPS,
            "maximum_hold_seconds": HORIZON_SECONDS,
            "stop_wins_same_one_second_bucket": True,
            "configuration_reason": (
                "highest net reward-to-risk member of the already frozen "
                "grid and positive gross target after doubled fees/slippage"
            ),
        },
        "features": {
            "maximum_lookback_seconds": (
                MAXIMUM_FEATURE_LOOKBACK_SECONDS
            ),
            "windows_seconds": [5, 15, 30, 60],
            "context_seconds": [60, 300],
            "directional_symmetry": (
                "the same model receives sign-normalized LONG and SHORT rows"
            ),
            "names_by_window": [
                "directional_mid_return_bps",
                "directional_microprice_premium_bps_mean",
                "spread_bps_mean",
                "spread_bps_max",
                "directional_level5_book_imbalance_mean",
                "directional_level5_book_imbalance_slope",
                "directional_aggressor_size_imbalance",
                "directional_aggressor_count_imbalance",
                "book_event_intensity",
                "trade_event_intensity",
                "realized_mid_volatility_bps",
                "high_low_range_bps",
            ],
            "context_names": [
                "directional_one_minute_context_bps",
                "directional_five_minute_context_bps",
                "one_to_five_minute_regime_ratio",
                "utc_hour_sine",
                "utc_hour_cosine",
            ],
            "causality": (
                "every feature uses records received no later than the "
                "decision second close"
            ),
            "candidate_requires_continuous_lookback": True,
            "label_requires_continuous_future": True,
        },
        "labels_and_costs": {
            "target_before_stop_label": True,
            "timeouts_use_executable_deadline_quote": True,
            "fee_bps_per_fill": FEE_BPS_PER_FILL,
            "slippage_bps_per_fill": SLIPPAGE_BPS_PER_FILL,
            "fills_per_trade": 2,
            "primary_cost_multiplier": 1.0,
            "stress_cost_multiplier": COST_STRESS_MULTIPLIER,
            "stress_latency_ms": STRESS_LATENCY_MS,
            "retroactive_fills": False,
            "funding": (
                "excluded because no trade can span the eight-hour funding "
                "interval within the 120-second horizon"
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
            "training_stride_seconds": TRAINING_STRIDE_SECONDS,
            "calibration": "quantile_isotonic_on_latest_training_20pct",
            "calibration_fraction": CALIBRATION_FRACTION,
            "probability_quantiles": list(PROBABILITY_QUANTILES),
            "minimum_long_short_probability_margin": DIRECTION_MARGIN,
            "selection": (
                "lexicographic hard-gates-passed, stressed profit factor, "
                "stressed net return, trade count"
            ),
        },
        "temporal_validation": {
            "development": [SOURCE_START, TRAIN_END],
            "independent_selection": [TRAIN_END, SELECTION_END],
            "locked_final_test": [SELECTION_END, LOCKED_TEST_END],
            "walk_forward_folds_inside_development": WALK_FORWARD_FOLDS,
            "expanding_train": True,
            "embargo_seconds": EMBARGO_SECONDS,
            "locked_test_policy": (
                "do not compute labels, predictions, or metrics unless both "
                "development and independent selection gates pass"
            ),
            "no_mid_test_retuning": True,
        },
        "development_gate": {
            "minimum_oos_trades": 500,
            "minimum_net_profit_factor": 1.20,
            "maximum_drawdown_pct": 5.0,
            "minimum_positive_operating_days_pct": 55.0,
            "minimum_positive_folds": 4,
            "required_folds": WALK_FORWARD_FOLDS,
            "long_contribution_non_negative": True,
            "short_contribution_non_negative": True,
            "brier_better_than_constant_base_rate": True,
            "positive_under_doubled_cost_and_latency": True,
        },
        "selection_gate": {
            "minimum_trades": 100,
            "minimum_net_profit_factor": 1.20,
            "maximum_drawdown_pct": 5.0,
            "minimum_positive_operating_days_pct": 55.0,
            "long_contribution_non_negative": True,
            "short_contribution_non_negative": True,
            "brier_better_than_constant_base_rate": True,
            "positive_under_doubled_cost_and_latency": True,
        },
        "locked_test_gate": {
            "minimum_trades": 100,
            "minimum_net_profit_factor": 1.20,
            "maximum_drawdown_pct": 5.0,
            "minimum_positive_operating_days_pct": 55.0,
            "long_contribution_non_negative": True,
            "short_contribution_non_negative": True,
            "positive_under_doubled_cost_and_latency": True,
            "paper_shadow_consequence": (
                "passing permits only a separately approved research shadow"
            ),
        },
        "multiple_testing_disclosure": (
            "two model families and four predeclared probability quantiles "
            "are compared only inside development; the independent selection "
            "and locked test protect against choosing the best noise"
        ),
        "results": None,
    }


def write_or_verify_protocol(
    path_value: typing.Union[str, pathlib.Path],
) -> dict:
    """Atomically write the protocol once, or verify exact identity."""

    path = pathlib.Path(path_value).resolve()
    protocol = frozen_protocol()
    payload = {**protocol, "protocol_sha256": _json_hash(protocol)}
    if path.is_file():
        persisted = json.loads(path.read_text(encoding="utf-8"))
        if persisted != payload:
            raise ValueError("persisted scalping search protocol differs")
        return persisted
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(
        json.dumps(payload, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    temporary.replace(path)
    return payload

