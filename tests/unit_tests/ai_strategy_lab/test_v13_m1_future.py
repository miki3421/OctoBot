"""Prospective causal, persistence and failure boundaries, no live study activation."""
import copy,datetime as dt,hashlib,importlib.util,json,sqlite3,tempfile,unittest
from pathlib import Path
ROOT=Path(__file__).resolve().parents[3]
spec=importlib.util.spec_from_file_location('future',ROOT/'octobot/ai_strategy_lab/v13_m1_future.py');f=importlib.util.module_from_spec(spec);spec.loader.exec_module(f)
spec=importlib.util.spec_from_file_location('assessment',ROOT/'octobot/ai_strategy_lab/v13_m1_future_evaluate.py');assessment=importlib.util.module_from_spec(spec);spec.loader.exec_module(assessment)
P=json.loads((ROOT/'docs/research-protocols/v13-m1-short-prospective-v1.json').read_text())
NOW=dt.datetime(2026,10,15,12,tzinfo=dt.timezone.utc).timestamp()
def rows(slot):return [dict(time=slot-86400+i*300,prices={s:100-i*.1 for s in P['universe']},source_times={s:slot-86400+i*300-10 for s in P['universe']}) for i in range(289)]
class FutureTests(unittest.TestCase):
 def setUp(self):
  self.temp=tempfile.TemporaryDirectory();self.path=Path(self.temp.name)/'test.sqlite';self.j=f.Journal.create(self.path,P,NOW,fixture=True)
 def tearDown(self):self.j.close();self.temp.cleanup()
 def active(self):return self.j.start(NOW)['t0']
 def test_preparation_does_not_start_observation(self):
  self.assertEqual(self.j.summary()['state'],'PREPARED_NOT_STARTED')
  with self.assertRaisesRegex(ValueError,'prepared_not_started'):self.j.record(int(NOW)//300*300,[],NOW)
 def test_future_boundary_and_start_receipt_survive_restart(self):
  receipt=self.j.start(NOW);self.assertEqual(receipt['t0'],NOW+43200)
  self.j.close();self.j=f.Journal(self.path,P)
  self.assertEqual(self.j.start(NOW+60),receipt)
 def test_historical_and_future_slots_refused(self):
  t=self.active()
  with self.assertRaises(ValueError):self.j.record(t-300,rows(t-300),t)
  with self.assertRaises(ValueError):self.j.record(t,rows(t),t-1)
 def test_valid_signal_and_restart_do_not_duplicate_or_change_it(self):
  t=self.active();r=self.j.record(t,rows(t),t+1);self.assertEqual(r['status'],'SCHEDULED')
  self.assertEqual(r['episode']['entry_slot'],t+300)
  self.assertEqual(f.digest(r['consumed_rows']),r['input_hash'])
  self.j.close();self.j=f.Journal(self.path,P)
  self.assertEqual(self.j.record(t,rows(t),t+2),r)
  changed=rows(t);changed[-1]['prices']['BTCUSDT']=1e6
  with self.assertRaisesRegex(ValueError,'slot_conflict'):self.j.record(t,changed,t+3)
  self.assertEqual(self.j.db.execute('SELECT count(*) FROM episodes').fetchone()[0],1)
 def test_late_positive_signal_is_missed_forever(self):
  t=self.active();r=self.j.record(t,rows(t),t+121)
  self.assertEqual(r['status'],'MISSED');self.assertIsNone(r['episode'])
  self.assertEqual(self.j.record(t,rows(t),t+122)['status'],'MISSED')
 def test_gap_slots_are_recorded_and_cannot_be_backfilled(self):
  t=self.active();self.j.record(t+900,rows(t+900),t+901)
  self.assertEqual(self.j.db.execute("SELECT COUNT(*) FROM slots WHERE status='MISSED'").fetchone()[0],3)
  with self.assertRaises(ValueError):self.j.record(t,rows(t),t+902)
 def test_future_prices_and_incomplete_history_cannot_trigger(self):
  t=self.active();v=rows(t);v[-1]['source_times']['BTCUSDT']=t+1
  self.assertEqual(self.j.record(t,v,t+1)['status'],'INSUFFICIENT_INPUT')
  self.assertEqual(self.j.record(t+300,rows(t+300)[1:],t+301)['status'],'INSUFFICIENT_INPUT')
 def test_cooldown_persists_and_failed_entry_is_not_retried(self):
  t=self.active();self.j.record(t,rows(t),t+1)
  self.assertEqual(self.j.record(t+600,rows(t+600),t+601)['status'],'COOLDOWN')
  self.assertEqual(self.j.db.execute('SELECT status FROM episodes').fetchone()[0],'ENTRY_MISSED')
  self.j.close();self.j=f.Journal(self.path,P)
  self.assertEqual(self.j.record(t+900,rows(t+900),t+901)['status'],'COOLDOWN')
 def test_captures_require_delayed_book_and_ordered_phases(self):
  t=self.active();e=self.j.record(t,rows(t),t+1)['episode']
  p=dict(snapshot_sha256='a'*64,market_hash='b'*64,market_observed_at=t+200,captured_at=t+301)
  self.j.capture(e['id'],'entry',p,t+301)
  x=dict(p,market_observed_at=e['exit_slot']-10,captured_at=e['exit_slot']+1)
  self.j.capture(e['id'],'exit',x,e['exit_slot']+1)
  self.assertEqual(self.j.db.execute('SELECT status FROM episodes').fetchone()[0],'CAPTURE_COMPLETE_AWAITING_OFFLINE_REPLAY')
 def test_past_or_future_capture_cannot_be_accepted(self):
  t=self.active();e=self.j.record(t,rows(t),t+1)['episode']
  p=dict(snapshot_sha256='a'*64,market_hash='b'*64,market_observed_at=t+50,captured_at=t+301)
  with self.assertRaisesRegex(ValueError,'causality'):self.j.capture(e['id'],'entry',p,t+301)
  p['market_observed_at']=t+301
  with self.assertRaisesRegex(ValueError,'causality'):self.j.capture(e['id'],'entry',p,t+301)
  with self.assertRaisesRegex(ValueError,'window_missed'):self.j.capture(e['id'],'entry',p,t+421)
 def test_no_free_form_profit_or_ledger_write_api(self):
  t=self.active();e=self.j.record(t,rows(t),t+1)['episode'];p=dict(snapshot_sha256='a'*64,market_hash='b'*64,market_observed_at=t+200,captured_at=t+301,pnl=9999)
  with self.assertRaisesRegex(ValueError,'capture_schema'):self.j.capture(e['id'],'entry',p,t+301)
 def test_storage_error_rolls_back_slot_episode_and_cooldown(self):
  t=self.active();self.j.db.execute('PRAGMA query_only=ON')
  with self.assertRaises(sqlite3.OperationalError):self.j.record(t,rows(t),t+1)
  self.assertEqual(self.j.db.execute('SELECT COUNT(*) FROM slots').fetchone()[0],0)
  self.assertIsNone(self.j.meta('cooldown_until'))
  self.j.db.execute('PRAGMA query_only=OFF');self.assertEqual(self.j.record(t,rows(t),t+2)['status'],'SCHEDULED')
 def test_append_only_slot_and_protocol_drift(self):
  t=self.active();self.j.record(t,rows(t),t+1)
  with self.assertRaises(sqlite3.IntegrityError):self.j.db.execute('DELETE FROM slots')
  self.j.db.rollback();p=copy.deepcopy(P);p['created_at']='changed'
  with self.assertRaisesRegex(ValueError,'identity_changed'):f.Journal(self.path,p)
 def test_clock_regression_denies_changes(self):
  t=self.active();self.j.record(t,rows(t),t+10)
  with self.assertRaisesRegex(ValueError,'clock_regression'):self.j.record(t+300,rows(t+300),t+9)
 def test_seal_has_fixed_horizon_and_fixtures_never_become_real_evidence(self):
  t=self.active();end=t+90*86400
  with self.assertRaises(ValueError):self.j.seal(end-1)
  self.j.seal(end);self.assertEqual(self.j.db.execute('SELECT COUNT(*) FROM slots').fetchone()[0],90*288)
  self.assertEqual(self.j.summary()['state'],'HORIZON_ENDED_AWAITING_OFFLINE_REPLAY')
  with self.assertRaisesRegex(ValueError,'fixture'):assessment.assess(self.j,Path(self.temp.name),P,end)
 def test_readonly_window_excludes_future_and_preserves_source_bytes(self):
  t=self.active();source=Path(self.temp.name)/'source.sqlite';db=sqlite3.connect(source)
  db.executescript('CREATE TABLE state(id INTEGER,payload TEXT);CREATE TABLE marks(bar TEXT,symbol TEXT,price REAL)')
  db.execute('INSERT INTO state VALUES(1,?)',(json.dumps(dict(positions={s:{} for s in P['universe']})),))
  for r in rows(t)+[dict(time=t+300,prices={s:1e9 for s in P['universe']})]:
   for s,p in r['prices'].items():db.execute('INSERT INTO marks VALUES(?,?,?)',(dt.datetime.fromtimestamp(r['time'],dt.timezone.utc).isoformat(),s,p))
  db.commit();db.close();before=hashlib.sha256(source.read_bytes()).hexdigest()
  window=f.read_window(source,t,P['universe']);self.assertLess(window[-1]['prices']['BTCUSDT'],100)
  self.assertEqual(hashlib.sha256(source.read_bytes()).hexdigest(),before)
  self.assertEqual(self.j.record(t,window,t+1)['status'],'SCHEDULED')

class FutureReplayTests(unittest.TestCase):
 def bundle(self,path,finish_price):
  start=NOW+43200+290;end=start+21600;captures={}
  for phase,at,mark in [('entry',start,100.),('exit',end,finish_price)]:
   target=path/(phase+'.original.sqlite');db=sqlite3.connect(target)
   db.executescript('CREATE TABLE state(id INTEGER,payload TEXT);CREATE TABLE orders(id INTEGER,bar TEXT,symbol TEXT,quantity REAL,price REAL,fee REAL,status TEXT);CREATE TABLE funding_events(symbol TEXT,timestamp_ms INTEGER,amount REAL);CREATE TABLE marks(bar TEXT,symbol TEXT,price REAL,PRIMARY KEY(bar,symbol))')
   db.execute('INSERT INTO state VALUES(1,?)',(json.dumps(dict(initial_equity=10000.,positions={s:{} for s in P['universe']})),))
   for i,s in enumerate(P['universe']):db.execute('INSERT INTO orders VALUES(?,?,?,?,?,?,?)',(i,dt.datetime.fromtimestamp(start-86400,dt.timezone.utc).isoformat(),s,1.,80.,.048,'filled'))
   for t in range(int(start),int(at)+1,300):
    value=100.+(finish_price-100.)*(t-start)/21600
    for s in P['universe']:db.execute('INSERT INTO marks VALUES(?,?,?)',(dt.datetime.fromtimestamp(t,dt.timezone.utc).isoformat(),s,value))
   db.commit();db.close()
   quote=dict(mark_price=mark,quantity_step=1.,price_tick=.01,fee_rate=.0006,min_quantity=None,min_notional=None,bids=[dict(price=mark,base_quantity=100.)],asks=[dict(price=mark,base_quantity=100.)],funding_interval_ms=28800000,funding=[dict(timestamp_ms=int((start-290)*1000),rate=.0001)])
   book=dict(scope='RESEARCH_SIMULATION_ONLY',observed_at_end=dt.datetime.fromtimestamp(at,dt.timezone.utc).isoformat(),quotes={s:copy.deepcopy(quote) for s in P['universe']});book['record_hash']=assessment.digest(book)
   (path/(phase+'.market.json')).write_text(json.dumps(book));captures[phase]=dict(snapshot_sha256=assessment.sha(target),market_hash=book['record_hash'],market_observed_at=at,captured_at=at+10)
  return captures
 def test_future_paired_replay_charges_cash_and_short_returns(self):
  with tempfile.TemporaryDirectory() as d:
   path=Path(d);captures=self.bundle(path,90.);result=assessment.episode(path,captures,P['universe'])
   self.assertEqual(result['status'],'COMPLETE');self.assertGreater(result['arms']['SHORT']['pnl'],0)
   self.assertLess(result['arms']['CASH']['pnl'],0);self.assertLess(result['baseline_pnl'],result['arms']['CASH']['pnl'])
   self.assertGreater(result['arms']['SHORT']['turnover'],result['arms']['CASH']['turnover'])
 def test_rebound_punishes_short_more_than_cash(self):
  with tempfile.TemporaryDirectory() as d:
   path=Path(d);captures=self.bundle(path,110.);result=assessment.episode(path,captures,P['universe'])
   self.assertLess(result['delta'],0);self.assertGreater(result['baseline_pnl'],0)
 def test_snapshot_tampering_is_rejected(self):
  with tempfile.TemporaryDirectory() as d:
   path=Path(d);captures=self.bundle(path,90.);p=path/'exit.original.sqlite';p.write_bytes(p.read_bytes()+b'changed')
   with self.assertRaisesRegex(ValueError,'snapshot_hash'):assessment.episode(path,captures,P['universe'])

if __name__=='__main__':unittest.main()
