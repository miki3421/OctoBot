"""Bounded offline integrity and insertion-order chronology checks. No returns."""
import argparse
import datetime as dt
import json
from pathlib import Path
import sqlite3
import time

def chronology(rows,progress=None):
    n=receive_back=exchange_back=sequence_back=switches=0;previous=None;max_back=0;examples=[]
    for ident,session,sequence,exchange,received in rows:
        n+=1
        if previous:
            pid,ps,pseq,pex,pr=previous
            if ident<=pid:raise ValueError('row_id_order')
            if received<pr:
                receive_back+=1;max_back=max(max_back,pr-received)
                if len(examples)<10:examples.append(dict(id=ident,back_ns=pr-received))
            if session==ps:
                exchange_back+=int(exchange<pex);sequence_back+=int(sequence<pseq)
            else:switches+=1
        previous=(ident,session,sequence,exchange,received)
        if progress and n%100000==0:progress(n)
    return dict(rows=n,received_timestamp_regressions=receive_back,maximum_receive_regression_ns=max_back,exchange_timestamp_regressions_same_session=exchange_back,sequence_regressions_same_session=sequence_back,session_switches=switches,examples=examples)

def main():
    p=argparse.ArgumentParser();p.add_argument('command',choices=['integrity','chronology']);p.add_argument('--snapshot',type=Path,required=True);p.add_argument('--output',type=Path,required=True);a=p.parse_args()
    if a.snapshot.is_symlink() or a.snapshot.stat().st_mode&0o222 or a.snapshot.resolve()==Path('/root/auto_trading_sys/octobot-local/scalping/btc-futures-level5.sqlite').resolve():raise ValueError('sealed_offline_copy_only')
    c=sqlite3.connect(a.snapshot.resolve().as_uri()+'?mode=ro&immutable=1',uri=True);c.execute('PRAGMA query_only=ON');c.execute('PRAGMA cache_size=-65536');started=time.monotonic();last=[started]
    def progress(rows=None):
        t=time.monotonic()
        if t-last[0]>15:print(json.dumps(dict(phase=a.command,elapsed_seconds=round(t-started,1),rows=rows)),flush=True);last[0]=t
        return 0
    if a.command=='integrity':
        c.set_progress_handler(progress,100000);result=dict(result=[r[0] for r in c.execute('PRAGMA integrity_check')])
    else:result=chronology(c.execute('SELECT id,session_id,sequence,exchange_ts_ns,received_ts_ns FROM book_events ORDER BY id'),progress)
    c.close();result.update(scope='IMMUTABLE_OFFLINE_COPY_ONLY',elapsed_seconds=time.monotonic()-started,completed_at=dt.datetime.now(dt.timezone.utc).isoformat());a.output.write_text(json.dumps(result,indent=2)+'\n');print(json.dumps(result),flush=True)
if __name__=='__main__':main()
