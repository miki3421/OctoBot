"""Post-horizon research assessment from captured original ledgers, never free-form PnL."""
import collections,copy,datetime as dt,hashlib,importlib.util,json,math,random,sqlite3
from pathlib import Path
spec=importlib.util.spec_from_file_location('paired_account',Path(__file__).with_name('v13_close_short_diagnostic.py'));a=importlib.util.module_from_spec(spec);spec.loader.exec_module(a)
spec=importlib.util.spec_from_file_location('frozen_detector',Path(__file__).with_name('v13_crash_diagnostic.py'));detector=importlib.util.module_from_spec(spec);spec.loader.exec_module(detector)
def stamp(s):return dt.datetime.fromisoformat(s).timestamp()
def digest(v):return hashlib.sha256(json.dumps(v,sort_keys=True,separators=(',',':'),allow_nan=False).encode()).hexdigest()
def sha(path):return hashlib.sha256(path.read_bytes()).hexdigest()
def validate_consumed(directory,decision,universe):
 rows=decision['consumed_rows']
 if (len(rows)!=289 or rows[-1]['time']!=decision['slot'] or digest(rows)!=decision['input_hash'] or
         detector.features(rows,288)!=decision['feature'] or not detector.signal(decision['feature'],'momentum_breadth')):raise ValueError('consumed_signal_changed')
 db=ro(directory/'entry.original.sqlite')
 try:
  for row in rows:
   if set(row['prices'])!=set(universe) or set(row['source_times'])!=set(universe):raise ValueError('consumed_universe')
   for s,at in row['source_times'].items():
    if not 0<=row['time']-at<=120:raise ValueError('consumed_future_or_stale')
    point=db.execute('SELECT price FROM marks WHERE symbol=? AND bar=?',(s,dt.datetime.fromtimestamp(at,dt.timezone.utc).isoformat())).fetchone()
    if not point or point[0]!=row['prices'][s]:raise ValueError('consumed_point_missing_from_snapshot')
 finally:db.close()
def ro(path):
 if path.is_symlink():raise ValueError('snapshot_symlink')
 db=sqlite3.connect(path.resolve().as_uri()+'?mode=ro',uri=True);db.row_factory=sqlite3.Row;db.execute('PRAGMA query_only=ON')
 if db.execute('PRAGMA integrity_check').fetchone()[0]!='ok':db.close();raise ValueError('snapshot_integrity')
 return db

def episode(directory,captures,universe):
 books={};dbs={}
 try:
  for phase in ['entry','exit']:
   p=directory/(phase+'.original.sqlite');receipt=captures[phase]
   if sha(p)!=receipt['snapshot_sha256']:raise ValueError('snapshot_hash')
   marketfile=directory/(phase+'.market.json')
   if marketfile.is_symlink():raise ValueError('market_symlink')
   book=json.loads(marketfile.read_text())
   if (book['record_hash']!=receipt['market_hash'] or digest({k:v for k,v in book.items() if k!='record_hash'})!=book['record_hash'] or book['scope']!='RESEARCH_SIMULATION_ONLY' or set(book['quotes'])!=set(universe)):raise ValueError('book_identity')
   if stamp(book['observed_at_end'])!=receipt['market_observed_at']:raise ValueError('book_time')
   for q in book['quotes'].values():
    if q['min_quantity'] is not None or q['min_notional'] is not None:raise ValueError('simulation_scope')
   books[phase]=book;dbs[phase]=ro(p)
  start,end=[stamp(books[k]['observed_at_end']) for k in ['entry','exit']]
  if not 21360<=end-start<=21840:raise ValueError('holding_window')
  def actual(db,t):
   saved=json.loads(db.execute('SELECT payload FROM state WHERE id=1').fetchone()[0])
   if set(saved['positions'])!=set(universe):raise ValueError('snapshot_universe')
   state=dict(initial_equity=saved['initial_equity'],positions={s:a.new_position() for s in universe})
   for f in db.execute("SELECT * FROM orders WHERE status='filled' AND bar<=? ORDER BY bar,id",(dt.datetime.fromtimestamp(t,dt.timezone.utc).isoformat(),)):
    a.fill(state['positions'][f['symbol']],f['quantity'],f['price'],f['fee'])
   for f in db.execute('SELECT * FROM funding_events WHERE timestamp_ms<=?',(int(t*1000),)):state['positions'][f['symbol']]['funding']+=f['amount']
   return state
  eq={s:q['mark_price'] for s,q in books['entry']['quotes'].items()};xq={s:q['mark_price'] for s,q in books['exit']['quotes'].items()}
  seed=actual(dbs['entry'],start);baseline=actual(dbs['exit'],end);begin=a.totals(seed,eq);finish=a.totals(baseline,xq)
  if not any(p['quantity']>1e-10 for p in seed['positions'].values()):return dict(status='NO_LONG_NO_INTERVENTION',entry_equity=begin['equity'])
  # Check that entry-prefix economics have not changed between immutable captures.
  later_seed=actual(dbs['exit'],start)
  if any(abs(seed['positions'][s][k]-later_seed['positions'][s][k])>1e-7 for s in universe for k in ['quantity','entry_price','realized_pnl','fees','funding']):raise ValueError('historical_prefix_changed_or_late_funding')
  def mark_before(symbol,time):
   row=dbs['exit'].execute('SELECT bar,price FROM marks WHERE symbol=? AND bar<? ORDER BY bar DESC LIMIT 1',(symbol,dt.datetime.fromtimestamp(time,dt.timezone.utc).isoformat())).fetchone()
   if not row or time-stamp(row['bar'])>1800:raise ValueError('funding_reference_missing')
   return row['price']
  targets={s:p['quantity'] for s,p in baseline['positions'].items()};arms={};flows={}
  # Same 5-minute observed grid. Missing rows make this episode unresolved, not zero.
  grids=list(range((int(start)//300+1)*300,int(end)+1,300));vectors=[]
  for t in grids:
   vector={}
   for s in universe:
    row=dbs['exit'].execute('SELECT bar,price FROM marks WHERE symbol=? AND bar<=? ORDER BY bar DESC LIMIT 1',(s,dt.datetime.fromtimestamp(t,dt.timezone.utc).isoformat())).fetchone()
    if not row or t-stamp(row['bar'])>120:raise ValueError('valuation_grid_missing')
    vector[s]=row['price']
   vectors.append(vector)
  for arm in ['CASH','SHORT']:
   state,entry_legs=a.rebalance(seed,a.targets_for(seed,arm),books['entry']['quotes']);events=[]
   for s,p in state['positions'].items():
    if abs(p['quantity'])<1e-10:continue
    for f in a.settlements(books['exit']['quotes'][s],int(start*1000),int(end*1000)):
     time=f['timestamp_ms']/1000;events.append((time,s,-p['quantity']*mark_before(s,time)*f['rate']))
   events.sort();cursor=0;peak=begin['equity'];dd=0.
   for t,vector in [(start,eq)]+list(zip(grids,vectors))+[(end,xq)]:
    while cursor<len(events) and events[cursor][0]<=t:
     _,s,amount=events[cursor];state['positions'][s]['funding']+=amount;cursor+=1
    value=a.totals(state,vector)['equity'];peak=max(peak,value);dd=max(dd,peak-value)
   state,exit_legs=a.rebalance(state,targets,books['exit']['quotes']);tot=a.totals(state,xq);dd=max(dd,peak-tot['equity'])
   legs=entry_legs+exit_legs;turnover=sum(f['turnover'] for f in legs);fund=tot['funding']-begin['funding']
   if any(abs(state['positions'][s]['quantity']-targets[s])>1e-8 for s in universe):raise ValueError('terminal_quantity')
   flows[arm]=math.fsum(-f['quantity']*f['price']-f['fee'] for f in legs)+fund
   arms[arm]=dict(pnl=tot['equity']-begin['equity'],stress_pnl=tot['equity']-begin['equity']-.002*turnover,fees=tot['fees']-begin['fees'],funding=fund,turnover=turnover,drawdown_usdt=dd)
  delta=arms['SHORT']['pnl']-arms['CASH']['pnl']
  if abs(delta-(flows['SHORT']-flows['CASH']))>1e-6:raise ValueError('cashflow_identity')
  return dict(status='COMPLETE',entry_equity=begin['equity'],baseline_pnl=finish['equity']-begin['equity'],arms=arms,delta=delta,stress_delta=arms['SHORT']['stress_pnl']-arms['CASH']['stress_pnl'])
 finally:
  for db in dbs.values():db.close()

def assess(journal,state_directory,protocol,now):
 receipt=journal.meta('activation')
 if not receipt or now<receipt['end_exclusive'] or not journal.meta('sealed'):raise ValueError('fixed_horizon_not_sealed')
 if journal.meta('fixture'):raise ValueError('fixture_not_scientific_evidence')
 results=[]
 for e in journal.db.execute('SELECT * FROM episodes ORDER BY slot'):
  value=dict(id=e['id'],slot=e['slot'],status=e['status'])
  if e['status']=='CAPTURE_COMPLETE_AWAITING_OFFLINE_REPLAY':
   captures={r[0]:json.loads(r[1]) for r in journal.db.execute('SELECT phase,payload FROM captures WHERE episode_id=?',(e['id'],))}
   try:
    decision=json.loads(journal.db.execute('SELECT payload FROM slots WHERE slot=?',(e['slot'],)).fetchone()[0])
    rows=decision['consumed_rows']
    if digest(rows)!=decision['input_hash'] or journal.meta('identity')['protocol']!=digest(protocol):raise ValueError('consumed_input_identity')
    validate_consumed(state_directory/'episodes'/e['id'],decision,protocol['universe'])
    value.update(episode(state_directory/'episodes'/e['id'],captures,protocol['universe']))
   except (ValueError,OSError,KeyError,TypeError,sqlite3.Error) as error:value.update(status='UNRESOLVED',reason=str(error))
  results.append(value)
 slots=dict(journal.db.execute('SELECT status,COUNT(*) FROM slots GROUP BY status'));expected=90*288
 valid=sum(n for status,n in slots.items() if status not in ['MISSED','INSUFFICIENT_INPUT'])
 good=[e for e in results if e['status']=='COMPLETE'];pending=[e for e in results if e['status'] not in ['COMPLETE','NO_LONG_NO_INTERVENTION']]
 days={dt.datetime.fromtimestamp(e['slot'],dt.timezone.utc).date().isoformat() for e in good};weeks=collections.defaultdict(list)
 for e in good:
  date=dt.datetime.fromtimestamp(e['slot'],dt.timezone.utc);weeks[date.strftime('%G-W%V')].append(e['delta'])
 delta=math.fsum(e['delta'] for e in good);stress_delta=math.fsum(e['stress_delta'] for e in good);short=math.fsum(e['arms']['SHORT']['pnl'] for e in good);stress_short=math.fsum(e['arms']['SHORT']['stress_pnl'] for e in good)
 criteria=protocol['evaluation'];coverage=valid/expected
 sufficient=(len(good)>=criteria['minimum_complete_episodes'] and len(days)>=criteria['minimum_distinct_trigger_days'] and len(weeks)>=criteria['minimum_trigger_weeks'] and coverage>=criteria['minimum_valid_slot_fraction'] and not pending)
 label='INCONCLUSIVE_NO_PROMOTION' if not sufficient else ('CANDIDATE_FOR_FURTHER_REVIEW_ONLY' if min(delta,stress_delta,short,stress_short)>0 else 'MIXED_OR_NEGATIVE_NO_PROMOTION')
 interval=None
 if len(weeks)>=2:
  rng=random.Random(0);groups=list(weeks.values());means=[]
  for _ in range(5000):
   sample=[rng.choice(groups) for _ in groups];means.append(math.fsum(sum(v) for v in sample)/sum(len(v) for v in sample))
  means.sort();interval=[means[125],means[4874]]
 return dict(label=label,operational_approval=False,complete_episodes=len(good),unresolved_episodes=len(pending),distinct_days=len(days),distinct_weeks=len(weeks),valid_slot_fraction=coverage,primary_mean_delta=delta/len(good) if good else None,short_total=short if good else None,stress_short_total=stress_short if good else None,stress_paired_total=stress_delta if good else None,weekly_block_interval95=interval,episodes=results,slots=slots)
