"""Single-run evaluator for the frozen TimesFM 3 crypto protocol.

The evaluator is historical-diagnostic only.  It loads one pinned local model,
runs one zero-shot pass, compares fixed causal baselines, and applies a separate
cost-aware economic translation.  No result can authorize paper or real orders.
"""

from __future__ import annotations

import argparse
import datetime
import json
import math
import os
import pathlib
import tempfile
import time
import typing

import numpy

from octobot.ai_strategy_lab import funding as funding_module
from octobot.ai_strategy_lab import timesfm3_research_v1 as protocol_module


SCHEMA_VERSION = 1
EVALUATOR_VERSION = "timesfm3_crypto_multivariate_evaluator_v1"
QUANTILES = numpy.asarray([value / 10 for value in range(1, 10)])


class EvaluationError(ValueError):
    """Raised when an immutable input or evaluated result is invalid."""


def _load_json(path_value: typing.Union[str, pathlib.Path]) -> dict:
    return json.loads(pathlib.Path(path_value).resolve().read_text(encoding="utf-8"))


def _artifact(label: str, path_value: typing.Union[str, pathlib.Path]) -> dict:
    path = pathlib.Path(path_value).resolve()
    if not path.is_file():
        raise FileNotFoundError(path)
    return {
        "label": label,
        "path": str(path),
        "bytes": path.stat().st_size,
        "sha256": protocol_module.file_hash(path),
    }


def _verify_content_hash(payload: dict) -> None:
    content = {key: value for key, value in payload.items() if key != "content_sha256"}
    if payload.get("content_sha256") != protocol_module.logical_hash(content):
        raise EvaluationError("implementation lock content hash differs")


def write_evaluation_lock(
    *,
    protocol_value: typing.Union[str, pathlib.Path],
    phase_zero_lock_value: typing.Union[str, pathlib.Path],
    checkpoint_verification_value: typing.Union[str, pathlib.Path],
    license_acceptance_value: typing.Union[str, pathlib.Path],
    artifacts: dict[str, typing.Union[str, pathlib.Path]],
    output_value: typing.Union[str, pathlib.Path],
) -> pathlib.Path:
    """Freeze the complete evaluator after weights, before historical forecasts."""

    output = pathlib.Path(output_value).resolve()
    protocol_path = pathlib.Path(protocol_value).resolve()
    phase_zero_path = pathlib.Path(phase_zero_lock_value).resolve()
    checkpoint_path = pathlib.Path(checkpoint_verification_value).resolve()
    acceptance_path = pathlib.Path(license_acceptance_value).resolve()
    protocol = _load_json(protocol_path)
    phase_zero = _load_json(phase_zero_path)
    checkpoint = _load_json(checkpoint_path)
    acceptance = protocol_module.validate_license_acceptance(acceptance_path)
    frozen = protocol_module.frozen_protocol()
    frozen_with_hash = {
        **frozen,
        "protocol_sha256": protocol_module.logical_hash(frozen),
    }
    if protocol != frozen_with_hash:
        raise EvaluationError("persisted TimesFM 3 protocol differs")
    _verify_content_hash(phase_zero)
    phase_zero_checks = (
        phase_zero.get("protocol_sha256") == protocol["protocol_sha256"],
        phase_zero.get("economic_outcomes_read_before_lock") is False,
        phase_zero.get("model_forecasts_run_before_lock") is False,
        phase_zero.get("results_existing_before_lock") is False,
        phase_zero.get("orders_authorized") is False,
        phase_zero.get("paper_orders_authorized") is False,
        phase_zero.get("results") is None,
    )
    checkpoint_checks = (
        checkpoint.get("weights_sha256") == protocol_module.MODEL_WEIGHTS_SHA256,
        checkpoint.get("weights_bytes") == protocol_module.MODEL_WEIGHTS_BYTES,
        checkpoint.get("license_acceptance_sha256")
        == protocol_module.file_hash(acceptance_path),
        checkpoint.get("orders_authorized") is False,
        checkpoint.get("paper_orders_authorized") is False,
    )
    if not all(phase_zero_checks):
        raise EvaluationError("phase-zero lock is not result-free")
    if not all(checkpoint_checks):
        raise EvaluationError("checkpoint verification differs")
    source_artifacts = [
        _artifact(label, path) for label, path in sorted(artifacts.items())
    ]
    created_at = datetime.datetime.now(datetime.timezone.utc).isoformat()
    if output.exists():
        created_at = _load_json(output).get("created_at", created_at)
    payload = {
        "schema_version": SCHEMA_VERSION,
        "evaluator_version": EVALUATOR_VERSION,
        "created_at": created_at,
        "status": "evaluator_frozen_before_historical_forecasts",
        "protocol_sha256": protocol["protocol_sha256"],
        "protocol_file_sha256": protocol_module.file_hash(protocol_path),
        "phase_zero_lock_file_sha256": protocol_module.file_hash(phase_zero_path),
        "phase_zero_lock_content_sha256": phase_zero["content_sha256"],
        "checkpoint_verification_file_sha256": protocol_module.file_hash(
            checkpoint_path
        ),
        "license_acceptance_file_sha256": protocol_module.file_hash(acceptance_path),
        "accepted_by": acceptance["accepted_by"],
        "source_artifacts": source_artifacts,
        "synthetic_smoke_forecasts_before_lock": 2,
        "historical_market_forecasts_before_lock": False,
        "historical_economic_outcomes_read_before_lock": False,
        "results_existing_before_lock": False,
        "weights_downloaded": True,
        "license_accepted": True,
        "research_only": True,
        "credentials_used": False,
        "orders_authorized": False,
        "paper_orders_authorized": False,
        "automatic_promotion": False,
        "results": None,
    }
    payload["content_sha256"] = protocol_module.logical_hash(payload)
    if output.exists():
        if _load_json(output) != payload:
            raise EvaluationError("existing evaluation lock differs")
        return output
    protocol_module._atomic_json(output, payload)
    return output


def verify_evaluation_lock(
    lock_value: typing.Union[str, pathlib.Path],
    *,
    artifacts: dict[str, typing.Union[str, pathlib.Path]],
) -> dict:
    lock = _load_json(lock_value)
    _verify_content_hash(lock)
    checks = (
        lock.get("evaluator_version") == EVALUATOR_VERSION,
        lock.get("status") == "evaluator_frozen_before_historical_forecasts",
        lock.get("protocol_sha256")
        == protocol_module.logical_hash(protocol_module.frozen_protocol()),
        lock.get("source_artifacts")
        == [_artifact(label, path) for label, path in sorted(artifacts.items())],
        lock.get("historical_market_forecasts_before_lock") is False,
        lock.get("historical_economic_outcomes_read_before_lock") is False,
        lock.get("results_existing_before_lock") is False,
        lock.get("weights_downloaded") is True,
        lock.get("license_accepted") is True,
        lock.get("orders_authorized") is False,
        lock.get("paper_orders_authorized") is False,
        lock.get("automatic_promotion") is False,
        lock.get("results") is None,
    )
    if not all(checks):
        raise EvaluationError("evaluation lock differs")
    return lock


def ar1_path(log_context: numpy.ndarray, horizon: int) -> numpy.ndarray:
    """Fit one stable AR(1) to past hourly returns and forecast levels."""

    values = numpy.asarray(log_context, dtype=numpy.float64)
    if values.ndim != 2 or values.shape[1] < 3 or horizon < 1:
        raise EvaluationError("invalid AR(1) input")
    result = numpy.empty((values.shape[0], horizon), dtype=numpy.float64)
    for asset, levels in enumerate(values):
        returns = numpy.diff(levels)
        mean = float(numpy.mean(returns))
        left = returns[:-1] - mean
        right = returns[1:] - mean
        denominator = float(numpy.dot(left, left))
        phi = 0.0 if denominator <= 1e-20 else float(numpy.dot(left, right) / denominator)
        phi = float(numpy.clip(phi, -0.99, 0.99))
        previous = float(returns[-1])
        level = float(levels[-1])
        for step in range(horizon):
            previous = mean + phi * (previous - mean)
            level += previous
            result[asset, step] = level
    return result


def _pinball(actual: numpy.ndarray, predicted: numpy.ndarray, quantile: float) -> float:
    error = actual - predicted
    return float(numpy.mean(numpy.maximum(quantile * error, (quantile - 1) * error)))


def predictive_metrics(
    *,
    origin_log_prices: numpy.ndarray,
    actual_log_paths: numpy.ndarray,
    model_paths: numpy.ndarray,
    model_quantiles: numpy.ndarray,
    unchanged_paths: numpy.ndarray,
    seasonal_paths: numpy.ndarray,
    ar1_paths: numpy.ndarray,
) -> dict:
    """Compute fixed price-path metrics in basis points."""

    actual = numpy.asarray(actual_log_paths, dtype=numpy.float64)
    point = numpy.asarray(model_paths, dtype=numpy.float64)
    quantiles = numpy.asarray(model_quantiles, dtype=numpy.float64)
    expected = actual.shape
    if point.shape != expected or expected[1:] != (
        len(protocol_module.ASSETS),
        protocol_module.HORIZON_HOURS,
    ):
        raise EvaluationError("unexpected model or actual path shape")
    if quantiles.shape != (*expected, len(QUANTILES)):
        raise EvaluationError("unexpected quantile shape")
    for baseline in (unchanged_paths, seasonal_paths, ar1_paths):
        if numpy.asarray(baseline).shape != expected:
            raise EvaluationError("unexpected baseline path shape")
    arrays = (actual, point, quantiles, unchanged_paths, seasonal_paths, ar1_paths)
    if not all(numpy.all(numpy.isfinite(value)) for value in arrays):
        raise EvaluationError("predictive arrays contain non-finite values")

    terminal_actual = (actual[:, :, -1] - origin_log_prices) * 10_000
    terminal_model = (point[:, :, -1] - origin_log_prices) * 10_000
    terminal_unchanged = (
        numpy.asarray(unchanged_paths)[:, :, -1] - origin_log_prices
    ) * 10_000
    model_errors = numpy.abs(terminal_actual - terminal_model)
    unchanged_errors = numpy.abs(terminal_actual - terminal_unchanged)
    pooled_model_mae = float(numpy.mean(model_errors))
    pooled_unchanged_mae = float(numpy.mean(unchanged_errors))
    pooled_skill = (
        1 - pooled_model_mae / pooled_unchanged_mae
        if pooled_unchanged_mae > 0
        else -math.inf
    )
    asset_metrics = {}
    for index, asset in enumerate(protocol_module.ASSETS):
        model_mae = float(numpy.mean(model_errors[:, index]))
        unchanged_mae = float(numpy.mean(unchanged_errors[:, index]))
        asset_metrics[asset] = {
            "terminal_mae_bps": model_mae,
            "unchanged_terminal_mae_bps": unchanged_mae,
            "mae_skill_vs_unchanged": (
                1 - model_mae / unchanged_mae if unchanged_mae > 0 else None
            ),
            "direction_accuracy": float(
                numpy.mean(
                    numpy.sign(terminal_model[:, index])
                    == numpy.sign(terminal_actual[:, index])
                )
            ),
        }

    predicted_return_quantiles = (
        quantiles[:, :, -1, :] - origin_log_prices[:, :, None]
    ) * 10_000
    pinball = {
        f"q{int(round(q * 100)):02d}": _pinball(
            terminal_actual,
            predicted_return_quantiles[:, :, index],
            float(q),
        )
        for index, q in enumerate(QUANTILES)
    }
    coverage = float(
        numpy.mean(
            (terminal_actual >= predicted_return_quantiles[:, :, 0])
            & (terminal_actual <= predicted_return_quantiles[:, :, -1])
        )
    )
    path_metrics = {}
    for label, forecast in (
        ("timesfm3", point),
        ("unchanged", unchanged_paths),
        ("seasonal_24h", seasonal_paths),
        ("rolling_ar1", ar1_paths),
    ):
        path_metrics[label] = {
            "mae_bps": float(numpy.mean(numpy.abs(actual - forecast)) * 10_000),
            "terminal_mae_bps": float(
                numpy.mean(numpy.abs(actual[:, :, -1] - forecast[:, :, -1]))
                * 10_000
            ),
        }
    return {
        "daily_origins": int(actual.shape[0]),
        "pooled_terminal_mae_bps": pooled_model_mae,
        "pooled_unchanged_terminal_mae_bps": pooled_unchanged_mae,
        "pooled_mae_skill_vs_unchanged": float(pooled_skill),
        "direction_accuracy": float(
            numpy.mean(numpy.sign(terminal_model) == numpy.sign(terminal_actual))
        ),
        "q10_q90_coverage": coverage,
        "mean_pinball_loss_bps": float(numpy.mean(list(pinball.values()))),
        "pinball_loss_bps": pinball,
        "by_asset": asset_metrics,
        "path_baselines": path_metrics,
    }


def _funding_sums(
    rates: dict[str, tuple[numpy.ndarray, numpy.ndarray]],
    decision_timestamps: numpy.ndarray,
) -> numpy.ndarray:
    result = numpy.zeros(
        (len(decision_timestamps), len(protocol_module.ASSETS)),
        dtype=numpy.float64,
    )
    for asset_index, symbol in enumerate(protocol_module.FUTURES_SYMBOLS):
        timestamps, values = rates[symbol]
        for row, entry in enumerate(decision_timestamps):
            exit_at = int(entry) + protocol_module.HORIZON_HOURS * 3_600
            start = numpy.searchsorted(timestamps, int(entry), side="right")
            stop = numpy.searchsorted(timestamps, exit_at, side="right")
            result[row, asset_index] = float(numpy.sum(values[start:stop]))
    return result


def _maximum_drawdown(returns: numpy.ndarray) -> float:
    equity = numpy.cumprod(1 + numpy.asarray(returns, dtype=numpy.float64))
    if not len(equity):
        return 0.0
    peaks = numpy.maximum.accumulate(numpy.concatenate(([1.0], equity)))[:-1]
    return float(numpy.max(1 - equity / peaks))


def _economic_summary(
    portfolio_returns: numpy.ndarray,
    trade_returns: numpy.ndarray,
    active: numpy.ndarray,
) -> dict:
    values = numpy.asarray(portfolio_returns, dtype=numpy.float64)
    selected = numpy.asarray(trade_returns, dtype=numpy.float64)[active]
    total_return = float(numpy.prod(1 + values) - 1)
    annualized = float((1 + total_return) ** (365 / len(values)) - 1)
    standard_deviation = float(numpy.std(values, ddof=1))
    sharpe = (
        float(numpy.sqrt(365) * numpy.mean(values) / standard_deviation)
        if standard_deviation > 0
        else 0.0
    )
    gains = float(numpy.sum(selected[selected > 0]))
    losses = float(-numpy.sum(selected[selected < 0]))
    profit_factor = gains / losses if losses > 0 else (math.inf if gains > 0 else 0.0)
    return {
        "daily_observations": len(values),
        "trades": int(numpy.sum(active)),
        "total_return": total_return,
        "annualized_return": annualized,
        "sharpe": sharpe,
        "profit_factor": float(profit_factor),
        "maximum_drawdown": _maximum_drawdown(values),
        "win_rate": float(numpy.mean(selected > 0)) if len(selected) else 0.0,
    }


def economic_metrics(
    *,
    origin_log_prices: numpy.ndarray,
    model_quantiles: numpy.ndarray,
    entry_prices: numpy.ndarray,
    exit_prices: numpy.ndarray,
    funding_sums: numpy.ndarray,
) -> dict:
    """Apply the preregistered non-overlapping daily signal translation."""

    q20 = (
        model_quantiles[:, :, -1, 1] - origin_log_prices
    )
    q80 = (
        model_quantiles[:, :, -1, 7] - origin_log_prices
    )
    threshold = protocol_module.frozen_protocol()["fixed_economic_translation"][
        "round_trip_cost_rate"
    ]
    signals = numpy.where(q20 > threshold, 1.0, numpy.where(q80 < -threshold, -1.0, 0.0))
    active = signals != 0
    raw_price_returns = signals * (exit_prices / entry_prices - 1)
    funding_returns = -signals * funding_sums
    base_cost = active * threshold
    stress_cost = active * threshold * 3
    base_trade_returns = raw_price_returns + funding_returns - base_cost
    stress_trade_returns = raw_price_returns + funding_returns - stress_cost
    fraction = protocol_module.frozen_protocol()["fixed_economic_translation"][
        "position_fraction_per_asset"
    ]
    base_portfolio = numpy.sum(base_trade_returns * fraction, axis=1)
    stress_portfolio = numpy.sum(stress_trade_returns * fraction, axis=1)
    by_asset = {}
    for index, asset in enumerate(protocol_module.ASSETS):
        by_asset[asset] = {
            "trades": int(numpy.sum(active[:, index])),
            "longs": int(numpy.sum(signals[:, index] > 0)),
            "shorts": int(numpy.sum(signals[:, index] < 0)),
            "mean_trade_return": float(
                numpy.mean(base_trade_returns[active[:, index], index])
            )
            if numpy.any(active[:, index])
            else 0.0,
        }
    return {
        "base": _economic_summary(base_portfolio, base_trade_returns, active),
        "stress_3x_cost": _economic_summary(
            stress_portfolio,
            stress_trade_returns,
            active,
        ),
        "maximum_gross_fraction": float(numpy.max(numpy.sum(active, axis=1) * fraction)),
        "by_asset": by_asset,
        "signals": signals,
        "base_trade_returns": base_trade_returns,
        "stress_trade_returns": stress_trade_returns,
        "base_portfolio_returns": base_portfolio,
        "stress_portfolio_returns": stress_portfolio,
    }


def evaluate_gates(predictive: dict, economic: dict) -> dict:
    frozen = protocol_module.frozen_protocol()["forward_eligibility_gates"]
    asset_skills = [
        value["mae_skill_vs_unchanged"]
        for value in predictive["by_asset"].values()
    ]
    checks = {
        "minimum_daily_origins": predictive["daily_origins"]
        >= frozen["minimum_daily_origins"],
        "pooled_mae_improvement_over_unchanged": predictive[
            "pooled_mae_skill_vs_unchanged"
        ]
        >= frozen["pooled_mae_improvement_over_unchanged"],
        "every_asset_mae_skill_strictly_positive": all(
            value is not None and value > 0 for value in asset_skills
        ),
        "q10_q90_coverage_range": frozen["q10_q90_coverage_range"][0]
        <= predictive["q10_q90_coverage"]
        <= frozen["q10_q90_coverage_range"][1],
        "minimum_direction_accuracy": predictive["direction_accuracy"]
        >= frozen["minimum_direction_accuracy"],
        "minimum_net_trades": economic["base"]["trades"]
        >= frozen["minimum_net_trades"],
        "minimum_net_sharpe": economic["base"]["sharpe"]
        >= frozen["minimum_net_sharpe"],
        "minimum_net_profit_factor": economic["base"]["profit_factor"]
        >= frozen["minimum_net_profit_factor"],
        "maximum_net_drawdown": economic["base"]["maximum_drawdown"]
        <= frozen["maximum_net_drawdown"],
        "stress_net_return_strictly_positive": economic["stress_3x_cost"][
            "total_return"
        ]
        > 0,
    }
    return {
        "checks": checks,
        "passed": int(sum(checks.values())),
        "total": len(checks),
        "all_passed": all(checks.values()),
    }


def _atomic_npz(path: pathlib.Path, **arrays: numpy.ndarray) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(
        mode="wb",
        dir=path.parent,
        prefix=f".{path.name}.",
        suffix=".tmp",
        delete=False,
    ) as stream:
        temporary = pathlib.Path(stream.name)
        numpy.savez_compressed(stream, **arrays)
        stream.flush()
        os.fsync(stream.fileno())
    os.replace(temporary, path)


def run_evaluation(
    *,
    lock_value: typing.Union[str, pathlib.Path],
    lock_artifacts: dict[str, typing.Union[str, pathlib.Path]],
    futures_value: typing.Union[str, pathlib.Path],
    spot_value: typing.Union[str, pathlib.Path],
    funding_value: typing.Union[str, pathlib.Path],
    checkpoint_value: typing.Union[str, pathlib.Path],
    acceptance_value: typing.Union[str, pathlib.Path],
    output_root_value: typing.Union[str, pathlib.Path],
) -> dict:
    """Run the one allowed historical diagnostic after verifying its lock."""

    lock_path = pathlib.Path(lock_value).resolve()
    lock = verify_evaluation_lock(lock_path, artifacts=lock_artifacts)
    checkpoint = protocol_module.validate_local_checkpoint(
        checkpoint_value,
        acceptance_value,
    )
    output_root = pathlib.Path(output_root_value).resolve()
    forecasts_path = output_root / "forecasts.npz"
    report_path = output_root / "report.json"
    if forecasts_path.exists() or report_path.exists():
        raise EvaluationError("TimesFM 3 historical evaluation already exists")
    panel = protocol_module.load_aligned_panel(
        futures_value,
        spot_value,
        funding_value,
    )
    origin_indices = protocol_module.eligible_origin_indices(panel)
    if len(origin_indices) != 1_130:
        raise EvaluationError("eligible origin count differs from frozen preflight")

    from timesfm3 import ModelConfig, TimesFM3Evaluator

    load_started = time.monotonic()
    model = TimesFM3Evaluator(
        ModelConfig(
            checkpoint_path=str(pathlib.Path(checkpoint_value).resolve()),
            per_core_batch_size=1,
            device="cpu",
            local_files_only=True,
            revision=protocol_module.MODEL_REVISION,
        )
    )
    load_seconds = time.monotonic() - load_started
    count = len(origin_indices)
    shape = (count, len(protocol_module.ASSETS), protocol_module.HORIZON_HOURS)
    model_paths = numpy.empty(shape, dtype=numpy.float32)
    model_quantiles = numpy.empty((*shape, len(QUANTILES)), dtype=numpy.float32)
    actual_paths = numpy.empty(shape, dtype=numpy.float32)
    unchanged_paths = numpy.empty(shape, dtype=numpy.float32)
    seasonal_paths = numpy.empty(shape, dtype=numpy.float32)
    ar1_paths = numpy.empty(shape, dtype=numpy.float32)
    origin_log_prices = numpy.empty((count, len(protocol_module.ASSETS)), dtype=numpy.float32)
    decision_timestamps = numpy.empty(count, dtype=numpy.int64)
    entry_prices = numpy.empty((count, len(protocol_module.ASSETS)), dtype=numpy.float64)
    exit_prices = numpy.empty_like(entry_prices)
    forecast_started = time.monotonic()
    for row, raw_origin in enumerate(origin_indices):
        origin = int(raw_origin)
        query = protocol_module.build_causal_query(panel, origin)
        output = next(
            model.predict_batch(
                contexts=[query.targets.astype(numpy.float32)],
                horizon=protocol_module.HORIZON_HOURS,
                past_only_covariates=[
                    query.past_only_covariates.astype(numpy.float32)
                ],
                past_future_covariates=[
                    query.past_future_covariates.astype(numpy.float32)
                ],
                return_quantiles=True,
                use_symmetric_averaging=False,
            )
        )
        forecast = numpy.asarray(output.forecast, dtype=numpy.float32)
        quantiles = numpy.asarray(output.quantiles, dtype=numpy.float32)
        if forecast.shape != shape[1:] or quantiles.shape != (
            *shape[1:],
            len(QUANTILES),
        ):
            raise EvaluationError("TimesFM 3 returned an unexpected shape")
        if not numpy.all(numpy.isfinite(forecast)) or not numpy.all(
            numpy.isfinite(quantiles)
        ):
            raise EvaluationError("TimesFM 3 returned non-finite values")
        current = query.targets[:, -1]
        future_closes = panel.futures_candles[
            :, origin + 1 : origin + protocol_module.HORIZON_HOURS + 1, 4
        ]
        actual = numpy.log(future_closes)
        model_paths[row] = forecast
        model_quantiles[row] = quantiles
        actual_paths[row] = actual
        unchanged_paths[row] = numpy.repeat(
            current[:, None], protocol_module.HORIZON_HOURS, axis=1
        )
        seasonal_paths[row] = query.targets[:, -protocol_module.HORIZON_HOURS :]
        ar1_paths[row] = ar1_path(query.targets, protocol_module.HORIZON_HOURS)
        origin_log_prices[row] = current
        decision_timestamps[row] = query.decision_timestamp
        entry_prices[row] = panel.futures_candles[:, origin + 1, 1]
        exit_prices[row] = panel.futures_candles[
            :, origin + protocol_module.HORIZON_HOURS, 4
        ]
        if (row + 1) % 25 == 0 or row + 1 == count:
            elapsed = time.monotonic() - forecast_started
            print(
                json.dumps(
                    {
                        "status": "forecasting",
                        "completed": row + 1,
                        "total": count,
                        "elapsed_seconds": round(elapsed, 3),
                    },
                    sort_keys=True,
                ),
                flush=True,
            )

    forecast_seconds = time.monotonic() - forecast_started
    rates = funding_module.load_funding(funding_value)
    funding_sums = _funding_sums(rates, decision_timestamps)
    predictive = predictive_metrics(
        origin_log_prices=origin_log_prices,
        actual_log_paths=actual_paths,
        model_paths=model_paths,
        model_quantiles=model_quantiles,
        unchanged_paths=unchanged_paths,
        seasonal_paths=seasonal_paths,
        ar1_paths=ar1_paths,
    )
    economic_full = economic_metrics(
        origin_log_prices=origin_log_prices,
        model_quantiles=model_quantiles,
        entry_prices=entry_prices,
        exit_prices=exit_prices,
        funding_sums=funding_sums,
    )
    economic = {
        key: value
        for key, value in economic_full.items()
        if key
        not in {
            "signals",
            "base_trade_returns",
            "stress_trade_returns",
            "base_portfolio_returns",
            "stress_portfolio_returns",
        }
    }
    gates = evaluate_gates(predictive, economic)
    _atomic_npz(
        forecasts_path,
        decision_timestamps=decision_timestamps,
        origin_log_prices=origin_log_prices,
        model_paths=model_paths,
        model_quantiles=model_quantiles,
        actual_log_paths=actual_paths,
        unchanged_log_paths=unchanged_paths,
        seasonal_log_paths=seasonal_paths,
        ar1_log_paths=ar1_paths,
        entry_prices=entry_prices,
        exit_prices=exit_prices,
        funding_sums=funding_sums,
        signals=economic_full["signals"],
        base_trade_returns=economic_full["base_trade_returns"],
        stress_trade_returns=economic_full["stress_trade_returns"],
        base_portfolio_returns=economic_full["base_portfolio_returns"],
        stress_portfolio_returns=economic_full["stress_portfolio_returns"],
    )
    report = {
        "schema_version": SCHEMA_VERSION,
        "evaluator_version": EVALUATOR_VERSION,
        "created_at": datetime.datetime.now(datetime.timezone.utc).isoformat(),
        "verdict": (
            "PASS_DIAGNOSTIC_FORWARD_OBSERVER_REVIEW_REQUIRED"
            if gates["all_passed"]
            else "REJECTED_HISTORICAL_DIAGNOSTIC"
        ),
        "historical_role": "diagnostic_only_due_to_dataset_reuse",
        "protocol_sha256": lock["protocol_sha256"],
        "evaluation_lock_content_sha256": lock["content_sha256"],
        "checkpoint": checkpoint,
        "forecast_artifact": _artifact("forecasts", forecasts_path),
        "runtime": {
            "device": "cpu",
            "model_load_seconds": load_seconds,
            "forecast_seconds": forecast_seconds,
            "seconds_per_origin": forecast_seconds / count,
        },
        "predictive": predictive,
        "economic": economic,
        "gates": gates,
        "research_only": True,
        "credentials_used": False,
        "orders_authorized": False,
        "paper_orders_authorized": False,
        "automatic_promotion": False,
        "real_income_authorized": False,
    }
    report["content_sha256"] = protocol_module.logical_hash(report)
    protocol_module._atomic_json(report_path, report)
    return report


def _parse_artifacts(values: list[str]) -> dict[str, str]:
    artifacts = {}
    for value in values:
        if "=" not in value:
            raise ValueError("artifacts must use label=path")
        label, path = value.split("=", 1)
        if not label or label in artifacts:
            raise ValueError("artifact labels must be unique and non-empty")
        artifacts[label] = path
    return artifacts


def create_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Single-run offline TimesFM 3 evaluator; cannot place orders."
    )
    commands = parser.add_subparsers(dest="command", required=True)
    lock = commands.add_parser("freeze-lock")
    lock.add_argument("--protocol", required=True)
    lock.add_argument("--phase-zero-lock", required=True)
    lock.add_argument("--checkpoint-verification", required=True)
    lock.add_argument("--license-acceptance", required=True)
    lock.add_argument("--artifact", action="append", default=[])
    lock.add_argument("--output", required=True)
    evaluate = commands.add_parser("evaluate")
    evaluate.add_argument("--lock", required=True)
    evaluate.add_argument("--artifact", action="append", default=[])
    evaluate.add_argument("--futures", required=True)
    evaluate.add_argument("--spot", required=True)
    evaluate.add_argument("--funding", required=True)
    evaluate.add_argument("--checkpoint", required=True)
    evaluate.add_argument("--license-acceptance", required=True)
    evaluate.add_argument("--output-root", required=True)
    return parser


def main(argv: typing.Optional[list[str]] = None) -> int:
    arguments = create_parser().parse_args(argv)
    artifacts = _parse_artifacts(arguments.artifact)
    if arguments.command == "freeze-lock":
        path = write_evaluation_lock(
            protocol_value=arguments.protocol,
            phase_zero_lock_value=arguments.phase_zero_lock,
            checkpoint_verification_value=arguments.checkpoint_verification,
            license_acceptance_value=arguments.license_acceptance,
            artifacts=artifacts,
            output_value=arguments.output,
        )
        print(json.dumps({"evaluation_lock": str(path)}, sort_keys=True))
        return 0
    report = run_evaluation(
        lock_value=arguments.lock,
        lock_artifacts=artifacts,
        futures_value=arguments.futures,
        spot_value=arguments.spot,
        funding_value=arguments.funding,
        checkpoint_value=arguments.checkpoint,
        acceptance_value=arguments.license_acceptance,
        output_root_value=arguments.output_root,
    )
    print(json.dumps(report, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
