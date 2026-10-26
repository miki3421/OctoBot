"""Future checkout must distinguish waiting, completion and gated execution."""
import datetime as dt
import importlib.util
from pathlib import Path
import unittest

spec = importlib.util.spec_from_file_location('checkout', Path(__file__).resolve().parents[3] / 'scripts/check_m1_daily_slot.py')
c = importlib.util.module_from_spec(spec)
spec.loader.exec_module(c)
NOW = dt.datetime(2026, 10, 27, 0, 25, tzinfo=dt.timezone.utc)
SLOT = '2026-10-27T00:15:00+00:00'
PRIOR = '2026-10-26T00:15:00+00:00'


class CheckoutTests(unittest.TestCase):
    def setUp(self):
        self.expected = dict(slot=SLOT, prior_denied_slot=PRIOR, account='m1',
                             delegation_id='trusted', short_caps={'BTC': .08},
                             legacy_quantity_ceilings={'BTC': .002})
        self.account = dict(available=True, generated_at=NOW.isoformat(), health={'status': 'OBSERVING'},
                            variant={'account_id': 'm1'},
                            control=dict(baseline_day='2026-10-26', baseline_error=None, phase='NORMAL'),
                            daily_slots=[dict(slot=SLOT, status='FILLED'), dict(slot=PRIOR, status='DENIED')])
        self.management = dict(available=True, generated_at=NOW.isoformat(), active=True,
                               account='m1', orders_authorized=False,
                               automatic_review=dict(enabled=True, delegation_id='trusted', input_status=None),
                               policy=dict(short_caps={'BTC': .08}, quantity_ceilings={'BTC': .002},
                                           valid_until='2026-11-02T00:00:00+00:00'))

    def result(self):
        return c.evaluate(self.account, self.management, self.expected, NOW)

    def test_completed_slot_and_retained_denial_pass(self):
        self.assertEqual(self.result()['status'], 'PASS')

    def test_no_fill_is_distinct_completed_outcome(self):
        self.account['daily_slots'][0]['status'] = 'NO_FILL'
        self.assertEqual(self.result()['daily_status'], 'NO_FILL')
        self.assertEqual(self.result()['status'], 'PASS')

    def test_future_slot_is_waiting_not_executed(self):
        early = NOW - dt.timedelta(days=1)
        self.account['generated_at'] = self.management['generated_at'] = early.isoformat()
        self.account['daily_slots'] = self.account['daily_slots'][1:]
        self.account['control']['baseline_day'] = '2026-10-25'
        self.assertEqual(c.evaluate(self.account, self.management, self.expected, early)['status'], 'READY_WAITING_SLOT')

    def test_missing_and_denied_and_overlay_hold_are_not_pass(self):
        for status in ('DENIED', 'MISSED', 'OVERLAY_HOLD', 'PENDING'):
            self.account['daily_slots'][0]['status'] = status
            self.assertEqual(self.result()['status'], 'REVIEW_REQUIRED')
        self.account['daily_slots'] = self.account['daily_slots'][1:]
        self.assertIn('daily_slot_missing', self.result()['issues'])

    def test_stale_or_future_projection_fails(self):
        for seconds in (-181, 1):
            self.account['generated_at'] = (NOW + dt.timedelta(seconds=seconds)).isoformat()
            self.assertIn('account_stale_or_future', self.result()['issues'])

    def test_changed_short_authority_or_legacy_ceiling_fails(self):
        self.management['policy']['short_caps']['BTC'] = .09
        self.assertIn('short_budget_changed', self.result()['issues'])
        self.management['policy']['quantity_ceilings']['BTC'] = .005
        self.assertIn('legacy_ceiling_restored:BTC', self.result()['issues'])

    def test_lower_ceiling_is_permitted(self):
        self.management['policy']['quantity_ceilings']['BTC'] = 0
        self.assertEqual(self.result()['status'], 'PASS')

    def test_old_science_or_blocked_baseline_requires_review(self):
        self.account['control']['baseline_day'] = '2026-10-25'
        self.assertIn('daily_science_not_current', self.result()['issues'])
        self.account['control']['baseline_error'] = 'daily_identity'
        self.assertIn('baseline_error', self.result()['issues'])

    def test_expired_or_wrong_account_and_delegation_fail(self):
        self.management['policy']['valid_until'] = NOW.isoformat()
        self.management['account'] = 'other'
        self.management['automatic_review']['delegation_id'] = 'ui-flag'
        self.assertTrue({'policy_expired', 'account_identity_or_inactive', 'automatic_delegation'} <= set(self.result()['issues']))

    def test_real_order_permission_or_deleted_denial_fails(self):
        self.management['orders_authorized'] = True
        self.account['daily_slots'] = self.account['daily_slots'][:1]
        self.assertTrue({'real_order_boundary', 'prior_denied_evidence_missing'} <= set(self.result()['issues']))

    def test_stored_management_contract_requires_scope_and_preserves_failure(self):
        self.assertTrue(c.management_projection(dict(scope='M1_WEEKLY_MANAGEMENT_STATUS_V1'))['available'])
        self.assertFalse(c.management_projection(dict(scope='M1_WEEKLY_MANAGEMENT_STATUS_V1', available=False))['available'])
        with self.assertRaises(ValueError):
            c.management_projection(dict(scope='other'))

    def test_other_account_projection_cannot_pass_with_correct_management(self):
        self.account['variant']['account_id'] = 'another-account'
        self.assertIn('account_projection_identity', self.result()['issues'])


if __name__ == '__main__':
    unittest.main()
