"""Independent derivation check for offline BTC research V2 records."""
from __future__ import annotations

import hashlib
import importlib.util
from pathlib import Path

PATH = Path(__file__).with_name("v13_btc_research_v2.py")
SPEC = importlib.util.spec_from_file_location("v13_btc_research_v2", PATH)
producer = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(producer)


def verify(archive, decision, provenance, expected_producer_sha256):
    if hashlib.sha256(PATH.read_bytes()).hexdigest() != expected_producer_sha256:
        raise ValueError("PRODUCER_HASH_MISMATCH")
    if decision.get("producer_sha256") != expected_producer_sha256:
        raise ValueError("DECISION_PRODUCER_MISMATCH")
    if decision.get("status") == "MISSING":
        raise ValueError("MISSING_HAS_NO_SOURCE_DERIVATION")
    receipt, _ = producer.load_receipt(archive, provenance["receipt_id"])
    if receipt["raw_sha256"] != provenance["raw_sha256"] or receipt["received_at"] != provenance["received_at"]:
        raise ValueError("PROVENANCE_MISMATCH")
    observed = max(producer.utc_time(receipt["received_at"]),
                   producer.slot_time(decision["slot_utc"]))
    reconstructed, _ = producer.produce(archive, provenance["receipt_id"],
                                        decision["slot_utc"], observed.isoformat(),
                                        expected_producer_sha256)
    if reconstructed != decision:
        raise ValueError("DERIVATION_MISMATCH")
    return {"verified": True, "decision_id": decision["decision_id"],
            "observation_id": decision["observation_id"]}
