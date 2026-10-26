"""Complete copied-account mechanics; synthetic future data is never a score."""
import argparse
import copy
import datetime as dt
import json
import os
from pathlib import Path
import shutil
import sqlite3
import subprocess
import sys
from unittest.mock import patch

from octobot.ai_strategy_lab import v13_fork_discrete_offline as d

f=d.f
TABLES=('slots','fills','funding','observations','inputs')


def logical(runner):
    return {t:[tuple(r) for r in runner.db.execute('SELECT * FROM '+t+' ORDER BY rowid')]
            for t in ('states','slots','fills','funding','observations')}


def write_book(root, record):
    (root/'market.json').write_text(f.dump(record))
    path=root/'market'/(record['record_hash']+'.json');path.write_text(f.dump(record))
    at=f.p.timestamp(record['observed_at_end']).timestamp();os.utime(path,(at,at))


def tick(runner,instant):
    with patch.object(f.source,'now',return_value=instant):runner.tick(instant)


def crash_worker(path):
    config=json.loads(path.read_text());r=d.OfflineRunner(config)
    r.db.execute('PRAGMA cache_size=1')
    r.db.execute('CREATE TABLE mechanical_crash_spill(id INTEGER PRIMARY KEY,payload TEXT)')
    with r.db:r.db.executemany('INSERT INTO mechanical_crash_spill VALUES(?,?)',[(i,'a'*8192) for i in range(256)])
    r.db.create_function('die',0,lambda:os._exit(91))
    r.db.execute("CREATE TRIGGER mechanical_crash BEFORE UPDATE ON states WHEN new.arm='HALF' AND json_extract(new.payload,'$.last_discrete_plan_version') IS NOT NULL BEGIN UPDATE mechanical_crash_spill SET payload=replace(payload,'a','b'); SELECT die(); END;")
    tick(r,f.p.timestamp(config['offline']['boundary'])+dt.timedelta(seconds=45))
    raise AssertionError('crash_not_triggered')


def qualify(source,work):
    manifest=json.loads((source/'input-manifest.json').read_text())
    if manifest['role']!='SEALED_OFFLINE_COPIES':raise ValueError('offline_evidence_required')
    for name,h in manifest['sha256'].items():
        if Path(name).is_absolute() or '..' in Path(name).parts or f.sha(source/name)!=h:raise ValueError('evidence_hash')
    if work.exists():raise ValueError('fresh_work_directory_required')
    work.mkdir();(work/'market').mkdir()
    integrity={}
    for name in ('paired.sqlite','original.sqlite','parent-snapshot.sqlite'):
        c=f.ro(source/name)
        try:integrity[name]=[r[0] for r in c.execute('PRAGMA integrity_check')]
        finally:c.close()
        if integrity[name]!=['ok']:raise ValueError('input_integrity')
    shutil.copyfile(source/'paired.sqlite',work/'paired.sqlite')
    shutil.copyfile(source/'original.sqlite',work/'synthetic-reference.sqlite')
    c=f.ro(source/'paired.sqlite')
    try:
        inherited={r['arm']:json.loads(r['payload']) for r in c.execute('SELECT * FROM states')}
        receipt=json.loads(c.execute("SELECT payload FROM meta WHERE key='receipt'").fetchone()[0])
        last=f.p.timestamp(c.execute('SELECT MAX(at) FROM observations').fetchone()[0])
        cached=json.loads(c.execute('SELECT payload FROM inputs ORDER BY day DESC LIMIT 1').fetchone()[0])
        prefix={t:(c.execute('SELECT MAX(rowid) FROM '+t).fetchone()[0] or 0,
                   f.p.digest([tuple(r) for r in c.execute('SELECT * FROM '+t+' ORDER BY rowid')])) for t in TABLES}
    finally:c.close()
    slot=(last+dt.timedelta(days=1)).replace(hour=0,minute=15,second=0,microsecond=0)
    original_book=f.read(source/'market.json')
    symbols=sorted(original_book['quotes'])
    # Explicitly synthetic marks extend the copied reference beyond capture.
    # No generated row is put into source evidence or any running account.
    reference=sqlite3.connect(work/'synthetic-reference.sqlite')
    start=dt.datetime.fromtimestamp((int(last.timestamp())//300)*300,f.UTC)
    rows=[];at=start
    while at<=slot:
        rows.extend((at.isoformat(),s,original_book['quotes'][s]['mark_price']) for s in symbols)
        at+=dt.timedelta(minutes=5)
    reference.executemany('INSERT OR REPLACE INTO marks VALUES(?,?,?)',rows);reference.commit();reference.close()
    def mechanical_book(instant):
        record=copy.deepcopy(original_book)
        record.update(observed_at_start=instant.isoformat(),observed_at_end=instant.isoformat(),
                      fixture_role='SYNTHETIC_FUTURE_MECHANICS_NOT_MARKET_EVIDENCE',source_record_hash=original_book['record_hash'])
        endms=int(instant.timestamp()*1000)
        for q in record['quotes'].values():
            q.update(timestamp=instant.isoformat(),mark_timestamp=instant.isoformat(),metadata_observed_at=instant.isoformat())
            points=q['funding'];next_ms=points[-1]['timestamp_ms']+q['funding_interval_ms']
            while next_ms<=endms:
                points.append(dict(timestamp_ms=next_ms,rate=.0001));next_ms+=q['funding_interval_ms']
            # A labelled non-calendar settlement exercises atomic slot funding.
            forced=int((slot+dt.timedelta(seconds=10)).timestamp()*1000)
            if forced<=endms and points[-1]['timestamp_ms']<forced:
                points.append(dict(timestamp_ms=forced,rate=.0001))
        record['record_hash']=f.p.digest({k:v for k,v in record.items() if k!='record_hash'})
        return record
    repo=Path(f.__file__).resolve().parents[2]
    config=dict(protocol=str(repo/'docs/research-protocols/v13-prospective-risk-matched-v2.json'),
                seed=str(source/'parent-snapshot.sqlite'),original=str(work/'synthetic-reference.sqlite'),repo=str(repo),
                db=str(work/'paired.sqlite'),derivation=dict(source=str(work)),
                offline=dict(scope=d.SCOPE,work_dir=str(work),boundary=slot.isoformat(),source_ledger_sha256=manifest['sha256']['paired.sqlite']))
    r=d.OfflineRunner(config)
    assert r.states()==inherited and r.receipt==receipt
    inherited_hash=f.p.digest(inherited)
    item=dict(cached,day=(slot.date()-dt.timedelta(days=1)).isoformat(),
              source_day=cached['day'],fixture_role='SYNTHETIC_FUTURE_MECHANICS_NOT_SCIENTIFIC_DERIVATION',
              proposal_id='SYNTHETIC_MECHANICAL_INPUT',snapshot_id='SYNTHETIC_MECHANICAL_INPUT')
    with r.db:r.db.execute('INSERT INTO inputs VALUES(?,?)',(item['day'],f.dump(item)))
    write_book(work,mechanical_book(slot-dt.timedelta(minutes=1)))
    tick(r,slot-dt.timedelta(seconds=30))
    pre=logical(r)
    pre_counts={t:r.db.execute('SELECT COUNT(*) FROM '+t).fetchone()[0] for t in TABLES}
    write_book(work,mechanical_book(slot+dt.timedelta(seconds=30)))
    r.db.execute("CREATE TRIGGER mechanical_half_failure BEFORE UPDATE ON states WHEN new.arm='HALF' AND json_extract(new.payload,'$.last_discrete_plan_version') IS NOT NULL BEGIN SELECT RAISE(ABORT,'qualification storage failure'); END;")
    try:tick(r,slot+dt.timedelta(seconds=45))
    except sqlite3.IntegrityError:pass
    else:raise AssertionError('half_failure_not_triggered')
    assert logical(r)==pre
    r.db.execute('DROP TRIGGER mechanical_half_failure');r.close()
    config_path=work/'offline-config.json';config_path.write_text(f.dump(config))
    process=subprocess.run([sys.executable,__file__,'--crash-worker',str(config_path)],capture_output=True,text=True,timeout=30)
    if process.returncode!=91:raise AssertionError('crash_worker_failed:'+process.stderr[-1000:])
    journal=Path(config['db']+'-journal');assert journal.is_file() and journal.stat().st_size>0
    journal_bytes=journal.stat().st_size
    r=d.OfflineRunner(config)
    assert logical(r)==pre
    assert r.db.execute("SELECT COUNT(*) FROM mechanical_crash_spill WHERE payload LIKE 'b%'").fetchone()[0]==0
    r.db.execute('DROP TRIGGER mechanical_crash')
    tick(r,slot+dt.timedelta(seconds=45))
    decision=r.db.execute('SELECT status,payload FROM slots WHERE slot=?',(slot.isoformat(),)).fetchone()
    outcome=json.loads(decision['payload'])
    committed=logical(r);r.close();r=d.OfflineRunner(config)
    tick(r,slot+dt.timedelta(seconds=45));assert logical(r)==committed
    post_counts={t:r.db.execute('SELECT COUNT(*) FROM '+t).fetchone()[0] for t in TABLES}
    assert r.receipt==receipt
    for t,(max_row,expected) in prefix.items():
        actual=f.p.digest([tuple(row) for row in r.db.execute('SELECT * FROM '+t+' WHERE rowid<=? ORDER BY rowid',(max_row,))])
        assert actual==expected
    for a,state in r.states().items():
        for s,pos in state['positions'].items():
            reconstructed=r.parent['positions'][s]['quantity']+sum(row[0] for row in r.db.execute('SELECT quantity FROM fills WHERE arm=? AND symbol=?',(a,s)))
            assert abs(reconstructed-pos['quantity'])<1e-8
    result=dict(scope=d.SCOPE,fixture_role='SYNTHETIC_FUTURE_MECHANICS_ONLY_NOT_A_BACKTEST',
                inherited_full_state_sha256=inherited_hash,legacy_receipt_unchanged=True,all_historical_prefix_rows_unchanged=True,
                source_cutoff=last.isoformat(),mechanical_boundary=slot.isoformat(),
                cached_input_source_day=cached['day'],future_scientific_inputs_qualified=False,
                input_integrity=integrity,half_write_rollback_passed=True,hard_process_exit_code=process.returncode,
                interrupted_journal_bytes=journal_bytes,hot_journal_recovery_passed=True,restart_idempotent=True,
                filled_quantities_reconcile=True,new_rows={t:post_counts[t]-pre_counts[t] for t in TABLES},
                decision_status=decision['status'],decision=outcome,
                work_copy_integrity=[row[0] for row in r.db.execute('PRAGMA integrity_check')],
                execution_authorized=False,live_mutations=False,profitability_evaluated=False)
    r.close()
    for name,h in manifest['sha256'].items():assert f.sha(source/name)==h
    result['source_evidence_unchanged']=True
    return result


if __name__=='__main__':
    if len(sys.argv)==3 and sys.argv[1]=='--crash-worker':
        crash_worker(Path(sys.argv[2]))
    else:
        parser=argparse.ArgumentParser(description=__doc__)
        parser.add_argument('--evidence',type=Path,required=True)
        parser.add_argument('--work',type=Path,required=True)
        parser.add_argument('--output',type=Path,required=True)
        args=parser.parse_args();result=qualify(args.evidence,args.work)
        args.output.write_text(json.dumps(result,indent=2,allow_nan=False)+'\n')
        print(json.dumps({k:v for k,v in result.items() if k!='decision'},indent=2))
