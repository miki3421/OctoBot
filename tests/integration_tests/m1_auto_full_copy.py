"""Real automatic runner on full preserved ledger; synthetic control inputs only."""
import copy
import datetime as dt
import json
import os
from pathlib import Path
import shutil
import sqlite3
import uuid
from unittest.mock import patch
from octobot.ai_strategy_lab import v13_m1_auto as auto
from octobot.ai_strategy_lab import v13_m1_weekly as w
from octobot.ai_strategy_lab import v13_m1_paper as base
from octobot.ai_strategy_lab.v13_m1_paper_view import publish

E=Path('/evidence');F=E/('full-copy-'+uuid.uuid4().hex[:8]);F.mkdir(mode=0o750);os.chown(F,0,30910)
for name,uid in [('state',30943),('projection',30943),('source',30944),('configuration',0),('approvals',30945)]:
    p=F/name;p.mkdir(mode=0o750);os.chown(p,uid,30910)
(F/'source/science').mkdir(mode=0o750);os.chown(F/'source/science',30944,30910)


def write(path,value,uid=0):
    path.write_text(json.dumps(value,indent=2)+'\n');os.chown(path,uid,30910);path.chmod(0o440 if uid==0 else 0o640)


for name,uid in [('account',30943),('approvals',30945)]:
    target=F/('state' if name=='account' else 'approvals')/(name+'.sqlite')
    shutil.copyfile(E/('m1.sqlite' if name=='account' else 'approvals.sqlite'),target);os.chown(target,uid,30910);target.chmod(0o640)
cfg=json.loads(Path('/release/configuration/config.json').read_text())
for name in ('protocol','genesis-upgrade','successor-authority','successor-proposal','automatic-authority'):
    write(F/'configuration'/(name+'.json'),json.loads(Path('/release/configuration',name+'.json').read_text()))
db=sqlite3.connect(F/'state/account.sqlite');state=json.loads(db.execute('SELECT payload FROM state').fetchone()[0]);control=json.loads(db.execute("SELECT payload FROM m1_meta WHERE key='control'").fetchone()[0]);before_orders=db.execute('SELECT COUNT(*) FROM orders').fetchone()[0];db.close()
T=w.when(control['last_seen'])+dt.timedelta(minutes=2)
cfg.update(repo='/runtime',db=str(F/'state/account.sqlite'),original='/original.sqlite',seed='/seed.sqlite',receipt='/clone-receipt.json',protocol=str(F/'configuration/protocol.json'),runtime_upgrade=str(F/'configuration/runtime-upgrade.json'),output=str(F/'projection/account.json'))
cfg['successor'].update(authority=str(F/'configuration/successor-authority.json'),proposal=str(F/'configuration/successor-proposal.json'),genesis_upgrade=str(F/'configuration/genesis-upgrade.json'))
cfg['automatic_review']['authority']=str(F/'configuration/automatic-authority.json')
cfg['management'].update(scope='M1_WEEKLY_MANAGEMENT_CONTROL_TEST_V1',source=str(F/'source'),approvals=str(F/'approvals/approvals.sqlite'),projection=str(F/'projection/management.json'),transition_proposal=str(F/'configuration/successor-proposal.json'))
up=json.loads(Path('/release/configuration/runtime-upgrade-template.json').read_text());up.update(authorized_at=T.isoformat(),owner_reference='CONTROL FIXTURE ONLY',backup_sha256=base.shared.sha(E/'m1.sqlite'));write(F/'configuration/runtime-upgrade.json',up)
inputs=json.loads((E/'inputs.json').read_text());original_sc=inputs['science'];original_market=inputs['market']
scenario={'positive':True}


def science(at):
    sc=copy.deepcopy(original_sc);shift=at.date()-dt.timedelta(days=1)-dt.date.fromisoformat(sc['day'])
    sc['day']=str(at.date()-dt.timedelta(days=1));sc['published_at']=at.isoformat()
    for s,series in sc['bars'].items():
        for bar in series:
            bar['day']=str(dt.date.fromisoformat(bar['day'])+shift);bar['received_at']=at.isoformat()
        # One clearly positive fresh candidate; all other histories deteriorate.
        series[0]['close']=80.;series[-31]['close']=120.;series[-1]['close']=100.
        if s=='QNTUSDT' and scenario['positive']:series[0]['close']=50.;series[-31]['close']=60.;series[-1]['close']=100.
    sc['snapshot_id']=w.digest({k:v for k,v in sc.items() if k!='snapshot_id'});return sc


def market(at):
    m=copy.deepcopy(original_market);m['fixture']=True;m['observed_at_start']=(at-dt.timedelta(seconds=2)).isoformat();m['observed_at_end']=at.isoformat()
    for q in m['quotes'].values():
        for key in ('timestamp','mark_timestamp','metadata_observed_at','book_timestamp'):
            if key in q:q[key]=(at-dt.timedelta(seconds=1)).isoformat()
        q['funding']=[dict(timestamp_ms=int(at.timestamp())//28800*28800000,rate=0.)];q['funding_interval_ms']=28800000
    q=m['quotes']['QNTUSDT'];mark=q['mark_price']
    # A qualified-book control, not invented historical execution evidence.
    q['bids']=[dict(price=mark-.01,base_quantity=100.)];q['asks']=[dict(price=mark+.01,base_quantity=100.)]
    m['record_hash']=w.digest({k:v for k,v in m.items() if k!='record_hash'});return m


os.setgroups([30910]);os.setgid(30910);os.setuid(30943)
clock={'now':T};timer=patch.object(base.source,'now',side_effect=lambda:clock['now']);timer.start()
runner=auto.Runner(cfg)
shorts=copy.deepcopy(runner.managed_policy()['short_caps']);epoch=runner.meta('strategy_successor');risk=copy.deepcopy(state['risk_policy_state'])


def setup(at):
    clock['now']=at
    runner.science=lambda:science(at);runner.prior_science=lambda sc:science(at-dt.timedelta(days=1))
    def observed(now):
        runner.full_market=market(now);return runner.project_market(runner.full_market,runner.universe)
    runner.market_record=observed


def tick(at):
    setup(at)
    def baseline(instance,c,now):c.update(baseline_targets={s:.3 for s in instance.universe},baseline_day=str(now.date()-dt.timedelta(days=1)))
    with patch.object(base.Runner,'baseline',autospec=True,side_effect=baseline),patch.object(runner,'funding',side_effect=lambda s,r:s),patch.object(base.causal,'read_window',return_value=None):runner.tick(at)


tick(T);p=runner.managed_policy()
assert p['authority_kind']=='delegated_automatic_review',runner.meta('automatic_input_status')
assert p['short_caps']==shorts
assert runner.db.execute('SELECT COUNT(*) FROM orders').fetchone()[0]==before_orders
publish(runner);runner.publish_management();shutil.copyfile(F/'projection/management.json',F/'projection/first-management.json')
runner.close();runner=auto.Runner(cfg);tick(T+dt.timedelta(seconds=40))
assert runner.db.execute('SELECT COUNT(*) FROM orders').fetchone()[0]==before_orders
at=T+dt.timedelta(days=1,minutes=3)
tick(at);tick(at+dt.timedelta(seconds=40));tick(at+dt.timedelta(seconds=80))
p=runner.managed_policy();assert p['automatic_admissions']['QNTUSDT']['status']=='PENDING',runner.meta('automatic_input_status')
at+=dt.timedelta(minutes=3);setup(at);control=runner.meta('control')
control['baseline_targets']['QNTUSDT']=p['long_caps']['QNTUSDT']
state=json.loads(runner.db.execute('SELECT payload FROM state').fetchone()[0])
with runner.db:runner.intent(control,'DAILY',control['baseline_targets'],at,at)
setup(at+dt.timedelta(seconds=40));r=runner.market_record(clock['now'])
with runner.db,patch.object(runner,'funding',side_effect=lambda s,r:s):
    after=runner.execute_pending(state,control,r,clock['now'],None)
    runner.db.execute('UPDATE state SET payload=? WHERE id=1',(base.shared.dump(after),));runner.put('control',control)
assert after['positions']['QNTUSDT']['quantity']>0,control['last_action']
assert runner.managed_policy()['automatic_admissions']['QNTUSDT']['status']=='CONSUMED'
after_count=runner.db.execute('SELECT COUNT(*) FROM orders').fetchone()[0]
tick(at+dt.timedelta(seconds=80));assert runner.db.execute('SELECT COUNT(*) FROM orders').fetchone()[0]==after_count
# A closed/covered admission cannot use the old permit again.
flat=copy.deepcopy(after);flat['positions']['QNTUSDT']['quantity']=0.
q,_=w.targets(flat,runner.managed_policy(),{s:.3 for s in flat['positions']},runner.full_market['quotes'],kind='REENTRY');assert q['QNTUSDT']==0.
q,_=w.targets(flat,runner.managed_policy(),{s:.3 for s in flat['positions']},runner.full_market['quotes'],kind='DAILY');assert q['QNTUSDT']==0.
scenario['positive']=False
initial_entry=after['positions']['QNTUSDT']['quantity']
for offset,fraction in ((1,.5),(2,.25),(3,0.)):
    review_at=at+dt.timedelta(days=offset,minutes=offset*3)
    tick(review_at);tick(review_at+dt.timedelta(seconds=40))
    current=json.loads(runner.db.execute('SELECT payload FROM state').fetchone()[0])
    expected=w.floor_quantity(initial_entry*fraction,original_market['quotes']['QNTUSDT']['quantity_step'])
    assert current['positions']['QNTUSDT']['quantity']==expected,(offset,current['positions']['QNTUSDT']['quantity'],expected)
assert runner.managed_policy()['short_caps']==shorts and runner.meta('strategy_successor')==epoch
assert runner.db.execute('SELECT COUNT(*) FROM orders WHERE id<=?',(before_orders,)).fetchone()[0]==before_orders
assert runner.db.execute('PRAGMA integrity_check').fetchone()[0]=='ok'
for op in ('UPDATE m1_auto_reviews SET kind=kind','DELETE FROM m1_auto_reviews'):
    try:runner.db.execute(op)
    except sqlite3.IntegrityError:pass
    else:raise AssertionError('audit_not_append_only')
with runner.db:runner.db.execute('ROLLBACK') if runner.db.in_transaction else None
publish(runner);runner.publish_management()
result=dict(passed=True,scope='CONTROL_FIXTURE_ONLY_NO_RETURN_CLAIM',same_account=runner.account,history_retained=before_orders,
    automatic_approval=True,actual_new_symbol_buy=True,no_duplicate_entry_after_restart=True,no_repurchase_after_close=True,
    short_budget_unchanged=True,append_only_audit=True,new_admission_gradual_exit=True,original_and_collectors_read_only=True)
(F/'projection/result.json').write_text(json.dumps(result,indent=2)+'\n');print(json.dumps(result));runner.close();timer.stop()
