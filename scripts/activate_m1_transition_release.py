"""Exact manual operator deploy gate. Never approves the paper rebalance.

Default: verify prepared artifacts only. Mutation needs all explicit CLI flags.
"""
import argparse
import datetime as dt
import hashlib
import json
import os
from pathlib import Path
import shutil
import sqlite3
import subprocess
import time


def sha(path):return hashlib.sha256(Path(path).read_bytes()).hexdigest()
def run(*args,cwd=None):return subprocess.check_output(list(args),cwd=cwd,text=True).strip()
def ro(path):
    db=sqlite3.connect(Path(path).resolve().as_uri()+'?mode=ro',uri=True);db.execute('PRAGMA query_only=ON');return db
def snapshot(source,target):
    a=ro(source);b=sqlite3.connect(target);a.backup(b)
    if b.execute('PRAGMA integrity_check').fetchone()[0]!='ok':raise ValueError('backup_integrity')
    a.close();b.close();target.chmod(0o440)
def write(path,value):
    tmp=path.with_suffix('.pending');tmp.write_text(json.dumps(value,indent=2)+'\n');os.chown(tmp,0,30910);tmp.chmod(0o440);os.replace(tmp,path)
def containers():
    names=run('docker','ps','--filter','name=octobot-','--format','{{.Names}}').splitlines()
    raw=json.loads(run('docker','inspect',*names))
    return {v['Name'].lstrip('/'):dict(id=v['Id'],started=v['State']['StartedAt'],restarts=v['RestartCount'],health=v['State'].get('Health',{}).get('Status')) for v in raw}
def wait_healthy(names):
    deadline=time.monotonic()+180
    while time.monotonic()<deadline:
        actual=containers()
        if all(actual.get(n,{}).get('health')=='healthy' for n in names):return actual
        time.sleep(2)
    raise ValueError('services_not_healthy_read_logs_no_automatic_approval')


def main():
    parser=argparse.ArgumentParser();parser.add_argument('--root',type=Path,default=Path('/root/auto_trading_sys'))
    parser.add_argument('--release',type=Path,required=True);parser.add_argument('--release-sha256',required=True)
    parser.add_argument('--manual-operator-deploy',action='store_true');parser.add_argument('--operator-reference')
    args=parser.parse_args();root=args.root.resolve();target=args.release.resolve();manifest_path=target/'release-manifest.json'
    if os.geteuid()!=0 or sha(manifest_path)!=args.release_sha256:raise ValueError('root_and_exact_manifest_required')
    manifest=json.loads(manifest_path.read_text());runtime=Path(manifest['runtime'])
    if manifest['scope']!='M1_TRANSITION_V2_PREPARED_NOT_ACTIVATED':raise ValueError('release_scope')
    if str(target)!=str(root/'octobot-local/v13-m1-management-v2-r2'):raise ValueError('compose_release_binding')
    if sha(Path(__file__))!=manifest['activation_helper_sha256']:raise ValueError('activation_helper_changed')
    if sha(root/'octobot-source/docker-compose.v13-m1-transition.yml')!=manifest['compose_sha256']:raise ValueError('compose_changed')
    for name,digest in manifest['web_code_pins'].items():
        if sha(root/'octobot-source'/name)!=digest:raise ValueError('web_code_changed')
    for name,digest in manifest['runtime_files'].items():
        path=runtime/name
        if path.is_symlink() or path.stat().st_uid!=0 or path.stat().st_mode&0o022 or sha(path)!=digest:raise ValueError('runtime_pin')
    for name,digest in manifest['files'].items():
        path=target/name
        if path.is_symlink() or path.stat().st_uid!=0 or path.stat().st_mode&0o022 or sha(path)!=digest:raise ValueError('release_pin')
    if manifest.get('image_id')!=run('docker','image','inspect','octobot-local:dev','--format','{{.Id}}'):raise ValueError('local_image_changed')
    if not args.manual_operator_deploy:
        print(json.dumps(dict(verified=True,proposal_id=manifest['proposal_id'],activated=False,manual_operator_gate=True)));return
    if not args.operator_reference or len(args.operator_reference)>240:raise ValueError('operator_reference_required')
    proposal=json.loads((target/'configuration/transition-proposal.json').read_text())
    if dt.datetime.now(dt.timezone.utc)>dt.datetime.fromisoformat(proposal['expires_at']):raise ValueError('proposal_expired_new_version_required')
    state_path=root/'octobot-local/v13-m1-paper-v1/state/account.sqlite';approval_path=root/'octobot-local/v13-m1-management-v1/approvals/approvals.sqlite'
    db=ro(state_path)
    if db.execute("SELECT payload FROM m1_meta WHERE key='management_policy'").fetchone():raise ValueError('existing_policy_requires_new_migration_review')
    control=json.loads(db.execute("SELECT payload FROM m1_meta WHERE key='control'").fetchone()[0]);db.close()
    if control['phase']!='NORMAL' or control.get('pending'):raise ValueError('wait_for_normal_phase_no_pending_intent')
    a=ro(approval_path);count=a.execute('SELECT COUNT(*) FROM decisions').fetchone()[0];a.close()
    if count:raise ValueError('unexpected_existing_operator_decision')
    stamp=dt.datetime.now(dt.timezone.utc).strftime('%Y%m%dT%H%M%SZ');e=root/'audit-evidence/m1-v2-ui-20261024'/('manual-deploy-'+stamp);e.mkdir(mode=0o700)
    before=containers();write(e/'containers-before.json',before)
    # Stop the approval writer first, then take the single execution writer down.
    for name in ('octobot-m1-approval-broker','octobot-v13-m1-paper'):run('docker','stop','--timeout','30',name)
    snapshot(state_path,e/'m1.sqlite');snapshot(approval_path,e/'approvals.sqlite')
    a=ro(e/'approvals.sqlite');count=a.execute('SELECT COUNT(*) FROM decisions').fetchone()[0];a.close()
    db=ro(e/'m1.sqlite');identity=json.loads(db.execute("SELECT payload FROM m1_meta WHERE key='identity'").fetchone()[0]);policy=db.execute("SELECT payload FROM m1_meta WHERE key='management_policy'").fetchone();db.close()
    template=json.loads((target/'configuration/runtime-upgrade-template.json').read_text())
    if count or policy or template['from_identity']!=identity:raise ValueError('stopped_backup_authority_changed_keep_stopped_for_review')
    template.update(authorized_at=dt.datetime.now(dt.timezone.utc).isoformat(),owner_reference=args.operator_reference,backup_sha256=sha(e/'m1.sqlite'))
    write(target/'configuration/runtime-upgrade.json',template)
    for name in ('octobot-m1-approval-broker','octobot-v13-m1-paper'):
        run('docker','update','--restart=no',name);run('docker','rename',name,name+'-v3-preserved-'+stamp)
    compose=root/'octobot-source/docker-compose.v13-m1-transition.yml'
    run('docker-compose','-p','trading-m1-v2','-f',str(compose),'config','-q',cwd=root/'octobot-source')
    run('docker-compose','-p','trading-m1-v2','-f',str(compose),'up','-d','m1-paper','m1-approval',cwd=root/'octobot-source')
    wait_healthy(['octobot-v13-m1-paper','octobot-m1-approval-broker'])
    web=root/'octobot-local/tentacles/Services/Interfaces/web_interface'
    for name,relative in [('v13_m1_review.html','templates/v13_m1_review.html'),('v13_m1_weekly.js','static/js/common/v13_m1_weekly.js')]:
        dst=web/relative;shutil.copy2(dst,e/('before-'+name));shutil.copyfile(target/'ui'/name,dst)
    run('docker','restart','octobot-local');after=wait_healthy(['octobot-local','octobot-v13-m1-paper','octobot-m1-approval-broker'])
    changed=[n for n,v in before.items() if n not in ('octobot-local','octobot-v13-m1-paper','octobot-m1-approval-broker') and any(after.get(n,{}).get(k)!=v[k] for k in ('id','started','restarts'))]
    if changed:raise ValueError('unrelated_container_changed')
    a=ro(approval_path);count=a.execute('SELECT COUNT(*) FROM decisions').fetchone()[0];a.close()
    db=ro(state_path);policy=db.execute("SELECT payload FROM m1_meta WHERE key='management_policy'").fetchone();db.close()
    projection=json.loads((root/'octobot-local/v13-paper/m1-paper-ui/management.json').read_text())
    if count or policy or projection['proposal']['proposal_id']!=manifest['proposal_id']:raise ValueError('postdeploy_requires_review')
    write(e/'result.json',dict(activated=True,proposal_id=manifest['proposal_id'],operator_reference=args.operator_reference,
                              rebalance_approved=False,approval_decisions=0,management_policy=None,containers=after,unchanged_other_services=True))
    print(json.dumps(dict(activated=True,evidence=str(e),rebalance_approved=False,approval_decisions=0)))


if __name__=='__main__':main()
