"""Fourth account projection and read-only merge; no old simulator changes."""
import copy
import datetime as dt
import json
import math
import os
from pathlib import Path
import stat
from octobot.ai_strategy_lab import v13_fork_view as legacy
from octobot.ai_strategy_lab import v13_original_structural_view

UID = 30943


def public(path, now):
    path=Path(path); fd=os.open(path,os.O_RDONLY|os.O_NOFOLLOW)
    try:
        info=os.fstat(fd)
        if not stat.S_ISREG(info.st_mode) or info.st_uid!=UID or info.st_mode&0o022 or info.st_size>4000000:
            raise ValueError('fourth_projection_custody')
        value=json.loads(os.read(fd,4000001))
    finally:os.close(fd)
    if value['scope']!='AUTONOMOUS_M1_PAPER_RESEARCH_ONLY' or value['arm']!='M1' or value['schema']!=1:
        raise ValueError('fourth_projection_scope')
    age=(now-dt.datetime.fromisoformat(value['generated_at'])).total_seconds()
    if age<0:raise ValueError('fourth_projection_future')
    value['stale']=age>180
    return value


def publish(runner):
    paper,source=runner_paper_source()
    db=runner.db;state=json.loads(db.execute('SELECT payload FROM state WHERE id=1').fetchone()[0])
    totals=paper.totals(state,require_positive=False);parent=runner.parent;baseline=paper.totals(parent,require_positive=False)
    positions=[]
    for s,pos in sorted(state['positions'].items()):
        def net(v):return v['realized_pnl']+v['quantity']*(v['current_price']-v['entry_price'])+v['funding']-v['fees']
        positions.append(dict(symbol=s,quantity=pos['quantity'],entry=pos['entry_price'],mark=pos['current_price'],unrealized=pos['quantity']*(pos['current_price']-pos['entry_price']),net=net(pos),since_fork=net(pos)-net(parent['positions'][s]),filter=None))
    fills=[json.loads(r[0]) for r in db.execute('SELECT payload FROM m1_fills ORDER BY at,id')]
    inherited=[dict(r) for r in runner.seed.execute('SELECT bar,symbol,action,quantity,price,fee,status FROM orders ORDER BY bar,id')]
    prefix=legacy.downsample([[r[0],r[1]] for r in runner.seed.execute('SELECT bar,equity FROM equity_history ORDER BY bar')])
    curve=[[runner.t0.isoformat(),baseline['equity']]]
    curve += [[r['at'],json.loads(r['payload'])['metrics']['equity']] for r in db.execute('SELECT * FROM m1_observations ORDER BY at')]
    peak=baseline['equity'];dd=0.
    for _,e in curve:peak=max(peak,e);dd=max(dd,1-e/peak)
    variant=dict(label='V13 + M1 SHORT',metrics=totals,change=totals['equity']-baseline['equity'],change_pct=(totals['equity']/baseline['equity']-1)*100,
                 fees_since_fork=totals['fees']-baseline['fees'],funding_since_fork=totals['funding']-baseline['funding'],
                 equity_curve=legacy.downsample(curve),inherited_curve=prefix,drawdown_pct=dd*100,positions=positions,fills=fills,
                 historical_order_count=len(inherited),post_fork_order_count=len(fills),risk=state['risk_policy_state'],
                 observed_at=state.get('m1_last_market_at',runner.t0.isoformat()),account_id=runner.account,
                 fork_at=runner.t0.isoformat(),baseline=baseline,first_decision_slot=runner.activation['first_signal_slot'])
    successor=runner.meta('strategy_successor')
    if successor:
        variant.update(label=successor['label'],strategy_epoch=successor,
            epoch_change=totals['equity']-successor['boundary_metrics']['equity'],
            epoch_change_pct=(totals['equity']/successor['boundary_metrics']['equity']-1)*100)
    reference=runner.meta('comparison_reference')
    if not reference:
        try:
            other=json.loads(Path(runner.c['comparators']).read_text())
            if (source.now()-dt.datetime.fromisoformat(other['generated_at'])).total_seconds()>180:
                raise ValueError('comparators_stale')
            first=dt.datetime.fromisoformat(runner.activation['first_signal_slot']).timestamp()
            series={k:v['equity_curve'] for k,v in other['variants'].items()};series['M1']=curve
            buckets={}
            for arm,points in series.items():
                arm_buckets={}
                for at,equity in points:
                    ts=dt.datetime.fromisoformat(at).timestamp()
                    if ts>=first:arm_buckets.setdefault(int(ts)//300,dict(at=at,equity=equity))
                buckets[arm]=arm_buckets
            if set(buckets)!={'ORIGINAL','FAST','HALF','M1'}:raise ValueError('comparators_scope')
            common=set.intersection(*(set(v) for v in buckets.values()))
            for bucket in sorted(common):
                points={k:v[bucket] for k,v in buckets.items()}
                times=[dt.datetime.fromisoformat(v['at']).timestamp() for v in points.values()]
                if max(times)-min(times)<=120 and all(math.isfinite(v['equity']) and v['equity']>0 for v in points.values()):
                    reference=dict(bucket_utc=dt.datetime.fromtimestamp(bucket*300,dt.timezone.utc).isoformat(),points=points,maximum_skew_seconds=max(times)-min(times),method='FIRST_AVAILABLE_COMMON_5MIN_BUCKET_NO_OUTCOME_SELECTION')
                    with db:runner.put('comparison_reference',reference)
                    break
        except (OSError,ValueError,KeyError,TypeError):pass
    slots=[dict(r) for r in db.execute('SELECT kind,slot,status,payload FROM m1_slots ORDER BY slot DESC LIMIT 100')]
    for row in slots:row['detail']=json.loads(row.pop('payload'))
    daily_slots=[dict(r) for r in db.execute("SELECT kind,slot,status FROM m1_slots WHERE kind='DAILY' ORDER BY slot DESC LIMIT 7")]
    episodes=[dict(r) for r in db.execute('SELECT id,signal_at,entry_due,exit_due,status FROM m1_episodes ORDER BY signal_at DESC')]
    result=dict(schema=1,scope='AUTONOMOUS_M1_PAPER_RESEARCH_ONLY',arm='M1',available=True,generated_at=source.now().isoformat(),
                variant=variant,inherited_fills=inherited,activation=runner.activation,
                receipt={k:runner.receipt[k] for k in ('account_id','seed_sha256','economic_t0','scope')},
                control=runner.meta('control'),health=runner.meta('health'),slots=slots,daily_slots=daily_slots,
                daily_missed_count=db.execute("SELECT COUNT(*) FROM m1_slots WHERE kind='DAILY' AND status IN ('MISSED','DENIED')").fetchone()[0],episodes=episodes,
                comparison_reference=reference,risk_policy=runner.protocol['risk_policy'],scientific_status='UNASSESSED',real_kucoin_minimums='UNKNOWN')
    if successor:
        result.update(successor=successor,reduction_progress=runner.meta('successor_progress'),
                      successor_input_status=runner.meta('successor_input_status'))
    # Consumed signal rows, source bytes and copied authorizations never enter this view.
    if result['control']:
        result['control']={k:v for k,v in result['control'].items() if k not in {'entry_quantities','baseline_targets'}}
    source.atomic(runner.c['output'],result)


def runner_paper_source():
    from octobot.ai_strategy_lab import v13_paper_v2,v13_research_source
    return v13_paper_v2,v13_research_source


def load(path='/v13-paper/forks-ui/comparison.json', fourth='/v13-paper/m1-paper-ui/account.json', now=None):
    now=now or dt.datetime.now(dt.timezone.utc)
    data=legacy.load(path)
    if not data.get('available'):return data
    data=copy.deepcopy(data)
    for v in data['variants'].values():v['fork_at']=data['receipt']['economic_t0']
    try:value=public(fourth,now)
    except (OSError,ValueError,KeyError,TypeError):
        data['fourth_available']=False;data['fourth_message']='Quarta versione temporaneamente non verificabile.'
        return v13_original_structural_view.merge(data, now=now)
    data['fourth_available']=True;data['fourth_stale']=value['stale'];data['variants']['M1']=value['variant']
    data['m1']=value;data['comparison_reference']=value['comparison_reference']
    reference=value['comparison_reference']
    if reference:
        for arm,variant in data['variants'].items():
            ref=reference['points'][arm]
            variant['common_change']=variant['metrics']['equity']-ref['equity']
            variant['common_change_pct']=(variant['metrics']['equity']/ref['equity']-1)*100
            variant['common_reference_at']=ref['at']
    return v13_original_structural_view.merge(data, now=now)
