"""Unmodified M1 feature/signal reference for the isolated Timestral study.

Extracted from v13_crash_diagnostic.py, SHA-256
f5b9b722716dfb2d4d4d9de092ba465e6bd7405b69ab684d57aaf492d43142d3.
Keep the deliverable independent of untracked historical worktree files.
Card: work-card-54f64f8b-68bc-4183-892b-eb73d03165fa.
"""
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
