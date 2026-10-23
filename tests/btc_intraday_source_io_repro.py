"""Offline writer/RO-reader rendezvous, never mount the live collector here."""
import json,os,sqlite3,sys,time
from pathlib import Path
mode=sys.argv[1];root=Path('/fixture');out=Path('/out')
def wait(path):
    end=time.monotonic()+40
    while not path.exists():
        if time.monotonic()>end:raise TimeoutError(path.name)
        time.sleep(.02)
def row(identity):
    now=time.time_ns();v=dict(id=identity,session_id='fixture',received_ts_ns=now,exchange_ts_ns=now-10000000,payload_sha256='a'*64)
    for side in ('bid','ask'):
        for i in range(1,6):v[f'{side}_price_{i}']=100000-i if side=='bid' else 100000+i;v[f'{side}_size_{i}']=100.
    return v
if mode=='writer':
    db=sqlite3.connect(root/'book.sqlite');db.execute('PRAGMA journal_mode=WAL')
    first=row(1);columns={k:'INTEGER' if isinstance(v,int) else 'REAL' if isinstance(v,float) else 'TEXT' for k,v in first.items()};columns['id']='INTEGER PRIMARY KEY'
    db.execute('CREATE TABLE book_events('+','.join(k+' '+v for k,v in columns.items())+')')
    def insert(db,v):db.execute('INSERT INTO book_events('+','.join(v)+') VALUES('+','.join('?' for k in v)+')',tuple(v.values()));db.commit()
    insert(db,first);(root/'ready').write_text('ready');wait(root/'close');db.close();(root/'closed').write_text('closed')
    wait(root/'reopen');db=sqlite3.connect(root/'book.sqlite');insert(db,row(2));(root/'reopened').write_text('reopened');wait(root/'release');db.close()
else:
    sys.path[:0]=['/runtime','/runtime/frozen']
    import btc_intraday_availability as receipts
    from btc_intraday_source_io import RecoveringBookReader,append_event
    clock=receipts.Clock();events=[];witness=receipts.Witness(out/'receipts',clock)
    def record(v):events.append(v);append_event(out/'io.jsonl',v)
    reader=RecoveringBookReader(root/'book.sqlite',clock,record);assert reader.poll() is None and reader.cursor==1
    pid=os.getpid();(out/'reader-ready').write_text('ready')
    end=time.monotonic()+40
    while time.monotonic()<end:
        result=reader.poll()
        if reader.state=='WAITING_SOURCE':(out/'waiting').touch()
        if result:
            payload,start,finish=result;assert [r['id'] for r in payload['rows']]==[2] and reader.cursor==1
            try:
                data,_=witness.observe('book','2:2',payload,start,finish,payload['rows'][-1]['received_ts_ns'])
                proof=witness.available_now(data,clock.sample()['utc_ns']+1000000000)
                assert proof['scope']=='INPUT_AVAILABILITY_ONLY_NO_ORDER_AUTHORIZATION'
                reader.cursor=2
            finally:witness.close()
            result=dict(sqlite=sqlite3.sqlite_version,pid_unchanged=os.getpid()==pid,cursor=reader.cursor,events=[v['event'] for v in events],codes=[v.get('sqlite_errorcode') for v in events],persisted_before_cursor=True,read_only_source=True)
            assert result['events']==['BOOK_READ_WAIT','BOOK_READ_RECOVERED'];(out/'result.json').write_text(json.dumps(result,indent=2));print(json.dumps(result));break
        time.sleep(.02)
    else:raise TimeoutError('reader recovery')
