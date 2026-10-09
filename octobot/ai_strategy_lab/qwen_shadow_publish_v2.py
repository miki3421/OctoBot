"""Operational projection only. Model/output stores never mounted in the UI.
Card work-card-ef81ac4d-1ff5-4693-94ce-98228018e69a.
"""
import importlib.util
import os
from pathlib import Path
import sqlite3
import tempfile


def load(name):
    spec=importlib.util.spec_from_file_location(name,Path(__file__).with_name(name+'.py'))
    module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module);return module

c=load('qwen_shadow_custody_v2');v=load('qwen_shadow_view');p=c.p


def build(manifest,bundle_sha256,journal,outcomes,*,clock=p.now,scheduler_active=False):
    now=clock();value=v.prepared(manifest,bundle_sha256,now.isoformat())
    start=p.utc(manifest['start_slot_utc']);end=p.utc(manifest['end_slot_utc'])
    value.update(phase='WAITING' if now<start else 'COLLECTING' if now<=end+c.dt.timedelta(minutes=10) else 'MATURING' if now<p.utc(manifest['review_at']) else 'REVIEW_DUE',
                 decisions_pending=[],issues=[],scheduler_active=scheduler_active,integrity='OK')
    try:
        original,records=c.sources(journal,manifest) if Path(journal).exists() else ({},[])
        indexed={(r['slot_utc'],r['arm']):r for r in records}
        mature=set()
        if Path(outcomes).exists():
            with sqlite3.connect(Path(outcomes).resolve().as_uri()+'?mode=ro',uri=True) as db:
                if db.execute('PRAGMA integrity_check').fetchone()[0]!='ok' or p.strict_json(db.execute('SELECT manifest FROM metadata').fetchone()[0])!=manifest:raise ValueError('OUTCOME_MANIFEST_INVALID')
                for slot,raw in db.execute('SELECT slot,payload FROM outcomes'):
                    row=p.strict_json(raw)
                    if row['status']=='AVAILABLE':
                        if slot not in original or p.utc(slot)+c.DAY>now:raise ValueError('OUTCOME_BEFORE_MATURITY')
                        mature.add(slot)
        if Path(journal).exists():
            with sqlite3.connect(Path(journal).resolve().as_uri()+'?mode=ro',uri=True) as db:
                value['conflicts']=db.execute("SELECT count(*) FROM events WHERE kind='CONFLICT'").fetchone()[0]
        for row in value['calendar']:
            slot=row['slot_utc'];due=now>p.utc(slot)+c.dt.timedelta(minutes=10);value['expected']+=int(due)
            for arm in ('baseline','qwen'):
                record=indexed.get((slot,arm));state='UNRECORDED' if due else 'PENDING'
                if record:
                    result=record['result'];row[arm].update(state=result['decision'],reason_codes=result['reason_codes'])
                    if record['timings']:
                        seconds=record['timings'].get('wall_seconds')
                        if type(seconds) in (int,float) and 0<=seconds<=60:row[arm]['latency_seconds']=seconds
                else:row[arm]['state']='RESERVED' if slot in original and not due else state
            row['mature']=slot in mature
            value['recorded_pairs']+=int(all(row[a]['state'] in {'LONG','SHORT','NO_PROPOSAL','MISSING'} for a in ('baseline','qwen')))
        value['mature_outcomes']=len(mature)
        if any(r[a]['state']=='UNRECORDED' for r in value['calendar'] for a in ('baseline','qwen')):value['issues'].append('UNRECORDED_SLOTS')
        if value['conflicts']:value['issues'].append('SOURCE_CONFLICT')
    except (OSError,ValueError,KeyError,TypeError,sqlite3.Error):
        value=v.prepared(manifest,bundle_sha256,now.isoformat());value.update(phase='ATTENTION',integrity='UNAVAILABLE',decisions_pending=[],issues=['JOURNAL_UNAVAILABLE'])
    if not scheduler_active and now<=end+c.DAY:value['issues'].append('SCHEDULER_INACTIVE')
    if value['issues']:value['phase']='ATTENTION'
    return v.validate(value,now=now)


def publish(path,value):
    raw=p.canonical(v.validate(value));temporary=None
    try:
        with tempfile.NamedTemporaryFile(dir=Path(path).parent,prefix='.status-',delete=False) as f:
            temporary=f.name;f.write(raw);f.flush();os.fchmod(f.fileno(),0o640);os.fsync(f.fileno())
        os.replace(temporary,path);temporary=None
        fd=os.open(Path(path).parent,os.O_RDONLY|os.O_DIRECTORY)
        try:os.fsync(fd)
        finally:os.close(fd)
    finally:
        if temporary:os.unlink(temporary)


if __name__=='__main__':
    manifest=p.strict_json(c.read_file(Path(__file__).with_name('manifest.json'),100000,0))
    approval=c.approved('publish',manifest);c.validate_directories('publish')
    import subprocess
    active=all(subprocess.run(['/usr/bin/systemctl','is-active','--quiet','qwen-btc-shadow-'+role+'.timer']).returncode==0 for role in ('collect','decide','recover','mature'))
    publish(c.BASE/'published'/'status.json',build(manifest,approval['bundle_sha256'],c.BASE/'journal'/'shadow-forward.sqlite',c.BASE/'outcomes'/'outcomes.sqlite',scheduler_active=active))
