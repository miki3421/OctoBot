"""Original V13 portfolio executor: isolated synthetic architecture only.

Work card: work-card-9be311a0-d1b3-4350-8931-639d8240eb4f.
No operational mode, credential, grant writer, strategy callback or daemon.
Approvals are read-only; only the executor owns claims and economic storage.
"""
from __future__ import annotations

import argparse
import copy
from contextlib import ExitStack, closing
import datetime as dt
import fcntl
import hashlib
import math
import os
from pathlib import Path
import sqlite3
import stat
import sys

from octobot.ai_strategy_lab import paper_authorization as auth
from octobot.ai_strategy_lab import paper_runtime_authorization as wiring
from octobot.ai_strategy_lab import v13_exposure as exposure
from octobot.ai_strategy_lab import v13_market as market
from octobot.ai_strategy_lab import v13_market_sanity as sanity
from octobot.ai_strategy_lab import v13_original_issuer as issuer
from octobot.ai_strategy_lab import v13_original_portfolio as p
from octobot.ai_strategy_lab import v13_paper_v2 as paper

FIXTURE = issuer.FIXTURE
INTENT_FIELDS = {'schema_version', 'intent_id', 'account', 'account_epoch',
                 'execution_binding_ref', 'proposal_id', 'approval_id', 'receipt_hash'}
TABLES = {
    'execution_namespace': 'CREATE TABLE execution_namespace (key TEXT PRIMARY KEY, value TEXT NOT NULL)',
    'received_intents': '''CREATE TABLE received_intents (
        intent_id TEXT PRIMARY KEY, payload TEXT NOT NULL, payload_hash TEXT NOT NULL,
        received_at TEXT NOT NULL)''',
    'portfolio_attempts': '''CREATE TABLE portfolio_attempts (
        proposal_id TEXT PRIMARY KEY, intent_id TEXT NOT NULL UNIQUE,
        started_at TEXT NOT NULL, status TEXT NOT NULL CHECK(status IN ('STARTED','COMMITTED','DENIED')))''',
    'portfolio_claims': '''CREATE TABLE portfolio_claims (
        approval_id TEXT PRIMARY KEY, proposal_id TEXT NOT NULL UNIQUE,
        intent_id TEXT NOT NULL UNIQUE, account TEXT NOT NULL, account_epoch TEXT NOT NULL,
        binding_ref TEXT NOT NULL, source_record_hash TEXT NOT NULL, source_bar_date TEXT NOT NULL,
        claimed_at TEXT NOT NULL, global_claim_required INTEGER NOT NULL CHECK(global_claim_required IN (0,1)),
        status TEXT NOT NULL CHECK(status IN ('RESERVED','COMMITTED','DENIED')),
        UNIQUE(account,account_epoch,binding_ref,source_record_hash),
        UNIQUE(account,account_epoch,binding_ref,source_bar_date))''',
    'portfolio_batches': '''CREATE TABLE portfolio_batches (
        proposal_id TEXT PRIMARY KEY, approval_id TEXT NOT NULL UNIQUE,
        intent_id TEXT NOT NULL UNIQUE, committed_at TEXT NOT NULL,
        source_bar_date TEXT NOT NULL, market_hash TEXT NOT NULL,
        state_before_hash TEXT NOT NULL, state_after_hash TEXT NOT NULL,
        new_risk INTEGER NOT NULL, result TEXT NOT NULL)''',
    'execution_events': '''CREATE TABLE execution_events (
        id INTEGER PRIMARY KEY, event_at TEXT NOT NULL, intent_id TEXT,
        status TEXT NOT NULL, reason TEXT NOT NULL)''',
}
ECONOMIC_TABLES = {'account_version', 'state', 'orders', 'equity_history', 'marks',
                   'funding_events', 'market_events', 'risk_events', 'intents'}
AUDIT_TABLES = {
    'audit_namespace':'CREATE TABLE audit_namespace (key TEXT PRIMARY KEY, value TEXT NOT NULL)',
    'claims':'CREATE TABLE claims(account TEXT, entry_id TEXT, payload TEXT NOT NULL, PRIMARY KEY(account,entry_id))',
    'checks':'CREATE TABLE checks(id INTEGER PRIMARY KEY, payload TEXT NOT NULL)',
}


def component_files(repo):
    modules = {'executor': sys.modules[__name__], 'adapter': p, 'issuer': issuer,
               'paper': paper, 'market': market, 'P0_03': sanity, 'P0_02': exposure,
               'P0_04': auth, 'runtime_wiring': wiring, 'upstream': paper.upstream}
    return {**{name: Path(module.__file__) for name, module in modules.items()},
            'verifier': Path(repo)/'octobot/ai_strategy_lab/v13_original_verify.py'}


def _reason(error):
    if isinstance(error, auth.Denied):
        return error.code
    if isinstance(error, sqlite3.Error):
        return 'authorization_storage_failure'
    if isinstance(error, p.Rejected):
        return str(error).split(':', 1)[0]
    if isinstance(error, sanity.Veto):
        return str(error)
    if 'funding' in str(error):
        return 'funding_coverage_or_cursor_failure'
    return 'execution_validation_failure'


def _owned_path(path, config, *, exists=True):
    path = issuer._inside(path, config['sandbox_root'])
    if 'octobot-local' in path.resolve().parts:
        raise p.Rejected('operational_path_forbidden')
    for ancestor in path.parents:
        if ancestor == Path(config['sandbox_root']):
            break
        info = ancestor.lstat()
        if (not stat.S_ISDIR(info.st_mode) or info.st_uid not in (0, config['executor_uid'])
                or info.st_mode & 0o022):
            raise p.Rejected('unsafe_execution_parent')
    issuer._directory(path.parent, owner=config['executor_uid'])
    if path.parent.stat().st_mode & 0o077:
        raise p.Rejected('execution_directory_not_private')
    if exists:
        info = path.lstat()
        if (not stat.S_ISREG(info.st_mode) or info.st_uid != config['executor_uid']
                or info.st_mode & 0o077 or info.st_nlink != 1):
            raise p.Rejected('unsafe_execution_storage')
    return path


class Executor:
    def __init__(self, config_path, *, expected_config_sha256):
        self.path = Path(config_path).absolute()
        self.pin = p.require_hash(expected_config_sha256)
        info = self.path.lstat()
        if (not stat.S_ISREG(info.st_mode) or info.st_uid != 0 or info.st_mode & 0o022
                or info.st_nlink != 1):
            raise p.Rejected('executor_config_not_root_pinned')
        raw = self.path.read_bytes()
        if hashlib.sha256(raw).hexdigest() != self.pin:
            raise p.Rejected('executor_config_hash_mismatch')
        self.config = p.read_json(raw)
        self._config()
        self.contract, self.schema = p.load_contract(self.config['repo_root'])
        self.db_path = issuer._inside(self.config['execution_db'], self.config['sandbox_root'])
        if self.db_path.name != 'execution.sqlite':
            raise p.Rejected('execution_store_name')

    def _root_json(self, descriptor):
        return p.read_json(issuer._trusted_bytes(descriptor['path'], owner=0,
            root=self.config['sandbox_root'], expected_hash=descriptor['file_sha256']))

    def _config(self):
        c = self.config
        if (type(c.get('schema_version')) is not int or c['schema_version'] != 1
                or c.get('mode') != 'architecture_fixture' or c.get('scope') != FIXTURE):
            raise p.Rejected('no_operational_executor_mode')
        if (type(c['executor_uid']) is not int or c['executor_uid'] <= 0
                or os.geteuid() != c['executor_uid'] or os.getegid() != c['executor_gid']):
            raise p.Rejected('executor_identity_invalid')
        issuer._trusted_bytes(self.path, owner=0, root=c['sandbox_root'], expected_hash=self.pin)
        marker = issuer._trusted_bytes(Path(c['sandbox_root'])/'sandbox.marker', owner=0, root=c['sandbox_root'])
        if marker != issuer.MARKER or 'octobot-local' in Path(c['sandbox_root']).resolve().parts:
            raise p.Rejected('isolated_sandbox_required')
        files = component_files(c['repo_root'])
        if set(files) != set(c['component_hashes']):
            raise p.Rejected('executor_bundle_incomplete')
        for name, path in files.items():
            if hashlib.sha256(path.read_bytes()).hexdigest() != p.require_hash(c['component_hashes'][name]):
                raise p.Rejected('executor_component_changed')
        self.issuer_config = self._root_json(c['issuer_config'])
        ic = self.issuer_config
        if (ic.get('mode') != 'architecture_fixture' or ic.get('fixture_label') != FIXTURE
                or ic['sandbox_root'] != c['sandbox_root'] or ic['executor_gid'] != c['executor_gid']
                or ic['repo_root'] != c['repo_root']
                or len({c['executor_uid'], ic['issuer_uid'], ic['strategy_uid'], ic['verifier_uid']}) != 4
                or ic['component_hashes'] != {k:c['component_hashes'][k] for k in ('adapter', 'issuer', 'verifier')}):
            raise p.Rejected('issuer_binding_not_fixture')
        self.policy = self._root_json(ic['fixture_policy'])
        if (self.policy.get('scope') != FIXTURE or self.policy.get('scientific_certified') is not False
                or not isinstance(self.policy.get('version'), str) or not self.policy['version']
                or any(type(self.policy.get(k)) not in (int, float) or not math.isfinite(self.policy[k])
                       or self.policy[k] <= 0 for k in ('daily_loss', 'drawdown', 'order_frequency', 'cooldown'))
                or not 0 < self.policy['daily_loss'] < 1 or not 0 < self.policy['drawdown'] < 1
                or type(self.policy['order_frequency']) is not int):
            raise p.Rejected('fixture_risk_policy_incomplete')
        self.gate_policy = dict(self.policy, per_asset_exposure=paper.MAX_ASSET,
                                gross_exposure=paper.MAX_GROSS, missing_gates=[])
        self.identity = auth.Identity(**c['fixture_identity'])
        self.identity.validate()
        if (self.identity.account != ic['fixture_binding']['account']
                or self.identity.strategy != 'v13-original-portfolio-fixture'
                or self.identity.lineage_hash != self._root_contract_lineage()
                or self.identity.risk_policy != self.policy['version']
                or self.identity.risk_policy_hash != auth.digest(self.gate_policy)
                or not self.identity.authorization_id.startswith('fixture:')):
            raise p.Rejected('fixture_control_binding_invalid')
        p.require_hash(c['store_id'])
        for name in ('control_root',):
            root = issuer._inside(c[name], c['sandbox_root'])
            issuer._directory(root, owner=0)
            issuer._trusted_bytes(root/'registry.json', owner=0, root=c['sandbox_root'])
            issuer._trusted_bytes(root/'gate.lock', owner=0, root=c['sandbox_root'])

    def _root_contract_lineage(self):
        return p.load_contract(self.config['repo_root'])[0]['scientific_lineage_ref']

    def _namespace(self):
        return {'version':'v13-original-execution-fixture-v1', 'store_id':self.config['store_id'],
            'executor_config_sha256':self.pin, 'scope':FIXTURE,
            'account':self.identity.account, 'account_epoch':self.issuer_config['fixture_binding']['account_epoch'],
            'binding_ref':p.digest(self.issuer_config['fixture_binding'])}

    def initialize(self):
        self._config()
        path = _owned_path(self.db_path, self.config, exists=False)
        baseline = self._root_json(self.config['fixture_baseline'])
        if baseline.get('scope') != FIXTURE or baseline.get('kind') != 'synthetic_account_baseline_v1':
            raise p.Rejected('real_account_migration_not_implemented')
        state = baseline['state']
        self._state_valid(state)
        if state['order_count'] != 0 or state.get('pending') is not None or state.get('executed_targets') is not None:
            raise p.Rejected('fixture_baseline_not_pristine')
        fd = os.open(path, os.O_WRONLY|os.O_CREAT|os.O_EXCL|os.O_NOFOLLOW, 0o600)
        os.close(fd)
        audit_path = _owned_path(self.config['consumer_audit'], self.config, exists=False)
        if audit_path == path:
            raise p.Rejected('distinct_audit_storage_required')
        audit_fd = os.open(audit_path, os.O_WRONLY|os.O_CREAT|os.O_EXCL|os.O_NOFOLLOW, 0o600)
        os.close(audit_fd)
        with closing(sqlite3.connect(audit_path)) as audit:
            audit.execute('PRAGMA journal_mode=DELETE')
            audit.execute('PRAGMA synchronous=FULL')
            audit.execute('BEGIN IMMEDIATE')
            for ddl in AUDIT_TABLES.values():
                audit.execute(ddl)
            audit.executemany('INSERT INTO audit_namespace VALUES (?,?)', self._namespace().items())
            audit.commit()
        with closing(paper.init_db(path)) as db:
            db.execute('PRAGMA journal_mode=DELETE')
            db.execute('PRAGMA synchronous=FULL')
            db.execute('BEGIN IMMEDIATE')
            for ddl in TABLES.values():
                db.execute(ddl)
            db.executemany('INSERT INTO execution_namespace VALUES (?,?)', self._namespace().items())
            db.execute('INSERT INTO state VALUES (1,?)', (p.canonical_bytes(state).decode(),))
            totals = paper.totals(state, require_positive=False)
            db.execute('INSERT INTO equity_history VALUES (?,?,?)',
                       (state['activation_at'], totals['equity'], totals['pnl']))
            db.execute('PRAGMA user_version=1')
            db.commit()
        _owned_path(path, self.config)
        fd = os.open(path.parent, os.O_RDONLY|os.O_DIRECTORY)
        try:
            os.fsync(fd)
        finally:
            os.close(fd)

    def _open(self):
        _owned_path(self.db_path, self.config)
        self._audit_store()
        db = sqlite3.connect(self.db_path.as_uri()+'?mode=rw', uri=True, timeout=0)
        try:
            db.execute('PRAGMA trusted_schema=OFF')
            db.execute('PRAGMA synchronous=FULL')
            if db.execute('PRAGMA journal_mode').fetchone()[0] != 'delete':
                raise p.Rejected('execution_journal_mode')
            if db.execute('PRAGMA integrity_check').fetchall() != [('ok',)]:
                raise p.Rejected('execution_integrity_failure')
            schema = dict(db.execute("SELECT name,sql FROM sqlite_master WHERE type='table'"))
            normalize = lambda value:' '.join(value.split())
            if (set(schema) != ECONOMIC_TABLES|set(TABLES)
                    or any(normalize(schema[k]) != normalize(TABLES[k]) for k in TABLES)
                    or db.execute("SELECT count(*) FROM sqlite_master WHERE type IN ('view','trigger')").fetchone()[0]
                    or db.execute('PRAGMA user_version').fetchone()[0] != 1
                    or dict(db.execute('SELECT key,value FROM execution_namespace')) != self._namespace()
                    or db.execute('SELECT mode FROM account_version').fetchall() != [(paper.MODE,)]):
                raise p.Rejected('execution_store_identity_or_schema')
            return db
        except BaseException:
            db.close()
            raise

    def _audit_store(self):
        path = _owned_path(self.config['consumer_audit'], self.config)
        with closing(sqlite3.connect(path.as_uri()+'?mode=ro', uri=True, timeout=0)) as db:
            db.execute('PRAGMA query_only=ON')
            db.execute('PRAGMA trusted_schema=OFF')
            schema = dict(db.execute("SELECT name,sql FROM sqlite_master WHERE type='table'"))
            normalize = lambda value:' '.join(value.split())
            if (set(schema) != set(AUDIT_TABLES) or any(normalize(schema[k]) != normalize(AUDIT_TABLES[k]) for k in AUDIT_TABLES)
                    or db.execute('PRAGMA journal_mode').fetchone()[0] != 'delete'
                    or db.execute('PRAGMA integrity_check').fetchall() != [('ok',)]
                    or dict(db.execute('SELECT key,value FROM audit_namespace')) != self._namespace()
                    or db.execute("SELECT count(*) FROM sqlite_master WHERE type IN ('view','trigger')").fetchone()[0]):
                raise p.Rejected('P004_audit_schema_or_identity')
            return dict(db.execute('SELECT entry_id,payload FROM claims WHERE account=?', (self.identity.account,)))

    def _lock(self, stack):
        self._config()
        path = _owned_path(self.config['account_lock'], self.config, exists=False)
        fd = os.open(path, os.O_RDWR|os.O_CREAT|os.O_NOFOLLOW, 0o600)
        stream = stack.enter_context(os.fdopen(fd, 'a+'))
        _owned_path(path, self.config)
        fcntl.flock(stream, fcntl.LOCK_EX|fcntl.LOCK_NB)

    def _state_valid(self, state):
        if state.get('mode') != paper.MODE or state.get('pending') is not None:
            raise p.Rejected('unreconciled_account_state')
        if not set(state['positions']) <= set(p.load_contract(self.config['repo_root'])[0]['universe']):
            raise p.Rejected('unexpected_held_symbol')
        if (type(state['order_count']) is not int or state['order_count'] < 0
                or type(state['initial_equity']) not in (int, float) or state['initial_equity'] <= 0):
            raise p.Rejected('invalid_account_baseline')
        p.timestamp(state['activation_at'])
        exposure.quantities_and_marks(state)
        paper.totals(state, require_positive=False)
        for position in state['positions'].values():
            if position.get('last_mark_at') is not None:
                p.timestamp(position['last_mark_at'])
            if position['quantity'] and (position.get('last_mark_at') is None
                    or not isinstance(position.get('position_id'), str)
                    or type(position.get('position_generation')) is not int or position['position_generation'] <= 0):
                raise p.Rejected('position_identity_or_cursor_missing')

    def _event(self, db, now, intent_id, status, reason):
        db.execute('INSERT INTO execution_events(event_at,intent_id,status,reason) VALUES (?,?,?,?)',
                   (now, intent_id, status, reason))

    def _deny(self, now, intent_id, reason, *, reserved=False, commit_uncertain=False):
        with closing(self._open()) as db:
            db.execute('BEGIN IMMEDIATE')
            if commit_uncertain:
                row = db.execute('SELECT result FROM portfolio_batches WHERE intent_id=?', (intent_id,)).fetchone()
                if row:
                    receipt = p.read_json(row[0])
                    p.check_receipt(receipt, receipt['receipt_hash'])
                    self._event(db, now, intent_id, 'COMMIT_CONFIRMED', 'durable_commit_read_back_after_error')
                    db.commit()
                    return {'status':'COMMIT_CONFIRMED', 'receipt':receipt, 'orders':receipt['orders'],
                            'scope':FIXTURE, 'operational_execution':False}
            if reserved:
                db.execute("UPDATE portfolio_claims SET status='DENIED' WHERE intent_id=? AND status='RESERVED'", (intent_id,))
            db.execute("UPDATE portfolio_attempts SET status='DENIED' WHERE intent_id=? AND status='STARTED'", (intent_id,))
            self._event(db, now, intent_id, 'DENY', reason)
            db.commit()
        return {'status':'DENY', 'reason':reason, 'persisted':True, 'orders':0,
                'scope':FIXTURE, 'operational_execution':False}

    def _validate_intent(self, intent):
        if (not isinstance(intent, dict) or set(intent) != INTENT_FIELDS
                or type(intent['schema_version']) is not int or intent['schema_version'] != 1):
            raise p.Rejected('portfolio_intent_schema')
        for key in INTENT_FIELDS-{'schema_version', 'account'}:
            p.require_hash(intent[key])
        if (intent['account'] != self.identity.account
                or intent['account_epoch'] != self.issuer_config['fixture_binding']['account_epoch']
                or intent['execution_binding_ref'] != p.digest(self.issuer_config['fixture_binding'])):
            raise p.Rejected('intent_account_epoch_binding_mismatch')

    def _approval(self, intent, now):
        self._validate_intent(intent)
        ic = self.issuer_config
        store = issuer.ApprovalStore(ic)
        store._check_file()
        with closing(sqlite3.connect(store.path.as_uri()+'?mode=ro', uri=True, timeout=0)) as db:
            db.execute('PRAGMA query_only=ON')
            db.execute('PRAGMA trusted_schema=OFF')
            tables = dict(db.execute("SELECT name,sql FROM sqlite_master WHERE type='table'"))
            normalize = lambda value:' '.join(value.split())
            if (db.execute('PRAGMA journal_mode').fetchone()[0] != 'delete'
                    or db.execute('PRAGMA integrity_check').fetchall() != [('ok',)]
                    or set(tables) != set(issuer.TABLES)
                    or any(normalize(tables[k]) != normalize(issuer.TABLES[k]) for k in issuer.TABLES)
                    or db.execute("SELECT count(*) FROM sqlite_master WHERE type IN ('view','trigger')").fetchone()[0]
                    or dict(db.execute('SELECT key,value FROM store_metadata')) != {
                        'schema_version':'1', 'store_id':ic['store_id'], 'mode':'architecture_fixture', 'fixture_label':FIXTURE}):
                raise p.Rejected('approval_store_schema_or_identity')
            row = db.execute('SELECT * FROM approvals WHERE approval_id=?', (intent['approval_id'],)).fetchone()
            newest = db.execute('SELECT MAX(source_bar_date) FROM approvals WHERE account=? AND account_epoch=? AND binding_ref=?',
                (intent['account'], intent['account_epoch'], intent['execution_binding_ref'])).fetchone()[0]
        if row is None:
            raise p.Rejected('portfolio_approval_missing')
        receipt = p.read_json(row[-1])
        p.check_receipt(receipt, intent['receipt_hash'])
        proposal = receipt['proposal']
        p.validate_proposal(proposal, self.contract, self.schema, checked_at=now)
        if (tuple(row[:-1]) != (receipt['approval_id'], proposal['proposal_id'], proposal['account'],
                proposal['account_epoch'], proposal['execution_binding_ref'], proposal['source_record_hash'],
                proposal['source_bar_date'], p.digest(proposal))
                or receipt['approval_id'] != intent['approval_id'] or proposal['proposal_id'] != intent['proposal_id']
                or proposal['account_epoch'] != intent['account_epoch']
                or proposal['execution_binding_ref'] != intent['execution_binding_ref']
                or receipt.get('scope') != FIXTURE or receipt.get('operational_approval') is not False
                or receipt.get('scientific_certified') is not False or receipt.get('kucoin_order_admissibility_proven') is not False
                or receipt.get('result') != 'APPROVE' or receipt['proposal_hash'] != p.digest(proposal)
                or receipt['issuer_config_sha256'] != self.config['issuer_config']['file_sha256']
                or receipt['component_hashes'] != ic['component_hashes']
                or receipt['candidate_contract_sha256'] != p.CONTRACT_SHA256
                or receipt['proposal_schema_sha256'] != p.SCHEMA_SHA256
                or receipt['risk_policy_sha256'] != ic['fixture_policy']['file_sha256']
                or receipt['risk_policy_version'] != self.policy['version']
                or receipt['admissibility_contract_sha256'] != ic['fixture_admissibility']['file_sha256']
                or receipt['fixture_binding_sha256'] != intent['execution_binding_ref']):
            raise p.Rejected('portfolio_approval_mismatch')
        if not p.timestamp(proposal['proposal_timestamp']) <= p.timestamp(receipt['approved_at']) <= p.timestamp(now) < p.timestamp(receipt['expires_at']):
            raise p.Rejected('portfolio_approval_expired_or_future')
        if newest != proposal['source_bar_date']:
            raise p.Rejected('source_slot_superseded')
        return receipt

    def _ready(self, db, now):
        latest = db.execute('SELECT MAX(event_at) FROM execution_events').fetchone()[0]
        if latest and p.timestamp(now) < p.timestamp(latest):
            raise p.Rejected('executor_clock_regression')
        if db.execute("SELECT 1 FROM portfolio_claims WHERE status='RESERVED'").fetchone():
            raise p.Rejected('unresolved_reservation_reconciliation_required')
        if db.execute("SELECT 1 FROM portfolio_attempts WHERE status='STARTED'").fetchone():
            raise p.Rejected('unresolved_P004_attempt_reconciliation_required')
        audit = self._audit_store()
        for proposal_id, in db.execute('SELECT proposal_id FROM portfolio_claims WHERE global_claim_required=1'):
            if proposal_id not in audit:
                raise p.Rejected('restore_P004_claim_mismatch')
            claim = p.read_json(audit[proposal_id])
            if claim.get('identity') != auth.asdict(self.identity) or claim.get('result') != 'GLOBAL_CLAIM':
                raise p.Rejected('restore_P004_claim_mismatch')

    def receive(self, intent_path, *, checked_at=None):
        now = p.timestamp(checked_at).isoformat() if checked_at else dt.datetime.now(p.UTC).isoformat()
        intent_id = None
        with ExitStack() as stack:
            self._lock(stack)
            try:
                intent = p.read_json(issuer._trusted_bytes(intent_path, owner=self.issuer_config['strategy_uid'], root=self.config['sandbox_root']))
                self._validate_intent(intent)
                intent_id = intent['intent_id']
                self._approval(intent, now)
                with closing(self._open()) as db:
                    db.execute('BEGIN IMMEDIATE')
                    self._ready(db, now)
                    row = db.execute('SELECT payload_hash,received_at FROM received_intents WHERE intent_id=?', (intent_id,)).fetchone()
                    if row and row[0] != p.digest(intent):
                        raise p.Rejected('intent_id_conflict')
                    if not row:
                        db.execute('INSERT INTO received_intents VALUES (?,?,?,?)',
                            (intent_id, p.canonical_bytes(intent).decode(), p.digest(intent), now))
                    self._event(db, now, intent_id, 'RECEIVED' if not row else 'DUPLICATE_INTENT', 'no_authorization_consumed')
                    db.commit()
                return {'status':'RECEIVED', 'received_at':row[1] if row else now, 'intent_id':intent_id,
                        'scope':FIXTURE, 'operational_execution':False}
            except (ValueError, OSError, sqlite3.Error, KeyError, TypeError) as error:
                return self._deny(now, intent_id, _reason(error))

    def _begin_global_attempt(self, intent, now):
        with closing(self._open()) as db:
            db.execute('BEGIN IMMEDIATE')
            self._ready(db, now)
            if db.execute('SELECT 1 FROM portfolio_attempts WHERE proposal_id=?', (intent['proposal_id'],)).fetchone():
                raise p.Rejected('portfolio_global_attempt_consumed')
            db.execute('INSERT INTO portfolio_attempts VALUES (?,?,?,?)', (intent['proposal_id'],intent['intent_id'],now,'STARTED'))
            self._event(db, now, intent['intent_id'], 'P004_ATTEMPT', 'durable_attempt_not_an_authorization')
            db.commit()

    def _reserve(self, intent, proposal, now, *, global_claim_required=False):
        with closing(self._open()) as db:
            db.execute('BEGIN IMMEDIATE')
            if global_claim_required:
                attempt = db.execute('SELECT intent_id,status FROM portfolio_attempts WHERE proposal_id=?', (intent['proposal_id'],)).fetchone()
                if attempt != (intent['intent_id'],'STARTED'):
                    raise p.Rejected('durable_P004_attempt_missing')
            else:
                self._ready(db, now)
            if db.execute('SELECT 1 FROM portfolio_claims WHERE approval_id=? OR proposal_id=? OR intent_id=?',
                    (intent['approval_id'], intent['proposal_id'], intent['intent_id'])).fetchone():
                raise p.Rejected('portfolio_approval_consumed')
            db.execute('INSERT INTO portfolio_claims VALUES (?,?,?,?,?,?,?,?,?,?,?)',
                (intent['approval_id'], intent['proposal_id'], intent['intent_id'], intent['account'], intent['account_epoch'],
                 intent['execution_binding_ref'], proposal['source_record_hash'], proposal['source_bar_date'], now, int(global_claim_required), 'RESERVED'))
            self._event(db, now, intent['intent_id'], 'RESERVED', 'durable_P0_01_consumption')
            db.commit()

    def _risk_policy(self, db, marked, candidate, now):
        instant = p.timestamp(now)
        midnight = dt.datetime.combine(instant.date(), dt.time(), p.UTC).isoformat()
        opening = db.execute('SELECT equity FROM equity_history WHERE bar>=? ORDER BY bar LIMIT 1', (midnight,)).fetchone()
        prior = db.execute('SELECT equity FROM equity_history ORDER BY bar DESC LIMIT 1').fetchone()
        reference = opening[0] if opening else prior[0]
        peak = db.execute('SELECT MAX(equity) FROM equity_history').fetchone()[0]
        equities = [paper.totals(s, require_positive=False)['equity'] for s in (marked, candidate)]
        if min(equities) < reference*(1-self.policy['daily_loss']):
            raise p.Rejected('fixture_daily_loss_limit')
        if min(equities) < max(peak, reference)*(1-self.policy['drawdown']):
            raise p.Rejected('fixture_drawdown_limit')
        count = db.execute('SELECT count(*) FROM portfolio_batches WHERE new_risk=1 AND committed_at>=?', (midnight,)).fetchone()[0]
        if count >= self.policy['order_frequency']:
            raise p.Rejected('fixture_batch_frequency_limit')
        latest = db.execute('SELECT MAX(committed_at) FROM portfolio_batches WHERE new_risk=1').fetchone()[0]
        if latest and (instant-p.timestamp(latest)).total_seconds() < self.policy['cooldown']:
            raise p.Rejected('fixture_cooldown_active')

    def execute(self, intent_id, *, market_id=None, checked_at=None):
        p.require_hash(intent_id)
        now = p.timestamp(checked_at).isoformat() if checked_at else dt.datetime.now(p.UTC).isoformat()
        reserved = False
        commit_started = False
        with ExitStack() as stack:
            self._lock(stack)
            try:
                with closing(self._open()) as db:
                    row = db.execute('SELECT payload,payload_hash,received_at FROM received_intents WHERE intent_id=?', (intent_id,)).fetchone()
                    if row is None:
                        raise p.Rejected('persisted_intent_missing')
                    intent = p.read_json(row[0])
                    if p.digest(intent) != row[1] or intent['intent_id'] != intent_id or p.timestamp(row[2]) > p.timestamp(now):
                        raise p.Rejected('persisted_intent_mismatch')
                    self._validate_intent(intent)
                    prior = db.execute('SELECT result FROM portfolio_batches WHERE proposal_id=?', (intent['proposal_id'],)).fetchone()
                    if prior:
                        result = p.read_json(prior[0])
                        p.check_receipt(result, result['receipt_hash'])
                        if result['approval_id'] != intent['approval_id'] or result['account_epoch'] != intent['account_epoch']:
                            raise p.Rejected('committed_batch_mismatch')
                        return {'status':'ALREADY_COMMITTED', 'receipt':result, 'orders':0,
                                'scope':FIXTURE, 'operational_execution':False}
                    self._ready(db, now)
                    if db.execute('SELECT 1 FROM portfolio_claims WHERE approval_id=? OR proposal_id=?', (intent['approval_id'], intent['proposal_id'])).fetchone():
                        raise p.Rejected('portfolio_approval_consumed')
                    if db.execute('SELECT 1 FROM portfolio_batches WHERE proposal_id=?', (intent['proposal_id'],)).fetchone():
                        raise p.Rejected('portfolio_batch_replay')
                    receipt = self._approval(intent, now)
                    proposal = receipt['proposal']
                    state = p.read_json(db.execute('SELECT payload FROM state WHERE id=1').fetchone()[0])
                    self._state_valid(state)
                    newest = db.execute('SELECT MAX(source_bar_date) FROM portfolio_batches').fetchone()[0]
                    if newest and proposal['source_bar_date'] <= newest:
                        raise p.Rejected('source_slot_superseded')
                    selected_market = p.require_hash(market_id or self.config['default_market_id'])
                    envelope = self._root_json(self.config['fixture_markets'][selected_market])
                    if envelope.get('scope') != FIXTURE or envelope.get('kind') != 'synthetic_market_snapshot_v1':
                        raise p.Rejected('fixture_market_required')
                    record = envelope['record']
                    market._validate_record(record, p.timestamp(now), market.MAX_QUOTE_AGE_SECONDS)
                    quotes = market.market_quotes(record, set(self.contract['universe']))
                    if (p.timestamp(record['observed_at_start']) < p.timestamp(row[2])
                            or any(p.timestamp(q['timestamp']) <= p.timestamp(row[2]) for q in quotes.values())):
                        raise p.Rejected('market_precedes_persisted_intent')
                    if state.get('last_market_at') and p.timestamp(record['observed_at_end']) <= p.timestamp(state['last_market_at']):
                        raise p.Rejected('market_not_increasing')
                    targets = {s:p.decode_weight(v) for s,v in proposal['targets'].items()}
                    noop = state.get('executed_targets') == targets
                    working = copy.deepcopy(state)
                    working['pending'] = None if noop else {'targets':targets, 'noticed_at':row[2], 'decision_hash':intent['proposal_id']}
                    marked = None
                    def scope(account, entry_id, **kwargs):
                        nonlocal reserved, marked
                        if account != intent['account'] or entry_id != intent['proposal_id']:
                            raise auth.Denied('entry_identity_invalid')
                        marked = copy.deepcopy(kwargs['marked_state'])
                        self._begin_global_attempt(intent, now)
                        def claim():
                            nonlocal reserved
                            self._approval(intent, now)
                            self._reserve(intent, proposal, now, global_claim_required=True)
                            reserved = True
                            return True
                        return auth.Registry(self.config['control_root'],
                            _owned_path(self.config['consumer_audit'], self.config, exists=False),
                            clock=lambda:p.timestamp(now)).entry(self.identity, intent['proposal_id'], self.gate_policy, claim)
                    candidate, fills, funding, marks = paper.process_market(working, record, quotes, p.timestamp(now),
                        authorization_stack=stack, authorization_scope=scope)
                    if candidate['risk']['action'] not in ('new_risk', 'risk_reduction', 'mark_only'):
                        raise p.Rejected(candidate['risk']['reason'] or 'portfolio_preflight_denied')
                    if not noop and candidate.get('pending') is not None:
                        raise p.Rejected('portfolio_plan_not_completed')
                    if not noop and not reserved:
                        # Certain strategy reductions still require one-shot P0-01.
                        self._reserve(intent, proposal, now)
                        reserved = True
                    new_risk = candidate['risk']['action'] == 'new_risk'
                    if new_risk:
                        self._risk_policy(db, marked, candidate, now)
                    for fill in fills:
                        old = state['positions'].get(fill['symbol'], {})
                        current = candidate['positions'][fill['symbol']]
                        if old.get('quantity', 0) == 0 and current['quantity'] != 0 or old.get('quantity', 0)*current['quantity'] < 0:
                            current['position_id'] = hashlib.sha256(os.urandom(32)).hexdigest()
                            current['position_generation'] = old.get('position_generation', 0)+1
                    self._state_valid(candidate)
                    candidate['last_bar'] = proposal['source_bar_date']
                    candidate['pending'] = None
                    db.execute('BEGIN IMMEDIATE')
                    for fill in fills:
                        keys = tuple(fill)
                        db.execute('INSERT INTO orders('+','.join(keys)+') VALUES ('+','.join('?' for _ in keys)+')', tuple(fill.values()))
                    db.executemany('INSERT INTO funding_events VALUES (?,?,?,?,?,?)', funding)
                    db.executemany('INSERT INTO marks VALUES (?,?,?)', marks)
                    db.execute('INSERT INTO market_events VALUES (?,?,?,?)',
                        (record['record_hash'], record['observed_at_end'], now, p.canonical_bytes(record).decode()))
                    db.execute('INSERT INTO risk_events VALUES (?,?)', (record['record_hash'], p.canonical_bytes(candidate['risk']).decode()))
                    db.execute('INSERT INTO intents VALUES (?,?,?,?,?)',
                        (intent['proposal_id'], row[2], proposal['source_bar_date'], p.canonical_bytes(targets).decode(), 'noop' if noop else 'executed'))
                    totals = paper.totals(candidate, require_positive=False)
                    db.execute('INSERT INTO equity_history VALUES (?,?,?)', (record['observed_at_end'], totals['equity'], totals['pnl']))
                    db.execute('UPDATE state SET payload=? WHERE id=1', (p.canonical_bytes(candidate).decode(),))
                    result = p.seal_receipt({'scope':FIXTURE, 'operational_execution':False, 'scientific_certified':False,
                        'kucoin_order_admissibility_proven':False, 'status':'NO_CHANGE' if noop else 'COMMITTED',
                        'proposal_id':intent['proposal_id'], 'approval_id':intent['approval_id'],
                        'intent_id':intent_id, 'intent_received_at':row[2], 'committed_at':now,
                        'executor_config_sha256':self.pin, 'orders':len(fills), 'market_hash':record['record_hash'],
                        'state_before_hash':p.digest(state), 'state_after_hash':p.digest(candidate),
                        'targets':proposal['targets'], 'account_epoch':intent['account_epoch']})
                    db.execute('INSERT INTO portfolio_batches VALUES (?,?,?,?,?,?,?,?,?,?)',
                        (intent['proposal_id'], intent['approval_id'], intent_id, now, proposal['source_bar_date'],
                         record['record_hash'], p.digest(state), p.digest(candidate), int(new_risk), p.canonical_bytes(result).decode()))
                    if reserved:
                        changed = db.execute("UPDATE portfolio_claims SET status='COMMITTED' WHERE intent_id=? AND status='RESERVED'", (intent_id,)).rowcount
                        if changed != 1:
                            raise p.Rejected('durable_reservation_missing')
                    db.execute("UPDATE portfolio_attempts SET status='COMMITTED' WHERE intent_id=? AND status='STARTED'", (intent_id,))
                    self._event(db, now, intent_id, result['status'], 'synthetic_atomic_commit')
                    commit_started = True
                    db.commit()  # P0-04 lease and exclusive account lock still held.
                return result
            except (ValueError, OSError, sqlite3.Error, KeyError, TypeError, ArithmeticError) as error:
                return self._deny(now, intent_id, _reason(error), reserved=reserved, commit_uncertain=commit_started)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--config', type=Path, required=True)
    parser.add_argument('--config-sha256', required=True)
    actions = parser.add_mutually_exclusive_group(required=True)
    actions.add_argument('--initialize-store', action='store_true')
    actions.add_argument('--receive-intent', type=Path)
    actions.add_argument('--execute-intent', type=str)
    parser.add_argument('--market-id', type=str)
    args = parser.parse_args(argv)
    try:
        executor = Executor(args.config, expected_config_sha256=args.config_sha256)
        if args.initialize_store:
            executor.initialize()
            result = {'status':'INITIALIZED', 'scope':FIXTURE, 'operational_execution':False}
        elif args.receive_intent:
            result = executor.receive(args.receive_intent)
        else:
            result = executor.execute(args.execute_intent, market_id=args.market_id)
        print(p.canonical_bytes(result).decode())
        return 1 if result['status'] == 'DENY' else 0
    except (ValueError, OSError, sqlite3.Error, KeyError, TypeError, ArithmeticError) as error:
        print(p.canonical_bytes({'status':'DENY', 'reason':_reason(error), 'persisted':False,
                                'scope':FIXTURE, 'operational_execution':False}).decode())
        return 2


if __name__ == '__main__':
    sys.exit(main())
