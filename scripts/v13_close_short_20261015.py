"""Offline conditional portfolio episodes. Never reads or modifies live journals.
Card work-card-1c625e23-0331-4fa3-a9d5-98e9fc21499e.
"""
import bisect,collections,copy,datetime as dt,gzip,hashlib,importlib.util,json,math,sqlite3
from pathlib import Path
ROOT=Path('/root/auto_trading_sys');BASE=ROOT/'audit-evidence/v13-crash-20261015';OUT=ROOT/'audit-evidence/v13-close-vs-short-20261015'
REPO=Path(__file__).resolve().parents[1]
spec=importlib.util.spec_from_file_location('account',REPO/'octobot/ai_strategy_lab/v13_close_short_diagnostic.py');a=importlib.util.module_from_spec(spec);spec.loader.exec_module(a)
assert hashlib.sha256((OUT/'protocol.json').read_bytes()).hexdigest()=='0c3290a09372c57f362a0cb0136925e970355e18ba5bac170bc455fe53d87647'
protocol=json.loads((OUT/'protocol.json').read_text());assert hashlib.sha256((BASE/'manifest.json').read_bytes()).hexdigest()==protocol['source_manifest_sha256']
manifest=json.loads((BASE/'manifest.json').read_text())['evidence']
def digest(path):return hashlib.sha256(path.read_bytes()).hexdigest()
def checked(name):
 p=BASE/name
 assert digest(p)==manifest[name],('input_changed',name)
 return p
for name in ['original.sqlite','models.json','grid.json']:checked(name)
def seconds(s):return dt.datetime.fromisoformat(s).timestamp()
def iso(t):return dt.datetime.fromtimestamp(t,dt.timezone.utc).isoformat()
def save(name,v):(OUT/name).write_text(json.dumps(v,indent=2,allow_nan=False))
db=sqlite3.connect('file:'+str(BASE/'original.sqlite')+'?mode=ro',uri=True);db.row_factory=sqlite3.Row
assert db.execute('pragma integrity_check').fetchone()[0]=='ok'
original=json.loads(db.execute('select payload from state where id=1').fetchone()[0]);symbols=sorted(original['positions']);initial=original['initial_equity']
orders=[dict(r) for r in db.execute("select * from orders where status='filled' order by bar,id")]
for f in orders:f['at_seconds']=seconds(f['bar'])
funding=[dict(r) for r in db.execute('select * from funding_events order by timestamp_ms')]
marks=collections.defaultdict(list)
for r in db.execute('select bar,symbol,price from marks order by bar'):marks[r['symbol']].append((seconds(r['bar']),r['price']))
mt={s:[v[0] for v in rows] for s,rows in marks.items()}
def reference(s,t,strict=False):
 index=(bisect.bisect_left if strict else bisect.bisect_right)(mt[s],t)-1
 if index<0 or t-marks[s][index][0]>(1800 if strict else 120):raise ValueError('reference_missing:'+s)
 return marks[s][index][1]
def actual(t,prices=None):
 state=dict(initial_equity=initial,positions={s:a.new_position() for s in symbols})
 for f in orders:
  if f['at_seconds']<=t:a.fill(state['positions'][f['symbol']],f['quantity'],f['price'],f['fee'])
 for f in funding:
  if f['timestamp_ms']/1000<=t:state['positions'][f['symbol']]['funding']+=f['amount']
 return state
# Entire preserved history reproduces all stored economic state fields exactly.
replayed=actual(math.inf)
checks={s:{k:replayed['positions'][s][k]-original['positions'][s][k] for k in ['quantity','entry_price','realized_pnl','fees','funding']} for s in symbols}
assert max(abs(v) for r in checks.values() for v in r.values())<1e-7
last=db.execute('select bar,equity from equity_history order by bar desc limit 1').fetchone()
last_marks={s:reference(s,seconds(last['bar'])) for s in symbols};last_equity=a.totals(replayed,last_marks)['equity'];assert abs(last_equity-last['equity'])<1e-6
save('reconciliation.json',dict(position_errors=checks,final_equity_error=last_equity-last['equity'],orders=len(orders),funding_events=len(funding)))
used={};book_cache={}
def book(h):
 if h in book_cache:return book_cache[h]
 name='input-archives/market/'+h+'.json.gz';p=checked(name);v=json.loads(gzip.decompress(p.read_bytes()))
 canonical=json.dumps({k:x for k,x in v.items() if k!='record_hash'},sort_keys=True,separators=(',',':'),ensure_ascii=False,allow_nan=False).encode()
 assert hashlib.sha256(canonical).hexdigest()==h and v['scope']=='RESEARCH_SIMULATION_ONLY'
 t=seconds(v['observed_at_end']);assert t<=seconds(protocol['source_cutoff'])
 assert set(v['quotes'])==set(symbols)
 for s,q in v['quotes'].items():
  assert q['symbol']==s and q['metadata_scope']=='REAL_PRECISION_WITH_SEPARATE_SIMULATED_MINIMUMS'
  assert q['min_quantity'] is None and q['min_notional'] is None
  assert 0<=t-seconds(q['timestamp'])<=120 and 0<=t-seconds(q['mark_timestamp'])<=120
 used[name]=digest(p);book_cache[h]=v;return v
rows=json.loads((BASE/'grid.json').read_text());models=json.loads((BASE/'models.json').read_text())
def risk_path(seed,times,prices,changes):
 state=copy.deepcopy(seed);pending=iter(changes);next_change=next(pending,None);points=[]
 for time,marks_ in zip(times,prices):
  while next_change is not None and next_change['time']<=time:
   state['positions'][next_change['symbol']]['funding']+=next_change['amount'];next_change=next(pending,None)
  points.append(dict(at=iso(time),**a.totals(state,marks_)))
 return state,points

def run(event):
 if not event['complete']:return dict(signal_at=event['signal_at'],status='CENSORED',reason='six_hour_outcome_unavailable')
 be=book(event['long']['entry_hash']);bx=book(event['long']['exit_hash']);start,end=map(seconds,[be['observed_at_end'],bx['observed_at_end']])
 if start-seconds(event['signal_at'])<60:raise ValueError('execution_too_early')
 eq={s:q['mark_price'] for s,q in be['quotes'].items()};xq={s:q['mark_price'] for s,q in bx['quotes'].items()}
 seed=actual(start);baseline=actual(end);base_initial=a.totals(seed,eq);base_final=a.totals(baseline,xq)
 # Never seed a synthetic quantity or discard the inherited cost basis / P&L.
 assert all(v['quantity']>=-1e-10 for v in seed['positions'].values()),'unexpected_inherited_short'
 target={s:v['quantity'] for s,v in baseline['positions'].items()};longs=sum(v['quantity']>1e-10 for v in seed['positions'].values())
 if not longs:raise ValueError('no_inherited_long')
 grid=[r for r in rows if start<r['time']<end];times=[start]+[r['time'] for r in grid]+[end];price_vectors=[eq]+[r['prices'] for r in grid]+[xq]
 arms={};paths={}
 basepath=[dict(at=iso(t),**a.totals(actual(t),prices)) for t,prices in zip(times,price_vectors)]
 paths['BASELINE']=basepath
 for arm in ['CASH','SHORT']:
  state,entry_legs=a.rebalance(seed,a.targets_for(seed,arm),be['quotes'])
  events=[]
  for s,pos in state['positions'].items():
   if abs(pos['quantity'])<1e-10:continue # known zero exposure has no funding liability
   for f in a.settlements(bx['quotes'][s],int(start*1000),int(end*1000)):
    t=f['timestamp_ms']/1000;mark=reference(s,t,strict=True);amount=-pos['quantity']*mark*f['rate']
    events.append(dict(time=t,symbol=s,rate=f['rate'],quantity=pos['quantity'],reference_mark=mark,amount=amount))
  events.sort(key=lambda x:(x['time'],x['symbol']))
  # Also verify schedule support on the seed-long symbols when CASH has no exposure.
  for s,pos in seed['positions'].items():
   if pos['quantity']>1e-10:a.settlements(bx['quotes'][s],int(start*1000),int(end*1000))
  state,points=risk_path(state,times,price_vectors,events)
  pre=a.totals(state,xq);restored,exit_legs=a.rebalance(state,target,bx['quotes']);post=a.totals(restored,xq)
  assert all(abs(restored['positions'][s]['quantity']-target[s])<1e-9 for s in symbols)
  realized=post['realized']-base_initial['realized'];unrealized=post['unrealized']-base_initial['unrealized'];fees=post['fees']-base_initial['fees'];fund=post['funding']-base_initial['funding'];pnl=post['equity']-base_initial['equity']
  assert abs(pnl-(realized+unrealized-fees+fund))<1e-6
  peak=base_initial['equity'];dd=0.
  for point in points+[dict(equity=post['equity'])]:peak=max(peak,point['equity']);dd=max(dd,peak-point['equity'])
  turnover=sum(f['turnover'] for f in entry_legs+exit_legs);paths[arm]=points+[dict(at=iso(end),phase='after_return',**post)]
  legs=[dict(phase='entry',**f) for f in entry_legs]+[dict(phase='return',**f) for f in exit_legs]
  arms[arm]=dict(before_return_equity=pre['equity'],after_return_equity=post['equity'],pnl=pnl,versus_baseline=post['equity']-base_final['equity'],fees=fees,funding=fund,turnover=turnover,extra_20bps_pnl=pnl-turnover*.002,max_drawdown_usdt=dd,maximum_gross=max(v['gross'] for v in points),minimum_equity=min(v['equity'] for v in points),entry_gross=points[0]['gross'],entry_net=points[0]['net_exposure'],legs=legs,funding_events=events)
 base_peak=base_initial['equity'];base_dd=0.
 for point in basepath:base_peak=max(base_peak,point['equity']);base_dd=max(base_dd,base_peak-point['equity'])
 arms['BASELINE']=dict(pnl=base_final['equity']-base_initial['equity'],after_return_equity=base_final['equity'],fees=base_final['fees']-base_initial['fees'],funding=base_final['funding']-base_initial['funding'],max_drawdown_usdt=base_dd,minimum_equity=min(v['equity'] for v in basepath))
 return dict(status='COMPLETE',signal_at=event['signal_at'],entry_at=iso(start),exit_at=iso(end),entry_hash=be['record_hash'],exit_hash=bx['record_hash'],initial_equity=base_initial['equity'],initial_gross=base_initial['gross'],long_positions=longs,arms=arms,short_minus_cash=arms['SHORT']['pnl']-arms['CASH']['pnl'],paths=paths)

results={}
for rule,value in models.items():
 episodes=[]
 for e in value['episodes']:
  try:episodes.append(run(e))
  except (ValueError,AssertionError) as exc:episodes.append(dict(signal_at=e['signal_at'],status='UNAVAILABLE',reason=str(exc)))
 valid=[e for e in episodes if e['status']=='COMPLETE'];summary={}
 for arm in ['BASELINE','CASH','SHORT']:
  summary[arm]=dict(pnl=sum(e['arms'][arm]['pnl'] for e in valid),fees=sum(e['arms'][arm]['fees'] for e in valid),funding=sum(e['arms'][arm]['funding'] for e in valid),worst_episode=min([e['arms'][arm]['pnl'] for e in valid] or [0]),largest_sampled_drawdown=max([e['arms'][arm]['max_drawdown_usdt'] for e in valid] or [0]))
  if arm!='BASELINE':summary[arm]['extra_20bps_pnl']=sum(e['arms'][arm]['extra_20bps_pnl'] for e in valid)
 results[rule]=dict(episodes=episodes,summary=summary,completed=len(valid),unavailable=sum(e['status']=='UNAVAILABLE' for e in episodes),censored=sum(e['status']=='CENSORED' for e in episodes),short_beats_cash=sum(e['short_minus_cash']>0 for e in valid))
 print(rule,{k:v for k,v in results[rule].items() if k not in ['episodes']})
 print('unavailable',[(e['signal_at'],e.get('reason')) for e in episodes if e['status']=='UNAVAILABLE'])
save('results.json',results);save('used-archives.json',used)
# Independent cash-flow identity: with equal terminal quantities all mark terms cancel.
identities=[]
for rule,value in results.items():
 for e in value['episodes']:
  if e['status']!='COMPLETE':continue
  cash,short=e['arms']['CASH'],e['arms']['SHORT']
  def cashflows(arm):return math.fsum(-f['quantity']*f['price']-f['fee'] for f in arm['legs'])+arm['funding']
  error=(short['after_return_equity']-cash['after_return_equity'])-(cashflows(short)-cashflows(cash))
  assert abs(error)<1e-6
  q={}
  for name,arm in [('CASH',cash),('SHORT',short)]:
   q[name]=collections.defaultdict(float)
   for f in arm['legs']:q[name][f['symbol']]+=f['quantity']
  assert all(abs(q['CASH'][s]-q['SHORT'][s])<1e-8 for s in symbols)
  entry={name:{f['symbol']:f for f in arm['legs'] if f['phase']=='entry'} for name,arm in [('CASH',cash),('SHORT',short)]}
  assert entry['CASH'].keys()==entry['SHORT'].keys()
  assert all(abs(entry['SHORT'][s]['quantity']-2*f['quantity'])<1e-8 for s,f in entry['CASH'].items())
  assert abs(short['entry_gross']-e['initial_gross'])<1e-7 and cash['entry_gross']==0
  identities.append(dict(rule=rule,signal=e['signal_at'],incremental_cashflow_error=error,matched_entry_gross=True,combined_crossing_depth=True,same_terminal_quantity=True))
save('independent-identities.json',identities)
print('Independent cash-flow and quantity checks:',len(identities))
