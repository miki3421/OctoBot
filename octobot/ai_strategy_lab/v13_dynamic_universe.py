"""Offline candidate only. Card ea6b980a; no IO, grants, ledger or fills.

Caller supplies verified causal bars and an anchored previous decision. Hashes
provide reproducibility, not authentication. Persistent custody is not provided.
"""
import datetime as dt
import hashlib
import json
import math
import statistics

VERSION = 'v13-dynamic-universe-weekly-research-v2'
UNIVERSE = tuple(sorted(('AAVE ADA ARB ASTER ATOM AVAX BCH BTC DOGE DOT ENA ETH '
                         'HBAR HYPE INJ LINK LTC NEAR ONDO PUMP QNT SOL SUI TAO '
                         'UNI XLM XMR XRP ZEC').split()))
UNIVERSE = tuple(s + 'USDT' for s in UNIVERSE)
UTC = dt.timezone.utc


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(',', ':'),
                                     allow_nan=False).encode()).hexdigest()


def timestamp(value):
    t = dt.datetime.fromisoformat(value.replace('Z', '+00:00'))
    if t.tzinfo is None or t.utcoffset() != dt.timedelta(0):
        raise ValueError('utc_required')
    return t


def slot_index(slot, start):
    s, a = timestamp(slot), timestamp(start)
    if s.time() != dt.time(0, 15) or a.time() != dt.time(0, 15):
        raise ValueError('invalid_slot')
    days = (s - a).total_seconds() / 86400
    if days < 0 or days % 7:
        raise ValueError('not_weekly_slot')
    return int(days // 7)


def select(rows, previous=(), initial=False):
    """Pure selection kernel; rows contain already verified signals/scores."""
    if set(rows) != set(UNIVERSE) or len(set(previous)) != len(previous) or len(previous) > 18:
        raise ValueError('invalid_universe_or_state')
    if not set(previous) <= set(UNIVERSE) or (initial and previous):
        raise ValueError('invalid_previous_selection')
    for r in rows.values():
        if r['signal'] not in (-1, 0, 1) or isinstance(r['signal'], bool):
            raise ValueError('invalid_signal')
        score = r['score']
        if score is not None and (isinstance(score, bool) or not math.isfinite(score) or score <= 0):
            raise ValueError('invalid_score')
    ranked = sorted((s for s in rows if rows[s]['signal'] and rows[s]['score'] is not None),
                    key=lambda s: (-rows[s]['score'], s))
    chosen = set(ranked[:18] if initial else (s for s in previous if s in ranked))
    events = [{'symbol': s, 'reason': 'mandatory_exit'} for s in sorted(set(previous) - chosen)]
    if initial:
        events += [{'symbol': s, 'reason': 'initial_selection'} for s in sorted(chosen)]
    else:
        # Only incumbents can be replaced; no repeated churn of this slot's additions.
        incumbents = set(chosen)
        for _ in range(2):
            outsiders = [s for s in ranked if s not in chosen and s not in previous]
            # Former incumbents removed only for no signal cannot be eligible here.
            if not outsiders:
                break
            new = outsiders[0]
            if len(chosen) < 18:
                chosen.add(new)
                events.append({'symbol': new, 'reason': 'vacancy'})
                continue
            weakest = sorted(incumbents, key=lambda s: (rows[s]['score'], s))
            if not weakest:
                break
            old = weakest[0]
            if rows[new]['score'] <= 1.20 * rows[old]['score']:
                break
            chosen.remove(old)
            incumbents.remove(old)
            chosen.add(new)
            events.append({'symbol': new, 'replaces': old, 'reason': 'score_margin'})
    return sorted(chosen), events


def decide(bars, *, slot, start, lineage, previous=None, expected_previous_id=None):
    """Bars: symbol -> [{day: ISO date, close: number, received_at: UTC}].

    Only the last121 completed daily bars are consumed. Later bars and older
    acquisition payloads are irrelevant to decision identity. Raises on any
    invalid common input before returning a new state. No state is written.
    """
    index = slot_index(slot, start)
    if not isinstance(lineage, str) or not lineage.strip():
        raise ValueError('lineage_required')
    if set(bars) != set(UNIVERSE):
        raise ValueError('common_universe_required')
    boundary = timestamp(slot)
    last = boundary.date() - dt.timedelta(days=1)
    dates = [(last - dt.timedelta(days=n)).isoformat() for n in range(120, -1, -1)]
    causal = {}
    raw_signals = {}
    rows = {}
    for symbol in UNIVERSE:
        chosen = {}
        for bar in bars[symbol]:
            day = bar['day']
            if day not in dates:
                continue
            if day in chosen:
                raise ValueError('duplicate_causal_bar')
            close = bar['close']
            received = timestamp(bar['received_at'])
            closed = dt.datetime.combine(dt.date.fromisoformat(day) + dt.timedelta(days=1), dt.time(), UTC)
            if (isinstance(close, bool) or not isinstance(close, (int, float))
                    or not math.isfinite(close) or close <= 0 or not closed <= received <= boundary):
                raise ValueError('invalid_or_unavailable_bar')
            chosen[day] = float(close)
        if set(chosen) != set(dates):
            raise ValueError('missing_common_history')
        c = [chosen[d] for d in dates]
        causal[symbol] = [[d, chosen[d]] for d in dates]
        r30, r120 = c[-1] / c[-31] - 1, c[-1] / c[0] - 1
        signal = 1 if r30 > 0 and r120 > 0 else -1 if r30 < 0 and r120 < 0 else 0
        vol = statistics.stdev([c[i] / c[i-1] - 1 for i in range(61, 121)])
        score = min(abs(r30) / math.sqrt(30), abs(r120) / math.sqrt(120)) / vol if signal and vol > 0 else None
        if score is not None and not math.isfinite(score):
            raise ValueError('nonfinite_score')
        raw_signals[symbol] = signal
        rows[symbol] = dict(signal=signal, score=score)
    for s in UNIVERSE:
        if rows[s]['signal'] < 0 and raw_signals['BTCUSDT'] >= 0:
            rows[s]['signal'] = 0
    previous_symbols = ()
    parent = None
    if previous is not None:
        body = {k: v for k, v in previous.items() if k != 'decision_id'}
        parent = previous.get('decision_id')
        if (not expected_previous_id or parent != expected_previous_id or digest(body) != parent
                or previous.get('version') != VERSION or previous.get('lineage') != lineage
                or previous.get('start') != start):
            raise ValueError('previous_binding_mismatch')
        prior_index = slot_index(previous['slot'], start)
        if prior_index > index:
            raise ValueError('out_of_order')
        if prior_index == index:
            if previous['causal_hash'] != digest(causal):
                raise ValueError('slot_conflict')
            return json.loads(json.dumps(previous))
        previous_symbols = previous['selected']
    elif expected_previous_id is not None or index != 0:
        raise ValueError('previous_state_required')
    selected, events = select(rows, previous_symbols, initial=previous is None)
    result = dict(version=VERSION, lineage=lineage, start=start, slot=slot,
                  causal_hash=digest(causal), parent_id=parent, selected=selected,
                  rows=rows, events=events, scope='OFFLINE_CANDIDATE',
                  orders_authorized=False, paper_orders_authorized=False)
    result['decision_id'] = digest(result)
    return result


def target_weights(signals, covariance, symbols, selected):
    """Use the actual frozen V13 allocator; caller supplies its causal covariance.

    This adapter is not an executor or a standalone simulation. Validate the
    complete covariance rather than allowing the original allocator to replace
    invalid entries with zero. Actual covariance derivation is caller-owned.
    """
    import numpy as np
    from octobot.ai_strategy_lab import trend
    if len(set(symbols)) != len(symbols) or not set(selected) <= set(symbols):
        raise ValueError('invalid_mask')
    s = np.asarray(signals, dtype=float)
    cov = np.asarray(covariance, dtype=float)
    if s.shape != (len(symbols),) or cov.shape != (len(symbols), len(symbols)):
        raise ValueError('invalid_shape')
    if not np.isfinite(cov).all() or not np.isfinite(s).all() or not np.isin(s, [-1, 0, 1]).all():
        raise ValueError('invalid_numeric_input')
    if not np.allclose(cov, cov.T, rtol=0, atol=1e-12) or np.linalg.eigvalsh(cov).min() < -1e-12:
        raise ValueError('invalid_covariance')
    config = next(c for c in trend.TREND_CONFIGS if c.name == 'risk_budgeted_bear_regime_v13')
    masked = np.where([symbol in selected for symbol in symbols], s, 0.0)
    return trend._target_weights(masked, cov, config)
