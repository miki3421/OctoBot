"""Exact operator-directed replacement on the same paper ledger.

Default verifies only. A manual deploy records the actual operator instruction
as root-owned strategy authority; it never impersonates a browser decision or
reads its password. No account balance, order, position or risk counter is reset.
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
from activate_m1_transition_release import containers,wait_healthy,ro,snapshot,write,sha,run


def digest(value):return hashlib.sha256(json.dumps(value,sort_keys=True,separators=(',',':'),ensure_ascii=False,allow_nan=False).encode()).hexdigest()


def main():
    p=argparse.ArgumentParser();p.add_argument('--release',type=Path,required=True);p.add_argument('--manifest-sha256',required=True)
    p.add_argument('--manual-operator-deploy',action='store_true');p.add_argument('--operator-reference');p.add_argument('--proposal-id')
    args=p.parse_args();root=Path('/root/auto_trading_sys');repo=root/'octobot-source';release=args.release.resolve()
    if os.geteuid()!=0 or release.parent!=root.resolve()/'octobot-local' or not release.name.startswith('v13-m1-successor-'):
        raise ValueError('root_and_canonical_release_required')
    manifest=release/'release-manifest.json'
    if sha(manifest)!=args.manifest_sha256:raise ValueError('manifest_digest')
    m=json.loads(manifest.read_text());runtime=Path(m['runtime'])
    if m['scope']!='M1_SUCCESSOR_PREPARED_MANUAL_REPLACEMENT' or sha(__file__)!=m['helper_sha256']:
        raise ValueError('helper_or_release_scope_changed')
    for name,value in m['files'].items():
        f=release/name
        if f.is_symlink() or f.stat().st_uid!=0 or f.stat().st_mode&0o022 or sha(f)!=value:raise ValueError('release_pin:'+name)
    for name,value in m['runtime_files'].items():
        f=runtime/name
        if f.is_symlink() or f.stat().st_uid!=0 or f.stat().st_mode&0o022 or sha(f)!=value:raise ValueError('runtime_pin:'+name)
    if run('docker','image','inspect','octobot-local:dev','--format','{{.Id}}')!=m['image_id']:raise ValueError('image_changed')
    proposal=json.loads((release/'configuration/successor-proposal.json').read_text())
    if not args.manual_operator_deploy:
        print(json.dumps(dict(verified=True,activated=False,proposal_id=m['proposal_id'])));return
    if not args.operator_reference or len(args.operator_reference)>500 or args.proposal_id!=m['proposal_id']:
        raise ValueError('exact_manual_operator_instruction_required')
    now=dt.datetime.now(dt.timezone.utc)
    if not dt.datetime.fromisoformat(proposal['created_at'])<=now<=dt.datetime.fromisoformat(proposal['expires_at']):raise ValueError('proposal_expired')
    state_path=root/'octobot-local/v13-m1-paper-v1/state/account.sqlite';approval_path=root/'octobot-local/v13-m1-management-v1/approvals/approvals.sqlite'
    db=ro(state_path)
    control=json.loads(db.execute("SELECT payload FROM m1_meta WHERE key='control'").fetchone()[0])
    state=json.loads(db.execute('SELECT payload FROM state WHERE id=1').fetchone()[0])
    if control['phase']!='NORMAL' or control.get('pending') or db.execute("SELECT 1 FROM m1_meta WHERE key IN ('management_policy','strategy_successor')").fetchone():raise ValueError('normal_unmanaged_account_required')
    db.close()
    if {s:v['quantity'] for s,v in state['positions'].items()}!=proposal['initial_quantities']:raise ValueError('quantities_changed_new_proposal_required')
    a=ro(approval_path);decisions=a.execute('SELECT COUNT(*) FROM decisions').fetchone()[0];a.close()
    if decisions:raise ValueError('concurrent_operator_decision_requires_review')
    science=json.loads((root/'octobot-local/v13-m1-management-v1/source/science.json').read_text())
    if science['snapshot_id']!=proposal['candidate_id']:raise ValueError('science_changed_new_proposal_required')
    stamp=now.strftime('%Y%m%dT%H%M%SZ');e=root/'audit-evidence/m1-successor-20261025'/('manual-'+stamp);e.mkdir(mode=0o700)
    before=containers();write(e/'containers-before.json',before)
    for name in ('octobot-m1-approval-broker','octobot-v13-m1-paper'):run('docker','stop','--timeout','30',name)
    snapshot(state_path,e/'m1.sqlite');snapshot(approval_path,e/'approvals.sqlite')
    db=ro(e/'m1.sqlite');state=json.loads(db.execute('SELECT payload FROM state WHERE id=1').fetchone()[0]);control=json.loads(db.execute("SELECT payload FROM m1_meta WHERE key='control'").fetchone()[0]);db.close()
    if {s:v['quantity'] for s,v in state['positions'].items()}!=proposal['initial_quantities'] or control['phase']!='NORMAL' or control.get('pending'):
        raise ValueError('stopped_ledger_changed_keep_backup_for_review')
    a=ro(e/'approvals.sqlite');decisions=a.execute('SELECT COUNT(*) FROM decisions').fetchone()[0];a.close()
    if decisions:raise ValueError('operator_decision_arrived_during_stop')
    now=dt.datetime.now(dt.timezone.utc);upgrade=json.loads((release/'configuration/runtime-upgrade-template.json').read_text())
    upgrade.update(authorized_at=now.isoformat(),owner_reference=args.operator_reference,backup_sha256=sha(e/'m1.sqlite'))
    write(release/'configuration/runtime-upgrade.json',upgrade)
    authority=dict(scope='MANUAL_OPERATOR_M1_STRATEGY_REPLACEMENT',account=m['account'],proposal_id=m['proposal_id'],
        authorized_at=now.isoformat(),operator_reference=args.operator_reference,backup_sha256=upgrade['backup_sha256'],
        quantities=proposal['initial_quantities'])
    authority['activation_id']=digest(authority);write(release/'configuration/successor-authority.json',authority)
    for name in ('octobot-m1-approval-broker','octobot-v13-m1-paper'):
        run('docker','update','--restart=no',name);run('docker','rename',name,name+'-legacy-m1-preserved-'+stamp)
    run('docker-compose','-p','trading-m1-successor','-f',str(release/'compose.yml'),'config','-q',cwd=repo)
    run('docker-compose','-p','trading-m1-successor','-f',str(release/'compose.yml'),'up','-d','m1-paper','m1-approval',cwd=repo)
    wait_healthy(['octobot-v13-m1-paper','octobot-m1-approval-broker'])
    web=repo/'packages/tentacles/Services/Interfaces/web_interface'
    for relative in m['ui_paths']:
        target=web/relative;shutil.copy2(target,e/('before-'+target.name));shutil.copyfile(release/'ui'/target.name,target)
    run('docker','restart','octobot-local');after=wait_healthy(m['services'])
    other=[n for n,v in before.items() if n not in m['services'] and any(after.get(n,{}).get(k)!=v[k] for k in ('id','started','restarts'))]
    if other:raise ValueError('unrelated_container_changed')
    projection=json.loads((root/'octobot-local/v13-paper/m1-paper-ui/management.json').read_text())
    if not projection['active'] or projection['policy']['version']!='m1-gradual-long-short-v3' or projection['policy']['short_caps']!=proposal['short_caps']:
        raise ValueError('successor_policy_readback')
    a=ro(approval_path);count=a.execute('SELECT COUNT(*) FROM decisions').fetchone()[0];a.close()
    if count:raise ValueError('unexpected_browser_decision')
    write(e/'result.json',dict(active=True,legacy_strategy_retired=True,same_account=m['account'],proposal_id=m['proposal_id'],
        activation_id=authority['activation_id'],operator_reference=args.operator_reference,initial_equity_reset=False,
        approval_database_decisions=count,approval_source='direct_operator_instruction_not_browser',
        short_budget_unchanged=True,other_containers_unchanged=True,containers=after))
    print(json.dumps(dict(active=True,evidence=str(e),account=m['account'],legacy_retired=True)))


if __name__=='__main__':main()
