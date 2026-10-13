"""Offline fast-protection replay; fixed archived inputs, no network or live writes.

Card: work-card-5c4e17ca-19f8-460f-a59f-3be148cffd9b.
Run only as a diagnostic with /base and /evidence mounts; not a runtime module."""
import json,datetime as dt,collections,math
from pathlib import Path
from octobot.ai_strategy_lab import v13_paper_v2 as paper
from octobot.ai_strategy_lab import v13_research_paper as engine
D=json.loads(Path('/base/snapshot.json').read_text())
SIGNALS=json.loads(Path('/evidence/signals.json').read_text())['features']
START='2026-09-28T20:05:52.361621+00:00'
def millis(t):return int(dt.datetime.fromisoformat(t).timestamp()*1000)
batches=collections.defaultdict(list)
for o in D['orders']:batches[o['bar']].append(o)
first_targets={s:float(v) for s,v in D['proposals']['2026-09-28']['targets'].items()} if '2026-09-28' in D['proposals'] else None
# Identify changes from complete proposal vector, not whether a symbol traded.
previous=None;changed={};targets_by_bar={}
for bar in sorted(batches):
 if bar<START:continue
 day=(dt.datetime.fromisoformat(bar).date()-dt.timedelta(days=1)).isoformat()
 if bar==START:
  # Initial common bootstrap follows its actual, already executed allocation.
  changed[bar]=True;continue
 targets={s:float(v) for s,v in D['proposals'][day]['targets'].items()}
 if previous is None:
  prior=[k for k in D['proposals'] if k<day]
  previous={s:float(v) for s,v in D['proposals'][max(prior)]['targets'].items()}
 changed[bar]=targets!=previous;targets_by_bar[bar]=targets;previous=targets

def run(mode):
 reduced={s:False for s in D['marks']};transitions=[];trajectory=[]
 state={'initial_equity':10000.,'positions':{s:paper.new_position() for s in D['marks']}}
 pos=state['positions'];trades=[];notes=[];matches=[]
 timeline=[(millis(bar),1,bar) for bar in batches]+[(f['timestamp_ms'],0,f) for f in D['funding']]
 for _,kind,event in sorted(timeline,key=lambda x:(x[0],x[1])):
  if kind==0:
   f=event;p=pos[f['symbol']];p['funding']+=-p['quantity']*f['reference_mark']*f['rate'];continue
  bar=event;actual=batches[bar]
  if bar<=START or mode=='actual':legs=actual
  else:
   book=D['books'][actual[0]['market_hash']]
   for s,q in book['quotes'].items():pos[s]['current_price']=q['mark_price']
   targets=dict(targets_by_bar[bar])
   if mode=='fast':
    for sym,weight in targets.items():
     f=SIGNALS[bar][sym];prior=reduced[sym]
     if f['below']:reduced[sym]=True
     elif f['above']:reduced[sym]=False
     if prior!=reduced[sym]:transitions.append(dict(bar=bar,symbol=sym,reduced=reduced[sym],close=f['close'],sma=f['sma']))
     if weight>0 and reduced[sym]:targets[sym]=weight*.5
   legs,n=engine.research_plan(state,book['quotes'],targets,True) if mode in ('daily','no_topups','fast') or changed[bar] else ([],[])
   notes.extend(dict(bar=bar,**x) for x in n)
   if mode=='fast':legs=[x for x in legs if not (reduced[x['symbol']] and targets[x['symbol']]>0 and not x['protective'])]
   if mode=='no_topups' and not changed[bar]:legs=[x for x in legs if x['protective']]
   if mode=='daily':
    observed={x['symbol']:x for x in actual};predicted={x['symbol']:x for x in legs}
    matches.append(dict(bar=bar,same_symbols=set(observed)==set(predicted),max_quantity_error=max([abs(x['quantity']-observed[s]['quantity']) for s,x in predicted.items() if s in observed] or [0]),max_price_error=max([abs(x['price']-observed[s]['price']) for s,x in predicted.items() if s in observed] or [0])))
  for leg in legs:
   s=leg['symbol'];before=pos[s]['quantity'];paper.apply_fill(pos[s],leg['quantity'],leg['price'],leg['fee'])
   trades.append(dict(bar=bar,symbol=s,quantity=leg['quantity'],price=leg['price'],fee=leg['fee'],before=before,intermediate=bar>START and not changed[bar]))
  if bar>=START:
   book=D['books'][actual[0]['market_hash']]
   for sym,q in book['quotes'].items():pos[sym]['current_price']=q['mark_price']
   trajectory.append(dict(bar=bar,equity=paper.totals(state)['equity']))
 for s,v in D['marks'].items():pos[s]['current_price']=v
 totals=paper.totals(state)
 symbols={s:dict(quantity=p['quantity'],net=p['realized_pnl']+p['quantity']*(p['current_price']-p['entry_price'])-p['fees']+p['funding'],fees=p['fees'],funding=p['funding']) for s,p in pos.items()}
 trajectory.append(dict(bar=D['last']['bar'],equity=totals['equity']))
 return dict(transitions=transitions,trajectory=trajectory,totals=totals,symbols=symbols,trades=trades,notes=notes,matches=matches,turnover=sum(abs(x['quantity']*x['price']) for x in trades))

results={mode:run(mode) for mode in ['actual','daily','fast']}
assert abs(results['actual']['totals']['equity']-D['last']['equity'])<1e-6
assert all(x['same_symbols'] and x['max_quantity_error']<1e-7 and x['max_price_error']<1e-7 for x in results['daily']['matches'])
assert abs(results['daily']['totals']['equity']-D['last']['equity'])<1e-6
# Funding event support: no counterfactual exposure at dates when actual is flat.
qa=collections.defaultdict(float);qb=collections.defaultdict(float);ev=collections.defaultdict(list)
for mode,k in [('actual',0),('fast',1)]:
 for x in results[mode]['trades']:ev[x['bar']].append((k,x))
for bar,events in sorted(ev.items()):
 for k,x in events:(qa if k==0 else qb)[x['symbol']]+=x['quantity']
 assert all(abs(q)<1e-8 or abs(qa[s])>1e-8 for s,q in qb.items()),('funding support missing',bar)
for mode,v in results.items():
 peak=v['trajectory'][0]['equity'];dd=0
 for point in v['trajectory']:
  peak=max(peak,point['equity']);dd=max(dd,1-point['equity']/peak)
 v['sampled_drawdown_pct']=dd*100
intervals=[]
a=results['daily']['trajectory'];b=results['fast']['trajectory']
for i in range(1,len(a)):
 av=a[i]['equity']-a[i-1]['equity'];bv=b[i]['equity']-b[i-1]['equity']
 intervals.append(dict(to=a[i]['bar'],baseline_change=av,protected_change=bv,delta=bv-av))
results['intervals']=intervals
results['protocol_sha256']=__import__('hashlib').sha256(Path('/evidence/protocol.json').read_bytes()).hexdigest()
Path('/evidence/results.json').write_text(json.dumps(results,indent=2))
for mode in ['daily','fast']:print(mode,results[mode]['totals'],'fills',len(results[mode]['trades']),'sampled_dd',results[mode]['sampled_drawdown_pct'])
print('changes',len(results['fast']['transitions']))
