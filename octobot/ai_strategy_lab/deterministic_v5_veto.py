"""Audit a frozen V5 veto over recorded deterministic BTC decisions.

The module never generates a trading signal. It replays approved BUY/SELL
decisions already present in the append-only AI journal and compares the
unchanged fixed TP/SL economics with a counterfactual arm that may only reject
an entry when the frozen V5 surface does not support the same direction.
"""

from __future__ import annotations

import argparse
import dataclasses
import datetime
import hashlib
import json
import pathlib
import sqlite3
import typing

import numpy

from octobot.ai_strategy_lab import dataset as dataset_module
from octobot.ai_strategy_lab import funding as funding_module
from octobot.ai_strategy_lab import perfect_map_student as v1
from octobot.ai_strategy_lab import perfect_map_student_v5 as v5


SCHEMA_VERSION = 1
PROTOCOL_VERSION = "btc_deterministic_v5_veto_v1"
PREREGISTRATION_DATE = "2026-07-28"
SYMBOL = "BTC/USDT:USDT"
CANDLE_SECONDS = 900
TAKE_PROFIT_PCT = 4.0
STOP_LOSS_PCT = 2.0
HORIZON_BARS = 96
ROUND_TRIP_COST_PCT = 0.16
STRESS_ROUND_TRIP_COST_PCT = 0.24
V5_EXPECTED_NET_THRESHOLD_PCT = 0.075
V5_DIRECTION_MARGIN_PCT = 0.03
DIAGNOSTIC_REUSE_END_TIMESTAMP = int(
    datetime.datetime(
        2026, 7, 21, tzinfo=datetime.timezone.utc
    ).timestamp()
)
CRASH_CASE_DECISION_TIMESTAMP = int(
    datetime.datetime(
        2026, 7, 27, 16, 15, tzinfo=datetime.timezone.utc
    ).timestamp()
)


@dataclasses.dataclass(frozen=True)
class DecisionCandidate:
    decision_id: int
    decision_timestamp: int
    candle_index: int
    action: str
    direction: str
    confidence: float
    signal_strength: float
    long_expected_net_pct: float
    short_expected_net_pct: float
    selected_expected_net_pct: float
    opposite_expected_net_pct: float
    direction_margin_pct: float
    v5_preferred_direction: str
    target_probability_pct: float
    stop_probability_pct: float
    timeout_probability_pct: float
    target_profit_pct: float
    horizon_hours: int
    veto_allows: bool
    veto_reason: str


def _sha256(path: pathlib.Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _artifact(path_value: typing.Union[str, pathlib.Path]) -> dict:
    path = pathlib.Path(path_value).resolve()
    return {
        "path": str(path),
        "sha256": _sha256(path),
        "bytes": path.stat().st_size,
    }


def _json_hash(payload: dict) -> str:
    encoded = json.dumps(
        payload,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def frozen_protocol() -> dict:
    """Return the result-free design frozen before the first audit."""

    return {
        "schema_version": SCHEMA_VERSION,
        "protocol_version": PROTOCOL_VERSION,
        "preregistered_on": PREREGISTRATION_DATE,
        "status": "preregistered_design_only",
        "research_only": True,
        "orders_authorized": False,
        "paper_orders_authorized": False,
        "automatic_promotion": False,
        "candidate_source": {
            "journal_table": "ai_decisions",
            "symbol": SYMBOL,
            "model": "deterministic-alignment",
            "actions": ["BUY", "SELL"],
            "approved_only": True,
            "deduplication": "one unambiguous action per triggered_at",
            "decision_time": "closed 15m candle timestamp",
            "journal_used_for_training": False,
        },
        "veto": {
            "model": v5.PROTOCOL_VERSION,
            "model_retrained": False,
            "required_same_direction": True,
            "minimum_direction_expected_net_pct": (
                V5_EXPECTED_NET_THRESHOLD_PCT
            ),
            "minimum_margin_over_opposite_pct": (
                V5_DIRECTION_MARGIN_PCT
            ),
            "missing_or_invalid_input": "reject_entry_fail_closed",
            "can_create_signal": False,
            "can_reverse_signal": False,
        },
        "primary_comparison": {
            "only_difference": "V5 may veto an otherwise unchanged entry",
            "entry": "decision candle close",
            "one_trade_at_a_time": True,
            "take_profit_pct": TAKE_PROFIT_PCT,
            "stop_loss_pct": STOP_LOSS_PCT,
            "time_stop_hours": HORIZON_BARS / 4,
            "same_candle_policy": "stop_wins",
            "round_trip_cost_pct": ROUND_TRIP_COST_PCT,
            "stress_round_trip_cost_pct": (
                STRESS_ROUND_TRIP_COST_PCT
            ),
            "funding": "public settled rates when available",
        },
        "evidence": {
            "diagnostic_reuse": {
                "start": "2026-04-22",
                "end_inclusive": "2026-07-20",
            },
            "initial_forward": {
                "start": "2026-07-21",
                "minimum_days_before_promotion": 30,
                "promotion_allowed_by_this_audit": False,
            },
            "crash_case": {
                "decision_timestamp": CRASH_CASE_DECISION_TIMESTAMP,
                "may_choose_parameters": False,
            },
        },
        "gate_for_more_forward_observation": {
            "minimum_baseline_trades": 30,
            "minimum_guarded_trades": 10,
            "both_guarded_directions_required": True,
            "minimum_guarded_profit_factor": 1.10,
            "guarded_profit_factor_must_exceed_baseline": True,
            "guarded_compounded_return_must_exceed_baseline": True,
            "guarded_drawdown_must_not_exceed_baseline": True,
            "guarded_stress_compounded_return_non_negative": True,
            "does_not_authorize_shadow_or_orders": True,
        },
        "implementation": {
            "protocol_file_required_before_audit": True,
            "snapshot_max_decision_id": True,
            "persist_input_and_model_hashes": True,
            "persist_candidates_trades_and_report": True,
            "reloaded_v5_predictions_must_match_exactly": True,
            "results_in_this_protocol": False,
        },
    }


def write_protocol(
    output_value: typing.Union[str, pathlib.Path],
) -> pathlib.Path:
    output = pathlib.Path(output_value).resolve()
    output.mkdir(parents=True, exist_ok=True)
    protocol = frozen_protocol()
    path = output / "protocol.json"
    path.write_text(
        json.dumps(
            {
                **protocol,
                "protocol_sha256": _json_hash(protocol),
            },
            indent=2,
            sort_keys=True,
        )
        + "\n",
        encoding="utf-8",
    )
    return path


def _verify_protocol(output: pathlib.Path) -> dict:
    path = output / "protocol.json"
    if not path.is_file():
        raise FileNotFoundError(
            "write protocol.json before running the V5 veto audit"
        )
    expected = frozen_protocol()
    persisted = json.loads(path.read_text(encoding="utf-8"))
    if persisted.get("protocol_sha256") != _json_hash(expected):
        raise ValueError("persisted V5 veto protocol hash differs")
    without_hash = {
        key: value
        for key, value in persisted.items()
        if key != "protocol_sha256"
    }
    if without_hash != expected:
        raise ValueError("persisted V5 veto protocol content differs")
    return persisted


def load_decisions(
    path_value: typing.Union[str, pathlib.Path],
) -> tuple[list[dict], dict]:
    """Load a stable, read-only snapshot of eligible journal decisions."""

    path = pathlib.Path(path_value).resolve()
    if not path.is_file():
        raise FileNotFoundError(path)
    connection = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
    try:
        integrity = connection.execute("PRAGMA integrity_check").fetchone()
        if not integrity or integrity[0] != "ok":
            raise ValueError("AI decision journal failed integrity check")
        maximum_id = int(
            connection.execute(
                "SELECT COALESCE(MAX(id), 0) FROM ai_decisions"
            ).fetchone()[0]
        )
        rows = connection.execute(
            """
            SELECT
                id, triggered_at, action, confidence, signal_strength
            FROM ai_decisions
            WHERE id <= ?
              AND symbol = ?
              AND model = 'deterministic-alignment'
              AND approved = 1
              AND action IN ('BUY', 'SELL')
              AND triggered_at IS NOT NULL
            ORDER BY triggered_at, id
            """,
            (maximum_id, SYMBOL),
        ).fetchall()
    finally:
        connection.close()

    by_timestamp: dict[int, list[tuple]] = {}
    for row in rows:
        by_timestamp.setdefault(int(row[1]), []).append(row)
    decisions = []
    ambiguous_timestamps = []
    duplicate_rows = 0
    for timestamp, values in sorted(by_timestamp.items()):
        actions = {str(value[2]) for value in values}
        if len(actions) != 1:
            ambiguous_timestamps.append(timestamp)
            continue
        selected = values[-1]
        duplicate_rows += len(values) - 1
        decisions.append(
            {
                "decision_id": int(selected[0]),
                "decision_timestamp": timestamp,
                "action": str(selected[2]),
                "confidence": float(selected[3]),
                "signal_strength": float(selected[4]),
            }
        )
    return decisions, {
        "maximum_decision_id": maximum_id,
        "eligible_rows": len(rows),
        "deduplicated_decisions": len(decisions),
        "duplicate_rows_removed": duplicate_rows,
        "ambiguous_timestamps_rejected": len(ambiguous_timestamps),
        "ambiguous_timestamps": ambiguous_timestamps,
        "journal": _artifact(path),
        "integrity_check": "ok",
    }


def load_btc_candles(
    path_value: typing.Union[str, pathlib.Path],
) -> numpy.ndarray:
    path = pathlib.Path(path_value).resolve()
    series = dataset_module.load_collector_series(
        [path], required_time_frames=("15m",)
    )
    matching = [
        frames["15m"].values
        for symbol, frames in series.items()
        if symbol == SYMBOL
    ]
    if len(matching) != 1:
        raise ValueError(f"expected one {SYMBOL} 15m series")
    return matching[0]


def load_btc_funding(
    path_value: typing.Optional[typing.Union[str, pathlib.Path]],
) -> tuple[numpy.ndarray, numpy.ndarray]:
    if path_value is None:
        return (
            numpy.asarray([], dtype=numpy.int64),
            numpy.asarray([], dtype=float),
        )
    path = pathlib.Path(path_value).resolve()
    values = funding_module.load_funding(path)
    if SYMBOL not in values:
        raise ValueError(f"funding file has no {SYMBOL}")
    return values[SYMBOL]


def veto_decision(
    *,
    direction: str,
    long_expected_net_pct: float,
    short_expected_net_pct: float,
) -> tuple[bool, str, str, float, float]:
    """Return a fail-closed frozen veto decision."""

    scores = {
        v5.DIRECTIONS[0]: float(long_expected_net_pct),
        v5.DIRECTIONS[1]: float(short_expected_net_pct),
    }
    if not all(numpy.isfinite(value) for value in scores.values()):
        return False, "non_finite_v5_score", "NONE", float("nan"), float("nan")
    preferred = max(scores, key=scores.get)
    selected = scores[direction]
    opposite_direction = (
        v5.DIRECTIONS[1]
        if direction == v5.DIRECTIONS[0]
        else v5.DIRECTIONS[0]
    )
    opposite = scores[opposite_direction]
    margin = selected - opposite
    if preferred != direction:
        return False, "v5_prefers_opposite_direction", preferred, selected, margin
    if selected < V5_EXPECTED_NET_THRESHOLD_PCT:
        return False, "v5_expected_net_below_threshold", preferred, selected, margin
    if margin < V5_DIRECTION_MARGIN_PCT:
        return False, "v5_direction_margin_below_threshold", preferred, selected, margin
    return True, "allowed", preferred, selected, margin


def build_candidates(
    *,
    candles: numpy.ndarray,
    decisions: list[dict],
    model: v5.V5Model,
    veto_function: typing.Callable[
        ...,
        tuple[bool, str, str, float, float],
    ] = veto_decision,
) -> tuple[list[DecisionCandidate], dict, dict[str, numpy.ndarray]]:
    """Align recorded decisions with causal features and frozen V5 outputs."""

    features, feature_names = v1.sequence_features(candles)
    if feature_names != v1.student_feature_names():
        raise ValueError("V5 veto feature schema differs")
    predictions = model.predict(features)
    close_to_index = {
        int(open_timestamp) + CANDLE_SECONDS: index
        for index, open_timestamp in enumerate(candles[:, 0])
    }
    candidates = []
    missing_timestamp = 0
    invalid_feature = 0
    for decision in decisions:
        timestamp = int(decision["decision_timestamp"])
        candle_index = close_to_index.get(timestamp)
        if candle_index is None:
            missing_timestamp += 1
            continue
        if not numpy.all(numpy.isfinite(features[candle_index])):
            invalid_feature += 1
            continue
        action = str(decision["action"])
        direction = (
            v5.DIRECTIONS[0] if action == "BUY" else v5.DIRECTIONS[1]
        )
        direction_index = 0 if direction == v5.DIRECTIONS[0] else 1
        opposite_index = 1 - direction_index
        long_score = float(
            predictions["expected_net_pct"][candle_index, 0]
        )
        short_score = float(
            predictions["expected_net_pct"][candle_index, 1]
        )
        allowed, reason, preferred, selected, margin = veto_function(
            direction=direction,
            long_expected_net_pct=long_score,
            short_expected_net_pct=short_score,
        )
        target_index = int(
            predictions["target_index"][
                candle_index, direction_index
            ]
        )
        horizon_index = int(
            predictions["horizon_index"][
                candle_index, direction_index
            ]
        )
        candidates.append(
            DecisionCandidate(
                decision_id=int(decision["decision_id"]),
                decision_timestamp=timestamp,
                candle_index=candle_index,
                action=action,
                direction=direction,
                confidence=float(decision["confidence"]),
                signal_strength=float(decision["signal_strength"]),
                long_expected_net_pct=long_score,
                short_expected_net_pct=short_score,
                selected_expected_net_pct=selected,
                opposite_expected_net_pct=float(
                    predictions["expected_net_pct"][
                        candle_index, opposite_index
                    ]
                ),
                direction_margin_pct=margin,
                v5_preferred_direction=preferred,
                target_probability_pct=float(
                    predictions["target_probability"][
                        candle_index, direction_index
                    ]
                    * 100
                ),
                stop_probability_pct=float(
                    predictions["stop_probability"][
                        candle_index, direction_index
                    ]
                    * 100
                ),
                timeout_probability_pct=float(
                    predictions["timeout_probability"][
                        candle_index, direction_index
                    ]
                    * 100
                ),
                target_profit_pct=float(
                    v5.TARGET_PROFITS_PCT[target_index]
                ),
                horizon_hours=int(v5.HORIZON_HOURS[horizon_index]),
                veto_allows=allowed,
                veto_reason=reason,
            )
        )
    diagnostics = {
        "input_decisions": len(decisions),
        "aligned_candidates": len(candidates),
        "missing_timestamp_rejected": missing_timestamp,
        "invalid_feature_rejected": invalid_feature,
        "allowed_candidates": sum(
            candidate.veto_allows for candidate in candidates
        ),
        "rejected_candidates": sum(
            not candidate.veto_allows for candidate in candidates
        ),
        "veto_reasons": _counts(
            candidate.veto_reason for candidate in candidates
        ),
    }
    return candidates, diagnostics, predictions


def _counts(values: typing.Iterable[typing.Any]) -> dict[str, int]:
    result: dict[str, int] = {}
    for value in values:
        key = str(value)
        result[key] = result.get(key, 0) + 1
    return dict(sorted(result.items()))


def _funding_return_pct(
    *,
    direction: str,
    entry_timestamp: int,
    exit_timestamp: int,
    funding_timestamps: numpy.ndarray,
    funding_rates: numpy.ndarray,
) -> float:
    first = int(
        numpy.searchsorted(
            funding_timestamps, entry_timestamp, side="right"
        )
    )
    last = int(
        numpy.searchsorted(
            funding_timestamps, exit_timestamp, side="right"
        )
    )
    paid_rate = float(numpy.sum(funding_rates[first:last]))
    return (
        -paid_rate * 100
        if direction == v5.DIRECTIONS[0]
        else paid_rate * 100
    )


def simulate_fixed_trade(
    *,
    candles: numpy.ndarray,
    entry_index: int,
    direction: str,
    round_trip_cost_pct: float,
    funding_timestamps: numpy.ndarray,
    funding_rates: numpy.ndarray,
) -> typing.Optional[dict]:
    """Simulate the unchanged +4/-2 bracket with a 24-hour time stop."""

    required_final_index = entry_index + HORIZON_BARS
    if entry_index + 1 >= len(candles):
        return None
    horizon_is_complete = required_final_index < len(candles)
    final_index = min(required_final_index, len(candles) - 1)
    entry_price = float(candles[entry_index, 4])
    if direction == v5.DIRECTIONS[0]:
        target_price = entry_price * (1 + TAKE_PROFIT_PCT / 100)
        stop_price = entry_price * (1 - STOP_LOSS_PCT / 100)
    else:
        target_price = entry_price * (1 - TAKE_PROFIT_PCT / 100)
        stop_price = entry_price * (1 + STOP_LOSS_PCT / 100)
    exit_index = final_index
    exit_price = float(candles[final_index, 4])
    outcome = "TIMEOUT"
    for index in range(entry_index + 1, final_index + 1):
        high = float(candles[index, 2])
        low = float(candles[index, 3])
        if direction == v5.DIRECTIONS[0]:
            stopped = low <= stop_price
            targeted = high >= target_price
        else:
            stopped = high >= stop_price
            targeted = low <= target_price
        if stopped:
            exit_index = index
            exit_price = stop_price
            outcome = "STOP"
            break
        if targeted:
            exit_index = index
            exit_price = target_price
            outcome = "TARGET"
            break
    if outcome == "TIMEOUT" and not horizon_is_complete:
        return None
    direction_sign = 1.0 if direction == v5.DIRECTIONS[0] else -1.0
    gross_return_pct = (
        (exit_price / entry_price - 1) * 100 * direction_sign
    )
    entry_timestamp = int(candles[entry_index, 0]) + CANDLE_SECONDS
    exit_timestamp = int(candles[exit_index, 0]) + CANDLE_SECONDS
    funding_return_pct = _funding_return_pct(
        direction=direction,
        entry_timestamp=entry_timestamp,
        exit_timestamp=exit_timestamp,
        funding_timestamps=funding_timestamps,
        funding_rates=funding_rates,
    )
    net_return_pct = (
        gross_return_pct
        - round_trip_cost_pct
        + funding_return_pct
    )
    return {
        "entry_index": entry_index,
        "exit_index": exit_index,
        "entry_timestamp": entry_timestamp,
        "exit_timestamp": exit_timestamp,
        "entry_price": entry_price,
        "exit_price": exit_price,
        "direction": direction,
        "outcome": outcome,
        "gross_return_pct": gross_return_pct,
        "funding_return_pct": funding_return_pct,
        "round_trip_cost_pct": round_trip_cost_pct,
        "net_return_pct": net_return_pct,
        "duration_bars": exit_index - entry_index,
    }


def simulate_candidates(
    *,
    candles: numpy.ndarray,
    candidates: list[DecisionCandidate],
    guarded: bool,
    round_trip_cost_pct: float,
    funding_timestamps: numpy.ndarray,
    funding_rates: numpy.ndarray,
) -> tuple[list[dict], dict]:
    next_available = 0
    trades = []
    skipped_while_open = 0
    provisional = 0
    for candidate in candidates:
        if guarded and not candidate.veto_allows:
            continue
        if candidate.candle_index < next_available:
            skipped_while_open += 1
            continue
        trade = simulate_fixed_trade(
            candles=candles,
            entry_index=candidate.candle_index,
            direction=candidate.direction,
            round_trip_cost_pct=round_trip_cost_pct,
            funding_timestamps=funding_timestamps,
            funding_rates=funding_rates,
        )
        if trade is None:
            provisional += 1
            continue
        trade.update(
            {
                "decision_id": candidate.decision_id,
                "action": candidate.action,
                "confidence": candidate.confidence,
                "signal_strength": candidate.signal_strength,
                "veto_allows": candidate.veto_allows,
                "veto_reason": candidate.veto_reason,
                "selected_expected_net_pct": (
                    candidate.selected_expected_net_pct
                ),
                "opposite_expected_net_pct": (
                    candidate.opposite_expected_net_pct
                ),
                "direction_margin_pct": (
                    candidate.direction_margin_pct
                ),
            }
        )
        trades.append(trade)
        next_available = int(trade["exit_index"]) + 1
    return trades, {
        "skipped_while_position_open": skipped_while_open,
        "provisional_candidates": provisional,
    }


def trade_metrics(trades: list[dict]) -> dict:
    returns = numpy.asarray(
        [float(trade["net_return_pct"]) for trade in trades],
        dtype=float,
    )
    if not len(returns):
        return {
            "trades": 0,
            "wins": 0,
            "losses": 0,
            "win_rate_pct": None,
            "profit_factor": None,
            "compounded_net_return_pct": 0.0,
            "maximum_drawdown_pct": 0.0,
            "expectancy_pct": None,
            "by_direction": {
                direction: {"trades": 0, "net_return_sum_pct": 0.0}
                for direction in v5.DIRECTIONS
            },
            "outcomes": {},
        }
    wins = returns > 0
    gross_profit = float(numpy.sum(returns[wins]))
    gross_loss = float(-numpy.sum(returns[~wins]))
    equity = numpy.cumprod(1 + returns / 100)
    peaks = numpy.maximum.accumulate(
        numpy.concatenate((numpy.asarray([1.0]), equity))
    )[1:]
    drawdowns = (peaks - equity) / peaks * 100
    by_direction = {}
    for direction in v5.DIRECTIONS:
        selected = [
            trade
            for trade in trades
            if trade["direction"] == direction
        ]
        by_direction[direction] = {
            "trades": len(selected),
            "net_return_sum_pct": float(
                sum(float(trade["net_return_pct"]) for trade in selected)
            ),
        }
    return {
        "trades": len(trades),
        "wins": int(numpy.sum(wins)),
        "losses": int(numpy.sum(~wins)),
        "win_rate_pct": float(numpy.mean(wins) * 100),
        "profit_factor": (
            gross_profit / gross_loss
            if gross_loss > 0
            else None
        ),
        "compounded_net_return_pct": float((equity[-1] - 1) * 100),
        "maximum_drawdown_pct": float(
            numpy.max(drawdowns) if len(drawdowns) else 0.0
        ),
        "expectancy_pct": float(numpy.mean(returns)),
        "by_direction": by_direction,
        "outcomes": _counts(trade["outcome"] for trade in trades),
    }


def _split_trades(trades: list[dict], reused: bool) -> list[dict]:
    return [
        trade
        for trade in trades
        if (
            int(trade["entry_timestamp"])
            < DIAGNOSTIC_REUSE_END_TIMESTAMP
        )
        == reused
    ]


def _comparison(
    baseline: dict,
    guarded: dict,
    guarded_stress: dict,
) -> dict:
    baseline_pf = baseline["profit_factor"]
    guarded_pf = guarded["profit_factor"]
    gate = {
        "minimum_baseline_trades": baseline["trades"] >= 30,
        "minimum_guarded_trades": guarded["trades"] >= 10,
        "both_guarded_directions": all(
            guarded["by_direction"][direction]["trades"] > 0
            for direction in v5.DIRECTIONS
        ),
        "guarded_profit_factor_at_least_1_10": (
            guarded_pf is not None and guarded_pf >= 1.10
        ),
        "guarded_profit_factor_exceeds_baseline": (
            guarded_pf is not None
            and (
                baseline_pf is None
                or guarded_pf > baseline_pf
            )
        ),
        "guarded_return_exceeds_baseline": (
            guarded["compounded_net_return_pct"]
            > baseline["compounded_net_return_pct"]
        ),
        "guarded_drawdown_not_greater": (
            guarded["maximum_drawdown_pct"]
            <= baseline["maximum_drawdown_pct"]
        ),
        "guarded_stress_return_non_negative": (
            guarded_stress["compounded_net_return_pct"] >= 0
        ),
    }
    return {
        "results": gate,
        "passed": all(gate.values()),
        "automatic_promotion": False,
        "orders_authorized": False,
    }


def _serializable(value: typing.Any) -> typing.Any:
    if dataclasses.is_dataclass(value):
        return {
            field.name: _serializable(getattr(value, field.name))
            for field in dataclasses.fields(value)
        }
    if isinstance(value, dict):
        return {
            str(key): _serializable(item)
            for key, item in value.items()
        }
    if isinstance(value, (list, tuple)):
        return [_serializable(item) for item in value]
    if isinstance(value, numpy.generic):
        return value.item()
    if isinstance(value, numpy.ndarray):
        return value.tolist()
    return value


def run_audit(
    *,
    decision_db: typing.Union[str, pathlib.Path],
    collector: typing.Union[str, pathlib.Path],
    v5_model_directory: typing.Union[str, pathlib.Path],
    output_directory: typing.Union[str, pathlib.Path],
    funding_path: typing.Optional[
        typing.Union[str, pathlib.Path]
    ] = None,
    protocol_version: str = PROTOCOL_VERSION,
    protocol_verifier: typing.Callable[[pathlib.Path], dict] = (
        _verify_protocol
    ),
    veto_function: typing.Callable[
        ...,
        tuple[bool, str, str, float, float],
    ] = veto_decision,
) -> dict:
    output = pathlib.Path(output_directory).resolve()
    output.mkdir(parents=True, exist_ok=True)
    protocol = protocol_verifier(output)
    decisions, decision_snapshot = load_decisions(decision_db)
    collector_path = pathlib.Path(collector).resolve()
    model_directory = pathlib.Path(v5_model_directory).resolve()
    candles = load_btc_candles(collector_path)
    funding_timestamps, funding_rates = load_btc_funding(funding_path)
    model = v5.V5Model.load(model_directory)
    if (
        abs(
            model.expected_net_threshold_pct
            - V5_EXPECTED_NET_THRESHOLD_PCT
        )
        > 1e-12
    ):
        raise ValueError("persisted V5 threshold differs from veto protocol")
    candidates, candidate_diagnostics, predictions = build_candidates(
        candles=candles,
        decisions=decisions,
        model=model,
        veto_function=veto_function,
    )
    reloaded = v5.V5Model.load(model_directory)
    features, _ = v1.sequence_features(candles)
    replay = reloaded.predict(features)
    replay_differences = {}
    for key in (
        "probabilities",
        "expected_net_pct",
        "target_probability",
        "stop_probability",
        "timeout_probability",
    ):
        original_values = numpy.asarray(predictions[key], dtype=float)
        replay_values = numpy.asarray(replay[key], dtype=float)
        if not numpy.array_equal(
            original_values, replay_values, equal_nan=True
        ):
            raise ValueError(
                f"reloaded V5 prediction differs for {key}"
            )
        finite = numpy.isfinite(original_values)
        replay_differences[key] = (
            float(
                numpy.max(
                    numpy.abs(
                        original_values[finite] - replay_values[finite]
                    )
                )
            )
            if numpy.any(finite)
            else 0.0
        )

    baseline_trades, baseline_flow = simulate_candidates(
        candles=candles,
        candidates=candidates,
        guarded=False,
        round_trip_cost_pct=ROUND_TRIP_COST_PCT,
        funding_timestamps=funding_timestamps,
        funding_rates=funding_rates,
    )
    guarded_trades, guarded_flow = simulate_candidates(
        candles=candles,
        candidates=candidates,
        guarded=True,
        round_trip_cost_pct=ROUND_TRIP_COST_PCT,
        funding_timestamps=funding_timestamps,
        funding_rates=funding_rates,
    )
    stress_trades, stress_flow = simulate_candidates(
        candles=candles,
        candidates=candidates,
        guarded=True,
        round_trip_cost_pct=STRESS_ROUND_TRIP_COST_PCT,
        funding_timestamps=funding_timestamps,
        funding_rates=funding_rates,
    )

    metrics = {}
    for split_name, reused in (
        ("diagnostic_reuse", True),
        ("initial_forward", False),
    ):
        metrics[split_name] = {
            "baseline": trade_metrics(
                _split_trades(baseline_trades, reused)
            ),
            "guarded": trade_metrics(
                _split_trades(guarded_trades, reused)
            ),
            "guarded_stress": trade_metrics(
                _split_trades(stress_trades, reused)
            ),
        }
    gate = _comparison(
        metrics["diagnostic_reuse"]["baseline"],
        metrics["diagnostic_reuse"]["guarded"],
        metrics["diagnostic_reuse"]["guarded_stress"],
    )
    crash_candidates = [
        candidate
        for candidate in candidates
        if candidate.decision_timestamp
        == CRASH_CASE_DECISION_TIMESTAMP
    ]
    crash_case = {
        "decision_timestamp": CRASH_CASE_DECISION_TIMESTAMP,
        "found": len(crash_candidates) == 1,
        "candidate": (
            _serializable(crash_candidates[0])
            if len(crash_candidates) == 1
            else None
        ),
        "used_for_parameter_selection": False,
    }
    if len(crash_candidates) == 1:
        simulated = simulate_fixed_trade(
            candles=candles,
            entry_index=crash_candidates[0].candle_index,
            direction=crash_candidates[0].direction,
            round_trip_cost_pct=ROUND_TRIP_COST_PCT,
            funding_timestamps=funding_timestamps,
            funding_rates=funding_rates,
        )
        crash_case["fixed_bracket_outcome"] = simulated

    candidates_path = output / "candidates.json"
    candidates_path.write_text(
        json.dumps(
            [_serializable(candidate) for candidate in candidates],
            indent=2,
            sort_keys=True,
        )
        + "\n",
        encoding="utf-8",
    )
    trades_path = output / "trades.json"
    trades_path.write_text(
        json.dumps(
            {
                "baseline": baseline_trades,
                "guarded": guarded_trades,
                "guarded_stress": stress_trades,
            },
            indent=2,
            sort_keys=True,
        )
        + "\n",
        encoding="utf-8",
    )
    model_artifacts = {
        str(path.relative_to(model_directory)): _artifact(path)
        for path in sorted(model_directory.rglob("*"))
        if path.is_file()
    }
    report = {
        "schema_version": SCHEMA_VERSION,
        "protocol_version": protocol_version,
        "created_at": datetime.datetime.now(
            datetime.timezone.utc
        ).isoformat(),
        "research_only": True,
        "orders_authorized": False,
        "paper_orders_authorized": False,
        "automatic_promotion": False,
        "protocol": {
            "path": str((output / "protocol.json").resolve()),
            "sha256": protocol["protocol_sha256"],
        },
        "inputs": {
            "decision_snapshot": decision_snapshot,
            "collector": _artifact(collector_path),
            "funding": (
                _artifact(pathlib.Path(funding_path).resolve())
                if funding_path is not None
                else None
            ),
            "model_artifacts": model_artifacts,
            "candle_rows": len(candles),
            "first_candle_open_timestamp": int(candles[0, 0]),
            "last_candle_open_timestamp": int(candles[-1, 0]),
            "funding_points": len(funding_timestamps),
        },
        "candidate_diagnostics": candidate_diagnostics,
        "flow": {
            "baseline": baseline_flow,
            "guarded": guarded_flow,
            "guarded_stress": stress_flow,
        },
        "metrics": metrics,
        "gate_for_more_forward_observation": gate,
        "crash_case": crash_case,
        "reloaded_prediction_max_absolute_difference": (
            replay_differences
        ),
        "warning": (
            "This is a reused-data counterfactual veto audit. It cannot "
            "authorize paper or real orders and it does not validate V5."
        ),
    }
    report_path = output / "report.json"
    report_path.write_text(
        json.dumps(_serializable(report), indent=2, sort_keys=True)
        + "\n",
        encoding="utf-8",
    )
    artifacts = {
        "candidates": _artifact(candidates_path),
        "trades": _artifact(trades_path),
        "report": _artifact(report_path),
    }
    return {
        **report,
        "artifacts": artifacts,
        "report_path": str(report_path),
    }


def main(argv: typing.Optional[list[str]] = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--decision-db")
    parser.add_argument("--collector")
    parser.add_argument("--funding")
    parser.add_argument("--v5-model")
    parser.add_argument("--output", required=True)
    parser.add_argument(
        "--write-protocol",
        action="store_true",
        help="write the result-free protocol and exit",
    )
    args = parser.parse_args(argv)
    if args.write_protocol:
        path = write_protocol(args.output)
        print(json.dumps({"protocol": str(path)}, indent=2))
        return 0
    required = {
        "--decision-db": args.decision_db,
        "--collector": args.collector,
        "--v5-model": args.v5_model,
    }
    missing = [name for name, value in required.items() if not value]
    if missing:
        parser.error(f"missing required arguments: {', '.join(missing)}")
    result = run_audit(
        decision_db=args.decision_db,
        collector=args.collector,
        funding_path=args.funding,
        v5_model_directory=args.v5_model,
        output_directory=args.output,
    )
    print(
        json.dumps(
            {
                "report": result["report_path"],
                "gate": result["gate_for_more_forward_observation"],
                "metrics": result["metrics"],
                "crash_case": result["crash_case"],
            },
            indent=2,
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
