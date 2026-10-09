"""Offline comparison of prospective announcements with public history.

Not a reviewed calendar, coverage certificate, mark estimate or execution grant.
History is acquired after the interval and keeps its actual receipt timestamp.
"""
import hashlib
import json
import math
from pathlib import Path
from urllib.parse import urlsplit, parse_qs

try:
    from . import v13_universe_qualification as capture
except ImportError:
    import v13_universe_qualification as capture


def reconcile(observations, history_root, mapping, *, as_of):
    root=Path(history_root)
    envelope=capture.decode((root/'report.json').read_bytes());report=envelope['report']
    pin=capture.sha(capture.canonical(report))
    if pin!=envelope['report_sha256'] or report.get('scope')!='PUBLIC_FUNDING_HISTORY_REVIEW':
        raise ValueError('history_report_binding')
    start,end=observations['start']*1000,observations['end']*1000
    if end>as_of*1000 or set(observations['symbols'])!=set(mapping):raise ValueError('review_window_or_symbols')
    events={s:{} for s in mapping};seen=set();unavailable=set()
    for receipt in report['receipts']:
        ident=capture.sha(capture.canonical({k:v for k,v in receipt.items() if k!='receipt_id'}))
        if receipt['receipt_id']!=ident:raise ValueError('history_receipt_binding')
        p=root/'raw'/(ident+'.raw')
        if p.is_symlink():raise ValueError('history_symlink')
        raw=p.read_bytes()
        if len(raw)>65536 or hashlib.sha256(raw).hexdigest()!=receipt['raw_sha256']:raise ValueError('history_raw_hash')
        parts=urlsplit(receipt['url']);query=parse_qs(parts.query)
        if (parts.scheme!='https' or parts.netloc!='api-futures.kucoin.com'
                or parts.path!='/api/v1/contract/funding-rates' or parts.fragment
                or set(query)!={'symbol','from','to'}):raise ValueError('history_endpoint')
        remote=query['symbol']
        symbols=[s for s,r in mapping.items() if remote==[r]]
        if len(symbols)!=1:raise ValueError('history_symbol')
        symbol=symbols[0]
        if symbol in seen or query['from']!=[str(start)] or query['to']!=[str(end)]:raise ValueError('history_query_or_duplicate')
        received=capture.utc(receipt['received_at']);started=capture.utc(receipt['started_at'])
        if not end/1000<=started<=received<=as_of or receipt['status']!=200:raise ValueError('history_time_or_status')
        value=capture.decode(raw)
        if value.get('code')!='200000':raise ValueError('history_response')
        seen.add(symbol)
        if value.get('data') is None:
            unavailable.add(symbol)
            continue
        if not isinstance(value['data'],list):raise ValueError('history_response')
        for row in value['data']:
            at=row['timepoint'];rate=row['fundingRate']
            if type(at) is not int or not start<=at<=end or at in events[symbol]:raise ValueError('history_event_time')
            if isinstance(rate,bool) or not math.isfinite(float(rate)):raise ValueError('history_rate')
            if 'symbol' in row and row['symbol']!=mapping[symbol]:raise ValueError('history_event_symbol')
            if at>start:events[symbol][at]=float(rate)
    if seen!=set(mapping):raise ValueError('history_symbols_incomplete')
    symbols={};count=0
    for symbol,record in observations['symbols'].items():
        expected=set(record['announced_events_due']);actual=set(events[symbol]);count+=len(expected)
        symbols[symbol]=dict(announced=len(expected),observed_settlements=None if symbol in unavailable else len(actual),
            history_available=symbol not in unavailable,
            missing=sorted(expected-actual),unexpected=sorted(actual-expected),
            interval_changes=sum(t['interval_changed'] for t in record['transitions']),
            discontinuous_transitions=sum(not t['contiguous_boundary'] for t in record['transitions']))
    matched=(not unavailable and observations['status']=='OBSERVATIONS_COMPLETE' and not any(
        r['missing'] or r['unexpected'] or r['discontinuous_transitions'] for r in symbols.values()))
    status=('NO_MATURE_SETTLEMENTS' if count==0 and matched else
            'MATCHED_OBSERVED_ANNOUNCEMENTS_NOT_CERTIFIED' if matched else 'REVIEW_REQUIRED')
    return dict(scope='FUNDING_HISTORY_RECONCILIATION_NOT_CALENDAR',status=status,
        history_report_sha256=pin,start=observations['start'],end=observations['end'],symbols=symbols,
        funding_coverage_certified=False,mark_coverage='NOT_REVIEWED',execution_ready=False)
