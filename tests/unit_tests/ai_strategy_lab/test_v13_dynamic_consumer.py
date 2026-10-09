import copy
import json
import sqlite3
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
import v13_dynamic_consumer as c
import v13_dynamic_intent as intent
from test_v13_dynamic_preview import receipts,START
import test_v13_dynamic_data as data_tests

NOW='2026-10-19T00:15:06Z'


class ConsumerTests(unittest.TestCase):
    def setup(self,tmp):
        root=Path(tmp);store=intent.IntentStore(root/'intents.sqlite',create=True)
        with patch.object(intent,'utc_now',side_effect=['2026-10-19T00:15:01Z','2026-10-19T00:15:02Z']):
            ident=store.record(receipts(),slot=START,start=START,lineage='consumer-synthetic-test')['id']
        books=data_tests.BookAdmissionTests().records()
        for book in books:
            book.update(at='2026-10-19T00:15:04Z',received_at='2026-10-19T00:15:05Z',bids=[[99.,10000.]],asks=[[101.,10000.]])
        books[0]['precision']['public_taker_fee']='0.002'
        consumer=c.Consumer(repo=root,approval_path=root/'approval',approval_sha256='not-a-real-pin',
                            archive=root/'archive',activation=root/'activation',intents=store,ledger_path=root/'ledger.sqlite')
        funding=dict(interval={'from':None,'to':NOW,'coverage_complete':True,'events':[]},
                     estimate={'scope':'FUNDING_ESTIMATE_DIAGNOSTIC_ONLY','events':[]})
        return store,consumer,ident,books,funding

    def test_real_denial_never_creates_ledger_or_changes_intent(self):
        with tempfile.TemporaryDirectory() as tmp:
            store,consumer,ident,books,funding=self.setup(tmp)
            before=store.db.execute('SELECT * FROM intents').fetchall()
            with patch.object(consumer,'readiness',return_value={'execution_ready':False,'blockers':['qualification_not_passed','funding_coverage_unresolved']}):
                with self.assertRaises(c.AdmissionDenied):consumer.consume(ident)
            with patch.object(consumer,'readiness',return_value={'execution_ready':True,'blockers':[]}):
                with self.assertRaisesRegex(c.AdmissionDenied,'funding_coverage_verifier_unavailable'):consumer.consume(ident)
            self.assertFalse(consumer.ledger_path.exists())
            self.assertEqual(store.db.execute('SELECT * FROM intents').fetchall(),before)
            store.close()

    def test_controller_transaction_with_explicitly_mocked_authorities(self):
        # Positive architecture test ONLY: no real qualification/funding approval.
        with tempfile.TemporaryDirectory() as tmp:
            store,consumer,ident,books,funding=self.setup(tmp)
            with patch.object(consumer,'readiness',return_value={'execution_ready':True,'blockers':[]}), \
                 patch.object(consumer,'_funding_available'),patch.object(consumer,'_read_books',return_value=books), \
                 patch.object(consumer,'_verified_funding',return_value=funding), \
                 patch.object(intent,'utc_now',return_value=NOW),patch.object(c,'utc_now',return_value=NOW):
                result=consumer.consume(ident)
                self.assertTrue(result['trades'])
                self.assertEqual(result,consumer.consume(ident))
                for trade in result['trades']:
                    source=next(b for b in books if b['symbol']==trade['symbol'])
                    expected=max(.0006,float(source['precision']['public_taker_fee']))
                    self.assertAlmostEqual(trade['fee'],abs(trade['quantity'])*trade['price']*expected)
                with sqlite3.connect(consumer.ledger_path) as db:
                    self.assertEqual(db.execute('SELECT COUNT(*) FROM batches').fetchone()[0],1)
                    self.assertEqual(db.execute('PRAGMA integrity_check').fetchone()[0],'ok')
            store.close()

    def test_failure_after_reduction_rolls_back_consumption_and_balances(self):
        with tempfile.TemporaryDirectory() as tmp:
            store,consumer,ident,books,funding=self.setup(tmp)
            ledger=c._Ledger(consumer.ledger_path,create=True)
            ledger.db.execute("CREATE TRIGGER fail BEFORE INSERT ON batches BEGIN SELECT RAISE(ABORT,'failure'); END")
            ledger.close()
            with patch.object(consumer,'readiness',return_value={'execution_ready':True,'blockers':[]}), \
                 patch.object(consumer,'_funding_available'),patch.object(consumer,'_read_books',return_value=books), \
                 patch.object(consumer,'_verified_funding',return_value=funding), \
                 patch.object(intent,'utc_now',return_value=NOW),patch.object(c,'utc_now',return_value=NOW):
                with self.assertRaises(sqlite3.DatabaseError):consumer.consume(ident)
            with sqlite3.connect(consumer.ledger_path) as db:
                self.assertEqual(db.execute('SELECT COUNT(*) FROM batches').fetchone()[0],0)
            store.close()

    def test_tampered_packet_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            store,consumer,ident,books,funding=self.setup(tmp)
            with patch.object(intent,'utc_now',return_value=NOW):packet=store.execution_inputs(ident,books)
            altered=copy.deepcopy(packet);altered['derived']['targets']['A']['BTCUSDT']=.99
            with self.assertRaisesRegex(ValueError,'packet_integrity'):c._reduce(None,altered,funding)
            store.close()
