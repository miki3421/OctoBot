"""Prepare v4, never activate or approve. Existing M1 ledger/source stay untouched."""
import argparse
import datetime as dt
import hashlib
import json
import os
from pathlib import Path
import shutil
import sqlite3
import subprocess

CHANGED=('v13_m1_weekly.py','v13_m1_managed.py','v13_m1_approval_broker.py',
         'v13_m1_management_web.py','v13_m1_transition.py','v13_m1_paper.py')


def sha(path):return hashlib.sha256(Path(path).read_bytes()).hexdigest()
def write(path,value):
    path.write_text(json.dumps(value,indent=2)+'\n');os.chown(path,0,30910);path.chmod(0o440)


def main():
    p=argparse.ArgumentParser();p.add_argument('--root',type=Path,required=True);p.add_argument('--snapshot',type=Path,required=True)
    p.add_argument('--proposal',type=Path,required=True);p.add_argument('--runtime',type=Path,required=True);p.add_argument('--target',type=Path);args=p.parse_args()
    if os.geteuid()!=0:raise ValueError('root_preparer_required')
    root=args.root.resolve();repo=root/'octobot-source';old=root/'octobot-local/v13-m1-management-v1/configuration'
    target=args.target or root/'octobot-local/v13-m1-management-v2';runtime=args.runtime
    if target.exists() or runtime.exists():raise ValueError('new_release_required')
    proposal=json.loads(args.proposal.read_text())
    if proposal['version']!='m1-long-maintenance-v2' or proposal['execution_authorized'] is not False:raise ValueError('proposal_scope')
    db=sqlite3.connect(args.snapshot.resolve().as_uri()+'?mode=ro',uri=True);db.execute('PRAGMA query_only=ON')
    if db.execute('PRAGMA integrity_check').fetchone()[0]!='ok':raise ValueError('snapshot_integrity')
    if db.execute("SELECT payload FROM m1_meta WHERE key='management_policy'").fetchone():raise ValueError('already_managed_requires_explicit_migration')
    identity=json.loads(db.execute("SELECT payload FROM m1_meta WHERE key='identity'").fetchone()[0]);db.close()
    shutil.copytree('/opt/v13-m1-paper-runtime-v3',runtime)
    for name in CHANGED:shutil.copyfile(repo/'octobot/ai_strategy_lab'/name,runtime/'octobot/ai_strategy_lab'/name)
    pins={str(f.relative_to(runtime)):sha(f) for f in runtime.rglob('*') if f.is_file() and '__pycache__' not in f.parts}
    for f in runtime.rglob('*'):
        if f.is_symlink():raise ValueError('runtime_symlink')
        os.chown(f,0,0);f.chmod(0o555 if f.is_dir() else 0o444)
    runtime.chmod(0o555)
    for folder in (target,target/'configuration',target/'ui'):
        folder.mkdir(parents=True,exist_ok=True);os.chown(folder,0,30910);folder.chmod(0o750)
    config=json.loads((old/'config.json').read_text());protocol=json.loads((old/'protocol.json').read_text())
    code=config['management']['code_pins']
    for name in CHANGED:code['octobot/ai_strategy_lab/'+name]=pins['octobot/ai_strategy_lab/'+name]
    protocol['source_code_pins'].update(code);protocol['management_extension']='M1_LONG_MAINTENANCE_V2'
    protocol['strategy']['normal']='Unchanged Original published baseline, capped by explicitly approved persistent LONG quantities; no automatic cash redistribution'
    config['management'].update(transition_proposal='/configuration/transition-proposal.json',transition_sha256=sha(args.proposal))
    write(target/'configuration/config.json',config);write(target/'configuration/protocol.json',protocol)
    # The proposal file is pinned by byte hash, so preserve its exact bytes.
    q=target/'configuration/transition-proposal.json';shutil.copyfile(args.proposal,q);os.chown(q,0,30910);q.chmod(0o440)
    broker=json.loads((old/'broker.json').read_text());broker['transition_only']=True;write(target/'configuration/broker.json',broker)
    template=dict(scope='M1_LONG_MAINTENANCE_V2',account=proposal['account'],from_identity=identity,
                  to_identity=dict(seed=identity['seed'],protocol=sha(target/'configuration/protocol.json'),runner=code['octobot/ai_strategy_lab/v13_m1_paper.py']),
                  authorized_at=None,owner_reference='PENDING_MANUAL_OPERATOR_DEPLOY',backup_sha256=sha(args.snapshot))
    write(target/'configuration/runtime-upgrade-template.json',template)
    web=repo/'packages/tentacles/Services/Interfaces/web_interface'
    for relative in ('templates/v13_m1_review.html','static/js/common/v13_m1_weekly.js'):
        f=target/'ui'/Path(relative).name;shutil.copyfile(web/relative,f);os.chown(f,0,30910);f.chmod(0o440)
    manifest=dict(scope='M1_TRANSITION_V2_PREPARED_NOT_ACTIVATED',prepared_at=dt.datetime.now(dt.timezone.utc).isoformat(),
                  candidate_id=proposal['candidate_id'],proposal_id=proposal['proposal_id'],account=proposal['account'],
                  runtime=str(runtime),runtime_files=pins,files={str(f.relative_to(target)):sha(f) for f in target.rglob('*') if f.is_file()},
                  image_id=subprocess.check_output(['docker','image','inspect','octobot-local:dev','--format','{{.Id}}'],text=True).strip(),
                  activation_helper_sha256=sha(repo/'scripts/activate_m1_transition_release.py'),
                  compose_sha256=sha(repo/'docker-compose.v13-m1-transition.yml'),
                  web_code_pins={f'octobot/ai_strategy_lab/{name}':pins[f'octobot/ai_strategy_lab/{name}'] for name in ('v13_m1_management_web.py','v13_m1_weekly.py','v13_m1_transition.py')},
                  required_services=['octobot-v13-m1-paper','octobot-m1-approval-broker','octobot-local'],
                  operator_manual_deploy_required=True,rebalance_approved=False,orders_authorized=False,
                  source_snapshot_sha256=sha(args.snapshot))
    write(target/'release-manifest.json',manifest)
    print(json.dumps(dict(prepared=True,activated=False,proposal_id=proposal['proposal_id'],runtime_files=len(pins))))


if __name__=='__main__':main()
