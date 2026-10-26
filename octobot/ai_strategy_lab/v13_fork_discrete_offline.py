"""Complete copied-ledger integration, deliberately without a service entrypoint.

Only explicitly labelled offline work copies are accepted. The existing running
Runner, protocol and receipt are never patched or promoted by this module.
"""
import copy
import datetime as dt
import json
from pathlib import Path
import sqlite3

from . import v13_fork_runner as f
from . import v13_discrete_risk_candidate as candidate
from .v13_fork_discrete_core import TickMixin, apply_pair

VERSION = 'fast-half-discrete-offline-integration-v1'
SCOPE = 'OFFLINE_INTEGRATION_ONLY'




class OfflineRunner(TickMixin, f.Runner):
    execution_scope = SCOPE
    """Retain legacy continuation identity and add a separate offline epoch."""
    def __init__(self, config):
        scope = config.get('offline',{})
        if scope.get('scope') != SCOPE:
            raise ValueError('offline_scope_required')
        work = Path(scope['work_dir']).resolve(strict=True)
        db = Path(config['db'])
        if (not db.is_file() or db.is_symlink() or not db.resolve().is_relative_to(work)
                or db.resolve() in (Path(config['seed']).resolve(),Path(config['original']).resolve())):
            raise ValueError('offline_work_copy_required')
        self.boundary = f.p.timestamp(scope['boundary'])
        if self.boundary.time() != dt.time(0,15):
            raise ValueError('offline_daily_boundary')
        expected = scope['source_ledger_sha256']
        f.p.require_hash(expected)
        self.offline_identity = dict(version=VERSION,scope=SCOPE,module_sha256=f.sha(__file__),
                                     candidate_sha256=f.sha(candidate.__file__),base_sha256=f.sha(f.__file__),
                                     boundary=self.boundary.isoformat(),source_ledger_sha256=expected)
        # A hot DELETE journal requires SQLite's physical rollback before even
        # a SELECT can succeed. Only the validated offline work copy is opened
        # read/write; semantic queries remain read-only. Never unlink journals.
        connection = sqlite3.connect(db,timeout=1)
        connection.execute('PRAGMA query_only=ON')
        try:
            row = connection.execute("SELECT payload FROM meta WHERE key='offline_discrete_identity'").fetchone()
            saved = json.loads(row[0]) if row else None
            latest = connection.execute('SELECT MAX(at) FROM observations').fetchone()[0]
        finally:
            connection.close()
        if saved is not None and saved != self.offline_identity:
            raise ValueError('offline_continuation_identity_changed')
        if saved is None and (f.sha(db)!=expected or (latest and self.boundary<=f.p.timestamp(latest))):
            raise ValueError('offline_source_or_boundary_changed')
        super().__init__(config,initialize=False)
        if saved is None:
            with self.db:
                self.put('offline_discrete_identity',self.offline_identity)
                self.put('offline_discrete_boundary',dict(at=self.boundary.isoformat(),
                    inherited_states_sha256=f.p.digest(self.states()),legacy_receipt_sha256=f.p.digest(self.receipt),
                    execution_authorized=False,scope=SCOPE))

    def first_decision_slot(self):
        return max(self.boundary, f.p.timestamp(self.receipt['first_decision_slot']))

    def apply_decision(self, *args):
        return apply_pair(*args)
