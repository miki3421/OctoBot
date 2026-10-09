"""Local paper-only authorization reader and durable single-use entry claims.

Administrative JSON and stable gate inode are NOT writable by trading runtimes.
A shared flock spans the authorization claim AND the complete simulated effect
(including its commit). Administrative kill/revoke takes the exclusive lock:
activation linearizes only after older effects finish. No cached permissions.
"""
from contextlib import contextmanager, closing
from dataclasses import dataclass, asdict
import datetime as dt
import fcntl
import hashlib
import json
import os
import pathlib
import re
import sqlite3
import stat

UTC = dt.timezone.utc
REQUIRED_CONTROLS = ('per_asset_exposure', 'gross_exposure', 'daily_loss',
                     'drawdown', 'order_frequency', 'cooldown')
_DEFER_DECISION = object()
DEFAULT_ROOT = pathlib.Path('/var/lib/octobot-paper-control')
DEFAULT_AUDIT = pathlib.Path('/var/lib/octobot-paper-consumer/authorization.sqlite')


def now():
    return dt.datetime.now(UTC)


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(',', ':'), allow_nan=False)


def digest(value):
    return hashlib.sha256(canonical(value).encode()).hexdigest()


class Denied(ValueError):
    def __init__(self, code, *, persisted=False, detail=None):
        super().__init__(code)
        self.code, self.persisted, self.detail = code, persisted, detail


def timestamp(value):
    if not isinstance(value, str):
        raise ValueError('timestamp required')
    result = dt.datetime.fromisoformat(value.replace('Z', '+00:00'))
    if result.tzinfo is None:
        raise ValueError('timezone required')
    return result.astimezone(UTC)


def identifier(value):
    return isinstance(value, str) and bool(re.fullmatch(r'[a-zA-Z0-9_.:-]{1,160}', value))


def sha(value):
    return isinstance(value, str) and bool(re.fullmatch('[a-f0-9]{64}', value))


@dataclass(frozen=True)
class Identity:
    account: str
    strategy: str
    lineage_hash: str
    risk_policy: str
    risk_policy_hash: str
    authorization_id: str
    environment: str = 'paper'

    def validate(self):
        if self.environment != 'paper':
            raise Denied('paper_environment_required')
        if not all(identifier(v) for v in (self.account, self.strategy, self.risk_policy, self.authorization_id)):
            raise Denied('authorization_identity_invalid')
        if not all(sha(v) for v in (self.lineage_hash, self.risk_policy_hash)):
            raise Denied('authorization_identity_invalid')


def validate_registry(doc):
    if not isinstance(doc, dict) or set(doc) != {'schema_version', 'revision', 'global_kill', 'authorizations'}:
        raise ValueError('registry schema')
    if type(doc['schema_version']) is not int or doc['schema_version'] != 1 or type(doc['revision']) is not int or doc['revision'] < 1:
        raise ValueError('registry version')
    kill = doc['global_kill']
    if not isinstance(kill, dict) or set(kill) != {'active', 'changed_at'} or type(kill['active']) is not bool:
        raise ValueError('kill schema')
    timestamp(kill['changed_at'])
    if not isinstance(doc['authorizations'], dict):
        raise ValueError('authorizations schema')
    for key, grant in doc['authorizations'].items():
        fields = set(Identity.__dataclass_fields__) | {'created_at', 'valid_from', 'expires_at', 'status'}
        if not isinstance(grant, dict) or set(grant) != fields or key != grant['authorization_id']:
            raise ValueError('grant schema')
        Identity(**{k: grant[k] for k in Identity.__dataclass_fields__}).validate()
        created, valid = timestamp(grant['created_at']), timestamp(grant['valid_from'])
        if valid < created or grant['status'] not in ('ACTIVE', 'REVOKED'):
            raise ValueError('grant status/time')
        if grant['expires_at'] is not None and timestamp(grant['expires_at']) <= valid:
            raise ValueError('grant expiry')
    return doc


def unique_object(pairs):
    result = {}
    for k, v in pairs:
        if k in result:
            raise ValueError('duplicate JSON key')
        result[k] = v
    return result


def secure_read(path):
    fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW)
    try:
        info = os.fstat(fd)
        if not stat.S_ISREG(info.st_mode) or info.st_mode & 0o022 or not info.st_mode & 0o444:
            raise OSError('unsafe or unreadable control file')
        return fd
    except BaseException:
        os.close(fd)
        raise


class Registry:
    def __init__(self, root=DEFAULT_ROOT, audit=DEFAULT_AUDIT, *, clock=now):
        self.root, self.audit, self.clock = pathlib.Path(root), pathlib.Path(audit), clock

    def _audit(self, identity, entry_id, result, reason, doc=None, *, claim=False):
        """Consumer-owned storage: no grant/kill columns writable here."""
        payload = dict(identity=asdict(identity), entry_id=entry_id, result=result,
            reason=reason, checked_at=self.clock().isoformat(),
            global_kill=doc['global_kill']['active'] if doc else None,
            registry_revision=doc['revision'] if doc else None)
        try:
            if self.audit.is_symlink():
                raise OSError('audit symlink')
            with closing(sqlite3.connect(self.audit, timeout=0)) as db:
                db.execute('PRAGMA synchronous=FULL')
                db.execute('BEGIN IMMEDIATE')
                db.execute('CREATE TABLE IF NOT EXISTS claims(account TEXT, entry_id TEXT, payload TEXT NOT NULL, PRIMARY KEY(account,entry_id))')
                db.execute('CREATE TABLE IF NOT EXISTS checks(id INTEGER PRIMARY KEY, payload TEXT NOT NULL)')
                if claim:
                    if db.execute('SELECT 1 FROM claims WHERE account=? AND entry_id=?', (identity.account, entry_id)).fetchone():
                        payload.update(result='DENY', reason='entry_already_claimed')
                        db.execute('INSERT INTO checks(payload) VALUES (?)', (canonical(payload),))
                        db.commit()
                        raise Denied('entry_already_claimed', persisted=True)
                    db.execute('INSERT INTO claims VALUES (?,?,?)', (identity.account, entry_id, canonical(payload)))
                db.execute('INSERT INTO checks(payload) VALUES (?)', (canonical(payload),))
                db.commit()
        except Denied:
            raise
        except (OSError, sqlite3.Error, ValueError) as exc:
            raise Denied('authorization_storage_failure', detail=str(exc)) from exc

    def global_entry(self, identity, entry_id, policy):
        """Global stage only; caller MUST execute P0-01 under this same lease."""
        return self.entry(identity, entry_id, policy, _DEFER_DECISION)

    @contextmanager
    def entry(self, identity, entry_id, policy, decision_claim):
        """Single-use global claim; lease must include the effect's durable commit.

        decision_claim is trusted application wiring to P0-01, NEVER a model flag.
        The callback must durably consume the exact decision or return False.
        """
        fd = None
        doc = None
        try:
            try:
                identity.validate()
                if not identifier(entry_id):
                    raise Denied('entry_identity_invalid')
                fd = secure_read(self.root/'gate.lock')
                fcntl.flock(fd, fcntl.LOCK_SH | fcntl.LOCK_NB)
                if (self.root/'mutation.pending').exists():
                    raise Denied('authorization_storage_failure', detail='administrative mutation incomplete')
                registry_fd = secure_read(self.root/'registry.json')
                with os.fdopen(registry_fd) as stream:
                    doc = validate_registry(json.load(stream, object_pairs_hook=unique_object))
                instant = self.clock()
                if timestamp(doc['global_kill']['changed_at']) > instant:
                    raise Denied('authorization_not_yet_valid')
                if doc['global_kill']['active']:
                    raise Denied('global_kill_active')
                grant = doc['authorizations'].get(identity.authorization_id)
                if grant is None:
                    raise Denied('authorization_missing')
                for field, code in (('account', 'account_mismatch'), ('strategy', 'strategy_mismatch'),
                        ('lineage_hash', 'lineage_mismatch'), ('risk_policy', 'risk_policy_mismatch'),
                        ('risk_policy_hash', 'risk_policy_mismatch')):
                    if grant[field] != getattr(identity, field):
                        raise Denied(code)
                if grant['status'] != 'ACTIVE':
                    raise Denied('authorization_revoked')
                if instant < timestamp(grant['created_at']) or instant < timestamp(grant['valid_from']):
                    raise Denied('authorization_not_yet_valid')
                if grant['expires_at'] is not None and instant >= timestamp(grant['expires_at']):
                    raise Denied('authorization_expired')
                if not isinstance(policy, dict) or digest(policy) != identity.risk_policy_hash:
                    raise Denied('risk_policy_mismatch')
                if any(policy.get(k) is None for k in REQUIRED_CONTROLS):
                    raise Denied('risk_policy_incomplete')
                if policy.get('missing_gates'):
                    raise Denied('execution_policy_incomplete')
                self._audit(identity, entry_id, 'GLOBAL_CLAIM', 'global_authorization_valid', doc, claim=True)
                if decision_claim is not _DEFER_DECISION:
                    if not callable(decision_claim):
                        raise Denied('decision_authorization_missing')
                    try:
                        accepted = decision_claim()
                    except Exception as exc:
                        raise Denied('decision_authorization_invalid', detail=str(exc)) from exc
                    if accepted is not True:
                        raise Denied('decision_authorization_invalid')
                    self._audit(identity, entry_id, 'ALLOW_ENTRY_PREFLIGHT', 'decision_authorization_valid', doc)
            except (OSError, sqlite3.Error, ValueError, TypeError, KeyError) as exc:
                if isinstance(exc, Denied):
                    denial = exc
                elif isinstance(exc, FileNotFoundError):
                    denial = Denied('authorization_missing')
                elif isinstance(exc, (OSError, sqlite3.Error)):
                    denial = Denied('authorization_storage_failure', detail=str(exc))
                else:
                    denial = Denied('authorization_malformed', detail=str(exc))
                # A failure to record DENY remains DENY, never an implicit grant.
                try:
                    self._audit(identity, entry_id, 'DENY', denial.code, doc)
                except Denied as storage_error:
                    raise storage_error from denial
                raise Denied(denial.code, persisted=True, detail=denial.detail) from exc
            yield dict(authorization_id=identity.authorization_id, entry_id=entry_id,
                       registry_revision=doc['revision'], environment='paper')
        finally:
            if fd is not None:
                fcntl.flock(fd, fcntl.LOCK_UN)
                os.close(fd)
