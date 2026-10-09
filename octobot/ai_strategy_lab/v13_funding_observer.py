"""Public-only prospective funding receipts. Never certifies trading readiness."""
import argparse
import datetime as dt
import fcntl
import gzip
import hashlib
import json
import math
import os
from pathlib import Path
import sqlite3
import time
import urllib.request
import urllib.error

INTERVAL=300
LIMIT=65536
CAP=256*1024*1024

class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self,*args,**kwargs):raise ValueError('redirect_forbidden')

def fetch(url):
    opener=urllib.request.build_opener(urllib.request.ProxyHandler({}),NoRedirect())
    try:response=opener.open(urllib.request.Request(url,headers={'Accept-Encoding':'identity','User-Agent':'V13FundingObserver/1'}),timeout=5)
    except urllib.error.HTTPError as exc:response=exc
    with response:return response.status,response.read(LIMIT+1)

def decode(raw):
    def bad(value):raise ValueError('nonfinite_json')
    return json.loads(raw,parse_constant=bad)

def validate(raw,remote,started,received):
    v=decode(raw)
    if v.get('code')!='200000':raise ValueError('api_code')
    data=v['data']
    if data['symbol']!='.'+remote+'FPI8H':raise ValueError('contract_identity')
    for field in ('granularity','timePoint','fundingTime'):
        if type(data[field]) is not int or data[field]<=0:raise ValueError('funding_timestamp')
    if not data['timePoint']<=received*1000<data['fundingTime']:raise ValueError('not_current_funding_window')
    if data['fundingTime']-data['timePoint']!=data['granularity']:raise ValueError('inconsistent_funding_window')
    for field in ('value','fundingRateCap','fundingRateFloor'):
        if type(data[field]) not in (int,float) or not math.isfinite(data[field]):raise ValueError('funding_rate')
    if received<started:raise ValueError('clock_regression')
    return data

class Archive:
    def __init__(self,path):
        path=Path(path)
        if path.is_symlink():raise ValueError('archive_symlink')
        self.db=sqlite3.connect(path,isolation_level=None)
        self.db.execute('PRAGMA synchronous=FULL')
        self.db.executescript('CREATE TABLE IF NOT EXISTS receipts(slot INTEGER,symbol TEXT,url TEXT,started REAL,received REAL,status INTEGER,raw_sha256 TEXT,raw_gzip BLOB,state TEXT,PRIMARY KEY(slot,symbol));CREATE TABLE IF NOT EXISTS controls(reason TEXT);')
    def close(self):self.db.close()
    def capture(self,mapping,clock=time.time,get=fetch):
        if self.db.execute('SELECT 1 FROM controls').fetchone():raise ValueError('operator_review_required')
        if self.db.execute('PRAGMA page_count').fetchone()[0]*self.db.execute('PRAGMA page_size').fetchone()[0]>=CAP:raise ValueError('archive_capacity')
        slot=int(clock()//INTERVAL)*INTERVAL;states=[]
        for symbol,remote in sorted(mapping.items()):
            if self.db.execute('SELECT 1 FROM receipts WHERE slot=? AND symbol=?',(slot,symbol)).fetchone():continue
            if not remote.isalnum() or not symbol.isalnum():raise ValueError('symbol_syntax')
            started=clock()
            if started>=slot+INTERVAL:break
            url='https://api-futures.kucoin.com/api/v1/funding-rate/'+remote+'/current'
            try:status,raw=get(url)
            except (OSError,ValueError):status,raw=0,b''
            received=clock();state='invalid'
            if status==200 and len(raw)<=LIMIT and received<slot+INTERVAL:
                try:validate(raw,remote,started,received);state='valid'
                except (ValueError,KeyError,TypeError):pass
            self.db.execute('BEGIN IMMEDIATE')
            try:
                self.db.execute('INSERT INTO receipts VALUES (?,?,?,?,?,?,?,?,?)',(slot,symbol,url,started,received,status,hashlib.sha256(raw).hexdigest(),gzip.compress(raw,mtime=0),state))
                if status in (418,429):self.db.execute('INSERT INTO controls VALUES (?)',('public_rate_limit',))
                self.db.execute('COMMIT')
            except BaseException:
                self.db.execute('ROLLBACK');raise
            states.append(state)
            if status in (418,429):break
        return dict(slot=slot,captured=len(states),valid=states.count('valid'),coverage_certified=False)

def main():
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--config',required=True);parser.add_argument('--sha256',required=True)
    args=parser.parse_args();path=Path(args.config)
    if path.is_symlink() or path.stat().st_uid!=0 or path.stat().st_mode&0o022:raise ValueError('config_custody')
    raw=path.read_bytes()
    if hashlib.sha256(raw).hexdigest()!=args.sha256:raise ValueError('config_pin')
    c=decode(raw)
    if c['public_downloads_authorized'] is not True or os.geteuid()==0 or os.geteuid()!=c['collector_uid']:raise ValueError('collector_authorization')
    if len(c['mapping'])!=29:raise ValueError('universe_size')
    with open(Path(c['archive']).with_suffix('.lock'),'a') as lock:
        fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
        archive=Archive(c['archive'])
        try:print(json.dumps(archive.capture(c['mapping'])))
        finally:archive.close()

if __name__=='__main__':main()
