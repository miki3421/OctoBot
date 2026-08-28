"""Orderless daily forward observer for the selected diversified portfolio.

The runner downloads only public Binance USD-M daily candles and funding,
archives immutable raw evidence, reconstructs the two frozen component paths
causally, and appends research targets to a hash-chained journal.  It has no
credential, exchange-account, simulator-order or live-order surface.
"""

from __future__ import annotations

import argparse
import concurrent.futures
import dataclasses
import datetime
import fcntl
import gzip
import hashlib
import json
import math
import os
import pathlib
import tempfile
import typing
import urllib.parse

import numpy

from octobot.ai_strategy_lab import category_momentum_v1 as category_protocol
from octobot.ai_strategy_lab import category_momentum_v1_research as public_source
from octobot.ai_strategy_lab import cointegration_pairs_v1 as pair_common
from octobot.ai_strategy_lab import cointegration_pairs_v2 as pair_protocol
from octobot.ai_strategy_lab import cointegration_pairs_v2_research as pairs
from octobot.ai_strategy_lab import diversified_trend_cointegration_forward_v1 as protocol
from octobot.ai_strategy_lab import diversified_trend_cointegration_v1 as parent_protocol
from octobot.ai_strategy_lab import diversified_trend_cointegration_v1_research as trainer
from octobot.ai_strategy_lab import dataset as dataset_module
from octobot.ai_strategy_lab import funding as funding_module
from octobot.ai_strategy_lab import indicators as indicators_module
from octobot.ai_strategy_lab import trend as trend_module


SCHEMA_VERSION = 1
OBSERVER_TYPE = "diversified_trend_cointegration_forward_observer_v1"
UTC = datetime.timezone.utc
DAY_MILLISECONDS = 86_400_000
BINANCE_API_ROOT = "https://fapi.binance.com"
MAXIMUM_FUNDING_PAGES = 8


class DataQualityError(ValueError):
    """Raised when frozen lineage or public daily evidence is invalid."""


FetchBytes = typing.Callable[[str], bytes]


@dataclasses.dataclass(frozen=True)
class ForwardObserverConfig:
    protocol_path: pathlib.Path
    implementation_lock_path: pathlib.Path
    parent_protocol_path: pathlib.Path
    selected_model_path: pathlib.Path
    training_report_path: pathlib.Path
    training_manifest_path: pathlib.Path
    training_trajectory_path: pathlib.Path
    snapshot_path: pathlib.Path
    history_path: pathlib.Path
    null_path: pathlib.Path
    archive_root: pathlib.Path
    raw_root: pathlib.Path
    journal_path: pathlib.Path
    health_path: pathlib.Path
    runner_lock_path: pathlib.Path
    timeout_seconds: float = 45.0
    maximum_workers: int = 8

    def validate(self) -> None:
        if self.timeout_seconds <= 0:
            raise ValueError("request timeout must be positive")
        if not 1 <= self.maximum_workers <= 32:
            raise ValueError("maximum workers must be in [1, 32]")
        if len({
            self.archive_root.resolve(),
            self.raw_root.resolve(),
            self.journal_path.resolve(),
            self.health_path.resolve(),
            self.runner_lock_path.resolve(),
        }) != 5:
            raise ValueError("observer output paths must be distinct")


def _canonical_bytes(value: object) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")


def _json_hash(value: object) -> str:
    return hashlib.sha256(_canonical_bytes(value)).hexdigest()


def _bytes_hash(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _atomic_bytes(path: pathlib.Path, payload: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(
        prefix=f".{path.name}.", suffix=".tmp", dir=str(path.parent)
    )
    temporary = pathlib.Path(temporary_name)
    try:
        with os.fdopen(descriptor, "wb") as stream:
            stream.write(payload)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    finally:
        if temporary.exists():
            temporary.unlink()


def _write_json_atomic(path: pathlib.Path, value: dict) -> None:
    _atomic_bytes(
        path,
        json.dumps(value, indent=2, sort_keys=True).encode("utf-8") + b"\n",
    )


def _verify_file(
    path_value: typing.Union[str, pathlib.Path], expected: str, label: str
) -> pathlib.Path:
    path = pathlib.Path(path_value).resolve()
    if not path.is_file() or pair_common._sha256(path) != expected:
        raise DataQualityError(f"{label} hash mismatch: {path}")
    return path


def _content_hash(value: dict, field: str = "content_sha256") -> str:
    return _json_hash({key: item for key, item in value.items() if key != field})


def _repo_root() -> pathlib.Path:
    return pathlib.Path(__file__).resolve().parents[2]


def _implementation_source_paths() -> dict[str, pathlib.Path]:
    root = _repo_root()
    return {
        "forward_protocol": pathlib.Path(protocol.__file__).resolve(),
        "forward_runner": pathlib.Path(__file__).resolve(),
        "parent_protocol": pathlib.Path(parent_protocol.__file__).resolve(),
        "parent_trainer": pathlib.Path(trainer.__file__).resolve(),
        "trend_component": pathlib.Path(trend_module.__file__).resolve(),
        "cointegration_common": pathlib.Path(pair_common.__file__).resolve(),
        "cointegration_protocol": pathlib.Path(pair_protocol.__file__).resolve(),
        "cointegration_research": pathlib.Path(pairs.__file__).resolve(),
        "category_protocol": pathlib.Path(category_protocol.__file__).resolve(),
        "public_source": pathlib.Path(public_source.__file__).resolve(),
        "dataset_loader": pathlib.Path(dataset_module.__file__).resolve(),
        "funding_loader": pathlib.Path(funding_module.__file__).resolve(),
        "trend_indicators": pathlib.Path(indicators_module.__file__).resolve(),
        "forward_protocol_tests": root
        / "tests/unit_tests/ai_strategy_lab/"
        "test_diversified_trend_cointegration_forward_v1.py",
        "forward_runner_tests": root
        / "tests/unit_tests/ai_strategy_lab/"
        "test_diversified_trend_cointegration_forward_runner.py",
        "docker_entrypoint": root
        / "docker/diversified-forward-observer-entrypoint.sh",
    }


def _source_artifacts() -> dict[str, dict]:
    root = _repo_root()
    result = {}
    for label, path in sorted(_implementation_source_paths().items()):
        resolved = path.resolve()
        if not resolved.is_file():
            raise DataQualityError(f"implementation source is missing: {label}")
        try:
            relative = str(resolved.relative_to(root))
        except ValueError:
            relative = resolved.name
        result[label] = {
            "repo_relative_path": relative,
            "bytes": resolved.stat().st_size,
            "sha256": pair_common._sha256(resolved),
        }
    return result


def _verify_selected_lineage(config: ForwardObserverConfig) -> dict:
    protocol_payload = protocol.load_and_verify_protocol(config.protocol_path)
    _verify_file(
        config.parent_protocol_path,
        protocol.PARENT_PROTOCOL_FILE_SHA256,
        "parent protocol",
    )
    selected_path = _verify_file(
        config.selected_model_path,
        protocol.SELECTED_MODEL_SHA256,
        "selected model",
    )
    report_path = _verify_file(
        config.training_report_path,
        protocol.TRAINING_REPORT_SHA256,
        "training report",
    )
    manifest_path = _verify_file(
        config.training_manifest_path,
        protocol.TRAINING_MANIFEST_SHA256,
        "training manifest",
    )
    trajectory_path = _verify_file(
        config.training_trajectory_path,
        protocol.TRAINING_TRAJECTORY_SHA256,
        "training trajectory",
    )
    selected = json.loads(selected_path.read_text(encoding="utf-8"))
    training_report = json.loads(report_path.read_text(encoding="utf-8"))
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    if (
        selected.get("content_sha256")
        != protocol.SELECTED_MODEL_CONTENT_SHA256
        or _content_hash(selected) != protocol.SELECTED_MODEL_CONTENT_SHA256
        or selected.get("configuration_id")
        != "trend50_cointegration50"
        or selected.get("trend_capital_weight") != 0.5
        or selected.get("cointegration_capital_weight") != 0.5
        or selected.get("orders_authorized") is not False
        or selected.get("paper_orders_authorized") is not False
        or selected.get("forward_started") is not False
    ):
        raise DataQualityError("selected model content or safeguards differ")
    if (
        manifest.get("content_sha256")
        != protocol.TRAINING_MANIFEST_CONTENT_SHA256
        or _content_hash(manifest)
        != protocol.TRAINING_MANIFEST_CONTENT_SHA256
        or manifest.get("selected_model_sha256")
        != protocol.SELECTED_MODEL_SHA256
        or manifest.get("report_sha256") != protocol.TRAINING_REPORT_SHA256
        or manifest.get("trajectory_sha256")
        != protocol.TRAINING_TRAJECTORY_SHA256
        or manifest.get("forward_started") is not False
        or manifest.get("orders_authorized") is not False
    ):
        raise DataQualityError("training manifest lineage differs")
    if (
        training_report.get("protocol_sha256")
        != protocol.PARENT_PROTOCOL_SHA256
        or training_report.get("selected_configuration_id")
        != "trend50_cointegration50"
        or training_report.get("verdict")
        != "TRAINING_MODEL_SELECTED_REQUIRES_180D_FORWARD"
        or training_report.get("orders_authorized") is not False
        or training_report.get("paper_orders_authorized") is not False
    ):
        raise DataQualityError("training report lineage differs")
    _verify_file(
        trend_module.__file__,
        parent_protocol.TREND_SOURCE_SHA256,
        "trend component source",
    )
    _verify_file(
        pairs.__file__,
        parent_protocol.COINTEGRATION_SOURCE_SHA256,
        "cointegration component source",
    )
    null_path = _verify_file(
        config.null_path,
        parent_protocol.COINTEGRATION_NULL_SHA256,
        "cointegration null",
    )
    null = numpy.load(null_path, allow_pickle=False)
    if (
        null.shape != (pair_protocol.MONTE_CARLO_SIMULATIONS,)
        or numpy.any(~numpy.isfinite(null))
        or numpy.any(numpy.diff(null) < 0)
    ):
        raise DataQualityError("cointegration null is invalid")
    (
        _snapshot_root,
        snapshot_manifest,
        _history_root,
        history_manifest,
        cointegration_market,
    ) = pairs._load_market(config.snapshot_path, config.history_path)
    if (
        snapshot_manifest["source_bundle_sha256"]
        != parent_protocol.SOURCE_SNAPSHOT_BUNDLE_SHA256
        or history_manifest["history_bundle_sha256"]
        != parent_protocol.HISTORY_BUNDLE_SHA256
        or len(cointegration_market["symbols"]) != 120
        or cointegration_market["dates"][-1] != datetime.date(2026, 7, 1)
    ):
        raise DataQualityError("frozen 120-asset market lineage differs")
    trend_market, trend_config, trend_artifacts = trainer._load_trend_component(
        training_report["trend_artifacts"]["report_path"]
    )
    trend_remote_symbols = [
        _local_to_binance_symbol(value) for value in trend_market["symbols"]
    ]
    if (
        trend_market["dates"][-1] != datetime.date(2026, 6, 30)
        or len(trend_remote_symbols) != 18
        or not set(trend_remote_symbols).issubset(cointegration_market["symbols"])
    ):
        raise DataQualityError("trend V13 market lineage differs")
    return {
        "protocol": protocol_payload,
        "selected": selected,
        "training_report": training_report,
        "manifest": manifest,
        "trajectory_path": trajectory_path,
        "null": null,
        "cointegration_market": cointegration_market,
        "trend_market": trend_market,
        "trend_config": trend_config,
        "trend_artifacts": trend_artifacts,
        "trend_remote_symbols": trend_remote_symbols,
    }


def create_or_verify_implementation_lock(
    config: ForwardObserverConfig,
    *,
    now: typing.Optional[datetime.datetime] = None,
) -> dict:
    """Freeze every executable and input hash before the forward starts."""

    config.validate()
    observed_at = now or datetime.datetime.now(UTC)
    if observed_at.tzinfo is None:
        raise ValueError("implementation-lock time must be timezone-aware")
    observed_at = observed_at.astimezone(UTC)
    if config.implementation_lock_path.is_file():
        return verify_implementation_lock(config)["implementation_lock"]
    if observed_at >= datetime.datetime.combine(
        protocol.FORWARD_START, datetime.time(), UTC
    ):
        raise RuntimeError("implementation lock cannot be created after start")
    context = _verify_selected_lineage(config)
    source_artifacts = _source_artifacts()
    preflight = _trend_mirror_preflight(
        context["trend_market"], context["trend_config"]
    )
    cointegration_preflight = _cointegration_mirror_preflight(
        context["cointegration_market"], context["null"]
    )
    payload = {
        "schema_version": SCHEMA_VERSION,
        "observer_type": OBSERVER_TYPE,
        "created_at": observed_at.isoformat(),
        "status": "immutable_pre_forward_implementation_lock",
        "research_only": True,
        "public_data_only": True,
        "credentials_used": False,
        "orders_authorized": False,
        "paper_orders_authorized": False,
        "automatic_promotion": False,
        "protocol_sha256": context["protocol"]["protocol_sha256"],
        "protocol_file_sha256": pair_common._sha256(config.protocol_path),
        "selected_model_sha256": protocol.SELECTED_MODEL_SHA256,
        "selected_model_content_sha256": (
            protocol.SELECTED_MODEL_CONTENT_SHA256
        ),
        "training_report_sha256": protocol.TRAINING_REPORT_SHA256,
        "training_manifest_sha256": protocol.TRAINING_MANIFEST_SHA256,
        "training_trajectory_sha256": protocol.TRAINING_TRAJECTORY_SHA256,
        "source_snapshot_bundle_sha256": (
            parent_protocol.SOURCE_SNAPSHOT_BUNDLE_SHA256
        ),
        "history_bundle_sha256": parent_protocol.HISTORY_BUNDLE_SHA256,
        "cointegration_null_sha256": (
            parent_protocol.COINTEGRATION_NULL_SHA256
        ),
        "universe_symbols_sha256": _json_hash(
            context["cointegration_market"]["symbols"]
        ),
        "universe_symbols": context["cointegration_market"]["symbols"],
        "trend_symbols_sha256": _json_hash(
            context["trend_market"]["symbols"]
        ),
        "trend_symbols": context["trend_market"]["symbols"],
        "source_files": source_artifacts,
        "trend_mirror_preflight": preflight,
        "cointegration_mirror_preflight": cointegration_preflight,
        "runtime": {
            "python_major_minor": [
                int(value)
                for value in (
                    f"{os.sys.version_info.major}.{os.sys.version_info.minor}"
                ).split(".")
            ],
            "numpy_version": numpy.__version__,
        },
    }
    locked = {**payload, "implementation_lock_sha256": _json_hash(payload)}
    _write_json_atomic(config.implementation_lock_path, locked)
    return verify_implementation_lock(config)["implementation_lock"]


def verify_implementation_lock(config: ForwardObserverConfig) -> dict:
    context = _verify_selected_lineage(config)
    path = config.implementation_lock_path.resolve()
    if not path.is_file():
        raise DataQualityError("implementation lock is missing")
    locked = json.loads(path.read_text(encoding="utf-8"))
    unsigned = {
        key: value
        for key, value in locked.items()
        if key != "implementation_lock_sha256"
    }
    if (
        locked.get("implementation_lock_sha256") != _json_hash(unsigned)
        or locked.get("protocol_sha256")
        != context["protocol"]["protocol_sha256"]
        or locked.get("protocol_file_sha256")
        != pair_common._sha256(config.protocol_path)
        or locked.get("selected_model_sha256")
        != protocol.SELECTED_MODEL_SHA256
        or locked.get("orders_authorized") is not False
        or locked.get("paper_orders_authorized") is not False
    ):
        raise DataQualityError("implementation lock content differs")
    current_sources = _source_artifacts()
    if locked.get("source_files") != current_sources:
        raise DataQualityError("implementation source changed after lock")
    if locked.get("universe_symbols") != context["cointegration_market"]["symbols"]:
        raise DataQualityError("locked universe differs")
    if locked.get("trend_symbols") != context["trend_market"]["symbols"]:
        raise DataQualityError("locked trend symbols differ")
    return {**context, "implementation_lock": locked}


def _local_to_binance_symbol(symbol: str) -> str:
    if not symbol.endswith("/USDT:USDT"):
        raise DataQualityError(f"unsupported trend symbol: {symbol}")
    return f"{symbol.split('/', 1)[0]}USDT"


def _query(path: str, parameters: dict) -> str:
    if path not in {"/fapi/v1/klines", "/fapi/v1/fundingRate"}:
        raise ValueError("forward observer endpoint is not approved")
    return f"{BINANCE_API_ROOT}{path}?{urllib.parse.urlencode(parameters)}"


def _default_fetch(url: str, *, timeout: float) -> bytes:
    return public_source._public_get(url, timeout=timeout)


def _store_raw_response(
    raw_root: pathlib.Path,
    *,
    url: str,
    payload: bytes,
) -> dict:
    parsed_url = urllib.parse.urlparse(url)
    if (
        parsed_url.scheme != "https"
        or parsed_url.hostname != "fapi.binance.com"
        or parsed_url.path not in {"/fapi/v1/klines", "/fapi/v1/fundingRate"}
        or parsed_url.username
        or parsed_url.password
    ):
        raise ValueError("raw response URL is not an approved public endpoint")
    json.loads(payload.decode("utf-8"))
    response_sha = _bytes_hash(payload)
    relative = pathlib.Path(response_sha[:2]) / f"{response_sha}.json.gz"
    path = raw_root / relative
    compressed = gzip.compress(payload, compresslevel=9, mtime=0)
    if path.is_file():
        if gzip.decompress(path.read_bytes()) != payload:
            raise DataQualityError("content-addressed raw response changed")
    else:
        _atomic_bytes(path, compressed)
    return {
        "path": str(relative),
        "url": url,
        "response_sha256": response_sha,
        "artifact_sha256": pair_common._sha256(path),
        "uncompressed_bytes": len(payload),
        "compressed_bytes": path.stat().st_size,
    }


def _date_range(start: datetime.date, end_exclusive: datetime.date) -> list:
    if end_exclusive <= start:
        return []
    return [
        start + datetime.timedelta(days=index)
        for index in range((end_exclusive - start).days)
    ]


def _parse_klines(
    payload: bytes,
    expected_dates: list[datetime.date],
) -> dict[datetime.date, float]:
    rows = json.loads(payload.decode("utf-8"))
    expected = {
        int(datetime.datetime.combine(date, datetime.time(), UTC).timestamp())
        * 1000: date
        for date in expected_dates
    }
    result = {}
    if not isinstance(rows, list):
        raise DataQualityError("Binance kline response is not a list")
    for row in rows:
        if not isinstance(row, list) or len(row) < 7:
            raise DataQualityError("Binance daily kline row is invalid")
        open_time = int(row[0])
        date = expected.get(open_time)
        if date is None:
            continue
        close_time = int(row[6])
        close = float(row[4])
        if close_time != open_time + DAY_MILLISECONDS - 1:
            raise DataQualityError(f"daily kline close time differs for {date}")
        if not math.isfinite(close) or close <= 0:
            raise DataQualityError(f"daily close is invalid for {date}")
        previous = result.get(date)
        if previous is not None and previous != close:
            raise DataQualityError(f"daily close duplicated with conflict: {date}")
        result[date] = close
    missing = sorted(set(expected_dates) - set(result))
    if missing:
        raise DataQualityError(
            f"daily kline response misses {len(missing)} bars starting {missing[0]}"
        )
    return result


def _parse_funding_rows(
    pages: list[bytes],
    expected_dates: list[datetime.date],
    expected_symbol: str,
) -> dict[datetime.date, tuple[float, int]]:
    if not expected_dates:
        return {}
    first_open = datetime.datetime.combine(expected_dates[0], datetime.time(), UTC)
    end_open = datetime.datetime.combine(
        expected_dates[-1] + datetime.timedelta(days=1),
        datetime.time(),
        UTC,
    )
    by_timestamp: dict[int, float] = {}
    for payload in pages:
        rows = json.loads(payload.decode("utf-8"))
        if not isinstance(rows, list):
            raise DataQualityError("Binance funding response is not a list")
        for row in rows:
            if not isinstance(row, dict):
                raise DataQualityError("Binance funding row is invalid")
            if row.get("symbol") != expected_symbol:
                raise DataQualityError("Binance funding symbol differs")
            timestamp = int(row["fundingTime"])
            rate = float(row["fundingRate"])
            if not math.isfinite(rate):
                raise DataQualityError("Binance funding rate is nonfinite")
            instant = datetime.datetime.fromtimestamp(timestamp / 1000, UTC)
            if not first_open < instant <= end_open:
                continue
            previous = by_timestamp.get(timestamp)
            if previous is not None and previous != rate:
                raise DataQualityError("funding settlement changed across pages")
            by_timestamp[timestamp] = rate
    grouped: dict[datetime.date, list[float]] = {
        date: [] for date in expected_dates
    }
    for timestamp, rate in sorted(by_timestamp.items()):
        assigned = datetime.datetime.fromtimestamp(
            (timestamp - 1) / 1000, UTC
        ).date()
        if assigned in grouped:
            grouped[assigned].append(rate)
    result = {}
    for date, rates in grouped.items():
        if not rates:
            raise DataQualityError(f"funding response misses settlements for {date}")
        result[date] = (float(sum(rates)), len(rates))
    return result


def _fetch_funding_pages(
    symbol: str,
    start: datetime.date,
    end_exclusive: datetime.date,
    *,
    fetcher: FetchBytes,
    raw_root: pathlib.Path,
) -> tuple[list[bytes], list[dict]]:
    start_ms = int(
        datetime.datetime.combine(start, datetime.time(), UTC).timestamp()
        * 1000
    ) + 1
    end_ms = int(
        datetime.datetime.combine(
            end_exclusive, datetime.time(), UTC
        ).timestamp()
        * 1000
    )
    pages = []
    artifacts = []
    cursor = start_ms
    for _page in range(MAXIMUM_FUNDING_PAGES):
        url = _query(
            "/fapi/v1/fundingRate",
            {
                "symbol": symbol,
                "startTime": cursor,
                "endTime": end_ms,
                "limit": 1000,
            },
        )
        payload = fetcher(url)
        rows = json.loads(payload.decode("utf-8"))
        if not isinstance(rows, list):
            raise DataQualityError("Binance funding page is not a list")
        pages.append(payload)
        artifacts.append(
            _store_raw_response(raw_root, url=url, payload=payload)
        )
        timestamps = [int(value["fundingTime"]) for value in rows]
        if timestamps != sorted(timestamps):
            raise DataQualityError("Binance funding page is not ordered")
        if not timestamps or len(rows) < 1000 or timestamps[-1] >= end_ms:
            break
        if timestamps[-1] < cursor:
            raise DataQualityError("Binance funding pagination did not advance")
        cursor = timestamps[-1] + 1
    else:
        raise DataQualityError("Binance funding pagination exceeded bound")
    return pages, artifacts


def _fetch_symbol_range(
    symbol: str,
    dates: list[datetime.date],
    *,
    fetcher: FetchBytes,
    raw_root: pathlib.Path,
) -> dict:
    start = dates[0]
    end_exclusive = dates[-1] + datetime.timedelta(days=1)
    start_ms = int(
        datetime.datetime.combine(start, datetime.time(), UTC).timestamp()
        * 1000
    )
    end_ms = int(
        datetime.datetime.combine(
            end_exclusive, datetime.time(), UTC
        ).timestamp()
        * 1000
    ) - 1
    kline_url = _query(
        "/fapi/v1/klines",
        {
            "symbol": symbol,
            "interval": "1d",
            "startTime": start_ms,
            "endTime": end_ms,
            "limit": min(1000, len(dates) + 2),
        },
    )
    kline_payload = fetcher(kline_url)
    kline_artifact = _store_raw_response(
        raw_root, url=kline_url, payload=kline_payload
    )
    funding_pages, funding_artifacts = _fetch_funding_pages(
        symbol,
        start,
        end_exclusive,
        fetcher=fetcher,
        raw_root=raw_root,
    )
    return {
        "symbol": symbol,
        "closes": _parse_klines(kline_payload, dates),
        "funding": _parse_funding_rows(funding_pages, dates, symbol),
        "raw": {
            "daily_klines": kline_artifact,
            "funding_pages": funding_artifacts,
        },
    }


def fetch_public_daily_range(
    symbols: list[str],
    start: datetime.date,
    end_exclusive: datetime.date,
    *,
    raw_root: pathlib.Path,
    maximum_workers: int = 8,
    timeout_seconds: float = 45.0,
    fetch_bytes: typing.Optional[FetchBytes] = None,
) -> dict[datetime.date, dict]:
    """Fetch one complete range using two public request families only."""

    dates = _date_range(start, end_exclusive)
    if not dates:
        return {}
    if len(dates) > 998:
        raise ValueError("daily public range exceeds one kline page")
    if len(symbols) != len(set(symbols)) or not symbols:
        raise ValueError("frozen symbol universe is invalid")
    fetcher = fetch_bytes or (
        lambda url: _default_fetch(url, timeout=timeout_seconds)
    )
    results = {}
    with concurrent.futures.ThreadPoolExecutor(
        max_workers=maximum_workers
    ) as executor:
        futures = {
            executor.submit(
                _fetch_symbol_range,
                symbol,
                dates,
                fetcher=fetcher,
                raw_root=raw_root,
            ): symbol
            for symbol in symbols
        }
        for future in concurrent.futures.as_completed(futures):
            symbol = futures[future]
            value = future.result()
            if value["symbol"] != symbol:
                raise DataQualityError("public symbol result differs")
            results[symbol] = value
    if sorted(results) != sorted(symbols):
        raise DataQualityError("public range did not return the frozen universe")
    daily = {}
    for date in dates:
        daily[date] = {
            "symbols": {
                symbol: {
                    "close": results[symbol]["closes"][date],
                    "funding_rate_sum": results[symbol]["funding"][date][0],
                    "funding_settlement_count": (
                        results[symbol]["funding"][date][1]
                    ),
                    "raw": results[symbol]["raw"],
                }
                for symbol in symbols
            }
        }
    return daily


def _daily_record_hash(record: dict) -> str:
    return _json_hash(
        {key: value for key, value in record.items() if key != "record_hash"}
    )


def load_daily_records(
    archive_root: pathlib.Path,
    *,
    raw_root: typing.Optional[pathlib.Path] = None,
    expected_symbols: typing.Optional[list[str]] = None,
) -> list[dict]:
    records = []
    previous_hash = None
    previous_date = None
    if not archive_root.exists():
        return records
    for path in sorted(archive_root.glob("????-??-??.json.gz")):
        record = json.loads(gzip.decompress(path.read_bytes()).decode("utf-8"))
        date = datetime.date.fromisoformat(record["bar_date"])
        if path.name != f"{date.isoformat()}.json.gz":
            raise DataQualityError("daily archive filename differs")
        if record.get("record_hash") != _daily_record_hash(record):
            raise DataQualityError("daily archive record hash differs")
        if record.get("previous_record_hash") != previous_hash:
            raise DataQualityError("daily archive hash chain differs")
        if previous_date is not None and date != previous_date + datetime.timedelta(days=1):
            raise DataQualityError("daily archive calendar is not contiguous")
        if expected_symbols is not None and list(record["symbols"]) != expected_symbols:
            raise DataQualityError("daily archive symbol universe differs")
        if raw_root is not None:
            _verify_raw_artifacts(record, raw_root)
        records.append(record)
        previous_hash = record["record_hash"]
        previous_date = date
    return records


def _verify_raw_artifacts(record: dict, raw_root: pathlib.Path) -> None:
    seen = set()
    for values in record["symbols"].values():
        artifacts = [values["raw"]["daily_klines"]] + list(
            values["raw"]["funding_pages"]
        )
        for artifact in artifacts:
            key = artifact["response_sha256"]
            if key in seen:
                continue
            seen.add(key)
            path = (raw_root / artifact["path"]).resolve()
            if not path.is_relative_to(raw_root.resolve()):
                raise DataQualityError("raw artifact path escapes archive")
            if (
                not path.is_file()
                or pair_common._sha256(path) != artifact["artifact_sha256"]
            ):
                raise DataQualityError("raw response artifact hash differs")
            payload = gzip.decompress(path.read_bytes())
            if _bytes_hash(payload) != key:
                raise DataQualityError("raw response content hash differs")


def append_daily_records(
    archive_root: pathlib.Path,
    fetched: dict[datetime.date, dict],
    *,
    expected_symbols: list[str],
    collected_at: datetime.datetime,
) -> list[dict]:
    existing = load_daily_records(
        archive_root, expected_symbols=expected_symbols
    )
    previous_hash = existing[-1]["record_hash"] if existing else None
    expected_next = (
        datetime.date.fromisoformat(existing[-1]["bar_date"])
        + datetime.timedelta(days=1)
        if existing
        else protocol.WARMUP_START
    )
    appended = []
    for date, payload in sorted(fetched.items()):
        if date < expected_next:
            continue
        if date != expected_next:
            raise DataQualityError("cannot append a noncontiguous daily record")
        if list(payload["symbols"]) != expected_symbols:
            raise DataQualityError("fetched daily symbol order differs")
        record = {
            "schema_version": SCHEMA_VERSION,
            "observer_type": OBSERVER_TYPE,
            "mode": "warmup_only" if date < protocol.FORWARD_START else "forward_only",
            "public_data_only": True,
            "credentials_used": False,
            "orders_authorized": False,
            "paper_orders_authorized": False,
            "automatic_promotion": False,
            "bar_date": date.isoformat(),
            "bar_open_utc": f"{date.isoformat()}T00:00:00+00:00",
            "bar_close_utc": (
                f"{(date + datetime.timedelta(days=1)).isoformat()}"
                "T00:00:00+00:00"
            ),
            "collected_at": collected_at.isoformat(),
            "previous_record_hash": previous_hash,
            "symbol_count": len(expected_symbols),
            "symbols": payload["symbols"],
        }
        record["record_hash"] = _daily_record_hash(record)
        encoded = gzip.compress(
            _canonical_bytes(record), compresslevel=9, mtime=0
        )
        path = archive_root / f"{date.isoformat()}.json.gz"
        if path.exists():
            raise DataQualityError("daily archive path already exists")
        _atomic_bytes(path, encoded)
        appended.append(record)
        existing.append(record)
        previous_hash = record["record_hash"]
        expected_next = date + datetime.timedelta(days=1)
    return appended


def _records_to_arrays(records: list[dict], symbols: list[str]) -> dict:
    if not records:
        empty = numpy.empty((0, len(symbols)), dtype=numpy.float64)
        return {
            "dates": [],
            "closes": empty.copy(),
            "funding": empty.copy(),
            "funding_counts": numpy.empty(
                (0, len(symbols)), dtype=numpy.int16
            ),
        }
    dates = [datetime.date.fromisoformat(value["bar_date"]) for value in records]
    closes = numpy.asarray(
        [
            [float(record["symbols"][symbol]["close"]) for symbol in symbols]
            for record in records
        ],
        dtype=numpy.float64,
    )
    funding = numpy.asarray(
        [
            [
                float(record["symbols"][symbol]["funding_rate_sum"])
                for symbol in symbols
            ]
            for record in records
        ],
        dtype=numpy.float64,
    )
    counts = numpy.asarray(
        [
            [
                int(record["symbols"][symbol]["funding_settlement_count"])
                for symbol in symbols
            ]
            for record in records
        ],
        dtype=numpy.int16,
    )
    expected_shape = (len(records), len(symbols))
    if (
        closes.shape != expected_shape
        or funding.shape != expected_shape
        or counts.shape != expected_shape
        or numpy.any(~numpy.isfinite(closes))
        or numpy.any(closes <= 0)
        or numpy.any(~numpy.isfinite(funding))
        or numpy.any(counts < 1)
    ):
        raise DataQualityError("normalized public daily matrix is invalid")
    return {
        "dates": dates,
        "closes": closes,
        "funding": funding,
        "funding_counts": counts,
    }


def extend_cointegration_market(
    frozen: dict,
    records: list[dict],
) -> dict:
    symbols = list(frozen["symbols"])
    extension = _records_to_arrays(records, symbols)
    if records and (
        extension["dates"][0] != protocol.WARMUP_START
        or frozen["dates"][-1] + datetime.timedelta(days=1)
        != extension["dates"][0]
    ):
        raise DataQualityError("cointegration extension does not follow history")
    dates = list(frozen["dates"]) + extension["dates"]
    closes = numpy.vstack((frozen["closes"], extension["closes"]))
    funding = numpy.vstack((frozen["funding"], extension["funding"]))
    counts = numpy.vstack(
        (frozen["funding_counts"], extension["funding_counts"])
    )
    returns = numpy.zeros_like(closes)
    complete = (
        numpy.isfinite(closes[1:])
        & numpy.isfinite(closes[:-1])
        & (closes[1:] > 0)
        & (closes[:-1] > 0)
    )
    calculated = numpy.zeros_like(closes[1:])
    calculated[complete] = closes[1:][complete] / closes[:-1][complete] - 1.0
    returns[1:] = calculated
    return {
        "dates": dates,
        "timestamps": numpy.asarray(
            [
                int(datetime.datetime.combine(value, datetime.time(), UTC).timestamp())
                for value in dates
            ],
            dtype=numpy.int64,
        ),
        "symbols": symbols,
        "closes": closes,
        "returns": returns,
        "return_complete": numpy.vstack(
            (numpy.zeros((1, closes.shape[1]), dtype=bool), complete)
        ),
        "funding": funding,
        "funding_counts": counts,
    }


def extend_trend_market(
    frozen_trend: dict,
    frozen_cointegration: dict,
    records: list[dict],
) -> dict:
    local_symbols = list(frozen_trend["symbols"])
    remote_symbols = [_local_to_binance_symbol(value) for value in local_symbols]
    remote_columns = {
        symbol: frozen_cointegration["symbols"].index(symbol)
        for symbol in remote_symbols
    }
    bridge_date = frozen_trend["dates"][-1] + datetime.timedelta(days=1)
    if bridge_date != datetime.date(2026, 7, 1):
        raise DataQualityError("trend-to-public bridge date differs")
    bridge_index = frozen_cointegration["dates"].index(bridge_date)
    bridge_closes = numpy.asarray(
        [
            frozen_cointegration["closes"][bridge_index, remote_columns[symbol]]
            for symbol in remote_symbols
        ],
        dtype=numpy.float64,
    )
    bridge_funding = numpy.asarray(
        [
            frozen_cointegration["funding"][bridge_index, remote_columns[symbol]]
            for symbol in remote_symbols
        ],
        dtype=numpy.float64,
    )
    if numpy.any(~numpy.isfinite(bridge_closes)) or numpy.any(bridge_closes <= 0):
        raise DataQualityError("trend bridge closes are invalid")
    extension = _records_to_arrays(records, list(frozen_cointegration["symbols"]))
    extension_columns = [
        frozen_cointegration["symbols"].index(symbol)
        for symbol in remote_symbols
    ]
    dates = list(frozen_trend["dates"]) + [bridge_date] + extension["dates"]
    closes = numpy.vstack(
        (
            frozen_trend["closes"],
            bridge_closes[numpy.newaxis, :],
            extension["closes"][:, extension_columns],
        )
    )
    funding = numpy.vstack(
        (
            frozen_trend["funding"],
            bridge_funding[numpy.newaxis, :],
            extension["funding"][:, extension_columns],
        )
    )
    if any(
        right - left != datetime.timedelta(days=1)
        for left, right in zip(dates, dates[1:])
    ):
        raise DataQualityError("extended trend calendar is not contiguous")
    returns = numpy.zeros_like(closes)
    returns[1:] = closes[1:] / closes[:-1] - 1.0
    return {
        "dates": dates,
        "symbols": local_symbols,
        "closes": closes,
        "returns": returns,
        "funding": funding,
    }


def _stressed_trend_config(
    value: trend_module.TrendConfig, multiplier: float
) -> trend_module.TrendConfig:
    if multiplier == 1.0:
        return value
    return dataclasses.replace(
        value,
        name=f"{value.name}_cost_stress_{multiplier:g}x",
        fee_per_turnover=value.fee_per_turnover * multiplier,
        slippage_per_turnover=value.slippage_per_turnover * multiplier,
    )


def simulate_trend_forward(
    market: dict,
    config: trend_module.TrendConfig,
    start: datetime.date,
    end_exclusive: datetime.date,
) -> dict:
    """Mirror frozen V13 while exposing each causal post-close target."""

    config.validate()
    if (
        config.name.split("_cost_stress_", 1)[0]
        != "risk_budgeted_bear_regime_v13"
        or config.drawdown_soft_limit
        or config.volatility_brake_lookback_days
    ):
        raise ValueError("trend forward mirror accepts only frozen V13")
    start_index, end_index = trainer._interval_indices(
        market["dates"], start, end_exclusive
    )
    signals = trend_module._signals(
        market["closes"], config, market["symbols"]
    )
    covariances = trend_module._rolling_covariance(
        market["returns"], config.volatility_lookback_days
    )
    weights = numpy.zeros(len(market["symbols"]), dtype=numpy.float64)
    equity = 1.0
    last_rebalance = -config.rebalance_days
    daily = []
    equities = []
    targets = []
    turnovers = []
    costs = []
    funding_values = []
    invested_days = 0
    for index in range(start_index, end_index):
        before = equity
        price_return = float(numpy.sum(weights * market["returns"][index]))
        funding_return = float(
            numpy.sum(-weights * market["funding"][index])
        )
        gross_return = price_return + funding_return
        if gross_return <= -1:
            raise DataQualityError("trend daily gross return is below -100%")
        equity *= 1.0 + gross_return
        turnover = 0.0
        cost = 0.0
        if index - last_rebalance >= config.rebalance_days:
            target = trend_module._target_weights(
                signals[index], covariances[index], config
            )
            turnover = float(numpy.sum(numpy.abs(target - weights)))
            cost = turnover * (
                config.fee_per_turnover + config.slippage_per_turnover
            )
            equity *= 1.0 - cost
            weights = target
            last_rebalance = index
        if numpy.sum(numpy.abs(weights)) > 1e-15:
            invested_days += 1
        daily.append(equity / before - 1.0)
        equities.append(equity)
        targets.append(weights.copy())
        turnovers.append(turnover)
        costs.append(cost)
        funding_values.append(funding_return)
    return {
        "dates": list(market["dates"][start_index:end_index]),
        "daily_return": numpy.asarray(daily, dtype=numpy.float64),
        "equity": numpy.asarray(equities, dtype=numpy.float64),
        "targets": numpy.asarray(targets, dtype=numpy.float64),
        "turnover": numpy.asarray(turnovers, dtype=numpy.float64),
        "cost_return": numpy.asarray(costs, dtype=numpy.float64),
        "funding_return": numpy.asarray(funding_values, dtype=numpy.float64),
        "invested_days": invested_days,
    }


def _trend_mirror_preflight(
    market: dict, config: trend_module.TrendConfig
) -> dict:
    start = datetime.date(2026, 1, 1)
    end = datetime.date(2026, 7, 1)
    result = {}
    for multiplier in (1.0, 3.0):
        evaluated = _stressed_trend_config(config, multiplier)
        mirrored = simulate_trend_forward(market, evaluated, start, end)
        start_index, end_index = trainer._interval_indices(
            market["dates"], start, end
        )
        reference = trend_module._simulate(
            market,
            evaluated,
            1.0,
            include_trajectory=True,
            evaluation_start_index=start_index,
            evaluation_end_index=end_index,
        )
        reference_equity = numpy.asarray(
            reference["trajectory"]["equity"], dtype=numpy.float64
        )
        equity_difference = float(
            numpy.max(numpy.abs(reference_equity - mirrored["equity"]))
        )
        ending_difference = max(
            abs(
                float(mirrored["targets"][-1, column])
                - float(reference["ending_weights"][symbol])
            )
            for column, symbol in enumerate(market["symbols"])
        )
        if equity_difference > 1e-14 or ending_difference > 1e-14:
            raise DataQualityError("trend forward mirror failed exact preflight")
        result[f"cost_{multiplier:g}x"] = {
            "days": len(mirrored["dates"]),
            "maximum_equity_absolute_difference": equity_difference,
            "maximum_ending_weight_absolute_difference": ending_difference,
        }
    return result


def simulate_cointegration_forward(
    market: dict,
    null: numpy.ndarray,
    start: datetime.date,
    end_exclusive: datetime.date,
    *,
    cost_multiplier: float,
    formation_cache: typing.Optional[dict[int, dict]] = None,
) -> dict:
    """Run V2 from flat without an artificial daily terminal liquidation."""

    if cost_multiplier < 1:
        raise ValueError("cointegration cost multiplier must be at least one")
    indices = [
        index
        for index, date in enumerate(market["dates"])
        if start <= date < end_exclusive
    ]
    if not indices or market["dates"][indices[0]].day != 1:
        raise ValueError("forward cointegration must start on a formation day")
    formation_cache = formation_cache or pairs.build_formation_cache(
        market, start, end_exclusive, null
    )
    required_formations = {
        index
        for index in indices
        if market["dates"][index].day == 1
    }
    if not required_formations.issubset(formation_cache):
        raise DataQualityError("cointegration formation cache is incomplete")
    symbols = market["symbols"]
    weights = numpy.zeros(len(symbols), dtype=numpy.float64)
    selected: dict[tuple[int, int], pair_common.PairModel] = {}
    states: dict[tuple[int, int], int] = {}
    stopped: set[tuple[int, int]] = set()
    open_trades: dict[tuple[int, int], dict] = {}
    closed_trades = []
    selection_audit = []
    cost_rate = cost_multiplier * (
        pair_common.FEE_PER_TURNOVER + pair_common.SLIPPAGE_PER_TURNOVER
    )
    equity = 1.0
    daily = []
    equities = []
    targets = []
    turnovers = []
    costs = []
    funding_values = []
    selected_names = []
    invested_days = 0

    def close_trade(
        key: tuple[int, int],
        date: datetime.date,
        reason: str,
        exit_cost: float,
    ) -> None:
        trade = open_trades.pop(key, None)
        if trade is None:
            return
        trade["cost_return"] += exit_cost
        trade["net_return"] -= exit_cost
        trade["exit_date"] = date.isoformat()
        trade["exit_reason"] = reason
        closed_trades.append(trade)

    for index in indices:
        date = market["dates"][index]
        before = equity
        targeted = numpy.flatnonzero(numpy.abs(weights) > 1e-15)
        if len(targeted) and (
            not numpy.all(market["return_complete"][index, targeted])
            or not numpy.all(market["funding_counts"][index, targeted] > 0)
        ):
            raise DataQualityError(
                "open pair has an incomplete forward price or funding outcome"
            )
        price_by_symbol = weights * market["returns"][index]
        funding_by_symbol = -weights * market["funding"][index]
        gross_return = float(numpy.sum(price_by_symbol + funding_by_symbol))
        if gross_return <= -1:
            raise DataQualityError("cointegration daily return is below -100%")
        equity *= 1.0 + gross_return
        for key, trade in open_trades.items():
            model = selected[key]
            columns = [model.first, model.second]
            contribution = float(
                numpy.sum(
                    price_by_symbol[columns] + funding_by_symbol[columns]
                )
            )
            trade["gross_return"] += contribution
            trade["net_return"] += contribution
            trade["funding_return"] += float(
                numpy.sum(funding_by_symbol[columns])
            )

        day_turnover = 0.0
        day_cost = 0.0
        if index in formation_cache:
            refit_turnover = float(numpy.sum(numpy.abs(weights)))
            refit_cost = refit_turnover * cost_rate
            if refit_cost:
                equity *= 1.0 - refit_cost
                day_turnover += refit_turnover
                day_cost += refit_cost
            for key in list(open_trades):
                model = open_trades[key]["model"]
                pair_weights = numpy.asarray(
                    [weights[model.first], weights[model.second]]
                )
                exit_cost = float(numpy.sum(numpy.abs(pair_weights))) * cost_rate
                close_trade(key, date, "monthly_refit", exit_cost)
            weights = numpy.zeros(len(symbols), dtype=numpy.float64)
            selected_values, audit = pairs.select_pairs(
                formation_cache[index], symbols
            )
            selected = {value.key: value for value in selected_values}
            states = {key: 0 for key in selected}
            stopped = set()
            selection_audit.append(audit)

        target = numpy.zeros(len(symbols), dtype=numpy.float64)
        exit_reasons: dict[tuple[int, int], str] = {}
        pending_entries = []
        for key, model in selected.items():
            x = math.log(float(market["closes"][index, model.first]))
            y = math.log(float(market["closes"][index, model.second]))
            residual = y - model.alpha - model.beta * x
            z_score = (residual - model.residual_mean) / model.residual_std
            state = states.get(key, 0)
            if state:
                if abs(z_score) <= pair_common.EXIT_Z:
                    exit_reasons[key] = "mean_reversion"
                    state = 0
                elif abs(z_score) >= pair_common.STOP_Z:
                    exit_reasons[key] = "spread_stop"
                    stopped.add(key)
                    state = 0
            elif key not in stopped and abs(z_score) >= pair_common.ENTRY_Z:
                state = -1 if z_score > 0 else 1
                pending_entries.append((key, model, state, z_score))
            states[key] = state
            if state:
                allocation = 1.0 / pair_common.MAXIMUM_PAIRS
                normalizer = 1.0 + abs(model.beta)
                target[model.second] += state * allocation / normalizer
                target[model.first] -= (
                    state * model.beta * allocation / normalizer
                )

        delta = target - weights
        turnover = float(numpy.sum(numpy.abs(delta)))
        transaction_cost = turnover * cost_rate
        if transaction_cost:
            equity *= 1.0 - transaction_cost
            day_turnover += turnover
            day_cost += transaction_cost
        for key, reason in exit_reasons.items():
            model = open_trades.get(key, {}).get("model")
            if model is None:
                continue
            old_pair_weights = numpy.asarray(
                [weights[model.first], weights[model.second]]
            )
            exit_cost = float(numpy.sum(numpy.abs(old_pair_weights))) * cost_rate
            close_trade(key, date, reason, exit_cost)
        for key, model, state, z_score in pending_entries:
            allocation = 1.0 / pair_common.MAXIMUM_PAIRS
            entry_cost = allocation * cost_rate
            open_trades[key] = {
                "pair": pairs._pair_name(model, symbols),
                "model": model,
                "entry_date": date.isoformat(),
                "entry_z": float(z_score),
                "direction": int(state),
                "gross_return": 0.0,
                "funding_return": 0.0,
                "cost_return": entry_cost,
                "net_return": -entry_cost,
            }
        weights = target
        if numpy.sum(numpy.abs(weights)) > 1e-15:
            invested_days += 1
        daily.append(equity / before - 1.0)
        equities.append(equity)
        targets.append(weights.copy())
        turnovers.append(day_turnover)
        costs.append(day_cost)
        funding_values.append(float(numpy.sum(funding_by_symbol)))
        selected_names.append(
            [pairs._pair_name(value, symbols) for value in selected.values()]
        )
    return {
        "dates": [market["dates"][index] for index in indices],
        "daily_return": numpy.asarray(daily, dtype=numpy.float64),
        "equity": numpy.asarray(equities, dtype=numpy.float64),
        "targets": numpy.asarray(targets, dtype=numpy.float64),
        "turnover": numpy.asarray(turnovers, dtype=numpy.float64),
        "cost_return": numpy.asarray(costs, dtype=numpy.float64),
        "funding_return": numpy.asarray(funding_values, dtype=numpy.float64),
        "invested_days": invested_days,
        "closed_trades": [
            {key: value for key, value in trade.items() if key != "model"}
            for trade in closed_trades
        ],
        "open_trades": [
            {key: value for key, value in trade.items() if key != "model"}
            for trade in open_trades.values()
        ],
        "selection_audit": selection_audit,
        "selected_pairs": selected_names,
        "terminal_gross_exposure": float(numpy.sum(numpy.abs(weights))),
        "terminal_cost_rate": cost_rate,
    }


def _sparse_weights(symbols: list[str], values: numpy.ndarray) -> dict:
    return {
        symbol: float(value)
        for symbol, value in zip(symbols, values)
        if abs(float(value)) > 1e-15
    }


def _cointegration_mirror_preflight(market: dict, null: numpy.ndarray) -> dict:
    start = datetime.date(2026, 1, 1)
    end = datetime.date(2026, 7, 1)
    cache = pairs.build_formation_cache(market, start, end, null)
    result = {}
    for multiplier in (1.0, 3.0):
        mirrored = simulate_cointegration_forward(
            market,
            null,
            start,
            end,
            cost_multiplier=multiplier,
            formation_cache=cache,
        )
        reference = pairs.simulate_period(
            market,
            cache,
            start,
            end,
            cost_multiplier=multiplier,
            include_trajectory=True,
        )
        reference_daily = numpy.asarray(
            reference["_trajectory"]["daily_return"], dtype=numpy.float64
        )
        difference = float(
            numpy.max(
                numpy.abs(
                    reference_daily[:-1] - mirrored["daily_return"][:-1]
                )
            )
        )
        if difference > 1e-14:
            raise DataQualityError(
                "cointegration forward mirror failed causal preflight"
            )
        result[f"cost_{multiplier:g}x"] = {
            "days_compared_before_terminal_close": len(reference_daily) - 1,
            "maximum_daily_return_absolute_difference": difference,
            "terminal_day_intentionally_excluded": True,
        }
    return result


def _combined_equity(trend_equity, cointegration_equity) -> numpy.ndarray:
    trend_values = numpy.asarray(trend_equity, dtype=numpy.float64)
    pair_values = numpy.asarray(cointegration_equity, dtype=numpy.float64)
    if trend_values.shape != pair_values.shape or not len(trend_values):
        raise DataQualityError("component forward equity shapes differ")
    result = 0.5 * trend_values + 0.5 * pair_values
    if numpy.any(~numpy.isfinite(result)) or numpy.any(result <= 0):
        raise DataQualityError("combined forward equity is invalid")
    return result


def build_decision_payloads(
    trend_market: dict,
    cointegration_market: dict,
    trend_config: trend_module.TrendConfig,
    null: numpy.ndarray,
    records: list[dict],
) -> list[dict]:
    official = [
        value
        for value in records
        if datetime.date.fromisoformat(value["bar_date"])
        >= protocol.FORWARD_START
    ]
    if not official:
        return []
    end_exclusive = (
        datetime.date.fromisoformat(official[-1]["bar_date"])
        + datetime.timedelta(days=1)
    )
    components = {}
    formation_cache = pairs.build_formation_cache(
        cointegration_market,
        protocol.FORWARD_START,
        end_exclusive,
        null,
    )
    for multiplier in (1.0, 3.0):
        trend = simulate_trend_forward(
            trend_market,
            _stressed_trend_config(trend_config, multiplier),
            protocol.FORWARD_START,
            end_exclusive,
        )
        cointegration = simulate_cointegration_forward(
            cointegration_market,
            null,
            protocol.FORWARD_START,
            end_exclusive,
            cost_multiplier=multiplier,
            formation_cache=formation_cache,
        )
        if trend["dates"] != cointegration["dates"]:
            raise DataQualityError("forward component dates differ")
        combined = _combined_equity(trend["equity"], cointegration["equity"])
        starting = numpy.concatenate((numpy.ones(1), combined))
        components[multiplier] = {
            "trend": trend,
            "cointegration": cointegration,
            "combined_equity": combined,
            "combined_daily": numpy.diff(starting) / starting[:-1],
        }
    base = components[1.0]
    stress = components[3.0]
    by_date = {
        datetime.date.fromisoformat(value["bar_date"]): value
        for value in official
    }
    payloads = []
    for index, date in enumerate(base["trend"]["dates"]):
        evidence = by_date[date]
        base_combined_equity = float(base["combined_equity"][index])
        trend_effective_capital = (
            0.5 * float(base["trend"]["equity"][index])
            / base_combined_equity
        )
        pair_effective_capital = (
            0.5 * float(base["cointegration"]["equity"][index])
            / base_combined_equity
        )
        trend_weights = base["trend"]["targets"][index]
        pair_weights = base["cointegration"]["targets"][index]
        payload = {
            "schema_version": SCHEMA_VERSION,
            "observer_type": OBSERVER_TYPE,
            "mode": "forward_research_target_only",
            "research_only": True,
            "public_data_only": True,
            "credentials_used": False,
            "orders_authorized": False,
            "paper_orders_authorized": False,
            "automatic_promotion": False,
            "bar_date": date.isoformat(),
            "decision_available_not_before_utc": (
                f"{(date + datetime.timedelta(days=1)).isoformat()}T00:10:00+00:00"
            ),
            "target_return_bearing_bar": (
                date + datetime.timedelta(days=1)
            ).isoformat(),
            "market_record_hash": evidence["record_hash"],
            "base": {
                "portfolio_daily_return": float(
                    base["combined_daily"][index]
                ),
                "portfolio_equity": base_combined_equity,
                "trend_daily_return": float(
                    base["trend"]["daily_return"][index]
                ),
                "trend_equity": float(base["trend"]["equity"][index]),
                "cointegration_daily_return": float(
                    base["cointegration"]["daily_return"][index]
                ),
                "cointegration_equity": float(
                    base["cointegration"]["equity"][index]
                ),
            },
            "stress_3x_cost": {
                "portfolio_daily_return": float(
                    stress["combined_daily"][index]
                ),
                "portfolio_equity": float(
                    stress["combined_equity"][index]
                ),
                "trend_daily_return": float(
                    stress["trend"]["daily_return"][index]
                ),
                "trend_equity": float(stress["trend"]["equity"][index]),
                "cointegration_daily_return": float(
                    stress["cointegration"]["daily_return"][index]
                ),
                "cointegration_equity": float(
                    stress["cointegration"]["equity"][index]
                ),
            },
            "research_targets": {
                "trend_component_weights": _sparse_weights(
                    trend_market["symbols"], trend_weights
                ),
                "cointegration_component_weights": _sparse_weights(
                    cointegration_market["symbols"], pair_weights
                ),
                "trend_effective_portfolio_capital": trend_effective_capital,
                "cointegration_effective_portfolio_capital": (
                    pair_effective_capital
                ),
                "trend_effective_portfolio_weights": _sparse_weights(
                    trend_market["symbols"],
                    trend_weights * trend_effective_capital,
                ),
                "cointegration_effective_portfolio_weights": _sparse_weights(
                    cointegration_market["symbols"],
                    pair_weights * pair_effective_capital,
                ),
                "cointegration_selected_pairs": base["cointegration"][
                    "selected_pairs"
                ][index],
                "cross_sleeve_netting_applied": False,
            },
            "cumulative_activity": {
                "trend_invested_days": int(
                    numpy.sum(
                        numpy.sum(
                            numpy.abs(base["trend"]["targets"][: index + 1]),
                            axis=1,
                        )
                        > 1e-15
                    )
                ),
                "cointegration_invested_days": int(
                    numpy.sum(
                        numpy.sum(
                            numpy.abs(
                                base["cointegration"]["targets"][: index + 1]
                            ),
                            axis=1,
                        )
                        > 1e-15
                    )
                ),
                "cointegration_closed_trades": sum(
                    trade["exit_date"] <= date.isoformat()
                    for trade in base["cointegration"]["closed_trades"]
                ),
            },
        }
        payloads.append(
            {**payload, "decision_payload_sha256": _json_hash(payload)}
        )
    return payloads


def _journal_record_hash(record: dict) -> str:
    return _json_hash(
        {key: value for key, value in record.items() if key != "journal_record_hash"}
    )


def load_decision_journal(path: pathlib.Path) -> list[dict]:
    if not path.is_file():
        return []
    records = []
    previous_hash = None
    previous_date = None
    with path.open("r", encoding="utf-8") as stream:
        for line_number, line in enumerate(stream, start=1):
            if not line.strip():
                raise DataQualityError(
                    f"blank decision journal line {line_number}"
                )
            record = json.loads(line)
            payload = record["decision_payload"]
            unsigned_payload = {
                key: value
                for key, value in payload.items()
                if key != "decision_payload_sha256"
            }
            if payload.get("decision_payload_sha256") != _json_hash(
                unsigned_payload
            ):
                raise DataQualityError("decision payload hash differs")
            if record.get("previous_journal_hash") != previous_hash:
                raise DataQualityError("decision journal chain differs")
            if record.get("journal_record_hash") != _journal_record_hash(record):
                raise DataQualityError("decision journal record hash differs")
            date = datetime.date.fromisoformat(payload["bar_date"])
            if previous_date is not None and date != previous_date + datetime.timedelta(days=1):
                raise DataQualityError("decision journal calendar is not contiguous")
            if payload.get("orders_authorized") is not False:
                raise DataQualityError("decision journal contains order authority")
            records.append(record)
            previous_hash = record["journal_record_hash"]
            previous_date = date
    return records


def append_decision_payloads(
    path: pathlib.Path,
    payloads: list[dict],
    *,
    recorded_at: datetime.datetime,
) -> dict:
    existing = load_decision_journal(path)
    if len(existing) > len(payloads):
        raise DataQualityError("decision journal exceeds reproducible path")
    for index, record in enumerate(existing):
        if record["decision_payload"] != payloads[index]:
            raise DataQualityError(
                "prior forward decision does not reproduce exactly"
            )
    if existing and not payloads:
        raise DataQualityError("existing decisions lost from reconstruction")
    previous_hash = existing[-1]["journal_record_hash"] if existing else None
    appended = 0
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as stream:
        for payload in payloads[len(existing) :]:
            record = {
                "schema_version": SCHEMA_VERSION,
                "observer_type": OBSERVER_TYPE,
                "recorded_at": recorded_at.isoformat(),
                "previous_journal_hash": previous_hash,
                "decision_payload": payload,
            }
            record["journal_record_hash"] = _journal_record_hash(record)
            stream.write(
                json.dumps(record, separators=(",", ":"), sort_keys=True)
                + "\n"
            )
            stream.flush()
            os.fsync(stream.fileno())
            previous_hash = record["journal_record_hash"]
            appended += 1
    return {
        "existing_records": len(existing),
        "appended_records": appended,
        "total_records": len(existing) + appended,
        "last_journal_hash": previous_hash,
    }


def _bind_decision_lineage(payloads: list[dict], context: dict) -> list[dict]:
    result = []
    for value in payloads:
        unsigned = {
            key: item
            for key, item in value.items()
            if key != "decision_payload_sha256"
        }
        unsigned["lineage"] = {
            "forward_protocol_sha256": context["protocol"]["protocol_sha256"],
            "implementation_lock_sha256": context["implementation_lock"][
                "implementation_lock_sha256"
            ],
            "selected_model_sha256": protocol.SELECTED_MODEL_SHA256,
        }
        result.append(
            {**unsigned, "decision_payload_sha256": _json_hash(unsigned)}
        )
    return result


def _latest_mature_bar(now: datetime.datetime) -> datetime.date:
    if now.tzinfo is None:
        raise ValueError("observer time must be timezone-aware")
    observed = now.astimezone(UTC)
    delay = datetime.timedelta(
        minutes=protocol.DAILY_FINALIZATION_DELAY_MINUTES
    )
    current_midnight = datetime.datetime.combine(
        observed.date(), datetime.time(), UTC
    )
    if observed >= current_midnight + delay:
        return observed.date() - datetime.timedelta(days=1)
    return observed.date() - datetime.timedelta(days=2)


def _tree_bytes(path: pathlib.Path) -> int:
    if path.is_file():
        return path.stat().st_size
    if not path.exists():
        return 0
    return sum(value.stat().st_size for value in path.rglob("*") if value.is_file())


def audit_forward_storage(config: ForwardObserverConfig) -> dict:
    context = verify_implementation_lock(config)
    symbols = list(context["cointegration_market"]["symbols"])
    records = load_daily_records(
        config.archive_root,
        raw_root=config.raw_root,
        expected_symbols=symbols,
    )
    decisions = load_decision_journal(config.journal_path)
    official_records = [
        value
        for value in records
        if datetime.date.fromisoformat(value["bar_date"])
        >= protocol.FORWARD_START
    ]
    if len(decisions) > len(official_records):
        raise DataQualityError("decision journal exceeds market evidence")
    return {
        "schema_version": SCHEMA_VERSION,
        "observer_type": OBSERVER_TYPE,
        "archive_consistent": True,
        "raw_archive_consistent": True,
        "journal_consistent": True,
        "orders_authorized": False,
        "daily_records": len(records),
        "warmup_records": len(records) - len(official_records),
        "official_records": len(official_records),
        "decision_records": len(decisions),
        "last_market_record_hash": (
            records[-1]["record_hash"] if records else None
        ),
        "last_journal_hash": (
            decisions[-1]["journal_record_hash"] if decisions else None
        ),
        "storage_bytes": {
            "daily_archive": _tree_bytes(config.archive_root),
            "raw_archive": _tree_bytes(config.raw_root),
            "decision_journal": _tree_bytes(config.journal_path),
        },
    }


def run_forward_once(
    config: ForwardObserverConfig,
    *,
    now: typing.Optional[datetime.datetime] = None,
    fetch_bytes: typing.Optional[FetchBytes] = None,
) -> dict:
    """Collect every mature missing day and append reproducible targets."""

    config.validate()
    attempted_at = (now or datetime.datetime.now(UTC)).astimezone(UTC)
    for path in (
        config.archive_root,
        config.raw_root,
        config.journal_path.parent,
        config.health_path.parent,
        config.runner_lock_path.parent,
    ):
        path.mkdir(parents=True, exist_ok=True)
    with config.runner_lock_path.open("a+", encoding="utf-8") as lock_stream:
        try:
            fcntl.flock(
                lock_stream.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB
            )
        except BlockingIOError as error:
            raise RuntimeError("diversified forward observer is already active") from error
        try:
            context = verify_implementation_lock(config)
            symbols = list(context["cointegration_market"]["symbols"])
            records = load_daily_records(
                config.archive_root, expected_symbols=symbols
            )
            latest_mature = min(
                _latest_mature_bar(attempted_at),
                protocol.FORWARD_CUTOFF_EXCLUSIVE
                - datetime.timedelta(days=1),
            )
            next_date = (
                datetime.date.fromisoformat(records[-1]["bar_date"])
                + datetime.timedelta(days=1)
                if records
                else protocol.WARMUP_START
            )
            fetched_count = 0
            if next_date <= latest_mature:
                fetched = fetch_public_daily_range(
                    symbols,
                    next_date,
                    latest_mature + datetime.timedelta(days=1),
                    raw_root=config.raw_root,
                    maximum_workers=config.maximum_workers,
                    timeout_seconds=config.timeout_seconds,
                    fetch_bytes=fetch_bytes,
                )
                appended = append_daily_records(
                    config.archive_root,
                    fetched,
                    expected_symbols=symbols,
                    collected_at=attempted_at,
                )
                fetched_count = len(appended)
            records = load_daily_records(
                config.archive_root, expected_symbols=symbols
            )
            payloads = []
            if records and datetime.date.fromisoformat(records[-1]["bar_date"]) >= protocol.FORWARD_START:
                cointegration_market = extend_cointegration_market(
                    context["cointegration_market"], records
                )
                trend_market = extend_trend_market(
                    context["trend_market"],
                    context["cointegration_market"],
                    records,
                )
                payloads = _bind_decision_lineage(
                    build_decision_payloads(
                        trend_market,
                        cointegration_market,
                        context["trend_config"],
                        context["null"],
                        records,
                    ),
                    context,
                )
            journal = append_decision_payloads(
                config.journal_path,
                payloads,
                recorded_at=attempted_at,
            )
            official_records = sum(
                datetime.date.fromisoformat(value["bar_date"])
                >= protocol.FORWARD_START
                for value in records
            )
            last_bar = records[-1]["bar_date"] if records else None
            gate_calendar_complete = bool(
                records
                and datetime.date.fromisoformat(records[-1]["bar_date"])
                >= protocol.FORWARD_CUTOFF_EXCLUSIVE
                - datetime.timedelta(days=1)
            )
            health = {
                "schema_version": SCHEMA_VERSION,
                "observer_type": OBSERVER_TYPE,
                "mode": "forward_observation_only",
                "research_only": True,
                "public_data_only": True,
                "credentials_used": False,
                "orders_authorized": False,
                "paper_orders_authorized": False,
                "automatic_promotion": False,
                "status": "healthy",
                "phase": (
                    "warmup"
                    if latest_mature < protocol.FORWARD_START
                    else "forward"
                ),
                "last_attempt_at": attempted_at.isoformat(),
                "last_success_at": datetime.datetime.now(UTC).isoformat(),
                "latest_mature_bar": latest_mature.isoformat(),
                "last_archived_bar": last_bar,
                "fetched_days_this_cycle": fetched_count,
                "daily_records": len(records),
                "warmup_records": len(records) - official_records,
                "official_records": official_records,
                "decision_records": journal["total_records"],
                "decisions_appended_this_cycle": journal["appended_records"],
                "protocol_sha256": context["protocol"]["protocol_sha256"],
                "implementation_lock_sha256": context["implementation_lock"][
                    "implementation_lock_sha256"
                ],
                "last_market_record_hash": (
                    records[-1]["record_hash"] if records else None
                ),
                "last_journal_hash": journal["last_journal_hash"],
                "earliest_gate_evaluation_not_before_utc": (
                    context["protocol"]["timeline"][
                        "earliest_gate_evaluation_not_before_utc"
                    ]
                ),
                "gate_calendar_complete": gate_calendar_complete,
                "gate_evaluation_authorized": False,
                "orders_or_paper_authorized": False,
                "storage_bytes": {
                    "daily_archive": _tree_bytes(config.archive_root),
                    "raw_archive": _tree_bytes(config.raw_root),
                    "decision_journal": _tree_bytes(config.journal_path),
                },
            }
            _write_json_atomic(config.health_path, health)
            return health
        except Exception as error:
            previous = {}
            if config.health_path.is_file():
                try:
                    previous = json.loads(
                        config.health_path.read_text(encoding="utf-8")
                    )
                except (OSError, ValueError):
                    previous = {}
            _write_json_atomic(
                config.health_path,
                {
                    "schema_version": SCHEMA_VERSION,
                    "observer_type": OBSERVER_TYPE,
                    "mode": "forward_observation_only",
                    "public_data_only": True,
                    "credentials_used": False,
                    "orders_authorized": False,
                    "paper_orders_authorized": False,
                    "automatic_promotion": False,
                    "status": "failed",
                    "last_attempt_at": attempted_at.isoformat(),
                    "last_success_at": previous.get("last_success_at"),
                    "error_type": type(error).__name__,
                    "error": str(error),
                },
            )
            raise


def _add_common_paths(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--protocol", type=pathlib.Path, required=True)
    parser.add_argument("--implementation-lock", type=pathlib.Path, required=True)
    parser.add_argument("--parent-protocol", type=pathlib.Path, required=True)
    parser.add_argument("--selected-model", type=pathlib.Path, required=True)
    parser.add_argument("--training-report", type=pathlib.Path, required=True)
    parser.add_argument("--training-manifest", type=pathlib.Path, required=True)
    parser.add_argument("--training-trajectory", type=pathlib.Path, required=True)
    parser.add_argument("--snapshot", type=pathlib.Path, required=True)
    parser.add_argument("--history", type=pathlib.Path, required=True)
    parser.add_argument("--null", type=pathlib.Path, required=True)
    parser.add_argument("--archive-root", type=pathlib.Path, required=True)
    parser.add_argument("--raw-root", type=pathlib.Path, required=True)
    parser.add_argument("--journal", type=pathlib.Path, required=True)
    parser.add_argument("--health", type=pathlib.Path, required=True)
    parser.add_argument("--runner-lock", type=pathlib.Path, required=True)
    parser.add_argument("--timeout-seconds", type=float, default=45.0)
    parser.add_argument("--maximum-workers", type=int, default=8)


def _config_from_arguments(arguments) -> ForwardObserverConfig:
    return ForwardObserverConfig(
        protocol_path=arguments.protocol,
        implementation_lock_path=arguments.implementation_lock,
        parent_protocol_path=arguments.parent_protocol,
        selected_model_path=arguments.selected_model,
        training_report_path=arguments.training_report,
        training_manifest_path=arguments.training_manifest,
        training_trajectory_path=arguments.training_trajectory,
        snapshot_path=arguments.snapshot,
        history_path=arguments.history,
        null_path=arguments.null,
        archive_root=arguments.archive_root,
        raw_root=arguments.raw_root,
        journal_path=arguments.journal,
        health_path=arguments.health,
        runner_lock_path=arguments.runner_lock,
        timeout_seconds=arguments.timeout_seconds,
        maximum_workers=arguments.maximum_workers,
    )


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)
    for name in ("freeze-implementation", "run-once", "audit"):
        child = subparsers.add_parser(name)
        _add_common_paths(child)
    return parser


def main(argv: typing.Optional[list[str]] = None) -> int:
    arguments = _parser().parse_args(argv)
    config = _config_from_arguments(arguments)
    if arguments.command == "freeze-implementation":
        result = create_or_verify_implementation_lock(config)
    elif arguments.command == "run-once":
        result = run_forward_once(config)
    else:
        result = audit_forward_storage(config)
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
