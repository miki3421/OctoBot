"""Prepare the operator-requested successor. Never stops or starts services."""
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

ROOT=Path('/root/auto_trading_sys')
CHANGED=('v13_m1_successor.py','v13_m1_weekly.py','v13_m1_approval_broker.py','v13_m1_paper.py','v13_m1_paper_view.py')


def sha(path):return hashlib.sha256(Path(path).read_bytes()).hexdigest()
def write(path,value):
    path.write_text(json.dumps(value,indent=2)+'\n');os.chown(path,0,30910);path.chmod(0o440)
def snapshot(source,target):
    a=sqlite3.connect(source.resolve().as_uri()+'?mode=ro',uri=True,timeout=1);b=sqlite3.connect(target);began=time.monotonic()
    def progress(*_):
        if time.monotonic()-began>4:raise ValueError('bounded_snapshot_timeout')
    try:a.backup(b,pages=512,progress=progress,sleep=.005)
    finally:a.close();b.close()
    c=sqlite3.connect(target.resolve().as_uri()+'?mode=ro',uri=True)
    try:
        if c.execute('PRAGMA integrity_check').fetchone()[0]!='ok':raise ValueError('snapshot_integrity')
    finally:c.close()
    target.chmod(0o440)


def main():
    a=argparse.ArgumentParser();a.add_argument('--proposal-only',action='store_true');a.add_argument('--remaining',default='0.5,0.25,0');a.add_argument('--suffix',default='v1');args=a.parse_args()
    if args.proposal_only:
        from octobot.ai_strategy_lab import v13_m1_successor as s
        e=Path('/evidence');data=json.loads((e/'proposal-input.json').read_text())
        p=s.proposal(data['parent'],data['state'],data['science'],data['market'],data['at'],remaining=data['remaining'])
        (e/'proposal.json').write_text(json.dumps(p,indent=2)+'\n')
        print(json.dumps(dict(proposal=p['proposal_id'],summary=p['summary'],changes=p['indicative_changes'])));return
    if os.geteuid()!=0:raise ValueError('root_preparer_required')
    repo=ROOT/'octobot-source';target=ROOT/'octobot-local'/('v13-m1-successor-'+args.suffix);runtime=Path('/opt')/('v13-m1-successor-runtime-'+args.suffix)
    e=ROOT/'audit-evidence/m1-successor-20261025'/args.suffix
    if target.exists() or runtime.exists() or e.exists():raise ValueError('new_immutable_release_required')
    e.mkdir(parents=True,mode=0o750);os.chown(e,0,30910)
    snapshot(ROOT/'octobot-local/v13-m1-paper-v1/state/account.sqlite',e/'m1.sqlite')
    snapshot(ROOT/'octobot-local/v13-m1-management-v1/approvals/approvals.sqlite',e/'approvals.sqlite')
    db=sqlite3.connect((e/'m1.sqlite').as_uri()+'?mode=ro',uri=True)
    state=json.loads(db.execute('SELECT payload FROM state WHERE id=1').fetchone()[0])
    control=json.loads(db.execute("SELECT payload FROM m1_meta WHERE key='control'").fetchone()[0])
    if control['phase']!='NORMAL' or control.get('pending') or db.execute("SELECT 1 FROM m1_meta WHERE key='management_policy'").fetchone():raise ValueError('unmanaged_normal_required')
    identity=json.loads(db.execute("SELECT payload FROM m1_meta WHERE key='identity'").fetchone()[0]);db.close()
    old=ROOT/'octobot-local/v13-m1-management-v2-r2/configuration'
    source=ROOT/'octobot-local/v13-m1-management-v1/source'
    science=json.loads((source/'science.json').read_text());market=json.loads((source/'market.json').read_text())
    for s,pos in state['positions'].items():pos['current_price']=market['quotes'][s]['mark_price']
    data=dict(state=state,parent=json.loads((old/'transition-proposal.json').read_text()),science=science,market=market,
              at=dt.datetime.now(dt.timezone.utc).isoformat(),remaining=[float(v) for v in args.remaining.split(',')])
    write(e/'proposal-input.json',data)
    image=subprocess.check_output(['docker','image','inspect','octobot-local:dev','--format','{{.Id}}'],text=True).strip()
    subprocess.run(['docker','run','--rm','--pull=never','--network','none','--read-only','--memory','768m','--cpus','1',
        '--tmpfs','/tmp:rw,size=128m','-e','PYTHONPATH=/workspace','-e','PYTHONDONTWRITEBYTECODE=1',
        '-v',str(repo)+':/workspace:ro','-v',str(e)+':/evidence:rw','--entrypoint','python3',image,
        '-B','/workspace/scripts/prepare_m1_successor.py','--proposal-only'],check=True)
    proposal=json.loads((e/'proposal.json').read_text());os.chown(e/'proposal.json',0,30910);(e/'proposal.json').chmod(0o440)
    shutil.copytree('/opt/v13-m1-paper-runtime-v4.1',runtime)
    for name in CHANGED:
        f=runtime/'octobot/ai_strategy_lab'/name
        if f.exists():f.chmod(0o644)
        shutil.copyfile(repo/'octobot/ai_strategy_lab'/name,f)
    pins={str(f.relative_to(runtime)):sha(f) for f in runtime.rglob('*') if f.is_file() and '__pycache__' not in f.parts}
    for f in runtime.rglob('*'):
        if f.is_symlink():raise ValueError('runtime_symlink')
        os.chown(f,0,0);f.chmod(0o555 if f.is_dir() else 0o444)
    runtime.chmod(0o555)
    for folder in (target,target/'configuration',target/'ui'):
        folder.mkdir(parents=True,exist_ok=True);os.chown(folder,0,30910);folder.chmod(0o750)
    config=json.loads((old/'config.json').read_text());protocol=json.loads((old/'protocol.json').read_text())
    for name in CHANGED:config['management']['code_pins']['octobot/ai_strategy_lab/'+name]=pins['octobot/ai_strategy_lab/'+name]
    protocol['source_code_pins'].update(config['management']['code_pins']);protocol['management_extension']='M1_GRADUAL_LONG_SHORT_V3'
    protocol['strategy']['normal']='Monotone LONG quantities with confirmed staged reductions; independent unchanged M1 SHORT capacity; same account and no automatic LONG restoration'
    config['management'].update(transition_proposal='/configuration/successor-proposal.json',transition_sha256=sha(e/'proposal.json'))
    config['successor']=dict(proposal='/configuration/successor-proposal.json',proposal_sha256=sha(e/'proposal.json'),authority='/configuration/successor-authority.json')
    write(target/'configuration/config.json',config);write(target/'configuration/protocol.json',protocol)
    shutil.copyfile(e/'proposal.json',target/'configuration/successor-proposal.json');os.chown(target/'configuration/successor-proposal.json',0,30910);(target/'configuration/successor-proposal.json').chmod(0o440)
    broker=json.loads((old/'broker.json').read_text())
    broker.update(successor_only=True,replacement_proposal_id=proposal['proposal_id'])
    write(target/'configuration/broker.json',broker)
    write(target/'configuration/runtime-upgrade-template.json',dict(scope='M1_GRADUAL_LONG_SHORT_V3',account=proposal['account'],from_identity=identity,
        to_identity=dict(seed=identity['seed'],protocol=sha(target/'configuration/protocol.json'),runner=pins['octobot/ai_strategy_lab/v13_m1_paper.py']),
        authorized_at=None,owner_reference='PENDING_MANUAL_OPERATOR_DEPLOY',backup_sha256=sha(e/'m1.sqlite')))
    web=repo/'packages/tentacles/Services/Interfaces/web_interface'
    relatives=['static/js/common/v13_m1_weekly.js','static/js/common/v13_variants_lifecycle.js','templates/v13_m1_review.html','templates/v13_variants.html','templates/components/lab_sidebar.html']
    for relative in relatives:
        body=(web/relative).read_text()
        if relative.endswith('lab_sidebar.html'):
            body=body.replace('>V13 + M1 SHORT</a>','>M1 · gestione graduale + SHORT</a>').replace('>Simboli · V13 + M1 SHORT</a>','>Simboli · M1 graduale + SHORT</a>')
        for script in ('v13_m1_weekly','v13_variants_lifecycle'):
            import re
            body=re.sub(script+r'\.js\?v=[a-zA-Z0-9]+',script+'.js?v='+sha(web/'static/js/common'/(script+'.js'))[:16],body)
        f=target/'ui'/Path(relative).name;f.write_text(body);os.chown(f,0,30910);f.chmod(0o440)
    compose=(repo/'docker-compose.v13-m1-transition.yml').read_text().replace('v13_m1_managed','v13_m1_successor').replace('/opt/v13-m1-paper-runtime-v4.1',str(runtime)).replace(str(ROOT/'octobot-local/v13-m1-management-v2-r2'),str(target)).replace('transition-proposal.json','successor-proposal.json')
    compose=compose.replace('      - '+str(target)+'/configuration/successor-proposal.json:/configuration/successor-proposal.json:ro',
        '      - '+str(target)+'/configuration/successor-proposal.json:/configuration/successor-proposal.json:ro\n      - '+str(target)+'/configuration/successor-authority.json:/configuration/successor-authority.json:ro')
    f=target/'compose.yml';f.write_text(compose);os.chown(f,0,30910);f.chmod(0o440)
    manifest=dict(scope='M1_SUCCESSOR_PREPARED_MANUAL_REPLACEMENT',prepared_at=dt.datetime.now(dt.timezone.utc).isoformat(),
        proposal_id=proposal['proposal_id'],account=proposal['account'],runtime=str(runtime),runtime_files=pins,
        files={str(f.relative_to(target)):sha(f) for f in target.rglob('*') if f.is_file()},image_id=image,
        helper_sha256=sha(repo/'scripts/activate_m1_successor.py'),ui_paths=relatives,
        services=['octobot-v13-m1-paper','octobot-m1-approval-broker','octobot-local'],
        source_snapshot_sha256=sha(e/'m1.sqlite'),new_account=False,operator_manual_deploy_required=True)
    write(target/'release-manifest.json',manifest)
    print(json.dumps(dict(prepared=True,release=str(target),manifest=sha(target/'release-manifest.json'),proposal_id=proposal['proposal_id'])))


if __name__=='__main__':main()
