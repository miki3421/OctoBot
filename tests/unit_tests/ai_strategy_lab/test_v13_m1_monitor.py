"""M1 monitoring fixtures: no future observations or execution permission."""
import copy
import datetime as dt
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import sqlite3
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[3]
spec = importlib.util.spec_from_file_location('monitor', ROOT / 'octobot/ai_strategy_lab/v13_m1_monitor.py')
m = importlib.util.module_from_spec(spec); spec.loader.exec_module(m)
PROTOCOL = ROOT / 'docs/research-protocols/v13-m1-short-prospective-v1.json'
T0 = dt.datetime(2032, 5, 10, tzinfo=dt.timezone.utc).timestamp()


class MonitorTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(); self.root = Path(self.temp.name)
        self.path = self.root / 'observation.sqlite'; self.output = self.root / 'status.json'
        p = json.loads(PROTOCOL.read_text()); self.identity = dict(protocol=hashlib.sha256(m.encoded(p).encode()).hexdigest(), journal=p['source_code_pins']['octobot/ai_strategy_lab/v13_m1_future.py'], detector=p['source_code_pins']['octobot/ai_strategy_lab/v13_crash_diagnostic.py'])
        self.activation = dict(recorded_at=T0 - 3600, t0=T0, end_exclusive=T0 + 90*86400, study=m.STUDY, protocol_hash=self.identity['protocol'], fixture=False)
        with sqlite3.connect(self.path) as db:
            db.executescript('CREATE TABLE meta(key TEXT PRIMARY KEY,payload TEXT); CREATE TABLE slots(slot INTEGER PRIMARY KEY,status TEXT,payload TEXT); CREATE TABLE episodes(id TEXT PRIMARY KEY,slot INTEGER,entry_slot INTEGER,exit_slot INTEGER,status TEXT); CREATE TABLE captures(episode_id TEXT,phase TEXT,payload TEXT);')
            for k, v in dict(identity=self.identity, activation=self.activation, fixture=False, last_seen=T0-3600).items():
                db.execute('INSERT INTO meta VALUES(?,?)', (k, m.encoded(v)))
        os.chown(self.path, m.WRITER_UID, -1); self.path.chmod(0o600)
        self.system = lambda now: dict(timer_active=True, enabled=True, result='success', exit_status=0, run_age_seconds=10., last_run_at=m.iso(now-10), clock_synchronized=True)

    def tearDown(self): self.temp.cleanup()
    def build(self, now=T0-60, system=None): return m.build(self.path, PROTOCOL, now, system=system or self.system)
    def slot(self, offset, status, feature=None):
        slot = int(T0 + offset)
        payload = dict(recorded_at=slot+10, feature=feature, consumed_rows=[{'PRIVATE_RAW':True}], pnl=12345)
        with sqlite3.connect(self.path) as db:
            db.execute('INSERT INTO slots VALUES(?,?,?)', (slot, status, json.dumps(payload)))
        return slot
    def projected(self, value, now):
        m.publish(self.output, value); os.chown(self.output, m.WRITER_UID, -1)
        return m.public_view(self.output, now=now)

    def test_waiting_has_no_due_slots_but_verified_scheduler(self):
        v = self.build(); self.assertEqual(v['phase'], 'waiting'); self.assertEqual(v['coverage']['expected'], 0)
        self.assertIsNone(v['coverage']['valid_fraction']); self.assertEqual(v['issues'], [])
        self.assertEqual(self.projected(v, T0-60), v)

    def test_no_signal_is_valid_collection_and_readonly(self):
        self.slot(0, 'NO_SIGNAL', dict(btc_60m=.001, negative_breadth=5/18))
        before = self.path.read_bytes(); v = self.build(T0+180)
        self.assertEqual(v['coverage']['valid'], 1); self.assertEqual(v['counts']['signals'], 0)
        self.assertEqual(v['last_feature']['negative_symbols'], 5); self.assertEqual(self.path.read_bytes(), before)
        self.assertNotIn('PRIVATE_RAW', json.dumps(v)); self.assertNotIn('pnl', json.dumps(v))

    def test_trigger_and_cooldown_are_distinct_from_admitted_episode(self):
        f = dict(btc_60m=-.012, negative_breadth=14/18)
        self.slot(0, 'SCHEDULED', f); self.slot(300, 'COOLDOWN', f)
        with sqlite3.connect(self.path) as db:
            db.execute('INSERT INTO episodes VALUES(?,?,?,?,?)', ('a'*64, T0, T0+300, T0+21900, 'SCHEDULED'))
        v = self.build(T0+480); self.assertEqual(v['counts']['signals'], 2)
        self.assertEqual(v['counts']['episodes']['SCHEDULED'], 1); self.assertEqual(len(v['signals']), 2)
        self.assertIsNone(v['signals'][0]['episode_id']); self.assertEqual(v['signals'][1]['episode_id'], 'a'*64)
        self.assertEqual(self.projected(v, T0+480), v)

    def test_due_unrecorded_slots_and_missing_inputs_do_not_disappear(self):
        self.slot(0, 'INSUFFICIENT_INPUT'); self.slot(300, 'MISSED')
        v = self.build(T0+780); self.assertEqual(v['coverage']['expected'], 3)
        self.assertEqual(v['coverage']['overdue'], 1); self.assertEqual(v['coverage']['valid_fraction'], 0)
        self.assertIn('MISSING_INPUT', v['issues']); self.assertIn('UNRECORDED_SLOTS', v['issues'])

    def test_successful_inactive_oneshot_is_healthy_but_failed_or_late_is_not(self):
        v = self.build(); self.assertNotIn('COLLECTOR_FAILURE', v['issues'])
        for change, issue in [(dict(result='exit-code', exit_status=1), 'COLLECTOR_FAILURE'), (dict(run_age_seconds=181), 'COLLECTOR_LATE'), (dict(timer_active=False), 'SCHEDULER_INACTIVE'), (dict(clock_synchronized=False), 'CLOCK_UNSYNCHRONIZED')]:
            system = lambda now, change=change: dict(self.system(now), **change)
            with self.subTest(issue=issue): self.assertIn(issue, self.build(system=system)['issues'])

    def test_projection_stale_future_or_missing_is_not_zero_success(self):
        v = self.build(); m.publish(self.output, v); os.chown(self.output, m.WRITER_UID, -1)
        stale = m.public_view(self.output, now=T0+180); self.assertTrue(stale['stale']); self.assertIn('MONITOR_STALE', stale['issues'])
        self.assertFalse(m.public_view(self.output, now=T0-120)['available'])
        self.output.unlink(); missing = m.public_view(self.output, now=T0)
        self.assertFalse(missing['available']); self.assertIsNone(missing['counts']); self.assertFalse(self.output.exists())

    def test_fixture_wrong_identity_and_bad_protocol_are_rejected(self):
        for key, value in [('fixture', True), ('identity', dict(self.identity, protocol='x'))]:
            with sqlite3.connect(self.path) as db:
                old = db.execute('SELECT payload FROM meta WHERE key=?', (key,)).fetchone()[0]
                db.execute('UPDATE meta SET payload=? WHERE key=?', (json.dumps(value), key))
            with self.subTest(key=key), self.assertRaises(ValueError): self.build()
            with sqlite3.connect(self.path) as db: db.execute('UPDATE meta SET payload=? WHERE key=?', (old, key))
        bad = self.root/'bad.json'; bad.write_text('{}')
        with self.assertRaises(ValueError): m.build(self.path, bad, T0, self.system)

    def test_corrupt_missing_symlink_and_writable_journal_refused(self):
        self.path.chmod(0o666)
        with self.assertRaises(ValueError): self.build()
        self.path.chmod(0o600); saved = self.path.with_suffix('.saved'); self.path.rename(saved); self.path.symlink_to(saved)
        with self.assertRaises(ValueError): self.build()
        self.path.unlink()
        with self.assertRaises(FileNotFoundError): self.build()
        self.assertFalse(self.path.exists()); self.path.write_bytes(b'bad'); os.chown(self.path, m.WRITER_UID, -1)
        with self.assertRaises(sqlite3.Error): self.build()

    def test_unexpected_performance_or_private_nested_fields_never_reach_web(self):
        v = self.build()
        for key in ('top', 'collector', 'counts', 'activation', 'slots'):
            candidate = copy.deepcopy(v)
            if key == 'top': candidate['pnl'] = 99
            elif key == 'slots': candidate['slots'] = [dict(slot=m.iso(T0), status='NO_SIGNAL', recorded_at=m.iso(T0+1), private_path='hidden')]
            else: candidate[key]['pnl'] = 99
            with self.subTest(key=key): self.assertFalse(self.projected(candidate, T0-60)['available'])

    def test_negative_counts_bad_states_and_projection_custody_rejected(self):
        v = self.build(); v['counts']['signals'] = -1
        self.assertFalse(self.projected(v, T0-60)['available'])
        v = self.build(); self.projected(v, T0-60); self.output.chmod(0o666)
        self.assertFalse(m.public_view(self.output, now=T0-60)['available'])
        self.output.chmod(0o640); saved = self.output.with_suffix('.saved'); self.output.rename(saved); self.output.symlink_to(saved)
        self.assertFalse(m.public_view(self.output, now=T0-60)['available'])

    def test_retained_rows_bounded_and_full_counts_preserved(self):
        for n in range(110): self.slot(n*300, 'NO_SIGNAL')
        v = self.build(T0+110*300); self.assertEqual(len(v['slots']), 100)
        self.assertEqual(v['counts']['slots']['NO_SIGNAL'], 110)

    def test_episode_captures_shown_without_pnl_or_snapshot_paths(self):
        self.slot(0, 'SCHEDULED', dict(btc_60m=-.02, negative_breadth=1.))
        with sqlite3.connect(self.path) as db:
            db.execute('INSERT INTO episodes VALUES(?,?,?,?,?)', ('b'*64, T0, T0+300, T0+21900, 'CAPTURE_COMPLETE_AWAITING_OFFLINE_REPLAY'))
            for phase, at in [('entry', T0+310), ('exit', T0+21910)]:
                db.execute('INSERT INTO captures VALUES(?,?,?)', ('b'*64, phase, json.dumps(dict(captured_at=at, snapshot_sha256='PRIVATE_HASH'))))
        v = self.build(T0+22000); self.assertEqual(len(v['episodes']), 1)
        self.assertIsNotNone(v['episodes'][0]['exit_captured_at']); self.assertTrue(v['performance_sealed'])
        self.assertNotIn('PRIVATE_HASH', json.dumps(v))


if __name__ == '__main__': unittest.main()
