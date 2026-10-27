"""Conditional SHORT diagnostics on sealed successor-era books, never live.

This is not an endogenous portfolio backtest. The existing episode's causal
entry state is reused; the sizing-only control and corrected exits share size
and costs. Twenty seconds of assumed processing latency precedes a later-book
fill. No parameter search or production action exists in this tool.
"""
import argparse
import datetime as dt
import gzip
import hashlib
import importlib.util
import json
from pathlib import Path
import sqlite3

ROOT=Path(__file__).resolve().parents[1]


def load(name):
    spec=importlib.util.spec_from_file_location(name,ROOT/'octobot/ai_strategy_lab'/(name+'.py'))
    module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
    return module


def analyze(evidence):
    e=Path(evidence).resolve();risk=load('v13_m1_short_risk');r=load('v13_m1_symbol_review');causal=load('v13_m1_future')
    protocol=json.loads((e/'frozen-protocol.json').read_text());risk.validate(protocol)
    lock=json.loads((e/'verification-lock.json').read_text())
    for filename,h in lock['code_sha256'].items():
        if hashlib.sha256((ROOT/filename).read_bytes()).hexdigest()!=h:
            raise ValueError('verification_code_changed:'+filename)
    capture=json.loads((e/'capture.json').read_text())
    for name in ('m1','original'):
        path=e/'input'/(name+'.sqlite')
        if path.stat().st_mode & 0o222 or hashlib.sha256(path.read_bytes()).hexdigest()!=capture['files'][name]['sha256']:
            raise ValueError('sealed_input_identity')
    manifest=json.loads((e/'replay-inputs.json').read_text())
    if hashlib.sha256((e/'replay-inputs.json').read_bytes()).hexdigest()!=lock['replay_manifest_sha256'] or manifest['missing']:
        raise ValueError('incomplete_replay_book_coverage')
    db=sqlite3.connect((e/'input/m1.sqlite').as_uri()+'?mode=ro',uri=True);db.row_factory=sqlite3.Row
    try:
        account=r.load_snapshot(e/'input/m1.sqlite')
        fills={s:[f for f in account['fills'] if f['symbol']==s] for s in account['state']['positions']}
        funds={s:[f for f in account['funding'] if f['symbol']==s] for s in account['state']['positions']}
        results=[]
        for item in manifest['episodes']:
            row=db.execute('SELECT payload FROM m1_episodes WHERE id=?',(item['id'],)).fetchone()
            payload=json.loads(row[0]);entered=r.timestamp(payload['entry_outcome']['at'])
            model=risk.model(payload['consumed_rows'],r.timestamp(item['signal_at']))
            books=[]
            for rec in item['books']:
                path=e/'books'/(rec['hash']+'.json.gz')
                if hashlib.sha256(path.read_bytes()).hexdigest()!=manifest['files'][rec['hash']]['sha256']:
                    raise ValueError('book_file_changed')
                value=json.loads(gzip.decompress(path.read_bytes()))
                if risk.digest({k:v for k,v in value.items() if k!='record_hash'})!=rec['hash']:
                    raise ValueError('book_digest')
                if value['observed_at_end']!=rec['observed_at']:
                    raise ValueError('book_observation_binding')
                books.append(value)
            entry=next(b for b in books if b['observed_at_end']==payload['entry_outcome']['at'])
            equity=account['state']['initial_equity']
            for symbol in account['state']['positions']:
                pos=r.replay(fills[symbol],entered-.00001)
                mark=entry['quotes'][symbol]['mark_price'] if pos['q'] else 0.
                equity+=pos['realized']-pos['fees']+pos['q']*(mark-pos['entry'])
                equity+=sum(f['amount'] for f in funds[symbol] if f['timestamp_ms']/1000<=entered)
            plan=risk.size(protocol,model,equity,protocol['short_caps'],entry['quotes'])
            positions={};entry_fills=[]
            for symbol,quantity in plan['quantities'].items():
                q=entry['quotes'][symbol];price=risk.vwap(q,abs(quantity),'bids');fee=abs(quantity)*price*q['fee_rate']
                positions[symbol]=dict(quantity=quantity,entry_price=price,funding=0.)
                entry_fills.append(dict(symbol=symbol,before=0.,after=quantity,quantity=quantity,fee=fee))
            episode=risk.episode(plan,{},positions,entry_fills,entered,item['id'])
            timeout=r.timestamp(item['exit_due'])
            cache={};paid=set();pending=None;corrected=None;control=None;gaps=[];last=entered
            control_decision=None
            for book in books:
                at=r.timestamp(book['observed_at_end'])
                if at<entered:
                    continue
                gaps.append(at-last);last=at
                available={}
                for symbol in positions:
                    available[symbol]={x['timestamp_ms']:x for x in book['quotes'][symbol]['funding']}
                funding_ok=True
                for symbol,pos in positions.items():
                    for f in funds[symbol]:
                        settlement=f['timestamp_ms']/1000
                        key=(symbol,f['timestamp_ms'])
                        if entered<settlement<=at and key not in paid:
                            observed=available[symbol].get(f['timestamp_ms'])
                            if observed is None or observed['rate']!=f['rate']:
                                funding_ok=False;continue
                            pos['funding'] += -pos['quantity']*f['reference_mark']*f['rate'];paid.add(key)
                if at>=timeout and control_decision is None:
                    control_decision=at+20
                if control is None and control_decision is not None and r.timestamp(book['observed_at_start'])>control_decision:
                    control=dict(at=book['observed_at_end'],net=risk.liquidation(episode,positions,book['quotes']))
                if corrected is not None:
                    if control is not None:
                        break
                    continue
                if pending is not None:
                    if r.timestamp(book['observed_at_start'])>pending['decision_at']:
                        corrected=dict(at=book['observed_at_end'],reason=pending['reason'],
                                       decided_at=r.iso(pending['decision_at']),
                                       net=risk.liquidation(episode,positions,book['quotes']))
                    continue
                if at>=timeout:
                    pending=dict(reason='MAX_HOLD',decision_at=at+20)
                    continue
                slot=int(at)//300*300;feature=None;feature_slot=None
                if slot>=entered:
                    feature_slot=slot
                    if slot not in cache:
                        try:cache[slot]=risk.model(causal.read_window(e/'input/original.sqlite',slot,list(risk.SIGNALS)),slot)['feature']
                        except ValueError:cache[slot]=None
                    feature=cache[slot]
                if funding_ok:
                    episode,reason=risk.watch(protocol,episode,positions,book['quotes'],at=at,
                        market_id=book['record_hash'],feature_slot=feature_slot,feature=feature)
                    if reason:
                        pending=dict(reason=reason,decision_at=at+20)
            if corrected is None or control is None:
                raise ValueError('later_exit_book_not_available')
            # Independent cash flow reconstruction at both conditional exits.
            for result in (corrected,control):
                book=next(b for b in books if b['observed_at_end']==result['at'])
                end=r.timestamp(result['at']);cash=0.
                for f in entry_fills:
                    symbol=f['symbol'];q=positions[symbol]['quantity'];price=risk.vwap(book['quotes'][symbol],abs(q),'asks')
                    cash+=q*(price-positions[symbol]['entry_price'])-f['fee']-abs(q)*price*book['quotes'][symbol]['fee_rate']
                    cash+=sum(-q*x['reference_mark']*x['rate'] for x in funds[symbol] if entered<x['timestamp_ms']/1000<=end)
                if not r.close(cash,result['net']):
                    raise ValueError('conditional_cash_flow_reconciliation')
            actual_exit=db.execute("SELECT MAX(at) FROM m1_fills WHERE json_extract(payload,'$.kind')='EXIT' AND at>? AND at<=?",
                (payload['entry_outcome']['at'],r.iso(timeout+300))).fetchone()[0]
            if actual_exit is None:
                raise ValueError('actual_episode_unclosed')
            actual=sum(r.attribution(fills[s],funds[s],account['marks'][s],entered-.00001,r.timestamp(actual_exit))['sides']['SHORT']['net']
                       for s in account['state']['positions'])
            results.append(dict(signal_at=item['signal_at'],entry_at=entry['observed_at_end'],
                risk_unit=plan['risk_unit'],short_notional=plan['short_notional'],planned_stopped_risk=plan['planned_stopped_risk'],
                scale=plan['scale'],quantities=plan['quantities'],corrected=corrected,sizing_only_6h_control=control,
                actual_legacy_short_net=actual,incremental_exit_effect=corrected['net']-control['net'],
                maximum_observation_gap_seconds=max(gaps)))
        result=dict(scope='CONDITIONAL_HISTORICAL_EPISODE_DIAGNOSTIC_NOT_PORTFOLIO_BACKTEST',
            protocol_id=risk.PROTOCOL_ID,results=results,economic_status='INSUFFICIENT_EVIDENCE_NO_PROMOTION',
            fill_latency_assumption_seconds=20,earlier_predecessor_events_excluded=True,
            complete_portfolio_replayed=False,future_risk_counter_feedback_replayed=False,
            frozen_parameters_changed=False,new_live_orders=False,
            limitations=['Only the closed successor-era episode is eligible; applying the later basket to older episodes would leak portfolio selection.',
                'Twenty seconds is an execution assumption after observed availability, not measured counterfactual processing latency.',
                'Recorded settlement reference marks are estimates; rate availability is checked in each observed book.',
                'Removing LONG entry closures and endogenously changing future portfolio equity is outside this conditional SHORT diagnostic.'])
        (e/'output/conditional-replay.json').write_text(json.dumps(result,indent=2,allow_nan=False)+'\n')
        print(json.dumps(result,indent=2));return result
    finally:
        db.close()


if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--evidence',required=True,type=Path)
    analyze(p.parse_args().evidence)
