"""One-shot owner-authorized public research acquisition, never an operational collector.

Card work-card-0f4dfb58-e446-466d-bfc7-ed6a3a074df9.
"""
import datetime as dt
import hashlib
import json
import math
from pathlib import Path
import statistics
import time
import urllib.error
import urllib.parse
import urllib.request

if __package__:
    from . import v13_universe_view as view
    from . import v13_candidate_shortlist as shortlist
else:
    import v13_universe_view as view
    import v13_candidate_shortlist as shortlist

DAY = 86400000
PLAN = 'docs/V13_SHORTLIST_MEASUREMENT_V1.md'
REPORT = 'docs/data/v13-shortlist-measurements-v1.json'
COLLECTION_SHORTLIST_SHA256 = 'aa7a0995fd0f809c9cf8aed671ea3f45f56beb5e862435428cbf7b883c15efd2'


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *args, **kwargs):
        raise ValueError('redirect_forbidden')


def acquire(url, directory, receipts):
    parts = urllib.parse.urlsplit(url)
    allowed = {('fapi.binance.com', '/fapi/v1/exchangeInfo'), ('fapi.binance.com', '/fapi/v1/klines'),
               ('fapi.binance.com', '/fapi/v1/fundingRate'),
               ('api-futures.kucoin.com', '/api/v1/contracts/active'),
               ('api-futures.kucoin.com', '/api/v1/level2/depth20')}
    if parts.scheme != 'https' or (parts.netloc, parts.path) not in allowed or parts.fragment:
        raise ValueError('unauthorized_endpoint')
    started = dt.datetime.now(dt.timezone.utc).isoformat()
    time.sleep(0.25)
    try:
        with urllib.request.build_opener(NoRedirect()).open(
                urllib.request.Request(url, headers={'User-Agent': 'V13-Shortlist-Research/1'}), timeout=30) as response:
            raw = response.read(view.MAX_BYTES + 1); status = response.status
    except urllib.error.HTTPError as error:
        raw = error.read(view.MAX_BYTES + 1); status = error.code
    if len(raw) > view.MAX_BYTES:
        raise ValueError('response_too_large')
    record = dict(url=url, started_at=started, received_at=dt.datetime.now(dt.timezone.utc).isoformat(),
                  status=status, raw_sha256=hashlib.sha256(raw).hexdigest())
    key = view.digest(record); record['receipt_id'] = key
    (directory / (key + '.raw')).write_bytes(raw)
    (directory / (key + '.json')).write_text(json.dumps(record, indent=2))
    receipts.append(record)
    print(json.dumps({'endpoint': parts.path, 'query': parts.query, 'http': status}), flush=True)
    if status in (418, 429):
        raise ValueError('rate_limit_stop')
    if status != 200:
        return None, record
    return view.decode(raw), record


def mapping(kucoin, binance):
    expected = kucoin.get('baseCurrency', '') + 'USDT'
    matches = [r for r in binance if r.get('symbol') == expected and r.get('baseAsset') == kucoin.get('baseCurrency')
               and r.get('quoteAsset') == 'USDT' and r.get('marginAsset') == 'USDT'
               and r.get('contractType') == 'PERPETUAL' and r.get('status') == 'TRADING']
    return expected if len(matches) == 1 else None


def candles(rows, start, end):
    if not isinstance(rows, list):
        raise ValueError('candles_unavailable')
    closes = {}; previous = -1
    for row in rows:
        if not isinstance(row, list) or len(row) < 7:
            raise ValueError('invalid_candle')
        opened = row[0]; closed = row[6]; value = float(row[4])
        if (type(opened) is not int or type(closed) is not int or opened % DAY
                or not start <= opened < end or closed != opened + DAY - 1
                or closed >= end or opened <= previous or not math.isfinite(value) or value <= 0):
            raise ValueError('invalid_candle')
        closes[opened] = value; previous = opened
    return closes


def returns(closes, end):
    keys = list(range(end - 181 * DAY, end, DAY))
    if any(k not in closes for k in keys):
        return None
    values = [closes[k] for k in keys]
    result = [b / a - 1 for a, b in zip(values, values[1:])]
    return result if all(math.isfinite(v) for v in result) else None


def pearson(a, b):
    if a is None or b is None or len(a) != 180 or len(b) != 180:
        return None
    if not all(math.isfinite(v) for v in a+b):
        return None
    ma, mb = statistics.mean(a), statistics.mean(b)
    aa, bb = [v - ma for v in a], [v - mb for v in b]
    denom = math.sqrt(math.fsum(v*v for v in aa) * math.fsum(v*v for v in bb))
    if not denom:
        return None
    return max(-1.0, min(1.0, math.fsum(x*y for x, y in zip(aa, bb)) / denom))


def book_metrics(data, contract, received):
    if not isinstance(data, dict) or data.get('code') != '200000':
        raise ValueError('book_unavailable')
    book = data['data']; stamp = book['ts']
    # KuCoin level2 ts is nanoseconds in the captured API, accept documented
    # precision variants only by magnitude and verify against receipt time.
    if type(stamp) is not int or stamp <= 0:
        raise ValueError('book_timestamp')
    seconds = stamp / (1e9 if stamp >= 1e17 else 1e6 if stamp >= 1e14 else 1e3)
    observed = dt.datetime.fromtimestamp(seconds, dt.timezone.utc)
    if not 0 <= (view.timestamp(received) - observed).total_seconds() <= 60:
        raise ValueError('book_stale_or_future')
    multiplier = float(contract['multiplier'])
    if not math.isfinite(multiplier) or multiplier <= 0:
        raise ValueError('invalid_multiplier')
    sides = []
    for side, reverse in [('bids', True), ('asks', False)]:
        levels = [(float(p), float(q)) for p, q in book[side]]
        if not levels or len(levels) > 20 or any(not math.isfinite(p*q) or p <= 0 or q <= 0 for p,q in levels):
            raise ValueError('invalid_depth')
        prices = [p for p,q in levels]
        if prices != sorted(set(prices), reverse=reverse):
            raise ValueError('unordered_depth')
        sides.append(levels)
    bid, ask = sides[0][0][0], sides[1][0][0]
    if ask <= bid:
        raise ValueError('crossed_book')
    return {'as_of': observed.isoformat(), 'spread_bps': (ask-bid)/((ask+bid)/2)*10000,
            'bid_depth_usdt': math.fsum(p*q*multiplier for p,q in sides[0]),
            'ask_depth_usdt': math.fsum(p*q*multiplier for p,q in sides[1]),
            'bid_levels': len(sides[0]), 'ask_levels': len(sides[1])}


def collect(repo, output, fetch=acquire, end_ms=None):
    repo, output = Path(repo), Path(output); output.mkdir(exist_ok=False)
    rawdir = output / 'raw'; rawdir.mkdir(); receipts = []
    frozen = shortlist.load_public(repo)
    if frozen['report_sha256'] != COLLECTION_SHORTLIST_SHA256:
        raise ValueError('outside_authorized_shortlist')
    selected = [r['symbol'] for r in frozen['rows'] if r['selected']]
    baseline_raw = (repo / 'docs/contracts/v13-original-portfolio-adapter-candidate-v1.json').read_bytes()
    if hashlib.sha256(baseline_raw).hexdigest() != view.CONTRACT_HASH:
        raise ValueError('baseline_contract_changed')
    baseline = view.decode(baseline_raw)['universe']
    end = end_ms if end_ms is not None else int(dt.datetime.combine(dt.datetime.now(dt.timezone.utc).date(), dt.time(), dt.timezone.utc).timestamp()*1000)
    if type(end) is not int or end % DAY:
        raise ValueError('invalid_daily_cutoff')
    start = end - 366*DAY
    def get(host, path, **query):
        return fetch('https://'+host+path+('?' + urllib.parse.urlencode(query) if query else ''), rawdir, receipts)
    exchange, _ = get('fapi.binance.com','/fapi/v1/exchangeInfo')
    remote, _ = get('api-futures.kucoin.com','/api/v1/contracts/active')
    if not exchange or not isinstance(exchange.get('symbols'),list) or not remote or remote.get('code') != '200000':
        raise ValueError('identity_sources_unavailable')
    contracts = {r['symbol']: r for r in remote['data']}
    maps = {s: mapping(contracts[s], exchange['symbols']) if s in contracts and view._classify(contracts[s]) == ([],[]) else None for s in selected}
    series, errors = {}, {}
    valid_baseline = {s for s in baseline if any(r.get('symbol')==s and r.get('baseAsset')==s[:-4] and r.get('status')=='TRADING' and r.get('contractType')=='PERPETUAL' and r.get('quoteAsset')=='USDT' and r.get('marginAsset')=='USDT' for r in exchange['symbols'])}
    for symbol in sorted(valid_baseline | {s for s in maps.values() if s}):
        data, _ = get('fapi.binance.com','/fapi/v1/klines',symbol=symbol,interval='1d',startTime=start,endTime=end-1,limit=499)
        try: series[symbol] = candles(data,start,end)
        except (ValueError, TypeError, KeyError): errors[symbol]='INVALID_OR_UNAVAILABLE_CANDLES'
    rows = []
    for s in selected:
        mapped = maps[s]; closes = series.get(mapped,{})
        row = {'symbol':s,'binance_symbol':mapped,'mapping_status':'EXACT' if mapped else 'UNRESOLVED',
               'daily_count':len(closes),'daily_expected':366,'daily_complete':len(closes)==366,
               'missing_daily_count':366-len(closes),'correlation':None,'book':None,'funding':None,'issues':[],
               'min_quantity':None,'min_notional':None}
        if mapped is None: row['issues'].append('Nessun mapping Binance esatto verificato; nessuna equivalenza 1000-token dedotta')
        elif mapped in errors: row['issues'].append('Candele non verificabili')
        candidate_returns = returns(closes,end)
        correlations = {b: pearson(candidate_returns,returns(series.get(b,{}),end)) for b in baseline}
        if all(v is not None for v in correlations.values()):
            strongest = sorted(correlations,key=lambda b:(-abs(correlations[b]),b))[0]
            row['correlation'] = dict(observations=180, against='DAILY_ASSET_RETURNS_NOT_STRATEGY_PNL',
                                     maximum_absolute_peer=strongest, signed_value=correlations[strongest],
                                     btc=correlations['BTCUSDT'], all_peers=correlations)
        else: row['issues'].append('Correlazione non calcolabile su 180 rendimenti contigui comuni a tutti i riferimenti')
        if s in contracts:
            data,r = get('api-futures.kucoin.com','/api/v1/level2/depth20',symbol=s)
            try: row['book']=book_metrics(data,contracts[s],r['received_at'])
            except (ValueError,TypeError,KeyError,OverflowError): row['issues'].append('Book non verificabile')
        if mapped:
            events=[]; cursor=start; complete=False
            for _ in range(12):
                data,r = get('fapi.binance.com','/fapi/v1/fundingRate',symbol=mapped,startTime=cursor,endTime=end-1,limit=1000)
                if not isinstance(data,list): break
                valid=True
                for event in data:
                    stamp=event.get('fundingTime');rate=float(event.get('fundingRate','nan'))
                    if event.get('symbol')!=mapped or type(stamp) is not int or not cursor<=stamp<end or not math.isfinite(rate) or (events and stamp<=events[-1]['fundingTime']):
                        valid=False;break
                    events.append(event)
                if not valid: break
                if len(data)<1000:complete=True;break
                cursor=events[-1]['fundingTime']+1
            row['funding']=dict(events=len(events),pagination_exhausted=complete,
                               first=events[0]['fundingTime'] if events else None,last=events[-1]['fundingTime'] if events else None,
                               settlement_coverage='NOT_CERTIFIED')
            if not complete:row['issues'].append('Raccolta funding incompleta o non verificabile')
        rows.append(row)
    report=dict(version='v13-shortlist-measurements-v1',scope='DESCRIPTIVE_RESEARCH_ONLY',
                shortlist_sha256=frozen['report_sha256'],plan_sha256=hashlib.sha256((repo/PLAN).read_bytes()).hexdigest(),
                generated_at=dt.datetime.now(dt.timezone.utc).isoformat(),from_ms=start,to_exclusive_ms=end,
                correlation_from_ms=end-180*DAY,baseline=baseline,rows=rows,receipts=receipts,
                baseline_coverage={b:len(series.get(b,{})) for b in baseline},orders_authorized=False)
    envelope=dict(report=report,report_sha256=view.digest(report))
    (output/'report.json').write_text(json.dumps(envelope,ensure_ascii=False,indent=2)+'\n')
    print(json.dumps({'complete':True,'requests':len(receipts),'summary':[{k:r[k] for k in ['symbol','mapping_status','daily_count','correlation','issues']} for r in rows]}),flush=True)


def replay(repo, source, output):
    """Byte-verified deterministic replay, with no network fallback."""
    source=Path(source); envelope=view.decode((source/'report.json').read_bytes()); original=envelope['report']
    if envelope['report_sha256']!=view.digest(original):
        raise ValueError('replay_report_changed')
    records=original['receipts']; used=[]
    def offline(url, directory, receipts):
        if len(used)>=len(records):raise ValueError('unexpected_replay_request')
        r=records[len(used)]
        if r['url']!=url or r['receipt_id']!=view.digest({k:v for k,v in r.items() if k!='receipt_id'}):
            raise ValueError('replay_receipt_changed')
        raw=(source/'raw'/(r['receipt_id']+'.raw')).read_bytes()
        if hashlib.sha256(raw).hexdigest()!=r['raw_sha256'] or view.timestamp(r['started_at'])>view.timestamp(r['received_at']):
            raise ValueError('replay_raw_or_clock_changed')
        used.append(url);receipts.append(r)
        return (view.decode(raw) if r['status']==200 else None),r
    collect(repo,output,fetch=offline,end_ms=original['to_exclusive_ms'])
    result=view.decode((Path(output)/'report.json').read_bytes())['report']
    if len(used)!=len(records) or {k:v for k,v in result.items() if k!='generated_at'}!={k:v for k,v in original.items() if k!='generated_at'}:
        raise ValueError('replay_result_changed')
    return {'receipts_verified':len(used),'exact_semantic_replay':True,'network_calls':0}


def load_public(repo='/workspace'):
    repo=Path(repo); value=view.decode((repo/REPORT).read_bytes());r=value['report']
    if value['report_sha256']!=view.digest(r) or r['version']!='v13-shortlist-measurements-v1' or r['scope']!='DESCRIPTIVE_RESEARCH_ONLY' or r['orders_authorized'] is not False:
        raise ValueError('measurement_report_changed')
    if r['shortlist_sha256']!=shortlist.load_public(repo)['report_sha256'] or r['plan_sha256']!=hashlib.sha256((repo/PLAN).read_bytes()).hexdigest():
        raise ValueError('measurement_binding_changed')
    return dict(available=True,**{k:v for k,v in r.items() if k!='receipts'},report_sha256=value['report_sha256'])


if __name__=='__main__':
    import argparse
    p=argparse.ArgumentParser();p.add_argument('--repo',required=True);p.add_argument('--output',required=True)
    p.add_argument('--replay-from',help='Existing capture directory; prohibits network fallback')
    a=p.parse_args()
    if a.replay_from:print(json.dumps(replay(a.repo,a.replay_from,a.output)))
    else:collect(a.repo,a.output)
