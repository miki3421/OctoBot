"""Causal raw L5 adapter and exogenous taker-cost diagnostic, offline only.

Cards 0cef3daa/c9187254/0211c696/d3eaae8f/26bdb4f5. No order interfaces.
Run by filename: standard library only, without importing the lab package.
"""
import argparse
from collections import Counter, defaultdict
import csv
import hashlib
import json
import math
from pathlib import Path
import sqlite3
import time

from scalping_archive_qualification import file_sha, now, ro, validate_copy, write

NS = 1_000_000_000
MS = 1_000_000
COLUMNS = ('id,session_id,sequence,exchange_ts_ns,received_ts_ns,latency_ms,' +
           ','.join(f'{side}_{field}_{i}' for side in ('bid', 'ask')
                    for i in range(1, 6) for field in ('price', 'size')) +
           ',mid_price,payload_sha256')


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(',', ':'),
                                     allow_nan=False).encode()).hexdigest()


def validate_rules(rules):
    positive = ('max_capture_ms', 'max_quote_age_ms', 'max_source_age_ms',
                'max_segment_gap_ms', 'arrival_wait_ms', 'grid_seconds',
                'feature_window_seconds', 'stress_cost_multiplier')
    if any(not math.isfinite(rules[k]) or rules[k] <= 0 for k in positive):
        raise ValueError('invalid_rules')
    if any(not math.isfinite(rules[k]) or rules[k] < 0
           for k in ('taker_fee_bps', 'adverse_slippage_bps')):
        raise ValueError('invalid_costs')
    if not rules['sizes_native'] or any(not math.isfinite(x) or x <= 0 for x in rules['sizes_native']):
        raise ValueError('invalid_size')
    if not rules['latencies_ms'] or any(type(x) is not int or x < 0 for x in rules['latencies_ms']):
        raise ValueError('invalid_latency')
    if rules['sides'] != ['BUY', 'SELL'] or rules['symbol'] != 'XBTUSDTM':
        raise ValueError('identity_or_sides')
    if any(type(rules[k]) is not int for k in ('grid_seconds', 'feature_window_seconds')):
        raise ValueError('integer_intervals_required')


def make_segments(rows, rules, emit):
    """Bounded-memory chronology scan. Segment ID depends only on its first event.

    Raw session changes reset even if the new session's first quote is late.
    Rejected quotes never update the last accepted clock or bridge a long gap.
    """
    stats = Counter(); segment = None; raw_session = None; prior_id = prior_ns = None
    exchange_by_session = None
    for event_id, session, exchange, received in rows:
        if prior_id is not None and (event_id <= prior_id or received < prior_ns):
            raise ValueError('raw_chronology')
        changed = session != raw_session
        if changed:
            if segment is not None:
                emit(tuple(segment)); segment = None
            stats['session_starts'] += 1
            exchange_by_session = None
        if exchange_by_session is not None and exchange < exchange_by_session:
            raise ValueError('exchange_chronology')
        exchange_by_session = exchange
        prior_id, prior_ns, raw_session = event_id, received, session
        stats['raw'] += 1
        lag = received - exchange
        if not 0 <= lag <= rules['max_capture_ms'] * MS:
            stats['rejected_capture'] += 1
            continue
        if segment is not None and received - segment[4] > rules['max_segment_gap_ms'] * MS:
            emit(tuple(segment)); segment = None; stats['gap_resets'] += 1
        if segment is None:
            # first ID, session, first receive, last ID, last receive, accepted count
            segment = [event_id, session, received, event_id, received, 0]
            stats['segments'] += 1
        segment[3:5] = [event_id, received]; segment[5] += 1
        stats['accepted'] += 1
    if segment is not None:
        emit(tuple(segment))
    return dict(stats)


def create_segments(source, destination, rules):
    destination.execute('CREATE TABLE segments(first_id INTEGER PRIMARY KEY, session TEXT, first_ns INTEGER UNIQUE, last_id INTEGER, last_ns INTEGER, accepted INTEGER)')
    rows = source.execute('SELECT id,session_id,exchange_ts_ns,received_ts_ns FROM book_events ORDER BY id')
    stats = make_segments(rows, rules, lambda r: destination.execute('INSERT INTO segments VALUES(?,?,?,?,?,?)', r))
    destination.commit()
    return stats


def unpack(row):
    if row is None:
        return None
    return dict(id=row[0], session=row[1], sequence=row[2], exchange_ns=row[3],
                received_ns=row[4], capture_ms=row[5],
                bids=[(row[6+i*2], row[7+i*2]) for i in range(5)],
                asks=[(row[16+i*2], row[17+i*2]) for i in range(5)],
                mid=row[26], payload_sha256=row[27])


class CausalAdapter:
    """Read-only queries on a validated copy, with its derived segment index.

    Constructor receives connections for isolated tests. Production CLI verifies
    the sealed copy and qualification before constructing this object.
    """
    def __init__(self, source, segments, rules):
        validate_rules(rules)
        self.source, self.segments, self.rules = source, segments, rules
        self.identity_rules = {k: rules[k] for k in (
            'id', 'symbol', 'max_capture_ms', 'max_quote_age_ms', 'max_source_age_ms',
            'max_segment_gap_ms', 'size_semantics')}

    def segment(self, received):
        row = self.segments.execute('SELECT * FROM segments WHERE first_ns<=? ORDER BY first_ns DESC LIMIT 1', (received,)).fetchone()
        return row if row is not None and received <= row[4] else None

    def quote(self, at_ns, arrival=False):
        """As-of input or first observed arrival; never search beyond deadline."""
        r = self.rules
        if arrival:
            sql = f'SELECT {COLUMNS} FROM book_events WHERE received_ts_ns>=? AND received_ts_ns<=? AND latency_ms BETWEEN 0 AND ? ORDER BY received_ts_ns,id LIMIT 1'
            args = (at_ns, at_ns + r['arrival_wait_ms'] * MS, r['max_capture_ms'])
        else:
            sql = f'SELECT {COLUMNS} FROM book_events WHERE received_ts_ns<=? AND received_ts_ns>=? AND latency_ms BETWEEN 0 AND ? ORDER BY received_ts_ns DESC,id DESC LIMIT 1'
            args = (at_ns, at_ns-r['max_quote_age_ms']*MS, r['max_capture_ms'])
        q = unpack(self.source.execute(sql, args).fetchone())
        if q is None:
            return None, 'NO_FRESH_ARRIVAL' if arrival else 'NO_FRESH_REFERENCE'
        observed = q['received_ns'] if arrival else at_ns
        if not 0 <= observed-q['exchange_ns'] <= r['max_source_age_ms']*MS:
            return None, 'SOURCE_STALE'
        # A late first event in a new session must invalidate old-session state.
        latest = self.source.execute('SELECT session_id FROM book_events WHERE received_ts_ns<=? ORDER BY received_ts_ns DESC,id DESC LIMIT 1', (observed,)).fetchone()
        segment = self.segment(q['received_ns'])
        if not segment or latest[0] != q['session'] or segment[1] != q['session']:
            return None, 'SESSION_RESET'
        q['segment_id'] = segment[0]
        return q, 'OK'

    def frame(self, decision_ns, window_seconds):
        """Complete receive-time seconds only; no partially observed bucket.

        Return incomplete coverage explicitly. No interpolation or carry-forward.
        Trades are counted only in the current session/accepted-book segment.
        Future raw acquisition hash is provenance, never part of feature identity.
        """
        if type(window_seconds) is not int or window_seconds <= 0:
            raise ValueError('invalid_window')
        q, status = self.quote(decision_ns)
        end_ns = decision_ns//NS*NS; start_ns = end_ns-window_seconds*NS
        if q is None:
            return dict(status=status, decision_ns=decision_ns, seconds=[], complete=False)
        segment = self.segment(q['received_ns']); buckets = {}; consumed = []
        for row in self.source.execute(f'SELECT {COLUMNS} FROM book_events WHERE received_ts_ns>=? AND received_ts_ns<? AND session_id=? AND id>=? AND id<=? AND latency_ms BETWEEN 0 AND ? ORDER BY received_ts_ns,id',
                (max(start_ns, segment[2]), end_ns, q['session'], segment[0], segment[3], self.rules['max_capture_ms'])):
            book = unpack(row); second = book['received_ns']//NS
            available = (second+1)*NS
            if available-book['exchange_ns'] > self.rules['max_source_age_ms']*MS:
                # This quote could not be used as a fresh completed-second close.
                continue
            b = buckets.setdefault(second, dict(second=second, available_ns=available,
                    book_count=0, trade_count=0, buy_native=0., sell_native=0.))
            b['book_count'] += 1; b['last_book'] = book
            consumed.append(('book', book['id'], book['payload_sha256']))
        for row in self.source.execute('SELECT id,session_id,received_ts_ns,exchange_ts_ns,side,size,payload_sha256 FROM trade_events WHERE received_ts_ns>=? AND received_ts_ns<? ORDER BY received_ts_ns,id',
                                       (max(start_ns, segment[2]), end_ns)):
            event, session, received, exchange, side, size, payload_hash = row
            if session != q['session'] or not 0 <= received-exchange <= self.rules['max_capture_ms']*MS:
                continue
            second = received//NS
            if second not in buckets:
                continue  # no fabricated trade-only book or carry-forward
            b = buckets[second]; b['trade_count'] += 1; b[side+'_native'] += size
            consumed.append(('trade', event, payload_hash))
        values = [buckets[k] for k in sorted(buckets)]
        complete = (start_ns >= segment[2] and len(values) == window_seconds)
        # Identity commits to consumed data and parameters, not future DB contents.
        identity = digest(dict(rules=self.identity_rules, decision_ns=decision_ns,
                               window_seconds=window_seconds, segment_id=segment[0],
                               data=values, consumed=consumed))
        return dict(status='COMPLETE' if complete else 'INCOMPLETE_WINDOW',
                    decision_ns=decision_ns, seconds=values, complete=complete,
                    segment_id=segment[0], causal_sha256=identity)


def sweep(book, side, quantity):
    """Hypothetical taker; require full visible depth. Units deliberately native."""
    if side not in ('BUY', 'SELL') or not math.isfinite(quantity) or quantity <= 0:
        raise ValueError('side_or_quantity')
    levels = book['asks'] if side == 'BUY' else book['bids']
    if any(not math.isfinite(p) or not math.isfinite(v) or p <= 0 or v < 0 for p,v in levels):
        raise ValueError('invalid_depth')
    remain = quantity; value = 0.
    for price, volume in levels:
        take = min(remain, volume); value += take*price; remain -= take
        if remain <= max(1e-12, quantity*1e-12):
            return value/quantity
    return None  # no partial-fill economics or extrapolation beyond L5


def cost_row(reference, arrival, side, quantity, rules):
    price = sweep(arrival, side, quantity)
    if price is None:
        return dict(status='INSUFFICIENT_L5_DEPTH')
    sign = 1 if side == 'BUY' else -1
    ref = reference['mid']; mid = arrival['mid']
    touch = arrival['asks'][0][0] if side == 'BUY' else arrival['bids'][0][0]
    spread = sign*(touch-mid)/ref*10000
    depth = sign*(price-touch)/ref*10000
    movement = sign*(mid-ref)/ref*10000
    execution = movement+spread+depth
    # Fee and adverse slippage assumptions are assessed on executed notional.
    assumed = (rules['taker_fee_bps']+rules['adverse_slippage_bps'])*price/ref
    return dict(status='MEASURED_HYPOTHETICAL', price=price,
                half_spread_bps=spread, depth_impact_bps=depth,
                latency_move_bps=movement, execution_shortfall_bps=execution,
                assumed_cost_bps=assumed, total_bps=execution+assumed,
                stressed_total_bps=movement+rules['stress_cost_multiplier']*(spread+depth+assumed))


def describe(values):
    if not values:
        return None
    v = sorted(values)
    return dict(n=len(v), mean=sum(v)/len(v), p50=v[(len(v)-1)//2],
                p95=v[math.ceil(len(v)*.95)-1], p99=v[math.ceil(len(v)*.99)-1],
                minimum=v[0], maximum=v[-1])


def benchmark(adapter, rules, first, last, out):
    start = ((first//NS+rules['grid_seconds']-1)//rules['grid_seconds'])*rules['grid_seconds']
    stop = last//NS
    metrics = ('half_spread_bps', 'depth_impact_bps', 'latency_move_bps',
               'execution_shortfall_bps', 'assumed_cost_bps', 'total_bps', 'stressed_total_bps')
    fields = ['slot_ns', 'side', 'size_native', 'latency_ms', 'status', 'reference_id',
              'arrival_id', 'reference_ns', 'arrival_ns', 'segment_id', 'price', *metrics]
    summaries = {}; days = {}; count = features = complete = 0
    with (out/'intents.csv').open('x', newline='') as f, (out/'sampled-features.jsonl').open('x') as ff:
        writer = csv.DictWriter(f, fields); writer.writeheader()
        for second in range(start, stop+1, rules['grid_seconds']):
            slot = second*NS; reference, ref_status = adapter.quote(slot)
            frame = adapter.frame(slot, rules['feature_window_seconds'])
            ff.write(json.dumps(frame, sort_keys=True, allow_nan=False)+'\n')
            features += 1; complete += int(frame['complete'])
            for latency in rules['latencies_ms']:
                arrival, status = adapter.quote(slot+latency*MS, arrival=True) if reference else (None, ref_status)
                if arrival and reference and arrival['segment_id'] != reference['segment_id']:
                    arrival, status = None, 'SEGMENT_RESET'
                for side in rules['sides']:
                    for size in rules['sizes_native']:
                        key = f'{side}:{size}:{latency}'
                        s = summaries.setdefault(key, dict(expected=0, statuses=Counter(), metrics=defaultdict(list)))
                        row = dict(slot_ns=slot, side=side, size_native=size, latency_ms=latency,
                                   status=status, reference_id=reference['id'] if reference else None,
                                   reference_ns=reference['received_ns'] if reference else None,
                                   arrival_id=arrival['id'] if arrival else None,
                                   arrival_ns=arrival['received_ns'] if arrival else None,
                                   segment_id=reference['segment_id'] if reference else None)
                        if arrival:
                            row.update(cost_row(reference, arrival, side, size, rules))
                        s['expected'] += 1; s['statuses'][row['status']] += 1
                        day = time.strftime('%Y-%m-%d', time.gmtime(second))
                        d = days.setdefault(day, Counter()); d['expected'] += 1; d[row['status']] += 1
                        for name in metrics:
                            if name in row:
                                s['metrics'][name].append(row[name])
                        writer.writerow(row); count += 1
            if features % 500 == 0:
                print(json.dumps(dict(phase='BENCHMARK', slots=features)), flush=True)
    result = {}
    for key, s in summaries.items():
        result[key] = dict(expected=s['expected'], statuses=dict(s['statuses']),
                           measured_fraction=s['statuses']['MEASURED_HYPOTHETICAL']/s['expected'],
                           metrics={k: describe(v) for k,v in s['metrics'].items()})
    return dict(scope='NATIVE_L5_COST_DIAGNOSTIC_NOT_KUCOIN_ORDER_ADMISSIBILITY',
                first_slot_ns=start*NS, last_slot_ns=(start+(features-1)*rules['grid_seconds'])*NS,
                slots=features, intents=count, complete_feature_windows=complete,
                incomplete_feature_windows=features-complete, groups=result,
                by_day={k:dict(v) for k,v in days.items()},
                omitted_intents=0, pnl_or_alpha_computed=False,
                min_quantity='UNKNOWN', min_notional='UNKNOWN',
                account_created=False, existing_strategies_changed=False)


def run(source, qualification_dir, contract_path, destination):
    """Fail closed on identity, failed qualification, reuse, disk or partial run.

    On failure preserve the incomplete directory for inspection. A successful
    completion receipt is written last; consumers must verify its file hashes.
    """
    source, qualification_dir, destination = map(Path, (source, qualification_dir, destination))
    if destination.exists():
        raise ValueError('new_destination_required')
    rules = json.loads(Path(contract_path).read_text()); validate_rules(rules)
    m = validate_copy(source, qualification_dir/'snapshot-manifest.json')
    qualification = json.loads((qualification_dir/'qualification.json').read_text())
    chronology = json.loads((qualification_dir/'chronology.json').read_text())
    if m['sha256'] != rules['snapshot_sha256'] or not qualification['technical_rows_valid'] or qualification['snapshot_sha256'] != m['sha256']:
        raise ValueError('qualification_identity_or_status')
    expected_rows = sum(d['rows'] for d in qualification['book_days'])
    if chronology['rows'] != expected_rows or any(chronology[k] for k in
            ('received_timestamp_regressions', 'exchange_timestamp_regressions_same_session', 'sequence_regressions_same_session')):
        raise ValueError('chronology_status_or_count')
    # These receipts are diagnostic prerequisites, not permission to trade.
    if json.loads((qualification_dir/'integrity.json').read_text())['result'] != ['ok']:
        raise ValueError('integrity')
    import os
    import shutil
    if os.stat(destination.parent).st_dev == os.stat('/').st_dev or shutil.disk_usage(destination.parent).free < 2*1024**3:
        raise ValueError('large_disk_budget_required')
    destination.mkdir(mode=0o750)
    started = time.monotonic(); source_db = ro(source, True); derived = sqlite3.connect(destination/'segments.sqlite')
    try:
        frozen = json.loads(Path(contract_path).read_text())
        if frozen != rules:
            raise ValueError('contract_changed')
        write(destination/'contract.json', frozen)
        stats = create_segments(source_db, derived, rules)
        if stats['raw'] != expected_rows:
            raise ValueError('raw_row_count')
        print(json.dumps(dict(phase='SEGMENTS_READY', **stats)), flush=True)
        first, last = source_db.execute('SELECT received_ts_ns FROM book_events ORDER BY received_ts_ns LIMIT 1').fetchone()[0], source_db.execute('SELECT received_ts_ns FROM book_events ORDER BY received_ts_ns DESC LIMIT 1').fetchone()[0]
        result = benchmark(CausalAdapter(source_db, derived, rules), rules, first, last, destination)
        result.update(completed_at=now(), elapsed_seconds=time.monotonic()-started,
                      snapshot_sha256=m['sha256'], contract_sha256=file_sha(destination/'contract.json'),
                      segment_scan=stats)
        write(destination/'results.json', result)
    finally:
        source_db.close(); derived.close()
    files = ['contract.json', 'segments.sqlite', 'intents.csv', 'sampled-features.jsonl', 'results.json']
    receipt = dict(status='COMPLETE_OFFLINE_DIAGNOSTIC_ONLY', completed_at=now(),
                   snapshot_sha256=m['sha256'], tool_sha256=file_sha(__file__),
                   qualification_tool_sha256=file_sha(Path(__file__).with_name('scalping_archive_qualification.py')),
                   prerequisite_sha256={n:file_sha(qualification_dir/n) for n in
                     ('snapshot-manifest.json', 'qualification.json', 'chronology.json', 'integrity.json')},
                   files={n:file_sha(destination/n) for n in files})
    for name in files:
        (destination/name).chmod(0o440)
    write(destination/'completion.json', receipt); (destination/'completion.json').chmod(0o440)
    print(json.dumps(dict(phase='COMPLETE', slots=result['slots'], intents=result['intents'])), flush=True)
    return result


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--source', type=Path, required=True)
    parser.add_argument('--qualification-dir', type=Path, required=True)
    parser.add_argument('--contract', type=Path, required=True)
    parser.add_argument('--destination', type=Path, required=True)
    args = parser.parse_args()
    run(args.source, args.qualification_dir, args.contract, args.destination)
