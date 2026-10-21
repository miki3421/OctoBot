"""Prospective local availability witness. No strategy, approval, intent or fill API.

Cards: 1a999de7 (implementation), 5c75e0d0 (tests), 0437e0c4 (probe), a655a24c.
Source connections are read-only. Only an explicitly supplied isolated journal is written.
"""
import argparse
from collections import Counter
from contextlib import closing
import fcntl
import hashlib
import json
import math
import os
from pathlib import Path
import sqlite3
import time
import uuid

from .source import (
    NS, canonical, digest, hashed, normalize, read_blob, selected, strict, timestamp,
)

PROTOCOL_SHA = 'bbc19094ac23b8b13a0d82919802f2ede3787add5eda2e13f0f2d8489861493b'
ZERO = '0'*64


class Denied(ValueError):
    pass


class Clock:
    """One process/boot epoch. A clock fault latches until a new run, never retries."""
    def __init__(self, wall=time.time_ns, mono=time.monotonic_ns, boot=None):
        self.wall, self.mono = wall, mono
        self.boot = boot or (lambda: Path('/proc/sys/kernel/random/boot_id').read_text().strip())
        self.previous = None
        self.failed = False

    def sample(self):
        if self.failed:
            raise Denied('clock_fault_latched')
        v = dict(utc_ns=self.wall(), monotonic_ns=self.mono(), boot_id=self.boot())
        p = self.previous
        if p and (v['boot_id'] != p['boot_id'] or v['utc_ns'] < p['utc_ns'] or
                  v['monotonic_ns'] < p['monotonic_ns'] or
                  abs((v['utc_ns']-p['utc_ns'])-(v['monotonic_ns']-p['monotonic_ns'])) > NS):
            self.failed = True
            raise Denied('clock_discontinuity')
        self.previous = v
        return v


def ro(path):
    db = sqlite3.connect(Path(path).resolve().as_uri()+'?mode=ro', uri=True, timeout=0.1)
    db.row_factory = sqlite3.Row
    db.execute('PRAGMA query_only=ON')
    return db


def verify(db):
    """Verify this small witness journal, never scan the live source journal."""
    previous = ZERO
    number=0;observations={}
    for seq, raw, sha in db.execute('SELECT seq,body,sha FROM events ORDER BY seq'):
        v = strict(raw)
        if seq!=number+1 or v['seq'] != seq or v['previous'] != previous or digest(v) != sha:
            raise Denied('witness_chain_corrupted')
        if v['kind']=='data':
            key=(v['payload']['source'],v['payload']['key'])
            if key in observations:raise Denied('duplicate_data_identity')
            observations[key]=(v['run'],sha)
        number=seq;previous = sha
    indexed={(r[0],r[1]):(r[2],r[3]) for r in db.execute('SELECT source,key,run,event_sha FROM observed')}
    if indexed!=observations:raise Denied('observation_index_mismatch')
    return previous


class Witness:
    def __init__(self, directory, clock=None, after_commit=None):
        self.directory = Path(directory)
        if self.directory.is_symlink():
            raise Denied('symlink_destination')
        self.directory.mkdir(mode=0o750, parents=False, exist_ok=True)
        self.path = self.directory/'availability.sqlite'
        if self.path.is_symlink() or (self.directory/'writer.lock').is_symlink():
            raise Denied('symlink_destination')
        self.lock = open(self.directory/'writer.lock', 'a')
        try:
            fcntl.flock(self.lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError:
            self.lock.close()
            raise Denied('writer_already_running') from None
        self.clock = clock or Clock()
        self.after_commit = after_commit or (lambda phase: None)
        self.failed = False
        self.run = uuid.uuid4().hex
        try:
            self.db = sqlite3.connect(self.path, timeout=0.1)
            self.db.execute('PRAGMA journal_mode=DELETE')
            self.db.execute('PRAGMA synchronous=FULL')
            self.db.executescript('''
                CREATE TABLE IF NOT EXISTS events(seq INTEGER PRIMARY KEY,body TEXT NOT NULL,sha TEXT UNIQUE NOT NULL);
                CREATE TABLE IF NOT EXISTS observed(source TEXT,key TEXT,run TEXT,event_sha TEXT,PRIMARY KEY(source,key));
                CREATE TRIGGER IF NOT EXISTS no_update BEFORE UPDATE ON events BEGIN SELECT RAISE(ABORT,'append_only'); END;
                CREATE TRIGGER IF NOT EXISTS no_delete BEFORE DELETE ON events BEGIN SELECT RAISE(ABORT,'append_only'); END;
            ''')
            self.previous = verify(self.db)
            self.seq = self.db.execute('SELECT COALESCE(MAX(seq),0) FROM events').fetchone()[0]
            self.start = self.clock.sample()
            last=self.db.execute('SELECT body FROM events ORDER BY seq DESC LIMIT 1').fetchone()
            if last:
                prior=strict(last[0])['recorded_before_commit']
                if self.start['utc_ns']<prior['utc_ns'] or (self.start['boot_id']==prior['boot_id'] and self.start['monotonic_ns']<prior['monotonic_ns']):
                    raise Denied('clock_regression_across_restart')
            self.append('run', dict(protocol_sha256=PROTOCOL_SHA, started=self.start,
                                    code_sha256=hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
                                    recovery='Old unacknowledged batches are never completed on restart.'))
        except BaseException:
            if hasattr(self, 'db'):
                self.db.close()
            self.lock.close()
            raise

    def append(self, kind, payload, observation_key=None):
        if self.failed:
            raise Denied('storage_fault_latched')
        try:
            stamp = self.clock.sample()
            body = dict(seq=self.seq+1, run=self.run, previous=self.previous,
                        kind=kind, recorded_before_commit=stamp, payload=payload)
            sha = digest(body)
            self.db.execute('BEGIN IMMEDIATE')
            self.db.execute('INSERT INTO events VALUES(?,?,?)', (body['seq'],canonical(body).decode(),sha))
            if observation_key:
                self.db.execute('INSERT INTO observed VALUES(?,?,?,?)', (*observation_key,self.run,sha))
            self.db.commit()
            returned = self.clock.sample()
            self.seq, self.previous = body['seq'], sha
            self.after_commit(kind)  # failure/crash injection only; never used by CLI
            return sha, returned
        except BaseException:
            self.failed = True
            self.db.rollback()
            raise

    def observe(self, source, key, payload, started, completed, received_max_ns, bootstrap=False):
        if started['boot_id'] != completed['boot_id'] or started['boot_id'] != self.start['boot_id']:
            raise Denied('read_epoch')
        if (started['utc_ns'] > completed['utc_ns'] or
                started['monotonic_ns'] > completed['monotonic_ns'] or
                received_max_ns > completed['utc_ns']):
            raise Denied('read_or_source_time')
        now = self.clock.sample()
        if (type(received_max_ns) is not int or completed['utc_ns'] > now['utc_ns'] or
                completed['monotonic_ns'] > now['monotonic_ns'] or
                started['monotonic_ns'] < self.start['monotonic_ns']):
            raise Denied('read_not_observed_in_this_run')
        if self.db.execute('SELECT 1 FROM observed WHERE source=? AND key=?',(source,key)).fetchone():
            raise Denied('duplicate_observation')
        data, persisted = self.append('data', dict(source=source,key=key,input_sha256=digest(payload),
                input=payload,read_started=started,read_completed=completed,
                received_max_ns=received_max_ns,bootstrap=bootstrap), (source,key))
        seal, confirmed = self.append('confirmation',dict(data_sha256=data,data_commit_returned=persisted))
        # This subsequent durable record attests an already returned confirmation commit.
        # It never pretends to timestamp its own commit completion.
        ack, _ = self.append('acknowledgement',dict(data_sha256=data,confirmation_sha256=seal,
                                                   confirmation_commit_returned=confirmed))
        return data, ack

    def available_now(self, data_sha, deadline_ns):
        """Availability ONLY, not admission. A real current RO read must finish by deadline.

        A historical acknowledgement is NOT a backdated admission token. Old epochs,
        bootstrap, absent confirmation, and a missed deadline always deny.
        """
        if self.failed:
            raise Denied('storage_fault_latched')
        try:
            with closing(ro(self.path)) as read:
                records = [strict(r['body']) for r in read.execute('SELECT body FROM events WHERE sha=?',(data_sha,))]
                if not records:
                    raise Denied('data_absent')
                data = records[0]
                if digest(data) != data_sha or data['kind'] != 'data' or data['run'] != self.run:
                    raise Denied('identity_or_old_epoch')
                if data['payload']['bootstrap']:
                    raise Denied('bootstrap_not_prospective')
                found = {}
                # Small indexed-by-sequence suffix; only records of this data batch are accepted.
                for r in read.execute('SELECT body,sha FROM events WHERE seq>? AND seq<=?',(data['seq'],data['seq']+2)):
                    v = strict(r['body'])
                    if digest(v) != r['sha'] or v['run'] != self.run or v['payload'].get('data_sha256') != data_sha:
                        raise Denied('confirmation_identity')
                    found[v['kind']] = (v,r['sha'])
                if set(found) != {'confirmation','acknowledgement'}:
                    raise Denied('persistence_unconfirmed')
                seal, seal_sha = found['confirmation']; ack, _ = found['acknowledgement']
                if seal['previous'] != data_sha or ack['previous'] != seal_sha or ack['payload']['confirmation_sha256'] != seal_sha:
                    raise Denied('confirmation_chain')
            observed = self.clock.sample()
            if observed['utc_ns'] > deadline_ns:
                raise Denied('availability_deadline_missed')
            return dict(data_sha256=data_sha, observed_visible=observed,
                        deadline_ns=deadline_ns, scope='INPUT_AVAILABILITY_ONLY_NO_ORDER_AUTHORIZATION')
        except (OSError,sqlite3.Error):
            self.failed = True
            raise

    def close(self):
        self.db.close()
        self.lock.close()


def read_market(source, protocol, clock):
    started = clock.sample()
    market, _ = read_blob(Path(source)/'market.json')
    hashed(market, 'record_hash')
    if market['scope'] != 'RESEARCH_SIMULATION_ONLY' or set(market['quotes']) != set(protocol['signal']['universe']):
        raise Denied('market_scope_or_universe')
    if len(market['capture_ids']) != 55 or len(set(market['capture_ids'])) != 55:
        raise Denied('market_capture_count')
    end = timestamp(market['observed_at_end'])
    if not timestamp(market['observed_at_start']) <= end <= clock.sample()['utc_ns']:
        raise Denied('market_clock')
    raw, normalized = [], []
    counts = Counter()
    for key in market['capture_ids']:
        if not isinstance(key,str) or len(key) != 64 or any(x not in '0123456789abcdef' for x in key):
            raise Denied('capture_path')
        path = Path(source)/'raw'/(key+'.json.gz')
        if not path.exists():
            path = Path(source)/'raw'/(key+'.json')
        receipt, _ = read_blob(path)
        if receipt['capture_id'] != key:
            raise Denied('capture_identity')
        if selected(receipt['url'], protocol['signal']['universe']):
            kind, value = normalize(receipt,market,protocol,clock.sample()['utc_ns'])
            counts[kind] += 1
            raw.append(receipt); normalized.append(dict(kind=kind,value=value))
    if counts['mark'] != 18 or counts['calendar'] != 1 or counts['rate']+counts['rates_missing'] != 1:
        raise Denied('market_required_inputs')
    completed = clock.sample()
    return market['record_hash'], dict(market=market,receipts=raw,normalized=normalized), started, completed, end


class BookReader:
    """Short RO transactions over the primary-key suffix; never pin source WAL."""
    def __init__(self, path, clock):
        self.path, self.clock = Path(path), clock
        self.last_validated = None
        self.identity = (self.path.stat().st_dev,self.path.stat().st_ino)
        with closing(ro(self.path)) as db:
            self.cursor = db.execute('SELECT COALESCE(MAX(id),0) FROM book_events').fetchone()[0]

    def poll(self, limit=200):
        before = self.clock.sample()
        if (self.path.stat().st_dev,self.path.stat().st_ino) != self.identity:
            raise Denied('source_file_replaced')
        with closing(ro(self.path)) as db:
            if db.execute('SELECT COALESCE(MAX(id),0) FROM book_events').fetchone()[0] < self.cursor:
                raise Denied('source_cursor_regression')
            rows = [dict(r) for r in db.execute('SELECT * FROM book_events WHERE id>? ORDER BY id LIMIT ?', (self.cursor,limit+1))]
        after = self.clock.sample()
        if len(rows)>limit:
            raise Denied('source_backlog_not_skipped')
        if not rows:
            return None
        previous = self.last_validated if self.last_validated and self.last_validated['id']==self.cursor else None
        for row in rows:
            if previous and (row['id']<=previous['id'] or row['received_ts_ns']<previous['received_ts_ns'] or
                    (row['session_id']==previous['session_id'] and row['exchange_ts_ns']<previous['exchange_ts_ns'])):
                raise Denied('source_chronology_regression')
            previous=row
            received, exchange = row['received_ts_ns'],row['exchange_ts_ns']
            if type(received) is not int or type(exchange) is not int or not 0<exchange<=received<=after['utc_ns']:
                raise Denied('book_clock')
            bids, asks = [], []
            for side,prices in [('bid',bids),('ask',asks)]:
                for level in range(1,6):
                    price,size=row[f'{side}_price_{level}'],row[f'{side}_size_{level}']
                    if type(price) not in (int,float) or type(size) not in (int,float) or not math.isfinite(price) or not math.isfinite(size) or price<=0 or size<=0:
                        raise Denied('book_level')
                    prices.append(price)
            if bids != sorted(set(bids),reverse=True) or asks != sorted(set(asks)) or bids[0]>=asks[0]:
                raise Denied('book_order')
            key=row['payload_sha256']
            if len(key)!=64 or any(x not in '0123456789abcdef' for x in key):
                raise Denied('source_payload_hash_syntax')
        self.last_validated=rows[-1]
        # Caller must persist before advancing the in-memory cursor.
        return dict(rows=rows,cursor_before=self.cursor,source_identity=list(self.identity)), before,after
