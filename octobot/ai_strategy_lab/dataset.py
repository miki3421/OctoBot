"""Build leakage-resistant, triple-barrier datasets from OctoBot collectors."""

from __future__ import annotations

import dataclasses
import datetime
import hashlib
import json
import pathlib
import sqlite3
import typing

import numpy

from octobot.ai_strategy_lab import indicators


SCHEMA_VERSION = 1
TIME_FRAME_SECONDS = {"15m": 900, "1h": 3600, "4h": 14400}
REQUIRED_TIME_FRAMES = tuple(TIME_FRAME_SECONDS)
OUTCOME_STOP = -1
OUTCOME_TIMEOUT = 0
OUTCOME_TARGET = 1
DIRECTIONAL_FEATURES = {
    "return_1",
    "return_4",
    "ema_spread_pct",
    "ema_slope_pct",
    "bb_position",
    "rsi_centered",
    "macd_hist_pct",
}


@dataclasses.dataclass(frozen=True)
class BarrierConfig:
    atr_multiplier: float = 1.5
    reward_risk_ratio: float = 2.0
    minimum_stop_pct: float = 0.005
    maximum_stop_pct: float = 0.02
    horizon_bars: int = 16
    fee_rate_per_fill: float = 0.0006
    slippage_rate_per_fill: float = 0.0002
    funding_rate_per_8h: float = 0.0

    def validate(self) -> None:
        if self.atr_multiplier <= 0:
            raise ValueError("atr_multiplier must be positive")
        if self.reward_risk_ratio <= 0:
            raise ValueError("reward_risk_ratio must be positive")
        if not 0 < self.minimum_stop_pct <= self.maximum_stop_pct:
            raise ValueError("stop percentage bounds are invalid")
        if self.horizon_bars < 1:
            raise ValueError("horizon_bars must be at least one")
        for name in (
            "fee_rate_per_fill",
            "slippage_rate_per_fill",
            "funding_rate_per_8h",
        ):
            if getattr(self, name) < 0:
                raise ValueError(f"{name} cannot be negative")


@dataclasses.dataclass(frozen=True)
class DatasetBuildConfig:
    barriers: BarrierConfig = dataclasses.field(default_factory=BarrierConfig)
    candidate_stride: int = 1

    def validate(self) -> None:
        self.barriers.validate()
        if self.candidate_stride < 1:
            raise ValueError("candidate_stride must be at least one")


@dataclasses.dataclass(frozen=True)
class CandleSeries:
    symbol: str
    time_frame: str
    values: numpy.ndarray

    @property
    def open_times(self) -> numpy.ndarray:
        return self.values[:, 0].astype(numpy.int64)

    @property
    def close_times(self) -> numpy.ndarray:
        return self.open_times + TIME_FRAME_SECONDS[self.time_frame]


@dataclasses.dataclass(frozen=True)
class ResearchDataset:
    features: numpy.ndarray
    feature_names: tuple[str, ...]
    label: numpy.ndarray
    outcome: numpy.ndarray
    profitable: numpy.ndarray
    net_return: numpy.ndarray
    gross_return: numpy.ndarray
    timestamp: numpy.ndarray
    exit_timestamp: numpy.ndarray
    event_end_timestamp: numpy.ndarray
    symbol: numpy.ndarray
    direction: numpy.ndarray
    entry_price: numpy.ndarray
    stop_price: numpy.ndarray
    target_price: numpy.ndarray
    duration_bars: numpy.ndarray
    mfe_return: numpy.ndarray
    mae_return: numpy.ndarray

    def validate(self) -> None:
        row_count = len(self.label)
        for field in dataclasses.fields(self):
            if field.name == "feature_names":
                continue
            values = getattr(self, field.name)
            name = field.name
            if len(values) != row_count:
                raise ValueError(f"{name} has {len(values)} rows, expected {row_count}")
        if self.features.ndim != 2:
            raise ValueError("features must be a two-dimensional array")
        if self.features.shape[1] != len(self.feature_names):
            raise ValueError("feature_names does not match the feature matrix")
        if not numpy.all(numpy.isfinite(self.features)):
            raise ValueError("features contain non-finite values")
        if not numpy.all(numpy.isfinite(self.net_return)):
            raise ValueError("net_return contains non-finite values")
        if numpy.any(self.exit_timestamp <= self.timestamp):
            raise ValueError("every label must exit after its decision timestamp")
        if numpy.any(self.event_end_timestamp < self.exit_timestamp):
            raise ValueError("event_end_timestamp cannot precede exit_timestamp")
        if set(numpy.unique(self.direction)) - {-1, 1}:
            raise ValueError("direction must contain only -1 or 1")
        if set(numpy.unique(self.outcome)) - {
            OUTCOME_STOP,
            OUTCOME_TIMEOUT,
            OUTCOME_TARGET,
        }:
            raise ValueError("unknown triple-barrier outcome")


def build_dataset(
    collector_paths: typing.Iterable[typing.Union[str, pathlib.Path]],
    config: DatasetBuildConfig = DatasetBuildConfig(),
    funding_rates: typing.Optional[
        dict[str, tuple[numpy.ndarray, numpy.ndarray]]
    ] = None,
) -> ResearchDataset:
    """Build long and short candidates at each eligible 15m candle close."""

    config.validate()
    paths = [pathlib.Path(path).resolve() for path in collector_paths]
    if not paths:
        raise ValueError("at least one collector path is required")
    series_by_symbol = load_collector_series(paths)
    blocks = [
        _build_symbol_dataset(
            symbol,
            time_frames,
            config,
            None if funding_rates is None else funding_rates.get(symbol),
        )
        for symbol, time_frames in sorted(series_by_symbol.items())
    ]
    blocks = [block for block in blocks if len(block.label)]
    if not blocks:
        raise ValueError("collector files contain no eligible point-in-time candidates")
    dataset = _concatenate_datasets(blocks)
    order = numpy.lexsort((dataset.direction, dataset.symbol, dataset.timestamp))
    dataset = _take_dataset(dataset, order)
    dataset.validate()
    return dataset


def load_collector_series(
    collector_paths: typing.Iterable[pathlib.Path],
) -> dict[str, dict[str, CandleSeries]]:
    merged: dict[tuple[str, str], dict[int, tuple[float, ...]]] = {}
    for path in collector_paths:
        if not path.is_file():
            raise FileNotFoundError(path)
        connection = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
        try:
            integrity = connection.execute("PRAGMA integrity_check").fetchone()
            if not integrity or integrity[0] != "ok":
                raise ValueError(f"collector failed SQLite integrity check: {path}")
            tables = {
                row[0]
                for row in connection.execute(
                    "SELECT name FROM sqlite_master WHERE type='table'"
                )
            }
            if "ohlcv" not in tables:
                raise ValueError(f"collector has no ohlcv table: {path}")
            for symbol, time_frame, raw_candle in connection.execute(
                """
                SELECT symbol, time_frame, candle
                FROM ohlcv
                WHERE time_frame IN ('15m', '1h', '4h')
                ORDER BY symbol, time_frame, timestamp
                """
            ):
                candle = json.loads(raw_candle)
                if len(candle) < 6:
                    raise ValueError(f"invalid OHLCV row in {path}")
                values = tuple(float(value) for value in candle[:6])
                merged.setdefault((symbol, time_frame), {})[int(values[0])] = values
        finally:
            connection.close()

    result: dict[str, dict[str, CandleSeries]] = {}
    for (symbol, time_frame), candles_by_time in merged.items():
        values = numpy.asarray(
            [candles_by_time[key] for key in sorted(candles_by_time)],
            dtype=float,
        )
        _validate_candles(symbol, time_frame, values)
        result.setdefault(symbol, {})[time_frame] = CandleSeries(
            symbol, time_frame, values
        )

    incomplete = {
        symbol: sorted(set(REQUIRED_TIME_FRAMES) - set(time_frames))
        for symbol, time_frames in result.items()
        if set(time_frames) != set(REQUIRED_TIME_FRAMES)
    }
    if incomplete:
        formatted = ", ".join(
            f"{symbol}:missing={missing}" for symbol, missing in incomplete.items()
        )
        raise ValueError(f"incomplete multi-timeframe coverage: {formatted}")
    return result


def save_dataset(
    dataset: ResearchDataset,
    output_path: typing.Union[str, pathlib.Path],
    *,
    collector_paths: typing.Iterable[typing.Union[str, pathlib.Path]],
    config: DatasetBuildConfig,
    funding_path: typing.Optional[typing.Union[str, pathlib.Path]] = None,
) -> dict:
    dataset.validate()
    output = pathlib.Path(output_path).resolve()
    output.parent.mkdir(parents=True, exist_ok=True)
    numpy.savez_compressed(
        output,
        features=dataset.features,
        feature_names=numpy.asarray(dataset.feature_names),
        label=dataset.label,
        outcome=dataset.outcome,
        profitable=dataset.profitable,
        net_return=dataset.net_return,
        gross_return=dataset.gross_return,
        timestamp=dataset.timestamp,
        exit_timestamp=dataset.exit_timestamp,
        event_end_timestamp=dataset.event_end_timestamp,
        symbol=dataset.symbol,
        direction=dataset.direction,
        entry_price=dataset.entry_price,
        stop_price=dataset.stop_price,
        target_price=dataset.target_price,
        duration_bars=dataset.duration_bars,
        mfe_return=dataset.mfe_return,
        mae_return=dataset.mae_return,
    )
    inputs = []
    for path_value in collector_paths:
        path = pathlib.Path(path_value).resolve()
        inputs.append(
            {
                "path": str(path),
                "sha256": _sha256(path),
                "bytes": path.stat().st_size,
            }
        )
    manifest = {
        "schema_version": SCHEMA_VERSION,
        "created_at": datetime.datetime.now(datetime.timezone.utc).isoformat(),
        "dataset_path": str(output),
        "dataset_sha256": _sha256(output),
        "inputs": inputs,
        "config": dataclasses.asdict(config),
        "rows": len(dataset.label),
        "features": list(dataset.feature_names),
        "symbols": sorted(str(value) for value in numpy.unique(dataset.symbol)),
        "start_timestamp": int(numpy.min(dataset.timestamp)),
        "end_timestamp": int(numpy.max(dataset.timestamp)),
        "outcomes": {
            "target": int(numpy.sum(dataset.outcome == OUTCOME_TARGET)),
            "stop": int(numpy.sum(dataset.outcome == OUTCOME_STOP)),
            "timeout": int(numpy.sum(dataset.outcome == OUTCOME_TIMEOUT)),
            "profitable": int(numpy.sum(dataset.profitable)),
        },
    }
    if funding_path is not None:
        resolved_funding_path = pathlib.Path(funding_path).resolve()
        manifest["funding"] = {
            "path": str(resolved_funding_path),
            "sha256": _sha256(resolved_funding_path),
            "bytes": resolved_funding_path.stat().st_size,
        }
    manifest_path = output.with_suffix(output.suffix + ".manifest.json")
    manifest_path.write_text(
        json.dumps(manifest, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return manifest


def load_dataset(path_value: typing.Union[str, pathlib.Path]) -> ResearchDataset:
    path = pathlib.Path(path_value).resolve()
    with numpy.load(path, allow_pickle=False) as values:
        dataset = ResearchDataset(
            features=values["features"],
            feature_names=tuple(str(value) for value in values["feature_names"]),
            label=values["label"],
            outcome=values["outcome"],
            profitable=values["profitable"],
            net_return=values["net_return"],
            gross_return=values["gross_return"],
            timestamp=values["timestamp"],
            exit_timestamp=values["exit_timestamp"],
            event_end_timestamp=values["event_end_timestamp"],
            symbol=values["symbol"],
            direction=values["direction"],
            entry_price=values["entry_price"],
            stop_price=values["stop_price"],
            target_price=values["target_price"],
            duration_bars=values["duration_bars"],
            mfe_return=values["mfe_return"],
            mae_return=values["mae_return"],
        )
    dataset.validate()
    return dataset


def _build_symbol_dataset(
    symbol: str,
    time_frames: dict[str, CandleSeries],
    config: DatasetBuildConfig,
    funding_series: typing.Optional[tuple[numpy.ndarray, numpy.ndarray]],
) -> ResearchDataset:
    base = time_frames["15m"]
    features_by_time_frame = {
        time_frame: indicators.compute_feature_arrays(series.values)
        for time_frame, series in time_frames.items()
    }
    feature_names = tuple(
        f"{time_frame}_{name}"
        for time_frame in REQUIRED_TIME_FRAMES
        for name in features_by_time_frame[time_frame]
    )
    directional_feature_names = tuple(
        f"directional_{name}"
        for name in feature_names
        if name.split("_", 1)[1] in DIRECTIONAL_FEATURES
    )
    all_feature_names = feature_names + directional_feature_names + (
        "direction",
        "hour_sin",
        "hour_cos",
        "weekday_sin",
        "weekday_cos",
    )
    directional_indices = [
        index
        for index, name in enumerate(feature_names)
        if f"directional_{name}" in directional_feature_names
    ]

    rows: list[numpy.ndarray] = []
    labels: list[int] = []
    outcomes: list[int] = []
    profitable: list[int] = []
    net_returns: list[float] = []
    gross_returns: list[float] = []
    timestamps: list[int] = []
    exit_timestamps: list[int] = []
    event_end_timestamps: list[int] = []
    symbols: list[str] = []
    directions: list[int] = []
    entry_prices: list[float] = []
    stop_prices: list[float] = []
    target_prices: list[float] = []
    durations: list[int] = []
    mfe_returns: list[float] = []
    mae_returns: list[float] = []

    aligned_indices = {
        time_frame: numpy.searchsorted(
            time_frames[time_frame].close_times,
            base.close_times,
            side="right",
        )
        - 1
        for time_frame in REQUIRED_TIME_FRAMES
    }
    base_atr_pct = features_by_time_frame["15m"]["atr_pct"]
    final_entry_index = len(base.values) - config.barriers.horizon_bars - 1

    for base_index in range(0, max(0, final_entry_index + 1), config.candidate_stride):
        raw_features: list[float] = []
        valid = True
        for time_frame in REQUIRED_TIME_FRAMES:
            aligned_index = int(aligned_indices[time_frame][base_index])
            if aligned_index < 0:
                valid = False
                break
            for values in features_by_time_frame[time_frame].values():
                raw_features.append(float(values[aligned_index]))
        if not valid:
            continue
        raw_feature_array = numpy.asarray(raw_features, dtype=float)
        if not indicators.is_finite_feature_row(raw_feature_array):
            continue

        decision_timestamp = int(base.close_times[base_index])
        time_features = _cyclical_time_features(decision_timestamp)
        for direction in (1, -1):
            label_data = _triple_barrier_label(
                base.values,
                base_index,
                direction,
                float(base_atr_pct[base_index]),
                config.barriers,
                funding_series,
            )
            directional_values = raw_feature_array[directional_indices] * direction
            row = numpy.concatenate(
                (
                    raw_feature_array,
                    directional_values,
                    numpy.asarray((direction, *time_features), dtype=float),
                )
            )
            rows.append(row)
            labels.append(int(label_data["outcome"] == OUTCOME_TARGET))
            outcomes.append(int(label_data["outcome"]))
            profitable.append(int(label_data["net_return"] > 0))
            net_returns.append(float(label_data["net_return"]))
            gross_returns.append(float(label_data["gross_return"]))
            timestamps.append(decision_timestamp)
            exit_timestamps.append(int(label_data["exit_timestamp"]))
            event_end_timestamps.append(
                decision_timestamp
                + config.barriers.horizon_bars * TIME_FRAME_SECONDS["15m"]
            )
            symbols.append(symbol)
            directions.append(direction)
            entry_prices.append(float(label_data["entry_price"]))
            stop_prices.append(float(label_data["stop_price"]))
            target_prices.append(float(label_data["target_price"]))
            durations.append(int(label_data["duration_bars"]))
            mfe_returns.append(float(label_data["mfe_return"]))
            mae_returns.append(float(label_data["mae_return"]))

    return ResearchDataset(
        features=numpy.asarray(rows, dtype=numpy.float32).reshape(
            (-1, len(all_feature_names))
        ),
        feature_names=all_feature_names,
        label=numpy.asarray(labels, dtype=numpy.int8),
        outcome=numpy.asarray(outcomes, dtype=numpy.int8),
        profitable=numpy.asarray(profitable, dtype=numpy.int8),
        net_return=numpy.asarray(net_returns, dtype=numpy.float64),
        gross_return=numpy.asarray(gross_returns, dtype=numpy.float64),
        timestamp=numpy.asarray(timestamps, dtype=numpy.int64),
        exit_timestamp=numpy.asarray(exit_timestamps, dtype=numpy.int64),
        event_end_timestamp=numpy.asarray(event_end_timestamps, dtype=numpy.int64),
        symbol=numpy.asarray(symbols),
        direction=numpy.asarray(directions, dtype=numpy.int8),
        entry_price=numpy.asarray(entry_prices, dtype=numpy.float64),
        stop_price=numpy.asarray(stop_prices, dtype=numpy.float64),
        target_price=numpy.asarray(target_prices, dtype=numpy.float64),
        duration_bars=numpy.asarray(durations, dtype=numpy.int16),
        mfe_return=numpy.asarray(mfe_returns, dtype=numpy.float64),
        mae_return=numpy.asarray(mae_returns, dtype=numpy.float64),
    )


def _triple_barrier_label(
    candles: numpy.ndarray,
    entry_index: int,
    direction: int,
    atr_pct: float,
    config: BarrierConfig,
    funding_series: typing.Optional[
        tuple[numpy.ndarray, numpy.ndarray]
    ] = None,
) -> dict:
    entry_price = float(candles[entry_index, 4])
    stop_pct = min(
        config.maximum_stop_pct,
        max(config.minimum_stop_pct, atr_pct * config.atr_multiplier),
    )
    target_pct = stop_pct * config.reward_risk_ratio
    stop_price = entry_price * (1.0 - direction * stop_pct)
    target_price = entry_price * (1.0 + direction * target_pct)

    future = candles[
        entry_index + 1 : entry_index + 1 + config.horizon_bars
    ]
    outcome = OUTCOME_TIMEOUT
    exit_price = float(future[-1, 4])
    exit_index = len(future) - 1
    favorable_prices = []
    adverse_prices = []

    for index, candle in enumerate(future):
        high = float(candle[2])
        low = float(candle[3])
        favorable_prices.append(high if direction == 1 else low)
        adverse_prices.append(low if direction == 1 else high)
        stop_hit = low <= stop_price if direction == 1 else high >= stop_price
        target_hit = high >= target_price if direction == 1 else low <= target_price
        # A candle has no reliable intrabar ordering.  Stop first is conservative.
        if stop_hit:
            outcome = OUTCOME_STOP
            exit_price = stop_price
            exit_index = index
            break
        if target_hit:
            outcome = OUTCOME_TARGET
            exit_price = target_price
            exit_index = index
            break

    gross_return = direction * (exit_price - entry_price) / entry_price
    exit_ratio = exit_price / entry_price
    trading_cost = config.fee_rate_per_fill * (1.0 + exit_ratio)
    slippage_cost = config.slippage_rate_per_fill * 2.0
    held_hours = (exit_index + 1) * TIME_FRAME_SECONDS["15m"] / 3600.0
    entry_timestamp = int(candles[entry_index, 0]) + TIME_FRAME_SECONDS["15m"]
    exit_timestamp = (
        int(future[exit_index, 0]) + TIME_FRAME_SECONDS["15m"]
    )
    if funding_series is None:
        funding_intervals = held_hours / 8.0
        # Without signed history, a configured stress rate is conservatively a
        # cost for both sides.  Zero is the default and is explicit in manifests.
        funding_cost = config.funding_rate_per_8h * funding_intervals
    else:
        funding_timestamps, funding_values = funding_series
        first = int(
            numpy.searchsorted(funding_timestamps, entry_timestamp, side="right")
        )
        last = int(
            numpy.searchsorted(funding_timestamps, exit_timestamp, side="right")
        )
        # Positive KuCoin funding is paid by longs and received by shorts.
        funding_cost = direction * float(numpy.sum(funding_values[first:last]))
    net_return = gross_return - trading_cost - slippage_cost - funding_cost

    favorable = (
        max(favorable_prices) if direction == 1 else min(favorable_prices)
    )
    adverse = min(adverse_prices) if direction == 1 else max(adverse_prices)
    mfe_return = direction * (favorable - entry_price) / entry_price
    mae_return = direction * (adverse - entry_price) / entry_price
    return {
        "outcome": outcome,
        "entry_price": entry_price,
        "stop_price": stop_price,
        "target_price": target_price,
        "gross_return": gross_return,
        "net_return": net_return,
        "exit_timestamp": exit_timestamp,
        "duration_bars": exit_index + 1,
        "mfe_return": max(0.0, mfe_return),
        "mae_return": min(0.0, mae_return),
    }


def _cyclical_time_features(timestamp: int) -> tuple[float, float, float, float]:
    value = datetime.datetime.fromtimestamp(timestamp, datetime.timezone.utc)
    hour_angle = 2.0 * numpy.pi * (
        value.hour + value.minute / 60.0
    ) / 24.0
    weekday_angle = 2.0 * numpy.pi * value.weekday() / 7.0
    return (
        float(numpy.sin(hour_angle)),
        float(numpy.cos(hour_angle)),
        float(numpy.sin(weekday_angle)),
        float(numpy.cos(weekday_angle)),
    )


def _validate_candles(symbol: str, time_frame: str, values: numpy.ndarray) -> None:
    if values.ndim != 2 or values.shape[1] < 6:
        raise ValueError(f"invalid candle matrix for {symbol} {time_frame}")
    if len(values) < 150:
        raise ValueError(f"insufficient candles for {symbol} {time_frame}")
    if not numpy.all(numpy.isfinite(values)):
        raise ValueError(f"non-finite candle value for {symbol} {time_frame}")
    if numpy.any(numpy.diff(values[:, 0]) <= 0):
        raise ValueError(f"duplicate or unordered candles for {symbol} {time_frame}")
    if numpy.any(values[:, 2] < values[:, 3]):
        raise ValueError(f"high below low for {symbol} {time_frame}")
    if numpy.any(values[:, 4] <= 0):
        raise ValueError(f"non-positive close for {symbol} {time_frame}")


def _concatenate_datasets(datasets: list[ResearchDataset]) -> ResearchDataset:
    feature_names = datasets[0].feature_names
    if any(dataset.feature_names != feature_names for dataset in datasets[1:]):
        raise ValueError("feature schemas differ between symbols")
    values = {}
    for field in dataclasses.fields(ResearchDataset):
        if field.name == "feature_names":
            continue
        values[field.name] = numpy.concatenate(
            [getattr(dataset, field.name) for dataset in datasets],
            axis=0,
        )
    return ResearchDataset(feature_names=feature_names, **values)


def _take_dataset(dataset: ResearchDataset, indices: numpy.ndarray) -> ResearchDataset:
    values = {}
    for field in dataclasses.fields(ResearchDataset):
        if field.name == "feature_names":
            continue
        values[field.name] = getattr(dataset, field.name)[indices]
    return ResearchDataset(feature_names=dataset.feature_names, **values)


def _sha256(path: pathlib.Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()
