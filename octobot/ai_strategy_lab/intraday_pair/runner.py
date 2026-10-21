"""Durable four-arm fanout. No network, service registration or existing accounts.

Only a new private namespace may be initialized. Candidate mode deliberately
requires a future T0 for public-source probes; synthetic qualification can use
an injected clock. Public activation remains a separate exact-bundle decision.
"""
from contextlib import closing
import fcntl
import hashlib
import os
from pathlib import Path
import sqlite3
import uuid

from . import engine, receipts
from .source import canonical, digest, strict, NS

ARMS = (('control', False), ('candidate', False), ('control', True), ('candidate', True))


def key(arm, stress):
    return arm + ('-stress' if stress else '-primary')


class Pair:
    def __init__(self, directory, t0, bundle_sha, *, initialize=False, clock=None,
                 synthetic=False, after_arm=None, activation=None):
        self.engines = {}; self.db = None; self.witness = None; self.lock = None
        self.failed = False; self.clock = clock or receipts.Clock()
        self.path = Path(directory)
        self.after_arm = after_arm or (lambda name: None)
        if activation is not None and (synthetic or activation.get('t0_ns')!=t0 or
                activation.get('scope')!='AUTHORIZED_SYNTHETIC_PAPER_PAIR'):
            raise ValueError('activation_scope')
        self.authorized=activation is not None
        self.mode = ('AUTHORIZED_RESEARCH_PAPER_PAIR' if self.authorized else
                     'SYNTHETIC_TEST_ONLY' if synthetic else 'PRESTART_PUBLIC_SOURCE_QUALIFICATION_ONLY')
        self.t0 = t0
        try:
            if type(t0) is not int or t0 < 0:
                raise ValueError('invalid_t0')
            if not synthetic and not self.authorized and t0 <= self.clock.sample()['utc_ns']:
                raise ValueError('activation_not_authorized')
            if any(p.is_symlink() for p in (self.path, *self.path.parents)):
                raise ValueError('namespace_symlink')
            if initialize:
                self.path.mkdir(mode=0o700, parents=False, exist_ok=False)
            if not self.path.is_dir() or self.path.stat().st_uid != os.geteuid() or self.path.stat().st_mode & 0o077:
                raise ValueError('private_owned_namespace_required')
            self.lock = open(self.path/'pair.lock', 'a')
            fcntl.flock(self.lock, fcntl.LOCK_EX|fcntl.LOCK_NB)
            names = ['input.sqlite', 'pair.lock'] + [key(*a)+'.sqlite' for a in ARMS]
            if any((self.path/n).is_symlink() for n in names):
                raise ValueError('namespace_file_symlink')
            if not initialize and any(not (self.path/n).is_file() for n in names):
                raise ValueError('pair_state_missing_no_reset')
            if not initialize and (not (self.path/'witness/availability.sqlite').is_file() or
                                   (self.path/'witness').is_symlink()):
                raise ValueError('witness_state_missing_no_reset')
            self.db = sqlite3.connect(self.path/'input.sqlite', timeout=.2)
            self.db.row_factory = sqlite3.Row
            self.db.execute('PRAGMA journal_mode=WAL'); self.db.execute('PRAGMA synchronous=FULL')
            self.identity = dict(schema=1, protocol_sha=engine.PROTOCOL_SHA, bundle_sha=bundle_sha,
                                 t0=t0, mode=self.mode, arms=[key(*a) for a in ARMS])
            if initialize:
                self.db.executescript('''
                    CREATE TABLE identity(payload TEXT NOT NULL);
                    CREATE TABLE inputs(seq INTEGER PRIMARY KEY,kind TEXT,payload TEXT,sha TEXT UNIQUE);
                    CREATE TABLE receipts(data_sha TEXT PRIMARY KEY,seq INTEGER UNIQUE);
                    CREATE TABLE observations(slot_ns INTEGER PRIMARY KEY,observed_ns INTEGER,payload TEXT,sha TEXT);
                    CREATE TRIGGER immutable_input_update BEFORE UPDATE ON inputs BEGIN SELECT RAISE(ABORT,'append_only'); END;
                    CREATE TRIGGER immutable_input_delete BEFORE DELETE ON inputs BEGIN SELECT RAISE(ABORT,'append_only'); END;
                ''')
                with self.db:self.db.execute('INSERT INTO identity VALUES(?)',(canonical(self.identity).decode(),))
            elif strict(self.db.execute('SELECT payload FROM identity').fetchone()[0]) != self.identity:
                raise ValueError('pair_identity_changed')
            self.previous = '0'*64; self.seq = 0
            for r in self.db.execute('SELECT * FROM inputs ORDER BY seq'):
                v = strict(r['payload'])
                if r['seq'] != self.seq+1 or v['previous'] != self.previous or digest(v) != r['sha']:
                    raise ValueError('input_chain_corrupt')
                self.previous = r['sha']; self.seq = r['seq']
            self.witness = receipts.Witness(self.path/'witness', self.clock)
            for arm, stress in ARMS:
                name = key(arm, stress)
                self.engines[name] = engine.Engine(self.path/(name+'.sqlite'), t0, bundle_sha,
                    self.clock, initialize=initialize, arm=arm, stress_mode=stress)
                self.engines[name].db.execute('CREATE INDEX IF NOT EXISTS events_time ON events(at_ns)')
                self.engines[name].db.commit()
            for e in self.engines.values():
                seq = e.s['last_input_seq']
                r = self.db.execute('SELECT sha FROM inputs WHERE seq=?',(seq,)).fetchone()
                if seq and (not r or r['sha'] != e.s['last_input_sha']):
                    raise ValueError('account_input_cursor_mismatch')
            last=self.db.execute("SELECT payload FROM inputs WHERE kind='market' ORDER BY seq DESC LIMIT 1").fetchone()
            self.market_key=strict(last[0])['payload'].get('market_hash') if last else None
        except BaseException:
            self.close(); raise

    def close(self):
        for e in self.engines.values(): e.close()
        self.engines.clear()
        if self.witness is not None:self.witness.close(); self.witness = None
        if self.db is not None:self.db.close(); self.db = None
        if self.lock is not None:self.lock.close(); self.lock = None

    def _guard(self):
        if self.failed: raise ValueError('pair_storage_or_processing_fault_latched')
        if self.mode == 'PRESTART_PUBLIC_SOURCE_QUALIFICATION_ONLY' and self.clock.sample()['utc_ns'] >= self.t0:
            raise ValueError('activation_not_authorized')

    def publish(self, kind, source_key, payload, started, completed, received_max):
        """Persist local availability first, then a common durable input envelope.

        Real-source callers must use poll_sources() which verifies raw captures.
        Direct normalized injection is restricted to explicit synthetic mode.
        """
        self._guard()
        if not self.mode == 'SYNTHETIC_TEST_ONLY' and not getattr(self, '_verified_source', False):
            raise ValueError('raw_source_verification_required')
        if kind not in ('market', 'book', 'heartbeat','admin'): raise ValueError('input_kind')
        try:
            data, _ = self.witness.observe(kind, source_key, payload, started, completed, received_max)
            proof = self.witness.available_now(data, self.clock.sample()['utc_ns']+NS)
            v = dict(kind=kind, payload=payload, proof=proof, previous=self.previous)
            sha = digest(v)
            with self.db:
                self.db.execute('INSERT INTO inputs VALUES(?,?,?,?)',
                                (self.seq+1,kind,canonical(v).decode(),sha))
                self.db.execute('INSERT INTO receipts VALUES(?,?)',(data,self.seq+1))
            self.seq += 1; self.previous = sha
            self.drain()
            return self.seq
        except BaseException:
            self.failed = True; raise

    def drain(self):
        self._guard()
        try:
            first = min(e.s['last_input_seq'] for e in self.engines.values())+1
            for r in self.db.execute('SELECT * FROM inputs WHERE seq>=? ORDER BY seq',(first,)):
                v = strict(r['payload'])
                if digest(v) != r['sha']: raise ValueError('input_chain_corrupt')
                for arm, stress in ARMS:
                    name = key(arm,stress); e = self.engines[name]
                    if e.s['last_input_seq'] >= r['seq']:continue
                    primary = self.engines[key(arm,False)]
                    last = e.s['last_slot'] if e.s['last_slot'] is not None else -1
                    slots = ([dict(row) for row in primary.db.execute(
                        'SELECT * FROM slots WHERE slot_ns>? ORDER BY slot_ns',(last,))] if stress else None)
                    e.consume(r['seq'],r['sha'],r['kind'],v['payload'],v['proof'],slots)
                    self.after_arm(name)
        except BaseException:
            self.failed = True; raise

    def poll_sources(self, market_source, book_reader):
        """Bounded caller-driven polling; no scheduler, network or source writes."""
        self._guard(); self._verified_source = True
        try:
            p = self.engines['control-primary'].protocol
            pointer,_=receipts.read_blob(Path(market_source)/'market.json')
            if pointer.get('record_hash') != getattr(self,'market_key',None):
                h,payload,before,after,received=receipts.read_market(market_source,p,self.clock)
                compact = dict(market_hash=h,normalized=payload['normalized'],
                    raw_receipts=[dict(capture_id=r['capture_id'],raw_sha256=r['raw_sha256']) for r in payload['receipts']])
                self.publish('market',h,compact,before,after,received); self.market_key=h
            result = book_reader.poll()
            if result:
                payload,before,after = result; rows=payload['rows']
                self.publish('book',str(rows[0]['id'])+':'+str(rows[-1]['id']),payload,
                             before,after,max(r['received_ts_ns'] for r in rows))
                book_reader.cursor=rows[-1]['id']
            else:
                now = self.clock.sample()
                self.publish('heartbeat',uuid.uuid4().hex,{'rows':[]},now,now,now['utc_ns'])
        finally:self._verified_source = False

    def administrative_file(self,path):
        """No-follow, bounded, root-owned local command channel; no UI writer."""
        self._guard()
        fd=os.open(path,os.O_RDONLY|os.O_NOFOLLOW|os.O_NONBLOCK)
        try:
            import stat
            s=os.fstat(fd)
            if not stat.S_ISREG(s.st_mode) or s.st_uid!=0 or s.st_mode&0o022 or s.st_size>16384:
                raise ValueError('administrative_file_custody')
            raw=os.read(fd,16385)
            if len(raw)>16384:raise ValueError('administrative_file_size')
        finally:os.close(fd)
        command=strict(raw)
        if command.get('scenario') not in ('primary','stress'):raise ValueError('administrative_scenario')
        already=self.witness.db.execute("SELECT 1 FROM observed WHERE source='admin' AND key=?",(digest(command),)).fetchone()
        if already:return None
        now=self.clock.sample()
        self._verified_source=True
        try:return self.publish('admin',digest(command),command,now,now,now['utc_ns'])
        finally:self._verified_source=False

    def status(self):
        return dict(mode=self.mode,active_account=self.authorized,protocol_sha=engine.PROTOCOL_SHA,
            input_seq=self.seq,arms={k:dict(cursor=e.s['last_input_seq'],q=e.s['q'],
                equity=e.equity(),fills=e.s['fills'],reason=e.s['reason'],
                input_sha=e.s['last_input_sha'],complete=e.accounting_complete()) for k,e in self.engines.items()},
            real_min_quantity='UNKNOWN',real_min_notional='UNKNOWN',scientific_validity='UNASSESSED')

    def observe_grid(self, slot_ns):
        """Reconstruct one common cutoff; no state or quote published later leaks in.

        State must have a returned commit acknowledgment by cutoff. The book must
        have a common availability receipt by cutoff and be fresh at cutoff.
        Missing data remain incomplete. This is valuation, never an entry replay.
        """
        self._guard(); now=self.clock.sample()['utc_ns']
        if type(slot_ns) is not int or slot_ns% (300*NS) or not self.t0<=slot_ns<=self.t0+90*86400*NS or now<slot_ns:
            raise ValueError('valuation_cutoff')
        existing=self.db.execute('SELECT payload FROM observations WHERE slot_ns=?',(slot_ns,)).fetchone()
        if existing:return strict(existing[0])
        book=None
        for r in self.db.execute("SELECT payload FROM inputs WHERE kind='book' ORDER BY seq DESC"):
            v=strict(r[0])
            if v['proof']['observed_visible']['utc_ns']>slot_ns:continue
            candidates=[row for row in v['payload']['rows'] if row['received_ts_ns']<=slot_ns]
            if candidates:book=candidates[-1];break
        mid=(book['bid_price_1']+book['ask_price_1'])/2 if book and engine.fresh(book,slot_ns) else None
        values={}
        for name,e in self.engines.items():
            row=e.db.execute('''SELECT payload FROM events e JOIN acknowledgements a USING(seq)
                WHERE at_ns<=? AND commit_returned_ns<=? ORDER BY e.seq DESC LIMIT 1''',(slot_ns,slot_ns)).fetchone()
            state=strict(row[0])['state'] if row else None
            pending_funding=e.db.execute("SELECT 1 FROM funding WHERE status='PENDING' AND tau<=?",(slot_ns,)).fetchone()
            # A later reconciliation must not turn a provisional historical point
            # into a complete one: as-of state records the then-known cash/funding.
            pending_asof=e.db.execute("SELECT 1 FROM funding WHERE tau<=? AND (observed>? OR status='PENDING')",(slot_ns,slot_ns)).fetchone()
            complete=bool(state and mid is not None and not pending_funding and not pending_asof
                          and not state.get('funding_pending') and not state['integrity_halt'])
            eq=state['cash']+state['q']*(mid-state['entry']) if state and mid is not None else None
            values[name]=dict(at_ns=slot_ns,equity=eq,complete=complete,q=state['q'] if state else None)
        out=dict(slot_ns=slot_ns,observed_ns=now,mid=mid,accounts=values)
        with self.db:self.db.execute('INSERT INTO observations VALUES(?,?,?,?)',
            (slot_ns,now,canonical(out).decode(),digest(out)))
        return out

    def export(self):
        """Export only this namespace. Scientific evaluator enforces the horizon."""
        observations=[]
        for row in self.db.execute('SELECT payload,sha FROM observations ORDER BY slot_ns'):
            v=strict(row[0])
            if digest(v)!=row[1]:raise ValueError('valuation_integrity')
            observations.append(v)
        arms={}
        for name,e in self.engines.items():
            fills=[]
            for r in e.db.execute('SELECT at_ns,quantity,price,fee,realized,payload FROM fills ORDER BY at_ns,rowid'):
                fills.append(dict(at_ns=r['at_ns'],quantity=r['quantity'],price=r['price'],
                                  fee=r['fee'],realized=r['realized'],detail=strict(r['payload'])))
            arms[name]=dict(points=[o['accounts'][name] for o in observations],fills=fills,
                final_q=e.s['q'],complete=e.accounting_complete(),integrity_halt=e.s['integrity_halt'],
                valid_slots=e.s['valid_slots'],slots=e.s['slots'],fees=e.s['fees'],funding=e.s['funding'],
                realized=e.s['realized'],slot_status_counts={r[0]:r[1] for r in e.db.execute('SELECT status,count(*) FROM slots GROUP BY status')})
        return dict(mode=self.mode,identity=self.identity,t0=self.t0,t1=self.t0+90*86400*NS,arms=arms)


def close_request(state, now, *, uid=None, stress=False):
    """Only the authenticated local root channel may construct a close request.

    Caller must still custody-check a root-owned file before forwarding to the
    executor. No UI route or command writer is installed by this function.
    """
    if (os.geteuid() if uid is None else uid) != 0: raise PermissionError('local_root_required')
    if not state['q']: raise ValueError('already_flat')
    account=state['account']; generation=state['position_generation']
    return dict(schema=1,account=account,scenario='stress' if stress else 'primary',action='CLOSE_ONLY',
        administrator=dict(uid=0,channel='AUTHENTICATED_LOCAL_ROOT_OWNED_FILE'),
        position_id=account+':'+str(generation),generation=generation,
        maximum_quantity_btc=abs(state['q']),nonce=uuid.uuid4().hex,
        issued_ns=now,expires_ns=now+60*NS)
