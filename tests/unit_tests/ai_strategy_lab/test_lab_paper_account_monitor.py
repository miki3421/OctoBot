import datetime as dt
import importlib.util
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

spec=importlib.util.spec_from_file_location('monitor',Path(__file__).resolve().parents[3]/'scripts/lab_resource_monitor.py')
m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m)

class PaperAccountMonitorTests(unittest.TestCase):
    def test_missed_daily_not_hidden_by_healthy_process_or_recent_signal_slots(self):
        now=dt.datetime(2026,10,19,10,tzinfo=dt.timezone.utc);at=now.isoformat()
        v=dict(scope='AUTONOMOUS_M1_PAPER_RESEARCH_ONLY',arm='M1',health=dict(checked_at=at,status='OBSERVING'),
            activation=dict(first_signal_slot='2026-10-17T09:15:00+00:00'),variant=dict(observed_at=at,metrics=dict(equity=10000)),
            slots=[],daily_slots=[dict(kind='DAILY',slot='2026-10-19T00:15:00+00:00',status='MISSED')])
        with tempfile.TemporaryDirectory() as d:
            p=Path(d)/'account.json';p.write_text(json.dumps(v));p.chmod(0o640)
            c=dict(path=str(p),uid=os.getuid(),heartbeat_warn_after_seconds=180,valuation_warn_after_seconds=300)
            self.assertIn('PAPER_DAILY_NOT_EXECUTED:m1',m.read_paper_account('m1',c,now.timestamp())['issues'])
            v['daily_slots'][0]['status']='FILLED';p.write_text(json.dumps(v))
            self.assertFalse(m.read_paper_account('m1',c,now.timestamp())['issues'])
            self.assertIn('PAPER_ACCOUNT_STALE:m1',m.read_paper_account('m1',c,now.timestamp()+301)['issues'])
            self.assertIn('PAPER_ACCOUNT_UNAVAILABLE:m1',m.read_paper_account('m1',c,now.timestamp()-1)['issues'])

    def test_intraday_remembered_reason_does_not_hide_fresh_no_signal(self):
        now=1800000000
        v=dict(scope='SYNTHETIC_RESEARCH_PAPER_NOT_KUCOIN_ORDER_ADMISSIBILITY',checked_at_ns=now*10**9,
            accounting_complete=True,metrics=dict(equity=10000),slots=[dict(status='NO_SIGNAL')],
            state=dict(last_market_received=now*10**9,reason='PRICE_MISSING',integrity_halt=False,drawdown_halt=False))
        with tempfile.TemporaryDirectory() as d:
            p=Path(d)/'account.json';p.write_text(json.dumps(v));p.chmod(0o640)
            c=dict(path=str(p),uid=os.getuid(),heartbeat_warn_after_seconds=180,valuation_warn_after_seconds=300)
            self.assertFalse(m.read_paper_account('intraday',c,now)['issues'])
            v['accounting_complete']=False;p.write_text(json.dumps(v))
            self.assertIn('PAPER_ACCOUNT_BLOCKED:intraday',m.read_paper_account('intraday',c,now)['issues'])


class PaperAccountReadClockTests(unittest.TestCase):
    """Offline projection fixtures only; never hold a lock on a live journal."""
    T = 1800000000

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.path = Path(self.tmp.name) / 'account.json'
        self.config = dict(path=str(self.path), uid=os.getuid(),
                           heartbeat_warn_after_seconds=180, valuation_warn_after_seconds=300)
        self.value = dict(scope='SYNTHETIC_RESEARCH_PAPER_NOT_KUCOIN_ORDER_ADMISSIBILITY',
            checked_at_ns=(self.T+1)*10**9, accounting_complete=True,
            metrics=dict(equity=10000), slots=[dict(status='NO_SIGNAL')],
            state=dict(last_market_received=(self.T+1)*10**9,
                       integrity_halt=False, drawdown_halt=False))
        self.write()

    def write(self):
        self.path.write_text(json.dumps(self.value))
        self.path.chmod(0o640)

    def read(self, start=None, end=None):
        clock = [self.T if start is None else start, self.T+2 if end is None else end]
        with patch.object(m.time, 'time', side_effect=clock):
            return m.read_paper_account('intraday', self.config)

    def test_collect_accepts_publication_after_sample_start_before_read_end(self):
        mem = dict(MemTotal=1000, MemAvailable=500, SwapTotal=0, SwapFree=0)
        proc = {'/proc/uptime': '100 0', '/proc/sys/kernel/random/boot_id': 'boot',
                **{'/proc/pressure/'+kind: 'some avg10=0\nfull avg10=0'
                   for kind in ('cpu', 'memory', 'io')}}
        def text(path, *args, **kwargs):
            return proc[str(path)]
        # collect starts at T; an atomic publication at T+1 is read by T+2.
        with patch.object(m.time, 'time', side_effect=[self.T, self.T+.25, self.T+2]), \
                patch.object(m, 'counters', side_effect=[mem, dict(pswpin=0, pswpout=0)]), \
                patch.object(m.Path, 'read_text', text), \
                patch.object(m, 'inspect_containers', return_value=dict(containers=[])):
            sample = m.collect(dict(disks={}, collectors={}, containers=[],
                                    paper_accounts={'intraday': self.config}))
        result = sample['paper_accounts']['intraday']
        self.assertEqual(result['status'], 'healthy')
        self.assertEqual(result['issues'], [])
        self.assertEqual(result['heartbeat_age_seconds'], 1)
        self.assertLess(sample['observed_at'], result['validation_at'])
        self.assertEqual(result['validation_at'], result['read_completed_at'])

    def test_true_future_heartbeat_or_market_is_still_rejected(self):
        for field in ('heartbeat', 'market'):
            with self.subTest(field=field):
                self.value['checked_at_ns'] = (self.T+1)*10**9
                self.value['state']['last_market_received'] = (self.T+1)*10**9
                if field == 'heartbeat':
                    self.value['checked_at_ns'] = (self.T+3)*10**9
                else:
                    self.value['state']['last_market_received'] = (self.T+3)*10**9
                self.write()
                result = self.read()
                self.assertEqual(result['error_code'], 'TIMESTAMP_FUTURE')
                self.assertEqual(result['issues'], ['PAPER_ACCOUNT_UNAVAILABLE:intraday'])

    def test_clock_regression_during_read_fails_closed(self):
        result = self.read(start=self.T+2, end=self.T+1)
        self.assertEqual(result['error_code'], 'READ_CLOCK_REGRESSION')
        self.assertEqual(result['status'], 'unavailable')

    def test_freshness_uses_read_completion_without_extending_thresholds(self):
        self.value['checked_at_ns'] = self.T*10**9
        self.value['state']['last_market_received'] = self.T*10**9
        self.write()
        self.assertEqual(self.read(end=self.T+180)['issues'], [])
        result = self.read(end=self.T+181)
        self.assertEqual(result['issues'], ['PAPER_ACCOUNT_STALE:intraday'])
        self.value['checked_at_ns'] = (self.T+301)*10**9
        self.write()
        result = self.read(end=self.T+301)
        self.assertEqual(result['heartbeat_age_seconds'], 0)
        self.assertEqual(result['valuation_age_seconds'], 301)
        self.assertIn('PAPER_ACCOUNT_STALE:intraday', result['issues'])

    def test_untrusted_permissions_and_uid_still_alert_immediately(self):
        self.path.chmod(0o666)
        self.assertEqual(self.read()['error_code'], 'CUSTODY_INVALID')
        self.path.chmod(0o640)
        self.config['uid'] += 1
        self.assertEqual(self.read()['error_code'], 'CUSTODY_INVALID')

    def test_symlink_and_missing_file_are_not_followed_or_created(self):
        target = self.path.with_suffix('.target')
        self.path.rename(target)
        self.path.symlink_to(target)
        self.assertEqual(self.read()['error_code'], 'READ_ERROR')
        self.path.unlink()
        self.assertEqual(self.read()['error_code'], 'READ_ERROR')
        self.assertFalse(self.path.exists())

    def test_parse_schema_scope_and_size_errors_have_bounded_diagnostics(self):
        cases = [('private malformed payload', 'JSON_INVALID'),
                 ('{}', 'SCHEMA_INVALID'),
                 (json.dumps(dict(self.value, scope='PRIVATE_SCOPE')), 'SCOPE_INVALID'),
                 ('x'*(8*1024*1024+1), 'PROJECTION_TOO_LARGE')]
        for raw, expected in cases:
            with self.subTest(expected=expected):
                self.path.write_text(raw)
                result = self.read()
                self.assertEqual(result['error_code'], expected)
                self.assertEqual(result['issues'], ['PAPER_ACCOUNT_UNAVAILABLE:intraday'])
                self.assertNotIn(str(self.path), str(result))
                self.assertNotIn('private', str(result).lower())

    def test_real_account_halts_and_incomplete_accounting_remain_alerts(self):
        for kind in ('accounting', 'integrity', 'drawdown'):
            with self.subTest(kind=kind):
                self.value['accounting_complete'] = kind != 'accounting'
                self.value['state']['integrity_halt'] = kind == 'integrity'
                self.value['state']['drawdown_halt'] = kind == 'drawdown'
                self.write()
                result = self.read()
                self.assertEqual(result['issues'], ['PAPER_ACCOUNT_BLOCKED:intraday'])
                self.assertEqual(result['status'], 'attention')
