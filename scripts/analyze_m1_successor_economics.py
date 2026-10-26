"""Describe recorded M1 economics on sealed copies; no strategy or live access.

The evidence directory must contain input/{m1,original}.sqlite, receipt.json
and capture.json. No ledger, configuration, service or threshold is changed.
Intratrade extrema are observed marks, not executable alternative exits.
"""
import argparse
import bisect
from collections import Counter, defaultdict
import datetime as dt
import gzip
import hashlib
import importlib.util
import json
from pathlib import Path
import sqlite3


ROOT = Path(__file__).resolve().parents[1]


def module(name):
    spec = importlib.util.spec_from_file_location(name, ROOT / 'octobot/ai_strategy_lab' / (name + '.py'))
    result = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(result)
    return result


def read_database(path):
    path = Path(path).resolve()
    if not path.is_file() or path.stat().st_mode & 0o222:
        raise ValueError('sealed_copy_required')
    db = sqlite3.connect(path.as_uri() + '?mode=ro', uri=True)
    db.row_factory = sqlite3.Row
    db.execute('PRAGMA query_only=ON')
    return db


def analyze(evidence):
    evidence = Path(evidence).resolve()
    r = module('v13_m1_symbol_review')
    live = module('v13_m1_live_review')
    manifest = json.loads((evidence / 'capture.json').read_text())
    if manifest['scope'] != 'READ_ONLY_ECONOMIC_ANALYSIS_NO_ORDERS':
        raise ValueError('evidence_scope')
    for name in ('v13_m1_live_review.py', 'v13_m1_symbol_review.py'):
        path = ROOT / 'octobot/ai_strategy_lab' / name
        if hashlib.sha256(path.read_bytes()).hexdigest() != manifest['files'][name]['sha256']:
            raise ValueError('accounting_code_identity:' + name)
    for name in ('m1', 'original', 'receipt'):
        extension = 'json' if name == 'receipt' else 'sqlite'
        path = evidence / 'input' / (name + '.' + extension)
        if hashlib.sha256(path.read_bytes()).hexdigest() != manifest['files'][name]['sha256']:
            raise ValueError('snapshot_identity:' + name)
    accounts = {name: r.load_snapshot(evidence / 'input' / (name + '.sqlite')) for name in ('m1', 'original')}
    receipt = json.loads((evidence / 'input/receipt.json').read_text())
    db = read_database(evidence / 'input/m1.sqlite')
    try:
        meta = {row['key']: json.loads(row['payload']) for row in db.execute('SELECT * FROM m1_meta')}
        full = live.calculate(accounts['m1'], accounts['original'], receipt, meta['strategy_successor'],
                              dt.datetime.now(dt.timezone.utc), r)
        start, epoch, end = map(r.timestamp, (full['start'], full['epoch_start'], full['end']))
        grouped = live.validate_account(accounts['m1'], r)
        fills, funding = grouped
        symbols = sorted(accounts['m1']['state']['positions'])

        def window(a, b):
            anchors = receipt['inherited_positions'] if a == start else None
            rows, total = live.window(accounts['m1'], grouped, symbols, a, b, r, anchors)
            if not total['available']:
                raise ValueError('incomplete_accounting_window')
            total['sides'] = {side: {key: sum(x['sides'][side][key] for x in rows.values())
                                    for key in ('net', 'fees', 'funding', 'realized', 'turnover', 'notional_days')}
                              for side in r.SIDES}
            return rows, total

        equity = [(r.timestamp(x['bar']), x['equity']) for x in db.execute(
            'SELECT bar,equity FROM equity_history WHERE bar>=? AND bar<=? ORDER BY bar',
            (full['start'], full['end']))]
        times = [x[0] for x in equity]

        def observed_equity(at):
            i = bisect.bisect_right(times, at) - 1
            if i < 0 or at - times[i] > r.MAX_AGE:
                raise ValueError('equity_boundary_unavailable')
            return dict(at=r.iso(times[i]), equity=equity[i][1])

        peak = max(equity, key=lambda x: x[1])
        _, since_peak = window(peak[0], end)
        _, at_peak = window(start, peak[0])
        detail_fills = [json.loads(x['payload']) for x in db.execute('SELECT * FROM m1_fills ORDER BY at,symbol')]
        episodes = []
        for episode in db.execute('SELECT * FROM m1_episodes ORDER BY signal_at'):
            payload = json.loads(episode['payload'])
            entry = r.timestamp(payload['entry_outcome']['at'])
            if entry > end:
                continue
            exits = [f for f in detail_fills if f['kind'] == 'EXIT'
                     and entry < r.timestamp(f['at']) <= r.timestamp(episode['exit_due']) + 180]
            closed = bool(exits)
            if (episode['status'] == 'COMPLETED') != closed:
                raise ValueError('episode_exit_status')
            terminal = max(r.timestamp(f['at']) for f in exits) if closed else end
            entry_fills = [f for f in detail_fills if f['kind'] == 'M1_ENTRY' and r.timestamp(f['at']) == entry]
            if not entry_fills or any(f['after'] >= 0 for f in entry_fills):
                raise ValueError('short_entry_required')
            if any(entry < r.timestamp(f['at']) < terminal and f['kind'] != 'EXIT' for f in detail_fills):
                raise ValueError('intratrade_quantity_change_requires_full_replay')
            # Attribute the closing LONG and opening SHORT fee proportionally.
            opening_fee = sum(f['fee'] * abs(f['after']) / abs(f['quantity']) for f in entry_fills)
            short_funding = [(f['timestamp_ms']/1000, f['amount']) for f in accounts['m1']['funding']
                             if entry <= f['timestamp_ms']/1000 <= terminal and f['quantity'] < 0]
            path = []
            missing = 0
            for at, _ in accounts['m1']['marks']['BTCUSDT']:
                if not entry <= at < terminal:
                    continue
                value = -opening_fee + sum(amount for t, amount in short_funding if t <= at)
                try:
                    for f in entry_fills:
                        mark = r.price_before(accounts['m1']['marks'][f['symbol']], at)[1]
                        value += f['after'] * (mark-f['price'])
                except ValueError:
                    missing += 1
                    continue
                path.append((at, value))
            rows, total = window(entry-0.00001, terminal)
            short = total['sides']['SHORT']
            if not r.close(short['fees'], opening_fee + sum(f['fee'] for f in exits)):
                raise ValueError('episode_fee_split')
            best, worst = max(path, key=lambda x: x[1]), min(path, key=lambda x: x[1])
            reentries = [f for f in detail_fills if f['kind'] == 'REENTRY'
                         and terminal < r.timestamp(f['at']) < terminal+180] if closed else []
            gaps = [b[0]-a[0] for a, b in zip(path, path[1:])]
            short_net = short['net']
            item = dict(signal_at=episode['signal_at'], entry_at=r.iso(entry), exit_due=episode['exit_due'],
                        actual_exit=r.iso(terminal) if closed else None, valued_at=r.iso(terminal),
                        status='CLOSED' if closed else 'OPEN_NOT_FINAL', feature=payload['feature'],
                        entry_lag_after_due_seconds=entry-r.timestamp(episode['entry_due']),
                        exit_lag_after_due_seconds=terminal-r.timestamp(episode['exit_due']) if closed else None,
                        short=short, short_price_component=short_net+short['fees']-short['funding'],
                        net_by_symbol={s: v['sides']['SHORT']['net'] for s,v in rows.items()
                                       if v['sides']['SHORT']['fees'] or v['sides']['SHORT']['net']},
                        observed_best=dict(at=r.iso(best[0]), before_exit_cost=best[1]),
                        observed_worst=dict(at=r.iso(worst[0]), before_exit_cost=worst[1]),
                        giveback_from_observed_best=best[1]-short_net,
                        observed_points=len(path), missing_points=missing, max_gap_seconds=max(gaps, default=0),
                        extrema_executable=False, short_opening_fee=opening_fee,
                        entry_positions={f['symbol']: {k:f[k] for k in ('before','after','price','quantity','fee')}
                                         for f in entry_fills},
                        reentry_delay_seconds=min(r.timestamp(f['at']) for f in reentries)-terminal if reentries else None,
                        entry_equity=observed_equity(entry), terminal_equity=observed_equity(terminal))
            item['entry_long_notional_at_fill_prices'] = sum(max(0.,f['before'])*f['price'] for f in entry_fills)
            item['entry_short_notional_at_fill_prices'] = sum(abs(f['after'])*f['price'] for f in entry_fills)
            item['short_to_prior_long_notional_ratio'] = (
                item['entry_short_notional_at_fill_prices']/item['entry_long_notional_at_fill_prices']
                if item['entry_long_notional_at_fill_prices'] else None)
            if reentries:
                until = min(end, terminal+21600)
                _, post = window(terminal, until)
                item['recorded_long_next_6h'] = post['long_net']
            (evidence/'output'/('episode-'+episode['signal_at'][:10]+'.json')).write_text(
                json.dumps([[r.iso(t),v] for t,v in path], indent=2))
            episodes.append(item)

        if not r.close(sum(x['short']['net'] for x in episodes), full['m1']['totals']['since_clone']['short_net']):
            raise ValueError('episode_short_reconciliation')
        successor_fills = [f for f in detail_fills if epoch < r.timestamp(f['at']) <= end]
        long_openings = [f for f in successor_fills if f['after'] > max(0.,f['before'])+1e-10]
        if long_openings:
            raise ValueError('successor_unexpected_long_rebuy')
        policy = meta['management_policy']
        auto = [json.loads(x['payload']) for x in db.execute('SELECT * FROM m1_auto_reviews ORDER BY at,rowid')]
        latest = next(x for x in reversed(auto) if x['kind'] == 'DAILY_RENEWAL_AND_WEEKLY_SELECTION')
        candidates = latest['details']['candidates']
        admission_costs = []
        market_path = evidence / 'input/admission-market.json.gz'
        if market_path.exists():
            market = json.loads(gzip.decompress(market_path.read_bytes()))
            body = {k:v for k,v in market.items() if k != 'record_hash'}
            if live.digest(body) != market['record_hash']:
                raise ValueError('admission_market_digest')
            for candidate in candidates:
                if not candidate['signal']['signal'] > 0:
                    continue
                if candidate['market_hash'] != market['record_hash']:
                    raise ValueError('admission_market_binding')
                q = market['quotes'][candidate['symbol']]
                quantity = candidate['quantity']
                prices = []
                for side in ('asks', 'bids'):
                    left, gross = quantity, 0.
                    for level in q[side]:
                        used = min(left, level['base_quantity'])
                        gross += used * level['price']
                        left -= used
                        if left <= 1e-10:
                            break
                    if left > 1e-8 or quantity <= 0:
                        raise ValueError('admission_depth_unavailable')
                    prices.append(gross / quantity)
                mid = (q['asks'][0]['price'] + q['bids'][0]['price']) / 2
                admission_costs.append(dict(symbol=candidate['symbol'],at=latest['at'],
                    market_hash=market['record_hash'],quantity=quantity,notional=quantity*q['mark_price'],
                    spread=(q['asks'][0]['price']-q['bids'][0]['price'])/mid,
                    round_trip_cost=(prices[0]*1.0002-prices[1]*.9998)/q['mark_price']+2*q['fee_rate'],
                    round_trip_fee=2*q['fee_rate'],reasons=candidate['reasons']))
        slots = [dict(x) for x in db.execute('SELECT kind,slot,status,payload FROM m1_slots ORDER BY slot')]
        daily_slots = [{k:x[k] for k in ('kind','slot','status')} | {'reason':json.loads(x['payload'])}
                       for x in slots if x['kind']=='DAILY']
        phases = []
        boundaries = [epoch] + sorted({r.timestamp(f['at']) for f in successor_fills}) + [end]
        for a,b in zip(boundaries,boundaries[1:]):
            _, total = window(a,b)
            phases.append(dict(start=r.iso(a),end=r.iso(b),net=total['net'],long_net=total['long_net'],
                               short_net=total['short_net'],fees=total['fees'],funding=total['funding']))
        # Windows are (a,b], so boundary fills belong to the preceding phase.
        if not r.close(sum(x['net'] for x in phases), full['m1']['totals']['since_version']['net']):
            raise ValueError('phase_reconciliation')
        result = dict(scope='READ_ONLY_DESCRIPTIVE_ECONOMIC_ANALYSIS_NOT_STRATEGY_QUALIFICATION',
                      generated_at=dt.datetime.now(dt.timezone.utc).isoformat(),as_of=full['end'],
                      snapshot_sha256={n:manifest['files'][n]['sha256'] for n in ('m1','original','receipt')},
                      windows={name:full[name]['totals'] for name in ('m1','original')},
                      peak=dict(at=r.iso(peak[0]),equity=peak[1],contributions=at_peak), since_peak=since_peak,
                      symbols={s:{w:v for w,v in item['windows'].items()} for s,item in full['m1']['symbols'].items()},
                      episodes=episodes,successor_phases=phases, successor_long_openings=long_openings,
                      admission_costs=admission_costs,
                      successor_fill_kinds=dict(Counter(f['kind'] for f in successor_fills)),
                      management=dict(long_budget=sum(policy['long_caps'].values()),
                                      short_budget=sum(policy['short_caps'].values()),
                                      current_quantity_ceilings=policy['quantity_ceilings'],
                                      automatic_review_count=len(auto),latest_review=latest['at'],
                                      admissions=latest['details']['admitted'],
                                      candidates=[{k:x.get(k) for k in ('symbol','status','score','reasons','signal','quality')}
                                                  for x in candidates]),
                      daily_slots=daily_slots, m1_slot_counts=dict(Counter(x['status'] for x in slots if x['kind']=='M1')),
                      no_live_writes=True,no_alternative_trades_simulated=True,
                      limitations=['Only three closed SHORT episodes and one still-open episode.',
                                   'Observed extrema omit a hypothetical closing spread, depth and fee.',
                                   'Funding is the recorded simulator estimate, not reconstructed availability.',
                                   'Actual account exposures and rules differ; Original is descriptive context.',
                                   'Signal thresholds, quantities, holding rules and future decisions were not optimized.'])
        m1_total = full['m1']['totals']['since_clone']
        original_total = full['original']['totals']['since_clone']
        comparison = dict(net=m1_total['net']-original_total['net'],
                          price_component=(m1_total['net']+m1_total['fees']-m1_total['funding'])
                          -(original_total['net']+original_total['fees']-original_total['funding']),
                          extra_fees=m1_total['fees']-original_total['fees'],
                          funding_difference=m1_total['funding']-original_total['funding'])
        if not r.close(comparison['net'], comparison['price_component']-comparison['extra_fees']+comparison['funding_difference']):
            raise ValueError('comparison_reconciliation')
        result['difference_against_original'] = comparison
        (evidence/'output/accounting.json').write_text(json.dumps(full,indent=2,allow_nan=False))
        (evidence/'output/analysis.json').write_text(json.dumps(result,indent=2,allow_nan=False))
        return result
    finally:
        db.close()


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--evidence', type=Path, required=True)
    args = parser.parse_args()
    result = analyze(args.evidence)
    print(json.dumps({k:result[k] for k in ('as_of','windows','episodes','successor_phases','management')},indent=2))
