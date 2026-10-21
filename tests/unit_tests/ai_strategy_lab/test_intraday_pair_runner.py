"""Synthetic E2E qualification. Never opens an existing account or source DB."""
import ast
import copy
import hashlib
import json
import os
from pathlib import Path
import sqlite3
import subprocess
import sys
import tempfile
import types
import unittest

ROOT=Path(__file__).resolve().parents[3]
LAB=ROOT/'octobot/ai_strategy_lab'
sys.path.insert(0,str(LAB))
from intraday_pair import engine as m, receipts
from intraday_pair.runner import Pair, close_request
from intraday_pair.evaluation import evaluate
from intraday_pair.service import authority, root_document
NS=m.NS


class Clock:
    def __init__(self):self.t=10*NS
    def sample(self):return dict(utc_ns=self.t,monotonic_ns=self.t,boot_id='fixture')


def row(at,price=100000.,size=100.,identity=None):
    r=dict(id=at if identity is None else identity,session_id='fixture',received_ts_ns=at,
           exchange_ts_ns=at-10*m.MS,payload_sha256='a'*64)
    for side in ('bid','ask'):
        for i in range(1,6):
            r[f'{side}_price_{i}']=price-i if side=='bid' else price+i
            r[f'{side}_size_{i}']=size
    return r


def books(at,price=100000.):
    return [row(t,price) for t in range(at-12*NS,at+1,100*m.MS)]


def frozen_reference():
    raw=(Path(__file__).parent/'fixtures/btc_intraday_short_runner_reference_v1.txt').read_bytes()
    assert hashlib.sha256(raw).hexdigest()=='52e2d6843527c3ef1bdffc32ffef982a0e06adf7eea7fe8f1335f0480282e555'
    text=raw.decode().split('\ndef atomic(')[0]
    tree=ast.parse(text)
    tree.body=[n for n in tree.body if not (isinstance(n,ast.Import) and any(
        a.name=='btc_intraday_availability' for a in n.names)) and not (
        isinstance(n,ast.ImportFrom) and n.module=='btc_intraday_source_qualification')]
    namespace=dict(receipt=types.SimpleNamespace(Clock=receipts.Clock,
        PROTOCOL_SHA='bbc19094ac23b8b13a0d82919802f2ede3787add5eda2e13f0f2d8489861493b'),
        NS=NS,canonical=m.canonical,digest=m.digest,strict=m.strict)
    exec(compile(tree,'hash-pinned-short-reference','exec'),namespace)
    return types.SimpleNamespace(**namespace)


class EngineTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.clock=Clock()
        self.path=Path(self.temp.name)/'candidate.sqlite'
        self.e=m.Engine(self.path,0,'test-bundle',self.clock,True,arm='candidate')
    def tearDown(self):self.e.close();self.temp.cleanup()
    def act(self,at,fn):self.clock.t=at;return self.e.transaction('TEST',at,fn)
    def tick(self,at,rows):
        self.clock.t=at;self.e.tick(rows,dict(data_sha256='fixture',observed_visible=self.clock.sample()))
    def open(self,q=.005,at=100*NS):
        self.act(at-NS,lambda:self.e.risk(at-NS,100000.))
        self.act(at,lambda:self.e.fill(row(at),q,at,'ENTRY'))
    def pending(self,direction):
        due=600*NS+500*m.MS
        self.act(302*NS,lambda:self.e.s.update(pending=dict(kind='ENTRY',commit_seq=self.e.seq+1,
            slot=300*NS,due=due,deadline=due+1000*m.MS,quantity=.005,direction=direction,id='fixture')))
        self.e.db.execute('INSERT INTO calendars VALUES(?,?,?,?,?,?)',('cal',599*NS,599*NS,10000*NS,28800000,1));self.e.db.commit()
        return due
    def funding(self,tau,rate):
        self.e.db.execute('INSERT INTO announced VALUES(?)',(tau,))
        self.e.db.execute('INSERT INTO rates VALUES(?,?,?,?)',('rate',tau,tau+NS,rate))
        self.e.db.execute('INSERT INTO marks VALUES(?,?,?,?,?,?)',('mark','BTCUSDT',tau-NS,tau-2*NS,tau+2*NS,100000.));self.e.db.commit()

    def test_long_prospective_entry_ask_latency_and_no_duplicate(self):
        due=self.pending(1)
        self.tick(due-1,books(due-1));self.assertEqual(self.e.s['q'],0)
        self.tick(due+100*m.MS,[row(due+100*m.MS)])
        self.assertEqual(self.e.s['q'],.005);self.assertGreater(self.e.s['entry'],100001)
        self.tick(due+200*m.MS,[row(due+200*m.MS)])
        self.assertEqual(self.e.s['fills'],1)

    def test_long_stop_latches_and_uses_new_bid_after_latency(self):
        self.open();self.tick(101*NS,[row(101*NS,98000.)])
        self.assertEqual(self.e.s['pending']['reason'],'STOP_LOSS')
        self.tick(101*NS+600*m.MS,[row(101*NS+600*m.MS,99000.)])
        self.assertEqual(self.e.s['q'],0);self.assertLess(self.e.s['realized'],0)
        fill=self.e.db.execute('SELECT * FROM fills ORDER BY at_ns DESC LIMIT 1').fetchone()
        self.assertLess(fill['quantity'],0);self.assertLess(fill['price'],99000)

    def test_long_take_profit_and_partial_protective_close(self):
        self.open(.009);self.tick(101*NS,[row(101*NS,103000.)])
        self.assertEqual(self.e.s['pending']['reason'],'TAKE_PROFIT')
        self.tick(102*NS,[row(102*NS,103000.,size=1)])
        self.assertAlmostEqual(self.e.s['q'],.004);self.assertIsNotNone(self.e.s['pending'])
        self.tick(103*NS,[row(103*NS,103000.)]);self.assertEqual(self.e.s['q'],0)
        self.assertGreater(self.e.s['realized'],0)

    def test_missing_data_requests_exit_but_never_invents_flat(self):
        self.open();self.tick(110*NS,[])
        self.assertEqual(self.e.s['q'],.005);self.assertEqual(self.e.s['pending']['kind'],'EXIT')

    def test_exit_cannot_invert_increase_or_close_wrong_direction(self):
        self.open()
        for amount in (.001,-.009):
            with self.assertRaisesRegex(ValueError,'reversed'):
                self.act(101*NS,lambda:self.e.fill(row(101*NS),amount,101*NS,'EXIT'))
            self.assertEqual(self.e.s['q'],.005)
            self.e.failed=False  # explicit new test operation after injected API misuse

    def test_long_funding_pays_positive_and_reconciles_once(self):
        self.open();self.funding(200*NS,.001)
        self.act(261*NS,lambda:self.e.reconcile(261*NS))
        self.assertAlmostEqual(self.e.s['funding'],-.5)
        self.act(262*NS,lambda:self.e.reconcile(262*NS))
        self.assertAlmostEqual(self.e.s['funding'],-.5)

    def test_long_protective_sell_before_settlement_keeps_worst_debit(self):
        self.open();tau=200*NS;self.funding(tau,.001)
        self.act(tau-10*NS,lambda:self.e.fill(row(tau-10*NS),-.005,tau-10*NS,'EXIT'))
        self.act(tau+61*NS,lambda:self.e.reconcile(tau+61*NS))
        self.assertAlmostEqual(self.e.s['funding'],-.5)

    def test_long_protective_sell_after_settlement_suppresses_uncertain_credit(self):
        self.open();tau=200*NS;self.funding(tau,-.001)
        self.act(tau+10*NS,lambda:self.e.fill(row(tau+10*NS),-.005,tau+10*NS,'EXIT'))
        self.act(tau+61*NS,lambda:self.e.reconcile(tau+61*NS))
        self.assertEqual(self.e.s['funding'],0)

    def test_conflicting_rate_and_late_mark_remain_pending(self):
        self.open();tau=200*NS;self.funding(tau,.001)
        self.e.db.execute('UPDATE marks SET received=?',(tau+1,));self.e.db.commit()
        self.act(tau+61*NS,lambda:self.e.reconcile(tau+61*NS))
        self.assertFalse(self.e.accounting_complete())
        self.e.db.execute('UPDATE marks SET received=?',(tau-1,))
        self.e.db.execute('INSERT INTO rates VALUES(?,?,?,?)',('other',tau,tau+NS,-.001));self.e.db.commit()
        self.act(tau+62*NS,lambda:self.e.reconcile(tau+62*NS))
        self.assertFalse(self.e.accounting_complete())

    def test_long_restart_keeps_position_high_water_and_halt(self):
        self.open();self.act(101*NS,lambda:self.e.s.update(high_water=12000.,drawdown_halt=True))
        self.e.close();self.e=m.Engine(self.path,0,'test-bundle',self.clock,arm='candidate')
        self.assertEqual(self.e.s['q'],.005);self.assertTrue(self.e.s['drawdown_halt'])
        self.assertEqual(self.e.s['high_water'],12000)

    def test_storage_failure_rolls_back_and_latches(self):
        self.e.db.execute('PRAGMA query_only=ON')
        with self.assertRaises(sqlite3.OperationalError):self.open()
        self.assertEqual(self.e.s['q'],0);self.assertTrue(self.e.failed)
        with self.assertRaisesRegex(ValueError,'storage_fault'):self.open()

    def test_admin_long_close_nonce_generation_expiry_and_no_replay(self):
        self.open();now=101*NS;command=close_request(self.e.s,now)
        for change in ({'generation':99},{'account':'v13-paper-v2'},{'expires_ns':now-1}):
            with self.assertRaisesRegex(ValueError,'administrative'):
                self.e.administrative_close({**command,**change},now)
        self.clock.t=now;self.assertTrue(self.e.administrative_close(command,now))
        self.assertFalse(self.e.administrative_close(command,now))
        self.tick(now+600*m.MS,[row(now+600*m.MS)]);self.assertEqual(self.e.s['q'],0)

    def test_control_still_rejects_long(self):
        path=Path(self.temp.name)/'control.sqlite';control=m.Engine(path,0,'b',self.clock,True)
        try:
            with self.assertRaisesRegex(ValueError,'entry_position'):
                control.transaction('TEST',100*NS,lambda:control.fill(row(100*NS),.005,100*NS,'ENTRY'))
            self.assertEqual(control.s['q'],0)
        finally:control.close()


class ParityTests(unittest.TestCase):
    def test_reused_receipt_and_source_definitions_match_frozen_ast_pins(self):
        pins=json.loads((Path(__file__).parent/'fixtures/intraday_pair_receipt_ast_pins.json').read_text())
        for name,pin in pins.items():
            actual={n.name:hashlib.sha256(ast.dump(n,include_attributes=False).encode()).hexdigest()
                    for n in ast.parse((LAB/'intraday_pair'/name).read_text()).body
                    if isinstance(n,(ast.FunctionDef,ast.ClassDef))}
            self.assertEqual(actual,pin['definitions'])

    def test_reference_short_paths_have_equal_economic_trace(self):
        legacy=frozen_reference();clock=Clock()
        for prices in ((100000.,98000.,99000.),(100000.,102000.,101000.)):
            with tempfile.TemporaryDirectory() as d:
                old=legacy.Engine(Path(d)/'old.sqlite',0,'b',clock,True)
                new=m.Engine(Path(d)/'new.sqlite',0,'b',clock,True)
                old.protocol={'signal':{'universe':new.protocol['signal']['universe']}}
                try:
                    for e in (old,new):
                        clock.t=99*NS;e.transaction('TEST',clock.t,lambda:e.risk(clock.t,100000.))
                        clock.t=100*NS;e.transaction('TEST',clock.t,lambda:e.fill(row(clock.t,prices[0]),-.005,clock.t,'ENTRY'))
                        for at,price in ((101*NS,prices[1]),(102*NS,prices[2])):
                            clock.t=at;e.tick([row(at,price)],dict(data_sha256='fixture',observed_visible=clock.sample()))
                    for field in ('q','cash','fees','funding','realized','entry','fills','high_water','drawdown_halt','pending'):
                        self.assertEqual(old.s[field],new.s[field],field)
                    a=[tuple(r) for r in old.db.execute('SELECT quantity,price,fee,realized FROM fills ORDER BY at_ns')]
                    b=[tuple(r) for r in new.db.execute('SELECT quantity,price,fee,realized FROM fills ORDER BY at_ns')]
                    self.assertEqual(a,b)
                finally:old.close();new.close()

    def test_boundary_signal_keeps_reference_float_semantics(self):
        legacy=frozen_reference();clock=Clock();slot=400*300*NS
        for final in (99000.,99000.000000001,101000.,101000.000000001):
            with tempfile.TemporaryDirectory() as d:
                engines=[legacy.Engine(Path(d)/'old.sqlite',0,'b',clock,True),m.Engine(Path(d)/'new.sqlite',0,'b',clock,True)]
                try:
                    for e in engines:
                        e.protocol={'signal':{'universe':m.strict(Path(m.__file__).with_name('protocol.json').read_bytes())['signal']['universe']}}
                        for i in range(288):
                            at=slot-(288-i)*300*NS;payload={s:dict(price=100000.) for s in e.protocol['signal']['universe']}
                            e.db.execute('INSERT INTO grid VALUES(?,?,?)',(at,1,m.canonical(payload).decode()))
                        for s in e.protocol['signal']['universe']:
                            e.db.execute('INSERT INTO marks VALUES(?,?,?,?,?,?)',(s,s,slot-20*NS,slot-21*NS,slot-19*NS,final))
                        e.books.extend(books(slot))
                        e.db.execute('INSERT INTO calendars VALUES(?,?,?,?,?,?)',('cal',slot-20*NS,slot-19*NS,slot+10000*NS,28800000,1))
                        e.db.commit();clock.t=slot+2*NS
                        e.transaction('TEST',clock.t,lambda:e.signal_slot(slot,clock.t,'receipt'))
                    statuses=[e.db.execute('SELECT status FROM slots').fetchone()[0] for e in engines]
                    self.assertEqual(statuses[0],statuses[1])
                finally:
                    for e in engines:e.close()


class PairTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.path=Path(self.tmp.name)/'pair';self.clock=Clock()
        self.p=Pair(self.path,0,'fixture',initialize=True,clock=self.clock,synthetic=True)
    def tearDown(self):self.p.close();self.tmp.cleanup()
    def publish(self,kind,payload,at=None,key='fixture'):
        if at is not None:self.clock.t=at
        stamp=self.clock.sample()
        return self.p.publish(kind,key,payload,stamp,stamp,stamp['utc_ns'])

    def test_same_durable_receipt_and_seed_in_all_four_ledgers(self):
        self.publish('heartbeat',{'rows':[]})
        values=list(self.p.status()['arms'].values())
        self.assertEqual({x['cursor'] for x in values},{1})
        self.assertEqual(len({x['input_sha'] for x in values}),1)
        self.assertEqual({x['equity'] for x in values},{10000.})

    def test_partial_fanout_restart_skips_already_committed_arm(self):
        def crash(name):
            if name=='control-primary':raise RuntimeError('injected_crash')
        self.p.after_arm=crash
        with self.assertRaisesRegex(RuntimeError,'injected_crash'):self.publish('heartbeat',{'rows':[]})
        first=self.p.engines['control-primary'].seq
        self.p.close();self.p=Pair(self.path,0,'fixture',clock=self.clock,synthetic=True)
        self.p.drain()
        self.assertEqual(self.p.engines['control-primary'].seq,first)
        self.assertEqual({v.s['last_input_seq'] for v in self.p.engines.values()},{1})

    def test_input_storage_failure_never_reaches_any_account(self):
        self.p.db.execute('PRAGMA query_only=ON')
        with self.assertRaises(sqlite3.OperationalError):self.publish('heartbeat',{'rows':[]})
        self.assertEqual({v.s['last_input_seq'] for v in self.p.engines.values()},{0})
        with self.assertRaisesRegex(ValueError,'fault_latched'):self.publish('heartbeat',{'rows':[]})

    def test_duplicate_source_receipt_never_duplicates_a_fill(self):
        self.publish('heartbeat',{'rows':[]})
        with self.assertRaisesRegex(ValueError,'duplicate_observation'):self.publish('heartbeat',{'rows':[]})
        self.assertEqual({v.s['fills'] for v in self.p.engines.values()},{0})

    def test_missing_ledger_cannot_be_reinitialized(self):
        self.p.close();(self.path/'candidate-primary.sqlite').unlink()
        with self.assertRaisesRegex(ValueError,'state_missing'):Pair(self.path,0,'fixture',clock=self.clock,synthetic=True)

    def test_identity_change_and_existing_destination_rejected(self):
        self.p.close()
        with self.assertRaisesRegex(ValueError,'identity_changed'):Pair(self.path,0,'other',clock=self.clock,synthetic=True)
        with self.assertRaises(FileExistsError):Pair(self.path,0,'fixture',initialize=True,clock=self.clock,synthetic=True)

    def test_public_mode_refuses_activation_and_raw_injection(self):
        with self.assertRaisesRegex(ValueError,'activation_not_authorized'):Pair(Path(self.tmp.name)/'active',0,'b',initialize=True,clock=self.clock)
        public=Pair(Path(self.tmp.name)/'public',86400*NS,'b',initialize=True,clock=self.clock)
        try:
            t=self.clock.sample()
            with self.assertRaisesRegex(ValueError,'raw_source'):public.publish('heartbeat','x',{'rows':[]},t,t,t['utc_ns'])
        finally:public.close()

    def test_snapshot_cannot_use_future_book_or_future_account_state(self):
        self.publish('book',{'rows':[row(299*NS+500*m.MS)]},299*NS+500*m.MS)
        self.publish('book',{'rows':[row(301*NS,200000.)]},301*NS,key='future')
        for e in self.p.engines.values():
            self.clock.t=302*NS;e.transaction('TEST',302*NS,lambda:e.s.update(cash=9999.))
        observed=self.p.observe_grid(300*NS)
        self.assertEqual(observed['mid'],100000.)
        self.assertEqual({a['equity'] for a in observed['accounts'].values()},{10000.})
        self.assertTrue(all(a['complete'] for a in observed['accounts'].values()))

    def test_stale_snapshot_remains_incomplete_without_interpolation(self):
        self.clock.t=300*NS
        v=self.p.observe_grid(300*NS)
        self.assertTrue(all(not a['complete'] for a in v['accounts'].values()))
        self.assertEqual(v,self.p.observe_grid(300*NS))

    def test_cold_copy_integrity_and_input_cursor(self):
        self.publish('heartbeat',{'rows':[]});self.p.close()
        for path in self.path.glob('*.sqlite'):
            with sqlite3.connect(path) as db:self.assertEqual(db.execute('PRAGMA integrity_check').fetchone()[0],'ok')
        self.p=Pair(self.path,0,'fixture',clock=self.clock,synthetic=True)
        self.assertEqual(self.p.status()['input_seq'],1)

    def test_receipts_to_long_and_independent_stress_full_roundtrip(self):
        universe=self.p.engines['control-primary'].protocol['signal']['universe']
        for i in range(1,290):
            slot=i*300*NS;price=102000. if i==289 else 100000.
            normalized=[dict(kind='mark',value=[f'{i}:{s}','package',slot-20*NS,slot-19*NS,s,slot-21*NS,price]) for s in universe]
            normalized.append(dict(kind='calendar',value=[f'cal:{i}','package',slot-20*NS,slot-19*NS,2*86400*NS,28800000,1]))
            self.publish('market',dict(normalized=normalized),slot-19*NS,key=f'market:{i}')
            self.publish('book',dict(rows=books(slot+2*NS,price)),slot+2*NS,key=f'book:{i}')
        candidate=self.p.engines['candidate-primary'];stress=self.p.engines['candidate-stress']
        self.assertEqual(candidate.s['pending']['direction'],1)
        self.assertIsNone(self.p.engines['control-primary'].s['pending'])
        due=candidate.s['pending']['due']
        at=due-20*NS
        normalized=[dict(kind='mark',value=[f'arrival:{s}','package',at-NS,at,s,at-2*NS,102000.]) for s in universe]
        normalized.append(dict(kind='calendar',value=['arrival:cal','package',at-NS,at,2*86400*NS,28800000,1]))
        self.publish('market',dict(normalized=normalized),at,key='arrival-market')
        self.publish('book',dict(rows=books(due-100*m.MS,102000.)),due-100*m.MS,key='arrival-pre')
        self.publish('book',dict(rows=[row(due+100*m.MS,102000.)]),due+100*m.MS,key='arrival-base')
        self.assertGreater(candidate.s['q'],0);self.assertEqual(stress.s['q'],0)
        self.publish('book',dict(rows=[row(due+600*m.MS,102000.)]),due+600*m.MS,key='arrival-stress')
        self.assertGreater(stress.s['q'],0)
        trigger=due+1500*m.MS
        self.publish('book',dict(rows=[row(trigger,105000.)]),trigger,key='tp-trigger')
        self.publish('book',dict(rows=[row(trigger+600*m.MS,105000.)]),trigger+600*m.MS,key='exit-base')
        self.assertEqual(candidate.s['q'],0);self.assertGreater(stress.s['q'],0)
        self.publish('book',dict(rows=[row(trigger+1100*m.MS,105000.)]),trigger+1100*m.MS,key='exit-stress')
        self.assertEqual(stress.s['q'],0)
        self.assertEqual(candidate.s['fills'],2);self.assertEqual(stress.s['fills'],2)
        self.assertEqual(self.p.engines['control-primary'].s['fills'],0)
        self.assertGreater(candidate.equity(),stress.equity())
        self.assertEqual({e.s['last_input_seq'] for e in self.p.engines.values()},{self.p.seq})

    def test_admin_file_custody_and_target_scenario(self):
        e=self.p.engines['candidate-primary'];self.clock.t=100*NS
        e.transaction('TEST',100*NS,lambda:e.fill(row(100*NS),.005,100*NS,'ENTRY'))
        command=close_request(e.s,101*NS);path=Path(self.tmp.name)/'command.json'
        path.write_bytes(m.canonical(command));path.chmod(0o666)
        with self.assertRaisesRegex(ValueError,'custody'):self.p.administrative_file(path)
        path.chmod(0o600);self.clock.t=101*NS;self.p.administrative_file(path)
        self.assertEqual(e.s['pending']['reason'],'ADMIN_CLOSE')
        self.assertIsNone(self.p.engines['candidate-stress'].s['pending'])

    def test_read_clock_regression_latches_witness(self):
        clock=receipts.Clock(wall=lambda:10*NS,mono=lambda:10*NS,boot=lambda:'fixture')
        clock.sample();clock.wall=lambda:9*NS
        with self.assertRaisesRegex(ValueError,'clock_discontinuity'):clock.sample()
        with self.assertRaisesRegex(ValueError,'clock_fault_latched'):clock.sample()


class EvaluationTests(unittest.TestCase):
    def fixture(self,positive=True):
        t1=90*86400*NS;points=range(0,t1+300*NS,300*NS);arms={}
        for name in ('control-primary','candidate-primary','control-stress','candidate-stress'):
            slope=(20 if positive else -20) if name.startswith('candidate') else 0
            rows=[dict(at_ns=at,equity=10000+slope*at/t1,complete=True) for at in points]
            fills=[]
            for day in range(0,80,3):
                at=(day*86400+100)*NS
                fills.extend([dict(at_ns=at,quantity=.001,detail=dict(kind='ENTRY',after=.001)),
                              dict(at_ns=at+NS,quantity=-.001,detail=dict(kind='EXIT',after=0))])
            arms[name]=dict(points=rows,fills=fills,final_q=0,complete=True,integrity_halt=False,valid_slots=90*288,slots=90*288)
        return dict(mode='SYNTHETIC_TEST_ONLY',t0=0,t1=t1,arms=arms)

    def test_frozen_future_review_cannot_be_unblinded_early(self):
        x=self.fixture()
        with self.assertRaisesRegex(ValueError,'sealed_until'):evaluate(x,1)

    def test_weekly_paired_bootstrap_is_deterministic_and_fixture_labelled(self):
        x=self.fixture();a=evaluate(x,x['t1'],synthetic=True);b=evaluate(x,x['t1'],synthetic=True)
        self.assertEqual(a,b);self.assertEqual(a['classification'],'CANDIDATE_FOR_FURTHER_REVIEW_ONLY')
        self.assertTrue(a['synthetic_fixture']);self.assertFalse(a['automatic_promotion'])
        self.assertGreater(a['bootstrap_lower_95'],0)

    def test_negative_case_fails_fixed_criteria(self):
        x=self.fixture(False);self.assertEqual(evaluate(x,x['t1'],synthetic=True)['classification'],'FAILED_FROZEN_CRITERIA')

    def test_missing_week_zero_activity_or_pending_is_inconclusive(self):
        for kind in ('gap','activity','pending'):
            x=self.fixture();arm=x['arms']['candidate-primary']
            if kind=='gap':arm['points'].pop(10)
            elif kind=='activity':arm['fills']=[]
            else:arm['complete']=False
            self.assertEqual(evaluate(x,x['t1'],synthetic=True)['classification'],'INCONCLUSIVE_NO_PROMOTION')


class CrashTests(unittest.TestCase):
    def test_process_crash_after_long_commit_preserves_position_and_halts(self):
        with tempfile.TemporaryDirectory() as d:
            path=Path(d)/'long.sqlite'
            code='''
import sys,os,time
sys.path.insert(0,sys.argv[1])
from intraday_pair import engine as m
e=m.Engine(sys.argv[2],0,'crash-fixture',initialize=True,arm='candidate')
at=time.time_ns();r=dict(id=1,session_id='fixture',received_ts_ns=at,exchange_ts_ns=at-1000000)
for side in ('bid','ask'):
 for i in range(1,6):r[f'{side}_price_{i}']=100000-i if side=='bid' else 100000+i;r[f'{side}_size_{i}']=100
e.after_commit=lambda:os._exit(74)
e.transaction('ENTRY',at,lambda:e.fill(r,.005,at,'ENTRY'))
'''
            result=subprocess.run([sys.executable,'-B','-c',code,str(LAB),str(path)],capture_output=True)
            self.assertEqual(result.returncode,74,result.stderr.decode())
            e=m.Engine(path,0,'crash-fixture',arm='candidate')
            try:
                self.assertEqual(e.s['q'],.005);self.assertTrue(e.s['integrity_halt'])
                self.assertEqual(e.s['fills'],1)
                self.assertEqual(e.db.execute('PRAGMA integrity_check').fetchone()[0],'ok')
            finally:e.close()


class AuthorityTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.root=Path(self.tmp.name)
        package=LAB/'intraday_pair'
        self.receipt=dict(scope='AUTHORIZED_SYNTHETIC_PAPER_PAIR',paper_pair_activation_authorized=True,
            real_orders=False,exchange_credentials=False,operational_grants=False,
            protocol_sha256=m.PROTOCOL_SHA,operator_acceptance_reference='UNIT_TEST_ONLY_NOT_REAL_APPROVAL',
            t0_ns=86400*NS,t1_ns=91*86400*NS,directory=str(self.root/'new-pair'),
            account_ids=['btc-intraday-short-control-v1','btc-intraday-long-short-v1'],
            code_pins={p.name:hashlib.sha256(p.read_bytes()).hexdigest() for p in list(package.glob('*.py'))+[package/'protocol.json']})
        self.path=self.root/'receipt.json'
        self.config=dict(activation=str(self.path),directory=str(self.root/'new-pair'),
                         source=str(self.root/'source'),book=str(self.root/'book/book.sqlite'))
    def tearDown(self):self.tmp.cleanup()
    def check(self):
        self.path.write_bytes(m.canonical(self.receipt));self.path.chmod(0o600)
        return authority(self.config,initialize=True,now_ns=10*NS)

    def test_exact_pins_and_future_common_horizon_are_required(self):
        self.assertEqual(self.check(),self.receipt)
        self.receipt['code_pins']['engine.py']='0'*64
        with self.assertRaisesRegex(ValueError,'pin_mismatch'):self.check()

    def test_no_synthetic_result_or_empty_approval_can_activate(self):
        self.receipt['paper_pair_activation_authorized']=False
        with self.assertRaisesRegex(ValueError,'operator_receipt'):self.check()
        self.receipt['paper_pair_activation_authorized']=True
        self.receipt['operator_acceptance_reference']=''
        with self.assertRaisesRegex(ValueError,'operator_receipt'):self.check()

    def test_unsafe_custody_old_t0_and_different_destination_deny(self):
        self.check();self.path.chmod(0o666)
        with self.assertRaisesRegex(ValueError,'root_owned'):root_document(self.path)
        self.receipt['t0_ns']=0;self.receipt['t1_ns']=90*86400*NS
        with self.assertRaisesRegex(ValueError,'future_common_horizon'):self.check()
        self.receipt['t0_ns']=86400*NS;self.receipt['t1_ns']=91*86400*NS
        self.receipt['directory']=str(self.root/'other')
        with self.assertRaisesRegex(ValueError,'destination_mismatch'):self.check()


if __name__=='__main__':unittest.main()
