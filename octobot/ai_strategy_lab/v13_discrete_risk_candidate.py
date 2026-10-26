"""Inactive pure post-cost risk repair. No runner, network or ledger writer.

The input quantities are a proposed plan, never an authority to execute it.
This candidate is intentionally not imported by any active strategy.
"""
import copy
from decimal import Decimal
import math
from . import v13_fork_runner as f

TOLERANCE = .02
MAX_ITERATIONS = 1000
VERSION = 'fast-half-discrete-risk-offline-candidate-v1'


def volatility(state, covariance, symbols):
    import numpy as np
    equity = f.paper.totals(state, require_positive=False)['equity']
    if equity <= 0:
        raise ValueError('risk_equity')
    weights = np.array([state['positions'][s]['quantity']*state['positions'][s]['current_price']/equity for s in symbols])
    variance = float(weights @ covariance @ weights)
    if not math.isfinite(variance) or variance < -1e-12:
        raise ValueError('risk_variance')
    return math.sqrt(max(0., 365*variance))


def risk_gap(vols):
    maximum = max(vols.values())
    return abs(vols['FAST']-vols['HALF'])/maximum if maximum else 0.


def funding_problem(record):
    """Check supplied observations, in addition to the caller's ledger debt.

    This does not replace reconciliation of held quantities and funding cursors.
    The independent historical test retains the recorded funding-debt outcome.
    """
    cutoff = int(f.p.timestamp(record['observed_at_end']).timestamp()*1000)
    for symbol, quote in record['quotes'].items():
        interval = quote.get('funding_interval_ms')
        points = quote.get('funding')
        if type(interval) is not int or not 0 < interval <= 86400000 or not points:
            return 'funding_coverage_missing:' + symbol
        times = [x['timestamp_ms'] for x in points]
        if (any(type(t) is not int for t in times) or times != sorted(set(times))
                or times[-1] > cutoff or times[-1]+interval <= cutoff
                or any(b-a > interval for a,b in zip(times,times[1:]))):
            return 'funding_coverage_invalid:' + symbol
        if any(not math.isfinite(float(x['rate'])) for x in points):
            return 'funding_rate_invalid:' + symbol
    return None


def exact_legs(state, quotes, quantities, allow):
    """Same synthetic contract as research_plan, with explicit quantities.

    A complete net order uses each symbol's observed side depth only once.
    Protective reductions retain the existing simulated-minimum exceptions.
    """
    legs, notes = [], []
    equity = f.paper.totals(state, require_positive=False)['equity']
    for symbol, target in sorted(quantities.items()):
        target = f.exposure.number(target, 'target quantity')
        quote = quotes[symbol]
        old = state['positions'][symbol]['quantity']
        step = f.exposure.number(quote['quantity_step'], 'simulation step', positive=True)
        if abs(target/step-round(target/step)) > 1e-7:
            raise ValueError('quantity_not_aligned')
        delta = target-old
        if abs(delta) <= 8*max(math.ulp(old), math.ulp(target), math.ulp(1.)):
            continue
        protective = old*target >= 0 and abs(target) < abs(old)
        if not allow and not protective:
            notes.append(dict(symbol=symbol, reason='new_risk_suspended'))
            continue
        mid = (quote['asks'][0]['price']+quote['bids'][0]['price'])/2
        if not protective and ((quote['asks'][0]['price']-quote['bids'][0]['price'])/mid > float(f.sanity.POLICY.max_spread_ratio)
                               or abs(quote['mark_price']-mid)/mid > float(f.sanity.POLICY.max_mark_mid_divergence)):
            notes.append(dict(symbol=symbol, reason='paired_market_veto'))
            continue
        capacity = math.fsum(x['base_quantity'] for x in quote['asks' if delta>0 else 'bids'])
        if abs(delta) > capacity:
            delta = math.copysign(float((Decimal(str(capacity))//Decimal(str(step)))*Decimal(str(step))), delta)
            notes.append(dict(symbol=symbol, reason='partial_observed_depth'))
        if abs(delta) < step*(1-1e-12) and not (protective and target == 0):
            notes.append(dict(symbol=symbol, reason='below_simulated_quantity_minimum'))
            continue
        if not delta:
            continue
        price = f.exposure.execution_price(quote, delta, f.engine.market.fill_price)
        if abs(delta*price) < 1 and not protective:
            notes.append(dict(symbol=symbol, reason='paired_market_veto'))
            continue
        fee_rate = f.exposure.number(quote['fee_rate'], 'fee', nonnegative=True)
        if not .0006 <= fee_rate < 1:
            raise ValueError('fee_invalid')
        legs.append(dict(symbol=symbol, quantity=delta, price=price, fee=abs(delta*price)*fee_rate,
                         protective=protective, weight=target*quote['mark_price']/equity))
    return sorted(legs, key=lambda x:(not x['protective'], x['symbol'])), notes


def simulate(pre, quantities, record, allow):
    result = copy.deepcopy(pre)
    plans = {a:exact_legs(result[a], record['quotes'], quantities[a], allow) for a in f.ARMS}
    if allow and any(x['reason']=='paired_market_veto' for _,notes in plans.values() for x in notes):
        states, fills, notes, complete, _ = simulate(pre, quantities, record, False)
        return states, fills, notes, complete, True
    fills, notes = [], []
    for arm in f.ARMS:
        legs, skipped = plans[arm]
        notes.extend(dict(arm=arm, **x) for x in skipped)
        for leg in legs:
            old = result[arm]['positions'][leg['symbol']]['quantity']
            f.paper.apply_fill(result[arm]['positions'][leg['symbol']], leg['quantity'], leg['price'], leg['fee'])
            qs, marks = f.exposure.quantities_and_marks(result[arm])
            cap = f.exposure.snapshot(qs, marks, f.paper.totals(result[arm], require_positive=False)['equity'], .90, .315)
            if cap['breaches'] and not leg['protective']:
                if not allow:
                    raise ValueError('protective_exposure_failure')
                states, fs, ns, complete, _ = simulate(pre, quantities, record, False)
                return states, fs, ns, complete, True
            fills.append(dict(arm=arm, **leg, before=old,
                              after=result[arm]['positions'][leg['symbol']]['quantity']))
    complete = all(abs(result[a]['positions'][s]['quantity']-quantities[a][s]) < 1e-8
                   for a in f.ARMS for s in quantities[a])
    return result, fills, notes, complete, False


def repair(states, quantities, covariance, record, instant, funding_debt=None, *, paired_entry_veto=False):
    """Project/repair one independent context; every qualification is technical."""
    import numpy as np
    original = copy.deepcopy(states)
    result = dict(version=VERSION, scope='OFFLINE_TECHNICAL_RISK_PLAN_ONLY',
                  execution_authorized=False, orders_authorized=False, qualified=False,
                  states=original, fills=[], adjustments=[], notes=[], gap=None)
    try:
        symbols = sorted(record['quotes'])
        f.verified_market(record, symbols, instant)
        if set(states) != set(f.ARMS) or set(quantities) != set(f.ARMS):
            raise ValueError('pair_scope')
        if any(set(states[a]['positions']) != set(symbols) or set(quantities[a]) != set(symbols) for a in f.ARMS):
            raise ValueError('symbol_scope')
        cov = np.asarray(covariance, dtype=float)
        if (cov.shape != (len(symbols),len(symbols)) or not np.isfinite(cov).all()
                or not np.allclose(cov,cov.T,rtol=0,atol=1e-12)
                or np.linalg.eigvalsh(cov).min() < -1e-12):
            raise ValueError('risk_covariance')
        pre = copy.deepcopy(states)
        for state in pre.values():
            for s, pos in state['positions'].items():
                pos['current_price'] = record['quotes'][s]['mark_price']
            f.exposure.quantities_and_marks(state)
        blocks = {a:f.engine.risk_gate(pre[a],instant,f.paper.totals(pre[a],require_positive=False)['equity']) for a in f.ARMS}
        debt = funding_debt or funding_problem(record)
        allow = not debt and not any(blocks.values()) and not paired_entry_veto
        baseline, fills, notes, complete, discovered_veto = simulate(pre, quantities, record, allow)
        paired_veto = bool(paired_entry_veto or discovered_veto)
        partial = any(x['reason'] in ('partial_observed_depth','below_simulated_quantity_minimum') for x in notes)
        result.update(states=baseline, fills=fills, notes=notes, blocks=blocks,
                      funding_debt=debt, paired_entry_veto=paired_veto,
                      requested_plan_completed=complete)
        if debt:
            result['status']='UNQUALIFIED_FUNDING'
            return result
        vols = {a:volatility(baseline[a],cov,symbols) for a in f.ARMS}
        gap = risk_gap(vols)
        result.update(initial_volatility=vols, initial_gap=gap, volatility=vols, gap=gap)
        if partial:
            result['status']='UNQUALIFIED_PARTIAL_EXECUTION'
            return result
        if not max(vols.values()):
            flat = all(not p['quantity'] for state in baseline.values() for p in state['positions'].values())
            result.update(status='MATCHED_FLAT' if flat else 'UNQUALIFIED_ZERO_COVARIANCE', qualified=flat)
            return result
        if not min(vols.values()):
            result['status']='UNQUALIFIED_ONE_SIDED_ZERO_RISK'
            return result
        current = baseline
        target = {a:{s:baseline[a]['positions'][s]['quantity'] for s in symbols} for a in f.ARMS}
        # A paired veto remains binding for every proposed replacement order.
        allow = allow and not paired_veto
        for _ in range(MAX_ITERATIONS):
            if gap <= TOLERANCE:
                break
            arm = max(f.ARMS, key=lambda a:vols[a])
            options = []
            for symbol in symbols:
                old = target[arm][symbol]
                step = record['quotes'][symbol]['quantity_step']
                if abs(old) < step*(1-1e-9):
                    continue
                proposal = copy.deepcopy(target)
                proposal[arm][symbol] = math.copysign(max(0,round(abs(old)/step)-1)*step,old)
                trial, trial_fills, trial_notes, reached, veto = simulate(pre,proposal,record,allow)
                if not reached or veto or any(x['reason']=='partial_observed_depth' for x in trial_notes):
                    continue
                trial_vols = {a:volatility(trial[a],cov,symbols) for a in f.ARMS}
                trial_gap = risk_gap(trial_vols)
                if trial_gap < gap-1e-12 and trial_vols[arm] <= vols[arm]+1e-12:
                    options.append((trial_gap,symbol,proposal,trial,trial_fills,trial_notes,trial_vols))
            if not options:
                result['status']='UNQUALIFIED_NO_ONE_LOT_IMPROVEMENT'
                break
            new_gap,symbol,proposal,current,fills,notes,vols = min(options,key=lambda x:(x[0],x[1]))
            result['adjustments'].append(dict(arm=arm,symbol=symbol,before=target[arm][symbol],
                                               after=proposal[arm][symbol],gap_before=gap,gap_after=new_gap))
            target=proposal;gap=new_gap
        else:
            result['status']='UNQUALIFIED_ITERATION_LIMIT'
        if gap <= TOLERANCE:
            result.update(status='MATCHED' if result['adjustments'] else 'MATCHED_UNCHANGED',qualified=True)
        result.update(states=current,fills=fills,notes=notes,volatility=vols,gap=gap)
        for arm in f.ARMS:
            for symbol in symbols:
                old=baseline[arm]['positions'][symbol]['quantity'];new=current[arm]['positions'][symbol]['quantity']
                if old*new < 0 or abs(new)>abs(old)+1e-9:
                    raise ValueError('repair_increased_quantity')
        return result
    except (ValueError,KeyError,TypeError,OverflowError) as error:
        result.update(status='INVALID_INPUT',qualified=False,states=original,fills=[],gap=None,
                      reason=str(error),adjustments=[])
        return result
