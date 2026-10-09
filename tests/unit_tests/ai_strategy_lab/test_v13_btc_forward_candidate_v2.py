"""Isolated synthetic transport/schedule tests; no public fetch or forward start."""
import datetime as dt
import importlib.util
import json
import os
from pathlib import Path
import sqlite3
import subprocess
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest import mock

ROOT = Path(__file__).resolve().parents[3]
MODULE = ROOT / "octobot/ai_strategy_lab/v13_btc_forward_candidate_v2.py"
SPEC = importlib.util.spec_from_file_location("v13_btc_forward_candidate_v2_test",MODULE)
c = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(c)
p = c.p
UTC = dt.timezone.utc
START = dt.datetime(2027,1,1,0,10,tzinfo=UTC)


class CandidateForwardTest(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root=Path(self.tmp.name)
        self.archive=self.root/"archive"
        self.db=self.root/"research.sqlite"

    def rows(self,slot,*,last_close_shift=0):
        latest=slot.replace(minute=0)-dt.timedelta(days=1)
        rows=[]
        for i in range(121):
            day=latest-dt.timedelta(days=120-i)
            close=100+i+(last_close_shift if i==120 else 0)
            rows.append([int(day.timestamp()*1000),close,close,close,close,1,1])
        return rows

    def collect(self,slot,rows=None,*,status=200):
        raw=json.dumps({"code":"200000","data":rows or self.rows(slot)}).encode()
        times=iter((slot+dt.timedelta(minutes=1),slot+dt.timedelta(minutes=1,seconds=1)))
        return c.collect_once(self.archive,slot.isoformat(),clock=lambda:next(times),
                              fetch=lambda url:(raw,status,None))

    def final(self,slot,minutes=9,seconds=45):
        time=slot+dt.timedelta(minutes=minutes,seconds=seconds)
        return c.finalize_from_archive(self.db,self.archive,slot.isoformat(),clock=lambda:time)

    def test_public_url_and_capture_attestation(self):
        slot=START
        expected=c.query_url(slot.isoformat(),(slot+dt.timedelta(minutes=1)).isoformat())
        self.assertTrue(expected.startswith(c.ENDPOINT+"?symbol=XBTUSDTM&granularity=1440&"))
        with self.assertRaisesRegex(ValueError,"COLLECTION_OUTSIDE_SLOT"):
            c.query_url(slot.isoformat(),(slot-dt.timedelta(seconds=1)).isoformat())
        result=self.collect(slot)
        docs=c.read_attestations(self.archive,slot.isoformat())
        self.assertEqual(len(docs),1)
        self.assertEqual(docs[0]["receipt_id"],result["receipt_id"])
        self.assertEqual(docs[0]["request_url"],expected)
        self.assertEqual(docs[0]["http_status"],200)
        with self.assertRaisesRegex(ValueError,"SOURCE_CAPTURE_INVALID"):
            self.collect(slot,status=503)

    def test_activation_and_clock_checks_fail_closed(self):
        args=SimpleNamespace(activation=None,bundle=None,archive=self.archive,
                             journal=self.db,mode="status",slot=None)
        with self.assertRaisesRegex(ValueError,"FORWARD_APPROVAL_MISSING"):
            c.preflight(args)
        with mock.patch.object(c.subprocess,"run",return_value=SimpleNamespace(returncode=1,stdout="")):
            with self.assertRaisesRegex(ValueError,"CLOCK_NOT_SYNCHRONIZED"):
                c.require_synchronized_clock()
        activation=self.root/"activation.json"
        activation.write_text("{}")
        activation.chmod(0o666)
        with self.assertRaisesRegex(ValueError,"ACTIVATION_OWNERSHIP_INVALID"):
            c._read_root_activation(activation)

    def test_timely_slot_restart_status_and_sealing(self):
        slot=START
        self.collect(slot)
        written,decision=self.final(slot)
        self.assertTrue(written)
        self.assertEqual(decision["status"],"LONG")
        self.assertEqual(decision["research_only"],True)
        again,second=self.final(slot,minutes=10,seconds=30)
        self.assertFalse(again)
        self.assertEqual(second["decision_id"],decision["decision_id"])
        status=c.status_only(self.db)
        self.assertEqual(status["slot_counts"]["LONG"],1)
        self.assertEqual(status["mature_outcome_count"],0)
        self.assertNotIn("return",json.dumps(status).lower())
        self.assertNotIn("hit_rate",json.dumps(status).lower())

    def test_missed_and_late_source_never_becomes_decision(self):
        slot=START
        with self.assertRaisesRegex(ValueError,"SLOT_NOT_FINALIZABLE"):
            self.final(slot)
        written,decision=self.final(slot,minutes=10,seconds=30)
        self.assertTrue(written)
        self.assertEqual((decision["status"],decision["reason_code"]),("MISSING","SOURCE_FAILURE"))
        self.collect(slot)
        with self.assertRaisesRegex(ValueError,"SLOT_INTEGRITY_CONFLICT"):
            self.final(slot,minutes=10,seconds=31)
        db=sqlite3.connect(self.db)
        self.assertEqual(db.execute("SELECT count(*) FROM slots").fetchone()[0],1)
        self.assertEqual(db.execute("SELECT count(*) FROM conflicts").fetchone()[0],1)
        db.close()

    def test_conflicting_sources_and_tampered_attestation_fail_closed(self):
        slot=START
        self.collect(slot)
        self.collect(slot,self.rows(slot,last_close_shift=1))
        with self.assertRaisesRegex(ValueError,"SLOT_NOT_FINALIZABLE"):
            self.final(slot)
        written,decision=self.final(slot,minutes=10,seconds=0)
        self.assertTrue(written)
        self.assertEqual((decision["status"],decision["reason_code"]),("MISSING","INTEGRITY_FAILURE"))
        next_slot=slot+dt.timedelta(days=1)
        self.collect(next_slot)
        path=next((self.archive/"attestations"/next_slot.strftime("%Y%m%d")).glob("*.json"))
        path.chmod(0o600)
        data=json.loads(path.read_text());data["raw_sha256"]="0"*64
        path.write_text(json.dumps(data))
        written,decision=self.final(next_slot,minutes=10,seconds=0)
        self.assertTrue(written)
        self.assertEqual((decision["status"],decision["reason_code"]),("MISSING","INTEGRITY_FAILURE"))

    def test_next_day_outcome_uses_preserved_capture_only(self):
        first=START
        self.collect(first)
        _,decision=self.final(first)
        next_day=first+dt.timedelta(days=1)
        with self.assertRaisesRegex(ValueError,"OUTCOME_SOURCE_MISSING"):
            c.mature_previous(self.db,self.archive,next_day.isoformat(),
                              clock=lambda:next_day+dt.timedelta(minutes=11))
        self.collect(next_day)
        self.assertTrue(c.mature_previous(self.db,self.archive,next_day.isoformat(),
                                          clock=lambda:next_day+dt.timedelta(minutes=11)))
        self.assertFalse(c.mature_previous(self.db,self.archive,next_day.isoformat(),
                                           clock=lambda:next_day+dt.timedelta(minutes=12)))
        db=sqlite3.connect(self.db)
        stored=json.loads(db.execute("SELECT outcome_json FROM outcomes").fetchone()[0])
        self.assertEqual(stored["decision_id"],decision["decision_id"])
        self.assertEqual(db.execute("SELECT decision_id FROM slots").fetchone()[0],decision["decision_id"])
        db.close()

    def test_180_synthetic_slots_no_performance_calculation(self):
        for day in range(180):
            slot=START+dt.timedelta(days=day)
            self.collect(slot)
            written,decision=self.final(slot)
            self.assertTrue(written)
            self.assertEqual(decision["status"],"LONG")
        status=c.status_only(self.db)
        self.assertEqual(status["slot_counts"]["LONG"],180)
        self.assertEqual(status["mature_outcome_count"],0)
        db=sqlite3.connect(self.db)
        self.assertEqual(db.execute("PRAGMA integrity_check").fetchone()[0],"ok")
        db.close()

    def test_distinct_uid_storage_boundary_in_temporary_directory(self):
        if os.geteuid() != 0:
            self.skipTest("requires disposable numeric Unix UIDs")
        self.root.chmod(0o755)
        self.archive.mkdir()
        os.chown(self.archive,30040,30041)
        self.archive.chmod(0o750)
        raw=self.archive/"sample.json"
        raw.write_bytes(b"public research source")
        os.chown(raw,30040,30041)
        raw.chmod(0o440)
        journal_dir=self.root/"journal"
        journal_dir.mkdir()
        os.chown(journal_dir,30041,30041)
        journal_dir.chmod(0o700)
        journal=journal_dir/"slots.sqlite"
        journal.write_bytes(b"research ledger")
        os.chown(journal,30041,30041)
        journal.chmod(0o600)
        script="""import pathlib,sys
raw,journal,archive=map(pathlib.Path,sys.argv[1:4])
role=sys.argv[4]
raw.read_bytes()
def denied(path):
 try: path.write_bytes(b'bad')
 except PermissionError: return
 raise SystemExit('write unexpectedly permitted: '+str(path))
if role=='finalizer':
 denied(raw)
 journal.write_bytes(b'research ledger')
else:
 (archive/'collector-owned').write_bytes(b'public')
 denied(journal)
"""
        for uid,role in ((30040,"collector"),(30041,"finalizer")):
            def drop(target=uid):
                os.setgroups([])
                os.setgid(30041)
                os.setuid(target)
            result=subprocess.run([sys.executable,"-c",script,str(raw),str(journal),
                                   str(self.archive),role],preexec_fn=drop,
                                  capture_output=True,text=True)
            self.assertEqual(result.returncode,0,result.stderr)
        self.assertEqual(journal.read_bytes(),b"research ledger")


if __name__=="__main__":
    unittest.main()
