"""Inactive, deterministic M1 SHORT sizing/exit candidate. No I/O or trading.

Rules were frozen before verification in m1-short-risk-exits-candidate-v1.
R is a planned loss unit, not a loss guarantee across gaps or funding delays.
"""
import copy
from decimal import Decimal, ROUND_FLOOR
import hashlib
import json
import math

VERSION = 'm1-short-risk-exits-candidate-v1'
PROTOCOL_ID = 'a77bc705b996d5680c5dd9301351e64f0f58ab9e9dcc9a56795c3cb234351aa8'
SIGNALS = tuple(sorted(('AAVEUSDT','ADAUSDT','ATOMUSDT','AVAXUSDT','BCHUSDT','BTCUSDT',
    'DOGEUSDT','DOTUSDT','ETHUSDT','HBARUSDT','LINKUSDT','LTCUSDT','NEARUSDT','SOLUSDT',
    'UNIUSDT','XLMUSDT','XRPUSDT','ZECUSDT')))


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(',', ':'),
                                    allow_nan=False).encode()).hexdigest()


def number(value):
    if type(value) not in (int, float) or not math.isfinite(value):
        raise ValueError('finite_number_required')
    return float(value)


def validate(protocol):
    if (protocol.get('protocol_id') != PROTOCOL_ID
            or digest({k:v for k,v in protocol.items() if k != 'protocol_id'}) != PROTOCOL_ID):
        raise ValueError('frozen_protocol_identity')
    return protocol


def floor_quantity(quantity, step):
    if number(step) <= 0 or number(quantity) < 0:
        raise ValueError('quantity_step')
    return float((Decimal(str(quantity))/Decimal(str(step))).to_integral_value(rounding=ROUND_FLOOR)*Decimal(str(step)))


def model(rows, slot):
    """Complete 24h past-only 5m panel and hourly returns used by M1."""
    slot = number(slot)
    if len(rows) != 289 or slot % 300:
        raise ValueError('contiguous_24h_window_required')
    for i, row in enumerate(rows):
        at = slot-(288-i)*300
        if row['time'] != at or set(row['prices']) != set(SIGNALS) or set(row['source_times']) != set(SIGNALS):
            raise ValueError('window_grid_or_universe')
        for symbol in SIGNALS:
            if number(row['prices'][symbol]) <= 0 or not 0 <= at-number(row['source_times'][symbol]) <= 120:
                raise ValueError('window_future_stale_or_invalid_price')
    returns = {s:[number(b['prices'][s])/number(a['prices'][s])-1 for a,b in zip(rows,rows[1:])]
               for s in SIGNALS}
    hourly = {s:rows[-1]['prices'][s]/rows[-13]['prices'][s]-1 for s in SIGNALS}
    return dict(slot=slot, input_hash=digest(rows), returns=returns,
                feature=dict(btc_60m=hourly['BTCUSDT'],
                             negative_breadth=sum(x<0 for x in hourly.values())/len(SIGNALS)))


def basket_sigma(returns, weights):
    """Sample covariance, 20% diagonal shrinkage, scaled from 5m to one hour."""
    if not weights or not math.isclose(sum(weights.values()),1.,abs_tol=1e-10):
        raise ValueError('normalized_basket_required')
    if any(number(w)<0 or len(returns[s]) != 288 for s,w in weights.items()):
        raise ValueError('basket_return_shape')
    means={s:math.fsum(returns[s])/288 for s in weights}
    portfolio=[math.fsum(w*(returns[s][i]-means[s]) for s,w in weights.items()) for i in range(288)]
    sample=math.fsum(x*x for x in portfolio)/287
    diagonal=math.fsum(w*w*math.fsum((x-means[s])**2 for x in returns[s])/287 for s,w in weights.items())
    return math.sqrt(max(0.,(.8*sample+.2*diagonal)*12))


def vwap(quote, quantity, side):
    if side not in ('asks','bids') or number(quantity) <= 0:
        raise ValueError('execution_quantity')
    left=quantity;gross=0.
    previous=None
    for level in quote[side]:
        price=number(level['price']);capacity=number(level['base_quantity'])
        if price<=0 or capacity<0 or (previous is not None and
                (side=='asks' and price<previous or side=='bids' and price>previous)):
            raise ValueError('invalid_depth')
        previous=price
        used=min(left,capacity);gross+=used*price;left-=used
        if left<=1e-10:
            return gross/quantity*(1.0002 if side=='asks' else .9998)
    raise ValueError('insufficient_observed_depth')


def round_trip_cost(quote, quantity):
    mark=number(quote['mark_price']);fee=number(quote['fee_rate'])
    if mark<=0 or not .0006<=fee<1 or quote['asks'][0]['price'] < quote['bids'][0]['price']:
        raise ValueError('mark_fee_or_crossed_book')
    return max(0.,(vwap(quote,quantity,'asks')-vwap(quote,quantity,'bids'))/mark+2*fee)


def size(protocol, history, equity, caps, quotes):
    """One common downscale, lot floor and explicit stopped-risk recheck.

    Receives a validated fresh book from the existing runner. Unused lots and
    budget never move to another symbol. Full-authority depth is conservative:
    its absence rejects new SHORT risk instead of inventing a smaller book.
    """
    validate(protocol)
    if caps != protocol['short_caps'] or number(equity)<=0:
        raise ValueError('account_budget_binding')
    allowed={s:number(w) for s,w in caps.items() if w>0}
    if not set(allowed)<=set(quotes) or not set(allowed)<=set(history['returns']):
        raise ValueError('sizing_input_missing')
    risk_unit=equity*.0025
    full={s:floor_quantity(equity*w/number(quotes[s]['mark_price']),quotes[s]['quantity_step']) for s,w in allowed.items()}
    full={s:q for s,q in full.items() if q>0}
    if not full:
        raise ValueError('no_executable_short_lot')
    # Validate both-side observed depth at the unscaled authority once.
    full_cost={s:round_trip_cost(quotes[s],q) for s,q in full.items()}
    total=math.fsum(q*quotes[s]['mark_price'] for s,q in full.items())
    weights={s:q*quotes[s]['mark_price']/total for s,q in full.items()}
    sigma=basket_sigma(history['returns'],weights)
    distance=max(.01,2*sigma)
    scale=min(1.,risk_unit/(total*distance+math.fsum(full[s]*quotes[s]['mark_price']*full_cost[s] for s in full)))
    for _ in range(16):
        quantities={s:floor_quantity(equity*allowed[s]*scale/quotes[s]['mark_price'],quotes[s]['quantity_step']) for s in full}
        quantities={s:q for s,q in quantities.items() if q>0}
        if not quantities:
            raise ValueError('no_executable_short_lot')
        notionals={s:q*quotes[s]['mark_price'] for s,q in quantities.items()}
        total=math.fsum(notionals.values())
        weights={s:n/total for s,n in notionals.items()}
        sigma=basket_sigma(history['returns'],weights);distance=max(.01,2*sigma)
        costs=math.fsum(notionals[s]*round_trip_cost(quotes[s],q) for s,q in quantities.items())
        stopped_risk=total*distance+costs
        if stopped_risk<=risk_unit+1e-9:
            if any(n>equity*allowed[s]+1e-8 for s,n in notionals.items()) or total>equity*sum(allowed.values())+1e-8:
                raise ValueError('quantity_authority_exceeded')
            plan=dict(version=VERSION,protocol_id=PROTOCOL_ID,input_hash=history['input_hash'],
                      signal_slot=history['slot'],risk_unit=risk_unit,entry_equity=equity,
                      quantities={s:-q for s,q in quantities.items()},hourly_sigma=sigma,
                      stop_distance=distance,round_trip_cost=costs,planned_stopped_risk=stopped_risk,
                      short_notional=total,scale=scale,short_budget=sum(caps.values()))
            plan['plan_id']=digest(plan)
            return plan
        scale*=risk_unit/stopped_risk*.999999
    raise ValueError('discrete_risk_not_converged')


def episode(plan, positions_before, positions_after, fills, at, episode_id):
    """Anchor only actual newly opened SHORTs, proportional reversal fees."""
    if digest({k:v for k,v in plan.items() if k!='plan_id'})!=plan['plan_id'] or plan['protocol_id']!=PROTOCOL_ID:
        raise ValueError('plan_identity')
    legs={}
    for fill in fills:
        s=fill['symbol'];after=number(fill['after']);before=number(fill['before'])
        if after>=0:
            continue
        if before<0 or s in legs or not math.isclose(after,plan['quantities'].get(s,0),abs_tol=1e-10):
            raise ValueError('entry_not_from_frozen_plan')
        position=positions_after[s]
        legs[s]=dict(quantity=after,entry=position['entry_price'],
                     opening_fee=fill['fee']*abs(after)/abs(fill['quantity']),
                     funding_anchor=position['funding'])
    if not legs:
        return None
    if set(legs)!=set(plan['quantities']):
        raise ValueError('partial_short_entry_not_authorized')
    return dict(version=VERSION,protocol_id=PROTOCOL_ID,plan_id=plan['plan_id'],episode_id=episode_id,
                at=number(at),risk_unit=plan['risk_unit'],entry_equity=plan['entry_equity'],legs=legs,
                peak=None,armed=False,last_at=number(at),last_market=None,
                recovery_count=0,last_recovery_slot=None,exit_reason=None)


def liquidation(episode, positions, quotes):
    value=0.
    for s,leg in episode['legs'].items():
        pos=positions[s];quantity=number(pos['quantity']);q=quotes[s]
        if not math.isclose(quantity,leg['quantity'],abs_tol=1e-10) or pos['entry_price'] != leg['entry']:
            raise ValueError('episode_position_changed')
        price=vwap(q,abs(quantity),'asks');fee=number(q['fee_rate'])
        if not .0006<=fee<1:
            raise ValueError('fee_invalid')
        value += quantity*(price-leg['entry'])-leg['opening_fee']-abs(quantity)*price*fee
        value += number(pos['funding'])-leg['funding_anchor']
    return value


def watch(protocol, saved, positions, quotes, *, at, market_id, feature_slot=None, feature=None):
    """Fresh executable values and two distinct, consecutive recovery slots.

    Exit reasons are sticky across restarts. This function emits a reason,
    never a fill: a persisted intent must wait for the next observed book.
    """
    validate(protocol)
    e=copy.deepcopy(saved);at=number(at)
    if e['protocol_id']!=PROTOCOL_ID or at<e['last_at']:
        raise ValueError('episode_identity_or_clock')
    if e['exit_reason']:
        return e,e['exit_reason']
    if at==e['last_at'] and e['last_market'] not in (None,market_id):
        raise ValueError('conflicting_episode_market')
    if at==e['last_at'] and e['last_market']==market_id:
        return e,None
    value=liquidation(e,positions,quotes);e['last_at']=at;e['last_market']=market_id
    e['last_liquidation_net']=value
    e['peak']=value if e['peak'] is None else max(e['peak'],value)
    risk=number(e['risk_unit'])
    if risk<=0:
        raise ValueError('episode_risk_missing')
    e['armed']=e['armed'] or e['peak']>=risk
    recovery=False
    if feature_slot is not None:
        slot=number(feature_slot)
        if slot%300 or not e['at']<=slot<=at:
            raise ValueError('feature_slot_not_causal')
        previous=e['last_recovery_slot']
        if previous is not None and slot<previous:
            raise ValueError('feature_slot_regression')
        if previous!=slot:
            valid=feature is not None
            if valid:
                btc=number(feature['btc_60m']);breadth=number(feature['negative_breadth'])
                if not 0<=breadth<=1:
                    raise ValueError('invalid_breadth')
                recovery=btc>=0 and breadth<=.5
            consecutive=previous is not None and slot-previous==300
            e['recovery_count']=(e['recovery_count']+1 if consecutive else 1) if recovery else 0
            e['last_recovery_slot']=slot
    reason=None
    if value<=-risk:
        reason='LOSS_STOP'
    elif e['armed'] and value<=e['peak']-.5*risk:
        reason='PROFIT_GIVEBACK'
    elif e['recovery_count']>=2:
        reason='SIGNAL_INVALIDATED'
    if reason:
        e['exit_reason']=reason;e['exit_decided_at']=at
    return e,reason
