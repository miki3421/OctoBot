"""Offline BTC forward-research candidate V2; no issuer or execution access."""
from __future__ import annotations

import datetime as dt
from decimal import Decimal, InvalidOperation
import hashlib
import json
import math
import os
from pathlib import Path
import sqlite3

UTC = dt.timezone.utc
DAY = dt.timedelta(days=1)
VERSION = "btc-daily-dual-momentum-research-v2"
EXPERIMENT = "v13-btc-paper-new-v1"
LINEAGE = "29ae069f52b7cb820fb54476d5e47e094ac1174a98186da9ada107e728a2efb7"
SYMBOL = "BTC/USDT:USDT"
EXCHANGE_SYMBOL = "XBTUSDTM"
TERMINAL = frozenset(("LONG", "SHORT", "NO_PROPOSAL", "MISSING"))
MISSING_REASONS = frozenset(("DATA_NOT_AVAILABLE", "STALE_DATA", "NONCONTIGUOUS_BARS",
                             "LATE_ACQUISITION", "SOURCE_FAILURE", "INTEGRITY_FAILURE"))


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"),
                      ensure_ascii=False, allow_nan=False).encode()


def sha(value):
    return hashlib.sha256(canonical(value)).hexdigest()


def pairs_unique(pairs):
    out = {}
    for key, val in pairs:
        if key in out:
            raise ValueError("DUPLICATE_JSON_KEY")
        out[key] = val
    return out


def utc_time(value):
    t = dt.datetime.fromisoformat(value.replace("Z", "+00:00"))
    if t.tzinfo is None or t.utcoffset() != dt.timedelta(0):
        raise ValueError("TIMESTAMP_INVALID")
    return t.astimezone(UTC)


def slot_time(value):
    t = utc_time(value)
    if (t.hour, t.minute, t.second, t.microsecond) != (0, 10, 0, 0):
        raise ValueError("SLOT_INVALID")
    return t


def close_text(value):
    if isinstance(value, bool) or not isinstance(value, (str, int, float)):
        raise ValueError("CLOSE_INVALID")
    try:
        number = Decimal(str(value))
    except InvalidOperation as exc:
        raise ValueError("CLOSE_INVALID") from exc
    if not number.is_finite() or number <= 0:
        raise ValueError("CLOSE_INVALID")
    return format(number.normalize(), "f")


def parse_raw(raw):
    body = json.loads(raw, object_pairs_hook=pairs_unique)
    if not isinstance(body, dict) or set(body) != {"code", "data"} or body["code"] != "200000" or not isinstance(body["data"], list):
        raise ValueError("SOURCE_INVALID")
    bars = []
    for row in body["data"]:
        if not isinstance(row, list) or len(row) != 7 or type(row[0]) is not int or row[0] % 86400000:
            raise ValueError("BAR_INVALID")
        bars.append([row[0], close_text(row[4])])
    # KuCoin's ordered response is required. Excluded bars can be permuted only
    # by a source adapter that canonicalizes and validates them separately.
    if any(bars[i][0] <= bars[i-1][0] for i in range(1, len(bars))):
        raise ValueError("BAR_ORDER_INVALID")
    return bars


def _atomic_new(path, data):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o440)
    except FileExistsError:
        if path.read_bytes() != data:
            raise ValueError("ARCHIVE_CONFLICT")
        return
    with os.fdopen(fd, "wb") as stream:
        stream.write(data)
        stream.flush()
        os.fsync(stream.fileno())


def capture(archive, raw, received_at, *, request_url=None):
    """Archive source bytes and receipt; URL/time are provenance, not features."""
    if not isinstance(raw, bytes) or len(raw) > 2_000_000:
        raise ValueError("SOURCE_INVALID")
    parse_raw(raw)
    received = utc_time(received_at).isoformat()
    raw_sha = hashlib.sha256(raw).hexdigest()
    receipt = {"schema_version": 2, "raw_sha256": raw_sha,
               "received_at": received, "request_url": request_url}
    receipt_id = sha(receipt)
    root = Path(archive)
    _atomic_new(root / "raw" / (raw_sha + ".json"), raw)
    _atomic_new(root / "receipts" / (receipt_id + ".json"), canonical(receipt) + b"\n")
    return receipt_id


def load_receipt(archive, receipt_id):
    if not isinstance(receipt_id, str) or len(receipt_id) != 64 or any(c not in "0123456789abcdef" for c in receipt_id):
        raise ValueError("RECEIPT_ID_INVALID")
    root = Path(archive)
    receipt = json.loads((root / "receipts" / (receipt_id + ".json")).read_bytes(), object_pairs_hook=pairs_unique)
    if set(receipt) != {"schema_version", "raw_sha256", "received_at", "request_url"} or receipt["schema_version"] != 2 or sha(receipt) != receipt_id:
        raise ValueError("RECEIPT_INVALID")
    raw_hash = receipt["raw_sha256"]
    if not isinstance(raw_hash, str) or len(raw_hash) != 64 or any(c not in "0123456789abcdef" for c in raw_hash):
        raise ValueError("RAW_HASH_INVALID")
    raw = (root / "raw" / (raw_hash + ".json")).read_bytes()
    if len(raw) > 2_000_000 or hashlib.sha256(raw).hexdigest() != raw_hash:
        raise ValueError("RAW_HASH_MISMATCH")
    return receipt, parse_raw(raw)


def _identity(slot, causal_sha):
    basis = {"experiment_id": EXPERIMENT, "lineage": LINEAGE, "producer_version": VERSION,
             "symbol": SYMBOL, "slot_utc": slot.isoformat(),
             "input_cutoff_utc": slot.isoformat(), "causal_input_sha256": causal_sha}
    return sha(basis)


def produce(archive, receipt_id, slot_utc, observed_at, producer_sha256):
    """Build a terminal research record. Caller archives the immutable source."""
    slot = slot_time(slot_utc)
    observed = utc_time(observed_at)
    if observed < slot:
        raise ValueError("OBSERVED_BEFORE_SLOT")
    if observed > slot + dt.timedelta(minutes=10):
        raise ValueError("SLOT_DEADLINE_PASSED")
    receipt, bars = load_receipt(archive, receipt_id)
    received = utc_time(receipt["received_at"])
    if received > observed or received > slot + dt.timedelta(minutes=10):
        raise ValueError("LATE_ACQUISITION")
    expected = int((slot.replace(minute=0) - DAY).timestamp() * 1000)
    eligible = [bar for bar in bars if bar[0] <= expected]
    if not eligible or eligible[-1][0] != expected:
        raise ValueError("STALE_DATA")
    causal = eligible[-121:]
    if len(causal) != 121:
        raise ValueError("DATA_NOT_AVAILABLE")
    if any(causal[i][0] - causal[i-1][0] != 86400000 for i in range(1, 121)):
        raise ValueError("NONCONTIGUOUS_BARS")
    causal_sha = sha(causal)
    observation_id = _identity(slot, causal_sha)
    fast = Decimal(causal[-1][1]) / Decimal(causal[-31][1]) - 1
    slow = Decimal(causal[-1][1]) / Decimal(causal[0][1]) - 1
    if fast > 0 and slow > 0:
        status, target, reason = "LONG", "0.10", "DUAL_MOMENTUM_POSITIVE"
    elif fast < 0 and slow < 0:
        status, target, reason = "SHORT", "-0.10", "DUAL_MOMENTUM_NEGATIVE"
    else:
        status, target, reason = "NO_PROPOSAL", None, "MOMENTUM_DISAGREEMENT_OR_ZERO"
    core = {"schema_version": 2, "research_only": True, "execution_approved": False,
            "experiment_id": EXPERIMENT, "lineage": LINEAGE, "producer_version": VERSION,
            "producer_sha256": producer_sha256, "symbol": SYMBOL,
            "exchange_symbol": EXCHANGE_SYMBOL, "slot_utc": slot.isoformat(),
            "observation_id": observation_id, "causal_input_sha256": causal_sha,
            "causal_bars": causal, "status": status, "target_weight": target,
            "reason_code": reason}
    return {**core, "decision_id": sha(core)}, {"receipt_id": receipt_id,
            "raw_sha256": receipt["raw_sha256"], "received_at": receipt["received_at"]}


def missing(slot_utc, observed_at, producer_sha256, reason_code):
    slot = slot_time(slot_utc)
    observed = utc_time(observed_at)
    if reason_code not in MISSING_REASONS or observed < slot or observed < slot + dt.timedelta(minutes=10):
        raise ValueError("MISSING_RECORD_INVALID")
    core = {"schema_version": 2, "research_only": True, "execution_approved": False,
            "experiment_id": EXPERIMENT, "lineage": LINEAGE, "producer_version": VERSION,
            "producer_sha256": producer_sha256, "symbol": SYMBOL,
            "exchange_symbol": EXCHANGE_SYMBOL, "slot_utc": slot.isoformat(),
            "observation_id": None, "causal_input_sha256": None,
            "causal_bars": None, "status": "MISSING", "target_weight": None,
            "reason_code": reason_code}
    return {**core, "decision_id": sha(core)}, None


def connect(path):
    db = sqlite3.connect(path, timeout=10, isolation_level=None)
    db.execute("PRAGMA journal_mode=WAL")
    db.execute("PRAGMA synchronous=FULL")
    db.executescript("""CREATE TABLE IF NOT EXISTS slots (
        slot_utc TEXT PRIMARY KEY, decision_id TEXT NOT NULL UNIQUE,
        decision_json BLOB NOT NULL, provenance_json BLOB,
        recorded_at TEXT NOT NULL, previous_hash TEXT, record_hash TEXT NOT NULL UNIQUE);
        CREATE TABLE IF NOT EXISTS conflicts (
        id INTEGER PRIMARY KEY, slot_utc TEXT NOT NULL, existing_id TEXT NOT NULL,
        conflicting_id TEXT NOT NULL, observed_at TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS outcomes (
        slot_utc TEXT PRIMARY KEY REFERENCES slots(slot_utc),
        outcome_json BLOB NOT NULL, outcome_id TEXT NOT NULL UNIQUE);
        CREATE TRIGGER IF NOT EXISTS slots_no_update BEFORE UPDATE ON slots BEGIN SELECT RAISE(ABORT,'immutable_slot'); END;
        CREATE TRIGGER IF NOT EXISTS slots_no_delete BEFORE DELETE ON slots BEGIN SELECT RAISE(ABORT,'immutable_slot'); END;
        CREATE TRIGGER IF NOT EXISTS outcomes_no_update BEFORE UPDATE ON outcomes BEGIN SELECT RAISE(ABORT,'immutable_outcome'); END;
        CREATE TRIGGER IF NOT EXISTS outcomes_no_delete BEFORE DELETE ON outcomes BEGIN SELECT RAISE(ABORT,'immutable_outcome'); END;""")
    return db


def append_slot(path, decision, provenance, observed_at):
    if (decision.get("status") not in TERMINAL
        or decision.get("decision_id") != sha({k:v for k,v in decision.items() if k != "decision_id"})
        or decision.get("research_only") is not True
        or decision.get("execution_approved") is not False
        or decision.get("experiment_id") != EXPERIMENT
        or decision.get("lineage") != LINEAGE
        or decision.get("producer_version") != VERSION
        or decision.get("symbol") != SYMBOL):
        raise ValueError("DECISION_INVALID")
    observed = utc_time(observed_at)
    slot = slot_time(decision["slot_utc"])
    if (observed < slot
        or (decision["status"] == "MISSING" and observed < slot + dt.timedelta(minutes=10))):
        raise ValueError("RECORD_TIME_INVALID")
    late_directional = (decision["status"] != "MISSING"
                        and observed > slot + dt.timedelta(minutes=10))
    if decision["status"] == "MISSING":
        if provenance is not None or decision.get("reason_code") not in MISSING_REASONS or decision.get("target_weight") is not None:
            raise ValueError("MISSING_RECORD_INVALID")
    elif (not isinstance(provenance, dict) or
          set(provenance) != {"receipt_id", "raw_sha256", "received_at"} or
          decision.get("observation_id") != _identity(slot, decision.get("causal_input_sha256")) or
          sha(decision.get("causal_bars")) != decision.get("causal_input_sha256")):
        raise ValueError("SOURCE_RECORD_INVALID")
    elif utc_time(provenance["received_at"]) > observed:
        raise ValueError("SOURCE_AVAILABLE_AFTER_RECORD")
    db = connect(path)
    try:
        db.execute("BEGIN IMMEDIATE")
        row = db.execute("SELECT decision_id FROM slots WHERE slot_utc=?", (decision["slot_utc"],)).fetchone()
        if row:
            if row[0] == decision["decision_id"]:
                db.execute("COMMIT")
                return False
            db.execute("INSERT INTO conflicts(slot_utc,existing_id,conflicting_id,observed_at) VALUES(?,?,?,?)",
                       (decision["slot_utc"], row[0], decision["decision_id"], observed_at))
            db.execute("COMMIT")
            raise ValueError("SLOT_INTEGRITY_CONFLICT")
        if late_directional:
            raise ValueError("RECORD_TIME_INVALID")
        prior = db.execute("SELECT record_hash FROM slots ORDER BY rowid DESC LIMIT 1").fetchone()
        previous = prior[0] if prior else None
        record_hash = sha({"decision":decision,"provenance":provenance,
                           "recorded_at":observed_at,"previous_hash":previous})
        db.execute("INSERT INTO slots VALUES(?,?,?,?,?,?,?)", (decision["slot_utc"], decision["decision_id"],
                   canonical(decision), canonical(provenance) if provenance else None,
                   observed_at, previous, record_hash))
        db.execute("COMMIT")
        return True
    except BaseException:
        if db.in_transaction:
            db.execute("ROLLBACK")
        raise
    finally:
        db.close()


def finalize_slot(path, archive, receipt_id, slot_utc, observed_at, producer_sha256):
    """Finalize one scheduled slot; late runs can record MISSING, never backfill signals."""
    slot = slot_time(slot_utc)
    now = utc_time(observed_at)
    deadline = slot + dt.timedelta(minutes=10)
    if now < slot:
        raise ValueError("SLOT_NOT_OPEN")
    if now > deadline:
        decision, provenance = missing(slot_utc, observed_at, producer_sha256,
                                       "LATE_ACQUISITION" if receipt_id else "SOURCE_FAILURE")
    elif receipt_id is None:
        if now < deadline:
            raise ValueError("SLOT_NOT_FINALIZABLE")
        decision, provenance = missing(slot_utc, observed_at, producer_sha256,
                                       "DATA_NOT_AVAILABLE")
    else:
        try:
            decision, provenance = produce(archive, receipt_id, slot_utc,
                                           observed_at, producer_sha256)
        except (ValueError, OSError, json.JSONDecodeError) as exc:
            if now < deadline:
                raise ValueError("SLOT_NOT_FINALIZABLE") from exc
            code = str(exc)
            reason = code if code in MISSING_REASONS else "INTEGRITY_FAILURE"
            decision, provenance = missing(slot_utc, observed_at, producer_sha256, reason)
    return append_slot(path, decision, provenance, observed_at), decision


def mature(path, archive, slot_utc, receipt_id):
    db = connect(path)
    try:
        db.execute("BEGIN IMMEDIATE")
        row = db.execute("SELECT decision_json FROM slots WHERE slot_utc=?", (slot_utc,)).fetchone()
        if not row:
            raise ValueError("SLOT_UNKNOWN")
        decision = json.loads(row[0])
        if decision["status"] not in ("LONG", "SHORT"):
            raise ValueError("OUTCOME_NOT_DIRECTIONAL")
        bars = decision["causal_bars"]
        if sha(bars) != decision["causal_input_sha256"] or sha({k:v for k,v in decision.items() if k != "decision_id"}) != decision["decision_id"]:
            raise ValueError("DECISION_INTEGRITY_FAILURE")
        receipt, observed_bars = load_receipt(archive, receipt_id)
        slot = slot_time(slot_utc)
        if utc_time(receipt["received_at"]) < slot + DAY:
            raise ValueError("OUTCOME_NOT_MATURE")
        expected = int(slot.replace(minute=0).timestamp() * 1000)
        matches = [bar for bar in observed_bars if bar[0] == expected]
        if len(matches) != 1:
            raise ValueError("OUTCOME_BAR_MISSING")
        base = Decimal(bars[-1][1]); final = Decimal(matches[0][1])
        signed = math.log(float(final / base)) * (1 if decision["status"] == "LONG" else -1)
        outcome = {"schema_version": 2, "slot_utc": slot_utc,
                   "decision_id": decision["decision_id"], "base_close": bars[-1][1],
                   "outcome_bar_start_ms": expected, "outcome_close": matches[0][1],
                   "signed_log_outcome": signed, "receipt_id": receipt_id,
                   "raw_sha256": receipt["raw_sha256"], "available_at": receipt["received_at"]}
        outcome_id = sha(outcome)
        prior = db.execute("SELECT outcome_id FROM outcomes WHERE slot_utc=?", (slot_utc,)).fetchone()
        if prior:
            if prior[0] != outcome_id:
                raise ValueError("OUTCOME_INTEGRITY_CONFLICT")
            db.execute("COMMIT")
            return False
        db.execute("INSERT INTO outcomes VALUES(?,?,?)", (slot_utc, canonical(outcome), outcome_id))
        db.execute("COMMIT")
        return True
    except BaseException:
        if db.in_transaction:
            db.execute("ROLLBACK")
        raise
    finally:
        db.close()
