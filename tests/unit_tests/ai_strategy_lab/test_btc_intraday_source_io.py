"""IO-only continuation tests for the initial BTC intraday account."""
import copy,hashlib,json,os,sqlite3,sys,tempfile,unittest
from pathlib import Path
from unittest.mock import patch
LAB=Path(__file__).resolve().parents[3]/'octobot/ai_strategy_lab'
sys.path[:0]=[str(LAB),str(Path(__file__).parent)]
import btc_intraday_source_io as io
import btc_intraday_io_continuation as live
import btc_intraday_availability as receipts
from test_btc_intraday_paper import Clock,row,P
NS=live.frozen.NS
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

    def test_outage_heartbeats_keep_short_and_latch_protective_exit(self):
        with tempfile.TemporaryDirectory() as d:
            e=live.frozen.Engine(Path(d)/'account.sqlite',0,'fixture',self.clock,True)
            try:
                e.protocol=P
                e.transaction('FIXTURE_ENTRY',self.clock.t,lambda:e.fill(row(self.clock.t),-.005,self.clock.t,'ENTRY'))
                before=(e.s['q'],e.s['fills'],e.s['cash'])
                self.delegate.error=failure(sqlite3.SQLITE_CANTOPEN)
                self.clock.t+=2*NS;self.assertIsNone(self.reader.poll())
                proof=dict(data_sha256='NO_NEW_BOOK_NO_FILL',observed_visible=dict(utc_ns=self.clock.t))
                e.tick([],proof)
                self.assertEqual((e.s['q'],e.s['fills'],e.s['cash']),before)
                self.assertEqual(e.s['pending']['kind'],'EXIT')
                self.assertEqual(e.s['pending']['reason'],'STALE_DATA')
            finally:e.close()

    def test_existing_position_accounting_and_risk_survive_restart(self):
        with tempfile.TemporaryDirectory() as d:
            p=Path(d)/'account.sqlite'
            e=live.frozen.Engine(p,0,'same-activation',self.clock,True);e.protocol=P
            e.transaction('FIXTURE_ENTRY',self.clock.t,lambda:e.fill(row(self.clock.t),-.005,self.clock.t,'ENTRY'))
            fields=('q','cash','fills','fees','funding','realized','entry','entry_at','daily','high_water','drawdown_halt','integrity_halt')
            before={k:copy.deepcopy(e.s[k]) for k in fields};e.close()
            e=live.frozen.Engine(p,0,'same-activation',self.clock,False)
            try:self.assertEqual({k:e.s[k] for k in fields},before)
            finally:e.close()

class ContinuationTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.root=Path(self.tmp.name);state=self.root/'state';state.mkdir(mode=0o750)
        self.prior=dict(db=str(state/'account.sqlite'),activation=str(self.root/'activation.json'),continuation=str(self.root/'continuation.json'),source='frozen-source',book='frozen-book')
        self.activation=dict(protocol_sha256='frozen-protocol',original_identity=True)
        self.write(self.root/'prior.json',self.prior);self.write(self.root/'activation.json',self.activation);self.write(self.root/'continuation.json',{'legacy':'unchanged'})
        self.config=dict(predecessor_configuration=str(self.root/'prior.json'),io_continuation=str(self.root/'io.json'),source_io_log=str(state/'source-read-events.jsonl'))
        self.approval=dict(scope=live.SCOPE,account=live.frozen.ACCOUNT,predecessor_configuration_sha256=self.sha('prior.json'),activation_sha256=self.sha('activation.json'),legacy_continuation_sha256=self.sha('continuation.json'),protocol_sha256='frozen-protocol',strategy_unchanged=True,state_reset_allowed=False,real_orders=False,exchange_credentials=False,operational_grants=False,operator_acceptance_reference='fixture only',runtime_files={n:hashlib.sha256((LAB/n).read_bytes()).hexdigest() for n in live.FILES})
    def sha(self,name):return hashlib.sha256((self.root/name).read_bytes()).hexdigest()
    def write(self,path,value):path.write_text(json.dumps(value));path.chmod(0o440)
    def check(self):
        self.write(self.root/'io.json',self.approval)
        with patch.object(live.frozen,'authority',return_value=(b'',self.activation)) as check:
            result=live.authorized(self.config);check.assert_called_once_with(self.prior);return result
    def test_original_config_and_authority_are_preserved(self):
        self.assertEqual(self.check(),self.prior)
    def test_unapproved_hash_scope_or_privilege_change_denied(self):
        original=copy.deepcopy(self.approval)
        for k,v in [('scope','wrong'),('account','another'),('predecessor_configuration_sha256','0'*64),('activation_sha256','0'*64),('legacy_continuation_sha256','0'*64),('protocol_sha256','wrong'),('strategy_unchanged',False),('state_reset_allowed',True),('real_orders',True),('exchange_credentials',True),('operational_grants',True),('operator_acceptance_reference',''),('runtime_files',{})]:
            self.approval=copy.deepcopy(original);self.approval[k]=v
            with self.subTest(k=k),self.assertRaises(ValueError):self.check()
        self.approval=original;self.approval['runtime_files']['btc_intraday_source_io.py']='0'*64
        with self.assertRaisesRegex(ValueError,'pin_mismatch'):self.check()
    def test_changed_original_config_is_not_accepted(self):
        changed=dict(self.prior,source='another-source');self.write(self.root/'prior.json',changed)
        with self.assertRaises(ValueError):self.check()
    def test_extra_fields_and_diagnostic_escape_refused(self):
        self.config['db']='another-account'
        with self.assertRaises(ValueError):self.check()
        del self.config['db'];self.config['source_io_log']=str(self.root/'public.json')
        with self.assertRaises(ValueError):self.check()
    def test_root_file_custody_and_symlink_refused(self):
        self.write(self.root/'io.json',self.approval);p=self.root/'prior.json';p.chmod(0o666)
        with self.assertRaises(ValueError):live.authorized(self.config)
        p.chmod(0o440);p.rename(self.root/'preserved');p.symlink_to(self.root/'preserved')
        with self.assertRaises(OSError):live.authorized(self.config)
    def test_reader_adapter_scope_is_restored_on_failure(self):
        old=live.frozen.receipt.BookReader
        def execute(config):
            self.assertEqual(config,self.prior)
            wrapped=live.frozen.receipt.BookReader(self.root/'placeholder',Clock())
            self.assertIsInstance(wrapped,io.RecoveringBookReader);self.assertIs(wrapped.factory,old)
            raise RuntimeError('fixture terminal storage fault')
        with patch.object(live,'authorized',return_value=self.prior),patch.object(live.frozen,'run',side_effect=execute):
            with self.assertRaises(RuntimeError):live.run(self.config)
        self.assertIs(live.frozen.receipt.BookReader,old)
    def test_diagnostic_log_is_append_only_private(self):
        p=Path(self.config['source_io_log']);io.append_event(p,{'event':'WAIT'});io.append_event(p,{'event':'RECOVER'})
        self.assertEqual([json.loads(x)['event'] for x in p.read_text().splitlines()],['WAIT','RECOVER'])
        p.chmod(0o644)
        with self.assertRaises(ValueError):io.append_event(p,{'event':'refused'})
        self.assertEqual(len(p.read_text().splitlines()),2)

if __name__=='__main__':unittest.main()
