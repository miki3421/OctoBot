"""Read-only V13 descriptive analytics. Card d9aa3d09; never imported by traders."""
import datetime as dt
import hashlib
import json
import math
from pathlib import Path
import re
import sqlite3

CONTRACT = 'qwen-v13-analysis-v1'
SCOPE = 'RESEARCH_SIMULATION_ONLY'
SYMBOL = re.compile(r'^[A-Z0-9]{2,24}USDT$')


def timestamp(value):
    result = dt.datetime.fromisoformat(str(value).replace('Z', '+00:00'))
    if result.tzinfo is None:
        raise ValueError('timezone_required')
    return result.astimezone(dt.timezone.utc)


def number(value):
    if isinstance(value, bool) or not isinstance(value, (float, int)) or not math.isfinite(value):
        raise ValueError('nonfinite_metric')
    return float(value)


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=False,
                                    separators=(',', ':'), allow_nan=False).encode()).hexdigest()


def window(points, end, seconds, activation):
    cutoff = end - dt.timedelta(seconds=seconds) if seconds else activation
    # Use real endpoints only. A nearby earlier point gives a faithful boundary;
    # otherwise expose the first later observation and flag incomplete coverage.
    before = [p for p in points if timestamp(p['time']) <= cutoff]
    first = before[-1] if before else next((p for p in points if timestamp(p['time']) >= cutoff), None)
    if first is None:
        return {'available': False, 'complete': False}
    selected = [p for p in points if timestamp(p['time']) >= timestamp(first['time'])]
    last = selected[-1]
    gaps = [(timestamp(b['time']) - timestamp(a['time'])).total_seconds()
            for a, b in zip(selected, selected[1:])]
    peak = selected[0]['equity']; drawdown = 0.0
    for p in selected:
        peak = max(peak, p['equity'])
        if peak > 0:
            drawdown = max(drawdown, 1 - p['equity'] / peak)
    start_equity = first['equity']; change = last['equity'] - start_equity
    return {'available': True, 'from': first['time'], 'to': last['time'],
            'requested_from': cutoff.isoformat(), 'observations': len(selected),
            'complete': abs((timestamp(first['time']) - cutoff).total_seconds()) <= 180
                        and (end - timestamp(last['time'])).total_seconds() <= 180
                        and not any(g > 1800 for g in gaps),
            'gap_count': sum(g > 1800 for g in gaps), 'max_gap_seconds': max(gaps, default=0),
            'net_change': change,
            'return_pct': change / start_equity * 100 if start_equity > 0 else None,
            'observed_drawdown_pct': drawdown * 100}


def calculate(state, history, fills, now=None):
    now = now or dt.datetime.now(dt.timezone.utc)
    if state.get('mode') != 'trend_v13_paper_v2' or not state.get('research_epoch'):
        raise ValueError('wrong_account_scope')
    activation = timestamp(state['activation_at']); as_of = timestamp(state['last_success_at'])
    if not 0 <= (now - as_of).total_seconds() <= 180:
        raise ValueError('stale_account')
    initial = number(state['initial_equity'])
    if initial <= 0 or not history:
        raise ValueError('missing_account_history')
    positions = state['positions']
    if not isinstance(positions, dict) or len(positions) > 100:
        raise ValueError('invalid_positions')
    counts = {s: {'fills': 0, 'reductions': 0, 'full_exits': 0} for s in positions}
    running = {s: 0.0 for s in positions}; fill_fees = {s: 0.0 for s in positions}
    for fill in fills:
        s = fill['symbol']; q = number(fill['quantity']); price = number(fill['price']); fee = number(fill['fee'])
        when = timestamp(fill['bar'])
        if s not in positions or not SYMBOL.fullmatch(s) or price <= 0 or fee < 0 or q == 0:
            raise ValueError('invalid_fill')
        if not activation <= when <= as_of or fill['action'] != ('BUY' if q > 0 else 'SELL'):
            raise ValueError('invalid_fill_identity')
        old = running[s]
        counts[s]['fills'] += 1
        if old * q < 0:
            counts[s]['reductions'] += 1
            if abs(q) >= abs(old) - 1e-10:
                counts[s]['full_exits'] += 1
        running[s] += q; fill_fees[s] += fee
    rows = []
    for s, p in positions.items():
        if not SYMBOL.fullmatch(s):
            raise ValueError('invalid_symbol')
        q = number(p['quantity']); entry = number(p['entry_price']); mark = number(p['current_price'])
        realized = number(p['realized_pnl']); fees = number(p['fees']); funding = number(p['funding'])
        if fees < 0 or (q and (entry <= 0 or mark <= 0)):
            raise ValueError('invalid_position')
        if not math.isclose(running[s], q, rel_tol=1e-9, abs_tol=1e-8) or not math.isclose(fill_fees[s], fees, rel_tol=1e-9, abs_tol=1e-6):
            raise ValueError('incomplete_fill_history')
        unrealized = q * (mark - entry)
        rows.append({'symbol': s, 'realized_pnl': realized, 'unrealized_pnl': unrealized,
                     'fees': fees, 'funding': funding, 'net_pnl': realized + unrealized + funding - fees,
                     'notional': abs(q * mark), 'quantity': q, **counts[s]})
    totals = {k: math.fsum(r[k] for r in rows) for k in
              ['realized_pnl', 'unrealized_pnl', 'fees', 'funding', 'net_pnl', 'notional']}
    equity = initial + totals['net_pnl']; points = []; previous = None
    for p in history:
        t = timestamp(p['bar']); e = number(p['equity']); pnl = number(p['pnl'])
        if t < activation or t > as_of or (previous is not None and t <= previous):
            raise ValueError('invalid_history_clock')
        if not math.isclose(e - initial, pnl, abs_tol=1e-6):
            raise ValueError('unreconciled_history')
        points.append({'time': p['bar'], 'equity': e}); previous = t
    if timestamp(points[-1]['time']) != as_of or not math.isclose(points[-1]['equity'], equity, abs_tol=1e-6):
        raise ValueError('unreconciled_account')
    for r in rows:
        r['weight_pct'] = r['notional'] / equity * 100 if equity > 0 else None
    rows.sort(key=lambda r: (-r['net_pnl'], r['symbol']))
    positive = math.fsum(max(0, r['net_pnl']) for r in rows)
    return {'as_of': as_of.isoformat(), 'activation_at': activation.isoformat(),
            'initial_equity': initial, 'equity': equity, 'totals': totals, 'symbols': rows,
            'return_pct': totals['net_pnl'] / initial * 100,
            'gross_exposure_pct': totals['notional'] / equity * 100 if equity > 0 else None,
            'largest_weight_pct': max((r['weight_pct'] for r in rows if r['weight_pct'] is not None), default=None),
            'top_positive_contribution_pct': max((r['net_pnl'] for r in rows), default=0) / positive * 100 if positive > 0 else None,
            'positive_symbols': sum(r['net_pnl'] > 0 for r in rows),
            'negative_symbols': sum(r['net_pnl'] < 0 for r in rows),
            'fills': len(fills), 'reductions': sum(r['reductions'] for r in rows),
            'windows': {name: window(points, as_of, seconds, activation)
                        for name, seconds in [('24h', 86400), ('7d', 604800), ('all', None)]},
            'funding_quality': 'ESTIMATED', 'min_quantity': 'UNKNOWN', 'min_notional': 'UNKNOWN'}


def load_metrics(root='/v13-paper', now=None):
    root = Path(root) / 'research' / 'execution'
    health = json.loads((root / 'health-research.json').read_text())
    if (health.get('execution_scope') != SCOPE or health.get('mode') != 'trend_v13_paper_v2'
            or health.get('credentials_used') is not False or health.get('orders_authorized') is not False
            or health.get('min_quantity') != 'UNKNOWN' or health.get('min_notional') != 'UNKNOWN'):
        raise ValueError('wrong_health_scope')
    database = root / 'execution.sqlite'
    if not database.is_file():
        raise FileNotFoundError('missing_ledger')
    def read(uri):
        with sqlite3.connect(uri, uri=True, timeout=2) as c:
            c.row_factory = sqlite3.Row; c.execute('BEGIN')
            state = json.loads(c.execute('SELECT payload FROM state WHERE id=1').fetchone()[0])
            history = [dict(r) for r in c.execute('SELECT bar,equity,pnl FROM equity_history ORDER BY bar')]
            fills = [dict(r) for r in c.execute("SELECT bar,symbol,quantity,price,fee,action FROM orders WHERE status='filled' ORDER BY bar,id")]
        return calculate(state, history, fills, now)
    uri = database.resolve().as_uri() + '?mode=ro'
    try:
        return read(uri)
    except sqlite3.OperationalError:
        wal = Path(str(database) + '-wal')
        if wal.exists() and wal.stat().st_size:
            raise
        return read(uri + '&immutable=1')


def snapshot(metrics, now=None):
    now = now or dt.datetime.now(dt.timezone.utc); t = metrics['totals']; evidence = {}
    def fact(id, text):
        evidence[id] = text
    fact('account', f"Dall'attivazione {metrics['activation_at']}: P/L netto {t['net_pnl']:.2f} USDT; rendimento {metrics['return_pct']:.2f}%; equity {metrics['equity']:.2f} USDT. Capitale virtuale e fill simulati.")
    fact('composition', f"P/L realizzato {t['realized_pnl']:.2f}, aperto {t['unrealized_pnl']:.2f}, commissioni {t['fees']:.2f}, funding stimato {t['funding']:.2f} USDT. Il P/L aperto può cambiare; slippage incluso nei prezzi, non conteggiato due volte.")
    fact('sample', f"Storico dal {metrics['activation_at']}; fill {metrics['fills']}, riduzioni {metrics['reductions']}. Riduzioni parziali non equivalgono a trade indipendenti. Nessuna validazione scientifica o stima affidabile di profitto futuro.")
    fact('breadth', f"Simboli con contributo netto positivo {metrics['positive_symbols']}, negativo {metrics['negative_symbols']}. Contributi assoluti non comparabili come rendimento per capitale.")
    gross = metrics['gross_exposure_pct']; largest = metrics['largest_weight_pct']; top = metrics['top_positive_contribution_pct']
    fact('concentration', 'Esposizione lorda '+(f'{gross:.2f}%' if gross is not None else 'UNKNOWN')+', peso massimo '+(f'{largest:.2f}%' if largest is not None else 'UNKNOWN')+', contributo del miglior simbolo sulla somma dei contributi positivi '+(f'{top:.2f}%' if top is not None else 'UNKNOWN')+'. Esposizione e concentrazione dei guadagni sono concetti distinti.')
    for name, w in metrics['windows'].items():
        if w['available']:
            fact('window_'+name, f"Finestra {name}: osservazioni da {w['from']} a {w['to']}, variazione netta {w['net_change']:.2f} USDT, drawdown osservato {w['observed_drawdown_pct']:.2f}%; copertura {'completa' if w['complete'] else 'INCOMPLETA'}, gap oltre trenta minuti {w['gap_count']}. Nessuna interpolazione; i gap possono nascondere picchi/perdite.")
    for i, r in enumerate(metrics['symbols']):
        fact('symbol_'+str(i), f"{r['symbol']}: contributo netto {r['net_pnl']:.2f} USDT; realizzato {r['realized_pnl']:.2f}, aperto {r['unrealized_pnl']:.2f}, commissioni {r['fees']:.2f}, funding stimato {r['funding']:.2f}; fill {r['fills']}, riduzioni {r['reductions']}, uscite complete {r['full_exits']}. Questi contatori non dimostrano redditività persistente.")
    core = {'contract': CONTRACT, 'scope': SCOPE, 'as_of': metrics['as_of'], 'metrics': metrics, 'evidence': evidence}
    return {**core, 'snapshot_id': digest(core), 'generated_at': now.isoformat()}
