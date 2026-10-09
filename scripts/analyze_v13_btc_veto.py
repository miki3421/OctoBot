"""Exploratory offline matched-order study. No operational writes or grants.

Card work-card-7d58d1a7-bcf5-4aa9-be63-edea482ac6a9.
Inputs are consistent copies; market receipts are read-only. Never a new issuer.
"""
import argparse
from bisect import bisect_right
from collections import defaultdict
import datetime as dt
import gzip
import hashlib
import json
from pathlib import Path
import sqlite3
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from octobot.ai_strategy_lab import v13_exposure as exposure, v13_market as market


def timestamp(value):
    return dt.datetime.fromisoformat(value.replace('Z', '+00:00')).timestamp()


def load_book(root, digest):
    path = Path(root) / (digest + '.json.gz')
    if path.is_symlink():
        raise ValueError('symlink_market')
    payload = json.loads(gzip.decompress(path.read_bytes()))
    expected = hashlib.sha256(json.dumps({k: v for k, v in payload.items() if k != 'record_hash'},
        sort_keys=True, separators=(',', ':'), allow_nan=False).encode()).hexdigest()
    if expected != digest or payload['record_hash'] != digest or payload['scope'] != 'RESEARCH_SIMULATION_ONLY':
        raise ValueError('market_binding')
    return payload


def matched_quantity(old, baseline_delta, veto):
    if old < -1e-10:
        raise ValueError('long_only_diagnostic_required')
    return 0. if baseline_delta > 0 and veto else (
        max(baseline_delta, -old) if baseline_delta < 0 else baseline_delta)


def read_db(path):
    db = sqlite3.connect(Path(path).resolve().as_uri() + '?mode=ro&immutable=1', uri=True)
    db.row_factory = sqlite3.Row
    db.execute('PRAGMA query_only=ON')
    if db.execute('PRAGMA integrity_check').fetchone()[0] != 'ok':
        db.close()
        raise ValueError('snapshot_integrity')
    return db


def study(execution, approvals, books):
    db = read_db(execution)
    approval_db = read_db(approvals)
    approval = sorted([json.loads(r['payload']) for r in approval_db.execute('SELECT payload FROM approvals')],
                      key=lambda a: a['issued_at'])
    orders = [dict(r) for r in db.execute("SELECT * FROM orders WHERE status='filled' ORDER BY bar,id")]
    history = [dict(r) for r in db.execute('SELECT * FROM equity_history ORDER BY bar')]
    funding = [dict(r) for r in db.execute('SELECT * FROM funding_events ORDER BY timestamp_ms,symbol')]
    marks = [dict(r) for r in db.execute('SELECT * FROM marks ORDER BY bar,symbol')]
    actual_state = json.loads(db.execute('SELECT payload FROM state WHERE id=1').fetchone()['payload'])
    db.close(); approval_db.close()
    if (actual_state.get('mode') != 'trend_v13_paper_v2' or not actual_state.get('research_epoch')
            or any(a.get('scope') != 'RESEARCH_SIMULATION_ONLY' or
                   a.get('epoch') != actual_state['research_epoch'] for a in approval)):
        raise ValueError('wrong_research_account_scope')
    # Strategic updates are distinguished from daily republication of unchanged weights.
    updates = []
    previous = None
    for a in approval:
        weights = {s: float(w) for s, w in a['targets'].items()}
        if previous is None or weights != previous:
            drop = previous is not None and 0 < weights['BTCUSDT'] < previous['BTCUSDT']
            updates.append(dict(at=timestamp(a['issued_at']), day=a['day'], decision=a['decision_id'],
                veto=drop, btc=weights['BTCUSDT'], previous_btc=previous['BTCUSDT'] if previous else None,
                active=sum(w != 0 for w in weights.values())))
            previous = weights
    update_times = [u['at'] for u in updates]

    def veto_at(at):
        i = bisect_right(update_times, at) - 1
        return updates[i] if i >= 0 else None

    symbols = sorted(actual_state['positions'])
    arms = {name: dict(q=defaultdict(float), cash=defaultdict(float), fees=defaultdict(float),
                      funding=defaultdict(float), fills=0, skipped=0, curves=[], handled=set())
            for name in ('baseline', 'veto_entries', 'veto_exit')}
    events = [(timestamp(o['bar']), 1, 'order', o) for o in orders]
    events += [(r['timestamp_ms'] / 1000, 0, 'funding', r) for r in funding]
    events.sort(key=lambda x: (x[0], x[1]))
    event_index = mark_index = 0
    prices = {}
    cache = {}
    triggers = []

    def fill(arm, symbol, quantity, price, fee):
        arm['q'][symbol] += quantity
        arm['cash'][symbol] -= quantity * price
        arm['fees'][symbol] += fee
        arm['fills'] += 1

    for point in history:
        at = timestamp(point['bar'])
        while event_index < len(events) and events[event_index][0] <= at:
            when, _, kind, row = events[event_index]
            event_index += 1
            if kind == 'funding':
                for name, arm in arms.items():
                    if name == 'baseline':
                        amount = row['amount']
                    else:
                        # Same recorded settlement rate and ESTIMATED previous mark.
                        amount = -arm['q'][row['symbol']] * row['reference_mark'] * row['rate']
                    arm['funding'][row['symbol']] += amount
                continue
            update = veto_at(when)
            veto = bool(update and update['veto'])
            fill(arms['baseline'], row['symbol'], row['quantity'], row['price'], row['fee'])
            if veto and row['decision_hash'] == update['decision'] and update['decision'] not in arms['veto_exit']['handled']:
                digest = row['market_hash']
                book = cache.setdefault(digest, load_book(books, digest))
                if timestamp(book['observed_at_end']) > when or timestamp(book['observed_at_start']) <= update['at']:
                    raise ValueError('noncausal_trigger_book')
                arms['veto_exit']['handled'].add(update['decision'])
                # Close positions held immediately before this observed batch, not its future buys.
                close_arm = arms['veto_exit']
                closed = []
                for s in symbols:
                    q = close_arm['q'][s]
                    if q:
                        quote = book['quotes'][s]
                        if not 0 <= when - timestamp(quote['timestamp']) <= 60:
                            raise ValueError('stale_exit_book')
                        price = exposure.execution_price(quote, -q, market.fill_price)
                        fee = abs(q * price) * quote['fee_rate']
                        fill(close_arm, s, -q, price, fee)
                        closed.append(s)
                triggers.append(dict(day=update['day'], issuer_at=dt.datetime.fromtimestamp(update['at'],dt.timezone.utc).isoformat(),
                    execution_at=row['bar'], previous_btc_weight=update['previous_btc'],
                    btc_weight=update['btc'], active=update['active'], closed_symbols=closed, market_hash=digest))
            for name in ('veto_entries', 'veto_exit'):
                arm = arms[name]
                quantity = matched_quantity(arm['q'][row['symbol']], row['quantity'], veto)
                if abs(quantity) < 1e-12:
                    arm['skipped'] += 1
                    continue
                if abs(quantity - row['quantity']) < 1e-10:
                    price, fee = row['price'], row['fee']
                else:
                    digest = row['market_hash']
                    book = cache.setdefault(digest, load_book(books, digest))
                    quote = book['quotes'][row['symbol']]
                    price = exposure.execution_price(quote, quantity, market.fill_price)
                    fee = abs(quantity * price) * quote['fee_rate']
                fill(arm, row['symbol'], quantity, price, fee)
                if not -1e-9 <= arm['q'][row['symbol']] <= arms['baseline']['q'][row['symbol']] + 1e-9:
                    raise ValueError('counterfactual_position_bound')
        while mark_index < len(marks) and timestamp(marks[mark_index]['bar']) <= at:
            mark = marks[mark_index]
            prices[mark['symbol']] = mark['price']
            mark_index += 1
        calculated = {}
        for name, arm in arms.items():
            calculated[name] = 10000 + sum(arm['q'][s] * prices.get(s, 0) + arm['cash'][s] -
                arm['fees'][s] + arm['funding'][s] for s in symbols)
        for name, arm in arms.items():
            # Keep the actual observed baseline curve; compare matched cashflows.
            arm['curves'].append(dict(at=point['bar'], equity=point['equity'] + calculated[name] - calculated['baseline']))
    result = {}
    for name, arm in arms.items():
        peak = arm['curves'][0]['equity']; drawdown = 0.
        for point in arm['curves']:
            peak = max(peak, point['equity'])
            drawdown = max(drawdown, 1 - point['equity'] / peak)
        contributions = {s: arm['q'][s] * prices[s] + arm['cash'][s] - arm['fees'][s] + arm['funding'][s] for s in symbols}
        result[name] = dict(equity=arm['curves'][-1]['equity'], max_drawdown_pct=drawdown * 100,
            fees=sum(arm['fees'].values()), funding=sum(arm['funding'].values()), fills=arm['fills'],
            skipped=arm['skipped'], contributions=contributions, curves=arm['curves'])
    final_error = abs(result['baseline']['equity'] - (10000 + sum(result['baseline']['contributions'].values())))
    if final_error > 1e-6:
        raise ValueError('baseline_final_reconciliation')
    return dict(scope='EXPLORATORY_MATCHED_ORDER_RESEARCH_NOT_VALIDATION',
        as_of=history[-1]['bar'], updates=updates, triggers=triggers, arms=result,
        baseline_final_error=final_error, funding_quality='ESTIMATED',
        kucoin_min_quantity='UNKNOWN', kucoin_min_notional='UNKNOWN', operational=False)


def main():
    p = argparse.ArgumentParser(description=__doc__)
    for name in ('execution', 'approvals', 'books', 'output'):
        p.add_argument('--' + name, required=True)
    args = p.parse_args()
    result = study(args.execution, args.approvals, args.books)
    with Path(args.output).open('x') as stream:
        json.dump(result, stream, indent=2)
    print(json.dumps({name: {k: value[k] for k in ('equity','max_drawdown_pct','fees','funding','fills','skipped')}
                      for name, value in result['arms'].items()}))


if __name__ == '__main__':
    main()
