"""Read-only, bounded public projection of the separate synthetic intraday account."""
import hashlib
import json
import math
from pathlib import Path
import time


def public(path='/v13-paper/intraday-ui/account.json',now_ns=None):
    p=Path(path)
    if p.is_symlink() or p.stat().st_size>2*1024*1024:raise ValueError('projection_file')
    def pairs(items):
        result={}
        for k,v in items:
            if k in result:raise ValueError('duplicate_key')
            result[k]=v
        return result
    raw=p.read_bytes()
    v=json.loads(raw,object_pairs_hook=pairs)
    json.dumps(v,allow_nan=False)
    if v['schema']!=1 or v['account']!='btc-intraday-m1-l5-paper-v1' or v['scope']!='SYNTHETIC_RESEARCH_PAPER_NOT_KUCOIN_ORDER_ADMISSIBILITY' or v['no_real_orders'] is not True:
        raise ValueError('projection_scope')
    now_ns=now_ns if now_ns is not None else time.time_ns()
    age=(now_ns-v['checked_at_ns'])/1e9
    if age<0:raise ValueError('future_projection')
    v['stale']=age>30;v['age_seconds']=age
    retirement=p.parent.parent/'intraday-retirement/receipt.json'
    if retirement.exists() or retirement.is_symlink():
        from octobot.ai_strategy_lab.btc_intraday_retirement import validate
        v['retirement']=validate(retirement,raw,now_ns=now_ns,projection=v)
        v.update(retired=True,status='RETIRED',stale=False,read_only_archive=True)
    return v
