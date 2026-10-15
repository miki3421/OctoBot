"""One-shot preparation/check/start/tick tool; never installs or starts a service.
Runs only research observations and immutable input captures, never fills.
"""
import argparse,datetime as dt,fcntl,gzip,hashlib,importlib.util,json,os,sqlite3,uuid
from pathlib import Path
REPO=Path(__file__).resolve().parents[1]
ROOT=Path('/root/auto_trading_sys')
STATE=ROOT/'octobot-local/v13-m1-short-future-v1'
SOURCE=ROOT/'octobot-local/v13-paper/research/source'
ORIGINAL=ROOT/'octobot-local/v13-paper/research/execution/execution.sqlite'
PROTOCOL=REPO/'docs/research-protocols/v13-m1-short-prospective-v1.json'
spec=importlib.util.spec_from_file_location('future',REPO/'octobot/ai_strategy_lab/v13_m1_future.py');f=importlib.util.module_from_spec(spec);spec.loader.exec_module(f)
def now():return dt.datetime.now(dt.timezone.utc).timestamp()
def sha(path):
 h=hashlib.sha256()
 with Path(path).open('rb') as stream:
  for block in iter(lambda:stream.read(1048576),b''):h.update(block)
 return h.hexdigest()
def load_protocol():
 p=json.loads(PROTOCOL.read_text());f.validate_protocol(p)
 for name,h in p['source_code_pins'].items():
  if sha(REPO/name)!=h:raise ValueError('source_code_pin_changed:'+name)
 bundle=json.loads((REPO/'docs/research-protocols/v13-m1-short-preparation-bundle-v1.json').read_text())
 if bundle['study_id']!=p['study_id'] or bundle['operational_approval'] is not False:raise ValueError('bundle_scope')
 for name,h in bundle['files'].items():
  path=Path(name)
  if path.is_absolute() or '..' in path.parts or not (REPO/path).resolve().is_relative_to(REPO.resolve()):raise ValueError('bundle_path')
  if sha(REPO/path)!=h:raise ValueError('bundle_file_changed:'+name)
 return p

def market_for(slot,p):
 candidates=[]
 for path in (SOURCE/'market').iterdir():
  # Hint only; verify embedded capture time, scope and content before selection.
  if not slot-360<=path.stat().st_mtime<=slot+360:continue
  if path.is_symlink() or path.stat().st_uid!=30911 or path.stat().st_mode&0o022:raise ValueError('source_archive_ownership')
  raw=path.read_bytes();record=json.loads(gzip.decompress(raw) if path.suffix=='.gz' else raw)
  at=dt.datetime.fromisoformat(record['observed_at_end']).timestamp()
  if not slot-120<=at<=slot:continue
  if record['record_hash']!=f.digest({k:v for k,v in record.items() if k!='record_hash'}) or record['scope']!='RESEARCH_SIMULATION_ONLY':raise ValueError('market_hash_or_scope')
  if set(record['quotes'])!=set(p['universe']):raise ValueError('market_universe')
  for q in record['quotes'].values():
   if q['min_quantity'] is not None or q['min_notional'] is not None:raise ValueError('simulation_contract_changed')
   for field in ['timestamp','mark_timestamp']:
    if not 0<=at-dt.datetime.fromisoformat(q[field]).timestamp()<=120:raise ValueError('quote_stale')
  candidates.append((at,record))
 if not candidates:raise ValueError('qualified_book_unavailable')
 return max(candidates,key=lambda v:v[0])

def take_capture(journal,episode,phase,p):
 if journal.db.execute('SELECT 1 FROM captures WHERE episode_id=? AND phase=?',(episode['id'],phase)).fetchone():return
 scheduled=episode[phase+'_slot'];instant=now()
 if not scheduled<=instant<=scheduled+120:return
 at,market=market_for(scheduled,p)
 directory=STATE/'episodes'/episode['id'];directory.mkdir(parents=True,exist_ok=True)
 target=directory/(phase+'.original.sqlite');marketfile=directory/(phase+'.market.json')
 if target.exists() or marketfile.exists():raise ValueError('orphan_capture_requires_review_no_overwrite')
 if ORIGINAL.is_symlink() or ORIGINAL.stat().st_uid!=30914 or ORIGINAL.stat().st_mode&0o022:raise ValueError('source_ledger_ownership')
 temp=directory/('.pending-'+uuid.uuid4().hex+'.sqlite')
 src=sqlite3.connect(ORIGINAL.resolve().as_uri()+'?mode=ro',uri=True);dest=sqlite3.connect(temp)
 try:src.backup(dest)
 finally:dest.close();src.close()
 test=sqlite3.connect(temp.resolve().as_uri()+'?mode=ro',uri=True)
 try:
  if test.execute('PRAGMA integrity_check').fetchone()[0]!='ok':raise ValueError('snapshot_integrity')
 finally:test.close()
 temp.chmod(0o440);os.rename(temp,target)
 with marketfile.open('x') as output:
  output.write(f.encoded(market)+'\n');output.flush();os.fsync(output.fileno())
 marketfile.chmod(0o440)
 dfd=os.open(directory,os.O_RDONLY)
 try:os.fsync(dfd)
 finally:os.close(dfd)
 captured=now();journal.capture(episode['id'],phase,dict(snapshot_sha256=sha(target),market_hash=market['record_hash'],market_observed_at=at,captured_at=captured),captured)

def main():
 parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('command',choices=['check','start','tick','status','evaluate']);args=parser.parse_args();p=load_protocol()
 if args.command=='check':
  print(json.dumps(dict(state='PREPARATION_BUNDLE_VALID',protocol_file_sha256=sha(PROTOCOL),code_pins_valid=True,service_installed_by_this_tool=False,source_io='READ_ONLY',future_start='next UTC midnight after explicit durable start',offline_replay='evaluate after sealed fixed horizon; no PnL accepted by observer')));return
 if args.command=='status' and not (STATE/'observation.sqlite').exists():
  print(json.dumps(dict(state='PREPARED_NOT_STARTED',activation=None)));return
 if STATE.exists() and (STATE.is_symlink() or STATE.stat().st_uid!=os.geteuid() or STATE.stat().st_mode&0o022):raise ValueError('state_directory_ownership')
 STATE.mkdir(mode=0o700,parents=True,exist_ok=True)
 with (STATE/'writer.lock').open('a') as lock:
  fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
  path=STATE/'observation.sqlite'
  if args.command=='start' and not path.exists():j=f.Journal.create(path,p,now())
  else:j=f.Journal(path,p)
  try:
   if j.meta('fixture'):raise ValueError('fixture_journal_not_live_eligible')
   if args.command=='start':print(json.dumps(j.start(now())));return
   if args.command=='status':print(json.dumps(j.summary()));return
   if args.command=='evaluate':
    spec=importlib.util.spec_from_file_location('evaluate',REPO/'octobot/ai_strategy_lab/v13_m1_future_evaluate.py');e=importlib.util.module_from_spec(spec);spec.loader.exec_module(e)
    result=e.assess(j,STATE,p,now());dest=STATE/('assessment-'+uuid.uuid4().hex+'.json')
    with dest.open('x') as output:output.write(json.dumps(result,indent=2)+'\n')
    print(json.dumps(dict(assessment=str(dest),label=result['label'],operational_approval=False)));return
   receipt=j.meta('activation');instant=now()
   if not receipt:raise ValueError('prepared_not_started')
   if instant<receipt['t0']:print(json.dumps(dict(state='WAITING_FOR_FUTURE_T0',activation=receipt)));return
   if instant>=receipt['end_exclusive']:j.seal(instant);print(json.dumps(j.summary()));return
   if ORIGINAL.is_symlink() or ORIGINAL.stat().st_uid!=30914 or ORIGINAL.stat().st_mode&0o022:raise ValueError('source_ledger_ownership')
   slot=int(instant)//300*300;old=j.db.execute('SELECT payload FROM slots WHERE slot=?',(slot,)).fetchone()
   if old:result=json.loads(old[0])
   else:result=j.record(slot,f.read_window(ORIGINAL,slot,p['universe']),now())
   with j.db:j.clock(now());j.expire(now())
   for episode in j.db.execute("SELECT * FROM episodes WHERE status IN ('SCHEDULED','ENTRY_RECORDED') ORDER BY slot").fetchall():
    take_capture(j,episode,'entry' if episode['status']=='SCHEDULED' else 'exit',p)
   print(json.dumps(dict(slot=result['status'],**j.summary())))
  finally:j.close()
if __name__=='__main__':main()
