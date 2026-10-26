"""Immutable M1 scientific-scope correction; preserve all prior authorities."""
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
    p=argparse.ArgumentParser();p.add_argument('--suffix',required=True);a=p.parse_args()
    if not re.fullmatch('v[0-9]+',a.suffix):raise ValueError('release_suffix')
    old=ROOT/'octobot-local/v13-m1-auto-v6';repo=ROOT/'octobot-source'
    target=ROOT/'octobot-local'/('v13-m1-scope-fix-'+a.suffix);runtime=Path('/opt')/('v13-m1-scope-fix-runtime-'+a.suffix)
    evidence=ROOT/'audit-evidence/lab-fixes-20261026'/a.suffix
    if any(x.exists() for x in (target,runtime,evidence)):raise ValueError('new_immutable_release_required')
    evidence.mkdir(parents=True,mode=0o750);os.chown(evidence,0,30910)
    snapshot(ROOT/'octobot-local/v13-m1-paper-v1/state/account.sqlite',evidence/'m1.sqlite')
    shutil.copytree('/opt/v13-m1-auto-runtime-v6',runtime)
    relative='octobot/ai_strategy_lab/v13_m1_managed.py';(runtime/relative).chmod(0o644);shutil.copyfile(repo/relative,runtime/relative)
    pins={str(f.relative_to(runtime)):sha(f) for f in runtime.rglob('*') if f.is_file() and '__pycache__' not in f.parts}
    for f in runtime.rglob('*'):os.chown(f,0,0);f.chmod(0o555 if f.is_dir() else 0o444)
    runtime.chmod(0o555)
    for f in (target,target/'configuration'):f.mkdir(parents=True,exist_ok=True);os.chown(f,0,30910);f.chmod(0o750)
    for name in ('successor-proposal','successor-authority','genesis-upgrade','automatic-authority'):
        shutil.copyfile(old/'configuration'/(name+'.json'),target/'configuration'/(name+'.json'));os.chown(target/'configuration'/(name+'.json'),0,30910);(target/'configuration'/(name+'.json')).chmod(0o440)
    cfg=json.loads((old/'configuration/config.json').read_text());protocol=json.loads((old/'configuration/protocol.json').read_text())
    cfg['management']['code_pins'][relative]=pins[relative];protocol['source_code_pins'][relative]=pins[relative]
    protocol['management_input_scope_note']='Frozen original scientific universe verified independently of managed execution membership'
    write(target/'configuration/config.json',cfg);write(target/'configuration/protocol.json',protocol)
    d=sqlite3.connect((evidence/'m1.sqlite').as_uri()+'?mode=ro',uri=True);identity=json.loads(d.execute("SELECT payload FROM m1_meta WHERE key='identity'").fetchone()[0]);d.close()
    write(target/'configuration/runtime-upgrade-template.json',dict(scope='M1_DELEGATED_AUTOMATIC_REVIEW_V1',account=json.loads((old/'configuration/automatic-authority.json').read_text())['account'],from_identity=identity,
        to_identity=dict(seed=identity['seed'],protocol=sha(target/'configuration/protocol.json'),runner=pins['octobot/ai_strategy_lab/v13_m1_paper.py']),authorized_at=None,owner_reference='PENDING_SCOPE_FIX_DEPLOY',backup_sha256=None))
    compose=(old/'compose.yml').read_text().replace(str(old),str(target)).replace('/opt/v13-m1-auto-runtime-v6',str(runtime))
    (target/'compose.yml').write_text(compose);os.chown(target/'compose.yml',0,30910);(target/'compose.yml').chmod(0o440)
    m=dict(scope='M1_SCIENTIFIC_SCOPE_CORRECTION_PREPARED',runtime=str(runtime),evidence=str(evidence),
        files={str(f.relative_to(target)):sha(f) for f in target.rglob('*') if f.is_file()},runtime_files=pins,
        helper_sha256=sha(repo/'scripts/activate_m1_scope_fix.py'),image_id='sha256:7e825796375e06e3cfb6ea46b5b7202bdba4c0bb998bdffea5e02b8bd9d67575')
    write(target/'release-manifest.json',m);print(json.dumps(dict(release=str(target),manifest=sha(target/'release-manifest.json'),evidence=str(evidence))))


if __name__=='__main__':main()
