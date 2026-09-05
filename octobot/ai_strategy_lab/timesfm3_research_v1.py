"""Result-free scaffold for an offline TimesFM 3 crypto experiment.

This module deliberately stops before model download and outcome evaluation.  It
freezes the hypothesis, verifies immutable local inputs, and constructs causal
multivariate queries.  Loading model weights additionally requires an explicit
local acceptance record for Google's non-commercial, non-production license.
Nothing in this module imports an exchange client or can authorize an order.
"""

from __future__ import annotations

import argparse
import dataclasses
import datetime
import hashlib
import importlib.metadata
import json
import os
import pathlib
import platform
import tempfile
import typing

import numpy

from octobot.ai_strategy_lab import dataset as dataset_module
from octobot.ai_strategy_lab import funding as funding_module


SCHEMA_VERSION = 1
PROTOCOL_VERSION = "timesfm3_crypto_multivariate_zero_shot_v1"
PREREGISTRATION_DATE = "2026-09-03"
MODEL_REPOSITORY = "google/timesfm-3.0-pytorch"
MODEL_REVISION = "43046b85ec22d584a13f8098c2ed39c889e129c2"
MODEL_WEIGHTS_SHA256 = (
    "a7592b0a8432baee54483254e5647856911ce69e09d09a9bb65904b2d98f17da"
)
MODEL_WEIGHTS_BYTES = 1_322_898_824
MODEL_LICENSE_ID = "timesfm-non-commercial-license-v1.0"
MODEL_LICENSE_URL = (
    "https://huggingface.co/google/timesfm-3.0-pytorch/blob/main/LICENSE"
)
TIMESFM_PACKAGE_VERSION = "3.0.1"
TORCH_CPU_VERSION = "2.14.0+cpu"
ASSETS = ("BTC", "ETH", "SOL", "XRP")
FUTURES_SYMBOLS = tuple(f"{asset}/USDT:USDT" for asset in ASSETS)
SPOT_SYMBOLS = tuple(f"{asset}/USDT" for asset in ASSETS)
CONTEXT_HOURS = 1_536
HORIZON_HOURS = 24
ORIGIN_HOUR_UTC = 0
TARGET_CHANNELS = 4
PAST_ONLY_CHANNELS = 16
PAST_FUTURE_CHANNELS = 5
TOTAL_VARIATES = TARGET_CHANNELS + PAST_ONLY_CHANNELS + PAST_FUTURE_CHANNELS
MAX_MODEL_VARIATES = 32

FROZEN_INPUTS = {
    "futures_collector": {
        "filename": "binance_um_all_20220501_20260630.data",
        "sha256": "cdacae131f194c2b4e0b5a2dce51569de23b6fca9be9f34e68240769c7c53a6d",
        "bytes": 73_801_728,
    },
    "futures_manifest": {
        "filename": "binance_um_all_20220501_20260630.data.manifest.json",
        "sha256": "53d5182102676b683149e6f2b9d9bfa5c96dbf1f1dbf53b0441026844e91b9fd",
    },
    "spot_collector": {
        "filename": "binance_spot_all_20220501_20260630.data",
        "sha256": "12ef3439bee72a6f58c7f07d06c9e17b9e5461fb357e1b4bbfaf3be2be18b703",
        "bytes": 74_285_056,
    },
    "spot_manifest": {
        "filename": "binance_spot_all_20220501_20260630.data.manifest.json",
        "sha256": "242b9a371b98260420f30dcbeb549a79843690f5d5aca3a38fe45571d4e343ab",
    },
    "funding": {
        "filename": "binance_um_all_funding_20220501_20260630.json",
        "sha256": "8590651353fb9ac1743d9f0ec659bd4a076db6156654e8ea5054a5f8c50bc67b",
    },
}


class DataQualityError(ValueError):
    """Raised when a supposedly frozen input or causal query differs."""


class LicenseAcceptanceRequired(PermissionError):
    """Raised before any TimesFM 3 weight is loaded without acceptance."""


@dataclasses.dataclass(frozen=True)
class MarketPanel:
    """Aligned one-hour public market inputs, with no outcome fields."""

    open_timestamps: numpy.ndarray
    futures_candles: numpy.ndarray
    spot_candles: numpy.ndarray
    funding_rates: numpy.ndarray

    def validate(self) -> None:
        rows = len(self.open_timestamps)
        expected_candles = (len(ASSETS), rows, 6)
        if self.futures_candles.shape != expected_candles:
            raise DataQualityError("unexpected futures panel shape")
        if self.spot_candles.shape != expected_candles:
            raise DataQualityError("unexpected spot panel shape")
        if self.funding_rates.shape != (len(ASSETS), rows):
            raise DataQualityError("unexpected funding panel shape")
        if rows < CONTEXT_HOURS + HORIZON_HOURS:
            raise DataQualityError("insufficient hourly history")
        if numpy.any(numpy.diff(self.open_timestamps) != 3_600):
            raise DataQualityError("aligned one-hour panel is not contiguous")
        for values in (self.futures_candles, self.spot_candles):
            if not numpy.all(numpy.isfinite(values)):
                raise DataQualityError("market panel contains non-finite values")
            if numpy.any(values[:, :, 1:5] <= 0):
                raise DataQualityError("market panel contains non-positive prices")
            if numpy.any(values[:, :, 5] < 0):
                raise DataQualityError("market panel contains negative volume")


@dataclasses.dataclass(frozen=True)
class CausalQuery:
    """A TimesFM query containing information known at one decision time."""

    decision_timestamp: int
    targets: numpy.ndarray
    past_only_covariates: numpy.ndarray
    past_future_covariates: numpy.ndarray

    def validate(self) -> None:
        if self.targets.shape != (TARGET_CHANNELS, CONTEXT_HOURS):
            raise DataQualityError("unexpected target query shape")
        if self.past_only_covariates.shape != (
            PAST_ONLY_CHANNELS,
            CONTEXT_HOURS,
        ):
            raise DataQualityError("unexpected past-only query shape")
        if self.past_future_covariates.shape != (
            PAST_FUTURE_CHANNELS,
            CONTEXT_HOURS + HORIZON_HOURS,
        ):
            raise DataQualityError("unexpected known-future query shape")
        if TOTAL_VARIATES > MAX_MODEL_VARIATES:
            raise DataQualityError("query exceeds the frozen model variate limit")
        for values in (
            self.targets,
            self.past_only_covariates,
            self.past_future_covariates,
        ):
            if not numpy.all(numpy.isfinite(values)):
                raise DataQualityError("query contains non-finite values")


def frozen_protocol() -> dict:
    """Return the immutable hypothesis without reading any market outcome."""

    return {
        "schema_version": SCHEMA_VERSION,
        "protocol_version": PROTOCOL_VERSION,
        "preregistration_date": PREREGISTRATION_DATE,
        "status": "preregistered_before_timesfm3_outcomes",
        "question": (
            "Does zero-shot TimesFM 3 add calibrated 24h price-path information "
            "beyond simple causal baselines on liquid crypto perpetuals?"
        ),
        "scope": {
            "historical_role": "diagnostic_only_due_to_dataset_reuse",
            "universe": list(ASSETS),
            "venue": "Binance USD-M public archive",
            "frequency": "1h completed candles",
            "context_hours": CONTEXT_HOURS,
            "horizon_hours": HORIZON_HOURS,
            "forecast_origin": "daily at 00:00 UTC",
            "zero_shot": True,
            "fine_tuning_allowed": False,
            "hyperparameter_search_allowed": False,
            "first_clean_evidence": "new forward data after protocol publication",
        },
        "model": {
            "repository": MODEL_REPOSITORY,
            "revision": MODEL_REVISION,
            "weights_sha256": MODEL_WEIGHTS_SHA256,
            "weights_bytes": MODEL_WEIGHTS_BYTES,
            "package": "timesfm",
            "package_version": TIMESFM_PACKAGE_VERSION,
            "torch_cpu_version": TORCH_CPU_VERSION,
            "device": "cpu",
            "input_patch_length": 32,
            "output_patch_length": 64,
            "maximum_variates": MAX_MODEL_VARIATES,
            "quantiles": [value / 10 for value in range(1, 10)],
            "symmetric_averaging": False,
            "local_files_only": True,
        },
        "license_gate": {
            "license_id": MODEL_LICENSE_ID,
            "license_url": MODEL_LICENSE_URL,
            "restriction": "non-commercial and non-production research only",
            "explicit_local_acceptance_required_before_download_or_load": True,
            "accepted_in_this_protocol": False,
            "weights_downloaded_in_this_protocol": False,
        },
        "inputs": {
            "frozen_files": FROZEN_INPUTS,
            "target_channels": [f"log_futures_close:{asset}" for asset in ASSETS],
            "past_only_channels": [
                f"{feature}:{asset}"
                for feature in (
                    "log_notional_volume",
                    "absolute_log_return",
                    "futures_spot_basis_bps",
                    "last_published_funding_bps",
                )
                for asset in ASSETS
            ],
            "known_future_channels": [
                "hour_sin",
                "hour_cos",
                "weekday_sin",
                "weekday_cos",
                "scheduled_funding_window",
            ],
            "total_variates": TOTAL_VARIATES,
            "missing_data_policy": (
                "inner join exact hourly timestamps; reject non-contiguous spans; "
                "never backfill funding from the future"
            ),
        },
        "causality": {
            "decision_time": "one hour after the final context candle open",
            "latest_market_value": "close of the final completed context candle",
            "funding": "last publication timestamp not later than decision time",
            "known_future_data": "calendar and funding schedule only",
            "future_prices_or_rates_in_model_input": False,
        },
        "baselines": [
            "unchanged terminal price",
            "same UTC hour one day earlier",
            "rolling AR(1) fitted inside each context",
            "EWMA volatility for risk calibration",
        ],
        "metrics": {
            "primary_predictive": [
                "pooled 24h terminal-return MAE in basis points",
                "per-asset MAE skill versus unchanged price",
                "mean quantile pinball loss",
                "q10-q90 empirical coverage",
            ],
            "secondary_predictive": [
                "terminal direction accuracy",
                "path MAE by forecast hour",
                "interval width versus realized absolute return",
            ],
            "economic_is_separate_from_predictive": True,
        },
        "fixed_economic_translation": {
            "entry": "next hourly open after the 00:00 UTC decision",
            "long": "q20 terminal return strictly exceeds round-trip cost",
            "short": "q80 terminal return is strictly below negative round-trip cost",
            "otherwise": "flat",
            "holding_period_hours": 24,
            "overlapping_positions": False,
            "position_fraction_per_asset": 0.10,
            "maximum_gross_fraction": 0.40,
            "leverage": 1.0,
            "fee_rate_per_fill": 0.0006,
            "slippage_rate_per_fill": 0.0002,
            "round_trip_cost_rate": 0.0016,
            "stress_cost_multiplier": 3.0,
            "funding": "actual signed settlements while the diagnostic is open",
        },
        "forward_eligibility_gates": {
            "all_gates_required": True,
            "minimum_daily_origins": 1_000,
            "pooled_mae_improvement_over_unchanged": 0.02,
            "every_asset_mae_skill_strictly_positive": True,
            "q10_q90_coverage_range": [0.725, 0.875],
            "minimum_direction_accuracy": 0.525,
            "minimum_net_trades": 100,
            "minimum_net_sharpe": 0.50,
            "minimum_net_profit_factor": 1.05,
            "maximum_net_drawdown": 0.20,
            "stress_net_return_strictly_positive": True,
            "minimum_forward_observation_days_after_pass": 180,
            "historical_pass_can_authorize_orders": False,
        },
        "runtime_boundaries": {
            "container_network": "none during inference and evaluation",
            "market_inputs_read_only": True,
            "model_cache_read_only": True,
            "separate_from_octobot_runtime": True,
            "credentials_used": False,
            "orders_authorized": False,
            "paper_orders_authorized": False,
            "automatic_promotion": False,
            "real_income_authorized": False,
        },
        "results": None,
    }


def _canonical_json(value: typing.Any) -> bytes:
    return json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
    ).encode("utf-8")


def logical_hash(value: typing.Any) -> str:
    return hashlib.sha256(_canonical_json(value)).hexdigest()


def file_hash(path_value: typing.Union[str, pathlib.Path]) -> str:
    path = pathlib.Path(path_value).resolve()
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _atomic_json(path: pathlib.Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(
        mode="w",
        encoding="utf-8",
        dir=path.parent,
        prefix=f".{path.name}.",
        suffix=".tmp",
        delete=False,
    ) as stream:
        temporary = pathlib.Path(stream.name)
        json.dump(payload, stream, indent=2, sort_keys=True)
        stream.write("\n")
        stream.flush()
        os.fsync(stream.fileno())
    os.replace(temporary, path)


def write_protocol(output_value: typing.Union[str, pathlib.Path]) -> pathlib.Path:
    output = pathlib.Path(output_value).resolve()
    protocol = frozen_protocol()
    payload = {**protocol, "protocol_sha256": logical_hash(protocol)}
    if output.exists():
        persisted = json.loads(output.read_text(encoding="utf-8"))
        if persisted != payload:
            raise DataQualityError("existing TimesFM 3 protocol differs")
        return output
    _atomic_json(output, payload)
    return output


def _verify_frozen_file(label: str, path: pathlib.Path) -> dict:
    expected = FROZEN_INPUTS[label]
    if path.name != expected["filename"]:
        raise DataQualityError(f"{label} filename differs")
    if not path.is_file():
        raise FileNotFoundError(path)
    actual_hash = file_hash(path)
    if actual_hash != expected["sha256"]:
        raise DataQualityError(f"{label} SHA-256 differs")
    expected_bytes = expected.get("bytes")
    if expected_bytes is not None and path.stat().st_size != expected_bytes:
        raise DataQualityError(f"{label} size differs")
    return {
        "label": label,
        "filename": path.name,
        "bytes": path.stat().st_size,
        "sha256": actual_hash,
    }


def _series_map(path: pathlib.Path, symbols: tuple[str, ...]) -> dict[str, numpy.ndarray]:
    loaded = dataset_module.load_collector_series([path], ("1h",))
    if set(loaded) != set(symbols):
        raise DataQualityError(f"unexpected symbols in {path.name}")
    return {symbol: loaded[symbol]["1h"].values for symbol in symbols}


def load_aligned_panel(
    futures_value: typing.Union[str, pathlib.Path],
    spot_value: typing.Union[str, pathlib.Path],
    funding_value: typing.Union[str, pathlib.Path],
) -> MarketPanel:
    """Load and align public inputs; no forward target is constructed here."""

    futures_path = pathlib.Path(futures_value).resolve()
    spot_path = pathlib.Path(spot_value).resolve()
    funding_path = pathlib.Path(funding_value).resolve()
    futures = _series_map(futures_path, FUTURES_SYMBOLS)
    spot = _series_map(spot_path, SPOT_SYMBOLS)
    rates = funding_module.load_funding(funding_path)
    if set(rates) != set(FUTURES_SYMBOLS):
        raise DataQualityError("unexpected funding symbols")

    timestamp_sets = []
    for values in (*futures.values(), *spot.values()):
        timestamp_sets.append(set(values[:, 0].astype(numpy.int64)))
    common = sorted(set.intersection(*timestamp_sets))
    if not common:
        raise DataQualityError("futures and spot inputs do not overlap")
    timestamps = numpy.asarray(common, dtype=numpy.int64)

    # The fixed protocol rejects the entire history at any cross-market gap.
    # The supplied spot archive has one known two-hour hole, so keep only the
    # longest contiguous segment rather than silently interpolating across it.
    discontinuities = numpy.flatnonzero(numpy.diff(timestamps) != 3_600)
    boundaries = numpy.concatenate(
        (numpy.asarray([-1]), discontinuities, numpy.asarray([len(timestamps) - 1]))
    )
    spans = [
        (int(boundaries[i] + 1), int(boundaries[i + 1] + 1))
        for i in range(len(boundaries) - 1)
    ]
    start, stop = max(spans, key=lambda value: value[1] - value[0])
    timestamps = timestamps[start:stop]

    def align(source: dict[str, numpy.ndarray], symbols: tuple[str, ...]) -> numpy.ndarray:
        blocks = []
        for symbol in symbols:
            rows = {int(row[0]): row for row in source[symbol]}
            blocks.append(numpy.asarray([rows[int(ts)] for ts in timestamps]))
        return numpy.asarray(blocks, dtype=numpy.float64)

    funding_values = []
    decision_times = timestamps + 3_600
    for symbol in FUTURES_SYMBOLS:
        published_at, values = rates[symbol]
        indices = numpy.searchsorted(published_at, decision_times, side="right") - 1
        if numpy.any(indices < 0):
            raise DataQualityError(f"funding begins after market data for {symbol}")
        funding_values.append(values[indices])

    panel = MarketPanel(
        open_timestamps=timestamps,
        futures_candles=align(futures, FUTURES_SYMBOLS),
        spot_candles=align(spot, SPOT_SYMBOLS),
        funding_rates=numpy.asarray(funding_values, dtype=numpy.float64),
    )
    panel.validate()
    return panel


def eligible_origin_indices(panel: MarketPanel) -> numpy.ndarray:
    """Return daily origins using timestamps only, never future prices."""

    panel.validate()
    candidates = numpy.arange(
        CONTEXT_HOURS - 1,
        len(panel.open_timestamps) - HORIZON_HOURS,
        dtype=numpy.int64,
    )
    decision_times = panel.open_timestamps[candidates] + 3_600
    hours = (decision_times // 3_600) % 24
    return candidates[hours == ORIGIN_HOUR_UTC]


def build_causal_query(panel: MarketPanel, origin_index: int) -> CausalQuery:
    """Build one query using no market value after its decision timestamp."""

    panel.validate()
    origin = int(origin_index)
    start = origin - CONTEXT_HOURS + 1
    if start < 0 or origin + HORIZON_HOURS >= len(panel.open_timestamps):
        raise DataQualityError("origin lacks the frozen context or timestamp horizon")
    window = slice(start, origin + 1)
    futures = panel.futures_candles[:, window]
    spot = panel.spot_candles[:, window]
    closes = futures[:, :, 4]
    log_closes = numpy.log(closes)
    prior_index = start - 1
    if prior_index < 0:
        prior = log_closes[:, :1]
    else:
        prior = numpy.log(panel.futures_candles[:, prior_index : start, 4])
    absolute_returns = numpy.abs(numpy.diff(numpy.concatenate((prior, log_closes), axis=1)))
    log_notional_volume = numpy.log1p(closes * futures[:, :, 5])
    basis_bps = (log_closes - numpy.log(spot[:, :, 4])) * 10_000
    funding_bps = panel.funding_rates[:, window] * 10_000
    past_only = numpy.concatenate(
        (log_notional_volume, absolute_returns, basis_bps, funding_bps),
        axis=0,
    )

    decision_timestamp = int(panel.open_timestamps[origin] + 3_600)
    calendar_timestamps = (
        numpy.arange(
            decision_timestamp - (CONTEXT_HOURS - 1) * 3_600,
            decision_timestamp + (HORIZON_HOURS + 1) * 3_600,
            3_600,
            dtype=numpy.int64,
        )[: CONTEXT_HOURS + HORIZON_HOURS]
    )
    hours = (calendar_timestamps // 3_600) % 24
    weekdays = numpy.asarray(
        [
            datetime.datetime.fromtimestamp(int(value), datetime.timezone.utc).weekday()
            for value in calendar_timestamps
        ],
        dtype=numpy.float64,
    )
    known_future = numpy.vstack(
        (
            numpy.sin(2 * numpy.pi * hours / 24),
            numpy.cos(2 * numpy.pi * hours / 24),
            numpy.sin(2 * numpy.pi * weekdays / 7),
            numpy.cos(2 * numpy.pi * weekdays / 7),
            numpy.isin(hours, (0, 8, 16)).astype(numpy.float64),
        )
    )
    query = CausalQuery(
        decision_timestamp=decision_timestamp,
        targets=log_closes,
        past_only_covariates=past_only,
        past_future_covariates=known_future,
    )
    query.validate()
    return query


def structural_preflight(
    *,
    futures: typing.Union[str, pathlib.Path],
    futures_manifest: typing.Union[str, pathlib.Path],
    spot: typing.Union[str, pathlib.Path],
    spot_manifest: typing.Union[str, pathlib.Path],
    funding: typing.Union[str, pathlib.Path],
) -> dict:
    """Verify the frozen inputs and query geometry without forecasting."""

    paths = {
        "futures_collector": pathlib.Path(futures).resolve(),
        "futures_manifest": pathlib.Path(futures_manifest).resolve(),
        "spot_collector": pathlib.Path(spot).resolve(),
        "spot_manifest": pathlib.Path(spot_manifest).resolve(),
        "funding": pathlib.Path(funding).resolve(),
    }
    artifacts = [_verify_frozen_file(label, path) for label, path in paths.items()]
    for collector_label, manifest_label in (
        ("futures_collector", "futures_manifest"),
        ("spot_collector", "spot_manifest"),
    ):
        manifest = json.loads(paths[manifest_label].read_text(encoding="utf-8"))
        if manifest.get("collector_sha256") != FROZEN_INPUTS[collector_label]["sha256"]:
            raise DataQualityError(f"{manifest_label} does not bind its collector")

    panel = load_aligned_panel(paths["futures_collector"], paths["spot_collector"], paths["funding"])
    origins = eligible_origin_indices(panel)
    if not len(origins):
        raise DataQualityError("preflight produced no daily origin")
    first_query = build_causal_query(panel, int(origins[0]))
    last_query = build_causal_query(panel, int(origins[-1]))
    protocol = frozen_protocol()
    return {
        "schema_version": SCHEMA_VERSION,
        "protocol_version": PROTOCOL_VERSION,
        "status": "ready_for_license_review_and_implementation_lock",
        "protocol_sha256": logical_hash(protocol),
        "artifacts": artifacts,
        "aligned_hourly_rows": len(panel.open_timestamps),
        "first_open_timestamp": int(panel.open_timestamps[0]),
        "last_open_timestamp": int(panel.open_timestamps[-1]),
        "daily_origins": len(origins),
        "first_decision_timestamp": first_query.decision_timestamp,
        "last_decision_timestamp": last_query.decision_timestamp,
        "query_shapes": {
            "targets": list(first_query.targets.shape),
            "past_only_covariates": list(first_query.past_only_covariates.shape),
            "past_future_covariates": list(first_query.past_future_covariates.shape),
            "total_variates": TOTAL_VARIATES,
        },
        "economic_outcomes_read": False,
        "model_forecasts_run": False,
        "license_accepted": False,
        "weights_downloaded": False,
        "credentials_used": False,
        "orders_authorized": False,
        "paper_orders_authorized": False,
        "automatic_promotion": False,
        "results": None,
    }


def validate_license_acceptance(
    acceptance_value: typing.Union[str, pathlib.Path],
) -> dict:
    """Require a user-created record before checkpoint download or loading."""

    path = pathlib.Path(acceptance_value).resolve()
    if not path.is_file():
        raise LicenseAcceptanceRequired(
            "TimesFM 3 weights require explicit local license acceptance"
        )
    payload = json.loads(path.read_text(encoding="utf-8"))
    checks = (
        payload.get("schema_version") == 1,
        payload.get("model_repository") == MODEL_REPOSITORY,
        payload.get("model_revision") == MODEL_REVISION,
        payload.get("license_id") == MODEL_LICENSE_ID,
        payload.get("accepted") is True,
        payload.get("noncommercial_research_only") is True,
        payload.get("production_use") is False,
        payload.get("commercial_use") is False,
        isinstance(payload.get("accepted_by"), str),
        bool(str(payload.get("accepted_by", "")).strip()),
        isinstance(payload.get("accepted_at"), str),
        bool(str(payload.get("accepted_at", "")).strip()),
    )
    if not all(checks):
        raise LicenseAcceptanceRequired("TimesFM 3 license acceptance record differs")
    return payload


def validate_local_checkpoint(
    checkpoint_value: typing.Union[str, pathlib.Path],
    acceptance_value: typing.Union[str, pathlib.Path],
) -> dict:
    """Validate a pinned local checkpoint without importing or executing it."""

    acceptance = validate_license_acceptance(acceptance_value)
    checkpoint = pathlib.Path(checkpoint_value).resolve()
    config_path = checkpoint / "config.json"
    weights_path = checkpoint / "model.safetensors"
    if not checkpoint.is_dir() or not config_path.is_file() or not weights_path.is_file():
        raise DataQualityError("local TimesFM 3 checkpoint is incomplete")
    if weights_path.stat().st_size != MODEL_WEIGHTS_BYTES:
        raise DataQualityError("TimesFM 3 checkpoint size differs")
    if file_hash(weights_path) != MODEL_WEIGHTS_SHA256:
        raise DataQualityError("TimesFM 3 checkpoint SHA-256 differs")
    config = json.loads(config_path.read_text(encoding="utf-8"))
    expected = (
        config.get("input_patch_len") == 32,
        config.get("output_patch_len") == 64,
        config.get("transformer_config", {})
        .get("transformer", {})
        .get("max_variates")
        == MAX_MODEL_VARIATES,
    )
    if not all(expected):
        raise DataQualityError("TimesFM 3 checkpoint configuration differs")
    return {
        "checkpoint": str(checkpoint),
        "weights_sha256": MODEL_WEIGHTS_SHA256,
        "weights_bytes": MODEL_WEIGHTS_BYTES,
        "license_acceptance_sha256": file_hash(pathlib.Path(acceptance_value)),
        "accepted_by": acceptance["accepted_by"],
        "orders_authorized": False,
        "paper_orders_authorized": False,
    }


def runtime_environment() -> dict:
    """Describe the isolated CPU image without loading model weights."""

    import torch

    return {
        "schema_version": SCHEMA_VERSION,
        "python": platform.python_version(),
        "numpy": numpy.__version__,
        "timesfm": importlib.metadata.version("timesfm"),
        "torch": torch.__version__,
        "cuda_available": torch.cuda.is_available(),
        "model_weights_loaded": False,
        "credentials_used": False,
        "orders_authorized": False,
        "paper_orders_authorized": False,
    }


def download_checkpoint(
    checkpoint_value: typing.Union[str, pathlib.Path],
    acceptance_value: typing.Union[str, pathlib.Path],
) -> dict:
    """Download the pinned checkpoint only after explicit license acceptance."""

    validate_license_acceptance(acceptance_value)
    checkpoint = pathlib.Path(checkpoint_value).resolve()
    checkpoint.mkdir(parents=True, exist_ok=True)
    from huggingface_hub import snapshot_download

    snapshot_download(
        repo_id=MODEL_REPOSITORY,
        revision=MODEL_REVISION,
        local_dir=str(checkpoint),
        allow_patterns=("LICENSE", "README.md", "config.json", "model.safetensors"),
        token=False,
    )
    return validate_local_checkpoint(checkpoint, acceptance_value)


def write_implementation_lock(
    *,
    protocol_value: typing.Union[str, pathlib.Path],
    preflight_value: typing.Union[str, pathlib.Path],
    environment_value: typing.Union[str, pathlib.Path],
    artifacts: dict[str, typing.Union[str, pathlib.Path]],
    image_id: str,
    output_value: typing.Union[str, pathlib.Path],
) -> pathlib.Path:
    """Freeze executable inputs before the first model forecast or outcome."""

    protocol_path = pathlib.Path(protocol_value).resolve()
    preflight_path = pathlib.Path(preflight_value).resolve()
    environment_path = pathlib.Path(environment_value).resolve()
    output = pathlib.Path(output_value).resolve()
    expected_protocol = frozen_protocol()
    protocol = json.loads(protocol_path.read_text(encoding="utf-8"))
    preflight = json.loads(preflight_path.read_text(encoding="utf-8"))
    environment = json.loads(environment_path.read_text(encoding="utf-8"))
    if protocol != {
        **expected_protocol,
        "protocol_sha256": logical_hash(expected_protocol),
    }:
        raise DataQualityError("TimesFM 3 persisted protocol differs")
    preflight_checks = (
        preflight.get("protocol_sha256") == protocol["protocol_sha256"],
        preflight.get("economic_outcomes_read") is False,
        preflight.get("model_forecasts_run") is False,
        preflight.get("license_accepted") is False,
        preflight.get("weights_downloaded") is False,
        preflight.get("orders_authorized") is False,
        preflight.get("paper_orders_authorized") is False,
        preflight.get("results") is None,
    )
    if not all(preflight_checks):
        raise DataQualityError("TimesFM 3 preflight is not result-free")
    environment_checks = (
        environment.get("timesfm") == TIMESFM_PACKAGE_VERSION,
        environment.get("torch") == TORCH_CPU_VERSION,
        environment.get("cuda_available") is False,
        environment.get("model_weights_loaded") is False,
        environment.get("credentials_used") is False,
        environment.get("orders_authorized") is False,
        environment.get("paper_orders_authorized") is False,
    )
    if not all(environment_checks):
        raise DataQualityError("TimesFM 3 runtime environment differs")
    if not image_id.startswith("sha256:") or len(image_id) != 71:
        raise DataQualityError("Docker image ID is not a SHA-256 identifier")
    source_artifacts = []
    for label, value in sorted(artifacts.items()):
        path = pathlib.Path(value).resolve()
        if not path.is_file():
            raise FileNotFoundError(path)
        source_artifacts.append(
            {
                "label": label,
                "path": str(path),
                "bytes": path.stat().st_size,
                "sha256": file_hash(path),
            }
        )
    created_at = datetime.datetime.now(datetime.timezone.utc).isoformat()
    if output.exists():
        created_at = json.loads(output.read_text(encoding="utf-8")).get(
            "created_at", created_at
        )
    payload = {
        "schema_version": SCHEMA_VERSION,
        "protocol_version": PROTOCOL_VERSION,
        "created_at": created_at,
        "status": "implementation_frozen_before_model_or_economic_outcomes",
        "protocol_sha256": protocol["protocol_sha256"],
        "protocol_file_sha256": file_hash(protocol_path),
        "preflight_file_sha256": file_hash(preflight_path),
        "environment_file_sha256": file_hash(environment_path),
        "docker_image_id": image_id,
        "source_artifacts": source_artifacts,
        "economic_outcomes_read_before_lock": False,
        "model_forecasts_run_before_lock": False,
        "license_accepted_before_lock": False,
        "weights_downloaded_before_lock": False,
        "results_existing_before_lock": False,
        "credentials_used": False,
        "orders_authorized": False,
        "paper_orders_authorized": False,
        "automatic_promotion": False,
        "results": None,
    }
    payload["content_sha256"] = logical_hash(payload)
    if output.exists():
        persisted = json.loads(output.read_text(encoding="utf-8"))
        if persisted != payload:
            raise DataQualityError("existing TimesFM 3 implementation lock differs")
        return output
    _atomic_json(output, payload)
    return output


def create_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Offline TimesFM 3 research scaffold; cannot place orders."
    )
    commands = parser.add_subparsers(dest="command", required=True)
    freeze = commands.add_parser("freeze-protocol")
    freeze.add_argument("--output", required=True)
    preflight = commands.add_parser("preflight")
    preflight.add_argument("--futures", required=True)
    preflight.add_argument("--futures-manifest", required=True)
    preflight.add_argument("--spot", required=True)
    preflight.add_argument("--spot-manifest", required=True)
    preflight.add_argument("--funding", required=True)
    preflight.add_argument("--output", required=True)
    checkpoint = commands.add_parser("validate-checkpoint")
    checkpoint.add_argument("--checkpoint", required=True)
    checkpoint.add_argument("--license-acceptance", required=True)
    checkpoint.add_argument("--output", required=True)
    environment = commands.add_parser("environment-report")
    environment.add_argument("--output", required=True)
    download = commands.add_parser("download-checkpoint")
    download.add_argument("--checkpoint", required=True)
    download.add_argument("--license-acceptance", required=True)
    download.add_argument("--output", required=True)
    lock = commands.add_parser("freeze-implementation")
    lock.add_argument("--protocol", required=True)
    lock.add_argument("--preflight", required=True)
    lock.add_argument("--environment", required=True)
    lock.add_argument("--artifact", action="append", default=[])
    lock.add_argument("--image-id", required=True)
    lock.add_argument("--output", required=True)
    return parser


def main(argv: typing.Optional[list[str]] = None) -> int:
    arguments = create_parser().parse_args(argv)
    if arguments.command == "freeze-protocol":
        path = write_protocol(arguments.output)
        print(json.dumps({"protocol": str(path)}, sort_keys=True))
        return 0
    if arguments.command == "preflight":
        report = structural_preflight(
            futures=arguments.futures,
            futures_manifest=arguments.futures_manifest,
            spot=arguments.spot,
            spot_manifest=arguments.spot_manifest,
            funding=arguments.funding,
        )
        output = pathlib.Path(arguments.output).resolve()
        _atomic_json(output, report)
        print(json.dumps(report, sort_keys=True))
        return 0
    if arguments.command == "environment-report":
        report = runtime_environment()
        output = pathlib.Path(arguments.output).resolve()
        _atomic_json(output, report)
        print(json.dumps(report, sort_keys=True))
        return 0
    if arguments.command in {"validate-checkpoint", "download-checkpoint"}:
        function = (
            download_checkpoint
            if arguments.command == "download-checkpoint"
            else validate_local_checkpoint
        )
        report = function(arguments.checkpoint, arguments.license_acceptance)
        output = pathlib.Path(arguments.output).resolve()
        _atomic_json(output, report)
        print(json.dumps(report, sort_keys=True))
        return 0
    artifact_values = {}
    for value in arguments.artifact:
        if "=" not in value:
            raise ValueError("artifacts must use label=path")
        label, path = value.split("=", 1)
        if not label or label in artifact_values:
            raise ValueError("artifact labels must be unique and non-empty")
        artifact_values[label] = path
    path = write_implementation_lock(
        protocol_value=arguments.protocol,
        preflight_value=arguments.preflight,
        environment_value=arguments.environment,
        artifacts=artifact_values,
        image_id=arguments.image_id,
        output_value=arguments.output,
    )
    print(json.dumps({"implementation_lock": str(path)}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
