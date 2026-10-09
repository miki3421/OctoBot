import sqlite3
import tempfile
from pathlib import Path
import unittest
from unittest.mock import patch
import v13_dynamic_linked as linked
from test_v13_dynamic_runner import request


def wrapped(day):
    r=request(day)
    if day==1:
        r['tick']['funding']['events']=[dict(id='funding',symbol='BTCUSDT',at='2026-10-20T00:00:00Z',rate=.001,mark=100.)]
    return dict(scope=linked.SCOPE,id=r['id'],runner=r)


class LinkedTests(unittest.TestCase):
    def test_consumption_rolls_back_with_failed_ledger_insert(self):
        with tempfile.TemporaryDirectory() as tmp:
            store=linked.LinkedStore(Path(tmp)/'linked.sqlite',create=True)
            store.db.execute("CREATE TRIGGER fail BEFORE INSERT ON batches BEGIN SELECT RAISE(ABORT,'failure'); END")
            with self.assertRaises(sqlite3.DatabaseError):store.commit(wrapped(0))
            self.assertEqual(store.db.execute('SELECT COUNT(*) FROM consumed_intents').fetchone()[0],0)
            store.db.execute('DROP TRIGGER fail')
            first=store.commit(wrapped(0))
            self.assertEqual(store.db.execute('SELECT COUNT(*) FROM consumed_intents').fetchone()[0],1)
            self.assertEqual(store.commit(wrapped(0)),first)
            original=linked.runner.prepare(linked.runner.accounting.initial_state(),wrapped(0)['runner'])
            # Simulate a duplicate admission attempting a different batch ID.
            with patch.object(linked.runner,'prepare',return_value=original):
                with self.assertRaisesRegex(ValueError,'intent_already_consumed'):store.commit(wrapped(1))
            self.assertEqual(store.db.execute('SELECT COUNT(*) FROM batches').fetchone()[0],1)
            store.close()

    def test_two_weekly_slots_funding_restart_and_replay(self):
        with tempfile.TemporaryDirectory() as tmp:
            path=Path(tmp)/'linked.sqlite'
            store=linked.LinkedStore(path,create=True)
            first=store.commit(wrapped(0));self.assertTrue(first['trades'])
            for day in range(1,8):
                result=store.commit(wrapped(day))
                for arm in ('A','B','C'):
                    self.assertAlmostEqual(result['runner']['arms'][arm]['cash'],result['cash']['arms'][arm]['cash'])
                    self.assertAlmostEqual(result['runner']['arms'][arm]['funding'],result['cash']['arms'][arm]['funding'])
                store.close();store=linked.LinkedStore(path)
                self.assertEqual(store.commit(wrapped(day)),result)
            self.assertNotEqual(first['runner']['selection']['decision_id'],result['runner']['selection']['decision_id'])
            self.assertEqual(store.db.execute('SELECT COUNT(*) FROM batches').fetchone()[0],8)
            self.assertEqual(store.db.execute('SELECT COUNT(*) FROM consumed_intents').fetchone()[0],2)
            self.assertEqual(store.db.execute('PRAGMA integrity_check').fetchone()[0],'ok')
            store.close()

    def test_atomic_failure_and_real_label_denial(self):
        with tempfile.TemporaryDirectory() as tmp:
            store=linked.LinkedStore(Path(tmp)/'linked.sqlite',create=True)
            first=store.commit(wrapped(0))
            store.db.execute("CREATE TRIGGER fail BEFORE INSERT ON batches BEGIN SELECT RAISE(ABORT,'storage failure'); END")
            with self.assertRaises(sqlite3.DatabaseError):store.commit(wrapped(1))
            self.assertEqual(store.commit(wrapped(0)),first)
            self.assertEqual(store.db.execute('SELECT COUNT(*) FROM batches').fetchone()[0],1)
            store.db.execute('DROP TRIGGER fail')
            bad=wrapped(1);bad['runner']['scope']='REAL_RECEIPT_DERIVATION_PREVIEW_V1'
            with self.assertRaisesRegex(ValueError,'synthetic_runner_only'):store.commit(bad)
            store.commit(wrapped(1));store.close()
