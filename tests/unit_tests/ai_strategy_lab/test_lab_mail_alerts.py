import importlib.util
import json
from pathlib import Path
import sqlite3
import tempfile
import unittest
from unittest.mock import patch

spec = importlib.util.spec_from_file_location('mail', Path(__file__).resolve().parents[3] / 'scripts/lab_mail_alerts.py')
mail = importlib.util.module_from_spec(spec)
spec.loader.exec_module(mail)


class MailTests(unittest.TestCase):
    def test_restart_deduplication_and_recovery(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / 'state.sqlite'
            sent = []
            with sqlite3.connect(path) as db:
                self.assertEqual(mail.notify(db, ['CONTAINER_STATE_UNAVAILABLE'], 10000,
                    lambda *args: sent.append(args)), 'PROBLEMA')
            with sqlite3.connect(path) as db:
                self.assertEqual(mail.notify(db, ['CONTAINER_STATE_UNAVAILABLE'], 10300,
                    lambda *args: sent.append(args)), 'DEDUPLICATO')
                self.assertEqual(mail.notify(db, [], 10600,
                    lambda *args: sent.append(args)), 'RECUPERO')
                self.assertEqual(mail.notify(db, [], 10900,
                    lambda *args: sent.append(args)), 'DEDUPLICATO')
            self.assertEqual(len(sent), 2)

    def test_failed_delivery_does_not_consume_notification(self):
        with sqlite3.connect(':memory:') as db:
            def fail(*args):
                raise OSError('synthetic transport failure')
            with self.assertRaises(OSError):
                mail.notify(db, ['CONTAINER_STATE_UNAVAILABLE'], 10000, fail)
            self.assertEqual(db.execute('SELECT count(*) FROM notification_state').fetchone()[0], 0)
            sent = []
            self.assertEqual(mail.notify(db, ['CONTAINER_STATE_UNAVAILABLE'], 10300,
                lambda *args: sent.append(args)), 'PROBLEMA')

    def test_rate_limit_and_daily_reminder(self):
        state = dict(alerts=['CONTAINER_STATE_UNAVAILABLE'], sent_at=10000)
        self.assertIsNone(mail.plan(['MEMORY_AVAILABLE_BELOW_10_PERCENT'], state, 10300))
        self.assertEqual(mail.plan(['MEMORY_AVAILABLE_BELOW_10_PERCENT'], state, 11800), 'AGGIORNAMENTO')
        self.assertEqual(mail.plan(state['alerts'], state, 96400), 'PROMEMORIA')

    def test_no_healthy_start_mail_and_first_incident_immediate(self):
        with sqlite3.connect(':memory:') as db:
            sent = []
            mail.notify(db, [], 10000, lambda *args: sent.append(args))
            self.assertFalse(sent)
            mail.notify(db, ['CONTAINER_STATE_UNAVAILABLE'], 10300, lambda *args: sent.append(args))
            self.assertEqual(len(sent), 1)

    def test_stale_and_missing_monitor_alert(self):
        with tempfile.TemporaryDirectory() as tmp:
            p = Path(tmp) / 'status.json'
            self.assertEqual(mail.read_alerts(p, 10000), ['MONITOR_UNAVAILABLE_OR_STALE'])
            p.write_text(json.dumps(dict(scope='PASSIVE_LAB_TELEMETRY_ONLY',
                observed_at='1970-01-01T00:00:00+00:00', alerts=[])))
            self.assertEqual(mail.read_alerts(p, 10000), ['MONITOR_UNAVAILABLE_OR_STALE'])

    def test_verified_tls_before_login(self):
        config = dict(SMTP_HOST='smtp.example.test', SMTP_PORT='587', SMTP_USERNAME='sender@example.test',
            SMTP_PASSWORD='synthetic-password', SMTP_FROM='sender@example.test', SMTP_TO='recipient@example.test')
        with patch.object(mail.smtplib, 'SMTP') as factory:
            smtp = factory.return_value.__enter__.return_value
            smtp.send_message.return_value = {}
            mail.deliver(config, 'TEST', [], 10000)
            self.assertTrue(smtp.starttls.call_args.kwargs['context'].check_hostname)
            names = [c[0] for c in smtp.method_calls]
            self.assertLess(names.index('starttls'), names.index('login'))
            smtp.starttls.side_effect = OSError('synthetic TLS failure')
            smtp.reset_mock()
            with self.assertRaises(OSError):
                mail.deliver(config, 'TEST', [], 10000)
            smtp.login.assert_not_called()

    def test_confirmation_filters_only_single_blind_check(self):
        with tempfile.TemporaryDirectory() as tmp:
            p=Path(tmp)/'status.json'
            value=dict(scope='PASSIVE_LAB_TELEMETRY_ONLY',observed_at='2026-10-10T00:00:00+00:00',
                alerts=['CONTAINER_STATE_UNAVAILABLE'],notification_alerts=[],container_check_failure_streak=1)
            now=mail.dt.datetime.fromisoformat(value['observed_at']).timestamp()+5
            p.write_text(json.dumps(value))
            self.assertEqual(mail.read_alerts(p,now),[])
            value.update(container_check_failure_streak=2,notification_alerts=['CONTAINER_STATE_UNAVAILABLE'])
            p.write_text(json.dumps(value))
            self.assertEqual(mail.read_alerts(p,now),['CONTAINER_STATE_UNAVAILABLE'])
            value.update(alerts=['CONTAINER_NOT_HEALTHY:paper'],notification_alerts=[])
            p.write_text(json.dumps(value))
            self.assertEqual(mail.read_alerts(p,now),['MONITOR_UNAVAILABLE_OR_STALE'])

    def test_legacy_projection_retains_immediate_alerts(self):
        with tempfile.TemporaryDirectory() as tmp:
            p=Path(tmp)/'status.json'
            p.write_text(json.dumps(dict(scope='PASSIVE_LAB_TELEMETRY_ONLY',
                observed_at='2026-10-10T00:00:00+00:00',alerts=['CONTAINER_STATE_UNAVAILABLE'])))
            now=mail.dt.datetime.fromisoformat('2026-10-10T00:00:00+00:00').timestamp()+5
            self.assertEqual(mail.read_alerts(p,now),['CONTAINER_STATE_UNAVAILABLE'])
