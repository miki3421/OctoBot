"""Bounded read-only public projection; no ledger or control channel."""
import json
import math
import os
from pathlib import Path
import stat
import time

SCOPE = 'SYNTHETIC_RESEARCH_PAPER_NOT_KUCOIN_ORDER_ADMISSIBILITY'
PROTOCOL = '06c8fa9aa85ecb5ea9fae49fd1b9cbe81178f14b85a033bb2b3dda4e8413caeb'
ARMS = {'control-primary', 'candidate-primary', 'control-stress', 'candidate-stress'}


def public(path='/v13-paper/intraday-pair-ui/comparison.json', now_ns=None, uid=30943):
    def pairs(items):
        out = {}
        for k, v in items:
            if k in out:
                raise ValueError('duplicate_key')
            out[k] = v
        return out
    before = time.time_ns() if now_ns is None else now_ns
    fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    try:
        s = os.fstat(fd)
        if not stat.S_ISREG(s.st_mode) or s.st_uid != uid or s.st_mode & 0o022 or s.st_size > 8*1024*1024:
            raise ValueError('projection_custody_or_size')
        raw = os.read(fd, 8*1024*1024+1)
    finally:
        os.close(fd)
    if len(raw) > 8*1024*1024:
        raise ValueError('projection_size')
    v = json.loads(raw, object_pairs_hook=pairs)
    json.dumps(v, allow_nan=False)
    now = time.time_ns() if now_ns is None else now_ns
    if (now < before or v.get('schema') != 1 or v.get('scope') != SCOPE
            or v.get('no_real_orders') is not True or type(v.get('checked_at_ns')) is not int
            or not 0 <= now-v['checked_at_ns']):
        raise ValueError('projection_identity_or_clock')
    v['age_seconds'] = (now-v['checked_at_ns'])/1e9
    v['stale'] = v['age_seconds'] > 30
    if v.get('phase') == 'BLOCKED':
        return v
    if (v.get('protocol_sha') != PROTOCOL or v.get('mode') != 'AUTHORIZED_RESEARCH_PAPER_PAIR'
            or v.get('active_account') is not True or set(v.get('arms', {})) != ARMS
            or v.get('real_min_quantity') != 'UNKNOWN' or v.get('real_min_notional') != 'UNKNOWN'
            or type(v.get('t0_ns')) is not int or v['t0_ns'] % (86400*10**9)
            or v.get('t1_ns') != v['t0_ns']+90*86400*10**9
            or v.get('phase') not in ('PRESTART', 'WARMUP', 'OBSERVING', 'COMPLETED')
            or (v['phase'] == 'PRESTART' and v['checked_at_ns'] >= v['t0_ns'])
            or (v['phase'] == 'COMPLETED' and v['checked_at_ns'] < v['t1_ns'])):
        raise ValueError('pair_identity')
    for name, a in v['arms'].items():
        expected = 'btc-intraday-short-control-v1' if name.startswith('control') else 'btc-intraday-long-short-v1'
        if a.get('account') != expected or a.get('scenario') != name.split('-')[1]:
            raise ValueError('account_identity')
        for k in ('equity', 'q', 'fees', 'funding', 'realized'):
            if type(a.get(k)) not in (int, float) or not math.isfinite(a[k]):
                raise ValueError('accounting_invalid')
        for k in ('last_market_ns', 'last_book_ns'):
            if a.get(k) is not None and (type(a[k]) is not int or a[k] > now):
                raise ValueError('source_clock')
        if type(a.get('cursor')) is not int or type(a.get('fills')) is not int or a['fills'] < 0:
            raise ValueError('account_counters')
    return v
