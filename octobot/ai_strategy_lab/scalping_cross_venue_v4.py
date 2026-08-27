"""Frozen cross-venue BTC lead/lag research protocol V4.

The module is deliberately research-only.  It downloads checksummed public
Binance USD-M aggregate trades, aligns them causally to the already frozen
KuCoin pre-test decisions, and evaluates one interpretable lead/lag rule.  It
does not import an exchange trading API and cannot create orders.
"""

from __future__ import annotations

import csv
import dataclasses
import datetime
import hashlib
import io
import json
import math
import pathlib
import shutil
import typing
import urllib.request
import zipfile

import numpy

from octobot.ai_strategy_lab import scalping_strategy_search as v1
from octobot.ai_strategy_lab import scalping_strategy_search_v2 as v2


SCHEMA_VERSION = 1
PROTOCOL_VERSION = "btc_futures_cross_venue_lead_lag_v4"
PREREGISTRATION_DATE = "2026-08-27"
PARENT_PROTOCOL_SHA256 = (
    "22d0872fc679f1b9f01110409251a0a8dd792fa4844670f67c3da703c7744a04"
)
PARENT_DATASET_SHA256 = (
    "6b9f69908c603d66608ea34cea1d89d5c69c1e8b8fb081ed0cb1b1b14524a159"
)
PARENT_REPORT_SHA256 = (
    "c298856cf1b42c331bbc34e06bb12c6cb7b059708152746683297401a26243cb"
)
SOURCE_START = v1.SOURCE_START
DEVELOPMENT_END = v2.DEVELOPMENT_END
DIAGNOSTIC_CONFIRMATION_END = v2.DIAGNOSTIC_CONFIRMATION_END
LOCKED_TEST_END = v2.LOCKED_TEST_END
BINANCE_SYMBOL = "BTCUSDT"
ARCHIVE_START_DATE = datetime.date(2026, 7, 23)
ARCHIVE_END_DATE = datetime.date(2026, 8, 19)
ARCHIVE_URL_TEMPLATE = (
    "https://data.binance.vision/data/futures/um/daily/aggTrades/"
    "{symbol}/{symbol}-aggTrades-{date}.zip"
)
PRIMARY_AVAILABILITY_DELAY_SECONDS = 1
DELAY_STRESS_SECONDS = 2
SIGNAL_WINDOW_SECONDS = 5
IMPULSE_QUANTILE = 0.99
MINIMUM_DIRECTIONAL_LAG_BPS = 1.0
MINIMUM_DIRECTIONAL_FLOW_IMBALANCE = 0.10
MINIMUM_BINANCE_TRADES = 3
CONFIGURATION_INDEX = 0
CONFIGURATION = v2.CONFIGURATIONS[CONFIGURATION_INDEX]
DEVELOPMENT_MINIMUM_TRADES = 50
CONFIRMATION_MINIMUM_TRADES = 10


def _json_hash(value: object) -> str:
    return hashlib.sha256(
        json.dumps(value, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()


def _sha256(path: pathlib.Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _atomic_json(path: pathlib.Path, value: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(
        json.dumps(v1._json_safe(value), indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    temporary.replace(path)


def frozen_protocol() -> dict:
    """Return the immutable, result-free V4 protocol."""

    return {
        "schema_version": SCHEMA_VERSION,
        "protocol_version": PROTOCOL_VERSION,
        "preregistered_on": PREREGISTRATION_DATE,
        "status": "result_free_evaluation_protocol",
        "research_only": True,
        "public_data_only": True,
        "credentials_used": False,
        "orders_authorized": False,
        "paper_orders_authorized": False,
        "automatic_promotion": False,
        "parent_rejection": {
            "protocol_sha256": PARENT_PROTOCOL_SHA256,
            "dataset_sha256": PARENT_DATASET_SHA256,
            "report_sha256": PARENT_REPORT_SHA256,
            "lesson_used": (
                "single-venue KuCoin aggregate and queue-flow features did "
                "not cover taker costs; a new hypothesis must change the "
                "information set"
            ),
            "economic_outcomes_reused_without_change": True,
            "parent_thresholds_not_retuned": True,
        },
        "hypothesis": {
            "name": "binance_impulse_kucoin_lag_continuation",
            "statement": (
                "an extreme five-second Binance USD-M taker impulse that is "
                "not yet fully reflected in KuCoin, and whose signed trade "
                "flow agrees with its direction, predicts continuation large "
                "enough to overcome a KuCoin taker round trip"
            ),
            "direction_symmetric": True,
            "one_rule_only": True,
        },
        "source": {
            "kucoin_parent_dataset_sha256": PARENT_DATASET_SHA256,
            "binance_market": "USD-M futures",
            "binance_symbol": BINANCE_SYMBOL,
            "binance_archive": "daily aggregate trades",
            "binance_archive_start": ARCHIVE_START_DATE.isoformat(),
            "binance_archive_end": ARCHIVE_END_DATE.isoformat(),
            "checksum_required_for_every_archive": True,
            "source_clock": "Binance aggregate-trade transaction time",
            "primary_availability_delay_seconds": (
                PRIMARY_AVAILABILITY_DELAY_SECONDS
            ),
            "delay_stress_seconds": DELAY_STRESS_SECONDS,
            "future_or_locked_rows_excluded": True,
        },
        "signal": {
            "decision_stride_seconds": v2.DECISION_STRIDE_SECONDS,
            "window_seconds": SIGNAL_WINDOW_SECONDS,
            "impulse_threshold": (
                "99th percentile of absolute five-second Binance log return "
                "estimated only on each training fold"
            ),
            "minimum_directional_binance_minus_kucoin_return_bps": (
                MINIMUM_DIRECTIONAL_LAG_BPS
            ),
            "minimum_directional_binance_flow_imbalance": (
                MINIMUM_DIRECTIONAL_FLOW_IMBALANCE
            ),
            "minimum_binance_aggregate_trades": MINIMUM_BINANCE_TRADES,
            "direction": "sign of the five-second Binance return",
            "one_trade_at_a_time": True,
            "selection_candidates": 1,
        },
        "economics": {
            "configuration": CONFIGURATION,
            "entry_and_outcome_source": "unchanged frozen KuCoin V2 labels",
            "primary_entry_latency_ms": v2.PRIMARY_LATENCY_MS,
            "stress_entry_latency_ms": v2.STRESS_LATENCY_MS,
            "fee_bps_per_fill": v2.FEE_BPS_PER_FILL,
            "slippage_bps_per_fill": v2.SLIPPAGE_BPS_PER_FILL,
            "fills": 2,
            "position_fraction": v2.POSITION_FRACTION,
            "stress_cost_multiplier": v2.COST_STRESS_MULTIPLIER,
            "maker_fill_assumptions": False,
        },
        "validation": {
            "development": [SOURCE_START, DEVELOPMENT_END],
            "walk_forward_folds": v2.WALK_FORWARD_FOLDS,
            "purge_embargo_seconds": 900,
            "diagnostic_confirmation": [
                DEVELOPMENT_END,
                DIAGNOSTIC_CONFIRMATION_END,
            ],
            "diagnostic_confirmation_is_not_pristine": True,
            "locked_final_test": [
                DIAGNOSTIC_CONFIRMATION_END,
                LOCKED_TEST_END,
            ],
            "locked_test_policy": (
                "remain sealed unless every development and confirmation "
                "gate passes; no locked Binance archive is downloaded first"
            ),
        },
        "development_gate": {
            "minimum_trades": DEVELOPMENT_MINIMUM_TRADES,
            "minimum_profit_factor": 1.25,
            "maximum_drawdown_pct": 5.0,
            "minimum_positive_operating_days_pct": 55.0,
            "minimum_positive_folds": 4,
            "long_contribution_non_negative": True,
            "short_contribution_non_negative": True,
            "two_second_delay_and_doubled_costs_positive": True,
            "two_second_delay_profit_factor": 1.05,
        },
        "confirmation_gate": {
            "minimum_trades": CONFIRMATION_MINIMUM_TRADES,
            "minimum_profit_factor": 1.25,
            "maximum_drawdown_pct": 5.0,
            "minimum_positive_operating_days_pct": 55.0,
            "long_contribution_non_negative": True,
            "short_contribution_non_negative": True,
            "two_second_delay_and_doubled_costs_positive": True,
            "two_second_delay_profit_factor": 1.05,
        },
        "multiple_testing_disclosure": (
            "one signal window, one quantile, one lag threshold, one flow "
            "threshold and one unchanged economic configuration are tested"
        ),
        "promotion_consequence": (
            "even a complete pass permits only a manually approved, "
            "orderless shadow; it never authorizes paper or real orders"
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
            raise ValueError("persisted cross-venue V4 protocol differs")
        return persisted
    _atomic_json(path, payload)
    return payload


def _dates(start: datetime.date, end: datetime.date) -> typing.Iterator[datetime.date]:
    current = start
    while current <= end:
        yield current
        current += datetime.timedelta(days=1)


def _download(url: str, destination: pathlib.Path) -> None:
    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary = destination.with_suffix(destination.suffix + ".tmp")
    request = urllib.request.Request(
        url, headers={"User-Agent": "octobot-cross-venue-research/1"}
    )
    with urllib.request.urlopen(request, timeout=60) as response, temporary.open(
        "wb"
    ) as output:
        shutil.copyfileobj(response, output, length=1024 * 1024)
    temporary.replace(destination)


def fetch_pretest_archives(
    *,
    protocol_value: typing.Union[str, pathlib.Path],
    cache_root_value: typing.Union[str, pathlib.Path],
    manifest_value: typing.Union[str, pathlib.Path],
    progress: typing.Callable[[str], None] | None = None,
) -> dict:
    """Fetch and checksum only the pre-test Binance daily archives."""

    progress = progress or (lambda _message: None)
    protocol = write_or_verify_protocol(protocol_value)
    cache_root = pathlib.Path(cache_root_value).resolve()
    artifacts = []
    for day in _dates(ARCHIVE_START_DATE, ARCHIVE_END_DATE):
        date = day.isoformat()
        url = ARCHIVE_URL_TEMPLATE.format(symbol=BINANCE_SYMBOL, date=date)
        filename = url.rsplit("/", 1)[-1]
        archive = cache_root / filename
        checksum_file = cache_root / f"{filename}.CHECKSUM"
        if not archive.is_file():
            progress(f"download {filename}")
            _download(url, archive)
        if not checksum_file.is_file():
            _download(url + ".CHECKSUM", checksum_file)
        checksum_parts = checksum_file.read_text(encoding="utf-8").split()
        if not checksum_parts or len(checksum_parts[0]) != 64:
            raise ValueError(f"invalid Binance checksum for {filename}")
        expected = checksum_parts[0].lower()
        actual = _sha256(archive)
        if actual != expected:
            raise ValueError(f"Binance checksum mismatch for {filename}")
        artifacts.append(
            {
                "date": date,
                "url": url,
                "path": str(archive),
                "bytes": archive.stat().st_size,
                "sha256": actual,
                "checksum_path": str(checksum_file),
                "checksum_sha256": _sha256(checksum_file),
            }
        )
    manifest = {
        "schema_version": SCHEMA_VERSION,
        "mode": "checksummed_binance_pretest_aggtrades",
        "created_at": datetime.datetime.now(datetime.timezone.utc).isoformat(),
        "research_only": True,
        "public_data_only": True,
        "credentials_used": False,
        "orders_authorized": False,
        "paper_orders_authorized": False,
        "automatic_promotion": False,
        "protocol_sha256": protocol["protocol_sha256"],
        "symbol": BINANCE_SYMBOL,
        "start_date": ARCHIVE_START_DATE.isoformat(),
        "end_date": ARCHIVE_END_DATE.isoformat(),
        "locked_test_downloaded": False,
        "artifacts": artifacts,
    }
    manifest["content_sha256"] = _json_hash(manifest)
    _atomic_json(pathlib.Path(manifest_value).resolve(), manifest)
    return manifest


def _timestamp_second(value: str) -> int:
    timestamp = int(value)
    if timestamp >= 100_000_000_000_000_000:
        return timestamp // 1_000_000_000
    if timestamp >= 100_000_000_000_000:
        return timestamp // 1_000_000
    if timestamp >= 100_000_000_000:
        return timestamp // 1_000
    raise ValueError("Binance aggregate-trade timestamp is implausible")


def _header_indices(row: list[str]) -> dict[str, int] | None:
    normalized = {
        value.strip().lower().replace(" ", "_"): index
        for index, value in enumerate(row)
    }
    if not any("trade" in value and "id" in value for value in normalized):
        return None

    def locate(*names: str) -> int:
        for name in names:
            if name in normalized:
                return normalized[name]
        raise ValueError(f"Binance archive header lacks {names[0]}")

    return {
        "price": locate("price", "p"),
        "quantity": locate("quantity", "qty", "q"),
        "timestamp": locate("transact_time", "timestamp", "time", "t"),
        "buyer_maker": locate(
            "is_buyer_maker", "was_the_buyer_the_maker", "m"
        ),
    }


def _row_values(
    row: list[str], indices: dict[str, int] | None
) -> tuple[float, float, int, bool]:
    if indices is None:
        if len(row) < 7:
            raise ValueError("Binance aggregate-trade row is incomplete")
        price_value, quantity_value, timestamp_value, maker_value = (
            row[1],
            row[2],
            row[5],
            row[6],
        )
    else:
        price_value = row[indices["price"]]
        quantity_value = row[indices["quantity"]]
        timestamp_value = row[indices["timestamp"]]
        maker_value = row[indices["buyer_maker"]]
    price = float(price_value)
    quantity = float(quantity_value)
    if not math.isfinite(price) or price <= 0 or not math.isfinite(quantity) or quantity <= 0:
        raise ValueError("Binance aggregate-trade price or quantity is invalid")
    normalized_maker = maker_value.strip().lower()
    if normalized_maker not in {"true", "false"}:
        raise ValueError("Binance buyer-maker flag is invalid")
    return (
        price,
        quantity,
        _timestamp_second(timestamp_value),
        normalized_maker == "true",
    )


@dataclasses.dataclass
class CrossVenueDataset:
    timestamps: numpy.ndarray
    binance_return_bps: numpy.ndarray
    kucoin_return_bps: numpy.ndarray
    binance_flow_imbalance: numpy.ndarray
    binance_trade_count: numpy.ndarray
    delayed_binance_return_bps: numpy.ndarray
    delayed_binance_flow_imbalance: numpy.ndarray
    delayed_binance_trade_count: numpy.ndarray
    primary_long_return: numpy.ndarray
    primary_short_return: numpy.ndarray
    primary_long_exit: numpy.ndarray
    primary_short_exit: numpy.ndarray
    stress_long_return: numpy.ndarray
    stress_short_return: numpy.ndarray
    stress_long_exit: numpy.ndarray
    stress_short_exit: numpy.ndarray

    def validate(self) -> None:
        rows = len(self.timestamps)
        if not rows or numpy.any(numpy.diff(self.timestamps) <= 0):
            raise ValueError("cross-venue timestamps are empty or unordered")
        if int(self.timestamps[-1]) >= v1._iso_timestamp(
            DIAGNOSTIC_CONFIRMATION_END
        ):
            raise ValueError("cross-venue dataset enters the locked block")
        for field in dataclasses.fields(self):
            values = getattr(self, field.name)
            if values.shape != (rows,):
                raise ValueError(f"cross-venue field {field.name} is misaligned")
            if field.name not in {
                "primary_long_exit",
                "primary_short_exit",
                "stress_long_exit",
                "stress_short_exit",
            } and not numpy.all(numpy.isfinite(values)):
                raise ValueError(f"cross-venue field {field.name} is not finite")

    def save(self, path_value: typing.Union[str, pathlib.Path]) -> dict:
        self.validate()
        path = pathlib.Path(path_value).resolve()
        path.parent.mkdir(parents=True, exist_ok=True)
        temporary = path.with_suffix(path.suffix + ".tmp")
        with temporary.open("wb") as stream:
            numpy.savez_compressed(
                stream,
                schema_version=numpy.asarray([SCHEMA_VERSION]),
                protocol_version=numpy.asarray([PROTOCOL_VERSION]),
                protocol_sha256=numpy.asarray([_json_hash(frozen_protocol())]),
                parent_dataset_sha256=numpy.asarray([PARENT_DATASET_SHA256]),
                **{
                    field.name: getattr(self, field.name)
                    for field in dataclasses.fields(self)
                },
            )
        temporary.replace(path)
        return {
            "path": str(path),
            "bytes": path.stat().st_size,
            "sha256": _sha256(path),
        }

    @classmethod
    def load(
        cls,
        path_value: typing.Union[str, pathlib.Path],
        *,
        expected_sha256: str | None = None,
    ) -> "CrossVenueDataset":
        path = pathlib.Path(path_value).resolve()
        if expected_sha256 and _sha256(path) != expected_sha256:
            raise ValueError("cross-venue dataset hash differs")
        with numpy.load(path, allow_pickle=False) as values:
            if int(values["schema_version"][0]) != SCHEMA_VERSION:
                raise ValueError("unsupported cross-venue dataset schema")
            if str(values["protocol_version"][0]) != PROTOCOL_VERSION:
                raise ValueError("cross-venue dataset protocol differs")
            if str(values["protocol_sha256"][0]) != _json_hash(
                frozen_protocol()
            ):
                raise ValueError("cross-venue dataset protocol hash differs")
            if str(values["parent_dataset_sha256"][0]) != PARENT_DATASET_SHA256:
                raise ValueError("cross-venue parent dataset differs")
            dataset = cls(
                **{
                    field.name: values[field.name].copy()
                    for field in dataclasses.fields(cls)
                }
            )
        dataset.validate()
        return dataset


def _rolling_sum(values: numpy.ndarray, window: int) -> numpy.ndarray:
    cumulative = numpy.concatenate(
        (numpy.asarray([0.0]), numpy.cumsum(values, dtype=numpy.float64))
    )
    output = numpy.zeros(len(values), dtype=numpy.float64)
    output[window - 1 :] = cumulative[window:] - cumulative[:-window]
    return output


def _features_at_delay(
    *,
    candidate_seconds: numpy.ndarray,
    dense_start: int,
    prices: numpy.ndarray,
    buy_quantity: numpy.ndarray,
    sell_quantity: numpy.ndarray,
    trade_count: numpy.ndarray,
    delay_seconds: int,
) -> tuple[numpy.ndarray, numpy.ndarray, numpy.ndarray]:
    effective = candidate_seconds - delay_seconds - dense_start
    previous = effective - SIGNAL_WINDOW_SECONDS
    if numpy.any(previous < 0) or numpy.any(effective >= len(prices)):
        raise ValueError("Binance feature lookup exceeds dense archive")
    returns = numpy.log(prices[effective] / prices[previous]) * 10_000.0
    buy = _rolling_sum(buy_quantity, SIGNAL_WINDOW_SECONDS)[effective]
    sell = _rolling_sum(sell_quantity, SIGNAL_WINDOW_SECONDS)[effective]
    total = buy + sell
    imbalance = numpy.divide(
        buy - sell,
        total,
        out=numpy.zeros(len(effective), dtype=numpy.float64),
        where=total > 0,
    )
    counts = _rolling_sum(trade_count, SIGNAL_WINDOW_SECONDS)[effective]
    return returns, imbalance, counts


def build_pretest_dataset(
    *,
    parent_dataset_value: typing.Union[str, pathlib.Path],
    parent_manifest_value: typing.Union[str, pathlib.Path],
    archive_manifest_value: typing.Union[str, pathlib.Path],
    protocol_value: typing.Union[str, pathlib.Path],
    output_value: typing.Union[str, pathlib.Path],
    progress: typing.Callable[[str], None] | None = None,
) -> dict:
    progress = progress or (lambda _message: None)
    protocol = write_or_verify_protocol(protocol_value)
    parent_manifest_path = pathlib.Path(parent_manifest_value).resolve()
    parent_manifest = json.loads(parent_manifest_path.read_text(encoding="utf-8"))
    if parent_manifest.get("artifact", {}).get("sha256") != PARENT_DATASET_SHA256:
        raise ValueError("cross-venue V4 parent dataset differs")
    if parent_manifest.get("locked_test_materialized") is not False:
        raise ValueError("cross-venue V4 parent contains locked data")
    parent = v2.ScalpingV2Dataset.load(
        parent_dataset_value, expected_sha256=PARENT_DATASET_SHA256
    )
    archive_manifest_path = pathlib.Path(archive_manifest_value).resolve()
    archive_manifest = json.loads(
        archive_manifest_path.read_text(encoding="utf-8")
    )
    if archive_manifest.get("protocol_sha256") != protocol["protocol_sha256"]:
        raise ValueError("Binance archives belong to another protocol")
    if archive_manifest.get("locked_test_downloaded") is not False:
        raise ValueError("Binance archive manifest enters the locked block")
    dense_start = v1._iso_timestamp(SOURCE_START) - 120
    dense_end = v1._iso_timestamp(DIAGNOSTIC_CONFIRMATION_END)
    length = dense_end - dense_start
    prices = numpy.zeros(length, dtype=numpy.float64)
    buy_quantity = numpy.zeros(length, dtype=numpy.float64)
    sell_quantity = numpy.zeros(length, dtype=numpy.float64)
    trade_count = numpy.zeros(length, dtype=numpy.float64)
    parsed_rows = 0
    included_rows = 0
    first_trade_second: int | None = None
    last_trade_second: int | None = None
    for artifact in archive_manifest["artifacts"]:
        archive = pathlib.Path(artifact["path"]).resolve()
        if _sha256(archive) != artifact["sha256"]:
            raise ValueError(f"cached Binance archive changed: {archive.name}")
        progress(f"parse {archive.name}")
        with zipfile.ZipFile(archive) as compressed:
            members = [name for name in compressed.namelist() if not name.endswith("/")]
            if len(members) != 1:
                raise ValueError(f"unexpected members in {archive.name}")
            with compressed.open(members[0]) as raw, io.TextIOWrapper(
                raw, encoding="utf-8", newline=""
            ) as text:
                reader = csv.reader(text)
                indices: dict[str, int] | None = None
                first = True
                for row in reader:
                    if not row:
                        continue
                    if first:
                        first = False
                        indices = _header_indices(row)
                        if indices is not None:
                            continue
                    price, quantity, second, buyer_maker = _row_values(
                        row, indices
                    )
                    parsed_rows += 1
                    if second < dense_start or second >= dense_end:
                        continue
                    index = second - dense_start
                    prices[index] = price
                    if buyer_maker:
                        sell_quantity[index] += quantity
                    else:
                        buy_quantity[index] += quantity
                    trade_count[index] += 1
                    included_rows += 1
                    first_trade_second = (
                        second
                        if first_trade_second is None
                        else min(first_trade_second, second)
                    )
                    last_trade_second = (
                        second
                        if last_trade_second is None
                        else max(last_trade_second, second)
                    )
    observed = numpy.flatnonzero(prices > 0)
    required_last_index = (
        int(parent.timestamps[-1])
        - PRIMARY_AVAILABILITY_DELAY_SECONDS
        - dense_start
    )
    if (
        not len(observed)
        or observed[0] > 60
        or observed[-1] < required_last_index
    ):
        raise ValueError("Binance archive does not cover the required pre-test")
    prices[: observed[0]] = prices[observed[0]]
    last_observed_index = numpy.maximum.accumulate(
        numpy.where(prices > 0, numpy.arange(length), 0)
    )
    prices[:] = prices[last_observed_index]
    candidate_seconds = parent.timestamps.astype(numpy.int64)
    primary_return, primary_flow, primary_count = _features_at_delay(
        candidate_seconds=candidate_seconds,
        dense_start=dense_start,
        prices=prices,
        buy_quantity=buy_quantity,
        sell_quantity=sell_quantity,
        trade_count=trade_count,
        delay_seconds=PRIMARY_AVAILABILITY_DELAY_SECONDS,
    )
    delayed_return, delayed_flow, delayed_count = _features_at_delay(
        candidate_seconds=candidate_seconds,
        dense_start=dense_start,
        prices=prices,
        buy_quantity=buy_quantity,
        sell_quantity=sell_quantity,
        trade_count=trade_count,
        delay_seconds=DELAY_STRESS_SECONDS,
    )
    kucoin_return_index = v1.FEATURE_NAMES.index(
        "w5_directional_mid_return_bps"
    )
    view = parent.view(CONFIGURATION_INDEX)
    dataset = CrossVenueDataset(
        timestamps=parent.timestamps.copy(),
        binance_return_bps=primary_return.astype(numpy.float32),
        kucoin_return_bps=parent.features[:, kucoin_return_index].astype(
            numpy.float32
        ),
        binance_flow_imbalance=primary_flow.astype(numpy.float32),
        binance_trade_count=primary_count.astype(numpy.float32),
        delayed_binance_return_bps=delayed_return.astype(numpy.float32),
        delayed_binance_flow_imbalance=delayed_flow.astype(numpy.float32),
        delayed_binance_trade_count=delayed_count.astype(numpy.float32),
        **{
            name: getattr(view, name).copy()
            for name in (
                "primary_long_return",
                "primary_short_return",
                "primary_long_exit",
                "primary_short_exit",
                "stress_long_return",
                "stress_short_return",
                "stress_long_exit",
                "stress_short_exit",
            )
        },
    )
    artifact = dataset.save(output_value)
    manifest = {
        "schema_version": SCHEMA_VERSION,
        "mode": "pretest_cross_venue_v4_dataset",
        "created_at": datetime.datetime.now(datetime.timezone.utc).isoformat(),
        "research_only": True,
        "orders_authorized": False,
        "paper_orders_authorized": False,
        "automatic_promotion": False,
        "protocol_sha256": protocol["protocol_sha256"],
        "parent_dataset_sha256": PARENT_DATASET_SHA256,
        "parent_manifest_sha256": _sha256(parent_manifest_path),
        "archive_manifest_sha256": _sha256(archive_manifest_path),
        "archive_content_sha256": archive_manifest["content_sha256"],
        "locked_test_materialized": False,
        "rows": len(dataset.timestamps),
        "first_decision": datetime.datetime.fromtimestamp(
            int(dataset.timestamps[0]), datetime.timezone.utc
        ).isoformat(),
        "last_decision": datetime.datetime.fromtimestamp(
            int(dataset.timestamps[-1]), datetime.timezone.utc
        ).isoformat(),
        "parsed_binance_rows": parsed_rows,
        "included_binance_rows": included_rows,
        "first_binance_trade": datetime.datetime.fromtimestamp(
            typing.cast(int, first_trade_second), datetime.timezone.utc
        ).isoformat(),
        "last_binance_trade": datetime.datetime.fromtimestamp(
            typing.cast(int, last_trade_second), datetime.timezone.utc
        ).isoformat(),
        "artifact": artifact,
    }
    manifest_path = pathlib.Path(output_value).resolve().with_suffix(
        ".manifest.json"
    )
    _atomic_json(manifest_path, manifest)
    return {**manifest, "manifest": str(manifest_path)}


def _simulate(
    dataset: CrossVenueDataset,
    indices: numpy.ndarray,
    threshold_bps: float,
    *,
    stress: bool,
) -> dict[str, numpy.ndarray]:
    binance_returns = (
        dataset.delayed_binance_return_bps
        if stress
        else dataset.binance_return_bps
    )
    flows = (
        dataset.delayed_binance_flow_imbalance
        if stress
        else dataset.binance_flow_imbalance
    )
    counts = (
        dataset.delayed_binance_trade_count
        if stress
        else dataset.binance_trade_count
    )
    prefix = "stress" if stress else "primary"
    selected_rows = []
    selected_directions = []
    selected_returns = []
    selected_exits = []
    selected_strength = []
    free_after = -1
    for row in indices:
        timestamp = int(dataset.timestamps[row])
        if timestamp <= free_after:
            continue
        impulse = float(binance_returns[row])
        if abs(impulse) < threshold_bps or counts[row] < MINIMUM_BINANCE_TRADES:
            continue
        direction = 1 if impulse > 0 else -1
        directional_lag = direction * (
            impulse - float(dataset.kucoin_return_bps[row])
        )
        directional_flow = direction * float(flows[row])
        if (
            directional_lag < MINIMUM_DIRECTIONAL_LAG_BPS
            or directional_flow < MINIMUM_DIRECTIONAL_FLOW_IMBALANCE
        ):
            continue
        side = "long" if direction == 1 else "short"
        trade_return = float(getattr(dataset, f"{prefix}_{side}_return")[row])
        exit_timestamp = int(getattr(dataset, f"{prefix}_{side}_exit")[row])
        if exit_timestamp <= timestamp:
            raise ValueError("cross-venue exit is not after the decision")
        selected_rows.append(int(row))
        selected_directions.append(direction)
        selected_returns.append(trade_return)
        selected_exits.append(exit_timestamp)
        selected_strength.append(abs(impulse))
        free_after = exit_timestamp
    return {
        "rows": numpy.asarray(selected_rows, dtype=numpy.int64),
        "directions": numpy.asarray(selected_directions, dtype=numpy.int8),
        "instrument_returns": numpy.asarray(
            selected_returns, dtype=numpy.float64
        ),
        "exit_timestamps": numpy.asarray(selected_exits, dtype=numpy.int64),
        "probabilities": numpy.asarray(selected_strength, dtype=numpy.float64),
    }


def _threshold(dataset: CrossVenueDataset, indices: numpy.ndarray) -> float:
    values = numpy.abs(dataset.binance_return_bps[indices])
    values = values[
        dataset.binance_trade_count[indices] >= MINIMUM_BINANCE_TRADES
    ]
    if len(values) < 1_000:
        raise ValueError("cross-venue training block is too small")
    return float(numpy.quantile(values, IMPULSE_QUANTILE))


def _gate(
    primary: dict,
    stress: dict,
    *,
    minimum_trades: int,
    positive_folds: int | None = None,
    valid_folds: int | None = None,
) -> dict:
    checks = {
        "minimum_trades": primary["trades"] >= minimum_trades,
        "profit_factor": primary["profit_factor"] >= 1.25,
        "maximum_drawdown": primary["max_drawdown"] <= 0.05,
        "positive_operating_days": (
            primary["positive_operating_days_pct"] >= 55.0
        ),
        "long_non_negative": (
            primary["by_direction"]["long"]["total_return"] >= 0.0
        ),
        "short_non_negative": (
            primary["by_direction"]["short"]["total_return"] >= 0.0
        ),
        "delay_and_cost_stress_positive": stress["total_return"] > 0.0,
        "delay_and_cost_stress_profit_factor": (
            stress["profit_factor"] >= 1.05
        ),
    }
    if positive_folds is not None:
        checks["positive_folds"] = positive_folds >= 4
    if valid_folds is not None:
        checks["all_folds_fitted"] = valid_folds == v2.WALK_FORWARD_FOLDS
    return {
        "passed": all(checks.values()),
        "passed_checks": sum(bool(value) for value in checks.values()),
        "total_checks": len(checks),
        "checks": checks,
    }


def evaluate_pretest(
    *,
    dataset_value: typing.Union[str, pathlib.Path],
    dataset_manifest_value: typing.Union[str, pathlib.Path],
    protocol_value: typing.Union[str, pathlib.Path],
    output_root_value: typing.Union[str, pathlib.Path],
) -> dict:
    protocol = write_or_verify_protocol(protocol_value)
    dataset_manifest_path = pathlib.Path(dataset_manifest_value).resolve()
    dataset_manifest = json.loads(
        dataset_manifest_path.read_text(encoding="utf-8")
    )
    if dataset_manifest.get("protocol_sha256") != protocol["protocol_sha256"]:
        raise ValueError("cross-venue dataset/protocol mismatch")
    if dataset_manifest.get("locked_test_materialized") is not False:
        raise ValueError("cross-venue pre-test contains locked data")
    dataset = CrossVenueDataset.load(
        dataset_value,
        expected_sha256=dataset_manifest["artifact"]["sha256"],
    )
    fold_reports = []
    primary_parts = []
    stress_parts = []
    for fold_number, (train, test) in enumerate(
        v2._development_folds(dataset), 1
    ):
        threshold = _threshold(dataset, train)
        primary_trades = _simulate(
            dataset, test, threshold, stress=False
        )
        stress_trades = _simulate(dataset, test, threshold, stress=True)
        primary = v1._trade_metrics(dataset, primary_trades)
        stress = v1._trade_metrics(dataset, stress_trades)
        primary_parts.append(primary_trades)
        stress_parts.append(stress_trades)
        fold_reports.append(
            {
                "fold": fold_number,
                "train_rows": len(train),
                "test_rows": len(test),
                "impulse_threshold_bps": threshold,
                "primary": primary,
                "stress": stress,
            }
        )
    development_primary = v1._trade_metrics(
        dataset, v1._combine_trades(primary_parts)
    )
    development_stress = v1._trade_metrics(
        dataset, v1._combine_trades(stress_parts)
    )
    positive_folds = sum(
        fold["primary"]["total_return"] > 0 for fold in fold_reports
    )
    development_gate = _gate(
        development_primary,
        development_stress,
        minimum_trades=DEVELOPMENT_MINIMUM_TRADES,
        positive_folds=positive_folds,
        valid_folds=len(fold_reports),
    )
    development = numpy.flatnonzero(
        dataset.timestamps < v1._iso_timestamp(DEVELOPMENT_END)
    )
    final_threshold = _threshold(dataset, development)
    confirmation = numpy.flatnonzero(
        (dataset.timestamps >= v1._iso_timestamp(DEVELOPMENT_END))
        & (
            dataset.timestamps
            < v1._iso_timestamp(DIAGNOSTIC_CONFIRMATION_END)
        )
    )
    confirmation_primary_trades = _simulate(
        dataset, confirmation, final_threshold, stress=False
    )
    confirmation_stress_trades = _simulate(
        dataset, confirmation, final_threshold, stress=True
    )
    confirmation_primary = v1._trade_metrics(
        dataset, confirmation_primary_trades
    )
    confirmation_stress = v1._trade_metrics(
        dataset, confirmation_stress_trades
    )
    confirmation_gate = _gate(
        confirmation_primary,
        confirmation_stress,
        minimum_trades=CONFIRMATION_MINIMUM_TRADES,
    )
    locked_authorized = bool(
        development_gate["passed"] and confirmation_gate["passed"]
    )
    created_at = datetime.datetime.now(datetime.timezone.utc)
    experiment_id = f"{PROTOCOL_VERSION}-{created_at.strftime('%Y%m%dT%H%M%SZ')}"
    experiment = pathlib.Path(output_root_value).resolve() / experiment_id
    experiment.mkdir(parents=True, exist_ok=False)
    report = {
        "schema_version": SCHEMA_VERSION,
        "experiment_id": experiment_id,
        "created_at": created_at.isoformat(),
        "research_only": True,
        "orders_authorized": False,
        "paper_orders_authorized": False,
        "automatic_promotion": False,
        "protocol": {
            "version": PROTOCOL_VERSION,
            "sha256": protocol["protocol_sha256"],
        },
        "dataset": {
            "rows": len(dataset.timestamps),
            "sha256": dataset_manifest["artifact"]["sha256"],
            "locked_test_materialized": False,
        },
        "signal": {
            "configuration": CONFIGURATION,
            "impulse_quantile": IMPULSE_QUANTILE,
            "final_impulse_threshold_bps": final_threshold,
            "minimum_directional_lag_bps": MINIMUM_DIRECTIONAL_LAG_BPS,
            "minimum_directional_flow_imbalance": (
                MINIMUM_DIRECTIONAL_FLOW_IMBALANCE
            ),
            "minimum_binance_trades": MINIMUM_BINANCE_TRADES,
        },
        "development": {
            "primary": development_primary,
            "stress": development_stress,
            "positive_folds": positive_folds,
            "folds": fold_reports,
            "gate": development_gate,
        },
        "diagnostic_confirmation": {
            "diagnostic_reuse": True,
            "start": DEVELOPMENT_END,
            "end": DIAGNOSTIC_CONFIRMATION_END,
            "primary": confirmation_primary,
            "stress": confirmation_stress,
            "gate": confirmation_gate,
        },
        "locked_final_test": {
            "start": DIAGNOSTIC_CONFIRMATION_END,
            "end": LOCKED_TEST_END,
            "authorized_to_open": locked_authorized,
            "status": (
                "authorized_but_not_opened"
                if locked_authorized
                else "sealed_pretest_gate_failed"
            ),
            "binance_archive_downloaded": False,
            "labels_computed": False,
            "predictions_computed": False,
            "metrics_computed": False,
        },
        "conclusion": (
            "pretest_gates_passed_locked_test_may_be_opened_explicitly"
            if locked_authorized
            else "candidate_rejected_before_locked_test"
        ),
    }
    report_path = experiment / "report.json"
    _atomic_json(report_path, report)
    manifest = {
        "schema_version": SCHEMA_VERSION,
        "experiment_id": experiment_id,
        "created_at": created_at.isoformat(),
        "protocol_sha256": protocol["protocol_sha256"],
        "dataset_sha256": dataset_manifest["artifact"]["sha256"],
        "report": {
            "path": str(report_path),
            "bytes": report_path.stat().st_size,
            "sha256": _sha256(report_path),
        },
        "development_gate_passed": development_gate["passed"],
        "confirmation_gate_passed": confirmation_gate["passed"],
        "locked_test_authorized": locked_authorized,
        "orders_authorized": False,
        "paper_orders_authorized": False,
    }
    manifest_path = experiment / "manifest.json"
    _atomic_json(manifest_path, manifest)
    return {
        "experiment_id": experiment_id,
        "experiment_directory": str(experiment),
        "report": str(report_path),
        "development_gate_passed": development_gate["passed"],
        "confirmation_gate_passed": confirmation_gate["passed"],
        "locked_test_authorized": locked_authorized,
    }


def _main() -> None:
    import argparse

    parser = argparse.ArgumentParser(
        description="Frozen public-data-only BTC cross-venue research V4."
    )
    commands = parser.add_subparsers(dest="command", required=True)
    protocol_parser = commands.add_parser("write-protocol")
    protocol_parser.add_argument("--output", required=True)
    fetch_parser = commands.add_parser("fetch-pretest")
    fetch_parser.add_argument("--protocol", required=True)
    fetch_parser.add_argument("--cache-root", required=True)
    fetch_parser.add_argument("--manifest", required=True)
    build_parser = commands.add_parser("build-pretest-dataset")
    build_parser.add_argument("--parent-dataset", required=True)
    build_parser.add_argument("--parent-manifest", required=True)
    build_parser.add_argument("--archive-manifest", required=True)
    build_parser.add_argument("--protocol", required=True)
    build_parser.add_argument("--output", required=True)
    evaluate_parser = commands.add_parser("evaluate-pretest")
    evaluate_parser.add_argument("--dataset", required=True)
    evaluate_parser.add_argument("--dataset-manifest", required=True)
    evaluate_parser.add_argument("--protocol", required=True)
    evaluate_parser.add_argument("--output-root", required=True)
    arguments = parser.parse_args()
    if arguments.command == "write-protocol":
        result = write_or_verify_protocol(arguments.output)
    elif arguments.command == "fetch-pretest":
        result = fetch_pretest_archives(
            protocol_value=arguments.protocol,
            cache_root_value=arguments.cache_root,
            manifest_value=arguments.manifest,
            progress=lambda message: print(message, flush=True),
        )
    elif arguments.command == "build-pretest-dataset":
        result = build_pretest_dataset(
            parent_dataset_value=arguments.parent_dataset,
            parent_manifest_value=arguments.parent_manifest,
            archive_manifest_value=arguments.archive_manifest,
            protocol_value=arguments.protocol,
            output_value=arguments.output,
            progress=lambda message: print(message, flush=True),
        )
    else:
        result = evaluate_pretest(
            dataset_value=arguments.dataset,
            dataset_manifest_value=arguments.dataset_manifest,
            protocol_value=arguments.protocol,
            output_root_value=arguments.output_root,
        )
    print(json.dumps(v1._json_safe(result), indent=2, sort_keys=True))


if __name__ == "__main__":
    _main()
