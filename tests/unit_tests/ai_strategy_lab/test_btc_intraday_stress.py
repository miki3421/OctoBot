"""Independent stress branch: shared admissions, own timing/positions/risk/exits."""
import json
from pathlib import Path
import sys
import tempfile
import unittest

HERE=Path(__file__).parent;sys.path.insert(0,str(HERE))
import test_btc_intraday_paper as fixture
m=fixture.m;NS=m.NS

class StressTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.clock=fixture.Clock()
        self.e=m.Engine(Path(self.temp.name)/'stress.sqlite',0,'bundle',self.clock,True,stress_mode=True);self.e.protocol=fixture.P
    def tearDown(self):self.e.close();self.temp.cleanup()
    def transaction(self,at,fn):self.clock.t=at;return self.e.transaction('TEST',at,fn)
    def tick(self,at,rows,opps=None):
        self.clock.t=at;self.e.tick(rows,dict(data_sha256='shared-witness',observed_visible=dict(utc_ns=at)),opps or [])
    def opportunity(self,slot=300*NS,quantity=.005):
        return dict(slot_ns=slot,status='ENTRY_SCHEDULED',payload=m.canonical(dict(feature={'btc_return':-.02,'negative':18},admitted_opportunity=dict(kind='ENTRY',slot=slot,quantity=quantity,id='primary-frozen-intent',due=slot+300*NS+500*m.MS,deadline=slot+301*NS+500*m.MS))).decode())
    def prepare(self,quantity=.005):
        slot=300*NS;self.e.books.extend(fixture.books(slot))
        self.transaction(slot+2*NS,lambda:self.e.primary_opportunity(self.opportunity(quantity=quantity),slot+2*NS,'shared'))
        self.e.db.execute('INSERT INTO calendars VALUES(?,?,?,?,?,?)',('c',599*NS,599*NS,10000*NS,28800000,1));self.e.db.commit()
    def open(self):
        self.transaction(99*NS,lambda:self.e.risk(99*NS,100000.))
        self.transaction(100*NS,lambda:self.e.fill(fixture.row(100*NS),-.005,100*NS,'ENTRY'))
    def funding(self,rate):
        tau=200*NS
        self.e.db.execute('INSERT INTO announced VALUES(?)',(tau,))
        self.e.db.execute('INSERT INTO rates VALUES(?,?,?,?)',('r',tau,tau+NS,rate))
        self.e.db.execute('INSERT INTO marks VALUES(?,?,?,?,?,?)',('m','BTCUSDT',tau-NS,tau-2*NS,tau+2*NS,100000.));self.e.db.commit()
        self.transaction(tau+61*NS,lambda:self.e.reconcile(tau+61*NS))
    def test_latency_1000ms_and_shared_frozen_quantity(self):
        self.prepare();self.assertEqual(self.e.s['pending']['due'],601*NS)
        self.assertEqual(self.e.s['pending']['quantity'],.005)
        self.tick(600*NS+600*m.MS,fixture.books(600*NS+600*m.MS));self.assertEqual(self.e.s['q'],0)
        self.tick(601*NS+100*m.MS,[fixture.row(601*NS+100*m.MS)])
        self.assertEqual(self.e.s['q'],-.005)
        fill=self.e.db.execute('SELECT * FROM fills').fetchone()
        self.assertAlmostEqual(fill['fee'],abs(fill['quantity']*fill['price'])*.0012)
        self.assertLess(fill['price'],m.execution(fixture.row(601*NS),-.005)[1])
    def test_later_stress_arrival_can_miss_independently(self):
        self.prepare();self.tick(602*NS+1,fixture.books(602*NS+1))
        self.assertEqual(self.e.s['q'],0);self.assertIsNone(self.e.s['pending'])
    def test_prior_stress_position_suppresses_primary_admission(self):
        self.open();slot=300*NS;self.e.books.extend(fixture.books(slot))
        self.transaction(slot+2*NS,lambda:self.e.primary_opportunity(self.opportunity(),slot+2*NS,'shared'))
        self.assertEqual(self.e.s['q'],-.005);self.assertIsNone(self.e.s['pending'])
        self.assertEqual(self.e.db.execute('SELECT status FROM slots').fetchone()[0],'STRESS_PRIOR_POSITION_OR_INTENT')
    def test_no_independent_admission_when_primary_did_not_admit(self):
        op=self.opportunity();op.update(status='NO_SIGNAL',payload='{}')
        self.transaction(302*NS,lambda:self.e.primary_opportunity(op,302*NS,'shared'))
        self.assertIsNone(self.e.s['pending'])
    def test_admission_replay_late_or_duplicate_never_opens(self):
        self.transaction(331*NS,lambda:self.e.primary_opportunity(self.opportunity(),331*NS,'shared'))
        self.transaction(332*NS,lambda:self.e.primary_opportunity(self.opportunity(),332*NS,'shared'))
        self.assertIsNone(self.e.s['pending']);self.assertEqual(self.e.db.execute('SELECT COUNT(*) FROM slots').fetchone()[0],1)
    def test_own_entry_price_triggers_own_stop_with_1000ms_exit_latency(self):
        self.open();self.tick(101*NS,[fixture.row(101*NS,100979.)])
        self.assertEqual(self.e.s['pending']['reason'],'STOP_LOSS')
        self.assertEqual(self.e.s['pending']['due'],102*NS)
        self.tick(101*NS+600*m.MS,[fixture.row(101*NS+600*m.MS,100979.)]);self.assertLess(self.e.s['q'],0)
        self.tick(102*NS+100*m.MS,[fixture.row(102*NS+100*m.MS,100979.)]);self.assertEqual(self.e.s['q'],0)
    def test_signed_funding_doubles_debits(self):
        self.open();self.funding(-.001);self.assertAlmostEqual(self.e.s['funding'],-1.)
    def test_signed_funding_suppresses_credits(self):
        self.open();self.funding(.001);self.assertEqual(self.e.s['funding'],0.)
    def test_own_risk_halt_does_not_use_primary_equity(self):
        slot=300*NS;self.e.books.extend(fixture.books(slot))
        self.transaction(301*NS,lambda:self.e.s.update(cash=8900.))
        self.transaction(302*NS,lambda:self.e.primary_opportunity(self.opportunity(),302*NS,'shared'))
        self.assertIsNone(self.e.s['pending']);self.assertTrue(self.e.s['drawdown_halt'])
    def test_stress_intended_size_is_not_increased_on_revalidation(self):
        self.prepare(quantity=.003)
        self.tick(601*NS+100*m.MS,fixture.books(601*NS+100*m.MS,price=50000.))
        self.assertEqual(self.e.s['q'],-.003)

if __name__=='__main__':unittest.main()
