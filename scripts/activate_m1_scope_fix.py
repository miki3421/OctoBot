"""Scoped operator-authorized M1 code correction. No replay of missed slots."""
import argparse
import datetime as dt
import json
import os
from pathlib import Path
import time
from prepare_m1_successor import ROOT,sha,write,snapshot
from activate_m1_transition_release import containers,ro,run


def main():
    p=argparse.ArgumentParser();p.add_argument('--release',required=True,type=Path);p.add_argument('--manifest',required=True);p.add_argument('--activate-scope-fix',action='store_true');a=p.parse_args()
    release=a.release.resolve();m=json.loads((release/'release-manifest.json').read_text())
    if (os.geteuid()!=0 or release.parent!=(ROOT/'octobot-local').resolve() or not release.name.startswith('v13-m1-scope-fix-')
        or sha(release/'release-manifest.json')!=a.manifest or m['scope']!='M1_SCIENTIFIC_SCOPE_CORRECTION_PREPARED'
        or sha(__file__)!=m['helper_sha256']):raise ValueError('scope_fix_manifest')
    for root,pins in ((release,m['files']),(Path(m['runtime']),m['runtime_files'])):
        for name,value in pins.items():
            path=root/name
            if path.is_symlink() or path.stat().st_uid!=0 or path.stat().st_mode&0o022 or sha(path)!=value:raise ValueError('pin_changed:'+name)
    run('docker-compose','-f',str(release/'compose.yml'),'config','-q')
    if run('docker','image','inspect','octobot-local:dev','--format','{{.Id}}')!=m['image_id']:raise ValueError('image_changed')
    if not a.activate_scope_fix:print(json.dumps(dict(verified=True,active=False)));return
    source=ROOT/'octobot-local/v13-m1-paper-v1/state/account.sqlite';before=containers();d=ro(source)
    control=json.loads(d.execute("SELECT payload FROM m1_meta WHERE key='control'").fetchone()[0]);d.close()
    if control['phase']!='NORMAL' or control.get('pending'):raise ValueError('wait_normal_no_pending')
    stamp=dt.datetime.now(dt.timezone.utc).strftime('%Y%m%dT%H%M%SZ');e=Path(m['evidence'])/('deploy-'+stamp);e.mkdir(mode=0o700);write(e/'containers-before.json',before)
    run('docker','stop','--timeout','30','octobot-v13-m1-paper');snapshot(source,e/'account.sqlite')
    d=ro(e/'account.sqlite');orders=d.execute('SELECT COUNT(*) FROM orders').fetchone()[0];old_policy=json.loads(d.execute("SELECT payload FROM m1_meta WHERE key='management_policy'").fetchone()[0]);control=json.loads(d.execute("SELECT payload FROM m1_meta WHERE key='control'").fetchone()[0]);d.close()
    if control['phase']!='NORMAL' or control.get('pending'):raise ValueError('stopped_state_changed')
    upgrade=json.loads((release/'configuration/runtime-upgrade-template.json').read_text());upgrade.update(authorized_at=dt.datetime.now(dt.timezone.utc).isoformat(),owner_reference='Operator authorizes correction of M1 scientific versus execution input scope on 26 October',backup_sha256=sha(e/'account.sqlite'));write(release/'configuration/runtime-upgrade.json',upgrade)
    run('docker','update','--restart=no','octobot-v13-m1-paper');run('docker','rename','octobot-v13-m1-paper','octobot-v13-m1-paper-pre-scope-fix-'+stamp)
    run('docker-compose','-p','trading-m1-scope-fix','-f',str(release/'compose.yml'),'up','-d','m1-paper')
    deadline=time.monotonic()+180;projection=ROOT/'octobot-local/v13-paper/m1-paper-ui/account.json'
    while time.monotonic()<deadline:
        actual=containers();v=json.loads(projection.read_text())
        if actual.get('octobot-v13-m1-paper',{}).get('health')=='healthy' and v['control'].get('baseline_error') is None:break
        time.sleep(2)
    else:raise ValueError('scope_fix_readback_failed')
    if any(any(actual.get(n,{}).get(k)!=x[k] for k in ('id','started','restarts')) for n,x in before.items() if n!='octobot-v13-m1-paper'):raise ValueError('unrelated_service_changed')
    d=ro(source);new_policy=json.loads(d.execute("SELECT payload FROM m1_meta WHERE key='management_policy'").fetchone()[0]);preserved=d.execute('SELECT COUNT(*) FROM orders WHERE id<=?',(orders,)).fetchone()[0];denied=d.execute("SELECT status,payload FROM m1_slots WHERE kind='DAILY' AND slot='2026-10-26T00:15:00+00:00'").fetchone();d.close()
    if new_policy['short_caps']!=old_policy['short_caps'] or preserved!=orders or denied[0]!='DENIED':raise ValueError('history_or_policy_changed')
    write(e/'result.json',dict(active=True,baseline_error=None,retained_orders=preserved,missed_slot_retained=dict(status=denied[0],payload=json.loads(denied[1])),short_budget_unchanged=True,other_services_unchanged=True,containers=actual))
    print(json.dumps(dict(active=True,baseline_error=None,evidence=str(e))))


if __name__=='__main__':main()
