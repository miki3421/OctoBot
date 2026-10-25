"""Verify by default; exact delegated authority enables M1-only continuation."""
import argparse
import datetime as dt
import json
import os
from pathlib import Path
import shutil
import time
from prepare_m1_successor import ROOT,sha,write,snapshot
from activate_m1_transition_release import containers,run,ro


def main():
    p=argparse.ArgumentParser();p.add_argument('--release',type=Path,required=True);p.add_argument('--manifest',required=True)
    p.add_argument('--activate-delegated-review',action='store_true');p.add_argument('--delegation-id');args=p.parse_args()
    release=args.release.resolve();repo=ROOT/'octobot-source'
    if os.geteuid()!=0 or release.parent!=(ROOT/'octobot-local').resolve() or not release.name.startswith('v13-m1-auto-'):raise ValueError('release_boundary')
    m=json.loads((release/'release-manifest.json').read_text())
    if sha(release/'release-manifest.json')!=args.manifest or sha(__file__)!=m['helper_sha256'] or m['scope']!='M1_AUTO_REVIEW_PREPARED':raise ValueError('manifest_changed')
    runtime=Path(m['runtime'])
    for root,files in ((release,m['files']),(runtime,m['runtime_files'])):
        for name,digest in files.items():
            path=root/name
            if path.is_symlink() or path.stat().st_uid!=0 or path.stat().st_mode&0o022 or sha(path)!=digest:raise ValueError('pin_changed:'+name)
    if run('docker','image','inspect','octobot-local:dev','--format','{{.Id}}')!=m['image_id']:raise ValueError('image_changed')
    run('docker-compose','-f',str(release/'compose.yml'),'config','-q',cwd=repo)
    if not args.activate_delegated_review:print(json.dumps(dict(verified=True,active=False)));return
    if args.delegation_id!=m['delegation_id']:raise ValueError('exact_delegation_required')
    stamp=dt.datetime.now(dt.timezone.utc).strftime('%Y%m%dT%H%M%SZ');e=Path(m['evidence'])/('deploy-'+stamp);e.mkdir(mode=0o700)
    before=containers();write(e/'containers-before.json',before)
    source=ROOT/'octobot-local/v13-m1-paper-v1/state/account.sqlite'
    a=ro(source);control=json.loads(a.execute("SELECT payload FROM m1_meta WHERE key='control'").fetchone()[0]);a.close()
    if control['phase']!='NORMAL' or control.get('pending'):raise ValueError('wait_normal_no_pending')
    run('docker','stop','--timeout','30','octobot-v13-m1-paper');snapshot(source,e/'account.sqlite')
    snapshot(ROOT/'octobot-local/v13-m1-management-v1/approvals/approvals.sqlite',e/'approvals.sqlite')
    a=ro(e/'account.sqlite');control=json.loads(a.execute("SELECT payload FROM m1_meta WHERE key='control'").fetchone()[0]);orders=a.execute('SELECT COUNT(*) FROM orders').fetchone()[0];a.close()
    if control['phase']!='NORMAL' or control.get('pending'):raise ValueError('stopped_state_changed_keep_backup')
    upgrade=json.loads((release/'configuration/runtime-upgrade-template.json').read_text())
    upgrade.update(authorized_at=dt.datetime.now(dt.timezone.utc).isoformat(),owner_reference='Operator delegated automatic weighted M1 paper approvals',backup_sha256=sha(e/'account.sqlite'))
    write(release/'configuration/runtime-upgrade.json',upgrade)
    run('docker','update','--restart=no','octobot-v13-m1-paper');run('docker','rename','octobot-v13-m1-paper','octobot-v13-m1-paper-v6-preserved-'+stamp)
    run('docker-compose','-p','trading-m1-auto','-f',str(release/'compose.yml'),'up','-d','m1-paper',cwd=repo)
    # Bounded poll; no data restoration or automatic retry of a failed order.
    deadline=time.monotonic()+150
    while time.monotonic()<deadline:
        current=containers()
        if current.get('octobot-v13-m1-paper',{}).get('health')=='healthy':break
        time.sleep(2)
    else:raise ValueError('M1_not_healthy_inspect_logs')
    web=repo/'packages/tentacles/Services/Interfaces/web_interface'
    for name,relative in [('v13_m1_weekly.js','static/js/common/v13_m1_weekly.js'),('v13_m1_review.html','templates/v13_m1_review.html')]:
        dst=web/relative;shutil.copyfile(dst,e/('before-'+name));shutil.copyfile(release/'ui'/name,dst)
    run('docker','restart','octobot-local')
    after=containers()
    if any(any(after.get(n,{}).get(k)!=v[k] for k in ('id','started','restarts')) for n,v in before.items() if n not in ('octobot-v13-m1-paper','octobot-local')):raise ValueError('unrelated_service_changed')
    projection=json.loads((ROOT/'octobot-local/v13-paper/m1-paper-ui/management.json').read_text())
    if not projection.get('automatic_review',{}).get('enabled') or projection['policy']['short_caps']!=json.loads((release/'configuration/automatic-authority.json').read_text())['short_caps']:raise ValueError('automatic_review_readback')
    a=ro(source);retained=a.execute('SELECT COUNT(*) FROM orders WHERE id<=?',(orders,)).fetchone()[0];a.close()
    if retained!=orders:raise ValueError('history_retention')
    write(e/'result.json',dict(active=True,same_account=m['account'],delegation_id=m['delegation_id'],retained_orders=retained,other_services_unchanged=True,containers=after))
    print(json.dumps(dict(active=True,evidence=str(e),retained_orders=retained)))


if __name__=='__main__':main()
