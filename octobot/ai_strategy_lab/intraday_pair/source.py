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
