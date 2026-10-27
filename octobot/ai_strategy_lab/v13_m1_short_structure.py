"""Inactive causal recovery hypothesis. No account, network or order interface.

The separately frozen structural rule replaces only signal invalidation.
The parent loss/profit protections, quantities and six-hour deadline survive.
"""
import copy
import importlib.util
import math
from pathlib import Path

_spec = importlib.util.spec_from_file_location(
    '_structure_parent', Path(__file__).with_name('v13_m1_short_risk.py'))
R = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(R)

VERSION = 'm1-short-structural-invalidation-v1'
PROTOCOL_ID = 'b4474ccad3bb59d91f107674c3fb768b6b141fc2cdc88e7af76bbe6bf9cb7814'


def validate(policy):
    if (policy.get('protocol_id') != PROTOCOL_ID or
            R.digest({k: v for k, v in policy.items() if k != 'protocol_id'}) != PROTOCOL_ID):
        raise ValueError('structural_policy_identity')
    return policy


def ema(prices, periods):
    alpha = 2.0 / (periods + 1)
    values = [prices[0]]
    for price in prices[1:]:
        values.append(alpha * price + (1 - alpha) * values[-1])
    return values


def features(policy, rows, slot):
    """Use only a complete, validated 24h panel ending at this closed slot."""
    validate(policy)
    model = R.model(rows, slot)
    rule = policy['rule']
    per_symbol = {}
    for symbol in R.SIGNALS:
        prices = [row['prices'][symbol] for row in rows]
        slow = ema(prices, rule['ema_slow_periods'])
        hourly = prices[-1] / prices[-13] - 1
        per_symbol[symbol] = dict(
            above_slow=prices[-1] > slow[-1],
            rising_slow=slow[-1] > slow[-1-rule['slope_lag_periods']],
            positive_60m=hourly > 0)
        if symbol == 'BTCUSDT':
            fast = ema(prices, rule['ema_fast_periods'])[-1]
            gap = fast / slow[-1] - 1
    returns = model['returns']['BTCUSDT']
    mean = math.fsum(returns) / len(returns)
    sigma = math.sqrt(math.fsum((v-mean)**2 for v in returns) / (len(returns)-1) * 12)
    buffer = max(rule['btc_fast_over_slow_minimum_gap'],
                 rule['btc_fast_over_slow_sigma_multiple'] * sigma)
    recovering = sorted(s for s, checks in per_symbol.items() if all(checks.values()))
    btc = per_symbol['BTCUSDT']
    checks = dict(btc_above_slow=btc['above_slow'], btc_rising_slow=btc['rising_slow'],
                  btc_fast_slow_gap=gap >= buffer,
                  btc_nonnegative_60m=model['feature']['btc_60m'] >= 0,
                  broad_recovery=len(recovering) >= rule['market_confirmation']['minimum_symbols'])
    value = dict(protocol_id=PROTOCOL_ID, slot=slot, input_hash=model['input_hash'],
                 btc_60m=model['feature']['btc_60m'], btc_sigma_1h=sigma,
                 btc_fast_slow_gap=gap, required_gap=buffer,
                 recovering_symbols=recovering, checks=checks,
                 qualifies=all(checks.values()))
    value['feature_id'] = R.digest(value)
    return value


def watch(parent_protocol, policy, saved, positions, quotes, *, at, market_id,
          feature_slot=None, feature=None):
    """Persisted distinct-slot confirmation; the parent protections take priority.

    A feature absence resets the structural confirmation. It never disables
    executable loss/profit protection. A missing book remains the parent's veto.
    """
    validate(policy)
    if saved.get('structural_policy_id', PROTOCOL_ID) != PROTOCOL_ID:
        raise ValueError('episode_structural_policy')
    duplicate = at == saved['last_at'] and market_id == saved['last_market']
    episode, reason = R.watch(parent_protocol, saved, positions, quotes,
                              at=at, market_id=market_id)
    if reason or duplicate:
        return episode, reason
    episode.setdefault('structural_policy_id', PROTOCOL_ID)
    episode.setdefault('structure_count', 0)
    episode.setdefault('last_structure_slot', None)
    episode.setdefault('last_structure_feature', None)
    if feature_slot is None:
        episode['structure_count'] = 0
        episode['last_structure_slot'] = None
        episode['last_structure_feature'] = None
        return episode, None
    slot = R.number(feature_slot)
    if slot % 300 or not episode['at'] <= slot <= at or at-slot >= 300:
        raise ValueError('structural_feature_not_causal')
    previous = episode['last_structure_slot']
    if previous is not None and slot < previous:
        raise ValueError('structural_slot_regression')
    if feature is not None:
        if (feature.get('protocol_id') != PROTOCOL_ID or feature.get('slot') != slot or
                R.digest({k: v for k, v in feature.items() if k != 'feature_id'}) != feature.get('feature_id')):
            raise ValueError('structural_feature_identity')
    identity = feature['feature_id'] if feature is not None else None
    if previous == slot:
        if identity != episode['last_structure_feature']:
            raise ValueError('conflicting_structural_feature')
        return episode, None
    qualifies = feature is not None and feature['qualifies']
    consecutive = previous is not None and slot-previous == 300
    episode['structure_count'] = (episode['structure_count']+1 if consecutive else 1) if qualifies else 0
    episode['last_structure_slot'] = slot
    episode['last_structure_feature'] = identity
    if episode['structure_count'] >= policy['rule']['consecutive_distinct_slots']:
        reason = 'STRUCTURAL_REVERSAL'
        episode['exit_reason'] = reason
        episode['exit_decided_at'] = at
    return episode, reason
