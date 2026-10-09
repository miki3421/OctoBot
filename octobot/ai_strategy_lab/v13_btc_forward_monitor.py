"""Operational-only BTC forward publication. Never computes/exposes performance.
Work card: work-card-6f6c941d-0798-4054-a7f4-36096a43c31f.
"""
import argparse
import datetime as dt
import hashlib
import json
import os
from pathlib import Path
import sqlite3
import stat
import subprocess
import tempfile

UTC=dt.timezone.utc
DAY=dt.timedelta(days=1)
STATES={'LONG','SHORT','NO_PROPOSAL','MISSING'}
ROLES=('collector','finalizer','recover','mature')
SCOPE='FORWARD_RESEARCH_ONLY'
REASONS={'LONG':{'DUAL_MOMENTUM_POSITIVE'},'SHORT':{'DUAL_MOMENTUM_NEGATIVE'},'NO_PROPOSAL':{'MOMENTUM_DISAGREEMENT_OR_ZERO'},'MISSING':{'DATA_NOT_AVAILABLE','STALE_DATA','NONCONTIGUOUS_BARS','LATE_ACQUISITION','SOURCE_FAILURE','INTEGRITY_FAILURE'}}
PUBLIC_KEYS={'schema_version','scope','generated_at','start_slot_utc','end_slot_utc','review_at','phase','recorded','expected','mature_outcomes','counts','overdue','conflicts','integrity','clock_synchronized','timers','services','calendar','issues','performance_sealed','next_slot_utc'}


def canonical(v):return json.dumps(v,sort_keys=True,separators=(',',':'),ensure_ascii=False,allow_nan=False).encode()
def sha(v):return hashlib.sha256(canonical(v)).hexdigest()
def instant(v):
    t=dt.datetime.fromisoformat(v.replace('Z','+00:00'))
    if t.tzinfo is None or t.utcoffset()!=dt.timedelta(0):raise ValueError('utc_required')
    return t


def approved(path):
    fd=os.open(path,os.O_RDONLY|os.O_NOFOLLOW)
    try:
        info=os.fstat(fd)
        if info.st_uid!=0 or info.st_mode & 0o022 or not stat.S_ISREG(info.st_mode) or info.st_size>8192:raise ValueError('approval_invalid')
        data=os.read(fd,8193);v=json.loads(data)
    finally:os.close(fd)
    if v['status']!='APPROVED_FORWARD_RESEARCH_ONLY':raise ValueError('approval_missing')
    a,b=instant(v['start_slot_utc']),instant(v['end_slot_utc'])
    if b-a!=179*DAY or (a.hour,a.minute,a.second,a.microsecond)!=(0,10,0,0):raise ValueError('window_invalid')
    return v,a,b


def read_journal(path,start,end,now):
    records={};counts={k:0 for k in sorted(STATES)};outcomes=0;conflicts=0
    if path.exists():
        info=path.lstat()
        if not stat.S_ISREG(info.st_mode) or info.st_uid!=30041 or info.st_mode & 0o022:raise ValueError('journal_ownership_invalid')
        def read(uri):
            with sqlite3.connect(uri,uri=True,timeout=2) as db:
                db.execute('BEGIN')
                if db.execute('PRAGMA quick_check').fetchone()[0]!='ok':raise ValueError('journal_invalid')
                rows=db.execute('SELECT slot_utc,decision_id,decision_json,provenance_json,recorded_at,previous_hash,record_hash FROM slots ORDER BY rowid').fetchall()
                if len(rows)>180:raise ValueError('window_overflow')
                mature=db.execute('SELECT slot_utc FROM outcomes').fetchall()
                incidents=db.execute('SELECT count(*) FROM conflicts').fetchone()[0]
                return rows,mature,incidents
        try:rows,mature,conflicts=read('file:'+str(path)+'?mode=ro')
        except sqlite3.OperationalError:
            if Path(str(path)+'-wal').exists():raise
            rows,mature,conflicts=read('file:'+str(path)+'?mode=ro&immutable=1')
        previous=None
        for slot,decision_id,raw,provenance,recorded_at,parent,digest in rows:
            d=json.loads(raw);source=json.loads(provenance) if provenance else None;t=instant(slot);recorded=instant(recorded_at)
            if (not start<=t<=end or (t-start).total_seconds()%86400 or slot in records or recorded>now+dt.timedelta(seconds=5)
                    or parent!=previous or sha({'decision':d,'provenance':source,'recorded_at':recorded_at,'previous_hash':parent})!=digest
                    or d['decision_id']!=decision_id or sha({k:v for k,v in d.items() if k!='decision_id'})!=decision_id
                    or d.get('slot_utc')!=slot or d.get('research_only') is not True or d.get('execution_approved') is not False
                    or d.get('experiment_id')!='v13-btc-paper-new-v1' or d.get('status') not in STATES
                    or d.get('lineage')!='29ae069f52b7cb820fb54476d5e47e094ac1174a98186da9ada107e728a2efb7'
                    or d.get('reason_code') not in REASONS.get(d.get('status'),set())):raise ValueError('journal_chain_invalid')
            if recorded<t or (d['status']=='MISSING' and recorded<t+dt.timedelta(minutes=10)) or (d['status']!='MISSING' and recorded>t+dt.timedelta(minutes=10)):raise ValueError('journal_time_invalid')
            previous=digest;counts[d['status']]+=1
            records[slot]={'state':d['status'],'reason':str(d['reason_code']),'recorded_at':recorded_at}
        for (slot,) in mature:
            if slot not in records or records[slot]['state'] not in ('LONG','SHORT') or instant(slot)+DAY>now:raise ValueError('outcome_slot_invalid')
        outcomes=len(mature)
    calendar=[];expected=overdue=0
    for day in range(180):
        t=start+day*DAY;key=t.isoformat();due=now>=t+dt.timedelta(minutes=10);expected+=int(due)
        rec=records.get(key)
        if due and rec is None:overdue+=1
        calendar.append({'slot_utc':key,**(rec or {'state':'UNRECORDED' if due else 'PENDING','reason':None,'recorded_at':None})})
    return {'recorded':len(records),'expected':expected,'overdue':overdue,'mature_outcomes':outcomes,'counts':counts,'conflicts':conflicts,'integrity':'ok','calendar':calendar}


def system_status():
    timers={};services={}
    for role in ROLES:
        name='v13-btc-forward-'+role
        def show(suffix,keys):
            proc=subprocess.run(['/usr/bin/systemctl','show',name+suffix,*['--property='+k for k in keys]],capture_output=True,text=True,timeout=5)
            if proc.returncode:raise ValueError('system_status_unavailable')
            data=dict(line.split('=',1) for line in proc.stdout.splitlines() if '=' in line)
            return {k:data.get(k,'') for k in keys}
        timers[role]=show('.timer',['ActiveState','UnitFileState','NextElapseUSecRealtime','LastTriggerUSec'])
        services[role]=show('.service',['ActiveState','Result','ExecMainStatus','ExecMainExitTimestamp'])
    clock=subprocess.run(['/usr/bin/timedatectl','show','-p','NTPSynchronized','--value'],capture_output=True,text=True,timeout=5)
    return timers,services,clock.returncode==0 and clock.stdout.strip()=='yes'


def build(activation,journal,now,*,system=None):
    v,start,end=approved(activation)
    if str(journal)!=v['journal_path']:raise ValueError('journal_path_mismatch')
    timers,services,clock=(system or system_status)()
    issues=[]
    try:data=read_journal(journal,start,end,now)
    except (OSError,sqlite3.Error,ValueError,KeyError,TypeError):
        data={'recorded':0,'expected':0,'overdue':0,'mature_outcomes':0,'counts':{k:0 for k in sorted(STATES)},'conflicts':0,'integrity':'unavailable','calendar':[]};issues.append('JOURNAL_UNAVAILABLE')
    if data['overdue']:issues.append('UNRECORDED_SLOTS')
    if data['conflicts']:issues.append('SOURCE_CONFLICT')
    if not clock:issues.append('CLOCK_UNSYNCHRONIZED')
    if now<=end+DAY:
        if any(v['ActiveState']!='active' or v['UnitFileState']!='enabled' for v in timers.values()):issues.append('SCHEDULER_INACTIVE')
    if any(v.get('Result') not in ('','success') for v in services.values()):issues.append('SERVICE_FAILURE')
    phase='waiting' if now<start else 'collecting' if now<=end+dt.timedelta(minutes=10) else 'maturing' if now<start+181*DAY else 'review'
    next_slot=next((r['slot_utc'] for r in data['calendar'] if instant(r['slot_utc'])>now),None)
    return {'schema_version':1,'scope':SCOPE,'generated_at':now.isoformat(),'start_slot_utc':start.isoformat(),'end_slot_utc':end.isoformat(),'review_at':(start+181*DAY).isoformat(),'phase':'attention' if issues else phase,**data,'clock_synchronized':clock,'timers':timers,'services':services,'issues':issues,'performance_sealed':now<start+181*DAY,'next_slot_utc':next_slot}


def publish(path,value):
    payload=canonical(value)+b'\n';tmp=None
    try:
        with tempfile.NamedTemporaryFile(dir=path.parent,prefix='.status-',delete=False) as f:
            tmp=Path(f.name);f.write(payload);f.flush();os.fchmod(f.fileno(),0o640);os.fsync(f.fileno())
        os.replace(tmp,path);tmp=None
        fd=os.open(path.parent,os.O_RDONLY|os.O_DIRECTORY)
        try:os.fsync(fd)
        finally:os.close(fd)
    finally:
        if tmp is not None:tmp.unlink(missing_ok=True)


def public_view(path=Path('/btc-research-status/status.json'),*,now=None):
    now=now or dt.datetime.now(UTC)
    fd=os.open(path,os.O_RDONLY|os.O_NOFOLLOW)
    try:
        info=os.fstat(fd)
        if info.st_uid!=30041 or info.st_mode & 0o022 or not stat.S_ISREG(info.st_mode) or info.st_size>150000:raise ValueError('snapshot_invalid')
        v=json.loads(os.read(fd,150001))
    finally:os.close(fd)
    if set(v)!=PUBLIC_KEYS or v['scope']!=SCOPE or v['schema_version']!=1:raise ValueError('snapshot_schema_invalid')
    # Nested fields also have closed schemas; never publish future payload additions.
    if set(v['counts'])!=STATES or set(v['timers'])!=set(ROLES) or set(v['services'])!=set(ROLES):raise ValueError('snapshot_schema_invalid')
    if any(set(r)!={'slot_utc','state','reason','recorded_at'} for r in v['calendar']):raise ValueError('snapshot_schema_invalid')
    if any(set(t)!={'ActiveState','UnitFileState','NextElapseUSecRealtime','LastTriggerUSec'} for t in v['timers'].values()):raise ValueError('snapshot_schema_invalid')
    if any(set(s)!={'ActiveState','Result','ExecMainStatus','ExecMainExitTimestamp'} for s in v['services'].values()):raise ValueError('snapshot_schema_invalid')
    if len(v['calendar']) not in (0,180) or any(r['state'] not in STATES|{'PENDING','UNRECORDED'} for r in v['calendar']):raise ValueError('snapshot_schema_invalid')
    if v['phase'] not in {'waiting','collecting','maturing','review','attention'} or type(v['performance_sealed']) is not bool:raise ValueError('snapshot_schema_invalid')
    if any(type(v[k]) is not int or not 0<=v[k]<=180 for k in ('recorded','expected','mature_outcomes','overdue')):raise ValueError('snapshot_schema_invalid')
    if any(type(c) is not int or not 0<=c<=180 for c in v['counts'].values()) or sum(v['counts'].values())!=v['recorded']:raise ValueError('snapshot_schema_invalid')
    age=(now-instant(v['generated_at'])).total_seconds()
    if age< -5:raise ValueError('snapshot_future')
    if age>180:v['phase']='attention';v['issues']=['MONITOR_STALE']
    return v


if __name__=='__main__':
    args=argparse.ArgumentParser();args.add_argument('--activation',type=Path,required=True);args.add_argument('--journal',type=Path,required=True);args.add_argument('--output',type=Path,required=True);args=args.parse_args()
    if os.geteuid()!=30041:raise ValueError('monitor_uid_mismatch')
    publish(args.output,build(args.activation,args.journal,dt.datetime.now(UTC)))
