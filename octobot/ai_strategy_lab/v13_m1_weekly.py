"""Deterministic M1 weekly proposals and persistent side-specific target rules.

No network, account writes or approval capability. Card 026c44e2.
"""
import datetime as dt
import math
import statistics
from decimal import Decimal, ROUND_DOWN
from . import v13_dynamic_universe as selector

VERSION = 'm1-weekly-selection-v1'
UTC = dt.timezone.utc
POOL = selector.UNIVERSE
digest = selector.digest


def when(value):
    return selector.timestamp(value)


def num(value):
    if type(value) not in (int, float) or not math.isfinite(value):
        raise ValueError('finite_quantity_required')
    return float(value)


def verify(value, key):
    if value.get(key) != digest({k:v for k,v in value.items() if k != key}):
        raise ValueError('invalid_'+key)
    return value


def week(at):
    at = when(at)
    anchor = at.replace(hour=0,minute=15,second=0,microsecond=0)-dt.timedelta(days=at.weekday())
    if at<anchor:anchor-=dt.timedelta(days=7)
    return anchor.isoformat()


def signals(science, at):
    verify(science,'snapshot_id')
    if science.get('scope')!='M1_WEEKLY_CAUSAL_DAILY_V1':raise ValueError('science_scope')
    cutoff=when(at);published=when(science['published_at'])
    if not 0<=(cutoff-published).total_seconds()<=36*3600:
        raise ValueError('science_stale_or_future')
    end=(published.date()-dt.timedelta(days=1)).isoformat()
    if science['day']!=end:raise ValueError('daily_boundary')
    dates=[(dt.date.fromisoformat(end)-dt.timedelta(days=i)).isoformat() for i in range(120,-1,-1)]
    rows={};histories={};reasons={}
    for symbol in POOL:
        series=science['bars'].get(symbol)
        try:
            if not series or [x['day'] for x in series]!=dates:raise ValueError('121_closed_days_required')
            prices=[]
            for row in series:
                closed=dt.datetime.combine(dt.date.fromisoformat(row['day'])+dt.timedelta(days=1),dt.time(),UTC)
                if not closed<=when(row['received_at'])<=published:raise ValueError('unavailable_bar')
                price=num(row['close'])
                if price<=0:raise ValueError('invalid_close')
                prices.append(price)
            r30=prices[-1]/prices[-31]-1;r120=prices[-1]/prices[0]-1
            signal=1 if r30>0 and r120>0 else -1 if r30<0 and r120<0 else 0
            vol=statistics.stdev([prices[i]/prices[i-1]-1 for i in range(61,121)])
            score=min(abs(r30)/math.sqrt(30),abs(r120)/math.sqrt(120))/vol if signal and vol>0 else None
            rows[symbol]=dict(signal=signal,score=score);histories[symbol]=prices
        except (KeyError,ValueError,TypeError):
            rows[symbol]=dict(signal=0,score=None);reasons[symbol]='HISTORY_UNAVAILABLE'
    if 'BTCUSDT' not in histories:raise ValueError('BTC_history_required')
    for symbol in POOL:
        if rows[symbol]['signal']<0 and rows['BTCUSDT']['signal']>=0:rows[symbol]['signal']=0
    return rows,histories,reasons


def weights(science, selected, at):
    import numpy as np
    rows,histories,_=signals(science,at)
    if not set(selected)<=set(histories):raise ValueError('selected_history_missing')
    symbols=sorted(histories)
    x=np.array([histories[s][-61:] for s in symbols],dtype=float).T
    covariance=np.atleast_2d(np.cov(x[1:]/x[:-1]-1,rowvar=False,ddof=1))*365
    result=selector.target_weights([rows[s]['signal'] for s in symbols],covariance,symbols,selected)
    return {s:float(result[i]) for i,s in enumerate(symbols)}


def proposal(science, market, *, account, revision, previous, positions, equity, at, existing_short_caps=None):
    """A proposal never changes membership until a separate approval is consumed."""
    verify(market,'record_hash');rows,histories,reasons=signals(science,at)
    equity=num(equity)
    if not account or type(revision) is not int or revision<0 or equity<=0:raise ValueError('account_binding')
    if not set(previous)<=set(POOL) or len(previous)>18:raise ValueError('previous_universe')
    # Data outages on incumbents must not masquerade as economic exit signals.
    if not set(previous)<=set(histories):raise ValueError('incumbent_history_unavailable')
    from . import v13_market_sanity as sanity
    for symbol in POOL:
        try:
            q=market['quotes'][symbol]
            sanity.structure_and_time(symbol,q,market,when(at))
            bid=q['bids'][0]['price'];ask=q['asks'][0]['price'];mid=(bid+ask)/2
            if ((ask-bid)/mid>float(sanity.POLICY.max_spread_ratio) or abs(q['mark_price']-mid)/mid>float(sanity.POLICY.max_mark_mid_divergence)):
                raise ValueError('spread_or_mark')
            if min(sum(v['price']*v['base_quantity'] for v in q[side]) for side in ('bids','asks'))<.315*equity:
                raise ValueError('depth')
            funding=q['funding'];interval=q['funding_interval_ms'];cutoff=int(when(market['observed_at_end']).timestamp()*1000)
            if (type(interval) is not int or not 0<interval<=86400000 or not funding
                or not funding[-1]['timestamp_ms']<=cutoff<funding[-1]['timestamp_ms']+interval):
                raise ValueError('funding_coverage')
        except (ValueError,KeyError,TypeError):
            rows[symbol]=dict(signal=0,score=None);reasons[symbol]='BOOK_UNAVAILABLE'
    if any(s in reasons and reasons[s]=='BOOK_UNAVAILABLE' for s in previous):raise ValueError('incumbent_book_unavailable')
    selected,events=selector.select(rows,previous,initial=False)
    allocation=weights(science,selected,at)
    long_caps={s:max(0.,allocation.get(s,0.)) for s in POOL}
    # Retain the existing SHORT budget for a LONG exit unless the operator
    # explicitly also excludes its SHORT side in the approval dialog.
    short_caps={s:min(.315,max(abs(num(positions.get(s,{}).get('quantity',0)))*num(positions.get(s,{}).get('current_price',0))/equity,
                              num((existing_short_caps or {}).get(s,0.)))) for s in POOL}
    if sum(short_caps.values())>.90000001:raise ValueError('existing_short_budget_exceeds_risk')
    remaining=max(0.,.9-sum(short_caps.values()))
    for s in selected:
        added=min(remaining,max(0.,abs(allocation.get(s,0.))-short_caps[s]))
        short_caps[s]+=added;remaining-=added
    result=dict(version=VERSION,scope='M1_RESEARCH_PAPER_WEEKLY_PROPOSAL',account=account,
                parent_revision=revision,week=week(at),created_at=at,
                expires_at=(when(at)+dt.timedelta(hours=48)).isoformat(),
                science_id=science['snapshot_id'],market_hash=market['record_hash'],
                selected=selected,events=events,rows=rows,ineligible=reasons,
                long_caps=long_caps,short_caps=short_caps,previous=sorted(previous),
                indicative_positions={s:dict(quantity=v['quantity'],mark=v['current_price']) for s,v in positions.items()},
                reference_equity=equity,scientific_validity='UNASSESSED',
                simulation_contract='SEPARATE_SYNTHETIC_MINIMUMS',orders_authorized=False,execution_authorized=False)
    result['data_mode']='CONTROL_FIXTURE_ONLY' if market.get('fixture') else 'PUBLIC_CAPTURE_RESEARCH_ONLY'
    estimates={}
    for s in POOL:
        old=positions.get(s,{}).get('quantity',0.);quote=market['quotes'].get(s)
        if quote is None or reasons.get(s)=='BOOK_UNAVAILABLE':continue
        weight=long_caps[s] if allocation.get(s,0.)>=0 else -min(short_caps[s],abs(allocation[s]))
        q=floor_quantity(abs(weight)*equity/quote['mark_price'],quote['quantity_step'])*(1 if weight>=0 else -1)
        delta=q-old
        if abs(delta)<1e-10:continue
        remaining=abs(delta);gross=0.
        for level in quote['asks' if delta>0 else 'bids']:
            used=min(remaining,level['base_quantity']);gross+=used*level['price'];remaining-=used
            if remaining<1e-10:break
        available=remaining<1e-8
        fill=gross/abs(delta)*(1.0002 if delta>0 else .9998) if available else None
        fee=abs(delta)*fill*quote['fee_rate'] if available else None
        estimates[s]=dict(current_quantity=old,indicative_target=q,indicative_delta=delta,
                          indicative_weight=weight,cost_available=available,fee=fee,
                          immediate_equity_cost=delta*(fill-quote['mark_price'])+fee if available else None)
    result['indicative_changes']=estimates
    result['proposal_id']=digest(result)
    return result


def approved_policy(p, decision, previous_revision, at):
    if p.get('version') == 'm1-gradual-long-short-v3':
        from . import v13_m1_successor
        return v13_m1_successor.approved_policy(p,decision,previous_revision,at)
    from . import v13_m1_transition as transition
    if p.get('version') == transition.VERSION:
        return transition.approved_policy(p, decision, previous_revision, at)
    verify(p,'proposal_id');verify(decision,'decision_id')
    if (p['version']!=VERSION or p['scope']!='M1_RESEARCH_PAPER_WEEKLY_PROPOSAL'
        or type(p['parent_revision']) is not int or type(previous_revision) is not int
        or p['parent_revision']!=previous_revision or decision['proposal_id']!=p['proposal_id']
        or decision['account']!=p['account'] or decision['action']!='APPROVE'
        or decision.get('proposal_expires_at')!=p['expires_at']
        or not when(p['created_at'])<=when(decision['decided_at'])<=when(at)<=when(p['expires_at'])):
        raise ValueError('approval_binding_or_expiry')
    excluded=decision['exclude_short']
    excludable={s for s,v in p['short_caps'].items() if v>0}
    if len(set(excluded))!=len(excluded) or not set(excluded)<=excludable:
        raise ValueError('short_exclusion_scope')
    if len(set(p['selected']))!=len(p['selected']) or len(p['selected'])>18 or not set(p['selected'])<=set(POOL):
        raise ValueError('selected_universe')
    longs=dict(p['long_caps']);shorts=dict(p['short_caps'])
    for symbol in excluded:shorts[symbol]=0.
    for side in (longs,shorts):
        if set(side)!=set(POOL) or any(not 0<=num(v)<=.315 for v in side.values()) or sum(side.values())>.90000001:
            raise ValueError('budget_limits')
    if any(v>0 and s not in p['selected'] for s,v in longs.items()):raise ValueError('long_cap_outside_selection')
    selected=[s for s in p['selected'] if longs[s]>0 or shorts[s]>0]
    return dict(revision=previous_revision+1,account=p['account'],proposal_id=p['proposal_id'],
                decision_id=decision['decision_id'],selected=selected,long_caps=longs,
                short_caps=shorts,activated_at=at,quantity_ceilings={},
                valid_until=(when(p['week'])+dt.timedelta(days=9)).isoformat())


def floor_quantity(value,step):
    step=Decimal(str(num(step)))
    if step<=0:raise ValueError('invalid_step')
    return float((Decimal(str(abs(value)))/step).to_integral_value(rounding=ROUND_DOWN)*step)


def targets(state, policy, baseline, quotes, *, kind, short_reference=None):
    """Same account; no redistribution, no automatic restoration of LONG caps."""
    if policy.get('authority_kind') == 'delegated_automatic_review':
        from . import v13_m1_auto
        return v13_m1_auto.targets(state,policy,baseline,quotes,kind=kind,short_reference=short_reference)
    if policy.get('version') == 'm1-gradual-long-short-v3':
        from . import v13_m1_successor
        return v13_m1_successor.targets(state,policy,baseline,quotes,kind=kind,short_reference=short_reference)
    from . import v13_m1_transition as transition
    if policy.get('version') == transition.VERSION:
        return transition.targets(state, policy, baseline, quotes, kind=kind, short_reference=short_reference)
    import copy
    policy=copy.deepcopy(policy)
    equity=state['initial_equity']+sum(p['realized_pnl']+p['quantity']*(p['current_price']-p['entry_price'])-p['fees']+p['funding'] for p in state['positions'].values())
    if equity<=0:raise ValueError('positive_equity_required')
    result={}
    for symbol,pos in state['positions'].items():
        if symbol not in quotes:
            if pos['quantity']:raise ValueError('held_quote_missing')
            continue
        quote=quotes[symbol];mark=num(quote['mark_price']);step=num(quote['quantity_step'])
        if mark<=0:raise ValueError('positive_mark_required')
        raw=num(baseline.get(symbol,0.));long_cap=policy['long_caps'].get(symbol,0.);short_cap=policy['short_caps'].get(symbol,0.)
        if kind=='M1_ENTRY':
            # Preserve baseline SHORTs and independent overlay capacity without
            # treating a reduced held LONG as the available SHORT budget.
            reference=num((short_reference or baseline).get(symbol,0.))
            weight=-min(short_cap,abs(reference))
        elif kind=='MAINTENANCE_CLOSE':
            permitted=long_cap if pos['quantity']>0 else short_cap
            ceiling=permitted*equity/mark
            if pos['quantity']>0:ceiling=min(ceiling,policy['quantity_ceilings'].get(symbol,ceiling))
            q=math.copysign(min(abs(pos['quantity']),floor_quantity(ceiling,step)),pos['quantity'])
            result[symbol]=q;continue
        else:
            weight=min(max(raw,0.),long_cap) if raw>=0 else -min(abs(raw),short_cap)
        quantity=floor_quantity(abs(weight)*equity/mark,step)
        if weight>0:
            old=policy['quantity_ceilings'].get(symbol,quantity)
            quantity=floor_quantity(min(quantity,old),step);policy['quantity_ceilings'][symbol]=quantity
        elif kind!='M1_ENTRY':
            policy['quantity_ceilings'][symbol]=0.
        result[symbol]=quantity if weight>0 else -quantity if weight<0 else 0.
    return result,policy
