"""Independent one-slot technical qualification on sealed retained evidence.

This script cannot execute an order or advance a repaired historical account.
Run with the evidence and repository mounted read-only, without networking.
"""
import argparse
import copy
import hashlib
import json
from pathlib import Path

from octobot.ai_strategy_lab import v13_discrete_risk_candidate as candidate

f = candidate.f


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def qualify(root):
    manifest = json.loads((root/'input-manifest.json').read_text())
    if manifest['role'] != 'SEALED_OFFLINE_COPIES':
        raise ValueError('offline_evidence_role')
    for name, expected in manifest['sha256'].items():
        if Path(name).is_absolute() or '..' in Path(name).parts or digest(root/name) != expected:
            raise ValueError('offline_evidence_hash')
    db = f.ro(root/'forks.sqlite')
    seed = f.ro(root/'parent-snapshot.sqlite')
    integrity = {}
    for name, connection in (('forks.sqlite',db),('parent-snapshot.sqlite',seed)):
        integrity[name] = [r[0] for r in connection.execute('PRAGMA integrity_check')]
        if integrity[name] != ['ok']:
            raise ValueError('offline_integrity')
    parent = json.loads(seed.execute('SELECT payload FROM state WHERE id=1').fetchone()[0])
    seed.close()
    states = {a:copy.deepcopy(parent) for a in f.ARMS}
    filters = {s:'FULL' for s in parent['positions']}
    fills = [dict(r) for r in db.execute('SELECT * FROM fills ORDER BY at,id')]
    funding = [dict(r) for r in db.execute('SELECT * FROM funding ORDER BY at,arm,symbol')]
    rows = []
    fi = fu = 0
    for slot in db.execute("SELECT * FROM slots WHERE status='EXECUTED' ORDER BY slot"):
        detail = json.loads(slot['payload'])
        record = f.read(root/'market'/(detail['market_hash']+'.json.gz'))
        at = record['observed_at_end']
        instant = f.p.timestamp(at)
        endms = int(instant.timestamp()*1000)
        while fu < len(funding) and funding[fu]['at'] <= endms:
            event = funding[fu]
            states[event['arm']]['positions'][event['symbol']]['funding'] += event['amount']
            fu += 1
        for state in states.values():
            for s,pos in state['positions'].items():
                pos['current_price'] = record['quotes'][s]['mark_price']
        day = (f.p.timestamp(slot['slot']).date()-f.dt.timedelta(days=1)).isoformat()
        inputs = json.loads(db.execute('SELECT payload FROM inputs WHERE day=?',(day,)).fetchone()[0])
        targets = {s:f.p.decode_weight(v) if isinstance(v,str) else v for s,v in inputs['targets'].items()}
        weights,new_filters,cov,_,_ = f.risk_targets(states,targets,inputs['prices'],filters)
        allow = not detail.get('funding_debt') and not any(detail['blocks'].values()) and not detail.get('shared_entry_block')
        pre = copy.deepcopy(states)
        predicted = copy.deepcopy(states)
        for arm in f.ARMS:
            legs,_ = f.engine.research_plan(predicted[arm],record['quotes'],weights[arm],allow)
            for leg in legs:
                f.paper.apply_fill(predicted[arm]['positions'][leg['symbol']],leg['quantity'],leg['price'],leg['fee'])
        while fi < len(fills) and fills[fi]['at'] <= at:
            row = fills[fi];fill = json.loads(row['payload'])
            f.paper.apply_fill(states[row['arm']]['positions'][row['symbol']],fill['quantity'],fill['price'],fill['fee'])
            fi += 1
        symbols = sorted(targets)
        vols = {a:candidate.volatility(states[a],cov,symbols) for a in f.ARMS}
        actual_quantities = {a:{s:states[a]['positions'][s]['quantity'] for s in symbols} for a in f.ARMS}
        qty_error = max(abs(predicted[a]['positions'][s]['quantity']-actual_quantities[a][s]) for a in f.ARMS for s in symbols)
        fee_error = max(abs(predicted[a]['positions'][s]['fees']-states[a]['positions'][s]['fees']) for a in f.ARMS for s in symbols)
        vol_error = max(abs(vols[a]-detail['realized_allocation_volatility'][a]) for a in f.ARMS)
        weight_error = max(abs(weights[a][s]-detail['weights'][a][s]) for a in f.ARMS for s in symbols)
        actual_gap = candidate.risk_gap(vols)
        if qty_error>1e-8 or fee_error>1e-8 or vol_error>1e-10 or weight_error>1e-10 or abs(actual_gap-detail['risk_gap'])>1e-10:
            raise AssertionError('actual_replay_mismatch:'+slot['slot'])
        # Reconstruct the complete actual net orders, then make one independent
        # technical repair. The actual state chain above is never replaced.
        paired_veto = bool(detail.get('shared_entry_block'))
        out = candidate.repair(pre,actual_quantities,cov,record,instant,
                               detail.get('funding_debt'),paired_entry_veto=paired_veto)
        projected_base,_,_,_,_ = candidate.simulate(pre,actual_quantities,record,allow)
        base_error = max(abs(candidate.volatility(projected_base[a],cov,symbols)-vols[a]) for a in f.ARMS)
        if base_error > 1e-10:
            raise AssertionError('quantity_projection_mismatch:'+slot['slot'])
        if out.get('blocks') != detail['blocks']:
            raise AssertionError('gate_outcome_differs:'+slot['slot'])
        if out.get('initial_gap') is not None and abs(out['initial_gap']-actual_gap)>1e-10:
            raise AssertionError('candidate_baseline_mismatch:'+slot['slot'])
        if out.get('paired_entry_veto') != paired_veto:
            raise AssertionError('paired_veto_differs:'+slot['slot'])
        final = out['states']
        fees_original = {a:sum(p['fees'] for p in states[a]['positions'].values()) for a in f.ARMS}
        fees_candidate = {a:sum(p['fees'] for p in final[a]['positions'].values()) for a in f.ARMS}
        drag = {a:f.paper.totals(states[a],require_positive=False)['equity']-f.paper.totals(final[a],require_positive=False)['equity'] for a in f.ARMS}
        reduced = all(abs(final[a]['positions'][s]['quantity']) <= abs(actual_quantities[a][s])+1e-9
                      and final[a]['positions'][s]['quantity']*actual_quantities[a][s] >= 0 for a in f.ARMS for s in symbols)
        projected_vols = out.get('volatility')
        if not reduced or (projected_vols and any(projected_vols[a]>vols[a]+1e-10 for a in f.ARMS)):
            raise AssertionError('risk_expanded:'+slot['slot'])
        rows.append(dict(slot=slot['slot'],actual_gap=actual_gap,actual_matched=detail['risk_matched'],
                         actual_volatility=vols,replay_errors=dict(quantity=qty_error,fees=fee_error,volatility=vol_error,weight=weight_error),
                         candidate_status=out['status'],candidate_qualified=out['qualified'],candidate_gap=out['gap'],
                         candidate_volatility=out.get('volatility'),adjustments=out['adjustments'],
                         fees_original=fees_original,fees_replanned=fees_candidate,incremental_execution_drag=drag,
                         recorded_blocks=detail['blocks'],paired_entry_veto=out.get('paired_entry_veto'),
                         funding_debt=out.get('funding_debt'),notes=out['notes'],quantities_only_reduce=reduced))
        filters = new_filters
    db.close()
    for name, expected in manifest['sha256'].items():
        if digest(root/name) != expected:
            raise AssertionError('evidence_changed')
    n = len(rows)
    return dict(scope='CONSUMED_DATA_INDEPENDENT_ONE_SLOT_ENGINEERING_QUALIFICATION',
                candidate_version=candidate.VERSION,tolerance=candidate.TOLERANCE,
                executed=n,actual_matched=sum(x['actual_matched'] for x in rows),
                candidate_matched=sum(x['candidate_qualified'] for x in rows),
                original_history_reclassified=False,corrected_state_propagated=False,
                future_profit_used=False,profitability_validated=False,execution_authorized=False,
                limitation='Recorded historical gate outcomes constrain reconstruction; intermediate policy counters are not independently replayed. Real gate behavior is tested with synthetic fault controls.',
                integrity=integrity,evidence_manifest_sha256=digest(root/'input-manifest.json'),
                evidence_unchanged=True,slots=rows)


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--evidence',type=Path,required=True)
    parser.add_argument('--output',type=Path,required=True)
    args=parser.parse_args()
    result=qualify(args.evidence)
    args.output.write_text(json.dumps(result,indent=2,allow_nan=False)+'\n')
    print(json.dumps({k:v for k,v in result.items() if k!='slots'}))
    for row in result['slots']:
        print(row['slot'],row['candidate_status'],f"{row['actual_gap']:.6%} -> {row['candidate_gap']:.6%}" if row['candidate_gap'] is not None else 'unqualified',len(row['adjustments']))
