"""Frozen 90-day paired evaluator; synthetic fixtures never validate a strategy."""
import datetime as dt
import math
import random

from .source import NS

GRID=300*NS


def weekly_intervals(t0,t1):
    current=dt.datetime.fromtimestamp(t0//NS,dt.timezone.utc)
    midnight=current.replace(hour=0,minute=0,second=0,microsecond=0)
    next_monday=midnight+dt.timedelta(days=7-current.weekday())
    boundary=int(next_monday.timestamp())*NS
    edges=[t0]
    while boundary<t1:edges.append(boundary);boundary+=7*86400*NS
    return list(zip(edges,edges[1:]+[t1]))


def evaluate(export,now_ns,*,synthetic=False):
    t0,t1=export['t0'],export['t1']
    if type(t0) is not int or t0% (86400*NS) or t1!=t0+90*86400*NS:
        raise ValueError('frozen_horizon_required')
    if not synthetic and now_ns<t1:raise ValueError('scientific_review_sealed_until_t1')
    if synthetic and export['mode']!='SYNTHETIC_TEST_ONLY':
        raise ValueError('synthetic_override_for_fixture_only')
    expected=set(range(t0,t1+GRID,GRID));intervals=weekly_intervals(t0,t1)
    values={};summary={};incomplete=[]
    for name,arm in export['arms'].items():
        by={}
        for row in arm['points']:
            at=row['at_ns']
            if at in by:raise ValueError('duplicate_equity')
            if at not in expected:raise ValueError('equity_outside_frozen_grid')
            if row['complete'] is True:
                value=row['equity']
                if isinstance(value,bool) or not isinstance(value,(int,float)) or not math.isfinite(value) or value<=0:
                    raise ValueError('invalid_equity')
                by[at]=value
            else:by[at]=None
        complete=len([v for v in by.values() if v is not None])
        coverage=complete/len(expected)
        if set(by)!=set(expected) or any(v is None for v in by.values()):incomplete.append(name+':equity_grid_incomplete')
        if by.get(t0)!=10000:incomplete.append(name+':seed_missing_or_changed')
        if arm['final_q'] or not arm['complete'] or arm['integrity_halt']:incomplete.append(name+':unresolved_or_halted')
        valid=arm['valid_slots']/((t1-t0)//GRID)
        closed=0;entry=None;days=set();weeks=set()
        for fill in arm['fills']:
            at=fill['at_ns'];kind=fill['detail']['kind']
            if not t0<=at<=t1 or kind not in ('ENTRY','EXIT'):raise ValueError('episode_outside_horizon_or_kind')
            if kind=='ENTRY':
                if entry is not None:raise ValueError('overlapping_entry_in_export')
                entry=at
            elif kind=='EXIT' and fill['detail']['after']==0:
                if entry is None:raise ValueError('exit_without_entry_in_export')
                date=dt.datetime.fromtimestamp(entry//NS,dt.timezone.utc)
                days.add(date.date().isoformat());weeks.add(tuple(date.isocalendar()[:2]));closed+=1;entry=None
        if entry is not None:incomplete.append(name+':episode_open')
        sufficient=closed>=20 and len(days)>=20 and len(weeks)>=8 and valid>=.95 and coverage>=.95
        if not sufficient:incomplete.append(name+':minimum_activity_or_coverage')
        seen=[by[t] for t in sorted(by) if by[t] is not None];high=10000.;dd=0.
        for equity in seen:high=max(high,equity);dd=max(dd,1-equity/high)
        net=by[t1]-10000 if by.get(t1) is not None and by.get(t0)==10000 else None
        values[name]=by;summary[name]=dict(net_usdt=net,drawdown=dd,valid_slot_fraction=valid,
            equity_coverage=coverage,closed_episodes=closed,entry_days=len(days),entry_weeks=len(weeks))
    names={'control-primary','candidate-primary','control-stress','candidate-stress'}
    if set(values)!=names:raise ValueError('four_frozen_arms_required')
    if incomplete:
        return dict(classification='INCONCLUSIVE_NO_PROMOTION',reasons=incomplete,arms=summary,
                    synthetic_fixture=synthetic,scientific_validity='UNASSESSED',automatic_promotion=False)
    left,right=values['control-primary'],values['candidate-primary']
    differences=[(right[b]/right[a]-1)-(left[b]/left[a]-1) for a,b in intervals]
    rng=random.Random(20261021)
    samples=sorted(sum(rng.choice(differences) for _ in differences)/len(differences) for _ in range(10000))
    lower=samples[math.ceil(.05*len(samples))-1]
    delta=summary['candidate-primary']['net_usdt']-summary['control-primary']['net_usdt']
    stress_delta=summary['candidate-stress']['net_usdt']-summary['control-stress']['net_usdt']
    positive=(delta>0 and stress_delta>0 and lower>0 and summary['candidate-primary']['net_usdt']>0
              and summary['candidate-stress']['net_usdt']>0 and summary['candidate-primary']['drawdown']<=.1
              and summary['candidate-stress']['drawdown']<=.1)
    return dict(classification='CANDIDATE_FOR_FURTHER_REVIEW_ONLY' if positive else 'FAILED_FROZEN_CRITERIA',
        arms=summary,net_difference_usdt=delta,stress_net_difference_usdt=stress_delta,
        weekly_paired_differences=differences,bootstrap_lower_95=lower,
        synthetic_fixture=synthetic,scientific_validity='UNASSESSED',automatic_promotion=False)
