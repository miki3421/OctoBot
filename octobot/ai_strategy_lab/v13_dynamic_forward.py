"""Separate offline forward receipt archive; no network or service activation.

Ingests raw HTTP receipts matching the existing public endpoint schedule.
Unlike the qualification DB, this archive is not limited to its 14-day window.
The authorized collector supplies receipts; the strategy must not own this DB.
"""
import gzip
import json
import sqlite3
from pathlib import Path
try:
    from . import v13_dynamic_data as data
except ImportError:
    import v13_dynamic_data as data

SCOPE='ABC_FORWARD_RAW_RECEIPTS_V1'


class ForwardArchive:
    def __init__(self,path,repo,*,create=False,writable=False):
        self.path=Path(path).absolute();self.plan=data.capture.load_plan(Path(repo));self.writable=writable or create
        self._jobs={}
        if self.path.is_symlink():raise ValueError('forward_symlink')
        if create:
            with self.path.open('xb'):pass
        elif not self.path.is_file():raise ValueError('forward_missing')
        self.db=sqlite3.connect(self.path.as_uri()+('?mode=rw' if self.writable else '?mode=ro'),uri=True,isolation_level=None)
        self.db.row_factory=sqlite3.Row
        try:
            self.db.execute('PRAGMA trusted_schema=OFF')
            self.db.execute('PRAGMA synchronous=FULL')
            if not self.writable:self.db.execute('PRAGMA query_only=ON')
            if create:
                self.db.executescript('BEGIN; CREATE TABLE marker(scope TEXT,plan_hash TEXT); CREATE TABLE jobs(id TEXT PRIMARY KEY,kind TEXT,symbol TEXT,slot REAL,deadline REAL,url TEXT,started REAL,received REAL,status INTEGER,raw_hash TEXT,raw_gzip BLOB,metrics TEXT,state TEXT,error TEXT);')
                self.db.execute('INSERT INTO marker VALUES (?,?)',(SCOPE,data.capture.PLAN_HASH));self.db.execute('COMMIT')
            if [tuple(r) for r in self.db.execute('SELECT * FROM marker')]!=[(SCOPE,data.capture.PLAN_HASH)]:raise ValueError('forward_binding')
        except BaseException:self.db.close();raise

    def close(self):self.db.close()

    def jobs(self,day):
        if day not in self._jobs:
            self._jobs={day:{str(int(day))+':'+j[0]:j for j in data.capture.schedule(self.plan,day) if j[3]<day+86400}}
        return self._jobs[day]

    def _collector(self,day):
        return data.capture.Collector(self.path.parent,self.plan,day,'FORWARD_READ_ONLY',None)

    def ingest(self,job_id,*,day,url,started,received,status,raw):
        if not self.writable:raise ValueError('forward_read_only')
        job=self.jobs(day).get(job_id)
        if job is None or job[5]!=url or status!=200:raise ValueError('forward_request_binding')
        _,kind,symbol,slot,deadline,_=job
        if not slot<=started<=received<=deadline:raise ValueError('forward_receipt_time')
        if not isinstance(raw,bytes) or len(raw)>(4*1024*1024 if kind.endswith('metadata') else 64*1024):raise ValueError('forward_raw_size')
        self.db.execute('BEGIN IMMEDIATE')
        try:
            collector=self._collector(day);contract=None
            if not kind.endswith('metadata'):
                contract=collector.contracts(self.db,slot)[symbol]
                available=max(r[0] for r in self.db.execute("SELECT received FROM jobs WHERE slot=? AND kind IN ('kucoin_metadata','binance_metadata')",(day,)))
                if started<available:raise ValueError('noncausal_metadata')
            metrics=collector.validate(dict(kind=kind,slot=slot,deadline=deadline),raw,received,contract)
            values=(job_id,kind,symbol,slot,deadline,url,started,received,status,data.capture.sha(raw),gzip.compress(raw,mtime=0),data.capture.canonical(metrics).decode(),'valid',None)
            old=self.db.execute('SELECT * FROM jobs WHERE id=?',(job_id,)).fetchone()
            if old:
                if tuple(old)!=values:raise ValueError('forward_receipt_conflict')
            else:self.db.execute('INSERT INTO jobs VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)',values)
            self.db.execute('COMMIT')
        except BaseException:
            if self.db.in_transaction:self.db.execute('ROLLBACK')
            raise

    def read(self,day,as_of,kinds=('books','funding','daily')):
        if not set(kinds)<={'books','funding','daily'}:raise ValueError('forward_kinds')
        self.db.execute('BEGIN')
        try:
            collector=self._collector(day)
            metadata=list(self.db.execute("SELECT * FROM jobs WHERE slot=? AND kind IN ('kucoin_metadata','binance_metadata')",(day,)))
            if len(metadata)!=2:raise ValueError('forward_metadata_missing')
            expected=self.jobs(day)
            def verify(row,contract):
                job=expected.get(row['id'])
                if job is None or tuple(row[k] for k in ('kind','symbol','slot','deadline','url'))!=job[1:]:raise ValueError('forward_stored_binding')
                if row['received']>as_of:raise ValueError('forward_future_receipt')
                data.verify.verify_valid_row(collector,row,contract)
            for row in metadata:verify(row,None)
            contracts=collector.contracts(self.db,day);available=max(r['received'] for r in metadata)
            output=[]
            for row in self.db.execute('SELECT * FROM jobs WHERE slot>=? AND slot<? AND received<=? ORDER BY slot,id',(day,day+86400,as_of)):
                if row['kind'] not in kinds:continue
                verify(row,contracts[row['symbol']])
                if row['started']<available:raise ValueError('noncausal_metadata')
                record=data.project(collector,row,contracts[row['symbol']],as_of)
                record['scope']='VERIFIED_FORWARD_RECEIPT'
                if row['kind']=='books':record.update(precision=data.precision(contracts[row['symbol']]),metadata_hashes={r['kind']:r['raw_hash'] for r in metadata},metadata_received_at=data.dt.datetime.fromtimestamp(available,data.dt.timezone.utc).isoformat())
                output.append(record)
            self.db.execute('COMMIT');return output
        except BaseException:
            if self.db.in_transaction:self.db.execute('ROLLBACK')
            raise


class Collector:
    """One scheduled pass over public requests, supplied by an authorized runner.

    No catch-up outside the receipt deadline. Successful requests persist before
    the next pass; restart does not redownload them. Failure stays an error.
    """
    def __init__(self,archive,fetch,clock):
        if not archive.writable:raise ValueError('collector_requires_writer')
        self.archive=archive;self.fetch=fetch;self.clock=clock
        self.archive.db.execute('CREATE TABLE IF NOT EXISTS collector_control (reason TEXT NOT NULL)')

    def step(self):
        if self.archive.db.execute('SELECT 1 FROM collector_control').fetchone():
            raise ValueError('collector_requires_operator_review')
        now=self.clock();day=now//86400*86400;result=[]
        for ident,job in self.archive.jobs(day).items():
            _,kind,symbol,slot,deadline,url=job
            if self.archive.db.execute('SELECT 1 FROM jobs WHERE id=?',(ident,)).fetchone():continue
            started=self.clock()
            if not slot<=started<=deadline:continue
            try:
                # Do not download symbol data before today's metadata is valid.
                if not kind.endswith('metadata'):
                    self.archive._collector(day).contracts(self.archive.db,slot)
                status,raw=self.fetch(url,4*1024*1024 if kind.endswith('metadata') else 64*1024)
                if status in (418,429):
                    self.archive.db.execute('INSERT INTO collector_control VALUES (?)',('public_endpoint_rate_limit',))
                    result.append(dict(id=ident,state='halted_rate_limit'));break
                self.archive.ingest(ident,day=day,url=url,started=started,received=self.clock(),status=status,raw=raw)
                result.append(dict(id=ident,state='valid'))
            except (ValueError,KeyError,OSError,sqlite3.Error):
                result.append(dict(id=ident,state='failed'))
        return result


def main(argv=None):
    import argparse
    import hashlib
    import os
    import time
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--config',required=True);parser.add_argument('--config-sha256',required=True)
    parser.add_argument('--once',action='store_true')
    args=parser.parse_args(argv);path=Path(args.config)
    data.capture.safe_path(path,0);raw=path.read_bytes()
    if hashlib.sha256(raw).hexdigest()!=args.config_sha256:raise ValueError('forward_config_pin')
    config=json.loads(raw)
    if config.get('scope')!='ABC_FORWARD_COLLECTOR_CONFIGURATION_V1' or config.get('public_downloads_authorized') is not True:
        raise ValueError('public_collection_authorization_required')
    if type(config['collector_uid']) is not int or config['collector_uid']==0 or os.geteuid()!=config['collector_uid']:
        raise ValueError('dedicated_collector_required')
    if type(config['poll_seconds']) is not int or not 5<=config['poll_seconds']<=30:raise ValueError('poll_interval')
    data.store_path(config['archive'],config['collector_uid'])
    archive=ForwardArchive(config['archive'],config['repo'],writable=True)
    try:
        collector=Collector(archive,data.capture.public_get,time.time)
        while True:
            collector.step()
            if args.once:return 0
            time.sleep(config['poll_seconds'])
    finally:archive.close()


if __name__=='__main__':raise SystemExit(main())
