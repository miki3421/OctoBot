"""Isolated original V13 portfolio issuer; real candidate remains DENY.

Work card: work-card-71bc1c35-d049-48d2-825c-de2f5f479a67.
Architecture approvals are explicitly synthetic, with no operational grant.
Only this process writes approvals.sqlite; claims/ledger are not accessible.
"""
from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import os
import pathlib
import sqlite3
import stat
import sys

from octobot.ai_strategy_lab import v13_original_portfolio as p

FIXTURE = "SYNTHETIC_ARCHITECTURE_ONLY"
MARKER = b"v13-original-architecture-test-sandbox-v1\n"
SCHEMA_VERSION = 1
TABLES = {
    "store_metadata": "CREATE TABLE store_metadata (key TEXT PRIMARY KEY, value TEXT NOT NULL)",
    "approvals": """CREATE TABLE approvals (
        approval_id TEXT PRIMARY KEY, proposal_id TEXT NOT NULL UNIQUE,
        account TEXT NOT NULL, account_epoch TEXT NOT NULL, binding_ref TEXT NOT NULL,
        source_record_hash TEXT NOT NULL, source_bar_date TEXT NOT NULL,
        proposal_hash TEXT NOT NULL, body TEXT NOT NULL,
        UNIQUE(account, account_epoch, binding_ref, source_record_hash),
        UNIQUE(account, account_epoch, binding_ref, source_bar_date))""",
    "issuer_events": """CREATE TABLE issuer_events (
        id INTEGER PRIMARY KEY, event_at TEXT NOT NULL, status TEXT NOT NULL,
        reason TEXT NOT NULL, proposal_id TEXT, source_record_hash TEXT,
        approval_id TEXT, config_sha256 TEXT NOT NULL)""",
}


def _inside(path, root):
    path, root = pathlib.Path(path).absolute(), pathlib.Path(root).absolute()
    if not path.is_relative_to(root) or path == root:
        raise p.Rejected("path_outside_sandbox")
    return path


def _directory(path, *, owner, group=None):
    info = pathlib.Path(path).lstat()
    if (not stat.S_ISDIR(info.st_mode) or info.st_uid != owner or info.st_mode & 0o022
            or (group is not None and info.st_gid != group)):
        raise p.Rejected("unsafe_directory")


def _trusted_bytes(path, *, owner, root, expected_hash=None):
    path = _inside(path, root)
    _directory(root, owner=0)
    for ancestor in path.parents:
        if ancestor == pathlib.Path(root):
            break
        info = ancestor.lstat()
        if not stat.S_ISDIR(info.st_mode) or info.st_uid not in (0, owner) or info.st_mode & 0o022:
            raise p.Rejected("unsafe_input_parent")
    descriptor = os.open(path, os.O_RDONLY | os.O_NOFOLLOW)
    try:
        before = os.fstat(descriptor)
        if (not stat.S_ISREG(before.st_mode) or before.st_uid != owner
                or before.st_mode & 0o022 or before.st_nlink != 1):
            raise p.Rejected("unsafe_input_owner_or_mode")
        with os.fdopen(descriptor, "rb", closefd=False) as stream:
            payload = stream.read(p.MAX_JSON_BYTES + 1)
        after = os.fstat(descriptor)
        if (len(payload) > p.MAX_JSON_BYTES or (before.st_size, before.st_mtime_ns, before.st_ctime_ns)
                != (after.st_size, after.st_mtime_ns, after.st_ctime_ns)):
            raise p.Rejected("input_changed_during_read")
    finally:
        os.close(descriptor)
    if expected_hash is not None and hashlib.sha256(payload).hexdigest() != p.require_hash(expected_hash):
        raise p.Rejected("input_pin_mismatch")
    return payload


class ApprovalStore:
    """Issuer-only writer. No claim, consume, update or ledger API."""

    def __init__(self, config):
        self.config = config
        self.path = _inside(config["approval_db"], config["sandbox_root"])
        if self.path.name != "approvals.sqlite" or "octobot-local" in self.path.resolve().parts:
            raise p.Rejected("operational_store_forbidden")

    def _check_file(self):
        _directory(self.config["sandbox_root"], owner=0)
        for ancestor in self.path.parents:
            if ancestor == pathlib.Path(self.config["sandbox_root"]):
                break
            info = ancestor.lstat()
            if not stat.S_ISDIR(info.st_mode) or info.st_uid not in (0, self.config["issuer_uid"]) or info.st_mode & 0o022:
                raise p.Rejected("unsafe_store_parent")
        _directory(self.path.parent, owner=self.config["issuer_uid"], group=self.config["executor_gid"])
        info = self.path.lstat()
        if (not stat.S_ISREG(info.st_mode) or info.st_uid != self.config["issuer_uid"]
                or info.st_gid != self.config["executor_gid"] or info.st_mode & 0o027
                or info.st_nlink != 1):
            raise p.Rejected("unsafe_approval_store")

    def initialize(self):
        _directory(self.path.parent, owner=self.config["issuer_uid"], group=self.config["executor_gid"])
        fd = os.open(self.path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o640)
        os.close(fd)
        self._check_file()
        connection = sqlite3.connect(self.path.as_uri() + "?mode=rw", uri=True, timeout=0)
        try:
            connection.execute("PRAGMA journal_mode=DELETE")
            connection.execute("PRAGMA synchronous=FULL")
            connection.execute("BEGIN IMMEDIATE")
            for ddl in TABLES.values():
                connection.execute(ddl)
            metadata = {"schema_version": str(SCHEMA_VERSION), "store_id": self.config["store_id"],
                        "mode": self.config["mode"], "fixture_label": self.config["fixture_label"] or "NONE"}
            connection.executemany("INSERT INTO store_metadata VALUES (?,?)", metadata.items())
            connection.execute("PRAGMA user_version=1")
            connection.commit()
            descriptor = os.open(self.path.parent, os.O_RDONLY | os.O_DIRECTORY)
            try:
                os.fsync(descriptor)
            finally:
                os.close(descriptor)
        finally:
            connection.close()

    def open(self):
        self._check_file()
        connection = sqlite3.connect(self.path.as_uri() + "?mode=rw", uri=True, timeout=1)
        try:
            connection.execute("PRAGMA trusted_schema=OFF")
            if connection.execute("PRAGMA journal_mode").fetchone()[0] != "delete":
                raise p.Rejected("approval_journal_mode")
            connection.execute("PRAGMA synchronous=FULL")
            if connection.execute("PRAGMA integrity_check").fetchall() != [("ok",)]:
                raise p.Rejected("approval_integrity_failure")
            schema = dict(connection.execute("SELECT name,sql FROM sqlite_master WHERE type='table'"))
            normalize = lambda value: " ".join(value.split())
            if (set(schema) != set(TABLES) or any(normalize(schema[k]) != normalize(TABLES[k]) for k in TABLES)
                    or connection.execute("SELECT count(*) FROM sqlite_master WHERE type IN ('view','trigger')").fetchone()[0]
                    or connection.execute("PRAGMA user_version").fetchone()[0] != SCHEMA_VERSION):
                raise p.Rejected("approval_schema_mismatch")
            expected = {"schema_version": str(SCHEMA_VERSION), "store_id": self.config["store_id"],
                        "mode": self.config["mode"], "fixture_label": self.config["fixture_label"] or "NONE"}
            if dict(connection.execute("SELECT key,value FROM store_metadata")) != expected:
                raise p.Rejected("approval_store_identity")
            return connection
        except BaseException:
            connection.close()
            raise


class Issuer:
    def __init__(self, config_path, *, expected_config_sha256):
        self.path = pathlib.Path(config_path).absolute()
        self.expected_hash = p.require_hash(expected_config_sha256)
        # Bootstrap config ownership/hash before accepting its sandbox root.
        info = self.path.lstat()
        if not stat.S_ISREG(info.st_mode) or info.st_uid != 0 or info.st_mode & 0o022 or info.st_nlink != 1:
            raise p.Rejected("config_not_root_pinned")
        payload = self.path.read_bytes()
        if hashlib.sha256(payload).hexdigest() != self.expected_hash:
            raise p.Rejected("config_hash_mismatch")
        self.config = p.read_json(payload)
        self._check_config()
        self.contract, self.schema = p.load_contract(self.config["repo_root"])
        self.store = ApprovalStore(self.config)

    def _check_config(self):
        c = self.config
        if type(c.get("schema_version")) is not int or c["schema_version"] != 1 or c.get("mode") not in ("diagnostic_only", "architecture_fixture"):
            raise p.Rejected("issuer_mode_invalid")
        if c["mode"] == "architecture_fixture" and c.get("fixture_label") != FIXTURE:
            raise p.Rejected("fixture_label_required")
        if c["mode"] == "diagnostic_only" and c.get("fixture_label") is not None:
            raise p.Rejected("diagnostic_mode_invalid")
        roles = [c[k] for k in ["issuer_uid", "strategy_uid", "verifier_uid"]]
        if (any(type(uid) is not int or uid <= 0 for uid in roles) or len(set(roles)) != len(roles)
                or type(c["executor_gid"]) is not int or c["executor_gid"] <= 0
                or os.geteuid() != c["issuer_uid"] or os.getegid() != c["executor_gid"]):
            raise p.Rejected("issuer_identity_invalid")
        _trusted_bytes(self.path, owner=0, root=c["sandbox_root"], expected_hash=self.expected_hash)
        marker = _trusted_bytes(pathlib.Path(c["sandbox_root"]) / "sandbox.marker", owner=0, root=c["sandbox_root"])
        if marker != MARKER or "octobot-local" in pathlib.Path(c["sandbox_root"]).resolve().parts:
            raise p.Rejected("isolated_sandbox_required")
        repo = pathlib.Path(c["repo_root"])
        actual = {"adapter": pathlib.Path(p.__file__), "issuer": pathlib.Path(__file__),
                  "verifier": repo / "octobot/ai_strategy_lab/v13_original_verify.py"}
        for name, path in actual.items():
            if hashlib.sha256(path.read_bytes()).hexdigest() != p.require_hash(c["component_hashes"][name]):
                raise p.Rejected("issuer_component_changed")
        p.require_hash(c["store_id"])

    def _receipt(self, descriptor):
        value = p.read_json(_trusted_bytes(descriptor["path"], owner=descriptor["owner_uid"],
                                         root=self.config["sandbox_root"], expected_hash=descriptor["file_sha256"]))
        p.check_receipt(value, descriptor["receipt_hash"])
        return value

    def _event(self, connection, *, at, status, reason, proposal=None, source_hash=None, approval_id=None):
        safe_hash = lambda value: value if isinstance(value, str) and p.SHA_PATTERN.fullmatch(value) else None
        connection.execute("INSERT INTO issuer_events(event_at,status,reason,proposal_id,source_record_hash,approval_id,config_sha256) VALUES (?,?,?,?,?,?,?)",
                           (at, status, reason, safe_hash((proposal or {}).get("proposal_id")), safe_hash(source_hash), approval_id, self.expected_hash))

    def _deny(self, reason, now, *, proposal=None, source_hash=None, blockers=None):
        connection = self.store.open()
        try:
            connection.execute("BEGIN IMMEDIATE")
            self._event(connection, at=now, status="DENY", reason=reason, proposal=proposal, source_hash=source_hash)
            connection.commit()
        finally:
            connection.close()
        return {"status": "DENY", "reason": reason, "blockers": blockers or [reason],
                "persisted": True, "operational_approval": False}

    def diagnose(self, *, checked_at=None):
        now = p.timestamp(checked_at).isoformat() if checked_at else dt.datetime.now(p.UTC).isoformat()
        try:
            self._check_config()
            desc = self.config["diagnostic_receipt"]
            if desc["owner_uid"] != self.config["verifier_uid"]:
                raise p.Rejected("receipt_custodian_invalid")
            receipt = self._receipt(desc)
            if (receipt.get("scientific_lineage_ref") != self.contract["scientific_lineage_ref"]
                    or receipt.get("kind") != "v13-original-derivation-v1"
                    or receipt.get("code_hashes") != {k: self.config["component_hashes"][k] for k in ("adapter", "verifier")}):
                raise p.Rejected("diagnostic_receipt_identity")
            blockers = ["binding_unapproved"]
            if receipt.get("availability_status") != "VERIFIED":
                blockers.append("source_availability_unresolved")
            if receipt.get("independent_custody_verified") is not True:
                blockers.append("source_custody_unresolved")
            return self._deny("binding_unapproved", now, source_hash=receipt.get("source_record_hash"), blockers=blockers)
        except (p.Rejected, OSError, ValueError, KeyError, TypeError) as error:
            return self._deny(_reason(error), now)

    def _validate_fixture(self, proposal, now):
        c = self.config
        binding = c["fixture_binding"]
        if (binding.get("status") != FIXTURE or binding.get("owner_decision_ref", "").startswith("fixture:") is False
                or p.digest(binding) != proposal["execution_binding_ref"]
                or binding["account_epoch"] != proposal["account_epoch"]
                or binding["account"] != proposal["account"]):
            raise p.Rejected("fixture_binding_mismatch")
        if (p.timestamp(proposal["source_available_at"]) < p.timestamp(binding["effective_not_before"])
                or p.bar_date(proposal["source_bar_date"]) <= p.bar_date(binding["baseline_bar_date"])
                or proposal["source_record_hash"] == binding["baseline_source_record_hash"]):
            raise p.Rejected("historical_research_not_issuable")
        ttl, age = binding["ttl_seconds"], binding["max_proposal_age_seconds"]
        if (type(ttl) is not int or not 0 < ttl <= 1800 or type(age) is not int or age <= 0
                or (p.timestamp(now) - p.timestamp(proposal["proposal_timestamp"])).total_seconds() > age):
            raise p.Rejected("proposal_stale")
        policy = p.read_json(_trusted_bytes(c["fixture_policy"]["path"], owner=0, root=c["sandbox_root"],
                                          expected_hash=c["fixture_policy"]["file_sha256"]))
        if (policy.get("scope") != FIXTURE or policy.get("scientific_certified") is not False
                or not isinstance(policy.get("version"), str)
                or any(type(policy.get(k)) not in (float, int) or not 0 < policy[k] < float("inf")
                       for k in ("daily_loss", "drawdown", "order_frequency", "cooldown"))):
            raise p.Rejected("fixture_policy_incomplete")
        admissibility = p.read_json(_trusted_bytes(c["fixture_admissibility"]["path"], owner=0,
            root=c["sandbox_root"], expected_hash=c["fixture_admissibility"]["file_sha256"]))
        if (admissibility.get("scope") != FIXTURE
                or admissibility.get("mode") != "synthetic_control_pipeline"
                or not isinstance(admissibility.get("version"), str) or not admissibility["version"]
                or admissibility.get("scientific_certified") is not False
                or admissibility.get("kucoin_order_admissibility_proven") is not False):
            raise p.Rejected("fixture_admissibility_invalid")
        proofs = c["fixture_proofs"][proposal["source_record_hash"]]
        if (proofs["derivation"]["owner_uid"] != c["verifier_uid"]
                or proofs["publication"]["owner_uid"] != 0):
            raise p.Rejected("receipt_custodian_invalid")
        derivation, publication = self._receipt(proofs["derivation"]), self._receipt(proofs["publication"])
        if derivation.get("code_hashes") != {k: c["component_hashes"][k] for k in ("adapter", "verifier")}:
            raise p.Rejected("derivation_code_mismatch")
        p.verify_candidate_proposal(proposal, self.contract, self.schema, derivation_receipt=derivation,
                                   publication_receipt=publication, expected_derivation_hash=proofs["derivation"]["receipt_hash"],
                                   expected_publication_hash=proofs["publication"]["receipt_hash"], checked_at=now)
        return binding, policy, admissibility

    def issue(self, proposal_path, *, checked_at=None):
        now = p.timestamp(checked_at).isoformat() if checked_at else dt.datetime.now(p.UTC).isoformat()
        proposal = None
        try:
            self._check_config()
            proposal = p.read_json(_trusted_bytes(proposal_path, owner=self.config["strategy_uid"], root=self.config["sandbox_root"]))
            p.validate_proposal(proposal, self.contract, self.schema, checked_at=now)
            if self.config["mode"] != "architecture_fixture":
                return self._deny("binding_unapproved", now, proposal=proposal, source_hash=proposal["source_record_hash"])
            binding, policy, admissibility = self._validate_fixture(proposal, now)
        except (p.Rejected, OSError, ValueError, KeyError, TypeError) as error:
            return self._deny(_reason(error), now, proposal=proposal if isinstance(proposal, dict) else None)
        connection = self.store.open()
        try:
            connection.execute("BEGIN IMMEDIATE")
            row = connection.execute("SELECT body FROM approvals WHERE proposal_id=? OR (account=? AND account_epoch=? AND binding_ref=? AND (source_record_hash=? OR source_bar_date=?))",
                                     (proposal["proposal_id"], proposal["account"], proposal["account_epoch"], proposal["execution_binding_ref"], proposal["source_record_hash"], proposal["source_bar_date"])).fetchone()
            if row:
                previous = p.read_json(row[0]);p.check_receipt(previous, previous["receipt_hash"])
                if previous["proposal_hash"] != p.digest(proposal) or previous["issuer_config_sha256"] != self.expected_hash:
                    self._event(connection, at=now, status="DENY", reason="source_slot_conflict", proposal=proposal)
                    connection.commit()
                    return {"status": "DENY", "reason": "source_slot_conflict", "persisted": True, "operational_approval": False}
                self._event(connection, at=now, status="DUPLICATE", reason="same_receipt_no_reissue", proposal=proposal, approval_id=previous["approval_id"])
                connection.commit()
                return {"status": "DUPLICATE", "receipt": previous, "persisted": True, "operational_approval": False}
            newest = connection.execute("SELECT MAX(source_bar_date) FROM approvals WHERE account=? AND account_epoch=? AND binding_ref=?",
                                        (proposal["account"], proposal["account_epoch"], proposal["execution_binding_ref"])).fetchone()[0]
            if newest and proposal["source_bar_date"] < newest:
                self._event(connection, at=now, status="DENY", reason="source_slot_superseded", proposal=proposal)
                connection.commit()
                return {"status": "DENY", "reason": "source_slot_superseded", "persisted": True, "operational_approval": False}
            receipt = p.seal_receipt({"schema_version": 1, "domain": "v13-original-portfolio-approval-v1",
                "approval_id": hashlib.sha256(os.urandom(32)).hexdigest(), "proposal_id": proposal["proposal_id"],
                "proposal_hash": p.digest(proposal), "proposal": proposal, "issuer_config_sha256": self.expected_hash,
                "component_hashes": self.config["component_hashes"], "approved_at": now,
                "expires_at": (p.timestamp(now) + dt.timedelta(seconds=binding["ttl_seconds"])).isoformat(),
                "risk_policy_version": policy["version"], "risk_policy_sha256": self.config["fixture_policy"]["file_sha256"],
                "fixture_binding_sha256": p.digest(binding),
                "candidate_contract_version": self.contract["contract_id"], "candidate_contract_sha256": p.CONTRACT_SHA256,
                "proposal_schema_sha256": p.SCHEMA_SHA256,
                "admissibility_contract_version": admissibility["version"],
                "admissibility_contract_sha256": self.config["fixture_admissibility"]["file_sha256"], "result": "APPROVE",
                "scope": FIXTURE, "operational_approval": False, "scientific_certified": False,
                "kucoin_order_admissibility_proven": False})
            connection.execute("INSERT INTO approvals VALUES (?,?,?,?,?,?,?,?,?)",
                               (receipt["approval_id"], proposal["proposal_id"], proposal["account"], proposal["account_epoch"],
                                proposal["execution_binding_ref"], proposal["source_record_hash"], proposal["source_bar_date"],
                                receipt["proposal_hash"], p.canonical_bytes(receipt).decode()))
            self._event(connection, at=now, status="APPROVE", reason=FIXTURE, proposal=proposal,
                        source_hash=proposal["source_record_hash"], approval_id=receipt["approval_id"])
            connection.commit()
            return {"status": "APPROVE", "receipt": receipt, "persisted": True, "operational_approval": False}
        finally:
            if connection.in_transaction:
                connection.rollback()
            connection.close()


def _reason(error):
    return str(error).split(":", 1)[0] if isinstance(error, p.Rejected) else "input_validation_failure"


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=pathlib.Path, required=True)
    parser.add_argument("--config-sha256", required=True)
    action = parser.add_mutually_exclusive_group(required=True)
    action.add_argument("--initialize-store", action="store_true")
    action.add_argument("--diagnose", action="store_true")
    action.add_argument("--proposal", type=pathlib.Path)
    args = parser.parse_args(argv)
    try:
        issuer = Issuer(args.config, expected_config_sha256=args.config_sha256)
        if args.initialize_store:
            issuer.store.initialize()
            result = {"status": "INITIALIZED", "operational_approval": False}
        elif args.diagnose:
            result = issuer.diagnose()
        else:
            result = issuer.issue(args.proposal)
        print(p.canonical_bytes(result).decode())
        return 0
    except (p.Rejected, OSError, sqlite3.Error, ValueError, KeyError, TypeError) as error:
        print(p.canonical_bytes({"status": "DENY", "reason": _reason(error), "persisted": False,
                                "operational_approval": False}).decode())
        return 2


if __name__ == "__main__":
    sys.exit(main())
