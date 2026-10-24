"""Maintenance continuation must never bypass an active M1 episode or consent."""
import contextlib
import importlib.util
import io
import json
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import Mock, patch

SPEC = importlib.util.spec_from_file_location(
    'deferred_m1', Path(__file__).resolve().parents[3] / 'scripts/wait_m1_transition_deploy.py')
deploy = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(deploy)


class DeferredDeployTests(unittest.TestCase):
    def run_job(self, phase='ACTIVE', expiry='2099-01-01T00:00:00+00:00', check=False,
                governance_error=None, deploy_error=None, pending=None):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        root = Path(tmp.name)
        output = root / 'audit-evidence/m1-v2-ui-20261024'
        output.mkdir(parents=True)
        release = root / 'release'
        (release / 'configuration').mkdir(parents=True)
        (release / 'configuration/transition-proposal.json').write_text(json.dumps({'expires_at': expiry}))
        cp = Mock()
        cp.PROJECT = dict(work_board_url='board', active_coordination_session_url='active', coordination_sessions_url='sessions')
        cp.cp.return_value = {'cards': []}
        args = ['waiter', '--checkpoint-revision', '340', '--browser-image', 'sha256:local']
        if check:
            args.append('--check-only')
        controls = dict(phase=phase, pending=pending)
        with contextlib.ExitStack() as stack:
            stack.enter_context(patch.object(deploy, 'ROOT', root))
            stack.enter_context(patch.object(deploy, 'RELEASE', release))
            stack.enter_context(patch.object(deploy.sys, 'argv', args))
            stack.enter_context(patch.object(deploy, 'read_control', return_value=controls))
            stack.enter_context(patch.object(deploy.shutil, 'copyfile', side_effect=lambda _, dst: Path(dst).touch()))
            governance = stack.enter_context(patch.object(deploy, 'governance', return_value=cp, side_effect=governance_error))
            execute = stack.enter_context(patch.object(deploy.subprocess, 'run', side_effect=deploy_error))
            stack.enter_context(patch.object(deploy.time, 'sleep', side_effect=KeyboardInterrupt))
            stack.enter_context(patch.object(deploy.signal, 'signal'))
            stack.enter_context(patch.object(deploy, 'ui_target_alias', return_value=contextlib.nullcontext()))
            stack.enter_context(contextlib.redirect_stdout(io.StringIO()))
            error = None
            try:
                deploy.main()
            except (Exception, SystemExit) as caught:
                error = caught
        path = output / 'deferred-technical-deploy/status.json'
        return governance, execute, json.loads(path.read_text()) if path.exists() else None, error

    def test_check_only_is_read_only(self):
        governance, execute, state, error = self.run_job(check=True)
        governance.assert_not_called()
        execute.assert_not_called()
        self.assertIsNone(state)
        self.assertIsNone(error)

    def test_active_episode_never_stops_services(self):
        governance, execute, state, error = self.run_job()
        governance.assert_not_called()
        execute.assert_not_called()
        self.assertEqual(state['phase'], 'CANCELLED_NO_FURTHER_ACTION')
        self.assertFalse(state['rebalance_approved'])
        self.assertEqual(error.code, 130)

    def test_expired_window_never_deploys(self):
        governance, execute, state, error = self.run_job(expiry='2000-01-01T00:00:00+00:00')
        governance.assert_not_called()
        execute.assert_not_called()
        self.assertEqual(state['phase'], 'STOPPED_REVIEW_REQUIRED')
        self.assertIn('deadline', str(error))

    def test_pending_intent_blocks_even_normal_phase(self):
        governance, execute, state, _ = self.run_job(phase='NORMAL', pending={'kind': 'REENTRY'})
        governance.assert_not_called()
        execute.assert_not_called()
        self.assertEqual(state['phase'], 'CANCELLED_NO_FURTHER_ACTION')

    def test_changed_authority_never_deploys(self):
        _, execute, state, error = self.run_job(phase='NORMAL', governance_error=ValueError('checkpoint_changed'))
        execute.assert_not_called()
        self.assertEqual(state['phase'], 'STOPPED_REVIEW_REQUIRED')
        self.assertIn('checkpoint_changed', str(error))

    def test_failed_deploy_is_not_retried_or_followed_by_browser(self):
        governance, execute, state, error = self.run_job(
            phase='NORMAL', deploy_error=subprocess.CalledProcessError(1, 'installer'))
        governance.assert_called_once()
        execute.assert_called_once()
        command = execute.call_args.args[0]
        self.assertIn('--manual-operator-deploy', command)
        self.assertIn(deploy.SHA, command)
        self.assertIn('no rebalance approval', command[-1])
        self.assertEqual(state['phase'], 'STOPPED_REVIEW_REQUIRED')
        self.assertFalse(state['rebalance_approved'])
        self.assertIsInstance(error, subprocess.CalledProcessError)


class HostAssetCompatibilityTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.root=Path(self.tmp.name);self.target=self.root/'checkout';self.target.mkdir();self.alias=self.root/'workspace'

    def test_temporary_link_is_removed_on_success_or_failure(self):
        with deploy.ui_target_alias(self.alias,self.target):self.assertEqual(self.alias.resolve(),self.target)
        self.assertFalse(self.alias.is_symlink())
        with self.assertRaises(RuntimeError):
            with deploy.ui_target_alias(self.alias,self.target):raise RuntimeError('fixture deploy failed')
        self.assertFalse(self.alias.is_symlink())

    def test_existing_paths_are_not_replaced_or_removed(self):
        self.alias.mkdir()
        with self.assertRaises(ValueError):
            with deploy.ui_target_alias(self.alias,self.target):self.fail('must deny')
        self.assertTrue(self.alias.is_dir());self.alias.rmdir()
        other=self.root/'other';other.mkdir();self.alias.symlink_to(other)
        with self.assertRaises(ValueError):
            with deploy.ui_target_alias(self.alias,self.target):self.fail('must deny')
        self.assertEqual(self.alias.resolve(),other);self.alias.unlink()
        self.alias.symlink_to(self.target)
        with deploy.ui_target_alias(self.alias,self.target):self.assertTrue(self.alias.is_symlink())
        self.assertTrue(self.alias.is_symlink())


if __name__ == '__main__':
    unittest.main()
