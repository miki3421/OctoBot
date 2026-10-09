"""Read-only, closed projection for the independent Qwen shadow page.
Card work-card-a21f31fc-0da2-42bd-afdb-5894516fa76d.
Only a published status file is accessible to the web process, never journals.
"""
import datetime as dt
import json
import os
from pathlib import Path
import re
import stat

UTC=dt.timezone.utc
STATES={'PENDING','LONG','SHORT','NO_PROPOSAL','MISSING','UNRECORDED','RESERVED'}
KEYS={'schema_version','experiment_id','scope','phase','generated_at','start_slot_utc','end_slot_utc','review_at',
      'lineage','bundle_sha256','recorded_pairs','expected','mature_outcomes','conflicts','integrity','calendar',
      'performance_sealed','scheduler_active','issues','decisions_pending','model','timeout_seconds'}
REASONS={'SOURCE_INPUT_INVALID','SOURCE_NOT_AVAILABLE_IN_SLOT','NONCONTIGUOUS_BARS','INSUFFICIENT_OR_STALE_DATA',
    'SLOT_DEADLINE_MISSED','SOURCE_FAILURE','PROCESS_INTERRUPTED','LATE_MODEL_RESPONSE','MODEL_IDENTITY_MISMATCH',
    'MODEL_BUSY','MODEL_UNAVAILABLE','OUTPUT_SCHEMA_INVALID','OUTPUT_SEMANTICS_INVALID','OUTPUT_INCOMPLETE',
    'DUPLICATE_JSON_KEY','MODEL_RESPONSE_INVALID','TREND_UP','TREND_DOWN','MIXED','UNCERTAIN'}
ISSUES={'FORWARD_NOT_ACTIVE','MONITOR_STALE','JOURNAL_UNAVAILABLE','UNRECORDED_SLOTS','SOURCE_CONFLICT','CLOCK_UNSYNCHRONIZED','SCHEDULER_INACTIVE','SERVICE_FAILURE'}
DECISIONS={'PROTOCOL_AND_THRESHOLDS','FROZEN_BUNDLE_AND_CALENDAR','INDEPENDENT_PUBLIC_GETS','FORWARD_ACTIVATION'}
MODEL='Qwen3.6-35B-A3B UD-Q4_K_XL'


def instant(v):
    t=dt.datetime.fromisoformat(v.replace('Z','+00:00'))
    if t.tzinfo is None or t.utcoffset()!=dt.timedelta(0):raise ValueError('UTC_REQUIRED')
    return t


def validate(v, *, now=None):
    now=now or dt.datetime.now(UTC)
    if set(v)!=KEYS or v['schema_version']!=2 or v['experiment_id']!='qwen-btc-direction-shadow-v1' or v['scope']!='FORWARD_SHADOW_RESEARCH_ONLY':raise ValueError('PUBLIC_SCHEMA_INVALID')
    if v['phase'] not in {'PREPARED','WAITING','COLLECTING','MATURING','REVIEW_DUE','ATTENTION'} or v['model']!=MODEL or v['timeout_seconds']!=35:raise ValueError('PUBLIC_SCHEMA_INVALID')
    if v['performance_sealed'] is not True or type(v['scheduler_active']) is not bool:raise ValueError('NO_PERFORMANCE_ALLOWED')
    if any(not isinstance(v[k],str) or not re.fullmatch('[0-9a-f]{64}',v[k]) for k in ('lineage','bundle_sha256')):raise ValueError('HASH_INVALID')
    start=instant(v['start_slot_utc']);end=instant(v['end_slot_utc']);review=instant(v['review_at']);generated=instant(v['generated_at'])
    if end!=start+dt.timedelta(days=179) or review!=start+dt.timedelta(days=181,minutes=20) or (start.hour,start.minute,start.second,start.microsecond)!=(0,10,0,0):raise ValueError('CALENDAR_INVALID')
    if generated>now+dt.timedelta(seconds=5):raise ValueError('STATUS_FROM_FUTURE')
    if v['integrity'] not in {'NOT_STARTED','OK','UNAVAILABLE'}:raise ValueError('INTEGRITY_INVALID')
    for k in ('recorded_pairs','expected','mature_outcomes','conflicts'):
        if type(v[k]) is not int or not 0<=v[k]<=180:raise ValueError('COUNT_INVALID')
    if not isinstance(v['issues'],list) or any(i not in ISSUES for i in v['issues']):raise ValueError('ISSUES_INVALID')
    if not isinstance(v['decisions_pending'],list) or any(i not in DECISIONS for i in v['decisions_pending']):raise ValueError('DECISIONS_INVALID')
    if not isinstance(v['calendar'],list) or len(v['calendar'])!=180:raise ValueError('CALENDAR_INVALID')
    for i,row in enumerate(v['calendar']):
        if set(row)!={'slot_utc','baseline','qwen','mature'} or instant(row['slot_utc'])!=start+dt.timedelta(days=i) or type(row['mature']) is not bool:raise ValueError('ROW_INVALID')
        for arm in ('baseline','qwen'):
            a=row[arm]
            if set(a)!={'state','reason_codes','latency_seconds'} or a['state'] not in STATES or not isinstance(a['reason_codes'],list) or any(c not in REASONS for c in a['reason_codes']):raise ValueError('ARM_INVALID')
            latency=a['latency_seconds']
            if latency is not None and (type(latency) not in (int,float) or not 0<=latency<=60):raise ValueError('LATENCY_INVALID')
    count=sum(all(row[a]['state'] in {'LONG','SHORT','NO_PROPOSAL','MISSING'} for a in ('baseline','qwen')) for row in v['calendar'])
    if count!=v['recorded_pairs'] or sum(r['mature'] for r in v['calendar'])!=v['mature_outcomes']:raise ValueError('COUNTS_DISAGREE')
    if v['phase']=='PREPARED':
        if v['scheduler_active'] or any(v[k] for k in ('recorded_pairs','expected','mature_outcomes','conflicts')) or v['integrity']!='NOT_STARTED' or set(v['decisions_pending'])!=DECISIONS or any(r[a]['state']!='PENDING' for r in v['calendar'] for a in ('baseline','qwen')):raise ValueError('PREPARED_STATUS_INVALID')
    elif (now-generated).total_seconds()>180:
        v={**v,'phase':'ATTENTION','issues':['MONITOR_STALE']}
    return v


def public_view(path=Path('/qwen-shadow-status/status.json'),*,now=None):
    fd=os.open(path,os.O_RDONLY|os.O_NOFOLLOW)
    try:
        info=os.fstat(fd)
        if not stat.S_ISREG(info.st_mode) or info.st_uid not in (0,30919) or info.st_mode&0o022 or info.st_size>150000:raise ValueError('PUBLIC_FILE_INVALID')
        raw=os.read(fd,150001)
    finally:os.close(fd)
    def pairs(items):
        v={}
        for k,x in items:
            if k in v:raise ValueError('DUPLICATE_KEY')
            v[k]=x
        return v
    return validate(json.loads(raw,object_pairs_hook=pairs),now=now)


def prepared(manifest,bundle_sha256,generated_at):
    start=instant(manifest['start_slot_utc'])
    def pending():return {'state':'PENDING','reason_codes':[],'latency_seconds':None}
    return validate({'schema_version':2,'experiment_id':manifest['experiment_id'],'scope':manifest['scope'],
        'phase':'PREPARED','generated_at':generated_at,'start_slot_utc':manifest['start_slot_utc'],
        'end_slot_utc':manifest['end_slot_utc'],'review_at':manifest['review_at'],'lineage':manifest['lineage'],
        'bundle_sha256':bundle_sha256,'recorded_pairs':0,'expected':0,'mature_outcomes':0,'conflicts':0,
        'integrity':'NOT_STARTED','calendar':[{'slot_utc':(start+dt.timedelta(days=i)).isoformat(),
            'baseline':pending(),'qwen':pending(),'mature':False} for i in range(180)],
        'performance_sealed':True,'scheduler_active':False,'issues':['FORWARD_NOT_ACTIVE'],
        'decisions_pending':sorted(DECISIONS),'model':MODEL,'timeout_seconds':35},now=instant(generated_at))
