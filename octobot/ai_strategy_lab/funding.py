"""Download and load point-in-time KuCoin perpetual funding rates."""

from __future__ import annotations

import datetime
import hashlib
import json
import pathlib
import time
import typing
import urllib.parse
import urllib.request

import numpy


KUCOIN_PUBLIC_FUNDING_URL = (
    "https://api-futures.kucoin.com/api/v1/contract/funding-rates"
)
FUNDING_SCHEMA_VERSION = 1


def fetch_kucoin_funding(
    symbol_mapping: dict[str, str],
    start_timestamp_ms: int,
    end_timestamp_ms: int,
    *,
    chunk_days: int = 30,
) -> dict:
    if not symbol_mapping:
        raise ValueError("at least one OctoBot-to-KuCoin symbol mapping is required")
    if start_timestamp_ms >= end_timestamp_ms:
        raise ValueError("funding start timestamp must precede end timestamp")
    if chunk_days < 1:
        raise ValueError("chunk_days must be positive")

    chunk_ms = chunk_days * 24 * 3600 * 1000
    rates = {}
    for octobot_symbol, kucoin_symbol in sorted(symbol_mapping.items()):
        points = {}
        chunk_start = start_timestamp_ms
        while chunk_start < end_timestamp_ms:
            chunk_end = min(end_timestamp_ms, chunk_start + chunk_ms)
            query = urllib.parse.urlencode(
                {
                    "symbol": kucoin_symbol,
                    "from": chunk_start,
                    "to": chunk_end,
                }
            )
            request = urllib.request.Request(
                f"{KUCOIN_PUBLIC_FUNDING_URL}?{query}",
                headers={"User-Agent": "OctoBot-AI-Lab/1"},
            )
            with urllib.request.urlopen(request, timeout=30) as response:
                payload = json.load(response)
            if payload.get("code") != "200000":
                raise RuntimeError(
                    f"KuCoin funding request failed for {kucoin_symbol}: {payload}"
                )
            for point in payload.get("data", []):
                timestamp = int(point["timepoint"])
                if start_timestamp_ms <= timestamp <= end_timestamp_ms:
                    points[timestamp] = float(point["fundingRate"])
            chunk_start = chunk_end + 1
            time.sleep(0.05)
        rates[octobot_symbol] = [
            {"timestamp_ms": timestamp, "rate": points[timestamp]}
            for timestamp in sorted(points)
        ]
    return {
        "schema_version": FUNDING_SCHEMA_VERSION,
        "source": KUCOIN_PUBLIC_FUNDING_URL,
        "retrieved_at": datetime.datetime.now(datetime.timezone.utc).isoformat(),
        "start_timestamp_ms": start_timestamp_ms,
        "end_timestamp_ms": end_timestamp_ms,
        "symbol_mapping": symbol_mapping,
        "rates": rates,
    }


def save_funding(payload: dict, output_value: typing.Union[str, pathlib.Path]) -> dict:
    output = pathlib.Path(output_value).resolve()
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(
        json.dumps(payload, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return {
        "path": str(output),
        "sha256": _sha256(output),
        "bytes": output.stat().st_size,
        "points": {
            symbol: len(points)
            for symbol, points in payload["rates"].items()
        },
    }


def load_funding(
    path_value: typing.Union[str, pathlib.Path],
) -> dict[str, tuple[numpy.ndarray, numpy.ndarray]]:
    path = pathlib.Path(path_value).resolve()
    payload = json.loads(path.read_text(encoding="utf-8"))
    if payload.get("schema_version") != FUNDING_SCHEMA_VERSION:
        raise ValueError("unsupported funding file schema")
    result = {}
    for symbol, points in payload.get("rates", {}).items():
        ordered = sorted(points, key=lambda value: int(value["timestamp_ms"]))
        timestamps = numpy.asarray(
            [int(value["timestamp_ms"]) // 1000 for value in ordered],
            dtype=numpy.int64,
        )
        rates = numpy.asarray(
            [float(value["rate"]) for value in ordered],
            dtype=numpy.float64,
        )
        if len(timestamps) and numpy.any(numpy.diff(timestamps) <= 0):
            raise ValueError(f"funding timestamps are duplicated for {symbol}")
        if not numpy.all(numpy.isfinite(rates)):
            raise ValueError(f"funding rates contain non-finite values for {symbol}")
        result[symbol] = (timestamps, rates)
    return result


def parse_utc_date(value: str, *, end_of_day: bool = False) -> int:
    parsed = datetime.datetime.strptime(value, "%Y-%m-%d").replace(
        tzinfo=datetime.timezone.utc
    )
    if end_of_day:
        parsed += datetime.timedelta(days=1)
    return int(parsed.timestamp() * 1000)


def _sha256(path: pathlib.Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()
