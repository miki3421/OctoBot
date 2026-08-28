"""Orderless forward observer for breadth-confirmed market momentum V2.

The runner has no downloader.  It verifies and reuses the read-only daily/raw
archive produced by the diversified observer, then appends research decisions
and matured outcomes to its own hash-chained journal.
"""

from __future__ import annotations

import argparse
import contextlib
import datetime
import fcntl
import gzip
import hashlib
import json
import math
import os
import pathlib
import typing
import urllib.parse
from dataclasses import dataclass

import numpy

from octobot.ai_strategy_lab import cointegration_pairs_v1 as common
from octobot.ai_strategy_lab import (
    diversified_trend_cointegration_forward_runner as upstream_runner,
)
from octobot.ai_strategy_lab import (
    liquid_market_breadth_forward_v2 as protocol,
)
from octobot.ai_strategy_lab import (
    liquid_market_timeseries_momentum_v1_research as parent_research,
)


SCHEMA_VERSION = 1
OBSERVER_TYPE = "liquid_market_breadth_forward_observer_v2"
UTC = datetime.timezone.utc
DataQualityError = parent_research.DataQualityError


@dataclass(frozen=True)
class ForwardConfig:
    protocol_path: pathlib.Path
    implementation_lock_path: pathlib.Path
    parent_protocol_path: pathlib.Path
    parent_implementation_lock_path: pathlib.Path
    parent_report_path: pathlib.Path
    parent_manifest_path: pathlib.Path
    parent_trajectory_path: pathlib.Path
    upstream_protocol_path: pathlib.Path
    upstream_implementation_lock_path: pathlib.Path
    snapshot_path: pathlib.Path
    history_path: pathlib.Path
    upstream_daily_root: pathlib.Path
    upstream_raw_root: pathlib.Path
    upstream_health_path: pathlib.Path
    journal_path: pathlib.Path
    health_path: pathlib.Path
    runner_lock_path: pathlib.Path
    runner_test_path: pathlib.Path
    protocol_test_path: pathlib.Path
    entrypoint_path: pathlib.Path


def _canonical_bytes(value: object) -> bytes:
    return json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    ).encode("utf-8")


def _json_hash(value: object) -> str:
    return hashlib.sha256(_canonical_bytes(value)).hexdigest()


def _atomic_json(path: pathlib.Path, value: dict) -> None:
    common._atomic_json(path, value)


def _load_protocol(path: pathlib.Path) -> dict:
    persisted = json.loads(path.read_text(encoding="utf-8"))
    expected = protocol.protocol_payload()
    if persisted != expected:
        raise DataQualityError("breadth-forward protocol differs")
    return persisted


def _verify_parent(config: ForwardConfig) -> dict:
    paths = {
        "protocol": (
            config.parent_protocol_path,
            protocol.PARENT_PROTOCOL_FILE_SHA256,
        ),
        "implementation_lock": (
            config.parent_implementation_lock_path,
            protocol.PARENT_IMPLEMENTATION_LOCK_FILE_SHA256,
        ),
        "report": (config.parent_report_path, protocol.PARENT_REPORT_SHA256),
        "manifest": (
            config.parent_manifest_path,
            protocol.PARENT_MANIFEST_FILE_SHA256,
        ),
        "trajectory": (
            config.parent_trajectory_path,
            protocol.PARENT_TRAJECTORY_SHA256,
        ),
    }
    for label, (path, expected_hash) in paths.items():
        if not path.is_file() or common._sha256(path) != expected_hash:
            raise DataQualityError(f"parent V1 {label} differs")
    parent_protocol = json.loads(
        config.parent_protocol_path.read_text(encoding="utf-8")
    )
    parent_lock = json.loads(
        config.parent_implementation_lock_path.read_text(encoding="utf-8")
    )
    report = json.loads(config.parent_report_path.read_text(encoding="utf-8"))
    manifest = json.loads(
        config.parent_manifest_path.read_text(encoding="utf-8")
    )
    manifest_content = {
        key: value for key, value in manifest.items() if key != "content_sha256"
    }
    checks = (
        parent_protocol.get("protocol_sha256")
        == protocol.PARENT_PROTOCOL_SHA256,
        parent_lock.get("content_sha256")
        == protocol.PARENT_IMPLEMENTATION_LOCK_CONTENT_SHA256,
        report.get("protocol_sha256") == protocol.PARENT_PROTOCOL_SHA256,
        report.get("verdict") == "REJECTED_TRAINING_NO_FORWARD",
        report.get("historical_candidate") is False,
        report.get("orders_authorized") is False,
        report.get("paper_orders_authorized") is False,
        report.get("training_eligibility_gate", {}).get("passed_checks") == 26,
        report.get("training_eligibility_gate", {}).get("total_checks") == 30,
        manifest.get("content_sha256")
        == protocol.PARENT_MANIFEST_CONTENT_SHA256,
        manifest.get("content_sha256") == common._json_hash(manifest_content),
        manifest.get("report_sha256") == protocol.PARENT_REPORT_SHA256,
        manifest.get("trajectory_sha256")
        == protocol.PARENT_TRAJECTORY_SHA256,
        manifest.get("historical_candidate") is False,
        manifest.get("orders_authorized") is False,
        manifest.get("paper_orders_authorized") is False,
    )
    if not all(checks):
        raise DataQualityError("parent V1 evidence metadata differs")
    return {
        label: {
            "logical_id": f"parent_v1_{label}",
            "sha256": expected_hash,
        }
        for label, (_path, expected_hash) in paths.items()
    }


def _verify_upstream(config: ForwardConfig) -> dict:
    files = (
        (
            "protocol",
            config.upstream_protocol_path,
            protocol.UPSTREAM_PROTOCOL_FILE_SHA256,
        ),
        (
            "implementation_lock",
            config.upstream_implementation_lock_path,
            protocol.UPSTREAM_IMPLEMENTATION_LOCK_FILE_SHA256,
        ),
        (
            "runner",
            pathlib.Path(upstream_runner.__file__).resolve(),
            protocol.UPSTREAM_RUNNER_SHA256,
        ),
    )
    for label, path, expected_hash in files:
        if not path.is_file() or common._sha256(path) != expected_hash:
            raise DataQualityError(f"upstream {label} differs")
    upstream_protocol = json.loads(
        config.upstream_protocol_path.read_text(encoding="utf-8")
    )
    upstream_lock = json.loads(
        config.upstream_implementation_lock_path.read_text(encoding="utf-8")
    )
    if (
        upstream_protocol.get("protocol_sha256")
        != protocol.UPSTREAM_PROTOCOL_SHA256
        or upstream_protocol.get("orders_authorized") is not False
        or upstream_protocol.get("paper_orders_authorized") is not False
        or upstream_lock.get("implementation_lock_sha256")
        != protocol.UPSTREAM_IMPLEMENTATION_LOCK_SHA256
        or upstream_lock.get("orders_authorized") is not False
        or upstream_lock.get("paper_orders_authorized") is not False
    ):
        raise DataQualityError("upstream safety lineage differs")
    return {
        label: {
            "logical_id": f"diversified_upstream_{label}",
            "sha256": expected_hash,
        }
        for label, _path, expected_hash in files
    }


def _source_artifacts(config: ForwardConfig) -> list[dict]:
    values = (
        ("runner", pathlib.Path(__file__).resolve()),
        ("protocol_source", pathlib.Path(protocol.__file__).resolve()),
        ("runner_test", config.runner_test_path.resolve()),
        ("protocol_test", config.protocol_test_path.resolve()),
        ("entrypoint", config.entrypoint_path.resolve()),
        ("parent_research", pathlib.Path(parent_research.__file__).resolve()),
        ("upstream_runner", pathlib.Path(upstream_runner.__file__).resolve()),
    )
    artifacts = []
    for label, path in values:
        if not path.is_file():
            raise DataQualityError(f"breadth-forward source absent: {label}")
        artifacts.append(
            {
                "label": label,
                "bytes": path.stat().st_size,
                "sha256": common._sha256(path),
            }
        )
    return artifacts


def _verify_upstream_health(
    config: ForwardConfig,
    records: list[dict],
    now: datetime.datetime,
) -> dict:
    value = json.loads(config.upstream_health_path.read_text(encoding="utf-8"))
    last_success = datetime.datetime.fromisoformat(value["last_success_at"])
    if last_success.tzinfo is None:
        raise DataQualityError("upstream observer health clock lacks timezone")
    last_success = last_success.astimezone(UTC)
    latest = records[-1] if records else None
    checks = (
        value.get("status") == "healthy",
        value.get("observer_type")
        == "diversified_trend_cointegration_forward_observer_v1",
        value.get("protocol_sha256") == protocol.UPSTREAM_PROTOCOL_SHA256,
        value.get("implementation_lock_sha256")
        == protocol.UPSTREAM_IMPLEMENTATION_LOCK_SHA256,
        value.get("credentials_used") is False,
        value.get("orders_authorized") is False,
        value.get("paper_orders_authorized") is False,
        value.get("automatic_promotion") is False,
        value.get("daily_records") == len(records),
        value.get("last_archived_bar")
        == (latest["bar_date"] if latest else None),
        value.get("last_market_record_hash")
        == (latest["record_hash"] if latest else None),
        datetime.timedelta() <= now - last_success < datetime.timedelta(days=2),
    )
    if not all(checks):
        raise DataQualityError("upstream observer health differs")
    return value


def write_or_verify_implementation_lock(config: ForwardConfig) -> dict:
    protocol_payload = _load_protocol(config.protocol_path)
    parent = _verify_parent(config)
    upstream = _verify_upstream(config)
    loaded = parent_research._load_market(
        config.snapshot_path, config.history_path
    )
    frozen = loaded[-1]
    records = upstream_runner.load_daily_records(
        config.upstream_daily_root,
        raw_root=config.upstream_raw_root,
        expected_symbols=list(frozen["symbols"]),
    )
    official = [
        value
        for value in records
        if datetime.date.fromisoformat(value["bar_date"])
        >= protocol.FORWARD_START
    ]
    if official:
        raise DataQualityError("official upstream bars exist before V2 lock")
    if config.journal_path.exists() and config.journal_path.stat().st_size:
        raise DataQualityError("V2 journal is not empty before lock")
    if config.implementation_lock_path.is_file():
        return verify_implementation_lock(config)
    payload = {
        "schema_version": SCHEMA_VERSION,
        "observer_type": OBSERVER_TYPE,
        "created_at": datetime.datetime.now(UTC).isoformat(),
        "status": "implementation_frozen_before_first_forward_bar",
        "protocol_sha256": protocol_payload["protocol_sha256"],
        "protocol_file_sha256": common._sha256(config.protocol_path),
        "parent_evidence": parent,
        "upstream_evidence": upstream,
        "source_artifacts": _source_artifacts(config),
        "numpy_version": numpy.__version__,
        "warmup_records_at_lock": len(records),
        "official_records_at_lock": 0,
        "decision_records_at_lock": 0,
        "v2_historical_outcomes_calculated_before_lock": False,
        "network_capability_required": False,
        "research_only": True,
        "credentials_used": False,
        "orders_authorized": False,
        "paper_orders_authorized": False,
        "automatic_promotion": False,
    }
    payload["implementation_lock_sha256"] = _json_hash(payload)
    _atomic_json(config.implementation_lock_path, payload)
    return payload


def verify_implementation_lock(config: ForwardConfig) -> dict:
    lock = json.loads(
        config.implementation_lock_path.read_text(encoding="utf-8")
    )
    content = {
        key: value
        for key, value in lock.items()
        if key != "implementation_lock_sha256"
    }
    checks = (
        lock.get("implementation_lock_sha256") == _json_hash(content),
        lock.get("status") == "implementation_frozen_before_first_forward_bar",
        lock.get("protocol_sha256")
        == protocol.protocol_payload()["protocol_sha256"],
        lock.get("protocol_file_sha256") == common._sha256(config.protocol_path),
        lock.get("parent_evidence") == _verify_parent(config),
        lock.get("upstream_evidence") == _verify_upstream(config),
        lock.get("source_artifacts") == _source_artifacts(config),
        lock.get("numpy_version") == numpy.__version__,
        lock.get("official_records_at_lock") == 0,
        lock.get("decision_records_at_lock") == 0,
        lock.get("v2_historical_outcomes_calculated_before_lock") is False,
        lock.get("network_capability_required") is False,
        lock.get("research_only") is True,
        lock.get("credentials_used") is False,
        lock.get("orders_authorized") is False,
        lock.get("paper_orders_authorized") is False,
        lock.get("automatic_promotion") is False,
    )
    if not all(checks):
        raise DataQualityError("breadth-forward implementation lock differs")
    return lock


def _parse_kline_quote_volumes(payload: bytes) -> dict[datetime.date, dict]:
    rows = json.loads(payload.decode("utf-8"))
    if not isinstance(rows, list):
        raise DataQualityError("raw daily kline response is not a list")
    parsed = {}
    for row in rows:
        if not isinstance(row, list) or len(row) < 8:
            raise DataQualityError("raw daily kline row is invalid")
        open_ms = int(row[0])
        close_ms = int(row[6])
        if open_ms % 86_400_000 or close_ms != open_ms + 86_400_000 - 1:
            raise DataQualityError("raw daily kline clock differs")
        date = datetime.datetime.fromtimestamp(open_ms / 1000, UTC).date()
        close = float(row[4])
        quote_volume = float(row[7])
        if (
            date in parsed
            or not math.isfinite(close)
            or close <= 0
            or not math.isfinite(quote_volume)
            or quote_volume <= 0
        ):
            raise DataQualityError("raw daily kline value is invalid")
        parsed[date] = {"close": close, "quote_volume": quote_volume}
    return parsed


def quote_volumes_from_records(
    records: list[dict],
    raw_root: pathlib.Path,
    symbols: list[str],
) -> numpy.ndarray:
    """Recover one verified quote-volume value per normalized daily record."""

    cache: dict[str, dict[datetime.date, dict]] = {}
    matrix = numpy.empty((len(records), len(symbols)), dtype=numpy.float64)
    raw_root = raw_root.resolve()
    for row_index, record in enumerate(records):
        date = datetime.date.fromisoformat(record["bar_date"])
        for column, symbol in enumerate(symbols):
            values = record["symbols"][symbol]
            artifact = values["raw"]["daily_klines"]
            parsed_url = urllib.parse.urlparse(artifact["url"])
            query = urllib.parse.parse_qs(parsed_url.query)
            if (
                parsed_url.scheme != "https"
                or parsed_url.hostname != "fapi.binance.com"
                or parsed_url.path != "/fapi/v1/klines"
                or query.get("interval") != ["1d"]
                or query.get("symbol") != [symbol]
            ):
                raise DataQualityError("raw daily kline URL is not approved")
            key = str(artifact["response_sha256"])
            if key not in cache:
                path = (raw_root / artifact["path"]).resolve()
                if not path.is_relative_to(raw_root):
                    raise DataQualityError("raw kline path escapes archive")
                payload = gzip.decompress(path.read_bytes())
                if hashlib.sha256(payload).hexdigest() != key:
                    raise DataQualityError("raw kline content hash differs")
                cache[key] = _parse_kline_quote_volumes(payload)
            if date not in cache[key]:
                raise DataQualityError("raw kline response misses record date")
            raw_value = cache[key][date]
            if not math.isclose(
                raw_value["close"],
                float(values["close"]),
                rel_tol=1e-12,
                abs_tol=0.0,
            ):
                raise DataQualityError("raw and normalized closes differ")
            matrix[row_index, column] = raw_value["quote_volume"]
    return matrix


def load_extended_market(config: ForwardConfig) -> tuple[dict, list[dict]]:
    loaded = parent_research._load_market(config.snapshot_path, config.history_path)
    _snapshot, _snapshot_manifest, _history, _history_manifest, frozen = loaded
    symbols = list(frozen["symbols"])
    records = upstream_runner.load_daily_records(
        config.upstream_daily_root,
        raw_root=config.upstream_raw_root,
        expected_symbols=symbols,
    )
    if records:
        first = datetime.date.fromisoformat(records[0]["bar_date"])
        if (
            first != protocol.WARMUP_START
            or frozen["dates"][-1] + datetime.timedelta(days=1) != first
        ):
            raise DataQualityError("upstream extension does not follow history")
    extension = upstream_runner._records_to_arrays(records, symbols)
    quote_volumes = quote_volumes_from_records(
        records, config.upstream_raw_root, symbols
    )
    dates = list(frozen["dates"]) + extension["dates"]
    closes = numpy.vstack((frozen["closes"], extension["closes"]))
    funding = numpy.vstack((frozen["funding"], extension["funding"]))
    funding_counts = numpy.vstack(
        (frozen["funding_counts"], extension["funding_counts"])
    )
    all_quote_volumes = numpy.vstack(
        (frozen["quote_volumes"], quote_volumes)
    )
    returns = numpy.zeros_like(closes)
    complete = (
        numpy.isfinite(closes[1:])
        & numpy.isfinite(closes[:-1])
        & (closes[1:] > 0)
        & (closes[:-1] > 0)
    )
    calculated_returns = numpy.zeros_like(closes[1:])
    calculated_returns[complete] = (
        closes[1:][complete] / closes[:-1][complete] - 1.0
    )
    returns[1:] = calculated_returns
    market = {
        "dates": dates,
        "timestamps": numpy.asarray(
            [
                int(
                    datetime.datetime.combine(
                        date, datetime.time(), UTC
                    ).timestamp()
                )
                for date in dates
            ],
            dtype=numpy.int64,
        ),
        "symbols": symbols,
        "closes": closes,
        "quote_volumes": all_quote_volumes,
        "returns": returns,
        "return_complete": numpy.vstack(
            (numpy.zeros((1, closes.shape[1]), dtype=bool), complete)
        ),
        "funding": funding,
        "funding_counts": funding_counts,
    }
    return market, records


def breadth_decision(
    market: dict,
    index: int,
    basket: typing.Sequence[int],
    parent_active: bool,
) -> tuple[bool, dict]:
    if not basket:
        return False, {
            "positive_assets": 0,
            "basket_assets": 0,
            "positive_breadth": 0.0,
            "breadth_passed": False,
        }
    closes = numpy.asarray(market["closes"], dtype=numpy.float64)
    formation = protocol.parent.FORMATION_DAYS
    values = closes[index, list(basket)] / closes[
        index - formation, list(basket)
    ] - 1.0
    if not numpy.all(numpy.isfinite(values)):
        raise DataQualityError("forward breadth formation return is invalid")
    positive = int(numpy.sum(values > 0))
    breadth = positive / len(basket)
    passed = breadth >= protocol.MINIMUM_POSITIVE_BREADTH
    return bool(parent_active and passed), {
        "positive_assets": positive,
        "basket_assets": len(basket),
        "positive_breadth": breadth,
        "breadth_passed": passed,
    }


def _target_from_basket(
    asset_count: int,
    basket: typing.Sequence[int],
    active: bool,
) -> numpy.ndarray:
    target = numpy.zeros(asset_count, dtype=numpy.float64)
    if active and basket:
        target[list(basket)] = (
            protocol.parent.VINTAGE_GROSS_EXPOSURE / len(basket)
        )
    return target


def _sparse_weights(symbols: list[str], values: numpy.ndarray) -> dict:
    return {
        symbol: float(values[index])
        for index, symbol in enumerate(symbols)
        if abs(values[index]) > 1e-15
    }


def _outcome(
    market: dict,
    index: int,
    previous: numpy.ndarray,
    target: numpy.ndarray,
    multiplier: float,
) -> dict:
    targeted = numpy.flatnonzero(numpy.abs(target) > 1e-15)
    if len(targeted) and (
        not numpy.all(market["return_complete"][index, targeted])
        or not numpy.all(market["funding_counts"][index, targeted] > 0)
        or not numpy.all(numpy.isfinite(market["funding"][index, targeted]))
    ):
        raise DataQualityError("forward target outcome is incomplete")
    price = float(
        numpy.sum(target[targeted] * market["returns"][index, targeted])
    )
    funding = float(
        numpy.sum(-target[targeted] * market["funding"][index, targeted])
    )
    turnover = float(numpy.sum(numpy.abs(target - previous)))
    cost = multiplier * (
        protocol.parent.FEE_PER_TURNOVER
        + protocol.parent.SLIPPAGE_PER_TURNOVER
    ) * turnover
    net = price + funding - cost
    if not math.isfinite(net) or net <= -1.0:
        raise DataQualityError("forward portfolio outcome is invalid")
    return {
        "price_return": price,
        "funding_return": funding,
        "transaction_cost": cost,
        "turnover": turnover,
        "net_return": net,
        "gross_exposure": float(numpy.sum(numpy.abs(target))),
    }


def build_decision_payloads(market: dict, records: list[dict]) -> list[dict]:
    prepared = parent_research.prepare_market(market)
    cache = parent_research.build_signal_cache(market, prepared=prepared)
    record_by_date = {
        datetime.date.fromisoformat(value["bar_date"]): value
        for value in records
    }
    official_dates = sorted(
        date
        for date in record_by_date
        if protocol.FORWARD_START <= date < protocol.FORWARD_CUTOFF_EXCLUSIVE
    )
    if not official_dates:
        return []
    expected_dates = [
        protocol.FORWARD_START + datetime.timedelta(days=value)
        for value in range(len(official_dates))
    ]
    if official_dates != expected_dates:
        raise DataQualityError("official upstream records are not contiguous")
    date_to_index = {date: index for index, date in enumerate(market["dates"])}
    asset_count = len(market["symbols"])
    variants = ("breadth_v2", "parent_v1", "continuous")
    vintages = {
        key: numpy.zeros(
            (protocol.parent.STAGGERED_VINTAGES, asset_count),
            dtype=numpy.float64,
        )
        for key in variants
    }
    applied = {
        key: numpy.zeros(asset_count, dtype=numpy.float64) for key in variants
    }
    cost_basis = {key: value.copy() for key, value in applied.items()}
    payloads = []
    for position, date in enumerate(official_dates):
        index = date_to_index[date]
        matured = None
        if position:
            matured = {
                "decision_bar": official_dates[position - 1].isoformat(),
                "return_bearing_bar": date.isoformat(),
                "base": {
                    key: _outcome(
                        market, index, cost_basis[key], applied[key], 1.0
                    )
                    for key in variants
                },
                "stress_3x_cost": {
                    key: _outcome(
                        market,
                        index,
                        cost_basis[key],
                        applied[key],
                        protocol.parent.STRESS_COST_MULTIPLIER,
                    )
                    for key in variants
                },
            }
        basket = cache["baskets"][index]
        decision_valid = bool(cache["decision_valid"][index])
        parent_active = decision_valid and bool(cache["active"][index])
        v2_active, breadth = breadth_decision(
            market, index, basket, parent_active
        )
        new_targets = {
            "breadth_v2": _target_from_basket(
                asset_count, basket, v2_active
            ),
            "parent_v1": _target_from_basket(
                asset_count, basket, parent_active
            ),
            "continuous": _target_from_basket(
                asset_count, basket, bool(basket)
            ),
        }
        aggregates = {}
        for key in variants:
            aggregates[key] = parent_research.update_vintage_targets(
                vintages[key], date, new_targets[key]
            ).copy()
        evidence = record_by_date[date]
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
                f"{(date + datetime.timedelta(days=1)).isoformat()}"
                "T00:25:00+00:00"
            ),
            "target_return_bearing_bar": (
                date + datetime.timedelta(days=1)
            ).isoformat(),
            "upstream_market_record_hash": evidence["record_hash"],
            "signal": {
                "decision_valid": decision_valid,
                "market_score": (
                    float(cache["scores"][index])
                    if decision_valid
                    else None
                ),
                "historical_threshold": (
                    float(cache["thresholds"][index])
                    if decision_valid
                    else None
                ),
                "parent_v1_active": parent_active,
                "breadth_v2_active": v2_active,
                **breadth,
                "basket_symbols": [
                    market["symbols"][value] for value in basket
                ],
            },
            "research_targets": {
                key: _sparse_weights(market["symbols"], aggregates[key])
                for key in variants
            },
            "matured_outcome": matured,
        }
        payloads.append(
            {**payload, "decision_payload_sha256": _json_hash(payload)}
        )
        for key in variants:
            cost_basis[key] = applied[key].copy()
            applied[key] = aggregates[key].copy()
    return payloads


def _journal_record_hash(record: dict) -> str:
    return _json_hash(
        {key: value for key, value in record.items() if key != "journal_record_hash"}
    )


def load_journal(path: pathlib.Path) -> list[dict]:
    if not path.exists():
        return []
    records = []
    previous_hash = None
    previous_date = None
    with path.open("r", encoding="utf-8") as handle:
        for line_number, line in enumerate(handle, start=1):
            if not line.endswith("\n"):
                raise DataQualityError("breadth journal has a partial line")
            record = json.loads(line)
            payload = record["decision_payload"]
            payload_without_hash = {
                key: value
                for key, value in payload.items()
                if key != "decision_payload_sha256"
            }
            date = datetime.date.fromisoformat(payload["bar_date"])
            if (
                record.get("schema_version") != SCHEMA_VERSION
                or record.get("previous_journal_hash") != previous_hash
                or record.get("journal_record_hash")
                != _journal_record_hash(record)
                or payload.get("decision_payload_sha256")
                != _json_hash(payload_without_hash)
                or (
                    previous_date is not None
                    and date != previous_date + datetime.timedelta(days=1)
                )
            ):
                raise DataQualityError(
                    f"breadth journal chain differs at line {line_number}"
                )
            records.append(record)
            previous_hash = record["journal_record_hash"]
            previous_date = date
    return records


def append_payloads(path: pathlib.Path, expected_payloads: list[dict]) -> int:
    existing = load_journal(path)
    if len(existing) > len(expected_payloads):
        raise DataQualityError("breadth journal is ahead of source evidence")
    for index, record in enumerate(existing):
        if record["decision_payload"] != expected_payloads[index]:
            raise DataQualityError("prior breadth decision no longer reproduces")
    path.parent.mkdir(parents=True, exist_ok=True)
    previous_hash = existing[-1]["journal_record_hash"] if existing else None
    appended = 0
    with path.open("a", encoding="utf-8") as handle:
        for payload in expected_payloads[len(existing) :]:
            record = {
                "schema_version": SCHEMA_VERSION,
                "previous_journal_hash": previous_hash,
                "decision_payload": payload,
            }
            record["journal_record_hash"] = _journal_record_hash(record)
            handle.write(_canonical_bytes(record).decode("utf-8") + "\n")
            handle.flush()
            os.fsync(handle.fileno())
            previous_hash = record["journal_record_hash"]
            appended += 1
    return appended


@contextlib.contextmanager
def _exclusive_lock(path: pathlib.Path):
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a+", encoding="utf-8") as handle:
        fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        try:
            yield
        finally:
            fcntl.flock(handle.fileno(), fcntl.LOCK_UN)


def _health_payload(
    config: ForwardConfig,
    lock: dict,
    records: list[dict],
    journal: list[dict],
    appended: int,
    upstream_health: dict,
    now: datetime.datetime,
) -> dict:
    official_records = sum(
        protocol.FORWARD_START
        <= datetime.date.fromisoformat(value["bar_date"])
        < protocol.FORWARD_CUTOFF_EXCLUSIVE
        for value in records
    )
    outcomes = sum(
        value["decision_payload"]["matured_outcome"] is not None
        for value in journal
    )
    if now.date() < protocol.FORWARD_START:
        phase = "warmup"
    elif official_records < protocol.FORWARD_CALENDAR_DAYS:
        phase = "forward"
    else:
        phase = "waiting_for_gate_cutoff"
    blockers = []
    if official_records < protocol.FORWARD_CALENDAR_DAYS:
        blockers.append("official_market_records")
    if len(journal) < protocol.FORWARD_CALENDAR_DAYS:
        blockers.append("decision_records")
    if outcomes < protocol.FORWARD_CALENDAR_DAYS - 1:
        blockers.append("mature_outcomes")
    if now < datetime.datetime.combine(
        protocol.FORWARD_CUTOFF_EXCLUSIVE,
        datetime.time(
            hour=0,
            minute=protocol.DAILY_FINALIZATION_DELAY_MINUTES,
        ),
        UTC,
    ):
        blockers.append("calendar_cutoff")
    return {
        "schema_version": SCHEMA_VERSION,
        "observer_type": OBSERVER_TYPE,
        "mode": "forward_observation_only",
        "status": "healthy",
        "phase": phase,
        "last_success_at": now.isoformat(),
        "protocol_sha256": protocol.protocol_payload()["protocol_sha256"],
        "implementation_lock_sha256": lock["implementation_lock_sha256"],
        "upstream_last_success_at": upstream_health["last_success_at"],
        "upstream_last_archived_bar": upstream_health["last_archived_bar"],
        "source_daily_records": len(records),
        "warmup_records": sum(
            datetime.date.fromisoformat(value["bar_date"])
            < protocol.FORWARD_START
            for value in records
        ),
        "official_market_records": official_records,
        "decision_records": len(journal),
        "mature_outcomes": outcomes,
        "decisions_appended_this_cycle": appended,
        "last_decision_bar": (
            journal[-1]["decision_payload"]["bar_date"] if journal else None
        ),
        "last_journal_hash": (
            journal[-1]["journal_record_hash"] if journal else None
        ),
        "earliest_gate_evaluation_not_before_utc": (
            f"{protocol.FORWARD_CUTOFF_EXCLUSIVE.isoformat()}T00:25:00+00:00"
        ),
        "gate_evaluation_authorized": False,
        "pre_cutoff_aggregate_metrics_calculated": False,
        "current_blockers": blockers,
        "journal_bytes": (
            config.journal_path.stat().st_size
            if config.journal_path.exists()
            else 0
        ),
        "research_only": True,
        "public_data_only": True,
        "network_required": False,
        "credentials_used": False,
        "orders_authorized": False,
        "paper_orders_authorized": False,
        "automatic_promotion": False,
    }


def run_once(config: ForwardConfig, *, now: datetime.datetime | None = None) -> dict:
    now = datetime.datetime.now(UTC) if now is None else now.astimezone(UTC)
    with _exclusive_lock(config.runner_lock_path):
        _load_protocol(config.protocol_path)
        lock = verify_implementation_lock(config)
        market, records = load_extended_market(config)
        upstream_health = _verify_upstream_health(config, records, now)
        payloads = build_decision_payloads(market, records)
        appended = append_payloads(config.journal_path, payloads)
        journal = load_journal(config.journal_path)
        health = _health_payload(
            config,
            lock,
            records,
            journal,
            appended,
            upstream_health,
            now,
        )
        _atomic_json(config.health_path, health)
        return health


def _add_paths(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--protocol", required=True)
    parser.add_argument("--implementation-lock", required=True)
    parser.add_argument("--parent-protocol", required=True)
    parser.add_argument("--parent-implementation-lock", required=True)
    parser.add_argument("--parent-report", required=True)
    parser.add_argument("--parent-manifest", required=True)
    parser.add_argument("--parent-trajectory", required=True)
    parser.add_argument("--upstream-protocol", required=True)
    parser.add_argument("--upstream-implementation-lock", required=True)
    parser.add_argument("--snapshot", required=True)
    parser.add_argument("--history", required=True)
    parser.add_argument("--upstream-daily", required=True)
    parser.add_argument("--upstream-raw", required=True)
    parser.add_argument("--upstream-health", required=True)
    parser.add_argument("--journal", required=True)
    parser.add_argument("--health", required=True)
    parser.add_argument("--runner-lock", required=True)
    parser.add_argument("--runner-test", required=True)
    parser.add_argument("--protocol-test", required=True)
    parser.add_argument("--entrypoint", required=True)


def _config(arguments) -> ForwardConfig:
    return ForwardConfig(
        **{
            field: pathlib.Path(getattr(arguments, option)).resolve()
            for field, option in (
                ("protocol_path", "protocol"),
                ("implementation_lock_path", "implementation_lock"),
                ("parent_protocol_path", "parent_protocol"),
                (
                    "parent_implementation_lock_path",
                    "parent_implementation_lock",
                ),
                ("parent_report_path", "parent_report"),
                ("parent_manifest_path", "parent_manifest"),
                ("parent_trajectory_path", "parent_trajectory"),
                ("upstream_protocol_path", "upstream_protocol"),
                (
                    "upstream_implementation_lock_path",
                    "upstream_implementation_lock",
                ),
                ("snapshot_path", "snapshot"),
                ("history_path", "history"),
                ("upstream_daily_root", "upstream_daily"),
                ("upstream_raw_root", "upstream_raw"),
                ("upstream_health_path", "upstream_health"),
                ("journal_path", "journal"),
                ("health_path", "health"),
                ("runner_lock_path", "runner_lock"),
                ("runner_test_path", "runner_test"),
                ("protocol_test_path", "protocol_test"),
                ("entrypoint_path", "entrypoint"),
            )
        }
    )


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    for name in ("write-lock", "run-once"):
        command = commands.add_parser(name)
        _add_paths(command)
    return parser


def main(argv=None) -> int:
    arguments = _parser().parse_args(argv)
    config = _config(arguments)
    if arguments.command == "write-lock":
        result = write_or_verify_implementation_lock(config)
        summary = {
            "status": result["status"],
            "implementation_lock_sha256": result[
                "implementation_lock_sha256"
            ],
            "official_records_at_lock": 0,
            "orders_authorized": False,
        }
    else:
        result = run_once(config)
        summary = {
            "status": result["status"],
            "phase": result["phase"],
            "official_market_records": result["official_market_records"],
            "decision_records": result["decision_records"],
            "orders_authorized": False,
        }
    print(json.dumps(summary, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
