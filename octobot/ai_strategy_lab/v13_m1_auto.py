"""Operator-delegated paper M1 reviews; no web approval or credential bypass.

The root-owned, hash-pinned delegation is the authority. Scores describe rule
quality, not a probability of profit. Every hard veto wins over the total score.
All execution still goes through the existing single-writer intent/Risk Guard.
"""
import copy
import datetime as dt
import json
from pathlib import Path
from . import v13_m1_successor as successor
from . import v13_m1_weekly as w
from . import v13_m1_transition as transition
from . import v13_m1_managed as managed
from .v13_m1_approval_broker import safe_file

base = managed.base
VERSION = 'm1-weighted-automatic-review-v1'
RULES = dict(threshold=80, weights=dict(data=25, signal=30, liquidity=20, costs=15, budget=10),
    minimum_signal_score=.25, maximum_spread=.001, maximum_round_trip_cost=.002,
    maximum_entry_weight=.01, maximum_entries_per_week=2, entry_validity_hours=48,
    review_validity_days=7, required_positive_days=2, repurchase_excluded=False)


def delegation(config,account):
    c=config['automatic_review'];path=safe_file(c['authority'],0)
    if base.shared.sha(path)!=c['sha256']:raise ValueError('automatic_delegation_changed')
    d=json.loads(path.read_text());w.verify(d,'delegation_id')
    p,a=successor.authority(config,account)
    if (d['scope']!='M1_PAPER_DELEGATED_WEIGHTED_REVIEW' or d['account']!=account
        or d['genesis_activation_id']!=a['activation_id'] or d['rules']!=RULES
        or d['short_caps']!=p['short_caps'] or d['long_budget']!=sum(p['long_caps'].values())
        or not d['operator_reference'] or w.when(d['authorized_at'])>base.source.now()
        or type(d['allow_admissions']) is not bool or d['enabled'] is not True):
        raise ValueError('automatic_delegation_scope')
    return d


def quote_quality(symbol,quantity,market,at,*,entry):
    """Observed two-sided cost/depth; never treats missing liquidity as free."""
    from . import v13_market_sanity as sanity
    w.verify(market,'record_hash');q=market['quotes'][symbol]
    sanity.structure_and_time(symbol,q,market,w.when(at))
    bid=q['bids'][0]['price'];ask=q['asks'][0]['price'];mid=(bid+ask)/2
    spread=(ask-bid)/mid
    if quantity<=0:raise ValueError('quantity_below_minimum')
    prices=[]
    for side in ('asks','bids'):
        left=quantity;gross=0.
        for level in q[side]:
            used=min(left,w.num(level['base_quantity']));gross+=used*w.num(level['price']);left-=used
            if left<=1e-10:break
        if left>1e-8:raise ValueError('insufficient_observed_depth')
        prices.append(gross/quantity)
    # Same 2bp simulated adverse slippage per leg as the active engine.
    cost=(prices[0]*1.0002-prices[1]*.9998)/q['mark_price']+2*w.num(q['fee_rate'])
    if entry:
        checked=dict(q)
        if q.get('metadata_scope')=='REAL_PRECISION_WITH_SEPARATE_SIMULATED_MINIMUMS':
            checked.update(min_quantity=q['simulation_min_quantity'],min_notional=q['simulation_min_notional'])
        sanity.preflight(symbol,checked,quantity,False)
        interval=q['funding_interval_ms'];points=q['funding'];cutoff=int(w.when(market['observed_at_end']).timestamp()*1000)
        if (type(interval) is not int or not 0<interval<=86400000 or not points
            or not points[-1]['timestamp_ms']<=cutoff<points[-1]['timestamp_ms']+interval):
            raise ValueError('funding_coverage')
        if quantity<checked['min_quantity'] or quantity*q['mark_price']<checked['min_notional']:
            raise ValueError('quantity_below_minimum')
        if spread>RULES['maximum_spread']:raise ValueError('spread_limit')
        if cost>RULES['maximum_round_trip_cost']:raise ValueError('cost_limit')
    return dict(spread=spread,round_trip_cost=cost,estimated_entry_cost=quantity*q['mark_price']*cost/2,
                minimums='SEPARATE_SYNTHETIC_MINIMUMS' if q.get('metadata_scope')=='REAL_PRECISION_WITH_SEPARATE_SIMULATED_MINIMUMS' else 'OBSERVED_METADATA')


def assessment(symbol,kind,science,prior,market,state,policy,at,*,quantity,room=True):
    components=dict.fromkeys(RULES['weights'],0);veto=[];quality=None
    rows,histories,reasons=w.signals(science,at)
    latest=(w.when(at).date()-dt.timedelta(days=1)).isoformat()
    if science['day']!=latest or symbol not in histories or symbol in reasons:veto.append('WAITING_CURRENT_DAILY')
    else:components['data']=25
    positive=rows[symbol]['signal']>0
    if kind=='REDUCE':
        if positive:veto.append('SIGNAL_RECOVERED')
        else:components['signal']=30
    else:
        confirmed=False
        if prior is not None:
            old,_,missing=w.signals(prior,prior['published_at'])
            confirmed=(prior['day']==str(dt.date.fromisoformat(science['day'])-dt.timedelta(days=1))
                and w.when(prior['published_at'])<w.when(science['published_at'])<=w.when(at)
                and symbol not in missing and old[symbol]['signal']>0)
        if not positive:veto.append('NO_POSITIVE_SIGNAL')
        if positive and not confirmed:veto.append('WAITING_SECOND_POSITIVE_DAY')
        score=rows[symbol]['score']
        if positive and (score is None or score<RULES['minimum_signal_score']):veto.append('SIGNAL_TOO_WEAK')
        if positive and confirmed and score is not None:
            components['signal']=min(30,20+10*min(1,score))
        if not room:veto.append('LONG_BUDGET_OR_WEEKLY_LIMIT')
    try:
        quality=quote_quality(symbol,quantity,market,at,entry=kind=='ENTER')
        components['liquidity']=20
        components['costs']=15 if kind=='REDUCE' else max(0,15*(1-quality['round_trip_cost']/RULES['maximum_round_trip_cost']))
    except (ValueError,KeyError,TypeError) as error:
        code=str(error)
        veto.append(code.upper() if code in ('cost_limit','spread_limit','quantity_below_minimum') else 'WAITING_VALID_BOOK_COSTS_FUNDING')
        quality=dict(unavailable=True,reason=code[:120])
    if kind=='REDUCE' or room:components['budget']=10
    score=round(sum(components.values()),2)
    definitive={'NO_POSITIVE_SIGNAL','SIGNAL_TOO_WEAK','COST_LIMIT','SPREAD_LIMIT','SIGNAL_RECOVERED'}
    status='APPROVED' if not veto and score>=RULES['threshold'] else 'REJECTED' if definitive&set(veto) else 'DEFERRED' if any(v.startswith('WAITING_') for v in veto) else 'REJECTED'
    if not veto and score<RULES['threshold']:veto.append('SCORE_BELOW_THRESHOLD')
    return dict(symbol=symbol,kind=kind,status=status,score=score,threshold=RULES['threshold'],components=components,
        reasons=veto or ['ALL_REQUIRED_CHECKS_PASSED'],quantity=quantity,quality=quality,
        signal=rows[symbol],science_id=science['snapshot_id'],prior_science_id=prior['snapshot_id'] if prior else None,
        market_hash=market['record_hash'],short_budget_unchanged=True)


def validated_policy(runner,value):
    d=delegation(runner.c,runner.account)
    row=runner.db.execute('SELECT payload FROM m1_auto_reviews WHERE id=?',(value['automatic_decision_id'],)).fetchone()
    if not row:raise ValueError('automatic_policy_authority_missing')
    record=json.loads(row[0]);w.verify(record,'decision_id')
    expected=record['policy']
    if (record['delegation_id']!=d['delegation_id'] or record['status']!='APPROVED'
        or record['account']!=runner.account or value['short_caps']!=d['short_caps']
        or set(value)!=set(expected)|{'automatic_decision_id'}
        or any(value.get(k)!=v for k,v in expected.items() if k!='quantity_ceilings')):
        raise ValueError('automatic_policy_changed')
    ceilings=value['quantity_ceilings'];initial=expected['quantity_ceilings']
    if set(ceilings)!=set(initial) or any(not 0<=w.num(q)<=initial[s]+1e-10 for s,q in ceilings.items()):
        raise ValueError('automatic_quantity_ceiling_increased')
    genesis,_=successor.authority(runner.c,runner.account)
    if (value['initial_quantities']!=genesis['initial_quantities'] or value['stage_rule']!=genesis['stage_rule']
        or any(initial[s]>genesis['quantity_ceilings'][s]+1e-10 for s in genesis['quantity_ceilings'])
        or any(s in genesis['initial_quantities'] or not 0<=v['quantity'] or value['long_caps'][s]>.010000001
            for s,v in value.get('automatic_admissions',{}).items())):
        raise ValueError('automatic_delegation_budget_or_repurchase')
    return value


def targets(state,policy,baseline,quotes,*,kind,short_reference=None):
    result,updated=transition.targets(state,policy,baseline,quotes,kind=kind,short_reference=short_reference)
    admissions=policy.get('automatic_admissions',{})
    for s,q in result.items():
        if kind in ('M1_ENTRY','MAINTENANCE_CLOSE'):continue
        old=max(0.,state['positions'][s]['quantity'])
        permit=admissions.get(s)
        if permit and kind=='DAILY' and permit['status']=='PENDING':
            result[s]=min(policy['quantity_ceilings'][s],permit['quantity'])
        elif permit and old>0:
            result[s]=min(old,policy['quantity_ceilings'][s])
        elif q>0:result[s]=min(q,old)
        if result[s]>=0:updated['quantity_ceilings'][s]=min(policy['quantity_ceilings'][s],result[s])
    return result,updated


class Runner(successor.Runner):
    def __init__(self,config):
        # managed_policy may be called while the base initializes the ledger.
        # Tables must exist before a subsequent process restart validates policy.
        super().__init__(config)
        self.delegated=delegation(config,self.account)
        with self.db:
            self.db.executescript('CREATE TABLE IF NOT EXISTS m1_auto_reviews(id TEXT PRIMARY KEY,at TEXT NOT NULL,day TEXT NOT NULL,kind TEXT NOT NULL,payload TEXT NOT NULL);'
                'CREATE TRIGGER IF NOT EXISTS m1_auto_no_update BEFORE UPDATE ON m1_auto_reviews BEGIN SELECT RAISE(ABORT,"append_only_auto_reviews"); END;'
                'CREATE TRIGGER IF NOT EXISTS m1_auto_no_delete BEFORE DELETE ON m1_auto_reviews BEGIN SELECT RAISE(ABORT,"append_only_auto_reviews"); END;')

    def record_review(self,kind,at,details,policy=None,status='APPROVED'):
        old=self.db.execute('SELECT id FROM m1_auto_reviews ORDER BY rowid DESC LIMIT 1').fetchone()
        record=dict(version=VERSION,account=self.account,at=at,day=at[:10],kind=kind,status=status,
            delegation_id=self.delegated['delegation_id'],previous_id=old[0] if old else None,
            details=details,policy=copy.deepcopy(policy),orders_authorized=False)
        record['decision_id']=w.digest(record)
        self.db.execute('INSERT INTO m1_auto_reviews VALUES(?,?,?,?,?)',(record['decision_id'],at,record['day'],kind,base.shared.dump(record)))
        if policy is not None:
            policy['automatic_decision_id']=record['decision_id'];self.put('management_policy',policy)
        self.event('AUTOMATIC_REVIEW',dict(id=record['decision_id'],kind=kind,status=status,details=details))
        return record

    def prior_science(self,science):
        result=[]
        for path in (Path(self.mc['source'])/'science').glob('*.json'):
            value=base.source.owned_json(path,self.mc['capture_uid'])
            if value['day']<science['day'] and w.when(value['published_at'])<=w.when(science['published_at']):result.append(value)
        return max(result,key=lambda x:x['day']) if result else None

    def stage_review(self,policy,progress,state,science,at):
        updated,new_progress,events=successor.advance(policy,progress,state,science,at)
        for e in list(events):
            s=e['symbol'];a=assessment(s,'REDUCE',science,None,self.full_market,state,policy,at,
                quantity=max(0.,state['positions'][s]['quantity']-e['target']))
            key='automatic_stage:'+s
            fingerprint=[science['day'],e['stage'],a['status'],a['reasons']]
            if self.meta(key)!=fingerprint:
                self.record_review('GRADUAL_REDUCTION',at,[a],status=a['status']);self.put(key,fingerprint)
            if a['status']!='APPROVED':
                updated['quantity_ceilings'][s]=policy['quantity_ceilings'][s]
                new_progress[s]=copy.deepcopy((progress or {})[s]);new_progress[s]['status']='WAITING_DATA';events.remove(e)
        # New admissions retain the same gradual exit discipline. Their entry
        # permit is one-use; reductions never create another entry permission.
        rows,histories,missing=w.signals(science,at)
        admission_progress=copy.deepcopy(self.meta('automatic_admission_progress') or {})
        for s,permit in policy.get('automatic_admissions',{}).items():
            if permit['status']!='CONSUMED' or not permit.get('filled_quantity'):continue
            q=max(0.,state['positions'][s]['quantity']);step=self.full_market['quotes'][s]['quantity_step']
            g=admission_progress.setdefault(s,dict(stage=-1,completed_at=permit['filled_at'],science_day=permit['science_day']))
            if q>updated['quantity_ceilings'][s]+step/2:continue
            if g['completed_at'] is None:g['completed_at']=at
            if s not in histories or s in missing or rows[s]['signal']>0 or g['stage']>=2:continue
            if (w.when(at)-w.when(g['completed_at'])).total_seconds()<86400 or science['day']<=g['science_day']:continue
            target=w.floor_quantity(permit['filled_quantity']*[.5,.25,0.][g['stage']+1],step)
            a=assessment(s,'REDUCE',science,None,self.full_market,state,policy,at,quantity=max(0.,q-target))
            if a['status']=='APPROVED':
                g.update(stage=g['stage']+1,completed_at=None,science_day=science['day'])
                updated['quantity_ceilings'][s]=min(updated['quantity_ceilings'][s],target,q)
                events.append(dict(symbol=s,stage=g['stage']+1,target=target,science_id=science['snapshot_id']))
                self.record_review('ADMITTED_SYMBOL_REDUCTION',at,[a])
        self.put('automatic_admission_progress',admission_progress)
        return updated,new_progress,events

    def automatic_cycle(self,state,control,record,now,debt):
        sc=self.science();rows,histories,missing=w.signals(sc,now.isoformat())
        if sc['day']!=(now.date()-dt.timedelta(days=1)).isoformat():raise ValueError('automatic_latest_closed_day_required')
        quantities_id=w.digest({s:v['quantity'] for s,v in state['positions'].items()})
        if self.meta('automatic_science_id')==sc['snapshot_id'] and self.meta('automatic_quantities_id')==quantities_id:return state,record
        if control['phase']!='NORMAL' or control.get('pending') or debt:return state,record
        p=copy.deepcopy(self.managed_policy());d=self.delegated
        if any(s not in histories for s,v in p['short_caps'].items() if v):raise ValueError('automatic_incumbent_history_missing')
        at=now.isoformat();prior=self.prior_science(sc);equity=base.paper.totals(state,require_positive=False)['equity']
        if equity<=0:raise ValueError('automatic_positive_equity_required')
        weekly_due=self.meta('automatic_entry_week')!=w.week(at)
        used=sum(max(0.,v['quantity'])*v['current_price']/equity for v in state['positions'].values())
        room=max(0.,d['long_budget']-used)
        assessments=[];permits=copy.deepcopy(p.get('automatic_admissions',{}))
        old_assets=set(p['initial_quantities']);admitted=[]
        # Existing/reduced or previously admitted assets cannot be automatically
        # bought back. Only genuinely new flat candidates get one entry permit.
        candidates=sorted(w.POOL,key=lambda s:-(rows[s]['score'] or 0))
        risk=state['risk_policy_state'];daily_start=risk['daily_start_equity'] if 'daily_start_equity' in risk else risk.get('daily_start',equity)
        risk_ok=(equity>=daily_start*.98 and equity>=risk['high_water']*.9)
        for s in candidates:
            if s in old_assets or s in permits:continue
            q=self.full_market['quotes'].get(s)
            amount=w.floor_quantity(min(room,RULES['maximum_entry_weight'])*equity/q['mark_price'],q['quantity_step']) if q else 0.
            allowed=(d['allow_admissions'] and weekly_due and risk_ok and len(admitted)<2 and room>0)
            a=assessment(s,'ENTER',sc,prior,self.full_market,state,p,at,quantity=amount,room=allowed)
            if a['status']=='APPROVED':
                admitted.append(s);weight=amount*q['mark_price']/equity;room-=weight
                permits[s]=dict(quantity=amount,status='PENDING',approved_at=at,expires_at=(now+dt.timedelta(hours=48)).isoformat(),science_day=sc['day'])
                p['quantity_ceilings'][s]=amount;p['long_caps'][s]=weight
                p['selected']=sorted(set(p['selected'])|{s})
                if s not in state['positions']:
                    base.shared.sanity.structure_and_time(s,q,self.full_market,now)
                    state['positions'][s]=dict(base.paper.new_position(),current_price=q['mark_price'],last_mark_at=q['mark_timestamp'],funding_cursor=self.full_market['observed_at_end'],generation=0)
                    self.db.execute('INSERT INTO m1_management_admissions VALUES(?,?,?)',(s,self.full_market['observed_at_end'],p['proposal_id']))
                    self.db.execute('INSERT OR IGNORE INTO marks VALUES(?,?,?)',(self.full_market['observed_at_end'],s,q['mark_price']))
            assessments.append(a)
        p.update(authority_kind='delegated_automatic_review',automatic_admissions=permits,
            automatic_delegation_id=d['delegation_id'],valid_until=(now+dt.timedelta(days=7)).isoformat())
        # Actual stage ceilings may ratchet down between reviews; this immutable
        # approved snapshot becomes the next upper bound, never a restoration.
        p.pop('automatic_decision_id',None)
        self.record_review('DAILY_RENEWAL_AND_WEEKLY_SELECTION',at,dict(candidates=assessments,
            admitted=admitted,weekly_due=weekly_due,long_budget=d['long_budget'],short_budget=sum(d['short_caps'].values()),
            science_id=sc['snapshot_id'],market_hash=self.full_market['record_hash'],risk_ok=risk_ok),policy=p)
        self.put('automatic_science_id',sc['snapshot_id'])
        self.put('automatic_quantities_id',w.digest({s:v['quantity'] for s,v in state['positions'].items()}))
        if admitted:self.put('automatic_entry_week',w.week(at))
        self.universe=sorted(set(self.universe)|set(admitted));self.extend_parent(state)
        return state,self.project_market(self.full_market,self.universe) if admitted else record

    def management_cycle(self,state,control,record,now,debt):
        saved=copy.deepcopy(state);universe=list(self.universe)
        self.db.execute('SAVEPOINT automatic_review')
        try:
            state,record=self.automatic_cycle(state,control,record,now,debt)
            self.db.execute('RELEASE automatic_review')
            self.put('automatic_input_status',None)
        except (ValueError,KeyError,TypeError,OSError):
            self.db.execute('ROLLBACK TO automatic_review');self.db.execute('RELEASE automatic_review')
            state=saved;self.universe=universe
            self.put('automatic_input_status','WAITING_VALID_DATA_NO_NEW_APPROVAL')
            if self.meta('automatic_failure_day')!=now.date().isoformat():
                self.record_review('INPUTS_DEFERRED',now.isoformat(),dict(reason='WAITING_VALID_DATA_NO_NEW_APPROVAL'),status='DEFERRED')
                self.put('automatic_failure_day',now.date().isoformat())
        return super().management_cycle(state,control,record,now,debt)

    def baseline(self,control,now):
        super().baseline(control,now)
        p=self.managed_policy()
        for s,permit in p.get('automatic_admissions',{}).items():
            control['baseline_targets'][s]=p['long_caps'][s]

    def pending_targets(self,state,control,record,kind,weights,target):
        p=self.managed_policy();permits=p.get('automatic_admissions',{})
        if kind=='DAILY':
            rows,_,missing=w.signals(self.science(),record['observed_at_end'])
            changed=False
            equity=base.paper.totals(state,require_positive=False)['equity']
            gross=sum(max(0.,v['quantity'])*v['current_price'] for v in state['positions'].values())
            for s,v in permits.items():
                over_budget=gross+v['quantity']*record['quotes'][s]['mark_price']>self.delegated['long_budget']*equity+1e-8
                if v['status']=='PENDING' and (w.when(v['expires_at'])<w.when(record['observed_at_end']) or s in missing or rows[s]['signal']<=0 or over_budget):
                    # Revocation can only reduce permission. Persist an audit
                    # snapshot so policy authority remains reconstructible.
                    v['status']='CANCELLED';p['quantity_ceilings'][s]=0.;changed=True
                elif v['status']=='PENDING':gross+=v['quantity']*record['quotes'][s]['mark_price']
            if changed:
                p.pop('automatic_decision_id',None)
                self.record_review('ENTRY_PERMISSION_REVOKED',record['observed_at_end'],dict(reason='EXPIRED_OR_SIGNAL_NOT_POSITIVE'),policy=p)
        return super().pending_targets(state,control,record,kind,weights,target)

    def execute_pending(self,state,control,record,now,debt):
        before={s:v['quantity'] for s,v in state['positions'].items()};pending=copy.deepcopy(control.get('pending'))
        result=super().execute_pending(state,control,record,now,debt)
        p=copy.deepcopy(self.managed_policy());changed=False
        for s,v in p.get('automatic_admissions',{}).items():
            if v['status']=='PENDING' and (result['positions'][s]['quantity']>max(0.,before.get(s,0.)) or pending and pending['kind']=='M1_ENTRY'):
                v.update(status='CONSUMED' if result['positions'][s]['quantity']>0 else 'CANCELLED',filled_at=record['observed_at_end'],filled_quantity=max(0.,result['positions'][s]['quantity']))
                p['quantity_ceilings'][s]=max(0.,result['positions'][s]['quantity']);changed=True
        admission_progress=copy.deepcopy(self.meta('automatic_admission_progress') or {})
        if pending and pending['kind']=='MAINTENANCE_CLOSE' and not control.get('pending'):
            for s,g in admission_progress.items():
                if g['completed_at'] is None and result['positions'][s]['quantity']<=p['quantity_ceilings'][s]+record['quotes'][s]['quantity_step']/2:
                    g['completed_at']=record['observed_at_end']
            self.put('automatic_admission_progress',admission_progress)
        if changed:
            p.pop('automatic_decision_id',None)
            self.record_review('ENTRY_PERMISSION_CONSUMED',record['observed_at_end'],dict(reason='FILL_OR_M1_EPISODE'),policy=p)
        return result

    def publish_management(self):
        super().publish_management()
        path=Path(self.mc['projection']);value=json.loads(path.read_text())
        history=[json.loads(r[0]) for r in self.db.execute('SELECT payload FROM m1_auto_reviews ORDER BY rowid DESC LIMIT 50')]
        now=base.source.now();start=max(now.replace(hour=0,minute=0,second=0,microsecond=0),w.when(self.delegated['authorized_at'])).isoformat()
        fills=[json.loads(r[0]) for r in self.db.execute('SELECT payload FROM m1_fills WHERE at>=?',(start,))]
        statuses={}
        for row in self.db.execute('SELECT payload FROM m1_auto_reviews WHERE at>=?',(start,)):
            review=json.loads(row[0]);statuses[review['status']]=statuses.get(review['status'],0)+1
        daily=dict(since=start,decisions=statuses,fill_count=len(fills),
            fees=sum(f['fee'] for f in fills),realized=sum(f['realized_delta'] for f in fills),
            closed_pnl_less_current_fill_fees=sum(f['realized_delta']-f['fee'] for f in fills),
            meaning='FILL_ACCOUNTING_ONLY_NOT_TOTAL_RETURN_EXCLUDES_PRIOR_FEES_FUNDING_AND_OPEN_PNL')
        value['automatic_review']=dict(enabled=True,version=VERSION,rules=RULES,daily_review=daily,
            allow_admissions=self.delegated['allow_admissions'],input_status=self.meta('automatic_input_status'),
            delegation_id=self.delegated['delegation_id'],history=history,
            authority='operator_delegated_paper_only',short_budget=sum(self.delegated['short_caps'].values()),
            long_budget=self.delegated['long_budget'])
        base.source.atomic(path,value)


def main():
    managed.Runner=Runner
    managed.main()


if __name__=='__main__':main()
