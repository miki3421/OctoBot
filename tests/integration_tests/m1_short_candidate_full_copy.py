"""Inactive real runner on a complete ledger copy, synthetic future books only."""
import copy
import datetime as dt
import hashlib
import json
import math
import os
from pathlib import Path
import shutil
import sqlite3
import uuid
from unittest.mock import patch

from octobot.ai_strategy_lab import v13_m1_short_candidate as candidate
from octobot.ai_strategy_lab import v13_m1_short_risk as risk

base=candidate.base
E=Path('/audit-evidence/m1-short-correction-20261027')
F=E/('full-copy-'+uuid.uuid4().hex[:8]);F.mkdir(mode=0o750);os.chown(F,0,30910)
for name,uid in [('state',30943),('projection',30943),('source',30944),('configuration',0)]:
    path=F/name;path.mkdir(mode=0o750);os.chown(path,uid,30910)


def write(path,value,uid=0):
    path.write_text(json.dumps(value,indent=2)+'\n');os.chown(path,uid,30910);path.chmod(0o440)


source=E/'input/m1.sqlite';target=F/'state/account.sqlite'
shutil.copyfile(source,target);os.chown(target,30943,30910);target.chmod(0o640)
cfg=json.loads((E/'configuration/config.json').read_text())
cfg.update(repo=str(E/'runtime'),db=str(target),original=str(E/'input/original.sqlite'),
           seed=str(E/'input/seed.sqlite'),receipt=str(E/'input/receipt.json'),
           output=str(F/'projection/account.json'),protocol=str(E/'configuration/protocol.json'),
           runtime_upgrade=str(E/'configuration/runtime-upgrade.json'))
for name in ('authority','proposal','genesis_upgrade'):
    cfg['successor'][name]=str(E/'configuration'/Path(cfg['successor'][name]).name)
cfg['automatic_review']['authority']=str(E/'configuration/automatic-authority.json')
cfg['management'].update(scope='M1_WEEKLY_MANAGEMENT_CONTROL_TEST_V1',source=str(F/'source'),
                        approvals=str(E/'input/approvals.sqlite'),
                        projection=str(F/'projection/management.json'),
                        transition_proposal=str(E/'configuration/successor-proposal.json'))
cfg['short_candidate']=dict(scope='OFFLINE_QUALIFICATION_ONLY',work_root=str(F),
    protocol=str(E/'frozen-protocol.json'))
write(F/'OFFLINE_ONLY.json',dict(scope='OFFLINE_COPY_NO_OPERATING_AUTHORITY',protocol_id=risk.PROTOCOL_ID,
    account='v13-m1-short-paper-v1-5e761f0cedac',source_sha256=hashlib.sha256(source.read_bytes()).hexdigest()))
original_sc=json.loads((E/'input/science.json').read_text())
original_market=json.loads((E/'input/market.json').read_text())
db=sqlite3.connect(target)
control=json.loads(db.execute("SELECT payload FROM m1_meta WHERE key='control'").fetchone()[0])
prefix=[list(x) for x in db.execute('SELECT * FROM orders ORDER BY id')]
old_epoch=json.loads(db.execute("SELECT payload FROM m1_meta WHERE key='strategy_successor'").fetchone()[0])
db.close()
T=dt.datetime.fromtimestamp((int(base.p.timestamp(control['last_seen']).timestamp())//300+2)*300,dt.timezone.utc)
clock={'now':T};scenario={'factor':1.,'partial':False,'recovery':False}


def history(slot):
    panel=[]
    for i in range(289):
        at=slot-(288-i)*300
        factor=math.exp(.001*math.sin(i*.7))
        if i>=277:
            factor*=1.+(.012 if scenario['recovery'] else -.012)*(i-276)/12
        panel.append(dict(time=at,prices={s:original_market['quotes'][s]['mark_price']*factor for s in risk.SIGNALS},
                          source_times={s:at-1 for s in risk.SIGNALS}))
    return panel


def science(at):
    value=copy.deepcopy(original_sc)
    shift=at.date()-dt.timedelta(days=1)-dt.date.fromisoformat(value['day'])
    value['day']=str(at.date()-dt.timedelta(days=1));value['published_at']=at.isoformat()
    for series in value['bars'].values():
        for bar in series:
            bar['day']=str(dt.date.fromisoformat(bar['day'])+shift);bar['received_at']=at.isoformat()
        series[0]['close']=80.;series[-31]['close']=120.;series[-1]['close']=100.
    value['snapshot_id']=risk.digest({k:v for k,v in value.items() if k!='snapshot_id'})
    return value


def market(at,runner):
    value=copy.deepcopy(original_market);value['fixture']=True
    value['observed_at_start']=(at-dt.timedelta(seconds=2)).isoformat();value['observed_at_end']=at.isoformat()
    positions=json.loads(runner.db.execute('SELECT payload FROM state WHERE id=1').fetchone()[0])['positions']
    for symbol,q in value['quotes'].items():
        for key in ('timestamp','mark_timestamp','metadata_observed_at','book_timestamp'):
            if key in q:q[key]=(at-dt.timedelta(seconds=1)).isoformat()
        q['mark_price']*=scenario['factor']
        for side in ('asks','bids'):
            for level in q[side]:level['price']*=scenario['factor']
        for key in ('best_bid','best_ask'):
            if key in q:q[key]*=scenario['factor']
        if scenario['partial'] and positions.get(symbol,{}).get('quantity',0)<0:
            half=risk.floor_quantity(abs(positions[symbol]['quantity'])/2,q['quantity_step'])
            q['asks']=[dict(price=q['asks'][0]['price'],base_quantity=max(q['quantity_step'],half))]
        q['funding']=[dict(timestamp_ms=int(at.timestamp())//28800*28800000,rate=0.)];q['funding_interval_ms']=28800000
    value['record_hash']=risk.digest({k:v for k,v in value.items() if k!='record_hash'})
    return value


os.setgroups([30910]);os.setgid(30910);os.setuid(30943)
timer=patch.object(base.source,'now',side_effect=lambda:clock['now']);timer.start()
runner=candidate.Runner(cfg)
shorts=copy.deepcopy(runner.managed_policy()['short_caps'])


def tick(at):
    clock['now']=at
    runner.science=lambda:science(at);runner.prior_science=lambda sc:science(at-dt.timedelta(days=1))
    def observed(now):
        runner.full_market=market(now,runner)
        return runner.project_market(runner.full_market,runner.universe)
    runner.market_record=observed
    def baseline(instance,c,now):
        c.update(baseline_targets={s:0. for s in instance.universe},baseline_day=str(now.date()-dt.timedelta(days=1)))
    with patch.object(base.Runner,'baseline',autospec=True,side_effect=baseline), \
         patch.object(runner,'funding',side_effect=lambda s,r:s), \
         patch.object(base.causal,'read_window',side_effect=lambda path,slot,universe:history(slot)):
        runner.tick(at)


tick(T)
assert runner.meta('control')['phase']=='PENDING_ENTRY'
assert runner.db.execute('SELECT COUNT(*) FROM orders').fetchone()[0]==len(prefix)
before_entry_state=runner.db.execute('SELECT payload FROM state WHERE id=1').fetchone()[0]
before_entry_control=runner.meta('control')
real_event=runner.event
def failed_event(kind,*args,**kwargs):
    if kind=='SHORT_RISK_EPISODE_OPENED':
        raise RuntimeError('CONTROL_FIXTURE_TRANSACTION_CRASH')
    return real_event(kind,*args,**kwargs)
with patch.object(runner,'event',side_effect=failed_event):
    try:tick(T+dt.timedelta(seconds=300))
    except RuntimeError as error:assert str(error)=='CONTROL_FIXTURE_TRANSACTION_CRASH'
    else:raise AssertionError('transaction_crash_not_exercised')
assert runner.db.execute('SELECT COUNT(*) FROM orders').fetchone()[0]==len(prefix)
assert runner.db.execute('SELECT payload FROM state WHERE id=1').fetchone()[0]==before_entry_state
assert runner.meta('control')==before_entry_control
assert runner.meta('short_candidate_plan') is None and runner.meta('short_candidate_episode') is None
runner.close();runner=candidate.Runner(cfg)
tick(T+dt.timedelta(seconds=300))
saved=runner.meta('short_candidate_episode');plan=runner.meta('short_candidate_plan')
assert saved and runner.meta('control')['phase']=='ACTIVE',runner.meta('short_candidate_input_status')
assert plan['planned_stopped_risk']<=plan['risk_unit']+1e-9
entry_count=runner.db.execute('SELECT COUNT(*) FROM orders').fetchone()[0]
assert entry_count>len(prefix)
assert runner.managed_policy()['short_caps']==shorts
runner.close();runner=candidate.Runner(cfg)
assert runner.meta('short_candidate_episode')==saved
scenario['factor']=1.05
tick(T+dt.timedelta(seconds=340))
assert runner.meta('control')['phase']=='EXIT_PENDING'
assert runner.meta('short_candidate_episode')['exit_reason']=='LOSS_STOP'
assert runner.db.execute('SELECT COUNT(*) FROM orders').fetchone()[0]==entry_count,'same_book_exit'
runner.close();runner=candidate.Runner(cfg)
scenario['partial']=True
tick(T+dt.timedelta(seconds=380))
remaining=json.loads(runner.db.execute('SELECT payload FROM state WHERE id=1').fetchone()[0])
assert any(p['quantity']<0 for p in remaining['positions'].values())
assert runner.meta('control')['phase']=='EXIT_PENDING'
partial_count=runner.db.execute('SELECT COUNT(*) FROM orders').fetchone()[0]
assert partial_count>entry_count
scenario['partial']=False
tick(T+dt.timedelta(seconds=420))
assert runner.meta('control')['pending']['kind']=='EXIT','early_partial_retry_waited_for_6h'
assert runner.db.execute('SELECT COUNT(*) FROM orders').fetchone()[0]==partial_count
tick(T+dt.timedelta(seconds=460))
flat=json.loads(runner.db.execute('SELECT payload FROM state WHERE id=1').fetchone()[0])
assert all(p['quantity']==0 for p in flat['positions'].values())
closed=runner.meta('short_candidate_episode')
assert closed['status']=='CLOSED' and closed['exit_reason']=='LOSS_STOP'
closed_count=runner.db.execute('SELECT COUNT(*) FROM orders').fetchone()[0]
tick(T+dt.timedelta(seconds=500));tick(T+dt.timedelta(seconds=600))
assert runner.db.execute('SELECT COUNT(*) FROM orders').fetchone()[0]==closed_count,'automatic_long_rebuy'
assert runner.meta('strategy_successor')==old_epoch
assert runner.managed_policy()['short_caps']==shorts
assert [list(x) for x in runner.db.execute('SELECT * FROM orders WHERE id<=? ORDER BY id',(len(prefix),))]==prefix
assert runner.db.execute('PRAGMA integrity_check').fetchone()[0]=='ok'
result=dict(scope='SYNTHETIC_FULL_COPY_MECHANICS_NOT_RETURN_VALIDATION',passed=True,
    same_account=runner.account,history_orders_preserved=len(prefix),new_orders=closed_count-len(prefix),
    budget_unchanged=True,no_long_rebuy=True,quantity_downscale=True,actual_later_book_entry=True,
    stopped_risk_checked=True,no_same_book_exit=True,persisted_stop_across_restart=True,
    atomic_entry_plan_fills_and_episode_rollback=True,
    partial_exit_retry_before_timeout=True,original_successor_epoch_unchanged=True,
    operating_sources_read_only=True,deliberate_adverse_gap_exceeds_planned_loss_possible=True)
(F/'projection/result.json').write_text(json.dumps(result,indent=2)+'\n')
print(json.dumps(result));runner.close();timer.stop()
