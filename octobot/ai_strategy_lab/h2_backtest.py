"""Frozen, research-only validation runner for the BTC 15m H2 hypothesis.

This module deliberately keeps strategy selection separate from evaluation.
H2 parameters are constants imported from ``percentage_probability_engine``;
the runner never searches thresholds or changes the model.
"""

from __future__ import annotations

import argparse
import csv
import dataclasses
import datetime
import hashlib
import json
import math
import pathlib
import typing

import numpy

from octobot.ai_strategy_lab import dataset as dataset_module
from octobot.ai_strategy_lab import funding as funding_module
from octobot.ai_strategy_lab import indicators
from octobot.ai_strategy_lab import percentage_engine
from octobot.ai_strategy_lab import percentage_probability_engine as probability_module


SCHEMA_VERSION = 1
PROTOCOL_VERSION = "btc_h2_frozen_v1"
TIME_FRAME = "15m"
CANDLE_SECONDS = 15 * 60
BASE_COST_PCT = 0.16
COST_SCENARIOS = (0.16, 0.24, 0.32)
BOOTSTRAP_SEED = 20_260_724
BOOTSTRAP_SAMPLES = 10_000
GATES = {
    "minimum_trades": 100,
    "minimum_base_profit_factor": 1.20,
    "minimum_double_cost_profit_factor": 1.05,
    "maximum_drawdown_pct": 12.0,
    "minimum_positive_active_month_ratio": 0.55,
    "minimum_long_profit_factor": 1.0,
    "minimum_short_profit_factor": 1.0,
    "require_positive_bootstrap_expectancy_lower_95pct": True,
}


@dataclasses.dataclass(frozen=True)
class EvaluationBlock:
    name: str
    collector_path: pathlib.Path
    source_time_frame: str
    entry_start: datetime.date
    entry_end: datetime.date
    funding_path: pathlib.Path
    exchange: str
    evidence_role: str

    def validate(self) -> None:
        if self.source_time_frame not in {"5m", "15m"}:
            raise ValueError("source_time_frame must be 5m or 15m")
        if self.entry_start > self.entry_end:
            raise ValueError("entry_start must not follow entry_end")
        if not self.collector_path.is_file():
            raise FileNotFoundError(self.collector_path)
        if not self.funding_path.is_file():
            raise FileNotFoundError(self.funding_path)


def frozen_protocol() -> dict:
    """Return the pre-registered protocol without any observed results."""

    return {
        "schema_version": SCHEMA_VERSION,
        "protocol_version": PROTOCOL_VERSION,
        "strategy": {
            "name": "diagnostic_bidirectional_15m_hypothesis_h2",
            "time_frame": TIME_FRAME,
            "model": "frozen percentage_probability_v1/15m base logistic model",
            "score_threshold": (
                probability_module.LONG_15M_HYPOTHESIS_H2_SCORE_THRESHOLD
            ),
            "minimum_volume_zscore": (
                probability_module.LONG_15M_HYPOTHESIS_H2_VOLUME_ZSCORE
            ),
            "directions": ["LONG", "SHORT"],
            "directions_must_alternate": True,
            "one_trade_at_a_time": True,
            "entry": "decision candle close",
            "activation_pct": 1.2,
            "initial_stop_pct": 1.0,
            "protected_stop_pct": 1.0,
            "maximum_holding_hours": 24,
            "same_bar_stop_precedes_activation": True,
            "protected_stop_active_from_next_candle": True,
        },
        "evaluation": {
            "research_only": True,
            "orders_authorized": False,
            "automatic_promotion": False,
            "threshold_search": False,
            "purge_hours_at_block_end": 24,
            "base_round_trip_cost_pct": BASE_COST_PCT,
            "cost_scenarios_pct": list(COST_SCENARIOS),
            "funding_included": True,
            "bootstrap_seed": BOOTSTRAP_SEED,
            "bootstrap_samples": BOOTSTRAP_SAMPLES,
            "gates": GATES,
        },
        "evidence_policy": {
            "kucoin_2026_h2_selection_period": "in_sample_reference_only",
            "pre_model_and_pre_h2_periods": "h2_unseen_holdout",
            "note": (
                "A period can be unseen by H2 without being globally untouched "
                "by every other research project."
            ),
        },
    }


def protocol_sha256(protocol: dict) -> str:
    encoded = json.dumps(
        protocol, sort_keys=True, separators=(",", ":")
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def write_protocol(
    output_directory: typing.Union[str, pathlib.Path],
) -> pathlib.Path:
    """Persist the result-free protocol before an evaluation is run."""

    output = pathlib.Path(output_directory).resolve()
    output.mkdir(parents=True, exist_ok=True)
    protocol = frozen_protocol()
    payload = {
        **protocol,
        "protocol_sha256": protocol_sha256(protocol),
    }
    path = output / "protocol.json"
    path.write_text(
        json.dumps(payload, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return path


def run_backtest(
    *,
    blocks: typing.Iterable[EvaluationBlock],
    reference_blocks: typing.Iterable[EvaluationBlock] = (),
    model_root: typing.Union[str, pathlib.Path],
    output_directory: typing.Union[str, pathlib.Path],
) -> dict:
    """Run frozen H2 on pre-declared blocks and write reproducible evidence."""

    block_values = list(blocks)
    if not block_values:
        raise ValueError("at least one evaluation block is required")
    for block in block_values:
        block.validate()
    reference_values = list(reference_blocks)
    for block in reference_values:
        block.validate()

    output = pathlib.Path(output_directory).resolve()
    protocol_path = output / "protocol.json"
    if not protocol_path.is_file():
        raise FileNotFoundError(
            "protocol.json must be written before running the backtest"
        )
    persisted_protocol = json.loads(protocol_path.read_text(encoding="utf-8"))
    expected_protocol = frozen_protocol()
    if persisted_protocol.get("protocol_sha256") != protocol_sha256(
        expected_protocol
    ):
        raise ValueError("persisted H2 protocol does not match frozen code")

    model_directory = pathlib.Path(model_root).resolve() / TIME_FRAME
    model = probability_module.CalibratedPercentageModel.load(model_directory)
    all_trades = []
    block_reports = []
    for block in block_values:
        block_report, trades = _evaluate_block(block, model)
        block_reports.append(block_report)
        all_trades.extend(trades)
    reference_reports = [
        _evaluate_block(block, model)[0]
        for block in reference_values
    ]

    all_trades.sort(key=lambda value: (value["entry_timestamp"], value["block"]))
    scenarios = {
        _cost_key(cost): _metrics(all_trades, cost)
        for cost in COST_SCENARIOS
    }
    base = scenarios[_cost_key(BASE_COST_PCT)]
    double = scenarios[_cost_key(BASE_COST_PCT * 2)]
    gates = {
        "minimum_trades": base["trades"] >= GATES["minimum_trades"],
        "minimum_base_profit_factor": _at_least(
            base["profit_factor"], GATES["minimum_base_profit_factor"]
        ),
        "minimum_double_cost_profit_factor": _at_least(
            double["profit_factor"],
            GATES["minimum_double_cost_profit_factor"],
        ),
        "maximum_drawdown": (
            base["maximum_drawdown_pct"] <= GATES["maximum_drawdown_pct"]
        ),
        "minimum_positive_active_month_ratio": (
            base["positive_active_month_ratio"]
            >= GATES["minimum_positive_active_month_ratio"]
        ),
        "minimum_long_profit_factor": _at_least(
            base["by_direction"]["LONG"]["profit_factor"],
            GATES["minimum_long_profit_factor"],
        ),
        "minimum_short_profit_factor": _at_least(
            base["by_direction"]["SHORT"]["profit_factor"],
            GATES["minimum_short_profit_factor"],
        ),
        "positive_bootstrap_expectancy_lower_95pct": (
            base["bootstrap_mean_net_return_pct_95pct_ci"][0] > 0
        ),
    }
    artifacts = {
        "protocol": _artifact(protocol_path),
        "model": {
            name: _artifact(model_directory / name)
            for name in ("base_model.npz", "calibrator.json", "model.json")
        },
        "inputs": {
            block.name: {
                "collector": _artifact(block.collector_path),
                "funding": _artifact(block.funding_path),
            }
            for block in block_values + reference_values
        },
    }
    report = {
        "schema_version": SCHEMA_VERSION,
        "protocol_version": PROTOCOL_VERSION,
        "protocol_sha256": protocol_sha256(expected_protocol),
        "created_at": datetime.datetime.now(datetime.timezone.utc).isoformat(),
        "research_only": True,
        "orders_authorized": False,
        "automatic_promotion": False,
        "parameters_changed_during_evaluation": False,
        "funding_included": True,
        "blocks": block_reports,
        "in_sample_reproductions_excluded_from_gates": reference_reports,
        "cost_scenarios": scenarios,
        "gates": {
            "criteria": GATES,
            "results": gates,
            "passed": all(gates.values()),
        },
        "artifacts": artifacts,
        "limitations": [
            (
                "H2 was selected on KuCoin 2026 data; that period is excluded "
                "from holdout conclusions."
            ),
            (
                "OHLC candles do not reveal intrabar path; stop-first and "
                "next-candle lock rules are conservative."
            ),
            (
                "Historical fills use fixed cost stress, not a reconstructed "
                "order book. Funding is included at published settlements."
            ),
            (
                "The holdout periods are H2-unseen, but some were inspected by "
                "other unrelated strategy research."
            ),
        ],
    }
    output.mkdir(parents=True, exist_ok=True)
    report_path = output / "report.json"
    report_path.write_text(
        json.dumps(report, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    trades_path = output / "trades.csv"
    _write_trades(trades_path, all_trades)
    return {
        **report,
        "report_path": str(report_path),
        "trades_path": str(trades_path),
    }


def _evaluate_block(
    block: EvaluationBlock,
    model: probability_module.CalibratedPercentageModel,
) -> tuple[dict, list[dict]]:
    candles = _load_btc_15m(block.collector_path, block.source_time_frame)
    # Rows far beyond the declared block cannot affect causal features or its
    # 24-hour exits. Avoid processing them while retaining all prior warm-up.
    required_end = _date_timestamp(
        block.entry_end + datetime.timedelta(days=2)
    )
    candles = candles[candles[:, 0] < required_end]
    segments = _split_contiguous(candles)
    funding_values = funding_module.load_funding(block.funding_path)
    matching_funding = [
        values
        for symbol, values in funding_values.items()
        if symbol.startswith("BTC/")
    ]
    if len(matching_funding) != 1:
        raise ValueError(
            f"expected exactly one BTC funding series in {block.funding_path}"
        )
    funding_series = matching_funding[0]
    candidates_count = 0
    ignored_open = 0
    ignored_same = 0
    enriched = []
    for segment in segments:
        if len(segment) < 200:
            continue
        segment_result = _evaluate_contiguous_segment(
            block, segment, model, funding_series
        )
        candidates_count += segment_result["candidate_signals"]
        ignored_open += segment_result["ignored_while_trade_open"]
        ignored_same += segment_result["ignored_same_direction_reentries"]
        enriched.extend(segment_result["trades"])
    enriched.sort(key=lambda value: value["entry_timestamp"])
    for sequence, trade in enumerate(enriched, start=1):
        trade["trade_id"] = f"{block.name}-{sequence:04d}"
    return (
        {
            "name": block.name,
            "exchange": block.exchange,
            "evidence_role": block.evidence_role,
            "collector_time_frame": block.source_time_frame,
            "entry_start": block.entry_start.isoformat(),
            "entry_end": block.entry_end.isoformat(),
            "purged_last_24h": True,
            "candles": len(candles),
            "gap_count": len(segments) - 1,
            "continuous_segments": len(segments),
            "gap_policy": "split_and_reset_state_without_interpolation",
            "first_candle_open_utc": _timestamp_iso(int(candles[0, 0])),
            "last_candle_open_utc": _timestamp_iso(int(candles[-1, 0])),
            "candidate_signals": candidates_count,
            "ignored_while_trade_open": ignored_open,
            "ignored_same_direction_reentries": ignored_same,
            "trades": len(enriched),
            "base_cost_metrics": _metrics(enriched, BASE_COST_PCT),
        },
        enriched,
    )


def _evaluate_contiguous_segment(
    block: EvaluationBlock,
    candles: numpy.ndarray,
    model: probability_module.CalibratedPercentageModel,
    funding_series: tuple[numpy.ndarray, numpy.ndarray],
) -> dict:
    arrays = indicators.compute_feature_arrays(candles)
    raw = numpy.column_stack(
        [arrays[name] for name in probability_module.FEATURE_NAMES]
    )
    valid_indices = numpy.flatnonzero(numpy.all(numpy.isfinite(raw), axis=1))
    close_times = candles[:, 0].astype(numpy.int64) + CANDLE_SECONDS
    start_timestamp = _date_timestamp(block.entry_start)
    end_exclusive = _date_timestamp(block.entry_end + datetime.timedelta(days=1))
    last_entry_timestamp = (
        end_exclusive
        - probability_module.PercentageProbabilityConfig(TIME_FRAME).horizon_bars
        * CANDLE_SECONDS
    )
    entry_window = (
        (close_times[valid_indices] >= start_timestamp)
        & (close_times[valid_indices] <= last_entry_timestamp)
    )
    eligible_indices = valid_indices[entry_window]
    candidates = []
    for direction, sign in (
        (percentage_engine.LONG, 1),
        (percentage_engine.SHORT, -1),
    ):
        features = probability_module._feature_block(
            raw[eligible_indices],
            close_times[eligible_indices],
            sign,
        )
        scores = model.base_model.predict_proba(features)
        selected = probability_module._select_long_hypothesis_candidates(
            eligible_indices,
            scores,
            arrays["volume_zscore"],
            score_threshold=(
                probability_module.LONG_15M_HYPOTHESIS_H2_SCORE_THRESHOLD
            ),
            minimum_volume_zscore=(
                probability_module.LONG_15M_HYPOTHESIS_H2_VOLUME_ZSCORE
            ),
        )
        score_by_index = {
            int(index): float(score)
            for index, score in zip(eligible_indices, scores)
        }
        candidates.extend(
            {
                "entry_index": int(index),
                "direction": direction,
                "raw_score": score_by_index[int(index)],
                # H2 uses the base score. Calibrated probability is metadata only.
                "probability_pct": float(
                    model.calibrator.predict(
                        numpy.asarray([score_by_index[int(index)]])
                    )[0]
                    * 100
                ),
            }
            for index in selected
        )

    config = probability_module.PercentageProbabilityConfig(TIME_FRAME)
    trades, ignored_open, ignored_same = (
        probability_module._simulate_alternating_hypothesis(
            times=close_times.tolist(),
            highs=candles[:, 2].tolist(),
            lows=candles[:, 3].tolist(),
            closes=candles[:, 4].tolist(),
            candidates=candidates,
            last_closed_index=len(candles) - 1,
            config=config,
        )
    )
    funding_timestamps, funding_rates = funding_series
    enriched = []
    for trade in trades:
        if trade["status"] != "closed":
            raise ValueError("purged historical block unexpectedly contains open trade")
        entry_timestamp = int(trade["entry_time"])
        exit_timestamp = int(trade["exit_time"])
        first = int(
            numpy.searchsorted(
                funding_timestamps, entry_timestamp, side="right"
            )
        )
        last = int(numpy.searchsorted(funding_timestamps, exit_timestamp, side="right"))
        sign = 1 if trade["direction"] == percentage_engine.LONG else -1
        funding_cost_pct = sign * float(numpy.sum(funding_rates[first:last])) * 100
        enriched.append(
            {
                "block": block.name,
                "exchange": block.exchange,
                "evidence_role": block.evidence_role,
                "direction": trade["direction"],
                "entry_timestamp": entry_timestamp,
                "entry_time_utc": _timestamp_iso(entry_timestamp),
                "entry_price": float(trade["entry_price"]),
                "exit_timestamp": exit_timestamp,
                "exit_time_utc": _timestamp_iso(exit_timestamp),
                "exit_price": float(trade["exit_price"]),
                "exit_reason": trade["exit_reason"],
                "duration_hours": (
                    (exit_timestamp - entry_timestamp) / 3600
                ),
                "raw_score": float(trade["raw_score"]),
                "probability_pct": float(trade["probability_pct"]),
                "volume_zscore": float(
                    arrays["volume_zscore"][int(trade["entry_index"])]
                ),
                "gross_return_pct": float(trade["gross_return_pct"]),
                "funding_cost_pct": funding_cost_pct,
                "net_return_pct_base_cost": (
                    float(trade["gross_return_pct"])
                    - funding_cost_pct
                    - BASE_COST_PCT
                ),
                "maximum_favorable_excursion_pct": float(
                    trade["maximum_favorable_excursion_pct"]
                ),
                "maximum_adverse_excursion_pct": float(
                    trade["maximum_adverse_excursion_pct"]
                ),
            }
        )
    return {
        "candidate_signals": len(candidates),
        "ignored_while_trade_open": ignored_open,
        "ignored_same_direction_reentries": ignored_same,
        "trades": enriched,
    }


def _load_btc_15m(path: pathlib.Path, source_time_frame: str) -> numpy.ndarray:
    series = dataset_module.load_collector_series(
        [path], required_time_frames=(source_time_frame,)
    )
    matching = [
        frames[source_time_frame].values
        for symbol, frames in series.items()
        if symbol.startswith("BTC/")
    ]
    if len(matching) != 1:
        raise ValueError(f"expected one BTC series in {path}")
    values = matching[0]
    if source_time_frame == TIME_FRAME:
        return values
    return _aggregate_5m_to_15m(values)


def _aggregate_5m_to_15m(candles: numpy.ndarray) -> numpy.ndarray:
    buckets: dict[int, list[numpy.ndarray]] = {}
    for candle in candles:
        bucket = int(candle[0]) // CANDLE_SECONDS * CANDLE_SECONDS
        buckets.setdefault(bucket, []).append(candle)
    result = []
    for timestamp in sorted(buckets):
        rows = sorted(buckets[timestamp], key=lambda value: value[0])
        if len(rows) != 3:
            continue
        if any(
            int(rows[index][0] - rows[index - 1][0]) != 300
            for index in range(1, 3)
        ):
            continue
        result.append(
            [
                timestamp,
                float(rows[0][1]),
                max(float(row[2]) for row in rows),
                min(float(row[3]) for row in rows),
                float(rows[-1][4]),
                sum(float(row[5]) for row in rows),
            ]
        )
    return numpy.asarray(result, dtype=float)


def _split_contiguous(candles: numpy.ndarray) -> list[numpy.ndarray]:
    if len(candles) < 200:
        raise ValueError("H2 backtest needs at least 200 15m candles")
    gaps = numpy.flatnonzero(numpy.diff(candles[:, 0]) != CANDLE_SECONDS)
    return [
        segment
        for segment in numpy.split(candles, gaps + 1)
        if len(segment)
    ]


def _metrics(trades: list[dict], cost_pct: float) -> dict:
    returns = numpy.asarray(
        [
            float(trade["gross_return_pct"])
            - float(trade["funding_cost_pct"])
            - cost_pct
            for trade in trades
        ],
        dtype=float,
    )
    if not len(returns):
        return _empty_metrics()
    wins = returns > 0
    gains = float(numpy.sum(returns[returns > 0]))
    losses = float(-numpy.sum(returns[returns < 0]))
    equity = numpy.cumprod(1 + returns / 100)
    running_peak = numpy.maximum.accumulate(
        numpy.concatenate((numpy.asarray([1.0]), equity))
    )[1:]
    drawdowns = (1 - equity / running_peak) * 100
    monthly: dict[str, list[float]] = {}
    for trade, value in zip(trades, returns):
        key = f"{trade['exchange']}:{trade['entry_time_utc'][:7]}"
        monthly.setdefault(key, []).append(float(value))
    monthly_returns = {
        key: (math.prod(1 + value / 100 for value in values) - 1) * 100
        for key, values in sorted(monthly.items())
    }
    by_direction = {}
    for direction in (percentage_engine.LONG, percentage_engine.SHORT):
        selected = returns[
            numpy.asarray(
                [trade["direction"] == direction for trade in trades],
                dtype=bool,
            )
        ]
        direction_gains = float(numpy.sum(selected[selected > 0]))
        direction_losses = float(-numpy.sum(selected[selected < 0]))
        by_direction[direction] = {
            "trades": int(len(selected)),
            "win_rate_pct": float(numpy.mean(selected > 0) * 100)
            if len(selected)
            else 0.0,
            "net_return_sum_pct": float(numpy.sum(selected)),
            "profit_factor": (
                direction_gains / direction_losses
                if direction_losses
                else None
            ),
        }
    bootstrap_low, bootstrap_high = _bootstrap_mean_interval(returns)
    wilson_low, wilson_high = _wilson_interval(int(numpy.sum(wins)), len(returns))
    return {
        "trades": len(trades),
        "wins": int(numpy.sum(wins)),
        "win_rate_pct": float(numpy.mean(wins) * 100),
        "win_rate_95pct_wilson_ci": [wilson_low * 100, wilson_high * 100],
        "profit_factor": gains / losses if losses else None,
        "expectancy_pct_per_trade": float(numpy.mean(returns)),
        "bootstrap_mean_net_return_pct_95pct_ci": [
            bootstrap_low,
            bootstrap_high,
        ],
        "compounded_net_return_pct": float((equity[-1] - 1) * 100),
        "maximum_drawdown_pct": float(numpy.max(drawdowns)),
        "average_duration_hours": float(
            numpy.mean([trade["duration_hours"] for trade in trades])
        ),
        "exposure_hours": float(
            numpy.sum([trade["duration_hours"] for trade in trades])
        ),
        "positive_active_months": sum(value > 0 for value in monthly_returns.values()),
        "active_months": len(monthly_returns),
        "positive_active_month_ratio": (
            sum(value > 0 for value in monthly_returns.values())
            / len(monthly_returns)
        ),
        "monthly_compounded_returns_pct": monthly_returns,
        "by_direction": by_direction,
        "round_trip_cost_pct": cost_pct,
        "total_funding_cost_pct": float(
            sum(float(trade["funding_cost_pct"]) for trade in trades)
        ),
    }


def _empty_metrics() -> dict:
    return {
        "trades": 0,
        "wins": 0,
        "win_rate_pct": 0.0,
        "win_rate_95pct_wilson_ci": [0.0, 0.0],
        "profit_factor": None,
        "expectancy_pct_per_trade": 0.0,
        "bootstrap_mean_net_return_pct_95pct_ci": [0.0, 0.0],
        "compounded_net_return_pct": 0.0,
        "maximum_drawdown_pct": 0.0,
        "average_duration_hours": 0.0,
        "exposure_hours": 0.0,
        "positive_active_months": 0,
        "active_months": 0,
        "positive_active_month_ratio": 0.0,
        "monthly_compounded_returns_pct": {},
        "by_direction": {
            direction: {
                "trades": 0,
                "win_rate_pct": 0.0,
                "net_return_sum_pct": 0.0,
                "profit_factor": None,
            }
            for direction in (percentage_engine.LONG, percentage_engine.SHORT)
        },
        "round_trip_cost_pct": 0.0,
        "total_funding_cost_pct": 0.0,
    }


def _bootstrap_mean_interval(returns: numpy.ndarray) -> tuple[float, float]:
    if not len(returns):
        return 0.0, 0.0
    generator = numpy.random.default_rng(BOOTSTRAP_SEED)
    means = numpy.empty(BOOTSTRAP_SAMPLES, dtype=float)
    # Chunking avoids a large samples-by-trades allocation on long studies.
    chunk = 500
    for start in range(0, BOOTSTRAP_SAMPLES, chunk):
        count = min(chunk, BOOTSTRAP_SAMPLES - start)
        indices = generator.integers(0, len(returns), size=(count, len(returns)))
        means[start : start + count] = numpy.mean(returns[indices], axis=1)
    low, high = numpy.quantile(means, (0.025, 0.975))
    return float(low), float(high)


def _wilson_interval(wins: int, count: int) -> tuple[float, float]:
    if count == 0:
        return 0.0, 0.0
    z = 1.959963984540054
    proportion = wins / count
    denominator = 1 + z * z / count
    centre = proportion + z * z / (2 * count)
    margin = z * math.sqrt(
        proportion * (1 - proportion) / count + z * z / (4 * count * count)
    )
    return (centre - margin) / denominator, (centre + margin) / denominator


def _write_trades(path: pathlib.Path, trades: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fields = list(trades[0]) if trades else [
        "trade_id",
        "block",
        "exchange",
        "evidence_role",
        "direction",
        "entry_timestamp",
        "entry_time_utc",
        "entry_price",
        "exit_timestamp",
        "exit_time_utc",
        "exit_price",
        "exit_reason",
        "duration_hours",
        "raw_score",
        "probability_pct",
        "volume_zscore",
        "gross_return_pct",
        "funding_cost_pct",
        "net_return_pct_base_cost",
        "maximum_favorable_excursion_pct",
        "maximum_adverse_excursion_pct",
    ]
    with path.open("w", encoding="utf-8", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=fields)
        writer.writeheader()
        writer.writerows(trades)


def _cost_key(cost_pct: float) -> str:
    return f"round_trip_{cost_pct:.2f}pct"


def _at_least(value: typing.Optional[float], threshold: float) -> bool:
    return value is not None and value >= threshold


def _date_timestamp(value: datetime.date) -> int:
    return int(
        datetime.datetime.combine(
            value, datetime.time.min, datetime.timezone.utc
        ).timestamp()
    )


def _timestamp_iso(value: int) -> str:
    return datetime.datetime.fromtimestamp(
        value, datetime.timezone.utc
    ).isoformat()


def _sha256(path: pathlib.Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _artifact(path: pathlib.Path) -> dict:
    resolved = path.resolve()
    return {
        "path": str(resolved),
        "sha256": _sha256(resolved),
        "bytes": resolved.stat().st_size,
    }


def _parse_block(value: str) -> EvaluationBlock:
    parts = value.split("|")
    if len(parts) != 8:
        raise argparse.ArgumentTypeError(
            "block must be NAME|COLLECTOR|TF|START|END|FUNDING|EXCHANGE|ROLE"
        )
    try:
        return EvaluationBlock(
            name=parts[0],
            collector_path=pathlib.Path(parts[1]).resolve(),
            source_time_frame=parts[2],
            entry_start=datetime.date.fromisoformat(parts[3]),
            entry_end=datetime.date.fromisoformat(parts[4]),
            funding_path=pathlib.Path(parts[5]).resolve(),
            exchange=parts[6],
            evidence_role=parts[7],
        )
    except ValueError as error:
        raise argparse.ArgumentTypeError(str(error)) from error


def main(argv: typing.Optional[list[str]] = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--write-protocol-only",
        action="store_true",
        help="Write the result-free protocol and stop.",
    )
    parser.add_argument("--model-root")
    parser.add_argument("--output-directory", required=True)
    parser.add_argument(
        "--block",
        action="append",
        type=_parse_block,
        help="NAME|COLLECTOR|TF|START|END|FUNDING|EXCHANGE|ROLE",
    )
    parser.add_argument(
        "--reference-block",
        action="append",
        type=_parse_block,
        help=(
            "In-sample reproduction block, reported separately and excluded "
            "from validation gates."
        ),
    )
    args = parser.parse_args(argv)
    protocol_path = write_protocol(args.output_directory)
    if args.write_protocol_only:
        print(json.dumps({"protocol_path": str(protocol_path)}, indent=2))
        return 0
    if not args.model_root or not args.block:
        parser.error("--model-root and at least one --block are required")
    report = run_backtest(
        blocks=args.block,
        reference_blocks=args.reference_block or (),
        model_root=args.model_root,
        output_directory=args.output_directory,
    )
    base = report["cost_scenarios"][_cost_key(BASE_COST_PCT)]
    print(
        json.dumps(
            {
                "report_path": report["report_path"],
                "trades_path": report["trades_path"],
                "trades": base["trades"],
                "win_rate_pct": base["win_rate_pct"],
                "profit_factor": base["profit_factor"],
                "compounded_net_return_pct": base[
                    "compounded_net_return_pct"
                ],
                "maximum_drawdown_pct": base["maximum_drawdown_pct"],
                "gates_passed": report["gates"]["passed"],
            },
            indent=2,
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
