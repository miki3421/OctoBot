"""Build strictly forward, execution-aware carry examples after readiness."""

from __future__ import annotations

import datetime
import collections
import heapq
import hashlib
import json
import math
import pathlib
import typing

import numpy

from octobot.ai_strategy_lab import forward_evidence as forward_evidence_module
from octobot.ai_strategy_lab import microstructure as microstructure_module


DATASET_SCHEMA_VERSION = 1
DEFAULT_HORIZON_HOURS = (8, 24, 168)
DEFAULT_LEG_QUOTE = 1_000.0
FEATURE_NAMES = (
    "current_funding_rate",
    "predicted_funding_rate_filled",
    "predicted_funding_available",
    "funding_granularity_hours",
    "entry_basis_bps",
    "instant_round_trip_book_width_bps",
    "spot_spread_bps",
    "futures_spread_bps",
    "entry_capacity_usdt_depth20",
    "instant_exit_capacity_usdt_depth20",
    "spot_entry_vwap_slippage_bps",
    "futures_entry_vwap_slippage_bps",
    "spot_instant_exit_vwap_slippage_bps",
    "futures_instant_exit_vwap_slippage_bps",
    "open_interest_quote",
    "mark_index_basis_bps",
    "spot_conservative_taker_fee_rate",
    "futures_conservative_taker_fee_rate",
)


def build_forward_carry_dataset(
    journal_path: str | pathlib.Path,
    evidence_path: str | pathlib.Path,
    *,
    horizon_hours: typing.Iterable[int] = DEFAULT_HORIZON_HOURS,
    leg_quote: float = DEFAULT_LEG_QUOTE,
    entry_start_utc: str | datetime.datetime | None = None,
    entry_end_exclusive_utc: str | datetime.datetime | None = None,
    evidence_config: (
        forward_evidence_module.ForwardEvidenceConfig | None
    ) = None,
) -> dict:
    """Build generic labeled examples, refusing any unready evidence."""
    journal = pathlib.Path(journal_path).resolve()
    evidence_file = pathlib.Path(evidence_path).resolve()
    horizons = tuple(sorted(set(int(value) for value in horizon_hours)))
    if not horizons or any(value <= 0 for value in horizons):
        raise ValueError("at least one positive carry horizon is required")
    if leg_quote <= 0 or not math.isfinite(leg_quote):
        raise ValueError("carry leg quote must be positive and finite")
    entry_start = _parse_utc_bound(entry_start_utc, "entry start")
    entry_end = _parse_utc_bound(
        entry_end_exclusive_utc, "entry end exclusive"
    )
    if (
        entry_start is not None
        and entry_end is not None
        and entry_start >= entry_end
    ):
        raise ValueError("carry entry window must have positive duration")
    evidence = json.loads(evidence_file.read_text(encoding="utf-8"))
    _validate_evidence(evidence, journal)
    recomputed_evidence = (
        forward_evidence_module.evaluate_forward_market_evidence(
            journal, config=evidence_config
        )
    )
    if recomputed_evidence.get("strategy_development_ready") is not True:
        raise ValueError("recomputed forward strategy readiness is false")
    if evidence.get("thresholds") != recomputed_evidence.get("thresholds"):
        raise ValueError("forward evidence thresholds mismatch")
    if evidence.get("checks") != recomputed_evidence.get("checks"):
        raise ValueError("forward evidence checks mismatch")
    expected_bases = tuple(
        sorted(
            recomputed_evidence["settled_funding"][
                "unique_points_by_symbol"
            ]
        )
    )
    if len(expected_bases) != int(
        recomputed_evidence["thresholds"]["expected_symbol_count"]
    ):
        raise ValueError("forward carry expected symbol universe mismatch")
    settled = _settled_funding(
        microstructure_module.iter_microstructure_records(journal)
    )
    curve_key = f"{leg_quote:g}"
    rows = []
    exclusions = {
        "entry_schema_incomplete": 0,
        "missing_exact_exit_bucket": 0,
        "exit_schema_incomplete": 0,
        "insufficient_entry_depth": 0,
        "insufficient_exit_depth": 0,
    }
    exclusion_events = []
    pending: dict[datetime.datetime, list[tuple[datetime.datetime, int]]] = {}
    pending_heap: list[datetime.datetime] = []
    entries: dict[datetime.datetime, dict] = {}
    entry_order = collections.deque()
    maximum_horizon = datetime.timedelta(hours=max(horizons))
    for exit_record in microstructure_module.iter_microstructure_records(journal):
        exit_timestamp = datetime.datetime.fromisoformat(
            exit_record["bucket_start_utc"]
        )
        while pending_heap and pending_heap[0] < exit_timestamp:
            missing_timestamp = heapq.heappop(pending_heap)
            tasks = pending.pop(missing_timestamp, ())
            for entry_timestamp, horizon in tasks:
                _append_exclusions(
                    exclusion_events,
                    exclusions,
                    reason="missing_exact_exit_bucket",
                    entry_timestamp=entry_timestamp,
                    horizon=horizon,
                    bases=expected_bases,
                )
        if pending_heap and pending_heap[0] == exit_timestamp:
            heapq.heappop(pending_heap)
            tasks = pending.pop(exit_timestamp, ())
            for entry_timestamp, horizon in tasks:
                entry_record = entries.get(entry_timestamp)
                if entry_record is None:
                    raise ValueError("forward carry streaming entry expired early")
                _append_entry_exit_rows(
                    rows,
                    exclusion_events,
                    exclusions,
                    entry=entry_record,
                    exit_record=exit_record,
                    entry_timestamp=entry_timestamp,
                    exit_timestamp=exit_timestamp,
                    horizon=horizon,
                    expected_bases=expected_bases,
                    curve_key=curve_key,
                    leg_quote=leg_quote,
                    settled=settled,
                )
        entry_allowed = (
            (entry_start is None or exit_timestamp >= entry_start)
            and (entry_end is None or exit_timestamp < entry_end)
        )
        if entry_allowed:
            entries[exit_timestamp] = exit_record
            entry_order.append(exit_timestamp)
            for horizon in horizons:
                scheduled = exit_timestamp + datetime.timedelta(hours=horizon)
                if scheduled not in pending:
                    pending[scheduled] = []
                    heapq.heappush(pending_heap, scheduled)
                pending[scheduled].append((exit_timestamp, horizon))
        expiration = exit_timestamp - maximum_horizon
        while entry_order and entry_order[0] < expiration:
            entries.pop(entry_order.popleft(), None)
    while pending_heap:
        missing_timestamp = heapq.heappop(pending_heap)
        for entry_timestamp, horizon in pending.pop(missing_timestamp, ()):
            _append_exclusions(
                exclusion_events,
                exclusions,
                reason="missing_exact_exit_bucket",
                entry_timestamp=entry_timestamp,
                horizon=horizon,
                bases=expected_bases,
            )
    rows.sort(
        key=lambda value: (
            value["entry_timestamp_ms"],
            value["horizon_hours"],
            value["base"],
        )
    )
    exclusion_events.sort(
        key=lambda value: (
            value["entry_timestamp_ms"],
            value["horizon_hours"],
            value["base"],
            value["reason"],
        )
    )
    return {
        "schema_version": DATASET_SCHEMA_VERSION,
        "research_only": True,
        "orders_authorized": False,
        "automatic_promotion": False,
        "feature_names": list(FEATURE_NAMES),
        "horizon_hours": list(horizons),
        "leg_quote": leg_quote,
        "paired_gross_capital": 2 * leg_quote,
        "rows": rows,
        "row_count": len(rows),
        "exclusions": exclusions,
        "exclusion_events": exclusion_events,
        "source": {
            "journal_path": str(journal),
            "journal_sha256": _sha256(journal),
            "evidence_path": str(evidence_file),
            "evidence_sha256": _sha256(evidence_file),
            "expected_bases": list(expected_bases),
            "readiness_thresholds": recomputed_evidence["thresholds"],
        },
        "entry_window": {
            "start_inclusive_utc": (
                entry_start.isoformat() if entry_start is not None else None
            ),
            "end_exclusive_utc": (
                entry_end.isoformat() if entry_end is not None else None
            ),
        },
        "label_protocol": {
            "exact_exit_bucket_required": True,
            "interpolation_allowed": False,
            "mid_price_fill_assumed": False,
            "funding_interval": "entry_exclusive_exit_inclusive",
            "fees": "four_sided_conservative_taker",
        },
    }


def _append_entry_exit_rows(
    rows,
    exclusion_events,
    exclusions,
    *,
    entry,
    exit_record,
    entry_timestamp,
    exit_timestamp,
    horizon,
    expected_bases,
    curve_key,
    leg_quote,
    settled,
):
    for base in expected_bases:
        entry_symbol = entry["symbols"].get(base)
        exit_symbol = exit_record["symbols"].get(base)
        if not _has_execution_schema(entry_symbol, curve_key):
            _append_exclusions(
                exclusion_events,
                exclusions,
                reason="entry_schema_incomplete",
                entry_timestamp=entry_timestamp,
                horizon=horizon,
                bases=(base,),
            )
            continue
        if exit_symbol is None or not _has_execution_schema(
            exit_symbol, curve_key
        ):
            _append_exclusions(
                exclusion_events,
                exclusions,
                reason="exit_schema_incomplete",
                entry_timestamp=entry_timestamp,
                horizon=horizon,
                bases=(base,),
            )
            continue
        entry_curves = _curves(entry_symbol, curve_key)
        exit_curves = _curves(exit_symbol, curve_key)
        if not (
            entry_curves["spot_ask"]["sufficient_depth"]
            and entry_curves["futures_bid"]["sufficient_depth"]
        ):
            _append_exclusions(
                exclusion_events,
                exclusions,
                reason="insufficient_entry_depth",
                entry_timestamp=entry_timestamp,
                horizon=horizon,
                bases=(base,),
            )
            continue
        fills = _execution_fills(entry_symbol, exit_symbol, leg_quote)
        if fills is None:
            _append_exclusions(
                exclusion_events,
                exclusions,
                reason="insufficient_exit_depth",
                entry_timestamp=entry_timestamp,
                horizon=horizon,
                bases=(base,),
            )
            continue
        rows.append(
            _build_row(
                base=base,
                entry_timestamp=entry_timestamp,
                exit_timestamp=exit_timestamp,
                horizon=horizon,
                leg_quote=leg_quote,
                entry_symbol=entry_symbol,
                exit_symbol=exit_symbol,
                entry_curves=entry_curves,
                exit_curves=exit_curves,
                fills=fills,
                settled_points=settled.get(base, {}),
            )
        )


def save_forward_carry_dataset(
    dataset: dict,
    output_path: str | pathlib.Path,
) -> dict:
    output = pathlib.Path(output_path).resolve()
    if output.suffix != ".npz":
        raise ValueError("forward carry dataset output must end in .npz")
    output.parent.mkdir(parents=True, exist_ok=True)
    rows = dataset["rows"]
    features = numpy.asarray(
        [row["features"] for row in rows],
        dtype=numpy.float64,
    ).reshape((len(rows), len(FEATURE_NAMES)))
    temporary_output = output.with_name(output.name + ".tmp")
    with temporary_output.open("wb") as stream:
        numpy.savez_compressed(
            stream,
            schema_version=numpy.asarray(
                [DATASET_SCHEMA_VERSION], dtype=numpy.int16
            ),
            feature_names=numpy.asarray(FEATURE_NAMES),
            features=features,
            entry_timestamp_ms=numpy.asarray(
                [row["entry_timestamp_ms"] for row in rows],
                dtype=numpy.int64,
            ),
            exit_timestamp_ms=numpy.asarray(
                [row["exit_timestamp_ms"] for row in rows],
                dtype=numpy.int64,
            ),
            symbols=numpy.asarray([row["base"] for row in rows]),
            horizon_hours=numpy.asarray(
                [row["horizon_hours"] for row in rows],
                dtype=numpy.int16,
            ),
            spot_price_return=numpy.asarray(
                [row["label"]["spot_price_return"] for row in rows],
                dtype=numpy.float64,
            ),
            futures_price_return=numpy.asarray(
                [row["label"]["futures_price_return"] for row in rows],
                dtype=numpy.float64,
            ),
            settled_funding_return=numpy.asarray(
                [row["label"]["settled_funding_return"] for row in rows],
                dtype=numpy.float64,
            ),
            conservative_fee_return=numpy.asarray(
                [row["label"]["conservative_fee_return"] for row in rows],
                dtype=numpy.float64,
            ),
            net_pair_return=numpy.asarray(
                [row["label"]["net_pair_return"] for row in rows],
                dtype=numpy.float64,
            ),
        )
    temporary_output.replace(output)
    manifest = {
        key: value for key, value in dataset.items() if key != "rows"
    }
    manifest["output"] = {
        "path": str(output),
        "sha256": _sha256(output),
        "bytes": output.stat().st_size,
    }
    manifest["manifest_sha256"] = _json_hash(manifest)
    manifest_path = output.with_suffix(output.suffix + ".manifest.json")
    temporary_manifest = manifest_path.with_name(manifest_path.name + ".tmp")
    temporary_manifest.write_text(
        json.dumps(manifest, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    temporary_manifest.replace(manifest_path)
    return manifest


def load_forward_carry_dataset(
    path_value: str | pathlib.Path,
) -> dict:
    """Load and fully validate a saved forward carry dataset and manifest."""
    path = pathlib.Path(path_value).resolve()
    manifest_path = path.with_suffix(path.suffix + ".manifest.json")
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest_hash = manifest.pop("manifest_sha256", None)
    if manifest_hash != _json_hash(manifest):
        raise ValueError("forward carry manifest hash mismatch")
    manifest["manifest_sha256"] = manifest_hash
    if manifest.get("schema_version") != DATASET_SCHEMA_VERSION:
        raise ValueError("unsupported forward carry manifest schema")
    if (
        manifest.get("research_only") is not True
        or manifest.get("orders_authorized") is not False
        or manifest.get("automatic_promotion") is not False
    ):
        raise ValueError("forward carry manifest safety invariant failed")
    output = manifest.get("output", {})
    if output.get("sha256") != _sha256(path):
        raise ValueError("forward carry dataset hash mismatch")
    if int(output.get("bytes", -1)) != path.stat().st_size:
        raise ValueError("forward carry dataset size mismatch")
    with numpy.load(path, allow_pickle=False) as values:
        schema_version = int(values["schema_version"][0])
        feature_names = tuple(
            str(value) for value in values["feature_names"]
        )
        dataset = {
            "features": values["features"].astype(
                numpy.float64, copy=True
            ),
            "entry_timestamp_ms": values[
                "entry_timestamp_ms"
            ].astype(numpy.int64, copy=True),
            "exit_timestamp_ms": values[
                "exit_timestamp_ms"
            ].astype(numpy.int64, copy=True),
            "symbols": values["symbols"].astype(str, copy=True),
            "horizon_hours": values["horizon_hours"].astype(
                numpy.int16, copy=True
            ),
            "spot_price_return": values["spot_price_return"].astype(
                numpy.float64, copy=True
            ),
            "futures_price_return": values[
                "futures_price_return"
            ].astype(numpy.float64, copy=True),
            "settled_funding_return": values[
                "settled_funding_return"
            ].astype(numpy.float64, copy=True),
            "conservative_fee_return": values[
                "conservative_fee_return"
            ].astype(numpy.float64, copy=True),
            "net_pair_return": values["net_pair_return"].astype(
                numpy.float64, copy=True
            ),
        }
    if schema_version != DATASET_SCHEMA_VERSION:
        raise ValueError("unsupported forward carry dataset schema")
    if feature_names != FEATURE_NAMES:
        raise ValueError("forward carry feature schema mismatch")
    if tuple(manifest.get("feature_names", ())) != FEATURE_NAMES:
        raise ValueError("forward carry manifest feature schema mismatch")
    row_count = len(dataset["entry_timestamp_ms"])
    if dataset["features"].shape != (row_count, len(FEATURE_NAMES)):
        raise ValueError("forward carry feature matrix shape mismatch")
    for name, values in dataset.items():
        if name == "features":
            continue
        if len(values) != row_count:
            raise ValueError(f"forward carry {name} row count mismatch")
    numeric = [
        dataset["features"],
        dataset["spot_price_return"],
        dataset["futures_price_return"],
        dataset["settled_funding_return"],
        dataset["conservative_fee_return"],
        dataset["net_pair_return"],
    ]
    if any(not numpy.all(numpy.isfinite(values)) for values in numeric):
        raise ValueError("forward carry dataset contains non-finite values")
    if numpy.any(
        dataset["exit_timestamp_ms"]
        <= dataset["entry_timestamp_ms"]
    ):
        raise ValueError("forward carry exit must follow entry")
    elapsed_hours = (
        dataset["exit_timestamp_ms"]
        - dataset["entry_timestamp_ms"]
    ) / 3_600_000
    if not numpy.allclose(
        elapsed_hours,
        dataset["horizon_hours"].astype(numpy.float64),
        rtol=0,
        atol=0,
    ):
        raise ValueError("forward carry horizon does not match timestamps")
    if any(not value for value in dataset["symbols"]):
        raise ValueError("forward carry dataset contains an empty symbol")
    recomputed = (
        0.5
        * (
            dataset["spot_price_return"]
            + dataset["futures_price_return"]
            + dataset["settled_funding_return"]
        )
        - dataset["conservative_fee_return"]
    )
    if not numpy.allclose(
        recomputed,
        dataset["net_pair_return"],
        rtol=1e-12,
        atol=1e-12,
    ):
        raise ValueError("forward carry label accounting identity failed")
    if int(manifest.get("row_count", -1)) != row_count:
        raise ValueError("forward carry manifest row count mismatch")
    _validate_entry_window(dataset, manifest)
    _validate_exclusion_events(manifest)
    dataset.update(
        {
            "schema_version": schema_version,
            "feature_names": feature_names,
            "manifest": manifest,
        }
    )
    return dataset


def _parse_utc_bound(value, label):
    if value is None:
        return None
    parsed = (
        value
        if isinstance(value, datetime.datetime)
        else datetime.datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    )
    if parsed.tzinfo is None:
        raise ValueError(f"carry {label} must be timezone-aware")
    return parsed.astimezone(datetime.timezone.utc)


def _validate_entry_window(dataset, manifest):
    window = manifest.get("entry_window")
    if window is None:
        return
    if not isinstance(window, dict):
        raise ValueError("forward carry entry window is invalid")
    start = _parse_utc_bound(window.get("start_inclusive_utc"), "entry start")
    end = _parse_utc_bound(
        window.get("end_exclusive_utc"), "entry end exclusive"
    )
    if start is not None and end is not None and start >= end:
        raise ValueError("forward carry entry window has invalid duration")
    timestamps = dataset["entry_timestamp_ms"]
    if start is not None and numpy.any(
        timestamps < int(start.timestamp() * 1000)
    ):
        raise ValueError("forward carry row precedes entry window")
    if end is not None and numpy.any(
        timestamps >= int(end.timestamp() * 1000)
    ):
        raise ValueError("forward carry row exceeds entry window")


def _append_exclusions(
    events,
    counts,
    *,
    reason,
    entry_timestamp,
    horizon,
    bases,
):
    for base in sorted(bases):
        counts[reason] += 1
        events.append(
            {
                "entry_timestamp_ms": int(entry_timestamp.timestamp() * 1000),
                "horizon_hours": int(horizon),
                "base": str(base),
                "reason": reason,
            }
        )


def _validate_exclusion_events(manifest):
    exclusions = manifest.get("exclusions")
    events = manifest.get("exclusion_events")
    if not isinstance(exclusions, dict) or not isinstance(events, list):
        raise ValueError("forward carry exclusion audit is missing")
    recomputed = {name: 0 for name in exclusions}
    for event in events:
        if not isinstance(event, dict):
            raise ValueError("forward carry exclusion event is invalid")
        reason = event.get("reason")
        if reason not in recomputed:
            raise ValueError("forward carry exclusion reason is invalid")
        if int(event.get("entry_timestamp_ms", 0)) <= 0:
            raise ValueError("forward carry exclusion timestamp is invalid")
        if int(event.get("horizon_hours", 0)) <= 0:
            raise ValueError("forward carry exclusion horizon is invalid")
        if not str(event.get("base", "")):
            raise ValueError("forward carry exclusion symbol is invalid")
        recomputed[reason] += 1
    if any(int(exclusions[name]) != count for name, count in recomputed.items()):
        raise ValueError("forward carry exclusion counts mismatch")


def _json_hash(value):
    return hashlib.sha256(
        json.dumps(value, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()


def _validate_evidence(evidence, journal):
    if evidence.get("mode") != "forward_evidence_only":
        raise ValueError("forward evidence mode mismatch")
    if evidence.get("strategy_development_ready") is not True:
        raise ValueError("forward strategy development is not ready")
    if (
        evidence.get("orders_authorized") is not False
        or evidence.get("automatic_promotion") is not False
        or evidence.get("real_income_authorized") is not False
    ):
        raise ValueError("forward evidence safety invariant failed")
    source = evidence.get("source_journal", {})
    if source.get("sha256") != _sha256(journal):
        raise ValueError("forward evidence journal hash mismatch")


def _settled_funding(records):
    result = {}
    for record in records:
        for base, values in record["symbols"].items():
            points = result.setdefault(base, {})
            for point in values.get("funding", {}).get(
                "settled_last_24h", []
            ):
                timestamp = int(point["timestamp_ms"])
                rate = float(point["rate"])
                previous = points.get(timestamp)
                if previous is not None and previous != rate:
                    raise ValueError(
                        f"settled funding changed for {base} at {timestamp}"
                    )
                points[timestamp] = rate
    return result


def _has_execution_schema(value, curve_key):
    try:
        curves = _curves(value, curve_key)
        float(value["spot"]["conservative_taker_fee_rate"])
        float(value["futures"]["conservative_taker_fee_rate"])
        _validated_normalized_levels(value["spot"]["normalized_bids"])
        _validated_normalized_levels(value["spot"]["normalized_asks"])
        _validated_normalized_levels(value["futures"]["normalized_bids"])
        _validated_normalized_levels(value["futures"]["normalized_asks"])
        return all(
            curve.get("vwap") is not None for curve in curves.values()
        )
    except (KeyError, TypeError, ValueError):
        return False


def _curves(value, curve_key):
    return {
        "spot_ask": value["spot"]["ask_vwap_by_quote"][curve_key],
        "spot_bid": value["spot"]["bid_vwap_by_quote"][curve_key],
        "futures_bid": value["futures"]["bid_vwap_by_quote"][curve_key],
        "futures_ask": value["futures"]["ask_vwap_by_quote"][curve_key],
    }


def _execution_fills(entry_symbol, exit_symbol, leg_quote):
    spot_entry = _fill_quote(
        entry_symbol["spot"]["normalized_asks"], leg_quote
    )
    futures_entry = _fill_quote(
        entry_symbol["futures"]["normalized_bids"], leg_quote
    )
    if spot_entry is None or futures_entry is None:
        return None
    spot_exit = _fill_base(
        exit_symbol["spot"]["normalized_bids"],
        spot_entry["base_quantity"],
    )
    futures_exit = _fill_base(
        exit_symbol["futures"]["normalized_asks"],
        futures_entry["base_quantity"],
    )
    if spot_exit is None or futures_exit is None:
        return None
    return {
        "spot_entry": spot_entry,
        "futures_entry": futures_entry,
        "spot_exit": spot_exit,
        "futures_exit": futures_exit,
    }


def _validated_normalized_levels(values):
    if not isinstance(values, list) or not values:
        raise ValueError("normalized execution levels are missing")
    result = []
    for value in values:
        price = float(value["price"])
        base = float(value["base_quantity"])
        quote = float(value["quote_quantity"])
        if (
            not all(math.isfinite(element) for element in (price, base, quote))
            or price <= 0
            or base <= 0
            or quote <= 0
        ):
            raise ValueError("normalized execution level is invalid")
        result.append((price, base, quote))
    return result


def _fill_quote(values, target_quote):
    remaining = target_quote
    filled_quote = 0.0
    filled_base = 0.0
    for price, _, level_quote in _validated_normalized_levels(values):
        take_quote = min(remaining, level_quote)
        filled_quote += take_quote
        filled_base += take_quote / price
        remaining -= take_quote
        if remaining <= 1e-9:
            break
    if remaining > 1e-9 or filled_base <= 0:
        return None
    return {
        "quote_quantity": filled_quote,
        "base_quantity": filled_base,
        "vwap": filled_quote / filled_base,
    }


def _fill_base(values, target_base):
    remaining = target_base
    filled_quote = 0.0
    filled_base = 0.0
    for price, level_base, _ in _validated_normalized_levels(values):
        take_base = min(remaining, level_base)
        filled_base += take_base
        filled_quote += take_base * price
        remaining -= take_base
        if remaining <= 1e-12:
            break
    if remaining > 1e-12 or filled_base <= 0:
        return None
    return {
        "quote_quantity": filled_quote,
        "base_quantity": filled_base,
        "vwap": filled_quote / filled_base,
    }


def _build_row(
    *,
    base,
    entry_timestamp,
    exit_timestamp,
    horizon,
    leg_quote,
    entry_symbol,
    exit_symbol,
    entry_curves,
    exit_curves,
    fills,
    settled_points,
):
    entry_spot = float(fills["spot_entry"]["vwap"])
    entry_futures = float(fills["futures_entry"]["vwap"])
    exit_spot = float(fills["spot_exit"]["vwap"])
    exit_futures = float(fills["futures_exit"]["vwap"])
    spot_return = (
        fills["spot_exit"]["quote_quantity"]
        - fills["spot_entry"]["quote_quantity"]
    ) / leg_quote
    futures_return = (
        fills["futures_entry"]["quote_quantity"]
        - fills["futures_exit"]["quote_quantity"]
    ) / leg_quote
    entry_ms = int(entry_timestamp.timestamp() * 1000)
    exit_ms = int(exit_timestamp.timestamp() * 1000)
    funding_return = sum(
        rate
        for timestamp, rate in settled_points.items()
        if entry_ms < timestamp <= exit_ms
    )
    fee_quote = (
        fills["spot_entry"]["quote_quantity"]
        * float(entry_symbol["spot"]["conservative_taker_fee_rate"])
        + fills["spot_exit"]["quote_quantity"]
        * float(exit_symbol["spot"]["conservative_taker_fee_rate"])
        + fills["futures_entry"]["quote_quantity"]
        * float(entry_symbol["futures"]["conservative_taker_fee_rate"])
        + fills["futures_exit"]["quote_quantity"]
        * float(exit_symbol["futures"]["conservative_taker_fee_rate"])
    )
    conservative_fee_return = fee_quote / (2 * leg_quote)
    net_pair_return = (
        0.5 * (spot_return + futures_return + funding_return)
        - conservative_fee_return
    )
    funding = entry_symbol["funding"]
    predicted = funding.get("predicted_rate")
    predicted_available = predicted is not None
    predicted_filled = (
        float(predicted)
        if predicted_available
        else float(funding["current_rate"])
    )
    spot = entry_symbol["spot"]
    futures = entry_symbol["futures"]
    execution = entry_symbol["carry_execution"]
    features = [
        float(funding["current_rate"]),
        predicted_filled,
        float(predicted_available),
        float(funding["granularity_ms"]) / 3_600_000,
        float(execution["entry_basis_bps"]),
        float(execution["round_trip_book_width_bps"]),
        float(spot["spread_bps"]),
        float(futures["spread_bps"]),
        float(execution["entry_capacity_usdt_depth20"]),
        float(execution["exit_capacity_usdt_depth20"]),
        (entry_spot / float(spot["best_ask"]) - 1.0) * 10_000,
        (float(futures["best_bid"]) / entry_futures - 1.0)
        * 10_000,
        (float(spot["best_bid"]) / float(
            entry_curves["spot_bid"]["vwap"]
        ) - 1.0)
        * 10_000,
        (float(entry_curves["futures_ask"]["vwap"]) / float(
            futures["best_ask"]
        ) - 1.0)
        * 10_000,
        float(futures["open_interest_quote"]),
        float(futures["mark_index_basis_bps"]),
        float(spot["conservative_taker_fee_rate"]),
        float(futures["conservative_taker_fee_rate"]),
    ]
    if not all(math.isfinite(value) for value in features):
        raise ValueError(f"non-finite forward feature for {base}")
    label_values = (
        spot_return,
        futures_return,
        funding_return,
        conservative_fee_return,
        net_pair_return,
    )
    if not all(math.isfinite(value) for value in label_values):
        raise ValueError(f"non-finite forward label for {base}")
    return {
        "base": base,
        "entry_timestamp_ms": entry_ms,
        "exit_timestamp_ms": exit_ms,
        "horizon_hours": horizon,
        "leg_quote": leg_quote,
        "features": features,
        "label": {
            "spot_price_return": spot_return,
            "futures_price_return": futures_return,
            "settled_funding_return": funding_return,
            "conservative_fee_return": conservative_fee_return,
            "net_pair_return": net_pair_return,
        },
    }


def _sha256(path):
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()
