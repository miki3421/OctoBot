"""Public-data-only acquisition and evaluation for Category Momentum V1.

The frozen protocol lives in :mod:`category_momentum_v1`.  This module uses
only public HTTP GET endpoints, creates content-addressed offline artifacts and
has no authenticated exchange or order capability.
"""

from __future__ import annotations

import argparse
import datetime
import gzip
import hashlib
import json
import math
import os
import pathlib
import shutil
import statistics
import tempfile
import time
import typing
import urllib.error
import urllib.parse
import urllib.request

import numpy

from octobot.ai_strategy_lab import category_momentum_v1 as protocol_module
from octobot.ai_strategy_lab import cointegration_pairs_v1 as common


SCHEMA_VERSION = 1
UTC = datetime.timezone.utc
DAY_SECONDS = 86_400
DAY_MILLISECONDS = DAY_SECONDS * 1000
SNAPSHOT_CUTOFF = datetime.datetime(2026, 8, 28, tzinfo=UTC)
HISTORY_START = datetime.datetime(2022, 4, 1, tzinfo=UTC)
HISTORY_END = protocol_module.LOCKED_END
BINANCE_API_ROOT = "https://fapi.binance.com"
COINGECKO_API_ROOT = "https://api.coingecko.com"
APPROVED_HOSTS = {"fapi.binance.com", "api.coingecko.com"}
APPROVED_PATH_PREFIXES = {
    "fapi.binance.com": (
        "/fapi/v1/exchangeInfo",
        "/fapi/v1/klines",
        "/fapi/v1/fundingRate",
    ),
    "api.coingecko.com": (
        "/api/v3/coins/categories/list",
        "/api/v3/coins/markets",
    ),
}
STABLE_BASES = {
    "BUSD",
    "DAI",
    "FDUSD",
    "FRAX",
    "PYUSD",
    "TUSD",
    "USDC",
    "USDE",
    "USDP",
    "USDT",
}
SPECIAL_BASE_ALIASES = {
    "BEAMX": "beam",
    "DODOX": "dodo",
    "LUNA2": "luna",
}


class DataQualityError(ValueError):
    """Raised when a public source violates a frozen data-quality invariant."""


def _canonical_json_bytes(value: object) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")


def _sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _artifact(path: pathlib.Path, root: pathlib.Path) -> dict:
    return {
        "path": str(path.relative_to(root)),
        "bytes": path.stat().st_size,
        "sha256": common._sha256(path),
    }


def _atomic_bytes(path: pathlib.Path, payload: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(
        prefix=f".{path.name}.", suffix=".tmp", dir=str(path.parent)
    )
    temporary = pathlib.Path(temporary_name)
    try:
        with os.fdopen(descriptor, "wb") as handle:
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    finally:
        if temporary.exists():
            temporary.unlink()


def _require_no_official_artifact(
    output_root: pathlib.Path, pattern: str, label: str
) -> None:
    existing = sorted(output_root.glob(pattern))
    if existing:
        raise FileExistsError(
            f"{label} is single-run and already exists: {existing[0]}"
        )


def _verify_manifest_content_hash(manifest: dict, label: str) -> None:
    claimed = manifest.get("content_sha256")
    unsigned = {
        key: value
        for key, value in manifest.items()
        if key != "content_sha256"
    }
    if not claimed or common._json_hash(unsigned) != claimed:
        raise DataQualityError(f"{label} manifest content hash mismatch")


def _store_raw_json(
    root: pathlib.Path,
    relative_path: str,
    payload: bytes,
) -> dict:
    parsed = json.loads(payload.decode("utf-8"))
    canonical = _canonical_json_bytes(parsed)
    path = root / relative_path
    compressed = gzip.compress(payload, compresslevel=9, mtime=0)
    _atomic_bytes(path, compressed)
    result = _artifact(path, root)
    result.update(
        {
            "response_sha256": _sha256_bytes(payload),
            "canonical_json_sha256": _sha256_bytes(canonical),
            "uncompressed_bytes": len(payload),
        }
    )
    return result


def _read_gzip_json(path: pathlib.Path):
    return json.loads(gzip.decompress(path.read_bytes()).decode("utf-8"))


def _validate_public_url(url: str) -> None:
    parsed = urllib.parse.urlparse(url)
    if parsed.scheme != "https" or parsed.hostname not in APPROVED_HOSTS:
        raise ValueError(f"URL is not an approved public source: {url}")
    prefixes = APPROVED_PATH_PREFIXES[typing.cast(str, parsed.hostname)]
    if not any(parsed.path == prefix for prefix in prefixes):
        raise ValueError(f"URL path is not approved: {url}")
    if parsed.username or parsed.password:
        raise ValueError("credentials are forbidden in source URLs")


def _public_get(
    url: str,
    *,
    timeout: float = 45.0,
    attempts: int = 8,
    sleeper: typing.Callable[[float], None] = time.sleep,
) -> bytes:
    _validate_public_url(url)
    request = urllib.request.Request(
        url,
        headers={
            "Accept": "application/json",
            "Accept-Encoding": "identity",
            "User-Agent": "octobot-category-momentum-research/1",
        },
        method="GET",
    )
    for attempt in range(attempts):
        try:
            with urllib.request.urlopen(request, timeout=timeout) as response:
                _validate_public_url(response.geturl())
                if response.status != 200:
                    raise DataQualityError(
                        f"unexpected HTTP status {response.status} for {url}"
                    )
                return response.read()
        except urllib.error.HTTPError as error:
            if error.code not in {418, 429, 500, 502, 503, 504}:
                raise
            if attempt + 1 >= attempts:
                raise
            retry_after = error.headers.get("Retry-After")
            delay = float(retry_after) if retry_after else min(60.0, 2**attempt)
            sleeper(max(1.0, delay))
        except (TimeoutError, urllib.error.URLError):
            if attempt + 1 >= attempts:
                raise
            sleeper(min(30.0, 2**attempt))
    raise RuntimeError("unreachable public GET retry state")


def _query_url(root: str, path: str, parameters: dict) -> str:
    return f"{root}{path}?{urllib.parse.urlencode(parameters)}"


def _load_frozen_protocol(path_value: typing.Union[str, pathlib.Path]) -> dict:
    path = pathlib.Path(path_value).resolve()
    persisted = json.loads(path.read_text(encoding="utf-8"))
    frozen = protocol_module.frozen_protocol()
    expected = {**frozen, "protocol_sha256": common._json_hash(frozen)}
    if persisted != expected:
        raise ValueError("Category Momentum protocol is not the frozen version")
    return persisted


def _normalized_base(base: str) -> str:
    upper = base.upper()
    if upper in SPECIAL_BASE_ALIASES:
        return SPECIAL_BASE_ALIASES[upper]
    if upper.startswith("1000") and len(upper) > 4:
        return upper[4:].lower()
    return upper.lower()


def _eligible_contracts(exchange_info: dict) -> list[dict]:
    minimum_onboard = int(
        (
            SNAPSHOT_CUTOFF
            - datetime.timedelta(days=protocol_module.MINIMUM_LISTING_AGE_DAYS)
        ).timestamp()
        * 1000
    )
    result = []
    for value in exchange_info.get("symbols", []):
        base = str(value.get("baseAsset", "")).upper()
        if not (
            value.get("status") == "TRADING"
            and value.get("contractType") == "PERPETUAL"
            and value.get("quoteAsset") == "USDT"
            and value.get("marginAsset") == "USDT"
            and value.get("underlyingType") == "COIN"
            and int(value.get("onboardDate", 0)) <= minimum_onboard
            and base not in STABLE_BASES
        ):
            continue
        result.append(
            {
                "symbol": str(value["symbol"]),
                "base_asset": base,
                "normalized_base": _normalized_base(base),
                "onboard_timestamp_ms": int(value["onboardDate"]),
            }
        )
    return sorted(result, key=lambda value: value["symbol"])


def _parse_liquidity_rows(rows: list) -> dict:
    start_ms = int(
        (
            SNAPSHOT_CUTOFF
            - datetime.timedelta(days=protocol_module.LIQUIDITY_LOOKBACK_DAYS)
        ).timestamp()
        * 1000
    )
    end_ms = int(SNAPSHOT_CUTOFF.timestamp() * 1000)
    expected = list(
        range(start_ms, end_ms, DAY_MILLISECONDS)
    )
    by_open = {}
    for row in rows:
        if not isinstance(row, list) or len(row) < 8:
            raise DataQualityError("invalid Binance daily kline row")
        open_time = int(row[0])
        if start_ms <= open_time < end_ms:
            quote_volume = float(row[7])
            if not math.isfinite(quote_volume) or quote_volume < 0:
                raise DataQualityError("invalid daily quote volume")
            by_open[open_time] = quote_volume
    if sorted(by_open) != expected:
        raise DataQualityError(
            f"liquidity window is incomplete: {len(by_open)}/{len(expected)}"
        )
    values = [by_open[timestamp] for timestamp in expected]
    return {
        "days": len(values),
        "median_daily_quote_volume": float(statistics.median(values)),
        "minimum_daily_quote_volume": float(min(values)),
        "maximum_daily_quote_volume": float(max(values)),
    }


def _taxonomy_mapping(
    contracts: list[dict], category_payloads: dict[str, list]
) -> tuple[dict[str, dict], dict[str, set[str]], list[dict]]:
    candidates: dict[str, dict[str, dict]] = {}
    categories_by_coin: dict[str, set[str]] = {}
    for category_id, coins in category_payloads.items():
        if not isinstance(coins, list):
            raise DataQualityError(f"category {category_id} is not a list")
        for coin in coins:
            coin_id = str(coin.get("id", ""))
            symbol = str(coin.get("symbol", "")).lower()
            market_cap_value = coin.get("market_cap")
            market_cap = (
                float(market_cap_value)
                if market_cap_value is not None
                and math.isfinite(float(market_cap_value))
                else -1.0
            )
            if not coin_id or not symbol:
                continue
            candidates.setdefault(symbol, {})[coin_id] = {
                "coin_id": coin_id,
                "name": str(coin.get("name", "")),
                "snapshot_market_cap": market_cap,
            }
            categories_by_coin.setdefault(coin_id, set()).add(category_id)

    mapping = {}
    collisions = []
    for contract in contracts:
        symbol_candidates = list(
            candidates.get(contract["normalized_base"], {}).values()
        )
        symbol_candidates.sort(
            key=lambda value: (
                -value["snapshot_market_cap"],
                value["coin_id"],
            )
        )
        if not symbol_candidates:
            continue
        selected = symbol_candidates[0]
        mapping[contract["symbol"]] = {
            **selected,
            "categories": sorted(categories_by_coin[selected["coin_id"]]),
        }
        if len(symbol_candidates) > 1:
            collisions.append(
                {
                    "binance_symbol": contract["symbol"],
                    "normalized_base": contract["normalized_base"],
                    "selected_coin_id": selected["coin_id"],
                    "candidates": symbol_candidates,
                }
            )
    category_members = {
        category_id: {
            symbol
            for symbol, value in mapping.items()
            if category_id in value["categories"]
        }
        for category_id in category_payloads
    }
    return mapping, category_members, collisions


def _representative_categories(
    category_members: dict[str, set[str]],
) -> list[str]:
    candidates = [
        category_id
        for category_id, members in category_members.items()
        if len(members) >= protocol_module.MINIMUM_CATEGORY_ASSETS
    ]
    candidates.sort(key=lambda value: (-len(category_members[value]), value))
    accepted = []
    for category_id in candidates:
        members = category_members[category_id]
        if all(
            len(members & category_members[other])
            / min(len(members), len(category_members[other]))
            <= protocol_module.MAXIMUM_CATEGORY_OVERLAP
            for other in accepted
        ):
            accepted.append(category_id)
    return accepted


def _snapshot_payloads(
    fetcher: typing.Callable[[str], bytes],
    sleeper: typing.Callable[[float], None],
) -> tuple[dict, bytes, bytes, dict[str, bytes], dict[str, bytes]]:
    exchange_raw = fetcher(f"{BINANCE_API_ROOT}/fapi/v1/exchangeInfo")
    exchange = json.loads(exchange_raw.decode("utf-8"))
    category_list_raw = fetcher(
        f"{COINGECKO_API_ROOT}/api/v3/coins/categories/list"
    )
    category_payloads_raw = {}
    for index, category_id in enumerate(protocol_module.COINGECKO_CATEGORY_IDS):
        if index:
            sleeper(13.0)
        url = _query_url(
            COINGECKO_API_ROOT,
            "/api/v3/coins/markets",
            {
                "vs_currency": "usd",
                "category": category_id,
                "order": "market_cap_desc",
                "per_page": 250,
                "page": 1,
                "sparkline": "false",
            },
        )
        category_payloads_raw[category_id] = fetcher(url)

    liquidity_raw = {}
    start_ms = int(
        (
            SNAPSHOT_CUTOFF
            - datetime.timedelta(days=protocol_module.LIQUIDITY_LOOKBACK_DAYS)
        ).timestamp()
        * 1000
    )
    end_ms = int(SNAPSHOT_CUTOFF.timestamp() * 1000) - 1
    for contract in _eligible_contracts(exchange):
        url = _query_url(
            BINANCE_API_ROOT,
            "/fapi/v1/klines",
            {
                "symbol": contract["symbol"],
                "interval": "1d",
                "startTime": start_ms,
                "endTime": end_ms,
                "limit": protocol_module.LIQUIDITY_LOOKBACK_DAYS,
            },
        )
        liquidity_raw[contract["symbol"]] = fetcher(url)
    return (
        exchange,
        exchange_raw,
        category_list_raw,
        category_payloads_raw,
        liquidity_raw,
    )


def snapshot_sources(
    protocol_value: typing.Union[str, pathlib.Path],
    output_root_value: typing.Union[str, pathlib.Path],
    *,
    fetcher: typing.Callable[[str], bytes] = _public_get,
    sleeper: typing.Callable[[float], None] = time.sleep,
) -> dict:
    """Freeze public taxonomy and liquidity inputs before historical outcomes."""

    protocol = _load_frozen_protocol(protocol_value)
    output_root = pathlib.Path(output_root_value).resolve()
    output_root.mkdir(parents=True, exist_ok=True)
    prefix = f"source-snapshot-{protocol['protocol_sha256'][:12]}-*"
    _require_no_official_artifact(output_root, prefix, "source snapshot")
    temporary = pathlib.Path(
        tempfile.mkdtemp(prefix=".source-snapshot.", dir=str(output_root))
    )
    try:
        (
            exchange,
            exchange_raw,
            category_list_raw,
            categories_raw,
            liquidity_raw,
        ) = _snapshot_payloads(fetcher, sleeper)
        contracts = _eligible_contracts(exchange)
        raw_artifacts = []
        raw_artifacts.append(
            _store_raw_json(
                temporary,
                "raw/binance-exchange-info.json.gz",
                exchange_raw,
            )
        )
        raw_artifacts.append(
            _store_raw_json(
                temporary,
                "raw/coingecko-category-list.json.gz",
                category_list_raw,
            )
        )
        category_list = json.loads(category_list_raw.decode("utf-8"))
        if not isinstance(category_list, list):
            raise DataQualityError("CoinGecko category list is not a list")
        available_category_ids = {
            str(value.get("category_id", ""))
            for value in category_list
            if isinstance(value, dict)
        }
        missing_category_ids = sorted(
            set(protocol_module.COINGECKO_CATEGORY_IDS)
            - available_category_ids
        )
        if missing_category_ids:
            raise DataQualityError(
                f"frozen CoinGecko categories are absent: {missing_category_ids}"
            )
        category_payloads = {}
        for category_id in protocol_module.COINGECKO_CATEGORY_IDS:
            raw = categories_raw[category_id]
            category_payloads[category_id] = json.loads(raw.decode("utf-8"))
            raw_artifacts.append(
                _store_raw_json(
                    temporary,
                    f"raw/coingecko-memberships/{category_id}.json.gz",
                    raw,
                )
            )

        liquidity = {}
        liquidity_failures = []
        for contract in contracts:
            symbol = contract["symbol"]
            raw = liquidity_raw[symbol]
            raw_artifacts.append(
                _store_raw_json(
                    temporary,
                    f"raw/binance-liquidity/{symbol}.json.gz",
                    raw,
                )
            )
            try:
                liquidity[symbol] = _parse_liquidity_rows(
                    json.loads(raw.decode("utf-8"))
                )
            except DataQualityError as error:
                liquidity_failures.append(
                    {"symbol": symbol, "reason": str(error)}
                )

        mapping, category_members, collisions = _taxonomy_mapping(
            contracts, category_payloads
        )
        by_symbol = {value["symbol"]: value for value in contracts}
        ranked = [
            symbol
            for symbol in mapping
            if symbol in liquidity
        ]
        ranked.sort(
            key=lambda symbol: (
                -liquidity[symbol]["median_daily_quote_volume"],
                symbol,
            )
        )
        selected_symbols = ranked[: protocol_module.UNIVERSE_MAX_ASSETS]
        if not selected_symbols:
            raise DataQualityError("source snapshot selected no contracts")
        selected_set = set(selected_symbols)
        selected_categories = {
            category_id: sorted(members & selected_set)
            for category_id, members in category_members.items()
        }
        representative = _representative_categories(
            {key: set(value) for key, value in selected_categories.items()}
        )
        universe = {
            "schema_version": SCHEMA_VERSION,
            "snapshot_cutoff": SNAPSHOT_CUTOFF.isoformat(),
            "selection": (
                "top 120 median 28-day daily quote volume after structural "
                "and taxonomy filters"
            ),
            "eligible_structural_contracts": len(contracts),
            "mapped_contracts": len(mapping),
            "liquidity_complete_contracts": len(liquidity),
            "selected_contracts": len(selected_symbols),
            "symbols": [
                {
                    **by_symbol[symbol],
                    **mapping[symbol],
                    **liquidity[symbol],
                }
                for symbol in selected_symbols
            ],
            "excluded_liquidity_failures": liquidity_failures,
            "mapping_collisions": collisions,
            "special_base_aliases": SPECIAL_BASE_ALIASES,
            "generic_1000_prefix_removed": True,
        }
        taxonomy = {
            "schema_version": SCHEMA_VERSION,
            "snapshot_cutoff": SNAPSHOT_CUTOFF.isoformat(),
            "provider": "CoinGecko public API",
            "categories": [
                {
                    "category_id": category_id,
                    "snapshot_coin_count": len(category_payloads[category_id]),
                    "selected_universe_members": selected_categories[category_id],
                    "selected_member_count": len(selected_categories[category_id]),
                }
                for category_id in protocol_module.COINGECKO_CATEGORY_IDS
            ],
            "representative_categories_at_snapshot": representative,
            "representative_category_count": len(representative),
            "historical_taxonomy_is_point_in_time": False,
        }
        common._atomic_json(temporary / "universe.json", universe)
        common._atomic_json(temporary / "taxonomy.json", taxonomy)
        artifacts = sorted(raw_artifacts, key=lambda value: value["path"])
        derived = [
            _artifact(temporary / "universe.json", temporary),
            _artifact(temporary / "taxonomy.json", temporary),
        ]
        source_files = [
            pathlib.Path(protocol_module.__file__).resolve(),
            pathlib.Path(__file__).resolve(),
        ]
        source_bundle = {
            "protocol_sha256": protocol["protocol_sha256"],
            "snapshot_cutoff": SNAPSHOT_CUTOFF.isoformat(),
            "raw_artifacts": artifacts,
            "derived_artifacts": derived,
            "source_files": [
                {
                    "name": value.name,
                    "sha256": common._sha256(value),
                    "bytes": value.stat().st_size,
                }
                for value in source_files
            ],
        }
        source_bundle_sha256 = common._json_hash(source_bundle)
        manifest = {
            "schema_version": SCHEMA_VERSION,
            "created_at": datetime.datetime.now(UTC).isoformat(),
            "research_only": True,
            "public_data_only": True,
            "credentials_used": False,
            "orders_authorized": False,
            "paper_orders_authorized": False,
            "automatic_promotion": False,
            **source_bundle,
            "source_bundle_sha256": source_bundle_sha256,
        }
        manifest["content_sha256"] = common._json_hash(manifest)
        common._atomic_json(temporary / "manifest.json", manifest)
        target = output_root / (
            f"source-snapshot-{protocol['protocol_sha256'][:12]}-"
            f"{source_bundle_sha256[:12]}"
        )
        if target.exists():
            raise FileExistsError(f"source snapshot already exists: {target}")
        os.replace(temporary, target)
        return {
            "directory": str(target),
            "manifest": manifest,
            "universe": universe,
            "taxonomy": taxonomy,
        }
    except Exception:
        if temporary.exists():
            shutil.rmtree(temporary)
        raise


def _verify_artifacts(root: pathlib.Path, artifacts: list[dict]) -> None:
    for artifact in artifacts:
        path = root / artifact["path"]
        if not path.is_file() or common._sha256(path) != artifact["sha256"]:
            raise DataQualityError(f"artifact hash mismatch: {path}")


def _load_snapshot(
    path_value: typing.Union[str, pathlib.Path], protocol_sha256: str
) -> tuple[pathlib.Path, dict, dict, dict]:
    root = pathlib.Path(path_value).resolve()
    manifest = json.loads((root / "manifest.json").read_text(encoding="utf-8"))
    _verify_manifest_content_hash(manifest, "source snapshot")
    if manifest["protocol_sha256"] != protocol_sha256:
        raise ValueError("source snapshot protocol mismatch")
    if any(
        manifest.get(key) is not expected
        for key, expected in (
            ("research_only", True),
            ("public_data_only", True),
            ("credentials_used", False),
            ("orders_authorized", False),
            ("paper_orders_authorized", False),
        )
    ):
        raise ValueError("unsafe source snapshot metadata")
    _verify_artifacts(root, manifest["raw_artifacts"])
    _verify_artifacts(root, manifest["derived_artifacts"])
    expected_source_files = {
        pathlib.Path(protocol_module.__file__).resolve().name: common._sha256(
            pathlib.Path(protocol_module.__file__).resolve()
        ),
        pathlib.Path(__file__).resolve().name: common._sha256(
            pathlib.Path(__file__).resolve()
        ),
    }
    persisted_source_files = {
        value["name"]: value["sha256"] for value in manifest["source_files"]
    }
    if persisted_source_files != expected_source_files:
        raise ValueError("research source changed after source snapshot freeze")
    universe = json.loads((root / "universe.json").read_text(encoding="utf-8"))
    taxonomy = json.loads((root / "taxonomy.json").read_text(encoding="utf-8"))
    return root, manifest, universe, taxonomy


def _fetch_pages(
    symbol: str,
    kind: str,
    fetcher: typing.Callable[[str], bytes],
    sleeper: typing.Callable[[float], None],
) -> list[bytes]:
    start_ms = int(HISTORY_START.timestamp() * 1000)
    end_ms = int(HISTORY_END.timestamp() * 1000) - 1
    pages = []
    cursor = start_ms
    while cursor <= end_ms:
        if kind == "klines":
            path = "/fapi/v1/klines"
            parameters = {
                "symbol": symbol,
                "interval": "1d",
                "startTime": cursor,
                "endTime": end_ms,
                "limit": 1500,
            }
        elif kind == "funding":
            path = "/fapi/v1/fundingRate"
            parameters = {
                "symbol": symbol,
                "startTime": cursor,
                "endTime": end_ms,
                "limit": 1000,
            }
        else:
            raise ValueError("kind must be klines or funding")
        raw = fetcher(_query_url(BINANCE_API_ROOT, path, parameters))
        rows = json.loads(raw.decode("utf-8"))
        if not isinstance(rows, list):
            raise DataQualityError(f"{symbol} {kind} response is not a list")
        pages.append(raw)
        if not rows:
            break
        last_timestamp = int(
            rows[-1][0] if kind == "klines" else rows[-1]["fundingTime"]
        )
        next_cursor = (
            last_timestamp + DAY_MILLISECONDS
            if kind == "klines"
            else last_timestamp + 1
        )
        if next_cursor <= cursor:
            raise DataQualityError(f"{symbol} {kind} pagination did not advance")
        cursor = next_cursor
        if len(rows) < (1500 if kind == "klines" else 1000):
            break
        if kind == "funding":
            sleeper(0.7)
    return pages


def _rows_from_pages(pages: list[bytes]) -> list:
    result = []
    for raw in pages:
        result.extend(json.loads(raw.decode("utf-8")))
    return result


def _build_market_panel(
    symbols: list[str],
    klines_by_symbol: dict[str, list],
    funding_by_symbol: dict[str, list],
) -> tuple[dict, dict]:
    first_boundary = HISTORY_START + datetime.timedelta(days=1)
    boundaries = []
    value = first_boundary
    while value <= HISTORY_END:
        boundaries.append(int(value.timestamp()))
        value += datetime.timedelta(days=1)
    timestamps = numpy.asarray(boundaries, dtype=numpy.int64)
    index_by_timestamp = {value: index for index, value in enumerate(boundaries)}
    shape = (len(boundaries), len(symbols))
    closes = numpy.full(shape, numpy.nan, dtype=numpy.float64)
    quote_volumes = numpy.full(shape, numpy.nan, dtype=numpy.float64)
    funding_rates = numpy.zeros(shape, dtype=numpy.float64)
    funding_counts = numpy.zeros(shape, dtype=numpy.int16)
    coverage = {}

    for column, symbol in enumerate(symbols):
        seen_opens = set()
        for row in klines_by_symbol[symbol]:
            if not isinstance(row, list) or len(row) < 8:
                raise DataQualityError(f"invalid daily kline for {symbol}")
            open_ms = int(row[0])
            if open_ms % DAY_MILLISECONDS:
                raise DataQualityError(f"unaligned daily kline for {symbol}")
            if open_ms in seen_opens:
                raise DataQualityError(f"duplicate daily kline for {symbol}")
            seen_opens.add(open_ms)
            boundary = open_ms // 1000 + DAY_SECONDS
            index = index_by_timestamp.get(boundary)
            if index is None:
                continue
            close = float(row[4])
            quote_volume = float(row[7])
            if not (
                math.isfinite(close)
                and close > 0
                and math.isfinite(quote_volume)
                and quote_volume >= 0
            ):
                raise DataQualityError(f"invalid kline value for {symbol}")
            closes[index, column] = close
            quote_volumes[index, column] = quote_volume

        seen_funding = set()
        for point in funding_by_symbol[symbol]:
            timestamp_ms = int(point["fundingTime"])
            if timestamp_ms in seen_funding:
                raise DataQualityError(f"duplicate funding point for {symbol}")
            seen_funding.add(timestamp_ms)
            rate = float(point["fundingRate"])
            if not math.isfinite(rate):
                raise DataQualityError(f"invalid funding rate for {symbol}")
            timestamp_seconds = timestamp_ms // 1000
            boundary = (
                (timestamp_seconds + DAY_SECONDS - 1) // DAY_SECONDS
            ) * DAY_SECONDS
            index = index_by_timestamp.get(boundary)
            if index is None:
                continue
            funding_rates[index, column] += rate
            funding_counts[index, column] += 1

        finite = numpy.flatnonzero(numpy.isfinite(closes[:, column]))
        if not len(finite):
            raise DataQualityError(f"no historical daily prices for {symbol}")
        first, last = int(finite[0]), int(finite[-1])
        price_gaps = int(numpy.sum(~numpy.isfinite(closes[first : last + 1, column])))
        funding_gaps = int(
            numpy.sum(funding_counts[first + 1 : last + 1, column] == 0)
        )
        coverage[symbol] = {
            "price_rows": int(len(finite)),
            "first_boundary": datetime.datetime.fromtimestamp(
                boundaries[first], UTC
            ).isoformat(),
            "last_boundary": datetime.datetime.fromtimestamp(
                boundaries[last], UTC
            ).isoformat(),
            "internal_price_gaps": price_gaps,
            "funding_interval_gaps": funding_gaps,
            "funding_points": len(seen_funding),
        }

    panel = {
        "timestamps": timestamps,
        "symbols": numpy.asarray(symbols),
        "closes": closes,
        "quote_volumes": quote_volumes,
        "funding_rates": funding_rates,
        "funding_counts": funding_counts,
    }
    return panel, coverage


def fetch_history(
    protocol_value: typing.Union[str, pathlib.Path],
    snapshot_value: typing.Union[str, pathlib.Path],
    output_root_value: typing.Union[str, pathlib.Path],
    *,
    fetcher: typing.Callable[[str], bytes] = _public_get,
    sleeper: typing.Callable[[float], None] = time.sleep,
) -> dict:
    """Freeze daily price and signed funding history for the selected universe."""

    protocol = _load_frozen_protocol(protocol_value)
    snapshot_root, snapshot_manifest, universe, taxonomy = _load_snapshot(
        snapshot_value, protocol["protocol_sha256"]
    )
    if (
        taxonomy["representative_category_count"]
        < protocol_module.MINIMUM_REPRESENTATIVE_CATEGORIES
    ):
        raise DataQualityError(
            "source snapshot cannot form the frozen minimum number of "
            "representative categories; historical outcomes remain unread"
        )
    output_root = pathlib.Path(output_root_value).resolve()
    output_root.mkdir(parents=True, exist_ok=True)
    prefix = f"history-{protocol['protocol_sha256'][:12]}-*"
    _require_no_official_artifact(output_root, prefix, "history freeze")
    temporary = pathlib.Path(
        tempfile.mkdtemp(prefix=".history.", dir=str(output_root))
    )
    try:
        symbols = [value["symbol"] for value in universe["symbols"]]
        raw_artifacts = []
        klines_by_symbol = {}
        funding_by_symbol = {}
        for symbol in symbols:
            kline_pages = _fetch_pages(symbol, "klines", fetcher, sleeper)
            funding_pages = _fetch_pages(symbol, "funding", fetcher, sleeper)
            for index, raw in enumerate(kline_pages):
                raw_artifacts.append(
                    _store_raw_json(
                        temporary,
                        f"raw/klines/{symbol}/page-{index:03d}.json.gz",
                        raw,
                    )
                )
            for index, raw in enumerate(funding_pages):
                raw_artifacts.append(
                    _store_raw_json(
                        temporary,
                        f"raw/funding/{symbol}/page-{index:03d}.json.gz",
                        raw,
                    )
                )
            klines_by_symbol[symbol] = _rows_from_pages(kline_pages)
            funding_by_symbol[symbol] = _rows_from_pages(funding_pages)
        panel, coverage = _build_market_panel(
            symbols, klines_by_symbol, funding_by_symbol
        )
        dataset_path = temporary / "market-panel.npz"
        numpy.savez_compressed(dataset_path, **panel)
        coverage_path = temporary / "coverage.json"
        common._atomic_json(
            coverage_path,
            {
                "schema_version": SCHEMA_VERSION,
                "history_start": HISTORY_START.isoformat(),
                "history_end_exclusive": HISTORY_END.isoformat(),
                "symbols": coverage,
            },
        )
        artifacts = sorted(raw_artifacts, key=lambda value: value["path"])
        derived = [
            _artifact(dataset_path, temporary),
            _artifact(coverage_path, temporary),
        ]
        source_file = pathlib.Path(__file__).resolve()
        bundle = {
            "protocol_sha256": protocol["protocol_sha256"],
            "source_snapshot_bundle_sha256": snapshot_manifest[
                "source_bundle_sha256"
            ],
            "history_start": HISTORY_START.isoformat(),
            "history_end_exclusive": HISTORY_END.isoformat(),
            "symbols": symbols,
            "raw_artifacts": artifacts,
            "derived_artifacts": derived,
            "research_source_sha256": common._sha256(source_file),
            "research_source_bytes": source_file.stat().st_size,
        }
        history_bundle_sha256 = common._json_hash(bundle)
        manifest = {
            "schema_version": SCHEMA_VERSION,
            "created_at": datetime.datetime.now(UTC).isoformat(),
            "research_only": True,
            "public_data_only": True,
            "credentials_used": False,
            "orders_authorized": False,
            "paper_orders_authorized": False,
            "automatic_promotion": False,
            **bundle,
            "history_bundle_sha256": history_bundle_sha256,
        }
        manifest["content_sha256"] = common._json_hash(manifest)
        common._atomic_json(temporary / "manifest.json", manifest)
        target = output_root / (
            f"history-{protocol['protocol_sha256'][:12]}-"
            f"{history_bundle_sha256[:12]}"
        )
        if target.exists():
            raise FileExistsError(f"history already exists: {target}")
        os.replace(temporary, target)
        return {
            "directory": str(target),
            "manifest": manifest,
            "coverage": coverage,
            "snapshot_directory": str(snapshot_root),
        }
    except Exception:
        if temporary.exists():
            shutil.rmtree(temporary)
        raise


def _load_history(
    path_value: typing.Union[str, pathlib.Path],
    protocol_sha256: str,
    snapshot_bundle_sha256: str,
) -> tuple[pathlib.Path, dict, dict]:
    root = pathlib.Path(path_value).resolve()
    manifest = json.loads((root / "manifest.json").read_text(encoding="utf-8"))
    _verify_manifest_content_hash(manifest, "history")
    if manifest["protocol_sha256"] != protocol_sha256:
        raise ValueError("history protocol mismatch")
    if manifest["source_snapshot_bundle_sha256"] != snapshot_bundle_sha256:
        raise ValueError("history source snapshot mismatch")
    if any(
        manifest.get(key) is not expected
        for key, expected in (
            ("research_only", True),
            ("public_data_only", True),
            ("credentials_used", False),
            ("orders_authorized", False),
            ("paper_orders_authorized", False),
        )
    ):
        raise ValueError("unsafe history metadata")
    if common._sha256(pathlib.Path(__file__).resolve()) != manifest[
        "research_source_sha256"
    ]:
        raise ValueError("research source changed after history freeze")
    _verify_artifacts(root, manifest["raw_artifacts"])
    _verify_artifacts(root, manifest["derived_artifacts"])
    with numpy.load(root / "market-panel.npz", allow_pickle=False) as values:
        market = {key: values[key] for key in values.files}
    return root, manifest, market


def _capped_weights(values: numpy.ndarray, cap: float) -> numpy.ndarray:
    values = numpy.asarray(values, dtype=numpy.float64)
    if values.ndim != 1 or not len(values):
        raise ValueError("category weights require a non-empty vector")
    if not numpy.all(numpy.isfinite(values)) or numpy.any(values < 0):
        raise ValueError("category weight inputs must be finite and nonnegative")
    if len(values) * cap < 1.0 - 1e-12:
        raise ValueError("weight cap is infeasible for category membership")
    weights = numpy.zeros(len(values), dtype=numpy.float64)
    active = list(range(len(values)))
    remaining = 1.0
    while active:
        active_values = values[active]
        denominator = float(numpy.sum(active_values))
        proposed = (
            numpy.full(len(active), remaining / len(active))
            if denominator <= 0
            else remaining * active_values / denominator
        )
        over = [
            active[position]
            for position, value in enumerate(proposed)
            if value > cap + 1e-15
        ]
        if not over:
            for position, index in enumerate(active):
                weights[index] = proposed[position]
            break
        for index in over:
            weights[index] = cap
            active.remove(index)
            remaining -= cap
    if not numpy.isclose(numpy.sum(weights), 1.0, atol=1e-12):
        raise RuntimeError("category weights do not sum to one")
    if numpy.max(weights) > cap + 1e-12:
        raise RuntimeError("category weight cap was exceeded")
    return weights


def _eligible_symbol_indices(market: dict, index: int) -> list[int]:
    required = protocol_module.MINIMUM_CONTIGUOUS_HISTORY_DAYS
    if index + 1 < required:
        return []
    closes = market["closes"]
    volumes = market["quote_volumes"]
    price_window = closes[index - required + 1 : index + 1]
    volume_window = volumes[
        index - protocol_module.LIQUIDITY_LOOKBACK_DAYS + 1 : index + 1
    ]
    eligible = (
        numpy.all(numpy.isfinite(price_window), axis=0)
        & numpy.all(price_window > 0, axis=0)
        & numpy.all(numpy.isfinite(volume_window), axis=0)
        & numpy.all(volume_window >= 0, axis=0)
    )
    return [int(value) for value in numpy.flatnonzero(eligible)]


def target_weights(
    market: dict,
    taxonomy: dict,
    index: int,
    *,
    excluded_symbols: typing.AbstractSet[str] = frozenset(),
    excluded_categories: typing.AbstractSet[str] = frozenset(),
) -> tuple[numpy.ndarray, dict]:
    """Build one causal target using data available at ``index`` only."""

    symbols = [str(value) for value in market["symbols"]]
    symbol_to_column = {symbol: column for column, symbol in enumerate(symbols)}
    eligible_columns = set(_eligible_symbol_indices(market, index))
    eligible_columns -= {
        symbol_to_column[symbol]
        for symbol in excluded_symbols
        if symbol in symbol_to_column
    }
    category_values = []
    membership = {}
    for value in taxonomy["categories"]:
        category_id = value["category_id"]
        if category_id in excluded_categories:
            continue
        columns = sorted(
            {
                symbol_to_column[symbol]
                for symbol in value["selected_universe_members"]
                if symbol in symbol_to_column
                and symbol not in excluded_symbols
                and symbol_to_column[symbol] in eligible_columns
            }
        )
        if len(columns) < protocol_module.MINIMUM_CATEGORY_ASSETS:
            continue
        volume = numpy.sum(
            market["quote_volumes"][
                index - protocol_module.LIQUIDITY_LOOKBACK_DAYS + 1 : index + 1,
                columns,
            ],
            axis=0,
        )
        within = _capped_weights(
            volume, protocol_module.MAXIMUM_ASSET_CATEGORY_WEIGHT
        )
        formation = (
            market["closes"][index, columns]
            / market["closes"][index - protocol_module.FORMATION_DAYS, columns]
            - 1.0
        )
        score = float(numpy.dot(within, formation))
        membership[category_id] = set(columns)
        category_values.append(
            {
                "category_id": category_id,
                "columns": columns,
                "weights": within,
                "score": score,
            }
        )
    category_values.sort(
        key=lambda value: (-len(value["columns"]), value["category_id"])
    )
    representatives = []
    for value in category_values:
        members = membership[value["category_id"]]
        if all(
            len(members & membership[other["category_id"]])
            / min(len(members), len(membership[other["category_id"]]))
            <= protocol_module.MAXIMUM_CATEGORY_OVERLAP
            for other in representatives
        ):
            representatives.append(value)
    target = numpy.zeros(len(symbols), dtype=numpy.float64)
    if len(representatives) < protocol_module.MINIMUM_REPRESENTATIVE_CATEGORIES:
        return target, {
            "status": "INSUFFICIENT_REPRESENTATIVE_CATEGORIES",
            "eligible_symbols": len(eligible_columns),
            "representative_categories": len(representatives),
            "selected_long": [],
            "selected_short": [],
        }
    count = max(
        1,
        len(representatives) // protocol_module.CATEGORY_SELECTION_DENOMINATOR,
    )
    longs = sorted(
        representatives,
        key=lambda value: (-value["score"], value["category_id"]),
    )[:count]
    long_ids = {value["category_id"] for value in longs}
    shorts = sorted(
        (
            value
            for value in representatives
            if value["category_id"] not in long_ids
        ),
        key=lambda value: (value["score"], value["category_id"]),
    )[:count]
    for sign, selected in ((1.0, longs), (-1.0, shorts)):
        category_allocation = (
            sign * protocol_module.SIDE_GROSS_EXPOSURE / len(selected)
        )
        for value in selected:
            target[value["columns"]] += category_allocation * value["weights"]
    if not numpy.isclose(numpy.sum(target), 0.0, atol=1e-12):
        raise RuntimeError("category momentum target is not nominally neutral")
    if numpy.sum(numpy.abs(target)) > 0.8 + 1e-12:
        raise RuntimeError("category momentum target exceeds gross cap")
    return target, {
        "status": "TARGET",
        "eligible_symbols": len(eligible_columns),
        "representative_categories": len(representatives),
        "selected_long": [value["category_id"] for value in longs],
        "selected_short": [value["category_id"] for value in shorts],
        "long_scores": [value["score"] for value in longs],
        "short_scores": [value["score"] for value in shorts],
    }


def _period_compound_returns(
    dates: list[datetime.datetime], values: numpy.ndarray, format_value: str
) -> dict:
    grouped: dict[str, list[float]] = {}
    for date, value in zip(dates, values):
        grouped.setdefault(date.strftime(format_value), []).append(float(value))
    return {
        key: float(numpy.prod(1.0 + numpy.asarray(group)) - 1.0)
        for key, group in sorted(grouped.items())
    }


def _side_transaction_costs(
    previous: numpy.ndarray,
    target: numpy.ndarray,
    cost_rate: float,
) -> tuple[float, float]:
    long_cost = 0.0
    short_cost = 0.0
    for old, new in zip(previous, target):
        if old >= 0 and new >= 0:
            long_cost += abs(new - old) * cost_rate
        elif old <= 0 and new <= 0:
            short_cost += abs(new - old) * cost_rate
        else:
            if old > 0:
                long_cost += abs(old) * cost_rate
            elif old < 0:
                short_cost += abs(old) * cost_rate
            if new > 0:
                long_cost += abs(new) * cost_rate
            elif new < 0:
                short_cost += abs(new) * cost_rate
    return long_cost, short_cost


def simulate_period(
    market: dict,
    taxonomy: dict,
    start: datetime.datetime,
    end: datetime.datetime,
    *,
    cost_multiplier: float = 1.0,
    excluded_symbols: typing.AbstractSet[str] = frozenset(),
    excluded_categories: typing.AbstractSet[str] = frozenset(),
    include_trajectory: bool = False,
) -> dict:
    """Simulate one half-open interval, opening and closing it from flat."""

    if cost_multiplier < 1.0:
        raise ValueError("cost multiplier must be at least one")
    timestamps = market["timestamps"]
    start_s, end_s = int(start.timestamp()), int(end.timestamp())
    indices = [
        index
        for index in range(len(timestamps) - 1)
        if int(timestamps[index]) >= start_s
        and int(timestamps[index + 1]) <= end_s
    ]
    if not indices:
        raise ValueError("evaluation period is absent from the market panel")
    symbols = [str(value) for value in market["symbols"]]
    previous = numpy.zeros(len(symbols), dtype=numpy.float64)
    per_turnover_cost = cost_multiplier * (
        protocol_module.FEE_PER_TURNOVER
        + protocol_module.SLIPPAGE_PER_TURNOVER
    )
    daily_returns = []
    market_returns = []
    dates = []
    gross_exposure = []
    symbol_contributions = numpy.zeros(len(symbols), dtype=numpy.float64)
    long_contribution = 0.0
    short_contribution = 0.0
    total_price = 0.0
    total_funding = 0.0
    total_cost = 0.0
    total_turnover = 0.0
    invested_days = 0
    selected_category_frequency: dict[str, int] = {}
    ever_targeted_symbols = set()
    insufficient_category_days = 0

    for index in indices:
        target, audit = target_weights(
            market,
            taxonomy,
            index,
            excluded_symbols=excluded_symbols,
            excluded_categories=excluded_categories,
        )
        if audit["status"] != "TARGET":
            insufficient_category_days += 1
        for category_id in audit["selected_long"] + audit["selected_short"]:
            selected_category_frequency[category_id] = (
                selected_category_frequency.get(category_id, 0) + 1
            )
        outcome_close = market["closes"][index + 1]
        current_close = market["closes"][index]
        targeted = numpy.flatnonzero(numpy.abs(target) > 1e-15)
        if len(targeted) and (
            not numpy.all(numpy.isfinite(outcome_close[targeted]))
            or not numpy.all(outcome_close[targeted] > 0)
            or not numpy.all(market["funding_counts"][index + 1, targeted] > 0)
        ):
            raise DataQualityError(
                "a causal target has an incomplete next-day price or funding outcome"
            )
        returns = numpy.zeros(len(symbols), dtype=numpy.float64)
        complete = (
            numpy.isfinite(current_close)
            & numpy.isfinite(outcome_close)
            & (current_close > 0)
            & (outcome_close > 0)
        )
        returns[complete] = outcome_close[complete] / current_close[complete] - 1.0
        price = target * returns
        funding = -target * market["funding_rates"][index + 1]
        delta = target - previous
        cost = numpy.abs(delta) * per_turnover_cost
        contribution = price + funding - cost
        net = float(numpy.sum(contribution))
        if net <= -1.0:
            raise DataQualityError("portfolio return is at or below minus 100 percent")
        daily_returns.append(net)
        valid_market = complete
        market_returns.append(
            float(numpy.mean(returns[valid_market]))
            if numpy.any(valid_market)
            else 0.0
        )
        date = datetime.datetime.fromtimestamp(int(timestamps[index + 1]), UTC)
        dates.append(date)
        gross = float(numpy.sum(numpy.abs(target)))
        gross_exposure.append(gross)
        invested_days += int(gross > 1e-15)
        symbol_contributions += contribution
        total_price += float(numpy.sum(price))
        total_funding += float(numpy.sum(funding))
        total_cost += float(numpy.sum(cost))
        total_turnover += float(numpy.sum(numpy.abs(delta)))
        long_cost, short_cost = _side_transaction_costs(
            previous, target, per_turnover_cost
        )
        long_contribution += float(numpy.sum((price + funding)[target > 0]))
        long_contribution -= long_cost
        short_contribution += float(numpy.sum((price + funding)[target < 0]))
        short_contribution -= short_cost
        ever_targeted_symbols.update(symbols[value] for value in targeted)
        previous = target

    closing_cost = numpy.abs(previous) * per_turnover_cost
    if len(daily_returns):
        daily_returns[-1] -= float(numpy.sum(closing_cost))
    symbol_contributions -= closing_cost
    total_cost += float(numpy.sum(closing_cost))
    total_turnover += float(numpy.sum(numpy.abs(previous)))
    long_contribution -= float(numpy.sum(closing_cost[previous > 0]))
    short_contribution -= float(numpy.sum(closing_cost[previous < 0]))

    daily = numpy.asarray(daily_returns, dtype=numpy.float64)
    benchmark = numpy.asarray(market_returns, dtype=numpy.float64)
    equity = numpy.cumprod(1.0 + daily)
    peaks = numpy.maximum.accumulate(numpy.concatenate((numpy.ones(1), equity)))[1:]
    drawdown = 1.0 - equity / peaks
    elapsed_years = len(daily) / 365.25
    gains = float(numpy.sum(daily[daily > 0]))
    losses = float(-numpy.sum(daily[daily < 0]))
    variance = float(numpy.var(benchmark))
    beta = (
        float(numpy.mean((daily - numpy.mean(daily)) * (benchmark - numpy.mean(benchmark))))
        / variance
        if variance > 0
        else 0.0
    )
    monthly = _period_compound_returns(dates, daily, "%Y-%m")
    # strftime has no quarter token; build the groups explicitly.
    quarter_groups: dict[str, list[float]] = {}
    for date, value in zip(dates, daily):
        key = f"{date.year}-Q{(date.month - 1) // 3 + 1}"
        quarter_groups.setdefault(key, []).append(float(value))
    quarterly = {
        key: float(numpy.prod(1.0 + numpy.asarray(values)) - 1.0)
        for key, values in sorted(quarter_groups.items())
    }
    denominator = float(numpy.sum(numpy.abs(symbol_contributions)))
    report = {
        "start": start.isoformat(),
        "end": end.isoformat(),
        "outcomes": len(daily),
        "invested_days": invested_days,
        "cost_multiplier": cost_multiplier,
        "total_return": float(equity[-1] - 1.0),
        "annualized_return": (
            float(equity[-1] ** (1.0 / elapsed_years) - 1.0)
            if elapsed_years > 0 and equity[-1] > 0
            else -1.0
        ),
        "sharpe_zero_rate": (
            float(numpy.mean(daily) / numpy.std(daily) * math.sqrt(365.0))
            if numpy.std(daily) > 0
            else 0.0
        ),
        "profit_factor": gains / losses if losses > 0 else (math.inf if gains > 0 else 0.0),
        "maximum_drawdown": float(numpy.max(drawdown)),
        "positive_month_ratio": (
            sum(value > 0 for value in monthly.values()) / len(monthly)
            if monthly
            else 0.0
        ),
        "positive_quarters": sum(value > 0 for value in quarterly.values()),
        "months": monthly,
        "quarters": quarterly,
        "market_beta": beta,
        "price_additive_contribution": total_price,
        "funding_additive_contribution": total_funding,
        "cost_additive_contribution": total_cost,
        "long_additive_contribution": long_contribution,
        "short_additive_contribution": short_contribution,
        "total_turnover": total_turnover,
        "average_gross_exposure": float(numpy.mean(gross_exposure)),
        "maximum_gross_exposure": float(numpy.max(gross_exposure)),
        "maximum_symbol_absolute_contribution_share": (
            float(numpy.max(numpy.abs(symbol_contributions)) / denominator)
            if denominator > 0
            else 0.0
        ),
        "symbol_additive_contributions": {
            symbol: float(symbol_contributions[index])
            for index, symbol in enumerate(symbols)
            if abs(symbol_contributions[index]) > 1e-15
        },
        "ever_targeted_symbols": sorted(ever_targeted_symbols),
        "ever_selected_categories": sorted(selected_category_frequency),
        "selected_category_frequency": selected_category_frequency,
        "insufficient_category_days": insufficient_category_days,
    }
    if include_trajectory:
        report["_trajectory"] = {
            "dates": [value.isoformat() for value in dates],
            "daily_return": daily.tolist(),
            "market_return": benchmark.tolist(),
            "equity": equity.tolist(),
            "gross_exposure": gross_exposure,
        }
    return report


def _development_gate(
    report: dict,
    stress: dict,
    positive_folds: int,
    symbol_loo_ratio: float,
    category_loo_ratio: float,
) -> dict:
    gate = protocol_module.frozen_protocol()["development_gate"]
    checks = {
        "minimum_outcomes": report["outcomes"] >= gate["minimum_outcomes"],
        "minimum_invested_days": (
            report["invested_days"] >= gate["minimum_invested_days"]
        ),
        "positive_total_return": report["total_return"] > 0,
        "stress_total_return_positive": stress["total_return"] > 0,
        "minimum_annualized_return": (
            report["annualized_return"] >= gate["minimum_annualized_return"]
        ),
        "minimum_sharpe": report["sharpe_zero_rate"] >= gate["minimum_sharpe"],
        "minimum_profit_factor": (
            report["profit_factor"] >= gate["minimum_profit_factor"]
        ),
        "maximum_drawdown": report["maximum_drawdown"] <= gate["maximum_drawdown"],
        "minimum_positive_month_ratio": (
            report["positive_month_ratio"]
            >= gate["minimum_positive_month_ratio"]
        ),
        "minimum_positive_folds": positive_folds >= gate["minimum_positive_folds"],
        "both_side_contributions_nonnegative": (
            report["long_additive_contribution"] >= 0
            and report["short_additive_contribution"] >= 0
        ),
        "maximum_absolute_market_beta": (
            abs(report["market_beta"])
            <= gate["maximum_absolute_market_beta"]
        ),
        "maximum_symbol_absolute_contribution_share": (
            report["maximum_symbol_absolute_contribution_share"]
            <= gate["maximum_symbol_absolute_contribution_share"]
        ),
        "minimum_positive_leave_one_symbol_out_ratio": (
            symbol_loo_ratio
            >= gate["minimum_positive_leave_one_symbol_out_ratio"]
        ),
        "minimum_positive_leave_one_category_out_ratio": (
            category_loo_ratio
            >= gate["minimum_positive_leave_one_category_out_ratio"]
        ),
    }
    return {"checks": checks, "passed": all(checks.values())}


def _later_gate(report: dict, stress: dict, name: str) -> dict:
    gate = protocol_module.frozen_protocol()[name]
    checks = {
        "minimum_outcomes": report["outcomes"] >= gate["minimum_outcomes"],
        "minimum_invested_days": (
            report["invested_days"] >= gate["minimum_invested_days"]
        ),
        "positive_total_return": report["total_return"] > 0,
        "stress_total_return_positive": stress["total_return"] > 0,
        "minimum_annualized_return": (
            report["annualized_return"] >= gate["minimum_annualized_return"]
        ),
        "minimum_sharpe": report["sharpe_zero_rate"] >= gate["minimum_sharpe"],
        "minimum_profit_factor": (
            report["profit_factor"] >= gate["minimum_profit_factor"]
        ),
        "maximum_drawdown": report["maximum_drawdown"] <= gate["maximum_drawdown"],
        "minimum_positive_month_ratio": (
            report["positive_month_ratio"]
            >= gate["minimum_positive_month_ratio"]
        ),
        "both_side_contributions_nonnegative": (
            report["long_additive_contribution"] >= 0
            and report["short_additive_contribution"] >= 0
        ),
        "maximum_absolute_market_beta": (
            abs(report["market_beta"])
            <= gate["maximum_absolute_market_beta"]
        ),
    }
    if "minimum_positive_quarters" in gate:
        checks["minimum_positive_quarters"] = (
            report["positive_quarters"] >= gate["minimum_positive_quarters"]
        )
    return {"checks": checks, "passed": all(checks.values())}


def _without_trajectory(report: dict) -> dict:
    return {key: value for key, value in report.items() if key != "_trajectory"}


def evaluate(
    protocol_value: typing.Union[str, pathlib.Path],
    snapshot_value: typing.Union[str, pathlib.Path],
    history_value: typing.Union[str, pathlib.Path],
    output_root_value: typing.Union[str, pathlib.Path],
) -> dict:
    """Run the frozen sequential historical diagnostic exactly once."""

    protocol_path = pathlib.Path(protocol_value).resolve()
    protocol = _load_frozen_protocol(protocol_path)
    snapshot_root, snapshot_manifest, _universe, taxonomy = _load_snapshot(
        snapshot_value, protocol["protocol_sha256"]
    )
    history_root, history_manifest, market = _load_history(
        history_value,
        protocol["protocol_sha256"],
        snapshot_manifest["source_bundle_sha256"],
    )
    development_with_trajectory = simulate_period(
        market,
        taxonomy,
        protocol_module.DEVELOPMENT_START,
        protocol_module.DEVELOPMENT_END,
        include_trajectory=True,
    )
    development = _without_trajectory(development_with_trajectory)
    development_stress = simulate_period(
        market,
        taxonomy,
        protocol_module.DEVELOPMENT_START,
        protocol_module.DEVELOPMENT_END,
        cost_multiplier=protocol_module.STRESS_COST_MULTIPLIER,
    )
    folds = []
    for start, end in protocol_module.DEVELOPMENT_FOLDS:
        folds.append(simulate_period(market, taxonomy, start, end))
    positive_folds = sum(value["total_return"] > 0 for value in folds)

    symbol_loo = []
    for symbol in development["ever_targeted_symbols"]:
        result = simulate_period(
            market,
            taxonomy,
            protocol_module.DEVELOPMENT_START,
            protocol_module.DEVELOPMENT_END,
            excluded_symbols={symbol},
        )
        symbol_loo.append({"excluded_symbol": symbol, "report": result})
    category_loo = []
    for category_id in development["ever_selected_categories"]:
        result = simulate_period(
            market,
            taxonomy,
            protocol_module.DEVELOPMENT_START,
            protocol_module.DEVELOPMENT_END,
            excluded_categories={category_id},
        )
        category_loo.append(
            {"excluded_category": category_id, "report": result}
        )
    symbol_loo_ratio = (
        sum(value["report"]["total_return"] > 0 for value in symbol_loo)
        / len(symbol_loo)
        if symbol_loo
        else 0.0
    )
    category_loo_ratio = (
        sum(value["report"]["total_return"] > 0 for value in category_loo)
        / len(category_loo)
        if category_loo
        else 0.0
    )
    development_gate = _development_gate(
        development,
        development_stress,
        positive_folds,
        symbol_loo_ratio,
        category_loo_ratio,
    )

    confirmation = confirmation_stress = confirmation_gate = None
    locked = locked_stress = locked_gate = None
    if development_gate["passed"]:
        confirmation = simulate_period(
            market,
            taxonomy,
            protocol_module.CONFIRMATION_START,
            protocol_module.CONFIRMATION_END,
        )
        confirmation_stress = simulate_period(
            market,
            taxonomy,
            protocol_module.CONFIRMATION_START,
            protocol_module.CONFIRMATION_END,
            cost_multiplier=protocol_module.STRESS_COST_MULTIPLIER,
        )
        confirmation_gate = _later_gate(
            confirmation, confirmation_stress, "confirmation_gate"
        )
        if confirmation_gate["passed"]:
            locked = simulate_period(
                market,
                taxonomy,
                protocol_module.LOCKED_START,
                protocol_module.LOCKED_END,
            )
            locked_stress = simulate_period(
                market,
                taxonomy,
                protocol_module.LOCKED_START,
                protocol_module.LOCKED_END,
                cost_multiplier=protocol_module.STRESS_COST_MULTIPLIER,
            )
            locked_gate = _later_gate(locked, locked_stress, "locked_gate")
    historical_candidate = bool(
        development_gate["passed"]
        and confirmation_gate
        and confirmation_gate["passed"]
        and locked_gate
        and locked_gate["passed"]
    )
    source_sha256 = common._sha256(pathlib.Path(__file__).resolve())
    experiment_key = common._json_hash(
        {
            "protocol_sha256": protocol["protocol_sha256"],
            "snapshot_bundle_sha256": snapshot_manifest["source_bundle_sha256"],
            "history_bundle_sha256": history_manifest["history_bundle_sha256"],
            "research_source_sha256": source_sha256,
        }
    )
    output_root = pathlib.Path(output_root_value).resolve()
    output_root.mkdir(parents=True, exist_ok=True)
    prefix = f"category-momentum-v1-{protocol['protocol_sha256'][:12]}-*"
    _require_no_official_artifact(output_root, prefix, "official evaluation")
    experiment = output_root / (
        f"category-momentum-v1-{protocol['protocol_sha256'][:12]}-"
        f"{experiment_key[:12]}"
    )
    if experiment.exists():
        raise FileExistsError(f"official evaluation already exists: {experiment}")
    temporary = pathlib.Path(
        tempfile.mkdtemp(prefix=".evaluation.", dir=str(output_root))
    )
    try:
        trajectory_path = temporary / "development-trajectory.json"
        common._atomic_json(
            trajectory_path,
            {
                "schema_version": SCHEMA_VERSION,
                "protocol_sha256": protocol["protocol_sha256"],
                **development_with_trajectory["_trajectory"],
            },
        )
        report = {
            "schema_version": SCHEMA_VERSION,
            "protocol_version": protocol_module.PROTOCOL_VERSION,
            "created_at": datetime.datetime.now(UTC).isoformat(),
            "research_only": True,
            "public_data_only": True,
            "credentials_used": False,
            "orders_authorized": False,
            "paper_orders_authorized": False,
            "automatic_promotion": False,
            "protocol_path": str(protocol_path),
            "protocol_file_sha256": common._sha256(protocol_path),
            "protocol_sha256": protocol["protocol_sha256"],
            "source_snapshot_path": str(snapshot_root),
            "source_snapshot_bundle_sha256": snapshot_manifest[
                "source_bundle_sha256"
            ],
            "history_path": str(history_root),
            "history_bundle_sha256": history_manifest["history_bundle_sha256"],
            "research_source_sha256": source_sha256,
            "development": development,
            "development_stress": development_stress,
            "development_folds": folds,
            "development_positive_folds": positive_folds,
            "development_leave_one_symbol_out": symbol_loo,
            "development_positive_leave_one_symbol_out_ratio": symbol_loo_ratio,
            "development_leave_one_category_out": category_loo,
            "development_positive_leave_one_category_out_ratio": category_loo_ratio,
            "development_gate": development_gate,
            "confirmation": confirmation,
            "confirmation_stress": confirmation_stress,
            "confirmation_gate": confirmation_gate,
            "locked_test": locked,
            "locked_test_stress": locked_stress,
            "locked_gate": locked_gate,
            "historical_candidate": historical_candidate,
            "historical_status": (
                "diagnostic_reuse_current_taxonomy_and_survivor_universe"
            ),
            "forward_validation": {
                **protocol["forward_gate"],
                "started": False,
                "passed": False,
                "automatic_promotion": False,
            },
            "development_trajectory": {
                "path": trajectory_path.name,
                "sha256": common._sha256(trajectory_path),
            },
            "verdict": (
                "HISTORICAL_CANDIDATE_REQUIRES_180D_FORWARD"
                if historical_candidate
                else (
                    "REJECTED_LOCKED_TEST"
                    if locked is not None
                    else (
                        "REJECTED_CONFIRMATION_LOCK_REMAINS_SEALED"
                        if confirmation is not None
                        else "REJECTED_DEVELOPMENT_LATER_WINDOWS_UNMATERIALIZED"
                    )
                )
            ),
            "results_do_not_authorize_orders": True,
        }
        report_path = temporary / "report.json"
        common._atomic_json(report_path, report)
        manifest = {
            "schema_version": SCHEMA_VERSION,
            "protocol_sha256": protocol["protocol_sha256"],
            "experiment_key": experiment_key,
            "report_sha256": common._sha256(report_path),
            "trajectory_sha256": common._sha256(trajectory_path),
            "historical_candidate": historical_candidate,
            "confirmation_materialized": confirmation is not None,
            "locked_test_materialized": locked is not None,
            "orders_authorized": False,
            "paper_orders_authorized": False,
            "automatic_promotion": False,
        }
        manifest["content_sha256"] = common._json_hash(manifest)
        common._atomic_json(temporary / "manifest.json", manifest)
        os.replace(temporary, experiment)
        return {"directory": str(experiment), "report": report, "manifest": manifest}
    except Exception:
        if temporary.exists():
            shutil.rmtree(temporary)
        raise


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)
    snapshot = subparsers.add_parser("snapshot-sources")
    snapshot.add_argument("--protocol", required=True)
    snapshot.add_argument("--output-root", required=True)
    history = subparsers.add_parser("fetch-history")
    history.add_argument("--protocol", required=True)
    history.add_argument("--snapshot", required=True)
    history.add_argument("--output-root", required=True)
    evaluator = subparsers.add_parser("evaluate")
    evaluator.add_argument("--protocol", required=True)
    evaluator.add_argument("--snapshot", required=True)
    evaluator.add_argument("--history", required=True)
    evaluator.add_argument("--output-root", required=True)
    return parser


def main(argv=None) -> int:
    args = _parser().parse_args(argv)
    if args.command == "snapshot-sources":
        result = snapshot_sources(args.protocol, args.output_root)
        summary = {
            "directory": result["directory"],
            "source_bundle_sha256": result["manifest"]["source_bundle_sha256"],
            "selected_contracts": result["universe"]["selected_contracts"],
            "representative_categories": result["taxonomy"][
                "representative_category_count"
            ],
            "orders_authorized": False,
        }
    elif args.command == "fetch-history":
        result = fetch_history(args.protocol, args.snapshot, args.output_root)
        summary = {
            "directory": result["directory"],
            "history_bundle_sha256": result["manifest"]["history_bundle_sha256"],
            "symbols": len(result["manifest"]["symbols"]),
            "orders_authorized": False,
        }
    else:
        result = evaluate(
            args.protocol, args.snapshot, args.history, args.output_root
        )
        summary = {
            "directory": result["directory"],
            "verdict": result["report"]["verdict"],
            "development": result["report"]["development"],
            "development_gate": result["report"]["development_gate"],
            "report_sha256": result["manifest"]["report_sha256"],
            "orders_authorized": False,
        }
    print(json.dumps(summary, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
