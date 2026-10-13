"""Create sealed, non-operational V13 research forks using SQLite online backup.

No exchange, executor, service or authorization interface. Original opened read-only.
"""
import argparse
import datetime as dt
import hashlib
import json
import os
from pathlib import Path
import shutil
import sqlite3


def digest_file(path):
    h=hashlib.sha256()
    with path.open('rb') as f:
        for block in iter(lambda:f.read(1024*1024),b''):h.update(block)
    return h.hexdigest()


def describe(c):
    tables={}
    for (name,) in c.execute("SELECT name FROM sqlite_master WHERE type='table' ORDER BY name"):
        quoted='"'+name.replace('"','""')+'"'
        h=hashlib.sha256();n=0
        for row in c.execute('SELECT * FROM '+quoted+' ORDER BY rowid'):
            h.update(json.dumps(row,separators=(',',':'),ensure_ascii=False,allow_nan=False).encode()+b'\n');n+=1
        tables[name]={'rows':n,'sha256':h.hexdigest()}
    state=json.loads(c.execute('SELECT payload FROM state WHERE id=1').fetchone()[0])
    return tables,state


def seal(path):
    with path.open('rb') as f:os.fsync(f.fileno())
    path.chmod(0o440)


def main():
    ap=argparse.ArgumentParser(description=__doc__);ap.add_argument('--source',type=Path,required=True);ap.add_argument('--destination',type=Path,required=True)
    args=ap.parse_args();source=args.source
    if source.is_symlink() or not source.is_file():raise ValueError('source must be an existing regular DB')
    source=source.resolve();dest=args.destination.resolve()
    if dest.exists() or dest==source.parent or source.parent in dest.parents:raise ValueError('new isolated destination required')
    dest.mkdir(parents=True,mode=0o750);started=dt.datetime.now(dt.timezone.utc).isoformat()
    baseline=dest/'parent-snapshot.sqlite'
    src=sqlite3.connect(source.as_uri()+'?mode=ro',uri=True,timeout=15);src.execute('PRAGMA query_only=ON');src.execute('BEGIN')
    # Establish a single source transaction for row hashes, state and backup.
    tables,state=describe(src)
    dst=sqlite3.connect(baseline)
    try:
        src.backup(dst,pages=256,sleep=.01)
        assert dst.execute('PRAGMA integrity_check').fetchall()==[('ok',)]
        copy_tables,copy_state=describe(dst)
        assert copy_tables==tables and copy_state==state
    finally:
        dst.close();src.rollback();src.close()
    seal(baseline);h=digest_file(baseline)
    cutoff=state.get('last_success_at') or state.get('last_market_at')
    manifest={'schema_version':1,'scope':'SEALED_RESEARCH_FORK_PREPARATION','status':'PREPARED_NOT_RUNNING','backup_started_at':started,'backup_completed_at':dt.datetime.now(dt.timezone.utc).isoformat(),'source_alias':'v13-research-execution','economic_cutoff':cutoff,'parent_sha256':h,'tables':tables,'risk_state':state.get('risk_policy_state'),'inherited_history':'All source execution database tables and rows, unchanged; historical claims are evidence only, not fork authority.','arms':{}}
    for arm in ['FAST','HALF']:
        directory=dest/arm.lower();directory.mkdir(mode=0o750);target=directory/'execution.sqlite';shutil.copyfile(baseline,target);seal(target)
        assert digest_file(target)==h and target.stat().st_ino!=baseline.stat().st_ino
        account='v13-risk-matched-clone-v2-'+arm.lower()+'-'+h[:12]
        config={'schema_version':1,'account_id':account,'arm':arm,'enabled':False,'status':'SEALED_NOT_RUNNING','execution_scope':'OFFLINE_RESEARCH_ONLY','parent_sha256':h,'economic_cutoff':cutoff,'protocol':'v13-prospective-risk-matched-v2','executor_connection':None,'approvals_store':None,'operational_grants':False,'first_decision_slot':None,'historical_claims_usable':False,'new_position_identity':'Namespace inherited position IDs with this account_id before any future branch operation; inherited generations and accounting unchanged.','risk_state_policy':'Inherit daily start, high water, last increase, daily count; never reset on fork.'}
        config_path=directory/'branch.json';config_path.write_text(json.dumps(config,indent=2)+'\n');seal(config_path)
        manifest['arms'][arm]={'account_id':account,'db_sha256':h,'config_sha256':digest_file(config_path),'relative_db':str(target.relative_to(dest))}
    f=dest/'fork-manifest.json';f.write_text(json.dumps(manifest,indent=2)+'\n');seal(f)
    fd=os.open(dest,os.O_RDONLY)
    try:os.fsync(fd)
    finally:os.close(fd)
    print(json.dumps({'destination':str(dest),'cutoff':cutoff,'sha256':h,'tables':{k:v['rows'] for k,v in tables.items()},'risk_state':manifest['risk_state']}))


if __name__=='__main__':main()
