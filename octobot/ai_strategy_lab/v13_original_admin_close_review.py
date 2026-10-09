"""Inactive administrative reduction on a migration REVIEW copy only.

work-card-72a59034-fdee-494d-9d06-f996c5803088. No runtime entrypoint,
grant, strategy, issuer, market acquisition or operational account writer.
The privileged executor must supply external configuration/market/head pins.
"""
from __future__ import annotations

from contextlib import closing
import copy
import datetime as dt
from decimal import Decimal
import fcntl
import hashlib
import math
import os
from pathlib import Path
import socket
import sqlite3
import stat
import struct

from octobot.ai_strategy_lab import v13_original_migration as migration
from octobot.ai_strategy_lab import v13_original_portfolio as p
from octobot.ai_strategy_lab import v13_market as market
from octobot.ai_strategy_lab import v13_market_sanity as sanity
from octobot.ai_strategy_lab import v13_paper_v2 as paper

MODE = 'COPIED_ACCOUNT_ADMIN_REVIEW_ONLY'
MARKET_SCOPE = 'SYNTHETIC_ARCHITECTURE_ONLY'
FIELDS = {'schema_version', 'command_id', 'account', 'epoch_candidate', 'symbol',
          'position_id', 'generation', 'issued_at', 'expires_at', 'maximum_quantity_to_reduce'}
CONFIG_FIELDS = {'version', 'mode', 'runtime_admission', 'operational_apply', 'account',
    'epoch_candidate', 'manifest_sha256', 'bundle_name', 'executor_uid', 'executor_gid',
    'admin_uid', 'admin_gid', 'strategy_uid', 'channel_name', 'component_hashes'}
COMPONENTS = (Path(__file__).name, 'v13_original_migration.py', 'v13_original_portfolio.py',
              'v13_market.py', 'v13_market_sanity.py', 'v13_paper_v2.py')
TABLES = {
    'review_meta': 'CREATE TABLE review_meta (config_hash TEXT NOT NULL, initial_state TEXT NOT NULL, genesis TEXT NOT NULL)',
    'review_state': 'CREATE TABLE review_state (id INTEGER PRIMARY KEY CHECK(id=1), body TEXT NOT NULL)',
    'review_claims': 'CREATE TABLE review_claims (nonce TEXT PRIMARY KEY, command TEXT NOT NULL, status TEXT NOT NULL)',
    'review_events': 'CREATE TABLE review_events (seq INTEGER PRIMARY KEY, body TEXT NOT NULL, hash TEXT NOT NULL UNIQUE)',
}


def _json(value):
    return p.canonical_bytes(value).decode()


def _number(value, *, positive=False):
    if type(value) not in (int, float) or not math.isfinite(value) or (positive and value <= 0):
        raise p.Rejected('invalid_quantity_or_economic_number')
    return value


def _fsync(path):
    fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW)
    try:
        os.fsync(fd)
    finally:
        os.close(fd)


def _component_hashes():
    return {name: migration._hash(Path(__file__).parent/name) for name in COMPONENTS}


def review_config(bundle_name, manifest, manifest_sha256, *, executor_uid, executor_gid,
                  admin_uid, admin_gid, strategy_uid, channel_name='review-close.sock'):
    """Build an UNAPPROVED offline candidate, never an operational authorization."""
    return {'version': 1, 'mode': MODE, 'runtime_admission': False, 'operational_apply': False,
        'account': migration.ACCOUNT, 'epoch_candidate': manifest['epoch_candidate'],
        'manifest_sha256': manifest_sha256, 'bundle_name': bundle_name,
        'executor_uid': executor_uid, 'executor_gid': executor_gid,
        'admin_uid': admin_uid, 'admin_gid': admin_gid, 'strategy_uid': strategy_uid,
        'channel_name': channel_name, 'component_hashes': _component_hashes()}


class ReviewExecutor:
    def __init__(self, root, *, expected_config_hash):
        self.root = migration._safe(root, root, directory=True)
        config_path = migration._safe(root, self.root/'admin-review-config.json')
        info = config_path.stat()
        if info.st_uid != 0 or stat.S_IMODE(info.st_mode) != 0o444:
            raise p.Rejected('root_pinned_candidate_config_required')
        self.config_hash = p.require_hash(expected_config_hash)
        if migration._hash(config_path) != self.config_hash:
            raise p.Rejected('config_pin_mismatch')
        c = self.config = p.read_json(config_path.read_bytes())
        if (set(c) != CONFIG_FIELDS or type(c['version']) is not int or c['version'] != 1
                or c['mode'] != MODE or c['account'] != migration.ACCOUNT
                or c['runtime_admission'] is not False or c['operational_apply'] is not False):
            raise p.Rejected('inactive_review_config_required')
        for key in ('executor_uid', 'executor_gid', 'admin_uid', 'admin_gid', 'strategy_uid'):
            if type(c[key]) is not int or c[key] < 0:
                raise p.Rejected('candidate_identity_invalid')
        if len({c['executor_uid'], c['admin_uid'], c['strategy_uid']}) != 3:
            raise p.Rejected('separate_admin_executor_strategy_required')
        if ((os.geteuid(), os.getegid()) != (c['executor_uid'], c['executor_gid'])
                or self.root.stat().st_uid != c['executor_uid']):
            raise p.Rejected('executor_identity_required')
        for key in ('bundle_name', 'channel_name'):
            if not isinstance(c[key], str) or not c[key] or Path(c[key]).name != c[key] or c[key] in ('.', '..'):
                raise p.Rejected('candidate_path_invalid')
        if c['component_hashes'] != _component_hashes():
            raise p.Rejected('component_pin_mismatch')
        bundle = self.root/c['bundle_name']
        manifest = migration.verify(self.root, bundle, expected_manifest_sha256=c['manifest_sha256'])
        if manifest['scope'] != migration.SCOPE or manifest['epoch_candidate'] != c['epoch_candidate']:
            raise p.Rejected('migration_namespace_mismatch')
        receipt = p.read_json((bundle/'migration-receipt.json').read_bytes())
        self.checkpoint_at = p.timestamp(receipt['checkpoint_at'])
        with closing(migration._db(self.root, bundle/'execution-copy.sqlite')) as db:
            self.initial = p.read_json(db.execute('SELECT candidate_state FROM migration_review').fetchone()[0])
        self.genesis = p.digest({'mode': MODE, 'config_hash': self.config_hash,
            'manifest_sha256': c['manifest_sha256'], 'state_hash': p.digest(self.initial)})
        self.path = self.root/'admin-review.sqlite'

    def _file(self, path, *, mode=0o600):
        path = migration._safe(self.root, path)
        info = path.stat()
        if info.st_uid != self.config['executor_uid'] or stat.S_IMODE(info.st_mode) != mode:
            raise p.Rejected('executor_private_file_required')
        return path

    def initialize(self):
        """Only a new review DB. Neither migration files nor old economic rows change."""
        fd = os.open(self.path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
        os.close(fd)
        with closing(sqlite3.connect(self.path)) as db:
            db.execute('PRAGMA journal_mode=DELETE'); db.execute('PRAGMA synchronous=FULL')
            db.execute('BEGIN IMMEDIATE')
            for ddl in TABLES.values():
                db.execute(ddl)
            db.execute('INSERT INTO review_meta VALUES (?,?,?)',
                (self.config_hash, _json(self.initial), self.genesis))
            db.execute('INSERT INTO review_state VALUES (1,?)', (_json(self.initial),))
            db.commit()
        _fsync(self.path); _fsync(self.root)
        return self.genesis

    def _open(self, expected_head):
        self._file(self.path)
        db = sqlite3.connect(self.path.as_uri()+'?mode=rw', uri=True, timeout=0.1)
        try:
            db.execute('PRAGMA trusted_schema=OFF')
            if db.execute('PRAGMA journal_mode').fetchone()[0] != 'delete':
                raise p.Rejected('offline_delete_journal_required')
            db.execute('PRAGMA synchronous=FULL')
            if db.execute('PRAGMA integrity_check').fetchall() != [('ok',)]:
                raise p.Rejected('review_storage_integrity_failure')
            schema = dict(db.execute("SELECT name,sql FROM sqlite_master WHERE type='table'"))
            if schema != TABLES or db.execute("SELECT count(*) FROM sqlite_master WHERE type IN ('trigger','view')").fetchone()[0]:
                raise p.Rejected('review_schema_mismatch')
            if db.execute('SELECT * FROM review_meta').fetchall() != [(self.config_hash, _json(self.initial), self.genesis)]:
                raise p.Rejected('review_namespace_mismatch')
            state_rows = db.execute('SELECT * FROM review_state').fetchall()
            if len(state_rows) != 1 or state_rows[0][0] != 1:
                raise p.Rejected('review_state_invalid')
            state = p.read_json(state_rows[0][1]); state_hash = p.digest(self.initial)
            head = self.genesis; claims = {}
            for seq, raw, actual in db.execute('SELECT seq,body,hash FROM review_events ORDER BY seq'):
                event = p.read_json(raw)
                if seq != event['seq'] or seq != 1+sum(len(v) for v in claims.values()) or event['previous'] != head or p.digest(event) != actual:
                    raise p.Rejected('review_chain_invalid')
                if event['state_before'] != state_hash or event['account'] != self.config['account'] or event['epoch_candidate'] != self.config['epoch_candidate']:
                    raise p.Rejected('review_event_namespace_invalid')
                nonce = event['command']['command_id']; stages = claims.setdefault(nonce, [])
                if event['stage'] == 'RESERVED' and not stages and event['state_after'] == state_hash:
                    stages.append(event)
                elif event['stage'] == 'COMMITTED' and len(stages) == 1 and stages[0]['command'] == event['command']:
                    stages.append(event); state_hash = event['state_after']
                else:
                    raise p.Rejected('review_claim_chain_invalid')
                head = actual
            expected_claims = sorted((n, _json(v[0]['command']), v[-1]['stage']) for n, v in claims.items())
            if sorted(db.execute('SELECT * FROM review_claims')) != expected_claims or p.digest(state) != state_hash:
                raise p.Rejected('review_claim_or_state_mismatch')
            if head != p.require_hash(expected_head):
                raise p.Rejected('external_review_head_mismatch')
            return db, state, head
        except BaseException:
            db.close()
            raise

    def _event(self, db, command, stage, before, after, head, *, detail=None):
        event = {'seq': db.execute('SELECT count(*) FROM review_events').fetchone()[0]+1,
            'previous': head, 'account': self.config['account'], 'epoch_candidate': self.config['epoch_candidate'],
            'stage': stage, 'command': command, 'state_before': p.digest(before), 'state_after': p.digest(after),
            'detail': detail}
        digest = p.digest(event)
        db.execute('INSERT INTO review_events VALUES (?,?,?)', (event['seq'], _json(event), digest))
        return digest

    def _validate(self, command, now):
        c = self.config
        if not isinstance(command, dict) or set(command) != FIELDS or type(command['schema_version']) is not int or command['schema_version'] != 1:
            raise p.Rejected('admin_command_schema_invalid')
        for key in ('command_id', 'epoch_candidate', 'position_id'):
            p.require_hash(command[key])
        if command['account'] != c['account'] or command['epoch_candidate'] != c['epoch_candidate']:
            raise p.Rejected('admin_command_namespace_invalid')
        if type(command['generation']) is not int or command['generation'] < 1:
            raise p.Rejected('admin_command_generation_invalid')
        issued, expires = p.timestamp(command['issued_at']), p.timestamp(command['expires_at'])
        if issued < self.checkpoint_at:
            raise p.Rejected('command_predates_candidate_epoch')
        if not issued <= now < expires or not dt.timedelta(0) < expires-issued <= dt.timedelta(minutes=5):
            raise p.Rejected('admin_command_expired_or_future')
        if not isinstance(command['symbol'], str) or command['symbol'] not in self.initial['positions']:
            raise p.Rejected('admin_command_symbol_invalid')
        _number(command['maximum_quantity_to_reduce'], positive=True)

    def _market(self, path, pin, symbol, now):
        raw = migration._safe(self.root, path).read_bytes()
        if hashlib.sha256(raw).hexdigest() != p.require_hash(pin):
            raise p.Rejected('market_fixture_pin_mismatch')
        value = p.read_json(raw)
        if (value.get('scope') != MARKET_SCOPE or value.get('kucoin_order_admissibility_proven') is not False
                or value.get('credentials_used') is not False or type(value.get('schema_version')) is not int
                or value.get('schema_version') != 2):
            raise p.Rejected('explicit_synthetic_market_required')
        if value.get('record_hash') != p.digest({k: v for k, v in value.items() if k != 'record_hash'}):
            raise p.Rejected('market_record_hash_invalid')
        quote = value['quotes'][symbol]
        # Stronger review evidence completeness; never change the P0-03 implementation.
        if quote.get('mark_timestamp') is None or quote.get('metadata_observed_at') is None:
            raise p.Rejected('mark_or_metadata_timestamp_unknown')
        if quote.get('min_quantity') is not None or quote.get('min_notional') is not None:
            raise p.Rejected('minimums_must_remain_unknown')
        sanity.structure_and_time(symbol, quote, value, now)
        return value, quote

    def _execute(self, command, *, market_path, expected_market_hash, expected_head, now, fault=None, clock=None):
        """Privileged executor primitive; untrusted callers enter through handle_one."""
        self.__init__(self.root, expected_config_hash=self.config_hash)
        now = p.timestamp(now)
        current_time = clock or (lambda: now.isoformat())
        self._validate(command, now)
        lock_path = self.root/'admin-review.lock'
        fd = os.open(lock_path, os.O_RDWR | os.O_CREAT | os.O_NOFOLLOW, 0o600)
        with os.fdopen(fd, 'rb+') as lock:
            self._file(lock_path)
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
            db, state, head = self._open(expected_head)
            with closing(db):
                if db.execute('SELECT 1 FROM review_claims WHERE nonce=?', (command['command_id'],)).fetchone():
                    raise p.Rejected('admin_command_replay')
                if db.execute("SELECT 1 FROM review_claims WHERE status='RESERVED'").fetchone():
                    raise p.Rejected('uncertain_reservation_requires_reconciliation')
                if state.get('pending') is not None:
                    raise p.Rejected('outstanding_intent_requires_reconciliation')
                position = state['positions'].get(command['symbol'])
                if (not position or position.get('position_id') != command['position_id']
                        or position.get('generation') != command['generation']):
                    raise p.Rejected('position_identity_mismatch')
                old = _number(position['quantity']); maximum = _number(command['maximum_quantity_to_reduce'], positive=True)
                if old == 0 or maximum > abs(old):
                    raise p.Rejected('admin_close_exceeds_current_position_or_flat')
                self._validate(command, p.timestamp(current_time()))
                # Burn nonce durably before any economic transaction. Uncertain reservation
                # is not retried automatically, even when no fill was committed.
                db.execute('BEGIN IMMEDIATE')
                try:
                    db.execute('INSERT INTO review_claims VALUES (?,?,?)', (command['command_id'], _json(command), 'RESERVED'))
                    head = self._event(db, command, 'RESERVED', state, state, head)
                    if fault: fault('before_reserve_commit', db)
                    db.commit(); _fsync(self.path); _fsync(self.root)
                except BaseException:
                    db.rollback(); raise
                if fault: fault('after_reserve_commit', db)
                now = p.timestamp(current_time())
                self._validate(command, now)
                record, quote = self._market(market_path, expected_market_hash, command['symbol'], now)
                if maximum < abs(old):
                    step = Decimal(str(sanity.numeric(quote.get('step'), 'step', positive=True)))
                    if Decimal(str(maximum)) % step:
                        raise p.Rejected('partial_reduction_step_invalid')
                delta = -math.copysign(maximum, old)
                observed = sanity.preflight(command['symbol'], quote, delta, True)
                price = market.fill_price(quote, delta)
                fee = abs(delta)*price*float(sanity.numeric(quote.get('fee_rate'), 'fee_rate', nonnegative=True))
                after = copy.deepcopy(state); selected = after['positions'][command['symbol']]
                selected['current_price'] = float(quote['mark_price'])
                paper.apply_fill(selected, delta, price, fee)
                new = selected['quantity']
                if (abs(new) >= abs(old) or (new != 0 and math.copysign(1, new) != math.copysign(1, old))
                        or abs(Decimal(str(old))-Decimal(str(new))) > Decimal(str(maximum))):
                    raise p.Rejected('fill_exceeds_authorized_reduction')
                # No funding cursor advancement, backfilled funding, strategy fill or
                # current portfolio-equity claim. Historical order_count stays historical.
                detail = {'scope': MODE, 'market_scope': MARKET_SCOPE,
                    'peer_identity_candidate': {'uid': self.config['admin_uid'], 'gid': self.config['admin_gid']},
                    'account': self.config['account'], 'epoch_candidate': self.config['epoch_candidate'],
                    'position_id': command['position_id'], 'generation': command['generation'],
                    'recorded_at': now.isoformat(), 'symbol': command['symbol'],
                    'quantity_before': old, 'quantity_after': new, 'delta': delta,
                    'price': price, 'fee': fee, 'realized_pnl_delta': selected['realized_pnl']-position['realized_pnl'],
                    'market_hash': expected_market_hash, 'observation': record,
                    'P0_03': observed, 'funding_coverage': 'UNRESOLVED',
                    'funding_cursor_advanced': False, 'operational_apply': False,
                    'kucoin_order_admissibility_proven': False}
                db.execute('BEGIN IMMEDIATE')
                try:
                    db.execute('UPDATE review_state SET body=? WHERE id=1', (_json(after),))
                    db.execute("UPDATE review_claims SET status='COMMITTED' WHERE nonce=?", (command['command_id'],))
                    head = self._event(db, command, 'COMMITTED', state, after, head, detail=detail)
                    if fault: fault('before_fill_commit', db)
                    commit_time = p.timestamp(current_time())
                    self._validate(command, commit_time)
                    sanity.structure_and_time(command['symbol'], quote, record, commit_time)
                    db.commit(); _fsync(self.path); _fsync(self.root)
                except BaseException:
                    db.rollback(); raise
                if fault: fault('after_fill_commit', db)
                return {'status': 'SIMULATED_REVIEW_CLOSE', 'head': head, 'detail': detail,
                    'readiness': 'BLOCKED', 'runtime_admission': False, 'operational_apply': False}

    def handle_one(self, socket_directory, *, market_path, expected_market_hash, expected_head,
                   clock=lambda: dt.datetime.now(dt.timezone.utc).isoformat(), ready=None):
        """One ephemeral offline request. No daemon or runtime installation entrypoint.

        Socket directory is executor-owned 0750 with the candidate admin primary
        GID. DB directory remains 0700 executor-only; no per-table ACL claim.
        """
        if not hasattr(socket, 'SO_PEERCRED'):
            raise p.Rejected('peer_credentials_unavailable')
        directory = Path(socket_directory).absolute()
        for item in (directory, *directory.parents):
            if item.is_symlink(): raise p.Rejected('socket_symlink_forbidden')
        info = directory.stat()
        if (info.st_uid, info.st_gid, stat.S_IMODE(info.st_mode)) != (self.config['executor_uid'], self.config['admin_gid'], 0o750):
            raise p.Rejected('candidate_socket_directory_unsafe')
        path = directory/self.config['channel_name']
        if path.exists() or path.is_symlink(): raise p.Rejected('candidate_socket_exists')
        with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as server:
            server.bind(str(path)); os.chown(path, -1, self.config['admin_gid']); os.chmod(path, 0o660)
            server.listen(1); server.settimeout(5)
            try:
                if ready: ready()
                connection, _ = server.accept()
                with connection:
                    connection.settimeout(5)
                    _, uid, gid = struct.unpack('3i', connection.getsockopt(socket.SOL_SOCKET, socket.SO_PEERCRED, 12))
                    result = {'status': 'DENY', 'reason': 'admin_peer_denied', 'operational_apply': False}
                    if (uid, gid) == (self.config['admin_uid'], self.config['admin_gid']):
                        try:
                            raw = bytearray()
                            while len(raw) <= 4096 and not raw.endswith(b'\n'):
                                part = connection.recv(4097-len(raw))
                                if not part: break
                                raw.extend(part)
                            if len(raw) > 4096 or not raw.endswith(b'\n'):
                                raise p.Rejected('admin_command_size_invalid')
                            command = p.read_json(bytes(raw))
                            result = self._execute(command, market_path=market_path,
                                expected_market_hash=expected_market_hash, expected_head=expected_head, now=clock(), clock=clock)
                        except (p.Rejected, ValueError, KeyError, TypeError, OSError, sqlite3.Error) as exc:
                            result = {'status': 'DENY', 'reason': str(exc), 'operational_apply': False,
                                'reconciliation_required': True}
                    connection.sendall(p.canonical_bytes(result)+b'\n')
                    return result
            finally:
                path.unlink(missing_ok=True)
