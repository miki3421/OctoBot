"""Original V13 candidate proposal primitives; no issuance or execution surface.

Work card: work-card-fe78a248-3d67-45fa-86b0-bbc5eed8e71e.
The committed candidate is DRAFT. Validation proves shape/derivation only,
never custody, scientific quality, KuCoin admissibility or an approval.
"""

from __future__ import annotations

import datetime as dt
import hashlib
import json
import math
import pathlib
import re

UTC = dt.timezone.utc
CONTRACT_SHA256 = "5dfa8ade1eb8b22bf92fe6c88658d4a433be80def181b97d73f4f9bd380911b8"
SCHEMA_SHA256 = "3ed2a5a0723f249f8b9188c19d6a86ec96aec4db529055a3af51ff24e9620fec"
HASH_DOMAIN = "v13-original-portfolio-proposal-v1"
MAX_JSON_BYTES = 16 * 1024 * 1024
SHA_PATTERN = re.compile(r"[a-f0-9]{64}")


class Rejected(ValueError):
    """A candidate input cannot be verified; callers must not authorize it."""


def _unique_object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise Rejected("duplicate_key")
        result[key] = value
    return result


def _nonfinite(_value):
    raise Rejected("nonfinite_json")


def _finite_float(value):
    number = float(value)
    if not math.isfinite(number):
        raise Rejected("nonfinite_json")
    return number


def read_json(payload):
    if not isinstance(payload, (bytes, str)) or len(payload) > MAX_JSON_BYTES:
        raise Rejected("invalid_json_size")
    try:
        return json.loads(payload, object_pairs_hook=_unique_object,
                          parse_constant=_nonfinite, parse_float=_finite_float)
    except (ValueError, UnicodeError, RecursionError) as error:
        raise Rejected("invalid_json: " + str(error)) from error


def canonical_bytes(value):
    try:
        return json.dumps(value, sort_keys=True, separators=(",", ":"),
                          ensure_ascii=False, allow_nan=False).encode("utf-8")
    except (ValueError, TypeError, OverflowError) as error:
        raise Rejected("noncanonical_json") from error


def digest(value):
    return hashlib.sha256(canonical_bytes(value)).hexdigest()


def require_hash(value):
    if not isinstance(value, str) or not SHA_PATTERN.fullmatch(value):
        raise Rejected("invalid_hash")
    return value


def timestamp(value):
    if not isinstance(value, str) or not re.fullmatch(
            r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d+)?(?:Z|[+-](?:[01]\d|2[0-3]):[0-5]\d)", value):
        raise Rejected("invalid_timestamp")
    try:
        result = dt.datetime.fromisoformat(value.replace("Z", "+00:00"))
        if result.tzinfo is None:
            raise ValueError("timezone missing")
        return result.astimezone(UTC)
    except ValueError as error:
        raise Rejected("invalid_timestamp") from error


def bar_date(value):
    try:
        if not isinstance(value, str):
            raise ValueError("date type")
        result = dt.date.fromisoformat(value)
        if result.isoformat() != value:
            raise ValueError("date encoding")
        return result
    except ValueError as error:
        raise Rejected("invalid_bar_date") from error


def encode_weight(value):
    if type(value) not in (int, float):
        raise Rejected("invalid_weight")
    try:
        number = float(value)
    except (ValueError, OverflowError) as error:
        raise Rejected("invalid_weight") from error
    if not math.isfinite(number):
        raise Rejected("invalid_weight")
    return "0" if number == 0 else repr(number)


def decode_weight(value):
    if not isinstance(value, str):
        raise Rejected("noncanonical_weight")
    try:
        number = float(value)
    except (ValueError, OverflowError) as error:
        raise Rejected("noncanonical_weight") from error
    if encode_weight(number) != value:
        raise Rejected("noncanonical_weight")
    return number


def load_contract(repo_root):
    root = pathlib.Path(repo_root)
    directory = root / "docs/contracts"
    paths = [(directory / "v13-original-portfolio-adapter-candidate-v1.json", CONTRACT_SHA256),
             (directory / "v13-original-portfolio-proposal.schema.json", SCHEMA_SHA256)]
    values = []
    for path, expected in paths:
        payload = path.read_bytes()
        if hashlib.sha256(payload).hexdigest() != expected:
            raise Rejected("candidate_contract_changed")
        values.append(read_json(payload))
    contract, schema = values
    if (contract["active"] is not False or contract["status"] != "DRAFT"
            or digest(contract["source_identity"]) != contract["scientific_lineage_ref"]
            or digest(contract["universe"]) != contract["universe_hash"]
            or set(schema["properties"]["targets"]["required"]) != set(contract["universe"])):
        raise Rejected("candidate_contract_mismatch")
    return contract, schema


def complete_targets(sparse, contract):
    """Expand only the frozen research universe; never normalize arbitrary aliases."""
    if not isinstance(sparse, dict):
        raise Rejected("invalid_targets")
    aliases = {m["research_symbol"]: m["symbol"]
               for m in contract["symbol_mapping_candidates"]}
    if not set(sparse) <= aliases.keys():
        raise Rejected("unexpected_research_symbol")
    result = {s: "0" for s in contract["universe"]}
    for alias, value in sparse.items():
        result[aliases[alias]] = encode_weight(value)
    return result


def proposal_id(payload):
    return digest({"domain": HASH_DOMAIN,
                   "proposal": {k: v for k, v in payload.items() if k != "proposal_id"}})


def validate_proposal(payload, contract, schema, *, checked_at):
    """Strict candidate shape, identity, hash, target and causal-clock checks.

    This is NOT an issuance check. A correctly formed fixture may pass while
    its binding is unapproved and its derivation/custody is entirely absent.
    """
    if not isinstance(payload, dict) or set(payload) != set(schema["required"]):
        raise Rejected("proposal_fields")
    for key, shape in schema["properties"].items():
        value = payload[key]
        if "const" in shape and (type(value) is not type(shape["const"])
                                 or value != shape["const"]):
            raise Rejected("proposal_identity: " + key)
        if shape.get("pattern") == "^[a-f0-9]{64}$":
            require_hash(value)
    if not isinstance(payload["targets"], dict) or set(payload["targets"]) != set(contract["universe"]):
        raise Rejected("portfolio_incomplete")
    weights = {s: decode_weight(v) for s, v in payload["targets"].items()}
    # Same ULP tolerance as P0-02; this precheck does not replace its fill checks.
    max_asset = contract["operational_risk_policy"]["per_asset_exposure"]
    max_gross = contract["operational_risk_policy"]["gross_exposure"]
    if (any(abs(v) > max_asset + 8 * math.ulp(max_asset) for v in weights.values())
            or math.fsum(abs(v) for v in weights.values()) > max_gross + 8 * math.ulp(max_gross)):
        raise Rejected("target_exposure")
    day = bar_date(payload["source_bar_date"])
    mature = dt.datetime.combine(day + dt.timedelta(days=1), dt.time(), UTC) + dt.timedelta(minutes=10)
    available = timestamp(payload["source_available_at"])
    decided = timestamp(payload["decision_timestamp"])
    proposed = timestamp(payload["proposal_timestamp"])
    checked = timestamp(checked_at)
    if not mature <= available <= decided <= proposed <= checked:
        raise Rejected("source_not_available")
    if proposal_id(payload) != payload["proposal_id"]:
        raise Rejected("proposal_hash_mismatch")
    return weights


def seal_receipt(payload):
    if "receipt_hash" in payload:
        raise Rejected("receipt_already_sealed")
    return {**payload, "receipt_hash": digest(payload)}


def check_receipt(receipt, expected_hash):
    """An expected digest must come from the verifier's custodian, never the model."""
    require_hash(expected_hash)
    if not isinstance(receipt, dict):
        raise Rejected("receipt_missing")
    unsigned = {k: v for k, v in receipt.items() if k != "receipt_hash"}
    if receipt.get("receipt_hash") != expected_hash or digest(unsigned) != expected_hash:
        raise Rejected("receipt_hash_mismatch")


def verify_candidate_proposal(payload, contract, schema, *, derivation_receipt,
                              publication_receipt, expected_derivation_hash,
                              expected_publication_hash, checked_at):
    """Validate candidate against separately supplied, pinned verifier evidence.

    Future issuer must additionally authenticate custody, future boundary,
    epoch, slot uniqueness, freshness, policy and admissibility. No APPROVE
    is returned here; current real diagnostic receipts deliberately fail.
    """
    validate_proposal(payload, contract, schema, checked_at=checked_at)
    check_receipt(derivation_receipt, expected_derivation_hash)
    check_receipt(publication_receipt, expected_publication_hash)
    if (payload["derivation_receipt_hash"] != expected_derivation_hash
            or payload["source_publication_receipt_hash"] != expected_publication_hash):
        raise Rejected("proposal_receipt_mismatch")
    for receipt in (derivation_receipt, publication_receipt):
        for key in ("source_record_hash", "source_bar_date", "scientific_lineage_ref", "universe_hash"):
            if receipt.get(key) != payload[key]:
                raise Rejected("receipt_identity_mismatch")
    if (derivation_receipt.get("kind") != "v13-original-derivation-v1"
            or derivation_receipt.get("derivation_status") != "VERIFIED"
            or derivation_receipt.get("research_only") is not True
            or derivation_receipt.get("execution_approved") is not False
            or derivation_receipt.get("targets") != payload["targets"]
            or derivation_receipt.get("availability_status") != "VERIFIED"
            or publication_receipt.get("kind") != "v13-original-publication-v1"
            or publication_receipt.get("causal_input_hash") != derivation_receipt.get("causal_input_hash")):
        raise Rejected("derivation_or_availability_unverified")
    dependencies = publication_receipt.get("dependency_receipts")
    expected = derivation_receipt.get("raw_response_hashes")
    if (not isinstance(dependencies, dict) or not dependencies or not isinstance(expected, list)
            or set(dependencies) != set(expected)):
        raise Rejected("dependency_receipts_missing")
    require_hash(derivation_receipt.get("causal_input_hash"))
    if len(set(expected)) != len(expected):
        raise Rejected("dependency_receipts_conflict")
    for response_hash in expected:
        require_hash(response_hash)
    received = [timestamp(v) for v in dependencies.values()]
    published = timestamp(publication_receipt.get("completed_at"))
    verified = timestamp(derivation_receipt.get("verified_at"))
    available = timestamp(payload["source_available_at"])
    if max(received) > published or published > verified or available != max([published, verified, *received]):
        raise Rejected("source_not_available")
    return {"status": "CANDIDATE_VERIFIED", "research_only": True,
            "execution_approved": False, "issuable": False,
            "issuance_denial": "binding_unapproved", "proposal_id": payload["proposal_id"]}


def issuance_status(repo_root):
    """Current pinned DRAFT can never authorize a proposal, even after validation."""
    load_contract(repo_root)
    return {"status": "DENY", "reason": "binding_unapproved", "issuable": False}
