"""Real isolated control plane at the V13 fill and transaction boundaries."""
import contextlib
import copy
import dataclasses
import json
import sqlite3
from unittest.mock import Mock, patch

import pytest
from tests.unit_tests.ai_strategy_lab.test_paper_authorization import rig, activate, POLICY, NOW
from tests.unit_tests.ai_strategy_lab.test_v13_paper_v2 import state, market, quote, START, dt, runtime, decision
from octobot.ai_strategy_lab import paper_authorization as auth, paper_runtime_authorization as wiring
from octobot.ai_strategy_lab import v13_paper_v2 as paper

AT = START+dt.timedelta(minutes=15)


def wire(monkeypatch, rig, *, decision_claim=lambda: True):
    _, registry, identity = rig
    # Synthetic account + policy; no existing account is granted authorization.
    monkeypatch.setattr(wiring, 'entry_scope', lambda account, entry, **kwargs:
        registry.entry(identity, entry, POLICY, decision_claim))


def execute(account=None, quotes=None):
    return paper.process_market(account or state(), market(AT), quotes or {'BTCUSDT':quote(AT)}, AT)


@pytest.mark.parametrize('status,code', [('kill','global_kill_active'), ('absent','authorization_missing'),
    ('revoked','authorization_revoked'), ('expired','authorization_expired'),
    ('corrupt','authorization_malformed'), ('storage','authorization_storage_failure')])
def test_denied_fill_boundary_and_reopen(monkeypatch, rig, status, code):
    admin, registry, identity = rig
    if status!='absent': activate(rig)
    else: admin.set_kill(False)
    if status=='kill': admin.set_kill(True)
    if status=='revoked': admin.revoke(identity.authorization_id)
    if status=='expired': registry.clock=lambda: NOW+dt.timedelta(days=2); doc=json.loads((admin.root/'registry.json').read_text()); doc['authorizations'][identity.authorization_id]['expires_at']=(NOW+dt.timedelta(days=1)).isoformat(); admin._write(doc)
    if status=='corrupt': (admin.root/'registry.json').write_text('{}')
    if status=='storage': registry.audit=registry.audit.parent/'missing'/'audit.sqlite'
    wire(monkeypatch, rig)
    with patch.object(paper, 'apply_fill', wraps=paper.apply_fill) as execution:
        for _ in range(2):
            result, fills, _, _ = execute()
            assert not fills and result['risk']['reason']==code
        execution.assert_not_called()


def test_all_stages_pass_only_with_explicit_isolated_grant(monkeypatch, rig):
    activate(rig); wire(monkeypatch, rig)
    with patch.object(paper, 'apply_fill', wraps=paper.apply_fill) as execution:
        result, fills, _, _ = execute()
        assert len(fills)==1
        execution.assert_called_once()
    assert result['risk']['global_authorization']['authorization_id']=='test-grant'
    assert not result['risk']['current']['breaches']
    assert result['risk']['market_checks']


@pytest.mark.parametrize('veto', ['exposure','market','decision'])
def test_interaction_with_other_gates_never_fills(monkeypatch, rig, veto):
    activate(rig); wire(monkeypatch, rig, decision_claim=lambda: veto!='decision')
    account=state(targets={'BTCUSDT':.315 if veto=='exposure' else .1})
    q=quote(AT)
    if veto=='market': q['asks'][0]['price']=150.
    with patch.object(paper,'apply_fill',wraps=paper.apply_fill) as execution:
        result,fills,_,_=execute(account,{'BTCUSDT':q})
        execution.assert_not_called()
    assert not fills
    assert result['risk']['reason']=={'exposure':'projected_exposure_limit','market':'spread_limit','decision':'decision_authorization_invalid'}[veto]


@pytest.mark.parametrize('target', [0.,.1])
def test_kill_does_not_freeze_safe_reductions(monkeypatch,rig,target):
    activate(rig);rig[0].set_kill(True);wire(monkeypatch,rig)
    account=state(targets={'BTCUSDT':target})
    account['positions']['BTCUSDT']=dict(paper.new_position(),quantity=20.,entry_price=100.,current_price=100.)
    result,fills,_,_=execute(account)
    assert len(fills)==1 and fills[0]['quantity']<0
    assert result['positions']['BTCUSDT']['quantity']<=10.


def test_kill_does_not_manufacture_liquidity_for_close(monkeypatch,rig):
    activate(rig);rig[0].set_kill(True);wire(monkeypatch,rig)
    account=state(targets={})
    account['positions']['BTCUSDT']=dict(paper.new_position(),quantity=20.,entry_price=100.,current_price=100.)
    q=quote(AT);q['bids'][0]['base_quantity']=1.
    with patch.object(paper,'apply_fill',wraps=paper.apply_fill) as execution:
        result,fills,_,_=execute(account,{'BTCUSDT':q});execution.assert_not_called()
    assert not fills and result['risk']['reason']=='insufficient_depth'


def test_default_binding_cannot_make_policy_complete_from_health(monkeypatch,rig):
    admin,registry,_=rig
    admin.set_kill(False)
    identity,policy=wiring.binding('v13-paper-v2')
    assert any(policy[k] is None for k in auth.REQUIRED_CONTROLS)
    identity = dataclasses.replace(identity, account='fixture-v13', strategy='fixture-v13')
    monkeypatch.setattr(wiring, 'binding', lambda *a, **k: (identity, policy))
    # Hypothetical explicit test grant STILL cannot fill missing policy/gates.
    admin.grant(identity,valid_from=NOW.isoformat())
    monkeypatch.setattr(auth,'Registry',lambda:registry)
    account=state();account.update(paper_orders_authorized=True,health='healthy',container='running')
    with patch.object(paper,'apply_fill',wraps=paper.apply_fill) as execution:
        result,fills,_,_=execute(account);execution.assert_not_called()
    assert not fills and result['risk']['reason']=='risk_policy_incomplete'


def test_global_lease_spans_database_commit(monkeypatch,rig,runtime):
    activate(rig);wire(monkeypatch,rig)
    current,database,_,run,advance=runtime
    run();advance(AT)
    original=paper.init_db
    observed=[]
    class Connection:
        def __init__(self,db):self.db=db
        def __getattr__(self,name):return getattr(self.db,name)
        def __enter__(self):self.db.__enter__();return self
        def __exit__(self,*args):
            # Tick's atomic commit must still exclude activation of kill.
            try:rig[0].set_kill(True)
            except BlockingIOError:observed.append('lease-held')
            else:observed.append('UNSAFE')
            return self.db.__exit__(*args)
    monkeypatch.setattr(paper,'init_db',lambda path:Connection(original(path)))
    result=run(AT+dt.timedelta(seconds=2))
    assert result['order_count']==1 and observed==['lease-held']
    rig[0].set_kill(True)
    with sqlite3.connect(database) as db:assert db.execute('SELECT COUNT(*) FROM orders').fetchone()[0]==1


def test_policy_or_lineage_changed_in_source_requires_new_binding(tmp_path):
    source=tmp_path/'lineage.json';source.write_text('version one')
    first,_=wiring.binding('v13-paper-v2',context_paths=[source])
    source.write_text('version two')
    second,_=wiring.binding('v13-paper-v2',context_paths=[source])
    assert first.lineage_hash!=second.lineage_hash


def test_entry_claim_remains_burned_after_exposure_veto(monkeypatch,rig):
    activate(rig);wire(monkeypatch,rig)
    with patch.object(paper,'apply_fill',wraps=paper.apply_fill) as execution:
        first=execute(state(targets={'BTCUSDT':.315}))[0]
        second=execute()[0]
        execution.assert_not_called()
    assert first['risk']['reason']=='projected_exposure_limit'
    assert second['risk']['reason']=='entry_already_claimed'
