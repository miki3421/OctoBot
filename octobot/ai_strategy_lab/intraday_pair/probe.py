"""Bounded RO source/fanout qualification. Cannot activate a strategy.

Run as a module with an explicit NEW private evidence destination. All state
writers are confined to that destination; original source DBs are opened RO.
"""
import argparse
import json
from pathlib import Path
import sqlite3
import time

from . import receipts
from .runner import Pair
from .source import NS, canonical


def probe(source,book,output,seconds=15):
    if not 1<=seconds<=30:raise ValueError('bounded_duration_required')
    source,book,output=Path(source).resolve(),Path(book).resolve(),Path(output).absolute()
    for original in (source,book.parent):
        if output.resolve().is_relative_to(original) or original.is_relative_to(output.resolve()):
            raise ValueError('source_destination_overlap')
    now=time.time_ns();t0=(now//(86400*NS)+1)*86400*NS
    pair=Pair(output,t0,'PUBLIC_SOURCE_PROBE_NOT_AN_ACTIVATION',initialize=True)
    deadline=time.monotonic()+seconds;cycles=0
    try:
        reader=receipts.BookReader(book,pair.clock)
        while time.monotonic()<deadline:
            pair.poll_sources(source,reader);cycles+=1;time.sleep(.1)
        result=pair.status()
        if any(a['fills'] or a['q'] for a in result['arms'].values()):raise ValueError('probe_must_remain_flat')
        if len({a['cursor'] for a in result['arms'].values()})!=1:raise ValueError('incomplete_fanout')
        counts={r[0]:r[1] for r in pair.db.execute('SELECT kind,count(*) FROM inputs GROUP BY kind')}
        lags=[]
        for row in pair.db.execute("SELECT payload FROM inputs WHERE kind='book'"):
            v=json.loads(row[0]);visible=v['proof']['observed_visible']['utc_ns']
            lags.extend((visible-r['received_ts_ns'])/1e6 for r in v['payload']['rows'])
        qualified=counts.get('market',0)>0 and any(0<=lag<=1000 for lag in lags)
        result.update(status='PUBLIC_INPUT_FANOUT_QUALIFIED_PRESTART_ONLY' if qualified else 'INCONCLUSIVE_PUBLIC_INPUT_COVERAGE',cycles=cycles,
                      input_counts=counts,book_rows=len(lags),fresh_book_rows=sum(0<=lag<=1000 for lag in lags),
                      visibility_lag_ms=dict(min=min(lags),max=max(lags)) if lags else None,
                      no_new_network_acquisitions=True,no_strategy_activated=True,
                      no_predictive_or_order_admissibility_evidence=True)
    finally:pair.close()
    result['cold_integrity']={}
    for path in list(output.glob('*.sqlite'))+[output/'witness/availability.sqlite']:
        with sqlite3.connect(path.as_uri()+'?mode=ro',uri=True) as db:
            values=[r[0] for r in db.execute('PRAGMA integrity_check')]
            if values!=['ok']:raise ValueError('private_cold_copy_integrity')
            result['cold_integrity'][str(path.relative_to(output))]='ok'
    (output/'qualification.json').write_bytes(canonical(result)+b'\n')
    return result


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--source',required=True);p.add_argument('--book',required=True)
    p.add_argument('--output',required=True);p.add_argument('--seconds',type=int,default=15)
    args=p.parse_args()
    print(json.dumps(probe(args.source,args.book,args.output,args.seconds),indent=2))
