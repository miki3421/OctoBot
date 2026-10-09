"""Research producer tests use synthetic candles and isolated storage only."""
import copy
import datetime as dt
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[3]
MODULE = ROOT / "octobot/ai_strategy_lab/v13_btc_research_producer.py"
VERIFY = ROOT / "octobot/ai_strategy_lab/v13_btc_research_verify.py"
CONTRACT = ROOT / "octobot/ai_strategy_lab/v13_btc_research_contract_v1.json"


def load(path, name):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


p = load(MODULE, "research_producer")
v = load(VERIFY, "research_verifier")
UTC = dt.timezone.utc


class ResearchProducerTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.archive = self.root / "archive"
        self.acquired = dt.datetime(2026, 9, 25, 11, tzinfo=UTC)
        self.decision_at = dt.datetime(2026, 9, 25, 12, tzinfo=UTC).isoformat()
        self.last = dt.datetime(2026, 9, 24, tzinfo=UTC)
        self.rows = self.rows_for_days(121)
        self.capture()

    def rows_for_days(self, count):
        return [[int((self.last - dt.timedelta(days=count-1-i)).timestamp()*1000),
                 100+i, 101+i, 99+i, 100+i, 10, 1000]
                for i in range(count)]

    def capture(self):
        payload = json.dumps({"code": "200000", "data": self.rows}).encode()
        calls = iter((self.acquired, self.acquired + dt.timedelta(seconds=1)))
        self.snapshot_hash = p.collect(self.archive, CONTRACT, now=lambda: next(calls),
                                       fetch=lambda url: payload)
        self.result = p.decision(self.archive, self.snapshot_hash, CONTRACT, self.decision_at)
        self.manifest_hash = p.digest(p.manifest(CONTRACT))
        self.code_hash = hashlib.sha256(MODULE.read_bytes()).hexdigest()

    def verify(self, result=None):
        return v.verify(self.archive, CONTRACT, self.manifest_hash,
                        self.code_hash, result or self.result)

    def test_deterministic_and_verified(self):
        self.assertEqual(self.result["status"], "PROPOSAL")
        self.assertEqual(self.result, p.decision(self.archive, self.snapshot_hash,
                                                CONTRACT, self.decision_at))
        self.assertTrue(self.verify()["verified"])

    def test_insufficient_gap_and_incomplete(self):
        self.rows = self.rows_for_days(100)
        self.capture()
        self.assertEqual(self.result["payload"]["reason"], "warmup_incomplete")
        self.assertTrue(self.verify()["verified"])
        self.rows = self.rows_for_days(122)
        del self.rows[20]
        self.capture()
        self.assertEqual(self.result["payload"]["reason"], "daily_gap")
        self.rows = self.rows_for_days(121)
        self.rows[-1][0] += 86400000
        self.capture()
        self.assertEqual(self.result["payload"]["reason"], "latest_bar_missing_or_stale")

    def test_late_data_no_proposal_and_duplicate_rejected(self):
        old_t = (self.acquired - dt.timedelta(seconds=1)).isoformat()
        late = p.decision(self.archive, self.snapshot_hash, CONTRACT, old_t)
        self.assertEqual(late["payload"]["reason"], "source_available_after_decision")
        self.assertTrue(self.verify(late)["verified"])
        self.rows.append(self.rows[-1])
        with self.assertRaisesRegex(ValueError, "duplicate"):
            self.capture()

    def test_tamper_hash_and_derivation(self):
        raw = next((self.archive / "raw").iterdir())
        raw.chmod(0o600)
        raw.write_bytes(raw.read_bytes() + b" ")
        with self.assertRaisesRegex(ValueError, "raw_content_changed"):
            self.verify()
        raw.write_bytes(raw.read_bytes()[:-1])
        snapshot = next((self.archive / "snapshots").iterdir())
        original = snapshot.read_bytes()
        snapshot.chmod(0o600)
        changed = json.loads(original)
        changed["symbol"] = "ETH/USDT:USDT"
        snapshot.write_text(json.dumps(changed))
        with self.assertRaisesRegex(ValueError, "snapshot_content_invalid"):
            self.verify()
        snapshot.write_bytes(original)
        altered = copy.deepcopy(self.result)
        altered["payload"]["target_weight"] = "0.11"
        altered["decision_id"] = p.digest(altered["payload"])
        with self.assertRaisesRegex(ValueError, "derivation_mismatch"):
            self.verify(altered)
        altered = copy.deepcopy(self.result)
        altered["payload"]["source_record_hash"] = "0"*64
        altered["decision_id"] = p.digest(altered["payload"])
        with self.assertRaises(FileNotFoundError):
            self.verify(altered)

    def test_identity_and_version_binding(self):
        for field, value in (("symbol", "ETH/USDT:USDT"),
                             ("experiment_id", "other"), ("producer_version", "v2")):
            altered = copy.deepcopy(self.result)
            altered["payload"][field] = value
            altered["decision_id"] = p.digest(altered["payload"])
            with self.assertRaisesRegex(ValueError, "derivation_mismatch"):
                self.verify(altered)
        with self.assertRaisesRegex(ValueError, "manifest_binding_failed"):
            v.verify(self.archive, CONTRACT, "0"*64, self.code_hash, self.result)
        with self.assertRaisesRegex(ValueError, "producer_code_binding_failed"):
            v.verify(self.archive, CONTRACT, self.manifest_hash, "0"*64, self.result)

    def test_journal_idempotent(self):
        journal = self.root / "research.jsonl"
        self.assertTrue(p.append_research_journal(journal, self.result))
        initial = journal.read_bytes()
        self.assertFalse(p.append_research_journal(journal, self.result))
        self.assertEqual(journal.read_bytes(), initial)
        later = p.decision(self.archive, self.snapshot_hash, CONTRACT,
                           dt.datetime(2026, 9, 25, 13, tzinfo=UTC).isoformat())
        with self.assertRaisesRegex(ValueError, "decision_slot_already_recorded"):
            p.append_research_journal(journal, later)

    def test_role_cannot_write_trusted_archive(self):
        if os.geteuid() != 0:
            self.skipTest("requires separate UID")
        # A real unprivileged UID can traverse and read, but cannot write the
        # root-owned snapshot or unrelated trusted state.
        self.root.chmod(0o755)
        for folder in (self.archive, self.archive / "raw", self.archive / "snapshots"):
            folder.chmod(0o555)
        for path in (self.archive / "raw").iterdir():
            path.chmod(0o444)
        for path in (self.archive / "snapshots").iterdir():
            path.chmod(0o444)
        trusted = self.root / "approvals.sqlite"
        trusted.write_bytes(b"trusted")
        trusted.chmod(0o400)
        script = "import pathlib,sys; p=pathlib.Path(sys.argv[1]); q=pathlib.Path(sys.argv[2]); p.read_bytes();\nfor x in (p,q):\n try: x.write_bytes(b'bad')\n except PermissionError: pass\n else: raise SystemExit(2)"
        target = next((self.archive / "snapshots").iterdir())
        completed = subprocess.run([sys.executable, "-c", script, str(target), str(trusted)],
                                   preexec_fn=lambda: os.setuid(65534), capture_output=True)
        self.assertEqual(completed.returncode, 0, completed.stderr)
        self.assertEqual(trusted.read_bytes(), b"trusted")


if __name__ == "__main__":
    unittest.main()
