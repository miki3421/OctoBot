"""The source is available before a decision derived from it."""
import datetime as dt
import hashlib
import json
import os
from pathlib import Path
import sqlite3
import tempfile
import unittest

from octobot.ai_strategy_lab import paper_authorization as auth
from octobot.ai_strategy_lab import v13_btc_issuer as issuer
from octobot.ai_strategy_lab import v13_btc_approval as approval
from octobot.ai_strategy_lab import v13_trusted_execution as executor
from octobot.ai_strategy_lab import v13_market_sanity as sanity

UTC = dt.timezone.utc
PROTOCOL = json.loads((Path(__file__).resolve().parents[3] /
    "octobot/ai_strategy_lab/v13_btc_experiment_protocol_v1.json").read_text())
NOW = dt.datetime(2026, 9, 25, 12, tzinfo=UTC)


class CausalTimeTest(unittest.TestCase):
    def test_v1_synthetic_issuer_regression(self):
        if os.geteuid() != 0:
            self.skipTest("requires root-owned isolated config")
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            producer = root/"producer"
            producer.mkdir(mode=0o750)
            approvals = root/"approvals"
            approvals.mkdir(mode=0o750)
            db_path = approvals/"approvals.sqlite"
            db_path.touch(mode=0o640)
            source = root/"synthetic_producer.py"
            source.write_text("# synthetic test only\n")
            protocol = dict(PROTOCOL,producer_status="VALIDATED",
                producer_implementation={"path":str(source),
                  "sha256":hashlib.sha256(source.read_bytes()).hexdigest()})
            protocol_path = root/"protocol.json"
            protocol_path.write_text(json.dumps(protocol))
            proposal = self.proposal(NOW-dt.timedelta(minutes=3))
            record = {"proposal":proposal,"previous_record_hash":None}
            record["record_hash"] = auth.digest(record)
            journal = producer/"proposals.jsonl"
            journal.write_text(json.dumps(record)+"\n")
            config = {"schema_version":1,"protocol_path":str(protocol_path),
                "protocol_sha256":auth.digest(protocol),"journal_path":str(journal),
                "producer_uid":0,"issuer_uid":0,"executor_gid":0,
                "approval_db":str(db_path)}
            config_path = root/"issuer.json"
            config_path.write_text(json.dumps(config))
            self.assertEqual(issuer.issue(config_path,now=NOW)[0][1],"APPROVE")
            with sqlite3.connect(db_path) as db:
                self.assertEqual(db.execute("SELECT COUNT(*) FROM approvals WHERE result='APPROVE'").fetchone()[0],1)

    def test_unknown_exchange_minima_veto_new_risk(self):
        quote = {"bids":[{"price":80000,"quantity":1}],
                 "asks":[{"price":80001,"quantity":1}],"mark_price":80000.5,
                 "price_tick":0.1,"quantity_step":0.001,"step":0.001,
                 "contract_multiplier":0.001,"min_quantity":None,
                 "min_notional":None,"fee_rate":0.0005}
        with self.assertRaises(sanity.Veto):
            sanity.preflight("BTCUSDT", quote, .01, False)

    def test_issuer_cannot_issue_from_unresolved_protocol(self):
        if os.geteuid() != 0:
            self.skipTest("requires root-owned isolated config")
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            protocol_path = root/"protocol.json"
            protocol_path.write_text(json.dumps(PROTOCOL))
            config = {"schema_version":1,"protocol_path":str(protocol_path),
                "protocol_sha256":auth.digest(PROTOCOL),"journal_path":str(root/"missing.jsonl"),
                "producer_uid":30010,"issuer_uid":0,"executor_gid":0,
                "approval_db":str(root/"approvals.sqlite")}
            config_path = root/"issuer.json"
            config_path.write_text(json.dumps(config))
            with self.assertRaisesRegex(ValueError, "producer_unresolved"):
                issuer.issue(config_path, now=NOW)
            self.assertFalse((root/"approvals.sqlite").exists())

    def proposal(self, available):
        value = {"schema_version":1,"experiment_id":PROTOCOL["experiment_id"],
            "account":PROTOCOL["account"],"symbol":PROTOCOL["symbol"],
            "strategy":PROTOCOL["strategy"],"strategy_lineage_hash":PROTOCOL["lineage_root"],
            "direction":"LONG","target_weight":.1,
            "decision_timestamp":(NOW-dt.timedelta(minutes=2)).isoformat(),
            "available_at":available.isoformat(),"source_record_hash":"a"*64}
        value["decision_id"] = auth.digest(value)
        return value

    def test_issuer_requires_source_before_decision(self):
        good = self.proposal(NOW-dt.timedelta(minutes=3))
        self.assertEqual(issuer._validate_proposal({"proposal":good}, PROTOCOL, NOW), good)
        late = self.proposal(NOW-dt.timedelta(minutes=1))
        with self.assertRaisesRegex(ValueError, "proposal_time_invalid"):
            issuer._validate_proposal({"proposal":late}, PROTOCOL, NOW)

    def test_executor_intent_uses_same_ordering(self):
        proposal = self.proposal(NOW-dt.timedelta(minutes=3))
        value = {"schema_version":2,"intent_id":"intent-1","experiment_id":proposal["experiment_id"],
            "account":proposal["account"],"symbol":"BTCUSDT","strategy":proposal["strategy"],
            "strategy_lineage_hash":proposal["strategy_lineage_hash"],
            "decision_id":proposal["decision_id"],"direction":proposal["direction"],
            "target_weight":proposal["target_weight"],
            "decision_timestamp":proposal["decision_timestamp"],
            "available_at":proposal["available_at"],"source_record_hash":proposal["source_record_hash"],
            "decision_authorization_id":"token-1","intent_timestamp":NOW.isoformat()}
        self.assertEqual(executor.validate_intent(value, NOW), value)
        value["available_at"] = (NOW-dt.timedelta(minutes=1)).isoformat()
        with self.assertRaisesRegex(ValueError, "intent_availability_invalid"):
            executor.validate_intent(value, NOW)

    def test_approval_claim_uses_causal_ordering(self):
        proposal = self.proposal(NOW-dt.timedelta(minutes=3))
        intent = {"schema_version":2,"intent_id":"intent-1",
            "decision_authorization_id":"token-1", "experiment_id":proposal["experiment_id"],
            "account":proposal["account"],"symbol":"BTCUSDT","strategy":proposal["strategy"],
            "strategy_lineage_hash":proposal["strategy_lineage_hash"],
            "decision_id":proposal["decision_id"],"direction":proposal["direction"],
            "target_weight":proposal["target_weight"],
            "decision_timestamp":proposal["decision_timestamp"],
            "available_at":proposal["available_at"],"source_record_hash":proposal["source_record_hash"]}
        with tempfile.TemporaryDirectory() as folder:
            db_path = Path(folder)/"approvals.sqlite"
            issuer.initialize(db_path)
            with sqlite3.connect(db_path) as db:
                db.execute('INSERT INTO approvals VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)',
                    (proposal["decision_id"],"token-1",proposal["experiment_id"],
                     proposal["account"],proposal["symbol"],proposal["strategy"],
                     proposal["strategy_lineage_hash"],proposal["direction"],
                     proposal["target_weight"],proposal["decision_timestamp"],
                     proposal["available_at"],proposal["source_record_hash"],"b"*64,
                     issuer.POLICY_VERSION,"c"*64,(NOW-dt.timedelta(minutes=1)).isoformat(),
                     (NOW+dt.timedelta(minutes=20)).isoformat(),"APPROVE","admissible"))
            with sqlite3.connect(Path(folder)/"execution.sqlite") as ledger:
                approval.initialize_claims(ledger)
                self.assertEqual(approval.claim(db_path, ledger, intent,
                    protocol_hash="c"*64, now=NOW), proposal["source_record_hash"])
                with self.assertRaisesRegex(ValueError, "approval_consumed"):
                    approval.claim(db_path, ledger, intent, protocol_hash="c"*64, now=NOW)
                db_path.unlink()
                with self.assertRaisesRegex(ValueError, "approval_store_missing"):
                    approval.claim(db_path, ledger, dict(intent, intent_id="intent-2"),
                                   protocol_hash="c"*64, now=NOW)


if __name__ == "__main__":
    unittest.main()
