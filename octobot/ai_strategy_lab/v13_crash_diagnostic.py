"""Offline exploratory early-warning diagnostics, never a trading entrypoint.

Card work-card-a70c873b-71b2-4158-afc2-2a86b5af336a. Rows contain only
prices already observed at their timestamp. No model fitting or parameter search.
"""
import bisect
import math


def features(rows, index):
    """Require a contiguous five-minute past; never inspect a future row."""
    if index < 288:
        return None
    past = rows[index - 288:index + 1]
    if any(b['time'] - a['time'] != 300 for a, b in zip(past, past[1:])):
        return None
    symbols = set(past[-1]['prices'])
    if len(symbols) != 18 or 'BTCUSDT' not in symbols:
        return None
    if any(set(r['prices']) != symbols or any(
            not math.isfinite(p) or p <= 0 for p in r['prices'].values()) for r in past):
        return None
    current, hour = past[-1]['prices'], past[-13]['prices']
    returns = {s: current[s] / hour[s] - 1 for s in symbols}
    return dict(btc_60m=returns['BTCUSDT'],
                negative_breadth=sum(v < 0 for v in returns.values()) / len(symbols),
                new_24h_low=current['BTCUSDT'] < min(r['prices']['BTCUSDT'] for r in past[:-1]))


def signal(feature, rule):
    if feature is None:
        return False
    breadth = feature['negative_breadth'] >= 2 / 3
    if rule == 'momentum_breadth':
        return breadth and feature['btc_60m'] <= -.01
    if rule == 'breakout_breadth':
        return breadth and feature['new_24h_low']
    raise ValueError('unknown_rule')


def episodes(rows, rule):
    """Execute after >=60 seconds; hold six hours, non-overlapping episodes.

    A missing outcome is retained as censored. Price gaps cannot supply an
    executable entry or exit. Thresholds and holding time are fixed in protocol.
    """
    times = [r['time'] for r in rows]
    if any(not math.isfinite(t) for t in times) or any(b <= a for a, b in zip(times, times[1:])):
        raise ValueError('invalid_clock_order')
    result, ready = [], -math.inf
    for i, row in enumerate(rows):
        if row['time'] < ready or not signal(features(rows, i), rule):
            continue
        entry = bisect.bisect_left(times, row['time'] + 60)
        if entry == len(rows) or times[entry] - row['time'] > 360:
            continue
        exit_ = bisect.bisect_left(times, times[entry] + 21600)
        complete = exit_ < len(rows) and times[exit_] - times[entry] <= 21900
        result.append(dict(signal_index=i, entry_index=entry,
                           exit_index=exit_ if complete else None,
                           feature=features(rows, i)))
        ready = times[entry] + 21600 + 21600
    return result


def vwap(levels, quantity):
    if not math.isfinite(quantity) or quantity <= 0:
        raise ValueError('invalid_quantity')
    remaining, value = quantity, 0.
    for price, available in levels:
        if not all(math.isfinite(v) and v > 0 for v in (price, available)):
            raise ValueError('invalid_depth')
        take = min(remaining, available)
        value += take * price
        remaining -= take
        if remaining <= 1e-10:
            return value / quantity
    raise ValueError('insufficient_depth')


def trade_pnl(side, quantity, entry, exit_, funding):
    """Book VWAP + adverse 2bps each side, >=6bps fee; funding is mandatory."""
    if side not in (-1, 1) or funding is None or not math.isfinite(funding):
        raise ValueError('unknown_side_or_funding')
    buy_entry = side == 1
    pe = vwap(entry['asks' if buy_entry else 'bids'], quantity) * (1 + side * .0002)
    px = vwap(exit_['bids' if buy_entry else 'asks'], quantity) * (1 - side * .0002)
    fee = quantity * (pe * max(.0006, entry['fee_rate']) + px * max(.0006, exit_['fee_rate']))
    gross = side * quantity * (px - pe)
    return dict(gross=gross, fee=fee, funding=funding, net=gross-fee+funding,
                entry_price=pe, exit_price=px, quantity=quantity)
