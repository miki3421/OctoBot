"""Runtime qualification regressions, synthetic transport only."""
import datetime as dt
import importlib.util
import json
from pathlib import Path
import sqlite3
import tempfile
import unittest

ROOT=Path(__file__).resolve().parents[3]
SPEC=importlib.util.spec_from_file_location('btc_runtime_v22_test',ROOT/'octobot/ai_strategy_lab/v13_btc_forward_runtime_v2_2.py')
c=importlib.util.module_from_spec(SPEC);SPEC.loader.exec_module(c)
T=dt.datetime(2027,1,1,0,10,tzinfo=dt.timezone.utc)


class RuntimeTests(unittest.TestCase):
    def test_late_missing_is_stable_across_recovery_with_timely_raw(self):
        with tempfile.TemporaryDirectory() as root:
            archive=Path(root)/'archive';db=Path(root)/'slots.sqlite'
            last=T.replace(minute=0)-dt.timedelta(days=1)
            rows=[[int((last-dt.timedelta(days=120-i)).timestamp()*1000),100+i,100+i,100+i,100+i,1,1] for i in range(121)]
            times=iter([T+dt.timedelta(minutes=1),T+dt.timedelta(minutes=1,seconds=1)])
            c.collect_once(archive,T.isoformat(),clock=lambda:next(times),fetch=lambda url:(json.dumps({'code':'200000','data':rows}).encode(),200,None))
            written,first=c.finalize_from_archive(db,archive,T.isoformat(),clock=lambda:T+dt.timedelta(minutes=11))
            self.assertTrue(written);self.assertEqual(first['status'],'MISSING')
            written,second=c.finalize_from_archive(db,archive,T.isoformat(),clock=lambda:T+dt.timedelta(minutes=12))
            self.assertFalse(written);self.assertEqual(first,second)
            with sqlite3.connect(db) as con:self.assertEqual(con.execute('SELECT count(*) FROM conflicts').fetchone()[0],0)

    def test_unapproved_entry_point_is_closed(self):
        from types import SimpleNamespace
        with self.assertRaisesRegex(ValueError,'FORWARD_APPROVAL_MISSING'):c.preflight(SimpleNamespace(activation=None,bundle=None))

    def test_redirects_are_rejected(self):
        with self.assertRaisesRegex(ValueError,'SOURCE_REDIRECT_DENIED'):c.NoRedirect().redirect_request(None,None,302,'',{},'https://example.com')

    def test_oversized_capture_never_archived(self):
        with tempfile.TemporaryDirectory() as root:
            times=iter([T+dt.timedelta(minutes=1),T+dt.timedelta(minutes=1,seconds=1)])
            with self.assertRaisesRegex(ValueError,'SOURCE_CAPTURE_INVALID'):c.collect_once(root,T.isoformat(),clock=lambda:next(times),fetch=lambda url:(b'x'*(c.MAX_BYTES+1),200,None))
            self.assertFalse(list(Path(root).iterdir()))

    def test_regressing_clock_denies_capture(self):
        with tempfile.TemporaryDirectory() as root:
            times=iter([T+dt.timedelta(minutes=1),T])
            with self.assertRaisesRegex(ValueError,'SOURCE_CAPTURE_INVALID'):c.collect_once(root,T.isoformat(),clock=lambda:next(times),fetch=lambda url:(b'{}',200,None))

    def test_storage_failure_is_not_a_terminal_missing(self):
        with tempfile.TemporaryDirectory() as root:
            db=Path(root)/'slots.sqlite';con=c.p.connect(db)
            con.execute("CREATE TRIGGER fail BEFORE INSERT ON slots BEGIN SELECT RAISE(ABORT,'disk fault'); END;");con.close()
            with self.assertRaises(sqlite3.IntegrityError):c.finalize_from_archive(db,Path(root)/'archive',T.isoformat(),clock=lambda:T+dt.timedelta(minutes=11))
            with sqlite3.connect(db) as con:self.assertEqual(con.execute('SELECT count(*) FROM slots').fetchone()[0],0)


if __name__=='__main__':unittest.main()
