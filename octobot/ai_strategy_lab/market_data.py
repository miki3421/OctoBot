"""Reproducible public-market-data collectors for cross-exchange research."""

from __future__ import annotations

import csv
import dataclasses
import datetime
import hashlib
import io
import json
import os
import pathlib
import sqlite3
import tempfile
import time
import typing
import urllib.error
import urllib.request
import zipfile


BINANCE_ARCHIVE_ROOT = "https://data.binance.vision/data/futures/um/monthly"
COLLECTOR_SCHEMA_VERSION = 1
TIME_FRAME_SECONDS = {"15m": 900, "1h": 3600, "4h": 14400}


@dataclasses.dataclass(frozen=True)
class BinanceArchiveConfig:
    symbol_mapping: dict[str, str]
    start_date: datetime.date
    end_date: datetime.date

    def validate(self) -> None:
        if not self.symbol_mapping:
            raise ValueError("at least one symbol mapping is required")
        if self.start_date > self.end_date:
            raise ValueError("start date must not follow end date")
        for octobot_symbol, archive_symbol in self.symbol_mapping.items():
            if not octobot_symbol or not archive_symbol:
                raise ValueError("symbol mappings cannot be empty")


def fetch_binance_archive(
    config: BinanceArchiveConfig,
    output_value: typing.Union[str, pathlib.Path],
    *,
    funding_output_value: typing.Optional[typing.Union[str, pathlib.Path]] = None,
    cache_value: typing.Optional[typing.Union[str, pathlib.Path]] = None,
) -> dict:
    """Build an OctoBot-compatible collector from checksummed Binance archives."""

    config.validate()
    output = pathlib.Path(output_value).resolve()
    output.parent.mkdir(parents=True, exist_ok=True)
    cache = (
        pathlib.Path(cache_value).resolve()
        if cache_value is not None
        else output.parent / ".binance-archive-cache"
    )
    cache.mkdir(parents=True, exist_ok=True)

    archive_manifest = []
    series_by_symbol = {}
    funding_by_symbol = {}
    for octobot_symbol, archive_symbol in sorted(config.symbol_mapping.items()):
        candles = {}
        funding_points = {}
        for year, month in _iter_months(config.start_date, config.end_date):
            candle_name = f"{archive_symbol}-15m-{year:04d}-{month:02d}.zip"
            candle_path = (
                f"klines/{archive_symbol}/15m/{candle_name}"
            )
            candle_bytes, candle_record = _download_verified_archive(
                candle_path, cache
            )
            archive_manifest.append(candle_record)
            for candle in parse_binance_kline_archive(candle_bytes):
                open_date = datetime.datetime.fromtimestamp(
                    candle[0], datetime.timezone.utc
                ).date()
                if config.start_date <= open_date <= config.end_date:
                    candles[int(candle[0])] = candle

            if funding_output_value is not None:
                funding_name = (
                    f"{archive_symbol}-fundingRate-{year:04d}-{month:02d}.zip"
                )
                funding_path = (
                    f"fundingRate/{archive_symbol}/{funding_name}"
                )
                funding_bytes, funding_record = _download_verified_archive(
                    funding_path, cache
                )
                archive_manifest.append(funding_record)
                for timestamp_ms, rate in parse_binance_funding_archive(
                    funding_bytes
                ):
                    point_date = datetime.datetime.fromtimestamp(
                        timestamp_ms / 1000, datetime.timezone.utc
                    ).date()
                    if config.start_date <= point_date <= config.end_date:
                        funding_points[timestamp_ms] = rate

        ordered = [candles[key] for key in sorted(candles)]
        _validate_contiguous_15m(octobot_symbol, ordered)
        series_by_symbol[octobot_symbol] = {
            "15m": ordered,
            "1h": aggregate_candles(ordered, 4),
            "4h": aggregate_candles(ordered, 16),
        }
        funding_by_symbol[octobot_symbol] = [
            {"timestamp_ms": key, "rate": funding_points[key]}
            for key in sorted(funding_points)
        ]

    _write_collector_atomic(output, series_by_symbol, config)
    collector_sha = _sha256(output)
    manifest = {
        "schema_version": COLLECTOR_SCHEMA_VERSION,
        "created_at": datetime.datetime.now(datetime.timezone.utc).isoformat(),
        "source": BINANCE_ARCHIVE_ROOT,
        "research_only": True,
        "collector_path": str(output),
        "collector_sha256": collector_sha,
        "collector_bytes": output.stat().st_size,
        "config": {
            "symbol_mapping": config.symbol_mapping,
            "start_date": config.start_date.isoformat(),
            "end_date": config.end_date.isoformat(),
        },
        "archives": archive_manifest,
        "coverage": {
            symbol: {
                time_frame: {
                    "rows": len(candles),
                    "first_open_timestamp": int(candles[0][0]),
                    "last_open_timestamp": int(candles[-1][0]),
                }
                for time_frame, candles in time_frames.items()
            }
            for symbol, time_frames in series_by_symbol.items()
        },
    }
    manifest_path = output.with_suffix(output.suffix + ".manifest.json")
    manifest_path.write_text(
        json.dumps(manifest, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )

    result = {
        "collector": {
            "path": str(output),
            "sha256": collector_sha,
            "bytes": output.stat().st_size,
        },
        "manifest": str(manifest_path),
        "coverage": manifest["coverage"],
    }
    if funding_output_value is not None:
        funding_output = pathlib.Path(funding_output_value).resolve()
        funding_output.parent.mkdir(parents=True, exist_ok=True)
        funding_payload = {
            "schema_version": 1,
            "source": f"{BINANCE_ARCHIVE_ROOT}/fundingRate",
            "retrieved_at": datetime.datetime.now(
                datetime.timezone.utc
            ).isoformat(),
            "start_timestamp_ms": int(
                datetime.datetime.combine(
                    config.start_date,
                    datetime.time.min,
                    datetime.timezone.utc,
                ).timestamp()
                * 1000
            ),
            "end_timestamp_ms": int(
                datetime.datetime.combine(
                    config.end_date + datetime.timedelta(days=1),
                    datetime.time.min,
                    datetime.timezone.utc,
                ).timestamp()
                * 1000
            ),
            "symbol_mapping": config.symbol_mapping,
            "rates": funding_by_symbol,
        }
        funding_output.write_text(
            json.dumps(funding_payload, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        result["funding"] = {
            "path": str(funding_output),
            "sha256": _sha256(funding_output),
            "bytes": funding_output.stat().st_size,
            "points": {
                symbol: len(points)
                for symbol, points in funding_by_symbol.items()
            },
        }
    return result


def parse_binance_kline_archive(archive: bytes) -> list[list[float]]:
    rows = _read_single_csv_archive(archive)
    candles = []
    for row in rows:
        if row and row[0] == "open_time":
            continue
        if len(row) < 6:
            raise ValueError("invalid Binance kline row")
        timestamp_ms = int(row[0])
        if timestamp_ms >= 10**15:
            timestamp_ms //= 1000
        candles.append(
            [
                timestamp_ms // 1000,
                float(row[1]),
                float(row[2]),
                float(row[3]),
                float(row[4]),
                float(row[5]),
            ]
        )
    return candles


def parse_binance_funding_archive(archive: bytes) -> list[tuple[int, float]]:
    rows = _read_single_csv_archive(archive)
    points = []
    for row in rows:
        if row and row[0] == "calc_time":
            continue
        if len(row) < 3:
            raise ValueError("invalid Binance funding row")
        points.append((int(row[0]), float(row[2])))
    return points


def aggregate_candles(
    candles: list[list[float]], bars_per_bucket: int
) -> list[list[float]]:
    if bars_per_bucket < 1:
        raise ValueError("bars_per_bucket must be positive")
    interval = 900 * bars_per_bucket
    buckets: dict[int, list[list[float]]] = {}
    for candle in candles:
        bucket = int(candle[0]) // interval * interval
        buckets.setdefault(bucket, []).append(candle)
    result = []
    for timestamp in sorted(buckets):
        rows = buckets[timestamp]
        if len(rows) != bars_per_bucket:
            continue
        if any(
            int(rows[index][0]) - int(rows[index - 1][0]) != 900
            for index in range(1, len(rows))
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
    return result


def _download_verified_archive(
    relative_path: str, cache: pathlib.Path
) -> tuple[bytes, dict]:
    archive_url = f"{BINANCE_ARCHIVE_ROOT}/{relative_path}"
    checksum_url = f"{archive_url}.CHECKSUM"
    cache_path = cache / relative_path
    checksum_path = cache_path.with_suffix(cache_path.suffix + ".CHECKSUM")
    cache_path.parent.mkdir(parents=True, exist_ok=True)
    if not cache_path.exists():
        _download_to(archive_url, cache_path)
    if not checksum_path.exists():
        _download_to(checksum_url, checksum_path)
    expected = checksum_path.read_text(encoding="utf-8").split()[0].lower()
    actual = _sha256(cache_path)
    if actual != expected:
        raise ValueError(
            f"checksum mismatch for {relative_path}: {actual} != {expected}"
        )
    return cache_path.read_bytes(), {
        "relative_path": relative_path,
        "sha256": actual,
        "bytes": cache_path.stat().st_size,
    }


def _download_to(url: str, destination: pathlib.Path) -> None:
    for attempt in range(3):
        request = urllib.request.Request(
            url, headers={"User-Agent": "OctoBot-AI-Lab/1"}
        )
        try:
            with urllib.request.urlopen(request, timeout=60) as response:
                payload = response.read()
            temporary = destination.with_suffix(destination.suffix + ".partial")
            temporary.write_bytes(payload)
            os.replace(temporary, destination)
            return
        except (urllib.error.URLError, TimeoutError):
            if attempt == 2:
                raise
            time.sleep(0.5 * (2**attempt))


def _read_single_csv_archive(archive: bytes) -> list[list[str]]:
    with zipfile.ZipFile(io.BytesIO(archive)) as zipped:
        files = [name for name in zipped.namelist() if not name.endswith("/")]
        if len(files) != 1:
            raise ValueError("expected exactly one CSV in archive")
        with zipped.open(files[0]) as stream:
            return list(
                csv.reader(
                    io.TextIOWrapper(stream, encoding="utf-8", newline="")
                )
            )


def _validate_contiguous_15m(
    symbol: str, candles: list[list[float]]
) -> None:
    if len(candles) < 1000:
        raise ValueError(f"insufficient 15m candles for {symbol}")
    gaps = [
        (int(previous[0]), int(current[0]))
        for previous, current in zip(candles, candles[1:])
        if int(current[0]) - int(previous[0]) != 900
    ]
    if gaps:
        raise ValueError(
            f"{symbol} contains {len(gaps)} 15m gaps; first={gaps[0]}"
        )


def _write_collector_atomic(
    output: pathlib.Path,
    series_by_symbol: dict[str, dict[str, list[list[float]]]],
    config: BinanceArchiveConfig,
) -> None:
    handle, temporary_name = tempfile.mkstemp(
        prefix=f".{output.name}.", suffix=".tmp", dir=str(output.parent)
    )
    os.close(handle)
    temporary = pathlib.Path(temporary_name)
    try:
        connection = sqlite3.connect(temporary)
        connection.execute(
            "CREATE TABLE description (timestamp datetime, version text, "
            "type text, exchange text, symbols text, time_frames text, "
            "start_timestamp text, end_timestamp)"
        )
        connection.execute(
            "CREATE TABLE ohlcv (timestamp datetime, exchange_name text, "
            "cryptocurrency text, symbol text, time_frame text, candle)"
        )
        now = int(datetime.datetime.now(datetime.timezone.utc).timestamp())
        connection.execute(
            "INSERT INTO description VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (
                now,
                "ai-lab-binance-archive-v1",
                "research_only",
                "binance",
                json.dumps(sorted(config.symbol_mapping)),
                json.dumps(sorted(TIME_FRAME_SECONDS)),
                config.start_date.isoformat(),
                config.end_date.isoformat(),
            ),
        )
        for symbol, time_frames in sorted(series_by_symbol.items()):
            cryptocurrency = symbol.split("/", 1)[0]
            for time_frame, candles in sorted(time_frames.items()):
                close_offset = TIME_FRAME_SECONDS[time_frame]
                connection.executemany(
                    "INSERT INTO ohlcv VALUES (?, ?, ?, ?, ?, ?)",
                    (
                        (
                            int(candle[0]) + close_offset,
                            "binance",
                            cryptocurrency,
                            symbol,
                            time_frame,
                            json.dumps(candle, separators=(",", ":")),
                        )
                        for candle in candles
                    ),
                )
        connection.commit()
        integrity = connection.execute("PRAGMA integrity_check").fetchone()
        if not integrity or integrity[0] != "ok":
            raise ValueError("generated collector failed integrity check")
        connection.close()
        os.replace(temporary, output)
    finally:
        if temporary.exists():
            temporary.unlink()


def _iter_months(
    start_date: datetime.date, end_date: datetime.date
) -> typing.Iterator[tuple[int, int]]:
    year, month = start_date.year, start_date.month
    while (year, month) <= (end_date.year, end_date.month):
        yield year, month
        month += 1
        if month == 13:
            year += 1
            month = 1


def parse_date(value: str) -> datetime.date:
    return datetime.datetime.strptime(value, "%Y-%m-%d").date()


def _sha256(path: pathlib.Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()
