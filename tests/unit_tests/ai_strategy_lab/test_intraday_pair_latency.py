"""Equivalent as-of selection, immutable engine, and exact continuation custody."""
import ast
import copy
import hashlib
import importlib.util
import inspect
import json
from pathlib import Path
import sqlite3
import sys
import tempfile
import textwrap
import unittest
from unittest.mock import patch

LAB = Path(__file__).resolve().parents[3] / 'octobot/ai_strategy_lab'
sys.path.insert(0, str(LAB))
from intraday_pair.runner import Pair
from intraday_pair.source import digest
from btc_intraday_pair_latency import FastValuationPair
import btc_intraday_pair_live as original
import btc_intraday_pair_latency_live as candidate
import scalping_observer as collector

INSTALL_SPEC = importlib.util.spec_from_file_location('latency_installer', LAB.parents[1] / 'scripts/activate_intraday_pair_latency.py')
installer = importlib.util.module_from_spec(INSTALL_SPEC)
INSTALL_SPEC.loader.exec_module(installer)


def method_tree(method):
    return ast.parse(textwrap.dedent(inspect.getsource(method)))


def query(method):
    return next(n.value for n in ast.walk(method_tree(method))
                if isinstance(n, ast.Constant) and isinstance(n.value, str)
                and 'JOIN acknowledgements' in n.value)


class EquivalentQueryTests(unittest.TestCase):
    def test_only_change_in_valuation_is_sql_plan_hint(self):
        old = method_tree(Pair.observe_grid)
        new = method_tree(FastValuationPair.observe_grid)
        hint_count = 0
        for n in ast.walk(new):
            if isinstance(n, ast.Constant) and isinstance(n.value, str) and ' NOT INDEXED ' in n.value:
                n.value = n.value.replace(' NOT INDEXED ', ' ')
                hint_count += 1
        self.assertEqual(hint_count, 1)
        self.assertEqual(ast.dump(old), ast.dump(new))
        self.assertEqual(set(FastValuationPair.__dict__) - {'__module__', '__doc__'}, {'observe_grid'})
        self.assertIs(FastValuationPair.poll_sources, Pair.poll_sources)
        self.assertIs(FastValuationPair.drain, Pair.drain)

    def test_cutoff_and_commit_visibility_results_identical(self):
        with sqlite3.connect(':memory:') as db:
            db.executescript('CREATE TABLE events(seq INTEGER PRIMARY KEY,at_ns INTEGER,payload TEXT);'
                             'CREATE INDEX events_time ON events(at_ns);'
                             'CREATE TABLE acknowledgements(seq INTEGER PRIMARY KEY,commit_returned_ns INTEGER);')
            # Non-monotone times and missing/late acknowledgments must still
            # select greatest eligible sequence, not greatest timestamp.
            db.executemany('INSERT INTO events VALUES(?,?,?)',
                           [(i, (i * 17) % 100, str(i)) for i in range(1, 1001)])
            db.executemany('INSERT INTO acknowledgements VALUES(?,?)',
                           [(i, (i * 31) % 150) for i in range(1, 1001) if i % 7])
            for cutoff in (-1, 0, 1, 20, 50, 90, 99, 100, 150):
                with self.subTest(cutoff=cutoff):
                    old = db.execute(query(Pair.observe_grid), (cutoff, cutoff)).fetchone()
                    new = db.execute(query(FastValuationPair.observe_grid), (cutoff, cutoff)).fetchone()
                    self.assertEqual(old, new)
            old_plan = str(db.execute('EXPLAIN QUERY PLAN ' + query(Pair.observe_grid), (100, 100)).fetchall())
            new_plan = str(db.execute('EXPLAIN QUERY PLAN ' + query(FastValuationPair.observe_grid), (100, 100)).fetchall())
            self.assertIn('TEMP B-TREE', old_plan)
            self.assertNotIn('TEMP B-TREE', new_plan)

    def test_collector_changes_only_persistence_interval(self):
        root = LAB.parents[1]
        old = (root / 'docker/scalping-observer-entrypoint.sh').read_text()
        new = (root / 'docker/scalping-observer-low-latency-entrypoint.sh').read_text()
        self.assertEqual(new.replace('--commit-interval-seconds 0.1 ', '--commit-interval-seconds 1 '), old)
        self.assertEqual(new.count('--commit-interval-seconds 0.1 '), 1)

    def test_runtime_loop_semantics_unchanged(self):
        def loop(fn):
            tree = method_tree(fn)
            for n in ast.walk(tree):
                if isinstance(n, ast.Attribute) and isinstance(n.value, ast.Name) and n.value.id == 'previous' and n.attr == 'projection':
                    n.value.id = '__projection_module__'
            return next(n for n in ast.walk(tree) if isinstance(n, ast.While))
        old = loop(original.run)
        new = loop(candidate.run)
        class Normalize(ast.NodeTransformer):
            def visit_Attribute(self, node):
                if isinstance(node.value, ast.Name) and node.value.id == '__projection_module__':
                    return ast.Name(id='projection', ctx=ast.Load())
                return self.generic_visit(node)
        self.assertEqual(ast.dump(old), ast.dump(Normalize().visit(new)))


class ContinuationTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.predecessor = Path(self.tmp.name) / 'io-v2.json'
        self.prior = dict(directory='/synthetic/new-pair-only', activation='original', source='same-source',
                          book='same-book', continuation='old-io-receipt')
        self.predecessor.write_text(json.dumps(self.prior))
        self.config = dict(self.prior, io_predecessor_configuration=str(self.predecessor), latency_continuation='new-receipt')
        self.activation = dict(original_identity='preserved')
        self.receipt = dict(scope='AUTHORIZED_PAPER_PAIR_LATENCY_CONTINUATION',
            prior_activation_sha256=digest(self.activation), directory=self.prior['directory'],
            predecessor_configuration_sha256=hashlib.sha256(self.predecessor.read_bytes()).hexdigest(),
            strategy_unchanged=True, state_reset_allowed=False, real_orders=False,
            exchange_credentials=False, operational_grants=False, operator_acceptance_reference='synthetic test only',
            runtime_files={n:hashlib.sha256((LAB/n).read_bytes()).hexdigest()
                           for n in ('btc_intraday_pair_latency.py', 'btc_intraday_pair_latency_live.py')})

    def authorize(self):
        with patch.object(original, 'authorized', return_value=self.activation), patch.object(candidate, 'root_document',
                side_effect=lambda p: self.receipt if str(p) == 'new-receipt' else self.prior):
            return candidate.authorized(self.config)

    def test_original_activation_identity_preserved(self):
        self.assertIs(self.authorize(), self.activation)

    def test_old_custody_denial_cannot_be_bypassed(self):
        with patch.object(original, 'authorized', side_effect=ValueError('old pin denied')):
            with self.assertRaisesRegex(ValueError, 'old pin denied'):
                candidate.authorized(self.config)

    def test_reset_grants_wrong_scope_or_runtime_pins_denied(self):
        baseline = copy.deepcopy(self.receipt)
        for k, value in [('strategy_unchanged', False), ('state_reset_allowed', True), ('real_orders', True),
                         ('exchange_credentials', True), ('operational_grants', True), ('directory', 'other'),
                         ('scope', 'other'), ('operator_acceptance_reference', ''), ('prior_activation_sha256', 'bad')]:
            self.receipt = copy.deepcopy(baseline)
            self.receipt[k] = value
            with self.subTest(field=k), self.assertRaises(ValueError):
                self.authorize()
        self.receipt = copy.deepcopy(baseline)
        self.receipt['runtime_files']['btc_intraday_pair_latency.py'] = '0' * 64
        with self.assertRaisesRegex(ValueError, 'pin_mismatch'):
            self.authorize()

    def test_no_source_or_configuration_changes_allowed(self):
        for k in self.prior:
            old = self.config[k]
            self.config[k] = 'different'
            with self.subTest(field=k), self.assertRaises(ValueError):
                self.authorize()
            self.config[k] = old
        self.config['unexpected'] = True
        with self.assertRaises(ValueError):
            self.authorize()


class PersistenceTests(unittest.TestCase):
    def test_100ms_commit_exposes_same_rows_without_retimestamping(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            stores = []
            try:
                for name, interval in [('old', 1.0), ('new', .1)]:
                    config = collector.ScalpingObserverConfig(root / (name + '.sqlite'), root / (name + '.json'),
                                                             commit_interval_seconds=interval)
                    stores.append(collector.ScalpingStore(config, 'same-synthetic-session'))
                for s in stores:
                    s.last_commit_monotonic = 0
                stamp = 1_800_000_000_000_000_000
                for sequence, elapsed in enumerate((.11, .22, .33), 1):
                    message = dict(type='message', subject='level2', topic='/contractMarket/level2Depth5:XBTUSDTM', data=dict(sequence=sequence,
                        timestamp=(stamp + sequence * 100_000_000) // 1_000_000,
                        bids=[[str(100 - i / 10), '10'] for i in range(5)],
                        asks=[[str(101 + i / 10), '10'] for i in range(5)]))
                    event = collector.parse_book_message(message, stamp + sequence * 100_000_000 + 20_000_000)
                    for s in stores:
                        self.assertTrue(s.record_book(event))
                        with patch.object(collector.time, 'monotonic', return_value=elapsed):
                            s.commit_if_due()
                    with sqlite3.connect(stores[0].config.database_path) as a, sqlite3.connect(stores[1].config.database_path) as b:
                        self.assertEqual(a.execute('SELECT COUNT(*) FROM book_events').fetchone()[0], 0)
                        self.assertEqual(b.execute('SELECT COUNT(*) FROM book_events').fetchone()[0], sequence)
                for s in stores:
                    s.commit_if_due(force=True)
                with sqlite3.connect(stores[0].config.database_path) as a, sqlite3.connect(stores[1].config.database_path) as b:
                    self.assertEqual(a.execute('SELECT * FROM book_events ORDER BY id').fetchall(),
                                     b.execute('SELECT * FROM book_events ORDER BY id').fetchall())
                    self.assertEqual(a.execute('SELECT * FROM second_buckets ORDER BY bucket_ts_s').fetchall(),
                                     b.execute('SELECT * FROM second_buckets ORDER BY bucket_ts_s').fetchall())
            finally:
                for s in stores:
                    s.close('completed', 'offline persistence test')


class ManualDeployGateTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        for name in ('repo', 'release', 'config', 'state', 'runtime'):
            (self.root / name).mkdir()
        (self.root / 'repo/docker-compose.local.yml').touch()
        (self.root / 'runtime/files.sha256').touch()
        manifest = dict(scope='PREPARED_INTRADAY_LATENCY_NOT_DEPLOYED', runtime=str(self.root / 'runtime'),
            runtime_files={}, checksum_file_sha256=installer.sha(self.root / 'runtime/files.sha256'),
            compose_files={}, base_compose_sha256=installer.sha(self.root / 'repo/docker-compose.local.yml'),
            activation_helper_sha256=installer.sha(Path(installer.__file__)),
            preserved_configuration_files={}, stage_files={}, image_id='fixture-image')
        (self.root / 'release/manifest.json').write_text(json.dumps(manifest))
        self.digest = installer.sha(self.root / 'release/manifest.json')

    def invoke(self, states=None, manual=False, pin=None):
        args = ['installer', '--manifest-sha256', pin or self.digest]
        if manual:
            args += ['--manual-operator-deploy', '--operator-reference', 'fixture-only explicit technical consent']
        with patch.object(installer, 'ROOT', self.root), patch.object(installer, 'REPO', self.root / 'repo'), \
             patch.object(installer, 'RELEASE', self.root / 'release'), patch.object(installer, 'CONFIG', self.root / 'config'), \
             patch.object(installer, 'STATE', self.root / 'state'), patch.object(sys, 'argv', args), \
             patch.object(installer.os, 'geteuid', return_value=0), \
             patch.object(installer.shutil, 'disk_usage', return_value=type('Disk', (), {'free':100 * 2**30})()), \
             patch.object(installer, 'account_states', return_value=states) as read, \
             patch.object(installer, 'run', return_value='fixture-image') as command:
            error = None
            try:
                installer.main()
            except AssertionError as caught:
                error = str(caught)
            return read, command, error

    def test_default_mode_checks_artifact_without_reading_or_stopping_accounts(self):
        read, command, error = self.invoke()
        self.assertIsNone(error)
        read.assert_not_called()
        self.assertTrue(all(call.args[:2] == ('docker', 'inspect') for call in command.call_args_list))

    def test_wrong_exact_manifest_stops_before_runtime_or_docker(self):
        read, command, error = self.invoke(pin='0' * 64)
        self.assertIn('exact_root_release', error)
        read.assert_not_called()
        command.assert_not_called()

    def test_open_position_or_pending_intent_never_stops_services(self):
        for state in ({'q':-.01, 'pending':None}, {'q':0, 'pending':{'kind':'ENTRY'}}):
            _, command, error = self.invoke(states={a:state for a in installer.ARMS}, manual=True)
            self.assertIn('wait_pair_flat_no_pending', error)
            self.assertTrue(all(call.args[:2] == ('docker', 'inspect') for call in command.call_args_list))

    def test_existing_continuation_cannot_be_deployed_again(self):
        (self.root / 'config/config-latency-v1.json').touch()
        read, command, error = self.invoke(manual=True)
        self.assertIn('no_repeated_deploy', error)
        read.assert_not_called()
        self.assertTrue(all(call.args[:2] == ('docker', 'inspect') for call in command.call_args_list))


if __name__ == '__main__':
    unittest.main()
