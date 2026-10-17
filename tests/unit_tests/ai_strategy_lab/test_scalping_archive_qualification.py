"""Synthetic archived-book fixtures, not market or profitability evidence."""
import ast
import importlib.util
import json
from pathlib import Path
import sqlite3
import tempfile
import unittest
from unittest.mock import patch

ROOT=Path(__file__).resolve().parents[3]
spec=importlib.util.spec_from_file_location('qualification',ROOT/'octobot/ai_strategy_lab/scalping_archive_qualification.py');q=importlib.util.module_from_spec(spec);spec.loader.exec_module(q)
T=1790000000

def bucket(t,nb=1,nt=0):return (t,nb,nt,100.,100.,100.,100.,.1,0.,0.,0.,0,nt,99.9995,100.0005,140.)
def schema():
    tree=ast.parse((ROOT/'octobot/ai_strategy_lab/scalping_observer.py').read_text())
    return next(n.value for n in ast.walk(tree) if isinstance(n,ast.Constant) and isinstance(n.value,str) and 'CREATE TABLE IF NOT EXISTS scalping_sessions' in n.value)
def database(path):
    c=sqlite3.connect(path);c.execute('PRAGMA journal_mode=WAL');c.executescript(schema());c.execute("INSERT INTO scalping_sessions VALUES('s',1,'XBTUSDTM','2026-09-21T00:00:00+00:00',NULL,'running',NULL)")
    cols=[r[1] for r in c.execute('PRAGMA table_info(book_events)')];v=dict(session_id='s',sequence=1,exchange_ts_ns=T*10**9-140000000,received_ts_ns=T*10**9,latency_ms=140.,mid_price=100.,microprice=100.,spread_bps=(100.0005/99.9995-1)*10000,imbalance_5=0.,payload_sha256='a'*64)
    for i in range(1,6):v.update({f'bid_price_{i}':99.9995-(i-1)*.01,f'ask_price_{i}':100.0005+(i-1)*.01,f'bid_size_{i}':10.,f'ask_size_{i}':10.})
    keys=list(v);c.execute('INSERT INTO book_events('+','.join(keys)+') VALUES('+','.join('?' for _ in keys)+')',tuple(v.values()));c.execute('INSERT INTO second_buckets VALUES('+','.join('?' for _ in range(16))+')',bucket(T));c.commit();return c

class QualificationTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.root=Path(self.tmp.name);self.capacity_guard=q.ensure_capacity;self.capacity_patch=patch.object(q,'ensure_capacity');self.capacity_patch.start()
    def tearDown(self):self.capacity_patch.stop();self.tmp.cleanup()
    def test_root_filesystem_rejected_by_capacity_guard(self):
        with self.assertRaisesRegex(ValueError,'large_disk_required'):self.capacity_guard(Path('/'),self.root/'unused.sqlite')
    def test_gap_denominators_and_trade_only_seconds(self):
        r=q.bucket_summary([bucket(T),bucket(T+1,0),bucket(T+5)])
        self.assertEqual(r['expected_seconds'],6);self.assertEqual(r['book_seconds'],2);self.assertAlmostEqual(r['coverage'],1/3);self.assertEqual(r['max_missing_book_seconds'],4)
    def test_invalid_book_and_bucket_order(self):
        bad=list(bucket(T));bad[13]=101
        self.assertEqual(q.bucket_summary([bad])['invalid'],1)
        with self.assertRaisesRegex(ValueError,'bucket_order'):q.bucket_summary([bucket(T),bucket(T)])
    def test_empty_is_insufficient(self):self.assertEqual(q.bucket_summary([])['status'],'INSUFFICIENT')
    def test_calendar_denominator_cross_midnight(self):
        midnight=(T//86400+1)*86400;r=q.bucket_summary([bucket(midnight-1),bucket(midnight+1)])
        self.assertEqual(sorted(d['expected_seconds'] for d in r['days'].values()),[1,2]);self.assertEqual(r['coverage'],2/3)
    def test_sql_book_predicate_detects_depth_and_hash(self):
        c=database(self.root/'source.sqlite');pred=q.book_predicate();self.assertEqual(c.execute('SELECT '+pred+' FROM book_events').fetchone()[0],1)
        c.execute('UPDATE book_events SET bid_price_2=bid_price_1');self.assertEqual(c.execute('SELECT '+pred+' FROM book_events').fetchone()[0],0)
        c.rollback();c.execute("UPDATE book_events SET payload_sha256='z'");self.assertEqual(c.execute('SELECT '+pred+' FROM book_events').fetchone()[0],0);c.close()
    def test_backup_pins_snapshot_while_writer_continues(self):
        p=self.root/'source.sqlite';writer=database(p);real_ro=q.ro
        class Proxy:
            def __init__(self,c):self.c=c
            def __getattr__(self,k):return getattr(self.c,k)
            def backup(self,*args,**kwargs):
                writer.execute("INSERT INTO second_buckets VALUES("+','.join('?' for _ in range(16))+')',bucket(T+1,0));writer.commit()
                return self.c.backup(*args,**kwargs)
        with patch.object(q,'ro',side_effect=lambda path,*a:Proxy(real_ro(path,*a))):result=q.snapshot(p,self.root/'snapshot')
        c=q.ro(self.root/'snapshot/snapshot.sqlite',True);self.assertEqual(c.execute('SELECT COUNT(*) FROM second_buckets').fetchone()[0],1);c.close()
        self.assertEqual(writer.execute('SELECT COUNT(*) FROM second_buckets').fetchone()[0],2);writer.close();self.assertFalse(result['live_writes'])
    def test_identity_and_readonly_refusal(self):
        p=self.root/'source.sqlite';c=database(p);c.close();q.snapshot(p,self.root/'snapshot');d=self.root/'snapshot/snapshot.sqlite';m=self.root/'snapshot/snapshot-manifest.json';q.validate_copy(d,m)
        d.chmod(0o640)
        with self.assertRaisesRegex(ValueError,'sealed_offline'):q.validate_copy(d,m)
        d.chmod(0o440);v=json.loads(m.read_text());v['sha256']='0'*64;m.write_text(json.dumps(v))
        with self.assertRaisesRegex(ValueError,'snapshot_identity'):q.validate_copy(d,m)
    def test_sqlite_source_without_WAL_refused(self):
        p=self.root/'plain.sqlite';sqlite3.connect(p).close()
        with self.assertRaisesRegex(ValueError,'requires_WAL'):q.snapshot(p,self.root/'snapshot')
    def test_complete_audit_and_aggregate_mismatch(self):
        p=self.root/'source.sqlite';c=database(p);c.close();q.snapshot(p,self.root/'snapshot');out=self.root/'snapshot';(out/'integrity.json').write_text(json.dumps(dict(result=['ok'])))
        r=q.audit(out/'snapshot.sqlite',out);self.assertTrue(r['technical_rows_valid']);self.assertEqual(r['reconciliation']['book_raw'],1)
        # A mismatched aggregate must be reported, never silently corrected.
        d=out/'snapshot.sqlite';d.chmod(0o640);c=sqlite3.connect(d);c.execute('UPDATE second_buckets SET book_event_count=2');c.commit();c.close();d.chmod(0o440)
        m=json.loads((out/'snapshot-manifest.json').read_text());m['sha256']=q.file_sha(d);m['bytes']=d.stat().st_size;(out/'snapshot-manifest.json').write_text(json.dumps(m));self.assertFalse(q.audit(d,out)['technical_rows_valid'])

if __name__=='__main__':unittest.main()
