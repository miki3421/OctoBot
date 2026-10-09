"""Unified offline fixture runner. No real data, service, issuer or grants.

Derivation happens under the same SQLite write transaction as account commit.
A failed decision or funding check commits neither selector nor portfolio.
"""
import copy
import datetime as dt

# Direct CLI must use this checkout, never an unrelated installed OctoBot.
if not __package__:
    import sys
    from pathlib import Path
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
try:
    from . import v13_dynamic_universe as selector
    from . import v13_dynamic_comparison as accounting
except ImportError:
    import v13_dynamic_universe as selector
    import v13_dynamic_comparison as accounting

SCOPE='SYNTHETIC_ABC_RUNNER_V1'


def derive(bars, *, slot, start, lineage, previous=None):
    """Shared pure derivation; gives no execution authority to input data."""
    decision=selector.decide(bars,slot=slot,start=start,lineage=lineage,
                             previous=previous,expected_previous_id=previous['decision_id'] if previous else None)
    import numpy as np
    due=selector.timestamp(slot)
    dates=[(due.date()-dt.timedelta(days=d)).isoformat() for d in range(121,0,-1)]
    closes=np.array([[next(b['close'] for b in bars[s] if b['day']==day) for s in selector.UNIVERSE] for day in dates],dtype=float)
    returns=closes[1:]/closes[:-1]-1
    covariance=np.cov(returns[-60:],rowvar=False,ddof=1)*365.
    return dict(decision_at=slot,selection=decision,covariance=covariance.tolist(),
                targets=accounting.build_targets(decision,covariance))


def prepare(state, request):
    if request.get('scope')!=SCOPE:
        raise ValueError('synthetic_runner_only')
    start=request['start'];lineage=request['lineage']
    selector.slot_index(start,start)
    origin=selector.timestamp(start)
    tick=copy.deepcopy(request['tick'])
    if tick['id']!=request['id'] or tick['scope']!=accounting.SCOPE:
        raise ValueError('tick_binding')
    # Target/selection injection would bypass causal derivation.
    if any(k in tick for k in ('targets','selection','covariance','decision_at','protective_only')):
        raise ValueError('derived_fields_supplied')
    at=selector.timestamp(tick['at'])
    if at<origin:raise ValueError('before_start')
    previous=state['selection']
    if previous and (previous['start']!=start or previous['lineage']!=lineage):
        raise ValueError('runner_identity_changed')
    elapsed=(at.date()-origin.date()).days
    due=origin+dt.timedelta(days=elapsed)
    scheduled=elapsed%7==0 and at>due
    already_decided=previous and selector.timestamp(previous['slot'])==due
    if previous is None and (elapsed!=0 or not scheduled):
        raise ValueError('initial_slot_missing')
    if scheduled and not already_decided:
        tick.update(derive(request['bars'],slot=due.isoformat(),start=start,
                           lineage=lineage,previous=previous))
    return tick


def run_tick(store, request):
    if request.get('scope')!=SCOPE:raise ValueError('synthetic_runner_only')
    return store.commit(request,prepare=prepare)


def run_file(input_path, output_path, *, create=False):
    """Explicit fixture CLI; no operational store discovery or initialization."""
    import json
    requests=json.loads(input_path.read_text())
    if not isinstance(requests,list) or not requests:raise ValueError('fixture_sequence_required')
    store=accounting.FixtureStore(output_path,create=create)
    try:
        last=None
        for request in requests:last=run_tick(store,request)
        return dict(scope=SCOPE,ticks=len(requests),last_at=last[0]['last_at'],
                    equity={a:last[0]['arms'][a]['equity'] for a in accounting.ARMS},
                    performance_evidence=False,orders_authorized=False,paper_orders_authorized=False)
    finally:store.close()


if __name__=='__main__':
    import argparse
    import json
    from pathlib import Path
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--fixture',required=True,type=Path)
    parser.add_argument('--store',required=True,type=Path)
    parser.add_argument('--create',action='store_true')
    args=parser.parse_args()
    print(json.dumps(run_file(args.fixture,args.store,create=args.create),sort_keys=True))
