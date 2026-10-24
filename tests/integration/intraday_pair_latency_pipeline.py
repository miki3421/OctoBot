"""Synthetic local writer -> RO reader -> durable witness -> four accounts.

No public acquisition or live account access. Run in a network-none container.
Normal persistence must retain positions; a real publication outage still exits.
"""
import json
from pathlib import Path
import sqlite3
import sys
import threading
import time
import uuid

sys.path.insert(0, '/runtime')
from btc_intraday_pair_latency import FastValuationPair
from intraday_pair import receipts
from intraday_pair.source import NS
from intraday_pair.engine import fresh
import scalping_observer as collector

ROOT = Path('/fixture')
ready = threading.Event()
pause = threading.Event()
stop = threading.Event()
errors = []


def writer():
    store = None
    try:
        config = collector.ScalpingObserverConfig(ROOT/'book.sqlite', ROOT/'health.json', commit_interval_seconds=.1)
        store = collector.ScalpingStore(config, 'synthetic-latency-only')
        sequence = 0
        while not stop.is_set():
            if pause.is_set():
                time.sleep(.01)
                continue
            stamp = time.time_ns()
            sequence += 1
            message = dict(type='message', subject='level2', topic='/contractMarket/level2Depth5:XBTUSDTM',
                data=dict(sequence=sequence, timestamp=(stamp-20_000_000)//1_000_000,
                          bids=[[str(100000-i), '100'] for i in range(1, 6)],
                          asks=[[str(100000+i), '100'] for i in range(1, 6)]))
            store.record_book(collector.parse_book_message(message, stamp))
            store.commit_if_due()
            ready.set()
            time.sleep(.1)
    except BaseException as error:
        errors.append(repr(error))
    finally:
        if store:
            store.close('completed', 'synthetic pipeline test')


thread = threading.Thread(target=writer)
thread.start()
assert ready.wait(10)
clock = receipts.Clock()
t0 = time.time_ns()//(86400*NS)*(86400*NS)
pair = FastValuationPair(ROOT/'accounts', t0, 'synthetic-latency-fixture', initialize=True, clock=clock, synthetic=True)
reader = receipts.BookReader(ROOT/'book.sqlite', clock)
latencies = []
latest = None


def cycle(record=True):
    global latest
    value = reader.poll()
    if value:
        payload, before, after = value
        rows = payload['rows']
        pair.publish('book', str(rows[0]['id'])+':'+str(rows[-1]['id']), payload, before, after,
                     max(r['received_ts_ns'] for r in rows))
        reader.cursor = rows[-1]['id']
        latest = rows[-1]
        if record:
            latencies.append((time.time_ns()-latest['received_ts_ns'])/1e6)
    else:
        now = clock.sample()
        pair.publish('heartbeat', uuid.uuid4().hex, {'rows':[]}, now, now, now['utc_ns'])
    time.sleep(.025)


try:
    until = time.monotonic()+1.5
    while time.monotonic()<until:
        cycle()
    assert latest and fresh(latest, time.time_ns())
    for e in pair.engines.values():
        now = time.time_ns()
        e.transaction('SYNTHETIC_TEST_POSITION', now,
            lambda e=e, now=now: (e.risk(now,100000), e.fill(latest,-.001,now,'ENTRY')) and None)
    until = time.monotonic()+4
    while time.monotonic()<until:
        cycle()
        assert all(e.s['q']==-.001 and not e.s['pending'] for e in pair.engines.values())
    normal_retained = True
    pause.set()
    until = time.monotonic()+1.8
    while time.monotonic()<until:
        cycle(False)
    assert all(e.s['q']==-.001 and e.s['pending']['reason']=='STALE_DATA' for e in pair.engines.values())
    pause.clear()
    until = time.monotonic()+2
    while time.monotonic()<until:
        cycle(False)
    assert all(e.s['q']==0 and e.s['fills']==2 for e in pair.engines.values())
    assert not errors, errors
    values=sorted(latencies)
    result=dict(result='PASS',scope='SYNTHETIC_NETWORK_NONE_NO_LIVE_ACCOUNTS',normal_positions_retained=normal_retained,
                genuine_outage_still_protected=True,book_delivery_samples=len(values),
                book_receive_to_four_arm_completion_ms=dict(max=max(values),p50=values[len(values)//2],p95=values[int(len(values)*.95)]))
    (ROOT/'result.json').write_text(json.dumps(result,indent=2)+'\n')
    print(json.dumps(result),flush=True)
finally:
    stop.set()
    thread.join(10)
    pair.close()
