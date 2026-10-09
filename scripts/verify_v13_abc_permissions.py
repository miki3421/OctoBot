"""Isolated Unix/SQLite ownership proof using synthetic numeric UIDs, no host users.

Requires the existing local octobot-local:dev image. Never installs dependencies.
Creates fixtures only in the explicitly supplied NEW directory; preserves them.
"""
import argparse,json,os,sqlite3,subprocess
from pathlib import Path

p=argparse.ArgumentParser(description=__doc__);p.add_argument('--output',required=True)
p.add_argument('--plan',help='Use assigned UID/GID values on isolated fixtures, never on operational stores')
a=p.parse_args()
if os.geteuid()!=0:raise SystemExit('Root required only to chown isolated fixtures')
root=Path(a.output).absolute();root.mkdir(mode=0o755)
roles={'collector':(11001,11010),'producer':(11002,11003),'executor':(11003,11003)}
reader=11010
if a.plan:
 plan=json.loads(Path(a.plan).read_text());u=plan['uids'];g=plan['read_groups']
 if len(set(u.values()))!=3 or any(type(v) is not int or v<=0 for v in [*u.values(),*g.values()]):raise ValueError('invalid_role_identities')
 roles={'collector':(u['collector'],g['forward']),'producer':(u['producer'],g['intents']),'executor':(u['executor'],u['executor'])}
 reader=g['forward']
for name,(uid,gid) in roles.items():
 directory=root/name;directory.mkdir(mode=0o750 if name!='executor' else 0o700);os.chown(directory,uid,gid)
 db=sqlite3.connect(directory/'data.sqlite');db.execute('CREATE TABLE marker(value TEXT)');db.execute("INSERT INTO marker VALUES ('SYNTHETIC_PERMISSION_FIXTURE')");db.commit();db.close()
 os.chown(directory/'data.sqlite',uid,gid);os.chmod(directory/'data.sqlite',0o640)
repo=Path(__file__).resolve().parents[1]
probe='''import json,sqlite3,sys
sys.path.insert(0,'/workspace/octobot/ai_strategy_lab')
import v13_dynamic_data as data
result={}
for name,uid in ROLES:
 path='/proof/'+name+'/data.sqlite';entry={}
 for mode in ('ro','rw'):
  db=None
  try:
   data.store_path(path,uid)
   db=sqlite3.connect('file:'+path+'?mode='+mode,uri=True)
   if mode=='rw':db.execute('BEGIN IMMEDIATE');db.execute("INSERT INTO marker VALUES ('temporary')");db.rollback()
   else:db.execute('SELECT * FROM marker').fetchall()
   entry[mode]=True
  except (PermissionError,sqlite3.Error):entry[mode]=False
  finally:
   if db is not None:db.close()
 result[name]=entry
print(json.dumps(result))
'''
probe=probe.replace('ROLES',repr([(role,uid) for role,(uid,_) in roles.items()]))
results={}
for role,(uid,gid) in roles.items():
 groups=([reader] if role!='collector' else [])+([roles['producer'][1]] if role=='executor' else [])
 command=['docker','run','--rm','--network','none','--read-only','--cap-drop','ALL','--tmpfs','/tmp','--user',str(uid)+':'+str(uid)]
 for group in groups:command+=['--group-add',str(group)]
 command+=['--mount','type=bind,src='+str(root)+',dst=/proof','--mount','type=bind,src='+str(repo)+',dst=/workspace,readonly','--entrypoint','python3','octobot-local:dev','-B','-c',probe]
 r=subprocess.run(command,capture_output=True,text=True,check=True);results[role]=json.loads(r.stdout)
 for target,access in results[role].items():
  assert access['rw']==(target==role),(role,target,access)
 assert results[role][role]['ro']
assert results['producer']['collector']['ro'] and results['executor']['collector']['ro']
assert results['executor']['producer']['ro']
assert not results['producer']['executor']['ro']
(root/'result.json').write_text(json.dumps(dict(scope='ISOLATED_ASSIGNED_UID_PERMISSION_TEST' if a.plan else 'SYNTHETIC_UID_PERMISSION_TEST',roles=results),indent=2))
print(json.dumps(results))
