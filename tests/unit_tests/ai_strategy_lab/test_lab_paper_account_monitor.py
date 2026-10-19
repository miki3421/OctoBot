import datetime as dt
import importlib.util
import json
import os
from pathlib import Path
import tempfile
import unittest

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
