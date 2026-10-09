"""Trusted runtime bindings. Missing economic policies/gates remain explicit DENY.

No health/config authorization flags and no automatic grants are consulted.
These manifests describe CURRENT implementation, not invented economic limits.
"""
from decimal import ROUND_FLOOR
import pathlib
import hashlib
import math

from octobot.ai_strategy_lab import paper_authorization as auth
from octobot.ai_strategy_lab import v13_exposure


def increases(state, quotes, weights, equity):
    """Same quantity semantics as P0-02; uncertainty is never a reduction."""
    try:
        for symbol, weight in weights.items():
            if weight == 0:
                continue
            q = quotes[symbol]
            target = equity * weight / q['mark_price']
            quantity = math.copysign(v13_exposure.rounded(abs(target), q['step'], ROUND_FLOOR), target)
            old = state['positions'].get(symbol, {}).get('quantity', 0.)
            if quantity != old and not v13_exposure.reduced(old, quantity):
                return True
        return False
    except (ValueError, TypeError, KeyError, ArithmeticError):
        return True


def binding(account, *, context_paths=()):
    here = pathlib.Path(__file__).parent
    lineage = {}
    for path in [here/'v13_paper_v2.py', here/'diversified_manual_paper_v1.py', *map(pathlib.Path, context_paths)]:
        lineage[str(path)] = hashlib.sha256(path.read_bytes()).hexdigest()
    policy = dict(per_asset_exposure=.315 if account == 'v13-paper-v2' else None,
        gross_exposure=.90 if account == 'v13-paper-v2' else None,
        daily_loss=None, drawdown=None, order_frequency=None, cooldown=None,
        implementation={name: hashlib.sha256((here/name).read_bytes()).hexdigest()
            for name in ('v13_exposure.py', 'v13_market.py', 'v13_market_sanity.py', 'paper_authorization.py')},
        missing_gates=['P0-01 V13 decision adapter'] if account == 'v13-paper-v2' else ['complete P0-01/02/03 execution adapter'])
    identity = auth.Identity(account=account, strategy=account, lineage_hash=auth.digest(lineage),
        risk_policy='paper-risk-policy-incomplete-v1', risk_policy_hash=auth.digest(policy),
        authorization_id='unconfigured')
    return identity, policy


def entry_scope(account, entry_id, *, context_paths=()):
    try:
        identity, policy = binding(account, context_paths=context_paths)
    except (OSError, ValueError) as exc:
        raise auth.Denied('authorization_storage_failure', detail=str(exc)) from exc
    # DailyTradingMode already consumes P0-01 inside the leased callback.
    if account == 'local-guarded-paper':
        return auth.Registry().global_entry(identity, entry_id, policy)
    # Missing wiring to an exact P0-01 durable decision is not manufactured.
    return auth.Registry().entry(identity, entry_id, policy, decision_claim=None)


def unsupported_execution(account):
    """Legacy mirrors lack a causal book/complete policy; no fabricated close."""
    with entry_scope(account, 'unsupported-execution'):
        raise auth.Denied('execution_policy_incomplete')
