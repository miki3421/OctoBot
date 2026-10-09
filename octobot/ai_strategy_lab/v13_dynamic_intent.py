"""Offline intent persistence and temporal book check; never an execution grant.

Custody-verified receipts must be supplied by the existing readers. SQLite and
hashes do not protect against a writer controlling this offline file or host.
"""
import datetime as dt
import json
import sqlite3
from pathlib import Path
try:
    from . import v13_dynamic_preview as preview
except ImportError:
    import v13_dynamic_preview as preview

SCOPE='OFFLINE_ABC_INTENT_V1'


def utc_now():
    return dt.datetime.now(dt.timezone.utc).isoformat()


class IntentStore:
    def __init__(self,path,*,create=False,read_only=False):
        if create and read_only:raise ValueError('read_only_create')
        p=Path(path).absolute()
        if p.is_symlink():raise ValueError('symlink_store')
        if create:
            with p.open('xb'):pass
        elif not p.is_file():raise ValueError('intent_store_missing')
        self.db=sqlite3.connect(p.as_uri()+('?mode=ro' if read_only else '?mode=rw'),uri=True,isolation_level=None)
        try:
            self.db.execute('PRAGMA trusted_schema=OFF')
            self.db.execute('PRAGMA synchronous=FULL')
            if read_only:self.db.execute('PRAGMA query_only=ON')
            if create:
                self.db.executescript('BEGIN IMMEDIATE; CREATE TABLE marker(scope TEXT NOT NULL); '
                                     'CREATE TABLE intents(id TEXT PRIMARY KEY, payload TEXT NOT NULL, sealed_at TEXT);')
                self.db.execute('INSERT INTO marker VALUES (?)',(SCOPE,))
                self.db.execute('COMMIT')
            if self.db.execute('SELECT scope FROM marker').fetchall()!=[(SCOPE,)]:raise ValueError('foreign_intent_store')
        except BaseException:
            self.db.close();raise

    def close(self):self.db.close()

    def record(self,records,*,slot,start,lineage):
        # The decision is derived here, not accepted from an arbitrary payload.
        now=utc_now()
        self.db.execute('BEGIN IMMEDIATE')
        try:
            last=self.db.execute('SELECT id,payload,sealed_at FROM intents ORDER BY rowid DESC LIMIT 1').fetchone()
            if last and last[2] is None:raise ValueError('unsealed_intent_requires_review')
            previous=self._decode(last)['derived']['selection'] if last else None
            value=preview.preview(records,slot=slot,start=start,lineage=lineage,as_of=now,previous=previous)
            ident=value['derived']['selection']['decision_id']
            old=self.db.execute('SELECT id,payload,sealed_at FROM intents WHERE id=?',(ident,)).fetchone()
            if old:
                stored=self._decode(old)
                if stored['derived']!=value['derived']:raise ValueError('intent_conflict')
                self.db.execute('COMMIT')
                return dict(id=ident,sealed_at=old[2],execution_ready=False)
            value['persistence_hash']=preview.runner.selector.digest(value)
            payload=json.dumps(value,sort_keys=True,allow_nan=False)
            self.db.execute('INSERT INTO intents VALUES (?,?,NULL)',(ident,payload))
            self.db.execute('COMMIT')
        except BaseException:
            if self.db.in_transaction:self.db.execute('ROLLBACK')
            raise
        # Sample AFTER the payload commit. A crash before this seal is stored
        # leaves an unusable intent, not a fabricated pre-commit timestamp.
        sealed=utc_now()
        if preview.runner.selector.timestamp(sealed)<preview.runner.selector.timestamp(now):
            raise ValueError('clock_regression')
        self.db.execute('UPDATE intents SET sealed_at=? WHERE id=? AND sealed_at IS NULL',(sealed,ident))
        return dict(id=ident,sealed_at=sealed,execution_ready=False)

    def _decode(self,row):
        value=json.loads(row[1]);decision=value['derived']['selection']
        if preview.runner.selector.digest({k:v for k,v in value.items() if k!='persistence_hash'})!=value.get('persistence_hash'):
            raise ValueError('intent_integrity')
        if (decision['decision_id']!=row[0] or preview.runner.selector.digest(
                {k:v for k,v in decision.items() if k!='decision_id'})!=row[0]):
            raise ValueError('intent_integrity')
        return value

    def check_books(self,ident,records):
        row=self.db.execute('SELECT id,payload,sealed_at FROM intents WHERE id=?',(ident,)).fetchone()
        if row is None or row[2] is None:raise ValueError('sealed_intent_required')
        self._decode(row)
        result=preview.data.admit_books(records,intent_persisted_at=row[2],as_of=utc_now())
        return dict(result,intent_id=ident)

    def execution_inputs(self,ident,records):
        """Assemble real inputs from one durable intent; no fixture conversion.

        This is a preflight packet, not an order or a consumable authorization.
        Funding, qualification and operational admission must still be supplied
        by the future executor, never defaulted to passed by this method.
        """
        self.db.execute('BEGIN')
        try:
            row=self.db.execute('SELECT id,payload,sealed_at FROM intents WHERE id=?',(ident,)).fetchone()
            if row is None or row[2] is None:raise ValueError('sealed_intent_required')
            stored=self._decode(row)
            admitted=preview.data.admit_books(records,intent_persisted_at=row[2],as_of=utc_now())
            result=dict(scope='REAL_ABC_EXECUTION_INPUT_PREFLIGHT_V1',intent_id=ident,
                        intent_persisted_at=row[2],as_of=admitted['as_of'],
                        derived=stored['derived'],source_set_sha256=stored['source_set_sha256'],
                        books=admitted['books'],
                        price_ticks={s:r['precision']['price_tick'] for s,r in admitted['books'].items()},
                        quantity_steps={s:r['precision']['quantity_increment'] for s,r in admitted['books'].items()},
                        public_taker_fees={s:r['precision']['public_taker_fee'] for s,r in admitted['books'].items()},
                        funding_coverage='UNKNOWN',execution_ready=False,
                        orders_authorized=False,paper_orders_authorized=False,
                        blockers=['funding_coverage_unresolved','qualification_not_verified',
                                  'real_execution_admission_not_implemented'])
            result['packet_hash']=preview.runner.selector.digest(result)
            self.db.execute('COMMIT')
            return result
        except BaseException:
            if self.db.in_transaction:self.db.execute('ROLLBACK')
            raise
