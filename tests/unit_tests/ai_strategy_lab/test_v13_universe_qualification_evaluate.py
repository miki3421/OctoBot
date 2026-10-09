"""Full-window synthetic replay and adversarial qualification checks, no market data."""
import gzip
import hashlib
import json
from pathlib import Path
import shutil
import socket
import sqlite3
import tempfile
import unittest
from unittest.mock import patch

import v13_universe_qualification as q
import v13_universe_qualification_evaluate as e
import test_v13_universe_qualification as fixtures

START = fixtures.START


class EvaluationTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.folder=tempfile.TemporaryDirectory()
        cls.base=Path(cls.folder.name)/'base';cls.base.mkdir()
        cls.plan=q.load_plan(fixtures.REPO)
        c=q.Collector(cls.base,cls.plan,START,'SYNTHETIC-ONLY',None,lambda:START-1)
        c.initialize()
        f=fixtures.QualificationTest();f.plan=cls.plan;f.calls=[]
        rows=[]
        for key,kind,symbol,slot,deadline,url in c.jobs:
            received=slot+(0.25 if kind.endswith('metadata') else 2)
            started=slot+(0 if kind.endswith('metadata') else 1)
            f.now=received
            status,raw=f.fetch(url,4*1024*1024)
            job=dict(kind=kind,slot=slot,deadline=deadline)
            metrics=c.validate(job,raw,received,{'multiplier':1})
            rows.append((started,received,status,q.sha(raw),gzip.compress(raw,mtime=0),q.canonical(metrics).decode(),key))
        with c.connection() as db:
            db.executemany("UPDATE jobs SET state='valid',started=?,received=?,status=?,raw_hash=?,raw_gzip=?,metrics=? WHERE id=?",rows)
            db.execute("UPDATE control SET stopped='window_complete',last_clock=?",(START+14*q.DAY,))
        cls.baseline_hash=hashlib.sha256((cls.base/'qualification.sqlite').read_bytes()).hexdigest()

    @classmethod
    def tearDownClass(cls):
        cls.folder.cleanup()

    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.db=Path(self.tmp.name)/'qualification.sqlite'
        shutil.copyfile(self.base/'qualification.sqlite',self.db)
        guard=patch.object(socket.socket,'connect',side_effect=AssertionError('NETWORK_FORBIDDEN'))
        guard.start();self.addCleanup(guard.stop)

    def evaluate(self,now=START+14*q.DAY,binding='SYNTHETIC-ONLY'):
        return e.evaluate(self.db,self.plan,START,binding,now)

    def change(self,sql,params=()):
        with sqlite3.connect(self.db) as db:db.execute(sql,params)

    def test_complete_window_qualifies_without_orders_and_is_readonly(self):
        r=self.evaluate()
        self.assertEqual(r['status'],'QUALIFIED')
        self.assertEqual(r['attempts'],39816)
        self.assertEqual(r['common_book_coverage'],1)
        self.assertEqual(r['maximum_common_gap_seconds'],0)
        self.assertEqual(len(r['symbols']),29)
        self.assertFalse(r['orders_authorized']);self.assertFalse(r['automatic_promotion'])
        self.assertIsNone(r['min_quantity']);self.assertIsNone(r['min_notional'])
        self.assertEqual(hashlib.sha256(self.db.read_bytes()).hexdigest(),self.baseline_hash)
        self.assertFalse((self.db.parent/'qualification.sqlite-journal').exists())

    def test_cutoff_blocks_early_verdict(self):
        r=self.evaluate(START+14*q.DAY-1)
        self.assertEqual(r['status'],'IN_PROGRESS');self.assertNotIn('symbols',r)

    def test_missing_one_day_bar_fails_whole_cohort(self):
        self.change("UPDATE jobs SET state='missing',started=NULL,received=NULL,status=NULL,raw_hash=NULL,raw_gzip=NULL,metrics=NULL,error='window_missed' WHERE id='0:daily:0:AAVEUSDT'")
        r=self.evaluate()
        self.assertEqual(r['status'],'NOT_QUALIFIED')
        self.assertFalse(r['symbols']['AAVEUSDT']['passed'])
        self.assertTrue(r['symbols']['ADAUSDT']['passed'])
        self.assertEqual(len(r['symbols']),29)

    def test_nine_missing_common_slots_fail_gap_despite_coverage(self):
        self.change("UPDATE jobs SET state='missing',started=NULL,received=NULL,status=NULL,raw_hash=NULL,raw_gzip=NULL,metrics=NULL,error='window_missed' WHERE kind='books' AND slot>=? AND slot<?",(START,START+9*900))
        r=self.evaluate()
        self.assertGreater(r['common_book_coverage'],.95)
        self.assertEqual(r['maximum_common_gap_seconds'],8100)
        self.assertEqual(r['status'],'NOT_QUALIFIED')

    def test_terminal_stop_never_qualifies(self):
        self.change("UPDATE control SET stopped='http_rate_limit'")
        self.assertEqual(self.evaluate()['status'],'INCONCLUSIVE')

    def test_forged_uncertain_reservation_is_rejected(self):
        self.change("UPDATE jobs SET state='uncertain',reserved=10 WHERE id='0:books:0:AAVEUSDT'")
        with self.assertRaisesRegex(ValueError,'uncertain_reservation'):self.evaluate()

    def test_metrics_tamper_detected(self):
        self.change("UPDATE jobs SET metrics='{}' WHERE id='0:books:0:AAVEUSDT'")
        with self.assertRaisesRegex(ValueError,'derived_metrics'):self.evaluate()

    def test_raw_tamper_detected(self):
        self.change("UPDATE jobs SET raw_hash='broken' WHERE id='0:books:0:AAVEUSDT'")
        with self.assertRaisesRegex(ValueError,'receipt_hash'):self.evaluate()

    def test_schedule_tamper_detected(self):
        self.change("DELETE FROM jobs WHERE id='0:books:0:AAVEUSDT'")
        with self.assertRaisesRegex(ValueError,'schedule_tampered'):self.evaluate()

    def test_wrong_binding_and_future_archive_clock(self):
        with self.assertRaisesRegex(ValueError,'binding'):self.evaluate(binding='other')
        self.change('UPDATE control SET last_clock=?',(START+15*q.DAY,))
        with self.assertRaisesRegex(ValueError,'future_archive'):self.evaluate()

    def test_late_success_receipt_rejected(self):
        self.change("UPDATE jobs SET received=deadline+1 WHERE id='0:books:0:AAVEUSDT'")
        with self.assertRaisesRegex(ValueError,'invalid_success'):self.evaluate()

    def test_metadata_must_precede_samples(self):
        self.change("UPDATE jobs SET started=slot WHERE id='0:books:0:AAVEUSDT'")
        with self.assertRaisesRegex(ValueError,'noncausal_metadata'):self.evaluate()

    def test_gzip_bomb_bounded(self):
        bomb=gzip.compress(b'x'*(65536+1))
        self.change("UPDATE jobs SET raw_gzip=? WHERE id='0:books:0:AAVEUSDT'",(bomb,))
        with self.assertRaisesRegex(ValueError,'receipt_hash_or_size'):self.evaluate()

    def test_symlink_archive_rejected(self):
        link=self.db.parent/'link.sqlite';link.symlink_to(self.db)
        with self.assertRaises(ValueError):e.evaluate(link,self.plan,START,'SYNTHETIC-ONLY',START+14*q.DAY)


class ThresholdTest(unittest.TestCase):
    def setUp(self):
        self.symbols=['A','B'];self.metrics={'spread_bps':20,'bid_depth_usdt':3150,'ask_depth_usdt':3150}
        self.books={s:{i:dict(self.metrics) for i in range(1344)} for s in self.symbols}
        self.days={s:set(range(14)) for s in self.symbols}

    def result(self):
        return e.summarize(self.symbols,self.books,self.days,self.days,set(range(14)))

    def test_exact_inclusive_thresholds(self):
        self.assertEqual(self.result()['status'],'QUALIFIED')

    def test_p95_nearest_rank_and_excess_spread(self):
        self.assertEqual(e.percentile95([1]*19+[25]),1)
        self.assertEqual(e.percentile95([1]*18+[25]*2),25)
        for i in range(68):self.books['A'][i]['spread_bps']=20.0001
        self.assertEqual(self.result()['status'],'NOT_QUALIFIED')

    def test_depth_denominator_valid_samples_and_both_sides(self):
        for i in range(68):self.books['A'][i]['ask_depth_usdt']=3149.999
        r=self.result()
        self.assertLess(r['symbols']['A']['both_sides_depth_pass_fraction'],.95)
        self.assertEqual(r['status'],'NOT_QUALIFIED')

    def test_missing_coverage_cannot_be_hidden_by_good_remaining_samples(self):
        for i in range(0,1344,10):del self.books['A'][i]
        r=self.result()
        self.assertEqual(r['symbols']['A']['both_sides_depth_pass_fraction'],1)
        self.assertFalse(r['symbols']['A']['passed'])

    def test_common_coverage_not_average_symbol_coverage(self):
        for i in range(60):del self.books['A'][i*10]
        for i in range(60):del self.books['B'][i*10+1]
        r=self.result()
        self.assertTrue(all(v['book_coverage']>=.95 for v in r['symbols'].values()))
        self.assertLess(r['common_book_coverage'],.95)
        self.assertEqual(r['status'],'NOT_QUALIFIED')

    def test_gap_edges_and_exact_two_hours(self):
        self.assertEqual(e.longest_missing([False]*8+[True]),7200)
        self.assertEqual(e.longest_missing([True]+[False]*9),8100)
        self.assertEqual(e.longest_missing([False]*1344),14*q.DAY)


if __name__=='__main__':unittest.main()
