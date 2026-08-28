"""Result-free BTC Level-5 absorption markout research V3.

The earlier queue-flow model showed that generic short-horizon return
prediction did not cover taker costs.  This experiment tests one narrower
microstructure mechanism without opening the sealed 20--26 August block:
extreme aggressive flow that is opposed by displayed refill/order-flow and
then fails to move the microprice may indicate absorption and a reversal.

Feature thresholds are estimated from past *features only*.  Economic
outcomes are fixed 15-minute executable markouts, evaluated after the result-
free protocol is persisted.  The module is offline, public-data-only and has
no order path.
"""

from __future__ import annotations

import argparse
import dataclasses
import datetime
import hashlib
import json
import math
import pathlib
import typing

import numpy

from octobot.ai_strategy_lab import scalping_strategy_search as v1
from octobot.ai_strategy_lab import scalping_strategy_search_v3 as parent


SCHEMA_VERSION = 1
PROTOCOL_VERSION = "btc_microstructure_absorption_markout_v3"
PREREGISTRATION_DATE = "2026-08-28"

PARENT_PROTOCOL_SHA256 = (
    "192c3dd1b040479d9f9f21cdc7ce9e985bb2fd4fdf2bfdb9dc88753c44ea3924"
)
PARENT_PROTOCOL_FILE_SHA256 = (
    "9ad5cf4397cbfac8ac31e7eb8f5517322d4c9b6c4369a1492acd3bd9a6b8a5c3"
)
PARENT_DATASET_SHA256 = (
    "6e7cbd40f26e6f3f8a65629f8e4c1d76de4f04bef5035e812f42f28f525403fe"
)
PARENT_DATASET_MANIFEST_SHA256 = (
    "6c4f94e19bdcd63858f0b123aedab8d8a7edc427fcca5a7140df6578fe896d65"
)
PARENT_REPORT_SHA256 = (
    "287272147cd20ba90131cc36ca75ee12a5765e4f2c2ab1ade1bd509840e80d24"
)
SOURCE_CACHE_SHA256 = (
    "f3cf2dd6b25dcd6966dc36dc38edec1ae075f554535b1067e0971a2a1835af7c"
)

SOURCE_START = parent.SOURCE_START
DEVELOPMENT_END = parent.DEVELOPMENT_END
DIAGNOSTIC_CONFIRMATION_END = parent.DIAGNOSTIC_CONFIRMATION_END
LOCKED_TEST_END = parent.LOCKED_TEST_END

PRIMARY_HORIZON_SECONDS = 15 * 60
PRIMARY_LATENCY_MS = 500
STRESS_LATENCY_MS = 1_000
FEE_BPS_PER_FILL = 6.0
SLIPPAGE_BPS_PER_FILL = 1.0
COST_STRESS_MULTIPLIER = 2.0
POSITION_FRACTION = 0.10
WALK_FORWARD_FOLDS = 5
EMBARGO_SECONDS = PRIMARY_HORIZON_SECONDS

# These quantiles were chosen using feature-frequency counts only.  No
# economic outcome was read when selecting them.
PRESSURE_QUANTILE = 0.99
DEFENDING_REFILL_QUANTILE = 0.35
BOOK_TRADE_DIVERGENCE_QUANTILE = 0.35
PRICE_RESPONSE_QUANTILE = 0.60
SPREAD_QUANTILE = 0.99

PRESSURE_FEATURE = "q60_directional_aggressor_to_depth"
REFILL_FEATURE = "q60_directional_refill_asymmetry_mean"
DIVERGENCE_FEATURE = "q60_directional_ofi_trade_divergence"
PRICE_RESPONSE_FEATURE = "w60_directional_mid_return_bps"
MICROPRICE_CONFIRMATION_FEATURE = "q5_directional_microprice_change_bps"
SPREAD_FEATURE = "w60_spread_bps_mean"
REQUIRED_FEATURES = (
    PRESSURE_FEATURE,
    REFILL_FEATURE,
    DIVERGENCE_FEATURE,
    PRICE_RESPONSE_FEATURE,
    MICROPRICE_CONFIRMATION_FEATURE,
    SPREAD_FEATURE,
)
FEATURE_INDICES = {
    name: parent.FEATURE_NAMES.index(name) for name in REQUIRED_FEATURES
}


def _json_hash(payload: object) -> str:
    return hashlib.sha256(
        json.dumps(
            payload, sort_keys=True, separators=(",", ":"), allow_nan=False
        ).encode("utf-8")
    ).hexdigest()


def _sha256(path: pathlib.Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _atomic_json(path: pathlib.Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(
        json.dumps(payload, indent=2, sort_keys=True, allow_nan=False) + "\n",
        encoding="utf-8",
    )
    temporary.replace(path)


def frozen_protocol() -> dict:
    """Return the result-free absorption protocol."""

    return {
        "schema_version": SCHEMA_VERSION,
        "protocol_version": PROTOCOL_VERSION,
        "preregistered_on": PREREGISTRATION_DATE,
        "status": "result_free_diagnostic_reuse_protocol",
        "research_only": True,
        "public_data_only": True,
        "credentials_used": False,
        "orders_authorized": False,
        "paper_orders_authorized": False,
        "automatic_promotion": False,
        "parent_v3": {
            "protocol_version": parent.PROTOCOL_VERSION,
            "protocol_sha256": PARENT_PROTOCOL_SHA256,
            "protocol_file_sha256": PARENT_PROTOCOL_FILE_SHA256,
            "dataset_sha256": PARENT_DATASET_SHA256,
            "dataset_manifest_sha256": PARENT_DATASET_MANIFEST_SHA256,
            "report_sha256": PARENT_REPORT_SHA256,
            "source_cache_sha256": SOURCE_CACHE_SHA256,
            "known_aggregate_lesson": (
                "generic event-level queue-flow prediction exposed at most "
                "about 1.3 gross bps and did not cover a 14-bps taker round "
                "trip"
            ),
            "row_level_economic_outcomes_reused": False,
            "feature_rows_reused": True,
        },
        "hypothesis": {
            "name": "aggressor_absorption_reversal",
            "statement": (
                "extreme 60-second aggressive flow that is opposed by "
                "displayed refill/order-flow divergence and followed by a "
                "five-second microprice reversal has a positive executable "
                "15-minute markout in the opposite direction"
            ),
            "primary_candidate_count": 1,
            "direction_symmetric": True,
            "continuation_arm": False,
            "post_fit_inversion": False,
        },
        "signal": {
            "decision_stride_seconds": 15,
            "pressure_feature": PRESSURE_FEATURE,
            "pressure_absolute_quantile": PRESSURE_QUANTILE,
            "defending_refill_feature": REFILL_FEATURE,
            "defending_refill_conditional_quantile": (
                DEFENDING_REFILL_QUANTILE
            ),
            "defending_refill_upper_bound": 0.0,
            "book_trade_divergence_feature": DIVERGENCE_FEATURE,
            "book_trade_divergence_conditional_quantile": (
                BOOK_TRADE_DIVERGENCE_QUANTILE
            ),
            "price_response_feature": PRICE_RESPONSE_FEATURE,
            "price_response_conditional_quantile": PRICE_RESPONSE_QUANTILE,
            "microprice_confirmation_feature": (
                MICROPRICE_CONFIRMATION_FEATURE
            ),
            "microprice_confirmation": "strictly_against_aggressor",
            "spread_feature": SPREAD_FEATURE,
            "spread_upper_quantile": SPREAD_QUANTILE,
            "threshold_fit": (
                "past feature distribution only; no label, return, MFE, MAE "
                "or trade outcome"
            ),
            "trade_direction": "opposite_to_aggressor_pressure",
            "one_trade_at_a_time": True,
            "cooldown_seconds": PRIMARY_HORIZON_SECONDS,
            "threshold_or_feature_search": False,
        },
        "markout": {
            "primary_horizon_seconds": PRIMARY_HORIZON_SECONDS,
            "take_profit": None,
            "stop_loss": None,
            "purpose": (
                "falsification screen for net directional value, not a final "
                "risk-managed strategy"
            ),
            "primary_entry": (
                "executable ask for long or bid for short after 500ms"
            ),
            "primary_exit": (
                "executable bid for long or ask for short after 15 minutes"
            ),
            "stress_entry_latency_ms": STRESS_LATENCY_MS,
            "fee_bps_per_fill": FEE_BPS_PER_FILL,
            "slippage_bps_per_fill": SLIPPAGE_BPS_PER_FILL,
            "primary_round_trip_cost_bps": 2
            * (FEE_BPS_PER_FILL + SLIPPAGE_BPS_PER_FILL),
            "stress_cost_multiplier": COST_STRESS_MULTIPLIER,
            "position_fraction": POSITION_FRACTION,
            "maker_fill_assumptions": False,
        },
        "validation": {
            "development": [SOURCE_START, DEVELOPMENT_END],
            "development_walk_forward_folds": WALK_FORWARD_FOLDS,
            "purge_embargo_seconds": EMBARGO_SECONDS,
            "diagnostic_confirmation": [
                DEVELOPMENT_END,
                DIAGNOSTIC_CONFIRMATION_END,
            ],
            "diagnostic_confirmation_is_not_pristine": True,
            "feature_frequency_was_inspected": True,
            "economic_outcomes_inspected_before_freeze": False,
            "locked_final_test": [
                DIAGNOSTIC_CONFIRMATION_END,
                LOCKED_TEST_END,
            ],
            "locked_test_materialized": False,
            "locked_test_policy": (
                "a separate command and artifact may be created once only if "
                "development and diagnostic confirmation pass every gate"
            ),
        },
        "development_gate": {
            "minimum_trades": 50,
            "minimum_trades_per_direction": 15,
            "minimum_profit_factor": 1.20,
            "minimum_mean_net_bps": 0.0,
            "minimum_positive_operating_days_pct": 55.0,
            "maximum_drawdown_pct": 5.0,
            "minimum_positive_folds": 3,
            "daily_block_bootstrap_one_sided_level": 0.90,
            "bootstrap_lower_mean_net_bps_above": 0.0,
            "long_and_short_contribution_non_negative": True,
            "double_cost_and_latency_total_return_positive": True,
        },
        "diagnostic_confirmation_gate": {
            "minimum_trades": 15,
            "minimum_trades_per_direction": 4,
            "minimum_profit_factor": 1.20,
            "minimum_mean_net_bps": 0.0,
            "minimum_positive_operating_days_pct": 55.0,
            "maximum_drawdown_pct": 5.0,
            "long_and_short_contribution_non_negative": True,
            "double_cost_and_latency_total_return_positive": True,
        },
        "multiple_testing_disclosure": (
            "one symmetric absorption rule is eligible; thresholds were "
            "chosen from feature-frequency counts only and are not searched "
            "against economic outcomes"
        ),
        "advancement_consequence": (
            "even a complete pre-test pass permits only one locked offline "
            "evaluation; it cannot authorize shadow, paper or real orders"
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
            raise ValueError("persisted absorption V3 protocol differs")
        return persisted
    _atomic_json(path, payload)
    return payload


@dataclasses.dataclass(frozen=True)
class FeatureDataset:
    timestamps: numpy.ndarray
    features: numpy.ndarray

    def validate(self) -> None:
        rows = len(self.timestamps)
        if rows == 0 or numpy.any(numpy.diff(self.timestamps) <= 0):
            raise ValueError("absorption feature timestamps are invalid")
        if self.features.shape != (rows, len(parent.FEATURE_NAMES)):
            raise ValueError("absorption feature matrix differs")
        if not numpy.all(numpy.isfinite(self.features)):
            raise ValueError("absorption features contain non-finite values")
        if int(self.timestamps[-1]) >= v1._iso_timestamp(
            DIAGNOSTIC_CONFIRMATION_END
        ):
            raise ValueError("absorption pre-test features enter locked data")


def load_feature_dataset(
    dataset_value: typing.Union[str, pathlib.Path],
    manifest_value: typing.Union[str, pathlib.Path],
) -> FeatureDataset:
    dataset_path = pathlib.Path(dataset_value).resolve()
    manifest_path = pathlib.Path(manifest_value).resolve()
    if _sha256(manifest_path) != PARENT_DATASET_MANIFEST_SHA256:
        raise ValueError("parent V3 dataset manifest hash differs")
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    if manifest.get("artifact", {}).get("sha256") != PARENT_DATASET_SHA256:
        raise ValueError("parent V3 dataset artifact differs")
    if manifest.get("locked_test_materialized") is not False:
        raise ValueError("parent V3 dataset opened locked data")
    if _sha256(dataset_path) != PARENT_DATASET_SHA256:
        raise ValueError("parent V3 dataset bytes differ")
    with numpy.load(dataset_path, allow_pickle=False) as values:
        if str(values["protocol_sha256"][0]) != PARENT_PROTOCOL_SHA256:
            raise ValueError("parent V3 protocol identity differs")
        if str(values["source_snapshot_sha256"][0]) != v1.SNAPSHOT_SHA256:
            raise ValueError("parent V3 snapshot identity differs")
        names = tuple(str(value) for value in values["feature_names"])
        if names != parent.FEATURE_NAMES:
            raise ValueError("parent V3 feature schema differs")
        dataset = FeatureDataset(
            timestamps=values["timestamps"].copy(),
            features=values["features"].copy(),
        )
    dataset.validate()
    return dataset


@dataclasses.dataclass(frozen=True)
class QuoteSource:
    start_second: int
    end_second: int
    entry_bid_0: numpy.ndarray
    entry_ask_0: numpy.ndarray
    entry_bid_500: numpy.ndarray
    entry_ask_500: numpy.ndarray
    last_bid: numpy.ndarray
    last_ask: numpy.ndarray
    prefix_last_bid_500: numpy.ndarray
    prefix_last_ask_500: numpy.ndarray

    def validate(self) -> None:
        length = self.end_second - self.start_second + 1
        if length <= PRIMARY_HORIZON_SECONDS:
            raise ValueError("quote source interval is too short")
        for field in dataclasses.fields(self):
            if field.name in {"start_second", "end_second"}:
                continue
            if len(getattr(self, field.name)) != length:
                raise ValueError(f"quote source field {field.name} differs")


def load_quote_source(
    path_value: typing.Union[str, pathlib.Path],
) -> QuoteSource:
    path = pathlib.Path(path_value).resolve()
    if _sha256(path) != SOURCE_CACHE_SHA256:
        raise ValueError("dense quote source hash differs")
    with numpy.load(path, allow_pickle=False) as values:
        if str(values["protocol_sha256"][0]) != v1._json_hash(
            v1.frozen_protocol()
        ):
            raise ValueError("dense quote source protocol differs")
        if str(values["source_snapshot_sha256"][0]) != v1.SNAPSHOT_SHA256:
            raise ValueError("dense quote source snapshot differs")
        source = QuoteSource(
            start_second=int(values["start_second"][0]),
            end_second=int(values["end_second"][0]),
            entry_bid_0=values["value_entry_bid_0"].copy(),
            entry_ask_0=values["value_entry_ask_0"].copy(),
            entry_bid_500=values["value_entry_bid_500"].copy(),
            entry_ask_500=values["value_entry_ask_500"].copy(),
            last_bid=values["value_last_bid"].copy(),
            last_ask=values["value_last_ask"].copy(),
            prefix_last_bid_500=values[
                "value_prefix_last_bid_500"
            ].copy(),
            prefix_last_ask_500=values[
                "value_prefix_last_ask_500"
            ].copy(),
        )
    source.validate()
    return source


def _feature(features: numpy.ndarray, name: str) -> numpy.ndarray:
    return features[:, FEATURE_INDICES[name]].astype(numpy.float64)


def fit_feature_thresholds(features: numpy.ndarray) -> dict[str, float]:
    """Fit absorption thresholds without accepting an outcome argument."""

    if len(features) < 100:
        raise ValueError("insufficient past features for absorption thresholds")
    pressure = _feature(features, PRESSURE_FEATURE)
    signs = numpy.sign(pressure)
    pressure_threshold = float(
        numpy.quantile(numpy.abs(pressure), PRESSURE_QUANTILE)
    )
    extreme = (numpy.abs(pressure) >= pressure_threshold) & (signs != 0)
    if numpy.count_nonzero(extreme) < 10:
        raise ValueError("insufficient extreme pressure feature rows")
    aligned_refill = signs * _feature(features, REFILL_FEATURE)
    aligned_divergence = signs * _feature(features, DIVERGENCE_FEATURE)
    aligned_response = signs * _feature(features, PRICE_RESPONSE_FEATURE)
    return {
        "pressure_absolute_minimum": pressure_threshold,
        "aligned_refill_maximum": min(
            0.0,
            float(
                numpy.quantile(
                    aligned_refill[extreme], DEFENDING_REFILL_QUANTILE
                )
            ),
        ),
        "aligned_divergence_maximum": float(
            numpy.quantile(
                aligned_divergence[extreme],
                BOOK_TRADE_DIVERGENCE_QUANTILE,
            )
        ),
        "aligned_price_response_maximum_bps": float(
            numpy.quantile(
                aligned_response[extreme], PRICE_RESPONSE_QUANTILE
            )
        ),
        "spread_maximum_bps": float(
            numpy.quantile(
                _feature(features, SPREAD_FEATURE), SPREAD_QUANTILE
            )
        ),
    }


def absorption_directions(
    features: numpy.ndarray, thresholds: dict[str, float]
) -> numpy.ndarray:
    """Return -1/0/+1 using only point-in-time feature values."""

    pressure = _feature(features, PRESSURE_FEATURE)
    signs = numpy.sign(pressure)
    aligned_refill = signs * _feature(features, REFILL_FEATURE)
    aligned_divergence = signs * _feature(features, DIVERGENCE_FEATURE)
    aligned_response = signs * _feature(features, PRICE_RESPONSE_FEATURE)
    aligned_microprice = signs * _feature(
        features, MICROPRICE_CONFIRMATION_FEATURE
    )
    spread = _feature(features, SPREAD_FEATURE)
    selected = (
        (signs != 0)
        & (
            numpy.abs(pressure)
            >= thresholds["pressure_absolute_minimum"]
        )
        & (aligned_refill <= thresholds["aligned_refill_maximum"])
        & (
            aligned_divergence
            <= thresholds["aligned_divergence_maximum"]
        )
        & (
            aligned_response
            <= thresholds["aligned_price_response_maximum_bps"]
        )
        & (aligned_microprice < 0.0)
        & (spread <= thresholds["spread_maximum_bps"])
    )
    directions = numpy.zeros(len(features), dtype=numpy.int8)
    directions[selected] = -signs[selected].astype(numpy.int8)
    return directions


def non_overlapping_rows(
    timestamps: numpy.ndarray,
    directions: numpy.ndarray,
    *,
    cooldown_seconds: int = PRIMARY_HORIZON_SECONDS,
) -> numpy.ndarray:
    if len(timestamps) != len(directions):
        raise ValueError("timestamps and directions are misaligned")
    selected: list[int] = []
    next_allowed = -1
    for row in numpy.flatnonzero(directions):
        timestamp = int(timestamps[row])
        if timestamp >= next_allowed:
            selected.append(int(row))
            next_allowed = timestamp + int(cooldown_seconds)
    return numpy.asarray(selected, dtype=numpy.int64)


def _development_folds(dataset: FeatureDataset) -> list[tuple[numpy.ndarray, numpy.ndarray]]:
    development = numpy.flatnonzero(
        dataset.timestamps < v1._iso_timestamp(DEVELOPMENT_END)
    )
    if len(development) < WALK_FORWARD_FOLDS + 1:
        raise ValueError("insufficient development rows")
    test_size = len(development) // (WALK_FORWARD_FOLDS + 1)
    if test_size < 1:
        raise ValueError("empty absorption walk-forward test")
    folds = []
    for fold in range(WALK_FORWARD_FOLDS):
        start = (fold + 1) * test_size
        end = len(development) if fold == WALK_FORWARD_FOLDS - 1 else start + test_size
        test = development[start:end]
        purge_before = int(dataset.timestamps[test[0]]) - EMBARGO_SECONDS
        train = development[dataset.timestamps[development] < purge_before]
        if len(train) < 100 or len(test) == 0:
            raise ValueError("purging leaves an empty absorption fold")
        folds.append((train, test))
    return folds


def executable_markouts(
    source: QuoteSource,
    timestamps: numpy.ndarray,
    directions: numpy.ndarray,
    *,
    stress: bool,
) -> numpy.ndarray:
    """Calculate fixed-horizon executable returns for selected signals."""

    if len(timestamps) != len(directions):
        raise ValueError("markout timestamps and directions are misaligned")
    if not set(numpy.unique(directions)).issubset({-1, 1}):
        raise ValueError("markout directions must be long or short")
    primary_start = timestamps.astype(numpy.int64) - source.start_second
    if stress:
        starts = primary_start + 1
        deadlines = starts + PRIMARY_HORIZON_SECONDS - 1
        entry_bid = source.entry_bid_0[starts]
        entry_ask = source.entry_ask_0[starts]
        exit_bid = source.last_bid[deadlines]
        exit_ask = source.last_ask[deadlines]
        multiplier = COST_STRESS_MULTIPLIER
    else:
        starts = primary_start
        deadlines = starts + PRIMARY_HORIZON_SECONDS
        entry_bid = source.entry_bid_500[starts]
        entry_ask = source.entry_ask_500[starts]
        exit_bid = source.prefix_last_bid_500[deadlines]
        exit_ask = source.prefix_last_ask_500[deadlines]
        multiplier = 1.0
    if numpy.any(starts < 0) or numpy.any(deadlines >= len(source.entry_bid_0)):
        raise ValueError("markout interval is outside the quote source")
    quotes = numpy.column_stack((entry_bid, entry_ask, exit_bid, exit_ask))
    if not numpy.all(numpy.isfinite(quotes)) or numpy.any(quotes <= 0):
        raise ValueError("markout interval contains invalid executable quotes")
    gross = numpy.where(
        directions == 1,
        exit_bid / entry_ask - 1.0,
        entry_bid / exit_ask - 1.0,
    )
    cost = (
        2.0
        * (FEE_BPS_PER_FILL + SLIPPAGE_BPS_PER_FILL)
        * multiplier
        / 10_000.0
    )
    return (gross - cost).astype(numpy.float64)


@dataclasses.dataclass(frozen=True)
class Trades:
    timestamps: numpy.ndarray
    directions: numpy.ndarray
    folds: numpy.ndarray
    primary_returns: numpy.ndarray
    stress_returns: numpy.ndarray

    def validate(self) -> None:
        rows = len(self.timestamps)
        for field in dataclasses.fields(self):
            if len(getattr(self, field.name)) != rows:
                raise ValueError("absorption trades are misaligned")
        if rows and numpy.any(numpy.diff(self.timestamps) <= 0):
            raise ValueError("absorption trades are not chronological")


def _combine_trade_parts(parts: list[Trades]) -> Trades:
    if not parts:
        empty_i64 = numpy.asarray([], dtype=numpy.int64)
        return Trades(
            timestamps=empty_i64,
            directions=numpy.asarray([], dtype=numpy.int8),
            folds=numpy.asarray([], dtype=numpy.int8),
            primary_returns=numpy.asarray([], dtype=numpy.float64),
            stress_returns=numpy.asarray([], dtype=numpy.float64),
        )
    timestamps = numpy.concatenate([part.timestamps for part in parts])
    order = numpy.argsort(timestamps, kind="stable")
    combined = Trades(
        timestamps=timestamps[order],
        directions=numpy.concatenate([part.directions for part in parts])[order],
        folds=numpy.concatenate([part.folds for part in parts])[order],
        primary_returns=numpy.concatenate(
            [part.primary_returns for part in parts]
        )[order],
        stress_returns=numpy.concatenate(
            [part.stress_returns for part in parts]
        )[order],
    )
    combined.validate()
    if not len(combined.timestamps):
        return combined
    keep = []
    next_allowed = -1
    for row, timestamp in enumerate(combined.timestamps):
        if int(timestamp) >= next_allowed:
            keep.append(row)
            next_allowed = int(timestamp) + PRIMARY_HORIZON_SECONDS
    indices = numpy.asarray(keep, dtype=numpy.int64)
    return Trades(
        **{
            field.name: getattr(combined, field.name)[indices]
            for field in dataclasses.fields(Trades)
        }
    )


def _maximum_drawdown(equity: numpy.ndarray) -> float:
    if not len(equity):
        return 0.0
    peaks = numpy.maximum.accumulate(equity)
    return float(numpy.max(1.0 - equity / peaks))


def _daily_bootstrap_lower_mean_bps(
    timestamps: numpy.ndarray,
    returns: numpy.ndarray,
    *,
    repetitions: int = 5_000,
) -> float | None:
    if not len(returns):
        return None
    days = timestamps // 86_400
    unique_days = numpy.unique(days)
    if len(unique_days) < 2:
        return None
    grouped = [returns[days == day] for day in unique_days]
    generator = numpy.random.default_rng(20260828)
    means = numpy.empty(repetitions, dtype=numpy.float64)
    for repetition in range(repetitions):
        selected = generator.integers(0, len(grouped), size=len(grouped))
        sample = numpy.concatenate([grouped[index] for index in selected])
        means[repetition] = numpy.mean(sample) * 10_000.0
    return float(numpy.quantile(means, 0.10))


def trade_metrics(
    timestamps: numpy.ndarray,
    directions: numpy.ndarray,
    returns: numpy.ndarray,
    *,
    bootstrap: bool,
) -> dict:
    rows = len(returns)
    positive = float(numpy.sum(returns[returns > 0])) if rows else 0.0
    negative = float(-numpy.sum(returns[returns < 0])) if rows else 0.0
    profit_factor = positive / negative if negative > 0 else None
    scaled = POSITION_FRACTION * returns
    equity = numpy.cumprod(1.0 + scaled) if rows else numpy.asarray([])
    days = timestamps // 86_400 if rows else numpy.asarray([], dtype=numpy.int64)
    daily_returns = []
    for day in numpy.unique(days):
        daily_returns.append(
            float(numpy.prod(1.0 + scaled[days == day]) - 1.0)
        )
    positive_days = sum(value > 0 for value in daily_returns)

    def direction_summary(direction: int) -> dict:
        selected = returns[directions == direction]
        return {
            "trades": int(len(selected)),
            "mean_net_bps": (
                float(numpy.mean(selected) * 10_000.0)
                if len(selected)
                else 0.0
            ),
            "total_return": (
                float(
                    numpy.prod(1.0 + POSITION_FRACTION * selected) - 1.0
                )
                if len(selected)
                else 0.0
            ),
        }

    return {
        "trades": int(rows),
        "wins": int(numpy.count_nonzero(returns > 0)),
        "win_rate_pct": (
            float(numpy.mean(returns > 0) * 100.0) if rows else 0.0
        ),
        "mean_net_bps": float(numpy.mean(returns) * 10_000.0) if rows else 0.0,
        "median_net_bps": (
            float(numpy.median(returns) * 10_000.0) if rows else 0.0
        ),
        "profit_factor": profit_factor,
        "total_return": float(equity[-1] - 1.0) if rows else 0.0,
        "max_drawdown": _maximum_drawdown(equity),
        "operating_days": int(len(daily_returns)),
        "positive_operating_days_pct": (
            positive_days / len(daily_returns) * 100.0
            if daily_returns
            else 0.0
        ),
        "daily_bootstrap_lower_mean_net_bps_90": (
            _daily_bootstrap_lower_mean_bps(timestamps, returns)
            if bootstrap
            else None
        ),
        "by_direction": {
            "long": direction_summary(1),
            "short": direction_summary(-1),
        },
    }


def _profit_factor_passes(metrics: dict, minimum: float) -> bool:
    value = metrics["profit_factor"]
    if value is None:
        return metrics["total_return"] > 0.0 and metrics["wins"] > 0
    return float(value) >= minimum


def gate(
    primary: dict,
    stress: dict,
    *,
    confirmation: bool,
    positive_folds: int | None = None,
) -> dict:
    minimum_trades = 15 if confirmation else 50
    minimum_per_direction = 4 if confirmation else 15
    checks = {
        "minimum_trades": primary["trades"] >= minimum_trades,
        "minimum_long_trades": (
            primary["by_direction"]["long"]["trades"]
            >= minimum_per_direction
        ),
        "minimum_short_trades": (
            primary["by_direction"]["short"]["trades"]
            >= minimum_per_direction
        ),
        "profit_factor": _profit_factor_passes(primary, 1.20),
        "mean_net_positive": primary["mean_net_bps"] > 0.0,
        "positive_operating_days": (
            primary["positive_operating_days_pct"] >= 55.0
        ),
        "maximum_drawdown": primary["max_drawdown"] <= 0.05,
        "long_non_negative": (
            primary["by_direction"]["long"]["total_return"] >= 0.0
        ),
        "short_non_negative": (
            primary["by_direction"]["short"]["total_return"] >= 0.0
        ),
        "stress_positive": stress["total_return"] > 0.0,
    }
    if confirmation:
        pass
    else:
        lower = primary["daily_bootstrap_lower_mean_net_bps_90"]
        checks["bootstrap_lower_mean_positive"] = (
            lower is not None and lower > 0.0
        )
        checks["positive_folds"] = (
            positive_folds is not None and positive_folds >= 3
        )
    return {
        "passed": all(checks.values()),
        "passed_checks": sum(bool(value) for value in checks.values()),
        "total_checks": len(checks),
        "checks": checks,
    }


def _trade_part(
    dataset: FeatureDataset,
    source: QuoteSource,
    rows: numpy.ndarray,
    thresholds: dict[str, float],
    fold: int,
) -> Trades:
    directions_all = absorption_directions(dataset.features[rows], thresholds)
    local = non_overlapping_rows(dataset.timestamps[rows], directions_all)
    selected = rows[local]
    directions = directions_all[local]
    primary_returns = executable_markouts(
        source, dataset.timestamps[selected], directions, stress=False
    )
    stress_returns = executable_markouts(
        source, dataset.timestamps[selected], directions, stress=True
    )
    return Trades(
        timestamps=dataset.timestamps[selected],
        directions=directions,
        folds=numpy.full(len(selected), fold, dtype=numpy.int8),
        primary_returns=primary_returns,
        stress_returns=stress_returns,
    )


def _save_decisions(path: pathlib.Path, trades: Trades) -> dict:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    with temporary.open("wb") as stream:
        numpy.savez_compressed(
            stream,
            protocol_version=numpy.asarray([PROTOCOL_VERSION]),
            protocol_sha256=numpy.asarray([_json_hash(frozen_protocol())]),
            **{
                field.name: getattr(trades, field.name)
                for field in dataclasses.fields(Trades)
            },
        )
        stream.flush()
    temporary.replace(path)
    return {
        "path": str(path),
        "bytes": path.stat().st_size,
        "sha256": _sha256(path),
    }


def evaluate_pretest(
    *,
    protocol_value: typing.Union[str, pathlib.Path],
    dataset_value: typing.Union[str, pathlib.Path],
    dataset_manifest_value: typing.Union[str, pathlib.Path],
    source_cache_value: typing.Union[str, pathlib.Path],
    output_root_value: typing.Union[str, pathlib.Path],
    progress: typing.Callable[[str], None] | None = None,
) -> dict:
    """Evaluate development and reused confirmation, never the locked block."""

    progress = progress or (lambda _message: None)
    protocol = write_or_verify_protocol(protocol_value)
    progress("loading feature-only parent rows")
    dataset = load_feature_dataset(dataset_value, dataset_manifest_value)
    progress("loading verified executable quote arrays")
    source = load_quote_source(source_cache_value)

    fold_parts: list[Trades] = []
    fold_reports = []
    for fold, (train, test) in enumerate(_development_folds(dataset), 1):
        thresholds = fit_feature_thresholds(dataset.features[train])
        part = _trade_part(dataset, source, test, thresholds, fold)
        fold_parts.append(part)
        primary = trade_metrics(
            part.timestamps,
            part.directions,
            part.primary_returns,
            bootstrap=False,
        )
        stress = trade_metrics(
            part.timestamps,
            part.directions,
            part.stress_returns,
            bootstrap=False,
        )
        fold_reports.append(
            {
                "fold": fold,
                "train_rows": int(len(train)),
                "test_rows": int(len(test)),
                "thresholds": thresholds,
                "primary": primary,
                "stress": stress,
            }
        )
        progress(
            f"absorption fold {fold}/{WALK_FORWARD_FOLDS}: "
            f"trades={primary['trades']} mean={primary['mean_net_bps']:.3f}bps"
        )
    development_trades = _combine_trade_parts(fold_parts)
    development_primary = trade_metrics(
        development_trades.timestamps,
        development_trades.directions,
        development_trades.primary_returns,
        bootstrap=True,
    )
    development_stress = trade_metrics(
        development_trades.timestamps,
        development_trades.directions,
        development_trades.stress_returns,
        bootstrap=False,
    )
    positive_folds = sum(
        report["primary"]["total_return"] > 0.0
        for report in fold_reports
    )
    development_gate = gate(
        development_primary,
        development_stress,
        confirmation=False,
        positive_folds=positive_folds,
    )

    development_rows = numpy.flatnonzero(
        dataset.timestamps < v1._iso_timestamp(DEVELOPMENT_END)
    )
    confirmation_rows = numpy.flatnonzero(
        (dataset.timestamps >= v1._iso_timestamp(DEVELOPMENT_END))
        & (
            dataset.timestamps
            < v1._iso_timestamp(DIAGNOSTIC_CONFIRMATION_END)
        )
    )
    final_thresholds = fit_feature_thresholds(
        dataset.features[development_rows]
    )
    confirmation_trades = _trade_part(
        dataset, source, confirmation_rows, final_thresholds, 0
    )
    confirmation_primary = trade_metrics(
        confirmation_trades.timestamps,
        confirmation_trades.directions,
        confirmation_trades.primary_returns,
        bootstrap=False,
    )
    confirmation_stress = trade_metrics(
        confirmation_trades.timestamps,
        confirmation_trades.directions,
        confirmation_trades.stress_returns,
        bootstrap=False,
    )
    confirmation_gate = gate(
        confirmation_primary,
        confirmation_stress,
        confirmation=True,
    )
    locked_authorized = (
        development_gate["passed"] and confirmation_gate["passed"]
    )

    timestamp = datetime.datetime.now(datetime.timezone.utc).strftime(
        "%Y%m%dT%H%M%SZ"
    )
    output = pathlib.Path(output_root_value).resolve() / (
        f"{PROTOCOL_VERSION}-{timestamp}"
    )
    output.mkdir(parents=True, exist_ok=False)
    development_artifact = _save_decisions(
        output / "development-decisions.npz", development_trades
    )
    confirmation_artifact = _save_decisions(
        output / "confirmation-decisions.npz", confirmation_trades
    )
    report = {
        "schema_version": SCHEMA_VERSION,
        "mode": "absorption_pretest_diagnostic_reuse",
        "created_at": datetime.datetime.now(datetime.timezone.utc).isoformat(),
        "research_only": True,
        "orders_authorized": False,
        "paper_orders_authorized": False,
        "automatic_promotion": False,
        "protocol_version": PROTOCOL_VERSION,
        "protocol_sha256": protocol["protocol_sha256"],
        "parent_dataset_sha256": PARENT_DATASET_SHA256,
        "source_cache_sha256": SOURCE_CACHE_SHA256,
        "development": {
            "start": SOURCE_START,
            "end": DEVELOPMENT_END,
            "folds": fold_reports,
            "positive_folds": positive_folds,
            "primary": development_primary,
            "stress": development_stress,
            "gate": development_gate,
            "decisions": development_artifact,
        },
        "diagnostic_confirmation": {
            "start": DEVELOPMENT_END,
            "end": DIAGNOSTIC_CONFIRMATION_END,
            "thresholds": final_thresholds,
            "primary": confirmation_primary,
            "stress": confirmation_stress,
            "gate": confirmation_gate,
            "decisions": confirmation_artifact,
        },
        "locked_test": {
            "start": DIAGNOSTIC_CONFIRMATION_END,
            "end": LOCKED_TEST_END,
            "materialized": False,
            "authorized_to_open": locked_authorized,
        },
        "verdict": (
            "PRETEST_PASS_LOCK_ELIGIBLE"
            if locked_authorized
            else "REJECTED_PRETEST_LOCK_REMAINS_SEALED"
        ),
    }
    report_path = output / "report.json"
    _atomic_json(report_path, report)
    report_sha256 = _sha256(report_path)
    manifest = {
        "schema_version": SCHEMA_VERSION,
        "protocol_version": PROTOCOL_VERSION,
        "protocol_sha256": protocol["protocol_sha256"],
        "report": {
            "path": str(report_path),
            "bytes": report_path.stat().st_size,
            "sha256": report_sha256,
        },
        "development_decisions": development_artifact,
        "confirmation_decisions": confirmation_artifact,
        "locked_test_materialized": False,
        "locked_test_authorized": locked_authorized,
        "orders_authorized": False,
        "paper_orders_authorized": False,
    }
    manifest_path = output / "manifest.json"
    _atomic_json(manifest_path, manifest)
    return {
        **report,
        "report_path": str(report_path),
        "report_sha256": report_sha256,
        "manifest_path": str(manifest_path),
        "manifest_sha256": _sha256(manifest_path),
    }


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)
    write = subparsers.add_parser("write-protocol")
    write.add_argument("--output", required=True)
    evaluate = subparsers.add_parser("evaluate-pretest")
    evaluate.add_argument("--protocol", required=True)
    evaluate.add_argument("--dataset", required=True)
    evaluate.add_argument("--dataset-manifest", required=True)
    evaluate.add_argument("--source-cache", required=True)
    evaluate.add_argument("--output-root", required=True)
    return parser


def main(argv: typing.Sequence[str] | None = None) -> int:
    arguments = _build_parser().parse_args(argv)
    if arguments.command == "write-protocol":
        result = write_or_verify_protocol(arguments.output)
    else:
        result = evaluate_pretest(
            protocol_value=arguments.protocol,
            dataset_value=arguments.dataset,
            dataset_manifest_value=arguments.dataset_manifest,
            source_cache_value=arguments.source_cache,
            output_root_value=arguments.output_root,
            progress=lambda message: print(message, flush=True),
        )
    print(json.dumps(result, indent=2, sort_keys=True, allow_nan=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
