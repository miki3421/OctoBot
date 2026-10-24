"""Read-only strategy review from archived local UI responses. Never stops a service."""
import argparse
import datetime as dt
import json
import math
import copy
import sqlite3
from pathlib import Path


def ts(value):return dt.datetime.fromisoformat(value).timestamp()
def iso(value):return dt.datetime.fromtimestamp(value,dt.timezone.utc).isoformat()


def common(variants,keys):
    start=max(ts(variants[k].get('first_decision_slot') or variants[k]['fork_at']) for k in keys);tables={}
    for key in keys:
        points={}
        for at,equity in variants[key]['equity_curve']:
            at=ts(at)
            if at>=start and math.isfinite(equity) and equity>0:points.setdefault(int(at)//300,(at,equity))
        tables[key]=points
    buckets=sorted(set.intersection(*(set(v) for v in tables.values())))
    buckets=[b for b in buckets if max(tables[k][b][0] for k in keys)-min(tables[k][b][0] for k in keys)<=120]
    if len(buckets)<2:raise ValueError('insufficient_common_points')
    result={}
    for key in keys:
        points=[tables[key][b] for b in buckets];first=points[0][1];last=points[-1][1];high=first;dd=0.
        for _,v in points:high=max(high,v);dd=max(dd,1-v/high)
        result[key]=dict(start_at=iso(points[0][0]),end_at=iso(points[-1][0]),start_equity=first,end_equity=last,
                         change=last-first,return_pct=100*(last/first-1),observed_drawdown_pct=100*dd)
    return dict(method='FIRST_COMMON_5MIN_BUCKET_NO_INTERPOLATION_MAX120S_SKEW',points=len(buckets),
                gaps_over30m=sum(b-a>6 for a,b in zip(buckets,buckets[1:])),strategies=result)


def main():
    p=argparse.ArgumentParser();p.add_argument('--input',type=Path,required=True);p.add_argument('--output',type=Path,required=True);args=p.parse_args()
    d=json.load(open(args.input/'strategies.json'));old=json.load(open(args.input/'intraday.json'));pair=json.load(open(args.input/'pair.json'));diag=json.load(open(args.input/'pair-slot-diagnostics.json'))
    if not d['available'] or d['stale'] or d['fourth_stale'] or d['funding_debt'] or d['valuation_gap']:raise ValueError('incomplete_views')
    curves=copy.deepcopy(d['variants'])
    # Raw coherent copies avoid independent UI downsampling of each curve.
    for key,name in [('ORIGINAL','original.sqlite'),('M1','m1.sqlite')]:
        db=sqlite3.connect((args.input/name).resolve().as_uri()+'?mode=ro',uri=True);db.execute('PRAGMA query_only=ON')
        curves[key]['equity_curve']=[list(r) for r in db.execute('SELECT bar,equity FROM equity_history ORDER BY bar')];db.close()
    db=sqlite3.connect((args.input/'forks.sqlite').resolve().as_uri()+'?mode=ro',uri=True);db.execute('PRAGMA query_only=ON')
    for key in ('FAST','HALF'):curves[key]['equity_curve']=[]
    for at,payload in db.execute('SELECT at,payload FROM observations ORDER BY at'):
        row=json.loads(payload)
        if row['funding_debt']:continue
        for key in ('FAST','HALF'):curves[key]['equity_curve'].append([at,row['states'][key]['equity']])
    db.close()
    groups=dict(v13_three=common(curves,['ORIGINAL','FAST','HALF']),v13_four=common(curves,['ORIGINAL','FAST','HALF','M1']))
    variants={}
    for key,v in d['variants'].items():
        variants[key]=dict(equity=v['metrics']['equity'],observed_at=v['observed_at'],fork_at=v['fork_at'],
                           own_fork_change=v['change'],own_fork_change_pct=v['change_pct'],own_fork_drawdown_pct=v['drawdown_pct'],
                           fills=v['post_fork_order_count'],fees=v['fees_since_fork'],funding=v['funding_since_fork'],
                           current_gross=sum(abs(p['quantity']*p['mark']) for p in v['positions'])/v['metrics']['equity'])
    result=dict(scope='OBSERVATIONAL_ANALYSIS_ONLY_NO_SHUTDOWN',as_of=d['generated_at'],groups=groups,variants=variants,
        legacy_intraday=dict(equity=old['metrics']['equity'],net=old['metrics']['pnl'],stress_net=old['metrics']['stress_equity']-10000,
                             fills=old['state']['fills'],round_trips=old['state']['position_generation'],fees=old['state']['fees'],gross_realized=old['state']['realized'],
                             valid_slots=old['state']['valid_slots'],slots=old['state']['slots'],valid_slot_ratio=old['state']['valid_slots']/old['state']['slots'],
                             activation_at=iso(old['state']['activation_at']/1e9)),
        paired_intraday={key:dict(account=v['account'],equity=v['equity'],fills=v['fills'],latest_reason=v['reason'],slot_counts=diag[key]['counts']) for key,v in pair['arms'].items() if key.endswith('primary')},
        m1_confounds=dict(missed_daily=d['m1']['daily_missed_count'],episodes=len(d['m1']['episodes']),first_approval_not_applied=True),
        limitations=['Short correlated market sample, not independent experiments','Different exposure, inception dates and missed daily M1 rebalances confound comparisons','Legacy intraday has only two round trips and incomplete input continuity','New paired accounts have no executions; flat equity is not demonstrated robustness'],
        recommendations=dict(ORIGINAL='KEEP_UNCHANGED_REFERENCE',M1='FOCUS_MAINTENANCE_WITH_EXPLICIT_APPROVAL',
                             HALF='KEEP_RISK_CONTROL',FAST='NO_STATISTICAL_REJECTION_YET_SLIGHTLY_BETTER_THAN_HALF',
                             legacy_intraday='FIRST_CONSOLIDATION_CANDIDATE_NOT_PROVEN_UNPROFITABLE',paired_intraday='CONTINUE_DATA_QUALIFIED_OBSERVATION_NOT_PROFITABILITY_VERDICT'),
        services_stopped=False)
    args.output.write_text(json.dumps(result,indent=2)+'\n')
    print(json.dumps(dict(common_four=groups['v13_four'],legacy=result['legacy_intraday']),indent=2))


if __name__=='__main__':main()
