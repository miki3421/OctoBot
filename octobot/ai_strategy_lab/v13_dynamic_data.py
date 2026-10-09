"""Read-only qualification receipt adapter; never turns real inputs into fixtures.

Caller pins plan, activation binding and archive. Reuses existing receipt/schema
validators, preserving UNKNOWN funding coverage and KuCoin minima.
"""
import datetime as dt
import sqlite3
from pathlib import Path
from decimal import Decimal, InvalidOperation
try:
    from . import v13_universe_qualification as capture
    from . import v13_universe_qualification_evaluate as verify
    from . import v13_dynamic_universe as selector
except ImportError:
    import v13_universe_qualification as capture
    import v13_universe_qualification_evaluate as verify
    import v13_dynamic_universe as selector


def store_path(path,owner):
    """A writer-owned directory below root-owned ancestors, and its regular file.

    SQLite needs its owner to create journals beside the DB. Requiring every
    ancestor including that directory to be root-owned would make it unusable.
    """
    import stat
    path=Path(path)
    if not path.is_absolute() or '..' in path.parts:raise ValueError('absolute_safe_path_required')
    capture.safe_path(path.parent,owner,directory=True)
    info=path.lstat()
    if not stat.S_ISREG(info.st_mode) or info.st_uid!=owner or info.st_mode&0o022:
        raise ValueError('untrusted_store_file')


def precision(contract):
    """Precision only, never infer exchange minimums from lotSize."""
    values={}
    for key in ('tickSize','lotSize','multiplier','takerFeeRate'):
        value=contract.get(key)
        if isinstance(value,bool) or not isinstance(value,(str,int,float)):
            raise ValueError('invalid_precision_metadata')
        try: number=Decimal(str(value))
        except InvalidOperation: raise ValueError('invalid_precision_metadata') from None
        if not number.is_finite() or number<0 or (key!='takerFeeRate' and number==0):
            raise ValueError('invalid_precision_metadata')
        values[key]=number
    return dict(price_tick=str(values['tickSize']),
                quantity_increment=str(values['lotSize']*values['multiplier']),
                public_taker_fee=str(values['takerFeeRate']),
                min_quantity=None,min_notional=None)


def admit_books(records, *, intent_persisted_at, as_of):
    """Pure temporal check on custody-verified reader output, not authorization.

    The caller must obtain intent_persisted_at from its durable intent store;
    a supplied timestamp or a receipt label alone is not proof of custody.
    Uses the simulator's 60-second book freshness rule for all 29 symbols.
    """
    import math
    intent, cutoff = selector.timestamp(intent_persisted_at), selector.timestamp(as_of)
    if intent >= cutoff: raise ValueError('intent_not_before_execution')
    chosen={}
    def hash_valid(value):
        return isinstance(value,str) and len(value)==64 and all(c in '0123456789abcdef' for c in value)
    for record in records:
        if record.get('kind')!='books':continue
        symbol=record['symbol']
        if symbol not in selector.UNIVERSE:raise ValueError('unexpected_book_symbol')
        if record.get('scope') not in ('VERIFIED_QUALIFICATION_RECEIPT','VERIFIED_FORWARD_RECEIPT'):raise ValueError('unverified_book')
        observed=selector.timestamp(record['at']);received=selector.timestamp(record['received_at'])
        # Historical and not-yet-available rows cannot become execution inputs.
        if received>cutoff or observed<=intent or (cutoff-observed).total_seconds()>60:continue
        if observed>received:raise ValueError('book_clock_order')
        metadata=record.get('metadata_hashes',{})
        if (set(metadata)!={'kucoin_metadata','binance_metadata'} or
                not all(hash_valid(h) for h in metadata.values()) or not hash_valid(record.get('raw_sha256'))):
            raise ValueError('book_provenance_required')
        if selector.timestamp(record['metadata_received_at'])>observed:raise ValueError('future_book_metadata')
        p=record['precision']
        for key in ('price_tick','quantity_increment','public_taker_fee'):
            if isinstance(p.get(key),bool):raise ValueError('invalid_precision_metadata')
            try:v=Decimal(str(p[key]))
            except (KeyError,InvalidOperation):raise ValueError('invalid_precision_metadata') from None
            if not v.is_finite() or v<0 or (key!='public_taker_fee' and v==0):raise ValueError('invalid_precision_metadata')
        for side in ('bids','asks'):
            levels=record[side]
            if not levels:raise ValueError('empty_book')
            for price,quantity in levels:
                if any(isinstance(v,bool) or not isinstance(v,(int,float)) or not math.isfinite(v) or v<=0 for v in (price,quantity)):
                    raise ValueError('invalid_book_level')
            prices=[v[0] for v in levels]
            if prices!=sorted(set(prices),reverse=side=='bids'):raise ValueError('unordered_book')
        if record['bids'][0][0]>=record['asks'][0][0]:raise ValueError('crossed_book')
        prior=chosen.get(symbol)
        if prior and selector.timestamp(prior['at'])==observed:
            if any(prior[k]!=record[k] for k in ('bids','asks','precision','metadata_hashes')):
                raise ValueError('conflicting_execution_book')
        if prior is None or (observed,received,record['raw_sha256'])>(selector.timestamp(prior['at']),selector.timestamp(prior['received_at']),prior['raw_sha256']):
            chosen[symbol]=record
    if set(chosen)!=set(selector.UNIVERSE):raise ValueError('common_fresh_books_required')
    return dict(scope='VERIFIED_BOOK_TEMPORAL_CHECK_ONLY',books=chosen,
                intent_persisted_at=intent_persisted_at,as_of=as_of,
                execution_ready=False,orders_authorized=False,paper_orders_authorized=False)


def project(collector, row, contract, as_of):
    if row['state'] != 'valid' or row['received'] > as_of:
        raise ValueError('receipt_not_available')
    verify.verify_valid_row(collector,row,contract)
    raw = verify.raw_bytes(row)
    value = capture.decode(raw)
    base = dict(symbol=row['symbol'],received_at=dt.datetime.fromtimestamp(row['received'],dt.timezone.utc).isoformat(),
                raw_sha256=row['raw_hash'],scope='VERIFIED_QUALIFICATION_RECEIPT',
                orders_authorized=False,paper_orders_authorized=False)
    if row['kind']=='daily':
        return dict(base,kind='daily',day=dt.datetime.fromtimestamp(value[0][0]/1000,dt.timezone.utc).date().isoformat(),close=float(value[0][4]))
    if row['kind']=='books':
        v=value['data'];stamp=v['ts'];seconds=stamp/(1e9 if stamp>=1e17 else 1e6 if stamp>=1e14 else 1e3)
        return dict(base,kind='books',at=dt.datetime.fromtimestamp(seconds,dt.timezone.utc).isoformat(),
                    bids=[[float(p),float(q)*float(contract['multiplier'])] for p,q in v['bids']],
                    asks=[[float(p),float(q)*float(contract['multiplier'])] for p,q in v['asks']],
                    min_quantity=None,min_notional=None)
    if row['kind']=='funding':
        return dict(base,kind='funding',window_start=dt.datetime.fromtimestamp(row['slot']//86400*86400-86400,dt.timezone.utc).isoformat(),window_end=dt.datetime.fromtimestamp(row['slot']//86400*86400,dt.timezone.utc).isoformat(),coverage_complete=False,events=[dict(at=item['timepoint'],rate=float(item['fundingRate']),mark=None) for item in value['data']])
    raise ValueError('unsupported_projection')


def read_day(archive, plan, start, binding, day, as_of, kinds=('daily','books','funding')):
    """Coherent read snapshot; check archive schedule/binding before projections.

    Reads completed rows of one day, not the final qualification verdict. Missing
    jobs remain missing. No evaluator cutoff is bypassed and no marks are invented.
    """
    if not kinds or not set(kinds)<= {'daily','books','funding'}:raise ValueError('invalid_kinds')
    p=Path(archive)
    if p.is_symlink() or not p.is_file():raise ValueError('archive_path')
    if day<start or (day-start)%86400 or day>=start+14*86400:raise ValueError('day_outside_plan')
    collector=capture.Collector(p.parent,plan,start,binding,None)
    with sqlite3.connect(p.resolve().as_uri()+'?mode=ro',uri=True) as db:
        db.row_factory=sqlite3.Row
        db.execute('PRAGMA query_only=ON');db.execute('PRAGMA trusted_schema=OFF');db.execute('BEGIN')
        collector.check(db)
        metadata=list(db.execute("SELECT * FROM jobs WHERE slot=? AND kind IN ('kucoin_metadata','binance_metadata') AND state='valid'",(day,)))
        if len(metadata)!=2:raise ValueError('metadata_missing')
        for r in metadata:
            if r['received']>as_of:raise ValueError('future_metadata')
            verify.verify_valid_row(collector,r,None)
        contracts=collector.contracts(db,day)
        available=max(r['received'] for r in metadata)
        precision_by_symbol={s:precision(c) for s,c in contracts.items()} if 'books' in kinds else {}
        output=[]
        for row in db.execute("SELECT * FROM jobs WHERE slot>=? AND slot<? AND kind IN ('daily','books','funding') AND state='valid' AND received<=? ORDER BY slot,id",(day,day+86400,as_of)):
            if row['kind'] not in kinds:continue
            if row['started']<available:raise ValueError('noncausal_metadata')
            projected=project(collector,row,contracts[row['symbol']],as_of)
            if row['kind']=='books':
                projected.update(precision=precision_by_symbol[row['symbol']],
                                 metadata_hashes={r['kind']:r['raw_hash'] for r in metadata},
                                 metadata_received_at=dt.datetime.fromtimestamp(available,dt.timezone.utc).isoformat())
            output.append(projected)
        return dict(scope='VERIFIED_QUALIFICATION_RECEIPTS_ONLY',records=output,
                    final_qualification_assessed=False,simulation_ready=False,
                    binding=binding,metadata_hashes=[r['raw_hash'] for r in metadata])


def weekly_calendar(start, days=180):
    selector.slot_index(start,start)
    if type(days) is not int or days<=0:raise ValueError('invalid_duration')
    origin=selector.timestamp(start)
    return [(origin+dt.timedelta(days=d)).isoformat() for d in range(0,days,7)]


def causal_panel(records, slot):
    """121 common daily closes; do not use late receipts or silently repair gaps."""
    cutoff=selector.timestamp(slot)
    dates=[(cutoff.date()-dt.timedelta(days=d)).isoformat() for d in range(121,0,-1)]
    panel={s:{} for s in selector.UNIVERSE}
    for r in records:
        if r['kind']!='daily' or r['symbol'] not in panel or r['day'] not in dates:continue
        if r['scope'] not in ('VERIFIED_QUALIFICATION_RECEIPT','VERIFIED_FORWARD_RECEIPT'):raise ValueError('unverified_input')
        if selector.timestamp(r['received_at'])>cutoff:continue
        symbol=r['symbol'];day=r['day']
        if day in panel[symbol] and panel[symbol][day]!=r['close']:raise ValueError('conflicting_close')
        panel[symbol][day]=r['close']
    if any(set(p)!=set(dates) for p in panel.values()):raise ValueError('common_warmup_incomplete')
    import numpy as np
    closes=np.array([[panel[s][d] for s in selector.UNIVERSE] for d in dates],dtype=float)
    if not np.isfinite(closes).all() or (closes<=0).any():raise ValueError('invalid_close')
    returns=closes[1:]/closes[:-1]-1
    # Matches frozen V13 rolling covariance; parity covered by synthetic test.
    covariance=np.cov(returns[-60:],rowvar=False,ddof=1)*365
    return dict(symbols=list(selector.UNIVERSE),dates=dates,closes=closes.tolist(),covariance=covariance.tolist(),
                covariance_convention='v13_sample60_annual365',execution_ready=False)


def estimate_funding(receipts, books, *, as_of, expected=None, maximum_mark_age_seconds=900):
    """Diagnostic estimates only; never certify settlement coverage from rates.

    `expected` is an optional externally supplied list of (symbol, epoch_ms).
    Matching it is diagnostic, not authentication of an exchange schedule.
    Mark proxy is the latest midpoint actually observed BEFORE settlement.
    Missing/late/stale inputs remain unresolved; this output cannot be handed
    straight to the execution kernel as coverage_complete=True.
    """
    import math
    cutoff=selector.timestamp(as_of)
    if type(maximum_mark_age_seconds) is not int or maximum_mark_age_seconds<=0:
        raise ValueError('invalid_mark_age_limit')
    rates={}
    for receipt in receipts:
        if receipt['scope'] not in ('VERIFIED_QUALIFICATION_RECEIPT','VERIFIED_FORWARD_RECEIPT') or receipt['kind']!='funding':
            raise ValueError('unverified_funding')
        if selector.timestamp(receipt['received_at'])>cutoff:continue
        for e in receipt['events']:
            if type(e['at']) is not int or not math.isfinite(e['rate']):raise ValueError('invalid_funding_event')
            when=dt.datetime.fromtimestamp(e['at']/1000,dt.timezone.utc)
            if when>cutoff:raise ValueError('future_settlement')
            key=(receipt['symbol'],e['at'])
            if key in rates and rates[key]!=e['rate']:raise ValueError('conflicting_funding')
            rates[key]=e['rate']
    output=[]
    for (symbol,milliseconds),rate in sorted(rates.items()):
        when=dt.datetime.fromtimestamp(milliseconds/1000,dt.timezone.utc)
        candidates={}
        for book in books:
            if book['scope'] not in ('VERIFIED_QUALIFICATION_RECEIPT','VERIFIED_FORWARD_RECEIPT') or book['kind']!='books':
                raise ValueError('unverified_book')
            if book['symbol']!=symbol:continue
            observed=selector.timestamp(book['at']);received=selector.timestamp(book['received_at'])
            if not observed<=received<when or (when-observed).total_seconds()>maximum_mark_age_seconds:continue
            bid=float(book['bids'][0][0]);ask=float(book['asks'][0][0])
            if not all(math.isfinite(x) and x>0 for x in (bid,ask)) or bid>=ask:raise ValueError('invalid_mark_proxy')
            midpoint=(bid+ask)/2
            if observed in candidates and candidates[observed][0]!=midpoint:raise ValueError('conflicting_mark_proxy')
            candidates[observed]=(midpoint,book['raw_sha256'])
        chosen=max(candidates) if candidates else None
        output.append(dict(id=selector.digest([symbol,milliseconds]),symbol=symbol,at=when.isoformat(),rate=rate,
                           mark=candidates[chosen][0] if chosen else None,
                           mark_source_hash=candidates[chosen][1] if chosen else None,
                           mark_observed_at=chosen.isoformat() if chosen else None,
                           status='ESTIMATED_PRIOR_BOOK_MIDPOINT' if chosen else 'MARK_UNRESOLVED'))
    expected_set=set(map(tuple,expected)) if expected is not None else None
    observed_set=set(rates)
    return dict(scope='FUNDING_ESTIMATE_DIAGNOSTIC_ONLY',events=output,coverage_complete=False,
                expected_schedule_match=(observed_set==expected_set) if expected_set is not None else None,
                missing_expected=sorted(expected_set-observed_set) if expected_set is not None else None,
                unexpected_observed=sorted(observed_set-expected_set) if expected_set is not None else None,
                execution_ready=False)


def read_warmup(source, expected_report_hash):
    """Byte-verified import of the pinned one-shot archive; no network fallback.

    External caller pins the report hash. Identity mapping is inherited from
    that reviewed acquisition, not inferred from a filename or a new API call.
    """
    import hashlib
    import math
    import urllib.parse
    try:
        from . import v13_universe_view as view
    except ImportError:
        import v13_universe_view as view
    root=Path(source)
    envelope=view.decode((root/'report.json').read_bytes());report=envelope['report']
    if view.digest(report)!=expected_report_hash or envelope['report_sha256']!=expected_report_hash:
        raise ValueError('warmup_report_binding')
    records=[]
    for receipt in report['receipts']:
        ident=receipt['receipt_id']
        if view.digest({k:v for k,v in receipt.items() if k!='receipt_id'})!=ident:
            raise ValueError('warmup_receipt_binding')
        path=root/'raw'/(ident+'.raw')
        if path.is_symlink():raise ValueError('warmup_symlink')
        raw=path.read_bytes()
        if hashlib.sha256(raw).hexdigest()!=receipt['raw_sha256']:raise ValueError('warmup_raw_hash')
        started=selector.timestamp(receipt['started_at']);received=selector.timestamp(receipt['received_at'])
        if started>received:raise ValueError('warmup_receipt_time')
        url=urllib.parse.urlsplit(receipt['url'])
        if url.scheme!='https' or url.netloc!='fapi.binance.com' or url.path!='/fapi/v1/klines':continue
        query=urllib.parse.parse_qs(url.query)
        if query.get('interval')!=['1d'] or len(query.get('symbol',[]))!=1:raise ValueError('warmup_query')
        symbol=query['symbol'][0]
        if symbol not in selector.UNIVERSE or receipt['status']!=200:continue
        lower=int(query['startTime'][0]);upper=int(query['endTime'][0])
        rows=view.decode(raw);seen=set()
        for row in rows:
            opened=row[0];closed=row[6]
            if (type(opened)!=int or type(closed)!=int or opened%86400000 or closed!=opened+86400000-1
                    or not lower<=opened<=closed<=upper or opened in seen):raise ValueError('warmup_bar_time')
            seen.add(opened)
            if closed/1000>=received.timestamp():raise ValueError('warmup_unclosed_bar')
            close=float(row[4])
            if not math.isfinite(close) or close<=0:raise ValueError('warmup_close')
            records.append(dict(scope='VERIFIED_QUALIFICATION_RECEIPT',kind='daily',symbol=symbol,
                                day=dt.datetime.fromtimestamp(opened/1000,dt.timezone.utc).date().isoformat(),close=close,
                                received_at=receipt['received_at'],raw_sha256=receipt['raw_sha256'],origin='PINNED_WARMUP'))
    return records


def bridge_daily(*archives, slot):
    """Merge only available daily rows; explicitly report per-symbol missing days."""
    cutoff=selector.timestamp(slot)
    days={(cutoff.date()-dt.timedelta(days=d)).isoformat() for d in range(1,122)}
    merged={}
    for archive in archives:
        for row in archive:
            if row['kind']!='daily' or row['symbol'] not in selector.UNIVERSE or row['day'] not in days:continue
            if row['scope'] not in ('VERIFIED_QUALIFICATION_RECEIPT','VERIFIED_FORWARD_RECEIPT'):raise ValueError('unverified_daily')
            if selector.timestamp(row['received_at'])>cutoff:continue
            key=(row['symbol'],row['day'])
            if key in merged and merged[key]['close']!=row['close']:raise ValueError('conflicting_daily')
            if key not in merged or selector.timestamp(row['received_at'])<selector.timestamp(merged[key]['received_at']):merged[key]=row
    missing={s:sorted(days-{day for symbol,day in merged if symbol==s}) for s in selector.UNIVERSE}
    return dict(records=[merged[k] for k in sorted(merged)],missing=missing,
                common_warmup_complete=not any(missing.values()),execution_ready=False)


def read_science_day(source_root, snapshot_path, repo, *, expected_uid, day, as_of):
    """Bridge one daily bar per original symbol using the actual custodian verifier.

    Historical import: availability is snapshot publication, never bar close.
    Does not re-run or promote the original strategy or its operational issuer.
    """
    import urllib.parse
    from octobot.ai_strategy_lab import v13_research_source as source
    contract,_=source.p.load_contract(repo)
    snapshot=source.owned_json(snapshot_path,expected_uid)
    published=selector.timestamp(snapshot['published_at'])
    cutoff=selector.timestamp(as_of)
    if (snapshot['scope']!=source.SCOPE or snapshot['lineage']!=contract['scientific_lineage_ref']
            or snapshot['universe']!=contract['universe'] or published>cutoff
            or snapshot['snapshot_id']!=source.p.digest({k:v for k,v in snapshot.items() if k!='snapshot_id'})):
        raise ValueError('science_binding')
    requested=dt.date.fromisoformat(day)
    if day>snapshot['day'] or published<dt.datetime.combine(requested+dt.timedelta(days=1),dt.time(0,10),dt.timezone.utc):
        raise ValueError('science_day_unavailable')
    result={};urls=set()
    for receipt in snapshot['requests']:
        if receipt['url'] in urls:raise ValueError('duplicate_science_url')
        urls.add(receipt['url'])
        if selector.timestamp(receipt['received_at'])>published:raise ValueError('science_publication_time')
        raw=source.captured(source_root,receipt,expected_uid)
        url=urllib.parse.urlsplit(receipt['url'])
        if url.scheme!='https' or url.netloc!='fapi.binance.com' or url.path!='/fapi/v1/klines':continue
        query=urllib.parse.parse_qs(url.query)
        if query.get('interval')!=['1d'] or len(query.get('symbol',[]))!=1:raise ValueError('science_query')
        symbol=query['symbol'][0]
        if symbol not in contract['universe']:raise ValueError('science_symbol')
        for row in source.p.read_json(raw):
            if dt.datetime.fromtimestamp(row[0]/1000,dt.timezone.utc).date()!=requested:continue
            opened=int(dt.datetime.combine(requested,dt.time(),dt.timezone.utc).timestamp()*1000)
            if (row[0]!=opened or row[6]!=opened+86400000-1 or symbol in result
                    or not int(query['startTime'][0])<=row[0]<=row[6]<=int(query['endTime'][0])):
                raise ValueError('science_bar_time')
            close=capture.positive(row[4])
            result[symbol]=dict(scope='VERIFIED_QUALIFICATION_RECEIPT',kind='daily',symbol=symbol,
                                day=day,close=close,received_at=snapshot['published_at'],
                                raw_sha256=receipt['raw_sha256'],origin='ORIGINAL_SCIENCE_BRIDGE',snapshot_id=snapshot['snapshot_id'])
    if set(result)!=set(contract['universe']):raise ValueError('science_day_incomplete')
    return [result[s] for s in sorted(result)]


def funding_readiness(receipts, books, *, symbols, start, end, as_of):
    """Distinguish daily receipt coverage, observed settlements and mark proxies.

    No regular settlement schedule is inferred from observed differences.
    A complete collection window is NOT proof of complete exchange settlements.
    """
    begin=selector.timestamp(start);finish=selector.timestamp(end);cutoff=selector.timestamp(as_of)
    if begin>=finish or begin.time()!=dt.time() or finish.time()!=dt.time() or finish>cutoff:
        raise ValueError('invalid_funding_window')
    days={(begin+dt.timedelta(days=i)).date().isoformat() for i in range((finish-begin).days)}
    result={}
    for symbol in symbols:
        selected=[];covered=set()
        for row in receipts:
            if row['symbol']!=symbol:continue
            if row['scope'] not in ('VERIFIED_QUALIFICATION_RECEIPT','VERIFIED_FORWARD_RECEIPT') or row['kind']!='funding':raise ValueError('unverified_funding')
            a=selector.timestamp(row['window_start']);b=selector.timestamp(row['window_end'])
            if b-a!=dt.timedelta(days=1) or a.time()!=dt.time() or selector.timestamp(row['received_at'])<b:raise ValueError('invalid_receipt_window')
            if a<begin or b>finish or selector.timestamp(row['received_at'])>cutoff:continue
            covered.add(a.date().isoformat());selected.append(row)
            for event in row['events']:
                t=dt.datetime.fromtimestamp(event['at']/1000,dt.timezone.utc)
                if not a<=t<b:raise ValueError('settlement_outside_receipt_window')
        estimate=estimate_funding(selected,[b for b in books if b['symbol']==symbol],as_of=as_of)
        unresolved=[e['at'] for e in estimate['events'] if e['mark'] is None]
        observed=sorted(e['at'] for e in estimate['events'])
        result[symbol]=dict(receipt_days=len(covered),expected_receipt_days=len(days),missing_receipt_days=sorted(days-covered),
                            observed_settlements=len(observed),estimated_marks=len(observed)-len(unresolved),unresolved_marks=unresolved,
                            settlement_coverage='UNKNOWN',observed_times=observed)
    return dict(scope='FUNDING_READINESS_DIAGNOSTIC',start=start,end=end,as_of=as_of,symbols=result,
                all_daily_receipts_present=all(not r['missing_receipt_days'] for r in result.values()) if result else False,
                all_observed_marks_estimated=all(not r['unresolved_marks'] for r in result.values()) if result else False,
                settlement_coverage='UNKNOWN',execution_ready=False)
