"""Causal and arithmetic contracts on synthetic fixtures, not exchange evidence."""
import copy
import importlib.util
import json
import math
from pathlib import Path
import sqlite3
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[3]
LAB = ROOT/'octobot/ai_strategy_lab'
sys.path.insert(0, str(LAB))
spec = importlib.util.spec_from_file_location('causal_costs', LAB/'scalping_causal_costs.py')
m = importlib.util.module_from_spec(spec); spec.loader.exec_module(m)
RULES = json.loads((ROOT/'docs/research-protocols/scalping-causal-costs-v1.json').read_text())
T = 1_790_000_100*m.NS


def db():
    c = sqlite3.connect(':memory:')
    fields = m.COLUMNS.split(',')
    c.execute('CREATE TABLE book_events('+','.join(x+(' TEXT' if x in ('session_id','payload_sha256') else ' REAL' if '_price_' in x or '_size_' in x or x in ('latency_ms','mid_price') else ' INTEGER') for x in fields)+')')
    c.execute('CREATE INDEX br ON book_events(received_ts_ns)')
    c.execute('CREATE TABLE trade_events(id INTEGER, session_id TEXT, received_ts_ns INTEGER, exchange_ts_ns INTEGER, side TEXT, size REAL, payload_sha256 TEXT)')
    return c


def add(c, ident, milliseconds, session='a', capture=100, mid=100):
    received = T+int(milliseconds*m.MS)
    row = [ident, session, ident, received-int(capture*m.MS), received, capture]
    for side in ('bid','ask'):
        for i in range(1,6):
            row += [mid+(-i if side=='bid' else i)*.01, 10.]
    row += [mid, format(ident, '064x')]
    c.execute('INSERT INTO book_events VALUES('+','.join('?' for _ in row)+')', row)


class AdapterTests(unittest.TestCase):
    def setUp(self):
        self.c = db(); self.s = sqlite3.connect(':memory:'); self.rules = copy.deepcopy(RULES)
    def tearDown(self):
        self.c.close(); self.s.close()
    def adapter(self):
        self.s.execute('DROP TABLE IF EXISTS segments')
        m.create_segments(self.c, self.s, self.rules)
        return m.CausalAdapter(self.c, self.s, self.rules)
    def test_received_clock_not_exchange_clock(self):
        add(self.c,1,100)
        a=self.adapter();self.assertIsNone(a.quote(T)[0]);self.assertEqual(a.quote(T+100*m.MS)[0]['id'],1)
    def test_no_future_lookahead(self):
        add(self.c,1,100);add(self.c,2,1100)
        a=self.adapter();past=a.frame(T+1500*m.MS,1)
        add(self.c,3,2500,mid=99999);a=self.adapter()
        self.assertEqual(past,a.frame(T+1500*m.MS,1))
        self.assertEqual(a.quote(T+1000*m.MS)[0]['id'],1)
    def test_future_trade_does_not_change_frame(self):
        add(self.c,1,200);add(self.c,2,900)
        self.c.execute('INSERT INTO trade_events VALUES(1,?,?,?,?,?,?)',('a',T+950*m.MS,T+850*m.MS,'buy',3.,'a'*64))
        a=self.adapter();past=a.frame(T+1000*m.MS,1)
        self.assertEqual(past['seconds'][0]['trade_count'],1)
        add(self.c,3,1100);a=self.adapter()
        self.assertEqual(past,a.frame(T+1000*m.MS,1))
    def test_partial_second_never_used(self):
        add(self.c,1,900);add(self.c,2,1100,mid=200)
        frame=self.adapter().frame(T+1500*m.MS,1)
        self.assertEqual([x['second'] for x in frame['seconds']],[T//m.NS])
        self.assertEqual(frame['seconds'][0]['last_book']['id'],1)
    def test_stale_capture_and_source(self):
        add(self.c,1,100);add(self.c,2,2000,capture=1500)
        a=self.adapter();self.assertIsNone(a.quote(T+2000*m.MS)[0])
        self.assertIsNone(a.quote(T+1150*m.MS)[0]) # receive age1050ms
        self.assertEqual(a.quote(T+1050*m.MS)[1],'SOURCE_STALE') # source age1050ms
    def test_gap_reset_and_no_carry(self):
        add(self.c,1,100);add(self.c,2,6100)
        a=self.adapter();self.assertIsNone(a.quote(T+4000*m.MS)[0])
        self.assertNotEqual(a.quote(T+100*m.MS)[0]['segment_id'],a.quote(T+6100*m.MS)[0]['segment_id'])
        self.assertFalse(a.frame(T+6500*m.MS,5)['complete'])
    def test_session_change_even_if_first_new_quote_late(self):
        add(self.c,1,100);add(self.c,2,300,session='b',capture=1200);add(self.c,3,500,session='b')
        a=self.adapter();self.assertEqual(a.quote(T+300*m.MS)[1],'SESSION_RESET')
        self.assertNotEqual(a.quote(T+100*m.MS)[0]['segment_id'],a.quote(T+500*m.MS)[0]['segment_id'])
    def test_missing_second_stays_incomplete(self):
        add(self.c,1,900);add(self.c,2,2900);add(self.c,3,3900)
        a=self.adapter();f=a.frame(T+4000*m.MS,3)
        self.assertFalse(f['complete']);self.assertEqual(len(f['seconds']),2)
    def test_late_trade_not_backdated_into_window(self):
        add(self.c,1,900);add(self.c,2,1100)
        self.c.execute('INSERT INTO trade_events VALUES(1,?,?,?,?,?,?)',('a',T+1200*m.MS,T+800*m.MS,'sell',3.,'b'*64))
        self.assertEqual(self.adapter().frame(T+1500*m.MS,1)['seconds'][0]['trade_count'],0)
    def test_arrival_deadline_no_remote_future_substitution(self):
        add(self.c,1,100);add(self.c,2,2500)
        a=self.adapter();self.assertIsNone(a.quote(T+1000*m.MS,arrival=True)[0])
        self.assertEqual(a.quote(T+2000*m.MS,arrival=True)[0]['id'],2)
    def test_stale_arrival_skipped_not_selected(self):
        add(self.c,1,200,capture=1200);add(self.c,2,500)
        self.assertEqual(self.adapter().quote(T,arrival=True)[0]['id'],2)
    def test_negative_capture_excluded(self):
        add(self.c,1,100,capture=-1)
        self.assertIsNone(self.adapter().quote(T+100*m.MS)[0])
    def test_chronology_regression_fails(self):
        add(self.c,1,200);add(self.c,2,100)
        with self.assertRaisesRegex(ValueError,'raw_chronology'):self.adapter()
    def test_source_and_index_untouched_by_queries(self):
        add(self.c,1,100);a=self.adapter();before=self.c.total_changes;db_before=self.s.total_changes
        a.quote(T+100*m.MS);a.frame(T+100*m.MS,1)
        self.assertEqual((before,db_before),(self.c.total_changes,self.s.total_changes))


class CostTests(unittest.TestCase):
    def book(self,mid=100):
        return dict(mid=mid,asks=[(mid+.01,10),(mid+.02,10)],bids=[(mid-.01,10),(mid-.02,10)])
    def test_vwap_known_depth_both_sides(self):
        self.assertAlmostEqual(m.sweep(self.book(),'BUY',15),(10*100.01+5*100.02)/15)
        self.assertAlmostEqual(m.sweep(self.book(),'SELL',15),(10*99.99+5*99.98)/15)
        self.assertIsNone(m.sweep(self.book(),'BUY',21))
    def test_cost_components_reconcile(self):
        b=self.book();r=m.cost_row(b,b,'BUY',15,RULES)
        self.assertAlmostEqual(r['latency_move_bps'],0)
        self.assertAlmostEqual(r['half_spread_bps'],1)
        self.assertAlmostEqual(r['depth_impact_bps'],1/3)
        self.assertAlmostEqual(r['total_bps'],4/3+7*r['price']/100)
        self.assertAlmostEqual(r['stressed_total_bps'],2*r['total_bps'])
    def test_signed_latency_not_confused_with_depth(self):
        r=m.cost_row(self.book(),self.book(99),'BUY',1,RULES)
        self.assertAlmostEqual(r['latency_move_bps'],-100)
        self.assertGreater(r['half_spread_bps'],0)
        self.assertAlmostEqual(r['execution_shortfall_bps'],(r['price']/100-1)*10000)
    def test_depth_failure_no_partial_fill(self):
        self.assertEqual(m.cost_row(self.book(),self.book(),'SELL',50,RULES),dict(status='INSUFFICIENT_L5_DEPTH'))
    def test_invalid_size_side_depth_and_rules(self):
        for x in (0,-1,math.nan,math.inf):
            with self.assertRaises(ValueError):m.sweep(self.book(),'BUY',x)
        with self.assertRaises(ValueError):m.sweep(self.book(),'OTHER',1)
        b=self.book();b['asks'][0]=(100.,-1.)
        with self.assertRaises(ValueError):m.sweep(b,'BUY',1)
        r=copy.deepcopy(RULES);r['latencies_ms']=[-1]
        with self.assertRaises(ValueError):m.validate_rules(r)
    def test_benchmark_retains_unavailable_and_depth_denominators(self):
        c=db();s=sqlite3.connect(':memory:');add(c,1,0);add(c,2,300)
        m.create_segments(c,s,RULES);a=m.CausalAdapter(c,s,RULES)
        rules=copy.deepcopy(RULES);rules.update(grid_seconds=1,latencies_ms=[0],sizes_native=[1,1000])
        with tempfile.TemporaryDirectory() as tmp:
            r=m.benchmark(a,rules,T,T+3*m.NS,Path(tmp))
            self.assertEqual(r['intents'],4*2*2)
            self.assertEqual(sum(x['expected'] for x in r['groups'].values()),r['intents'])
            self.assertGreater(sum(x['statuses'].get('INSUFFICIENT_L5_DEPTH',0) for x in r['groups'].values()),0)
            self.assertGreater(sum(x['statuses'].get('NO_FRESH_REFERENCE',0) for x in r['groups'].values()),0)
            self.assertEqual(r['min_quantity'],'UNKNOWN');self.assertFalse(r['pnl_or_alpha_computed'])
        c.close();s.close()
    def test_existing_destination_refused(self):
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaisesRegex(ValueError,'new_destination_required'):
                m.run(Path(tmp)/'missing',Path(tmp),Path(tmp)/'missing',Path(tmp))


if __name__=='__main__':unittest.main()
