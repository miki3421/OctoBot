"""Read-only observed prices and position-aware fills. Card 041b5bcb."""
import datetime as dt
from decimal import Decimal
import json
import math
from pathlib import Path
import re
import sqlite3
from collections import defaultdict

SYMBOL = re.compile(r'^[A-Z0-9]{2,24}USDT$')
MAX_POINTS = 20000
OVERVIEW_POINTS = 800


def timestamp(value):
    result = dt.datetime.fromisoformat(value.replace('Z', '+00:00'))
    if result.tzinfo is None:
        raise ValueError('timezone_required')
    return result.astimezone(dt.timezone.utc)


def number(value):
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
        raise ValueError('invalid_number')
    return float(value)


def transition(before, delta):
    """Signed base-asset quantity; a crossing fill closes and opens exposure."""
    old, change = Decimal(str(number(before))), Decimal(str(number(delta)))
    if not change:
        raise ValueError('zero_fill')
    after = old + change
    # Suppress floating-point residue, not meaningful small positions.
    if abs(after) <= Decimal('1e-12') * max(abs(old), abs(change)):
        after = Decimal(0)
    side = 'long' if after > 0 else 'short'
    previous = 'long' if old > 0 else 'short'
    if not old:
        kind, label = 'open', 'Apertura ' + side
    elif not after:
        kind, label = 'close', 'Chiusura ' + previous
    elif old * after < 0:
        kind, label = 'reverse', 'Chiusura ' + previous + ' + apertura ' + side
    elif old * change > 0:
        kind, label = 'increase', 'Aumento ' + side
    else:
        kind, label = 'reduce', 'Riduzione ' + previous
    closed = min(abs(old), abs(change)) if old * change < 0 else Decimal(0)
    return {'kind': kind, 'label': label, 'before': float(old), 'after': float(after),
            'closed_quantity': float(closed), 'opened_quantity': float(abs(change) - closed)}


def fill_accounting(before, entry, delta, price, fee, mark):
    """Average-cost realization, separate from equity change at a fixed mark.

    The research orders.realized_pnl field is cumulative while legacy rows
    store deltas. Replay quantities/prices rather than mixing those meanings.
    """
    before, entry, delta, price = map(number, (before, entry, delta, price))
    effect = transition(before, delta)
    if price <= 0 or (before and entry <= 0):
        raise ValueError('invalid_cost_basis')
    fee = number(fee) if fee is not None else None
    mark = number(mark) if mark is not None else None
    if (fee is not None and fee < 0) or (mark is not None and mark <= 0):
        raise ValueError('invalid_fill_cost')
    realized = effect['closed_quantity'] * (price - entry) * (1 if before > 0 else -1) if effect['closed_quantity'] else 0.0
    after = effect['after']
    if not after:
        next_entry = 0.0
    elif not before or before * after < 0:
        next_entry = price
    elif before * delta > 0:
        next_entry = (abs(before) * entry + abs(delta) * price) / abs(after)
    else:
        next_entry = entry
    unrealized_change = None if mark is None else after * (mark - next_entry) - before * (mark - entry)
    equity_impact = None if mark is None or fee is None else delta * (mark - price) - fee
    if equity_impact is not None and not math.isclose(
            equity_impact, realized + unrealized_change - fee, rel_tol=1e-8, abs_tol=1e-7):
        raise ValueError('fill_equity_does_not_reconcile')
    return {'realized_pnl': realized, 'fee': fee,
            'realized_less_fill_fee': None if fee is None else realized - fee,
            'unrealized_change': unrealized_change, 'equity_impact': equity_impact,
            'reference_mark': mark, 'entry_after': next_entry}


def project(state, fills, marks, symbol, now=None, truncated=False):
    now = now or dt.datetime.now(dt.timezone.utc)
    if state.get('mode') != 'trend_v13_paper_v2' or not state.get('research_epoch'):
        raise ValueError('wrong_account')
    positions = state['positions']
    if not positions or any(not SYMBOL.fullmatch(s) for s in positions):
        raise ValueError('invalid_symbols')
    if symbol not in positions:
        raise ValueError('unknown_symbol')
    start, as_of = timestamp(state['activation_at']), timestamp(state['last_success_at'])
    if as_of < start or as_of > now:
        raise ValueError('invalid_account_time')
    running, last_id, events = 0.0, 0, []
    entry, realized_total, fees_total, fees_complete = 0.0, 0.0, 0.0, True
    for fill in fills:
        q, price = number(fill['quantity']), number(fill['price'])
        quoted = timestamp(fill['bar'])
        executed = timestamp(fill['recorded_at']) if fill.get('recorded_at') else quoted
        if (fill['id'] <= last_id or fill['symbol'] != symbol or price <= 0
                or not start <= quoted <= executed <= as_of
                or fill['action'] != ('BUY' if q > 0 else 'SELL')):
            raise ValueError('invalid_fill')
        effect = transition(running, q)
        accounting = fill_accounting(running, entry, q, price, fill.get('fee'), fill.get('reference_mark'))
        entry = accounting['entry_after']
        realized_total += accounting['realized_pnl']
        if accounting['fee'] is None:
            fees_complete = False
        else:
            fees_total += accounting['fee']
        events.append({'id': fill['id'], 'time': executed.isoformat(),
                       'quote_time': quoted.isoformat(),
                       'time_basis': 'execution' if fill.get('recorded_at') else 'quote_only',
                       'action': fill['action'], 'quantity': q, 'price': price, **effect, **accounting})
        running, last_id = effect['after'], fill['id']
    quantity = number(positions[symbol]['quantity'])
    if not math.isclose(running, quantity, rel_tol=1e-9, abs_tol=1e-10):
        raise ValueError('incomplete_fill_history')
    position = positions[symbol]
    for key, calculated in [('entry_price', entry), ('realized_pnl', realized_total), ('fees', fees_total)]:
        if key in position and (key != 'fees' or fees_complete):
            if not math.isclose(number(position[key]), calculated, rel_tol=1e-9, abs_tol=1e-6):
                raise ValueError('fill_accounting_does_not_reconcile')
    points, last_time, gaps = [], None, 0
    for mark in marks:
        t, price = timestamp(mark['bar']), number(mark['price'])
        if price <= 0 or not start <= t <= as_of or (last_time and t <= last_time):
            raise ValueError('invalid_price_history')
        gap = last_time is not None and (t - last_time).total_seconds() > 1800
        gaps += int(gap)
        points.append({'time': t.isoformat(), 'price': price, 'gap_before': gap})
        last_time = t
    return {'available': True, 'symbol': symbol, 'symbols': sorted(positions),
            'as_of': as_of.isoformat(), 'stale': (now - as_of).total_seconds() > 180,
            'activation_at': start.isoformat(), 'quantity': quantity,
            'position': 'LONG' if quantity > 0 else 'SHORT' if quantity < 0 else 'FLAT',
            'points': points, 'fills': events, 'gaps': gaps,
            'prices_truncated': truncated, 'max_points': MAX_POINTS}


def load(symbol=None, root='/v13-paper', now=None):
    root = Path(root) / 'research' / 'execution'
    health = json.loads((root / 'health-research.json').read_text())
    if health.get('execution_scope') != 'RESEARCH_SIMULATION_ONLY' or health.get('orders_authorized') is not False:
        raise ValueError('wrong_scope')
    path = root / 'execution.sqlite'
    if not path.is_file():
        raise FileNotFoundError('missing_ledger')
    with sqlite3.connect(path.resolve().as_uri() + '?mode=ro', uri=True, timeout=3) as db:
        db.row_factory = sqlite3.Row
        db.execute('PRAGMA query_only=ON')
        db.execute('BEGIN')
        state = json.loads(db.execute('SELECT payload FROM state WHERE id=1').fetchone()[0])
        if db.execute("SELECT COUNT(*) FROM orders WHERE status='filled'").fetchone()[0] != state['order_count']:
            raise ValueError('incomplete_fill_history')
        symbol = symbol or ('BTCUSDT' if 'BTCUSDT' in state['positions'] else sorted(state['positions'])[0])
        if not isinstance(symbol, str) or not SYMBOL.fullmatch(symbol) or symbol not in state['positions']:
            raise ValueError('unknown_symbol')
        fills = [dict(r) for r in db.execute(
            "SELECT o.id,o.bar,o.recorded_at,o.symbol,o.action,o.quantity,o.price,o.fee,"
            "m.price AS reference_mark FROM orders o LEFT JOIN marks m "
            "ON m.symbol=o.symbol AND m.bar=o.bar "
            "WHERE o.status='filled' AND o.symbol=? ORDER BY o.id", (symbol,))]
        marks = [dict(r) for r in db.execute(
            'SELECT bar,price FROM marks WHERE symbol=? ORDER BY bar DESC LIMIT ?', (symbol, MAX_POINTS + 1))]
        return project(state, fills, list(reversed(marks[:MAX_POINTS])), symbol, now, len(marks) > MAX_POINTS)


def compact_points(points, limit=OVERVIEW_POINTS):
    """Keep observed extrema and endpoints; never connect through a source gap."""
    if len(points) <= limit:
        return points
    selected = {0, len(points)-1}
    buckets = (limit-2)//2
    for bucket in range(buckets):
        start = 1 + bucket*(len(points)-2)//buckets
        end = 1 + (bucket+1)*(len(points)-2)//buckets
        if start < end:
            selected.add(min(range(start,end), key=lambda i:points[i]['price']))
            selected.add(max(range(start,end), key=lambda i:points[i]['price']))
    result=[];previous=-1
    for index in sorted(selected):
        point=dict(points[index])
        point['gap_before']=any(p['gap_before'] for p in points[previous+1:index+1]) if previous>=0 else False
        result.append(point);previous=index
    return result


def load_overview(period='all', root='/v13-paper', now=None):
    """One coherent read-only snapshot for all charts, compacted for display."""
    if period not in ('all','1','7'):
        raise ValueError('unknown_chart_period')
    directory=Path(root)/'research/execution'
    health=json.loads((directory/'health-research.json').read_text())
    if health.get('execution_scope')!='RESEARCH_SIMULATION_ONLY' or health.get('orders_authorized') is not False:
        raise ValueError('wrong_scope')
    database=directory/'execution.sqlite'
    if not database.is_file():raise FileNotFoundError('missing_ledger')
    with sqlite3.connect(database.resolve().as_uri()+'?mode=ro',uri=True,timeout=3) as db:
        db.row_factory=sqlite3.Row;db.execute('PRAGMA query_only=ON');db.execute('BEGIN')
        state=json.loads(db.execute('SELECT payload FROM state WHERE id=1').fetchone()[0])
        start,as_of=timestamp(state['activation_at']),timestamp(state['last_success_at'])
        cutoff=start if period=='all' else max(start,as_of-dt.timedelta(days=int(period)))
        fills=defaultdict(list)
        for row in db.execute("SELECT o.id,o.bar,o.recorded_at,o.symbol,o.action,o.quantity,o.price,o.fee,"
            "m.price AS reference_mark FROM orders o LEFT JOIN marks m ON m.symbol=o.symbol AND m.bar=o.bar "
            "WHERE o.status='filled' ORDER BY o.id"):
            fills[row['symbol']].append(dict(row))
        if sum(map(len,fills.values()))!=state['order_count'] or set(fills)-set(state['positions']):
            raise ValueError('incomplete_fill_history')
        marks=defaultdict(list)
        for row in db.execute('SELECT symbol,bar,price FROM (SELECT symbol,bar,price, '
            'ROW_NUMBER() OVER(PARTITION BY symbol ORDER BY bar DESC) AS n FROM marks WHERE bar>=? AND bar<=?) '
            'WHERE n<=? ORDER BY symbol,bar',(cutoff.isoformat(),as_of.isoformat(),MAX_POINTS+1)):
            marks[row['symbol']].append(dict(row))
        charts=[]
        for symbol in sorted(state['positions']):
            prices=marks[symbol]
            chart=project(state,fills[symbol],prices[-MAX_POINTS:],symbol,now,len(prices)>MAX_POINTS)
            chart['total_fills']=len(chart['fills'])
            chart['fills']=[f for f in chart['fills'] if timestamp(f['time'])>=cutoff]
            chart['observed_points']=len(chart['points'])
            chart['points']=compact_points(chart['points'])
            charts.append(chart)
        return dict(available=True,as_of=as_of.isoformat(),from_time=cutoff.isoformat(),period=period,
                    stale=any(c['stale'] for c in charts),symbols=sorted(state['positions']),charts=charts)
