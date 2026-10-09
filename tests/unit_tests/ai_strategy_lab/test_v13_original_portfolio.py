"""Candidate-only adversarial checks; synthetic receipts are NOT authority.

Work card: work-card-b98fb679-5014-4b81-99fd-e5e5c09f7993.
"""
import json
from pathlib import Path

import pytest

from octobot.ai_strategy_lab import v13_original_portfolio as p
from octobot.ai_strategy_lab import v13_original_verify as v

ROOT = Path(__file__).resolve().parents[3]


@pytest.fixture
def context():
    return p.load_contract(ROOT)


def fixture_proposal(contract):
    # Every receipt, epoch and binding below is synthetic, test-only.
    result = {"schema_version": 1, "portfolio_id": contract["portfolio_id"],
              "account": contract["account"], "environment": "paper",
              "scientific_lineage_ref": contract["scientific_lineage_ref"],
              "execution_binding_ref": "b" * 64, "account_epoch": "c" * 64,
              "source_record_hash": "d" * 64, "source_bar_date": "2026-09-27",
              "source_publication_receipt_hash": "e" * 64, "derivation_receipt_hash": "f" * 64,
              "source_available_at": "2026-09-28T00:12:00Z",
              "decision_timestamp": "2026-09-28T00:13:00Z", "proposal_timestamp": "2026-09-28T00:14:00Z",
              "universe_hash": contract["universe_hash"], "complete_portfolio": True,
              "targets": {s: "0" for s in contract["universe"]}}
    result["targets"]["BTCUSDT"] = "0.1"
    result["proposal_id"] = p.proposal_id(result)
    return result


def synthetic_receipts(proposal):
    identity = {k: proposal[k] for k in ["source_record_hash", "source_bar_date", "scientific_lineage_ref", "universe_hash"]}
    raw_hash = "a" * 64
    causal_hash = "1" * 64
    publication = p.seal_receipt({**identity, "kind": "v13-original-publication-v1", "causal_input_hash": causal_hash,
                                  "dependency_receipts": {raw_hash: "2026-09-28T00:10:01Z"},
                                  "completed_at": "2026-09-28T00:11:00Z"})
    derivation = p.seal_receipt({**identity, "kind": "v13-original-derivation-v1", "causal_input_hash": causal_hash,
                                 "raw_response_hashes": [raw_hash], "targets": proposal["targets"],
                                 "derivation_status": "VERIFIED", "research_only": True, "execution_approved": False,
                                 "availability_status": "VERIFIED", "verified_at": "2026-09-28T00:12:00Z"})
    proposal["source_publication_receipt_hash"] = publication["receipt_hash"]
    proposal["derivation_receipt_hash"] = derivation["receipt_hash"]
    proposal["proposal_id"] = p.proposal_id(proposal)
    return derivation, publication


def verify(proposal, context, derivation, publication, **kwargs):
    contract, schema = context
    return p.verify_candidate_proposal(
        proposal, contract, schema, derivation_receipt=derivation, publication_receipt=publication,
        expected_derivation_hash=kwargs.get("derivation_hash", derivation["receipt_hash"]),
        expected_publication_hash=publication["receipt_hash"], checked_at="2026-09-28T00:15:00Z")


def test_positive_candidate_never_approves(context):
    proposal = fixture_proposal(context[0]);derivation, publication = synthetic_receipts(proposal)
    result = verify(proposal, context, derivation, publication)
    assert result["status"] == "CANDIDATE_VERIFIED"
    assert result["execution_approved"] is False and result["issuable"] is False
    assert p.issuance_status(ROOT) == {"status": "DENY", "reason": "binding_unapproved", "issuable": False}


@pytest.mark.parametrize("mutation", [
    lambda x: x["targets"].pop("ETHUSDT"),
    lambda x: x.update(targets={"BTCUSDT": "0.1"}),
    lambda x: x["targets"].update(UNKNOWNUSDT="0"),
    lambda x: x.update(approved=True),
    lambda x: x.update(approval_token="test"),
    lambda x: x.update(account="another-account"),
    lambda x: x.update(portfolio_id="v13-btc-paper-new-v1"),
    lambda x: x.update(environment="live"),
    lambda x: x.update(schema_version=True),
    lambda x: x.update(schema_version=1.0),
    lambda x: x.update(complete_portfolio=1),
    lambda x: x.update(universe_hash="0" * 64),
    lambda x: x.update(source_bar_date="2026-02-30"),
    lambda x: x.update(decision_timestamp="2026-09-28T00:13:00"),
    lambda x: x.update(decision_timestamp="2026-09-28 00:13:00Z"),
    lambda x: x.update(decision_timestamp="2026-09-28T00:13:00+00:99"),
    lambda x: x.update(source_available_at="2026-09-28T00:14:01Z"),
    lambda x: x.update(source_available_at="2026-09-28T00:09:59Z"),
    lambda x: x.update(proposal_timestamp="2026-09-28T00:16:00Z"),
    lambda x: x["targets"].update(BTCUSDT="0.316"),
    lambda x: x["targets"].update(BTCUSDT="0.3", ETHUSDT="0.3", SOLUSDT="0.3", XLMUSDT="0.1"),
])
def test_semantic_rejection_even_after_rehash(context, mutation):
    proposal = fixture_proposal(context[0]);mutation(proposal);proposal["proposal_id"] = p.proposal_id(proposal)
    with pytest.raises(p.Rejected):
        p.validate_proposal(proposal, *context, checked_at="2026-09-28T00:15:00Z")


def test_target_tamper_without_rehash(context):
    proposal = fixture_proposal(context[0]);proposal["targets"]["BTCUSDT"] = "0.2"
    with pytest.raises(p.Rejected, match="proposal_hash_mismatch"):
        p.validate_proposal(proposal, *context, checked_at="2026-09-28T00:15:00Z")


@pytest.mark.parametrize("value", ["-0", "0.0", "0.10", "1e309", "NaN", "Infinity", "+0.1", " 0.1", True, 0.1])
def test_noncanonical_weight(value):
    with pytest.raises(p.Rejected):p.decode_weight(value)


@pytest.mark.parametrize("value", [0.0, -0.0, 0.1, -0.1, 1e-7, 1e-200])
def test_no_rounding(value):
    assert p.decode_weight(p.encode_weight(value)) == value


@pytest.mark.parametrize("text", ['{"targets":{"BTCUSDT":"0.1","BTCUSDT":"0.2"}}', '{"x":NaN}', '{"x":Infinity}', '{"x":1e999}'])
def test_reject_duplicate_and_nonfinite_json(text):
    with pytest.raises(p.Rejected):p.read_json(text)


def test_sparse_expansion_only_frozen_aliases(context):
    result = p.complete_targets({"BTC/USDT:USDT": 0.1}, context[0])
    assert len(result) == 18 and result["ETHUSDT"] == "0" and result["BTCUSDT"] == "0.1"
    with pytest.raises(p.Rejected):p.complete_targets({"BTCUSDT": 0.1}, context[0])
    with pytest.raises(p.Rejected):p.complete_targets({"BTC/USDT:USDT": True}, context[0])


def test_receipt_digest_is_externally_pinned(context):
    proposal = fixture_proposal(context[0]);d, publication = synthetic_receipts(proposal)
    with pytest.raises(p.Rejected, match="receipt_hash_mismatch"):
        verify(proposal, context, d, publication, derivation_hash="0" * 64)
    d["targets"] = {**d["targets"], "BTCUSDT": "0.2"}
    with pytest.raises(p.Rejected, match="receipt_hash_mismatch"):
        verify(proposal, context, d, publication)


@pytest.mark.parametrize("mutation", [
    lambda d, pub: d.update(availability_status="UNRESOLVED"),
    lambda d, pub: d.update(source_record_hash="0" * 64),
    lambda d, pub: d.update(targets={**d["targets"], "BTCUSDT": "0.2"}),
    lambda d, pub: pub.update(dependency_receipts={}),
    lambda d, pub: pub.update(completed_at="2026-09-28T00:12:01Z"),
    lambda d, pub: pub.update(dependency_receipts={"a" * 64: "2026-09-28T00:11:01Z"}),
])
def test_sealed_but_inconsistent_receipt_is_denied(context, mutation):
    proposal = fixture_proposal(context[0]);d, pub = synthetic_receipts(proposal)
    d.pop("receipt_hash");pub.pop("receipt_hash");mutation(d, pub)
    d=p.seal_receipt(d);pub=p.seal_receipt(pub)
    proposal.update(derivation_receipt_hash=d["receipt_hash"], source_publication_receipt_hash=pub["receipt_hash"])
    proposal["proposal_id"] = p.proposal_id(proposal)
    with pytest.raises(p.Rejected):verify(proposal, context, d, pub)


def test_draft_contract_cannot_be_replaced(tmp_path):
    contracts = tmp_path / "docs/contracts";contracts.mkdir(parents=True)
    for src in (ROOT / "docs/contracts").glob("v13-original*.json"):
        (contracts/src.name).write_bytes(src.read_bytes())
    path = contracts / "v13-original-portfolio-adapter-candidate-v1.json"
    changed = json.loads(path.read_text());changed["active"] = True;path.write_text(json.dumps(changed))
    with pytest.raises(p.Rejected, match="candidate_contract_changed"):p.load_contract(tmp_path)


def test_archive_escape_and_symlink(tmp_path):
    with pytest.raises(p.Rejected):v._safe(tmp_path, "../escape")
    outside = tmp_path / "file";outside.write_text("payload");(tmp_path / "alias").symlink_to(outside)
    with pytest.raises(p.Rejected):v._safe(tmp_path, "alias")


def test_diagnostic_publication_does_not_overwrite(tmp_path):
    receipt = p.seal_receipt({"kind": "v13-original-derivation-v1", "research_only": True,
                              "execution_approved": False, "issuable": False})
    path = v.publish_diagnostic(tmp_path, receipt)
    assert v.publish_diagnostic(tmp_path, receipt) == path
    path.write_text("incomplete")
    with pytest.raises(p.Rejected, match="output_conflict"):v.publish_diagnostic(tmp_path, receipt)
    with pytest.raises(p.Rejected, match="operational_output"):v.publish_diagnostic(tmp_path / "octobot-local", receipt)


def test_storage_failure_cannot_be_reported_as_published(tmp_path, monkeypatch):
    receipt=p.seal_receipt({"kind": "v13-original-derivation-v1", "research_only": True,
                             "execution_approved": False, "issuable": False})
    def fail(_fd):raise OSError("storage failure")
    monkeypatch.setattr(v.os, "fsync", fail)
    with pytest.raises(OSError):v.publish_diagnostic(tmp_path, receipt)
    # Equal bytes from the first failed attempt do not bypass fsync on retry.
    with pytest.raises(OSError):v.publish_diagnostic(tmp_path, receipt)


def test_future_or_open_slot_is_not_reconstructed(tmp_path):
    inputs=v.Inputs(ROOT, tmp_path, tmp_path, tmp_path / "lock")
    with pytest.raises(p.Rejected, match="source_not_mature"):
        v.reconstruct(inputs, source_bar_date="2026-09-27", verified_at="2026-09-28T00:09:59Z")
