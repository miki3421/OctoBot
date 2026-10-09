import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
import v13_dynamic_service as service
import test_v13_dynamic_consumer as fixtures
import v13_dynamic_consumer as c

class ServiceTests(unittest.TestCase):
    def test_blocked_status_durable_without_ledger(self):
        with tempfile.TemporaryDirectory() as tmp:
            store,executor,ident,books,funding=fixtures.ConsumerTests().setup(tmp)
            runner=service.Service(executor,Path(tmp)/'status.json',intent_validity_seconds=60)
            with patch.object(executor,'readiness',return_value={'execution_ready':False,'blockers':['qualification_not_passed']}):
                self.assertEqual(runner.cycle()['status'],'BLOCKED')
                self.assertEqual(runner.cycle()['status'],'BLOCKED')
            self.assertFalse(executor.ledger_path.exists());store.close()

    def test_expired_intent_cannot_execute_after_restart(self):
        with tempfile.TemporaryDirectory() as tmp:
            store,executor,ident,books,funding=fixtures.ConsumerTests().setup(tmp)
            with patch.object(executor,'readiness',return_value={'execution_ready':True}),patch.object(c,'utc_now',return_value='2026-10-19T00:16:00Z'),patch.object(executor,'consume') as consume:
                for _ in range(2):
                    runner=service.Service(executor,Path(tmp)/'status.json',intent_validity_seconds=60)
                    self.assertEqual(runner.cycle()['status'],'EXPIRED')
                consume.assert_not_called()
            store.close()

    def test_observation_changes_equity_without_fills(self):
        with tempfile.TemporaryDirectory() as tmp:
            store,executor,ident,books,funding=fixtures.ConsumerTests().setup(tmp)
            with patch.object(fixtures.intent,'utc_now',return_value=fixtures.NOW):packet=store.execution_inputs(ident,books)
            previous=c._reduce(None,packet,funding)
            import copy
            tick=copy.deepcopy(packet);tick['as_of']='2026-10-19T00:30:06Z';tick['intent_persisted_at']=fixtures.NOW
            for b in tick['books'].values():b.update(at='2026-10-19T00:30:04Z',received_at='2026-10-19T00:30:05Z',bids=[[109.,10000.]],asks=[[111.,10000.]])
            tick['packet_hash']=c.cash.selector.digest({k:v for k,v in tick.items() if k!='packet_hash'})
            funding['interval'].update(**{'from':fixtures.NOW,'to':tick['as_of']})
            result=c._reduce(previous,tick,funding,observation=True)
            self.assertEqual(result['trades'],[])
            self.assertEqual(result['engine']['last_rebalance'],previous['engine']['last_rebalance'])
            self.assertNotEqual(result['engine']['arms']['A']['equity'],previous['engine']['arms']['A']['equity'])
            self.assertEqual(result['engine']['arms']['A']['positions'],previous['engine']['arms']['A']['positions'])
            store.close()

    def test_read_only_intent_store_cannot_write(self):
        import sqlite3
        import v13_dynamic_intent as intent
        with tempfile.TemporaryDirectory() as tmp:
            store,executor,ident,books,funding=fixtures.ConsumerTests().setup(tmp)
            path=Path(tmp)/'intents.sqlite';store.close()
            reader=intent.IntentStore(path,read_only=True)
            self.assertIsNotNone(reader.db.execute('SELECT id FROM intents').fetchone())
            with self.assertRaises(sqlite3.OperationalError):reader.db.execute('DELETE FROM intents')
            reader.close()

    def test_expiry_checked_inside_writer_transaction(self):
        import sqlite3
        with tempfile.TemporaryDirectory() as tmp:
            store,executor,ident,books,funding=fixtures.ConsumerTests().setup(tmp)
            with patch.object(executor,'readiness',return_value={'execution_ready':True}),patch.object(executor,'_funding_available'),patch.object(executor,'_read_books',return_value=books),patch.object(fixtures.intent,'utc_now',return_value=fixtures.NOW),patch.object(c,'utc_now',return_value='2026-10-19T00:16:00Z'):
                with self.assertRaisesRegex(ValueError,'intent_expired_under_writer_lock'):
                    executor.consume(ident,valid_until='2026-10-19T00:16:00Z')
            with sqlite3.connect(executor.ledger_path) as db:self.assertEqual(db.execute('SELECT COUNT(*) FROM batches').fetchone()[0],0)
            store.close()

    def test_protective_close_never_increases_or_reverses(self):
        import copy
        with tempfile.TemporaryDirectory() as tmp:
            store,executor,ident,books,funding=fixtures.ConsumerTests().setup(tmp)
            with patch.object(fixtures.intent,'utc_now',return_value=fixtures.NOW):packet=store.execution_inputs(ident,books)
            previous=c._reduce(None,packet,funding)
            tick=copy.deepcopy(packet);tick['as_of']='2026-10-19T00:30:06Z';tick['intent_persisted_at']='2026-10-19T00:30:00Z'
            for b in tick['books'].values():b.update(at='2026-10-19T00:30:04Z',received_at='2026-10-19T00:30:05Z')
            tick['packet_hash']=c.cash.selector.digest({k:v for k,v in tick.items() if k!='packet_hash'})
            funding['interval'].update(**{'from':fixtures.NOW,'to':tick['as_of']})
            result=c._reduce(previous,tick,funding,protective=True)
            self.assertTrue(result['trades'])
            for arm in c.cash.accounting.ARMS:
                before=previous['engine']['arms'][arm]['positions']
                for symbol,quantity in result['engine']['arms'][arm]['positions'].items():
                    self.assertLessEqual(abs(quantity),abs(before.get(symbol,0)))
                    self.assertGreaterEqual(quantity*before.get(symbol,0),0)
            store.close()

    def test_admin_command_commit_and_replay_denial(self):
        import json
        import sqlite3
        with tempfile.TemporaryDirectory() as tmp:
            store,executor,ident,books,funding=fixtures.ConsumerTests().setup(tmp)
            with patch.object(executor,'readiness',return_value={'execution_ready':True}),patch.object(executor,'_funding_available'),patch.object(executor,'_read_books',return_value=books),patch.object(executor,'_verified_funding',return_value=funding):
                with patch.object(fixtures.intent,'utc_now',return_value=fixtures.NOW),patch.object(c,'utc_now',return_value=fixtures.NOW):previous=executor.consume(ident)
                command=dict(scope='ABC_ADMIN_CLOSE_ALL_V1',id='synthetic-admin-command',ledger_path=str(executor.ledger_path),expected_state_hash=previous['state_hash'],issued_at='2026-10-19T00:30:00Z',expires_at='2026-10-19T00:31:00Z')
                path=Path(tmp)/'command.json';raw=json.dumps(command).encode();path.write_bytes(raw)
                for b in books:b.update(at='2026-10-19T00:30:04Z',received_at='2026-10-19T00:30:05Z')
                funding['interval'].update(**{'from':fixtures.NOW,'to':'2026-10-19T00:30:06Z'})
                # Authority fixture only: /tmp is not an authorized command location.
                with patch.object(c.data.capture,'safe_path'),patch.object(c,'utc_now',return_value='2026-10-19T00:30:06Z'):
                    # Close authorization is separate from permission to add risk.
                    with patch.object(executor,'readiness',return_value={'execution_ready':False,'blockers':['no_new_risk']}):
                        result=executor.close_all(path,c.data.capture.sha(raw))
                    self.assertTrue(result['trades'])
                    with self.assertRaises(ValueError):executor.close_all(path,c.data.capture.sha(raw))
                with sqlite3.connect(executor.ledger_path) as db:self.assertEqual(db.execute('SELECT COUNT(*) FROM batches').fetchone()[0],2)
            store.close()

    def test_incomplete_funding_close_preserves_debt_until_reconciliation(self):
        import copy
        with tempfile.TemporaryDirectory() as tmp:
            store,executor,ident,books,funding=fixtures.ConsumerTests().setup(tmp)
            with patch.object(fixtures.intent,'utc_now',return_value=fixtures.NOW):packet=store.execution_inputs(ident,books)
            previous=c._reduce(None,packet,funding)
            tick=copy.deepcopy(packet);tick['as_of']='2026-10-19T00:30:06Z';tick['intent_persisted_at']='2026-10-19T00:30:00Z'
            for b in tick['books'].values():b.update(at='2026-10-19T00:30:04Z',received_at='2026-10-19T00:30:05Z')
            tick['packet_hash']=c.cash.selector.digest({k:v for k,v in tick.items() if k!='packet_hash'})
            funding['interval'].update(**{'from':fixtures.NOW,'to':tick['as_of'],'coverage_complete':False})
            with self.assertRaisesRegex(ValueError,'funding_coverage_required'):c._reduce(previous,tick,funding,observation=True)
            closed=c._reduce(previous,tick,funding,protective=True)
            self.assertFalse(closed['equity_complete'])
            self.assertEqual(closed['engine']['funding_cursor'],fixtures.NOW)
            self.assertIsNone(closed['engine']['arms']['A']['net_equity'])
            symbol=next(s for s,q in previous['engine']['arms']['A']['positions'].items() if q)
            event=dict(id='synthetic-late-funding',symbol=symbol,at='2026-10-19T00:20:00Z',rate=.001,mark=100.,status='ESTIMATED_PRIOR_BOOK_MIDPOINT',mark_source_hash='a'*64,mark_observed_at='2026-10-19T00:19:00Z')
            tick['as_of']='2026-10-19T00:45:06Z';tick['intent_persisted_at']='2026-10-19T00:30:06Z'
            for b in tick['books'].values():b.update(at='2026-10-19T00:45:04Z',received_at='2026-10-19T00:45:05Z')
            tick['packet_hash']=c.cash.selector.digest({k:v for k,v in tick.items() if k!='packet_hash'})
            funding['interval'].update(to=tick['as_of'],coverage_complete=True,events=[event]);funding['estimate']['events']=[event]
            result=c._reduce(closed,tick,funding,observation=True)
            self.assertTrue(result['equity_complete'])
            self.assertAlmostEqual(result['engine']['arms']['A']['funding'],-previous['engine']['arms']['A']['positions'][symbol]*.1)
            store.close()

    def test_expired_new_intent_does_not_stop_existing_account_observations(self):
        with tempfile.TemporaryDirectory() as tmp:
            store,executor,ident,books,funding=fixtures.ConsumerTests().setup(tmp)
            ledger=c._Ledger(executor.ledger_path,create=True)
            ledger.db.execute("INSERT INTO batches VALUES ('prior-intent','fixture','{}')");ledger.close()
            runner=service.Service(executor,Path(tmp)/'status.json',intent_validity_seconds=60)
            with patch.object(executor,'readiness',return_value={'execution_ready':True}),patch.object(c,'utc_now',return_value='2026-10-19T00:16:00Z'),patch.object(executor,'consume') as consume,patch.object(executor,'observe') as observe:
                result=runner.cycle()
                self.assertEqual(result['status'],'EXPIRED');self.assertTrue(result['observation_updated'])
                consume.assert_not_called();observe.assert_called_once()
            store.close()
