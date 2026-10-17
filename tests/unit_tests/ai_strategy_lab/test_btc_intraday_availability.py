"""Internal synthetic failure tests; no exchange admissibility or independent QA claim."""
from contextlib import closing
import hashlib
import json
import os
from pathlib import Path
import sqlite3
import subprocess
import sys
import tempfile
import unittest

ROOT=Path(__file__).resolve().parents[3]
LAB=ROOT/'octobot/ai_strategy_lab';sys.path.insert(0,str(LAB))
import btc_intraday_availability as m


class FakeClock:
    def __init__(self):
        self.t=10*m.NS;self.monotonic=10*m.NS;self.boot='boot1'
        self.clock=m.Clock(lambda:self.t,lambda:self.monotonic,lambda:self.boot)
    def sample(self):return self.clock.sample()
    def advance(self,n):self.t+=n;self.monotonic+=n


def book_row(now):
    row=dict(session_id='s',sequence=1,exchange_ts_ns=now-10_000_000,
             received_ts_ns=now,payload_sha256='a'*64)
    for side in ('bid','ask'):
        for i in range(1,6):
            row[f'{side}_price_{i}']=100-i if side=='bid' else 100+i
            row[f'{side}_size_{i}']=1.
    return row


def source_db(path):
    db=sqlite3.connect(path)
    db.execute('PRAGMA journal_mode=WAL')
    row=book_row(m.NS)
    columns=','.join('"'+k+'" '+('TEXT' if isinstance(v,str) else 'REAL' if isinstance(v,float) else 'INTEGER') for k,v in row.items())
    db.execute('CREATE TABLE book_events(id INTEGER PRIMARY KEY,'+columns+')');db.commit()
    return db


def insert(db,row):
    db.execute('INSERT INTO book_events('+','.join(row)+') VALUES('+','.join('?' for _ in row)+')',list(row.values()))


class WitnessTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.path=Path(self.temp.name)/'w'
        self.clock=FakeClock();self.w=m.Witness(self.path,self.clock)
    def tearDown(self):
        self.w.close();self.temp.cleanup()
    def observe(self,bootstrap=False):
        start=self.clock.sample();self.clock.advance(1000);end=self.clock.sample()
        return self.w.observe('book','one',dict(row=1),start,end,end['utc_ns']-1,bootstrap)
    def test_three_distinct_phases_and_real_readback(self):
        data,ack=self.observe();v=self.w.available_now(data,self.clock.t)
        self.assertEqual(v['observed_visible']['utc_ns'],self.clock.t)
        events=[m.strict(r[0]) for r in self.w.db.execute('SELECT body FROM events ORDER BY seq')]
        self.assertEqual([v['kind'] for v in events],['run','data','confirmation','acknowledgement'])
        self.assertEqual(events[1]['payload']['input_sha256'],m.digest({'row':1}))
        self.assertIn('data_commit_returned',events[2]['payload'])
        self.assertIn('confirmation_commit_returned',events[3]['payload'])
        self.assertNotIn('own_commit_completed',events[3])
    def test_deadline_equality_allowed_later_read_not_retroactive(self):
        data,_=self.observe();deadline=self.clock.t
        self.w.available_now(data,deadline)
        self.clock.advance(1)
        with self.assertRaisesRegex(m.Denied,'deadline_missed'):self.w.available_now(data,deadline)
    def test_bootstrap_cannot_be_used_prospectively(self):
        data,_=self.observe(True)
        with self.assertRaisesRegex(m.Denied,'bootstrap'):self.w.available_now(data,self.clock.t)
    def test_replay_denied_without_second_observation(self):
        self.observe();count=self.w.seq
        with self.assertRaisesRegex(m.Denied,'duplicate_observation'):self.observe()
        self.assertEqual(self.w.seq,count)
    def test_unknown_input_denied(self):
        with self.assertRaisesRegex(m.Denied,'data_absent'):self.w.available_now('b'*64,self.clock.t)
    def test_two_writers_rejected_by_actual_lock(self):
        with self.assertRaisesRegex(m.Denied,'writer_already_running'):m.Witness(self.path,self.clock)
    def test_append_only_triggers(self):
        with self.assertRaisesRegex(sqlite3.IntegrityError,'append_only'):self.w.db.execute('DELETE FROM events')
    def test_source_future_receipt_denied(self):
        t=self.clock.sample()
        with self.assertRaisesRegex(m.Denied,'source_time'):self.w.observe('book','one',{},t,t,self.clock.t+1)
    def test_read_before_current_run_denied(self):
        t=self.clock.sample();old={**t,'monotonic_ns':t['monotonic_ns']-1}
        with self.assertRaisesRegex(m.Denied,'this_run'):self.w.observe('book','one',{},old,t,self.clock.t)
    def test_reversed_read_window_denied(self):
        t=self.clock.sample();future={**t,'utc_ns':t['utc_ns']+1}
        with self.assertRaisesRegex(m.Denied,'source_time'):self.w.observe('book','one',{},future,t,self.clock.t)
    def test_readonly_storage_fault_latches(self):
        self.w.db.execute('PRAGMA query_only=ON')
        with self.assertRaises(sqlite3.OperationalError):self.observe()
        with self.assertRaisesRegex(m.Denied,'storage_fault'):self.w.available_now('b'*64,self.clock.t)
    def test_actual_sqlite_full_preserves_prefix(self):
        self.w.db.execute('PRAGMA max_page_count='+str(self.w.db.execute('PRAGMA page_count').fetchone()[0]))
        before=self.w.seq;t=self.clock.sample()
        with self.assertRaisesRegex(sqlite3.OperationalError,'full'):
            self.w.observe('book','full',{'large':'x'*200000},t,t,self.clock.t)
        self.assertEqual(self.w.seq,before)
        self.assertTrue(self.w.failed)
        self.assertEqual(self.w.db.execute('PRAGMA integrity_check').fetchone()[0],'ok')
    def test_partial_confirmation_never_eligible(self):
        def fail(phase):
            if phase=='confirmation':raise OSError('injected after confirmation commit')
        self.w.after_commit=fail
        with self.assertRaises(OSError):self.observe()
        self.assertEqual(self.w.db.execute('SELECT COUNT(*) FROM events').fetchone()[0],3)
        with self.assertRaisesRegex(m.Denied,'storage_fault'):self.w.available_now('b'*64,self.clock.t)


class RecoveryTests(unittest.TestCase):
    def test_real_process_exit_at_every_commit_boundary(self):
        for phase in ('data','confirmation','acknowledgement'):
            with self.subTest(phase=phase),tempfile.TemporaryDirectory() as temp:
                path=Path(temp)/'w'
                code="""
import sys,os
sys.path.insert(0,sys.argv[1]);import btc_intraday_availability as m
w=m.Witness(sys.argv[2],after_commit=lambda p:os._exit(73) if p==sys.argv[3] else None)
t=w.clock.sample();w.observe('book','once',{'test':1},t,t,t['utc_ns'])
"""
                result=subprocess.run([sys.executable,'-c',code,str(LAB),str(path),phase],capture_output=True)
                self.assertEqual(result.returncode,73,result.stderr.decode())
                with closing(m.ro(path/'availability.sqlite')) as db:
                    self.assertEqual(db.execute('PRAGMA integrity_check').fetchone()[0],'ok')
                    count=db.execute('SELECT COUNT(*) FROM events').fetchone()[0]
                    data=db.execute('SELECT sha FROM events WHERE seq=2').fetchone()[0]
                self.assertEqual(count,{'data':2,'confirmation':3,'acknowledgement':4}[phase])
                w=m.Witness(path)
                try:
                    with self.assertRaisesRegex(m.Denied,'old_epoch'):w.available_now(data,time_now())
                    # New run only; no completion of old incomplete commits.
                    self.assertEqual(w.db.execute('SELECT COUNT(*) FROM events').fetchone()[0],count+1)
                    t=w.clock.sample()
                    with self.assertRaisesRegex(m.Denied,'duplicate'):w.observe('book','once',{},t,t,t['utc_ns'])
                finally:w.close()
    def test_tamper_rejected_on_restart(self):
        with tempfile.TemporaryDirectory() as temp:
            path=Path(temp)/'w';w=m.Witness(path);w.close()
            db=sqlite3.connect(path/'availability.sqlite');db.execute('DROP TRIGGER no_update')
            db.execute("UPDATE events SET body=replace(body,'Old unacknowledged','Tampered')");db.commit();db.close()
            with self.assertRaisesRegex(m.Denied,'chain_corrupted'):m.Witness(path)
    def test_symlink_destination_denied(self):
        with tempfile.TemporaryDirectory() as temp:
            p=Path(temp);(p/'link').symlink_to(p/'target')
            with self.assertRaisesRegex(m.Denied,'symlink'):m.Witness(p/'link')


def time_now():
    import time
    return time.time_ns()+m.NS


class ClockTests(unittest.TestCase):
    def test_regression_boot_change_and_jump_latch(self):
        for fault in ('wall','mono','boot','jump'):
            with self.subTest(fault=fault):
                c=FakeClock();c.sample()
                if fault=='wall':c.t-=1
                if fault=='mono':c.monotonic-=1
                if fault=='boot':c.boot='boot2'
                if fault=='jump':c.t+=2*m.NS
                with self.assertRaisesRegex(m.Denied,'discontinuity'):c.sample()
                c.t=100*m.NS;c.monotonic=100*m.NS;c.boot='boot1'
                with self.assertRaisesRegex(m.Denied,'latched'):c.sample()


class BookReaderTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.path=Path(self.temp.name)/'book.sqlite'
        self.db=source_db(self.path);self.clock=FakeClock()
    def tearDown(self):self.db.close();self.temp.cleanup()
    def test_uncommitted_invisible_and_no_initial_backfill(self):
        insert(self.db,book_row(m.NS));self.db.commit()
        reader=m.BookReader(self.path,self.clock)
        self.assertIsNone(reader.poll())
        insert(self.db,book_row(2*m.NS))
        self.assertIsNone(reader.poll())
        self.db.commit();payload,_,_=reader.poll()
        self.assertEqual(len(payload['rows']),1);self.assertEqual(payload['rows'][0]['id'],2)
        self.assertEqual(reader.cursor,1,'cursor only advanced by caller after persistence')
    def test_source_connection_really_readonly(self):
        with closing(m.ro(self.path)) as db:
            with self.assertRaises(sqlite3.OperationalError):db.execute('DELETE FROM book_events')
    def test_backlog_not_silently_skipped(self):
        reader=m.BookReader(self.path,self.clock)
        for i in range(3):insert(self.db,book_row((i+1)*m.NS))
        self.db.commit()
        with self.assertRaisesRegex(m.Denied,'backlog'):reader.poll(limit=2)
        self.assertEqual(reader.cursor,0)
    def test_replaced_file_or_regressed_cursor_denies(self):
        insert(self.db,book_row(m.NS));self.db.commit();reader=m.BookReader(self.path,self.clock)
        self.db.execute('DELETE FROM book_events');self.db.commit()
        with self.assertRaisesRegex(m.Denied,'cursor_regression'):reader.poll()
        reader.cursor=0;reader.identity=(-1,-1)
        with self.assertRaisesRegex(m.Denied,'file_replaced'):reader.poll()
    def test_future_and_crossed_book_denied(self):
        for fault in ('future','crossed','nonfinite'):
            with self.subTest(fault=fault):
                self.db.execute('DELETE FROM book_events');self.db.commit();reader=m.BookReader(self.path,self.clock)
                row=book_row(m.NS)
                if fault=='future':row['received_ts_ns']=20*m.NS
                if fault=='crossed':row['bid_price_1']=1000.
                if fault=='nonfinite':row['ask_price_5']=float('inf')
                insert(self.db,row);self.db.commit()
                with self.assertRaises(m.Denied):reader.poll()


class ContractTests(unittest.TestCase):
    def test_protocol_v2_still_exact_and_no_frequency_limits(self):
        raw=(ROOT/'docs/research-protocols/btc-intraday-m1-l5-paper-candidate-v2.json').read_bytes()
        self.assertEqual(hashlib.sha256(raw).hexdigest(),m.PROTOCOL_SHA)
        p=json.loads(raw)
        self.assertIsNone(p['risk_policy']['max_entries_per_utc_day'])
        self.assertEqual(p['timing']['cooldown_seconds_after_flat'],0)
        self.assertEqual(p['research_contract']['real_min_notional'],'UNKNOWN')
        self.assertEqual(p['signal']['commit_deadline_seconds'],30)
        self.assertEqual(p['market_data']['max_quote_age_ms'],1000)


if __name__=='__main__':unittest.main()
