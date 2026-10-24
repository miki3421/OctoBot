"""Approval-bound v2 maintenance. Pure contracts, never broker or ledger access."""
import copy
import datetime as dt
from . import v13_m1_weekly as w

VERSION = 'm1-long-maintenance-v2'
SCOPE = 'M1_RESEARCH_PAPER_LONG_MAINTENANCE_V2'
COMPONENTS = ('LONG_MAINTENANCE',)


def proposal(candidate, parent, state, market, at):
    w.verify(candidate, 'candidate_id'); w.verify(parent, 'proposal_id'); w.verify(market, 'record_hash')
    if (candidate['scope'] != 'OFFLINE_DESIGN_CANDIDATE_NOT_APPROVABLE_NOT_APPLIED'
            or candidate['parent_proposal_id'] != parent['proposal_id']
            or candidate['account'] != parent['account']):
        raise ValueError('candidate_parent_binding')
    if not w.when(candidate['as_of']) <= w.when(market['observed_at_end']) <= w.when(at) <= w.when(parent['expires_at']):
        raise ValueError('transition_times')
    equity = state['initial_equity'] + sum(v['realized_pnl'] + v['quantity'] * (v['current_price']-v['entry_price']) - v['fees'] + v['funding'] for v in state['positions'].values())
    if equity <= 0 or any(v['quantity'] < 0 for v in state['positions'].values()):
        raise ValueError('normal_long_snapshot_required')
    affected = [v['symbol'] for v in candidate['maintenance']['reductions']]
    ceiling = {}; changes = {}; positions = {}
    caps = {s: 0. for s in w.POOL}; shorts = {s: w.num(candidate['short_budget']['reference_caps'].get(s, 0.)) for s in w.POOL}
    if candidate['short_budget']['proposed_caps'] != candidate['short_budget']['reference_caps']:
        raise ValueError('short_expansion_forbidden')
    from . import v13_market_sanity as sanity
    for s, pos in state['positions'].items():
        if s not in w.POOL: raise ValueError('unknown_symbol')
        q = w.num(pos['quantity']); quote = market['quotes'][s]; mark = w.num(quote['mark_price'])
        if mark != pos['current_price'] or mark <= 0: raise ValueError('snapshot_mark')
        if q or s in affected: sanity.structure_and_time(s, quote, market, w.when(at))
        ceiling[s] = min(q, candidate['maintenance']['target_quantity_ceilings'][s]) if s in affected else q
        ceiling[s] = w.floor_quantity(ceiling[s], quote['quantity_step'])
        caps[s] = ceiling[s] * mark / equity
        positions[s] = dict(quantity=q, mark=mark)
        delta = ceiling[s]-q
        if abs(delta) < 1e-10: continue
        remaining = abs(delta); gross = 0.
        for level in quote['bids']:
            used = min(remaining, level['base_quantity']); gross += used*level['price']; remaining -= used
            if remaining < 1e-10: break
        available = remaining < 1e-8
        fill = gross/abs(delta)*.9998 if available else None
        fee = abs(delta)*fill*quote['fee_rate'] if available else None
        changes[s] = dict(current_quantity=q, indicative_target=ceiling[s], indicative_delta=delta,
                          indicative_weight=caps[s], cost_available=available, fee=fee,
                          immediate_equity_cost=delta*(fill-mark)+fee if available else None)
    p = dict(version=VERSION, scope=SCOPE, account=parent['account'], parent_revision=parent['parent_revision'],
             candidate_id=candidate['candidate_id'], parent_proposal_id=parent['proposal_id'],
             week=parent['week'], created_at=at, expires_at=parent['expires_at'],
             market_hash=market['record_hash'], candidate_as_of=candidate['as_of'],
             selected=sorted(s for s in ceiling if ceiling[s] or shorts[s]), previous=sorted(state['positions']),
             long_caps=caps, short_caps=shorts, short_reference_caps=dict(shorts),
             quantity_ceilings=ceiling, affected=sorted(affected),
             reference_equity=equity, indicative_positions=positions, indicative_changes=changes,
             rows=copy.deepcopy(parent['rows']), ineligible={},
             events=[dict(symbol=s, reason='long_reduction') for s in sorted(changes)],
             approval_components=list(COMPONENTS), admissions_included=False, short_increase_included=False,
             cadence='ORIGINAL_PUBLISHED_BASELINE', scientific_validity='UNASSESSED',
             data_mode='CONTROL_FIXTURE_ONLY' if market.get('fixture') else 'PUBLIC_CAPTURE_RESEARCH_ONLY',
             simulation_contract='SEPARATE_SYNTHETIC_MINIMUMS', orders_authorized=False, execution_authorized=False)
    p['summary'] = dict(long_before=sum(v['quantity']*v['mark']/equity for v in positions.values()),
                        long_after=sum(caps.values()), short_before=sum(shorts.values()), short_after=sum(shorts.values()),
                        turnover=sum(abs(v['indicative_delta'])*positions[s]['mark'] for s,v in changes.items()),
                        estimated_cost=sum(v['immediate_equity_cost'] for v in changes.values() if v['cost_available']))
    p['proposal_id'] = w.digest(p)
    validate(p)
    return p


def validate(p):
    w.verify(p, 'proposal_id')
    if (p['version'] != VERSION or p['scope'] != SCOPE or p['approval_components'] != list(COMPONENTS)
            or p['admissions_included'] is not False or p['short_increase_included'] is not False
            or p['short_caps'] != p['short_reference_caps'] or p['cadence'] != 'ORIGINAL_PUBLISHED_BASELINE'
            or p['orders_authorized'] is not False or p['execution_authorized'] is not False):
        raise ValueError('transition_scope_or_short_budget')
    for side in (p['long_caps'], p['short_caps']):
        if set(side) != set(w.POOL) or any(not 0 <= w.num(v) <= .315 for v in side.values()) or sum(side.values()) > .90000001:
            raise ValueError('transition_budget_limits')
    if set(p['quantity_ceilings']) != set(p['previous']) or not set(p['affected']) <= set(p['previous']):
        raise ValueError('transition_universe')
    for s,q in p['quantity_ceilings'].items():
        if not 0 <= w.num(q) <= w.num(p['indicative_positions'][s]['quantity']):
            raise ValueError('transition_increase_forbidden')


def approved_policy(p, decision, previous_revision, at):
    validate(p); w.verify(decision, 'decision_id')
    if (decision.get('components') != list(COMPONENTS) or decision.get('exclude_short') != []
            or decision['proposal_id'] != p['proposal_id'] or decision['account'] != p['account']
            or decision['action'] != 'APPROVE' or decision['parent_revision'] != p['parent_revision']
            or p['parent_revision'] != previous_revision or decision['proposal_expires_at'] != p['expires_at']
            or not w.when(p['created_at']) <= w.when(decision['decided_at']) <= w.when(at) <= w.when(p['expires_at'])):
        raise ValueError('transition_approval_binding')
    return dict(version=VERSION, revision=previous_revision+1, account=p['account'], proposal_id=p['proposal_id'],
                decision_id=decision['decision_id'], selected=p['selected'], long_caps=p['long_caps'],
                short_caps=p['short_caps'], activated_at=at,
                initial_quantity_ceilings=dict(p['quantity_ceilings']), quantity_ceilings=dict(p['quantity_ceilings']),
                cadence=p['cadence'], valid_until=(w.when(p['week'])+dt.timedelta(days=9)).isoformat())


def targets(state, policy, baseline, quotes, *, kind, short_reference=None):
    policy = copy.deepcopy(policy); result = {}
    equity = state['initial_equity'] + sum(v['realized_pnl'] + v['quantity']*(v['current_price']-v['entry_price'])-v['fees']+v['funding'] for v in state['positions'].values())
    if equity <= 0: raise ValueError('positive_equity_required')
    for s,pos in state['positions'].items():
        if s not in quotes:
            if pos['quantity']: raise ValueError('held_quote_missing')
            continue
        quote=quotes[s]; mark=w.num(quote['mark_price']); step=quote['quantity_step']
        if mark <= 0: raise ValueError('positive_mark_required')
        ceiling = policy['quantity_ceilings'].get(s,0.)
        if kind == 'MAINTENANCE_CLOSE':
            result[s]=min(pos['quantity'],ceiling) if pos['quantity']>0 else pos['quantity'];continue
        if kind == 'M1_ENTRY':
            weight=-min(policy['short_caps'].get(s,0.),abs((short_reference or policy['short_caps']).get(s,0.)))
        else:
            raw=w.num(baseline.get(s,0.));weight=raw if raw>=0 else -min(abs(raw),policy['short_caps'].get(s,0.))
        q=w.floor_quantity(abs(weight)*equity/mark,step)
        if weight>0:
            q=w.floor_quantity(min(q,ceiling),step);policy['quantity_ceilings'][s]=q
        elif kind!='M1_ENTRY':
            policy['quantity_ceilings'][s]=0.
        result[s]=q if weight>0 else -q if weight<0 else 0.
    return result,policy
