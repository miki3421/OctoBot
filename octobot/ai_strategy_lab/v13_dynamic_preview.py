"""Offline real-receipt derivation; no store, fills, network or authorization.

Inputs must come from the custody-verifying readers in v13_dynamic_data.
Receipt labels alone are not authentication. This boundary never accepts a
caller-supplied funding-complete flag or upgrades real inputs into fixtures.
"""
import datetime as dt
try:
    from . import v13_dynamic_data as data
    from . import v13_dynamic_runner as runner
except ImportError:
    import v13_dynamic_data as data
    import v13_dynamic_runner as runner


def preview(records, *, slot, start, lineage, as_of, previous=None):
    cutoff=runner.selector.timestamp(slot)
    if cutoff>runner.selector.timestamp(as_of):
        raise ValueError('future_decision_slot')
    runner.selector.slot_index(slot,start)
    # Validate complete common coverage and conflicting observations first.
    panel=data.causal_panel(records,slot)
    dates=set(panel['dates'])
    chosen={s:{} for s in runner.selector.UNIVERSE}
    for r in records:
        if r['kind']!='daily' or r['symbol'] not in chosen or r['day'] not in dates:
            continue
        received=runner.selector.timestamp(r['received_at'])
        if received>cutoff:
            continue
        closed=dt.datetime.combine(dt.date.fromisoformat(r['day'])+dt.timedelta(days=1),dt.time(),dt.timezone.utc)
        if received<closed:
            raise ValueError('receipt_before_bar_close')
        digest=r.get('raw_sha256','')
        if len(digest)!=64 or any(c not in '0123456789abcdef' for c in digest):
            raise ValueError('receipt_hash_missing')
        old=chosen[r['symbol']].get(r['day'])
        # Stable choice if archives contain the same close more than once.
        if old is None or (received,digest)<(runner.selector.timestamp(old['received_at']),old['raw_sha256']):
            chosen[r['symbol']][r['day']]=r
    bars={s:[dict(day=d,close=r['close'],received_at=r['received_at'])
             for d,r in sorted(rows.items())] for s,rows in chosen.items()}
    derived=runner.derive(bars,slot=slot,start=start,lineage=lineage,previous=previous)
    provenance=sorted({r['raw_sha256'] for rows in chosen.values() for r in rows.values()})
    return dict(scope='REAL_RECEIPT_DERIVATION_PREVIEW_V1',derived=derived,
                source_hashes=provenance,source_set_sha256=runner.selector.digest(provenance),
                execution_ready=False,orders_authorized=False,paper_orders_authorized=False,
                blockers=['funding_forward_policy_unresolved','final_qualification_pending',
                          'comparison_activation_not_completed'],performance_evidence=False)
