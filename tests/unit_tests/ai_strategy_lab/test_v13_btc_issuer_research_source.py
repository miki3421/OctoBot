"""Actual public BTC source through the v2 issuer, still denied as research-only."""
import datetime as dt
import hashlib
import json
import os
from pathlib import Path
import shutil
import sqlite3
import tempfile
import unittest

from octobot.ai_strategy_lab import paper_authorization as auth
from octobot.ai_strategy_lab import v13_btc_issuer as issuer
from octobot.ai_strategy_lab import v13_btc_research_producer as producer

ROOT = Path(__file__).resolve().parents[3]
EVIDENCE = Path(os.environ.get("V13_C_EVIDENCE", "/no-v13-c-evidence"))


class ResearchSourceIssuerTest(unittest.TestCase):
    def setUp(self):
        if os.geteuid() != 0 or not (EVIDENCE/"decision-result.json").is_file():
            self.skipTest("root and mounted Checkpoint C public evidence required")
        self.root = Path(tempfile.mkdtemp(prefix="v13-real-source-issuer-"))
        self.root.chmod(0o755)
        self.addCleanup(lambda: shutil.rmtree(self.root))
        self.result = json.loads((EVIDENCE/"decision-result.json").read_text())
        self.now = dt.datetime.fromisoformat(self.result["payload"]["decision_timestamp"])+dt.timedelta(minutes=1)
        archive = self.root/"archive"
        shutil.copytree(EVIDENCE/"raw",archive/"raw")
        shutil.copytree(EVIDENCE/"snapshots",archive/"snapshots")
        for folder in (archive,archive/"raw",archive/"snapshots"):
            folder.chmod(0o755)
        for folder in (archive/"raw",archive/"snapshots"):
            for file in folder.iterdir():
                file.chmod(0o644)
        proposal_dir = self.root/"producer"
        proposal_dir.mkdir()
        os.chown(proposal_dir,30010,30020)
        proposal_dir.chmod(0o750)
        journal = proposal_dir/"research.jsonl"
        producer.append_research_journal(journal,self.result)
        os.chown(journal,30010,30020)
        journal.chmod(0o640)
        protocol = json.loads((ROOT/"octobot/ai_strategy_lab/v13_btc_experiment_protocol_v1.json").read_text())
        source_code = ROOT/"octobot/ai_strategy_lab/v13_btc_research_producer.py"
        source_sha = hashlib.sha256(source_code.read_bytes()).hexdigest()
        protocol["producer_status"] = "VALIDATED"
        protocol["producer_implementation"] = {"path":str(source_code),"sha256":source_sha}
        protocol_path = self.root/"isolated-protocol.json"
        protocol_path.write_text(json.dumps(protocol))
        protocol_path.chmod(0o644)
        approvals = self.root/"approvals"
        approvals.mkdir()
        os.chown(approvals,30020,30000)
        approvals.chmod(0o750)
        db = approvals/"approvals.sqlite"
        db.touch()
        os.chown(db,30020,30000)
        db.chmod(0o640)
        contract = self.root/"research-contract.json"
        shutil.copyfile(ROOT/"octobot/ai_strategy_lab/v13_btc_research_contract_v1.json",contract)
        contract.chmod(0o644)
        verifier = ROOT/"octobot/ai_strategy_lab/v13_btc_research_verify.py"
        config = {"schema_version":2,"protocol_path":str(protocol_path),
            "protocol_sha256":auth.digest(protocol),"journal_path":str(journal),
            "producer_uid":30010,"issuer_uid":30020,"executor_gid":30000,
            "approval_db":str(db),"archive_path":str(archive),"archive_uid":0,
            "research_contract_path":str(contract),
            "research_contract_sha256":hashlib.sha256(contract.read_bytes()).hexdigest(),
            "producer_code_sha256":source_sha,
            "verifier_code_sha256":hashlib.sha256(verifier.read_bytes()).hexdigest()}
        self.config_path = self.root/"issuer.json"
        self.config_path.write_text(json.dumps(config))
        self.config_path.chmod(0o644)
        self.db = db
        self.journal = journal
        self.archive = archive

    def run_issuer(self):
        reader,writer = os.pipe()
        pid = os.fork()
        if pid == 0:
            os.close(reader)
            try:
                os.setgroups([])
                os.setgid(30020)
                os.setuid(30020)
                value = {"ok":True,"result":issuer.issue(self.config_path,now=self.now)}
            except BaseException as exc:
                value = {"ok":False,"error":type(exc).__name__+":"+str(exc)}
            os.write(writer,json.dumps(value).encode())
            os._exit(0)
        os.close(writer)
        data = json.loads(os.read(reader,16384))
        os.close(reader)
        os.waitpid(pid,0)
        return data

    def event_reason(self):
        with sqlite3.connect(f"file:{self.db}?mode=ro",uri=True) as db:
            return db.execute("SELECT reason_code FROM issuer_events ORDER BY id DESC LIMIT 1").fetchone()[0]

    def test_real_source_verified_then_research_contract_denied(self):
        outcome = self.run_issuer()
        self.assertTrue(outcome["ok"],outcome)
        self.assertEqual(outcome["result"][0][1:], ["DENY","research_only_not_issuable"])
        self.assertEqual(self.event_reason(),"research_only_not_issuable")
        with sqlite3.connect(f"file:{self.db}?mode=ro",uri=True) as db:
            self.assertEqual(db.execute("SELECT COUNT(*) FROM approvals").fetchone()[0],0)
            self.assertEqual(db.execute("PRAGMA integrity_check").fetchone()[0],"ok")

    def test_source_tamper_and_missing_archive_denied(self):
        file = next((self.archive/"raw").iterdir())
        file.write_bytes(file.read_bytes()+b" ")
        outcome = self.run_issuer()
        self.assertTrue(outcome["ok"],outcome)
        self.assertIn("raw_content_changed",self.event_reason())
        file.unlink()
        outcome = self.run_issuer()
        self.assertTrue(outcome["ok"],outcome)
        self.assertIn("No such file or directory",self.event_reason())

    def test_recomputed_target_and_chain_tamper_denied(self):
        changed = json.loads(json.dumps(self.result))
        changed["payload"]["target_weight"] = "0.11"
        changed["decision_id"] = producer.digest(changed["payload"])
        record = {"result":changed,"previous_record_hash":None}
        record["record_hash"] = producer.digest(record)
        self.journal.write_text(json.dumps(record)+"\n")
        outcome = self.run_issuer()
        self.assertTrue(outcome["ok"],outcome)
        self.assertIn("derivation_mismatch",self.event_reason())
        record["record_hash"] = "0"*64
        self.journal.write_text(json.dumps(record)+"\n")
        outcome = self.run_issuer()
        self.assertFalse(outcome["ok"])
        self.assertIn("producer_chain_invalid",self.event_reason())

    def test_restart_and_storage_failure_remain_closed(self):
        for _ in range(2):
            outcome = self.run_issuer()
            self.assertTrue(outcome["ok"],outcome)
            self.assertEqual(outcome["result"][0][1],"DENY")
        with sqlite3.connect(f"file:{self.db}?mode=ro",uri=True) as db:
            self.assertEqual(db.execute("SELECT COUNT(*) FROM approvals").fetchone()[0],0)
            self.assertEqual(db.execute("SELECT COUNT(*) FROM issuer_events").fetchone()[0],2)
        self.db.unlink()
        outcome = self.run_issuer()
        self.assertFalse(outcome["ok"])
        self.assertIn("FileNotFoundError",outcome["error"])
        self.assertFalse(self.db.exists())


if __name__ == "__main__":
    unittest.main()
