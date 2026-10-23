"""Pure, OFFLINE target preview. Not imported by any runner or order interface.

Card work-card-026c44e2-f248-41ac-aa1f-da68db8f1e98. This is preparation,
not an approved or active maintenance policy. No persistence or grant API.
"""
import math


def preview(baseline, current, long_caps, short_budgets, phase='NORMAL'):
    """Illustrate caps and separate SHORT budgets in base-asset quantities.

    Caps apply only to selected existing symbols. Returned next_caps must be
    persisted transactionally in a future integration; this function does not
    do so. M1_ENTRY never ratchets a LONG cap from an overlay SHORT quantity.
    Other M1 symbols retain inversion of their current held LONG quantities.
    Risk, lot/depth/funding checks and episode/approval handling remain required.
    """
    if phase not in ('NORMAL', 'REENTRY', 'M1_ENTRY'):
        raise ValueError('unsupported_phase')
    universe = set(baseline)
    if not universe or set(current) != universe or not set(long_caps) <= universe or set(long_caps) != set(short_budgets):
        raise ValueError('universe_or_budget_scope')
    for mapping in (baseline, current, long_caps, short_budgets):
        if any(type(v) not in (int,float) or not math.isfinite(v) for v in mapping.values()):
            raise ValueError('finite_quantities_required')
    if any(v<0 for v in baseline.values()) or any(v<0 for v in long_caps.values()) or any(v<0 for v in short_budgets.values()):
        raise ValueError('negative_budget')
    if any(short_budgets[s]<long_caps[s] for s in long_caps):
        raise ValueError('short_budget_below_long_cap')
    caps = dict(long_caps)
    if phase == 'M1_ENTRY':
        targets = {s:-max(current[s],0) if current[s]>=0 else current[s] for s in universe}
        for s in caps:
            targets[s] = -min(short_budgets[s], baseline[s])
    else:
        targets = dict(baseline)
        for s in caps:
            # A lower ordinary target ratchets the ceiling down. It cannot
            # restore itself just because tomorrow's signal becomes larger.
            caps[s] = min(caps[s], baseline[s])
            targets[s] = caps[s]
    return dict(scope='OFFLINE_PREPARATION_ONLY', active=False, execution_authorized=False,
                phase=phase, targets=targets, next_long_caps=caps,
                short_budgets=dict(short_budgets), freed_risk_reallocated=False,
                requires_existing_risk_checks=True)
