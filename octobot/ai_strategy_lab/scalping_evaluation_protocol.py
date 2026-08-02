"""Frozen, result-free protocol for the BTC Level 5 scalping evaluation."""

from __future__ import annotations

import bisect
import datetime
import hashlib
import json
import pathlib
import typing


SCHEMA_VERSION = 1
PROTOCOL_VERSION = "btc_futures_scalping_micro_momentum_v1"
PREREGISTRATION_DATE = "2026-07-23"
FORWARD_START = "2026-07-23T14:01:49.079623+00:00"
MINIMUM_FORWARD_DAYS = 30.0
MINIMUM_COVERAGE = 0.95
MAXIMUM_HOLD_SECONDS = 120
EMBARGO_SECONDS = MAXIMUM_HOLD_SECONDS
WALK_FORWARD_FOLDS = 5
FEATURE_WINDOWS_SECONDS = (5, 15, 30, 60)
CONTEXT_WINDOWS_SECONDS = (60, 300)
TARGET_BPS = (15, 20, 30, 40)
STOP_BPS = (10, 15, 20, 30)
HORIZON_SECONDS = (15, 30, 60, 120)
LATENCY_MILLISECONDS = (250, 500, 1_000)
FEE_BPS_PER_FILL = 6.0
SLIPPAGE_BPS_PER_FILL = 1.0


def _json_hash(payload: dict) -> str:
    return hashlib.sha256(
        json.dumps(
            payload, sort_keys=True, separators=(",", ":")
        ).encode("utf-8")
    ).hexdigest()


def frozen_protocol() -> dict:
    """Return the immutable plan without labels, predictions or performance."""

    return {
        "schema_version": SCHEMA_VERSION,
        "protocol_version": PROTOCOL_VERSION,
        "preregistered_on": PREREGISTRATION_DATE,
        "forward_start": FORWARD_START,
        "status": "collection_only_until_readiness_gate",
        "research_only": True,
        "public_data_only": True,
        "orders_authorized": False,
        "paper_orders_authorized": False,
        "automatic_promotion": False,
        "performance_evaluation_before_gate": False,
        "source": {
            "exchange": "kucoin_futures",
            "symbol": "XBTUSDTM",
            "book_depth": 5,
            "book_push_interval_ms": 100,
            "aggregation_seconds": 1,
        },
        "features_at_decision_time": {
            "windows_seconds": list(FEATURE_WINDOWS_SECONDS),
            "context_seconds": list(CONTEXT_WINDOWS_SECONDS),
            "names": [
                "mid_return",
                "microprice_premium_bps",
                "spread_bps_mean",
                "spread_bps_max",
                "level5_book_imbalance_mean",
                "level5_book_imbalance_slope",
                "aggressor_size_imbalance",
                "aggressor_count_imbalance",
                "book_event_intensity",
                "trade_event_intensity",
                "realized_mid_volatility",
                "high_low_range_bps",
                "one_minute_directional_context",
                "five_minute_regime_context",
                "utc_hour_sine",
                "utc_hour_cosine",
            ],
            "causality": (
                "every feature ends at or before the decision timestamp"
            ),
        },
        "execution_and_labels": {
            "entry": "buy_at_ask_sell_at_bid_after_latency",
            "retroactive_fills": False,
            "stop_wins_same_timestamp_ties": True,
            "target_bps": list(TARGET_BPS),
            "stop_bps": list(STOP_BPS),
            "horizon_seconds": list(HORIZON_SECONDS),
            "maximum_hold_seconds": MAXIMUM_HOLD_SECONDS,
            "fee_bps_per_fill": FEE_BPS_PER_FILL,
            "slippage_bps_per_fill": SLIPPAGE_BPS_PER_FILL,
            "latency_milliseconds": list(LATENCY_MILLISECONDS),
            "stress": {
                "fee_and_slippage_multiplier": 2.0,
                "latency_multiplier": 2.0,
            },
        },
        "validation": {
            "kind": "expanding_purged_walk_forward",
            "folds": WALK_FORWARD_FOLDS,
            "embargo_seconds": EMBARGO_SECONDS,
            "minimum_forward_days": MINIMUM_FORWARD_DAYS,
            "minimum_coverage_pct": MINIMUM_COVERAGE * 100,
            "full_offline_integrity_required": True,
            "declared_gap_audit_required": True,
            "dataset_freeze_required": True,
            "no_mid_test_retuning": True,
        },
        "paper_shadow_gate": {
            "minimum_out_of_sample_trades": 500,
            "minimum_net_profit_factor": 1.20,
            "maximum_drawdown_pct": 5.0,
            "minimum_positive_operating_days_pct": 55.0,
            "long_contribution_non_negative": True,
            "short_contribution_non_negative": True,
            "positive_under_doubled_cost_and_latency": True,
        },
        "results": None,
    }


def write_or_verify_protocol(path_value: typing.Union[str, pathlib.Path]) -> dict:
    path = pathlib.Path(path_value).resolve()
    protocol = frozen_protocol()
    payload = {**protocol, "protocol_sha256": _json_hash(protocol)}
    if path.is_file():
        persisted = json.loads(path.read_text(encoding="utf-8"))
        if persisted != payload:
            raise ValueError("persisted scalping evaluation protocol differs")
        return persisted
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(
        json.dumps(payload, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    temporary.replace(path)
    return payload


def readiness(
    scalping: dict,
    *,
    frozen_snapshot_verified: bool = False,
) -> dict:
    checks = {
        "minimum_forward_days": (
            float(scalping.get("span_days", 0.0)) >= MINIMUM_FORWARD_DAYS
        ),
        "minimum_coverage": (
            float(scalping.get("coverage", 0.0)) >= MINIMUM_COVERAGE
        ),
        "database_operational": (
            scalping.get("database_operational") is True
        ),
        "offline_integrity_and_gap_audit": bool(frozen_snapshot_verified),
    }
    return {
        "protocol_version": PROTOCOL_VERSION,
        "ready": all(checks.values()),
        "checks": checks,
        "span_days": float(scalping.get("span_days", 0.0)),
        "coverage": float(scalping.get("coverage", 0.0)),
        "minimum_forward_days": MINIMUM_FORWARD_DAYS,
        "minimum_coverage": MINIMUM_COVERAGE,
        "performance_evaluation_authorized": all(checks.values()),
        "orders_authorized": False,
        "automatic_promotion": False,
        "warning": (
            "Readiness only unlocks an offline evaluation; it never "
            "authorizes paper or real orders."
        ),
    }


def round_trip_cost_bps(
    spread_bps: float,
    *,
    fee_bps_per_fill: float = FEE_BPS_PER_FILL,
    slippage_bps_per_fill: float = SLIPPAGE_BPS_PER_FILL,
) -> float:
    """Conservative taker round-trip cost used by every future label."""

    return (
        float(spread_bps)
        + 2 * float(fee_bps_per_fill)
        + 2 * float(slippage_bps_per_fill)
    )


def purged_walk_forward_splits(
    timestamps: typing.Sequence[int],
    *,
    folds: int = WALK_FORWARD_FOLDS,
    embargo_seconds: int = EMBARGO_SECONDS,
) -> list[dict]:
    """Create deterministic expanding splits without inspecting any outcome."""

    values = [int(value) for value in timestamps]
    if values != sorted(values) or len(values) != len(set(values)):
        raise ValueError("timestamps must be strictly increasing")
    if folds < 1 or len(values) < folds + 1:
        raise ValueError("insufficient timestamps for requested folds")
    test_size = len(values) // (folds + 1)
    if test_size < 1:
        raise ValueError("empty walk-forward test block")
    splits = []
    for fold in range(folds):
        test_start = (fold + 1) * test_size
        test_end = (
            len(values) if fold == folds - 1 else test_start + test_size
        )
        purge_before = values[test_start] - int(embargo_seconds)
        train_end = bisect.bisect_left(values, purge_before)
        if train_end < 1 or test_end <= test_start:
            raise ValueError("purging leaves an empty split")
        splits.append(
            {
                "fold": fold + 1,
                "train_start_index": 0,
                "train_end_index_exclusive": train_end,
                "test_start_index": test_start,
                "test_end_index_exclusive": test_end,
                "train_end_at": datetime.datetime.fromtimestamp(
                    values[train_end - 1], datetime.timezone.utc
                ).isoformat(),
                "test_start_at": datetime.datetime.fromtimestamp(
                    values[test_start], datetime.timezone.utc
                ).isoformat(),
                "embargo_seconds": int(embargo_seconds),
            }
        )
    return splits
