"""Synthetic account trajectories and failures, not proof of trading edge or KuCoin rules."""
import copy
from contextlib import closing
import json
import os
from pathlib import Path
import sqlite3
import subprocess
import sys
import tempfile
import unittest

ROOT=Path(__file__).resolve().parents[3];LAB=ROOT/'octobot/ai_strategy_lab';sys.path.insert(0,str(LAB))
import btc_intraday_paper as m
P=json.loads((ROOT/'docs/research-protocols/btc-intraday-m1-l5-paper-candidate-v2.json').read_text())
NS=m.NS

class Clock:
    def __init__(self):self.t=10*NS
    def sample(self):return dict(utc_ns=self.t,monotonic_ns=self.t,boot_id='fixture')


def row(at,price=100000.,identity=None,size=100.):
    r=dict(id=identity or at,session_id='session',received_ts_ns=at,exchange_ts_ns=at-10*m.MS)
    for side in ('bid','ask'):
        for i in range(1,6):
            r[f'{side}_price_{i}']=price-i if side=='bid' else price+i
            r[f'{side}_size_{i}']=size
    return r


def books(until,price=100000.):
    return [row(t,price) for t in range(until-12*NS,until+1,100*m.MS)]


class AccountTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.path=Path(self.temp.name)/'account.sqlite';self.clock=Clock()
        self.e=m.Engine(self.path,0,'fixture-bundle',self.clock,True);self.e.protocol=P
    def tearDown(self):self.e.close();self.temp.cleanup()
    def act(self,now,mutate,kind='TEST'):
        self.clock.t=now;return self.e.transaction(kind,now,mutate)
    def tick(self,now,rows):
        self.clock.t=now;self.e.tick(rows,dict(data_sha256='fixture-receipt',observed_visible=dict(utc_ns=now)))
    def calendar(self,now,tau=None):
        tau=tau or now+10000*NS
        self.e.db.execute('INSERT INTO calendars VALUES(?,?,?,?,?,?)',(str(now),now,now,tau,28800000,1));self.e.db.commit()
    def pending(self,slot=300*NS,q=.005):
        due=slot+300*NS+500*m.MS
        def f():self.e.s['pending']=dict(kind='ENTRY',commit_seq=self.e.seq+1,slot=slot,due=due,deadline=due+1000*m.MS,quantity=q,id='intent')
        self.act(slot+2*NS,f);return due
    def open(self,at=100*NS,q=.005):
        self.act(at-NS,lambda:self.e.risk(at-NS,100000.))
        self.act(at,lambda:self.e.fill(row(at),-q,at,'ENTRY'))
    def funding_source(self,tau,rate=.001):
        self.e.db.execute('INSERT INTO calendars VALUES(?,?,?,?,?,?)',('cal',tau-100*NS,tau-100*NS,tau,28800000,1))
        self.e.db.execute('INSERT OR IGNORE INTO announced VALUES(?)',(tau,))
        self.e.db.execute('INSERT INTO rates VALUES(?,?,?,?)',('rate',tau,tau+NS,rate))
        self.e.db.execute('INSERT INTO marks VALUES(?,?,?,?,?,?)',('mark','BTCUSDT',tau-NS,tau-2*NS,tau+2*NS,100000.));self.e.db.commit()
    def test_seed_is_flat_cash_and_no_missing_db_reset(self):
        self.assertEqual(self.e.equity(),10000);self.assertEqual(self.e.s['q'],0)
        with self.assertRaisesRegex(ValueError,'exact_continuation'):m.Engine(self.path.parent/'missing.sqlite',0,'x',self.clock)
    def test_duplicate_initialization_refused(self):
        with self.assertRaisesRegex(ValueError,'exact_continuation'):m.Engine(self.path,0,'fixture-bundle',self.clock,True)
    def test_prospective_entry_after_latency_and_one_position_only(self):
        due=self.pending();self.calendar(due)
        self.tick(due-1,books(due-1));self.assertEqual(self.e.s['q'],0)
        self.tick(due+100*m.MS,[row(due+100*m.MS)])
        self.assertEqual(self.e.s['q'],-.005);self.assertEqual(self.e.s['fills'],1)
        cash=self.e.s['cash'];self.tick(due+200*m.MS,[row(due+200*m.MS)])
        self.assertEqual(self.e.s['fills'],1);self.assertEqual(self.e.s['cash'],cash)
    def test_late_arrival_never_reconstructed(self):
        due=self.pending();self.calendar(due)
        self.tick(due+1001*m.MS,books(due+1001*m.MS))
        self.assertEqual(self.e.s['q'],0);self.assertIsNone(self.e.s['pending'])
        self.assertIn('MISSED',self.e.s['reason'])
    def test_bad_freshness_or_missing_window_vetoes_entry(self):
        due=self.pending();self.calendar(due)
        self.tick(due+100*m.MS,[row(due+100*m.MS)])
        self.assertEqual(self.e.s['q'],0);self.assertIsNone(self.e.s['pending'])
    def test_risk_recheck_reduces_intent_quantity_never_increases(self):
        due=self.pending(q=.01);self.calendar(due)
        self.tick(due+100*m.MS,books(due+100*m.MS,price=200000.))
        self.assertLess(abs(self.e.s['q']),.01)
        price=self.e.db.execute('SELECT price FROM fills').fetchone()[0]
        self.assertLessEqual(abs(self.e.s['q'])*price,.1*self.e.equity()+1e-8)
    def test_no_partial_entry_on_insufficient_depth(self):
        due=self.pending(q=.005);self.calendar(due)
        rows=books(due+100*m.MS)
        for r in rows:
            for i in range(1,6):r[f'bid_size_{i}']=.1
        self.tick(due+100*m.MS,rows)
        self.assertEqual(self.e.s['q'],0)
    def test_exit_latches_and_uses_later_price_not_trigger(self):
        self.open();self.tick(101*NS,[row(101*NS,97000.)])
        self.assertEqual(self.e.s['pending']['reason'],'TAKE_PROFIT');self.assertEqual(self.e.s['q'],-.005)
        self.tick(101*NS+600*m.MS,[row(101*NS+600*m.MS,98000.)])
        self.assertEqual(self.e.s['q'],0);fill=self.e.db.execute('SELECT * FROM fills ORDER BY at_ns DESC LIMIT 1').fetchone()
        self.assertGreater(fill['price'],98000);self.assertGreater(fill['realized'],0)
    def test_stop_latches_even_if_price_recovers(self):
        self.open();self.tick(101*NS,[row(101*NS,102000.)])
        self.assertEqual(self.e.s['pending']['reason'],'STOP_LOSS')
        self.tick(101*NS+600*m.MS,[row(101*NS+600*m.MS,99000.)])
        self.assertEqual(self.e.s['q'],0)
    def test_missing_quote_requests_exit_without_fabricating_fill(self):
        self.open();self.tick(110*NS,[])
        self.assertEqual(self.e.s['pending']['kind'],'EXIT');self.assertEqual(self.e.s['q'],-.005)
        self.assertEqual(self.e.s['fills'],1)
    def test_partial_protective_exit_and_remainder(self):
        self.open(q=.009)
        self.tick(101*NS,[row(101*NS,102000.)])
        self.tick(102*NS,[row(102*NS,102000.,size=1)])
        self.assertAlmostEqual(self.e.s['q'],-.004);self.assertEqual(self.e.s['pending']['kind'],'EXIT')
        self.tick(103*NS,[row(103*NS,102000.,size=100)])
        self.assertEqual(self.e.s['q'],0)
    def test_funding_pending_late_signed_and_reconciled_once(self):
        tau=200*NS;self.open();self.funding_source(tau,rate=-.001)
        self.act(tau+10*NS,lambda:self.e.reconcile(tau+10*NS));self.assertFalse(self.e.accounting_complete())
        before=self.e.s['cash'];self.act(tau+61*NS,lambda:self.e.reconcile(tau+61*NS))
        self.assertAlmostEqual(self.e.s['cash']-before,-.5);self.assertTrue(self.e.accounting_complete())
        self.act(tau+62*NS,lambda:self.e.reconcile(tau+62*NS));self.assertAlmostEqual(self.e.s['cash']-before,-.5)
    def test_funding_conflict_and_late_mark_stay_pending(self):
        tau=200*NS;self.open();self.funding_source(tau)
        self.e.db.execute('UPDATE marks SET received=?',(tau+1,));self.e.db.commit()
        self.act(tau+61*NS,lambda:self.e.reconcile(tau+61*NS));self.assertFalse(self.e.accounting_complete())
        self.e.db.execute('UPDATE marks SET received=?',(tau-1,));self.e.db.execute('INSERT INTO rates VALUES(?,?,?,?)',('other',tau,tau+NS,-.001));self.e.db.commit()
        self.act(tau+62*NS,lambda:self.e.reconcile(tau+62*NS));self.assertFalse(self.e.accounting_complete())
    def test_protective_exit_before_settlement_keeps_worst_boundary_debit(self):
        tau=200*NS;self.open();self.funding_source(tau,rate=-.001)
        self.act(tau-10*NS,lambda:self.e.fill(row(tau-10*NS),.005,tau-10*NS,'EXIT'))
        self.assertEqual(self.e.s['q'],0)
        self.act(tau+61*NS,lambda:self.e.reconcile(tau+61*NS))
        self.assertAlmostEqual(self.e.s['funding'],-.5)
    def test_protective_exit_after_settlement_suppresses_boundary_credit(self):
        tau=200*NS;self.open();self.funding_source(tau,rate=.001)
        self.act(tau+NS,lambda:self.e.reconcile(tau+NS))
        self.act(tau+10*NS,lambda:self.e.fill(row(tau+10*NS),.005,tau+10*NS,'EXIT'))
        self.act(tau+61*NS,lambda:self.e.reconcile(tau+61*NS))
        self.assertAlmostEqual(self.e.s['funding'],0.)
    def test_daily_and_drawdown_halts_persist(self):
        self.act(100*NS,lambda:self.e.risk(100*NS,100000.))
        self.act(101*NS,lambda:self.e.s.update(cash=9700.))
        self.assertEqual(self.e.risk(101*NS,100000.),'DAILY_LOSS_HALT')
        self.e.s['cash']=10000.
        self.assertEqual(self.e.risk(102*NS,100000.),'DAILY_LOSS_HALT')
        self.e.s['cash']=8900.;self.assertEqual(self.e.risk(103*NS,100000.),'DRAWDOWN_HALT')
        self.act(104*NS,lambda:None)
        self.e.close();self.e=m.Engine(self.path,0,'fixture-bundle',self.clock);self.e.protocol=P
        self.assertTrue(self.e.s['drawdown_halt'])
    def test_old_slot_is_immutable_and_missed_slots_cannot_backfill(self):
        self.act(400*NS,lambda:self.e.signal_slot(300*NS,400*NS,'proof'))
        before=self.e.db.execute('SELECT * FROM slots').fetchall()
        self.act(401*NS,lambda:self.e.signal_slot(300*NS,301*NS,'other'))
        self.assertEqual([tuple(r) for r in before],[tuple(r) for r in self.e.db.execute('SELECT * FROM slots')])
        self.assertEqual(before[0]['status'],'MISSED_DEADLINE')
    def test_state_tamper_detected_on_restart(self):
        self.e.db.execute("UPDATE state SET payload=replace(payload,'10000.0','20000.0')");self.e.db.commit();self.e.close()
        with self.assertRaisesRegex(ValueError,'state_chain'):m.Engine(self.path,0,'fixture-bundle',self.clock)
        # Close invalid test connection/lock via GC then restore a different clean test account.
        self.path=Path(self.temp.name)/'clean.sqlite';self.e=m.Engine(self.path,0,'fixture-bundle',self.clock,True)
    def test_storage_failure_rolls_back_position_and_latches(self):
        self.e.db.execute('PRAGMA query_only=ON')
        with self.assertRaises(sqlite3.OperationalError):self.open()
        self.assertEqual(self.e.s['q'],0);self.assertTrue(self.e.failed)
        with self.assertRaisesRegex(ValueError,'storage_fault'):self.open()
    def test_close_never_inverts_or_increases(self):
        self.open()
        with self.assertRaisesRegex(ValueError,'reversed'):self.act(101*NS,lambda:self.e.fill(row(101*NS),.009,101*NS,'EXIT'))
        self.assertEqual(self.e.s['q'],-.005)
    def test_time_exit_without_full_entry_warmup(self):
        self.open();at=100*NS+21600*NS
        self.tick(at,[row(at)])
        self.assertEqual(self.e.s['pending']['reason'],'TIME_EXIT')
        self.tick(at+600*m.MS,[row(at+600*m.MS)])
        self.assertEqual(self.e.s['q'],0)

    def test_complete_m1_window_schedules_only_future_entry(self):
        slot=400*300*NS
        for i in range(288):
            at=slot-(288-i)*300*NS
            price=100000. if i<277 else 98000.
            payload={symbol:{'price':price} for symbol in P['signal']['universe']}
            self.e.db.execute('INSERT INTO grid VALUES(?,?,?)',(at,1,m.canonical(payload).decode()))
        for symbol in P['signal']['universe']:
            self.e.db.execute('INSERT INTO marks VALUES(?,?,?,?,?,?)',(symbol,symbol,slot-20*NS,slot-21*NS,slot-19*NS,98000.))
        self.e.db.commit();self.calendar(slot)
        self.e.books.extend(books(slot,98000.))
        self.act(slot+2*NS,lambda:self.e.signal_slot(slot,slot+2*NS,'receipt'))
        self.assertEqual(self.e.s['pending']['kind'],'ENTRY')
        self.assertEqual(self.e.s['pending']['due'],slot+300*NS+500*m.MS)
        self.assertEqual(self.e.s['q'],0.)
        self.assertEqual(self.e.db.execute('SELECT status FROM slots').fetchone()[0],'ENTRY_SCHEDULED')
    def test_market_received_before_slot_but_only_visible_after_is_not_backfilled(self):
        slot=400*300*NS
        for symbol in P['signal']['universe']:
            self.e.db.execute('INSERT INTO marks VALUES(?,?,?,?,?,?)',(symbol,symbol,slot-20*NS,slot-21*NS,slot+NS,98000.))
        self.e.db.commit()
        self.act(slot+2*NS,lambda:self.e.signal_slot(slot,slot+2*NS,'receipt'))
        self.assertEqual(self.e.db.execute('SELECT valid FROM grid').fetchone()[0],0)
        self.assertIsNone(self.e.s['pending'])
    def test_funding_crossing_utc_does_not_reset_halt_or_baseline(self):
        self.open();midnight=86400*NS
        self.e.books.extend(books(midnight-100*m.MS))
        self.act(midnight+NS,lambda:self.e.risk(midnight+NS,100000.))
        self.assertTrue(self.e.s['daily']['known'])
        base=self.e.s['daily']['base'];self.e.s['daily']['halt']=True
        self.act(midnight+2*NS,lambda:self.e.risk(midnight+2*NS,100000.))
        self.assertEqual(base,self.e.s['daily']['base']);self.assertTrue(self.e.s['daily']['halt'])

    def test_admin_close_one_use_identity_expiry_and_no_increase(self):
        import btc_intraday_admin as admin
        self.open();now=101*NS
        cmd=admin.request(self.e.s,now)
        self.clock.t=now;self.assertTrue(self.e.administrative_close(cmd,now))
        self.assertFalse(self.e.administrative_close(cmd,now))
        self.assertEqual(self.e.s['pending']['reason'],'ADMIN_CLOSE')
        self.tick(now+600*m.MS,[row(now+600*m.MS)])
        self.assertEqual(self.e.s['q'],0)
    def test_admin_rejects_wrong_generation_expiry_and_account(self):
        import btc_intraday_admin as admin
        self.open();now=101*NS;command=admin.request(self.e.s,now)
        for field,value in [('generation',99),('expires_ns',now-1),('account','v13-paper-v2'),('maximum_quantity_btc',.001)]:
            cmd={**command,field:value}
            with self.assertRaisesRegex(ValueError,'administrative'):self.e.administrative_close(cmd,now)
        self.assertIsNone(self.e.s['pending']);self.assertEqual(self.e.s['q'],-.005)
    def test_admin_storage_failure_does_not_consume_or_fill(self):
        import btc_intraday_admin as admin
        self.open();now=101*NS;command=admin.request(self.e.s,now);self.e.db.execute('PRAGMA query_only=ON')
        with self.assertRaises(sqlite3.OperationalError):self.e.administrative_close(command,now)
        self.assertEqual(self.e.s['q'],-.005)
        self.assertEqual(self.e.db.execute('SELECT COUNT(*) FROM admin_claims').fetchone()[0],0)


class CrashTests(unittest.TestCase):
    def test_process_crash_after_position_commit_preserves_position_and_halts(self):
        with tempfile.TemporaryDirectory() as temp:
            path=Path(temp)/'account.sqlite'
            code="""
import sys,os
sys.path.insert(0,sys.argv[1]);import btc_intraday_paper as m
w=m.Engine(sys.argv[2],0,'bundle',initialize=True)
r={'id':1,'received_ts_ns':100,'exchange_ts_ns':90,'session_id':'s'}
for side in ('bid','ask'):
 for i in range(1,6):r[f'{side}_price_{i}']=100000-i if side=='bid' else 100000+i;r[f'{side}_size_{i}']=100
w.after_commit=lambda:os._exit(74)
w.transaction('ENTRY',w.clock.sample()['utc_ns'],lambda:w.fill(r,-.005,100,'ENTRY'))
"""
            result=subprocess.run([sys.executable,'-c',code,str(LAB),str(path)],capture_output=True)
            self.assertEqual(result.returncode,74,result.stderr.decode())
            w=m.Engine(path,0,'bundle')
            try:
                self.assertEqual(w.s['q'],-.005);self.assertEqual(w.s['fills'],1)
                self.assertTrue(w.s['integrity_halt'])
                self.assertEqual(w.db.execute('PRAGMA integrity_check').fetchone()[0],'ok')
            finally:w.close()


class MathTests(unittest.TestCase):
    def test_size_uses_all_caps_and_floor_not_minimum_bump(self):
        self.assertEqual(m.quantity(10000,100000),.01)
        self.assertEqual(m.quantity(10000,1000000),.001)
        self.assertEqual(m.quantity(1,100000),0)
    def test_completed_seconds_no_session_bridge(self):
        rs=books(100*NS);self.assertTrue(m.frame(rs,100*NS))
        rs[-1]['session_id']='new';self.assertFalse(m.frame(rs,100*NS))
        self.assertFalse(m.frame([r for r in books(100*NS) if not 95*NS<=r['received_ts_ns']<96*NS],100*NS))
    def test_stress_is_adverse_and_depth_not_extrapolated(self):
        r=row(100*NS)
        base=m.execution(r,-.005);stress=m.execution(r,-.005,True)
        self.assertLess(stress[1],base[1]);self.assertGreater(stress[2],base[2])
        self.assertIsNone(m.execution(row(100*NS,size=.1),-.005))
    def test_utc_funding_mark_strict_before_and_calendar_not_inferred(self):
        self.assertEqual(P['funding']['preceding_mark_max_age_seconds'],60)
        self.assertIsNone(P['risk_policy']['max_entries_per_utc_day'])


if __name__=='__main__':unittest.main()
