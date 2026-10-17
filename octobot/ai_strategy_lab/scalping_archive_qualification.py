"""Read-only technical snapshots and offline L5 data quality; no economic labels.

A technical qualification copy is not the old stop-required scientific freeze.
Work cards 56d2d3e2, 72de3590, b5ebd41a; no exchange or execution interfaces.
"""
import argparse
import collections
import datetime as dt
import hashlib
import json
import math
import os
from pathlib import Path
import sqlite3
import time

LIVE = Path('/root/auto_trading_sys/octobot-local/scalping/btc-futures-level5.sqlite')
UTC=dt.timezone.utc

def dump(v):return json.dumps(v,sort_keys=True,allow_nan=False)
def now():return dt.datetime.now(UTC).isoformat()
def file_sha(path):
    h=hashlib.sha256()
    with Path(path).open('rb') as f:
        for b in iter(lambda:f.read(4*1024*1024),b''):h.update(b)
    return h.hexdigest()
def write(path,value):
    path=Path(path);tmp=path.with_suffix('.tmp');tmp.write_text(dump(value)+'\n');os.replace(tmp,path)
def ro(path,immutable=False):
    path=Path(path)
    if path.is_symlink() or not path.is_file():raise ValueError('existing_regular_file_required')
    c=sqlite3.connect(path.resolve().as_uri()+'?mode=ro'+('&immutable=1' if immutable else ''),uri=True,timeout=5)
    c.execute('PRAGMA query_only=ON');c.execute('PRAGMA cache_size=-65536');c.execute('PRAGMA temp_store=FILE');return c

def boundary(c):
    result={}
    for table,key in [('book_events','id'),('trade_events','id'),('second_buckets','bucket_ts_s')]:
        result[table]=[c.execute(f'SELECT {key} FROM {table} ORDER BY {key} LIMIT 1').fetchone(),c.execute(f'SELECT {key} FROM {table} ORDER BY {key} DESC LIMIT 1').fetchone()]
    result['schema']=c.execute("SELECT name,sql FROM sqlite_master ORDER BY name").fetchall()
    result['sessions']=c.execute('SELECT * FROM scalping_sessions ORDER BY session_id').fetchall()
    return result

def ensure_capacity(destination,source):
    import shutil
    if os.stat(destination).st_dev==os.stat('/').st_dev:raise ValueError('large_disk_required')
    if shutil.disk_usage(destination).free<source.stat().st_size*2+5*1024**3:raise ValueError('disk_budget')

def snapshot(source,destination,health=None):
    source,destination=Path(source),Path(destination)
    if destination.exists() or destination.resolve()==source.resolve():raise ValueError('new_destination_required')
    destination.mkdir(parents=True,mode=0o750)
    ensure_capacity(destination,source)
    c=ro(source)
    if c.execute('PRAGMA journal_mode').fetchone()[0]!='wal':raise ValueError('live_snapshot_requires_WAL')
    started=time.monotonic();c.execute('BEGIN');before=boundary(c)
    tmp=destination/'snapshot.sqlite.partial';dst=sqlite3.connect(tmp);last=[0]
    def progress(status,left,total):
        elapsed=time.monotonic()-started
        if elapsed>1200:raise TimeoutError('snapshot_deadline')
        wal=Path(str(source)+'-wal')
        if wal.exists() and wal.stat().st_size>512*1024**2:raise ValueError('live_WAL_budget')
        if elapsed-last[0]>=10:
            value=dict(phase='SNAPSHOT',at=now(),remaining_pages=left,total_pages=total,elapsed_seconds=round(elapsed,1));print(dump(value),flush=True);write(destination/'progress.json',value);last[0]=elapsed
    try:
        c.backup(dst,pages=4096,progress=progress,sleep=.01)
        if boundary(dst)!=before:raise ValueError('snapshot_boundary_mismatch')
        dst.commit()
    finally:
        dst.close();c.rollback();c.close()
    with tmp.open('rb') as f:os.fsync(f.fileno())
    final=destination/'snapshot.sqlite';tmp.rename(final);final.chmod(0o440)
    result=dict(schema=1,scope='TECHNICAL_DQA_COPY_NOT_SCIENTIFIC_FREEZE',completed_at=now(),copy_seconds=time.monotonic()-started,bytes=final.stat().st_size,sha256=file_sha(final),boundary=before,source_alias='scalping-live-readonly',live_writes=False,source_wal_mode=True,scientific_promotion=False)
    write(destination/'snapshot-manifest.json',result);print(dump(dict(phase='SNAPSHOT_COMPLETE',bytes=result['bytes'],sha256=result['sha256'],copy_seconds=result['copy_seconds'])),flush=True)
    return result


def bucket_summary(rows, progress=None):
    """Stream causal second aggregates; no future returns or trade labels."""
    days={};first=last=None;last_book=None;max_gap=0;gaps=[];bad=0;book_total=trade_total=0;hist=collections.Counter();bounds=[.05,.1,.25,.5,1,2,5,10,20,100]
    for i,r in enumerate(rows):
        t,nb,nt,op,hi,lo,cl,spread,imb,buy,sell,buy_n,sell_n,bid,ask,lat=r
        if last is not None and t<=last:raise ValueError('bucket_order_or_duplicate')
        first=t if first is None else first;last=t;day=dt.datetime.fromtimestamp(t,UTC).date().isoformat();d=days.setdefault(day,dict(rows=0,book_seconds=0,book_events=0,trade_events=0,invalid=0))
        d['rows']+=1;d['book_events']+=nb;d['trade_events']+=nt;book_total+=nb;trade_total+=nt
        valid=type(nb) is int and type(nt) is int and min(nb,nt,buy_n,sell_n,buy,sell)>=0 and buy_n+sell_n==nt
        if nb:
            valid=valid and all(v is not None and math.isfinite(v) and v>0 for v in [op,hi,lo,cl,bid,ask])
            if valid:valid=lo<=min(op,cl)<=max(op,cl)<=hi and bid<ask and math.isfinite(spread) and spread>=0 and math.isfinite(imb) and abs(imb)<=nb+1e-6
            d['book_seconds']+=1
            if last_book is not None:
                gap=t-last_book-1;max_gap=max(max_gap,gap)
                if gap>0:
                    gaps.append(dict(after=last_book,before=t,missing_seconds=gap));gaps=sorted(gaps,key=lambda x:x['missing_seconds'],reverse=True)[:30]
            last_book=t
            if spread is not None and math.isfinite(spread):
                avg=spread/nb;k=next((str(x) for x in bounds if avg<=x),'overflow');hist[k]+=1
        if not valid:bad+=1;d['invalid']+=1
        if progress and i%100000==0:progress(i)
    if first is None:return dict(status='INSUFFICIENT',days={},rows=0)
    for day,d in days.items():
        start=int(dt.datetime.fromisoformat(day).replace(tzinfo=UTC).timestamp());expected=min(last,start+86399)-max(first,start)+1
        d.update(expected_seconds=expected,book_coverage=d['book_seconds']/expected)
    return dict(status='AUDITED',first_bucket=first,last_bucket=last,expected_seconds=last-first+1,rows=sum(d['rows'] for d in days.values()),book_seconds=sum(d['book_seconds'] for d in days.values()),coverage=sum(d['book_seconds'] for d in days.values())/(last-first+1),book_event_sum=book_total,trade_event_sum=trade_total,invalid=bad,max_missing_book_seconds=max_gap,largest_gaps=gaps,spread_average_bps_histogram_upper_bounds=dict(hist),days=days)

def book_predicate():
    price=[f'{side}_price_{i}' for side in ['bid','ask'] for i in range(1,6)];size=[f'{side}_size_{i}' for side in ['bid','ask'] for i in range(1,6)]
    tests=[f'{x}>0 AND {x}<1e308' for x in price]+[f'{x}>=0 AND {x}<1e308' for x in size]
    tests += [f'bid_price_{i}>bid_price_{i+1}' for i in range(1,5)]+[f'ask_price_{i}<ask_price_{i+1}' for i in range(1,5)]
    tests += ['bid_price_1<ask_price_1','microprice>=bid_price_1','microprice<=ask_price_1','abs(mid_price-(bid_price_1+ask_price_1)/2)<max(1e-6,abs(mid_price)*1e-10)','abs(spread_bps-(ask_price_1/bid_price_1-1)*10000)<1e-6','imbalance_5>=-1.00000001','imbalance_5<=1.00000001','sequence>0','exchange_ts_ns>0','received_ts_ns>0','abs(latency_ms-(received_ts_ns-exchange_ts_ns)/1000000.0)<1e-5',"length(payload_sha256)=64 AND payload_sha256 NOT GLOB '*[^0-9a-f]*'",'session_id IN (SELECT session_id FROM scalping_sessions)']
    return '('+') AND ('.join(tests)+')'

def validate_copy(path,manifest):
    path=Path(path)
    if path.resolve()==LIVE.resolve() or path.stat().st_mode&0o222:raise ValueError('sealed_offline_copy_required')
    m=json.loads(Path(manifest).read_text())
    if m['scope']!='TECHNICAL_DQA_COPY_NOT_SCIENTIFIC_FREEZE' or path.stat().st_size!=m['bytes'] or file_sha(path)!=m['sha256']:raise ValueError('snapshot_identity')
    return m

def audit(path,output):
    output=Path(output);manifest=validate_copy(path,output/'snapshot-manifest.json')
    integrity=json.loads((output/'integrity.json').read_text())
    if integrity['result']!=['ok']:raise ValueError('offline_integrity_failed')
    (output/'sqlite-tmp').mkdir(exist_ok=True);os.environ['SQLITE_TMPDIR']=str(output/'sqlite-tmp');c=ro(path,True);started=time.monotonic();last=[0];phase=['START']
    def progress(n=None):
        elapsed=time.monotonic()-started
        if elapsed-last[0]>10:
            value=dict(phase=phase[0],elapsed_seconds=round(elapsed,1),at=now(),rows=n);write(output/'audit-progress.json',value);print(dump(value),flush=True);last[0]=elapsed
        return 0
    c.set_progress_handler(progress,100000)
    required={'scalping_sessions','book_events','trade_events','second_buckets'}
    if not required.issubset({r[0] for r in c.execute("SELECT name FROM sqlite_master WHERE type='table'")}):raise ValueError('schema_missing')
    sessions=[dict(zip(['session_id','schema_version','symbol','started_at','ended_at','status','stop_reason'],r)) for r in c.execute('SELECT * FROM scalping_sessions ORDER BY started_at')]
    if any(s['schema_version']!=1 or s['symbol']!='XBTUSDTM' for s in sessions):raise ValueError('session_identity')
    book=[];trade=[]
    nsday=86400*10**9
    first=c.execute('SELECT received_ts_ns FROM book_events ORDER BY received_ts_ns LIMIT 1').fetchone();end=c.execute('SELECT received_ts_ns FROM book_events ORDER BY received_ts_ns DESC LIMIT 1').fetchone()
    if not first or not end:raise ValueError('book_empty')
    start=first[0]//nsday*nsday;pred=book_predicate();lat_bounds=[0,50,100,150,250,500,1000,5000]
    prior=None
    while start<=end[0]:
        stop=start+nsday;day=dt.datetime.fromtimestamp(start/1e9,UTC).date().isoformat();phase[0]='BOOK_VALIDATION:'+day
        hist=','.join(f'SUM(CASE WHEN latency_ms<={bound} THEN 1 ELSE 0 END)' for bound in lat_bounds)
        sql=f'SELECT COUNT(*),MIN(received_ts_ns),MAX(received_ts_ns),SUM(CASE WHEN {pred} THEN 0 ELSE 1 END),MIN(latency_ms),MAX(latency_ms),AVG(latency_ms),{hist} FROM book_events WHERE received_ts_ns>=? AND received_ts_ns<?'
        r=c.execute(sql,(start,stop)).fetchone();item=dict(day=day,rows=r[0],first_received=r[1],last_received=r[2],invalid=r[3] or 0,latency_min_ms=r[4],latency_max_ms=r[5],latency_mean_ms=r[6],latency_histogram_cumulative=dict(zip(map(str,lat_bounds),r[7:])))
        phase[0]='BOOK_GAPS:'+day
        gaps=c.execute('SELECT MAX(delta),SUM(CASE WHEN delta>5000000000 THEN 1 ELSE 0 END) FROM (SELECT received_ts_ns-LAG(received_ts_ns) OVER (ORDER BY received_ts_ns) AS delta FROM book_events WHERE received_ts_ns>=? AND received_ts_ns<?)',(start,stop)).fetchone()
        seam=r[1]-prior if prior is not None and r[1] is not None else 0
        item['max_gap_ns']=max(gaps[0] or 0,seam);item['gaps_over_5_seconds']=(gaps[1] or 0)+int(seam>5*10**9);prior=r[2] if r[2] is not None else prior;book.append(item)
        phase[0]='TRADE_VALIDATION:'+day
        r=c.execute("SELECT COUNT(*),SUM(CASE WHEN price>0 AND price<1e308 AND size>0 AND size<1e308 AND side IN ('buy','sell') AND received_ts_ns>0 AND exchange_ts_ns>0 AND abs(latency_ms-(received_ts_ns-exchange_ts_ns)/1000000.0)<1e-5 AND length(payload_sha256)=64 AND payload_sha256 NOT GLOB '*[^0-9a-f]*' AND session_id IN (SELECT session_id FROM scalping_sessions) THEN 0 ELSE 1 END),MIN(latency_ms),MAX(latency_ms) FROM trade_events WHERE received_ts_ns>=? AND received_ts_ns<?",(start,stop)).fetchone();trade.append(dict(day=day,rows=r[0],invalid=r[1] or 0,min_latency_ms=r[2],max_latency_ms=r[3]))
        write(output/'book-trade-progress.json',dict(book_days=book,trade_days=trade));start=stop;progress()
    phase[0]='SECOND_BUCKET_RECONCILIATION'
    buckets=bucket_summary(c.execute('SELECT * FROM second_buckets ORDER BY bucket_ts_s'),progress)
    book_n=sum(r['rows'] for r in book);trade_n=sum(r['rows'] for r in trade);reconcile=dict(book_raw=book_n,book_bucket=buckets['book_event_sum'],trade_raw=trade_n,trade_bucket=buckets['trade_event_sum'])
    reconcile['matched']=book_n==buckets['book_event_sum'] and trade_n==buckets['trade_event_sum']
    c.close()
    result=dict(schema=1,scope='OFFLINE_DATA_QUALITY_NOT_STRATEGY_VALIDATION',completed_at=now(),snapshot_sha256=manifest['sha256'],snapshot_bytes=manifest['bytes'],elapsed_seconds=time.monotonic()-started,integrity=integrity,sessions=sessions,book_days=book,trade_days=trade,buckets=buckets,reconciliation=reconcile,book_invalid=sum(r['invalid'] for r in book),trade_invalid=sum(r['invalid'] for r in trade),raw_book_gaps_over_5_seconds=sum(r['gaps_over_5_seconds'] for r in book),largest_raw_book_gap_seconds=max(r['max_gap_ns'] for r in book)/1e9,technical_rows_valid=not(sum(r['invalid'] for r in book)+sum(r['invalid'] for r in trade)+buckets['invalid']) and reconcile['matched'],limitations=['No alpha,return,label,markout,trade simulation or sealed economic evaluation calculated','Raw size units need contemporaneous instrument metadata before conversion to BTC or USDT depth','No maker queue position/order-level cancels in L5 aggregated snapshots','Payload hashes can be syntax checked but raw exchange payloads are not preserved for independent reconstruction','Capture latency is observed exchange-to-receive clock difference; no calibrated end-to-end execution latency','New data qualification does not reopen rejected strategy families or authorize a paper account'])
    write(output/'qualification.json',result);print(dump(dict(phase='AUDIT_COMPLETE',book_rows=book_n,trade_rows=trade_n,technical_rows_valid=result['technical_rows_valid'],coverage=buckets['coverage'])),flush=True);return result

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('command',choices=['snapshot','audit']);p.add_argument('--source',type=Path,required=True);p.add_argument('--destination',type=Path,required=True);a=p.parse_args()
    if a.command=='snapshot':snapshot(a.source,a.destination)
    else:audit(a.source,a.destination)
