"""Offline browser-to-runner test on a private full copy, never a live ledger.

Run only with /fixture writable and /input, /prepared, /runtime and /actual-seed RO.
The network namespace is disabled; browser shares only its localhost namespace.
"""
import ast
import copy
import datetime as dt
import hashlib
import json
import os
from pathlib import Path
import shutil
import sqlite3
import subprocess
import sys
import threading
import time
import types
import flask

F=Path('/fixture');P=Path('/prepared');INPUT=Path('/input')
PASSWORD='fixture-only-v2-approval-password-20261024'


def save(path,value,uid=0,mode=0o440):
    path.write_text(json.dumps(value,indent=2)+'\n');os.chown(path,uid,30910);path.chmod(mode)


def demote(uid):
    def run():os.setgroups([]);os.setgid(30910);os.setuid(uid)
    return run


if len(sys.argv)>1 and sys.argv[1]=='source':
    from octobot.ai_strategy_lab import v13_research_source as source,v13_m1_weekly as w
    raw=json.load(open('/input/market.json'))
    while True:
        record=copy.deepcopy(raw);at=source.now().isoformat()
        record.update(observed_at_start=at,observed_at_end=at,capture_ids=[],fixture='CONTROL_FIXTURE_ONLY_SYNTHETIC_TIMES_FIXED_PRICES')
        for quote in record['quotes'].values():
            for key in ('timestamp','mark_timestamp','metadata_observed_at'):quote[key]=at
        record['record_hash']=w.digest({k:v for k,v in record.items() if k!='record_hash'})
        source.atomic('/fixture/source/market.json',record);time.sleep(2)

if len(sys.argv)>1 and sys.argv[1]=='runner':
    from octobot.ai_strategy_lab import v13_m1_managed as managed
    runner=managed.Runner(json.load(open('/fixture/config/config.json')))
    while True:
        runner.tick();runner.publish_management();time.sleep(2)

if os.geteuid()!=0 or F.exists() and list(F.iterdir()):raise ValueError('new_private_fixture_required')
F.mkdir(exist_ok=True);os.chown(F,0,30910);F.chmod(0o750)
for folder,uid in [('config',0),('state',30943),('projection',30943),('source',30944),('approvals',30945),('socket',30945)]:
    path=F/folder;path.mkdir();os.chown(path,uid,30910);path.chmod(0o750)
shutil.copyfile(INPUT/'original.sqlite',F/'config/original.sqlite');os.chown(F/'config/original.sqlite',0,30910);(F/'config/original.sqlite').chmod(0o440)
shutil.copyfile(INPUT/'m1.sqlite',F/'state/account.sqlite');os.chown(F/'state/account.sqlite',30943,30910);(F/'state/account.sqlite').chmod(0o640)
shutil.copyfile(INPUT/'approvals.sqlite',F/'approvals/approvals.sqlite');os.chown(F/'approvals/approvals.sqlite',30945,30910);(F/'approvals/approvals.sqlite').chmod(0o640)
config=json.load(open(P/'config.json'));config.update(repo='/runtime',db='/fixture/state/account.sqlite',protocol='/fixture/config/protocol.json',
    seed='/actual-seed/seed.sqlite',receipt='/actual-seed/clone-receipt.json',original='/fixture/config/original.sqlite',runtime_upgrade='/fixture/config/runtime-upgrade.json')
config['management'].update(scope='M1_WEEKLY_MANAGEMENT_CONTROL_TEST_V1',source='/fixture/source',approvals='/fixture/approvals/approvals.sqlite',projection='/fixture/projection/management.json',transition_proposal='/fixture/config/transition-proposal.json')
proposal=json.load(open(P/'transition-proposal.json'));proposal['data_mode']='CONTROL_FIXTURE_ONLY'
from octobot.ai_strategy_lab import v13_m1_weekly as w
proposal['proposal_id']=w.digest({k:v for k,v in proposal.items() if k!='proposal_id'})
save(F/'config/transition-proposal.json',proposal);config['management']['transition_sha256']=hashlib.sha256((F/'config/transition-proposal.json').read_bytes()).hexdigest()
save(F/'config/config.json',config);save(F/'config/protocol.json',json.load(open(P/'protocol.json')))
template=json.load(open(P/'runtime-upgrade-template.json'));template.update(authorized_at=dt.datetime.now(dt.timezone.utc).isoformat(),owner_reference='CONTROL_FIXTURE_ONLY_PRIVATE_COPY_NOT_ACTIVATION')
save(F/'config/runtime-upgrade.json',template)
salt=b'v2-private-fixture-salt-20261024';save(F/'config/verifier.json',dict(algorithm='scrypt-v1',salt=salt.hex(),scrypt=hashlib.scrypt(PASSWORD.encode(),salt=salt,n=16384,r=8,p=1,dklen=32).hex()))
broker=json.load(open(P/'broker.json'));broker.update(database='/fixture/approvals/approvals.sqlite',socket='/fixture/socket/approval.sock',verifier='/fixture/config/verifier.json',projection='/fixture/projection/management.json')
save(F/'config/broker.json',broker)
children=[]
def spawn(args,uid):
    env=dict(os.environ,PYTHONPATH='/runtime:/workspace');log=open(F/(str(uid)+'.log'),'w')
    child=subprocess.Popen([sys.executable,'-B',*args],env=env,preexec_fn=demote(uid),stdout=log,stderr=subprocess.STDOUT);children.append(child)
spawn([__file__,'source'],30944)
for _ in range(50):
    if (F/'source/market.json').exists():break
    time.sleep(.1)
spawn(['-m','octobot.ai_strategy_lab.v13_m1_approval_broker','--config','/fixture/config/broker.json'],30945)
spawn([__file__,'runner'],30943)
for _ in range(100):
    if (F/'projection/management.json').exists() and (F/'socket/approval.sock').exists():break
    if any(c.poll() is not None for c in children):raise ValueError('fixture_child_failed')
    time.sleep(.1)
else:raise ValueError('fixture_start_timeout')
from octobot.ai_strategy_lab import v13_m1_management_web as web
root=Path('/workspace/packages/tentacles/Services/Interfaces/web_interface')
tree=ast.parse((root/'controllers/home.py').read_text());register=next(n for n in tree.body if isinstance(n,ast.FunctionDef) and n.name=='register')
models=types.SimpleNamespace(accepted_terms=lambda:True,get_current_profile=lambda:types.SimpleNamespace(profile_id='local_ai_trading'))
namespace=dict(flask=flask,sqlite3=sqlite3,models=models,login=types.SimpleNamespace(login_required_when_activated=lambda f:f),
    v13_m1_management_web=types.SimpleNamespace(public_view=lambda:web.public_view(F/'projection/management.json',F/'socket/approval.sock'),decide=lambda payload:web.decide(payload,F/'socket/approval.sock')),
    v13_m1_review_view=types.SimpleNamespace(public_view=lambda:dict(available=False,message='CONTROL FIXTURE ONLY')))
exec(compile(ast.Module(body=[register],type_ignores=[]),str(root/'controllers/home.py'),'exec'),namespace)
app=flask.Flask(__name__,template_folder=str(root/'templates'),static_folder=str(root/'static'),static_url_path='/static');app.secret_key='v2-control-fixture-csrf-only'
namespace['register'](app)
@app.after_request
def label(response):
    if response.mimetype=='text/html':response.set_data(response.get_data(as_text=True).replace('<header>', '<p class="notice">CONTROL FIXTURE ONLY · COPIA PRIVATA</p><header>',1))
    return response
print('Private v2 fixture ready; no operational ledger or operator credential mounted',flush=True)
app.run(host='127.0.0.1',port=5103,threaded=False,use_reloader=False)
