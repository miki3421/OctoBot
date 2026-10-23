"""Separate public-only 29-symbol input custodian for managed M1.

No ledger, approval, order or credential mount. Original collectors unchanged.
"""
import argparse
import concurrent.futures
import datetime as dt
import hashlib
import json
import os
from pathlib import Path
import time
import urllib.parse
import urllib.request
from . import v13_research_source as source
from . import v13_m1_weekly as weekly
from .microstructure import _timestamp_ms


def fetch(root,url):
    parts=urllib.parse.urlsplit(url)
    allowed=(parts.scheme=='https' and not parts.fragment and
        ((parts.netloc=='fapi.binance.com' and parts.path in ('/fapi/v1/klines','/fapi/v1/exchangeInfo')) or
         (parts.netloc=='api-futures.kucoin.com' and (parts.path in ('/api/v1/contracts/active','/api/v1/level2/depth20','/api/v1/contract/funding-rates') or parts.path.startswith('/api/v1/mark-price/')))))
    if not allowed:raise ValueError('public_endpoint_forbidden')
    started=source.now()
    req=urllib.request.Request(url,headers={'User-Agent':'M1-Weekly-Paper-Research/1'})
    with urllib.request.build_opener(source.NoRedirect()).open(req,timeout=20) as response:
        raw=response.read(source.p.MAX_JSON_BYTES+1);status=response.status
    if status!=200 or len(raw)>source.p.MAX_JSON_BYTES:raise ValueError('public_response_invalid')
    receipt=dict(kind='LIVE_PUBLIC_HTTPS_CAPTURE',url=url,started_at=started.isoformat(),received_at=source.now().isoformat(),status=status,raw_sha256=hashlib.sha256(raw).hexdigest(),raw_hex=raw.hex())
    receipt['capture_id']=weekly.digest(receipt)
    source.atomic(root/'raw'/(receipt['capture_id']+'.json.gz'),receipt)
    return json.loads(raw),receipt


def kucoin(value):
    if str(value.get('code'))!='200000' or 'data' not in value:raise ValueError('public_api_error')
    return value['data']


def daily(root,fetcher=fetch):
    day=(source.now().date()-dt.timedelta(days=1));path=root/'science.json'
    if source.now().time().replace(tzinfo=None)<dt.time(0,10):
        if path.exists():return json.loads(path.read_text())
        raise ValueError('daily_close_lag_10_minutes')
    if path.exists():
        old=json.loads(path.read_text())
        if old['day']==day.isoformat():return old
    metadata,meta_receipt=fetcher(root,'https://fapi.binance.com/fapi/v1/exchangeInfo')
    contracts={v['symbol']:v for v in metadata['symbols']}
    last=int(dt.datetime.combine(day+dt.timedelta(days=1),dt.time(),weekly.UTC).timestamp()*1000)-1
    def one(symbol):
        try:
            m=contracts[symbol]
            if m['contractType']!='PERPETUAL' or m['quoteAsset']!='USDT' or m['marginAsset']!='USDT' or m['status']!='TRADING':raise ValueError('binance_contract_identity')
            payload,receipt=fetcher(root,'https://fapi.binance.com/fapi/v1/klines?'+urllib.parse.urlencode(dict(symbol=symbol,interval='1d',limit=121,endTime=last)))
            rows=[]
            for row in payload:
                opened=dt.datetime.fromtimestamp(int(row[0])/1000,weekly.UTC)
                if opened.time()!=dt.time() or int(row[6])!=int(row[0])+86400000-1:raise ValueError('daily_boundaries')
                price=weekly.num(float(row[4]))
                if price<=0:raise ValueError('positive_close_required')
                rows.append(dict(day=opened.date().isoformat(),close=price,received_at=receipt['received_at']))
            return symbol,rows,receipt['capture_id'],None
        except (ValueError,KeyError,TypeError,OSError):return symbol,None,None,'DAILY_CAPTURE_UNAVAILABLE'
    with concurrent.futures.ThreadPoolExecutor(max_workers=6) as pool:results=list(pool.map(one,weekly.POOL))
    science=dict(scope='M1_WEEKLY_CAUSAL_DAILY_V1',day=day.isoformat(),published_at=source.now().isoformat(),
                 bars={s:b for s,b,_,_ in results if b is not None},
                 unavailable={s:e for s,_,_,e in results if e},capture_ids=[meta_receipt['capture_id']]+[h for _,_,h,_ in results if h])
    science['snapshot_id']=weekly.digest(science)
    source.atomic(root/'science'/(science['snapshot_id']+'.json'),science);source.atomic(path,science)
    return science


def market(root,funding_start_ms,fetcher=fetch):
    started=source.now();payload,metadata=fetcher(root,'https://api-futures.kucoin.com/api/v1/contracts/active')
    contracts={m['symbol']:m for m in kucoin(payload)}
    def one(symbol):
        try:
            remote='XBTUSDTM' if symbol=='BTCUSDT' else symbol+'M';m=contracts[remote]
            if m['settleCurrency']!='USDT' or m['isInverse'] is not False or m['status']!='Open':raise ValueError('kucoin_contract_identity')
            book,r1=fetcher(root,'https://api-futures.kucoin.com/api/v1/level2/depth20?'+urllib.parse.urlencode({'symbol':remote}))
            mark,r2=fetcher(root,'https://api-futures.kucoin.com/api/v1/mark-price/'+remote+'/current')
            rates,r3=fetcher(root,'https://api-futures.kucoin.com/api/v1/contract/funding-rates?'+urllib.parse.urlencode(dict(symbol=remote,**{'from':funding_start_ms,'to':int(source.now().timestamp()*1000)})))
            book,mark,rates=kucoin(book),kucoin(mark),kucoin(rates)
            if mark['symbol']!=remote or mark['granularity']!=1000:raise ValueError('mark_identity')
            multiplier=weekly.num(float(m['multiplier']));step=multiplier*weekly.num(float(m['lotSize']))
            if multiplier<=0 or step<=0:raise ValueError('contract_precision')
            quote=dict(symbol=symbol,market_identity='kucoin_futures_usdt',
                timestamp=dt.datetime.fromtimestamp(_timestamp_ms(book['ts'])/1000,weekly.UTC).isoformat(),
                mark_timestamp=dt.datetime.fromtimestamp(mark['timePoint']/1000,weekly.UTC).isoformat(),mark_price=float(mark['value']),
                metadata_observed_at=metadata['received_at'],
                bids=[dict(price=float(p),base_quantity=float(q)*multiplier) for p,q in book['bids']],
                asks=[dict(price=float(p),base_quantity=float(q)*multiplier) for p,q in book['asks']],
                step=step,quantity_step=step,contract_multiplier=multiplier,price_tick=float(m['tickSize']),
                fee_rate=max(.0006,float(m['takerFeeRate'])),min_quantity=None,min_notional=None,
                simulation_min_quantity=step,simulation_min_notional=1.,metadata_scope='REAL_PRECISION_WITH_SEPARATE_SIMULATED_MINIMUMS',
                funding=sorted([dict(timestamp_ms=int(v['timepoint']),rate=float(v['fundingRate'])) for v in rates],key=lambda v:v['timestamp_ms']),
                funding_interval_ms=int(m.get('currentFundingRateGranularity') or m['fundingRateGranularity']))
            return symbol,quote,[r1['capture_id'],r2['capture_id'],r3['capture_id']],None
        except (ValueError,KeyError,TypeError,OSError):return symbol,None,[],'MARKET_CAPTURE_UNAVAILABLE'
    with concurrent.futures.ThreadPoolExecutor(max_workers=6) as pool:results=list(pool.map(one,weekly.POOL))
    record=dict(scope=source.SCOPE,observed_at_start=started.isoformat(),observed_at_end=source.now().isoformat(),
                quotes={s:q for s,q,_,_ in results if q},unavailable={s:e for s,_,_,e in results if e},
                capture_ids=[metadata['capture_id']]+[h for _,_,hs,_ in results for h in hs])
    record['record_hash']=weekly.digest(record)
    source.atomic(root/'market'/(record['record_hash']+'.json.gz'),record);source.atomic(root/'market.json',record)
    return record


def main():
    parser=argparse.ArgumentParser();parser.add_argument('--config',required=True);parser.add_argument('--once',action='store_true');args=parser.parse_args()
    path=Path(args.config)
    if path.is_symlink() or path.stat().st_uid!=0 or path.stat().st_mode&0o022:raise ValueError('root_owned_configuration_required')
    c=json.loads(path.read_text())
    if c['scope']!='M1_WEEKLY_PUBLIC_CAPTURE_V1' or not c['public_downloads_authorized'] or os.geteuid()!=c['capture_uid']:raise ValueError('public_capture_authorization')
    root=Path(c['output'])
    while True:
        try:
            daily(root);market(root,c['funding_start_ms'])
            source.atomic(root/'health.json',dict(status='HEALTHY',checked_at=source.now().isoformat(),orders_authorized=False))
        except (ValueError,KeyError,TypeError,OSError):
            source.atomic(root/'health.json',dict(status='WAITING_INPUT',checked_at=source.now().isoformat(),orders_authorized=False))
        if args.once:break
        time.sleep(c['poll_seconds'])


if __name__=='__main__':main()
