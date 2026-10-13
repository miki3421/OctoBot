"""Read-only dashboard projection for full-history V13 clones."""
import datetime as dt
import json
from pathlib import Path
from octobot.ai_strategy_lab import v13_paper_v2 as paper
from octobot.ai_strategy_lab import v13_research_source as source

LABELS={'ORIGINAL':'V13 originale','FAST':'V13 protezione rapida','HALF':'V13 esposizione ridotta'}

def downsample(points,maximum=1800):
    # Keep local minima/maxima, endpoints and gaps; no invented interpolation data.
    if len(points)<=maximum:return points
    width=max(1,len(points)//(maximum//2));out=[]
    for k in range(0,len(points),width):
        block=points[k:k+width]
        selected={0,len(block)-1,min(range(len(block)),key=lambda i:block[i][1]),max(range(len(block)),key=lambda i:block[i][1])}
        out.extend(block[i] for i in sorted(selected))
    return out

def publish(runner):
    db=runner.db;parent=runner.parent;start=paper.totals(parent,require_positive=False)
    original=json.loads(runner.original.execute('SELECT payload FROM state WHERE id=1').fetchone()[0])
    states=dict(runner.states(),ORIGINAL=original)
    inherited=[dict(r) for r in runner.seed.execute("SELECT bar,symbol,action,quantity,price,fee,status FROM orders ORDER BY bar,id")]
    prefix=downsample([[r[0],r[1]] for r in runner.seed.execute('SELECT bar,equity FROM equity_history ORDER BY bar')])
    curves={a:[[runner.t0.isoformat(),start['equity']]] for a in states}
    gaps=[]
    for row in db.execute('SELECT at,payload FROM observations ORDER BY at'):
        obs=json.loads(row['payload'])
        for a,v in obs['states'].items():curves[a].append([row['at'],v['equity']])
        if obs.get('funding_debt'):gaps.append(row['at'])
    allfills=[json.loads(r[0]) for r in db.execute('SELECT payload FROM fills ORDER BY at,id')]
    slots=[dict(r) for r in db.execute('SELECT * FROM slots ORDER BY slot DESC')]
    for row in slots:row['detail']=json.loads(row.pop('payload'))
    variants={}
    for arm,state in states.items():
        totals=paper.totals(state,require_positive=False)
        fills=[f for f in allfills if f['arm']==arm]
        if arm=='ORIGINAL':
            fills=[dict(r) for r in runner.original.execute("SELECT bar AS at,symbol,quantity,price,fee,action FROM orders WHERE status='filled' AND bar>? ORDER BY bar,id",(runner.t0.isoformat(),))]
        positions=[]
        for s,pos in sorted(state['positions'].items()):
            before=parent['positions'][s]
            def net(v):return v['realized_pnl']+v['quantity']*(v['current_price']-v['entry_price'])+v['funding']-v['fees']
            positions.append(dict(symbol=s,quantity=pos['quantity'],entry=pos['entry_price'],mark=pos['current_price'],
                unrealized=pos['quantity']*(pos['current_price']-pos['entry_price']),net=net(pos),since_fork=net(pos)-net(before),
                filter=runner.meta('filters').get(s) if arm=='FAST' else None))
        equity=totals['equity'];peak=start['equity'];dd=0
        for _,e in curves[arm]:peak=max(peak,e);dd=max(dd,1-e/peak)
        variants[arm]=dict(label=LABELS[arm],metrics=totals,change=equity-start['equity'],change_pct=(equity/start['equity']-1)*100,
            fees_since_fork=totals['fees']-start['fees'],funding_since_fork=totals['funding']-start['funding'],
            equity_curve=downsample(curves[arm]),drawdown_pct=dd*100,positions=positions,fills=fills,
            historical_order_count=len(inherited),post_fork_order_count=len(fills),risk=state['risk_policy_state'],
            observed_at=original.get('last_success_at') if arm=='ORIGINAL' else (curves[arm][-1][0]),
            account_id=state.get('fork_account','v13-paper-v2'))
    result=dict(schema=1,available=True,generated_at=source.now().isoformat(),health=runner.meta('health'),
        receipt={k:v for k,v in runner.receipt.items() if k not in ('inherited_positions','inherited_risk_state')},
        baseline=start,variants=variants,common_history=prefix,inherited_fills=inherited,slots=slots,
        funding_debt=runner.meta('funding_debt'),valuation_gap=runner.meta('valuation_gap'),
        incomplete_funding_observations=len(gaps),scientific_status='UNVALIDATED',real_kucoin_minimums='UNKNOWN')
    source.atomic(runner.c['output'],result)

def load(path='/v13-paper/forks-ui/comparison.json'):
    try:
        value=json.loads(Path(path).read_text())
        now=dt.datetime.now(dt.timezone.utc)
        age=(now-dt.datetime.fromisoformat(value['generated_at'])).total_seconds()
        checked=(now-dt.datetime.fromisoformat(value['health']['checked_at'])).total_seconds()
        value['stale']=not(0<=age<=180 and 0<=checked<=180)
        return value
    except (OSError,ValueError,KeyError,TypeError):
        return dict(available=False,message='Confronto temporaneamente non disponibile.')
