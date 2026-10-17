"""Synthetic causality/source integrity examples; no real trading evidence."""
import copy
import importlib.util
import json
from pathlib import Path
import sqlite3
import sys
import tempfile
import unittest

ROOT=Path(__file__).resolve().parents[3];LAB=ROOT/'octobot/ai_strategy_lab';sys.path.insert(0,str(LAB))
spec=importlib.util.spec_from_file_location('source_qual',LAB/'btc_intraday_source_qualification.py');m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m)
P=json.loads((ROOT/'docs/research-protocols/btc-intraday-m1-l5-paper-candidate-v2.json').read_text());T=m.timestamp('2026-10-16T00:00:00+00:00')

def receipt(url,data,received='2026-10-16T00:00:00+00:00'):
 raw=m.canonical(dict(code='200000',data=data));r=dict(kind='LIVE_PUBLIC_HTTPS_CAPTURE',status=200,url=url,started_at='2026-10-15T23:59:59+00:00',received_at=received,raw_sha256=m.hashlib.sha256(raw).hexdigest(),raw_hex=raw.hex());r['capture_id']=m.digest(r);return r

def mark_receipt():
 return receipt('https://api-futures.kucoin.com/api/v1/mark-price/XBTUSDTM/current',dict(symbol='XBTUSDTM',granularity=1000,timePoint=T//1000000-1000,value=100.))

def market():
 return dict(record_hash='a'*64,observed_at_start='2026-10-15T23:59:58+00:00',observed_at_end='2026-10-16T00:00:01+00:00',quotes={'BTCUSDT':dict(mark_price=100.,mark_timestamp='2026-10-15T23:59:59+00:00')})

def grid_db():
 c=sqlite3.connect(':memory:');c.execute('CREATE TABLE marks(capture TEXT,package TEXT,received INTEGER,available INTEGER,symbol TEXT,exchange INTEGER,price REAL)');return c

class ReceiptTests(unittest.TestCase):
 def test_raw_and_receipt_identity(self):
  r=mark_receipt();v,t,_=m.validate_receipt(r,T);self.assertEqual(v['value'],100);self.assertEqual(t,T)
  r['status']=500
  with self.assertRaisesRegex(ValueError,'capture_id'):m.validate_receipt(r,T)
 def test_raw_hash_not_receipt_hash_only(self):
  r=mark_receipt();r['raw_sha256']='0'*64;r['capture_id']=m.digest({k:v for k,v in r.items() if k!='capture_id'})
  with self.assertRaisesRegex(ValueError,'raw_hash'):m.validate_receipt(r,T)
 def test_future_receive_not_backdated(self):
  with self.assertRaisesRegex(ValueError,'capture_time'):m.validate_receipt(mark_receipt(),T-1)
 def test_invalid_source_endpoint(self):
  r=mark_receipt();r['url']=r['url'].replace('api-futures.kucoin.com','evil.example');r['capture_id']=m.digest({k:v for k,v in r.items() if k!='capture_id'})
  with self.assertRaisesRegex(ValueError,'source_endpoint'):m.validate_receipt(r,T)
 def test_nonfinite_duplicates_timezone(self):
  for raw in [b'{"v":NaN}',b'{"v":1e999}',b'{"v":1,"v":2}']:
   with self.assertRaises(ValueError):m.strict(raw)
  with self.assertRaisesRegex(ValueError,'timezone'):m.timestamp('2026-10-16T00:00:00')
 def test_mark_package_availability_not_just_receive(self):
  kind,row=m.normalize(mark_receipt(),market(),P,T+m.NS);self.assertEqual(kind,'mark');self.assertEqual(row[2],T);self.assertEqual(row[3],T+m.NS)
 def test_mark_future_exchange_or_wrong_derived_value(self):
  r=mark_receipt();pkg=market();pkg['quotes']['BTCUSDT']['mark_price']=101.
  with self.assertRaisesRegex(ValueError,'derived_mark'):m.normalize(r,pkg,P,T+m.NS)
  raw=json.loads(bytes.fromhex(r['raw_hex']));raw['data']['timePoint']=T//1000000+1;r=receipt(r['url'],raw['data'])
  with self.assertRaisesRegex(ValueError,'mark_value_or_time'):m.normalize(r,market(),P,T+m.NS)
 def test_current_funding_is_not_settled(self):
  r=receipt('https://api-futures.kucoin.com/api/v1/funding-rate/XBTUSDTM/current',{})
  self.assertFalse(m.selected(r['url'],P['signal']['universe']))
  with self.assertRaisesRegex(ValueError,'unrecognized'):m.normalize(r,market(),P,T+m.NS)
 def test_remaining_funding_time_not_reinterpreted_as_date(self):
  data=[dict(symbol='XBTUSDTM',settleCurrency='USDT',isInverse=False,status='Open',nextFundingRateTime=120000,nextFundingRateDateTime=None,currentFundingRateGranularity=28800000)]
  r=receipt('https://api-futures.kucoin.com/api/v1/contracts/active',data)
  kind,row=m.normalize(r,market(),P,T+m.NS);self.assertEqual(kind,'calendar');self.assertEqual(row[-1],0);self.assertIsNone(row[4])
 def test_existing_qualification_never_overwritten(self):
  with tempfile.TemporaryDirectory() as temp:
   (Path(temp)/'completion.json').write_text('{}')
   with self.assertRaisesRegex(ValueError,'already_used'):m.qualify(Path(temp),P,{},None,None,None)
 def test_null_settled_response_stays_missing(self):
  r=receipt('https://api-futures.kucoin.com/api/v1/contract/funding-rates?symbol=XBTUSDTM&from=1&to=2',None)
  self.assertEqual(m.normalize(r,market(),P,T+m.NS)[0],'rates_missing')

class GridTests(unittest.TestCase):
 def test_received_and_complete_package_cutoff(self):
  c=grid_db();small=copy.deepcopy(P);small['signal']['universe']=['BTCUSDT'];c.execute('INSERT INTO marks VALUES(?,?,?,?,?,?,?)',('a','p',T-10*m.NS,T+m.NS,'BTCUSDT',T-11*m.NS,100.))
  self.assertFalse(m.grid_points(c,small,T,T+m.NS)[0]['point_valid'])
  self.assertTrue(m.grid_points(c,small,T+2*m.NS,T+3*m.NS)[0]['point_valid']);c.close()
 def test_stale_mark_never_carried(self):
  c=grid_db();small=copy.deepcopy(P);small['signal']['universe']=['BTCUSDT'];c.execute('INSERT INTO marks VALUES(?,?,?,?,?,?,?)',('a','p',T-121*m.NS,T-120*m.NS,'BTCUSDT',T-122*m.NS,100.))
  self.assertFalse(m.grid_points(c,small,T,T+m.NS)[0]['point_valid']);c.close()
 def points(self):
  return [dict(slot_ns=T+i*300*m.NS,point_valid=True,missing=[],inputs={s:dict(price=(100. if i<277 else 98.),capture=str(i),available_ns=T+i*300*m.NS,exchange_ns=T+i*300*m.NS,received_ns=T+i*300*m.NS) for s in P['signal']['universe']}) for i in range(289)]
 def test_full_warmup_and_signal_not_profit(self):
  pts=self.points();r=m.m1_windows(pts,P);self.assertFalse(r[-2]['m1_valid']);self.assertTrue(r[-1]['m1_valid']);self.assertTrue(r[-1]['signal']);self.assertNotIn('pnl',r[-1])
 def test_missing_or_gapped_row_invalidates_whole_window(self):
  pts=self.points();pts[10]['point_valid']=False;self.assertFalse(m.m1_windows(pts,P)[-1]['m1_valid'])
  pts=self.points();pts[10]['slot_ns']+=1;self.assertFalse(m.m1_windows(pts,P)[-1]['m1_valid'])
 def test_future_append_does_not_change_past_identity(self):
  pts=self.points();r=m.m1_windows(pts,P)[-1];future=copy.deepcopy(pts[-1]);future['slot_ns']+=300*m.NS;future['inputs']['BTCUSDT']['price']=999999
  self.assertEqual(m.m1_windows(pts+[future],P)[-2],r)

class FundingTests(unittest.TestCase):
 def db(self):
  c=grid_db();c.executescript('CREATE TABLE calendars(available INTEGER,received INTEGER,next_ns INTEGER,interval_ms INTEGER,capture TEXT,valid INTEGER);CREATE TABLE rates(available INTEGER,received INTEGER,rate REAL,capture TEXT,tau INTEGER);')
  c.execute('INSERT INTO calendars VALUES(?,?,?,?,?,?)',(T-100*m.NS,T-100*m.NS,T,28800000,'c',1));return c
 def test_future_rate_does_not_close_pending(self):
  c=self.db();c.execute('INSERT INTO rates VALUES(?,?,?,?,?)',(T+61*m.NS,T+60*m.NS,.001,'r',T));_,r=m.funding_events(c,P,T,T+60*m.NS);self.assertEqual(r[0]['status'],'PENDING_FINAL_RATE');c.close()
 def test_future_mark_or_book_mid_not_substituted(self):
  c=self.db();c.execute('INSERT INTO rates VALUES(?,?,?,?,?)',(T+5*m.NS,T+4*m.NS,.001,'r',T));c.execute('INSERT INTO marks VALUES(?,?,?,?,?,?,?)',('m','p',T+m.NS,T+2*m.NS,'BTCUSDT',T-m.NS,100.));_,r=m.funding_events(c,P,T,T+60*m.NS);self.assertEqual(r[0]['status'],'MISSING_FRESH_PRECEDING_MARK');c.close()
 def test_signed_settled_rate_and_mark_qualified_without_pnl(self):
  c=self.db();c.execute('INSERT INTO rates VALUES(?,?,?,?,?)',(T+5*m.NS,T+4*m.NS,-.001,'r',T));c.execute('INSERT INTO marks VALUES(?,?,?,?,?,?,?)',('m','p',T-20*m.NS,T-19*m.NS,'BTCUSDT',T-21*m.NS,100.));_,r=m.funding_events(c,P,T,T+60*m.NS);self.assertEqual(r[0]['status'],'QUALIFIED_RESEARCH_ESTIMATE_INPUTS');self.assertEqual(r[0]['mark_age_seconds'],21);self.assertNotIn('cashflow',r[0]);c.close()
 def test_received_mark_before_event_can_be_reconciled_from_later_package(self):
  c=self.db();c.execute('INSERT INTO rates VALUES(?,?,?,?,?)',(T+5*m.NS,T+4*m.NS,.001,'r',T));c.execute('INSERT INTO marks VALUES(?,?,?,?,?,?,?)',('m','p',T-m.NS,T+2*m.NS,'BTCUSDT',T-2*m.NS,100.));_,r=m.funding_events(c,P,T,T+60*m.NS);self.assertEqual(r[0]['status'],'QUALIFIED_RESEARCH_ESTIMATE_INPUTS');self.assertFalse(r[0]['package_complete_before_event']);c.close()
 def test_conflicting_final_rate_denied(self):
  c=self.db();c.executemany('INSERT INTO rates VALUES(?,?,?,?,?)',[(T+5*m.NS,T+4*m.NS,.001,'r',T),(T+10*m.NS,T+9*m.NS,.002,'s',T)]);_,r=m.funding_events(c,P,T,T+60*m.NS);self.assertEqual(r[0]['status'],'CONFLICTING_FINAL_RATE');c.close()

if __name__=='__main__':unittest.main()
