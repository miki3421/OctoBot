"""Causal direct multi-horizon price-path research forecaster.

The model predicts close-to-close log returns independently at 1h, 2h, 4h,
6h and 8h from a closed 15m candle.  A robust linear ridge model supplies the
conditional center; held-out calibration residuals supply the 10th, 50th and
90th percentiles.  All outputs are research-only and cannot authorize orders.
"""

from __future__ import annotations

import argparse
import dataclasses
import datetime
import functools
import json
import os
import pathlib
import typing

import numpy

from octobot.ai_strategy_lab import dataset as dataset_module
from octobot.ai_strategy_lab import h2_backtest
from octobot.ai_strategy_lab import perfect_map_student as student


SCHEMA_VERSION = 1
PROTOCOL_VERSION = "direct_multi_horizon_quantile_ridge_v1"
PREREGISTRATION_DATE = "2026-07-27"
CANDLE_SECONDS = 900
ASSETS = ("BTC", "ETH")
HORIZONS = (("1h", 4), ("2h", 8), ("4h", 16), ("6h", 24), ("8h", 32))
QUANTILES = (0.10, 0.50, 0.90)
FEATURE_WARMUP = 96
TRAINING_STRIDE = 2
RIDGE_CANDIDATES = (0.0001, 0.001, 0.01, 0.1, 1.0)
ROLLING_ACCURACY_WINDOW = 96
MINIMUM_ROLLING_SAMPLES = 24
SPLITS = {
    "train": ("2022-05-01", "2024-12-30"),
    "calibration": ("2025-01-02", "2025-03-30"),
    "selection_reused": ("2025-04-02", "2025-06-29"),
    "binance_reused_2025": ("2025-07-02", "2025-12-30"),
    "binance_reused_2026": ("2026-01-02", "2026-06-29"),
    "kucoin_reused_2026": ("2026-01-02", "2026-07-20"),
}


@dataclasses.dataclass(frozen=True)
class PathDataset:
    features: numpy.ndarray
    targets_pct: numpy.ndarray
    timestamps: numpy.ndarray
    candle_indices: numpy.ndarray
    candles: numpy.ndarray

    def take(self, mask: numpy.ndarray) -> "PathDataset":
        return PathDataset(
            features=self.features[mask],
            targets_pct=self.targets_pct[mask],
            timestamps=self.timestamps[mask],
            candle_indices=self.candle_indices[mask],
            candles=self.candles,
        )


@dataclasses.dataclass(frozen=True)
class DirectPathModel:
    asset: str
    feature_mean: numpy.ndarray
    feature_scale: numpy.ndarray
    weights: numpy.ndarray
    residual_quantiles_pct: numpy.ndarray
    prediction_lower_pct: numpy.ndarray
    prediction_upper_pct: numpy.ndarray
    ridge_alpha: float

    def predict(self, features: numpy.ndarray) -> dict[str, numpy.ndarray]:
        values = numpy.asarray(features, dtype=float)
        standardized = numpy.clip(
            (values - self.feature_mean) / self.feature_scale,
            -8.0,
            8.0,
        )
        raw = (
            standardized @ self.weights[:-1]
            + self.weights[-1]
        )
        raw = numpy.clip(
            raw,
            self.prediction_lower_pct,
            self.prediction_upper_pct,
        )
        quantiles = (
            raw[:, :, None]
            + self.residual_quantiles_pct[None, :, :]
        )
        quantiles.sort(axis=2)
        return {
            "raw_return_pct": raw,
            "lower_return_pct": quantiles[:, :, 0],
            "median_return_pct": quantiles[:, :, 1],
            "upper_return_pct": quantiles[:, :, 2],
        }

    def save(
        self, directory_value: typing.Union[str, pathlib.Path]
    ) -> dict:
        directory = pathlib.Path(directory_value).resolve()
        directory.mkdir(parents=True, exist_ok=True)
        arrays_path = directory / "model.npz"
        numpy.savez_compressed(
            arrays_path,
            feature_mean=self.feature_mean,
            feature_scale=self.feature_scale,
            weights=self.weights,
            residual_quantiles_pct=self.residual_quantiles_pct,
            prediction_lower_pct=self.prediction_lower_pct,
            prediction_upper_pct=self.prediction_upper_pct,
        )
        metadata_path = directory / "model.json"
        metadata_path.write_text(
            json.dumps(
                {
                    "schema_version": SCHEMA_VERSION,
                    "protocol_version": PROTOCOL_VERSION,
                    "asset": self.asset,
                    "time_frame": "15m",
                    "feature_names": list(feature_names()),
                    "horizons": [
                        {"name": name, "candles": candles}
                        for name, candles in HORIZONS
                    ],
                    "quantiles": list(QUANTILES),
                    "ridge_alpha": self.ridge_alpha,
                    "research_only": True,
                    "orders_authorized": False,
                    "paper_orders_authorized": False,
                },
                indent=2,
                sort_keys=True,
            )
            + "\n",
            encoding="utf-8",
        )
        return {
            "arrays": student._artifact(arrays_path),
            "metadata": student._artifact(metadata_path),
        }

    @classmethod
    def load(
        cls, directory_value: typing.Union[str, pathlib.Path]
    ) -> "DirectPathModel":
        directory = pathlib.Path(directory_value).resolve()
        metadata = json.loads(
            (directory / "model.json").read_text(encoding="utf-8")
        )
        if metadata.get("schema_version") != SCHEMA_VERSION:
            raise ValueError("unsupported price-path model schema")
        if metadata.get("protocol_version") != PROTOCOL_VERSION:
            raise ValueError("unsupported price-path protocol")
        if tuple(metadata.get("feature_names", ())) != feature_names():
            raise ValueError("price-path feature schema differs")
        expected_horizons = [
            {"name": name, "candles": candles}
            for name, candles in HORIZONS
        ]
        if metadata.get("horizons") != expected_horizons:
            raise ValueError("price-path horizons differ")
        with numpy.load(directory / "model.npz") as arrays:
            return cls(
                asset=str(metadata["asset"]),
                feature_mean=arrays["feature_mean"],
                feature_scale=arrays["feature_scale"],
                weights=arrays["weights"],
                residual_quantiles_pct=arrays[
                    "residual_quantiles_pct"
                ],
                prediction_lower_pct=arrays[
                    "prediction_lower_pct"
                ],
                prediction_upper_pct=arrays[
                    "prediction_upper_pct"
                ],
                ridge_alpha=float(metadata["ridge_alpha"]),
            )


def feature_names() -> tuple[str, ...]:
    names = []
    for window in (1, 2, 4, 8, 16, 32, 64, 96):
        names.append(f"log_return_{window}")
    for window in (4, 8, 16, 32, 64, 96):
        names.append(f"realized_volatility_{window}")
    for window in (8, 16, 32, 64, 96):
        names.append(f"range_position_{window}")
    for window in (8, 16, 32, 64, 96):
        names.append(f"relative_volume_{window}")
    for window in (4, 16, 32, 96):
        names.append(f"atr_{window}")
    names.extend(
        (
            "body_pct",
            "range_pct",
            "upper_wick_pct",
            "lower_wick_pct",
            "volume_log_change_1",
            "volume_log_change_4",
            "ema_spread_8_32",
            "ema_spread_32_96",
            "return_to_volatility_4_32",
            "return_to_volatility_16_96",
            "hour_sin",
            "hour_cos",
            "weekday_sin",
            "weekday_cos",
        )
    )
    return tuple(names)


def _lagged_log_return(close: numpy.ndarray, window: int) -> numpy.ndarray:
    result = numpy.full(len(close), numpy.nan)
    result[window:] = numpy.log(close[window:] / close[:-window])
    return result


def _rolling_mean(values: numpy.ndarray, window: int) -> numpy.ndarray:
    result = numpy.full(len(values), numpy.nan)
    clean = numpy.nan_to_num(values, nan=0.0)
    sums = numpy.concatenate(([0.0], numpy.cumsum(clean)))
    result[window - 1 :] = (
        sums[window:] - sums[:-window]
    ) / window
    return result


def _rolling_std(values: numpy.ndarray, window: int) -> numpy.ndarray:
    result = numpy.full(len(values), numpy.nan)
    clean = numpy.nan_to_num(values, nan=0.0)
    sums = numpy.concatenate(([0.0], numpy.cumsum(clean)))
    squares = numpy.concatenate(([0.0], numpy.cumsum(clean * clean)))
    mean = (sums[window:] - sums[:-window]) / window
    variance = (
        (squares[window:] - squares[:-window]) / window
        - mean * mean
    )
    result[window - 1 :] = numpy.sqrt(numpy.maximum(variance, 0.0))
    return result


def _rolling_extreme(
    values: numpy.ndarray, window: int, maximum: bool
) -> numpy.ndarray:
    result = numpy.full(len(values), numpy.nan)
    view = numpy.lib.stride_tricks.as_strided(
        values,
        shape=(len(values) - window + 1, window),
        strides=(values.strides[0], values.strides[0]),
    )
    reducer = numpy.max if maximum else numpy.min
    result[window - 1 :] = reducer(view, axis=1)
    return result


def _ema(values: numpy.ndarray, span: int) -> numpy.ndarray:
    result = numpy.empty(len(values), dtype=float)
    result[0] = values[0]
    alpha = 2.0 / (span + 1.0)
    for index in range(1, len(values)):
        result[index] = (
            alpha * values[index]
            + (1.0 - alpha) * result[index - 1]
        )
    return result


def causal_features(candles: numpy.ndarray) -> numpy.ndarray:
    if candles.ndim != 2 or candles.shape[1] < 6:
        raise ValueError("candles must be an OHLCV matrix")
    times = candles[:, 0].astype(numpy.int64)
    open_price = candles[:, 1].astype(float)
    high = candles[:, 2].astype(float)
    low = candles[:, 3].astype(float)
    close = candles[:, 4].astype(float)
    volume = candles[:, 5].astype(float)
    if numpy.any(close <= 0):
        raise ValueError("price-path features require positive closes")
    log_return_1 = _lagged_log_return(close, 1)
    columns = []
    returns = {}
    for window in (1, 2, 4, 8, 16, 32, 64, 96):
        returns[window] = _lagged_log_return(close, window)
        columns.append(returns[window])
    volatility = {}
    for window in (4, 8, 16, 32, 64, 96):
        volatility[window] = _rolling_std(log_return_1, window)
        columns.append(volatility[window])
    for window in (8, 16, 32, 64, 96):
        rolling_high = _rolling_extreme(high, window, True)
        rolling_low = _rolling_extreme(low, window, False)
        width = numpy.maximum(rolling_high - rolling_low, close * 1e-9)
        columns.append((close - rolling_low) / width - 0.5)
    log_volume = numpy.log1p(numpy.maximum(volume, 0.0))
    for window in (8, 16, 32, 64, 96):
        mean = _rolling_mean(log_volume, window)
        deviation = _rolling_std(log_volume, window)
        columns.append(
            (log_volume - mean) / numpy.maximum(deviation, 1e-8)
        )
    previous_close = numpy.concatenate(([close[0]], close[:-1]))
    true_range = numpy.maximum.reduce(
        (
            high - low,
            numpy.abs(high - previous_close),
            numpy.abs(low - previous_close),
        )
    ) / close
    for window in (4, 16, 32, 96):
        columns.append(_rolling_mean(true_range, window))
    safe_close = numpy.maximum(close, 1e-12)
    columns.extend(
        (
            (close - open_price) / safe_close,
            (high - low) / safe_close,
            (high - numpy.maximum(open_price, close)) / safe_close,
            (numpy.minimum(open_price, close) - low) / safe_close,
            log_volume - numpy.roll(log_volume, 1),
            log_volume - numpy.roll(log_volume, 4),
        )
    )
    columns[-2][0] = numpy.nan
    columns[-1][:4] = numpy.nan
    ema_8 = _ema(close, 8)
    ema_32 = _ema(close, 32)
    ema_96 = _ema(close, 96)
    columns.extend(
        (
            (ema_8 - ema_32) / safe_close,
            (ema_32 - ema_96) / safe_close,
            returns[4] / numpy.maximum(volatility[32], 1e-8),
            returns[16] / numpy.maximum(volatility[96], 1e-8),
        )
    )
    close_times = times + CANDLE_SECONDS
    hours = (close_times % 86_400) / 3_600
    weekdays = (
        (close_times // 86_400 + 3) % 7
    ).astype(float)
    columns.extend(
        (
            numpy.sin(2 * numpy.pi * hours / 24),
            numpy.cos(2 * numpy.pi * hours / 24),
            numpy.sin(2 * numpy.pi * weekdays / 7),
            numpy.cos(2 * numpy.pi * weekdays / 7),
        )
    )
    features = numpy.column_stack(columns)
    if features.shape[1] != len(feature_names()):
        raise ValueError("price-path feature count differs")
    return features


def build_dataset(candles: numpy.ndarray) -> PathDataset:
    maximum_horizon = max(candles_count for _name, candles_count in HORIZONS)
    gaps = numpy.flatnonzero(
        numpy.diff(candles[:, 0].astype(numpy.int64)) != CANDLE_SECONDS
    )
    starts = numpy.concatenate((numpy.asarray([0]), gaps + 1))
    ends = numpy.concatenate((gaps + 1, numpy.asarray([len(candles)])))
    blocks = []
    for start_value, end_value in zip(starts, ends):
        start = int(start_value)
        end = int(end_value)
        if end - start <= FEATURE_WARMUP + maximum_horizon:
            continue
        block = candles[start:end]
        features = causal_features(block)
        indices = numpy.arange(
            FEATURE_WARMUP - 1,
            len(block) - maximum_horizon,
            dtype=numpy.int64,
        )
        indices = indices[
            numpy.all(numpy.isfinite(features[indices]), axis=1)
        ]
        if not len(indices):
            continue
        targets = numpy.column_stack(
            [
                numpy.log(
                    block[indices + horizon_bars, 4]
                    / block[indices, 4]
                )
                * 100
                for _horizon_name, horizon_bars in HORIZONS
            ]
        )
        blocks.append(
            PathDataset(
                features=features[indices].astype(numpy.float32),
                targets_pct=targets.astype(numpy.float32),
                timestamps=(
                    block[indices, 0].astype(numpy.int64)
                    + CANDLE_SECONDS
                ),
                candle_indices=indices + start,
                candles=candles,
            )
        )
    if not blocks:
        raise ValueError("no complete direct price-path examples")
    return PathDataset(
        features=numpy.concatenate([block.features for block in blocks]),
        targets_pct=numpy.concatenate(
            [block.targets_pct for block in blocks]
        ),
        timestamps=numpy.concatenate(
            [block.timestamps for block in blocks]
        ),
        candle_indices=numpy.concatenate(
            [block.candle_indices for block in blocks]
        ),
        candles=candles,
    )


def _fit_weights(
    features: numpy.ndarray,
    targets: numpy.ndarray,
    alpha: float,
) -> numpy.ndarray:
    augmented = numpy.column_stack(
        (features, numpy.ones(len(features), dtype=float))
    )
    gram = augmented.T @ augmented / len(augmented)
    right = augmented.T @ targets / len(augmented)
    penalty = numpy.eye(gram.shape[0]) * alpha
    penalty[-1, -1] = 0.0
    return numpy.linalg.solve(gram + penalty, right)


def fit_model(
    asset: str, dataset: PathDataset
) -> tuple[DirectPathModel, dict]:
    train_mask = student._date_mask(
        dataset.timestamps, *SPLITS["train"]
    )
    calibration_mask = student._date_mask(
        dataset.timestamps, *SPLITS["calibration"]
    )
    train_rows = numpy.flatnonzero(train_mask)[::TRAINING_STRIDE]
    calibration_rows = numpy.flatnonzero(calibration_mask)
    if len(train_rows) < 20_000 or len(calibration_rows) < 4_000:
        raise ValueError(f"insufficient {asset} direct path examples")
    split = len(calibration_rows) // 2
    selection_rows = calibration_rows[:split]
    residual_rows = calibration_rows[split:]
    mean = numpy.mean(dataset.features[train_rows], axis=0, dtype=float)
    scale = numpy.std(dataset.features[train_rows], axis=0, dtype=float)
    scale = numpy.where(scale < 1e-8, 1.0, scale)
    standardized_train = numpy.clip(
        (dataset.features[train_rows] - mean) / scale,
        -8.0,
        8.0,
    )
    standardized_selection = numpy.clip(
        (dataset.features[selection_rows] - mean) / scale,
        -8.0,
        8.0,
    )
    alpha_scores = []
    weights_by_alpha = {}
    for alpha in RIDGE_CANDIDATES:
        weights = _fit_weights(
            standardized_train,
            dataset.targets_pct[train_rows],
            alpha,
        )
        weights_by_alpha[alpha] = weights
        predictions = (
            standardized_selection @ weights[:-1] + weights[-1]
        )
        model_mae = numpy.mean(
            numpy.abs(
                dataset.targets_pct[selection_rows] - predictions
            ),
            axis=0,
        )
        flat_mae = numpy.mean(
            numpy.abs(dataset.targets_pct[selection_rows]), axis=0
        )
        alpha_scores.append(
            {
                "alpha": alpha,
                "mean_mae_pct": float(numpy.mean(model_mae)),
                "mean_flat_mae_pct": float(numpy.mean(flat_mae)),
                "mean_skill_vs_flat_pct": float(
                    numpy.mean((flat_mae - model_mae) / flat_mae) * 100
                ),
            }
        )
    selected_score = min(
        alpha_scores, key=lambda row: row["mean_mae_pct"]
    )
    selected_alpha = float(selected_score["alpha"])
    weights = weights_by_alpha[selected_alpha]
    standardized_residual = numpy.clip(
        (dataset.features[residual_rows] - mean) / scale,
        -8.0,
        8.0,
    )
    residual_prediction = (
        standardized_residual @ weights[:-1] + weights[-1]
    )
    residuals = (
        dataset.targets_pct[residual_rows] - residual_prediction
    )
    residual_quantiles = numpy.quantile(
        residuals, QUANTILES, axis=0
    ).T
    lower = numpy.quantile(
        dataset.targets_pct[train_rows], 0.001, axis=0
    )
    upper = numpy.quantile(
        dataset.targets_pct[train_rows], 0.999, axis=0
    )
    model = DirectPathModel(
        asset=asset,
        feature_mean=mean,
        feature_scale=scale,
        weights=weights,
        residual_quantiles_pct=residual_quantiles,
        prediction_lower_pct=lower,
        prediction_upper_pct=upper,
        ridge_alpha=selected_alpha,
    )
    return model, {
        "asset": asset,
        "training_rows": len(train_rows),
        "alpha_selection_rows": len(selection_rows),
        "residual_calibration_rows": len(residual_rows),
        "alpha_candidates": alpha_scores,
        "selected_alpha": selected_alpha,
    }


def evaluate_predictions(
    targets_pct: numpy.ndarray,
    predictions: dict[str, numpy.ndarray],
) -> dict:
    median = predictions["median_return_pct"]
    lower = predictions["lower_return_pct"]
    upper = predictions["upper_return_pct"]
    result = {}
    for horizon_index, (horizon_name, horizon_bars) in enumerate(HORIZONS):
        actual = targets_pct[:, horizon_index]
        predicted = median[:, horizon_index]
        nonzero = (actual != 0) & (predicted != 0)
        correct = actual[nonzero] * predicted[nonzero] > 0
        model_mae = float(numpy.mean(numpy.abs(actual - predicted)))
        flat_mae = float(numpy.mean(numpy.abs(actual)))
        non_overlapping = numpy.arange(0, len(actual), horizon_bars)
        non_overlap_nonzero = non_overlapping[
            (actual[non_overlapping] != 0)
            & (predicted[non_overlapping] != 0)
        ]
        non_overlap_correct = (
            actual[non_overlap_nonzero]
            * predicted[non_overlap_nonzero]
            > 0
        )
        result[horizon_name] = {
            "examples": len(actual),
            "directional_examples": int(numpy.sum(nonzero)),
            "directional_accuracy_pct": (
                float(numpy.mean(correct) * 100)
                if len(correct)
                else None
            ),
            "inverted_directional_accuracy_pct": (
                float((1.0 - numpy.mean(correct)) * 100)
                if len(correct)
                else None
            ),
            "non_overlapping_examples": len(non_overlap_nonzero),
            "non_overlapping_directional_accuracy_pct": (
                float(numpy.mean(non_overlap_correct) * 100)
                if len(non_overlap_correct)
                else None
            ),
            "non_overlapping_inverted_accuracy_pct": (
                float((1.0 - numpy.mean(non_overlap_correct)) * 100)
                if len(non_overlap_correct)
                else None
            ),
            "model_mean_absolute_error_pct": model_mae,
            "flat_mean_absolute_error_pct": flat_mae,
            "mae_skill_vs_flat_pct": (
                (flat_mae - model_mae) / flat_mae * 100
                if flat_mae
                else None
            ),
            "median_absolute_error_pct": float(
                numpy.median(numpy.abs(actual - predicted))
            ),
            "empirical_band_coverage_pct": float(
                numpy.mean(
                    (actual >= lower[:, horizon_index])
                    & (actual <= upper[:, horizon_index])
                )
                * 100
            ),
            "mean_predicted_return_pct": float(numpy.mean(predicted)),
            "mean_actual_return_pct": float(numpy.mean(actual)),
        }
    return result


def evaluate_block(
    dataset: PathDataset,
    model: DirectPathModel,
    date_range: tuple[str, str],
) -> tuple[dict, dict[str, numpy.ndarray]]:
    mask = student._date_mask(dataset.timestamps, *date_range)
    subset = dataset.take(mask)
    predictions = model.predict(subset.features)
    return (
        {
            "start": date_range[0],
            "end": date_range[1],
            "research_only": True,
            "evidence_role": "diagnostic_reuse",
            "horizons": evaluate_predictions(
                subset.targets_pct, predictions
            ),
        },
        {
            "timestamps": subset.timestamps,
            "targets_pct": subset.targets_pct,
            **predictions,
        },
    )


def _load_asset_15m(
    path: pathlib.Path, asset: str, source_time_frame: str
) -> numpy.ndarray:
    series = dataset_module.load_collector_series(
        [path], required_time_frames=(source_time_frame,)
    )
    matching = [
        frames[source_time_frame].values
        for symbol, frames in series.items()
        if symbol.startswith(f"{asset}/")
    ]
    if len(matching) != 1:
        raise ValueError(f"expected one {asset} series in {path}")
    if source_time_frame == "15m":
        return matching[0]
    if source_time_frame == "5m":
        return h2_backtest._aggregate_5m_to_15m(matching[0])
    raise ValueError("source time frame must be 5m or 15m")


def protocol_sha256(payload: dict) -> str:
    return student._json_hash(payload)


def frozen_protocol() -> dict:
    return {
        "schema_version": SCHEMA_VERSION,
        "protocol_version": PROTOCOL_VERSION,
        "preregistered_on": PREREGISTRATION_DATE,
        "status": "preregistered_design_only",
        "research_only": True,
        "orders_authorized": False,
        "paper_orders_authorized": False,
        "automatic_promotion": False,
        "assets": list(ASSETS),
        "separate_model_per_asset": True,
        "time_frame": "15m",
        "targets": {
            "kind": "future close log return pct",
            "horizons": [
                {"name": name, "candles": candles}
                for name, candles in HORIZONS
            ],
        },
        "features": {
            "causal_at_decision_close": True,
            "future_used": False,
            "names": list(feature_names()),
            "warmup_candles": FEATURE_WARMUP,
        },
        "model": {
            "kind": "standardized direct multi-output ridge",
            "ridge_candidates": list(RIDGE_CANDIDATES),
            "training_stride": TRAINING_STRIDE,
            "prediction_clip_train_quantiles": [0.001, 0.999],
        },
        "uncertainty": {
            "kind": "held-out residual quantiles",
            "quantiles": list(QUANTILES),
            "calibration_split": (
                "first half selects ridge; second half calibrates residuals"
            ),
        },
        "baseline": {
            "name": "unchanged_price",
            "return_pct": 0.0,
            "primary_skill": (
                "mean absolute return error reduction versus flat"
            ),
        },
        "diagnostics": {
            "directional_accuracy": True,
            "mean_absolute_error": True,
            "skill_vs_flat": True,
            "empirical_interval_coverage": True,
            "non_overlapping_directional_audit": True,
            "inverted_eth_audit_only": True,
            "automatic_direction_inversion": False,
        },
        "splits": SPLITS,
        "evidence_policy": {
            "all_dates_after_calibration": "diagnostic_reuse",
            "promotion_eligible": False,
            "new_forward_start_required_after": "2026-07-27",
            "minimum_forward_days": 60,
        },
        "implementation_policy": {
            "protocol_must_exist_before_training": True,
            "result_free_protocol": True,
            "model_reload_must_match": True,
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
            {**protocol, "protocol_sha256": protocol_sha256(protocol)},
            indent=2,
            sort_keys=True,
        )
        + "\n",
        encoding="utf-8",
    )
    return path


def run_study(
    *,
    inputs: dict[str, dict[str, typing.Union[str, pathlib.Path]]],
    output_directory: typing.Union[str, pathlib.Path],
) -> dict:
    output = pathlib.Path(output_directory).resolve()
    protocol_path = output / "protocol.json"
    if not protocol_path.is_file():
        raise FileNotFoundError("write protocol.json before training")
    protocol = frozen_protocol()
    persisted = json.loads(protocol_path.read_text(encoding="utf-8"))
    if persisted.get("protocol_sha256") != protocol_sha256(protocol):
        raise ValueError("persisted price-path protocol differs")
    reports = {}
    model_artifacts = {}
    input_artifacts = {}
    prediction_payload = {}
    replay_differences = {}
    for asset in ASSETS:
        config = inputs[asset]
        binance_path = pathlib.Path(
            config["binance_collector"]
        ).resolve()
        kucoin_path = pathlib.Path(
            config["kucoin_collector"]
        ).resolve()
        binance_dataset = build_dataset(
            _load_asset_15m(binance_path, asset, "15m")
        )
        model, fit_report = fit_model(asset, binance_dataset)
        kucoin_dataset = build_dataset(
            _load_asset_15m(
                kucoin_path,
                asset,
                str(config["kucoin_time_frame"]),
            )
        )
        blocks = {}
        for name, dataset_value, date_range in (
            (
                "selection_reused",
                binance_dataset,
                SPLITS["selection_reused"],
            ),
            (
                "binance_reused_2025",
                binance_dataset,
                SPLITS["binance_reused_2025"],
            ),
            (
                "binance_reused_2026",
                binance_dataset,
                SPLITS["binance_reused_2026"],
            ),
            (
                "kucoin_reused_2026",
                kucoin_dataset,
                SPLITS["kucoin_reused_2026"],
            ),
        ):
            block_report, block_predictions = evaluate_block(
                dataset_value, model, date_range
            )
            blocks[name] = block_report
            for key, values in block_predictions.items():
                prediction_payload[
                    f"{asset.lower()}_{name}_{key}"
                ] = values
        model_directory = output / "models" / asset.lower()
        model_artifacts[asset] = model.save(model_directory)
        restored = DirectPathModel.load(model_directory)
        replay_rows = min(5_000, len(binance_dataset.features))
        original = model.predict(binance_dataset.features[:replay_rows])
        reloaded = restored.predict(
            binance_dataset.features[:replay_rows]
        )
        difference = max(
            float(
                numpy.max(
                    numpy.abs(original[key] - reloaded[key])
                )
            )
            for key in original
        )
        if difference != 0:
            raise ValueError(f"reloaded {asset} path predictions differ")
        replay_differences[asset] = difference
        reports[asset] = {
            "fit": fit_report,
            "diagnostic_reuse_audits": blocks,
            "display_gate": {
                "research_only": True,
                "requires_skill_vs_flat": False,
                "reason": (
                    "the chart must reveal failure as well as success; "
                    "no displayed path authorizes orders"
                ),
            },
        }
        input_artifacts[asset] = {
            "binance_collector": student._artifact(binance_path),
            "kucoin_collector": student._artifact(kucoin_path),
        }
        del binance_dataset
        del kucoin_dataset
    predictions_path = output / "predictions.npz"
    numpy.savez_compressed(predictions_path, **prediction_payload)
    report = {
        "schema_version": SCHEMA_VERSION,
        "protocol_version": PROTOCOL_VERSION,
        "protocol_sha256": protocol_sha256(protocol),
        "created_at": datetime.datetime.now(
            datetime.timezone.utc
        ).isoformat(),
        "research_only": True,
        "orders_authorized": False,
        "paper_orders_authorized": False,
        "automatic_promotion": False,
        "future_used_for_features": False,
        "future_used_for_labels_and_evaluation": True,
        "evidence_role": "diagnostic_reuse",
        "assets": reports,
        "model_replay_max_absolute_difference": replay_differences,
        "promotion_eligible": False,
        "promotion_blocker": (
            "All visible audit dates are reused; collect at least 60 "
            "untouched forward days after 2026-07-27."
        ),
        "artifacts": {
            "protocol": student._artifact(protocol_path),
            "models": model_artifacts,
            "predictions": student._artifact(predictions_path),
            "inputs": input_artifacts,
        },
    }
    report_path = output / "report.json"
    report_path.write_text(
        json.dumps(report, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return {**report, "report_path": str(report_path)}


@functools.lru_cache(maxsize=4)
def _load_live_model(artifact_root: str, asset: str) -> DirectPathModel:
    return DirectPathModel.load(
        pathlib.Path(artifact_root) / "models" / asset.lower()
    )


@functools.lru_cache(maxsize=2)
def _load_live_report(artifact_root: str) -> dict:
    return json.loads(
        (pathlib.Path(artifact_root) / "report.json").read_text(
            encoding="utf-8"
        )
    )


def _advance_display_time(display_time: typing.Any, bars: int) -> str:
    parsed = datetime.datetime.strptime(
        str(display_time), "%y-%m-%d %H:%M:%S"
    )
    return (
        parsed + datetime.timedelta(seconds=bars * CANDLE_SECONDS)
    ).strftime("%y-%m-%d %H:%M:%S")


def _live_accuracy(
    *,
    closed: numpy.ndarray,
    display_values: list[typing.Any],
    valid: numpy.ndarray,
    predictions: dict[str, numpy.ndarray],
    horizon_index: int,
) -> dict:
    horizon_name, horizon_bars = HORIZONS[horizon_index]
    evaluated = []
    for prediction_row, candle_index_value in enumerate(valid):
        candle_index = int(candle_index_value)
        outcome_index = candle_index + horizon_bars
        if outcome_index >= len(closed):
            continue
        predicted = float(
            predictions["median_return_pct"][
                prediction_row, horizon_index
            ]
        )
        actual = float(
            numpy.log(
                closed[outcome_index, 4] / closed[candle_index, 4]
            )
            * 100
        )
        if actual == 0 or predicted == 0:
            continue
        lower = float(
            predictions["lower_return_pct"][
                prediction_row, horizon_index
            ]
        )
        upper = float(
            predictions["upper_return_pct"][
                prediction_row, horizon_index
            ]
        )
        evaluated.append(
            {
                "time": display_values[outcome_index],
                "correct": actual * predicted > 0,
                "inside_band": lower <= actual <= upper,
                "model_error": abs(actual - predicted),
                "flat_error": abs(actual),
            }
        )
    series = []
    for index in range(MINIMUM_ROLLING_SAMPLES - 1, len(evaluated)):
        start = max(0, index - ROLLING_ACCURACY_WINDOW + 1)
        window = evaluated[start : index + 1]
        accuracy = sum(row["correct"] for row in window) / len(window) * 100
        model_mae = sum(row["model_error"] for row in window) / len(window)
        flat_mae = sum(row["flat_error"] for row in window) / len(window)
        series.append(
            {
                "time": evaluated[index]["time"],
                "accuracy_pct": accuracy,
                "inverted_accuracy_pct": 100 - accuracy,
                "skill_vs_flat_pct": (
                    (flat_mae - model_mae) / flat_mae * 100
                    if flat_mae
                    else None
                ),
                "samples": len(window),
            }
        )
    count = len(evaluated)
    model_mae = (
        sum(row["model_error"] for row in evaluated) / count
        if count
        else None
    )
    flat_mae = (
        sum(row["flat_error"] for row in evaluated) / count
        if count
        else None
    )
    return {
        "horizon": horizon_name,
        "horizon_candles": horizon_bars,
        "mature_forecasts": count,
        "overall_directional_accuracy_pct": (
            sum(row["correct"] for row in evaluated) / count * 100
            if count
            else None
        ),
        "overall_inverted_accuracy_pct": (
            (
                1 - sum(row["correct"] for row in evaluated) / count
            )
            * 100
            if count
            else None
        ),
        "rolling_directional_accuracy_pct": (
            series[-1]["accuracy_pct"] if series else None
        ),
        "rolling_inverted_accuracy_pct": (
            series[-1]["inverted_accuracy_pct"] if series else None
        ),
        "model_mean_absolute_error_pct": model_mae,
        "flat_mean_absolute_error_pct": flat_mae,
        "mae_skill_vs_flat_pct": (
            (flat_mae - model_mae) / flat_mae * 100
            if flat_mae
            else None
        ),
        "rolling_skill_vs_flat_pct": (
            series[-1]["skill_vs_flat_pct"] if series else None
        ),
        "empirical_band_coverage_pct": (
            sum(row["inside_band"] for row in evaluated) / count * 100
            if count
            else None
        ),
        "series": series,
    }


def analyze_chart_path(
    *,
    times: typing.Iterable[typing.Any],
    display_times: typing.Iterable[typing.Any],
    opens: typing.Iterable[float],
    highs: typing.Iterable[float],
    lows: typing.Iterable[float],
    closes: typing.Iterable[float],
    volumes: typing.Iterable[float],
    symbol: str,
    artifact_root: typing.Optional[
        typing.Union[str, pathlib.Path]
    ] = None,
) -> dict:
    columns = [
        list(times),
        list(opens),
        list(highs),
        list(lows),
        list(closes),
        list(volumes),
    ]
    display_values = list(display_times)
    lengths = {len(column) for column in columns} | {len(display_values)}
    if len(lengths) != 1 or not columns[0]:
        raise ValueError("chart candle arrays must be non-empty and aligned")
    asset = str(symbol).split("/", 1)[0].upper()
    if asset not in ASSETS:
        raise ValueError(f"price-path model does not support {asset}")
    candles = numpy.column_stack(
        [numpy.asarray(column, dtype=float) for column in columns]
    )
    closed_count = len(candles) - 1
    if closed_count < FEATURE_WARMUP + max(
        horizon for _name, horizon in HORIZONS
    ):
        raise ValueError("price-path model needs more closed 15m candles")
    closed = candles[:closed_count]
    features = causal_features(closed)
    valid = numpy.flatnonzero(
        numpy.all(numpy.isfinite(features), axis=1)
    )
    if not len(valid):
        raise ValueError("price-path model has no complete feature rows")
    root = str(
        pathlib.Path(
            artifact_root
            or os.environ.get(
                "PRICE_PATH_FORECASTER_V1_ROOT",
                "/octobot/backtesting/research/price_path_forecaster_v1",
            )
        ).resolve()
    )
    model = _load_live_model(root, asset)
    predictions = model.predict(features[valid])
    latest_row = len(valid) - 1
    latest_index = int(valid[latest_row])
    x_values = [display_values[latest_index]]
    median_prices = [float(closed[latest_index, 4])]
    lower_prices = [float(closed[latest_index, 4])]
    upper_prices = [float(closed[latest_index, 4])]
    endpoints = {}
    anchor_price = float(closed[latest_index, 4])
    predicted_returns = {}
    for horizon_index, (horizon_name, horizon_bars) in enumerate(HORIZONS):
        time_value = _advance_display_time(
            display_values[latest_index], horizon_bars
        )
        lower_return = float(
            predictions["lower_return_pct"][latest_row, horizon_index]
        )
        median_return = float(
            predictions["median_return_pct"][latest_row, horizon_index]
        )
        upper_return = float(
            predictions["upper_return_pct"][latest_row, horizon_index]
        )
        lower_price = anchor_price * numpy.exp(lower_return / 100)
        median_price = anchor_price * numpy.exp(median_return / 100)
        upper_price = anchor_price * numpy.exp(upper_return / 100)
        endpoints[horizon_name] = {
            "time": time_value,
            "horizon_candles": horizon_bars,
            "lower_price": float(lower_price),
            "median_price": float(median_price),
            "upper_price": float(upper_price),
            "lower_return_pct": lower_return,
            "median_return_pct": median_return,
            "upper_return_pct": upper_return,
        }
        predicted_returns[horizon_name] = median_return
        x_values.append(time_value)
        lower_prices.append(float(lower_price))
        median_prices.append(float(median_price))
        upper_prices.append(float(upper_price))
    accuracy = {
        horizon_name: _live_accuracy(
            closed=closed,
            display_values=display_values[:closed_count],
            valid=valid,
            predictions=predictions,
            horizon_index=horizon_index,
        )
        for horizon_index, (horizon_name, _bars) in enumerate(HORIZONS)
    }
    longest_return = predicted_returns[HORIZONS[-1][0]]
    report = _load_live_report(root)
    audit = report["assets"][asset]["diagnostic_reuse_audits"][
        "kucoin_reused_2026"
    ]["horizons"]
    return {
        "schema_version": SCHEMA_VERSION,
        "mode": PROTOCOL_VERSION,
        "asset": asset,
        "research_only": True,
        "orders_authorized": False,
        "paper_orders_authorized": False,
        "automatic_promotion": False,
        "forecast_uses_future_outcomes": False,
        "accuracy_uses_future_outcomes": True,
        "overlapping_forecasts": True,
        "time_frame": "15m",
        "quantiles": list(QUANTILES),
        "nominal_band_coverage_pct": 80.0,
        "rolling_accuracy_window_forecasts": ROLLING_ACCURACY_WINDOW,
        "minimum_rolling_accuracy_samples": MINIMUM_ROLLING_SAMPLES,
        "baseline": "unchanged_price",
        "latest": {
            "anchor_time": display_values[latest_index],
            "anchor_price": anchor_price,
            "preferred_direction": (
                "LONG" if longest_return >= 0 else "SHORT"
            ),
            "predicted_return_pct": predicted_returns,
            "x": x_values,
            "median": median_prices,
            "lower": lower_prices,
            "upper": upper_prices,
            "endpoints": endpoints,
        },
        "accuracy": accuracy,
        "frozen_kucoin_audit": audit,
        "warning": (
            "Direct close-price quantile forecast on reused dates. "
            "Directional accuracy is not win rate; negative skill versus "
            "flat means the median is less accurate than unchanged price."
        ),
    }


def _input_mapping(args: argparse.Namespace) -> dict:
    return {
        "BTC": {
            "binance_collector": args.binance_btc_collector,
            "kucoin_collector": args.kucoin_btc_collector,
            "kucoin_time_frame": "5m",
        },
        "ETH": {
            "binance_collector": args.binance_eth_collector,
            "kucoin_collector": args.kucoin_eth_collector,
            "kucoin_time_frame": "15m",
        },
    }


def main(argv: typing.Optional[list[str]] = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-directory", required=True)
    parser.add_argument("--write-protocol-only", action="store_true")
    parser.add_argument("--binance-btc-collector")
    parser.add_argument("--binance-eth-collector")
    parser.add_argument("--kucoin-btc-collector")
    parser.add_argument("--kucoin-eth-collector")
    args = parser.parse_args(argv)
    if args.write_protocol_only:
        print(write_protocol(args.output_directory))
        return 0
    required = (
        args.binance_btc_collector,
        args.binance_eth_collector,
        args.kucoin_btc_collector,
        args.kucoin_eth_collector,
    )
    if any(value is None for value in required):
        parser.error("all collector paths are required for training")
    report = run_study(
        inputs=_input_mapping(args),
        output_directory=args.output_directory,
    )
    print(json.dumps(report, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
