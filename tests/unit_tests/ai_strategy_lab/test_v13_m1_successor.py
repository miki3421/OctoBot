"""Economic invariants of the single-account successor; synthetic inputs only."""
import copy
import datetime as dt
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from unittest.mock import Mock
from octobot.ai_strategy_lab import v13_m1_successor as s
from octobot.ai_strategy_lab import v13_m1_weekly as w
from octobot.ai_strategy_lab import v13_m1_paper as base
from tests.unit_tests.ai_strategy_lab.test_v13_m1_weekly import science,full_market
from tests.unit_tests.ai_strategy_lab.test_v13_m1_paper import T

SIX=['AAVEUSDT','BCHUSDT','BTCUSDT','DOTUSDT','LTCUSDT','NEARUSDT']


def weak(at=T):
    sc=science(at)
    for series in sc['bars'].values():
        series[0]['close']=80.
        series[-31]['close']=120.
        series[-1]['close']=100.
    sc['snapshot_id']=w.digest({k:v for k,v in sc.items() if k!='snapshot_id'})
    return sc


def fixture(at=T):
    m=full_market(at)
    state=dict(initial_equity=10000.,positions={v:dict(base.paper.new_position(),quantity=10.,entry_price=100.,current_price=m['quotes'][v]['mark_price']) for v in SIX})
    caps={v:(.04 if v in SIX else 0.) for v in w.POOL}
    parent=dict(account='fixture-m1',parent_proposal_id='a'*64,short_caps=caps)
    parent['proposal_id']=w.digest(parent)
    p=s.proposal(parent,state,weak(at),m,at.isoformat())
    policy=s.policy(p,at.isoformat(),'fixture-owner','direct_operator_instruction')
    return p,policy,state,m


class SuccessorTests(unittest.TestCase):
    def test_six_initial_reductions_and_no_budget_redistribution(self):
        p,policy,state,m=fixture()
        self.assertEqual(p['affected'],SIX)
        self.assertEqual(p['short_caps'],p['short_reference_caps'])
        self.assertEqual(p['summary']['short_before'],p['summary']['short_after'])
        self.assertEqual(p['summary']['long_after'],p['summary']['long_before']/2)
        self.assertEqual(set(policy['quantity_ceilings'].values()),{5.})

    def test_signal_error_or_recovery_cannot_become_first_reduction(self):
        p,_,state,m=fixture()
        parent=dict(account=p['account'],parent_proposal_id='a'*64,short_caps=p['short_caps']);parent['proposal_id']=w.digest(parent)
        with self.assertRaises(ValueError):s.proposal(parent,state,science(),m,T.isoformat())
        sc=weak();del sc['bars']['LTCUSDT'];sc['snapshot_id']=w.digest({k:v for k,v in sc.items() if k!='snapshot_id'})
        with self.assertRaises(ValueError):s.proposal(parent,state,sc,m,T.isoformat())

    def test_partial_execution_does_not_repeat_the_halving(self):
        _,p,state,_=fixture()
        state['positions']['BTCUSDT']['quantity']=8.
        u,g,events=s.advance(p,{},state,weak(),T.isoformat())
        self.assertEqual(u['quantity_ceilings']['BTCUSDT'],5.)
        self.assertIsNone(g['BTCUSDT']['completed_at']);self.assertEqual(events,[])
        u2,g2,e2=s.advance(u,copy.deepcopy(g),state,weak(),(T+dt.timedelta(seconds=20)).isoformat())
        self.assertEqual(u2,u);self.assertEqual(e2,[])

    def completed(self):
        _,p,state,m=fixture()
        for pos in state['positions'].values():pos['quantity']=5.
        p,g,_=s.advance(p,{},state,weak(),T.isoformat())
        return p,g,state,m

    def test_actual_completion_then_24h_and_a_distinct_day_are_required(self):
        p,g,state,_=self.completed()
        at=T+dt.timedelta(hours=23)
        u,_,events=s.advance(p,g,state,weak(at),at.isoformat());self.assertEqual(events,[])
        at=T+dt.timedelta(days=1)
        u,g,events=s.advance(p,g,state,weak(at),at.isoformat())
        self.assertEqual(len(events),6);self.assertEqual(set(u['quantity_ceilings'].values()),{2.5})
        self.assertEqual(u['short_caps'],p['short_caps'])
        u2,g2,e2=s.advance(u,g,state,weak(at), (at+dt.timedelta(seconds=20)).isoformat())
        self.assertEqual(e2,[]);self.assertEqual(u2,u)

    def test_third_stage_closes_the_remainder_and_is_restart_idempotent(self):
        p,g,state,_=self.completed();at=T+dt.timedelta(days=1)
        p,g,_=s.advance(p,g,state,weak(at),at.isoformat())
        for pos in state['positions'].values():pos['quantity']=2.5
        p,g,_=s.advance(p,g,state,weak(at),at.isoformat())
        at+=dt.timedelta(days=1)
        p,g,events=s.advance(p,g,state,weak(at),at.isoformat())
        self.assertEqual(set(p['quantity_ceilings'].values()),{0.});self.assertEqual(len(events),6)
        for pos in state['positions'].values():pos['quantity']=0.
        p2,g2,e2=s.advance(p,g,state,weak(at),at.isoformat())
        self.assertEqual(p2,p);self.assertEqual(e2,[])

    def test_recovery_holds_the_ceiling_but_never_rebuys(self):
        p,g,state,m=self.completed();at=T+dt.timedelta(days=1)
        u,g,events=s.advance(p,g,state,science(at),at.isoformat())
        self.assertEqual(events,[]);self.assertEqual(u['quantity_ceilings'],p['quantity_ceilings'])
        for pos in state['positions'].values():pos['quantity']=1.
        q,u=w.targets(state,u,{v:.3 for v in SIX},m['quotes'],kind='DAILY')
        self.assertTrue(all(v<=1. for v in q.values()))

    def test_missing_daily_history_is_not_a_forced_exit(self):
        p,g,state,_=self.completed();at=T+dt.timedelta(days=1);sc=weak(at)
        del sc['bars']['LTCUSDT'];sc['snapshot_id']=w.digest({k:v for k,v in sc.items() if k!='snapshot_id'})
        u,g,events=s.advance(p,g,state,sc,at.isoformat())
        self.assertEqual(u['quantity_ceilings']['LTCUSDT'],5.)
        self.assertEqual(g['LTCUSDT']['status'],'WAITING_DATA')
        self.assertNotIn('LTCUSDT',[e['symbol'] for e in events])

    def test_stale_and_future_days_fail_closed(self):
        p,g,state,_=self.completed()
        with self.assertRaises(ValueError):s.advance(p,g,state,weak(),(T+dt.timedelta(days=2)).isoformat())
        with self.assertRaises(ValueError):s.advance(p,g,state,weak(T+dt.timedelta(days=1)),T.isoformat())

    def test_reentry_cannot_restore_flat_longs_but_short_budget_remains_usable(self):
        _,p,state,m=fixture()
        for pos in state['positions'].values():pos['quantity']=0.
        q,p2=w.targets(state,p,{v:.2 for v in SIX},m['quotes'],kind='REENTRY')
        self.assertTrue(all(v==0 for v in q.values()))
        self.assertTrue(all(v==0 for v in p2['quantity_ceilings'].values()))
        q,p3=w.targets(state,p2,{v:.2 for v in SIX},m['quotes'],kind='M1_ENTRY',short_reference=p2['short_caps'])
        self.assertTrue(all(v<0 for v in q.values()))
        self.assertEqual(p3['short_caps'],p['short_caps'])

    def test_web_decision_requires_exact_replacement_component(self):
        from .test_v13_m1_weekly import broker
        p,_,_,_=fixture()
        with tempfile.TemporaryDirectory() as folder:
            store=broker.Store(Path(folder)/'decisions.sqlite',p['account'])
            try:
                with self.assertRaises(ValueError):store.record(p,action='APPROVE',exclude_short=[],components=['LONG_MAINTENANCE'],at=T.isoformat())
                d=store.record(p,action='APPROVE',exclude_short=[],components=list(s.COMPONENTS),at=T.isoformat())
                pol=w.approved_policy(p,d,0,T.isoformat())
                self.assertEqual(pol['short_caps'],p['short_caps'])
                self.assertEqual(pol['authority_kind'],'authenticated_operator')
            finally:store.close()

    def test_operator_authority_binds_account_backup_and_root_custody(self):
        p,_,_,_=fixture()
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);proposal=root/'proposal.json';proposal.write_text(json.dumps(p));proposal.chmod(0o440)
            auth=root/'authority.json';up=root/'upgrade.json'
            a=dict(scope='MANUAL_OPERATOR_M1_STRATEGY_REPLACEMENT',account=p['account'],proposal_id=p['proposal_id'],operator_reference='CONTROL FIXTURE ONLY',authorized_at=T.isoformat(),quantities=p['initial_quantities'],backup_sha256='a'*64)
            a['activation_id']=w.digest(a);auth.write_text(json.dumps(a));auth.chmod(0o440)
            up.write_text(json.dumps(dict(scope='M1_GRADUAL_LONG_SHORT_V3',account=p['account'],backup_sha256='a'*64)));up.chmod(0o440)
            cfg=dict(runtime_upgrade=str(up),successor=dict(authority=str(auth),proposal=str(proposal),proposal_sha256=base.shared.sha(proposal)))
            with patch.object(base.source,'now',return_value=T):
                self.assertEqual(s.authority(cfg,p['account'])[0],p)
                with self.assertRaises(ValueError):s.authority(cfg,'another-account')
                up.chmod(0o640);up.write_text(json.dumps(dict(scope='M1_GRADUAL_LONG_SHORT_V3',account=p['account'],backup_sha256='b'*64)))
                with self.assertRaises(ValueError):s.authority(cfg,p['account'])
                os.chown(auth,30943,-1)
                with self.assertRaises(ValueError):s.authority(cfg,p['account'])

    def test_active_manual_replacement_and_stale_old_tab_cannot_create_another_decision(self):
        from octobot.ai_strategy_lab import v13_m1_approval_broker as broker
        p,_,_,_=fixture()
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);verifier=root/'verifier.json';verifier.write_text('{}');projection=root/'projection.json'
            b=broker.Broker.__new__(broker.Broker);b.failures=[];b.store=Mock()
            b.c=dict(web_peer_uids=[42],verifier=str(verifier),projection=str(projection),runner_uid=30943,
                     successor_only=True,replacement_proposal_id=p['proposal_id'])
            request=dict(operation='decision',password='CONTROL FIXTURE ONLY',proposal_id=p['proposal_id'],action='APPROVE')
            value=dict(proposal=p,account=p['account'],successor={'proposal_id':p['proposal_id']},proposal_status='ACTIVE_SUCCESSOR')
            b.c['account']=p['account'];projection.write_text(json.dumps(value))
            with patch.object(broker,'password_valid',return_value=True),patch.object(broker,'safe_file',side_effect=lambda path,uid:Path(path)):
                with self.assertRaisesRegex(ValueError,'already_active'):b.handle(request,42)
                value['proposal']['version']='m1-long-maintenance-v2';projection.write_text(json.dumps(value))
                with self.assertRaisesRegex(ValueError,'superseded'):b.handle(request,42)
            b.store.record.assert_not_called()


if __name__=='__main__':unittest.main()
