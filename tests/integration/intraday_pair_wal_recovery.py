"""Offline two-process reproduction using a RW writer and RO reader mount.

Run writer as UID 1000, reader as UID 30943 with source mounted RO. Host test
orchestrator supplies close/reopen/release files; never point at live data.
"""
import json
from pathlib import Path
import sqlite3
import sys
import time

ROOT=Path('/fixture')


def report(value):print(json.dumps(value),flush=True)


def wait(name):
    until=time.monotonic()+90
    while not (ROOT/name).exists():
        if time.monotonic()>until:raise TimeoutError('offline fixture coordination')
        time.sleep(.05)


def connect():
    db=sqlite3.connect(ROOT/'book.sqlite');db.execute('PRAGMA journal_mode=WAL')
    columns=['id INTEGER PRIMARY KEY','session_id TEXT','received_ts_ns INTEGER','exchange_ts_ns INTEGER','payload_sha256 TEXT']
    columns += [f'{side}_{field}_{i} REAL' for side in ('bid','ask') for field in ('price','size') for i in range(1,6)]
    db.execute('CREATE TABLE IF NOT EXISTS book_events('+','.join(columns)+')')
    now=time.time_ns();row=dict(session_id='synthetic-session',received_ts_ns=now,exchange_ts_ns=now-1000000,payload_sha256='a'*64)
    for side in ('bid','ask'):
        for i in range(1,6):
            row[f'{side}_price_{i}']=100000-i if side=='bid' else 100000+i
            row[f'{side}_size_{i}']=100.
    db.execute('INSERT INTO book_events('+','.join(row)+') VALUES('+','.join('?' for _ in row)+')',tuple(row.values()));db.commit()
    return db


if sys.argv[1]=='writer':
    db=connect();(ROOT/'ready').write_text('ready');report(dict(writer='open',sqlite=sqlite3.sqlite_version))
    wait('close');db.close();(ROOT/'closed').write_text('closed');report(dict(writer='closed',sidecars=[p.name for p in ROOT.glob('book.sqlite-*')]))
    wait('reopen');db=connect();(ROOT/'reopened').write_text('reopened');report(dict(writer='reopened'))
    wait('release');db.close()
else:
    sys.path.insert(0,'/source/octobot/ai_strategy_lab')
    from intraday_pair.receipts import Clock
    from btc_intraday_pair_io import RecoveringBookReader
    events=[]
    def record(event):events.append(event);report(event)
    reader=RecoveringBookReader(ROOT/'book.sqlite',Clock(),record)
    reader.poll();assert reader.cursor==1
    report(dict(reader='ready',cursor=reader.cursor,sqlite=sqlite3.sqlite_version))
    until=time.monotonic()+80
    while time.monotonic()<until:
        batch=reader.poll()
        if batch:
            rows=batch[0]['rows'];assert [r['id'] for r in rows]==[2]
            assert reader.cursor==1  # No advance before successful persistence.
            reader.cursor=2
            assert any(e['event']=='BOOK_READ_WAIT' and e['sqlite_errorcode']==14 for e in events)
            assert events[-1]['event']=='BOOK_READ_RECOVERED'
            report(dict(result='PASS',same_process=True,cursor=reader.cursor,errors=reader.errors,
                        source_read_only=True,state=reader.status()['status']))
            break
        time.sleep(.05)
    else:raise TimeoutError('offline recovery was not observed')
