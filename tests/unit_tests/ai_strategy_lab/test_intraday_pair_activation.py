"""Offline fixtures: public read boundary, fanout faults and live projection."""
import copy
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[3]
LAB = ROOT/'octobot/ai_strategy_lab'
sys.path.insert(0, str(LAB))
import btc_intraday_pair_live as live
import btc_intraday_pair_view as view
from intraday_pair.runner import Pair
from test_intraday_pair_runner import Clock, NS
spec = importlib.util.spec_from_file_location('pair_monitor', ROOT/'scripts/lab_resource_monitor.py')
monitor = importlib.util.module_from_spec(spec)
spec.loader.exec_module(monitor)


class ActivationTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.clock = Clock()
        self.pair = Pair(Path(self.tmp.name)/'state', 86400*NS, 'fixture', initialize=True,
                         clock=self.clock, synthetic=True)
        self.addCleanup(self.pair.close)
        self.path = Path(self.tmp.name)/'public.json'
        self.value = live.projection(self.pair)
        # Fixtures substitute authority only, never real-state files.
        self.value.update(mode='AUTHORIZED_RESEARCH_PAPER_PAIR', active_account=True)
        for a in self.value['arms'].values():
            a.update(last_market_ns=self.clock.t, last_book_ns=self.clock.t)
        self.config = dict(path=str(self.path), uid=os.getuid(), heartbeat_warn_after_seconds=30,
                           market_warn_after_seconds=120, book_warn_after_seconds=30)
        self.write()

    def write(self):
        self.path.write_text(json.dumps(self.value))
        self.path.chmod(0o640)

    def read(self, now=None):
        return view.public(self.path, now_ns=self.clock.t if now is None else now, uid=os.getuid())

    def observe(self, now=None):
        return monitor.read_intraday_pair(self.config, now=self.clock.t/NS if now is None else now)

    def test_projection_preserves_real_equity_and_empty_history(self):
        v = self.read()
        self.assertEqual(v['phase'], 'PRESTART')
        self.assertEqual(len(v['arms']), 4)
        for a in v['arms'].values():
            self.assertEqual((a['equity'], a['q'], a['fills']), (10000, 0, 0))
            self.assertEqual(a['points'], [])
            self.assertEqual(a['trades'], [])
        self.assertEqual(self.observe()['issues'], [])

    def test_prestart_and_warmup_are_healthy_but_data_loss_is_not(self):
        for phase in ('PRESTART', 'WARMUP'):
            self.value['phase'] = phase
            self.write()
            self.assertEqual(self.observe()['issues'], [])
        self.value['arms']['candidate-primary']['last_book_ns'] = None
        self.write()
        self.assertIn('PAPER_ACCOUNT_STALE:intraday-pair-candidate-primary', self.observe()['issues'])

    def test_cursor_and_hash_disagreement_are_detected(self):
        for key, value in [('cursor', 1), ('input_sha', 'f'*64)]:
            old = self.value['arms']['candidate-primary'][key]
            self.value['arms']['candidate-primary'][key] = value
            self.write()
            self.assertIn('PAPER_ACCOUNT_BLOCKED:intraday-pair-candidate-primary', self.observe()['issues'])
            self.value['arms']['candidate-primary'][key] = old

    def test_incomplete_funding_and_integrity_halt_alert(self):
        for key, val in [('complete', False), ('integrity_halt', True)]:
            old = self.value['arms']['control-stress'][key]
            self.value['arms']['control-stress'][key] = val
            self.write()
            self.assertTrue(self.observe()['issues'])
            self.value['arms']['control-stress'][key] = old

    def test_future_heartbeat_and_read_clock_regression_rejected(self):
        with self.assertRaises(ValueError):
            self.read(self.clock.t-1)
        with patch.object(view.time, 'time_ns', side_effect=[self.clock.t+1, self.clock.t]):
            with self.assertRaises(ValueError):
                view.public(self.path, uid=os.getuid())

    def test_atomic_publication_during_monitor_read_is_accepted(self):
        with patch.object(view.time, 'time_ns', side_effect=[self.clock.t-NS, self.clock.t+NS]):
            self.assertFalse(view.public(self.path, uid=os.getuid())['stale'])

    def test_stale_and_blocked_have_actionable_existing_email_ids(self):
        self.assertIn('PAPER_ACCOUNT_STALE:intraday-pair', self.observe(now=self.clock.t/NS+31)['issues'])
        self.value = dict(schema=1, scope=view.SCOPE, no_real_orders=True,
                          checked_at_ns=self.clock.t, phase='BLOCKED', error_code='ValueError')
        self.write()
        self.assertIn('PAPER_ACCOUNT_BLOCKED:intraday-pair', self.observe()['issues'])

    def test_identity_nonfinite_permissions_duplicate_keys_and_symlink_rejected(self):
        original = copy.deepcopy(self.value)
        for mutate in [lambda v: v.update(protocol_sha='f'*64),
                       lambda v: v.update(real_min_notional=0),
                       lambda v: v['arms']['candidate-primary'].update(equity=float('nan')),
                       lambda v: v['arms']['control-primary'].update(account='legacy')]:
            self.value = copy.deepcopy(original); mutate(self.value); self.write()
            with self.assertRaises(ValueError): self.read()
        self.value = original; self.write(); self.path.chmod(0o666)
        self.assertEqual(self.observe()['status'], 'unavailable')
        self.write(); self.path.write_text(self.path.read_text()[:-1]+',"schema":1}')
        with self.assertRaises(ValueError): self.read()
        self.write(); target=self.path.with_suffix('.target'); self.path.rename(target);self.path.symlink_to(target)
        with self.assertRaises(OSError): self.read()

    def test_live_wrapper_requires_own_exact_hash_and_separate_projection(self):
        out=Path(self.tmp.name)/'publish';out.mkdir(mode=0o750)
        c=dict(directory=str(self.pair.path),source=str(Path(self.tmp.name)/'source'),
               book=str(Path(self.tmp.name)/'book/data.sqlite'),projection=str(out/'comparison.json'))
        approval=dict(live_wrapper_sha256=hashlib.sha256(Path(live.__file__).read_bytes()).hexdigest())
        with patch.object(live, 'authority', return_value=approval):
            self.assertEqual(live.authorized(c), approval)
            c['projection']=str(self.pair.path/'leak.json')
            with self.assertRaises(ValueError): live.authorized(c)
        with patch.object(live, 'authority', return_value={}):
            with self.assertRaises(ValueError): live.authorized(c)

    def test_ui_routes_have_existing_profile_and_login_guards(self):
        import ast
        tree=ast.parse((ROOT/'packages/tentacles/Services/Interfaces/web_interface/controllers/home.py').read_text())
        register=next(n for n in tree.body if isinstance(n,ast.FunctionDef) and n.name=='register')
        for name in ('btc_intraday_pair_dashboard','btc_intraday_pair_data'):
            f=next(n for n in register.body if isinstance(n,ast.FunctionDef) and n.name==name)
            text=ast.unparse(f)
            self.assertIn('login.login_required_when_activated',text)
            self.assertIn('local_ai_trading',text)
            self.assertIn('accepted_terms',text)
            self.assertNotIn('methods=',text)


if __name__ == '__main__':
    unittest.main()
