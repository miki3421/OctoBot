"""Prepare, explicitly cut over, or verify the single Original paper successor.

Preparation never stops a service or grants authority. Cutover requires root,
the exact prepared manifest and a manual operator reference. Historical rows
are never restored over a continuing account, including during recovery.
"""
import argparse
import copy
import datetime as dt
import hashlib
import json
import os
from pathlib import Path
import shutil
import sqlite3
import subprocess
import time

NAME='octobot-v13-research-executor'
ISSUER='octobot-v13-research-issuer'
MODULE='octobot.ai_strategy_lab.v13_original_structural'
PROTOCOL='docs/research-protocols/original-m1-structural-successor-v2.json'


def run(*args, **kwargs):
    return subprocess.check_output(list(args),text=True,**kwargs).strip()


def sha(path):return hashlib.sha256(Path(path).read_bytes()).hexdigest()
def digest(value):return hashlib.sha256(json.dumps(value,sort_keys=True,separators=(',',':'),allow_nan=False).encode()).hexdigest()


def write(path,value,mode=0o440):
    path=Path(path);tmp=path.with_suffix('.pending');tmp.write_text(json.dumps(value,indent=2)+'\n')
    os.chown(tmp,0,30910);tmp.chmod(mode);tmp.replace(path)


def inspection(name):return json.loads(run('docker','inspect',name))[0]


def containers():
    names=run('docker','ps','--filter','name=octobot-','--format','{{.Names}}').splitlines()
    fmt='{{json .Name}}|{{json .Id}}|{{json .State.StartedAt}}|{{json .RestartCount}}|{{if .State.Health}}{{json .State.Health.Status}}{{else}}null{{end}}'
    values={}
    for n in names:
        parts=[json.loads(v) for v in run('docker','inspect','--format',fmt,n).split('|')]
        values[n]=dict(zip(('name','id','started','restarts','health'),parts))
    return values


def snapshot(source,target):
    source=Path(source);target=Path(target)
    a=sqlite3.connect(source.as_uri()+'?mode=ro',uri=True);a.execute('PRAGMA query_only=ON')
    b=sqlite3.connect(target);a.backup(b)
    if b.execute('PRAGMA integrity_check').fetchone()[0]!='ok':raise ValueError('backup_integrity')
    a.close();b.close();target.chmod(0o440)


def prepare(root,release):
    if os.geteuid()!=0 or release.exists():raise ValueError('root_new_release_required')
    repo=root/'octobot-source';c=json.loads((root/'octobot-local/v13-paper/research/runtime-config.json').read_text())
    old=inspection(NAME);old_issuer=inspection(ISSUER)
    if any(v['State'].get('Health',{}).get('Status')!='healthy' for v in [old,old_issuer]):raise ValueError('predecessor_not_healthy')
    release.mkdir(mode=0o750,parents=True);os.chown(release,0,30910)
    runtime=release/'runtime';runtime.mkdir()
    shutil.copytree(repo/'octobot',runtime/'octobot',ignore=shutil.ignore_patterns('__pycache__','*.pyc'))
    shutil.copytree(repo/'docs/contracts',runtime/'docs/contracts')
    shutil.copytree(repo/'docs/research-protocols',runtime/'docs/research-protocols')
    for n,h in c['code_pins'].items():
        source=repo/n
        if sha(source)!=h:raise ValueError('legacy_code_changed:'+n)
        target=runtime/n;target.parent.mkdir(parents=True,exist_ok=True)
        if not target.exists():shutil.copyfile(source,target)
    for path in runtime.rglob('*'):
        os.chown(path,0,30910);path.chmod(0o550 if path.is_dir() else 0o440)
    os.chown(runtime,0,30910);runtime.chmod(0o550)
    config=release/'configuration';config.mkdir();os.chown(config,0,30910);config.chmod(0o750)
    policy=json.loads((repo/PROTOCOL).read_text())
    pins={n:sha(repo/n) for n in [PROTOCOL,'octobot/ai_strategy_lab/v13_original_structural.py',
        'octobot/ai_strategy_lab/v13_m1_short_risk.py','octobot/ai_strategy_lab/v13_m1_short_structure.py',
        'octobot/ai_strategy_lab/v13_m1_future.py']}
    template=dict(scope='MANUAL_ORIGINAL_STRUCTURAL_PAPER_CUTOVER',account=c['account'],protocol_id=policy['protocol_id'],
        real_orders_authorized=False,protocol=policy,
        parent=json.loads((repo/'docs/research-protocols/m1-short-risk-exits-candidate-v1.json').read_text()),
        structure=json.loads((repo/'docs/research-protocols/m1-short-structural-invalidation-v1.json').read_text()),code_pins=pins)
    write(config/'authority-template.json',template)
    compose=json.loads((repo/'docker-compose.v13-research.yml').read_text())
    services={}
    ledger_mount=next(v['Source'] for v in old['Mounts'] if v['Destination']=='/execution')
    for role,info in [('executor',old),('issuer',old_issuer)]:
        service=copy.deepcopy(compose['services'][role]);service.pop('depends_on',None);service.pop('profiles',None)
        service.update(image=info['Image'],mem_limit='512m' if role=='executor' else '256m',cpus=1.0 if role=='executor' else .5)
        volumes=[]
        for mount in info['Mounts']:
            if mount['Type']!='bind':raise ValueError('unexpected_role_mount')
            source=str(runtime) if mount['Destination']=='/workspace' else mount['Source']
            volumes.append(source+':'+mount['Destination']+('' if mount['RW'] else ':ro'))
        if role=='issuer':volumes.append(ledger_mount+':/execution:ro')
        service['volumes']=volumes+[str(config/'authority.json')+':/successor-authority.json:ro']
        service['entrypoint']=['python3','-B','-m',MODULE,role,'--config','/runtime-config.json','--poll','20',
            '--successor-authority','/successor-authority.json','--successor-authority-sha256','AUTHORITY_SHA256_REQUIRED']
        services[role]=service
    write(release/'compose-template.json',dict(version='2.4',services=services))
    runtime_files={str(p.relative_to(runtime)):sha(p) for p in runtime.rglob('*') if p.is_file()}
    ui=['octobot/ai_strategy_lab/v13_m1_paper_view.py','octobot/ai_strategy_lab/v13_original_structural_view.py',
        'packages/tentacles/Services/Interfaces/web_interface/static/js/common/v13_variants_lifecycle.js']
    manifest=dict(scope='ORIGINAL_STRUCTURAL_SINGLE_ACCOUNT_PREPARED_NOT_ACTIVATED',account=c['account'],
        image_id=old['Image'],predecessor_container_id=old['Id'],legacy_config_sha256=sha(root/'octobot-local/v13-paper/research/runtime-config.json'),
        predecessor_issuer_id=old_issuer['Id'],
        helper_sha256=sha(Path(__file__)),runtime=str(runtime),runtime_files=runtime_files,
        files={str(p.relative_to(release)):sha(p) for p in [config/'authority-template.json',release/'compose-template.json']},
        web_code_pins={n:sha(repo/n) for n in ui},protocol_id=policy['protocol_id'],
        git_head=run('git','-c','safe.directory='+str(repo),'-C',str(repo),'rev-parse','HEAD'),
        activated=False,operator_acceptance_pending=True)
    write(release/'release-manifest.json',manifest)
    print(json.dumps(dict(prepared=True,release=str(release),manifest_sha256=sha(release/'release-manifest.json'))))


def verify(root,release,expected):
    p=release/'release-manifest.json'
    if sha(p)!=expected:raise ValueError('exact_manifest_required')
    m=json.loads(p.read_text())
    if m['scope']!='ORIGINAL_STRUCTURAL_SINGLE_ACCOUNT_PREPARED_NOT_ACTIVATED' or m['account']!='v13-paper-v2':raise ValueError('release_scope')
    if sha(Path(__file__))!=m['helper_sha256']:raise ValueError('helper_changed')
    for n,h in m['runtime_files'].items():
        f=Path(m['runtime'])/n
        if f.is_symlink() or f.stat().st_uid!=0 or f.stat().st_mode&0o022 or sha(f)!=h:raise ValueError('runtime_changed:'+n)
    for n,h in m['files'].items():
        if sha(release/n)!=h:raise ValueError('release_changed:'+n)
    for n,h in m['web_code_pins'].items():
        if sha(root/'octobot-source'/n)!=h:raise ValueError('web_code_changed:'+n)
    if sha(root/'octobot-local/v13-paper/research/runtime-config.json')!=m['legacy_config_sha256']:raise ValueError('legacy_config_changed')
    return m


def activate(root,release,expected,reference):
    if os.geteuid()!=0 or not reference or len(reference)>240:raise ValueError('manual_operator_reference_required')
    m=verify(root,release,expected)
    if inspection(NAME)['Id']!=m['predecessor_container_id']:raise ValueError('predecessor_identity_changed')
    if inspection(ISSUER)['Id']!=m['predecessor_issuer_id']:raise ValueError('issuer_identity_changed')
    if (release/'activation-result.json').exists() or (release/'configuration/authority.json').exists():raise ValueError('activation_already_started_review_checkpoint')
    before=containers();write(release/'containers-before.json',before)
    ledger=root/'octobot-local/v13-paper/research/execution'
    write(release/'activation-checkpoint.json',dict(phase='BEFORE_ORIGINAL_ROLES_STOP',manifest_sha256=expected))
    # Only Original's two trusted roles stop. Shared capture/producer and all
    # five other accounts continue; the new issuer remains a separate UID.
    run('docker','stop','--time','30',ISSUER)
    run('docker','stop','--time','30',NAME)
    recover=sqlite3.connect(ledger/'execution.sqlite');recover.execute('PRAGMA quick_check').fetchone();recover.close()
    backup=release/'stopped-original.sqlite';snapshot(ledger/'execution.sqlite',backup)
    snapshot(root/'octobot-local/v13-paper/research/approvals/approvals.sqlite',release/'stopped-approvals.sqlite')
    db=sqlite3.connect(backup.as_uri()+'?mode=ro',uri=True)
    s=json.loads(db.execute('SELECT payload FROM state WHERE id=1').fetchone()[0]);db.close()
    if s.get('pending') or any(p['quantity']<0 for p in s['positions'].values()):
        run('docker','start',ISSUER,NAME);raise ValueError('boundary_not_ready_predecessors_resumed')
    a=json.loads((release/'configuration/authority-template.json').read_text())
    now=dt.datetime.now(dt.timezone.utc)
    policy=dict(a['protocol']['risk'],version='risk-policy-original-structural-v1',missing_gates=[])
    a.update(operator_reference=reference,activated_at=now.isoformat(),boundary_state_hash=digest(s),
        boundary_orders=s['order_count'],backup_sha256=sha(backup))
    a['authority_id']=digest(a)
    identity=dict(account='v13-paper-v2',strategy=a['protocol']['strategy'],lineage_hash=digest(dict(
        protocol=a['protocol_id'],authority=a['authority_id'])),risk_policy=policy['version'],
        risk_policy_hash=digest(policy),authorization_id='original-structural-'+now.strftime('%Y%m%dT%H%M%SZ'),environment='paper')
    a['identity']=identity;write(release/'configuration/authority.json',a)
    c=json.loads((root/'octobot-local/v13-paper/research/runtime-config.json').read_text())
    control=root/'octobot-local/v13-paper/research/control'
    if not control.is_dir():raise ValueError('existing_global_authorization_required')
    write(release/'registry-before.json',json.loads((control/'registry.json').read_text()))
    code="import json,datetime as d;from pathlib import Path;from octobot.ai_strategy_lab import paper_authorization as p;from octobot.ai_strategy_lab.paper_authorization_admin import Admin;a=json.load(open('/configuration/authority.json'));v=(p.now()+d.timedelta(seconds=5)).isoformat();Admin('/control').grant(p.Identity(**a['identity']),valid_from=v);print('New scoped research-paper grant recorded')"
    run('docker','run','--rm','--pull=never','--network','none','--read-only','--cap-drop','ALL','--user','0:0','--group-add','30910',
        '--tmpfs','/tmp:rw,nosuid,size=32m','-e','PYTHONDONTWRITEBYTECODE=1','-e','PYTHONPATH=/workspace',
        '-v',str(root/'octobot-source')+':/workspace:ro','-v',str(control)+':/control:rw',
        '-v',str(release/'configuration')+':/configuration:ro','--entrypoint','python3',m['image_id'],'-c',code)
    retired={n:n+'-original-retired-'+now.strftime('%Y%m%dT%H%M%SZ') for n in [NAME,ISSUER]}
    for n,newname in retired.items():
        run('docker','update','--restart=no',n);run('docker','rename',n,newname)
    compose=json.loads((release/'compose-template.json').read_text())
    for service in compose['services'].values():service['entrypoint'][-1]=sha(release/'configuration/authority.json')
    write(release/'compose.json',compose)
    write(release/'activation-checkpoint.json',dict(phase='PREDECESSOR_STOPPED_NEW_STARTING',retired_container=retired,
        authority_sha256=sha(release/'configuration/authority.json'),backup_sha256=sha(backup),account='v13-paper-v2'))
    run('docker-compose','-p','original-structural-v2','-f',str(release/'compose.json'),'config','-q')
    run('docker-compose','-p','original-structural-v2','-f',str(release/'compose.json'),'up','-d','issuer','executor')
    deadline=time.monotonic()+180
    projection=None
    while time.monotonic()<deadline:
        info=inspection(NAME)
        path=ledger/'structural-successor.json'
        if path.exists():
            projection=json.loads(path.read_text())
            if (info['State'].get('Health',{}).get('Status')=='healthy' and inspection(ISSUER)['State'].get('Health',{}).get('Status')=='healthy' and projection.get('protocol_id')==a['protocol_id']
                    and not projection.get('status','').startswith('AUTHORIZATION_DENIED:')):break
        time.sleep(2)
    else:raise ValueError('new_executor_requires_review_no_automatic_ledger_rewind')
    run('docker','restart','octobot-local')
    after=containers()
    for n,v in before.items():
        if n not in {NAME,ISSUER,'octobot-local'} and any(after.get(n,{}).get(k)!=v[k] for k in ('id','started','restarts')):
            raise ValueError('other_service_changed:'+n)
    write(release/'activation-result.json',dict(activated=True,authority_id=a['authority_id'],protocol_id=a['protocol_id'],
        account='v13-paper-v2',retired_container=retired,boundary=projection['boundary'],projection=projection,
        other_service_identities_and_starts_unchanged=True,containers=after,scientific_validity='UNASSESSED',
        operator_acceptance_pending=True))
    print(json.dumps(dict(activated=True,account='v13-paper-v2',boundary=projection['boundary'],retired_container=retired)))


if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('phase',choices=['prepare','verify','activate'])
    parser.add_argument('--root',type=Path,default=Path('/root/auto_trading_sys'));parser.add_argument('--release',type=Path,required=True)
    parser.add_argument('--manifest-sha256');parser.add_argument('--manual-operator-reference')
    args=parser.parse_args();root=args.root.resolve();release=args.release.resolve()
    if args.phase=='prepare':prepare(root,release)
    elif args.phase=='verify':verify(root,release,args.manifest_sha256);print('Prepared release verified; no activation')
    else:activate(root,release,args.manifest_sha256,args.manual_operator_reference)
