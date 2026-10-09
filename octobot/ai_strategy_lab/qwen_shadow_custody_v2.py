"""Independent capture/custody runtime candidate. No standing activation.
Card work-card-ef81ac4d-1ff5-4693-94ce-98228018e69a.
Public capture, writer and outcome stores have distinct OS owners at activation.
"""
import argparse
import datetime as dt
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import sqlite3
import ssl
import stat
import subprocess
import urllib.parse
import urllib.request

SPEC = importlib.util.spec_from_file_location('qwen_forward_core', Path(__file__).with_name('qwen_btc_shadow_forward_v2.py'))
p = importlib.util.module_from_spec(SPEC); SPEC.loader.exec_module(p)
ENDPOINT = 'https://api-futures.kucoin.com/api/v1/kline/query'
MAX_BYTES = 2000000
DAY = dt.timedelta(days=1)
ROLES = {'collect':30917, 'decide':30918, 'recover':30918, 'mature':30920, 'publish':30919}
BASE = Path('/srv/qwen-btc-shadow-v2')
APPROVAL = Path('/etc/qwen-btc-shadow-v2/activation.json')


def read_file(path, maximum=MAX_BYTES, owner=None):
    fd=os.open(path, os.O_RDONLY|os.O_NOFOLLOW)
    try:
        info=os.fstat(fd)
        if not stat.S_ISREG(info.st_mode) or info.st_size>maximum or (owner is not None and (info.st_uid!=owner or info.st_mode & 0o022)):
            raise ValueError('FILE_CUSTODY_INVALID')
        return os.read(fd, maximum+1)
    finally:os.close(fd)


def new_file(path, raw):
    """Never replace an acquisition/receipt; fsync both bytes and directory."""
    path=Path(path)
    fd=os.open(path, os.O_WRONLY|os.O_CREAT|os.O_EXCL|os.O_NOFOLLOW, 0o640)
    try:
        with os.fdopen(fd,'wb') as stream:
            stream.write(raw); stream.flush(); os.fsync(stream.fileno())
    except BaseException:
        # Partial bytes are evidence of a failed attempt, never cleaned for retry.
        raise
    directory=os.open(path.parent,os.O_RDONLY|os.O_DIRECTORY)
    try:os.fsync(directory)
    finally:os.close(directory)


def query_url(slot, started):
    t=p.slot_time(slot);s=p.utc(started)
    if not t<=s<=t+dt.timedelta(minutes=10):raise ValueError('COLLECTION_OUTSIDE_SLOT')
    return ENDPOINT+'?'+urllib.parse.urlencode({'symbol':'XBTUSDTM','granularity':1440,
        'from':int((t.replace(minute=0)-141*DAY).timestamp()*1000),'to':int(s.timestamp()*1000)})


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self,*args,**kwargs):raise ValueError('SOURCE_REDIRECT_DENIED')


def public_get(url):
    if urllib.parse.urlsplit(url)._replace(query='',fragment='').geturl()!=ENDPOINT:
        raise ValueError('SOURCE_ENDPOINT_INVALID')
    opener=urllib.request.build_opener(urllib.request.ProxyHandler({}),urllib.request.HTTPSHandler(context=ssl.create_default_context()),NoRedirect())
    request=urllib.request.Request(url,headers={'User-Agent':'qwen-btc-shadow-v2'},method='GET')
    with opener.open(request,timeout=15) as response:
        if response.status!=200 or response.geturl()!=url:raise ValueError('SOURCE_HTTP_INVALID')
        raw=response.read(MAX_BYTES+1)
        if len(raw)>MAX_BYTES:raise ValueError('SOURCE_TOO_LARGE')
        return raw


def rows(raw):
    doc=p.strict_json(raw)
    if not isinstance(doc,dict) or doc.get('code')!='200000' or not isinstance(doc.get('data'),list) or len(doc['data'])>1000:
        raise ValueError('SOURCE_SCHEMA_INVALID')
    bars=[]
    for row in doc['data']:
        if not isinstance(row,list) or len(row)!=7 or type(row[0]) is not int:raise ValueError('SOURCE_ROW_INVALID')
        bars.append([row[0], row[4]])
    bars.sort(key=lambda r:r[0])
    return bars


def collect(archive, slot, manifest, *, clock=p.now, fetch=public_get):
    p.check_manifest(manifest);t=p.slot_time(slot)
    if not p.utc(manifest['start_slot_utc'])<=t<=p.utc(manifest['end_slot_utc'])+DAY:raise ValueError('COLLECTION_WINDOW_INVALID')
    started=clock().isoformat();url=query_url(slot,started)
    archive=Path(archive);day=t.date().isoformat()
    # One public GET per day, reserved on disk before any network request.
    new_file(archive/(day+'.attempt.json'),p.canonical({'slot_utc':slot,'started_at':started,'lineage':manifest['lineage']}))
    raw=fetch(url);received=clock().isoformat()
    if not p.utc(started)<=p.utc(received)<=t+dt.timedelta(minutes=10):raise ValueError('LATE_ACQUISITION')
    parsed=rows(raw)
    # Validate source before accepting a receipt (extra final-day capture is not a decision).
    decision_slot=min(t,p.utc(manifest['end_slot_utc'])).isoformat()
    if t<=p.utc(manifest['end_slot_utc']):p.observation(parsed,decision_slot,received,manifest)
    digest=hashlib.sha256(raw).hexdigest()
    new_file(archive/(day+'.raw.json'),raw)
    receipt={'schema_version':2,'scope':p.SCOPE,'lineage':manifest['lineage'],'slot_utc':t.isoformat(),
             'started_at':started,'received_at':received,'request_url':url,'raw_sha256':digest}
    new_file(archive/(day+'.receipt.json'),p.canonical(receipt))
    return receipt


def capture(archive, slot, manifest, *, owner=None):
    t=p.slot_time(slot);day=t.date().isoformat();archive=Path(archive)
    receipt=p.strict_json(read_file(archive/(day+'.receipt.json'),8192,owner))
    expected={'schema_version','scope','lineage','slot_utc','started_at','received_at','request_url','raw_sha256'}
    if set(receipt)!=expected or receipt['schema_version']!=2 or receipt['scope']!=p.SCOPE or receipt['lineage']!=manifest['lineage'] or receipt['slot_utc']!=t.isoformat():raise ValueError('RECEIPT_IDENTITY_INVALID')
    if receipt['request_url']!=query_url(slot,receipt['started_at']) or not p.utc(receipt['started_at'])<=p.utc(receipt['received_at'])<=t+dt.timedelta(minutes=10):raise ValueError('RECEIPT_TIME_INVALID')
    raw=read_file(archive/(day+'.raw.json'),MAX_BYTES,owner)
    if hashlib.sha256(raw).hexdigest()!=receipt['raw_sha256']:raise ValueError('RAW_HASH_INVALID')
    return receipt,rows(raw)


def bind_provenance(database, source, receipt, manifest):
    con=p.connect(database,manifest)
    try:
        con.execute('CREATE TABLE IF NOT EXISTS provenance(slot TEXT PRIMARY KEY,receipt TEXT NOT NULL)')
        for action in ('UPDATE','DELETE'):
            con.execute(f"CREATE TRIGGER IF NOT EXISTS no_{action.lower()}_provenance BEFORE {action} ON provenance BEGIN SELECT RAISE(ABORT,'APPEND_ONLY'); END")
        con.execute('BEGIN IMMEDIATE')
        old=con.execute('SELECT receipt FROM provenance WHERE slot=?',(source['slot_utc'],)).fetchone()
        encoded=p.canonical(receipt).decode()
        if old and old[0]!=encoded:raise ValueError('PROVENANCE_CONFLICT')
        con.execute('INSERT OR IGNORE INTO provenance VALUES(?,?)',(source['slot_utc'],encoded));con.commit()
    finally:con.close()


def decide(archive, database, slot, manifest, *, clock=p.now, reader=p.local_json, owner=None):
    t=p.slot_time(slot)
    if clock()<t:raise ValueError('DECISION_BEFORE_SLOT')
    if clock()>t+dt.timedelta(minutes=10):return p.recover_slot(slot,manifest,database,clock)
    try:
        receipt,bars=capture(archive,slot,manifest,owner=owner)
        if p.utc(receipt['received_at'])>clock():raise ValueError('SOURCE_NOT_YET_RECEIVED')
        source=p.observation(bars,slot,receipt['received_at'],manifest)
    except (OSError,ValueError,KeyError,TypeError):
        return p.record_missing(slot,manifest,database,'SOURCE_FAILURE',clock)
    bind_provenance(database,source,receipt,manifest)
    return p.run(source,manifest,database,reader,clock)


def sources(database, manifest):
    records=p.inspect_journal(database)
    with sqlite3.connect(Path(database).resolve().as_uri()+'?mode=ro',uri=True) as con:
        stored=p.strict_json(con.execute('SELECT manifest FROM metadata WHERE id=1').fetchone()[0])
        if stored!=manifest:raise ValueError('JOURNAL_MANIFEST_MISMATCH')
        result={s:p.strict_json(raw) for s,raw in con.execute('SELECT slot,observation FROM attempts')}
    if len(result)>180:raise ValueError('JOURNAL_WINDOW_INVALID')
    for slot,source in result.items():
        t=p.slot_time(slot)
        if not p.utc(manifest['start_slot_utc'])<=t<=p.utc(manifest['end_slot_utc']):raise ValueError('JOURNAL_WINDOW_INVALID')
        if 'causal_bars' in source:p.check_observation(source,manifest)
        elif source.get('lineage')!=manifest['lineage'] or source.get('observation_id')!=p.sha({k:v for k,v in source.items() if k!='observation_id'}):raise ValueError('MISSING_IDENTITY_INVALID')
    for record in records:
        source=result.get(record['slot_utc'])
        if not source or record['scope']!=p.SCOPE or record['lineage']!=manifest['lineage'] or record['observation_id']!=source['observation_id'] or record['arm'] not in ('baseline','qwen'):raise ValueError('RECORD_IDENTITY_INVALID')
        if record['result']['decision']!='MISSING':
            p.output(p.canonical(record['result']));t=p.slot_time(record['slot_utc'])
            if not t<=p.utc(record['recorded_at'])<=t+dt.timedelta(minutes=10):raise ValueError('RECORD_TIME_INVALID')
            if record['arm']=='baseline' and record['result']!=p.baseline(source):raise ValueError('BASELINE_INVALID')
    return result,records


def outcome_connect(path, manifest):
    path=Path(path)
    if path.name!='outcomes.sqlite' or path.is_symlink():raise ValueError('OUTCOME_STORE_INVALID')
    if path.exists():
        with sqlite3.connect(path.resolve().as_uri()+'?mode=ro',uri=True) as old:
            if old.execute('SELECT manifest FROM metadata').fetchone()[0]!=p.canonical(manifest).decode():raise ValueError('OUTCOME_MANIFEST_INVALID')
    con=sqlite3.connect(path,timeout=5);con.execute('PRAGMA synchronous=FULL')
    con.executescript('CREATE TABLE IF NOT EXISTS metadata(id INTEGER PRIMARY KEY CHECK(id=1),manifest TEXT NOT NULL); CREATE TABLE IF NOT EXISTS outcomes(slot TEXT PRIMARY KEY,payload TEXT NOT NULL,previous_hash TEXT NOT NULL,record_hash TEXT NOT NULL);')
    for table in ('metadata','outcomes'):
        for action in ('UPDATE','DELETE'):
            con.execute(f"CREATE TRIGGER IF NOT EXISTS no_{action.lower()}_{table} BEFORE {action} ON {table} BEGIN SELECT RAISE(ABORT,'APPEND_ONLY'); END")
    con.execute('INSERT OR IGNORE INTO metadata VALUES(1,?)',(p.canonical(manifest).decode(),));con.commit();return con


def mature(archive, database, outcomes, slot, manifest, *, clock=p.now, owner=None):
    """An outcome uses only its next day's capture; missing stays missing."""
    p.check_manifest(manifest);t=p.slot_time(slot);current=t+DAY
    if clock()<current:raise ValueError('OUTCOME_BEFORE_MATURITY')
    original,_=sources(database,manifest);source=original.get(t.isoformat())
    if source is None:raise ValueError('DECISION_SLOT_NOT_RECORDED')
    value={'slot_utc':t.isoformat(),'lineage':manifest['lineage'],'observation_id':source['observation_id'],
           'status':'MISSING','origin_close':None,'next_close':None,'receipt':None,'recorded_at':clock().isoformat()}
    try:
        if clock()>current+dt.timedelta(minutes=20):raise ValueError('OUTCOME_ACQUISITION_MISSED')
        receipt,bars=capture(archive,current.isoformat(),manifest,owner=owner)
        if p.utc(receipt['received_at'])>clock():raise ValueError('OUTCOME_NOT_RECEIVED')
        if 'causal_bars' not in source:raise ValueError('ORIGIN_MISSING')
        target=source['causal_bars'][-1][0]+p.DAY_MS
        # Canonical source validation also validates the single outcome close numerically.
        selected=[r for r in bars if r[0]==target]
        if len(selected)!=1:raise ValueError('OUTCOME_BAR_MISSING')
        from decimal import Decimal
        close=Decimal(str(selected[0][1]))
        if not close.is_finite() or not Decimal('1e-12')<=close<Decimal('1e15'):raise ValueError('OUTCOME_CLOSE_INVALID')
        value.update(status='AVAILABLE',origin_close=source['causal_bars'][-1][1],next_close=str(close),receipt=receipt)
    except (OSError,ValueError,TypeError,KeyError):pass
    con=outcome_connect(outcomes,manifest)
    try:
        con.execute('BEGIN IMMEDIATE')
        if con.execute('SELECT 1 FROM outcomes WHERE slot=?',(t.isoformat(),)).fetchone():return {'status':'OUTCOME_REPLAY_PRESERVED'}
        last=con.execute('SELECT record_hash FROM outcomes ORDER BY rowid DESC LIMIT 1').fetchone();previous=last[0] if last else '0'*64
        con.execute('INSERT INTO outcomes VALUES(?,?,?,?)',(t.isoformat(),p.canonical(value).decode(),previous,p.sha({'payload':value,'previous_hash':previous})));con.commit()
        return {'status':value['status']}
    finally:con.close()


def approved(mode, manifest, *, path=APPROVAL):
    """No issuer grant. Root-owned human decision, exact bundle and fixed roles."""
    value=p.strict_json(read_file(path,16384,0))
    if (set(value)!={'status','manifest_sha256','lineage','public_gets_authorized','approved_at','bundle_sha256'} or
        value['status']!='APPROVED_SHADOW_FORWARD_ONLY' or value['public_gets_authorized'] is not True or
        value['manifest_sha256']!=p.sha(manifest) or value['lineage']!=manifest['lineage'] or
        p.utc(value['approved_at'])>=p.utc(manifest['start_slot_utc'])):raise ValueError('FORWARD_APPROVAL_REQUIRED')
    if os.geteuid()!=ROLES[mode]:raise ValueError('ROLE_UID_INVALID')
    p.check_manifest(manifest)
    import sys,platform,decimal,random,_sqlite3,_decimal,_ssl
    lock=p.strict_json(read_file(Path(__file__).with_name('bundle.json'),100000,0))
    if p.sha(lock)!=value['bundle_sha256'] or lock['manifest_sha256']!=p.sha(manifest):raise ValueError('BUNDLE_BINDING_INVALID')
    environment=lock['environment']
    if (environment['python_version']!=sys.version or environment['architecture']!=platform.machine() or
        environment['sqlite_version']!=sqlite3.sqlite_version or environment['openssl']!=ssl.OPENSSL_VERSION or
        environment['python_sha256']!=hashlib.sha256(Path(sys.executable).read_bytes()).hexdigest()):raise ValueError('RUNTIME_CHANGED')
    modules={'decimal':decimal,'random':random,'sqlite3':sqlite3,'ssl':ssl,'_sqlite3':_sqlite3,'_decimal':_decimal,'_ssl':_ssl}
    for name,digest in environment['module_sha256'].items():
        if hashlib.sha256(Path(modules[name].__file__).read_bytes()).hexdigest()!=digest:raise ValueError('LIBRARY_CHANGED')
    for name,digest in lock['files'].items():
        if '/' in name or name in ('.','..'):raise ValueError('BUNDLE_PATH_INVALID')
        if hashlib.sha256(read_file(Path(__file__).with_name(name),2000000,0)).hexdigest()!=digest:raise ValueError('BUNDLE_FILE_CHANGED')
    clock=subprocess.run(['/usr/bin/timedatectl','show','-p','NTPSynchronized','--value'],capture_output=True,text=True,timeout=5)
    if clock.returncode or clock.stdout.strip()!='yes':raise ValueError('CLOCK_UNSYNCHRONIZED')
    return value


def validate_directories(mode):
    info=BASE.lstat()
    if not stat.S_ISDIR(info.st_mode) or info.st_uid!=0 or info.st_mode&0o022:raise ValueError('CUSTODY_ROOT_INVALID')
    for name,uid,gid in [('archive',30917,30922),('journal',30918,30921),('outcomes',30920,30923),('published',30919,30919)]:
        visible={'collect':{'archive'},'decide':{'archive','journal'},'recover':{'archive','journal'},'mature':{'archive','journal','outcomes'},'publish':{'journal','outcomes','published'}}
        if name not in visible[mode]:continue
        info=(BASE/name).lstat()
        if not stat.S_ISDIR(info.st_mode) or info.st_uid!=uid or info.st_gid!=gid or info.st_mode&0o022:raise ValueError('CUSTODY_ROLE_INVALID')


def main():
    parser=argparse.ArgumentParser();parser.add_argument('mode',choices=('collect','decide','recover','mature'));args=parser.parse_args()
    manifest=p.strict_json(read_file(Path(__file__).with_name('manifest.json'),100000,0));approved(args.mode,manifest);validate_directories(args.mode)
    archive=BASE/'archive';database=BASE/'journal'/'shadow-forward.sqlite';outcomes=BASE/'outcomes'/'outcomes.sqlite'
    current=p.now().replace(hour=0,minute=10,second=0,microsecond=0);start=p.utc(manifest['start_slot_utc']);end=p.utc(manifest['end_slot_utc'])
    if args.mode=='collect':result=collect(archive,current.isoformat(),manifest)
    elif args.mode=='decide':result=decide(archive,database,current.isoformat(),manifest,owner=30917)
    elif args.mode=='recover':
        result=[]
        for i in range(180):
            slot=start+i*DAY
            if slot+dt.timedelta(minutes=10)<p.now():result.append(p.recover_slot(slot.isoformat(),manifest,database))
    else:
        prior=current-DAY
        if not start<=prior<=end:return
        result=mature(archive,database,outcomes,prior.isoformat(),manifest,owner=30917)
    print(json.dumps(result))


if __name__=='__main__':main()
