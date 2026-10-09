"""Synthetic diagnostic checks; no inference or official forward data writes.

Work card: work-card-39e3f6b0-0609-4c75-834a-cf0f5ce54ecb.
"""
import copy
import datetime as dt
import importlib.util
import json
from pathlib import Path
import tempfile
import unittest
from unittest import mock

PATH = Path(__file__).resolve().parents[3] / 'octobot/ai_strategy_lab/qwen_shadow_diagnostics.py'
spec = importlib.util.spec_from_file_location('qwen_diagnostic_test', PATH)
d = importlib.util.module_from_spec(spec)
spec.loader.exec_module(d)
START = dt.datetime(2030, 1, 1, 0, 10, tzinfo=dt.timezone.utc)
SLOT = START.isoformat()
NOW = START + dt.timedelta(minutes=20)


def fixture(reason='MODEL_UNAVAILABLE', latency=35.02):
    manifest = dict(start_slot_utc=SLOT, experiment_id='qwen-btc-direction-shadow-v1',
                    scope='FORWARD_SHADOW_RESEARCH_ONLY', lineage='0' * 64,
                    end_slot_utc=(START+dt.timedelta(days=179)).isoformat(),
                    review_at=(START+dt.timedelta(days=181, minutes=20)).isoformat())
    status = d._VIEW.prepared(manifest, '1' * 64, NOW.isoformat())
    status.update(phase='COLLECTING', scheduler_active=True, integrity='OK',
                  issues=[], decisions_pending=[], expected=1, recorded_pairs=1)
    status['calendar'][0]['baseline'].update(state='LONG', reason_codes=['TREND_UP'])
    status['calendar'][0]['qwen'].update(state='MISSING', reason_codes=[reason], latency_seconds=latency)
    return status


def log(role, seconds, message, pid=None):
    return dict(_SYSTEMD_UNIT=d.UNITS[role], _PID=pid or ('100' if role=='runner' else '200'),
                _BOOT_ID='a' * 32, __REALTIME_TIMESTAMP=str(int((START.timestamp()+seconds)*1e6)),
                MESSAGE=message)


def logs():
    runner = [log('runner', 155.06, json.dumps(dict(status='RECORDED', decision='MISSING', seconds=35.05)))]
    server = [log('server', 120.1, 'slot launch_slot_: id 0 | task 99 | processing task, is_child = 0'),
              log('server', 154, 'slot print_timing: id 0 | task 99 | prompt processing, n_tokens = 3169, progress = 1.00, t = 33.78 s / 93.81 tokens per second'),
              log('server', 155.04, 'W srv stop: cancel task, id_task = 99')]
    return runner, server


class DiagnosticTests(unittest.TestCase):
    def run_diagnostic(self, status=None, runner=None, server=None, now=NOW):
        a,b = logs()
        return d.diagnose(status or fixture(), SLOT, a if runner is None else runner,
                          b if server is None else server, now=now)

    def test_timeout_is_inferred_with_correlated_cancellation(self):
        result = self.run_diagnostic()
        self.assertEqual(result['diagnosis'], 'CLIENT_TIMEOUT_LIKELY')
        self.assertEqual(result['confidence'], 'INFERRED')
        self.assertIsNone(result['transport_exit_code'])
        self.assertAlmostEqual(result['timing_evidence']['generation_headroom_upper_bound_seconds'], 1.22)
        self.assertTrue(result['performance_sealed'])
        self.assertFalse(result['execution_approved'])

    def test_unavailable_without_logs_stays_unknown(self):
        result = self.run_diagnostic(runner=[], server=[])
        self.assertEqual(result['diagnosis'], 'MODEL_UNAVAILABLE_UNCLASSIFIED')
        self.assertEqual(result['confidence'], 'UNKNOWN')

    def test_busy_and_invalid_output_preserve_observed_reasons(self):
        for reason in ['MODEL_BUSY', 'MODEL_IDENTITY_MISMATCH', 'OUTPUT_SCHEMA_INVALID', 'PROCESS_INTERRUPTED']:
            with self.subTest(reason=reason):
                r = self.run_diagnostic(status=fixture(reason, .1), runner=[], server=[])
                self.assertEqual(r['diagnosis'], reason)
                self.assertEqual(r['confidence'], 'OBSERVED')

    def test_multiple_nearby_launches_cannot_be_attributed(self):
        a,b = logs()
        b.append(log('server', 120.2, 'slot launch_slot_: id 1 | task 100 | processing task, is_child = 0'))
        self.assertEqual(self.run_diagnostic(runner=a, server=b)['confidence'], 'UNKNOWN')

    def test_cancellation_for_another_task_or_process_is_ignored(self):
        for mutation in ['task', 'pid', 'boot']:
            a,b = logs()
            if mutation=='task': b[-1]['MESSAGE'] = 'srv stop: cancel task, id_task = 999'
            elif mutation=='pid': b[-1]['_PID'] = '201'
            else: b[-1]['_BOOT_ID'] = 'b' * 32
            self.assertEqual(self.run_diagnostic(runner=a, server=b)['confidence'], 'UNKNOWN')

    def test_stale_and_future_projection_do_not_yield_a_diagnosis(self):
        self.assertEqual(self.run_diagnostic(now=NOW+dt.timedelta(minutes=4))['diagnosis'], 'STATUS_UNVERIFIABLE')
        with self.assertRaises(ValueError): self.run_diagnostic(now=NOW-dt.timedelta(minutes=1))

    def test_latency_mismatch_and_multiple_terminals_remain_unknown(self):
        a,b = logs()
        self.assertEqual(self.run_diagnostic(status=fixture(latency=1), runner=a, server=b)['confidence'], 'UNKNOWN')
        self.assertEqual(self.run_diagnostic(runner=a+a, server=b)['confidence'], 'UNKNOWN')

    def test_raw_prompts_and_extra_payload_fields_are_discarded(self):
        a,b = logs()
        secret = 'CANARY_PRIVATE_TEXT'
        a.append(log('runner', 155, json.dumps(dict(status='RECORDED', decision='MISSING', seconds=35, prompt=secret))))
        b.append(log('server', 121, 'prompt '+secret))
        raw = json.dumps(self.run_diagnostic(runner=a, server=b))
        self.assertNotIn(secret, raw)
        self.assertNotIn('MESSAGE', raw)
        self.assertNotIn('_PID', raw)

    def test_invalid_log_values_are_ignored(self):
        a,b = logs()
        for bad in [None, {}, {'MESSAGE': 'secret'}, dict(b[0], __REALTIME_TIMESTAMP='NaN'), dict(b[0], _SYSTEMD_UNIT='wrong')]:
            self.assertEqual(d.events([bad], 'server'), [])
        a[0]['MESSAGE'] = '{"status":"RECORDED","decision":"MISSING","seconds":NaN}'
        self.assertEqual(self.run_diagnostic(runner=a, server=b)['confidence'], 'UNKNOWN')

    def test_projection_is_never_changed_and_valid_direction_is_not_exposed(self):
        status = fixture(); before=copy.deepcopy(status)
        self.run_diagnostic(status=status)
        self.assertEqual(status, before)
        status['calendar'][0]['qwen'].update(state='SHORT', reason_codes=['TREND_DOWN'])
        r=self.run_diagnostic(status=status)
        self.assertEqual(r['recorded_state'], 'RECORDED_VALID')
        self.assertEqual(r['reason_codes'], [])

    def test_successful_request_keeps_timing_without_exposing_prediction(self):
        status=fixture(); status['calendar'][0]['qwen'].update(state='LONG', reason_codes=['TREND_UP'])
        a,b=logs(); a[0]['MESSAGE']=json.dumps(dict(status='RECORDED', decision='LONG', seconds=35.05))
        r=self.run_diagnostic(status=status, runner=a, server=b[:-1])
        self.assertEqual(r['diagnosis'], 'RECORDED_VALID')
        self.assertEqual(r['confidence'], 'OBSERVED')
        self.assertEqual(r['timing_evidence']['prompt_processing_seconds'], 33.78)

    def test_journal_reader_uses_only_declared_unit_without_network(self):
        with mock.patch.object(d.subprocess, 'run', return_value=mock.Mock(returncode=0, stdout=b'')) as run:
            self.assertEqual(d.system_logs('server', SLOT), [])
            args=run.call_args.args[0]
            self.assertEqual(args[:3], ['/usr/bin/journalctl', '--unit', 'llama-moe.service'])
            self.assertNotIn('curl', ' '.join(args))

    def test_cli_rejects_database_path_before_read(self):
        with mock.patch('sys.argv', ['diagnostic', '--status', 'outcomes.sqlite', '--slot', SLOT, '--system-journal']), \
             mock.patch.object(d._VIEW, 'public_view') as reader:
            with self.assertRaises(SystemExit): d.main()
            reader.assert_not_called()

    def test_bounded_log_file_reader(self):
        with tempfile.TemporaryDirectory() as tmp:
            path=Path(tmp)/'runner.jsonl';path.write_text('x'*(d.MAX_BYTES+1))
            with self.assertRaises(ValueError):d.read_logs(path)
        with self.assertRaises(ValueError):d.read_logs('outcomes.sqlite')


if __name__ == '__main__':
    unittest.main()
