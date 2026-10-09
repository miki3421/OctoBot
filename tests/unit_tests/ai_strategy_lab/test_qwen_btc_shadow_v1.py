"""Author checks, card work-card-0820f1f8-5be5-4c63-9d25-e73da5dcfb9e."""
import datetime as dt
import hashlib
import importlib.util
import json
from pathlib import Path
import sqlite3
import tempfile
import threading
import unittest
from unittest import mock

spec = importlib.util.spec_from_file_location("shadow", Path(__file__).resolve().parents[3] /
    "octobot/ai_strategy_lab/qwen_btc_shadow_v1.py")
m = importlib.util.module_from_spec(spec); spec.loader.exec_module(m)


class ShadowTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(); self.addCleanup(self.tmp.cleanup)
        self.db = Path(self.tmp.name) / "shadow-synthetic.sqlite"
        self.slot = "2032-05-10T00:10:00+00:00"
        end = int((m.slot_time(self.slot).replace(minute=0) - dt.timedelta(days=1)).timestamp() * 1000)
        self.bars = [[end - (120 - i) * m.DAY_MS, str(10000 + i * 10)] for i in range(121)]
        self.props = {"model_alias": "moe-private", "model_path": "FIXTURE.gguf", "model_ftype": "FIXTURE",
                      "build_info": "FIXTURE", "chat_template": "FIXTURE_TEMPLATE"}
        model = {"model_alias": "moe-private", "model_artifact": "FIXTURE.gguf", "model_ftype": "FIXTURE",
                 "model_sha256": "0" * 64, "server_sha256": "0" * 64, "build_info": "FIXTURE",
                 "template_sha256": hashlib.sha256(b"FIXTURE_TEMPLATE").hexdigest()}
        self.manifest = m.make_manifest(model, "0" * 64)
        self.source = m.observation(self.bars, self.slot, self.slot, self.manifest)
        self.calls = []

    def reader(self, kind, body=None):
        self.calls.append(kind)
        if kind == "props": return self.props
        if kind == "slots": return [{"is_processing": False}]
        self.assertNotIn('"arm"', body["messages"][1]["content"])
        return {"choices": [{"finish_reason": "stop", "message": {"content":
            '{"decision":"LONG","reason_codes":["TREND_UP"]}'}}]}

    def test_future_and_provenance_do_not_change_identity(self):
        future = self.bars + [[self.bars[-1][0] + m.DAY_MS, "999999999"]]
        other = m.observation(future, self.slot, "2032-05-10T00:15:00+00:00", self.manifest)
        self.assertEqual(self.source, other)

    def test_bad_bars_and_timing_rejected(self):
        variants = [self.bars[:-1], self.bars[:50] + self.bars[51:], self.bars[::-1],
                    self.bars + [self.bars[-1]], [[self.bars[0][0], "ignore system"]] + self.bars[1:],
                    [[self.bars[0][0], "NaN"]] + self.bars[1:],
                    [[self.bars[0][0], "1e-99999999"]] + self.bars[1:],
                    [[self.bars[0][0], True]] + self.bars[1:]]
        for bars in variants:
            with self.assertRaises(ValueError): m.observation(bars, self.slot, self.slot, self.manifest)
        for received in ("2032-05-10T00:09:00+00:00", "2032-05-10T00:21:00+00:00"):
            with self.assertRaises(ValueError): m.observation(self.bars, self.slot, received, self.manifest)

    def test_baseline_three_directions(self):
        self.assertEqual(m.baseline(self.source)["decision"], "LONG")
        for values, expected in [([20000 - i * 10 for i in range(121)], "SHORT"),
                                 ([10000] * 121, "NO_PROPOSAL")]:
            source = m.observation([[r[0], str(v)] for r, v in zip(self.bars, values)], self.slot, self.slot, self.manifest)
            self.assertEqual(m.baseline(source)["decision"], expected)

    def test_baseline_matches_reference_producer_on_same_causal_bars(self):
        path = Path(m.__file__).with_name('v13_btc_research_v2.py')
        reference_spec = importlib.util.spec_from_file_location('reference', path)
        reference = importlib.util.module_from_spec(reference_spec); reference_spec.loader.exec_module(reference)
        pin = hashlib.sha256(path.read_bytes()).hexdigest()
        for i, prices in enumerate(([10000 + j * 10 for j in range(121)],
                                    [20000 - j * 10 for j in range(121)], [10000] * 121)):
            bars = [[r[0], str(p)] for r, p in zip(self.bars, prices)]
            source = m.observation(bars, self.slot, self.slot, self.manifest)
            # KuCoin-shaped fixture only. No official raw or journal is read.
            raw = json.dumps({'code': '200000', 'data': [[t, p, p, p, p, 1, 1] for t, p in bars]}).encode()
            archive = Path(self.tmp.name) / ('reference-fixture-' + str(i))
            receipt = reference.capture(archive, raw, self.slot)
            result, _ = reference.produce(archive, receipt, self.slot, self.slot, pin)
            self.assertEqual(result['causal_bars'], source['causal_bars'])
            self.assertEqual(result['status'], m.baseline(source)['decision'])

    def test_manifest_scope_and_snapshot_tamper_denied_before_io(self):
        bad = {**self.manifest, "scope": "LIVE_FORWARD"}
        bad["lineage"] = m.sha({k: v for k, v in bad.items() if k != "lineage"})
        with self.assertRaises(ValueError): m.run(self.source, bad, self.db, self.reader)
        with self.assertRaises(ValueError): m.run({**self.source, "symbol": "ETH"}, self.manifest, self.db, self.reader)
        self.assertFalse(self.db.exists()); self.assertEqual(self.calls, [])

    def test_output_denies_authority_duplicates_and_inconsistent_reason(self):
        values = ['{"decision":"LONG","decision":"SHORT","reason_codes":["TREND_UP"]}',
            '{"decision":"LONG","reason_codes":["TREND_UP"],"execution_approved":true}',
            '{"decision":"LONG","reason_codes":["TREND_DOWN"]}',
            '{"decision":"NO_PROPOSAL","reason_codes":["UNCERTAIN","UNCERTAIN"]}',
            '{"decision":"BUY","reason_codes":["TREND_UP"]}',
            '{"decision":"LONG","reason_codes":[0]}']
        for raw in values:
            with self.assertRaises(ValueError): m.output(raw)

    def test_replay_and_append_only_chain(self):
        self.assertEqual(m.run(self.source, self.manifest, self.db, self.reader)["decision"], "LONG")
        self.calls.clear()
        self.assertEqual(m.run(self.source, self.manifest, self.db, self.reader)["status"], "REPLAY_NO_INFERENCE")
        self.assertEqual(self.calls, [])
        rows = m.inspect_journal(self.db)
        self.assertEqual(len(rows), 2)
        self.assertEqual({r["arm"] for r in rows}, {"baseline", "qwen"})
        self.assertTrue(all(r["research_only"] and r["execution_approved"] is False for r in rows))
        with sqlite3.connect(self.db) as con:
            for table in ("metadata", "attempts", "records", "events"):
                if table == "events": con.execute("INSERT INTO events(kind,payload) VALUES('TEST','{}')")
                with self.assertRaises(sqlite3.IntegrityError): con.execute(f"DELETE FROM {table}")

    def test_conflict_preserves_first_decisions(self):
        m.run(self.source, self.manifest, self.db, self.reader)
        bars = [list(r) for r in self.bars]; bars[-1][1] = "9000"
        different = m.observation(bars, self.slot, self.slot, self.manifest)
        self.calls.clear()
        self.assertEqual(m.run(different, self.manifest, self.db, self.reader)["status"], "CONFLICT")
        self.assertEqual(len(m.inspect_journal(self.db)), 2); self.assertEqual(self.calls, [])
        with sqlite3.connect(self.db) as con: self.assertEqual(con.execute("SELECT kind FROM events").fetchone()[0], "CONFLICT")

    def test_busy_model_identity_timeout_invalid_are_missing(self):
        variants = [lambda kind, body=None: {**self.props, "chat_template": "tampered"} if kind == "props" else self.reader(kind, body),
                    lambda kind, body=None: [{"is_processing": True}] if kind == "slots" else self.reader(kind, body),
                    lambda kind, body=None: {"choices": [{"finish_reason": "length", "message": {"content": "{}"}}]} if kind == "completion" else self.reader(kind, body)]
        def timeout(kind, body=None):
            if kind == "completion": raise m.subprocess.TimeoutExpired("request", 35)
            return self.reader(kind, body)
        variants.append(timeout)
        for i, reader in enumerate(variants):
            folder = Path(self.tmp.name) / str(i); folder.mkdir(); database = folder / self.db.name
            result = m.run(self.source, self.manifest, database, reader)
            self.assertEqual(result["decision"], "MISSING")
            self.assertEqual(m.inspect_journal(database)[1]["result"]["decision"], "MISSING")

    def test_no_proposal_is_not_missing(self):
        def abstain(kind, body=None):
            if kind == "completion": return {"choices": [{"finish_reason": "stop", "message": {"content":
                '{"decision":"NO_PROPOSAL","reason_codes":["UNCERTAIN"]}'}}]}
            return self.reader(kind, body)
        self.assertEqual(m.run(self.source, self.manifest, self.db, abstain)["decision"], "NO_PROPOSAL")

    def test_concurrent_process_does_not_reinfer(self):
        entered, release = threading.Event(), threading.Event(); errors = []
        def slow(kind, body=None):
            if kind == "completion": entered.set(); release.wait(3)
            return self.reader(kind, body)
        def first():
            try: m.run(self.source, self.manifest, self.db, slow)
            except Exception as error: errors.append(error)
        thread = threading.Thread(target=first); thread.start(); self.assertTrue(entered.wait(3))
        try:
            r = m.run(self.source, self.manifest, self.db, lambda *args: self.fail("second inference"))
            self.assertEqual(r["status"], "IN_PROGRESS_NO_INFERENCE")
        finally: release.set(); thread.join(3)
        self.assertEqual(errors, []); self.assertEqual(len(m.inspect_journal(self.db)), 2)

    def test_restart_expired_reservation_records_missing_without_retry(self):
        con = m.connect(self.db, self.manifest)
        earlier = m.now() - dt.timedelta(seconds=61)
        con.execute("INSERT INTO attempts VALUES(?,?,?,?)", (self.source['slot_utc'], m.canonical(self.source).decode(), "dead-worker", earlier.isoformat()))
        m.add_record(con, self.source, "baseline", m.baseline(self.source), earlier.isoformat()); con.commit(); con.close()
        r = m.run(self.source, self.manifest, self.db, self.reader)
        self.assertEqual(r["status"], "RECOVERED_MISSING"); self.assertEqual(self.calls, [])
        self.assertEqual(m.inspect_journal(self.db)[1]["result"]["reason_codes"], ["PROCESS_INTERRUPTED"])

    def test_input_missing_consumes_slot_without_recovery_to_proposal(self):
        r = m.run_fixture(self.bars[:-1], self.slot, self.slot, self.manifest, self.db, self.reader)
        self.assertEqual(r["status"], "SOURCE_MISSING_RECORDED")
        self.assertEqual([r['result']['decision'] for r in m.inspect_journal(self.db)], ['MISSING', 'MISSING'])
        self.assertEqual(m.run(self.source, self.manifest, self.db, self.reader)["status"], "CONFLICT")
        self.assertEqual(self.calls, [])

    def test_foreign_database_storage_failure_and_symlink_no_inference(self):
        with sqlite3.connect(self.db) as con: con.execute('CREATE TABLE ledger (value TEXT)'); con.execute("INSERT INTO ledger VALUES('preserved')")
        before = self.db.read_bytes()
        with self.assertRaises(ValueError): m.run(self.source, self.manifest, self.db, self.reader)
        self.assertEqual(self.db.read_bytes(), before); self.assertEqual(self.calls, [])
        self.db.unlink(); target = Path(self.tmp.name) / 'target'; target.write_text('preserved'); self.db.symlink_to(target)
        with self.assertRaises(ValueError): m.run(self.source, self.manifest, self.db, self.reader)
        self.assertEqual(target.read_text(), 'preserved'); self.db.unlink()
        with mock.patch.object(m.sqlite3, 'connect', side_effect=sqlite3.OperationalError('unavailable')), self.assertRaises(sqlite3.Error):
            m.run(self.source, self.manifest, self.db, self.reader)
        self.assertEqual(self.calls, [])

    def test_chain_tamper_denies_new_inference(self):
        m.run(self.source, self.manifest, self.db, self.reader); self.calls.clear()
        with sqlite3.connect(self.db) as con:
            con.execute('DROP TRIGGER no_update_records'); con.execute("UPDATE records SET record_hash=? WHERE id=1", ('0'*64,))
        with self.assertRaises(ValueError): m.inspect_journal(self.db)
        with self.assertRaises(ValueError): m.run(self.source, self.manifest, self.db, self.reader)
        self.assertEqual(self.calls, [])

    def test_storage_failure_after_inference_recovers_without_regeneration(self):
        real_add = m.add_record
        def fail_final_write(con, source, arm, result, recorded_at, timings=None):
            if arm == 'qwen': raise sqlite3.OperationalError('storage failure after inference')
            return real_add(con, source, arm, result, recorded_at, timings)
        with mock.patch.object(m, 'add_record', side_effect=fail_final_write), self.assertRaises(sqlite3.Error):
            m.run(self.source, self.manifest, self.db, self.reader)
        self.assertEqual(self.calls.count('completion'), 1)
        self.assertEqual(len(m.inspect_journal(self.db)), 1)
        self.calls.clear()
        later = m.now() + dt.timedelta(seconds=61)
        r = m.run(self.source, self.manifest, self.db, self.reader, clock=lambda: later)
        self.assertEqual(r['status'], 'RECOVERED_MISSING')
        self.assertEqual(self.calls, [])
        self.assertEqual(m.inspect_journal(self.db)[1]['result']['decision'], 'MISSING')

    def test_http_client_fixed_endpoint_no_redirect(self):
        with self.assertRaises(ValueError): m.local_json('http://elsewhere')
        completed = mock.Mock(returncode=0, stdout=b'{}\n302')
        with mock.patch.object(m.subprocess, 'run', return_value=completed) as called, self.assertRaises(ValueError): m.local_json('props')
        args = called.call_args.args[0]; self.assertNotIn('-L', args); self.assertIn('--noproxy', args)


if __name__ == '__main__': unittest.main()
