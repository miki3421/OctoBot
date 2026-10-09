"""Offline, research-only BTC daily proposal producer; no execution imports."""
from __future__ import annotations

import argparse
import datetime as dt
import fcntl
import hashlib
import json
import os
from pathlib import Path
import stat
import urllib.parse
import urllib.request

UTC = dt.timezone.utc
DAY = dt.timedelta(days=1)
EXPECTED_KEYS = frozenset((
    "schema_version", "status", "experiment_id", "account", "symbol", "exchange_symbol",
    "strategy", "lineage_root", "producer_version", "source", "endpoint",
    "granularity_minutes", "lookback_fast_days", "lookback_slow_days",
    "required_contiguous_bars", "decision_lag_minutes", "target_weight_abs",
    "proposal_schema_version", "inherited_authorizations", "scientific_validity"))


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False).encode()


def digest(value):
    return hashlib.sha256(canonical(value)).hexdigest()


def unique(pairs):
    value = {}
    for key, item in pairs:
        if key in value:
            raise ValueError("duplicate_json_key")
        value[key] = item
    return value


def parse_time(value):
    if not isinstance(value, str):
        raise ValueError("time_invalid")
    result = dt.datetime.fromisoformat(value.replace("Z", "+00:00"))
    if result.tzinfo is None or result.utcoffset() != dt.timedelta(0):
        raise ValueError("time_not_utc")
    return result.astimezone(UTC)


def manifest(path):
    doc = json.loads(Path(path).read_text(), object_pairs_hook=unique)
    if (set(doc) != EXPECTED_KEYS or doc["schema_version"] != 1
        or doc["status"] != "CANDIDATE_RESEARCH_ONLY_NOT_APPROVED_FOR_EXECUTION"
        or doc["experiment_id"] != "v13-btc-paper-new-v1"
        or doc["account"] != "v13-paper-v2" or doc["symbol"] != "BTC/USDT:USDT"
        or doc["exchange_symbol"] != "XBTUSDTM"
        or doc["strategy"] != "v13-btc-paper-producer-v1"
        or doc["producer_version"] != "btc-daily-dual-momentum-research-v1"
        or doc["source"] != "kucoin-classic-futures-public-klines"
        or doc["endpoint"] != "https://api-futures.kucoin.com/api/v1/kline/query"
        or doc["granularity_minutes"] != 1440
        or doc["required_contiguous_bars"] != doc["lookback_slow_days"] + 1
        or not 0 < doc["lookback_fast_days"] < doc["lookback_slow_days"] <= 200
        or doc["decision_lag_minutes"] != 10
        or doc["target_weight_abs"] != "0.10"
        or doc["proposal_schema_version"] != 1
        or doc["inherited_authorizations"] is not False
        or doc["scientific_validity"] != "UNASSESSED"
        or not isinstance(doc["lineage_root"], str) or len(doc["lineage_root"]) != 64):
        raise ValueError("research_manifest_invalid")
    int(doc["lineage_root"], 16)
    return doc


def request_url(doc, start_ms, end_ms):
    params = urllib.parse.urlencode({"symbol": doc["exchange_symbol"],
        "granularity": doc["granularity_minutes"], "from": start_ms, "to": end_ms})
    return doc["endpoint"] + "?" + params


def _new_file(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o440)
    except FileExistsError:
        if path.read_bytes() != data:
            raise ValueError("archive_content_conflict")
        return
    try:
        with os.fdopen(fd, "wb") as stream:
            stream.write(data)
            stream.flush()
            os.fsync(stream.fileno())
    except BaseException:
        path.unlink(missing_ok=True)
        raise


def _read_archive(path, limit):
    fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW)
    try:
        info = os.fstat(fd)
        if not stat.S_ISREG(info.st_mode) or info.st_size > limit:
            raise ValueError("archive_file_invalid")
        with os.fdopen(fd, "rb") as stream:
            return stream.read()
    except BaseException:
        try:
            os.close(fd)
        except OSError:
            pass
        raise


def collect(archive, contract, *, now=None, fetch=None):
    """Capture one public 140-day page. Returned snapshot is historical replay input."""
    doc = manifest(contract)
    now = now or (lambda: dt.datetime.now(UTC))
    fetch = fetch or (lambda url: urllib.request.urlopen(url, timeout=20).read())
    started = now()
    end = int(started.timestamp() * 1000)
    start = end - 140 * 86400000
    url = request_url(doc, start, end)
    payload = fetch(url)
    received = now()
    if received < started or not isinstance(payload, bytes) or len(payload) > 2_000_000:
        raise ValueError("response_invalid")
    # Validate before archiving. The original response is retained byte-for-byte.
    parse_rows(payload)
    raw_hash = hashlib.sha256(payload).hexdigest()
    snapshot = {"schema_version": 1, "source": doc["source"],
        "experiment_id": doc["experiment_id"], "symbol": doc["symbol"],
        "exchange_symbol": doc["exchange_symbol"], "granularity_minutes": 1440,
        "request_url": url, "request_started_at": started.isoformat(),
        "received_at": received.isoformat(), "available_at": received.isoformat(),
        "raw_sha256": raw_hash, "acquisition_kind": "retrospective_public_fetch"}
    snap_hash = digest(snapshot)
    root = Path(archive)
    _new_file(root / "raw" / (raw_hash + ".json"), payload)
    _new_file(root / "snapshots" / (snap_hash + ".json"), canonical(snapshot) + b"\n")
    return snap_hash


def parse_rows(payload):
    body = json.loads(payload, object_pairs_hook=unique)
    if not isinstance(body, dict) or set(body) != {"code", "data"} or body["code"] != "200000" or not isinstance(body["data"], list):
        raise ValueError("kline_response_invalid")
    rows = []
    for raw in body["data"]:
        if not isinstance(raw, list) or len(raw) != 7 or type(raw[0]) is not int:
            raise ValueError("kline_row_invalid")
        if raw[0] % 86400000:
            raise ValueError("kline_time_unaligned")
        try:
            close = float(raw[4])
        except (TypeError, ValueError):
            raise ValueError("kline_close_invalid") from None
        if not 0 < close < float("inf"):
            raise ValueError("kline_close_invalid")
        if rows and raw[0] <= rows[-1][0]:
            raise ValueError("kline_order_or_duplicate")
        rows.append((raw[0], close))
    return rows


def load_snapshot(archive, snap_hash, doc):
    if len(snap_hash) != 64 or any(c not in "0123456789abcdef" for c in snap_hash):
        raise ValueError("snapshot_hash_invalid")
    root = Path(archive)
    snap_bytes = _read_archive(root / "snapshots" / (snap_hash + ".json"), 8192)
    snapshot = json.loads(snap_bytes, object_pairs_hook=unique)
    if digest(snapshot) != snap_hash or set(snapshot) != {
        "schema_version", "source", "experiment_id", "symbol", "exchange_symbol",
        "granularity_minutes", "request_url", "request_started_at", "received_at",
        "available_at", "raw_sha256", "acquisition_kind"}:
        raise ValueError("snapshot_content_invalid")
    if (snapshot["schema_version"] != 1 or snapshot["source"] != doc["source"]
        or snapshot["experiment_id"] != doc["experiment_id"]
        or snapshot["symbol"] != doc["symbol"]
        or snapshot["exchange_symbol"] != doc["exchange_symbol"]
        or snapshot["granularity_minutes"] != 1440
        or snapshot["acquisition_kind"] != "retrospective_public_fetch"):
        raise ValueError("snapshot_identity_invalid")
    parsed = urllib.parse.urlparse(snapshot["request_url"])
    query = urllib.parse.parse_qs(parsed.query, strict_parsing=True)
    if parsed.scheme + "://" + parsed.netloc + parsed.path != doc["endpoint"] or set(query) != {"symbol", "granularity", "from", "to"}:
        raise ValueError("snapshot_source_invalid")
    try:
        start, end = int(query["from"][0]), int(query["to"][0])
    except (ValueError, IndexError):
        raise ValueError("snapshot_query_invalid") from None
    if snapshot["request_url"] != request_url(doc, start, end) or end - start != 140 * 86400000:
        raise ValueError("snapshot_query_invalid")
    started, received, available = (parse_time(snapshot[k]) for k in
        ("request_started_at", "received_at", "available_at"))
    if not started <= received <= available or end != int(started.timestamp() * 1000):
        raise ValueError("snapshot_timing_invalid")
    raw_hash = snapshot["raw_sha256"]
    if not isinstance(raw_hash, str) or len(raw_hash) != 64 or any(c not in "0123456789abcdef" for c in raw_hash):
        raise ValueError("raw_hash_invalid")
    payload = _read_archive(root / "raw" / (raw_hash + ".json"), 2_000_000)
    if hashlib.sha256(payload).hexdigest() != raw_hash:
        raise ValueError("raw_content_changed")
    rows = parse_rows(payload)
    if any(not start <= stamp <= end for stamp, _ in rows):
        raise ValueError("kline_outside_request")
    return snapshot, rows


def decision(archive, snap_hash, contract, decision_at):
    doc = manifest(contract)
    t = parse_time(decision_at)
    snapshot, rows = load_snapshot(archive, snap_hash, doc)
    def abstain(reason):
        payload = {"schema_version": 1, "research_only": True,
                   "execution_approved": False, "experiment_id": doc["experiment_id"],
                   "account": doc["account"], "symbol": doc["symbol"],
                   "producer_version": doc["producer_version"],
                   "strategy_lineage_hash": doc["lineage_root"],
                   "manifest_sha256": digest(doc), "source_record_hash": snap_hash,
                   "decision_timestamp": t.isoformat(), "reason": reason}
        return {"status": "NO_PROPOSAL", "payload": payload,
                "decision_id": digest(payload)}
    if parse_time(snapshot["available_at"]) > t:
        return abstain("source_available_after_decision")
    lag = dt.timedelta(minutes=doc["decision_lag_minutes"])
    eligible = [(stamp, close) for stamp, close in rows if
                dt.datetime.fromtimestamp(stamp / 1000, UTC) + DAY + lag <= t]
    if not eligible:
        return abstain("no_closed_available_bar")
    latest = dt.datetime.fromtimestamp(eligible[-1][0] / 1000, UTC)
    expected = t.replace(hour=0, minute=0, second=0, microsecond=0) - DAY
    if latest != expected:
        return abstain("latest_bar_missing_or_stale")
    count = doc["required_contiguous_bars"]
    if len(eligible) < count:
        return abstain("warmup_incomplete")
    window = eligible[-count:]
    if any(window[i][0] - window[i-1][0] != 86400000 for i in range(1, len(window))):
        return abstain("daily_gap")
    fast = window[-1][1] / window[-1-doc["lookback_fast_days"]][1] - 1
    slow = window[-1][1] / window[-1-doc["lookback_slow_days"]][1] - 1
    if fast > 0 and slow > 0:
        direction, target = "LONG", doc["target_weight_abs"]
    elif fast < 0 and slow < 0:
        direction, target = "SHORT", "-" + doc["target_weight_abs"]
    else:
        return abstain("momentum_disagreement_or_zero")
    payload = {"schema_version": 1, "research_only": True,
        "execution_approved": False, "experiment_id": doc["experiment_id"],
        "account": doc["account"], "symbol": doc["symbol"],
        "exchange_symbol": doc["exchange_symbol"], "strategy": doc["strategy"],
        "strategy_lineage_hash": doc["lineage_root"],
        "producer_version": doc["producer_version"], "manifest_sha256": digest(doc),
        "source_record_hash": snap_hash, "decision_timestamp": t.isoformat(),
        "available_at": snapshot["available_at"], "signal_bar_start": latest.isoformat(),
        "direction": direction,
        "target_weight": target}
    return {"status": "PROPOSAL", "payload": payload, "decision_id": digest(payload)}


def append_research_journal(path, result):
    if result.get("status") != "PROPOSAL":
        return False
    journal = Path(path)
    journal.parent.mkdir(parents=True, exist_ok=True)
    fd = os.open(journal, os.O_RDWR | os.O_CREAT | os.O_NOFOLLOW, 0o600)
    try:
        fcntl.flock(fd, fcntl.LOCK_EX)
        with os.fdopen(fd, "r+b", closefd=False) as stream:
            data = stream.read()
            if data and not data.endswith(b"\n"):
                raise ValueError("research_journal_partial")
            records = [json.loads(line, object_pairs_hook=unique) for line in data.splitlines()]
            previous = None
            for record in records:
                if record != {"result": record.get("result"), "previous_record_hash": previous,
                              "record_hash": digest({"result": record.get("result"), "previous_record_hash": previous})}:
                    raise ValueError("research_journal_chain_invalid")
                previous = record["record_hash"]
                if record["result"]["decision_id"] == result["decision_id"]:
                    return False
                old_payload = record["result"].get("payload", {})
                new_payload = result["payload"]
                if (old_payload.get("experiment_id") == new_payload["experiment_id"]
                    and old_payload.get("signal_bar_start") == new_payload["signal_bar_start"]):
                    raise ValueError("research_decision_slot_already_recorded")
            entry = {"result": result, "previous_record_hash": previous}
            entry["record_hash"] = digest(entry)
            stream.seek(0, os.SEEK_END)
            stream.write(canonical(entry) + b"\n")
            stream.flush()
            os.fsync(stream.fileno())
        return True
    finally:
        os.close(fd)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("mode", choices=("collect", "produce"))
    parser.add_argument("--archive", type=Path, required=True)
    parser.add_argument("--contract", type=Path, required=True)
    parser.add_argument("--snapshot-hash")
    parser.add_argument("--decision-at")
    parser.add_argument("--journal", type=Path)
    args = parser.parse_args()
    if args.mode == "collect":
        print(collect(args.archive, args.contract))
    else:
        if not args.snapshot_hash or not args.decision_at:
            parser.error("produce requires --snapshot-hash and --decision-at")
        result = decision(args.archive, args.snapshot_hash, args.contract, args.decision_at)
        if args.journal:
            append_research_journal(args.journal, result)
        print(json.dumps(result, sort_keys=True))


if __name__ == "__main__":
    main()
