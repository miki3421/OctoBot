"""Four-arm offline diagnostic on the already sealed historical cohorts.

Future labels are descriptive outputs only. They cannot feed the causal rule,
change event selection, or issue orders. There is no production adapter.
"""
import argparse
import bisect
from collections import Counter
import copy
import importlib.util
import json
import math
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
_spec = importlib.util.spec_from_file_location('broader', ROOT/'scripts/qualify_m1_short_broader.py')
B = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(B)
S = B.load('v13_m1_short_structure')
ARMS = ('old_invalidation', 'structural', 'protection_only', 'six_hour')


def future_label(policy, grid, decision_at, feature):
    """Ex-post one-hour continuation, never an input to watch or eligibility."""
    slot = int(decision_at)//300*300
    i = (slot-grid[0]['time'])//300
    window = grid[i:i+13]
    unknown = dict(label='UNKNOWN', anchor=B.iso(slot), horizon_seconds=3600)
    if (feature is None or len(window) != 13 or
            any(not r['valid'] or r['time'] != slot+j*300 for j, r in enumerate(window))):
        return unknown
    returns = {s: window[-1]['prices'][s]/window[0]['prices'][s]-1 for s in B.R.SIGNALS}
    threshold = max(.001, .5*feature['btc_sigma_1h'])
    positive = sum(v > 0 for v in returns.values())
    negative = sum(v < 0 for v in returns.values())
    label = 'AMBIGUOUS'
    if returns['BTCUSDT'] >= threshold and positive >= 12:
        label = 'RECOVERY_CONTINUES'
    elif returns['BTCUSDT'] <= -threshold and negative >= 12:
        label = 'FAILED_REBOUND'
    return dict(label=label, anchor=B.iso(slot), horizon_seconds=3600,
                btc_future_1h=returns['BTCUSDT'], threshold=threshold,
                positive_breadth_count=positive, negative_breadth_count=negative)


def replay(parent, policy, signal, grid, books, marks, scenario, capital, cache):
    model = B.R.model(B.history(grid, signal['index']), signal['slot'])
    if model['input_hash'] != signal['input_hash']:
        raise ValueError('signal_identity')
    due = signal['slot']+300
    timeout = due+21600
    segment = books.segment(due, timeout+300)
    entry = next((b for b in segment if B.availability(b) <= due+120 and
                  B.stamp(b['observed_at_start']) > due+scenario['latency_seconds']), None)
    if entry is None:
        raise ValueError('entry_book_unavailable_or_late')
    eligible = [b for b in segment if B.availability(b) >= B.availability(entry)]
    if not eligible or B.availability(eligible[-1]) < timeout:
        raise ValueError('six_hour_outcome_censored')
    if any(B.availability(b)-B.availability(a) > 120 for a, b in zip(eligible, eligible[1:])):
        raise ValueError('book_gap_over_120_seconds')
    plan, first = B.opening(parent, model, B.stressed(entry, scenario), capital)
    arms = {name: copy.deepcopy(first) for name in ARMS}
    decisions = []
    errors = Counter()
    for original in eligible:
        book = B.stressed(original, scenario)
        at = B.availability(book)
        slot = int(at)//300*300
        # Both feature objects use exactly the same validated closed panel.
        if slot not in cache:
            i = (slot-grid[0]['time'])//300
            try:
                rows = B.history(grid, i)
                cache[slot] = (B.R.model(rows, slot)['feature'], S.features(policy, rows, slot))
            except (ValueError, IndexError):
                cache[slot] = (None, None)
        old_feature, structure_feature = cache[slot]
        for name, state in arms.items():
            if state['closed_at'] is not None:
                continue
            funding_ok = B.funding(state, book, marks)
            try:
                state['path'].append((at, B.executable_value(state, book['quotes'])))
            except ValueError:
                state['valuation_missing_points'] += 1
            if state['pending']:
                if B.stamp(book['observed_at_start']) > state['pending']:
                    B.cover(state, book)
                    if state['closed_at'] is not None and not funding_ok:
                        state['debt_at_close'] = True
                    if state['closed_at'] is None:
                        state['pending'] = at+scenario['latency_seconds']
                continue
            reason = None
            if name != 'six_hour' and funding_ok:
                feature_slot = slot if slot >= first['episode']['at'] else None
                try:
                    common = dict(at=at, market_id=original['record_hash'])
                    if name == 'structural':
                        ep, reason = S.watch(parent, policy, state['episode'], state['positions'],
                            book['quotes'], feature_slot=feature_slot,
                            feature=structure_feature if feature_slot is not None else None, **common)
                    else:
                        ep, reason = B.R.watch(parent, state['episode'], state['positions'], book['quotes'],
                            feature_slot=feature_slot if name == 'old_invalidation' else None,
                            feature=old_feature if name == 'old_invalidation' else None, **common)
                    state['episode'] = ep
                except ValueError as error:
                    errors[name+':'+str(error)] += 1
            if reason is None and at >= timeout:
                reason = 'MAX_HOLD'
            if reason:
                state['exit_reason'] = reason
                state['pending'] = at+scenario['latency_seconds']
                decisions.append(dict(arm=name, at=B.iso(at), reason=reason,
                    source_book=original['record_hash'], structural_feature=structure_feature,
                    old_feature=old_feature,
                    confirmed_structure_slots=state['episode'].get('structure_count', 0)))
        if all(v['closed_at'] is not None for v in arms.values()):
            break
    # Labels are computed only after every decision and simulated execution.
    for decision in decisions:
        if decision['reason'] in ('SIGNAL_INVALIDATED', 'STRUCTURAL_REVERSAL'):
            decision['future_label'] = future_label(policy, grid, B.stamp(decision['at']),
                                                    decision['structural_feature'])
    return dict(signal_at=B.iso(signal['slot']), entry_at=B.iso(B.availability(entry)),
        scenario=scenario['name'], capital_reference=capital, notional=plan['short_notional'],
        risk_unit=plan['risk_unit'], planned_stopped_risk=plan['planned_stopped_risk'],
        quantities=plan['quantities'], arms={name: B.summarize(state) for name, state in arms.items()},
        decisions=decisions, decision_errors=dict(errors))


def reproduce(row, expected, tolerance):
    """Reject a changed cashflow, clock, position, or exit on the two controls."""
    for key in ('signal_at', 'entry_at', 'scenario', 'quantities'):
        if row[key] != expected[key]:
            raise ValueError('control_reproduction:'+key)
    for name, old in [('old_invalidation', 'corrected'), ('six_hour', 'six_hour')]:
        actual = row['arms'][name]
        for key, value in expected[old].items():
            if key == 'path':
                continue
            if isinstance(value, (int, float)):
                if not math.isclose(actual[key], value, rel_tol=0, abs_tol=tolerance):
                    raise ValueError('control_reproduction:'+name+':'+key)
            elif actual[key] != value:
                raise ValueError('control_reproduction:'+name+':'+key)


def aggregate(rows):
    result = dict(episodes=len(rows), arms={}, structural_difference={})
    for name in ARMS:
        values = [r['arms'][name] for r in rows]
        result['arms'][name] = dict(net=math.fsum(v['net'] for v in values),
            fees=math.fsum(v['fees'] for v in values), funding=math.fsum(v['funding'] for v in values),
            winners=sum(v['net'] > 0 for v in values), worst_episode=min(v['net'] for v in values),
            worst_observed_executable_pnl=min(v['worst_executable_pnl'] for v in values)
                if all(v['valuation_missing_points'] == 0 for v in values) else None,
            unavailable_valuation_points=sum(v['valuation_missing_points'] for v in values),
            mean_holding_hours=math.fsum(v['holding_seconds'] for v in values)/len(values)/3600,
            exit_reasons=dict(Counter(v['reason'] for v in values)))
    for name in ('old_invalidation', 'protection_only', 'six_hour'):
        differences = [r['arms']['structural']['net']-r['arms'][name]['net'] for r in rows]
        weekly = {}
        for row, delta in zip(rows, differences):
            week = B.dt.datetime.fromisoformat(row['signal_at']).strftime('%G-W%V')
            weekly[week] = weekly.get(week, 0.)+delta
        total = math.fsum(differences)
        result['structural_difference'][name] = dict(net=total,
            improved=sum(v > 1e-8 for v in differences), worsened=sum(v < -1e-8 for v in differences),
            unchanged=sum(abs(v) <= 1e-8 for v in differences), weekly=weekly,
            leave_one_week_out={k: total-v for k, v in weekly.items()})
    result['invalidation_labels'] = {name: dict(Counter(
        d['future_label']['label'] for r in rows for d in r['decisions']
        if d['arm'] == name and 'future_label' in d)) for name in ('old_invalidation', 'structural')}
    return result


def run(evidence, previous):
    e, previous = Path(evidence), Path(previous)
    contract = json.loads((e/'verification-lock.json').read_text())
    if B.R.digest({k: v for k, v in contract.items() if k != 'lock_id'}) != contract['lock_id']:
        raise ValueError('verification_lock_identity')
    for name, expected in contract['code_sha256'].items():
        if B.sha(ROOT/name) != expected:
            raise ValueError('code_changed:'+name)
    for name, expected in contract['previous_evidence_sha256'].items():
        if B.sha(previous/name) != expected:
            raise ValueError('previous_evidence_changed:'+name)
    policy = json.loads((e/'frozen-protocol.json').read_text())
    S.validate(policy)
    if B.sha(e/'frozen-protocol.json') != contract['protocol_sha256']:
        raise ValueError('frozen_protocol_changed')
    for name, expected in policy['frozen_predecessor_sha256'].items():
        if B.sha(ROOT/name) != expected:
            raise ValueError('predecessor_changed:'+name)
    parent = json.loads((ROOT/'docs/research-protocols/m1-short-risk-exits-candidate-v1.json').read_text())
    inv = json.loads((previous/'inventory.json').read_text())
    payloads = {}
    for name, expected in inv['files'].items():
        if B.sha(previous/(name+'.json')) != expected:
            raise ValueError('previous_inventory_component_changed:'+name)
        payloads[name] = json.loads((previous/(name+'.json')).read_text())
    with B.sealed_db(inv['source'], inv['source_sha256']) as db:
        integrity = db.execute('PRAGMA integrity_check').fetchone()[0]
        if integrity != 'ok':
            raise ValueError('sealed_database_integrity')
        marks = {s: [] for s in B.R.SIGNALS}
        for row in db.execute('SELECT bar,symbol,price FROM marks ORDER BY bar,symbol'):
            marks[row['symbol']].append((B.stamp(row['bar']), row['price']))
    # Reuse the previously verified archive cache, never any live collector.
    books = B.Books(e, previous/'books', payloads['book_index'], B.stamp(inv['last'])+300, marks)
    base_prior = json.loads((previous/'coverage-supplement.json').read_text())['episodes']
    stress_prior = json.loads((previous/'results.json').read_text())['scenarios']
    scenarios = policy['evaluation']['scenarios']
    output = {}
    cache = {}
    for scenario in scenarios:
        expected_rows = base_prior if scenario['name'] == 'base' else stress_prior[scenario['name']]['episodes']
        cohort = policy['cohorts']['base' if scenario['name'] == 'base' else 'common_stress']
        if [r['signal_at'] for r in expected_rows] != cohort:
            raise ValueError('frozen_cohort_identity')
        rows = []
        for expected in expected_rows:
            signal = next(v for v in payloads['signals'] if B.iso(v['slot']) == expected['signal_at'])
            row = replay(parent, policy, signal, payloads['grid'], books, marks,
                         scenario, policy['evaluation']['reference_capital'], cache)
            reproduce(row, expected, policy['evaluation']['old_and_six_hour_reproduction_absolute_tolerance'])
            if row['decision_errors']:
                raise ValueError('unexpected_controller_error:'+str(row['decision_errors']))
            paths = {name: row['arms'][name].pop('path') for name in ARMS}
            (e/('paths-'+expected['signal_at'][:10]+'-'+scenario['name']+'.json')).write_text(
                json.dumps(paths, separators=(',', ':'), allow_nan=False)+'\n')
            rows.append(row)
            print('qualified', scenario['name'], expected['signal_at'], flush=True)
        output[scenario['name']] = dict(summary=aggregate(rows), episodes=rows)
    common = set(policy['cohorts']['common_stress'])
    result = dict(scope='EXPLORATORY_REUSED_HISTORICAL_OUTCOMES_NO_INDEPENDENT_VALIDATION',
        protocol_id=S.PROTOCOL_ID, verification_lock_id=contract['lock_id'],
        sealed_source_integrity=integrity, exact_prior_controls_reproduced=True,
        active_changes=False, promotion=False, scenarios=output,
        base_common_summary=aggregate([r for r in output['base']['episodes'] if r['signal_at'] in common]),
        features_cached=len(cache), used_books=len(books.used),
        limitations=policy['limitations'])
    (e/'results.json').write_text(json.dumps(result, indent=2, allow_nan=False)+'\n')
    (e/'used-books.json').write_text(json.dumps(books.used, indent=2)+'\n')
    print(json.dumps({k: v['summary'] for k, v in output.items()}, indent=2))
    return result


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--evidence', required=True)
    parser.add_argument('--previous', required=True)
    args = parser.parse_args()
    run(args.evidence, args.previous)
