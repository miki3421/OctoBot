"""Read-only, reproducible audit of a frozen M1 weekly proposal.

No live Runner/Store instantiation, decision, order, network request or DB write.
Card work-card-e3855103-c502-42b2-9ba9-a30e11061b3e.
"""
import copy,datetime as dt,gzip,hashlib,json,math,statistics,sqlite3
from pathlib import Path
from urllib.parse import urlsplit,parse_qs
import numpy as np
from octobot.ai_strategy_lab import v13_m1_weekly as weekly,v13_m1_paper as paper,trend,v13_research_source as source
E=Path('/evidence');S=Path('/source');UTC=dt.timezone.utc

def read(p):return json.loads(gzip.decompress(p.read_bytes()) if p.suffix=='.gz' else p.read_bytes())
def digest(v):return hashlib.sha256(json.dumps(v,sort_keys=True,separators=(',',':'),allow_nan=False).encode()).hexdigest()
def verify(v,key):assert digest({k:x for k,x in v.items() if k!=key})==v[key],key

def main():
 p=read(E/'proposal.json');sc=read(E/'science.json');market=read(E/'market.json.gz');verify(p,'proposal_id');verify(sc,'snapshot_id');verify(market,'record_hash')
 assert sc['snapshot_id']==p['science_id'] and market['record_hash']==p['market_hash']
 cutoff=dt.datetime.fromisoformat(p['created_at']);raw_by_symbol={};receipts={};counts={'science':0,'market':0}
 for scope,ids in [('science',sc['capture_ids']),('market',market['capture_ids'])]:
  for ident in ids:
   v=read(S/'raw'/(ident+'.json.gz'));verify(v,'capture_id');raw=bytes.fromhex(v['raw_hex']);assert hashlib.sha256(raw).hexdigest()==v['raw_sha256'];assert dt.datetime.fromisoformat(v['started_at'])<=dt.datetime.fromisoformat(v['received_at'])<=cutoff
   assert v['capture_id']==ident and v['status']==200 and v['kind']=='LIVE_PUBLIC_HTTPS_CAPTURE';url=urlsplit(v['url']);assert url.scheme=='https' and url.netloc in ('fapi.binance.com','api-futures.kucoin.com');receipts[ident]=v;counts[scope]+=1
   if scope=='science' and url.path=='/fapi/v1/klines':
    query=parse_qs(url.query);assert query['interval']==['1d'];symbol=query['symbol'][0];assert symbol not in raw_by_symbol
    raw_by_symbol[symbol]=[(dt.datetime.fromtimestamp(int(r[0])/1000,UTC).date().isoformat(),float(r[4])) for r in json.loads(raw)]
 assert set(raw_by_symbol)==set(weekly.POOL)
 rows=[];raw_signals={}
 for s in weekly.POOL:
  bars=sc['bars'][s];prices=[x['close'] for x in bars];assert len(bars)==121 and raw_by_symbol[s]==[(v['day'],v['close']) for v in bars]
  assert all((dt.date.fromisoformat(bars[i+1]['day'])-dt.date.fromisoformat(bars[i]['day'])).days==1 for i in range(120))
  assert dt.date.fromisoformat(bars[-1]['day'])<cutoff.date()
  r30=prices[-1]/prices[-31]-1;r120=prices[-1]/prices[0]-1;signal=1 if r30>0 and r120>0 else -1 if r30<0 and r120<0 else 0;raw_signals[s]=signal
  vol=statistics.stdev([prices[i]/prices[i-1]-1 for i in range(61,121)])
  rows.append(dict(symbol=s,r30=r30,r120=r120,raw_signal=signal,volatility_annual=vol*math.sqrt(365),score_raw=min(abs(r30)/math.sqrt(30),abs(r120)/math.sqrt(120))/vol if signal else None,selected=s in p['selected'],long_cap=p['long_caps'][s],short_cap=p['short_caps'][s]))
 for row in rows:
  s=row['symbol'];effective=row['raw_signal'] if row['raw_signal']>=0 or raw_signals['BTCUSDT']<0 else 0
  if s in p['ineligible']:effective=0
  assert effective==p['rows'][s]['signal'];row['effective_signal']=effective;row['ineligible']=p['ineligible'].get(s)
 positions={s:dict(quantity=v['quantity'],current_price=v['mark']) for s,v in p['indicative_positions'].items()}
 reproduced=weekly.proposal(sc,market,account=p['account'],revision=p['parent_revision'],previous=p['previous'],positions=positions,equity=p['reference_equity'],at=p['created_at'])
 assert reproduced==p,'proposal reconstruction mismatch'
 symbols=sorted(sc['bars']);x=np.array([[v['close'] for v in sc['bars'][s][-61:]] for s in symbols]).T;cov=np.cov(x[1:]/x[:-1]-1,rowvar=False,ddof=1)*365
 signals=np.array([p['rows'][s]['signal'] if s in p['selected'] else 0 for s in symbols]);inverse=np.where(signals!=0,1/np.sqrt(np.diag(cov)),0);unit=signals*inverse;unit=unit/np.abs(unit).sum();scale=min(.9,.135/np.sqrt(unit@cov@unit));independent=np.clip(unit*scale,-.315,.315);assert np.allclose(independent,np.array([p['long_caps'][s] for s in symbols]),atol=1e-12)
 equity=p['reference_equity'];held_weights={s:v['quantity']*v['mark']/equity for s,v in p['indicative_positions'].items()};target=p['long_caps'];oldgross=sum(abs(v) for v in held_weights.values());newgross=sum(target.values());neww=np.array([target.get(s,0) for s in symbols]);oldw=np.array([held_weights.get(s,0) for s in symbols]);marginal=neww*(cov@neww)/float(neww@cov@neww)
 for row in rows:
  s=row['symbol'];i=symbols.index(s);row.update(current_weight=held_weights.get(s,0),long_share=target[s]/newgross,variance_contribution=float(marginal[i]),spread_bps=(market['quotes'][s]['asks'][0]['price']-market['quotes'][s]['bids'][0]['price'])/((market['quotes'][s]['asks'][0]['price']+market['quotes'][s]['bids'][0]['price'])/2)*10000 if s in market['quotes'] else None)
 cost=sum(v['immediate_equity_cost'] for v in p['indicative_changes'].values() if v['cost_available']);fees=sum(v['fee'] for v in p['indicative_changes'].values() if v['cost_available']);turnover=sum(abs(v['indicative_delta'])*market['quotes'][s]['mark_price'] for s,v in p['indicative_changes'].items())
 sold=[s for s,v in p['indicative_changes'].items() if v['indicative_target']==0 and v['current_quantity']>0];bought=[s for s,v in p['indicative_changes'].items() if v['indicative_delta']>0]
 # Offline reconstruction of account entry prices/fees with frozen marks only.
 db=sqlite3.connect((E/'m1.sqlite').as_uri()+'?mode=ro',uri=True);db.execute('PRAGMA query_only=ON');state=json.loads(db.execute('SELECT payload FROM state').fetchone()[0]);control=json.loads(db.execute("SELECT payload FROM m1_meta WHERE key='control'").fetchone()[0]);db.close()
 # Undo only later booked funding, preserving every immutable source event.
 db=sqlite3.connect((E/'m1.sqlite').as_uri()+'?mode=ro',uri=True);db.execute('PRAGMA query_only=ON')
 assert db.execute('SELECT COUNT(*) FROM m1_fills WHERE at>?',(p['created_at'],)).fetchone()[0]==0,'Cannot rewind trades without a full replay'
 later_funding={s:float(amount) for s,amount in db.execute('SELECT symbol,SUM(amount) FROM funding_events WHERE timestamp_ms>? GROUP BY symbol',(int(cutoff.timestamp()*1000),))};db.close()
 for s,v in positions.items():
  assert state['positions'][s]['quantity']==v['quantity'];state['positions'][s]['current_price']=v['current_price'];state['positions'][s]['funding']-=later_funding.get(s,0.)
 assert math.isclose(paper.paper.totals(state,require_positive=False)['equity'],equity,abs_tol=1e-6)
 native_state=copy.deepcopy(state)
 for s in p['selected']:
  if s not in native_state['positions']:native_state['positions'][s]=dict(paper.paper.new_position(),current_price=market['quotes'][s]['mark_price'])
 quantities={s:(p['indicative_changes'][s]['indicative_target'] if s in p['indicative_changes'] else native_state['positions'][s]['quantity']) for s in native_state['positions']}
 # Pure simulator on the frozen quote; this does NOT assert timing permission or future fill availability.
 scenario_control=copy.deepcopy(control);scenario_control.update(normal_day=None,last_normal_at=None)
 updated,fills,outcome=paper.apply_weights(native_state,market['quotes'],{s:target.get(s,0) for s in native_state['positions']},cutoff,'DAILY',paper.POLICY if hasattr(paper,'POLICY') else 'M1_DEDICATED_APPROVED',scenario_control,exact_targets=quantities)
 actualcost=equity-paper.paper.totals(updated,require_positive=False)['equity'];realized=sum(f['realized_delta'] for f in fills)
 guarded,guardedfills,guardedoutcome=paper.apply_weights(native_state,market['quotes'],{s:target.get(s,0) for s in native_state['positions']},cutoff,'DAILY','M1_DEDICATED_APPROVED',control,exact_targets=quantities)
 # Baseline comparison uses only archived raw payloads and frozen artifacts, never fresh requests.
 c=read(E/'config.json')['derivation'];runner,ctx,contract=source.context(c);original_science=read(E/'original-science.json');responses={v['url']:bytes.fromhex(v['raw_hex']) for v in original_science['requests']}
 import tempfile
 with tempfile.TemporaryDirectory() as tmp:
  daily=runner.fetch_public_daily_range(contract['universe'],runner.protocol.WARMUP_START,dt.date.fromisoformat(original_science['day'])+dt.timedelta(days=1),raw_root=Path(tmp),maximum_workers=2,fetch_bytes=lambda url:responses[url])
 records=[dict(bar_date=d.isoformat(),symbols=v['symbols']) for d,v in sorted(daily.items())];frozen=dict(ctx['cointegration_market']);columns=[frozen['symbols'].index(s) for s in contract['universe']];frozen['symbols']=list(contract['universe']);frozen['closes']=frozen['closes'][:,columns];frozen['funding']=frozen['funding'][:,columns]
 original_market=runner.extend_trend_market(ctx['trend_market'],frozen,records);cfg=ctx['trend_config'];sim=runner.simulate_trend_forward(original_market,cfg,runner.protocol.FORWARD_START,dt.date.fromisoformat(original_science['day'])+dt.timedelta(days=1));last=read(E/'original-proposal.json');aliases={m['symbol']:m['research_symbol'] for m in contract['symbol_mapping_candidates']};reverse={v:k for k,v in aliases.items()};assert np.allclose(sim['targets'][-1],[float(last['targets'][reverse[s]]) for s in original_market['symbols']],atol=1e-12)
 dates=original_market['dates'];signal_matrix=trend._signals(original_market['closes'],cfg,original_market['symbols']);latest_index=dates.index(dt.date.fromisoformat(sc['day']));last_rebalance=runner.protocol.FORWARD_START+dt.timedelta(days=((dt.date.fromisoformat(sc['day'])-runner.protocol.FORWARD_START).days//7)*7);rebal_index=dates.index(last_rebalance)
 original_compare={}
 for s in contract['universe']:
  i=original_market['symbols'].index(aliases[s]);cl=original_market['closes'];r30=cl[latest_index,i]/cl[latest_index-30,i]-1;r120=cl[latest_index,i]/cl[latest_index-120,i]-1
  original_compare[s]=dict(latest_signal=float(signal_matrix[latest_index,i]),latest_r30=float(r30),latest_r120=float(r120),weekly_rebalance_signal=float(signal_matrix[rebal_index,i]),weekly_target=float(last['targets'][s]))
  ours=next(v for v in rows if v['symbol']==s);original_compare[s].update(r30_matches=math.isclose(ours['r30'],r30,abs_tol=1e-12),r120_matches=math.isclose(ours['r120'],r120,abs_tol=1e-12))
 # Transition alternatives are illustrative arithmetic, not optimized strategies.
 alternatives={}
 for label,affected in [('halve_five_exiting_longs',sold),('halve_aave_ltc_only',['AAVEUSDT','LTCUSDT'])]:
  q={s:v['quantity'] for s,v in state['positions'].items()}
  for symbol in affected:q[symbol]=weekly.floor_quantity(q[symbol]/2,market['quotes'][symbol]['quantity_step'])
  sw={s:q[s]*market['quotes'][s]['mark_price']/equity for s in q}
  st,ff,oo=paper.apply_weights(state,market['quotes'],sw,cutoff,'MAINTENANCE_CLOSE','M1_DEDICATED_APPROVED',control,force_reduce=True,exact_targets=q)
  alternatives[label]=dict(scope='ILLUSTRATIVE_ONLY_NOT_PROPOSED_OR_APPLIED',quantities={s:q[s] for s in affected},gross=sum(abs(v) for v in sw.values()),cost=equity-paper.paper.totals(st,require_positive=False)['equity'],turnover=sum(abs(f['quantity'])*market['quotes'][f['symbol']]['mark_price'] for f in ff),fills=len(ff),outcome=oo,new_long_admissions=0,short_budget_not_changed=True)
 shortv=np.array([p['short_caps'][s] for s in symbols])
 result=dict(scope='OFFLINE_REVIEW_NO_APPLY_NO_DECISION',proposal_id=p['proposal_id'],created_at=p['created_at'],science_day=sc['day'],later_funding_undone_for_frozen_account=sum(later_funding.values()),raw_receipts_verified=counts,reproduced_proposal_exactly=True,independent_allocator_matches=True,signals=rows,original_comparison=dict(reproduced=True,last_rebalance_day=last_rebalance.isoformat(),symbols=original_compare),impact=dict(reference_equity=equity,current_gross=oldgross,proposed_gross=newgross,proposed_cash_equivalent=1-newgross,current_long_count=sum(v>0 for v in held_weights.values()),proposed_long_count=len(p['selected']),mandatory_membership_exits=len([e for e in p['events'] if e['reason']=='mandatory_exit']),actual_full_closures=sold,increases=bought,turnover=turnover,turnover_ratio=turnover/equity,estimated_immediate_cost=cost,estimated_fees=fees,pure_native_cost=actualcost,pure_native_fees=sum(f['fee'] for f in fills),pure_native_realized_delta=realized,pure_native_fill_count=len(fills),pure_native_outcome=outcome,current_slot_outcome=guardedoutcome,current_slot_fill_count=len(guardedfills),current_estimated_annual_volatility=float(np.sqrt(oldw@cov@oldw)),proposed_estimated_annual_volatility=float(np.sqrt(neww@cov@neww)),gross_short_budget=sum(p['short_caps'].values()),old_short_reference_budget=oldgross,short_budget_increase_ratio=sum(p['short_caps'].values())/oldgross-1,short_budget_notional=equity*sum(p['short_caps'].values()),old_short_reference_notional=equity*oldgross,overlay_estimated_annual_volatility=float(np.sqrt(shortv@cov@shortv)),xmr_static_10pct_drop_pnl=-equity*target['XMRUSDT']*.1,all_long_static_10pct_drop_pnl=-equity*newgross*.1),cash_only_before_new_risk=dict(remaining_long_weight=held_weights['NEARUSDT'],cash_equivalent=1-held_weights['NEARUSDT']),native_fills=fills,illustrative_alternatives=alternatives)
 (E/'review.json').write_text(json.dumps(result,indent=2,allow_nan=False)+'\n')
 print(json.dumps(dict(proposal_id=p['proposal_id'],impact=result['impact'],original_last_rebalance=last_rebalance.isoformat(),alternatives=alternatives,selected=[v for v in rows if v['selected']]),indent=2))
if __name__=='__main__':main()
