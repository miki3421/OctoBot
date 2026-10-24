"""Read-only retirement receipt validation, never an execution authority."""
import hashlib
import json
import math
import os
from pathlib import Path
import stat

ACCOUNT = 'btc-intraday-m1-l5-paper-v1'
CONTAINER = 'octobot-btc-intraday-paper'
SCOPE = 'RETIRED_SYNTHETIC_PAPER_ACCOUNT'


def strict(raw):
    def pairs(items):
        value = {}
        for k, v in items:
            if k in value:
                raise ValueError('duplicate_key')
            value[k] = v
        return value
    value = json.loads(raw, object_pairs_hook=pairs)
    json.dumps(value, allow_nan=False)
    return value


def bounded(path, limit, *, uid):
    path = Path(path)
    fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    try:
        info = os.fstat(fd)
        if not stat.S_ISREG(info.st_mode) or info.st_uid != uid or info.st_mode & 0o022 or info.st_size > limit or info.st_nlink != 1:
            raise ValueError('archive_custody')
        raw = os.read(fd, limit+1)
    finally:
        os.close(fd)
    if len(raw) > limit:
        raise ValueError('archive_size')
    return raw


def validate(receipt_path, projection_raw, *, now_ns, projection=None):
    path = Path(receipt_path)
    parent = path.parent.stat()
    if path.parent.is_symlink() or parent.st_uid != 0 or parent.st_mode & 0o022:
        raise ValueError('retirement_parent_custody')
    r = strict(bounded(path, 65536, uid=0))
    v = strict(projection_raw) if projection is None else projection
    if (r.get('schema') != 1 or r.get('scope') != SCOPE or r.get('account') != ACCOUNT
            or r.get('container') != CONTAINER or r.get('retired') is not True
            or r.get('real_orders') is not False or r.get('both_scenarios_flat') is not True
            or r.get('both_scenarios_no_pending') is not True
            or not isinstance(r.get('operator_reference'), str) or not r['operator_reference'].strip()
            or type(r.get('retired_at_ns')) is not int
            or not v['checked_at_ns'] <= r['retired_at_ns'] <= now_ns
            or r.get('projection_sha256') != hashlib.sha256(projection_raw).hexdigest()
            or v.get('schema') != 1 or v.get('account') != ACCOUNT
            or v.get('scope') != 'SYNTHETIC_RESEARCH_PAPER_NOT_KUCOIN_ORDER_ADMISSIBILITY'
            or v.get('no_real_orders') is not True
            or v.get('accounting_complete') is not True or v['stress'].get('accounting_complete') is not True
            or type(v['state']['q']) not in (int, float) or type(v['stress']['q']) not in (int, float)
            or v['state']['q'] != 0 or v['stress']['q'] != 0 or v['state'].get('pending') is not None):
        raise ValueError('retirement_identity_hash_or_unsettled_state')
    for value in (v['metrics']['equity'], v['stress']['equity']):
        if type(value) not in (float, int) or not math.isfinite(value) or value <= 0:
            raise ValueError('retirement_accounting')
    return dict(retired=True, status='RETIRED', retired_at_ns=r['retired_at_ns'],
                reason='Sostituito dal confronto BTC intraday SHORT / LONG + SHORT',
                projection_sha256=r['projection_sha256'], read_only_archive=True)


def read(receipt_path, projection_path, *, now_ns, projection_uid=30943):
    raw = bounded(projection_path, 2*1024*1024, uid=projection_uid)
    return validate(receipt_path, raw, now_ns=now_ns)
