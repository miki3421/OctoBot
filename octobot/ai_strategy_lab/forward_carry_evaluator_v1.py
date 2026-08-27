"""Frozen offline evaluator for forward Carry V1.1.

The evaluator has no exchange client and cannot create orders.  Development
requires a ready, content-addressed forward dataset.  Confirmation additionally
requires a passed development report, its frozen model and the wall-clock gate
defined by the preregistered protocol.
"""

from __future__ import annotations

import argparse
import collections
import dataclasses
import datetime
import hashlib
import json
import math
import pathlib

import numpy

from octobot.ai_strategy_lab import forward_carry_dataset
from octobot.ai_strategy_lab import forward_carry_strategy_v1 as protocol_v1
from octobot.ai_strategy_lab import forward_carry_strategy_v1_1 as protocol_v1_1


SCHEMA_VERSION = 1
EVALUATOR_VERSION = "kucoin_forward_carry_evaluator_v1"
PRIMARY_HORIZON_HOURS = protocol_v1.PRIMARY_HORIZON_HOURS
PRIMARY_HORIZON_MS = PRIMARY_HORIZON_HOURS * 3_600_000
BUCKET_MS = 15 * 60 * 1000
SCHEDULE_SECONDS = (15 * 60, 8 * 3_600 + 15 * 60, 16 * 3_600 + 15 * 60)
EXIT_EXCLUSION_REASONS = {
    "missing_exact_exit_bucket",
    "exit_schema_incomplete",
    "insufficient_exit_depth",
}


@dataclasses.dataclass(frozen=True)
class RidgeModel:
    lower: numpy.ndarray
    upper: numpy.ndarray
    center: numpy.ndarray
    scale: numpy.ndarray
    coefficients: numpy.ndarray
    intercept: float
    log_indices: tuple[int, ...]
    feature_names: tuple[str, ...]
    alpha: float

    def predict(self, features: numpy.ndarray) -> numpy.ndarray:
        transformed = _transform_features(
            features,
            log_indices=self.log_indices,
        )
        clipped = numpy.clip(transformed, self.lower, self.upper)
        scaled = (clipped - self.center) / self.scale
        return scaled @ self.coefficients + self.intercept


def _json_hash(value: object) -> str:
    return hashlib.sha256(
        json.dumps(value, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()


def _sha256(path_value: str | pathlib.Path) -> str:
    path = pathlib.Path(path_value)
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def load_protocol(path_value: str | pathlib.Path) -> dict:
    path = pathlib.Path(path_value).resolve()
    persisted = json.loads(path.read_text(encoding="utf-8"))
    frozen = protocol_v1_1.frozen_protocol()
    expected = {
        **frozen,
        "protocol_sha256": protocol_v1._json_hash(frozen),
    }
    if persisted != expected:
        raise ValueError("Carry V1.1 protocol differs from frozen evaluator")
    return persisted


def phase_status(
    protocol: dict,
    evidence: dict,
    *,
    now: datetime.datetime | None = None,
    development_passed: bool = False,
    model_sha256: str | None = None,
) -> dict:
    now_utc = now or datetime.datetime.now(datetime.timezone.utc)
    if now_utc.tzinfo is None:
        raise ValueError("phase-status time must be timezone-aware")
    now_utc = now_utc.astimezone(datetime.timezone.utc)
    checks = evidence.get("checks", {})
    development_checks = {
        "protocol_is_v1_1": (
            protocol.get("protocol_version")
            == protocol_v1_1.PROTOCOL_VERSION
        ),
        "evidence_mode": evidence.get("mode") == "forward_evidence_only",
        "evidence_ready": evidence.get("strategy_development_ready") is True,
        "evidence_checks_pass": bool(checks) and all(checks.values()),
        "orders_not_authorized": (
            evidence.get("orders_authorized") is False
            and evidence.get("automatic_promotion") is False
            and evidence.get("real_income_authorized") is False
        ),
    }
    confirmation = protocol["validation"]["locked_confirmation"]
    earliest = datetime.datetime.fromisoformat(
        confirmation["earliest_open_utc"]
    )
    confirmation_checks = {
        **development_checks,
        "development_gate_passed": development_passed,
        "model_hash_frozen": (
            isinstance(model_sha256, str) and len(model_sha256) == 64
        ),
        "confirmation_clock_reached": now_utc >= earliest,
    }
    return {
        "schema_version": SCHEMA_VERSION,
        "evaluator_version": EVALUATOR_VERSION,
        "now_utc": now_utc.isoformat(),
        "development": {
            "allowed": all(development_checks.values()),
            "checks": development_checks,
        },
        "confirmation": {
            "allowed": all(confirmation_checks.values()),
            "checks": confirmation_checks,
            "earliest_open_utc": earliest.isoformat(),
        },
        "orders_authorized": False,
        "paper_orders_authorized": False,
        "automatic_promotion": False,
    }


def fit_ridge_model(
    features: numpy.ndarray,
    target: numpy.ndarray,
    protocol: dict,
) -> RidgeModel:
    features = numpy.asarray(features, dtype=numpy.float64)
    target = numpy.asarray(target, dtype=numpy.float64)
    if features.ndim != 2 or target.shape != (len(features),):
        raise ValueError("invalid Carry V1 ridge training shape")
    if len(features) <= features.shape[1]:
        raise ValueError("insufficient Carry V1 ridge training rows")
    if not numpy.all(numpy.isfinite(features)) or not numpy.all(
        numpy.isfinite(target)
    ):
        raise ValueError("non-finite Carry V1 ridge training value")
    names = tuple(protocol["dataset"]["feature_names"])
    model_protocol = protocol["candidate"]["model"]
    log_indices = tuple(
        names.index(name) for name in model_protocol["log1p_features"]
    )
    transformed = _transform_features(features, log_indices=log_indices)
    lower = numpy.quantile(transformed, 0.01, axis=0)
    upper = numpy.quantile(transformed, 0.99, axis=0)
    clipped = numpy.clip(transformed, lower, upper)
    center = numpy.median(clipped, axis=0)
    q25 = numpy.quantile(clipped, 0.25, axis=0)
    q75 = numpy.quantile(clipped, 0.75, axis=0)
    scale = q75 - q25
    scale[scale == 0] = 1.0
    scaled = (clipped - center) / scale
    design = numpy.column_stack((numpy.ones(len(scaled)), scaled))
    alpha = float(model_protocol["alpha"])
    penalty = numpy.eye(design.shape[1], dtype=numpy.float64) * alpha
    penalty[0, 0] = 0.0
    coefficients = numpy.linalg.pinv(design.T @ design + penalty) @ (
        design.T @ target
    )
    model = RidgeModel(
        lower=lower,
        upper=upper,
        center=center,
        scale=scale,
        coefficients=coefficients[1:],
        intercept=float(coefficients[0]),
        log_indices=log_indices,
        feature_names=names,
        alpha=alpha,
    )
    if not numpy.all(numpy.isfinite(model.predict(features))):
        raise ValueError("Carry V1 ridge produced non-finite predictions")
    return model


def _transform_features(
    features: numpy.ndarray,
    *,
    log_indices: tuple[int, ...],
) -> numpy.ndarray:
    values = numpy.asarray(features, dtype=numpy.float64).copy()
    for index in log_indices:
        if numpy.any(values[:, index] < 0):
            raise ValueError("Carry V1 log feature cannot be negative")
        values[:, index] = numpy.log1p(values[:, index])
    return values


def save_model(
    model: RidgeModel,
    path_value: str | pathlib.Path,
    *,
    protocol_sha256: str,
    dataset_sha256: str,
    dataset_manifest_sha256: str,
    training_rows: int,
) -> dict:
    path = pathlib.Path(path_value).resolve()
    payload = {
        "schema_version": SCHEMA_VERSION,
        "evaluator_version": EVALUATOR_VERSION,
        "protocol_version": protocol_v1_1.PROTOCOL_VERSION,
        "protocol_sha256": protocol_sha256,
        "dataset_sha256": dataset_sha256,
        "dataset_manifest_sha256": dataset_manifest_sha256,
        "training_rows": int(training_rows),
        "feature_names": list(model.feature_names),
        "alpha": model.alpha,
        "log_indices": list(model.log_indices),
        "lower": model.lower.tolist(),
        "upper": model.upper.tolist(),
        "center": model.center.tolist(),
        "scale": model.scale.tolist(),
        "coefficients": model.coefficients.tolist(),
        "intercept": model.intercept,
        "orders_authorized": False,
        "automatic_promotion": False,
    }
    payload["model_sha256"] = _json_hash(payload)
    _atomic_json(path, payload)
    loaded, persisted = load_model(
        path,
        expected_protocol_sha256=protocol_sha256,
    )
    probe = numpy.vstack((model.lower, model.upper)).copy()
    for index in model.log_indices:
        probe[:, index] = numpy.expm1(probe[:, index])
    if not numpy.allclose(
        model.predict(probe),
        loaded.predict(probe),
        rtol=0,
        atol=0,
    ):
        raise ValueError("persisted Carry V1 model is not reproducible")
    return persisted


def load_model(
    path_value: str | pathlib.Path,
    *,
    expected_protocol_sha256: str,
) -> tuple[RidgeModel, dict]:
    path = pathlib.Path(path_value).resolve()
    payload = json.loads(path.read_text(encoding="utf-8"))
    model_hash = payload.pop("model_sha256", None)
    if model_hash != _json_hash(payload):
        raise ValueError("Carry V1 model hash mismatch")
    payload["model_sha256"] = model_hash
    if payload.get("protocol_sha256") != expected_protocol_sha256:
        raise ValueError("Carry V1 model protocol hash mismatch")
    if (
        payload.get("schema_version") != SCHEMA_VERSION
        or payload.get("evaluator_version") != EVALUATOR_VERSION
        or payload.get("protocol_version") != protocol_v1_1.PROTOCOL_VERSION
        or int(payload.get("training_rows", 0)) <= 0
        or not isinstance(payload.get("dataset_sha256"), str)
        or len(payload["dataset_sha256"]) != 64
        or not isinstance(payload.get("dataset_manifest_sha256"), str)
        or len(payload["dataset_manifest_sha256"]) != 64
        or payload.get("orders_authorized") is not False
        or payload.get("automatic_promotion") is not False
    ):
        raise ValueError("Carry V1 model safety invariant failed")
    names = tuple(payload["feature_names"])
    expected_names = tuple(forward_carry_dataset.FEATURE_NAMES)
    if names != expected_names:
        raise ValueError("Carry V1 model feature schema mismatch")
    model = RidgeModel(
        lower=numpy.asarray(payload["lower"], dtype=numpy.float64),
        upper=numpy.asarray(payload["upper"], dtype=numpy.float64),
        center=numpy.asarray(payload["center"], dtype=numpy.float64),
        scale=numpy.asarray(payload["scale"], dtype=numpy.float64),
        coefficients=numpy.asarray(
            payload["coefficients"], dtype=numpy.float64
        ),
        intercept=float(payload["intercept"]),
        log_indices=tuple(int(value) for value in payload["log_indices"]),
        feature_names=names,
        alpha=float(payload["alpha"]),
    )
    lengths = {
        len(model.lower),
        len(model.upper),
        len(model.center),
        len(model.scale),
        len(model.coefficients),
        len(names),
    }
    if lengths != {len(expected_names)}:
        raise ValueError("Carry V1 model vector length mismatch")
    arrays = (
        model.lower,
        model.upper,
        model.center,
        model.scale,
        model.coefficients,
    )
    if (
        any(not numpy.all(numpy.isfinite(value)) for value in arrays)
        or not math.isfinite(model.intercept)
        or not math.isfinite(model.alpha)
        or model.alpha <= 0
        or numpy.any(model.lower > model.upper)
        or numpy.any(model.scale <= 0)
        or len(set(model.log_indices)) != len(model.log_indices)
        or any(
            index < 0 or index >= len(expected_names)
            for index in model.log_indices
        )
    ):
        raise ValueError("Carry V1 model numerical invariant failed")
    return model, payload


def base_candidate_mask(dataset: dict, protocol: dict) -> numpy.ndarray:
    names = tuple(dataset["feature_names"])
    if names != tuple(protocol["dataset"]["feature_names"]):
        raise ValueError("Carry V1 dataset feature schema differs")
    features = dataset["features"]
    current = features[:, names.index("current_funding_rate")]
    predicted = features[:, names.index("predicted_funding_rate_filled")]
    predicted_available = features[
        :, names.index("predicted_funding_available")
    ]
    entry_capacity = features[
        :, names.index("entry_capacity_usdt_depth20")
    ]
    exit_capacity = features[
        :, names.index("instant_exit_capacity_usdt_depth20")
    ]
    minimum_capacity = float(
        protocol["candidate"]["eligibility"][
            "minimum_entry_capacity_usdt"
        ]
    )
    seconds = (dataset["entry_timestamp_ms"] // 1000) % 86_400
    scheduled = numpy.isin(seconds, SCHEDULE_SECONDS)
    primary = dataset["horizon_hours"] == PRIMARY_HORIZON_HOURS
    return (
        scheduled
        & primary
        & (current > 0)
        & ((predicted_available < 0.5) | (predicted >= 0))
        & (entry_capacity >= minimum_capacity)
        & (exit_capacity >= minimum_capacity)
    )


def walk_forward_predictions(
    dataset: dict,
    protocol: dict,
    *,
    omitted_training_symbol: str | None = None,
) -> tuple[numpy.ndarray, numpy.ndarray, list[dict]]:
    mask = base_candidate_mask(dataset, protocol)
    predictions = numpy.full(len(mask), numpy.nan, dtype=numpy.float64)
    fold_ids = numpy.full(len(mask), -1, dtype=numpy.int16)
    folds = []
    entries = dataset["entry_timestamp_ms"]
    for fold_id, fold in enumerate(
        protocol["validation"]["development"]["walk_forward_folds"]
    ):
        train_end = _timestamp_ms(
            fold["training_entry_end_exclusive_utc"]
        )
        test_start = _timestamp_ms(fold["test_start_utc"])
        test_end = _timestamp_ms(fold["test_end_exclusive_utc"])
        train = mask & (entries < train_end)
        if omitted_training_symbol is not None:
            train &= dataset["symbols"] != omitted_training_symbol
        test = mask & (entries >= test_start) & (entries < test_end)
        if not numpy.any(test):
            raise ValueError(f"Carry V1 fold {fold_id} has no test rows")
        model = fit_ridge_model(
            dataset["features"][train],
            dataset["net_pair_return"][train],
            protocol,
        )
        predictions[test] = model.predict(dataset["features"][test])
        fold_ids[test] = fold_id
        folds.append(
            {
                "fold": fold_id,
                "training_rows": int(numpy.sum(train)),
                "test_rows": int(numpy.sum(test)),
                "training_entry_end_exclusive_utc": (
                    fold["training_entry_end_exclusive_utc"]
                ),
                "test_start_utc": fold["test_start_utc"],
                "test_end_exclusive_utc": fold["test_end_exclusive_utc"],
            }
        )
    return predictions, fold_ids, folds


def fit_final_development_model(
    dataset: dict,
    protocol: dict,
) -> tuple[RidgeModel, int]:
    mask = base_candidate_mask(dataset, protocol)
    end = _timestamp_ms(
        protocol["validation"]["development"][
            "final_fit_entry_end_exclusive_utc"
        ]
    )
    training = mask & (dataset["entry_timestamp_ms"] < end)
    model = fit_ridge_model(
        dataset["features"][training],
        dataset["net_pair_return"][training],
        protocol,
    )
    return model, int(numpy.sum(training))


def select_portfolio(
    dataset: dict,
    scores: numpy.ndarray,
    protocol: dict,
    *,
    start_ms: int,
    end_ms: int,
    fold_ids: numpy.ndarray | None = None,
    apply_prediction_gate: bool = True,
) -> list[dict]:
    entries = dataset["entry_timestamp_ms"]
    eligible = base_candidate_mask(dataset, protocol)
    selectable = (
        eligible
        & numpy.isfinite(scores)
        & (entries >= start_ms)
        & (entries < end_ms)
    )
    by_timestamp: dict[int, list[int]] = collections.defaultdict(list)
    for row in numpy.flatnonzero(selectable):
        by_timestamp[int(entries[row])].append(int(row))
    threshold = float(
        protocol["candidate"]["entry_gate"][
            "minimum_predicted_net_return"
        ]
    )
    maximum_pairs = int(
        protocol["candidate"]["portfolio"][
            "maximum_concurrent_pairs"
        ]
    )
    open_trades = []
    selected = []
    for timestamp in sorted(by_timestamp):
        open_trades = [
            trade for trade in open_trades if trade["exit_timestamp_ms"] > timestamp
        ]
        open_symbols = {trade["symbol"] for trade in open_trades}
        candidates = sorted(
            by_timestamp[timestamp],
            key=lambda row: (-float(scores[row]), str(dataset["symbols"][row])),
        )
        for row in candidates:
            score = float(scores[row])
            if apply_prediction_gate and score < threshold:
                break
            symbol = str(dataset["symbols"][row])
            if symbol in open_symbols or len(open_trades) >= maximum_pairs:
                continue
            trade = _trade_from_row(
                dataset,
                row,
                score=score,
                fold_id=(None if fold_ids is None else int(fold_ids[row])),
            )
            selected.append(trade)
            open_trades.append(trade)
            open_symbols.add(symbol)
    return selected


def _trade_from_row(dataset, row, *, score, fold_id):
    return {
        "row": int(row),
        "symbol": str(dataset["symbols"][row]),
        "entry_timestamp_ms": int(dataset["entry_timestamp_ms"][row]),
        "exit_timestamp_ms": int(dataset["exit_timestamp_ms"][row]),
        "score": float(score),
        "fold": fold_id,
        "spot_price_return": float(dataset["spot_price_return"][row]),
        "futures_price_return": float(dataset["futures_price_return"][row]),
        "settled_funding_return": float(
            dataset["settled_funding_return"][row]
        ),
        "conservative_fee_return": float(
            dataset["conservative_fee_return"][row]
        ),
        "net_pair_return": float(dataset["net_pair_return"][row]),
    }


def stress_trades(dataset: dict, trades: list[dict]) -> tuple[list[dict], int]:
    lookup = {
        (
            int(dataset["entry_timestamp_ms"][row]),
            str(dataset["symbols"][row]),
            int(dataset["horizon_hours"][row]),
        ): row
        for row in range(len(dataset["entry_timestamp_ms"]))
    }
    stressed = []
    missing = 0
    for trade in trades:
        row = lookup.get(
            (
                trade["entry_timestamp_ms"] + BUCKET_MS,
                trade["symbol"],
                PRIMARY_HORIZON_HOURS,
            )
        )
        if row is None:
            missing += 1
            continue
        value = _trade_from_row(
            dataset,
            row,
            score=trade["score"],
            fold_id=trade["fold"],
        )
        value["net_pair_return"] -= value["conservative_fee_return"]
        value["source_signal_entry_timestamp_ms"] = trade[
            "entry_timestamp_ms"
        ]
        stressed.append(value)
    return stressed, missing


def exclusion_audit(
    dataset: dict,
    *,
    start_ms: int,
    end_ms: int,
) -> dict:
    manifest = dataset["manifest"]
    successes = 0
    for timestamp, horizon in zip(
        dataset["entry_timestamp_ms"], dataset["horizon_hours"]
    ):
        seconds = (int(timestamp) // 1000) % 86_400
        if (
            int(horizon) == PRIMARY_HORIZON_HOURS
            and start_ms <= int(timestamp) < end_ms
            and seconds in SCHEDULE_SECONDS
        ):
            successes += 1
    exclusions = 0
    exit_exclusions = 0
    for event in manifest.get("exclusion_events", []):
        timestamp = int(event["entry_timestamp_ms"])
        seconds = (timestamp // 1000) % 86_400
        if (
            int(event["horizon_hours"]) == PRIMARY_HORIZON_HOURS
            and start_ms <= timestamp < end_ms
            and seconds in SCHEDULE_SECONDS
        ):
            exclusions += 1
            if event["reason"] in EXIT_EXCLUSION_REASONS:
                exit_exclusions += 1
    attempts = successes + exclusions
    fraction = exit_exclusions / attempts if attempts else 1.0
    return {
        "successful_rows": successes,
        "excluded_rows": exclusions,
        "exit_excluded_rows": exit_exclusions,
        "attempted_rows": attempts,
        "future_exit_exclusion_fraction": fraction,
    }


def endpoint_metrics(
    trades: list[dict],
    protocol: dict,
    *,
    mark_to_market: dict | None = None,
) -> dict:
    capital = float(
        protocol["candidate"]["portfolio"]["initial_capital_usdt"]
    )
    gross_per_trade = float(protocol["dataset"]["paired_gross_capital_usdt"])
    pnl = numpy.asarray(
        [trade["net_pair_return"] * gross_per_trade for trade in trades],
        dtype=numpy.float64,
    )
    gains = float(numpy.sum(pnl[pnl > 0]))
    losses = float(-numpy.sum(pnl[pnl < 0]))
    profit_factor = (
        gains / losses if losses > 0 else (math.inf if gains > 0 else 0.0)
    )
    by_symbol: dict[str, dict] = {}
    for trade, value in zip(trades, pnl):
        summary = by_symbol.setdefault(
            trade["symbol"], {"trades": 0, "pnl_quote": 0.0, "gross_profit": 0.0}
        )
        summary["trades"] += 1
        summary["pnl_quote"] += float(value)
        summary["gross_profit"] += max(float(value), 0.0)
    total_trades = len(trades)
    maximum_trade_fraction = max(
        (value["trades"] / total_trades for value in by_symbol.values()),
        default=0.0,
    )
    maximum_gross_profit_fraction = max(
        (value["gross_profit"] / gains for value in by_symbol.values()),
        default=0.0,
    ) if gains > 0 else 0.0
    weekly = collections.defaultdict(float)
    fold_pnl = collections.defaultdict(float)
    for trade, value in zip(trades, pnl):
        exit_at = datetime.datetime.fromtimestamp(
            trade["exit_timestamp_ms"] / 1000,
            tz=datetime.timezone.utc,
        )
        year, week, _ = exit_at.isocalendar()
        weekly[f"{year}-W{week:02d}"] += float(value)
        if trade.get("fold") is not None and trade["fold"] >= 0:
            fold_pnl[int(trade["fold"])] += float(value)
    realized_curve = capital + numpy.cumsum(
        [value for _, value in sorted(zip(
            [trade["exit_timestamp_ms"] for trade in trades], pnl
        ))]
    ) if total_trades else numpy.asarray([capital])
    realized_drawdown = _maximum_drawdown(realized_curve)
    mtm = mark_to_market or {
        "maximum_drawdown": realized_drawdown,
        "missing_intervals": None,
        "unpriced_intervals": None,
        "complete": False,
    }
    return {
        "closed_pairs": total_trades,
        "wins": int(numpy.sum(pnl > 0)),
        "win_rate": float(numpy.mean(pnl > 0)) if total_trades else 0.0,
        "gross_profit_quote": gains,
        "gross_loss_quote": losses,
        "profit_factor": profit_factor,
        "total_pnl_quote": float(numpy.sum(pnl)),
        "total_return": float(numpy.sum(pnl) / capital),
        "expectancy_quote": float(numpy.mean(pnl)) if total_trades else 0.0,
        "selected_symbols": len(by_symbol),
        "maximum_single_symbol_trade_fraction": maximum_trade_fraction,
        "maximum_single_symbol_gross_profit_fraction": (
            maximum_gross_profit_fraction
        ),
        "positive_operating_week_ratio": (
            sum(value > 0 for value in weekly.values()) / len(weekly)
            if weekly else 0.0
        ),
        "positive_walk_forward_folds": sum(
            value > 0 for value in fold_pnl.values()
        ),
        "by_symbol": by_symbol,
        "weekly_pnl_quote": dict(sorted(weekly.items())),
        "fold_pnl_quote": {
            str(key): value for key, value in sorted(fold_pnl.items())
        },
        "realized_only_maximum_drawdown": realized_drawdown,
        "mark_to_market": mtm,
    }


def mark_to_market_portfolios(
    journal_path: str | pathlib.Path,
    portfolios: dict[str, list[dict]],
    protocol: dict,
) -> dict[str, dict]:
    contexts = {
        name: _portfolio_context(trades, protocol)
        for name, trades in portfolios.items()
    }
    active_ranges = [
        (trade["entry_timestamp_ms"], trade["exit_timestamp_ms"])
        for trades in portfolios.values()
        for trade in trades
    ]
    if not active_ranges:
        return {
            name: {
                "maximum_drawdown": 0.0,
                "missing_intervals": 0,
                "unpriced_intervals": 0,
                "complete": True,
                "equity_points": 0,
            }
            for name in portfolios
        }
    first = min(value[0] for value in active_ranges)
    last = max(value[1] for value in active_ranges)
    with pathlib.Path(journal_path).open("r", encoding="utf-8") as stream:
        for line in stream:
            if not line.strip():
                continue
            record = json.loads(line)
            timestamp = int(
                datetime.datetime.fromisoformat(
                    record["bucket_start_utc"]
                ).timestamp()
                * 1000
            )
            if timestamp < first:
                continue
            if timestamp > last:
                break
            for context in contexts.values():
                _mark_context(context, record, timestamp, protocol)
    result = {}
    for name, context in contexts.items():
        unprocessed = sum(len(values) for values in context["opens"].values())
        complete = (
            not context["active"]
            and unprocessed == 0
            and context["unpriced_intervals"] == 0
        )
        result[name] = {
            "maximum_drawdown": _maximum_drawdown(context["equity"]),
            "missing_intervals": context["missing_intervals"],
            "unpriced_intervals": context["unpriced_intervals"],
            "complete": complete,
            "equity_points": len(context["equity"]),
            "minimum_equity": min(context["equity"], default=context["capital"]),
            "final_realized_equity": context["capital"] + context["realized"],
        }
    return result


def _portfolio_context(trades, protocol):
    opens = collections.defaultdict(list)
    for identifier, trade in enumerate(trades):
        opens[trade["entry_timestamp_ms"]].append((identifier, trade))
    return {
        "opens": opens,
        "active": {},
        "realized": 0.0,
        "capital": float(
            protocol["candidate"]["portfolio"]["initial_capital_usdt"]
        ),
        "equity": [],
        "last_active_record_ms": None,
        "missing_intervals": 0,
        "unpriced_intervals": 0,
    }


def _mark_context(context, record, timestamp, protocol):
    opening = context["opens"].pop(timestamp, [])
    had_active = bool(context["active"])
    if had_active and context["last_active_record_ms"] is not None:
        elapsed = timestamp - context["last_active_record_ms"]
        if elapsed > BUCKET_MS:
            context["missing_intervals"] += elapsed // BUCKET_MS - 1
    for identifier, trade in opening:
        symbol = record.get("symbols", {}).get(trade["symbol"])
        if symbol is None:
            context["unpriced_intervals"] += 1
            continue
        context["active"][identifier] = _open_position(
            trade, symbol, protocol
        )
    if not context["active"]:
        context["last_active_record_ms"] = None
        return
    unrealized = 0.0
    priced = {}
    for identifier, state in list(context["active"].items()):
        symbol = record.get("symbols", {}).get(state["trade"]["symbol"])
        if symbol is None:
            context["unpriced_intervals"] += 1
            continue
        _update_funding(state, symbol, timestamp)
        net = _liquidation_return(state, symbol, protocol)
        if net is None:
            context["unpriced_intervals"] += 1
            continue
        priced[identifier] = net
        unrealized += net * float(
            protocol["dataset"]["paired_gross_capital_usdt"]
        )
    context["equity"].append(
        context["capital"] + context["realized"] + unrealized
    )
    for identifier, net in priced.items():
        state = context["active"][identifier]
        if state["trade"]["exit_timestamp_ms"] != timestamp:
            continue
        expected = state["trade"]["net_pair_return"]
        if not math.isclose(net, expected, rel_tol=1e-10, abs_tol=1e-10):
            raise ValueError("Carry V1 mark-to-market exit differs from label")
        context["realized"] += net * float(
            protocol["dataset"]["paired_gross_capital_usdt"]
        )
        del context["active"][identifier]
    context["last_active_record_ms"] = (
        timestamp if context["active"] else None
    )


def _open_position(trade, symbol, protocol):
    quote = float(protocol["dataset"]["leg_quote_usdt"])
    key = f"{quote:g}"
    spot = symbol["spot"]["ask_vwap_by_quote"][key]
    futures = symbol["futures"]["bid_vwap_by_quote"][key]
    if not spot["sufficient_depth"] or not futures["sufficient_depth"]:
        raise ValueError("Carry V1 selected an insufficient entry book")
    return {
        "trade": trade,
        "spot_entry_quote": float(spot["filled_quote"]),
        "spot_entry_base": float(spot["filled_base"]),
        "futures_entry_quote": float(futures["filled_quote"]),
        "futures_entry_base": float(futures["filled_base"]),
        "spot_entry_fee": float(symbol["spot"]["conservative_taker_fee_rate"]),
        "futures_entry_fee": float(
            symbol["futures"]["conservative_taker_fee_rate"]
        ),
        "funding": {},
    }


def _update_funding(state, symbol, timestamp):
    entry = state["trade"]["entry_timestamp_ms"]
    for point in symbol["funding"].get("settled_last_24h", []):
        point_timestamp = int(point["timestamp_ms"])
        if entry < point_timestamp <= timestamp:
            state["funding"][point_timestamp] = float(point["rate"])


def _liquidation_return(state, symbol, protocol):
    spot_exit = forward_carry_dataset._fill_base(
        symbol["spot"]["normalized_bids"], state["spot_entry_base"]
    )
    futures_exit = forward_carry_dataset._fill_base(
        symbol["futures"]["normalized_asks"],
        state["futures_entry_base"],
    )
    if spot_exit is None or futures_exit is None:
        return None
    quote = float(protocol["dataset"]["leg_quote_usdt"])
    spot_return = (
        spot_exit["quote_quantity"] - state["spot_entry_quote"]
    ) / quote
    futures_return = (
        state["futures_entry_quote"] - futures_exit["quote_quantity"]
    ) / quote
    funding_return = sum(state["funding"].values())
    fee_quote = (
        state["spot_entry_quote"] * state["spot_entry_fee"]
        + state["futures_entry_quote"] * state["futures_entry_fee"]
        + spot_exit["quote_quantity"]
        * float(symbol["spot"]["conservative_taker_fee_rate"])
        + futures_exit["quote_quantity"]
        * float(symbol["futures"]["conservative_taker_fee_rate"])
    )
    return (
        0.5 * (spot_return + futures_return + funding_return)
        - fee_quote / (2 * quote)
    )


def evaluate_development_core(
    dataset: dict,
    protocol: dict,
    *,
    journal_path: str | pathlib.Path | None = None,
) -> tuple[dict, RidgeModel, int]:
    _validate_dataset_against_protocol(dataset, protocol)
    predictions, fold_ids, folds = walk_forward_predictions(dataset, protocol)
    development = protocol["validation"]["development"]
    start_ms = min(_timestamp_ms(fold["test_start_utc"]) for fold in folds)
    end_ms = _timestamp_ms(development["last_entry_exclusive_utc"])
    candidate = select_portfolio(
        dataset,
        predictions,
        protocol,
        start_ms=start_ms,
        end_ms=end_ms,
        fold_ids=fold_ids,
    )
    names = tuple(dataset["feature_names"])
    funding_scores = dataset["features"][
        :, names.index("current_funding_rate")
    ]
    benchmark = select_portfolio(
        dataset,
        funding_scores,
        protocol,
        start_ms=start_ms,
        end_ms=end_ms,
        fold_ids=fold_ids,
        apply_prediction_gate=False,
    )
    stressed, missing_stress = stress_trades(dataset, candidate)
    mtm = None
    if journal_path is not None:
        mtm = mark_to_market_portfolios(
            journal_path,
            {"candidate": candidate, "benchmark": benchmark},
            protocol,
        )
    candidate_metrics = endpoint_metrics(
        candidate,
        protocol,
        mark_to_market=(None if mtm is None else mtm["candidate"]),
    )
    benchmark_metrics = endpoint_metrics(
        benchmark,
        protocol,
        mark_to_market=(None if mtm is None else mtm["benchmark"]),
    )
    stress_metrics = endpoint_metrics(stressed, protocol)
    omissions = {}
    for symbol in sorted(set(str(value) for value in dataset["symbols"])):
        omitted_predictions, omitted_folds, _ = walk_forward_predictions(
            dataset,
            protocol,
            omitted_training_symbol=symbol,
        )
        omitted_trades = select_portfolio(
            dataset,
            omitted_predictions,
            protocol,
            start_ms=start_ms,
            end_ms=end_ms,
            fold_ids=omitted_folds,
        )
        omitted_metrics = endpoint_metrics(omitted_trades, protocol)
        omissions[symbol] = {
            "closed_pairs": omitted_metrics["closed_pairs"],
            "total_return": omitted_metrics["total_return"],
            "profit_factor": omitted_metrics["profit_factor"],
        }
    non_negative_omissions = sum(
        value["total_return"] >= 0 for value in omissions.values()
    )
    exclusion = exclusion_audit(
        dataset,
        start_ms=start_ms,
        end_ms=end_ms,
    )
    gate = _development_gate(
        protocol,
        candidate_metrics,
        benchmark_metrics,
        stress_metrics,
        missing_stress=missing_stress,
        non_negative_omissions=non_negative_omissions,
        omission_count=len(omissions),
        exclusion=exclusion,
    )
    final_model, training_rows = fit_final_development_model(
        dataset, protocol
    )
    return (
        {
            "candidate": candidate_metrics,
            "benchmark": benchmark_metrics,
            "stress": {
                **stress_metrics,
                "missing_delayed_rows": missing_stress,
            },
            "walk_forward_folds": folds,
            "leave_one_symbol_out": {
                "minimum_required_non_negative": protocol[
                    "validation"
                ]["leave_one_symbol_out"]["minimum_non_negative_omissions"],
                "non_negative_omissions": non_negative_omissions,
                "omissions": omissions,
            },
            "exclusion_audit": exclusion,
            "development_gate": gate,
            "selected_trades": candidate,
            "benchmark_trades": benchmark,
        },
        final_model,
        training_rows,
    )


def evaluate_confirmation_core(
    dataset: dict,
    protocol: dict,
    model: RidgeModel,
    *,
    journal_path: str | pathlib.Path | None = None,
) -> dict:
    _validate_dataset_against_protocol(dataset, protocol)
    confirmation = protocol["validation"]["locked_confirmation"]
    start_ms = _timestamp_ms(confirmation["entry_start_utc"])
    end_ms = _timestamp_ms(confirmation["entry_end_exclusive_utc"])
    eligible = base_candidate_mask(dataset, protocol)
    scores = numpy.full(len(eligible), numpy.nan, dtype=numpy.float64)
    scores[eligible] = model.predict(dataset["features"][eligible])
    candidate = select_portfolio(
        dataset,
        scores,
        protocol,
        start_ms=start_ms,
        end_ms=end_ms,
    )
    names = tuple(dataset["feature_names"])
    funding_scores = dataset["features"][
        :, names.index("current_funding_rate")
    ]
    benchmark = select_portfolio(
        dataset,
        funding_scores,
        protocol,
        start_ms=start_ms,
        end_ms=end_ms,
        apply_prediction_gate=False,
    )
    stressed, missing_stress = stress_trades(dataset, candidate)
    mtm = None
    if journal_path is not None:
        mtm = mark_to_market_portfolios(
            journal_path,
            {"candidate": candidate, "benchmark": benchmark},
            protocol,
        )
    candidate_metrics = endpoint_metrics(
        candidate,
        protocol,
        mark_to_market=(None if mtm is None else mtm["candidate"]),
    )
    benchmark_metrics = endpoint_metrics(
        benchmark,
        protocol,
        mark_to_market=(None if mtm is None else mtm["benchmark"]),
    )
    stress_metrics = endpoint_metrics(stressed, protocol)
    exclusion = exclusion_audit(
        dataset,
        start_ms=start_ms,
        end_ms=end_ms,
    )
    gate = _confirmation_gate(
        protocol,
        candidate_metrics,
        stress_metrics,
        missing_stress=missing_stress,
        exclusion=exclusion,
    )
    return {
        "candidate": candidate_metrics,
        "benchmark": benchmark_metrics,
        "stress": {
            **stress_metrics,
            "missing_delayed_rows": missing_stress,
        },
        "exclusion_audit": exclusion,
        "confirmation_gate": gate,
        "selected_trades": candidate,
        "benchmark_trades": benchmark,
    }


def _development_gate(
    protocol,
    candidate,
    benchmark,
    stress,
    *,
    missing_stress,
    non_negative_omissions,
    omission_count,
    exclusion,
):
    values = protocol["development_gate"]
    maximum_exclusion = protocol["dataset"][
        "maximum_excluded_future_exit_fraction"
    ]
    checks = {
        "minimum_closed_pairs": candidate["closed_pairs"]
        >= values["minimum_closed_pairs"],
        "total_return_positive": candidate["total_return"] > 0,
        "minimum_profit_factor": candidate["profit_factor"]
        >= values["minimum_profit_factor"],
        "minimum_win_rate": candidate["win_rate"] >= values["minimum_win_rate"],
        "maximum_mark_to_market_drawdown": candidate["mark_to_market"][
            "complete"
        ]
        and candidate["mark_to_market"]["maximum_drawdown"]
        <= values["maximum_mark_to_market_drawdown"],
        "minimum_positive_operating_weeks": candidate[
            "positive_operating_week_ratio"
        ]
        >= values["minimum_positive_operating_weeks"],
        "positive_walk_forward_folds": candidate[
            "positive_walk_forward_folds"
        ]
        >= values["positive_walk_forward_folds_required"],
        "minimum_selected_symbols": candidate["selected_symbols"]
        >= values["minimum_selected_symbols"],
        "maximum_single_symbol_trade_fraction": candidate[
            "maximum_single_symbol_trade_fraction"
        ]
        <= values["maximum_single_symbol_trade_fraction"],
        "maximum_single_symbol_gross_profit_fraction": candidate[
            "maximum_single_symbol_gross_profit_fraction"
        ]
        <= values["maximum_single_symbol_gross_profit_fraction"],
        "return_not_below_structural_benchmark": candidate["total_return"]
        >= benchmark["total_return"],
        "drawdown_not_above_structural_benchmark": benchmark[
            "mark_to_market"
        ]["complete"]
        and candidate["mark_to_market"]["maximum_drawdown"]
        <= benchmark["mark_to_market"]["maximum_drawdown"],
        "stress_complete": missing_stress == 0,
        "minimum_stress_profit_factor": stress["profit_factor"]
        >= values["minimum_stress_profit_factor"],
        "stress_total_return_positive": stress["total_return"] > 0,
        "leave_one_symbol_out": non_negative_omissions
        >= protocol["validation"]["leave_one_symbol_out"][
            "minimum_non_negative_omissions"
        ]
        and omission_count
        == protocol["validation"]["leave_one_symbol_out"]["total_omissions"],
        "future_exit_exclusion_fraction": exclusion[
            "future_exit_exclusion_fraction"
        ]
        <= maximum_exclusion,
    }
    return {
        "passed": all(checks.values()),
        "checks": checks,
        "interpretation": (
            "A pass freezes the final model and only unlocks the already "
            "defined confirmation after its wall-clock gate."
        ),
    }


def _confirmation_gate(
    protocol,
    candidate,
    stress,
    *,
    missing_stress,
    exclusion,
):
    values = protocol["confirmation_gate"]
    maximum_exclusion = protocol["dataset"][
        "maximum_excluded_future_exit_fraction"
    ]
    checks = {
        "minimum_closed_pairs": candidate["closed_pairs"]
        >= values["minimum_closed_pairs"],
        "total_return_positive": candidate["total_return"] > 0,
        "minimum_profit_factor": candidate["profit_factor"]
        >= values["minimum_profit_factor"],
        "minimum_win_rate": candidate["win_rate"] >= values["minimum_win_rate"],
        "maximum_mark_to_market_drawdown": candidate["mark_to_market"][
            "complete"
        ]
        and candidate["mark_to_market"]["maximum_drawdown"]
        <= values["maximum_mark_to_market_drawdown"],
        "minimum_positive_operating_weeks": candidate[
            "positive_operating_week_ratio"
        ]
        >= values["minimum_positive_operating_weeks"],
        "minimum_selected_symbols": candidate["selected_symbols"]
        >= values["minimum_selected_symbols"],
        "minimum_stress_profit_factor": stress["profit_factor"]
        >= values["minimum_stress_profit_factor"],
        "stress_total_return_non_negative": stress["total_return"] >= 0,
        "stress_complete": missing_stress == 0,
        "missing_forward_intervals": candidate["mark_to_market"][
            "missing_intervals"
        ]
        == values["missing_forward_intervals"],
        "future_exit_exclusion_fraction": exclusion[
            "future_exit_exclusion_fraction"
        ]
        <= maximum_exclusion,
    }
    return {
        "passed": all(checks.values()),
        "checks": checks,
        "interpretation": (
            "A pass permits only manual review for an orderless shadow."
        ),
    }


def evaluate_development_files(
    *,
    protocol_path: str | pathlib.Path,
    dataset_path: str | pathlib.Path,
    evidence_path: str | pathlib.Path,
    journal_path: str | pathlib.Path,
    output_directory: str | pathlib.Path,
) -> pathlib.Path:
    protocol, dataset, evidence = _load_file_inputs(
        protocol_path=protocol_path,
        dataset_path=dataset_path,
        evidence_path=evidence_path,
        journal_path=journal_path,
    )
    status = phase_status(protocol, evidence)
    if status["development"]["allowed"] is not True:
        raise ValueError("forward Carry V1 development is not ready")
    evaluation, final_model, training_rows = evaluate_development_core(
        dataset,
        protocol,
        journal_path=journal_path,
    )
    output = pathlib.Path(output_directory).resolve()
    output.mkdir(parents=True, exist_ok=True)
    model_artifact = None
    if evaluation["development_gate"]["passed"]:
        model_artifact = save_model(
            final_model,
            output / "frozen-model.json",
            protocol_sha256=protocol["protocol_sha256"],
            dataset_sha256=dataset["manifest"]["output"]["sha256"],
            dataset_manifest_sha256=dataset["manifest"][
                "manifest_sha256"
            ],
            training_rows=training_rows,
        )
    report = {
        "schema_version": SCHEMA_VERSION,
        "evaluator_version": EVALUATOR_VERSION,
        "created_at": datetime.datetime.now(datetime.timezone.utc).isoformat(),
        "phase": "development",
        "research_only": True,
        "orders_authorized": False,
        "paper_orders_authorized": False,
        "automatic_promotion": False,
        "protocol_version": protocol["protocol_version"],
        "protocol_sha256": protocol["protocol_sha256"],
        "dataset_sha256": dataset["manifest"]["output"]["sha256"],
        "dataset_manifest_sha256": dataset["manifest"][
            "manifest_sha256"
        ],
        "evidence_sha256": _sha256(evidence_path),
        "journal_sha256": _sha256(journal_path),
        **evaluation,
        "frozen_model": model_artifact,
        "confirmation": {
            "opened": False,
            "authorized": bool(model_artifact),
            "earliest_open_utc": protocol["validation"][
                "locked_confirmation"
            ]["earliest_open_utc"],
        },
    }
    path = output / "development-report.json"
    _write_hashed_report(path, report)
    return path


def evaluate_confirmation_files(
    *,
    protocol_path: str | pathlib.Path,
    dataset_path: str | pathlib.Path,
    evidence_path: str | pathlib.Path,
    journal_path: str | pathlib.Path,
    development_report_path: str | pathlib.Path,
    model_path: str | pathlib.Path,
    output_directory: str | pathlib.Path,
) -> pathlib.Path:
    protocol, dataset, evidence = _load_file_inputs(
        protocol_path=protocol_path,
        dataset_path=dataset_path,
        evidence_path=evidence_path,
        journal_path=journal_path,
    )
    model, model_payload = load_model(
        model_path,
        expected_protocol_sha256=protocol["protocol_sha256"],
    )
    development_report = _load_passing_development_report(
        development_report_path,
        protocol=protocol,
        model_payload=model_payload,
    )
    status = phase_status(
        protocol,
        evidence,
        development_passed=True,
        model_sha256=model_payload["model_sha256"],
    )
    if status["confirmation"]["allowed"] is not True:
        raise ValueError("forward Carry V1 confirmation remains locked")
    confirmation = protocol["validation"]["locked_confirmation"]
    required_exit_ms = _timestamp_ms(confirmation["earliest_open_utc"])
    primary_exits = dataset["exit_timestamp_ms"][
        dataset["horizon_hours"] == PRIMARY_HORIZON_HOURS
    ]
    if len(primary_exits) == 0 or int(numpy.max(primary_exits)) < required_exit_ms:
        raise ValueError("Carry V1 confirmation labels are not mature")
    evaluation = evaluate_confirmation_core(
        dataset,
        protocol,
        model,
        journal_path=journal_path,
    )
    report = {
        "schema_version": SCHEMA_VERSION,
        "evaluator_version": EVALUATOR_VERSION,
        "created_at": datetime.datetime.now(datetime.timezone.utc).isoformat(),
        "phase": "confirmation",
        "research_only": True,
        "orders_authorized": False,
        "paper_orders_authorized": False,
        "automatic_promotion": False,
        "protocol_version": protocol["protocol_version"],
        "protocol_sha256": protocol["protocol_sha256"],
        "model_sha256": model_payload["model_sha256"],
        "development_report_sha256": _sha256(development_report_path),
        "dataset_sha256": dataset["manifest"]["output"]["sha256"],
        "dataset_manifest_sha256": dataset["manifest"][
            "manifest_sha256"
        ],
        "evidence_sha256": _sha256(evidence_path),
        "journal_sha256": _sha256(journal_path),
        **evaluation,
        "shadow_review": {
            "eligible": evaluation["confirmation_gate"]["passed"],
            "orders_authorized": False,
            "minimum_orderless_shadow_days": 90,
            "manual_approval_required": True,
        },
    }
    output = pathlib.Path(output_directory).resolve()
    output.mkdir(parents=True, exist_ok=True)
    path = output / "confirmation-report.json"
    _write_hashed_report(path, report)
    return path


def _load_passing_development_report(
    path_value,
    *,
    protocol,
    model_payload,
):
    path = pathlib.Path(path_value).resolve()
    report = json.loads(path.read_text(encoding="utf-8"))
    report_hash = report.pop("report_sha256", None)
    if report_hash != _json_hash(report):
        raise ValueError("Carry V1 development report hash mismatch")
    report["report_sha256"] = report_hash
    if (
        report.get("schema_version") != SCHEMA_VERSION
        or report.get("evaluator_version") != EVALUATOR_VERSION
        or report.get("phase") != "development"
        or report.get("research_only") is not True
        or report.get("orders_authorized") is not False
        or report.get("paper_orders_authorized") is not False
        or report.get("automatic_promotion") is not False
        or report.get("protocol_version")
        != protocol_v1_1.PROTOCOL_VERSION
        or report.get("protocol_sha256") != protocol["protocol_sha256"]
        or report.get("development_gate", {}).get("passed") is not True
        or report.get("dataset_sha256")
        != model_payload.get("dataset_sha256")
        or report.get("dataset_manifest_sha256")
        != model_payload.get("dataset_manifest_sha256")
        or report.get("frozen_model") != model_payload
        or report.get("confirmation", {}).get("authorized") is not True
        or report.get("confirmation", {}).get("opened") is not False
    ):
        raise ValueError("Carry V1 development report did not pass integrity")
    return report


def _load_file_inputs(*, protocol_path, dataset_path, evidence_path, journal_path):
    protocol = load_protocol(protocol_path)
    evidence_file = pathlib.Path(evidence_path).resolve()
    journal_file = pathlib.Path(journal_path).resolve()
    evidence = json.loads(evidence_file.read_text(encoding="utf-8"))
    dataset = forward_carry_dataset.load_forward_carry_dataset(dataset_path)
    manifest_source = dataset["manifest"].get("source", {})
    journal_hash = _sha256(journal_file)
    evidence_hash = _sha256(evidence_file)
    if manifest_source.get("journal_sha256") != journal_hash:
        raise ValueError("Carry V1 dataset journal hash mismatch")
    if manifest_source.get("evidence_sha256") != evidence_hash:
        raise ValueError("Carry V1 dataset evidence hash mismatch")
    if evidence.get("source_journal", {}).get("sha256") != journal_hash:
        raise ValueError("Carry V1 evidence journal hash mismatch")
    return protocol, dataset, evidence


def _validate_dataset_against_protocol(dataset, protocol):
    manifest = dataset["manifest"]
    if (
        manifest.get("research_only") is not True
        or manifest.get("orders_authorized") is not False
        or manifest.get("automatic_promotion") is not False
    ):
        raise ValueError("Carry V1 dataset safety invariant failed")
    if tuple(dataset["feature_names"]) != tuple(
        protocol["dataset"]["feature_names"]
    ):
        raise ValueError("Carry V1 dataset feature protocol mismatch")
    if float(manifest.get("leg_quote", -1)) != float(
        protocol["dataset"]["leg_quote_usdt"]
    ):
        raise ValueError("Carry V1 dataset leg quote mismatch")
    if PRIMARY_HORIZON_HOURS not in set(
        int(value) for value in manifest.get("horizon_hours", [])
    ):
        raise ValueError("Carry V1 primary horizon is missing")
    keys = set()
    for timestamp, symbol, horizon in zip(
        dataset["entry_timestamp_ms"],
        dataset["symbols"],
        dataset["horizon_hours"],
    ):
        key = (int(timestamp), str(symbol), int(horizon))
        if key in keys:
            raise ValueError("Carry V1 dataset contains a duplicate row")
        keys.add(key)


def _maximum_drawdown(equity_values) -> float:
    values = numpy.asarray(equity_values, dtype=numpy.float64)
    if len(values) == 0:
        return 0.0
    if numpy.any(values <= 0) or not numpy.all(numpy.isfinite(values)):
        raise ValueError("invalid Carry V1 equity curve")
    peaks = numpy.maximum.accumulate(values)
    return float(numpy.max(1.0 - values / peaks))


def _timestamp_ms(value: str) -> int:
    timestamp = datetime.datetime.fromisoformat(value)
    if timestamp.tzinfo is None:
        raise ValueError("Carry V1 protocol timestamp must be timezone-aware")
    return int(timestamp.timestamp() * 1000)


def _atomic_json(path: pathlib.Path, value: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(
        json.dumps(_json_safe(value), indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    temporary.replace(path)


def _write_hashed_report(path: pathlib.Path, value: dict) -> dict:
    payload = _json_safe(value)
    payload["report_sha256"] = _json_hash(payload)
    _atomic_json(path, payload)
    persisted = json.loads(path.read_text(encoding="utf-8"))
    check = persisted.pop("report_sha256", None)
    if check != _json_hash(persisted):
        raise ValueError("Carry V1 persisted report hash mismatch")
    persisted["report_sha256"] = check
    return persisted


def _json_safe(value):
    if isinstance(value, dict):
        return {str(key): _json_safe(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_json_safe(item) for item in value]
    if isinstance(value, numpy.generic):
        return value.item()
    if isinstance(value, float) and not math.isfinite(value):
        return None
    return value


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    phase = commands.add_parser("phase-status")
    phase.add_argument("--protocol", required=True)
    phase.add_argument("--evidence", required=True)
    development = commands.add_parser("evaluate-development")
    confirmation = commands.add_parser("evaluate-confirmation")
    for command in (development, confirmation):
        command.add_argument("--protocol", required=True)
        command.add_argument("--dataset", required=True)
        command.add_argument("--evidence", required=True)
        command.add_argument("--journal", required=True)
        command.add_argument("--output-directory", required=True)
    confirmation.add_argument("--development-report", required=True)
    confirmation.add_argument("--model", required=True)
    return parser.parse_args()


def main() -> int:
    arguments = _parse_args()
    if arguments.command == "phase-status":
        protocol = load_protocol(arguments.protocol)
        evidence = json.loads(
            pathlib.Path(arguments.evidence).read_text(encoding="utf-8")
        )
        result = phase_status(protocol, evidence)
    elif arguments.command == "evaluate-development":
        path = evaluate_development_files(
            protocol_path=arguments.protocol,
            dataset_path=arguments.dataset,
            evidence_path=arguments.evidence,
            journal_path=arguments.journal,
            output_directory=arguments.output_directory,
        )
        result = {"report_path": str(path)}
    else:
        path = evaluate_confirmation_files(
            protocol_path=arguments.protocol,
            dataset_path=arguments.dataset,
            evidence_path=arguments.evidence,
            journal_path=arguments.journal,
            development_report_path=arguments.development_report,
            model_path=arguments.model,
            output_directory=arguments.output_directory,
        )
        result = {"report_path": str(path)}
    print(json.dumps(_json_safe(result), indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
