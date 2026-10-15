"""Reproduce the October 15 offline investigation; no service or source writes.
Cards: 1156f73d / a70c873b / 90d7f1d1. Paths are local research evidence only.
"""
import bisect,collections,copy,datetime as dt,gzip,hashlib,importlib.util,json,math,sqlite3
from pathlib import Path
ROOT=Path('/root/auto_trading_sys');OUT=ROOT/'audit-evidence/v13-crash-20261015'
REPO=Path(__file__).resolve().parents[1]
assert hashlib.sha256((OUT/'protocol.json').read_bytes()).hexdigest()=='4099a3c8a0350153ffca87a7f5a0e5149c5a2685d74d16e1785471aa464e9c14', 'protocol_changed'
spec=importlib.util.spec_from_file_location('diagnostic',REPO/'octobot/ai_strategy_lab/v13_crash_diagnostic.py');model=importlib.util.module_from_spec(spec);spec.loader.exec_module(model)
def seconds(s):return dt.datetime.fromisoformat(s).timestamp()
def iso(t):return dt.datetime.fromtimestamp(t,dt.timezone.utc).isoformat()
def save(n,v):(OUT/n).write_text(json.dumps(v,indent=2,allow_nan=False))
def connect(n):
 d=sqlite3.connect('file:'+str(OUT/n)+'?mode=ro',uri=True);d.row_factory=sqlite3.Row;return d
original=connect('original.sqlite');paired=connect('paired.sqlite')
projection=json.loads((OUT/'comparison.json').read_text());t0=seconds(projection['receipt']['economic_t0'])
seedpath=OUT/'parent.sqlite' if (OUT/'parent.sqlite').exists() else ROOT/'octobot-local/v13-prospective-forks/runtime-v2/seed/parent-snapshot.sqlite'
assert hashlib.sha256(seedpath.read_bytes()).hexdigest()==projection['receipt']['parent_snapshot_sha256']
seed=sqlite3.connect('file:'+str(seedpath)+'?mode=ro',uri=True);parent=json.loads(seed.execute('select payload from state').fetchone()[0])
symbols=sorted(parent['positions']);marks=collections.defaultdict(list)
for r in original.execute('select bar,symbol,price from marks order by bar'):
 marks[r['symbol']].append((seconds(r['bar']),r['price']))
marktimes={s:[v[0] for v in a] for s,a in marks.items()}
def price_at(s,t,max_age=120):
 i=bisect.bisect_right(marktimes[s],t)-1
 if i<0 or t-marks[s][i][0]>max_age:raise ValueError('missing_price:'+s+':'+iso(t))
 return marks[s][i][1]
end=seconds(paired.execute('select max(at) from observations').fetchone()[0])
start=seconds('2026-09-28T20:10:00+00:00');grid=[];missing=[]
for t in range(int(start),int(end)+1,300):
 try:prices={s:price_at(s,t) for s in symbols}
 except ValueError:missing.append(iso(t));continue
 grid.append(dict(time=t,at=iso(t),prices=prices))
save('grid.json',grid);save('coverage.json',dict(start=iso(start),end=iso(end),complete_rows=len(grid),missing_rows=missing,symbols=symbols))
# File mtime is only an index hint. Embedded observation time, scope and content hash decide eligibility.
archives=OUT/'input-archives/market' if (OUT/'input-archives/market').exists() else ROOT/'octobot-local/v13-paper/research/source/market';indexed=sorted((p.stat().st_mtime,p) for p in archives.iterdir() if p.is_file());mtimes=[v[0] for v in indexed];cache={};used={}
def book_at(t):
 key=round(t,6)
 if key in cache:return cache[key]
 choices=[]
 for _,p in indexed[max(0,bisect.bisect_left(mtimes,t-360)):bisect.bisect_right(mtimes,t+360)]:
  raw=p.read_bytes();v=json.loads(gzip.decompress(raw) if p.suffix=='.gz' else raw);seen=seconds(v['observed_at_end'])
  if not 0<=t-seen<=120:continue
  canonical=json.dumps({k:x for k,x in v.items() if k!='record_hash'},sort_keys=True,separators=(',',':'),ensure_ascii=False,allow_nan=False).encode()
  assert hashlib.sha256(canonical).hexdigest()==v['record_hash'] and v['scope']=='RESEARCH_SIMULATION_ONLY'
  choices.append((seen,p,v))
 if not choices:raise ValueError('no_verified_book:'+iso(t))
 seen,p,v=max(choices,key=lambda x:x[0]);used[p.name]=hashlib.sha256(p.read_bytes()).hexdigest()
 quote=v['quotes']['BTCUSDT'];q=dict(observed_at=seen,mark=quote['mark_price'],fee_rate=quote['fee_rate'],bids=[(x['price'],x['base_quantity']) for x in quote['bids']],asks=[(x['price'],x['base_quantity']) for x in quote['asks']],hash=v['record_hash'],funding=quote['funding'],funding_interval_ms=quote['funding_interval_ms'])
 cache[key]=q;return q
funding=[dict(r) for r in original.execute("select * from funding_events where symbol='BTCUSDT' order by timestamp_ms")]
def trade(entry_i,exit_i,side):
 e,x=grid[entry_i],grid[exit_i];be,bx=book_at(e['time']),book_at(x['time'])
 q=math.floor(1000/be['mark']/.001)*.001 # fixed 10% of 10,000 reference equity; not strategy overlay
 if q<=0:raise ValueError('quantity_below_step')
 payments=[f for f in funding if be['observed_at']*1000<f['timestamp_ms']<=bx['observed_at']*1000]
 # Verify each settlement implied by the exit archive is represented in the copied cash ledger.
 expected={f['timestamp_ms'] for f in bx['funding'] if be['observed_at']*1000<f['timestamp_ms']<=bx['observed_at']*1000}
 assert expected=={f['timestamp_ms'] for f in payments},'funding_support_mismatch'
 if not bx['funding'] or bx['funding'][-1]['timestamp_ms']+bx['funding_interval_ms']<=bx['observed_at']*1000:raise ValueError('funding_tail_missing')
 amount=sum(-side*q*f['reference_mark']*f['rate'] for f in payments)
 return dict(**model.trade_pnl(side,q,be,bx,amount),entry_at=iso(be['observed_at']),exit_at=iso(bx['observed_at']),entry_hash=be['hash'],exit_hash=bx['hash'],funding_events=len(payments))
results={}
for rule in ['momentum_breadth','breakout_breadth']:
 episodes=[]
 for event in model.episodes(grid,rule):
  i,j,k=event['signal_index'],event['entry_index'],event['exit_index'];r=dict(signal_at=grid[i]['at'],feature=event['feature'],entry_at=grid[j]['at'],complete=k is not None)
  if k is not None:
   r['exit_at']=grid[k]['at'];r['btc_mark_return']=grid[k]['prices']['BTCUSDT']/grid[j]['prices']['BTCUSDT']-1
   try:r['long']=trade(j,k,1);r['short']=trade(j,k,-1)
   except (ValueError,AssertionError) as exc:r['cost_or_funding_unavailable']=str(exc)
  episodes.append(r)
 valid=[v for v in episodes if 'short' in v]
 results[rule]=dict(episodes=episodes,complete_valid=len(valid),short_net=sum(v['short']['net'] for v in valid),long_net=sum(v['long']['net'] for v in valid),short_winners=sum(v['short']['net']>0 for v in valid),cash_reference_net=0,reference_capital=10000,fixed_target_notional=1000,continuous_compounding=False)
save('models.json',results)
features_near=[]
for i,row in enumerate(grid):
 if row['at'].startswith(('2026-10-14T12:','2026-10-14T13:','2026-10-15T00:','2026-10-15T02:')):
  features_near.append(dict(at=row['at'],**(model.features(grid,i) or {})))
save('features-near-events.json',features_near)
enriched=copy.deepcopy(results)
for value in enriched.values():
 valid=[e for e in value['episodes'] if 'short' in e]
 for e in valid:
  prices=[r['prices']['BTCUSDT'] for r in grid if e['entry_at']<=r['at']<=e['exit_at']]
  e['max_adverse_short_mark_usdt']=e['short']['quantity']*max(0,max(prices)-e['short']['entry_price'])
 value['prior_to_oct14_short_net']=sum(e['short']['net'] for e in valid if e['signal_at']<'2026-10-14')
 value['oct14_15_short_net']=sum(e['short']['net'] for e in valid if e['signal_at']>='2026-10-14')
 value['extra_20bps_roundtrip_short_net']=value['short_net']-sum(e['short']['quantity']*e['short']['entry_price']*.002 for e in valid)
save('models-enriched.json',enriched)
# Attribute exact inherited average-cost positions, all subsequent fills, funding and marks.
fills={'ORIGINAL':[dict(r) for r in original.execute("select * from orders where status='filled' and bar>? order by bar,id",(iso(t0),))]}
funds={'ORIGINAL':[dict(r) for r in original.execute('select * from funding_events where timestamp_ms>? order by timestamp_ms',(int(t0*1000),))]}
for arm in ['FAST','HALF']:
 fills[arm]=[json.loads(r[0]) for r in paired.execute('select payload from fills where arm=? order by at,id',(arm,))]
 funds[arm]=[dict(json.loads(r[0]),timestamp_ms=r[1]) for r in paired.execute('select payload,at from funding where arm=? order by at',(arm,))]
def state_at(arm,t,observation_marks=None):
 p=copy.deepcopy(parent['positions'])
 for f in fills[arm]:
  if seconds(f.get('bar',f.get('at')))>t:continue
  v=p[f['symbol']];old=v['quantity'];q=f['quantity'];new=old+q;price=f['price']
  if old*q<0:v['realized_pnl']+=min(abs(old),abs(q))*(price-v['entry_price'])*(1 if old>0 else -1)
  if abs(new)<1e-10:new=0;v['entry_price']=0
  elif old==0 or old*new<0:v['entry_price']=price
  elif old*q>0:v['entry_price']=(abs(old)*v['entry_price']+abs(q)*price)/abs(new)
  v['quantity']=new;v['fees']+=f['fee']
 for f in funds[arm]:
  if f['timestamp_ms']<=t*1000:p[f['symbol']]['funding']+=f['amount']
 for s,v in p.items():v['current_price']=observation_marks[s] if observation_marks else price_at(s,t)
 def net(v):return v['realized_pnl']+v['quantity']*(v['current_price']-v['entry_price'])-v['fees']+v['funding']
 nets={s:net(v) for s,v in p.items()}
 return dict(at=iso(t),equity=parent['initial_equity']+sum(nets.values()),gross=sum(abs(v['quantity']*v['current_price']) for v in p.values()),net_exposure=sum(v['quantity']*v['current_price'] for v in p.values()),pnl=nets,positions=p)
lastobs=json.loads(paired.execute('select payload from observations order by at desc limit 1').fetchone()[0]);end_original=seconds(lastobs['original_at'])
last_hash=paired.execute('select market_hash from observations order by at desc limit 1').fetchone()[0]
raw=gzip.decompress((archives/(last_hash+'.json.gz')).read_bytes());last_market=json.loads(raw)
assert hashlib.sha256(json.dumps({k:v for k,v in last_market.items() if k!='record_hash'},sort_keys=True,separators=(',',':'),ensure_ascii=False).encode()).hexdigest()==last_hash
observed_marks={s:q['mark_price'] for s,q in last_market['quotes'].items()}
check={}
for arm in ['ORIGINAL','FAST','HALF']:
 target=original.execute('select equity from equity_history where bar=?',(lastobs['original_at'],)).fetchone()[0] if arm=='ORIGINAL' else lastobs['states'][arm]['equity']
 t=end_original if arm=='ORIGINAL' else end
 reconstructed=state_at(arm,t,observed_marks if arm!='ORIGINAL' else None)['equity']
 check[arm]=dict(reconstructed=reconstructed,recorded=target,error=reconstructed-target)
 assert abs(check[arm]['error'])<1e-6,check
points=[iso(t0),'2026-10-14T12:25:00+00:00','2026-10-14T12:35:00+00:00','2026-10-14T18:30:00+00:00','2026-10-15T02:20:00+00:00','2026-10-15T02:30:00+00:00',iso(end_original)]
values={at:{arm:state_at(arm,seconds(at)) for arm in fills} for at in points}
for at,v in values.items():
 for arm,state in v.items():state['since_fork']={s:n-(parent['positions'][s]['realized_pnl']+parent['positions'][s]['quantity']*(parent['positions'][s]['current_price']-parent['positions'][s]['entry_price'])-parent['positions'][s]['fees']+parent['positions'][s]['funding']) for s,n in state['pnl'].items()}
save('attribution.json',dict(reconciliation=check,points=values))
observations=[dict(at=r[0],**json.loads(r[1])) for r in paired.execute('select at,payload from observations order by at')]
worst=sorted([dict(start=a['at'],end=b['at'],changes={arm:b['states'][arm]['equity']-a['states'][arm]['equity'] for arm in fills}) for a,b in zip(observations,observations[1:])],key=lambda x:x['changes']['ORIGINAL'])[:12]
save('event_timeline.json',dict(worst_intervals=worst,observations=observations))
save('archive-manifest.json',used)
print('coverage',len(grid),'missing',len(missing),'books',len(used));print('reconciliation',check)
for name,r in results.items():print(name,{k:v for k,v in r.items() if k!='episodes'},'last episodes',r['episodes'][-4:])
for at,v in values.items():print(at,{a:round(x['equity'],4) for a,x in v.items()})
