"""Synthetic source failures only: recovery, no cursor reset, risk and custody."""
import copy
import hashlib
import json
import os
from pathlib import Path
import sqlite3
import sys
import tempfile
import unittest
from unittest.mock import patch

LAB = Path(__file__).resolve().parents[3]/'octobot/ai_strategy_lab'
sys.path.insert(0, str(LAB))
import btc_intraday_pair_io as io
import btc_intraday_pair_live as live
from intraday_pair import receipts
from intraday_pair.runner import Pair
from intraday_pair.source import digest, NS
from test_intraday_pair_runner import Clock, row


def failure(code):
    error = sqlite3.OperationalError('synthetic source failure')
    error.sqlite_errorcode = code
    return error


class Delegate:
    def __init__(self):
        self.cursor = 17
        self.calls = 0
        self.error = None
        self.result = None
    def poll(self, limit):
        self.calls += 1
        if self.error: raise self.error
        return self.result


class RecoveryTests(unittest.TestCase):
    def setUp(self):
        self.clock = Clock(); self.events = []; self.delegate = Delegate()
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.source=Path(self.tmp.name)/'book';self.source.write_text('synthetic source placeholder')
        self.reader = io.RecoveringBookReader(self.source, self.clock, self.events.append,
                                               factory=lambda p,c:self.delegate)

    def test_temporary_close_keeps_cursor_and_returns_exact_new_batch(self):
        self.reader.poll();self.delegate.error = failure(sqlite3.SQLITE_CANTOPEN)
        self.assertIsNone(self.reader.poll())
        self.assertEqual(self.reader.cursor, 17)
        self.assertEqual(self.reader.status()['status'], 'WAITING_SOURCE')
        self.delegate.error = None; expected = (dict(rows=[dict(id=18)]), 'before', 'after')
        self.delegate.result = expected; self.clock.t += NS//4
        self.assertIs(self.reader.poll(), expected)
        self.assertEqual(self.reader.cursor, 17)  # Only Pair may advance after persistence.
        self.reader.cursor = 18
        self.assertEqual(self.delegate.cursor, 18)
        self.assertEqual([e['event'] for e in self.events], ['BOOK_READ_WAIT','BOOK_READ_RECOVERED'])

    def test_retry_backoff_never_sleeps_executor_or_spams_diagnostics(self):
        self.delegate.error = failure(sqlite3.SQLITE_BUSY)
        self.reader.poll()
        for _ in range(5): self.reader.poll()
        self.assertEqual(self.delegate.calls, 1)
        self.clock.t += NS//4; self.reader.poll()
        self.assertEqual(self.delegate.calls, 2)
        self.assertEqual(self.reader.errors, 2)
        self.assertEqual(len(self.events), 1)

    def test_temporary_bootstrap_failure_does_not_initialize_accounts(self):
        count = [0]
        def factory(p,c):
            count[0] += 1
            if count[0] == 1: raise failure(sqlite3.SQLITE_CANTOPEN)
            return self.delegate
        self.reader.factory = factory
        self.assertIsNone(self.reader.poll())
        self.assertIsNone(self.reader.reader)
        self.clock.t += NS//4;self.reader.poll()
        self.assertEqual(self.reader.cursor,17)
        self.assertEqual(count[0],2)

    def test_only_declared_source_sqlite_codes_recover(self):
        for code in (sqlite3.SQLITE_CANTOPEN, sqlite3.SQLITE_BUSY, sqlite3.SQLITE_LOCKED,
                     sqlite3.SQLITE_BUSY | (2<<8)):
            self.delegate.error = failure(code);self.clock.t += NS
            self.assertIsNone(self.reader.poll())
        for code in (sqlite3.SQLITE_IOERR,sqlite3.SQLITE_CORRUPT,sqlite3.SQLITE_NOTADB,sqlite3.SQLITE_READONLY):
            self.delegate.error = failure(code);self.clock.t += NS
            with self.assertRaises(sqlite3.OperationalError): self.reader.poll()
        self.delegate.error = sqlite3.OperationalError('no trusted code');self.clock.t += NS
        with self.assertRaises(sqlite3.OperationalError): self.reader.poll()

    def test_bootstrap_retry_cannot_accept_a_replaced_database(self):
        self.reader.factory=lambda p,c: (_ for _ in ()).throw(failure(sqlite3.SQLITE_CANTOPEN))
        self.reader.poll()
        self.source.rename(self.source.with_suffix('.preserved'));self.source.write_text('different source')
        self.clock.t += NS
        with self.assertRaisesRegex(receipts.Denied,'source_file_replaced'):self.reader.poll()

    def test_original_source_validation_denials_still_propagate(self):
        for reason in ('source_file_replaced','source_cursor_regression','source_backlog_not_skipped',
                       'source_chronology_regression','book_clock','book_level','book_order'):
            self.delegate.error = receipts.Denied(reason)
            with self.assertRaisesRegex(receipts.Denied,reason): self.reader.poll()

    def test_diagnostic_storage_fault_is_not_hidden_as_source_outage(self):
        self.delegate.error = failure(sqlite3.SQLITE_CANTOPEN)
        self.reader.record = lambda event: (_ for _ in ()).throw(OSError('fixture disk full'))
        with self.assertRaises(OSError): self.reader.poll()

    def test_original_book_reader_still_checks_inode_after_a_read_error(self):
        with tempfile.TemporaryDirectory() as d:
            path=Path(d)/'book.sqlite'
            with sqlite3.connect(path) as db: db.execute('CREATE TABLE book_events(id INTEGER PRIMARY KEY)')
            self.reader = io.RecoveringBookReader(path,self.clock,self.events.append)
            self.reader.poll()
            original=receipts.ro
            with patch.object(receipts,'ro',side_effect=failure(sqlite3.SQLITE_CANTOPEN)):
                self.assertIsNone(self.reader.poll())
            path.rename(path.with_suffix('.preserved'))
            with sqlite3.connect(path) as db: db.execute('CREATE TABLE book_events(id INTEGER PRIMARY KEY)')
            self.clock.t += NS
            with self.assertRaisesRegex(receipts.Denied,'source_file_replaced'): self.reader.poll()

    def test_outage_heartbeats_preserve_position_and_latch_protective_exit(self):
        with tempfile.TemporaryDirectory() as d:
            pair=Pair(Path(d)/'pair',0,'synthetic',initialize=True,clock=self.clock,synthetic=True)
            try:
                e=pair.engines['candidate-primary']
                e.transaction('TEST_POSITION',self.clock.t,lambda:e.fill(row(self.clock.t),.005,self.clock.t,'ENTRY'))
                before=(e.s['q'],e.s['fills']);self.delegate.error=failure(sqlite3.SQLITE_CANTOPEN)
                pair.market_key='fixture'
                with patch.object(receipts,'read_blob',return_value=({'record_hash':'fixture'},None)):
                    pair.poll_sources('/synthetic/source',self.reader)
                self.assertEqual((e.s['q'],e.s['fills']),before)
                self.assertEqual(e.s['pending']['kind'],'EXIT')
                self.assertEqual(e.s['pending']['reason'],'STALE_DATA')
                self.assertEqual(pair.seq,1)
                self.assertTrue(all(a.s['last_input_seq']==1 for a in pair.engines.values()))
            finally: pair.close()


class ContinuationTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        root=Path(self.tmp.name);self.state=root/'state';self.state.mkdir(mode=0o700)
        out=root/'published';out.mkdir(mode=0o750)
        self.config=dict(activation='old-root-receipt',directory=str(self.state/'accounts'),
            source=str(root/'source'),book=str(root/'book/data.sqlite'),control=str(root/'control'),
            projection=str(out/'comparison.json'))
        self.prior=copy.deepcopy(self.config);self.predecessor=root/'predecessor.json'
        self.predecessor.write_text(json.dumps(self.prior))
        self.config.update(continuation='fixture-root-continuation',
            predecessor_configuration=str(self.predecessor),source_io_log=str(self.state/'source-read-events.jsonl'))
        self.approval=dict(protocol_sha256='frozen-protocol',identity='original-not-replaced')
        self.cont=dict(scope='AUTHORIZED_PAPER_PAIR_IO_CONTINUATION',prior_activation_sha256=digest(self.approval),
            predecessor_configuration_sha256=hashlib.sha256(self.predecessor.read_bytes()).hexdigest(),
            protocol_sha256='frozen-protocol',directory=self.config['directory'],strategy_unchanged=True,
            state_reset_allowed=False,real_orders=False,exchange_credentials=False,operational_grants=False,
            operator_acceptance_reference='fixture-only',
            runtime_files={n:hashlib.sha256((LAB/n).read_bytes()).hexdigest() for n in
                           ('btc_intraday_pair_live.py','btc_intraday_pair_io.py')})

    def authorize(self):
        def document(p):
            return self.cont if str(p)=='fixture-root-continuation' else self.prior
        with patch.object(live,'authority',return_value=self.approval),patch.object(live,'root_document',side_effect=document):
            return live.authorized(self.config)

    def test_exact_continuation_returns_original_activation_identity(self):
        old=digest(self.approval)
        self.assertIs(self.authorize(),self.approval)
        self.assertEqual(digest(self.approval),old)

    def test_unapproved_change_or_reset_rejected(self):
        initial=copy.deepcopy(self.cont)
        for key,value in [('scope','other'),('prior_activation_sha256','0'*64),
                          ('predecessor_configuration_sha256','0'*64),('protocol_sha256','other'),
                          ('directory','other'),('state_reset_allowed',True),('strategy_unchanged',False),
                          ('real_orders',True),('exchange_credentials',True),('operational_grants',True),
                          ('operator_acceptance_reference',''),('runtime_files',{})]:
            self.cont=copy.deepcopy(initial);self.cont[key]=value
            with self.subTest(key=key),self.assertRaises(ValueError):self.authorize()
        self.cont=initial;self.cont['runtime_files']['btc_intraday_pair_io.py']='0'*64
        with self.assertRaisesRegex(ValueError,'pin_mismatch'):self.authorize()

    def test_source_mount_or_projection_change_not_authorized(self):
        for key in ('source','book','directory','control','projection','activation'):
            old=self.config[key];self.config[key]='different'
            with self.subTest(key=key),self.assertRaises(ValueError):self.authorize()
            self.config[key]=old

    def test_io_log_cannot_escape_private_state_or_follow_symlink(self):
        old=self.config['source_io_log'];self.config['source_io_log']=str(Path(self.tmp.name)/'public.json')
        with self.assertRaises(ValueError):self.authorize()
        self.config['source_io_log']=old;Path(old).symlink_to(Path(self.tmp.name)/'target')
        with self.assertRaises(ValueError):self.authorize()

    def test_append_diagnostics_preserves_history_and_rejects_unsafe_files(self):
        p=self.state/'source-read-events.jsonl';io.append_event(p,dict(event='A'));io.append_event(p,dict(event='B'))
        self.assertEqual([json.loads(s)['event'] for s in p.read_text().splitlines()],['A','B'])
        p.chmod(0o644)
        with self.assertRaises(ValueError):io.append_event(p,dict(event='C'))
        self.assertEqual(len(p.read_text().splitlines()),2)


if __name__=='__main__':unittest.main()
