"""Synthetic offline vectors only; no forward observation or performance test."""
import concurrent.futures
import datetime as dt
import hashlib
import importlib.util
import json
from pathlib import Path
import sqlite3
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[3]
MODULE = ROOT / "octobot/ai_strategy_lab/v13_btc_research_v2.py"
VERIFY = ROOT / "octobot/ai_strategy_lab/v13_btc_research_verify_v2.py"
EVAL = ROOT / "octobot/ai_strategy_lab/v13_btc_research_eval_v2.py"


def load(path, name):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


p = load(MODULE, "research_v2_test")
v = load(VERIFY, "verify_v2_test")
e = load(EVAL, "eval_v2_test")
UTC = dt.timezone.utc
SLOT = dt.datetime(2026, 10, 1, 0, 10, tzinfo=UTC)
PRODUCER_HASH = hashlib.sha256(MODULE.read_bytes()).hexdigest()


class ResearchV2Test(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.archive = self.root / "archive"
        self.db = self.root / "slots.sqlite"
        self.rows = self.bars()

    def bars(self, trend=1):
        last = SLOT.replace(hour=0, minute=0) - dt.timedelta(days=1)
        return [[int((last-dt.timedelta(days=120-i)).timestamp()*1000),
                 1,1,1,(100+i if trend > 0 else 300-i),1,1] for i in range(121)]

    def capture(self, rows=None, *, received=None, url=None):
        raw = json.dumps({"code":"200000","data":self.rows if rows is None else rows}).encode()
        stamp = received or SLOT + dt.timedelta(minutes=1)
        return p.capture(self.archive, raw, stamp.isoformat(), request_url=url)

    def decide(self, receipt=None):
        return p.produce(self.archive, receipt or self.capture(), SLOT.isoformat(),
                         (SLOT+dt.timedelta(minutes=2)).isoformat(), PRODUCER_HASH)

    def test_future_perturbations_keep_complete_decision_identity(self):
        original, src = self.decide()
        self.assertEqual(original["status"], "LONG")
        current = [int(SLOT.replace(minute=0).timestamp()*1000),1,1,1,999999,1,1]
        future = [int((SLOT.replace(minute=0)+dt.timedelta(days=1)).timestamp()*1000),1,1,1,1,1,1]
        for rows, url, received in ((self.rows+[current], "a", None),
                                    (self.rows+[current,future], "b", None),
                                    (self.rows+[current,[*future[:4],999999999,*future[5:]]], "c", None),
                                    (self.rows, "changed-acquisition-metadata", SLOT+dt.timedelta(seconds=90))):
            changed, new_src = self.decide(self.capture(rows, url=url, received=received))
            self.assertEqual(changed, original)
            self.assertNotEqual(new_src["raw_sha256"] if rows != self.rows else new_src["receipt_id"],
                                src["raw_sha256"] if rows != self.rows else src["receipt_id"])
            self.assertTrue(v.verify(self.archive, changed, new_src, PRODUCER_HASH)["verified"])
        altered = [row.copy() for row in self.rows]
        altered[40][4] += 1
        changed, _ = self.decide(self.capture(altered))
        self.assertNotEqual(changed["causal_input_sha256"], original["causal_input_sha256"])
        self.assertNotEqual(changed["observation_id"], original["observation_id"])
        self.assertNotEqual(changed["decision_id"], original["decision_id"])

    def test_four_terminal_states_and_missed_slot(self):
        long, long_src = self.decide()
        self.assertEqual(long["status"], "LONG")
        short, short_src = self.decide(self.capture(self.bars(-1)))
        self.assertEqual(short["status"], "SHORT")
        flat_rows = self.bars()
        flat_rows[-1][4] = 150
        no, no_src = self.decide(self.capture(flat_rows))
        self.assertEqual(no["status"], "NO_PROPOSAL")
        self.assertIsNone(no["target_weight"])
        self.assertEqual(no["reason_code"], "MOMENTUM_DISAGREEMENT_OR_ZERO")
        missed, evidence = p.missing(SLOT.isoformat(), (SLOT+dt.timedelta(minutes=10)).isoformat(),
                                     PRODUCER_HASH, "SOURCE_FAILURE")
        self.assertEqual(missed["status"], "MISSING")
        self.assertIsNone(evidence)
        for idx, (record, provenance) in enumerate(((long,long_src),(short,short_src),(no,no_src),(missed,None))):
            path = self.root / f"state-{idx}.sqlite"
            recorded_at = SLOT+dt.timedelta(minutes=10) if idx == 3 else SLOT+dt.timedelta(minutes=2)
            self.assertTrue(p.append_slot(path, record, provenance, recorded_at.isoformat()))
            db = sqlite3.connect(path)
            self.assertEqual(db.execute("SELECT count(*) FROM slots").fetchone()[0],1)
            db.close()
        with self.assertRaisesRegex(ValueError, "SLOT_DEADLINE_PASSED"):
            p.produce(self.archive, self.capture(), SLOT.isoformat(),
                      (SLOT+dt.timedelta(minutes=11)).isoformat(), PRODUCER_HASH)

    def test_scheduler_never_backfills_missed_forward_slot(self):
        with self.assertRaisesRegex(ValueError,"SLOT_NOT_FINALIZABLE"):
            p.finalize_slot(self.db,self.archive,None,SLOT.isoformat(),SLOT.isoformat(),PRODUCER_HASH)
        late = (SLOT+dt.timedelta(days=1)).isoformat()
        receipt=self.capture()
        written,record=p.finalize_slot(self.db,self.archive,receipt,SLOT.isoformat(),late,PRODUCER_HASH)
        self.assertTrue(written)
        self.assertEqual((record["status"],record["reason_code"]),("MISSING","LATE_ACQUISITION"))
        with self.assertRaisesRegex(ValueError,"SLOT_INTEGRITY_CONFLICT"):
            p.append_slot(self.db,self.decide(receipt)[0],
                          self.decide(receipt)[1],late)

    def test_idempotence_restart_concurrency_and_conflict(self):
        record, src = self.decide()
        recorded=(SLOT+dt.timedelta(minutes=2)).isoformat()
        self.assertTrue(p.append_slot(self.db,record,src,recorded))
        self.assertFalse(p.append_slot(self.db,record,src,recorded))
        changed_source = self.capture(self.rows + [[int(SLOT.replace(minute=0).timestamp()*1000),1,1,1,999,1,1]])
        same, changed_provenance = self.decide(changed_source)
        self.assertEqual(same,record)
        self.assertFalse(p.append_slot(self.db,same,changed_provenance,recorded))
        # Separate connections emulate process restart; concurrent writers see one slot.
        with concurrent.futures.ThreadPoolExecutor(max_workers=4) as pool:
            results = list(pool.map(lambda _: p.append_slot(self.db,record,src,recorded),range(8)))
        self.assertEqual(results,[False]*8)
        altered = [row.copy() for row in self.rows]; altered[40][4] += 1
        conflict,_ = self.decide(self.capture(altered))
        with self.assertRaisesRegex(ValueError,"SLOT_INTEGRITY_CONFLICT"):
            p.append_slot(self.db,conflict,src,recorded)
        db=sqlite3.connect(self.db)
        self.assertEqual(db.execute("SELECT count(*) FROM slots").fetchone()[0],1)
        self.assertEqual(db.execute("SELECT count(*) FROM conflicts").fetchone()[0],1)
        with self.assertRaises(sqlite3.DatabaseError):
            db.execute("UPDATE slots SET decision_id='bad'")
        db.close()

    def test_concurrent_first_writer_and_sealed_evaluator(self):
        record,source=self.decide()
        stamp=(SLOT+dt.timedelta(minutes=2)).isoformat()
        with concurrent.futures.ThreadPoolExecutor(max_workers=4) as pool:
            results=list(pool.map(lambda _: p.append_slot(self.db,record,source,stamp),range(8)))
        self.assertEqual(results.count(True),1)
        self.assertEqual(results.count(False),7)
        with self.assertRaisesRegex(ValueError,"PERFORMANCE_SEALED_UNTIL_CUTOFF"):
            e.review(self.db,self.archive,SLOT.isoformat(),(SLOT+dt.timedelta(days=180)).isoformat())

    def test_bootstrap_spec_on_constant_synthetic_vector(self):
        self.assertEqual(e.circular_ci([1.0]*180),(1.0,1.0))

    def test_outcome_maturity_duplicate_and_immutable_decision(self):
        record,src=self.decide()
        p.append_slot(self.db,record,src,(SLOT+dt.timedelta(minutes=2)).isoformat())
        db=sqlite3.connect(self.db)
        before=db.execute("SELECT decision_json FROM slots").fetchone()[0]
        db.close()
        outcome_row=[int(SLOT.replace(minute=0).timestamp()*1000),1,1,1,250,1,1]
        early=self.capture(self.rows+[outcome_row],received=SLOT+dt.timedelta(hours=1))
        with self.assertRaisesRegex(ValueError,"OUTCOME_NOT_MATURE"):
            p.mature(self.db,self.archive,SLOT.isoformat(),early)
        mature_at=SLOT+dt.timedelta(days=1,minutes=1)
        receipt=self.capture(self.rows+[outcome_row],received=mature_at)
        self.assertTrue(p.mature(self.db,self.archive,SLOT.isoformat(),receipt))
        self.assertFalse(p.mature(self.db,self.archive,SLOT.isoformat(),receipt))
        changed=[*outcome_row];changed[4]=251
        conflict=self.capture(self.rows+[changed],received=mature_at)
        with self.assertRaisesRegex(ValueError,"OUTCOME_INTEGRITY_CONFLICT"):
            p.mature(self.db,self.archive,SLOT.isoformat(),conflict)
        db=sqlite3.connect(self.db)
        self.assertEqual(db.execute("SELECT decision_json FROM slots").fetchone()[0],before)
        self.assertEqual(db.execute("SELECT count(*) FROM outcomes").fetchone()[0],1)
        with self.assertRaises(sqlite3.DatabaseError):
            db.execute("UPDATE outcomes SET outcome_id='bad'")
        db.close()

    def test_verifier_rejects_tamper_and_archive_change(self):
        record,src=self.decide()
        self.assertTrue(v.verify(self.archive,record,src,PRODUCER_HASH)["verified"])
        altered=dict(record);altered["target_weight"]="0.11"
        with self.assertRaisesRegex(ValueError,"DERIVATION_MISMATCH"):
            v.verify(self.archive,altered,src,PRODUCER_HASH)
        raw=self.archive/"raw"/(src["raw_sha256"]+".json")
        raw.chmod(0o600);raw.write_bytes(raw.read_bytes()+b" ")
        with self.assertRaisesRegex(ValueError,"RAW_HASH_MISMATCH"):
            v.verify(self.archive,record,src,PRODUCER_HASH)


if __name__ == "__main__":
    unittest.main()
