"""Pure offline transition candidate; never an approval or executable policy.

Card work-card-39a46574-e72f-4502-89b3-ce2d5366451c.
Uses the existing advisory criteria, preserving separate SHORT capacity.
"""
import copy
import hashlib
import json
import math
from . import v13_m1_symbol_review as review

VERSION = 'm1-portfolio-transition-candidate-v2'
SCOPE = 'OFFLINE_DESIGN_CANDIDATE_NOT_APPROVABLE_NOT_APPLIED'


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(',', ':'),
                                    allow_nan=False).encode()).hexdigest()


def candidates(attribution):
    """Keep the advisory method fixed; do not tune it to today's ranking."""
    if attribution['method'] != review.METHOD:
        raise ValueError('advisory_method_changed')
    ranked = []
    for symbol, value in attribution['m1']['symbols'].items():
        full = value['windows']['since_clone']['sides']['LONG']
        recent = value['windows']['48h']['sides']['LONG']
        if (value['current_quantity'] > 0 and full['net'] < 0 and recent['net'] < 0
                and full['active_days'] * 24 >= review.METHOD['minimum_long_exposure_hours']
                and all(v['coverage'] is not None and v['coverage'] >= review.METHOD['minimum_mark_coverage']
                        for v in (full, recent))):
            ranked.append((review.number(full['net_per_1000_notional_days']), symbol))
    return [symbol for _, symbol in sorted(ranked)[:review.METHOD['maximum_reduction_proposals']]]


def build(parent, attribution, market, *, phase):
    """Versioned diagnostic proposal. No runner, broker, store or network."""
    if phase != 'NORMAL':
        raise ValueError('normal_phase_required_for_transition_preview')
    if parent['proposal_id'] != digest({k: v for k, v in parent.items() if k != 'proposal_id'}):
        raise ValueError('invalid_parent')
    if market['record_hash'] != digest({k: v for k, v in market.items() if k != 'record_hash'}):
        raise ValueError('invalid_market')
    if (attribution['account'] != parent['account'] or attribution['end'] != market['observed_at_end']
            or attribution['source_hashes']['market'] != market['record_hash']):
        raise ValueError('account_or_market_binding')
    equity = review.number(attribution['m1']['equity'])
    if equity <= 0:
        raise ValueError('positive_equity_required')
    symbols = attribution['m1']['symbols']
    baseline = {}
    for symbol, value in symbols.items():
        quantity = review.number(value['current_quantity'])
        if quantity < 0:
            raise ValueError('existing_short_requires_separate_transition')
        mark = review.number(value['current_mark'])
        if mark <= 0 or market['quotes'][symbol]['mark_price'] != mark:
            raise ValueError('snapshot_mark_mismatch')
        baseline[symbol] = quantity
    short_caps = {s: q * symbols[s]['current_mark'] / equity for s, q in baseline.items()}
    if sum(short_caps.values()) > .9 or any(v > .315 for v in short_caps.values()):
        raise ValueError('existing_reference_exceeds_limits')
    targets = dict(baseline)
    reductions = []
    unavailable = []
    for symbol in candidates(attribution):
        estimate = review.reduction_cost(baseline[symbol], market['quotes'][symbol])
        if not estimate['available']:
            unavailable.append(dict(symbol=symbol, reason=estimate['reason']))
            continue  # Do not substitute another symbol after a liquidity failure.
        targets[symbol] = estimate['indicative_quantity_after']
        if not 0 < targets[symbol] < baseline[symbol]:
            raise ValueError('reduction_only_required')
        reductions.append(dict(symbol=symbol, reason='EXISTING_TWO_WINDOW_LONG_DETERIORATION_RULE',
                               estimate=estimate))
    before = sum(short_caps.values())
    after = sum(q * symbols[s]['current_mark'] / equity for s, q in targets.items())
    if after > before + 1e-12 or any(targets[s] > baseline[s] for s in targets):
        raise ValueError('cash_reallocation_forbidden')
    result = dict(
        version=VERSION, scope=SCOPE, account=parent['account'], parent_proposal_id=parent['proposal_id'],
        parent_revision=parent['parent_revision'], as_of=attribution['end'],
        input_hashes=dict(attribution=digest(attribution), **copy.deepcopy(attribution['source_hashes'])),
        method=copy.deepcopy(review.METHOD), reference_equity=equity,
        maintenance=dict(selected=candidates(attribution), reductions=reductions, unavailable=unavailable,
                         baseline_quantities=baseline, target_quantity_ceilings=targets,
                         no_automatic_rebuy=True, no_cash_reallocation=True,
                         reset_quantity_ceiling_only_on_new_explicit_approval=True),
        short_budget=dict(basis='CURRENT_HELD_LONG_MIRROR_AT_FROZEN_SNAPSHOT_NOT_PREVIOUS_V1_EXPANSION',
                          reference_caps=short_caps, proposed_caps=dict(short_caps),
                          reference_total=before, proposed_total=before,
                          parent_v1_total=sum(parent['short_caps'].values()), increase_authorized=False),
        new_symbol_admissions=dict(status='SEPARATE_DECISION_REQUIRED_NOT_INCLUDED',
                                   candidates=sorted(s for s in parent['selected'] if s not in symbols),
                                   admitted=[], requires_distinct_version_and_liquidity_review=True,
                                   requires_explicit_short_budget_redistribution_or_increase=True),
        cadence=dict(ordinary_signal_weights='REUSE_ORIGINAL_PUBLISHED_BASELINE_UNTIL_NEXT_ORIGINAL_RECALCULATION',
                     original_seven_day_anchor='2026-09-01', weekly_review='MONDAY_00:15_UTC',
                     extra_daily_weight_recalculation=False, intraday_m1_filter_unchanged=True,
                     contract_change_requires_new_approval=True),
        preview=dict(long_gross_before=before, long_gross_after=after,
                     freed_mark_notional=(before - after) * equity,
                     estimated_immediate_cost=sum(v['estimate']['estimated_immediate_equity_cost'] for v in reductions),
                     new_entries=0, full_closures=0),
        limitations=['Exploratory short account history, not proof of future profitability',
                     'Explicit amendment design uses later diagnostic data; not the frozen original weekly proposal',
                     'Indicative archived-book costs; future approved execution requires fresh inputs',
                     'SHORT reference preserves frozen capacity, not guaranteed future risk or PnL'],
        decisions=dict(maintenance='NOT_APPROVED', admissions='NOT_APPROVED', short_budget_increase='NOT_APPROVED'),
        orders_authorized=False, execution_authorized=False, live_activation_ready=False,
    )
    result['candidate_id'] = digest(result)
    return result
