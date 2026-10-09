"""Sealed, offline review procedure for the proposed 180-day BTC research run."""
from __future__ import annotations

import datetime as dt
import hashlib
import importlib.util
import json
import math
from pathlib import Path
import random
import sqlite3

PATH = Path(__file__).with_name("v13_btc_research_v2.py")
SPEC = importlib.util.spec_from_file_location("v13_btc_research_v2_eval", PATH)
p = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(p)

SLOTS = 180
BLOCK = 14
RESAMPLES = 10_000
SEED = 13120


def percentile(sorted_values, fraction):
    pos = (len(sorted_values)-1)*fraction
    lower = int(pos)
    upper = min(lower+1,len(sorted_values)-1)
    weight = pos-lower
    return sorted_values[lower]*(1-weight)+sorted_values[upper]*weight


def circular_ci(calendar_outcomes):
    """Two-sided 95% percentile CI over 180 calendar slots, omitting inactive days."""
    if len(calendar_outcomes) != SLOTS:
        raise ValueError("WINDOW_INVALID")
    rng = random.Random(SEED)
    means = []
    for _ in range(RESAMPLES):
        sample = []
        for _ in range(math.ceil(SLOTS/BLOCK)):
            first = rng.randrange(SLOTS)
            sample.extend(calendar_outcomes[(first+j)%SLOTS] for j in range(BLOCK))
        values = [x for x in sample[:SLOTS] if x is not None]
        if not values:
            raise ValueError("BOOTSTRAP_EMPTY_DIRECTIONAL_SAMPLE")
        means.append(sum(values)/len(values))
    means.sort()
    return percentile(means,0.025), percentile(means,0.975)


def review(db_path, archive, start_slot, reviewed_at):
    """Read-only final review. Deliberately unavailable before every outcome can mature."""
    start = p.slot_time(start_slot)
    if p.utc_time(reviewed_at) < start + dt.timedelta(days=SLOTS+1):
        raise ValueError("PERFORMANCE_SEALED_UNTIL_CUTOFF")
    db = sqlite3.connect(f"file:{Path(db_path)}?mode=ro", uri=True)
    try:
        slots = db.execute("SELECT slot_utc,decision_json,provenance_json,recorded_at,previous_hash,record_hash FROM slots ORDER BY rowid").fetchall()
        outcomes = {row[0]: (json.loads(row[1]),row[2]) for row in
                    db.execute("SELECT slot_utc,outcome_json,outcome_id FROM outcomes")}
    finally:
        db.close()
    previous = None
    by_slot = {}
    source_by_slot = {}
    actual_producer_hash = hashlib.sha256(PATH.read_bytes()).hexdigest()
    for slot, raw, provenance, recorded_at, parent, record_hash in slots:
        decision = json.loads(raw)
        source = json.loads(provenance) if provenance else None
        if (parent != previous or p.sha({"decision":decision,"provenance":source,
                                         "recorded_at":recorded_at,"previous_hash":parent}) != record_hash
            or decision.get("slot_utc") != slot or
            p.sha({k:v for k,v in decision.items() if k != "decision_id"}) != decision.get("decision_id")):
            raise ValueError("SLOT_CHAIN_INVALID")
        previous = record_hash
        by_slot[slot] = decision
        source_by_slot[slot] = source
    if any(slot not in by_slot for slot in outcomes):
        raise ValueError("ORPHAN_OUTCOME")
    calendar = []
    counts = {key:0 for key in p.TERMINAL}
    for i in range(SLOTS):
        key = (start + dt.timedelta(days=i)).isoformat()
        decision = by_slot.get(key)
        if decision is None:
            raise ValueError("UNRECORDED_SLOT")
        state = decision["status"]
        if state not in counts:
            raise ValueError("STATE_INVALID")
        counts[state] += 1
        if state != "MISSING":
            source = source_by_slot[key]
            if not source or decision.get("producer_sha256") != actual_producer_hash:
                raise ValueError("PRODUCER_OR_SOURCE_INVALID")
            receipt, _ = p.load_receipt(archive, source["receipt_id"])
            if (receipt["raw_sha256"] != source["raw_sha256"]
                or receipt["received_at"] != source["received_at"]):
                raise ValueError("SOURCE_PROVENANCE_INVALID")
            reconstructed, _ = p.produce(archive, source["receipt_id"], key,
                                         max(p.utc_time(source["received_at"]),
                                             p.slot_time(key)).isoformat(),
                                         actual_producer_hash)
            if reconstructed != decision:
                raise ValueError("SOURCE_DERIVATION_INVALID")
        outcome_pair = outcomes.get(key)
        if state in ("LONG","SHORT") and outcome_pair is not None:
            outcome, outcome_id = outcome_pair
            outcome_receipt, outcome_bars = p.load_receipt(archive, outcome["receipt_id"])
            expected_bar = int(p.slot_time(key).replace(minute=0).timestamp()*1000)
            matched = [bar for bar in outcome_bars if bar[0] == expected_bar]
            expected_signed = (math.log(float(p.Decimal(matched[0][1]) /
                                              p.Decimal(decision["causal_bars"][-1][1])))
                               * (1 if state == "LONG" else -1)) if len(matched) == 1 else None
            if (p.sha(outcome) != outcome_id or outcome.get("decision_id") != decision["decision_id"]
                or outcome.get("base_close") != decision["causal_bars"][-1][1]
                or outcome.get("outcome_bar_start_ms") != expected_bar
                or len(matched) != 1 or outcome.get("outcome_close") != matched[0][1]
                or outcome.get("raw_sha256") != outcome_receipt["raw_sha256"]
                or outcome.get("available_at") != outcome_receipt["received_at"]
                or p.utc_time(outcome_receipt["received_at"]) < p.slot_time(key)+dt.timedelta(days=1)
                or not math.isfinite(outcome.get("signed_log_outcome",float("nan")))
                or not math.isclose(outcome["signed_log_outcome"],expected_signed,rel_tol=0,abs_tol=1e-15)):
                raise ValueError("OUTCOME_INTEGRITY_FAILURE")
            calendar.append(outcome["signed_log_outcome"])
        elif outcome_pair is not None:
            raise ValueError("OUTCOME_NON_DIRECTIONAL")
        else:
            calendar.append(None)
    mature_long = sum(1 for i,x in enumerate(calendar) if x is not None and
                      by_slot[(start+dt.timedelta(days=i)).isoformat()]["status"] == "LONG")
    mature_short = sum(1 for i,x in enumerate(calendar) if x is not None and
                       by_slot[(start+dt.timedelta(days=i)).isoformat()]["status"] == "SHORT")
    if counts["MISSING"] > 10 or mature_long+mature_short < 60 or min(mature_long,mature_short) < 20:
        return {"state":"NOT_YET_MATURE","counts":counts,
                "mature_long":mature_long,"mature_short":mature_short}
    values = [x for x in calendar if x is not None]
    mean = sum(values)/len(values)
    low,high = circular_ci(calendar)
    return {"state":"SCIENTIFIC_GATE_CANDIDATE_PASS" if mean > 0 and low > 0 else "SCIENTIFIC_GATE_FAILED",
            "counts":counts,"mature_long":mature_long,"mature_short":mature_short,
            "mean_signed_log_outcome":mean,"ci_two_sided_95_percentile":[low,high],
            "method":"circular_moving_block_14_calendar_slots_10000_resamples_seed_13120"}
