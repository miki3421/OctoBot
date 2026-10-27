"""Replacement mechanics on synthetic input; no predictive validation claim."""
import copy
import datetime as dt
import json
import math
import os
from pathlib import Path
import sqlite3
import tempfile
import unittest
from unittest.mock import patch

from octobot.ai_strategy_lab import v13_original_structural as M

ROOT = Path(__file__).resolve().parents[3]
PROTOCOL = json.loads((ROOT/'docs/research-protocols/original-m1-structural-successor-v2.json').read_text())
PARENT = json.loads((ROOT/'docs/research-protocols/m1-short-risk-exits-candidate-v1.json').read_text())
STRUCTURE = json.loads((ROOT/'docs/research-protocols/m1-short-structural-invalidation-v1.json').read_text())
T = dt.datetime(2026, 10, 27, 12, tzinfo=dt.timezone.utc)


def state():
    positions = {s:dict(M.P.paper.new_position(), quantity=1. if PARENT['short_caps'][s]>0 else 0.,
                      current_price=100., entry_price=100., generation=1, position_id='inherited',
                      funding_cursor=T.isoformat(), last_mark_at=T.isoformat()) for s in M.R.SIGNALS}
    return dict(initial_equity=10000., order_count=6, positions=positions,
        risk_policy_state=dict(daily_day=T.date().isoformat(), daily_start=10000., daily_entries=0,
                               high_water=10100., last_increase_at=None))


def book(at, price=100., capacity=10000.):
    quotes = {s:dict(symbol=s, market_identity='kucoin_futures_usdt', mark_price=price,
        bids=[dict(price=price-.01, base_quantity=capacity)], asks=[dict(price=price+.01, base_quantity=capacity)],
        quantity_step=.01, step=.01, contract_multiplier=.01, price_tick=.01, fee_rate=.0006,
        min_quantity=None, min_notional=None, metadata_scope='REAL_PRECISION_WITH_SEPARATE_SIMULATED_MINIMUMS',
        simulation_min_quantity=.01, simulation_min_notional=1., funding_interval_ms=28800000,
        funding=[dict(timestamp_ms=int(T.timestamp()*1000),rate=0.)],
        timestamp=at.isoformat(), mark_timestamp=at.isoformat(), metadata_observed_at=at.isoformat())
        for s in M.R.SIGNALS}
    value = dict(scope=M.P.source.SCOPE, observed_at_start=at.isoformat(), observed_at_end=at.isoformat(), quotes=quotes)
    value['record_hash'] = M.digest(value)
    return value


def rows(slot):
    return [dict(time=slot-(288-i)*300, prices={s:100*math.exp(-.001*i) for s in M.R.SIGNALS},
        source_times={s:slot-(288-i)*300-1 for s in M.R.SIGNALS}) for i in range(289)]


class OriginalStructuralTests(unittest.TestCase):
    def setUp(self):
        self.db = sqlite3.connect(':memory:')
        self.s = state()
        self.a = dict(authority_id='test-original-authority', activated_at=T.isoformat(),
                      boundary_state_hash=M.digest(self.s), boundary_orders=6)
        self.control = M.initialize(self.db, self.a, PROTOCOL, self.s)
        self.c = dict(epoch='original-preserved-epoch')
        def approved(c,authority_id,slot,now,input_hash):
            return dict(approval_id=M.digest(dict(authority=authority_id,slot=slot,input_hash=input_hash)))
        self.approval_patch=patch.object(M,'read_signal_approval',side_effect=approved);self.approval_patch.start()

    def tearDown(self):
        self.approval_patch.stop()
        self.db.close()

    def step(self, at, rec=None, panel=None, daily=None, funding_ok=True):
        result = M.process(self.c, self.db, self.s, self.control, rec or book(at), at,
            PROTOCOL, PARENT, STRUCTURE, rows=panel, daily=daily, funding_ok=funding_ok)
        self.s, self.control = result[:2]
        return result

    def test_boundary_preserves_capital_positions_and_risk_and_restart(self):
        before = copy.deepcopy(self.s)
        self.assertEqual(self.control['boundary']['metrics']['equity'],10000.)
        self.assertEqual(self.s, before)
        self.assertEqual(M.initialize(self.db,self.a,PROTOCOL,self.s),self.control)
        self.a['authority_id']='different'
        with self.assertRaisesRegex(ValueError,'reactivation'): M.initialize(self.db,self.a,PROTOCOL,self.s)

    def test_wrong_protocol_or_changed_boundary_cannot_activate(self):
        p=copy.deepcopy(PROTOCOL);p['risk']['daily_loss']=.5
        with self.assertRaises(ValueError):M.validate(p)
        db=sqlite3.connect(':memory:');s=state();s['positions']['BTCUSDT']['quantity']=-1.
        with self.assertRaisesRegex(ValueError,'boundary'):M.initialize(db,self.a,PROTOCOL,s)
        db.close()

    def test_fifty_percent_reduction_waits_for_later_book(self):
        before=copy.deepcopy(self.s)
        _,control,legs,_,_=self.step(T+dt.timedelta(seconds=1))
        self.assertEqual(legs,[]);self.assertEqual(self.s,before)
        self.assertEqual(control['pending']['kind'],'LONG_REDUCE')
        self.step(T+dt.timedelta(seconds=30))
        self.assertTrue(all(p['quantity']==.5 for s,p in self.s['positions'].items() if s in control['initial_longs']))
        self.assertEqual(self.s['risk_policy_state']['daily_entries'],0)

    def test_no_topup_after_price_decline(self):
        self.step(T+dt.timedelta(seconds=1));self.step(T+dt.timedelta(seconds=30))
        q={s:p['quantity'] for s,p in self.s['positions'].items()}
        self.step(T+dt.timedelta(hours=1),book(T+dt.timedelta(hours=1),price=70.))
        self.assertEqual(q,{s:p['quantity'] for s,p in self.s['positions'].items()})
        self.assertIsNone(self.control['pending'])

    def test_next_stage_requires_distinct_day_24_hours_and_bad_daily_signal(self):
        self.step(T+dt.timedelta(seconds=1));self.step(T+dt.timedelta(seconds=30))
        daily=dict(day='2026-10-27',targets={s:'0' for s in M.R.SIGNALS})
        self.step(T+dt.timedelta(hours=23),daily=daily);self.assertIsNone(self.control['pending'])
        good=copy.deepcopy(daily);good['targets']={s:'0.1' for s in M.R.SIGNALS}
        self.step(T+dt.timedelta(hours=25),daily=good);self.assertIsNone(self.control['pending'])
        self.step(T+dt.timedelta(hours=25,seconds=1),daily=daily)
        self.assertEqual(self.control['pending']['kind'],'LONG_REDUCE')

    def admit(self):
        # Inherited LONG reduction is already complete for this synthetic entry.
        self.control['stages']={s:dict(index=2,at=T.timestamp(),day='2026-10-26') for s in self.control['initial_longs']}
        self.step(T+dt.timedelta(seconds=1),panel=rows(int(T.timestamp())))
        self.assertEqual(self.control['phase'],'ENTRY_PENDING')
        return self.step(T+dt.timedelta(seconds=330))

    def test_causal_signal_delays_entry_and_preserves_short_caps(self):
        result=self.admit()
        self.assertTrue(result[-1]);self.assertEqual(self.control['phase'],'ACTIVE')
        ep=self.control['episode'];self.assertLessEqual(ep['risk_unit'],25.)
        for s,p in self.s['positions'].items():
            self.assertLessEqual(abs(min(p['quantity'],0))*p['current_price'],10000*PARENT['short_caps'][s]+1e-8)
        self.assertTrue(all(p['quantity']<=0 for p in self.s['positions'].values()))

    def test_bad_window_and_late_slot_remain_neutral(self):
        bad=rows(int(T.timestamp()));bad[-1]['source_times']['BTCUSDT']=T.timestamp()+1
        self.step(T+dt.timedelta(seconds=1),panel=bad)
        self.assertNotEqual(self.control['phase'],'ENTRY_PENDING')
        self.assertIn('INVALID_CAUSAL',self.control['status'])

    def test_expired_entry_never_fills_retroactively(self):
        self.control['stages']={s:dict(index=2,at=T.timestamp(),day='2026-10-26') for s in self.control['initial_longs']}
        self.step(T+dt.timedelta(seconds=1),panel=rows(int(T.timestamp())))
        _,_,legs,_,increased=self.step(T+dt.timedelta(seconds=421))
        self.assertFalse(increased);self.assertEqual(legs,[])

    def test_risk_or_funding_veto_closes_longs_but_never_opens_short(self):
        self.control['stages']={s:dict(index=2,at=T.timestamp(),day='2026-10-26') for s in self.control['initial_longs']}
        self.s['risk_policy_state']['daily_entries']=1
        self.step(T+dt.timedelta(seconds=1),panel=rows(int(T.timestamp())))
        result=self.step(T+dt.timedelta(seconds=330),funding_ok=False)
        self.assertFalse(result[-1]);self.assertTrue(all(p['quantity']==0 for p in self.s['positions'].values()))

    def test_loss_intent_waits_for_next_book_and_close_keeps_no_new_long(self):
        self.admit()
        at=T+dt.timedelta(seconds=360)
        _,_,legs,_,_=self.step(at,book(at,price=103.))
        self.assertEqual(legs,[]);self.assertEqual(self.control['pending']['reason'],'LOSS_STOP')
        self.step(at+dt.timedelta(seconds=30),book(at+dt.timedelta(seconds=30),price=103.))
        self.assertTrue(all(p['quantity']==0 for p in self.s['positions'].values()))
        self.assertEqual(self.control['status'],'SHORT_CLOSED')
        self.step(at+dt.timedelta(seconds=60))
        self.assertTrue(all(p['quantity']==0 for p in self.s['positions'].values()))

    def test_partial_protective_cover_retries_remaining_only(self):
        self.admit();at=T+dt.timedelta(seconds=360)
        self.step(at,book(at,price=103.))
        self.step(at+dt.timedelta(seconds=30),book(at+dt.timedelta(seconds=30),price=103.,capacity=.5))
        self.assertEqual(self.control['phase'],'EXIT_PENDING');self.assertIsNotNone(self.control['pending'])
        self.step(at+dt.timedelta(seconds=60),book(at+dt.timedelta(seconds=60),price=103.))
        self.assertEqual(self.control['phase'],'NORMAL')
        self.assertTrue(all(p['quantity']==0 for p in self.s['positions'].values()))

    def test_timeout_remains_available_when_features_or_funding_are_missing(self):
        self.admit();at=dt.datetime.fromtimestamp(self.control['exit_due'],dt.timezone.utc)
        self.step(at,funding_ok=False)
        self.assertEqual(self.control['pending']['reason'],'MAX_HOLD')

    def test_unknown_real_minima_remain_unknown_and_only_synthetic_scope_is_used(self):
        record=book(T);old=copy.deepcopy(record)
        M.fill_plan(state(),record,{'BTCUSDT':-1.},protective_only=False,partial=False)
        self.assertEqual(record,old);self.assertIsNone(record['quotes']['BTCUSDT']['min_quantity'])

    def test_existing_exposure_breach_cannot_authorize_new_short_risk(self):
        self.s['positions']['BTCUSDT']['quantity']=100.
        self.assertEqual(M.entry_gate(self.s,T,PROTOCOL),'CURRENT_EXPOSURE_LIMIT')

    def test_inherited_recent_risk_increase_keeps_its_cooldown(self):
        self.s['risk_policy_state']['last_increase_at']=(T-dt.timedelta(hours=1)).isoformat()
        self.assertEqual(M.entry_gate(self.s,T,PROTOCOL),'RISK_INCREASE_COOLDOWN')

    def test_missing_independent_approval_cannot_schedule_an_entry(self):
        self.control['stages']={s:dict(index=2,at=T.timestamp(),day='2026-10-26') for s in self.control['initial_longs']}
        with patch.object(M,'read_signal_approval',side_effect=ValueError('NOT_ISSUED')):
            self.step(T+dt.timedelta(seconds=1),panel=rows(int(T.timestamp())))
        self.assertEqual(self.control['status'],'WAITING_INDEPENDENT_M1_APPROVAL')
        self.assertIsNone(self.control['pending']);self.assertIsNone(self.control['last_signal_slot'])
        self.step(T+dt.timedelta(seconds=60),panel=rows(int(T.timestamp())))
        self.assertEqual(self.control['phase'],'ENTRY_PENDING')

    def test_executor_identity_cannot_call_the_issuer_writer(self):
        with patch.object(M.os,'geteuid',return_value=30914),self.assertRaisesRegex(ValueError,'issuer_identity'):
            M.structural_issuer(dict(uids=dict(issuer=30913)))


class ApprovalReaderTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.root=Path(self.tmp.name);self.serial=0
    def tearDown(self):self.tmp.cleanup()
    def fixture(self,*,owner=30913,**changes):
        self.serial+=1;folder=self.root/str(self.serial);folder.mkdir()
        slot=int(T.timestamp());input_hash='a'*64
        value=dict(scope='ORIGINAL_STRUCTURAL_M1_SIGNAL_APPROVAL',status='APPROVE',account=M.ACCOUNT,
            protocol_id=M.PROTOCOL_ID,authority_id='test-authority',slot=slot,input_hash=input_hash,
            issued_at=(T+dt.timedelta(seconds=1)).isoformat(),expires_at=slot+420,issuer_uid=30913,
            real_orders_authorized=False)
        value.update(changes);value['approval_id']=M.digest(value)
        p=folder/'approvals.sqlite';db=sqlite3.connect(p)
        db.execute('CREATE TABLE structural_issuer_slots(protocol TEXT,slot INTEGER,payload TEXT)')
        db.execute('INSERT INTO structural_issuer_slots VALUES(?,?,?)',(M.PROTOCOL_ID,slot,json.dumps(value)))
        db.commit();db.close();p.chmod(0o640);os.chown(p,owner,30910)
        return dict(approvals=str(folder),uids=dict(issuer=30913)),slot,input_hash
    def test_valid_scoped_issuer_approval_is_read_only(self):
        c,slot,h=self.fixture();p=Path(c['approvals'])/'approvals.sqlite';before=p.read_bytes()
        value=M.read_signal_approval(c,'test-authority',slot,T+dt.timedelta(seconds=60),h)
        self.assertEqual(value['status'],'APPROVE');self.assertEqual(p.read_bytes(),before)
    def test_wrong_writer_account_or_input_cannot_authorize(self):
        for kwargs in [dict(owner=0),dict(account='other'),dict(input_hash='b'*64),dict(authority_id='other')]:
            c,slot,h=self.fixture(**kwargs)
            with self.subTest(kwargs=kwargs),self.assertRaises(ValueError):
                M.read_signal_approval(c,'test-authority',slot,T+dt.timedelta(seconds=60),h)
    def test_no_proposal_future_issue_and_expiry_are_rejected(self):
        for kwargs in [dict(status='NO_PROPOSAL'),dict(issued_at=(T+dt.timedelta(seconds=121)).isoformat()),dict(expires_at=int(T.timestamp())+421)]:
            c,slot,h=self.fixture(**kwargs)
            with self.subTest(kwargs=kwargs),self.assertRaises(ValueError):
                M.read_signal_approval(c,'test-authority',slot,T+dt.timedelta(seconds=60),h)
        c,slot,h=self.fixture()
        with self.assertRaises(ValueError):M.read_signal_approval(c,'test-authority',slot,T+dt.timedelta(seconds=421),h)


if __name__=='__main__':unittest.main()
