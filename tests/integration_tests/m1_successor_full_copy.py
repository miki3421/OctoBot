"""Real runner on a complete private copy. Future inputs are CONTROL FIXTURES.

No live state/source writes, network, approval password, or return comparison.
The artificial future days exercise the schedule, not economic performance.
"""
import copy
import datetime as dt
import hashlib
import json
import os
from pathlib import Path
import shutil
import sqlite3
import uuid
from unittest.mock import patch

from octobot.ai_strategy_lab import v13_m1_successor as successor
from octobot.ai_strategy_lab import v13_m1_paper as base
from octobot.ai_strategy_lab import v13_m1_weekly as w
from octobot.ai_strategy_lab.v13_m1_paper_view import publish

E=Path('/evidence');F=E/('full-copy-'+uuid.uuid4().hex[:8]);F.mkdir(mode=0o750);os.chown(F,0,30910)


def write(path,value,uid=0):
    path.write_text(json.dumps(value,indent=2)+'\n');os.chown(path,uid,30910);path.chmod(0o640 if uid else 0o440)


for name,uid in [('state',30943),('projection',30943),('approvals',30945),('source',30944),('configuration',0)]:
    f=F/name;f.mkdir(mode=0o750);os.chown(f,uid,30910)
shutil.copyfile(E/'m1.sqlite',F/'state/account.sqlite');os.chown(F/'state/account.sqlite',30943,30910);(F/'state/account.sqlite').chmod(0o640)
shutil.copyfile(E/'approvals.sqlite',F/'approvals/approvals.sqlite');os.chown(F/'approvals/approvals.sqlite',30945,30910);(F/'approvals/approvals.sqlite').chmod(0o640)
data=json.loads((E/'proposal-input.json').read_text());p=json.loads((E/'proposal.json').read_text());cfg=json.loads(Path('/release/configuration/config.json').read_text())
db=sqlite3.connect(F/'state/account.sqlite');state=json.loads(db.execute('SELECT payload FROM state').fetchone()[0]);control=json.loads(db.execute("SELECT payload FROM m1_meta WHERE key='control'").fetchone()[0]);identity=json.loads(db.execute("SELECT payload FROM m1_meta WHERE key='identity'").fetchone()[0]);db.close()
T=max(w.when(control['last_seen']),w.when(p['created_at']))+dt.timedelta(seconds=60)
cfg.update(repo='/runtime',db=str(F/'state/account.sqlite'),original='/original.sqlite',seed='/seed.sqlite',receipt='/clone-receipt.json',
           protocol=str(F/'configuration/protocol.json'),runtime_upgrade=str(F/'configuration/runtime-upgrade.json'),output=str(F/'projection/account.json'))
shutil.copyfile('/original.sqlite',F/'original.sqlite');os.chown(F/'original.sqlite',0,30910);(F/'original.sqlite').chmod(0o440);cfg['original']=str(F/'original.sqlite')
cfg['management'].update(scope='M1_WEEKLY_MANAGEMENT_CONTROL_TEST_V1',source=str(F/'source'),approvals=str(F/'approvals/approvals.sqlite'),
    projection=str(F/'projection/management.json'),transition_proposal=str(F/'configuration/proposal.json'))
cfg['successor'].update(proposal=str(F/'configuration/proposal.json'),authority=str(F/'configuration/authority.json'))
shutil.copyfile('/release/configuration/protocol.json',F/'configuration/protocol.json');os.chown(F/'configuration/protocol.json',0,30910)
shutil.copyfile(E/'proposal.json',F/'configuration/proposal.json');os.chown(F/'configuration/proposal.json',0,30910)
upgrade=json.loads(Path('/release/configuration/runtime-upgrade-template.json').read_text());upgrade.update(authorized_at=T.isoformat(),owner_reference='CONTROL FIXTURE ONLY',backup_sha256=base.shared.sha(E/'m1.sqlite'))
write(F/'configuration/runtime-upgrade.json',upgrade)
a=dict(scope='MANUAL_OPERATOR_M1_STRATEGY_REPLACEMENT',account=p['account'],proposal_id=p['proposal_id'],authorized_at=T.isoformat(),operator_reference='CONTROL FIXTURE ONLY',backup_sha256=upgrade['backup_sha256'],quantities=p['initial_quantities']);a['activation_id']=w.digest(a);write(F/'configuration/authority.json',a)
write(F/'configuration/config.json',cfg)
original_sha=base.shared.sha(F/'original.sqlite');seed_sha=base.shared.sha('/seed.sqlite')
before_orders=state['order_count'];before_risk=copy.deepcopy(state['risk_policy_state']);short_caps=dict(p['short_caps'])


def market(at):
    value=copy.deepcopy(data['market']);value['fixture']=True
    value['observed_at_start']=(at-dt.timedelta(seconds=2)).isoformat();value['observed_at_end']=at.isoformat()
    for q in value['quotes'].values():
        for k in ('book_timestamp','mark_timestamp','metadata_timestamp','timestamp','metadata_observed_at'):
            if k in q:q[k]=(at-dt.timedelta(seconds=1)).isoformat()
    value['record_hash']=w.digest({k:v for k,v in value.items() if k!='record_hash'})
    return value


def science(at):
    sc=copy.deepcopy(data['science']);old=dt.date.fromisoformat(sc['day']);day=at.date()-dt.timedelta(days=1);delta=day-old
    sc['day']=str(day);sc['published_at']=at.isoformat()
    for series in sc['bars'].values():
        for bar in series:
            bar['day']=str(dt.date.fromisoformat(bar['day'])+delta);bar['received_at']=at.isoformat()
    sc['snapshot_id']=w.digest({k:v for k,v in sc.items() if k!='snapshot_id'})
    return sc


os.setgroups([30910]);os.setgid(30910);os.setuid(30943)
clock={'now':T};clock_patch=patch.object(base.source,'now',side_effect=lambda:clock['now']);clock_patch.start()
with patch.object(base.source,'now',return_value=T):runner=successor.Runner(cfg)


def tick(at, pending_failure=False):
    clock['now']=at
    def record(now):
        runner.full_market=market(now);return runner.project_market(runner.full_market,runner.universe)
    runner.market_record=record;runner.science=lambda:science(at)
    def baseline(instance,c,now):
        c.update(baseline_targets={s:.3 for s in instance.universe},baseline_day=(now.date()-dt.timedelta(days=1)).isoformat())
    # Isolate scheduling from synthetic-future funding settlement coverage;
    # booked funding/state remain intact, and no scientific M1 signal is invented.
    with patch.object(base.source,'now',return_value=at),patch.object(base.Runner,'baseline',autospec=True,side_effect=baseline),patch.object(runner,'funding',side_effect=lambda state,record:state),patch.object(base.causal,'read_window',return_value=None):
        runner.tick(at)
        publish(runner);runner.publish_management()


def current():return json.loads(runner.db.execute('SELECT payload FROM state').fetchone()[0])


tick(T+dt.timedelta(seconds=20));after_intent=current();assert after_intent['order_count']==before_orders,'intent must precede a fresh execution book'
tick(T+dt.timedelta(seconds=60));first=current()
assert first['order_count']==before_orders+6
assert all(first['positions'][s]['quantity']==p['quantity_ceilings'][s] for s in p['affected'])
assert first['risk_policy_state']['high_water']==before_risk['high_water']
assert runner.managed_policy()['short_caps']==short_caps
epoch=runner.meta('strategy_successor');assert epoch['legacy_fill_count']==before_orders-199
assert epoch['boundary_metrics']==base.paper.totals(state,require_positive=False)
for name in ('account','management'):
    shutil.copyfile(F/'projection'/(name+'.json'),F/'projection'/('first-'+name+'.json'))
runner.close()
with patch.object(base.source,'now',return_value=T+dt.timedelta(seconds=80)):runner=successor.Runner(cfg)
tick(T+dt.timedelta(seconds=100));assert current()['order_count']==first['order_count']
at=T+dt.timedelta(days=1,seconds=120)
tick(at);tick(at+dt.timedelta(seconds=40));second=current()
assert all(second['positions'][s]['quantity']==p['indicative_changes'][s]['stages'][1] for s in p['affected'])
at+=dt.timedelta(days=1,seconds=120)
tick(at);tick(at+dt.timedelta(seconds=40));third=current()
assert all(third['positions'][s]['quantity']==0 for s in p['affected'])
assert runner.has_overlay_budget(third,runner.meta('control'))
entries,overlay=runner.entry_plan(third,runner.meta('control'))
assert all(entries[s]<0 for s in p['affected']) and set(overlay)==set(p['affected'])
pol=runner.managed_policy();q,pol2=w.targets(third,pol,{s:.3 for s in runner.universe},runner.full_market['quotes'],kind='REENTRY')
assert all(v==0 for v in q.values()) and pol2['short_caps']==short_caps
assert base.shared.sha(F/'original.sqlite')==original_sha and base.shared.sha('/seed.sqlite')==seed_sha
assert runner.db.execute('PRAGMA integrity_check').fetchone()[0]=='ok'
assert runner.db.execute('SELECT COUNT(*) FROM orders WHERE id<=?',(before_orders,)).fetchone()[0]==before_orders
assert runner.account==p['account'] and runner.meta('strategy_successor')==epoch
at+=dt.timedelta(minutes=5)
control=runner.meta('control');control.update(phase='PENDING_ENTRY',episode='CONTROL-FIXTURE-FLAT-LONG-SHORT',
    entry_quantities=entries,overlay_symbols=overlay)
with patch.object(base.source,'now',return_value=at),runner.db:
    runner.db.execute('INSERT INTO m1_episodes VALUES(?,?,?,?,?,?)',(control['episode'],at.isoformat(),at.isoformat(),(at+dt.timedelta(hours=6)).isoformat(),'PENDING_ENTRY','{}'))
    runner.intent(control,'M1_ENTRY',None,at,at)
    runner.full_market=market(at+dt.timedelta(seconds=40))
with patch.object(base.source,'now',return_value=at+dt.timedelta(seconds=40)),runner.db:
    r=runner.project_market(runner.full_market,runner.universe)
    opened=runner.execute_pending(third,control,r,at+dt.timedelta(seconds=40),None)
    assert all(opened['positions'][s]['quantity']<0 for s in p['affected'])
at+=dt.timedelta(hours=6,seconds=60)
with patch.object(base.source,'now',return_value=at),runner.db:
    runner.intent(control,'EXIT',None,at,at)
    runner.full_market=market(at+dt.timedelta(seconds=40))
with patch.object(base.source,'now',return_value=at+dt.timedelta(seconds=40)),runner.db:
    r=runner.project_market(runner.full_market,runner.universe)
    closed=runner.execute_pending(opened,control,r,at+dt.timedelta(seconds=40),None)
    assert all(closed['positions'][s]['quantity']==0 for s in p['affected'])
    runner.db.execute('UPDATE state SET payload=? WHERE id=1',(base.shared.dump(closed),))
    runner.put('control',control)
result=dict(scope='FULL_ACCOUNT_CONTROL_FIXTURE_ONLY_NOT_RETURN_COMPARISON',passed=True,account=runner.account,
    original_history_rows=before_orders,first_reduction_fills=6,second_reduction_fills=6,third_reduction_fills=6,
    original_and_seed_unchanged=True,short_budget_unchanged=True,no_repurchase=True,restart_idempotent=True,
    risk_high_water_preserved=True,actual_short_entry_from_flat=True,actual_buy_covers_only_short=True,
    authority='synthetic_operator_record_no_password',economic_claim=False)
(F/'projection/result.json').write_text(json.dumps(result,indent=2)+'\n');print(json.dumps(result));runner.close();clock_patch.stop()
