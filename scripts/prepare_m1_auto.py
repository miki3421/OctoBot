"""Prepare immutable automatic-review continuation; no service mutations."""
import argparse
import datetime as dt
import json
import os
from pathlib import Path
import re
import shutil
import sqlite3
from prepare_m1_successor import ROOT,sha,write,snapshot


def main():
    parser=argparse.ArgumentParser();parser.add_argument('--suffix',required=True);parser.add_argument('--allow-admissions',action='store_true');args=parser.parse_args()
    repo=ROOT/'octobot-source';old=ROOT/'octobot-local/v13-m1-successor-v6'
    release=ROOT/'octobot-local'/('v13-m1-auto-'+args.suffix);runtime=Path('/opt')/('v13-m1-auto-runtime-'+args.suffix)
    evidence=ROOT/'audit-evidence/m1-auto-20261025'/args.suffix
    if not re.fullmatch(r'v[0-9]+',args.suffix) or any(p.exists() for p in (release,runtime,evidence)):raise ValueError('new_release_required')
    evidence.mkdir(parents=True,mode=0o750);os.chown(evidence,0,30910)
    snapshot(ROOT/'octobot-local/v13-m1-paper-v1/state/account.sqlite',evidence/'m1.sqlite')
    snapshot(ROOT/'octobot-local/v13-m1-management-v1/approvals/approvals.sqlite',evidence/'approvals.sqlite')
    db=sqlite3.connect((evidence/'m1.sqlite').as_uri()+'?mode=ro',uri=True)
    meta=lambda k:json.loads(db.execute('SELECT payload FROM m1_meta WHERE key=?',(k,)).fetchone()[0])
    identity=meta('identity');epoch=meta('strategy_successor');db.close()
    shutil.copytree('/opt/v13-m1-successor-runtime-v6',runtime)
    changed=['v13_m1_auto.py','v13_m1_successor.py','v13_m1_weekly.py','v13_m1_paper.py']
    for name in changed:
        target=runtime/'octobot/ai_strategy_lab'/name
        if target.exists():target.chmod(0o644)
        shutil.copyfile(repo/'octobot/ai_strategy_lab'/name,target)
    pins={str(f.relative_to(runtime)):sha(f) for f in runtime.rglob('*') if f.is_file() and '__pycache__' not in f.parts}
    for f in runtime.rglob('*'):
        if f.is_symlink():raise ValueError('runtime_symlink')
        os.chown(f,0,0);f.chmod(0o555 if f.is_dir() else 0o444)
    runtime.chmod(0o555)
    for folder in (release,release/'configuration',release/'ui'):
        folder.mkdir(parents=True,exist_ok=True);os.chown(folder,0,30910);folder.chmod(0o750)
    for name in ('successor-proposal.json','successor-authority.json'):
        write(release/'configuration'/name,json.loads((old/'configuration'/name).read_text()))
    write(release/'configuration/genesis-upgrade.json',json.loads((old/'configuration/runtime-upgrade.json').read_text()))
    cfg=json.loads((old/'configuration/config.json').read_text());protocol=json.loads((old/'configuration/protocol.json').read_text())
    for name in changed:cfg['management']['code_pins']['octobot/ai_strategy_lab/'+name]=pins['octobot/ai_strategy_lab/'+name]
    protocol['source_code_pins'].update(cfg['management']['code_pins']);protocol['management_extension']='M1_DELEGATED_AUTOMATIC_REVIEW_V1'
    cfg['successor']['genesis_upgrade']='/configuration/genesis-upgrade.json'
    # Read the pure constants without importing the numerical runtime on host.
    import ast
    tree=ast.parse((repo/'octobot/ai_strategy_lab/v13_m1_auto.py').read_text())
    rule_node=next(n.value for n in tree.body if isinstance(n,ast.Assign) and any(isinstance(t,ast.Name) and t.id=='RULES' for t in n.targets))
    rules=eval(compile(ast.Expression(rule_node),'rules','eval'),{'__builtins__':{},'dict':dict})
    p=json.loads((old/'configuration/successor-proposal.json').read_text())
    from activate_m1_successor import digest
    authority=dict(scope='M1_PAPER_DELEGATED_WEIGHTED_REVIEW',account=p['account'],genesis_activation_id=epoch['activation_id'],
        authorized_at=dt.datetime.now(dt.timezone.utc).isoformat(),enabled=True,allow_admissions=args.allow_admissions,
        operator_reference='Operator requests weighted automatic M1 approval with daily review, preserving SHORT budget and no mechanical repurchases',
        rules=rules,short_caps=p['short_caps'],long_budget=sum(p['long_caps'].values()))
    authority['delegation_id']=digest(authority);write(release/'configuration/automatic-authority.json',authority)
    cfg['automatic_review']=dict(authority='/configuration/automatic-authority.json',sha256=sha(release/'configuration/automatic-authority.json'))
    write(release/'configuration/config.json',cfg);write(release/'configuration/protocol.json',protocol)
    write(release/'configuration/runtime-upgrade-template.json',dict(scope='M1_DELEGATED_AUTOMATIC_REVIEW_V1',account=p['account'],from_identity=identity,
        to_identity=dict(seed=identity['seed'],protocol=sha(release/'configuration/protocol.json'),runner=pins['octobot/ai_strategy_lab/v13_m1_paper.py']),
        authorized_at=None,owner_reference='PENDING_SCOPED_DEPLOY',backup_sha256=None))
    web=repo/'packages/tentacles/Services/Interfaces/web_interface'
    js=web/'static/js/common/v13_m1_weekly.js';shutil.copyfile(js,release/'ui'/js.name)
    html=re.sub(r'v13_m1_weekly.js\?v=[a-zA-Z0-9]+','v13_m1_weekly.js?v='+sha(js)[:16],(web/'templates/v13_m1_review.html').read_text())
    (release/'ui/v13_m1_review.html').write_text(html)
    for f in (release/'ui').iterdir():os.chown(f,0,30910);f.chmod(0o440)
    compose=(old/'compose.yml').read_text().split('  m1-approval:')[0].replace(str(old),str(release)).replace('/opt/v13-m1-successor-runtime-v6',str(runtime)).replace('v13_m1_successor','v13_m1_auto')
    for name in ('genesis-upgrade','automatic-authority'):
        compose=compose.replace('    volumes:\n','    volumes:\n      - '+str(release)+'/configuration/'+name+'.json:/configuration/'+name+'.json:ro\n',1)
    (release/'compose.yml').write_text(compose);os.chown(release/'compose.yml',0,30910);(release/'compose.yml').chmod(0o440)
    m=dict(scope='M1_AUTO_REVIEW_PREPARED',runtime=str(runtime),account=p['account'],delegation_id=authority['delegation_id'],
        runtime_files=pins,files={str(f.relative_to(release)):sha(f) for f in release.rglob('*') if f.is_file()},
        evidence=str(evidence),helper_sha256=sha(repo/'scripts/activate_m1_auto.py'),image_id='sha256:7e825796375e06e3cfb6ea46b5b7202bdba4c0bb998bdffea5e02b8bd9d67575')
    write(release/'release-manifest.json',m)
    print(json.dumps(dict(prepared=True,release=str(release),manifest=sha(release/'release-manifest.json'),evidence=str(evidence))))


if __name__=='__main__':main()
