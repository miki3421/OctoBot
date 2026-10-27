"""Broader *conditional* offline test of unchanged M1 SHORT rules.

One fixed-basket historical diagnostic, not an endogenous account backtest.
The contemporary-basket episode is reported separately. No fitting, downloads,
operating ledger writes, service operations or promotion interface exists.
"""
import argparse
import bisect
from collections import Counter
import copy
import datetime as dt
import gzip
import hashlib
import importlib.util
import json
import math
from pathlib import Path
import sqlite3

ROOT=Path(__file__).resolve().parents[1]
UTC=dt.timezone.utc


def load(name):
    spec=importlib.util.spec_from_file_location(name,ROOT/'octobot/ai_strategy_lab'/(name+'.py'))
    module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
    return module


R=load('v13_m1_short_risk')
stamp=lambda value:dt.datetime.fromisoformat(value).timestamp()
iso=lambda value:dt.datetime.fromtimestamp(value,UTC).isoformat()
sha=lambda path:hashlib.sha256(Path(path).read_bytes()).hexdigest()
availability=lambda book:stamp(book.get('_available_at',book['observed_at_end']))


def sealed_db(path, expected):
    path=Path(path).resolve()
    if path.stat().st_mode & 0o222 or sha(path)!=expected:
        raise ValueError('sealed_source_identity')
    db=sqlite3.connect(path.as_uri()+'?mode=ro',uri=True);db.row_factory=sqlite3.Row
    db.execute('PRAGMA query_only=ON')
    return db


def build_grid(marks):
    start=math.ceil(max(rows[0][0] for rows in marks.values())/300)*300
    end=math.floor(min(rows[-1][0] for rows in marks.values())/300)*300
    times={s:[v[0] for v in rows] for s,rows in marks.items()}
    grid=[];invalid=[]
    for at in range(start,end+1,300):
        prices={};sources={}
        for s in R.SIGNALS:
            i=bisect.bisect_right(times[s],at)-1
            if i<0 or at-marks[s][i][0]>120:
                break
            sources[s],prices[s]=marks[s][i]
        row=dict(time=at,prices=prices,source_times=sources)
        row['valid']=len(prices)==18 and all(math.isfinite(v) and v>0 for v in prices.values())
        if not row['valid']:invalid.append(at)
        grid.append(row)
    return grid,invalid


def history(grid,index):
    return [{k:row[k] for k in ('time','prices','source_times')} for row in grid[index-288:index+1]]


def signals(grid):
    result=[];bad=0
    for i,row in enumerate(grid):
        bad+=not row['valid']
        if i>=289:bad-=not grid[i-289]['valid']
        if i<288 or bad:
            continue
        returns={s:row['prices'][s]/grid[i-12]['prices'][s]-1 for s in R.SIGNALS}
        if returns['BTCUSDT']<=-.01 and sum(v<0 for v in returns.values())>=12:
            model=R.model(history(grid,i),row['time'])
            result.append(dict(index=i,slot=row['time'],feature=model['feature'],input_hash=model['input_hash']))
    return result


def inventory(evidence, original, expected):
    e=Path(evidence);e.mkdir(parents=True,exist_ok=True)
    with sealed_db(original,expected) as db:
        marks={s:[] for s in R.SIGNALS}
        for row in db.execute('SELECT bar,symbol,price FROM marks ORDER BY bar,symbol'):
            marks[row['symbol']].append((stamp(row['bar']),row['price']))
        grid,invalid=build_grid(marks)
        first=max(rows[0][0] for rows in marks.values())
        times=[stamp(x[0]) for x in db.execute('SELECT bar FROM equity_history WHERE bar>=? ORDER BY bar',(iso(first),))]
        hashes=[json.loads(x[0])['market_hash'] for x in db.execute('SELECT payload FROM research_events ORDER BY rowid')]
        if len(times)!=len(hashes) or any(b<=a for a,b in zip(times,times[1:])):
            raise ValueError('observation_index_unavailable')
        # This pairing is an INDEX HINT. Every consumed book must independently
        # prove its embedded timestamp and content identity before use.
        index=[dict(at=t,hash=h) for t,h in zip(times,hashes)]
    found=signals(grid)
    payloads=dict(grid=grid,book_index=index,signals=found)
    manifest=dict(scope='OFFLINE_COVERAGE_INVENTORY_NO_OUTCOME_SCORING',source=str(Path(original).resolve()),
                  source_sha256=expected,first=iso(grid[0]['time']),last=iso(grid[-1]['time']),
                  grid_rows=len(grid),invalid_grid_rows=len(invalid),raw_signal_count=len(found),
                  invalid_grid_times=[iso(t) for t in invalid],files={})
    for name,value in payloads.items():
        p=e/(name+'.json');p.write_text(json.dumps(value,separators=(',',':'),allow_nan=False)+'\n');p.chmod(0o440)
        manifest['files'][name]=sha(p)
    (e/'inventory.json').write_text(json.dumps(manifest,indent=2)+'\n');(e/'inventory.json').chmod(0o440)
    print(json.dumps({k:v for k,v in manifest.items() if k not in ('invalid_grid_times','files','source')},indent=2))


class Books:
    def __init__(self,e,source,index,cutoff,marks=None):
        self.e=Path(e);self.source=Path(source);self.index=index;self.times=[x['at'] for x in index]
        self.cutoff=cutoff;self.used={};self.cache={};self.marks=marks;(self.e/'books').mkdir(exist_ok=True)

    def get(self,index):
        item=self.index[index];key=item['hash']
        if key in self.cache:return self.cache[key]
        target=self.e/'books'/(key+'.json.gz')
        if not target.exists():
            raw=(self.source/(key+'.json.gz')).read_bytes()
        else:raw=target.read_bytes()
        b=json.loads(gzip.decompress(raw))
        if R.digest({k:v for k,v in b.items() if k!='record_hash'})!=key or b['scope']!='RESEARCH_SIMULATION_ONLY':
            raise ValueError('book_identity')
        observed=stamp(b['observed_at_end']);start=stamp(b['observed_at_start']);at=item['at']
        if not observed<=at<=observed+1800 or start>observed or at>self.cutoff or set(b['quotes'])!=set(R.SIGNALS):
            raise ValueError('book_index_or_universe_mismatch')
        for symbol,q in b['quotes'].items():
            if q['symbol']!=symbol or q['market_identity']!='kucoin_futures_usdt' or q['fee_rate']<.0006:
                raise ValueError('quote_identity_or_fee')
            for field in ('timestamp','mark_timestamp','metadata_observed_at'):
                if q.get(field) is not None and not 0<=at-stamp(q[field])<=1800:
                    raise ValueError('stale_or_future_book_component')
            if any(point['timestamp_ms']>observed*1000 for point in q['funding']):
                raise ValueError('funding_not_settled_at_source_observation')
            if self.marks is not None:
                rows=self.marks[symbol];i=bisect.bisect_left(rows,(at,-math.inf))
                if i==len(rows) or rows[i]!=(at,q['mark_price']):
                    raise ValueError('book_does_not_match_persisted_mark_vector')
        if not target.exists():target.write_bytes(raw);target.chmod(0o440)
        # Preserve the source's collection times. The sealed ledger records
        # when the executor persisted this exact 18-symbol mark vector.
        b['_available_at']=iso(at)
        self.used[key]=hashlib.sha256(raw).hexdigest();self.cache[key]=b
        if len(self.cache)>1200:self.cache={key:b}
        return b

    def segment(self,start,end):
        lo=bisect.bisect_left(self.times,start);hi=bisect.bisect_right(self.times,end)
        return [self.get(i) for i in range(lo,hi)]


def stressed(book,scenario):
    if scenario['fee_multiplier']==1 and scenario['extra_slippage_per_side']==0:return book
    b=copy.deepcopy(book)
    for q in b['quotes'].values():
        q['fee_rate']*=scenario['fee_multiplier']
        for side,factor in (('asks',1+scenario['extra_slippage_per_side']),('bids',1-scenario['extra_slippage_per_side'])):
            for level in q[side]:level['price']*=factor
    return b


def funding(state,book,marks):
    """Actual per-arm settlement quantities and strictly prior observed marks.

    Even late publication uses the quantity held at settlement, rather than
    the smaller current quantity after a partial cover. Both arms call this
    on the same public record. A missing batch does not advance its cursor.
    """
    at=availability(book);pending=[]
    for s,leg in state['positions'].items():
        q=book['quotes'][s];points=q['funding'];interval=q['funding_interval_ms']
        if type(interval) is not int or not 0<interval<=86400000 or not points:
            return False
        if (any(x['timestamp_ms']>at*1000 or not math.isfinite(x['rate']) for x in points)
                or any(b['timestamp_ms']<=a['timestamp_ms'] for a,b in zip(points,points[1:]))
                or points[-1]['timestamp_ms']+interval<=at*1000):
            return False
        events=[x for x in points if state['funding_cursor']*1000<x['timestamp_ms']<=at*1000]
        if (events and events[0]['timestamp_ms']-state['funding_cursor']*1000>interval
                or any(b['timestamp_ms']-a['timestamp_ms']>interval for a,b in zip(events,events[1:]))):
            return False
        for event in events:
            settle=event['timestamp_ms']/1000
            changes=state['quantity_history'][s]
            quantity=next((v for t,v in reversed(changes) if t<settle),0.)
            if quantity:
                i=bisect.bisect_left(marks[s],(settle,-math.inf))-1
                if i<0 or settle-marks[s][i][0]>1800:return False
                reference=marks[s][i][1]
                amount=-quantity*reference*event['rate']
            else:amount=0.
            pending.append((s,amount,event))
    for s,amount,event in pending:
        state['positions'][s]['funding']+=amount
        state['funding_events'].append(dict(symbol=s,amount=amount,timestamp_ms=event['timestamp_ms'],rate=event['rate']))
    state['funding_cursor']=at
    return True


def opening(protocol,model,book,equity):
    at=availability(book)
    for s,cap in protocol['short_caps'].items():
        if not cap:continue
        quote=book['quotes'][s];points=quote['funding'];interval=quote['funding_interval_ms']
        mid=(quote['asks'][0]['price']+quote['bids'][0]['price'])/2
        if ((quote['asks'][0]['price']-quote['bids'][0]['price'])/mid>.005
                or abs(quote['mark_price']-mid)/mid>.01):
            raise ValueError('parent_market_entry_veto')
        if (type(interval) is not int or not 0<interval<=86400000 or not points
                or points[-1]['timestamp_ms']+interval<=at*1000
                or any(x['timestamp_ms']>at*1000 or not math.isfinite(x['rate']) for x in points)
                or any(b['timestamp_ms']<=a['timestamp_ms'] for a,b in zip(points,points[1:]))):
            raise ValueError('entry_funding_coverage')
    plan=R.size(protocol,model,equity,protocol['short_caps'],book['quotes'])
    positions={};fills=[]
    for s,q in plan['quantities'].items():
        price=R.vwap(book['quotes'][s],abs(q),'bids');fee=abs(q)*price*book['quotes'][s]['fee_rate']
        if abs(q)*price<1:raise ValueError('parent_minimum_simulated_notional')
        positions[s]=dict(quantity=q,entry_price=price,funding=0.)
        fills.append(dict(symbol=s,before=0.,after=q,quantity=q,fee=fee,price=price))
    ep=R.episode(plan,{},positions,fills,at,'conditional-episode')
    state=dict(positions=positions,realized=0.,entry_fees=sum(f['fee'] for f in fills),cover_fees=0.,
               funding_cursor=at,funding_events=[],quantity_history={s:[(at,p['quantity'])] for s,p in positions.items()},
               pending=None,closed_at=None,exit_reason=None,episode=ep,cover_fills=[],path=[],valuation_missing_points=0)
    return plan,state


def executable_value(state,quotes):
    value=state['realized']-state['entry_fees']-state['cover_fees']
    for s,pos in state['positions'].items():
        value+=pos['funding']
        if pos['quantity']:
            price=R.vwap(quotes[s],abs(pos['quantity']),'asks')
            value+=pos['quantity']*(price-pos['entry_price'])-abs(pos['quantity'])*price*quotes[s]['fee_rate']
    return value


def cover(state,book):
    at=availability(book)
    for s,pos in state['positions'].items():
        before=pos['quantity']
        if not before:continue
        q=book['quotes'][s];capacity=math.fsum(x['base_quantity'] for x in q['asks'])
        amount=min(abs(before),R.floor_quantity(capacity,q['quantity_step']))
        if not amount:continue
        price=R.vwap(q,amount,'asks');fee=amount*price*q['fee_rate']
        realized=amount*(pos['entry_price']-price)
        state['realized']+=realized;state['cover_fees']+=fee
        pos['quantity']=0. if math.isclose(amount,abs(before),abs_tol=1e-10) else before+amount
        state['quantity_history'][s].append((at,pos['quantity']))
        state['cover_fills'].append(dict(symbol=s,at=at,quantity=amount,price=price,fee=fee,realized=realized))
    if not any(p['quantity'] for p in state['positions'].values()):
        state['closed_at']=at;state['pending']=None


def summarize(state):
    if state['closed_at'] is None:raise ValueError('outcome_not_closed')
    if state.get('debt_at_close'):raise ValueError('funding_unknown_at_exit')
    realized=math.fsum(f['realized'] for f in state['cover_fills'])
    fees=state['entry_fees']+math.fsum(f['fee'] for f in state['cover_fills'])
    funding_amount=math.fsum(f['amount'] for f in state['funding_events'])
    net=realized-fees+funding_amount
    if not math.isclose(net,executable_value(state,{}),abs_tol=1e-7):
        raise ValueError('independent_cashflow_mismatch')
    path=state['path'];values=[v for _,v in path]
    return dict(net=net,gross=realized,fees=fees,funding=funding_amount,
                exit_at=iso(state['closed_at']),reason=state['exit_reason'],
                worst_executable_pnl=min(values+[net]),best_executable_pnl=max(values+[net]),
                valuation_missing_points=state.get('valuation_missing_points',0),
                holding_seconds=state['closed_at']-state['episode']['at'],
                cover_fills=len(state['cover_fills']),path=path)


def pair(protocol,signal,grid,books,marks,scenario,capital,feature_cache):
    model=R.model(history(grid,signal['index']),signal['slot'])
    if model['input_hash']!=signal['input_hash']:raise ValueError('signal_identity')
    due=signal['slot']+300;timeout=due+21600
    segment=books.segment(due,timeout+300)
    entry=next((b for b in segment if availability(b)<=due+120
                and stamp(b['observed_at_start'])>due+scenario['latency_seconds']),None)
    if entry is None:raise ValueError('entry_book_unavailable_or_late')
    eligible=[b for b in segment if availability(b)>=availability(entry)]
    if not eligible or availability(eligible[-1])<timeout:raise ValueError('six_hour_outcome_censored')
    if any(availability(b)-availability(a)>120 for a,b in zip(eligible,eligible[1:])):
        raise ValueError('book_gap_over_120_seconds')
    plan,first=opening(protocol,model,stressed(entry,scenario),capital)
    arms=dict(corrected=copy.deepcopy(first),six_hour=copy.deepcopy(first))
    start=grid[0]['time']
    for original in eligible:
        book=stressed(original,scenario);at=availability(book);slot=int(at)//300*300
        for name,state in arms.items():
            if state['closed_at'] is not None:continue
            funding_ok=funding(state,book,marks)
            try:value=executable_value(state,book['quotes']);state['path'].append((at,value))
            except ValueError:value=None;state['valuation_missing_points']+=1
            if state['pending']:
                if stamp(book['observed_at_start'])>state['pending']:
                    cover(state,book)
                    if state['closed_at'] is not None and not funding_ok:state['debt_at_close']=True
                    if state['closed_at'] is None:state['pending']=at+scenario['latency_seconds']
                continue
            reason=None
            if name=='corrected' and funding_ok:
                feature_slot=slot if slot>=first['episode']['at'] else None
                feature=None
                if feature_slot is not None:
                    if slot not in feature_cache:
                        index=int((slot-start)//300)
                        try:feature_cache[slot]=R.model(history(grid,index),slot)['feature']
                        except (ValueError,IndexError):feature_cache[slot]=None
                    feature=feature_cache[slot]
                try:
                    ep,reason=R.watch(protocol,state['episode'],state['positions'],book['quotes'],
                        at=at,market_id=original['record_hash'],feature_slot=feature_slot,feature=feature)
                    state['episode']=ep
                except ValueError:reason=None
            if reason is None and at>=timeout:reason='MAX_HOLD'
            if reason:
                state['exit_reason']=reason;state['pending']=at+scenario['latency_seconds']
        if all(v['closed_at'] is not None for v in arms.values()):break
    result={name:summarize(state) for name,state in arms.items()}
    return dict(signal_at=iso(signal['slot']),entry_at=iso(availability(entry)),
                entry_source_observed_at=entry['observed_at_end'],scenario=scenario['name'],
                capital_reference=capital,notional=plan['short_notional'],risk_unit=plan['risk_unit'],
                planned_stopped_risk=plan['planned_stopped_risk'],quantities=plan['quantities'],
                corrected=result['corrected'],six_hour=result['six_hour'],
                difference=result['corrected']['net']-result['six_hour']['net'])


def aggregate(rows):
    arms={}
    for name in ('corrected','six_hour'):
        arms[name]=dict(net=sum(x[name]['net'] for x in rows),fees=sum(x[name]['fees'] for x in rows),
            funding=sum(x[name]['funding'] for x in rows),winners=sum(x[name]['net']>0 for x in rows),
            worst_episode=min((x[name]['net'] for x in rows),default=None),
            worst_observed_executable_pnl=(min((x[name]['worst_executable_pnl'] for x in rows),default=None)
                if all(x[name]['valuation_missing_points']==0 for x in rows) else None),
            unavailable_valuation_points=sum(x[name]['valuation_missing_points'] for x in rows),
            mean_holding_hours=sum(x[name]['holding_seconds'] for x in rows)/3600/len(rows) if rows else None)
    weekly={}
    for row in rows:
        week=dt.datetime.fromisoformat(row['signal_at']).strftime('%G-W%V')
        weekly[week]=weekly.get(week,0)+row['difference']
    total=sum(x['difference'] for x in rows)
    return dict(episodes=len(rows),arms=arms,difference=total,
                improved_exits=sum(x['difference']>0 for x in rows),exit_reasons=dict(Counter(x['corrected']['reason'] for x in rows)),
                weekly_difference=weekly,leave_one_week_out={k:total-v for k,v in weekly.items()})


def run(evidence):
    e=Path(evidence);contract=json.loads((e/'evaluation-contract.json').read_text())
    if R.digest({k:v for k,v in contract.items() if k!='evaluation_id'})!=contract['evaluation_id']:
        raise ValueError('evaluation_contract_identity')
    protocol=json.loads((ROOT/'docs/research-protocols/m1-short-risk-exits-candidate-v1.json').read_text());R.validate(protocol)
    for name,h in contract['frozen_code_sha256'].items():
        if sha(ROOT/name)!=h:raise ValueError('frozen_code_changed:'+name)
    for name,h in contract['evaluation_code_sha256'].items():
        if sha(ROOT/name)!=h:raise ValueError('evaluation_code_changed:'+name)
    inv=json.loads((e/'inventory.json').read_text())
    if sha(e/'inventory.json')!=contract['inventory_sha256']:raise ValueError('inventory_changed')
    payloads={}
    for name,h in inv['files'].items():
        if sha(e/(name+'.json'))!=h:raise ValueError('inventory_component_changed')
        payloads[name]=json.loads((e/(name+'.json')).read_text())
    with sealed_db(inv['source'],inv['source_sha256']) as db:
        marks={s:[] for s in R.SIGNALS}
        for x in db.execute('SELECT bar,symbol,price FROM marks ORDER BY bar,symbol'):
            marks[x['symbol']].append((stamp(x['bar']),x['price']))
    environment=json.loads((e/'environment.json').read_text())
    if environment['scope']!='OFFLINE_EXISTING_ARCHIVE_MAPPING':raise ValueError('archive_environment_scope')
    grid=payloads['grid'];book=Books(e,environment['archive_source'],payloads['book_index'],stamp(inv['last'])+300,marks)
    ready=-math.inf;last_day=None;selected=[];rejected=[];cache={}
    scenarios=contract['scenarios'];results={s['name']:[] for s in scenarios}
    for signal in payloads['signals']:
        day=iso(signal['slot'])[:10]
        if signal['slot']<ready or day==last_day:continue
        last_day=day
        rows=[]
        for scenario in scenarios:
            try:
                outcome=pair(protocol,signal,grid,book,marks,scenario,contract['capital_reference'],cache)
                rows.append(outcome)
            except (ValueError,FileNotFoundError,KeyError) as error:
                rejected.append(dict(signal_at=iso(signal['slot']),scenario=scenario['name'],reason=str(error)))
        if rows:
            # A common conditional entry schedule isolates exits. The slower
            # completed control sets a conservative shared six-hour cooldown.
            ready=max(stamp(x['six_hour']['exit_at']) for x in rows)+21600
        else:ready=signal['slot']+300+21600+300+21600
        if len(rows)!=len(scenarios):
            selected.append(dict(signal_at=iso(signal['slot']),status='UNAVAILABLE_COMMON_SCENARIO_POOL'))
            continue
        selected.append(dict(signal_at=iso(signal['slot']),status='COMPLETE'))
        for row in rows:results[row['scenario']].append(row)
        print('completed',iso(signal['slot']),flush=True)
    clean={}
    for name,rows in results.items():
        for row in rows:
            path=e/('paths-'+row['signal_at'][:10]+'-'+name+'.json')
            path.write_text(json.dumps({arm:row[arm].pop('path') for arm in ('corrected','six_hour')},separators=(',',':'))+'\n')
        clean[name]=dict(summary=aggregate(rows),episodes=rows)
    result=dict(scope='RETROSPECTIVE_FROZEN_BASKET_CONDITIONAL_DIAGNOSTIC_NOT_INDEPENDENT_VALIDATION',
        protocol_id=R.PROTOCOL_ID,evaluation_id=contract['evaluation_id'],first=inv['first'],last=inv['last'],
        capital_reference=contract['capital_reference'],capital_compounded=False,signals=inv['raw_signal_count'],
        selected=selected,rejected=rejected,scenarios=clean,used_books=len(book.used),
        active_strategies_changed=False,frozen_rules_changed=False,new_accounts=False,
        economic_status='NO_AUTOMATIC_PROMOTION',basket_selection_bias_before='2026-10-25T11:27:40.532267+00:00',
        complete_portfolio_and_risk_counter_feedback=False)
    (e/'results.json').write_text(json.dumps(result,indent=2,allow_nan=False)+'\n')
    (e/'used-books.json').write_text(json.dumps(book.used,indent=2)+'\n')
    print(json.dumps({name:v['summary'] for name,v in clean.items()},indent=2))
    return result


if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('phase',choices=('inventory','run'))
    parser.add_argument('--evidence',required=True,type=Path);parser.add_argument('--source',type=Path);parser.add_argument('--source-sha256')
    args=parser.parse_args()
    if args.phase=='inventory':inventory(args.evidence,args.source,args.source_sha256)
    else:run(args.evidence)
