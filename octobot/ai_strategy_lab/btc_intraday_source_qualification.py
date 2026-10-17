"""Offline receipt qualification for BTC intraday candidate v2. No trade/PnL API.

Cards 4cd8e105, efd1e408, e1d0fe15, 7faade8a. Standard-library CLI only.
"""
import argparse
import bisect
from collections import Counter, deque
import datetime as dt
import gzip
import hashlib
import json
import math
from pathlib import Path
import sqlite3
import time
import urllib.parse

NS = 1_000_000_000
LIMIT = 16*1024*1024


def canonical(v):
    return json.dumps(v, sort_keys=True, separators=(',', ':'), ensure_ascii=False, allow_nan=False).encode()


def digest(v):
    return hashlib.sha256(canonical(v)).hexdigest()


def strict(raw):
    def pairs(items):
        d = {}
        for k,v in items:
            if k in d:
                raise ValueError('duplicate_json_key')
            d[k] = v
        return d
    def bad(_):
        raise ValueError('nonfinite_json')
    if len(raw) > LIMIT:
        raise ValueError('json_size')
    def finite_float(value):
        result = float(value)
        if not math.isfinite(result):
            raise ValueError('nonfinite_json')
        return result
    return json.loads(raw, object_pairs_hook=pairs, parse_constant=bad, parse_float=finite_float)


def timestamp(s):
    x = dt.datetime.fromisoformat(s)
    if x.tzinfo is None:
        raise ValueError('timezone_required')
    delta = x.astimezone(dt.timezone.utc)-dt.datetime(1970,1,1,tzinfo=dt.timezone.utc)
    return (delta.days*86400+delta.seconds)*NS+delta.microseconds*1000


def read_blob(path):
    path = Path(path)
    if path.is_symlink() or path.stat().st_size > LIMIT:
        raise ValueError('regular_bounded_source_required')
    blob = path.read_bytes()
    if path.suffix == '.gz':
        with gzip.open(path, 'rb') as f:
            raw = f.read(LIMIT+1)
    else:
        raw = blob
    return strict(raw), blob


def hashed(v, field):
    if v.get(field) != digest({k:x for k,x in v.items() if k != field}):
        raise ValueError(field+'_mismatch')


def remote(symbol):
    return 'XBTUSDTM' if symbol == 'BTCUSDT' else symbol+'M'


def validate_receipt(receipt, cutoff):
    hashed(receipt, 'capture_id')
    if receipt['kind'] != 'LIVE_PUBLIC_HTTPS_CAPTURE' or receipt['status'] != 200:
        raise ValueError('capture_kind_or_http')
    started, received = timestamp(receipt['started_at']), timestamp(receipt['received_at'])
    if not started <= received <= cutoff:
        raise ValueError('capture_time')
    raw = bytes.fromhex(receipt['raw_hex'])
    if hashlib.sha256(raw).hexdigest() != receipt['raw_sha256']:
        raise ValueError('raw_hash')
    body = strict(raw)
    if body.get('code') != '200000':
        raise ValueError('exchange_code')
    url = urllib.parse.urlsplit(receipt['url'])
    if url.scheme != 'https' or url.netloc != 'api-futures.kucoin.com' or url.fragment:
        raise ValueError('source_endpoint')
    return body['data'], received, url


def normalize(receipt, market, protocol, cutoff):
    data, received, url = validate_receipt(receipt, cutoff)
    end = timestamp(market['observed_at_end'])
    if received > end or timestamp(receipt['started_at']) < timestamp(market['observed_at_start']):
        raise ValueError('package_capture_clock')
    available = max(received, end)  # conservative declared package availability
    common = (receipt['capture_id'], market['record_hash'], received, available)
    prefix = '/api/v1/mark-price/'
    if url.path.startswith(prefix) and url.path.endswith('/current'):
        if url.query:
            raise ValueError('mark_query')
        symbol = next((s for s in protocol['signal']['universe'] if url.path == prefix+remote(s)+'/current'), None)
        if symbol is None or data['symbol'] != remote(symbol) or data['granularity'] != 1000:
            raise ValueError('mark_identity')
        exchange = data['timePoint']*1_000_000; price = data['value']
        if type(data['timePoint']) is not int or not 0 < exchange <= received or not isinstance(price,(int,float)) or not math.isfinite(price) or price <= 0:
            raise ValueError('mark_value_or_time')
        q = market['quotes'][symbol]
        if q['mark_price'] != price or timestamp(q['mark_timestamp']) != exchange:
            raise ValueError('derived_mark_mismatch')
        return 'mark', (*common, symbol, exchange, price)
    if url.path == '/api/v1/contracts/active' and not url.query:
        matches = [x for x in data if x['symbol'] == 'XBTUSDTM']
        if len(matches) != 1:
            raise ValueError('contract_identity')
        v = matches[0]
        if v['settleCurrency'] != 'USDT' or v['isInverse'] is not False or v['status'] != 'Open':
            raise ValueError('contract_type')
        nxt, interval = v.get('nextFundingRateDateTime'), v.get('currentFundingRateGranularity')
        if interval is None:
            interval = v.get('fundingRateGranularity')
        valid = type(nxt) is int and type(interval) is int and nxt > 0 and interval > 0 and nxt*1_000_000 >= received
        # Invalid calendar remains an explicit row, never synthesize an interval.
        return 'calendar', (*common, nxt*1_000_000 if type(nxt) is int else None,
                            interval if type(interval) is int else None, int(valid))
    if url.path == '/api/v1/contract/funding-rates':
        query = urllib.parse.parse_qs(url.query)
        if query.get('symbol') != ['XBTUSDTM'] or set(query) != {'symbol','from','to'}:
            raise ValueError('funding_endpoint')
        if not isinstance(data, list):
            return 'rates_missing', common
        rows = []; seen = set()
        for v in data:
            tau, rate = v['timepoint'], v['fundingRate']
            if v['symbol'] != 'XBTUSDTM' or type(tau) is not int or not 0 < tau*1_000_000 <= received or not isinstance(rate,(int,float)) or not math.isfinite(rate) or tau in seen:
                raise ValueError('settled_rate_value_or_time')
            seen.add(tau); rows.append((*common, tau*1_000_000, rate))
        return 'rate', rows
    raise ValueError('unrecognized_selected_endpoint')


def selected(url, universe):
    parts = urllib.parse.urlsplit(url)
    return (parts.path == '/api/v1/contracts/active' or
            parts.path in {'/api/v1/mark-price/'+remote(s)+'/current' for s in universe} or
            (parts.path == '/api/v1/contract/funding-rates' and urllib.parse.parse_qs(parts.query).get('symbol') == ['XBTUSDTM']))


def freeze(source, output, protocol, plan, base_copy=None):
    """Only content-addressed archived files read. No live SQLite or network."""
    source, output = Path(source), Path(output)
    if output.exists():
        raise ValueError('new_destination_required')
    import os
    import shutil
    if os.stat(output.parent).st_dev == os.stat('/').st_dev or shutil.disk_usage(output.parent).free < 2*1024**3:
        raise ValueError('large_disk_budget')
    start, cutoff = timestamp(plan['warmup_start_utc'])-plan.get('boundary_prelude_seconds',0)*NS, timestamp(plan['cutoff_utc'])
    output.mkdir(mode=0o750); db = sqlite3.connect(output/'receipts.sqlite')
    inherited = Counter()
    if base_copy is not None:
        from scalping_archive_qualification import file_sha, ro
        base_copy = Path(base_copy); old = strict((base_copy/'input-manifest.json').read_bytes())
        if file_sha(base_copy/'receipts.sqlite') != old['database_sha256']:
            raise ValueError('base_copy_identity')
        for k in ('protocol_sha256','warmup_start_utc','evaluation_start_utc','cutoff_utc'):
            if old['plan'][k] != plan[k]:raise ValueError('base_copy_plan')
        if plan.get('boundary_prelude_seconds',0) < old['plan'].get('boundary_prelude_seconds',0):
            raise ValueError('base_copy_prefix_must_not_shrink')
        src = ro(base_copy/'receipts.sqlite',True)
        try:src.backup(db)
        finally:src.close()
        inherited.update(old['counts']); inherited['enumerated_packages']=0
    db.executescript('''
    CREATE TABLE IF NOT EXISTS packages(id TEXT PRIMARY KEY,file_sha TEXT,blob BLOB);
    CREATE TABLE IF NOT EXISTS captures(id TEXT PRIMARY KEY,file_sha TEXT,blob BLOB);
    CREATE TABLE IF NOT EXISTS marks(capture TEXT,package TEXT,received INTEGER,available INTEGER,symbol TEXT,exchange INTEGER,price REAL);
    CREATE TABLE IF NOT EXISTS calendars(capture TEXT,package TEXT,received INTEGER,available INTEGER,next_ns INTEGER,interval_ms INTEGER,valid INTEGER);
    CREATE TABLE IF NOT EXISTS rates(capture TEXT,package TEXT,received INTEGER,available INTEGER,tau INTEGER,rate REAL);
    CREATE TABLE IF NOT EXISTS missing_rates(capture TEXT,package TEXT,received INTEGER,available INTEGER);
    ''')
    counts = inherited; began = time.monotonic()
    try:
        for path in sorted((source/'market').iterdir()):
            if not (path.name.endswith('.json.gz') or path.name.endswith('.json')):
                continue
            record, blob = read_blob(path); counts['enumerated_packages'] += 1
            end = timestamp(record['observed_at_end'])
            if not start <= end <= cutoff:
                continue
            hashed(record, 'record_hash')
            if path.name.split('.')[0] != record['record_hash'] or record['scope'] != 'RESEARCH_SIMULATION_ONLY' or not timestamp(record['observed_at_start']) <= end:
                raise ValueError('package_identity')
            if set(record['quotes']) != set(protocol['signal']['universe']) or len(set(record['capture_ids'])) != 55:
                raise ValueError('package_universe_or_capture_count')
            if db.execute('SELECT 1 FROM packages WHERE id=?',(record['record_hash'],)).fetchone():
                continue
            db.execute('INSERT INTO packages VALUES(?,?,?)', (record['record_hash'],hashlib.sha256(blob).hexdigest(),blob))
            found = Counter()
            for ident in record['capture_ids']:
                if len(ident)!=64 or any(x not in '0123456789abcdef' for x in ident):
                    raise ValueError('capture_path')
                f = source/'raw'/(ident+'.json.gz')
                if not f.exists():
                    f = source/'raw'/(ident+'.json')
                receipt, raw_blob = read_blob(f)
                if not selected(receipt['url'], protocol['signal']['universe']):
                    counts['unneeded_receipts_not_qualified'] += 1
                    continue
                if receipt['capture_id'] != ident:
                    raise ValueError('capture_id_path')
                kind, value = normalize(receipt, record, protocol, cutoff)
                db.execute('INSERT OR IGNORE INTO captures VALUES(?,?,?)',(ident,hashlib.sha256(raw_blob).hexdigest(),raw_blob))
                if kind == 'mark':
                    db.execute('INSERT INTO marks VALUES(?,?,?,?,?,?,?)',value)
                elif kind == 'calendar':
                    db.execute('INSERT INTO calendars VALUES(?,?,?,?,?,?,?)',value)
                elif kind == 'rate':
                    db.executemany('INSERT INTO rates VALUES(?,?,?,?,?,?)',value)
                else:
                    db.execute('INSERT INTO missing_rates VALUES(?,?,?,?)',value)
                found[kind] += 1; counts[kind] += 1
            if found['mark'] != 18 or found['calendar'] != 1 or found['rate']+found['rates_missing'] != 1:
                raise ValueError('required_receipts_missing')
            counts['selected_packages'] += 1
            if counts['selected_packages'] % 200 == 0:
                db.commit(); print(json.dumps(dict(phase='FREEZE',**counts)),flush=True)
        db.executescript('CREATE INDEX IF NOT EXISTS mr ON marks(symbol,available); CREATE INDEX IF NOT EXISTS cr ON calendars(available); CREATE INDEX IF NOT EXISTS rt ON rates(tau,available);')
        db.commit(); integrity = [r[0] for r in db.execute('PRAGMA integrity_check')]
        if integrity != ['ok'] or not counts['selected_packages']:
            raise ValueError('offline_integrity_or_empty')
    finally:
        db.close()
    (output/'receipts.sqlite').chmod(0o440)
    from scalping_archive_qualification import file_sha
    manifest = dict(scope='TECHNICAL_INPUT_PREFIX_NOT_FORWARD_OR_TRADING',protocol_sha256=digest(protocol),
        protocol_file_sha256=plan['protocol_sha256'],plan=plan,counts=dict(counts),
        database_sha256=file_sha(output/'receipts.sqlite'),integrity=integrity,elapsed_seconds=time.monotonic()-began,
        original_files_modified=False,publication_commit_timestamps_present=False,
        timestamp_evidence='Declared collector receive times and package complete time, raw hash verified; not an independent clock attestation or historical commit proof')
    (output/'input-manifest.json').write_bytes(canonical(manifest)+b'\n');(output/'input-manifest.json').chmod(0o440)
    return manifest


def grid_points(db, protocol, start, cutoff):
    universe = protocol['signal']['universe']; step = protocol['signal']['grid_seconds']*NS
    values = {s:list(db.execute('SELECT available,received,exchange,price,capture FROM marks WHERE symbol=? ORDER BY available,capture',(s,))) for s in universe}
    stamps = {s:[x[0] for x in v] for s,v in values.items()}
    result = []
    for t in range(start,cutoff,step):
        used = {}; missing = []; reasons = Counter()
        for s in universe:
            i = bisect.bisect_right(stamps[s],t)-1
            if i < 0:
                missing.append(s);reasons['NOT_YET_AVAILABLE'] += 1;continue
            available, received, exchange, price, capture = values[s][i]
            if not exchange <= received <= available <= t or t-exchange > protocol['signal']['maximum_price_age_seconds']*NS or t-received > protocol['signal']['maximum_price_age_seconds']*NS:
                missing.append(s);reasons['STALE_OR_TIME_INVALID'] += 1;continue
            used[s] = dict(price=price,received_ns=received,exchange_ns=exchange,available_ns=available,capture=capture)
        result.append(dict(slot_ns=t,point_valid=not missing,missing=missing,reasons=dict(reasons),inputs=used))
    return result


def m1_windows(points, protocol):
    n = protocol['signal']['required_contiguous_grid_rows']; step = protocol['signal']['grid_seconds']*NS
    window = deque(maxlen=n); result = []
    for row in points:
        window.append(row); valid = len(window)==n and all(r['point_valid'] for r in window) and all(b['slot_ns']-a['slot_ns']==step for a,b in zip(window,list(window)[1:]))
        item = dict(slot_ns=row['slot_ns'],point_valid=row['point_valid'],m1_valid=valid,missing=row['missing'],signal=None)
        if valid:
            hour = list(window)[-13]; cur = row['inputs']
            returns = {s:cur[s]['price']/hour['inputs'][s]['price']-1 for s in protocol['signal']['universe']}
            item.update(signal=returns['BTCUSDT']<=protocol['signal']['btc_return_lte'] and sum(v<0 for v in returns.values())>=protocol['signal']['negative_symbol_count_gte'],
                        causal_sha256=digest(dict(protocol='btc-m1-received-mark-window-v1',slot_ns=row['slot_ns'],inputs=list(window))))
        result.append(item)
    return result


def funding_events(db, protocol, start, cutoff):
    announcements = list(db.execute('SELECT available,received,next_ns,interval_ms,capture,valid FROM calendars ORDER BY available,capture'))
    expected = sorted({r[2] for r in announcements if r[5] and start<=r[2]<cutoff and r[0]<=r[2]})
    marks = list(db.execute("SELECT available,received,exchange,price,capture FROM marks WHERE symbol='BTCUSDT' ORDER BY available,capture"));out=[]
    for tau in expected:
        rates = list(db.execute('SELECT available,received,rate,capture FROM rates WHERE tau=? AND available<=? ORDER BY available,capture',(tau,cutoff)))
        distinct = {x[2] for x in rates}
        eligible = [r for r in marks if r[1]<tau and r[2]<tau and tau-r[2]<=protocol['funding']['preceding_mark_max_age_seconds']*NS]
        mark = max(eligible,key=lambda r:(r[2],r[0])) if eligible else None
        status = 'QUALIFIED_RESEARCH_ESTIMATE_INPUTS'
        if not rates:status='PENDING_FINAL_RATE'
        elif len(distinct)!=1:status='CONFLICTING_FINAL_RATE'
        elif mark is None:status='MISSING_FRESH_PRECEDING_MARK'
        out.append(dict(tau_ns=tau,status=status,rate_first_available_ns=rates[0][0] if rates else None,
            rate_first_capture=rates[0][3] if rates else None,mark_capture=mark[4] if mark else None,
            mark_age_seconds=(tau-mark[2])/NS if mark else None,
            mark_received_ns=mark[1] if mark else None,mark_package_complete_ns=mark[0] if mark else None,
            package_complete_before_event=bool(mark and mark[0]<tau),rate_conflict=len(distinct)>1))
    return announcements,out


def qualify(output, protocol, plan, l5_source, l5_qualification, cost_bundle):
    from scalping_archive_qualification import file_sha, validate_copy, ro
    from scalping_causal_costs import CausalAdapter
    output=Path(output)
    if any((output/n).exists() for n in ('slots.jsonl','qualification.json','completion.json')):
        raise ValueError('qualification_destination_already_used')
    manifest=strict((output/'input-manifest.json').read_bytes())
    if manifest['plan']!=plan or manifest['protocol_file_sha256']!=plan['protocol_sha256'] or manifest['protocol_sha256']!=digest(protocol) or file_sha(output/'receipts.sqlite')!=manifest['database_sha256']:
        raise ValueError('input_identity')
    m=validate_copy(l5_source,Path(l5_qualification)/'snapshot-manifest.json')
    receipt=strict((Path(cost_bundle)/'completion.json').read_bytes())
    if m['sha256']!=protocol['provenance']['qualified_snapshot_sha256'] or receipt['snapshot_sha256']!=m['sha256'] or file_sha(Path(cost_bundle)/'segments.sqlite')!=receipt['files']['segments.sqlite']:
        raise ValueError('l5_identity')
    rules=strict((Path(cost_bundle)/'contract.json').read_bytes())
    for k in ('max_capture_ms','max_quote_age_ms','max_source_age_ms','max_segment_gap_ms'):
        if rules[k]!=protocol['market_data'][k]:raise ValueError('l5_rules_drift')
    db=ro(output/'receipts.sqlite',True);raw=ro(l5_source,True);segments=ro(Path(cost_bundle)/'segments.sqlite',True)
    try:
        warm,start,end=map(timestamp,(plan['warmup_start_utc'],plan['evaluation_start_utc'],plan['cutoff_utc']))
        points=grid_points(db,protocol,warm,end);windows=m1_windows(points,protocol)
        announcements,events=funding_events(db,protocol,start,end);ann_times=[r[0] for r in announcements]
        adapter=CausalAdapter(raw,segments,rules);rows=[];counts=Counter()
        for row in windows:
            slot=row['slot_ns']
            if slot<start:continue
            point=next(x for x in points if x['slot_ns']==slot)
            frame=adapter.frame(slot,protocol['market_data']['completed_second_warmup'])
            entry_ns=slot+protocol['timing']['entry_delay_seconds']*NS+protocol['timing']['execution_latency_ms']*1_000_000
            arrival,status=adapter.quote(entry_ns,arrival=True)
            entry_frame=adapter.frame(arrival['received_ns'],protocol['market_data']['completed_second_warmup']) if arrival else None
            i=bisect.bisect_right(ann_times,slot)-1
            calendar=announcements[i] if i>=0 else None
            calendar_ok=bool(calendar and calendar[5] and slot-calendar[1]<=300*NS and calendar[2]>=slot)
            row.update(point_input_count=len(point['inputs']),l5_decision_window=frame['status'],
                l5_arrival_receive_status=status,l5_arrival_id=arrival['id'] if arrival else None,
                l5_arrival_received_ns=arrival['received_ns'] if arrival else None,
                l5_entry_window=entry_frame['status'] if entry_frame else 'NO_FRESH_ARRIVAL',
                calendar_observed_and_fresh=calendar_ok,
                durable_publication_status='UNRESOLVED_NO_HISTORICAL_COMMIT_RECEIPTS',
                paper_entry_qualified=False)
            counts['slots']+=1;counts['point_valid']+=int(row['point_valid']);counts['m1_window_valid']+=int(row['m1_valid']);counts['m1_true']+=int(row['signal'] is True)
            counts['l5_decision_window_complete']+=int(frame['complete']);counts['l5_arrival_received']+=int(arrival is not None);counts['l5_entry_window_complete']+=int(entry_frame is not None and entry_frame['complete'])
            counts['calendar_observed_fresh']+=int(calendar_ok);counts['received_time_join_complete']+=int(row['m1_valid'] and frame['complete'] and entry_frame is not None and entry_frame['complete'] and calendar_ok)
            rows.append(row)
        statuses=Counter(x['status'] for x in events)
        gaps=['HISTORICAL_DURABLE_PUBLICATION_AND_ARRIVAL_COMMIT_RECEIPTS_UNRESOLVED']
        for metric in ('m1_window_valid','l5_decision_window_complete','l5_arrival_received','l5_entry_window_complete','calendar_observed_fresh'):
            if counts[metric]<counts['slots']:gaps.append(metric.upper()+'_GAPS')
        if not events or any(x['status']!='QUALIFIED_RESEARCH_ESTIMATE_INPUTS' for x in events):gaps.append('FUNDING_RECONCILIATION_GAPS_OR_UNOBSERVED_EVENTS')
        result=dict(scope='OFFLINE_SOURCE_QUALIFICATION_NOT_ACCOUNT_READINESS_OR_FORWARD_RESULTS',
            protocol_file_sha256=plan['protocol_sha256'],counts=dict(counts),funding_events=events,funding_statuses=dict(statuses),
            invalid_calendar_receipts=db.execute('SELECT COUNT(*) FROM calendars WHERE valid=0').fetchone()[0],
            missing_rate_receipts=db.execute('SELECT COUNT(*) FROM missing_rates').fetchone()[0],
            source_database_sha256=manifest['database_sha256'],l5_snapshot_sha256=m['sha256'],
            readiness='NOT_READY_SOURCE_EVIDENCE_GAPS',source_gaps=gaps,
            timestamp_evidence='Collector-declared raw receive times and conservative package complete times; no independent historical receipt-commit witness',
            exchange_min_quantity='UNKNOWN',exchange_min_notional='UNKNOWN',new_account_created=False,existing_strategies_changed=False,pnl_calculated=False,
            limitations=['Applies only to the inspected source and frozen prefix, not all repository sources','Late settled funding may reconcile a past event only when actually observed; never authorize a past decision','Raw L5 payloads absent, event hashes not independently reconstructible; sealed copy identity is verified','Historical receive timestamps do not prove durable publication or the arrival commit deadline','No external clock calibration, operational grant, strategy promotion or KuCoin order-admissibility validation'])
        (output/'slots.jsonl').write_text(''.join(json.dumps(x,sort_keys=True,allow_nan=False)+'\n' for x in rows))
        (output/'qualification.json').write_bytes(canonical(result)+b'\n')
    finally:
        db.close();raw.close();segments.close()
    completion=dict(status='TECHNICAL_QUALIFICATION_COMPLETE_NOT_READY_TO_START',tool_sha256=file_sha(__file__),
        files={n:file_sha(output/n) for n in ['input-manifest.json','receipts.sqlite','slots.jsonl','qualification.json']})
    for n in completion['files']:(output/n).chmod(0o440)
    (output/'completion.json').write_bytes(canonical(completion)+b'\n');(output/'completion.json').chmod(0o440)
    print(json.dumps(result,indent=2),flush=True)
    return result


if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('command',choices=['freeze','qualify']);p.add_argument('--source',type=Path);p.add_argument('--base-copy',type=Path);p.add_argument('--output',type=Path,required=True);p.add_argument('--protocol',type=Path,required=True);p.add_argument('--plan',type=Path,required=True);p.add_argument('--l5-source',type=Path);p.add_argument('--l5-qualification',type=Path);p.add_argument('--cost-bundle',type=Path);a=p.parse_args()
    protocol=strict(a.protocol.read_bytes());plan=strict(a.plan.read_bytes())
    if hashlib.sha256(a.protocol.read_bytes()).hexdigest()!=plan['protocol_sha256']:
        raise ValueError('protocol_pin')
    if a.command=='freeze':freeze(a.source,a.output,protocol,plan,a.base_copy)
    else:qualify(a.output,protocol,plan,a.l5_source,a.l5_qualification,a.cost_bundle)
