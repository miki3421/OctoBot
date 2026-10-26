"""Offline risk reconstruction from retained pair ledger and exact books.

No new strategy, optimizer, parameter search, outcome unsealing or live writes.
"""
import copy
import json
from pathlib import Path
import sqlite3
from octobot.ai_strategy_lab import v13_fork_runner as f

E=Path('/evidence');db=f.ro(E/'forks.sqlite');seed=f.ro('/seed/parent-snapshot.sqlite')
parent=json.loads(seed.execute('SELECT payload FROM state WHERE id=1').fetchone()[0]);seed.close()
states={a:copy.deepcopy(parent) for a in f.ARMS};filters={s:'FULL' for s in parent['positions']}
fills=[dict(r) for r in db.execute('SELECT * FROM fills ORDER BY at,id')]
funding=[dict(r) for r in db.execute('SELECT * FROM funding ORDER BY at,arm,symbol')]
print('fill_columns',list(fills[0]) if fills else [])
report=[];fi=fu=0
for slot in db.execute("SELECT * FROM slots WHERE status='EXECUTED' ORDER BY slot"):
    detail=json.loads(slot['payload']);record=f.read(Path('/source/market')/(detail['market_hash']+'.json.gz'))
    at=record['observed_at_end'];endms=int(f.p.timestamp(at).timestamp()*1000)
    while fu<len(funding) and funding[fu]['at']<=endms:
        event=funding[fu];states[event['arm']]['positions'][event['symbol']]['funding']+=event['amount'];fu+=1
    for state in states.values():
        for s,pos in state['positions'].items():pos['current_price']=record['quotes'][s]['mark_price']
    day=(f.p.timestamp(slot['slot']).date()-f.dt.timedelta(days=1)).isoformat()
    inputs=json.loads(db.execute('SELECT payload FROM inputs WHERE day=?',(day,)).fetchone()[0])
    targets={s:f.p.decode_weight(v) if isinstance(v,str) else v for s,v in inputs['targets'].items()}
    weights,new_filters,cov,before,common=f.risk_targets(states,targets,inputs['prices'],filters)
    # Reconstruct ordinary plan rounding/costs with the recorded permission
    # outcome. This is an execution diagnostic, not an alternative P/L path.
    allow=not detail.get('funding_debt') and not any(detail['blocks'].values()) and not detail.get('shared_entry_block')
    predicted=copy.deepcopy(states);predicted_qty={};skipped={}
    for arm in f.ARMS:
        legs,skipped[arm]=f.engine.research_plan(predicted[arm],record['quotes'],weights[arm],allow)
        for leg in legs:f.paper.apply_fill(predicted[arm]['positions'][leg['symbol']],leg['quantity'],leg['price'],leg['fee'])
        predicted_qty[arm]={s:p['quantity'] for s,p in predicted[arm]['positions'].items()}
    while fi<len(fills) and fills[fi]['at']<=at:
        row=fills[fi];fill=json.loads(row['payload']);f.paper.apply_fill(states[row['arm']]['positions'][row['symbol']],fill['quantity'],fill['price'],fill['fee']);fi+=1
    reconstructed={};quantity_errors={}
    import numpy as np,math
    for arm in f.ARMS:
        state=states[arm];eq=f.paper.totals(state,require_positive=False)['equity'];symbols=sorted(targets)
        w=np.array([state['positions'][s]['quantity']*state['positions'][s]['current_price']/eq for s in symbols])
        reconstructed[arm]=math.sqrt(max(0.,365*float(w@cov@w)))
        quantity_errors[arm]={s:state['positions'][s]['quantity']-predicted_qty[arm][s] for s in symbols if abs(state['positions'][s]['quantity']-predicted_qty[arm][s])>1e-8}
    vol_error=max(abs(reconstructed[a]-detail['realized_allocation_volatility'][a]) for a in f.ARMS)
    weight_error=max(abs(weights[a][s]-detail['weights'][a][s]) for a in f.ARMS for s in targets)
    report.append(dict(slot=slot['slot'],risk_gap=detail['risk_gap'],within_tolerance=detail['risk_matched'],
        continuous_common_volatility=common,reconstructed_volatility=reconstructed,volatility_error=vol_error,
        continuous_weight_error=weight_error,planned_quantity_errors=quantity_errors,skipped=skipped,
        independent_reconstruction_passed=vol_error<1e-10 and weight_error<1e-10 and not any(quantity_errors.values())))
    filters=new_filters
result=dict(scope='OFFLINE_DISCRETE_RISK_QUALIFICATION_NO_STRATEGY_CHANGE',executed=len(report),
    matched=sum(r['within_tolerance'] for r in report),fraction=sum(r['within_tolerance'] for r in report)/len(report),
    required_fraction=.95,tolerance=.02,slots=report)
(E/'fork-discrete-risk.json').write_text(json.dumps(result,indent=2)+'\n');print(json.dumps(result));db.close()
