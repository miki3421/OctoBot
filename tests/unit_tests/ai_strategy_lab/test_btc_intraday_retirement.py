"""Offline retirement fixtures: no real account, receipt or runtime mutation."""
import copy
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import sys
import tempfile
import types
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / 'octobot/ai_strategy_lab'))
import btc_intraday_retirement as archive


def load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


view = load('retirement_view', ROOT/'octobot/ai_strategy_lab/btc_intraday_view.py')
monitor = load('monitor', ROOT/'scripts/lab_resource_monitor.py')
with patch.dict(sys.modules, monitor=monitor):
    wrapper = load('retirement_monitor', ROOT/'scripts/lab_resource_monitor_retirement.py')


@unittest.skipUnless(os.getuid() == 0, 'root-owned receipt custody tests')
class RetirementTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        (self.root/'intraday-ui').mkdir()
        (self.root/'intraday-retirement').mkdir()
        self.path = self.root/'intraday-ui/account.json'
        self.receipt = self.root/'intraday-retirement/receipt.json'
        self.now = 1_800_000_000_000_000_000
        self.value = dict(schema=1, account=archive.ACCOUNT,
            scope='SYNTHETIC_RESEARCH_PAPER_NOT_KUCOIN_ORDER_ADMISSIBILITY', no_real_orders=True,
            checked_at_ns=self.now-86400*10**9, accounting_complete=True,
            metrics=dict(equity=9999.0), state=dict(q=0.0, pending=None),
            stress=dict(q=0.0, equity=9998.0, accounting_complete=True))
        self.record = dict(schema=1, scope=archive.SCOPE, account=archive.ACCOUNT,
            container=archive.CONTAINER, retired=True, real_orders=False,
            operator_reference='Synthetic author fixture only',
            both_scenarios_flat=True, both_scenarios_no_pending=True, retired_at_ns=self.now-10**9)
        self.write()

    def write(self):
        raw = json.dumps(self.value).encode()
        self.path.write_bytes(raw)
        self.record['projection_sha256'] = hashlib.sha256(raw).hexdigest()
        self.receipt.write_text(json.dumps(self.record))
        self.receipt.chmod(0o444)

    def validate(self):
        return archive.read(self.receipt, self.path, now_ns=self.now, projection_uid=0)

    def test_old_but_bound_flat_archive_is_valid_without_refreshing_timestamp(self):
        self.assertEqual(self.validate()['status'], 'RETIRED')
        with patch.dict(sys.modules, {'octobot.ai_strategy_lab.btc_intraday_retirement':archive}):
            value = view.public(self.path, self.now)
        self.assertTrue(value['retired'])
        self.assertFalse(value['stale'])
        self.assertEqual(value['age_seconds'], 86400)
        self.assertEqual(value['checked_at_ns'], self.value['checked_at_ns'])

    def test_without_receipt_old_projection_is_stale(self):
        self.receipt.unlink()
        self.assertTrue(view.public(self.path, self.now)['stale'])

    def test_content_change_cannot_hide_behind_retired_status(self):
        self.path.write_text(json.dumps(dict(self.value, metrics=dict(equity=10001))))
        with self.assertRaises(ValueError):
            self.validate()

    def test_position_pending_or_unsettled_scenario_rejected_even_with_matching_hash(self):
        baseline = copy.deepcopy(self.value)
        for change in ('primary', 'stress', 'pending', 'funding'):
            self.value = copy.deepcopy(baseline)
            if change == 'primary':self.value['state']['q'] = -.01
            elif change == 'stress':self.value['stress']['q'] = -.01
            elif change == 'pending':self.value['state']['pending'] = {'kind':'ENTRY'}
            else:self.value['stress']['accounting_complete'] = False
            self.write()
            with self.subTest(change=change), self.assertRaises(ValueError):self.validate()

    def test_other_account_future_or_false_retirement_rejected(self):
        baseline = copy.deepcopy(self.record)
        for key, value in [('account','m1'), ('container','other'), ('retired',False),
                           ('real_orders',True), ('retired_at_ns',self.now+1), ('both_scenarios_no_pending',False), ('operator_reference','')]:
            self.record = copy.deepcopy(baseline)
            self.record[key] = value
            self.write()
            with self.subTest(field=key), self.assertRaises(ValueError):self.validate()

    def test_untrusted_owner_parent_or_symlink_rejected(self):
        os.chown(self.receipt, 30943, 30910)
        with self.assertRaises(ValueError):self.validate()
        os.chown(self.receipt, 0, 0)
        self.receipt.parent.chmod(0o777)
        with self.assertRaises(ValueError):self.validate()
        self.receipt.parent.chmod(0o700)
        target = self.receipt.with_suffix('.preserved')
        self.receipt.rename(target)
        self.receipt.symlink_to(target)
        with self.assertRaises(OSError):self.validate()

    def test_monitor_expected_stop_has_no_alert_but_restart_or_unknown_state_does(self):
        item=dict(receipt=str(self.receipt),path=str(self.path),uid=0)
        for state in ('exited','running','restarting','created'):
            result=wrapper.retired_account(item,now_ns=self.now,inspect=lambda _:dict(containers=[dict(state=state)]))
            self.assertEqual(result['status']=='retired',state=='exited')
            self.assertEqual(bool(result['issues']),state!='exited')
        self.path.write_text('{}')
        self.assertTrue(wrapper.retired_account(item,now_ns=self.now,inspect=lambda _:dict(containers=[dict(state='exited')]))['issues'])

    def test_existing_monitor_still_keeps_other_accounts_and_collectors(self):
        config=dict(containers=['octobot-market-observer'],paper_accounts={'m1':{}},retired_accounts={'intraday':{}})
        sample=dict(paper_accounts={'m1':dict(status='healthy',issues=[])},containers=[dict(name='octobot-market-observer')])
        with patch.object(wrapper,'original_collect',return_value=sample), patch.object(wrapper,'retired_account',return_value=dict(status='retired',issues=[])):
            result=wrapper.collect(config)
        self.assertEqual(result['paper_accounts']['m1']['status'],'healthy')
        self.assertEqual(result['containers'][0]['name'],'octobot-market-observer')
        config['containers'].append(archive.CONTAINER)
        with patch.object(wrapper,'original_collect',return_value=sample),self.assertRaises(ValueError):wrapper.collect(config)


if __name__ == '__main__':
    unittest.main()
