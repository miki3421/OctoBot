"""Single-account M1 successor: monotone LONG risk, independent SHORT capacity.

Manual replacement authority is an immutable root-owned operator record, just
like the existing runtime upgrade record. It is not a browser approval and never
writes the password-protected approval database. Future web decisions retain
the existing broker boundary.
"""
import copy
import datetime as dt
import json
from pathlib import Path
from . import v13_m1_weekly as w
from . import v13_m1_transition as tr

VERSION = 'm1-gradual-long-short-v3'
SCOPE = 'M1_SINGLE_ACCOUNT_SUCCESSOR_V3'
COMPONENTS = ('STRATEGY_REPLACEMENT',)
LABEL = 'M1 · gestione graduale + SHORT'
DEFAULT_REMAINING = [.5, .25, 0.]


def proposal(parent, state, science, market, at, remaining=None):
    w.verify(parent, 'proposal_id'); w.verify(market, 'record_hash')
    rows, histories, unavailable = w.signals(science, at)
    when = w.when(at)
    if science['day'] != (when.date()-dt.timedelta(days=1)).isoformat():
        raise ValueError('latest_closed_day_required')
    held = sorted(s for s,p in state['positions'].items() if p['quantity'] > 0)
    if len(held) != 6 or any(p['quantity'] < 0 for p in state['positions'].values()):
        raise ValueError('six_normal_longs_required')
    if any(s in unavailable or rows[s]['signal'] > 0 for s in held):
        raise ValueError('six_deteriorated_signals_required')
    remain = list(remaining or DEFAULT_REMAINING)
    if remain not in ([.5,.25,0.], [.5,0.]):
        raise ValueError('unsupported_staging')
    from . import v13_market_sanity as sanity
    equity = state['initial_equity'] + sum(p['realized_pnl']+p['quantity']*(p['current_price']-p['entry_price'])-p['fees']+p['funding'] for p in state['positions'].values())
    if equity <= 0: raise ValueError('positive_equity_required')
    initial = {}; steps = {}; ceilings = {}; changes = {}; positions = {}; longs = {s:0. for s in w.POOL}
    for s,pos in state['positions'].items():
        q = w.num(pos['quantity']); quote = market['quotes'][s]
        if q:
            sanity.structure_and_time(s, quote, market, when)
        mark = w.num(quote['mark_price']); step = w.num(quote['quantity_step'])
        if mark != pos['current_price'] or mark <= 0 or step <= 0:
            raise ValueError('proposal_quote_binding')
        initial[s] = q; steps[s] = step
        ceilings[s] = w.floor_quantity(q*remain[0], step)
        longs[s] = ceilings[s]*mark/equity
        positions[s] = dict(quantity=q, mark=mark)
        if q:
            amount = q-ceilings[s]; left = amount; cost = 0.
            for level in quote['bids']:
                used = min(left, level['base_quantity']); cost += used*level['price']; left -= used
                if left <= 1e-10: break
            available = left <= 1e-8
            fill = cost/amount*.9998 if available else None
            fee = amount*fill*quote['fee_rate'] if available else None
            changes[s] = dict(current_quantity=q, indicative_target=ceilings[s], indicative_delta=-amount,
                indicative_weight=longs[s], cost_available=available, fee=fee,
                immediate_equity_cost=amount*(mark-fill)+fee if available else None,
                stages=[w.floor_quantity(q*f,step) for f in remain])
    shorts = {s:w.num(parent['short_caps'].get(s,0.)) for s in w.POOL}
    p = dict(version=VERSION, scope=SCOPE, account=parent['account'], parent_revision=0,
        parent_proposal_id=parent['parent_proposal_id'], supersedes=parent['proposal_id'],
        week=w.week(at), created_at=at, expires_at=(when+dt.timedelta(hours=48)).isoformat(),
        candidate_id=science['snapshot_id'], candidate_as_of=science['published_at'],
        market_hash=market['record_hash'], selected=sorted(s for s in initial if initial[s] or shorts[s]),
        previous=sorted(initial), affected=held, rows=rows, ineligible={},
        initial_quantities=initial, quantity_steps=steps, quantity_ceilings=ceilings,
        long_caps=longs, short_caps=shorts, short_reference_caps=dict(shorts),
        reference_equity=equity, indicative_positions=positions, indicative_changes=changes,
        approval_components=list(COMPONENTS), admissions_included=False, short_increase_included=False,
        cadence='ORIGINAL_PUBLISHED_BASELINE', scientific_validity='UNASSESSED',
        data_mode='CONTROL_FIXTURE_ONLY' if market.get('fixture') else 'PUBLIC_CAPTURE_RESEARCH_ONLY',
        simulation_contract='SEPARATE_SYNTHETIC_MINIMUMS', orders_authorized=False, execution_authorized=False,
        stage_rule=dict(remaining_fractions=remain, minimum_seconds=86400,
            distinct_closed_day=True, signal='EXISTING_DUAL_MOMENTUM_NOT_POSITIVE',
            repurchases=False, cash_redistribution=False, review_validity_days=7),
        events=[dict(symbol=s, reason='long_reduction') for s in held])
    p['summary'] = dict(long_before=sum(initial[s]*positions[s]['mark']/equity for s in initial),
        long_after=sum(longs.values()), short_before=sum(shorts.values()), short_after=sum(shorts.values()),
        turnover=sum(abs(c['indicative_delta'])*positions[s]['mark'] for s,c in changes.items()),
        estimated_cost=sum(c['immediate_equity_cost'] for c in changes.values() if c['cost_available']))
    p['proposal_id'] = w.digest(p); validate(p)
    return p


def validate(p):
    w.verify(p,'proposal_id')
    if p['version'] != VERSION or p['scope'] != SCOPE or p['approval_components'] != list(COMPONENTS):
        raise ValueError('successor_scope')
    normalized = copy.deepcopy(p)
    normalized.update(version=tr.VERSION, scope=tr.SCOPE, approval_components=list(tr.COMPONENTS))
    normalized['proposal_id'] = w.digest({k:v for k,v in normalized.items() if k!='proposal_id'})
    tr.validate(normalized)
    rule = p['stage_rule']
    if (rule != dict(remaining_fractions=rule['remaining_fractions'], minimum_seconds=86400,
                    distinct_closed_day=True, signal='EXISTING_DUAL_MOMENTUM_NOT_POSITIVE',
                    repurchases=False, cash_redistribution=False, review_validity_days=7)
            or rule['remaining_fractions'] not in ([.5,.25,0.],[.5,0.])):
        raise ValueError('successor_stage_rule')
    if set(p['initial_quantities']) != set(p['previous']) or set(p['quantity_steps']) != set(p['previous']):
        raise ValueError('successor_quantity_scope')
    for s,q in p['initial_quantities'].items():
        if q != p['indicative_positions'][s]['quantity'] or q < 0:
            raise ValueError('successor_initial_quantity')
        expected = w.floor_quantity(q*rule['remaining_fractions'][0],p['quantity_steps'][s])
        if p['quantity_ceilings'][s] != expected:
            raise ValueError('successor_first_stage')


def policy(p, at, authority_id, authority_kind):
    validate(p)
    if not w.when(p['created_at']) <= w.when(at) <= w.when(p['expires_at']):
        raise ValueError('successor_activation_expired')
    return dict(version=VERSION, revision=p['parent_revision']+1, account=p['account'],
        proposal_id=p['proposal_id'], decision_id=authority_id, authority_kind=authority_kind,
        selected=p['selected'], long_caps=p['long_caps'], short_caps=p['short_caps'],
        activated_at=at, initial_quantity_ceilings=dict(p['quantity_ceilings']),
        quantity_ceilings=dict(p['quantity_ceilings']), initial_quantities=p['initial_quantities'],
        quantity_steps=p['quantity_steps'], stage_rule=p['stage_rule'], cadence=p['cadence'],
        valid_until=(w.when(at)+dt.timedelta(days=7)).isoformat())


def approved_policy(p, decision, previous_revision, at):
    validate(p); w.verify(decision,'decision_id')
    if (decision.get('components') != list(COMPONENTS) or decision.get('exclude_short') != []
            or decision['proposal_id'] != p['proposal_id'] or decision['account'] != p['account']
            or decision['action'] != 'APPROVE' or decision['parent_revision'] != previous_revision
            or p['parent_revision'] != previous_revision or decision['proposal_expires_at'] != p['expires_at']
            or not w.when(p['created_at']) <= w.when(decision['decided_at']) <= w.when(at) <= w.when(p['expires_at'])):
        raise ValueError('successor_approval_binding')
    return policy(p,at,decision['decision_id'],'authenticated_operator')


def targets(state, policy, baseline, quotes, *, kind, short_reference=None):
    result, updated = tr.targets(state,policy,baseline,quotes,kind=kind,short_reference=short_reference)
    if kind != 'M1_ENTRY':
        for s,q in result.items():
            if q > 0:
                # BUY to cover a SHORT remains allowed by EXIT. Opening or
                # restoring LONG risk needs a future explicit revision.
                result[s] = min(q,max(0.,state['positions'][s]['quantity']))
                updated['quantity_ceilings'][s] = min(updated['quantity_ceilings'][s],result[s])
    return result,updated


def advance(policy, progress, state, science, at):
    """One stage per fresh daily confirmation, >=24h after actual completion.

    Call only while NORMAL with no pending intent. Missing input cannot become
    an exclusion. Partial fills keep the same target; restarts cannot halve it
    again. The budget on the SHORT side is never changed here.
    """
    p = copy.deepcopy(policy); progress = copy.deepcopy(progress or {})
    rows,histories,reasons = w.signals(science,at)
    now = w.when(at)
    if science['day'] != (now.date()-dt.timedelta(days=1)).isoformat():
        raise ValueError('successor_latest_day_required')
    events = []
    for s,initial in p['initial_quantities'].items():
        if not initial: continue
        if s not in histories or s in reasons:
            progress.setdefault(s,dict(stage=0,completed_at=None,science_day=science['day']))['status']='WAITING_DATA'
            continue
        step=p['quantity_steps'][s]; fractions=p['stage_rule']['remaining_fractions']
        g=progress.setdefault(s,dict(stage=0,completed_at=None,science_day=science['day']))
        quantity=max(0.,state['positions'][s]['quantity']); ceiling=p['quantity_ceilings'][s]
        if quantity > ceiling+step/2:
            g['status']='REDUCTION_PENDING';continue
        if g['completed_at'] is None:
            g.update(completed_at=at,science_day=science['day'])
        if g['stage'] == len(fractions)-1 or ceiling == 0:
            g['status']='LONG_CLOSED';continue
        if rows[s]['signal'] > 0:
            g['status']='RECOVERED_NO_REBUY';continue
        if (now-w.when(g['completed_at'])).total_seconds() < p['stage_rule']['minimum_seconds'] or science['day'] <= g['science_day']:
            g['status']='WAITING_NEXT_REVIEW';continue
        g['stage'] += 1; g.update(completed_at=None,science_day=science['day'],status='REDUCTION_PENDING')
        p['quantity_ceilings'][s] = min(ceiling,w.floor_quantity(initial*fractions[g['stage']],step),quantity)
        events.append(dict(symbol=s,stage=g['stage']+1,target=p['quantity_ceilings'][s],science_id=science['snapshot_id']))
    return p,progress,events


def authority(config, account):
    from .v13_m1_approval_broker import safe_file
    from . import v13_research_source as source
    c=config['successor']; path=safe_file(c['authority'],0)
    if path.stat().st_size > 200000: raise ValueError('successor_authority_size')
    value=json.loads(path.read_text());w.verify(value,'activation_id')
    proposal_path=safe_file(c['proposal'],0)
    from . import v13_fork_runner as shared
    if shared.sha(proposal_path) != c['proposal_sha256']:raise ValueError('successor_proposal_changed')
    p=json.loads(proposal_path.read_text());validate(p)
    if (value['scope']!='MANUAL_OPERATOR_M1_STRATEGY_REPLACEMENT' or value['account']!=account
            or value['proposal_id']!=p['proposal_id'] or not value['operator_reference']
            or w.when(value['authorized_at'])>source.now() or p['account']!=account):
        raise ValueError('successor_operator_authority')
    if value['quantities'] != p['initial_quantities']:
        raise ValueError('successor_activation_quantities_changed')
    upgrade=json.loads(safe_file(config['runtime_upgrade'],0).read_text())
    if (value['backup_sha256']!=upgrade['backup_sha256'] or upgrade['account']!=account
            or upgrade['scope']!='M1_GRADUAL_LONG_SHORT_V3'):
        raise ValueError('successor_stopped_backup_binding')
    return p,value


# The running account and all execution semantics remain in the existing engine.
from . import v13_m1_managed as managed


class Runner(managed.Runner):
    def __init__(self,config):
        super().__init__(config)
        p,a=authority(config,self.account)
        old=self.meta('strategy_successor')
        if old:
            if old['activation_id']!=a['activation_id']:raise ValueError('successor_reactivation_conflict')
            self.managed_policy();self.signal_boundary();return
        control=self.meta('control')
        state=json.loads(self.db.execute('SELECT payload FROM state WHERE id=1').fetchone()[0])
        if control['phase']!='NORMAL' or control.get('pending') or self.meta('management_policy'):
            raise ValueError('successor_requires_normal_unmanaged_account')
        if {s:v['quantity'] for s,v in state['positions'].items()} != a['quantities']:
            raise ValueError('successor_ledger_changed')
        initial=policy(p,a['authorized_at'],a['activation_id'],'direct_operator_instruction')
        with self.db:
            self.put('management_policy',initial)
            epoch=dict(activation_id=a['activation_id'],version=VERSION,label=LABEL,
                activated_at=a['authorized_at'],legacy_status='RETIRED',
                legacy_label='V13 + M1 SHORT · precedente',legacy_start=self.t0.isoformat(),
                boundary_metrics=managed.base.paper.totals(state,require_positive=False),
                legacy_fill_count=self.db.execute('SELECT COUNT(*) FROM m1_fills').fetchone()[0],
                proposal_id=p['proposal_id'],authority_kind='direct_operator_instruction')
            self.put('strategy_successor',epoch)
            self.db.execute("UPDATE m1_transition_reviews SET status='SUPERSEDED' WHERE status='PROPOSED'")
            self.db.execute("INSERT INTO m1_transition_reviews VALUES(?,?,?,'ACTIVE_SUCCESSOR',?)",(p['proposal_id'],p['week'],managed.base.shared.dump(p),a['activation_id']))
            self.event('STRATEGY_REPLACED',dict(epoch=epoch,operator_reference=a['operator_reference']),p['proposal_id'])
        self.signal_boundary()

    def signal_boundary(self):
        epoch=self.meta('strategy_successor')
        at=w.when(epoch['activated_at'])
        first=dt.datetime.fromtimestamp((int(at.timestamp())//300+1)*300,w.UTC).isoformat()
        # Preserve the old activation row. The successor never consumes a
        # signal slot preceding its own explicit operator activation.
        self.activation=dict(self.activation,legacy_first_signal_slot=self.activation['first_signal_slot'],
                             first_signal_slot=first)

    def transition_proposal(self):
        p,_=authority(self.c,self.account);return p

    def managed_policy(self):
        value=self.meta('management_policy')
        if value is None or value.get('authority_kind')!='direct_operator_instruction':
            return super().managed_policy()
        p,a=authority(self.c,self.account)
        expected=policy(p,a['authorized_at'],a['activation_id'],'direct_operator_instruction')
        if any(value.get(k)!=v for k,v in expected.items() if k!='quantity_ceilings'):
            raise ValueError('successor_policy_authority_changed')
        ceilings=value['quantity_ceilings']
        if set(ceilings)!=set(expected['quantity_ceilings']) or any(not 0<=w.num(q)<=expected['quantity_ceilings'][s] for s,q in ceilings.items()):
            raise ValueError('successor_quantity_ceiling_increased')
        epoch=self.meta('strategy_successor')
        if not epoch or epoch['activation_id']!=a['activation_id']:
            raise ValueError('successor_epoch_missing')
        return value

    def management_cycle(self,state,control,record,now,debt):
        p=self.managed_policy()
        if p and control['phase']=='NORMAL' and not control.get('pending'):
            try:
                updated,progress,events=advance(p,self.meta('successor_progress'),state,self.science(),now.isoformat())
                self.put('management_policy',updated);self.put('successor_progress',progress)
                self.put('successor_input_status',None)
                for event in events:self.event('GRADUAL_LONG_REDUCTION',event,p['proposal_id'])
            except (ValueError,KeyError,TypeError,OSError):
                self.put('successor_input_status','WAITING_FRESH_CAUSAL_DAILY_NO_EXTRA_REDUCTION')
        return super().management_cycle(state,control,record,now,debt)

    def execute_pending(self,state,control,record,now,debt):
        pending=copy.deepcopy(control.get('pending'))
        result=super().execute_pending(state,control,record,now,debt)
        if pending and pending['kind']=='MAINTENANCE_CLOSE' and not control.get('pending'):
            p=self.managed_policy();progress=copy.deepcopy(self.meta('successor_progress') or {})
            executed=control.get('last_action',{}).get('at')
            if executed:
                for s,initial in p['initial_quantities'].items():
                    if not initial:continue
                    g=progress.setdefault(s,dict(stage=0,completed_at=None,
                        science_day=(w.when(executed).date()-dt.timedelta(days=1)).isoformat()))
                    if max(0.,result['positions'][s]['quantity'])<=p['quantity_ceilings'][s]+p['quantity_steps'][s]/2 and g['completed_at'] is None:
                        g.update(completed_at=executed,status='WAITING_NEXT_REVIEW')
                self.put('successor_progress',progress)
        return result

    def publish_management(self):
        super().publish_management()
        path=Path(self.mc['projection']);value=json.loads(path.read_text())
        value.update(successor=self.meta('strategy_successor'),reduction_progress=self.meta('successor_progress'),
                     successor_input_status=self.meta('successor_input_status'))
        state=json.loads(self.db.execute('SELECT payload FROM state WHERE id=1').fetchone()[0])
        value['metrics']=managed.base.paper.totals(state,require_positive=False)
        managed.base.source.atomic(path,value)


def main():
    # Reuse the established single-writer lock, identity and loop.
    managed.Runner=Runner
    managed.main()


if __name__=='__main__':main()
