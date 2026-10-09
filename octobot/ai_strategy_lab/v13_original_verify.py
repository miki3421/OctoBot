"""Read-only original V13 reconstruction, executable in a separate offline process.

No producer claim is accepted as a derivation. Only pinned original functions
and the closed archive prefix are consumed. Receipts remain research-only;
legacy publication clocks are insufficient for future issuance.
Work card: work-card-fe78a248-3d67-45fa-86b0-bbc5eed8e71e.
"""

from __future__ import annotations

import argparse
import dataclasses
import datetime as dt
import gzip
import hashlib
import importlib
import io
import os
import pathlib
import sys
import urllib.parse

from octobot.ai_strategy_lab import v13_original_portfolio as candidate

VERSION = "v13-original-offline-verifier-v1"
OBSERVER = "diversified_trend_cointegration_forward_observer_v1"


@dataclasses.dataclass(frozen=True)
class Inputs:
    repo_root: pathlib.Path
    research_root: pathlib.Path
    archive_root: pathlib.Path
    implementation_lock: pathlib.Path


def _bytes(path):
    with pathlib.Path(path).open("rb") as stream:
        payload = stream.read(candidate.MAX_JSON_BYTES + 1)
    if len(payload) > candidate.MAX_JSON_BYTES:
        raise candidate.Rejected("input_too_large")
    return payload


def _unzip(payload):
    with gzip.GzipFile(fileobj=io.BytesIO(payload)) as stream:
        result = stream.read(candidate.MAX_JSON_BYTES + 1)
    if len(result) > candidate.MAX_JSON_BYTES:
        raise candidate.Rejected("decompressed_input_too_large")
    return result


def _safe(root, relative):
    if not isinstance(relative, str) or pathlib.Path(relative).is_absolute():
        raise candidate.Rejected("invalid_archive_path")
    base = pathlib.Path(root).resolve()
    path = base / relative
    # Reject symlinks even when their current destination happens to be in scope.
    if any(p.is_symlink() for p in [path, *path.parents] if p != base.parent):
        raise candidate.Rejected("symlink_input")
    if not path.resolve().is_relative_to(base):
        raise candidate.Rejected("archive_path_escape")
    return path


def _pin(path, expected):
    if hashlib.sha256(pathlib.Path(path).read_bytes()).hexdigest() != expected:
        raise candidate.Rejected("original_artifact_changed")


def _load_runner(inputs, contract):
    # Verify files BEFORE importing the frozen runner and its component code.
    for item in contract["source_identity"]["frozen_source_files"].values():
        _pin(_safe(inputs.repo_root, item["repo_relative_path"]), item["sha256"])
    runner = importlib.import_module(
        "octobot.ai_strategy_lab.diversified_trend_cointegration_forward_runner")
    actual = runner._source_artifacts()
    if actual != contract["source_identity"]["frozen_source_files"]:
        raise candidate.Rejected("loaded_original_module_mismatch")
    research = inputs.research_root
    training = research / "diversified-trend-cointegration-v1/training/diversified-trend-cointegration-v1-36f7b0106d97-3d7dcbc873cb"
    config = runner.ForwardObserverConfig(
        protocol_path=research / "diversified-trend-cointegration-v1/forward-protocol-v1.json",
        implementation_lock_path=inputs.implementation_lock,
        parent_protocol_path=research / "diversified-trend-cointegration-v1/protocol-v1_2.json",
        selected_model_path=training / "selected-model.json",
        training_report_path=training / "report.json",
        training_manifest_path=training / "manifest.json",
        training_trajectory_path=training / "training-trajectories.json",
        snapshot_path=research / "category-momentum-v1/sources/source-snapshot-b0204985b9fa-03d744e12e04",
        history_path=research / "category-momentum-v1/history/history-b0204985b9fa-4158e252768a",
        null_path=research / "expanded-cointegration-pairs-v2/evaluations/expanded-cointegration-pairs-v2-7718dd8e2f55-cfe3d78a318b/monte-carlo-null.npy",
        archive_root=inputs.archive_root / "daily", raw_root=inputs.archive_root / "raw",
        journal_path=inputs.archive_root / "decisions.jsonl",
        health_path=inputs.archive_root / "unused-health",
        runner_lock_path=inputs.archive_root / "unused-lock")
    identity = contract["source_identity"]
    for path, key in [(config.protocol_path, "forward_protocol_file_sha256"),
                      (config.implementation_lock_path, "implementation_lock_file_sha256"),
                      (config.selected_model_path, "selected_model_file_sha256"),
                      (config.training_manifest_path, "training_manifest_file_sha256")]:
        _pin(path, identity[key])
    context = runner.verify_implementation_lock(config)
    universe = [runner._local_to_binance_symbol(s) for s in context["trend_market"]["symbols"]]
    if sorted(universe) != contract["universe"]:
        raise candidate.Rejected("original_universe_mismatch")
    return runner, context


def _safeguards(value, *, research=False):
    expected = {"orders_authorized": False, "paper_orders_authorized": False,
                "credentials_used": False, "automatic_promotion": False, "public_data_only": True}
    if research:
        expected["research_only"] = True
    if (type(value.get("schema_version")) is not int or value["schema_version"] != 1
            or value.get("observer_type") != OBSERVER
            or any(value.get(k) is not v for k, v in expected.items())):
        raise candidate.Rejected("research_safeguards_changed")


def load_daily_prefix(inputs, runner, context, day):
    records, previous = [], None
    date = runner.protocol.WARMUP_START
    while date <= day:
        path = _safe(inputs.archive_root / "daily", date.isoformat() + ".json.gz")
        record = candidate.read_json(_unzip(_bytes(path)))
        _safeguards(record)
        if (record.get("bar_date") != date.isoformat()
                or record.get("previous_record_hash") != previous
                or record.get("record_hash") != candidate.digest({k: v for k, v in record.items() if k != "record_hash"})
                or set(record["symbols"]) != set(context["cointegration_market"]["symbols"])):
            raise candidate.Rejected("daily_prefix_mismatch")
        opened = dt.datetime.combine(date, dt.time(), candidate.UTC)
        if (candidate.timestamp(record.get("bar_open_utc")) != opened
                or candidate.timestamp(record.get("bar_close_utc")) != opened + dt.timedelta(days=1)
                or record.get("mode") != ("warmup_only" if date < runner.protocol.FORWARD_START else "forward_only")):
            raise candidate.Rejected("daily_slot_mismatch")
        previous = record["record_hash"]
        records.append(record)
        date += dt.timedelta(days=1)
    if not records:
        raise candidate.Rejected("daily_prefix_missing")
    return records


def load_source_prefix(path, day, contract):
    """Stop at the selected slot; later records cannot affect its identity."""
    previous, previous_day, prefix = None, None, []
    with pathlib.Path(path).open("rb") as stream:
        while True:
            line = stream.readline(candidate.MAX_JSON_BYTES + 1)
            if not line:
                break
            record = candidate.read_json(line)
            if (set(record) != {"schema_version", "observer_type", "recorded_at", "previous_journal_hash", "decision_payload", "journal_record_hash"}
                    or type(record["schema_version"]) is not int or record["schema_version"] != 1
                    or record["observer_type"] != OBSERVER):
                raise candidate.Rejected("source_schema_mismatch")
            candidate.timestamp(record["recorded_at"])  # Syntax only: never evidence of availability.
            payload = record["decision_payload"]
            _safeguards(payload, research=True)
            date = candidate.bar_date(payload["bar_date"])
            mature = dt.datetime.combine(date + dt.timedelta(days=1), dt.time(), candidate.UTC) + dt.timedelta(minutes=10)
            if (payload.get("mode") != "forward_research_target_only"
                    or payload.get("target_return_bearing_bar") != (date + dt.timedelta(days=1)).isoformat()
                    or candidate.timestamp(payload.get("decision_available_not_before_utc")) != mature):
                raise candidate.Rejected("source_slot_mismatch")
            if (record.get("previous_journal_hash") != previous
                    or record.get("journal_record_hash") != candidate.digest({k: v for k, v in record.items() if k != "journal_record_hash"})
                    or payload.get("decision_payload_sha256") != candidate.digest({k: v for k, v in payload.items() if k != "decision_payload_sha256"})
                    or (previous_day is not None and date != previous_day + dt.timedelta(days=1))
                    or (previous_day is None and date != dt.date(2026, 9, 1))):
                raise candidate.Rejected("source_prefix_mismatch")
            identity = contract["source_identity"]
            if payload.get("lineage") != {
                "forward_protocol_sha256": identity["forward_protocol_content_sha256"],
                "implementation_lock_sha256": identity["implementation_lock_content_sha256"],
                "selected_model_sha256": identity["selected_model_file_sha256"]}:
                raise candidate.Rejected("source_lineage_mismatch")
            prefix.append(record)
            previous, previous_day = record["journal_record_hash"], date
            if date == day:
                return record, prefix
            if date > day:
                break
    raise candidate.Rejected("source_slot_missing")


def _raw_bytes(inputs, artifact, *, symbol, endpoint, cache):
    url = urllib.parse.urlsplit(artifact["url"])
    query = urllib.parse.parse_qs(url.query, strict_parsing=True)
    allowed = {"symbol", "startTime", "endTime", "limit"}
    if endpoint.endswith("klines"):
        allowed.add("interval")
    if (url.scheme != "https" or url.netloc != "fapi.binance.com" or url.fragment
            or url.path != endpoint or query.get("symbol") != [symbol]
            or set(query) != allowed
            or any(len(v) != 1 for v in query.values())
            or (endpoint.endswith("klines") and query.get("interval") != ["1d"])):
        raise candidate.Rejected("raw_provenance_mismatch")
    key = candidate.require_hash(artifact["artifact_sha256"])
    response_hash = candidate.require_hash(artifact["response_sha256"])
    cache_key = (artifact["path"], key, response_hash)
    if cache_key not in cache:
        payload = _bytes(_safe(inputs.archive_root / "raw", artifact["path"]))
        if hashlib.sha256(payload).hexdigest() != key:
            raise candidate.Rejected("raw_artifact_changed")
        raw = _unzip(payload)
        if hashlib.sha256(raw).hexdigest() != response_hash:
            raise candidate.Rejected("raw_response_changed")
        # Reject duplicate keys and nonfinite JSON before original parsing.
        candidate.read_json(raw)
        cache[cache_key] = raw
    return cache[cache_key]


def verify_normalized_inputs(inputs, runner, records, universe):
    cache, response_hashes = {}, set()
    normalization = {}
    causal = []
    for record in records:
        day = candidate.bar_date(record["bar_date"])
        selected = {}
        for symbol in universe:
            values = record["symbols"][symbol]
            klines = values["raw"]["daily_klines"]
            funding = values["raw"]["funding_pages"]
            raw_close = _raw_bytes(inputs, klines, symbol=symbol, endpoint="/fapi/v1/klines", cache=cache)
            raw_funding = [_raw_bytes(inputs, a, symbol=symbol, endpoint="/fapi/v1/fundingRate", cache=cache) for a in funding]
            close = runner._parse_klines(raw_close, [day])[day]
            rate, count = runner._parse_funding_rows(raw_funding, [day], symbol)[day]
            # Old acquisition's sequential binary64 sum and the newer runtime
            # sum are reproducible encodings. Accept exact matches only and
            # expose the observed encoding; never invent a numerical tolerance.
            rates = {}
            start = int(dt.datetime.combine(day, dt.time(), candidate.UTC).timestamp() * 1000)
            for raw in raw_funding:
                for row in candidate.read_json(raw):
                    instant = int(row["fundingTime"])
                    if start < instant <= start + runner.DAY_MILLISECONDS:
                        rates[instant] = float(row["fundingRate"])
            sequential = 0.0
            for instant in sorted(rates):
                sequential += rates[instant]
            stored_rate = values["funding_rate_sum"]
            if stored_rate == rate:
                encoding = "current_runtime_sum"
            elif stored_rate == sequential:
                encoding = "left_to_right_binary64"
            else:
                raise candidate.Rejected("normalized_raw_mismatch: " + day.isoformat() + ":" + symbol)
            normalization[encoding] = normalization.get(encoding, 0) + 1
            if (type(values["close"]) not in (int, float) or type(values["funding_rate_sum"]) not in (int, float)
                    or type(values["funding_settlement_count"]) is not int
                    or close != values["close"]
                    or count != values["funding_settlement_count"]):
                raise candidate.Rejected("normalized_raw_mismatch: " + day.isoformat() + ":" + symbol)
            response_hashes.update(a["response_sha256"] for a in [klines, *funding])
            selected[symbol] = {"close": candidate.encode_weight(close),
                                "funding_rate_sum": candidate.encode_weight(stored_rate),
                                "funding_settlement_count": count}
        causal.append({"bar_date": day.isoformat(), "symbols": selected})
    return candidate.digest(causal), sorted(response_hashes), normalization


def reconstruct(inputs, *, source_bar_date, verified_at=None):
    """Recalculate the original path through one closed slot; never fetch data."""
    contract, _schema = candidate.load_contract(inputs.repo_root)
    day = candidate.bar_date(source_bar_date)
    checked = candidate.timestamp(verified_at) if verified_at is not None else dt.datetime.now(candidate.UTC)
    mature = dt.datetime.combine(day + dt.timedelta(days=1), dt.time(), candidate.UTC) + dt.timedelta(minutes=10)
    if checked < mature or day < dt.date(2026, 9, 1):
        raise candidate.Rejected("source_not_mature")
    runner, context = _load_runner(inputs, contract)
    records = load_daily_prefix(inputs, runner, context, day)
    source, prefix = load_source_prefix(_safe(inputs.archive_root, "decisions.jsonl"), day, contract)
    market_hashes = {record["bar_date"]: record["record_hash"] for record in records}
    if any(record["decision_payload"]["market_record_hash"] != market_hashes.get(record["decision_payload"]["bar_date"])
           for record in prefix):
        raise candidate.Rejected("source_market_mismatch")
    causal_hash, raw_hashes, normalization = verify_normalized_inputs(inputs, runner, records, contract["universe"])
    market = runner.extend_trend_market(context["trend_market"], context["cointegration_market"], records)
    derived = runner.simulate_trend_forward(market, context["trend_config"], runner.protocol.FORWARD_START, day + dt.timedelta(days=1))
    # Compare ALL selected-prefix targets; older altered targets cannot be hidden
    # by recomputing the last journal hash alone.
    by_date = {d: weights for d, weights in zip(derived["dates"], derived["targets"])}
    targets = None
    for record in prefix:
        date = candidate.bar_date(record["decision_payload"]["bar_date"])
        vector = {symbol: float(weight) for symbol, weight in zip(market["symbols"], by_date[date])}
        targets = candidate.complete_targets(vector, contract)
        claimed = candidate.complete_targets(record["decision_payload"]["research_targets"]["trend_component_weights"], contract)
        if targets != claimed:
            raise candidate.Rejected("derived_target_mismatch")
    code_hashes = {"adapter": hashlib.sha256(pathlib.Path(candidate.__file__).read_bytes()).hexdigest(),
                   "verifier": hashlib.sha256(pathlib.Path(__file__).read_bytes()).hexdigest()}
    completed = checked if verified_at is not None else dt.datetime.now(candidate.UTC)
    if completed < checked:
        raise candidate.Rejected("verifier_clock_regression")
    return candidate.seal_receipt({
        "schema_version": 1, "kind": "v13-original-derivation-v1", "verifier_version": VERSION,
        "candidate_contract_sha256": candidate.CONTRACT_SHA256, "code_hashes": code_hashes,
        "scientific_lineage_ref": contract["scientific_lineage_ref"], "universe_hash": contract["universe_hash"],
        "source_record_hash": source["journal_record_hash"], "source_bar_date": day.isoformat(),
        "source_prefix_records": len(prefix), "daily_prefix_records": len(records),
        "source_journal_prefix_hash": candidate.digest(prefix), "causal_input_hash": causal_hash,
        "raw_response_hashes": raw_hashes, "targets": targets, "verified_at": completed.isoformat(),
        "verification_clock_source": "supplied_diagnostic_clock" if verified_at is not None else "process_completion_clock",
        "funding_normalization_encodings_observed": normalization,
        "derivation_status": "VERIFIED", "availability_status": "UNRESOLVED",
        "availability_reason": "independent_publication_and_dependency_receipts_required",
        "source_available_at": None, "research_only": True, "execution_approved": False,
        "issuable": False, "issuance_denial": "binding_unapproved",
        "independent_custody_verified": False, "kucoin_order_admissibility_proven": False})


def publish_diagnostic(output_root, receipt):
    """Exclusive, durable candidate artifact; no overwrite or historical append."""
    candidate.check_receipt(receipt, receipt.get("receipt_hash"))
    if (receipt.get("research_only") is not True or receipt.get("execution_approved") is not False
            or receipt.get("issuable") is not False or receipt.get("kind") != "v13-original-derivation-v1"):
        raise candidate.Rejected("not_diagnostic_receipt")
    root = pathlib.Path(output_root)
    if "octobot-local" in root.resolve().parts or root.is_symlink():
        raise candidate.Rejected("operational_output_forbidden")
    root.mkdir(parents=True, exist_ok=True)
    payload = candidate.canonical_bytes(receipt) + b"\n"
    path = root / (receipt["receipt_hash"] + ".json")
    try:
        fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    except FileExistsError:
        if path.is_symlink() or path.read_bytes() != payload:
            raise candidate.Rejected("diagnostic_output_conflict")
        # An earlier failed fsync may leave equal bytes. Sync again on retry.
        fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW)
        try:
            os.fsync(fd)
        finally:
            os.close(fd)
        directory = os.open(root, os.O_RDONLY | os.O_DIRECTORY)
        try:
            os.fsync(directory)
        finally:
            os.close(directory)
        return path
    with os.fdopen(fd, "wb") as stream:
        stream.write(payload)
        stream.flush()
        os.fsync(stream.fileno())
    directory = os.open(root, os.O_RDONLY | os.O_DIRECTORY)
    try:
        os.fsync(directory)
    finally:
        os.close(directory)
    return path


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("repo-root", "research-root", "archive-root", "implementation-lock"):
        parser.add_argument("--" + name, required=True, type=pathlib.Path)
    parser.add_argument("--source-bar-date", required=True)
    parser.add_argument("--output-dir", type=pathlib.Path)
    args = parser.parse_args(argv)
    try:
        if args.output_dir and any(args.output_dir.resolve().is_relative_to(p.resolve()) for p in
                                   [args.repo_root, args.research_root, args.archive_root, args.implementation_lock.parent]):
            raise candidate.Rejected("input_output_overlap")
        result = reconstruct(Inputs(args.repo_root, args.research_root, args.archive_root, args.implementation_lock),
                             source_bar_date=args.source_bar_date)
        if args.output_dir:
            publish_diagnostic(args.output_dir, result)
        print(candidate.canonical_bytes(result).decode())
        return 0
    except (candidate.Rejected, OSError, ValueError, KeyError, TypeError) as error:
        print(candidate.canonical_bytes({"status": "DENY", "reason": str(error),
                                        "issuable": False, "execution_approved": False}).decode())
        return 2


if __name__ == "__main__":
    sys.exit(main())
