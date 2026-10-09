"""Independent archive binding and deterministic derivation check for research proposals."""
from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
from pathlib import Path

_PRODUCER_PATH = Path(__file__).with_name("v13_btc_research_producer.py")
_SPEC = importlib.util.spec_from_file_location("v13_btc_research_producer", _PRODUCER_PATH)
producer = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(producer)


def verify(archive, contract, expected_manifest_sha256, expected_producer_sha256, result):
    # Both trusted paths and both expected hashes are supplied by the verifier's
    # operator/configuration, never by the proposal being checked.
    doc = producer.manifest(contract)
    if producer.digest(doc) != expected_manifest_sha256:
        raise ValueError("manifest_binding_failed")
    code_hash = hashlib.sha256(Path(producer.__file__).read_bytes()).hexdigest()
    if code_hash != expected_producer_sha256:
        raise ValueError("producer_code_binding_failed")
    if not isinstance(result, dict) or set(result) != {"status", "payload", "decision_id"} or result["status"] not in {"PROPOSAL", "NO_PROPOSAL"}:
        raise ValueError("proposal_schema_invalid")
    payload = result["payload"]
    if not isinstance(payload, dict) or payload.get("manifest_sha256") != expected_manifest_sha256:
        raise ValueError("proposal_manifest_invalid")
    if result["decision_id"] != producer.digest(payload):
        raise ValueError("decision_hash_invalid")
    # Snapshot lookup uses only the hash in the configured archive. The proposal
    # cannot choose a path, endpoint, implementation or an alternate manifest.
    reconstructed = producer.decision(archive, payload.get("source_record_hash"),
                                      contract, payload.get("decision_timestamp"))
    if reconstructed != result:
        raise ValueError("derivation_mismatch")
    return {"verified": True, "status": result["status"], "decision_id": result["decision_id"],
            "source_record_hash": payload["source_record_hash"]}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--archive", type=Path, required=True)
    parser.add_argument("--contract", type=Path, required=True)
    parser.add_argument("--manifest-sha256", required=True)
    parser.add_argument("--producer-sha256", required=True)
    parser.add_argument("--proposal", type=Path, required=True)
    args = parser.parse_args()
    result = json.loads(args.proposal.read_text(), object_pairs_hook=producer.unique)
    print(json.dumps(verify(args.archive, args.contract, args.manifest_sha256,
                            args.producer_sha256, result), sort_keys=True))


if __name__ == "__main__":
    main()
