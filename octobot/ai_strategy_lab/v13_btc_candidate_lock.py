"""Offline consistency check for the V13 BTC paper-candidate designation."""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import stat

PATHS = {
    "research_contract": "octobot/ai_strategy_lab/v13_btc_research_contract_v1.json",
    "producer": "octobot/ai_strategy_lab/v13_btc_research_producer.py",
    "verifier": "octobot/ai_strategy_lab/v13_btc_research_verify.py",
    "operational_protocol": "octobot/ai_strategy_lab/v13_btc_experiment_protocol_v1.json",
}
FLAGS = ("issuer_authorized", "paper_orders_authorized", "orders_authorized",
         "automatic_promotion", "inherited_authorizations", "inherited_performance")


def _read(root, relative):
    path = root / relative
    fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW)
    try:
        info = os.fstat(fd)
        if not stat.S_ISREG(info.st_mode) or info.st_size > 1_000_000:
            raise ValueError("candidate_artifact_invalid")
        with os.fdopen(fd, "rb") as stream:
            return stream.read()
    except BaseException:
        try:
            os.close(fd)
        except OSError:
            pass
        raise


def verify(root, designation_path):
    """Check a review artifact; never update the issuer's trusted config."""
    root = Path(root)
    lock = json.loads(Path(designation_path).read_text())
    if (lock.get("schema_version") != 1 or lock.get("designation") != "PAPER_CANDIDATE_ONLY"
        or lock.get("allowed_use") != "offline_paper_candidate_review_only"
        or lock.get("scientific_validity") != "UNASSESSED"
        or any(lock.get(key) is not False for key in FLAGS)):
        raise ValueError("candidate_status_invalid")
    values = {}
    for prefix, relative in PATHS.items():
        if lock.get(prefix + "_path") != relative:
            raise ValueError("candidate_path_invalid")
        data = _read(root, relative)
        actual = hashlib.sha256(data).hexdigest()
        if lock.get(prefix + "_file_sha256") != actual:
            raise ValueError("candidate_artifact_hash_mismatch:" + prefix)
        values[prefix] = json.loads(data) if prefix in ("research_contract", "operational_protocol") else actual
    contract, protocol = values["research_contract"], values["operational_protocol"]
    for lock_key, contract_key in (("experiment_id", "experiment_id"),
        ("account", "account"), ("symbol", "symbol"),
        ("exchange_symbol", "exchange_symbol"), ("strategy", "strategy"),
        ("strategy_lineage_hash", "lineage_root"),
        ("producer_version", "producer_version"),
        ("proposal_schema_version", "proposal_schema_version"),
        ("source", "source"), ("source_endpoint", "endpoint")):
        if lock.get(lock_key) != contract.get(contract_key):
            raise ValueError("candidate_contract_identity_mismatch:" + lock_key)
    for key in ("experiment_id", "account", "symbol", "exchange_symbol", "strategy"):
        if lock[key] != protocol.get(key):
            raise ValueError("candidate_protocol_identity_mismatch:" + key)
    if (lock["strategy_lineage_hash"] != protocol.get("lineage_root")
        or lock.get("source_snapshot_schema_version") != 1
        or contract.get("status") != "CANDIDATE_RESEARCH_ONLY_NOT_APPROVED_FOR_EXECUTION"
        or protocol.get("producer_status") != "UNRESOLVED"
        or protocol.get("producer_implementation") is not None):
        raise ValueError("candidate_boundary_invalid")
    return {"designation": "PAPER_CANDIDATE_ONLY", "identity_bound": True,
            "artifacts_bound": True, "issuer_authorized": False,
            "paper_orders_authorized": False}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--designation", type=Path, required=True)
    args = parser.parse_args()
    print(json.dumps(verify(args.root, args.designation), sort_keys=True))


if __name__ == "__main__":
    main()
