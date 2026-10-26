"""One-shot read-only M1 checkout; never writes a ledger or executes trades."""
import argparse
import datetime as dt
import hashlib
import json
import os
from pathlib import Path


def timestamp(value):
    result = dt.datetime.fromisoformat(value)
    if result.tzinfo is None:
        raise ValueError('timezone_required')
    return result


def management_projection(value):
    """The stored producer projection precedes the web availability envelope."""
    if value.get('scope') != 'M1_WEEKLY_MANAGEMENT_STATUS_V1':
        raise ValueError('management_projection_scope')
    return dict(value, available=value.get('available', True))


def evaluate(account, management, expected, now):
    slot = timestamp(expected['slot'])
    due = now >= slot + dt.timedelta(seconds=120)
    issues = []
    for name, value in (('account', account), ('management', management)):
        if value.get('available') is not True:
            issues.append(name + '_unavailable')
        age = (now - timestamp(value['generated_at'])).total_seconds()
        if not 0 <= age <= 180:
            issues.append(name + '_stale_or_future')
    control = account['control']
    if account['health']['status'] != 'OBSERVING':
        issues.append('runner_unhealthy')
    if control.get('baseline_error'):
        issues.append('baseline_error')
    if management.get('orders_authorized') is not False:
        issues.append('real_order_boundary')
    if management.get('account') != expected['account'] or not management.get('active'):
        issues.append('account_identity_or_inactive')
    if account.get('variant', {}).get('account_id') != expected['account']:
        issues.append('account_projection_identity')
    automatic = management['automatic_review']
    if automatic.get('enabled') is not True or automatic.get('delegation_id') != expected['delegation_id']:
        issues.append('automatic_delegation')
    if automatic.get('input_status') or management.get('successor_input_status'):
        issues.append('automatic_or_successor_inputs_blocked')
    policy = management['policy']
    if policy['short_caps'] != expected['short_caps']:
        issues.append('short_budget_changed')
    for symbol, ceiling in expected['legacy_quantity_ceilings'].items():
        value = policy['quantity_ceilings'].get(symbol)
        if type(value) not in (int, float) or not 0 <= value <= ceiling + 1e-10:
            issues.append('legacy_ceiling_restored:' + symbol)
    if timestamp(policy['valid_until']) <= now:
        issues.append('policy_expired')
    rows = account['daily_slots']
    previous = next((r for r in rows if r['slot'] == expected['prior_denied_slot']), None)
    if not previous or previous['status'] != 'DENIED':
        issues.append('prior_denied_evidence_missing')
    row = next((r for r in rows if r['slot'] == expected['slot']), None)
    if due:
        if control.get('baseline_day') != (slot.date() - dt.timedelta(days=1)).isoformat():
            issues.append('daily_science_not_current')
        if not row:
            issues.append('daily_slot_missing')
        elif row['status'] not in ('FILLED', 'NO_FILL'):
            # An overlay/risk hold can be legitimate, but is never reported as
            # a successful ordinary execution by this checkout.
            issues.append('daily_slot_requires_review:' + row['status'])
    return dict(scope='READ_ONLY_OPERATIONAL_CHECK_NOT_STRATEGY_ACCEPTANCE',
                checked_at=now.isoformat(), expected_slot=expected['slot'],
                status='REVIEW_REQUIRED' if issues else 'PASS' if due else 'READY_WAITING_SLOT',
                issues=issues, daily_status=row['status'] if row else None,
                baseline_day=control.get('baseline_day'), phase=control['phase'],
                short_budget=sum(expected['short_caps'].values()),
                orders_authorized=False, mutations_performed=False)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--config', required=True)
    args = parser.parse_args()
    config_path = Path(args.config)
    stat = config_path.lstat()
    if config_path.is_symlink() or stat.st_uid != 0 or stat.st_mode & 0o022:
        raise ValueError('untrusted_checkout_config')
    config = json.loads(config_path.read_text())
    authority = Path(config['authority'])
    stat = authority.lstat()
    if authority.is_symlink() or stat.st_uid != 0 or stat.st_mode & 0o022:
        raise ValueError('untrusted_delegation')
    if hashlib.sha256(authority.read_bytes()).hexdigest() != config['authority_sha256']:
        raise ValueError('delegation_changed')
    delegation = json.loads(authority.read_text())
    expected = config['expected']
    if any(delegation[k] != expected[k] for k in ('account', 'delegation_id', 'short_caps')):
        raise ValueError('checkout_authority_scope')
    now = dt.datetime.now(dt.timezone.utc)
    try:
        account = json.loads(Path(config['account_projection']).read_text())
        management = management_projection(json.loads(Path(config['management_projection']).read_text()))
        # Capture validation time after both atomic producer files have been
        # read, so a concurrent publication cannot appear to be in the future.
        now = dt.datetime.now(dt.timezone.utc)
        result = evaluate(account, management, expected, now)
    except (OSError, ValueError, KeyError, TypeError) as error:
        result = dict(status='REVIEW_REQUIRED', checked_at=now.isoformat(),
                      issues=['projection_read_or_contract_error:' + type(error).__name__],
                      mutations_performed=False)
    target = Path(config['output'])
    temporary = target.with_suffix('.tmp')
    with temporary.open('x') as stream:
        os.chmod(temporary, 0o640)
        json.dump(result, stream, indent=2, allow_nan=False)
        stream.write('\n')
        stream.flush()
        os.fsync(stream.fileno())
    temporary.replace(target)
    print(json.dumps(result, allow_nan=False))
    return 1 if result['status'] == 'REVIEW_REQUIRED' else 0


if __name__ == '__main__':
    raise SystemExit(main())
