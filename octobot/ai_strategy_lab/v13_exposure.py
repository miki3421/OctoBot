"""Deterministic exposure preflight for the linear, base-quantity V13 ledger.

No sizing optimisation or exchange metadata inference. Prices are conservative
simulated execution prices, not exchange limit-order prices. Eight binary64
ULPs at the configured ratio boundary cover representation error only.
"""
import math
from decimal import Decimal, ROUND_FLOOR, ROUND_CEILING

RATIO_ULPS = 8


class Rejected(ValueError):
    def __init__(self, reason, exposure=None):
        super().__init__(reason)
        self.exposure = exposure


def number(value, name, *, positive=False, nonnegative=False):
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
        raise Rejected(f'invalid or missing {name}')
    if (positive and value <= 0) or (nonnegative and value < 0):
        raise Rejected(f'invalid {name}')
    return value


def above(value, limit):
    return value > limit + RATIO_ULPS * math.ulp(limit)


def snapshot(quantities, marks, equity, max_gross, max_asset):
    number(equity, 'equity')
    notionals = {s: number(q, 'position quantity') * number(marks[s], 'mark', positive=True)
                 for s, q in quantities.items() if q}
    gross, net = math.fsum(map(abs, notionals.values())), math.fsum(notionals.values())
    number(gross, 'gross exposure')
    per_asset = {s: abs(n) / equity for s, n in notionals.items()} if equity > 0 else {}
    breaches = ([] if equity > 0 else ['non_positive_equity'])
    if equity > 0:
        if above(gross / equity, max_gross):
            breaches.append('gross')
        breaches.extend('asset:' + s for s, ratio in sorted(per_asset.items()) if above(ratio, max_asset))
        # There is no separate configured net limit; |net| is bounded by gross.
        if above(abs(net) / equity, max_gross):
            breaches.append('net')
    return dict(equity=equity, gross=gross, net=net,
                gross_ratio=gross/equity if equity > 0 else None,
                net_ratio=net/equity if equity > 0 else None,
                asset_ratios=per_asset, breaches=breaches)


def quantities_and_marks(state):
    quantities, marks = {}, {}
    for s, p in state['positions'].items():
        quantities[s] = number(p['quantity'], 'position quantity')
        marks[s] = p['current_price']
        for field in ('entry_price', 'realized_pnl', 'fees', 'funding'):
            number(p[field], field, nonnegative=field in ('fees', 'entry_price'))
        if quantities[s]:
            number(p['entry_price'], 'entry price', positive=True)
    return quantities, marks


def reduced(old, new):
    return old != 0 and old * new >= 0 and abs(new) <= abs(old)


def rounded(value, step, rounding):
    return float((Decimal(str(value)) / Decimal(str(step))).to_integral_value(rounding=rounding) * Decimal(str(step)))


def execution_price(quote, delta, fill_price):
    """Same conservative price for projection, fill and ledger verification."""
    price = number(fill_price(quote, delta), 'fill price', positive=True)
    tick = quote.get('price_tick')
    if tick is not None:
        number(tick, 'price tick', positive=True)
        price = rounded(price, tick, ROUND_CEILING if delta > 0 else ROUND_FLOOR)
        number(price, 'rounded price', positive=True)
    return price


def plan(state, quotes, weights, equity, fill_price, max_gross, max_asset, *, market_guard=None):
    """Build every leg and verify every intermediate state BEFORE execution.

    Equity change from a fill is delta * (mark - price) - fee. This is
    independent of average-cost bookkeeping and includes existing P/L in the
    starting equity. Base quantities already include the contract multiplier.
    """
    quantities, marks = quantities_and_marks(state)
    if not isinstance(weights, dict):
        raise Rejected('invalid targets')
    required = {s for s, q in quantities.items() if q} | set(weights)
    if not required <= quotes.keys():
        raise Rejected('missing portfolio quotes')
    current = snapshot(quantities, marks, equity, max_gross, max_asset)
    legs = []
    for s in sorted(required):
        quote = quotes[s]
        mark = number(quote.get('mark_price'), 'mark', positive=True)
        weight = number(weights.get(s, 0), 'target weight')
        old = quantities.get(s, 0)
        # Exact closure requires no invented precision or non-positive-equity sizing.
        if weight == 0:
            new = 0.0
        else:
            if equity <= 0:
                raise Rejected('non_positive_equity')
            target = equity * weight / mark
            number(target, 'target quantity')
            if market_guard is not None:
                market_guard(s, quote, None, reduced(old, target))
            step = number(quote.get('step'), 'quantity step', positive=True)
            new = math.copysign(rounded(abs(target), step, ROUND_FLOOR), target)
        delta = float(Decimal(str(new)) - Decimal(str(old)))
        if delta == 0:
            continue
        protective = reduced(old, new)
        if market_guard is not None:
            market_guard(s, quote, delta, protective)
        fee_rate = number(quote.get('fee_rate'), 'fee rate', nonnegative=True)
        if fee_rate >= 1:
            raise Rejected('invalid fee rate')
        if not protective:
            step = number(quote.get('step'), 'quantity step', positive=True)
            declared_step = number(quote.get('quantity_step'), 'quantity precision', positive=True)
            if declared_step != step:
                raise Rejected('quantity step differs from declared precision')
            multiplier = number(quote.get('contract_multiplier'), 'contract multiplier', positive=True)
            units = Decimal(str(step)) / Decimal(str(multiplier))
            if units != units.to_integral_value() or units < 1:
                raise Rejected('quantity step inconsistent with contract multiplier')
            tick = number(quote.get('price_tick'), 'price tick', positive=True)
            minimum = number(quote.get('min_quantity'), 'minimum quantity', nonnegative=True)
            min_notional = number(quote.get('min_notional'), 'minimum notional', nonnegative=True)
            delta_units = abs(delta) / step
            grid_error = RATIO_ULPS * (math.ulp(old) + math.ulp(new) + math.ulp(delta)) / step
            if abs(delta_units - round(delta_units)) > grid_error:
                raise Rejected('delta violates quantity precision')
        # Missing tick metadata does not invent a price for protective exits:
        # those keep the observed depth VWAP and existing adverse slippage.
        price = execution_price(quote, delta, fill_price)
        if not protective and (abs(delta) < minimum or abs(delta * price) < min_notional):
            raise Rejected('below exchange minimum')
        fee = number(abs(delta * price) * fee_rate, 'projected fee', nonnegative=True)
        legs.append(dict(symbol=s, quantity=delta, resulting_quantity=new,
                         price=price, fee=fee, protective=protective))
    new_risk = any(not leg['protective'] for leg in legs)
    if new_risk and current['breaches']:
        raise Rejected('current_exposure_limit')
    # Reductions first, with deterministic order; a mixed intent is all-or-nothing.
    legs.sort(key=lambda leg: (not leg['protective'], leg['symbol']))
    projected = dict(quantities)
    for leg in legs:
        s = leg['symbol']
        equity += leg['quantity'] * (marks[s] - leg['price']) - leg['fee']
        projected[s] = leg['resulting_quantity']
        leg['exposure'] = snapshot(projected, marks, equity, max_gross, max_asset)
        if new_risk and leg['exposure']['breaches']:
            raise Rejected('projected_exposure_limit', leg['exposure'])
    return legs, current, new_risk
