"""Public-data custodian and original V13 derivation for research paper only.

Work card: work-card-77c03de2-8219-4ee0-8d56-a8651e760613.
Old research records, contracts and issuers are never promoted or rewritten.
"""
from __future__ import annotations

import concurrent.futures
import datetime as dt
import hashlib
import gzip
import math
import os
from pathlib import Path
import stat
import tempfile
import time
import urllib.parse
import urllib.request

from octobot.ai_strategy_lab import v13_original_portfolio as p
from octobot.ai_strategy_lab import v13_original_verify as original
from octobot.ai_strategy_lab.microstructure import _timestamp_ms

UTC = dt.timezone.utc
SCOPE = 'RESEARCH_SIMULATION_ONLY'


def now():
    return dt.datetime.now(UTC)


def atomic(path, value):
    path = Path(path)
    payload = p.canonical_bytes(value) + b'\n'
    if path.suffix=='.gz':payload=gzip.compress(payload,mtime=0)
    fd, name = tempfile.mkstemp(dir=path.parent, prefix='.pending-')
    try:
        with os.fdopen(fd, 'wb') as f:
            os.fchmod(f.fileno(), 0o640)
            f.write(payload); f.flush(); os.fsync(f.fileno())
        os.replace(name, path)
        fd = os.open(path.parent, os.O_RDONLY | os.O_DIRECTORY)
        try: os.fsync(fd)
        finally: os.close(fd)
    finally:
        if os.path.exists(name): os.unlink(name)


def config(path, role):
    path = Path(path)
    if path.is_symlink() or path.stat().st_uid != 0 or path.stat().st_mode & 0o022:
        raise p.Rejected('root_owned_config_required')
    c = p.read_json(path.read_bytes())
    if set(c['uids'])!={'capture','producer','issuer','executor'} or any(type(v)!=int or v<=0 for v in c['uids'].values()) or len(set(c['uids'].values()))!=4:
        raise p.Rejected('distinct_nonroot_roles_required')
    if c['scope'] != SCOPE or c['enabled'] is not True or os.geteuid() != c['uids'][role]:
        raise p.Rejected('role_or_scope_mismatch')
    for name, expected in c['code_pins'].items():
        file = Path(c['repo']) / name
        if hashlib.sha256(file.read_bytes()).hexdigest() != expected:
            raise p.Rejected('runtime_code_changed')
    contract = Path(c['repo']) / 'docs/contracts/v13-research-paper-v1.json'
    if hashlib.sha256(contract.read_bytes()).hexdigest() != c['contract_sha256']:
        raise p.Rejected('research_contract_changed')
    c['contract'] = p.read_json(contract.read_bytes())
    return c


def owned_json(path, uid):
    path = Path(path)
    if path.is_symlink() or path.stat().st_uid != uid or path.stat().st_mode & 0o022:
        raise p.Rejected('custody_owner_mismatch')
    if path.suffix=='.gz':
        with gzip.open(path,'rb') as stream:payload=stream.read(p.MAX_JSON_BYTES+1)
        return p.read_json(payload)
    return p.read_json(path.read_bytes())


def captured(root, receipt, uid):
    path = Path(root) / 'raw' / (p.require_hash(receipt['capture_id']) + '.json.gz')
    if not path.exists():path=path.with_suffix('')
    value = owned_json(path, uid)
    if value != receipt or value['kind'] != 'LIVE_PUBLIC_HTTPS_CAPTURE' or value['capture_id'] != p.digest({k:v for k,v in value.items() if k!='capture_id'}):
        raise p.Rejected('capture_receipt_mismatch')
    raw = bytes.fromhex(value['raw_hex'])
    if hashlib.sha256(raw).hexdigest() != value['raw_sha256']:
        raise p.Rejected('raw_hash_mismatch')
    start, end = p.timestamp(value['started_at']), p.timestamp(value['received_at'])
    if start > end or end > now() or value['status'] != 200:
        raise p.Rejected('capture_clock_or_http_invalid')
    return raw


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *args, **kwargs):
        raise p.Rejected('public_redirect_forbidden')


def fetch(root, url):
    parts = urllib.parse.urlsplit(url)
    if parts.scheme != 'https' or parts.netloc not in {'fapi.binance.com', 'api-futures.kucoin.com'} or parts.fragment:
        raise p.Rejected('public_endpoint_forbidden')
    if parts.netloc == 'fapi.binance.com' and parts.path not in {'/fapi/v1/klines', '/fapi/v1/fundingRate'}:
        raise p.Rejected('public_endpoint_forbidden')
    if parts.netloc == 'api-futures.kucoin.com' and not (parts.path in {'/api/v1/contracts/active', '/api/v1/level2/depth20', '/api/v1/contract/funding-rates'} or parts.path.startswith('/api/v1/mark-price/')):
        raise p.Rejected('public_endpoint_forbidden')
    started = now()
    request = urllib.request.Request(url, headers={'User-Agent': 'V13-Research-Paper/1'})
    with urllib.request.build_opener(NoRedirect()).open(request, timeout=30) as response:
        raw = response.read(p.MAX_JSON_BYTES + 1)
        status = response.status
    if len(raw) > p.MAX_JSON_BYTES or status != 200:
        raise p.Rejected('public_response_invalid')
    value = dict(kind='LIVE_PUBLIC_HTTPS_CAPTURE', url=url, started_at=started.isoformat(), received_at=now().isoformat(),
                 status=status, raw_sha256=hashlib.sha256(raw).hexdigest(), raw_hex=raw.hex())
    value['capture_id'] = p.digest(value)
    atomic(Path(root)/'raw'/(value['capture_id']+'.json.gz'), value)
    return raw, value


def context(c):
    contract, _ = p.load_contract(c['repo'])
    inputs = original.Inputs(Path(c['repo']), Path(c['research']), Path(c['bootstrap']), Path(c['lock']))
    runner, ctx = original._load_runner(inputs, contract)
    return runner, ctx, contract


def science_capture(c):
    root = Path(c['source'])
    path = root/'science.json'
    day = (now()-dt.timedelta(minutes=10)).date()-dt.timedelta(days=1)
    if path.exists() and owned_json(path,c['uids']['capture'])['day'] == day.isoformat():
        return
    runner, ctx, contract = context(c)
    receipts = []
    def fetcher(url):
        raw, receipt = fetch(root,url)
        receipts.append(receipt)
        return raw
    with tempfile.TemporaryDirectory() as tmp:
        daily = runner.fetch_public_daily_range(contract['universe'], runner.protocol.WARMUP_START,day+dt.timedelta(days=1),
            raw_root=Path(tmp), maximum_workers=6, fetch_bytes=fetcher)
    snapshot = dict(scope=SCOPE, day=day.isoformat(), requests=sorted(receipts,key=lambda r:r['url']),
                    published_at=now().isoformat(), daily_count=len(daily), lineage=contract['scientific_lineage_ref'],
                    universe=contract['universe'], historical_bootstrap_availability='UNRESOLVED')
    snapshot['snapshot_id'] = p.digest(snapshot)
    atomic(root/'science'/ (snapshot['snapshot_id']+'.json'), snapshot)
    atomic(path,snapshot)


def derive(c, snapshot, *, with_identity=False):
    runner, ctx, contract = context(c)
    if snapshot['scope'] != SCOPE or snapshot['lineage'] != contract['scientific_lineage_ref'] or snapshot['universe'] != contract['universe']:
        raise p.Rejected('scientific_identity_mismatch')
    if snapshot['snapshot_id'] != p.digest({k:v for k,v in snapshot.items() if k!='snapshot_id'}):
        raise p.Rejected('science_snapshot_changed')
    day = p.bar_date(snapshot['day'])
    mature = dt.datetime.combine(day+dt.timedelta(days=1),dt.time(),UTC)+dt.timedelta(minutes=10)
    if p.timestamp(snapshot['published_at']) < mature or (now()-p.timestamp(snapshot['published_at'])).total_seconds()>36*3600:
        raise p.Rejected('science_stale_or_future')
    responses = {}
    for receipt in snapshot['requests']:
        if p.timestamp(receipt['received_at'])>p.timestamp(snapshot['published_at']):
            raise p.Rejected('publication_before_capture')
        if receipt['url'] in responses:
            raise p.Rejected('duplicate_scientific_request')
        responses[receipt['url']] = captured(c['source'], receipt, c['uids']['capture'])
    used = set()
    def fetcher(url):
        if url not in responses: raise p.Rejected('scientific_capture_missing')
        used.add(url)
        return responses[url]
    with tempfile.TemporaryDirectory() as tmp:
        daily = runner.fetch_public_daily_range(contract['universe'],runner.protocol.WARMUP_START,day+dt.timedelta(days=1),
             raw_root=Path(tmp),maximum_workers=6,fetch_bytes=fetcher)
    if used != set(responses): raise p.Rejected('extraneous_scientific_capture')
    records = [dict(bar_date=d.isoformat(),symbols=v['symbols']) for d,v in sorted(daily.items())]
    # Project frozen bridge columns only; original extension and signal code unchanged.
    frozen = dict(ctx['cointegration_market'])
    columns = [frozen['symbols'].index(s) for s in contract['universe']]
    frozen['symbols'] = list(contract['universe'])
    frozen['closes'] = frozen['closes'][:,columns]
    frozen['funding'] = frozen['funding'][:,columns]
    market = runner.extend_trend_market(ctx['trend_market'], frozen, records)
    result = runner.simulate_trend_forward(market,ctx['trend_config'],runner.protocol.FORWARD_START,day+dt.timedelta(days=1))
    targets = p.complete_targets(dict(zip(market['symbols'],map(float,result['targets'][-1]))),contract)
    causal = p.digest([{'bar_date': record['bar_date'], 'symbols': {symbol: {key: record['symbols'][symbol][key] for key in ['close','funding_rate_sum','funding_settlement_count']} for symbol in contract['universe']}} for record in records])
    identity = p.digest(dict(domain='v13-original-causal-research-decision-v1',day=day.isoformat(),lineage=contract['scientific_lineage_ref'],causal_input_hash=causal))
    return dict(targets=targets,causal_input_hash=causal,decision_id=identity) if with_identity else targets


def _data(raw):
    v=p.read_json(raw)
    if v.get('code')!='200000': raise p.Rejected('kucoin_public_error')
    return v['data']


def market_capture(c):
    root=Path(c['source']); started=now(); receipts=[]
    raw,receipt=fetch(root,'https://api-futures.kucoin.com/api/v1/contracts/active');receipts.append(receipt)
    contracts={v['symbol']:v for v in _data(raw)}
    def one(symbol):
        remote='XBTUSDTM' if symbol=='BTCUSDT' else symbol+'M'
        m=contracts[remote]
        if m['settleCurrency']!='USDT' or m['isInverse'] is not False or m['status']!='Open': raise p.Rejected('contract_identity')
        urls=['https://api-futures.kucoin.com/api/v1/level2/depth20?'+urllib.parse.urlencode({'symbol':remote}),
              'https://api-futures.kucoin.com/api/v1/mark-price/'+remote+'/current',
              'https://api-futures.kucoin.com/api/v1/contract/funding-rates?'+urllib.parse.urlencode({'symbol':remote,'from':c['funding_start_ms'],'to':int(now().timestamp()*1000)})]
        values=[];rs=[]
        for url in urls:
            payload,r=fetch(root,url);rs.append(r);values.append(_data(payload))
        book,mark,rates=values
        multiplier=float(m['multiplier']); step=multiplier*float(m['lotSize'])
        if mark['symbol']!=remote or mark['granularity']!=1000:raise p.Rejected('mark_identity')
        def levels(side):return [dict(price=float(p),base_quantity=float(q)*multiplier) for p,q in book[side]]
        funding=sorted([dict(timestamp_ms=int(v['timepoint']),rate=float(v['fundingRate'])) for v in rates],key=lambda v:v['timestamp_ms'])
        quote=dict(symbol=symbol,market_identity='kucoin_futures_usdt',timestamp=dt.datetime.fromtimestamp(_timestamp_ms(book['ts'])/1000,UTC).isoformat(),
             mark_timestamp=dt.datetime.fromtimestamp(mark['timePoint']/1000,UTC).isoformat(),mark_price=float(mark['value']),
             metadata_observed_at=receipt['received_at'],bids=levels('bids'),asks=levels('asks'),
             step=step,quantity_step=step,contract_multiplier=multiplier,price_tick=float(m['tickSize']),
             fee_rate=max(0.0006,float(m['takerFeeRate'])),min_quantity=None,min_notional=None,
             funding=funding,funding_interval_ms=int(m.get('currentFundingRateGranularity') or m['fundingRateGranularity']),
             simulation_min_quantity=step,simulation_min_notional=1.0,metadata_scope='REAL_PRECISION_WITH_SEPARATE_SIMULATED_MINIMUMS')
        return symbol,quote,rs
    contract,_=p.load_contract(c['repo'])
    with concurrent.futures.ThreadPoolExecutor(max_workers=6) as pool:
        result=list(pool.map(one,contract['universe']))
    record=dict(scope=SCOPE,observed_at_start=started.isoformat(),observed_at_end=now().isoformat(),
           quotes={s:q for s,q,rs in result},capture_ids=[receipt['capture_id']]+[r['capture_id'] for s,q,rs in result for r in rs])
    record['record_hash']=p.digest(record)
    atomic(root/'market'/(record['record_hash']+'.json.gz'),record);atomic(root/'market.json',record)
