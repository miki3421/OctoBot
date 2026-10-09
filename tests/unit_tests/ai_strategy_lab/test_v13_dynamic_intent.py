import tempfile
from pathlib import Path
from unittest.mock import patch
import unittest
import v13_dynamic_intent as intent
from test_v13_dynamic_preview import receipts,START
import test_v13_dynamic_data as data_tests


class IntentTests(unittest.TestCase):
    def test_execution_packet_binds_saved_targets_and_real_precision(self):
        with tempfile.TemporaryDirectory() as tmp:
            store=intent.IntentStore(Path(tmp)/'intent.sqlite',create=True)
            first=self.record(store)
            books=data_tests.BookAdmissionTests().records()
            for b in books:
                b.update(at='2026-10-19T00:15:04Z',received_at='2026-10-19T00:15:05Z')
            with patch.object(intent,'utc_now',return_value='2026-10-19T00:15:06Z'):
                packet=store.execution_inputs(first['id'],books)
                self.assertEqual(packet,store.execution_inputs(first['id'],list(reversed(books))))
                self.assertEqual(packet['derived']['selection']['decision_id'],first['id'])
                self.assertEqual(set(packet['price_ticks'].values()),{'0.05'})
                self.assertEqual(packet['funding_coverage'],'UNKNOWN')
                self.assertFalse(packet['paper_orders_authorized'])
                with self.assertRaisesRegex(ValueError,'synthetic_runner_only'):
                    intent.preview.runner.run_tick(None,packet)
                with self.assertRaises(ValueError):store.execution_inputs(first['id'],books[:-1])
                self.assertFalse(store.db.in_transaction)
            store.close()

    def record(self,store):
        with patch.object(intent,'utc_now',side_effect=['2026-10-19T00:15:01Z','2026-10-19T00:15:02Z']):
            return store.record(receipts(),slot=START,start=START,lineage='offline-test')

    def test_post_commit_seal_restart_replay_and_book_binding(self):
        with tempfile.TemporaryDirectory() as tmp:
            path=Path(tmp)/'intent.sqlite';store=intent.IntentStore(path,create=True)
            first=self.record(store);store.close();store=intent.IntentStore(path)
            with patch.object(intent,'utc_now',return_value='2026-10-19T00:15:03Z'):
                self.assertEqual(store.record(receipts(),slot=START,start=START,lineage='offline-test'),first)
            books=data_tests.BookAdmissionTests().records()
            for b in books:
                b.update(at='2026-10-19T00:15:04Z',received_at='2026-10-19T00:15:05Z')
            with patch.object(intent,'utc_now',return_value='2026-10-19T00:15:06Z'):
                result=store.check_books(first['id'],books)
                self.assertEqual(result['intent_persisted_at'],first['sealed_at'])
                self.assertFalse(result['execution_ready'])
                books[0]['at']='2026-10-19T00:15:01Z'
                with self.assertRaises(ValueError):store.check_books(first['id'],books)
            self.assertEqual(store.db.execute('PRAGMA integrity_check').fetchone()[0],'ok');store.close()

    def test_failure_between_commit_and_seal_denies_restart(self):
        with tempfile.TemporaryDirectory() as tmp:
            p=Path(tmp)/'intent.sqlite';store=intent.IntentStore(p,create=True)
            with patch.object(intent,'utc_now',side_effect=['2026-10-19T00:15:01Z',RuntimeError('crash')]):
                with self.assertRaises(RuntimeError):store.record(receipts(),slot=START,start=START,lineage='offline-test')
            ident=store.db.execute('SELECT id FROM intents').fetchone()[0]
            store.close();store=intent.IntentStore(p)
            with self.assertRaisesRegex(ValueError,'sealed_intent_required'):store.check_books(ident,[])
            with patch.object(intent,'utc_now',return_value='2026-10-19T00:15:03Z'):
                with self.assertRaisesRegex(ValueError,'unsealed_intent_requires_review'):
                    store.record(receipts(),slot=START,start=START,lineage='offline-test')
            store.close()
