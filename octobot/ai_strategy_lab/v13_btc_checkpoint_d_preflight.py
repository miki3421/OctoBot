"""Read-only Checkpoint D boundary probe. Never issues or executes."""
from __future__ import annotations

import datetime as dt
import json
from pathlib import Path
import sqlite3

import importlib.util

_VERIFY_PATH = Path(__file__).with_name("v13_btc_research_verify.py")
_SPEC = importlib.util.spec_from_file_location("v13_btc_research_verify", _VERIFY_PATH)
verifier = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(verifier)

UTC = dt.timezone.utc


def probe(archive, contract, protocol_path, result, *, manifest_hash, code_hash,
          now, issuer_config=None, approval_db=None):
    """Return evidence and blocking gates. There is intentionally no approval path."""
    try:
        verified = verifier.verify(archive, contract, manifest_hash, code_hash, result)
    except (ValueError, TypeError, KeyError, OSError, json.JSONDecodeError) as exc:
        return {"state": "DENY", "reason": "source_or_derivation_invalid",
                "detail": type(exc).__name__ + ":" + str(exc), "authorization_created": False}
    if verified["status"] != "PROPOSAL":
        return {"state": "DENY", "reason": "no_proposal", "authorization_created": False}
    try:
        protocol = json.loads(Path(protocol_path).read_text(),
                              object_pairs_hook=verifier.producer.unique)
        payload = result["payload"]
        for source, target in (("experiment_id", "experiment_id"),
                               ("account", "account"), ("symbol", "symbol"),
                               ("strategy", "strategy"),
                               ("strategy_lineage_hash", "lineage_root")):
            if payload[source] != protocol[target]:
                return {"state": "DENY", "reason": "protocol_identity_mismatch",
                        "authorization_created": False}
        at = verifier.producer.parse_time(payload["decision_timestamp"])
        available = verifier.producer.parse_time(payload["available_at"])
        if now.tzinfo is None or not available <= at <= now or now-at > dt.timedelta(minutes=30):
            return {"state": "DENY", "reason": "proposal_stale_or_noncausal",
                    "authorization_created": False}
        gates = []
        if protocol.get("producer_status") != "VALIDATED":
            gates.append("producer_unresolved")
        if verifier.producer.manifest(contract)["status"] != "APPROVED_FOR_ISSUER":
            gates.append("research_contract_not_approved")
        if issuer_config is None or not Path(issuer_config).is_file():
            gates.append("issuer_unavailable")
        if approval_db is None or not Path(approval_db).is_file():
            gates.append("approval_storage_unavailable")
        else:
            try:
                with sqlite3.connect("file:" + str(Path(approval_db).resolve()) + "?mode=ro",
                                     uri=True) as db:
                    if db.execute("PRAGMA integrity_check").fetchone()[0] != "ok":
                        gates.append("approval_storage_corrupt")
            except (sqlite3.Error, OSError):
                gates.append("approval_storage_unavailable")
        # Unknown exchange minima are a separate and unavoidable fill veto.
        gates.append("exchange_minima_unknown")
        return {"state": "BLOCKED", "decision_verified": True,
                "decision_id": result["decision_id"], "gates": gates,
                "authorization_created": False, "paper_fill_created": False}
    except (ValueError, TypeError, KeyError, OSError, json.JSONDecodeError) as exc:
        return {"state": "DENY", "reason": "protocol_or_storage_invalid",
                "detail": type(exc).__name__ + ":" + str(exc), "authorization_created": False}
