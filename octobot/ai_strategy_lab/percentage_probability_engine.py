"""Calibrated, research-only percentage probabilities for BTC charts.

The model estimates the probability that price reaches the +1.2% activation
level before the -1.0% initial stop within a fixed 24-hour horizon.  Every
feature is computed from candles available at the decision close.  Future
candles are used exclusively to create and evaluate labels.
"""

from __future__ import annotations

import argparse
import dataclasses
import datetime
import hashlib
import json
import math
import os
import pathlib
import typing

import numpy

from octobot.ai_strategy_lab import dataset as dataset_module
from octobot.ai_strategy_lab import indicators
from octobot.ai_strategy_lab import model as model_module
from octobot.ai_strategy_lab import percentage_engine


FEATURE_NAMES = (
    "return_1",
    "return_4",
    "atr_pct",
    "adx",
    "ema_spread_pct",
    "ema_slope_pct",
    "bb_position",
    "bb_width_pct",
    "rsi_centered",
    "macd_hist_pct",
    "return_volatility",
    "volume_zscore",
)
DIRECTIONAL_FEATURE_NAMES = tuple(
    name for name in FEATURE_NAMES if name in dataset_module.DIRECTIONAL_FEATURES
)
MODEL_FEATURE_NAMES = (
    FEATURE_NAMES
    + tuple(f"directional_{name}" for name in DIRECTIONAL_FEATURE_NAMES)
    + ("direction", "hour_sin", "hour_cos", "weekday_sin", "weekday_cos")
)
LONG_15M_HYPOTHESIS_SCORE_THRESHOLD = 0.5280400789051197
LONG_15M_HYPOTHESIS_H2_SCORE_THRESHOLD = 0.515
LONG_15M_HYPOTHESIS_H2_VOLUME_ZSCORE = 1.0
LONG_15M_HYPOTHESIS_VALIDATION = {
    "examples": 8640,
    "base_rate_pct": 39.236111111111114,
    "selected_examples": 87,
    "selected_observed_pct": 36.7816091954023,
    "calibrated_probability_at_threshold_pct": 41.54,
}
LONG_15M_HYPOTHESIS_H2_DIAGNOSTIC = {
    "dataset": "reused KuCoin 2026-01-02 through 2026-07-21",
    "trades": 35,
    "long_trades": 18,
    "short_trades": 17,
    "win_rate_pct": 60.0,
    "profit_factor": 1.9954299253630066,
    "compounded_net_return_pct": 15.933182411177516,
    "selection_note": (
        "Directions must alternate; same-direction reentries are ignored."
    ),
}


@dataclasses.dataclass(frozen=True)
class PercentageProbabilityConfig:
    time_frame: str
    activation_pct: float = 1.2
    initial_stop_pct: float = 1.0
    horizon_hours: int = 24
    round_trip_cost_pct: float = 0.16

    @property
    def candle_seconds(self) -> int:
        return dataset_module.TIME_FRAME_SECONDS[self.time_frame]

    @property
    def horizon_bars(self) -> int:
        return self.horizon_hours * 3600 // self.candle_seconds

    @property
    def break_even_probability(self) -> float:
        win = 1.0 - self.round_trip_cost_pct
        loss = self.initial_stop_pct + self.round_trip_cost_pct
        return loss / (win + loss)

    def validate(self) -> None:
        if self.time_frame not in {"5m", "15m", "1h"}:
            raise ValueError("time_frame must be 5m, 15m, or 1h")
        if self.horizon_hours < 1 or self.horizon_bars < 1:
            raise ValueError("horizon must contain at least one candle")
        if self.activation_pct <= 0 or self.initial_stop_pct <= 0:
            raise ValueError("activation and stop percentages must be positive")
        if not 0 <= self.round_trip_cost_pct < 1:
            raise ValueError("round-trip cost percentage is invalid")


@dataclasses.dataclass(frozen=True)
class ProbabilityExamples:
    features: numpy.ndarray
    labels: numpy.ndarray
    timestamps: numpy.ndarray
    directions: numpy.ndarray

    def take(self, mask: numpy.ndarray) -> "ProbabilityExamples":
        return ProbabilityExamples(
            features=self.features[mask],
            labels=self.labels[mask],
            timestamps=self.timestamps[mask],
            directions=self.directions[mask],
        )


@dataclasses.dataclass
class CalibratedPercentageModel:
    base_model: model_module.NumpyLogisticModel
    calibrator: "QuantileIsotonicCalibrator"
    config: PercentageProbabilityConfig

    def predict_proba(self, features: numpy.ndarray) -> numpy.ndarray:
        return self.calibrator.predict(self.base_model.predict_proba(features))

    def save(self, directory_value: typing.Union[str, pathlib.Path]) -> dict:
        directory = pathlib.Path(directory_value).resolve()
        directory.mkdir(parents=True, exist_ok=True)
        base = self.base_model.save(directory / "base_model.npz")
        calibrator_path = directory / "calibrator.json"
        self.calibrator.save(calibrator_path)
        calibrator = {
            "path": str(calibrator_path),
            "sha256": _sha256(calibrator_path),
            "bins": len(self.calibrator.values),
        }
        metadata_path = directory / "model.json"
        metadata_path.write_text(
            json.dumps(
                {
                    "schema_version": 1,
                    "research_only": True,
                    "orders_authorized": False,
                    "automatic_promotion": False,
                    "signal_uses_future_outcomes": False,
                    "evaluation_uses_future_outcomes": True,
                    "feature_names": list(MODEL_FEATURE_NAMES),
                    "config": dataclasses.asdict(self.config),
                    "base_model": base,
                    "calibrator": calibrator,
                },
                indent=2,
                sort_keys=True,
            )
            + "\n",
            encoding="utf-8",
        )
        return {
            "directory": str(directory),
            "metadata": str(metadata_path),
            "metadata_sha256": _sha256(metadata_path),
            "base_model": base,
            "calibrator": calibrator,
        }

    @classmethod
    def load(
        cls, directory_value: typing.Union[str, pathlib.Path]
    ) -> "CalibratedPercentageModel":
        directory = pathlib.Path(directory_value).resolve()
        metadata = json.loads((directory / "model.json").read_text(encoding="utf-8"))
        if tuple(metadata["feature_names"]) != MODEL_FEATURE_NAMES:
            raise ValueError("percentage probability feature schema differs")
        return cls(
            base_model=model_module.NumpyLogisticModel.load(
                directory / "base_model.npz"
            ),
            calibrator=QuantileIsotonicCalibrator.load(
                directory / "calibrator.json"
            ),
            config=PercentageProbabilityConfig(**metadata["config"]),
        )


@dataclasses.dataclass(frozen=True)
class QuantileIsotonicCalibrator:
    """Monotonic empirical calibration with bounded tail extrapolation."""

    upper_score: numpy.ndarray
    values: numpy.ndarray

    @classmethod
    def fit(
        cls,
        scores: numpy.ndarray,
        labels: numpy.ndarray,
        maximum_bins: int = 200,
        minimum_rows_per_bin: int = 200,
    ) -> "QuantileIsotonicCalibrator":
        if len(scores) != len(labels) or not len(labels):
            raise ValueError("calibration data is empty or misaligned")
        order = numpy.argsort(scores, kind="stable")
        ordered_scores = scores[order]
        ordered_labels = labels[order].astype(float)
        bin_count = min(maximum_bins, len(scores) // minimum_rows_per_bin)
        if bin_count < 2:
            raise ValueError("calibration requires at least two stable bins")
        boundaries = numpy.linspace(0, len(scores), bin_count + 1).astype(int)
        blocks = []
        for index in range(bin_count):
            start, end = boundaries[index], boundaries[index + 1]
            blocks.append(
                {
                    "weight": end - start,
                    "successes": float(numpy.sum(ordered_labels[start:end])),
                    "upper_score": float(ordered_scores[end - 1]),
                }
            )
        index = 0
        while index < len(blocks) - 1:
            left = blocks[index]["successes"] / blocks[index]["weight"]
            right = blocks[index + 1]["successes"] / blocks[index + 1]["weight"]
            if left <= right:
                index += 1
                continue
            blocks[index : index + 2] = [
                {
                    "weight": blocks[index]["weight"]
                    + blocks[index + 1]["weight"],
                    "successes": blocks[index]["successes"]
                    + blocks[index + 1]["successes"],
                    "upper_score": blocks[index + 1]["upper_score"],
                }
            ]
            index = max(0, index - 1)
        return cls(
            upper_score=numpy.asarray(
                [block["upper_score"] for block in blocks], dtype=float
            ),
            values=numpy.asarray(
                [
                    block["successes"] / block["weight"]
                    for block in blocks
                ],
                dtype=float,
            ),
        )

    def predict(self, scores: numpy.ndarray) -> numpy.ndarray:
        indices = numpy.searchsorted(self.upper_score, scores, side="left")
        indices = numpy.clip(indices, 0, len(self.values) - 1)
        return self.values[indices]

    def save(self, path_value: typing.Union[str, pathlib.Path]) -> None:
        pathlib.Path(path_value).write_text(
            json.dumps(
                {
                    "schema_version": 1,
                    "upper_score": self.upper_score.tolist(),
                    "values": self.values.tolist(),
                },
                indent=2,
                sort_keys=True,
            )
            + "\n",
            encoding="utf-8",
        )

    @classmethod
    def load(
        cls, path_value: typing.Union[str, pathlib.Path]
    ) -> "QuantileIsotonicCalibrator":
        payload = json.loads(pathlib.Path(path_value).read_text(encoding="utf-8"))
        if payload.get("schema_version") != 1:
            raise ValueError("unsupported isotonic calibration schema")
        return cls(
            upper_score=numpy.asarray(payload["upper_score"], dtype=float),
            values=numpy.asarray(payload["values"], dtype=float),
        )


def build_examples(
    candles: numpy.ndarray,
    config: PercentageProbabilityConfig,
) -> ProbabilityExamples:
    """Build LONG and SHORT examples without leaking future values into features."""

    config.validate()
    if candles.ndim != 2 or candles.shape[1] < 6:
        raise ValueError("candles must be an OHLCV matrix")
    candle_count = len(candles)
    if candle_count <= config.horizon_bars + 60:
        raise ValueError("not enough candles for indicators and outcome horizon")

    close_times = (
        candles[:, 0].astype(numpy.int64) + config.candle_seconds
    )
    long_labels, long_resolved = _first_touch_labels(
        candles[:, 2],
        candles[:, 3],
        candles[:, 4],
        config,
        direction=1,
    )
    short_labels, short_resolved = _first_touch_labels(
        candles[:, 2],
        candles[:, 3],
        candles[:, 4],
        config,
        direction=-1,
    )

    final_index = candle_count - config.horizon_bars
    base_indices = numpy.arange(final_index, dtype=numpy.int64)
    horizon_contiguous = (
        candles[
            base_indices + config.horizon_bars, 0
        ].astype(numpy.int64)
        - candles[base_indices, 0].astype(numpy.int64)
        == config.horizon_bars * config.candle_seconds
    )
    arrays = indicators.compute_feature_arrays(candles)
    raw = numpy.column_stack([arrays[name] for name in FEATURE_NAMES])
    finite = numpy.all(numpy.isfinite(raw[base_indices]), axis=1)
    valid = finite & horizon_contiguous
    base_indices = base_indices[valid]
    if not len(base_indices):
        raise ValueError("no complete point-in-time examples")

    timestamp_values = close_times[base_indices]
    long_features = _feature_block(raw[base_indices], timestamp_values, 1)
    short_features = _feature_block(raw[base_indices], timestamp_values, -1)
    features = numpy.concatenate((long_features, short_features))
    labels = numpy.concatenate(
        (long_labels[base_indices], short_labels[base_indices])
    ).astype(numpy.int8)
    # ``resolved`` is retained in label construction for explicit semantics:
    # unresolved horizon outcomes are valid negatives (activation not reached).
    _ = long_resolved, short_resolved
    timestamps = numpy.concatenate((timestamp_values, timestamp_values))
    directions = numpy.concatenate(
        (
            numpy.ones(len(base_indices), dtype=numpy.int8),
            -numpy.ones(len(base_indices), dtype=numpy.int8),
        )
    )
    return ProbabilityExamples(features, labels, timestamps, directions)


def _feature_block(
    raw_features: numpy.ndarray,
    timestamps: numpy.ndarray,
    direction: int,
) -> numpy.ndarray:
    directional_indices = [
        FEATURE_NAMES.index(name) for name in DIRECTIONAL_FEATURE_NAMES
    ]
    datetimes = [
        datetime.datetime.fromtimestamp(
            int(timestamp), tz=datetime.timezone.utc
        )
        for timestamp in timestamps
    ]
    hours = numpy.asarray(
        [value.hour + value.minute / 60 for value in datetimes], dtype=float
    )
    weekdays = numpy.asarray([value.weekday() for value in datetimes], dtype=float)
    cyclical = numpy.column_stack(
        (
            numpy.sin(2 * numpy.pi * hours / 24),
            numpy.cos(2 * numpy.pi * hours / 24),
            numpy.sin(2 * numpy.pi * weekdays / 7),
            numpy.cos(2 * numpy.pi * weekdays / 7),
        )
    )
    return numpy.column_stack(
        (
            raw_features,
            raw_features[:, directional_indices] * direction,
            numpy.full(len(raw_features), direction, dtype=float),
            cyclical,
        )
    ).astype(numpy.float32)


def _candle_close_display_times(
    timestamps: numpy.ndarray,
    candle_seconds: int,
) -> list[str]:
    return [
        datetime.datetime.fromtimestamp(
            int(timestamp) + candle_seconds,
            tz=datetime.timezone.utc,
        ).strftime("%y-%m-%d %H:%M:%S")
        for timestamp in timestamps
    ]


def analyze_chart_probabilities(
    *,
    times: typing.Iterable[typing.Any],
    display_times: typing.Iterable[typing.Any],
    opens: typing.Iterable[typing.Any],
    highs: typing.Iterable[typing.Any],
    lows: typing.Iterable[typing.Any],
    closes: typing.Iterable[typing.Any],
    volumes: typing.Iterable[typing.Any],
    time_frame: str,
    artifact_root: typing.Optional[typing.Union[str, pathlib.Path]] = None,
) -> dict:
    """Return causal probabilities for closed chart candles.

    Only the strongest 10% of chart scores are returned as diagnostic markers;
    the latest LONG/SHORT percentages and the complete validation evidence are
    returned in the annotation payload.  Markers are not trade entries.
    """

    config = PercentageProbabilityConfig(time_frame=time_frame)
    config.validate()
    columns = [
        list(times),
        list(opens),
        list(highs),
        list(lows),
        list(closes),
        list(volumes),
    ]
    display_values = list(display_times)
    lengths = {len(values) for values in columns} | {len(display_values)}
    if len(lengths) != 1 or not columns[0]:
        raise ValueError("chart candle arrays must be non-empty and aligned")
    candles = numpy.column_stack(
        [numpy.asarray(values, dtype=float) for values in columns]
    )
    close_display_values = _candle_close_display_times(
        candles[:, 0], config.candle_seconds
    )
    # OctoBot includes the currently forming candle as the last chart row.
    closed_count = len(candles) - 1
    if closed_count < 60:
        raise ValueError("at least 60 candles, plus the open candle, are required")
    arrays = indicators.compute_feature_arrays(candles[:closed_count])
    raw = numpy.column_stack([arrays[name] for name in FEATURE_NAMES])
    valid_indices = numpy.flatnonzero(numpy.all(numpy.isfinite(raw), axis=1))
    close_times = (
        candles[:closed_count, 0].astype(numpy.int64) + config.candle_seconds
    )
    long_features = _feature_block(raw[valid_indices], close_times[valid_indices], 1)
    short_features = _feature_block(
        raw[valid_indices], close_times[valid_indices], -1
    )
    root = pathlib.Path(
        artifact_root
        or os.environ.get(
            "PERCENTAGE_PROBABILITY_MODEL_ROOT",
            "/octobot/backtesting/research/percentage_probability_v1",
        )
    )
    model = CalibratedPercentageModel.load(root / time_frame)
    long_scores = model.base_model.predict_proba(long_features)
    short_scores = model.base_model.predict_proba(short_features)
    long_probabilities = model.calibrator.predict(long_scores)
    short_probabilities = model.calibrator.predict(short_scores)
    report = json.loads(
        (root / time_frame / "report.json").read_text(encoding="utf-8")
    )
    combined_scores = numpy.concatenate((long_scores, short_scores))
    combined_probabilities = numpy.concatenate(
        (long_probabilities, short_probabilities)
    )
    diagnostic_score_threshold = float(numpy.quantile(combined_scores, 0.90))

    def points(
        probabilities: numpy.ndarray,
        scores: numpy.ndarray,
        direction: str,
    ) -> list[dict]:
        selected = numpy.flatnonzero(scores >= diagnostic_score_threshold)
        if len(selected) > 20:
            selected = selected[numpy.argsort(scores[selected])[-20:]]
            selected = numpy.sort(selected)
        return [
            {
                "time": close_display_values[int(valid_indices[index])],
                "price": float(
                    candles[int(valid_indices[index]), 3 if direction == "LONG" else 2]
                ),
                "probability_pct": float(probabilities[index] * 100),
                "direction": direction,
                "trade_qualified": bool(
                    probabilities[index] * 100
                    >= report["display_threshold_pct"]
                ),
            }
            for index in selected
        ]

    return {
        "schema_version": 1,
        "mode": "causal_calibrated_percentage_probability_v1",
        "research_only": True,
        "orders_authorized": False,
        "automatic_promotion": False,
        "signal_uses_future_outcomes": False,
        "evaluation_uses_future_outcomes": True,
        "time_frame": time_frame,
        "prediction_target": report["prediction_target"],
        "latest": {
            "time": close_display_values[int(valid_indices[-1])],
            "long_probability_pct": float(long_probabilities[-1] * 100),
            "short_probability_pct": float(short_probabilities[-1] * 100),
        },
        "display_threshold_pct": report["display_threshold_pct"],
        "diagnostic_probability_floor_pct": float(
            numpy.min(
                combined_probabilities[
                    combined_scores >= diagnostic_score_threshold
                ]
            )
            * 100
        ),
        "points": points(long_probabilities, long_scores, "LONG")
        + points(short_probabilities, short_scores, "SHORT"),
        "test": {
            "examples": report["metrics"]["test"]["examples"],
            "base_rate_pct": report["metrics"]["test"]["base_rate_pct"],
            "brier_score": report["metrics"]["test"]["brier_score"],
            "expected_calibration_error": report["metrics"]["test"][
                "expected_calibration_error"
            ],
            "above_display_threshold": report[
                "test_above_display_threshold"
            ],
        },
        "warning": report["warning"],
    }


def _simulate_long_hypothesis(
    *,
    times: list[typing.Any],
    highs: list[float],
    lows: list[float],
    closes: list[float],
    candidate_indices: numpy.ndarray,
    raw_scores_by_index: dict[int, float],
    probabilities_by_index: dict[int, float],
    last_closed_index: int,
    config: PercentageProbabilityConfig,
) -> tuple[list[dict], int]:
    trade_config = percentage_engine.PercentageEngineConfig(
        minimum_profit_pct=1.0,
        activation_pct=config.activation_pct,
        initial_stop_pct=config.initial_stop_pct,
        horizon_candles=config.horizon_bars,
        directions=(percentage_engine.LONG,),
        exclude_last_candle=True,
    )
    trades = []
    ignored_while_open = 0
    next_available_index = 0
    for value in candidate_indices:
        entry_index = int(value)
        if entry_index < next_available_index or entry_index >= last_closed_index:
            ignored_while_open += entry_index < next_available_index
            continue
        trade = percentage_engine.simulate_trade(
            times,
            highs,
            lows,
            closes,
            entry_index,
            percentage_engine.LONG,
            last_closed_index,
            trade_config,
        )
        truncated_at_chart_end = (
            entry_index + config.horizon_bars > last_closed_index
            and trade["exit_index"] == last_closed_index
            and trade["exit_reason"] in {"horizon", "horizon_after_lock"}
        )
        trade["status"] = "open_at_chart_end" if truncated_at_chart_end else "closed"
        if truncated_at_chart_end:
            trade["exit_reason"] = "chart_end_open"
            trade["exit_time"] = None
            trade["exit_price"] = None
            trade["gross_return_pct"] = None
            trade["net_return_pct"] = None
        else:
            trade["net_return_pct"] = (
                trade["gross_return_pct"] - config.round_trip_cost_pct
            )
        trade["raw_score"] = raw_scores_by_index[entry_index]
        trade["probability_pct"] = probabilities_by_index[entry_index] * 100
        trades.append(trade)
        next_available_index = (
            last_closed_index + 1
            if truncated_at_chart_end
            else int(trade["exit_index"]) + 1
        )
    return trades, ignored_while_open


def _simulate_alternating_hypothesis(
    *,
    times: list[typing.Any],
    highs: list[float],
    lows: list[float],
    closes: list[float],
    candidates: list[dict],
    last_closed_index: int,
    config: PercentageProbabilityConfig,
) -> tuple[list[dict], int, int]:
    trade_config = percentage_engine.PercentageEngineConfig(
        minimum_profit_pct=1.0,
        activation_pct=config.activation_pct,
        initial_stop_pct=config.initial_stop_pct,
        horizon_candles=config.horizon_bars,
        directions=(percentage_engine.LONG, percentage_engine.SHORT),
        exclude_last_candle=True,
    )
    trades = []
    ignored_while_open = 0
    ignored_same_direction = 0
    next_available_index = 0
    previous_direction = None
    for candidate in sorted(
        candidates,
        key=lambda value: (
            value["entry_index"],
            -value["raw_score"],
            value["direction"],
        ),
    ):
        entry_index = int(candidate["entry_index"])
        direction = candidate["direction"]
        if entry_index < next_available_index:
            ignored_while_open += 1
            continue
        if entry_index >= last_closed_index:
            continue
        if direction == previous_direction:
            ignored_same_direction += 1
            continue
        trade = percentage_engine.simulate_trade(
            times,
            highs,
            lows,
            closes,
            entry_index,
            direction,
            last_closed_index,
            trade_config,
        )
        truncated_at_chart_end = (
            entry_index + config.horizon_bars > last_closed_index
            and trade["exit_index"] == last_closed_index
            and trade["exit_reason"] in {"horizon", "horizon_after_lock"}
        )
        trade["status"] = "open_at_chart_end" if truncated_at_chart_end else "closed"
        if truncated_at_chart_end:
            trade["exit_reason"] = "chart_end_open"
            trade["exit_time"] = None
            trade["exit_price"] = None
            trade["gross_return_pct"] = None
            trade["net_return_pct"] = None
        else:
            trade["net_return_pct"] = (
                trade["gross_return_pct"] - config.round_trip_cost_pct
            )
        trade["raw_score"] = candidate["raw_score"]
        trade["probability_pct"] = candidate["probability_pct"]
        trades.append(trade)
        previous_direction = direction
        next_available_index = (
            last_closed_index + 1
            if truncated_at_chart_end
            else int(trade["exit_index"]) + 1
        )
    return trades, ignored_while_open, ignored_same_direction


def _select_long_hypothesis_candidates(
    valid_indices: numpy.ndarray,
    scores: numpy.ndarray,
    volume_zscores: numpy.ndarray,
    *,
    score_threshold: float,
    minimum_volume_zscore: typing.Optional[float],
) -> numpy.ndarray:
    selected_mask = scores >= score_threshold
    if minimum_volume_zscore is not None:
        selected_mask &= (
            volume_zscores[valid_indices] >= minimum_volume_zscore
        )
    return valid_indices[selected_mask]


def _analyze_long_15m_hypothesis(
    *,
    times: typing.Iterable[typing.Any],
    display_times: typing.Iterable[typing.Any],
    opens: typing.Iterable[typing.Any],
    highs: typing.Iterable[typing.Any],
    lows: typing.Iterable[typing.Any],
    closes: typing.Iterable[typing.Any],
    volumes: typing.Iterable[typing.Any],
    hypothesis: str,
    score_threshold: float,
    minimum_volume_zscore: typing.Optional[float],
    alternating_directions: bool,
    evidence: dict,
    warning: str,
    artifact_root: typing.Optional[typing.Union[str, pathlib.Path]] = None,
) -> dict:
    """Visualize a frozen point-in-time hypothesis on closed 15m candles."""

    config = PercentageProbabilityConfig(time_frame="15m")
    columns = [
        list(times),
        list(opens),
        list(highs),
        list(lows),
        list(closes),
        list(volumes),
    ]
    display_values = list(display_times)
    lengths = {len(values) for values in columns} | {len(display_values)}
    if len(lengths) != 1 or not columns[0]:
        raise ValueError("chart candle arrays must be non-empty and aligned")
    candles = numpy.column_stack(
        [numpy.asarray(values, dtype=float) for values in columns]
    )
    close_display_values = _candle_close_display_times(
        candles[:, 0], config.candle_seconds
    )
    closed_count = len(candles) - 1
    if closed_count < 60:
        raise ValueError("at least 60 candles, plus the open candle, are required")
    arrays = indicators.compute_feature_arrays(candles[:closed_count])
    raw = numpy.column_stack([arrays[name] for name in FEATURE_NAMES])
    valid_indices = numpy.flatnonzero(numpy.all(numpy.isfinite(raw), axis=1))
    close_times = (
        candles[:closed_count, 0].astype(numpy.int64) + config.candle_seconds
    )
    root = pathlib.Path(
        artifact_root
        or os.environ.get(
            "PERCENTAGE_PROBABILITY_MODEL_ROOT",
            "/octobot/backtesting/research/percentage_probability_v1",
        )
    )
    model = CalibratedPercentageModel.load(root / "15m")
    directions = (
        ((percentage_engine.LONG, 1), (percentage_engine.SHORT, -1))
        if alternating_directions
        else ((percentage_engine.LONG, 1),)
    )
    candidate_events = []
    selected_by_direction = {}
    scores_by_direction = {}
    probabilities_by_direction = {}
    for direction, sign in directions:
        features = _feature_block(
            raw[valid_indices],
            close_times[valid_indices],
            sign,
        )
        scores = model.base_model.predict_proba(features)
        probabilities = model.calibrator.predict(scores)
        selected = _select_long_hypothesis_candidates(
            valid_indices,
            scores,
            arrays["volume_zscore"],
            score_threshold=score_threshold,
            minimum_volume_zscore=minimum_volume_zscore,
        )
        selected_by_direction[direction] = selected
        scores_by_direction[direction] = {
            int(index): float(score)
            for index, score in zip(valid_indices, scores)
        }
        probabilities_by_direction[direction] = {
            int(index): float(probability)
            for index, probability in zip(valid_indices, probabilities)
        }
        candidate_events.extend(
            {
                "entry_index": int(index),
                "direction": direction,
                "raw_score": scores_by_direction[direction][int(index)],
                "probability_pct": (
                    probabilities_by_direction[direction][int(index)] * 100
                ),
            }
            for index in selected
        )
    if alternating_directions:
        trades, ignored, ignored_same_direction = (
            _simulate_alternating_hypothesis(
                times=close_display_values,
                highs=candles[:, 2].tolist(),
                lows=candles[:, 3].tolist(),
                closes=candles[:, 4].tolist(),
                candidates=candidate_events,
                last_closed_index=closed_count - 1,
                config=config,
            )
        )
    else:
        selected = selected_by_direction[percentage_engine.LONG]
        trades, ignored = _simulate_long_hypothesis(
            times=close_display_values,
            highs=candles[:, 2].tolist(),
            lows=candles[:, 3].tolist(),
            closes=candles[:, 4].tolist(),
            candidate_indices=selected,
            raw_scores_by_index=scores_by_direction[percentage_engine.LONG],
            probabilities_by_index=probabilities_by_direction[
                percentage_engine.LONG
            ],
            last_closed_index=closed_count - 1,
            config=config,
        )
        ignored_same_direction = 0
    for trade in trades:
        trade["entry_volume_zscore"] = float(
            arrays["volume_zscore"][trade["entry_index"]]
        )
    closed = [trade for trade in trades if trade["status"] == "closed"]
    net_returns = [float(trade["net_return_pct"]) for trade in closed]
    gains = sum(value for value in net_returns if value > 0)
    losses = -sum(value for value in net_returns if value < 0)
    compound = math.prod(1 + value / 100 for value in net_returns) - 1
    return {
        "schema_version": 1,
        "mode": (
            f"diagnostic_bidirectional_15m_hypothesis_{hypothesis.lower()}"
            if alternating_directions
            else f"diagnostic_long_15m_hypothesis_{hypothesis.lower()}"
        ),
        "hypothesis": hypothesis,
        "research_only": True,
        "diagnostic_reuse": True,
        "orders_authorized": False,
        "automatic_promotion": False,
        "signal_uses_future_outcomes": False,
        "evaluation_uses_future_outcomes": True,
        "short_enabled": alternating_directions,
        "alternating_directions": alternating_directions,
        "time_frame": "15m",
        "score_threshold": score_threshold,
        "minimum_volume_zscore": minimum_volume_zscore,
        "event_timestamp_semantics": "candle_close_when_condition_is_known",
        "config": {
            "entry": (
                "close of a LONG or SHORT score-threshold candle with volume "
                "z-score confirmation; direction must alternate"
                if alternating_directions
                else "close of a LONG score-threshold candle"
            ),
            "minimum_profit_pct": 1.0,
            "activation_pct": config.activation_pct,
            "initial_stop_pct": config.initial_stop_pct,
            "protected_stop_pct": 1.0,
            "horizon_hours": config.horizon_hours,
            "horizon_bars": config.horizon_bars,
            "round_trip_cost_pct": config.round_trip_cost_pct,
            "funding_included": False,
        },
        "diagnostic_evidence": evidence,
        "summary": {
            "candidate_signals": len(candidate_events),
            "ignored_while_trade_open": int(ignored),
            "ignored_same_direction_reentries": int(ignored_same_direction),
            "closed_trades": len(closed),
            "open_trades": len(trades) - len(closed),
            "wins": sum(value > 0 for value in net_returns),
            "long_trades": sum(
                trade["direction"] == percentage_engine.LONG for trade in closed
            ),
            "short_trades": sum(
                trade["direction"] == percentage_engine.SHORT for trade in closed
            ),
            "win_rate_pct": (
                sum(value > 0 for value in net_returns) * 100 / len(closed)
                if closed
                else 0.0
            ),
            "profit_factor": gains / losses if losses else None,
            "compounded_net_return_pct": compound * 100,
        },
        "trades": trades,
        "warning": warning,
    }


def analyze_long_15m_hypothesis(
    **kwargs: typing.Any,
) -> dict:
    return _analyze_long_15m_hypothesis(
        **kwargs,
        hypothesis="H1",
        score_threshold=LONG_15M_HYPOTHESIS_SCORE_THRESHOLD,
        minimum_volume_zscore=None,
        alternating_directions=False,
        evidence=LONG_15M_HYPOTHESIS_VALIDATION,
        warning=(
            "H1 is a visual diagnostic on reused validation evidence, not an "
            "approved strategy. Its selected validation rate was below the "
            "validation base rate; the visible chart can be coincidentally good."
        ),
    )


def analyze_long_15m_hypothesis_h2(
    **kwargs: typing.Any,
) -> dict:
    return _analyze_long_15m_hypothesis(
        **kwargs,
        hypothesis="H2",
        score_threshold=LONG_15M_HYPOTHESIS_H2_SCORE_THRESHOLD,
        minimum_volume_zscore=LONG_15M_HYPOTHESIS_H2_VOLUME_ZSCORE,
        alternating_directions=True,
        evidence=LONG_15M_HYPOTHESIS_H2_DIAGNOSTIC,
        warning=(
            "H2 was selected after inspecting reused KuCoin outcomes. Its "
            "apparent improvement is in-sample diagnostic evidence and requires "
            "new forward or purged walk-forward validation."
        ),
    )


def _first_touch_labels(
    highs: numpy.ndarray,
    lows: numpy.ndarray,
    closes: numpy.ndarray,
    config: PercentageProbabilityConfig,
    *,
    direction: int,
) -> tuple[numpy.ndarray, numpy.ndarray]:
    count = len(closes)
    labels = numpy.zeros(count, dtype=numpy.int8)
    resolved = numpy.zeros(count, dtype=bool)
    stop_ratio = 1.0 - direction * config.initial_stop_pct / 100
    target_ratio = 1.0 + direction * config.activation_pct / 100
    stop_levels = closes * stop_ratio
    target_levels = closes * target_ratio
    for offset in range(1, config.horizon_bars + 1):
        limit = count - offset
        if limit <= 0:
            break
        open_mask = ~resolved[:limit]
        if direction == 1:
            stop_touch = lows[offset:] <= stop_levels[:limit]
            target_touch = highs[offset:] >= target_levels[:limit]
        else:
            stop_touch = highs[offset:] >= stop_levels[:limit]
            target_touch = lows[offset:] <= target_levels[:limit]
        # Conservative OHLC ordering: a same-candle stop defeats the target.
        wins = open_mask & target_touch & ~stop_touch
        losses = open_mask & stop_touch
        labels[:limit][wins] = 1
        resolved[:limit][wins | losses] = True
    return labels, resolved


def fit_calibrated_model(
    training: ProbabilityExamples,
    calibration: ProbabilityExamples,
    config: PercentageProbabilityConfig,
) -> CalibratedPercentageModel:
    base = model_module.NumpyLogisticModel.fit(
        training.features,
        training.labels,
        MODEL_FEATURE_NAMES,
        model_module.LogisticConfig(
            epochs=10,
            batch_size=8192,
            learning_rate=0.008,
            l2=0.002,
            seed=42,
        ),
    )
    base_probabilities = numpy.clip(
        base.predict_proba(calibration.features), 1e-6, 1 - 1e-6
    )
    calibrator = QuantileIsotonicCalibrator.fit(
        base_probabilities,
        calibration.labels,
    )
    return CalibratedPercentageModel(base, calibrator, config)


def refit_calibrator(
    fitted: CalibratedPercentageModel,
    examples: ProbabilityExamples,
) -> CalibratedPercentageModel:
    base_probabilities = numpy.clip(
        fitted.base_model.predict_proba(examples.features), 1e-6, 1 - 1e-6
    )
    return CalibratedPercentageModel(
        fitted.base_model,
        QuantileIsotonicCalibrator.fit(
            base_probabilities,
            examples.labels,
        ),
        fitted.config,
    )


def _concatenate_examples(
    left: ProbabilityExamples,
    right: ProbabilityExamples,
) -> ProbabilityExamples:
    return ProbabilityExamples(
        features=numpy.concatenate((left.features, right.features)),
        labels=numpy.concatenate((left.labels, right.labels)),
        timestamps=numpy.concatenate((left.timestamps, right.timestamps)),
        directions=numpy.concatenate((left.directions, right.directions)),
    )


def evaluate(
    examples: ProbabilityExamples,
    probabilities: numpy.ndarray,
) -> dict:
    probabilities = numpy.clip(probabilities, 1e-9, 1 - 1e-9)
    labels = examples.labels.astype(float)
    return {
        "examples": int(len(labels)),
        "base_rate_pct": float(numpy.mean(labels) * 100),
        "mean_probability_pct": float(numpy.mean(probabilities) * 100),
        "brier_score": float(numpy.mean((probabilities - labels) ** 2)),
        "log_loss": float(
            -numpy.mean(
                labels * numpy.log(probabilities)
                + (1.0 - labels) * numpy.log(1.0 - probabilities)
            )
        ),
        "expected_calibration_error": model_module.expected_calibration_error(
            examples.labels, probabilities
        ),
        "reliability": _reliability(examples.labels, probabilities),
        "by_direction": {
            name: _small_probability_summary(
                examples.labels[examples.directions == sign],
                probabilities[examples.directions == sign],
            )
            for name, sign in (("long", 1), ("short", -1))
        },
    }


def _small_probability_summary(
    labels: numpy.ndarray, probabilities: numpy.ndarray
) -> dict:
    return {
        "examples": int(len(labels)),
        "observed_pct": float(numpy.mean(labels) * 100),
        "mean_probability_pct": float(numpy.mean(probabilities) * 100),
        "brier_score": float(numpy.mean((probabilities - labels) ** 2)),
    }


def _reliability(labels: numpy.ndarray, probabilities: numpy.ndarray) -> list[dict]:
    result = []
    for lower in numpy.linspace(0.0, 0.9, 10):
        upper = lower + 0.1
        mask = (probabilities >= lower) & (
            probabilities <= upper if upper >= 1 else probabilities < upper
        )
        if not numpy.any(mask):
            continue
        successes = int(numpy.sum(labels[mask]))
        count = int(numpy.sum(mask))
        low, high = _wilson_interval(successes, count)
        result.append(
            {
                "from_pct": round(lower * 100, 6),
                "to_pct": round(upper * 100, 6),
                "examples": count,
                "mean_probability_pct": float(numpy.mean(probabilities[mask]) * 100),
                "observed_pct": successes * 100 / count,
                "observed_95pct_ci": [low * 100, high * 100],
            }
        )
    return result


def _wilson_interval(successes: int, count: int) -> tuple[float, float]:
    if count == 0:
        return 0.0, 1.0
    z = 1.959963984540054
    proportion = successes / count
    denominator = 1 + z * z / count
    centre = (proportion + z * z / (2 * count)) / denominator
    margin = (
        z
        * math.sqrt(
            proportion * (1 - proportion) / count + z * z / (4 * count * count)
        )
        / denominator
    )
    return max(0.0, centre - margin), min(1.0, centre + margin)


def _date_timestamp(value: str) -> int:
    return int(
        datetime.datetime.fromisoformat(value)
        .replace(tzinfo=datetime.timezone.utc)
        .timestamp()
    )


def _period(
    examples: ProbabilityExamples,
    start: str,
    end_exclusive: str,
    *,
    horizon_seconds: int,
) -> ProbabilityExamples:
    start_timestamp = _date_timestamp(start)
    end_timestamp = _date_timestamp(end_exclusive)
    return examples.take(
        (examples.timestamps >= start_timestamp)
        & (examples.timestamps + horizon_seconds < end_timestamp)
    )


def run_study(
    *,
    time_frame: str,
    binance_collector: typing.Union[str, pathlib.Path],
    kucoin_collector: typing.Union[str, pathlib.Path],
    output_directory: typing.Union[str, pathlib.Path],
) -> dict:
    config = PercentageProbabilityConfig(time_frame=time_frame)
    config.validate()
    binance_path = pathlib.Path(binance_collector).resolve()
    kucoin_path = pathlib.Path(kucoin_collector).resolve()
    binance = _load_single_series(binance_path, time_frame)
    kucoin = _load_single_series(kucoin_path, time_frame)
    binance_examples = build_examples(binance, config)
    kucoin_examples = build_examples(kucoin, config)
    horizon_seconds = config.horizon_hours * 3600

    training = _period(
        binance_examples,
        "2022-05-01",
        "2025-06-30",
        horizon_seconds=horizon_seconds,
    )
    calibration = _period(
        binance_examples,
        "2025-07-01",
        "2025-10-01",
        horizon_seconds=horizon_seconds,
    )
    validation = _period(
        binance_examples,
        "2025-10-02",
        "2026-01-01",
        horizon_seconds=horizon_seconds,
    )
    test = _period(
        kucoin_examples,
        "2026-01-02",
        "2026-07-22",
        horizon_seconds=horizon_seconds,
    )
    if min(
        len(training.labels),
        len(calibration.labels),
        len(validation.labels),
        len(test.labels),
    ) == 0:
        raise ValueError("one or more chronological study blocks are empty")

    preliminary = fit_calibrated_model(training, calibration, config)
    block_examples = {
        "training": training,
        "calibration": calibration,
        "validation": validation,
    }
    metrics = {
        name: evaluate(values, preliminary.predict_proba(values.features))
        for name, values in block_examples.items()
    }
    validation_probabilities = preliminary.predict_proba(validation.features)
    display_threshold = max(
        config.break_even_probability,
        float(numpy.quantile(validation_probabilities, 0.95)),
    )
    # Once the architecture and display threshold are frozen, the later
    # Binance validation block can join calibration.  KuCoin stays untouched.
    fitted = refit_calibrator(
        preliminary,
        _concatenate_examples(calibration, validation),
    )
    test_probabilities = fitted.predict_proba(test.features)
    metrics["test"] = evaluate(test, test_probabilities)
    threshold_mask = test_probabilities >= display_threshold
    report = {
        "schema_version": 1,
        "created_at": datetime.datetime.now(datetime.timezone.utc).isoformat(),
        "research_only": True,
        "orders_authorized": False,
        "automatic_promotion": False,
        "signal_uses_future_outcomes": False,
        "evaluation_uses_future_outcomes": True,
        "prediction_target": (
            f"P(+{config.activation_pct:.1f}% before "
            f"-{config.initial_stop_pct:.1f}% within {config.horizon_hours}h)"
        ),
        "config": {
            **dataclasses.asdict(config),
            "horizon_bars": config.horizon_bars,
            "break_even_probability_pct": config.break_even_probability * 100,
            "funding_included": False,
            "cost_description": (
                "0.06% taker fee + 0.02% slippage per fill, two fills"
            ),
        },
        "splits": {
            "training": ["2022-05-01", "2025-06-30"],
            "calibration": ["2025-07-01", "2025-10-01"],
            "validation": ["2025-10-02", "2026-01-01"],
            "test": ["2026-01-02", "2026-07-22"],
            "embargo_hours": 24,
            "final_calibration": (
                "After validation and threshold freeze, calibration and "
                "validation were combined to fit the final monotonic mapper. "
                "KuCoin test remained untouched."
            ),
        },
        "inputs": {
            "binance": {
                "path": str(binance_path),
                "sha256": _sha256(binance_path),
            },
            "kucoin": {
                "path": str(kucoin_path),
                "sha256": _sha256(kucoin_path),
            },
        },
        "metrics": metrics,
        "display_threshold_pct": display_threshold * 100,
        "test_above_display_threshold": (
            {
                "examples": int(numpy.sum(threshold_mask)),
                "observed_pct": float(
                    numpy.mean(test.labels[threshold_mask]) * 100
                ),
                "mean_probability_pct": float(
                    numpy.mean(test_probabilities[threshold_mask]) * 100
                ),
            }
            if numpy.any(threshold_mask)
            else {"examples": 0, "observed_pct": None, "mean_probability_pct": None}
        ),
        "standardized_indicator_relationships": _relationships(fitted.base_model),
        "warning": (
            "Percentages are calibrated historical estimates, not certainties. "
            "The held-out KuCoin block was not used for fitting, calibration, "
            "or threshold selection."
        ),
    }
    output = pathlib.Path(output_directory).resolve() / time_frame
    artifact = fitted.save(output)
    report_path = output / "report.json"
    report["artifact"] = artifact
    report_path.write_text(
        json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    report["report_path"] = str(report_path)
    report["report_sha256"] = _sha256(report_path)
    return report


def _relationships(model: model_module.NumpyLogisticModel) -> list[dict]:
    values = [
        {"feature": name, "standardized_weight": float(weight)}
        for name, weight in zip(model.feature_names, model.weights)
    ]
    return sorted(values, key=lambda item: abs(item["standardized_weight"]), reverse=True)


def _load_single_series(path: pathlib.Path, time_frame: str) -> numpy.ndarray:
    series = dataset_module.load_collector_series(
        [path], required_time_frames=(time_frame,)
    )
    matching = [
        frames[time_frame].values
        for symbol, frames in series.items()
        if symbol.startswith("BTC/")
    ]
    if len(matching) != 1:
        raise ValueError(f"expected exactly one BTC {time_frame} series in {path}")
    return matching[0]


def _sha256(path: pathlib.Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def main(argv: typing.Optional[list[str]] = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--time-frame", required=True, choices=("5m", "15m", "1h"))
    parser.add_argument("--binance-collector", required=True)
    parser.add_argument("--kucoin-collector", required=True)
    parser.add_argument("--output-directory", required=True)
    args = parser.parse_args(argv)
    report = run_study(
        time_frame=args.time_frame,
        binance_collector=args.binance_collector,
        kucoin_collector=args.kucoin_collector,
        output_directory=args.output_directory,
    )
    print(
        json.dumps(
            {
                "time_frame": args.time_frame,
                "report_path": report["report_path"],
                "report_sha256": report["report_sha256"],
                "validation": report["metrics"]["validation"],
                "test": report["metrics"]["test"],
                "display_threshold_pct": report["display_threshold_pct"],
                "test_above_display_threshold": report[
                    "test_above_display_threshold"
                ],
            },
            indent=2,
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
