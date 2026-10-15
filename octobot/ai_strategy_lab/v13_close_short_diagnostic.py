"""Research-only basket accounting; no runtime, network, DB or order capability.

Card work-card-1c625e23-0331-4fa3-a9d5-98e9fc21499e.
"""
import copy
import math
from decimal import Decimal, ROUND_CEILING, ROUND_FLOOR


def new_position():
    return dict(quantity=0., entry_price=0., realized_pnl=0., fees=0., funding=0.)


def fill(position, quantity, price, fee):
    if not all(math.isfinite(v) for v in (quantity, price, fee)) or price <= 0 or fee < 0:
        raise ValueError('invalid_fill')
    before = position['quantity']
    after = before + quantity
    if before * quantity < 0:
        position['realized_pnl'] += min(abs(before), abs(quantity)) * (price - position['entry_price']) * (1 if before > 0 else -1)
    if abs(after) < 1e-10:
        after, position['entry_price'] = 0., 0.
    elif before == 0 or before * after < 0:
        position['entry_price'] = price
    elif before * quantity > 0:
        position['entry_price'] = (abs(before) * position['entry_price'] + abs(quantity) * price) / abs(after)
    position['quantity'] = after
    position['fees'] += fee


def totals(state, marks):
    p = state['positions']
    if set(p) != set(marks) or any(not math.isfinite(v) or v <= 0 for v in marks.values()):
        raise ValueError('incomplete_or_invalid_marks')
    realized = math.fsum(v['realized_pnl'] for v in p.values())
    unrealized = math.fsum(v['quantity'] * (marks[s] - v['entry_price']) for s, v in p.items())
    fees = math.fsum(v['fees'] for v in p.values())
    funding = math.fsum(v['funding'] for v in p.values())
    equity = math.fsum((state['initial_equity'], realized, unrealized, -fees, funding))
    if not all(math.isfinite(v) for v in (equity, realized, unrealized, fees, funding)):
        raise ValueError('invalid_accounting')
    return dict(equity=equity, realized=realized, unrealized=unrealized, fees=fees,
                funding=funding, gross=math.fsum(abs(v['quantity'] * marks[s]) for s, v in p.items()),
                net_exposure=math.fsum(v['quantity'] * marks[s] for s, v in p.items()))


def execution(delta, before, quote):
    """Price a crossing once on aggregate depth; only simulated minima apply."""
    if not math.isfinite(delta) or delta == 0:
        raise ValueError('invalid_delta')
    step = quote['quantity_step']
    tick = quote['price_tick']
    fee_rate = quote['fee_rate']
    if not all(math.isfinite(v) and v > 0 for v in (step, tick)) or not math.isfinite(fee_rate) or fee_rate < 0:
        raise ValueError('invalid_precision_or_fee')
    units = abs(delta) / step
    if abs(units - round(units)) > 1e-7:
        raise ValueError('quantity_off_step')
    after = before + delta
    opening = max(0., abs(after) - abs(before)) if before * after >= 0 else abs(after)
    if opening > 1e-10 and opening * quote['mark_price'] < 1. - 1e-9:
        raise ValueError('below_simulated_opening_minimum')
    side = 'asks' if delta > 0 else 'bids'
    remaining, amount = abs(delta), 0.
    last = None
    for level in quote[side]:
        price, available = level['price'], level['base_quantity']
        if not all(math.isfinite(v) and v > 0 for v in (price, available)):
            raise ValueError('invalid_depth')
        if last is not None and ((side == 'asks' and price < last) or (side == 'bids' and price > last)):
            raise ValueError('unordered_depth')
        last = price
        take = min(remaining, available)
        amount += take * price
        remaining -= take
        if remaining <= 1e-10:
            break
    if remaining > 1e-10:
        raise ValueError('insufficient_aggregate_depth')
    raw = amount / abs(delta) * (1.0002 if delta > 0 else .9998)
    rounding = ROUND_CEILING if delta > 0 else ROUND_FLOOR
    price = float((Decimal(str(raw)) / Decimal(str(tick))).to_integral_value(rounding=rounding) * Decimal(str(tick)))
    if price <= 0:
        raise ValueError('invalid_price')
    notional = abs(delta) * price
    return dict(quantity=delta, price=price, fee=notional * max(.0006, fee_rate), turnover=notional)


def rebalance(state, targets, quotes):
    """Atomic hypothetical batch; never partially change caller state on error."""
    if set(targets) != set(state['positions']) or set(quotes) != set(targets):
        raise ValueError('incomplete_basket')
    result = copy.deepcopy(state)
    legs = []
    for s in sorted(targets):
        if not math.isfinite(targets[s]):
            raise ValueError('invalid_target')
        pos = result['positions'][s]
        delta = targets[s] - pos['quantity']
        if abs(delta) <= 1e-10:
            continue
        leg = dict(symbol=s, **execution(delta, pos['quantity'], quotes[s]))
        fill(pos, delta, leg['price'], leg['fee'])
        legs.append(leg)
    return result, legs


def targets_for(state, arm):
    if arm not in ('CASH', 'SHORT'):
        raise ValueError('unknown_arm')
    return {s: (0. if arm == 'CASH' else -v['quantity']) if v['quantity'] > 0 else v['quantity']
            for s, v in state['positions'].items()}


def settlements(quote, start_ms, end_ms):
    """Unknown coverage raises; no inferred zero rate or invented settlement."""
    interval = quote['funding_interval_ms']
    if type(interval) != int or not 0 < interval <= 86400000 or end_ms <= start_ms:
        raise ValueError('invalid_funding_interval')
    points = [p for p in quote['funding'] if p['timestamp_ms'] <= end_ms]
    if not points or not any(p['timestamp_ms'] <= start_ms for p in points):
        raise ValueError('funding_start_missing')
    if any(b['timestamp_ms'] <= a['timestamp_ms'] for a, b in zip(points, points[1:])):
        raise ValueError('funding_order_invalid')
    previous = max(p['timestamp_ms'] for p in points if p['timestamp_ms'] <= start_ms)
    selected = [p for p in points if start_ms < p['timestamp_ms'] <= end_ms]
    times = [previous] + [p['timestamp_ms'] for p in selected]
    if any(b - a > interval for a, b in zip(times, times[1:])) or end_ms - times[-1] >= interval:
        raise ValueError('funding_gap')
    if any(not isinstance(p['rate'], (int, float)) or not math.isfinite(p['rate']) for p in selected):
        raise ValueError('funding_rate_unknown')
    return selected
