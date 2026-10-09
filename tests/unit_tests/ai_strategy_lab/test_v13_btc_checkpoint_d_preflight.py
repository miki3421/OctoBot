"""Checkpoint D stops at research/issuer boundary; no authorization fixture."""
import copy
import datetime as dt
import hashlib
import importlib.util
import json
from pathlib import Path
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[3]
BASE = ROOT / "octobot/ai_strategy_lab"


def load(filename, name):
    spec = importlib.util.spec_from_file_location(name, BASE / filename)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


p = load("v13_btc_research_producer.py", "p")
d = load("v13_btc_checkpoint_d_preflight.py", "d")
CONTRACT = BASE / "v13_btc_research_contract_v1.json"
PROTOCOL = BASE / "v13_btc_experiment_protocol_v1.json"
UTC = dt.timezone.utc


class BoundaryTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.archive = Path(self.tmp.name) / "archive"
        latest = dt.datetime(2026, 9, 24, tzinfo=UTC)
        rows = [[int((latest-dt.timedelta(days=120-i)).timestamp()*1000),
                 100+i, 101+i, 99+i, 100+i, 10, 1000] for i in range(121)]
        acquired = dt.datetime(2026, 9, 25, 11, tzinfo=UTC)
        times = iter((acquired, acquired+dt.timedelta(seconds=1)))
        snap = p.collect(self.archive, CONTRACT, now=lambda: next(times),
                         fetch=lambda url: json.dumps({"code":"200000","data":rows}).encode())
        self.result = p.decision(self.archive, snap, CONTRACT,
                                 dt.datetime(2026, 9, 25, 12, tzinfo=UTC).isoformat())
        self.manifest_hash = p.digest(p.manifest(CONTRACT))
        self.code_hash = hashlib.sha256((BASE / "v13_btc_research_producer.py").read_bytes()).hexdigest()
        self.now = dt.datetime(2026, 9, 25, 12, 1, tzinfo=UTC)

    def probe(self, result=None, **kwargs):
        return d.probe(self.archive, CONTRACT, PROTOCOL, result or self.result,
                       manifest_hash=self.manifest_hash, code_hash=self.code_hash,
                       now=kwargs.pop("now", self.now), **kwargs)

    def test_real_derivation_stops_before_issuer(self):
        answer = self.probe()
        self.assertEqual(answer["state"], "BLOCKED")
        self.assertTrue(answer["decision_verified"])
        self.assertFalse(answer["authorization_created"])
        self.assertFalse(answer["paper_fill_created"])
        self.assertIn("producer_unresolved", answer["gates"])
        self.assertIn("research_contract_not_approved", answer["gates"])
        self.assertIn("exchange_minima_unknown", answer["gates"])
        self.assertIn("issuer_unavailable", answer["gates"])
        self.assertIn("approval_storage_unavailable", answer["gates"])

    def test_tampering_identity_and_staleness_deny(self):
        for field, replacement in (("source_record_hash", "0"*64),
                                   ("target_weight", "0.11"),
                                   ("strategy_lineage_hash", "a"*64),
                                   ("account", "other"), ("symbol", "ETH/USDT:USDT")):
            changed = copy.deepcopy(self.result)
            changed["payload"][field] = replacement
            changed["decision_id"] = p.digest(changed["payload"])
            self.assertEqual(self.probe(changed)["state"], "DENY", field)
        stale = self.probe(now=self.now+dt.timedelta(hours=1))
        self.assertEqual(stale["reason"], "proposal_stale_or_noncausal")

    def test_corrupt_storage_stays_blocked(self):
        root = Path(self.tmp.name)
        config = root / "issuer.json"
        config.write_text("{}")
        store = root / "approvals.sqlite"
        store.write_bytes(b"not-a-sqlite-database")
        answer = self.probe(issuer_config=config, approval_db=store)
        self.assertEqual(answer["state"], "BLOCKED")
        self.assertIn("approval_storage_unavailable", answer["gates"])
        self.assertFalse(answer["authorization_created"])


if __name__ == "__main__":
    unittest.main()
