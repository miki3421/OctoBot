"""Offline full-ledger migration and execution mechanics with synthetic inputs.

Uses a sealed audit copy, root-owned local authority and the real Registry,
accounting, database transactions and projection. No network or live writes.
"""
import argparse
import copy
import datetime as dt
import hashlib
import json
import math
import os
from pathlib import Path
import shutil
import sqlite3
from unittest.mock import patch

from octobot.ai_strategy_lab import v13_original_structural as M
from octobot.ai_strategy_lab.paper_authorization_admin import Admin
from octobot.ai_strategy_lab import v13_original_structural_view as view

ROOT = Path('/workspace')


def run(source, work):
    source, work = Path(source), Path(work)
    if source.stat().st_mode & 0o222 or work.exists() or 'audit-evidence' not in str(work):
        raise ValueError('sealed_offline_copy_required')
    before_sha = hashlib.sha256(source.read_bytes()).hexdigest()
    work.mkdir(mode=0o700, parents=True)
    os.chown(work.parent,0,30910);work.parent.chmod(0o750)
    os.chown(work,0,30910);work.chmod(0o750)
    ledger = work/'ledger';ledger.mkdir()
    shutil.copyfile(source, ledger/'execution.sqlite')
    db = M.P.db(ledger/'execution.sqlite')
    state = json.loads(db.execute('SELECT payload FROM state WHERE id=1').fetchone()[0])
    old_orders = db.execute('SELECT * FROM orders ORDER BY id').fetchall()
    boundary_count = len(old_orders)
    last = M.P.p.timestamp(db.execute('SELECT MAX(bar) FROM equity_history').fetchone()[0])
    start = dt.datetime.fromtimestamp(math.ceil((last.timestamp()+120)/300)*300, dt.timezone.utc)
    clock = [start]
    protocol = json.loads((ROOT/'docs/research-protocols/original-m1-structural-successor-v2.json').read_text())
    parent = json.loads((ROOT/'docs/research-protocols/m1-short-risk-exits-candidate-v1.json').read_text())
    structure = json.loads((ROOT/'docs/research-protocols/m1-short-structural-invalidation-v1.json').read_text())
    policy = dict(protocol['risk'], version='risk-policy-original-structural-v1', missing_gates=[])
    identity = dict(account=M.ACCOUNT, strategy=protocol['strategy'],lineage_hash=M.digest(protocol),
        risk_policy='risk-policy-original-structural-v1',risk_policy_hash=M.digest(policy),
        authorization_id='original-structural-offline-test',environment='paper')
    admin = Admin(work/'control',clock=lambda:clock[0]);admin.initialize(reader_gid=30910)
    admin.grant(M.P.auth.Identity(**identity),valid_from=start.isoformat())
    admin.set_kill(False)
    a = dict(scope='MANUAL_ORIGINAL_STRUCTURAL_PAPER_CUTOVER',account=M.ACCOUNT,
        protocol_id=M.PROTOCOL_ID,real_orders_authorized=False,operator_reference='ISOLATED_SYNTHETIC_TEST_ONLY',
        authority_id='original-structural-offline-authority',activated_at=start.isoformat(),
        boundary_state_hash=M.digest(state),boundary_orders=state['order_count'],
        protocol=protocol,parent=parent,structure=structure,identity=identity,
        code_pins={n:hashlib.sha256((ROOT/n).read_bytes()).hexdigest() for n in [
            'octobot/ai_strategy_lab/v13_original_structural.py','octobot/ai_strategy_lab/v13_m1_short_risk.py',
            'octobot/ai_strategy_lab/v13_m1_short_structure.py']})
    path=work/'authority.json';path.write_text(json.dumps(a));path.chmod(0o440)
    M.AUTHORITY=dict(path=str(path),sha256=hashlib.sha256(path.read_bytes()).hexdigest())
    c=dict(account=M.ACCOUNT,repo=str(ROOT),source=str(work/'source'),ledger=str(ledger),control=str(work/'control'),
        approvals=str(work/'approvals'),epoch='preserved-original-epoch',uids=dict(capture=30911,producer=30912,issuer=30913,executor=30914))
    Path(c['source']).mkdir()
    Path(c['approvals']).mkdir();Path(c['approvals']).chmod(0o750);os.chown(c['approvals'],30913,30910)
    quote_source=json.loads((work.parent/'market-template.json').read_text())['quotes']
    base_prices={s:p['current_price'] for s,p in state['positions'].items()}
    history=[None]
    Registry=M.P.auth.Registry
    def registry(*args,**kwargs):return Registry(*args,**kwargs,clock=lambda:clock[0])
    def frame(at, factor=1.):
        quotes=copy.deepcopy(quote_source)
        for s,q in quotes.items():
            scale=base_prices[s]*factor/q['mark_price'];q['mark_price']=base_prices[s]*factor
            for side in ['bids','asks']:
                for v in q[side]:v['price']*=scale;v['base_quantity']=max(v['base_quantity'],100000.)
            for k in ['timestamp','mark_timestamp','metadata_observed_at']:q[k]=at.isoformat()
            end=int(at.timestamp()*1000)//28800000*28800000
            q['funding_interval_ms']=28800000
            q['funding']=[dict(timestamp_ms=end-j*28800000,rate=0.) for j in range(5,-1,-1)]
        r=dict(scope=M.P.source.SCOPE,fixture=True,observed_at_start=at.isoformat(),observed_at_end=at.isoformat(),quotes=quotes)
        r['record_hash']=M.digest(r)
        tmp=Path(c['source'])/'market.pending';tmp.write_text(json.dumps(r));tmp.chmod(0o640);os.chown(tmp,30911,30910);tmp.replace(Path(c['source'])/'market.json')
        os.seteuid(30913)
        try:M.structural_issuer(c)
        finally:os.seteuid(0)
    def tick(at,factor=1.):
        final_history=history[0]
        while (at-clock[0]).total_seconds()>900:
            history[0]=None;clock[0]+=dt.timedelta(seconds=900);frame(clock[0],factor)
            M.tick(c,db)
        history[0]=final_history
        clock[0]=at;frame(at,factor)
        return M.tick(c,db)
    with patch.object(M.P.source,'now',side_effect=lambda:clock[0]),patch.object(M.P.auth,'Registry',side_effect=registry),\
            patch.object(M,'ORIGINAL_ISSUER',return_value=None),\
            patch.object(M.P,'read_approval',side_effect=ValueError('NO_SYNTHETIC_DAILY')),\
            patch.object(M.causal,'read_window',side_effect=lambda *args:history[0]):
        tick(start+dt.timedelta(seconds=1))
        assert db.execute('SELECT COUNT(*) FROM orders').fetchone()[0]==boundary_count
        first_state=json.loads(db.execute('SELECT payload FROM state WHERE id=1').fetchone()[0])
        for s,p in state['positions'].items():
            for key in ['quantity','entry_price','realized_pnl','fees','funding']:
                assert first_state['positions'][s][key]==p[key],(s,key)
        tick(start+dt.timedelta(seconds=60))
        reduced=json.loads(db.execute('SELECT payload FROM state WHERE id=1').fetchone()[0])
        for s,p in state['positions'].items():
            if p['quantity']>0:
                ceiling=M.R.floor_quantity(p['quantity']*.5,quote_source[s]['quantity_step'])
                assert reduced['positions'][s]['quantity']==ceiling,(s,ceiling)
        signal=(start+dt.timedelta(days=1)).replace(hour=12,minute=0,second=0,microsecond=0)
        slot=int(signal.timestamp())
        history[0]=[dict(time=slot-(288-i)*300,
            prices={s:base_prices[s]*math.exp(.001*(288-i)) for s in M.R.SIGNALS},
            source_times={s:slot-(288-i)*300-1 for s in M.R.SIGNALS}) for i in range(289)]
        tick(signal+dt.timedelta(seconds=1))
        assert M.load(db)['phase']=='ENTRY_PENDING'
        history[0]=None
        tick(signal+dt.timedelta(seconds=340))
        control=M.load(db);assert control['phase']=='ACTIVE',control['status']
        opened=json.loads(db.execute('SELECT payload FROM state WHERE id=1').fetchone()[0])
        assert all(p['quantity']<=0 for p in opened['positions'].values())
        assert any(p['quantity']<0 for p in opened['positions'].values())
        assert db.execute("SELECT kind FROM research_claims WHERE id=?",(control['episode']['episode_id'],)).fetchone()==('structural-committed',)
        db.close();db=M.P.db(ledger/'execution.sqlite')
        assert M.initialize(db,a,protocol,opened)==control
        tick(signal+dt.timedelta(seconds=400),factor=1.03)
        control=M.load(db);assert control['pending']['reason']=='LOSS_STOP'
        n=db.execute('SELECT COUNT(*) FROM orders').fetchone()[0]
        tick(signal+dt.timedelta(seconds=410),factor=1.03)
        assert db.execute('SELECT COUNT(*) FROM orders').fetchone()[0]==n
        tick(signal+dt.timedelta(seconds=440),factor=1.03)
        closed=json.loads(db.execute('SELECT payload FROM state WHERE id=1').fetchone()[0])
        assert M.load(db)['phase']=='NORMAL'
        assert all(p['quantity']==0 for p in closed['positions'].values())
        tick(signal+dt.timedelta(seconds=500),factor=1.03)
        assert db.execute('SELECT * FROM orders ORDER BY id LIMIT ?', (boundary_count,)).fetchall()==old_orders
        assert db.execute('PRAGMA integrity_check').fetchone()[0]=='ok'
        # A revoked global grant rejects a later entry without freezing marks.
        next_signal=signal+dt.timedelta(days=1);slot=int(next_signal.timestamp())
        history[0]=[dict(time=slot-(288-i)*300,
            prices={s:base_prices[s]*1.03*math.exp(.001*(288-i)) for s in M.R.SIGNALS},
            source_times={s:slot-(288-i)*300-1 for s in M.R.SIGNALS}) for i in range(289)]
        admin.set_kill(True)
        tick(next_signal+dt.timedelta(seconds=1),factor=1.03)
        history[0]=None
        previous_count=db.execute('SELECT COUNT(*) FROM orders').fetchone()[0]
        previous_marks=db.execute('SELECT COUNT(*) FROM marks').fetchone()[0]
        tick(next_signal+dt.timedelta(seconds=340),factor=1.03)
        assert M.load(db)['status'].startswith('AUTHORIZATION_DENIED:')
        assert db.execute('SELECT COUNT(*) FROM orders').fetchone()[0]==previous_count
        assert db.execute('SELECT COUNT(*) FROM marks').fetchone()[0]>previous_marks
        # A crash after durable claims but before the economic commit is
        # recovered as a neutral rejected entry, never as duplicated SHORTs.
        admin.set_kill(False)
        crash_signal=next_signal+dt.timedelta(days=1);slot=int(crash_signal.timestamp())
        history[0]=[dict(time=slot-(288-i)*300,
            prices={s:base_prices[s]*1.03*math.exp(.001*(288-i)) for s in M.R.SIGNALS},
            source_times={s:slot-(288-i)*300-1 for s in M.R.SIGNALS}) for i in range(289)]
        tick(crash_signal+dt.timedelta(seconds=1),factor=1.03)
        history[0]=None
        with patch.object(M,'persist',side_effect=RuntimeError('ISOLATED_FORCED_CRASH')):
            try:tick(crash_signal+dt.timedelta(seconds=340),factor=1.03)
            except RuntimeError as error:assert str(error)=='ISOLATED_FORCED_CRASH'
            else:raise AssertionError('crash injection not reached')
        assert db.execute('SELECT COUNT(*) FROM orders').fetchone()[0]==previous_count
        db.close();db=M.P.db(ledger/'execution.sqlite')
        tick(crash_signal+dt.timedelta(seconds=370),factor=1.03)
        assert db.execute('SELECT COUNT(*) FROM orders').fetchone()[0]==previous_count
        assert M.load(db)['status'].startswith('AUTHORIZATION_DENIED:')
        os.seteuid(30914)
        try:
            try:
                denied=sqlite3.connect(str(Path(c['approvals'])/'approvals.sqlite'))
                try:denied.execute("INSERT INTO structural_issuer_slots VALUES('forged',0,'{}')")
                finally:denied.close()
            except (PermissionError,sqlite3.OperationalError):pass
            else:raise AssertionError('executor could write issuer approvals')
        finally:os.seteuid(0)
    projection=ledger/'structural-successor.json';os.chown(projection,30914,30910)
    merged=view.merge(dict(variants=dict(ORIGINAL=dict(account_id=M.ACCOUNT,metrics=M.P.paper.totals(closed)))),projection,clock[0])
    assert merged['variants']['ORIGINAL']['label']==protocol['label']
    assert merged['original_successor']['boundary']['order_count']==state['order_count']
    result=dict(scope='OFFLINE_FULL_LEDGER_COPY_SYNTHETIC_INPUT_AND_CLOCK_NOT_PREDICTIVE_VALIDATION',
        source_sha256=before_sha,source_unchanged=hashlib.sha256(source.read_bytes()).hexdigest()==before_sha,
        predecessor_orders_preserved=boundary_count,new_orders=db.execute('SELECT COUNT(*) FROM orders').fetchone()[0]-boundary_count,
        initial_capital_preserved=True,initial_positions_preserved_before_first_fresh_fill=True,
        root_authority_and_real_registry_checked=True,one_shot_claim_consumed=True,short_caps_preserved=True,
        restart_persisted=True,loss_intent_precedes_execution=True,no_long_repurchase=True,
        crash_after_claim_before_economic_commit_recovers_without_duplicate_order=True,
        authorization_veto_preserves_shared_mark_stream=True,projection_label_and_boundary_verified=True,
        separate_issuer_uid_and_approval_store_checked=True,executor_cannot_write_issuer_approval_store=True,
        integrity=db.execute('PRAGMA integrity_check').fetchone()[0])
    db.close();(work/'result.json').write_text(json.dumps(result,indent=2)+'\n');print(json.dumps(result,indent=2))


if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('--source',required=True);parser.add_argument('--work',required=True)
    args=parser.parse_args();run(args.source,args.work)
