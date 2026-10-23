"""Frozen, isolated Timestral/M1/simple BTC-sleeve pilot. Never an order client.

Cards 00bd0cb1,54f64f8b,1e1f028d. Live inputs read only in prepare; inference
can see only causal contexts. No existing prospective-study outcome is opened.
"""
import argparse,datetime as dt,hashlib,json,math,resource,sqlite3,time
from pathlib import Path
from . import timestral_m1_reference_v1 as detector
UTC=dt.timezone.utc
SYMBOLS=tuple(sorted(s+'USDT' for s in 'AAVE ADA ATOM AVAX BCH BTC DOGE DOT ETH HBAR LINK LTC NEAR SOL UNI XLM XRP ZEC'.split()))

def digest(value):return hashlib.sha256(json.dumps(value,sort_keys=True,separators=(',',':'),allow_nan=False).encode()).hexdigest()
def sha(path):return hashlib.sha256(Path(path).read_bytes()).hexdigest()
def stamp(value):return int(dt.datetime.fromisoformat(value).timestamp())
def iso(value):return dt.datetime.fromtimestamp(value,UTC).isoformat()
def write(path,value):Path(path).write_text(json.dumps(value,indent=2,allow_nan=False)+'\n')
def ro(path,sealed=False):
 # immutable is only for the separately qualified, sealed historical copy.
 c=sqlite3.connect(Path(path).resolve().as_uri()+'?mode=ro'+('&immutable=1' if sealed else ''),uri=True);c.execute('PRAGMA query_only=ON');return c

def protocol(path):
 p=json.loads(Path(path).read_text());assert p['protocol_id']==digest({k:v for k,v in p.items() if k!='protocol_id'});return p

def grids(records,start,end,max_age=120):
 """Every point is as-of receipt-time, no interpolation or future backfill."""
 rows=iter(records);pending=next(rows,None);last={};result=[]
 for grid in range(start,end+1,300):
  while pending is not None and pending[0]<=grid:
   at,s,price=pending;assert s in SYMBOLS and math.isfinite(price) and price>0
   last[s]=(at,price);pending=next(rows,None)
  valid=len(last)==len(SYMBOLS) and all(0<=grid-last[s][0]<=max_age for s in SYMBOLS)
  result.append(dict(time=grid,valid=valid,prices={s:last[s][1] for s in SYMBOLS} if valid else {},source_times={s:last[s][0] for s in SYMBOLS} if valid else {}))
 return result

def causal_input(rows,index):
 """Only past 289 points; the first 12 breadth values are deliberately unknown."""
 if index<288:return None
 context=rows[index-288:index+1]
 if any(not r['valid'] or set(r['prices'])!=set(SYMBOLS) or set(r['source_times'])!=set(SYMBOLS) or any(not 0<=r['time']-v<=120 for v in r['source_times'].values()) for r in context) or any(b['time']-a['time']!=300 for a,b in zip(context,context[1:])):return None
 btc=[math.log(r['prices']['BTCUSDT']) for r in context];breadth=[None]*12
 for i in range(12,289):breadth.append(sum(context[i]['prices'][s]<context[i-12]['prices'][s] for s in SYMBOLS)/18)
 raw=dict(time=rows[index]['time'],btc=btc,breadth=breadth,source_times=[r['source_times'] for r in context])
 return dict(index=index,slot=rows[index]['time'],fingerprint=digest(raw),btc=btc,breadth=breadth,feature=detector.features(context,288))

def book(db,due,wait=1):
 fields=['id','session_id','exchange_ts_ns','received_ts_ns']+[s+'_'+f+'_'+str(i) for s in ('bid','ask') for i in range(1,6) for f in ('price','size')]
 row=db.execute('SELECT '+','.join(fields)+' FROM book_events INDEXED BY idx_book_received WHERE received_ts_ns>=? AND received_ts_ns<=? AND latency_ms>=0 AND latency_ms<=1000 ORDER BY received_ts_ns LIMIT 1',(int(due*1e9),int((due+wait)*1e9))).fetchone()
 if row is None:return None
 v=dict(zip(fields,row));assert v['received_ts_ns']>=due*1e9 and 0<=v['received_ts_ns']-v['exchange_ts_ns']<=1e9
 sides={}
 for side in ('bid','ask'):
  levels=[[v[f'{side}_price_{i}'],v[f'{side}_size_{i}']] for i in range(1,6)]
  if any(not math.isfinite(x) or x<=0 for level in levels for x in level):raise ValueError('invalid_book')
  prices=[x[0] for x in levels];assert prices==sorted(prices,reverse=side=='bid');sides[side]=levels
 assert sides['bid'][0][0]<sides['ask'][0][0]
 return dict(id=v['id'],session=v['session_id'],received_ns=v['received_ts_ns'],exchange_ns=v['exchange_ts_ns'],**sides)

def prepare(args):
 import numpy as np
 p=protocol(args.protocol);out=Path(args.output);out.mkdir(exist_ok=True);start=stamp(p['period']['warmup_start']);end=stamp(p['period']['end_exclusive']);c=ro(args.original)
 records=((dt.datetime.fromisoformat(t).timestamp(),s,float(v)) for t,s,v in c.execute('SELECT bar,symbol,price FROM marks WHERE bar>=? AND bar<=? ORDER BY bar',(iso(start-120),iso(end))))
 rows=grids(records,start,end,p['input']['source_age_seconds']);funding=[dict(time=t//1000,rate=rate,mark=mark) for t,rate,mark in c.execute("SELECT timestamp_ms,rate,reference_mark FROM funding_events WHERE symbol='BTCUSDT' AND timestamp_ms>=? AND timestamp_ms<=? ORDER BY timestamp_ms",((start-86400)*1000,end*1000))];c.close()
 assert all(math.isfinite(v['rate']) and math.isfinite(v['mark']) and v['mark']>0 for v in funding)
 assert Path(args.scalping).stat().st_size==27573239808 and not Path(args.scalping).stat().st_mode&0o222
 source=ro(args.scalping,sealed=True);initial=source.execute('SELECT MAX(id) FROM book_events').fetchone()[0];quotes={};inputs=[];start_decision=stamp(p['period']['start']);expected=0;missing=0
 for i,r in enumerate(rows):
  if r['time']>=start_decision:
   quotes[str(r['time'])]=book(source,r['time'],p['execution']['quote_wait_seconds'])
  if not start_decision<=r['time']<end:continue
  expected+=1;item=causal_input(rows,i)
  if item:inputs.append(item)
  else:missing+=1
 source.close()
 np.savez_compressed(out/'contexts.npz',btc=np.array([v['btc'] for v in inputs],dtype=np.float32)[:,None,:],breadth=np.array([[float('nan') if x is None else x for x in v['breadth']] for v in inputs],dtype=np.float32)[:,None,:],slots=np.array([v['slot'] for v in inputs],dtype=np.int64))
 write(out/'inputs.json',[{k:v for k,v in x.items() if k not in ('btc','breadth')} for x in inputs]);write(out/'outcomes.json',dict(rows=rows,quotes=quotes,funding=funding))
 summary=dict(protocol_id=p['protocol_id'],scope=p['scope'],expected_decision_slots=expected,valid_contexts=len(inputs),invalid_contexts=missing,missing_book_points=sum(v is None for v in quotes.values()),book_points=len(quotes),funding_points=len(funding),source_original_copy_sha256=sha(args.original),scalping_boundary_id=initial,scalping_snapshot_bytes=Path(args.scalping).stat().st_size,scalping_expected_sha256='1141375eb2945a09c261e9f1d7b64972d532e2debd4e8543121734d9b739e678',scalping_full_hash_repeated=False,data_files={v.name:sha(v) for v in out.iterdir() if v.is_file()})
 write(out/'dataset-manifest.json',summary);print(json.dumps(summary),flush=True)

def infer(args):
 receipt=json.loads(Path(args.license_confirmation).read_text())
 if receipt.get('operator_confirmed_eligibility') is not True:raise ValueError('model_license_eligibility_not_confirmed')
 import numpy as np,torch
 from timestral import TimestralForecaster
 p=protocol(args.protocol);data=Path(args.data);out=Path(args.output);out.mkdir(exist_ok=True);manifest=json.loads((data/'dataset-manifest.json').read_text());assert manifest['protocol_id']==p['protocol_id'];assert all(sha(data/name)==manifest['data_files'][name] for name in ('contexts.npz','inputs.json'));c=np.load(data/'contexts.npz');items=json.loads((data/'inputs.json').read_text());torch.set_num_threads(p['input']['torch_threads']);torch.set_num_interop_threads(1);torch.manual_seed(0)
 assert sha(Path(args.model)/'model.safetensors')==p['model_weights_sha256'];started=time.monotonic();f=TimestralForecaster.from_pretrained(args.model,device='cpu',local_files_only=True,token=False);load=time.monotonic()-started;pred=[];latencies=[];batch=p['input']['batch_size']
 for start in range(0,len(items),batch):
  before=time.monotonic()
  with torch.inference_mode():v=f.forecast(c['btc'][start:start+batch],prediction_length=p['input']['model_horizon_steps'],past_covariates=c['breadth'][start:start+batch])
  q=v.quantiles[:,:,-1,:].detach().cpu().numpy();assert np.isfinite(q).all();assert np.all(np.diff(q,axis=-1)>=-1e-6);elapsed=time.monotonic()-before;latencies.append(elapsed)
  if start==0:
   with torch.inference_mode():one=f.forecast(c['btc'][:1],prediction_length=p['input']['model_horizon_steps'],past_covariates=c['breadth'][:1]).quantiles[:,:,-1,:].detach().cpu().numpy()
   assert np.allclose(one,q[:1],atol=2e-5,rtol=0),'batch_cross_sample_dependency'
  for k,item in enumerate(items[start:start+batch]):pred.append(dict(slot=item['slot'],fingerprint=item['fingerprint'],quantiles=[float(x) for x in q[k,0]],levels=list(v.quantile_levels)))
  if start//batch%20==0:print(json.dumps(dict(progress=min(start+batch,len(items)),total=len(items),elapsed_seconds=round(time.monotonic()-started,2))),flush=True)
 write(out/'predictions.json',dict(protocol_id=p['protocol_id'],contexts_sha256=sha(data/'contexts.npz'),model_sha256=p['model_weights_sha256'],records=pred));write(out/'runtime.json',dict(model_parameters=sum(x.numel() for x in f.model.parameters()),torch=torch.__version__,cpu_threads=torch.get_num_threads(),model_load_seconds=load,total_seconds=time.monotonic()-started,batch_latencies_seconds=latencies,peak_rss_kib=resource.getrusage(resource.RUSAGE_SELF).ru_maxrss,network='none',device=str(f.device)))
 print('Inference complete',len(pred),flush=True)

def fill_price(q,side,quantity,multiplier,slip):
 remaining=quantity;value=0.
 for price,native in q[side]:
  take=min(remaining,native*multiplier);value+=take*price;remaining-=take
  if remaining<=1e-10:return value/quantity*(1+slip if side=='ask' else 1-slip)
 raise ValueError('insufficient_L5_depth')

def settlement_value(points,start,end,quantity):
 prior=[v for v in points if v['time']<=start]
 if not prior:raise ValueError('funding_start_unknown')
 selected=[v for v in points if start<v['time']<=end];times=[prior[-1]['time']]+[v['time'] for v in selected]
 if any(b-a!=28800 for a,b in zip(times,times[1:])) or end-times[-1]>=28800:raise ValueError('funding_gap')
 return quantity*math.fsum(v['rate']*v['mark'] for v in selected)

def episode(data,p,slot,stress=1):
 e=p['execution'];due=slot+e['entry_delay_seconds'];exitdue=due+e['holding_seconds'];entry=data['quotes'].get(str(due));exit_=data['quotes'].get(str(exitdue))
 if entry is None:return dict(status='ENTRY_UNAVAILABLE',due=due,exit_due=exitdue)
 if exit_ is None:return dict(status='EXIT_UNAVAILABLE',due=due,exit_due=exitdue)
 mark=(entry['bid'][0][0]+entry['ask'][0][0])/2;quantity=math.floor(e['fixed_notional_per_episode']/mark/e['quantity_step_btc'])*e['quantity_step_btc']
 if quantity<=0:return dict(status='BELOW_SYNTHETIC_STEP',due=due,exit_due=exitdue)
 try:pe=fill_price(entry,'bid',quantity,e['synthetic_base_per_native_unit'],e['adverse_slippage_bps_per_fill']/10000*stress)
 except ValueError as error:return dict(status=str(error),due=due,exit_due=exitdue,stage='entry',unresolved_position=False)
 try:px=fill_price(exit_,'ask',quantity,e['synthetic_base_per_native_unit'],e['adverse_slippage_bps_per_fill']/10000*stress)
 except ValueError as error:return dict(status=str(error),due=due,exit_due=exitdue,stage='exit',unresolved_position=True)
 fees=quantity*(pe+px)*e['fee_bps_per_fill']/10000*stress;gross=quantity*(pe-px)
 try:funding=settlement_value(data['funding'],entry['received_ns']/1e9,exit_['received_ns']/1e9,quantity)
 except ValueError as error:return dict(status=str(error),due=due,exit_due=exitdue,quantity=quantity,gross=gross,fees=fees)
 return dict(status='COMPLETE',due=due,exit_due=exitdue,quantity=quantity,entry_price=pe,exit_price=px,gross=gross,fees=fees,funding=funding,net=gross-fees+funding,entry_received_ns=entry['received_ns'],exit_received_ns=exit_['received_ns'])

def evaluate(args):
 import numpy as np
 p=protocol(args.protocol);data=Path(args.data);out=Path(args.output);manifest=json.loads((data/'dataset-manifest.json').read_text());assert manifest['protocol_id']==p['protocol_id'] and all(sha(data/name)==manifest['data_files'][name] for name in ('contexts.npz','inputs.json','outcomes.json'));inputs=json.loads((data/'inputs.json').read_text());outcomes=json.loads((data/'outcomes.json').read_text());preds=json.loads((out/'predictions.json').read_text());assert preds['protocol_id']==p['protocol_id'] and preds['contexts_sha256']==sha(data/'contexts.npz') and preds['model_sha256']==p['model_weights_sha256'] and len(inputs)==len(preds['records']);end=stamp(p['period']['end_exclusive']);rows=outcomes['rows'];forecast_rows=[];signals={key:[] for key in ('timestral','m1','simple')};excluded_labels=0
 for inp,pred in zip(inputs,preds['records']):
  assert inp['fingerprint']==pred['fingerprint'] and inp['slot']==pred['slot'];index=inp['index'];current=math.log(rows[index]['prices']['BTCUSDT']);q=pred['quantiles'];levels=pred['levels'];median=q[levels.index(.5)]-current;signals['timestral'].append(median<=math.log(.99));signals['m1'].append(detector.signal(inp['feature'],'momentum_breadth'));signals['simple'].append(inp['feature']['btc_60m']<=-.01)
  future=index+p['input']['model_horizon_steps']
  if future>=len(rows) or rows[future]['time']>=end or not rows[future]['valid']:excluded_labels+=1;continue
  actual=math.log(rows[future]['prices']['BTCUSDT'])-current;lo=q[levels.index(.1)]-current;hi=q[levels.index(.9)]-current
  forecast_rows.append(dict(slot=inp['slot'],date=iso(inp['slot'])[:10],actual_log_return=actual,predicted_log_return=median,absolute_error=abs(median-actual),persistence_absolute_error=abs(actual),squared_error=(median-actual)**2,persistence_squared_error=actual**2,interval_covered=lo<=actual<=hi,interval_width=hi-lo))
 metrics=dict(complete_labels=len(forecast_rows),missing_or_tail_labels=excluded_labels,mae_bps=float(np.mean([r['absolute_error'] for r in forecast_rows])*10000),persistence_mae_bps=float(np.mean([r['persistence_absolute_error'] for r in forecast_rows])*10000),rmse_bps=float(np.sqrt(np.mean([r['squared_error'] for r in forecast_rows]))*10000),persistence_rmse_bps=float(np.sqrt(np.mean([r['persistence_squared_error'] for r in forecast_rows]))*10000),coverage_80=float(np.mean([r['interval_covered'] for r in forecast_rows])),mean_interval_width_bps=float(np.mean([r['interval_width'] for r in forecast_rows])*10000))
 metrics['mae_ratio_to_persistence']=metrics['mae_bps']/metrics['persistence_mae_bps'];days={d:dict(timestral_mae_bps=float(np.mean([r['absolute_error'] for r in forecast_rows if r['date']==d])*10000),persistence_mae_bps=float(np.mean([r['persistence_absolute_error'] for r in forecast_rows if r['date']==d])*10000),samples=sum(r['date']==d for r in forecast_rows)) for d in sorted({r['date'] for r in forecast_rows})};methods={}
 for method,flags in signals.items():
  ready=-math.inf;entry_days=set();episodes=[];reasons={};halted=False
  for inp,flag in zip(inputs,flags):
   if not flag:continue
   slot=inp['slot'];day=iso(slot)[:10]
   reason='EXIT_UNRESOLVED_HALTED' if halted else 'HORIZON_OUTSIDE' if slot+300+21600+1>end else 'COOLDOWN' if slot<ready else 'DAILY_LIMIT' if day in entry_days else None
   if reason:reasons[reason]=reasons.get(reason,0)+1;continue
   value=episode(outcomes,p,slot);stress=episode(outcomes,p,slot,p['execution']['stress_multiplier_fee_and_slippage']);episodes.append(dict(slot=slot,day=day,base=value,stress=stress));entry_days.add(day);ready=slot+300+21600+21600
   if value['status']=='EXIT_UNAVAILABLE' or value.get('unresolved_position'):halted=True
  complete=[v for v in episodes if v['base']['status']=='COMPLETE'];missing=[v for v in episodes if v['base']['status']!='COMPLETE'];methods[method]=dict(raw_signals=sum(flags),admitted=len(episodes),complete=len(complete),censored=len(missing),suppressed=reasons,base_net_observed=sum(v['base']['net'] for v in complete),base_fees=sum(v['base']['fees'] for v in complete),funding=sum(v['base']['funding'] for v in complete),stress_net_observed=sum(v['stress']['net'] for v in complete if v['stress']['status']=='COMPLETE'),wins=sum(v['base']['net']>0 for v in complete),interpretation='INCONCLUSIVE_MISSING_EXECUTION_OR_FUNDING' if missing else 'EXPLORATORY_FIXED_SIZE_EPISODE_PNL_NOT_A_LIVE_ACCOUNT',episodes=episodes)
 result=dict(protocol_id=p['protocol_id'],scope=p['scope'],forecast=metrics,per_day=days,methods=methods,forecast_metric_units='log return bps',economic_units='USDT under explicitly synthetic unit mapping',limitations=p['limitations']);write(out/'results.json',result);write(out/'forecast-outcomes.json',forecast_rows);print(json.dumps({k:result[k] for k in ('forecast',)}),flush=True);print(json.dumps({k:{x:y for x,y in v.items() if x!='episodes'} for k,v in methods.items()},indent=2),flush=True)

def main():
 a=argparse.ArgumentParser();a.add_argument('phase',choices=['prepare','infer','evaluate']);a.add_argument('--protocol',required=True);a.add_argument('--output',required=True);a.add_argument('--original');a.add_argument('--scalping');a.add_argument('--data');a.add_argument('--model');a.add_argument('--license-confirmation');args=a.parse_args();globals()[args.phase](args)
if __name__=='__main__':main()
