"""Isolated M1 approval writer over a local Unix socket. No execution DB access.

The browser cannot create authority by claiming approved=true. Only a password
verified here records a decision in this process-owned, append-only approval DB.
"""
import argparse
import datetime as dt
import hashlib
import hmac
import json
import os
from pathlib import Path
import socket
import sqlite3
import stat
import time
from . import v13_m1_weekly as weekly


def safe_file(path,uid):
    path=Path(path);info=path.lstat()
    if not stat.S_ISREG(info.st_mode) or info.st_uid!=uid or info.st_mode&0o022:
        raise ValueError('custody_invalid')
    return path


def password_valid(value,verifier):
    if not isinstance(value,str) or not 12<=len(value)<=256:return False
    actual=hashlib.scrypt(value.encode(),salt=bytes.fromhex(verifier['salt']),n=16384,r=8,p=1,dklen=32)
    return hmac.compare_digest(actual.hex(),verifier['scrypt'])


class Store:
    def __init__(self,path,account):
        path=Path(path);created=not path.exists()
        if path.is_symlink():raise ValueError('approval_store_symlink')
        if not created:safe_file(path,os.geteuid())
        self.db=sqlite3.connect(path,timeout=2);self.db.row_factory=sqlite3.Row
        if created:os.chmod(path,0o640)
        self.db.execute('PRAGMA synchronous=FULL')
        self.db.executescript('CREATE TABLE IF NOT EXISTS identity(account TEXT PRIMARY KEY); '
                             'CREATE TABLE IF NOT EXISTS decisions(id TEXT PRIMARY KEY,account TEXT NOT NULL,proposal_id TEXT UNIQUE NOT NULL,parent_revision INTEGER NOT NULL,action TEXT NOT NULL,decided_at TEXT NOT NULL,payload TEXT NOT NULL); '
                             'DROP INDEX IF EXISTS one_approval_per_revision; '
                             'CREATE INDEX IF NOT EXISTS decisions_revision ON decisions(account,parent_revision);')
        rows=self.db.execute('SELECT account FROM identity').fetchall()
        if rows and [r[0] for r in rows]!=[account]:raise ValueError('approval_account_mismatch')
        if not rows:
            with self.db:self.db.execute('INSERT INTO identity VALUES(?)',(account,))
        self.account=account

    def record(self,proposal,*,action,exclude_short,at,components=None):
        weekly.verify(proposal,'proposal_id')
        from . import v13_m1_transition as transition
        is_v2=proposal.get('version')==transition.VERSION
        if proposal['account']!=self.account or proposal['scope'] not in ('M1_RESEARCH_PAPER_WEEKLY_PROPOSAL',transition.SCOPE):raise ValueError('proposal_account')
        if is_v2:
            transition.validate(proposal)
            if components!=list(transition.COMPONENTS) or exclude_short:raise ValueError('transition_components')
        elif components is not None:raise ValueError('legacy_components_forbidden')
        if action not in ('APPROVE','REJECT') or not weekly.when(proposal['created_at'])<=weekly.when(at)<=weekly.when(proposal['expires_at']):raise ValueError('decision_action_or_expiry')
        if type(exclude_short) is not list or len(set(exclude_short))!=len(exclude_short):raise ValueError('short_exclusions')
        if not set(exclude_short)<={s for s,v in proposal['short_caps'].items() if v>0}:raise ValueError('short_exclusion_scope')
        decision=dict(account=self.account,proposal_id=proposal['proposal_id'],parent_revision=proposal['parent_revision'],action=action,exclude_short=sorted(exclude_short),decided_at=at,proposal_expires_at=proposal['expires_at'],actor='authenticated_operator',scope='M1_PAPER_MAINTENANCE_ONLY')
        if is_v2:decision['components']=list(components)
        decision['decision_id']=weekly.digest(decision)
        if action=='APPROVE':weekly.approved_policy(proposal,decision,proposal['parent_revision'],at)
        with self.db:
            old=self.db.execute('SELECT payload FROM decisions WHERE proposal_id=?',(proposal['proposal_id'],)).fetchone()
            if old:
                saved=json.loads(old[0])
                if saved['action']==action and saved['exclude_short']==sorted(exclude_short) and saved.get('components')==components:return saved
                raise ValueError('decision_conflict')
            if action=='APPROVE':
                for row in self.db.execute("SELECT payload FROM decisions WHERE account=? AND parent_revision=? AND action='APPROVE'",(self.account,proposal['parent_revision'])):
                    if weekly.when(json.loads(row[0])['proposal_expires_at'])>=weekly.when(at):
                        raise ValueError('another_unexpired_approval_for_revision')
            self.db.execute('INSERT INTO decisions VALUES(?,?,?,?,?,?,?)',(decision['decision_id'],self.account,proposal['proposal_id'],proposal['parent_revision'],action,at,json.dumps(decision,sort_keys=True,separators=(',',':'))))
        return decision

    def close(self):self.db.close()


class Broker:
    def __init__(self,config):
        self.c=config;self.store=Store(config['database'],config['account']);self.failures=[]

    def handle(self,request,peer_uid):
        if not isinstance(request,dict):raise ValueError('request_object_required')
        if request.get('operation')=='status' and peer_uid in self.c['web_peer_uids']+[self.c.get('approval_uid',os.geteuid())]:
            try:
                verifier=json.loads(safe_file(self.c['verifier'],0).read_text())
                configured=verifier.get('algorithm')=='scrypt-v1' and len(bytes.fromhex(verifier['scrypt']))==32 and len(bytes.fromhex(verifier['salt']))>=16
            except (OSError,ValueError,KeyError,TypeError):configured=False
            return dict(scope='M1_APPROVAL_WRITER_STATUS_V1',account=self.c['account'],authentication_configured=configured)
        if peer_uid not in self.c['web_peer_uids']:raise ValueError('peer_denied')
        if request.get('operation')!='decision':raise ValueError('operation_denied')
        now=time.monotonic();self.failures=[t for t in self.failures if t>now-60]
        if len(self.failures)>=5:raise ValueError('authentication_throttled')
        verifier=json.loads(safe_file(self.c['verifier'],0).read_text())
        if not password_valid(request.get('password'),verifier):
            self.failures.append(now);raise ValueError('authentication_failed')
        value=json.loads(safe_file(self.c['projection'],self.c['runner_uid']).read_text())
        proposal=value['proposal']
        if not proposal or request['proposal_id']!=proposal['proposal_id'] or value['account']!=self.c['account']:
            raise ValueError('proposal_changed_reload_required')
        if self.c.get('transition_only') and proposal.get('version')!='m1-long-maintenance-v2':raise ValueError('legacy_approval_disabled')
        return self.store.record(proposal,action=request['action'],exclude_short=request.get('exclude_short',[]),components=request.get('components'),at=dt.datetime.now(weekly.UTC).isoformat())


def main():
    parser=argparse.ArgumentParser();parser.add_argument('--config',required=True);args=parser.parse_args()
    config=json.loads(safe_file(args.config,0).read_text())
    if (config['scope']!='M1_APPROVAL_WRITER_V1' or os.geteuid()!=config['approval_uid'] or config['approval_uid']<=0
        or config['approval_uid']==config['runner_uid']):raise ValueError('approval_writer_identity')
    broker=Broker(config);path=Path(config['socket'])
    import fcntl
    lock=open(config['database']+'.lock','a');fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
    if path.exists():
        if not stat.S_ISSOCK(path.lstat().st_mode) or path.stat().st_uid!=os.geteuid():raise ValueError('socket_custody')
        path.unlink()
    server=socket.socket(socket.AF_UNIX,socket.SOCK_STREAM);server.bind(str(path));os.chmod(path,0o660);server.listen(8)
    try:
        while True:
            connection,_=server.accept()
            with connection:
                connection.settimeout(5)
                try:
                    import struct
                    _,uid,_=struct.unpack('3i',connection.getsockopt(socket.SOL_SOCKET,socket.SO_PEERCRED,12))
                    raw=b''
                    while b'\n' not in raw:
                        part=connection.recv(4096)
                        if not part or len(raw)+len(part)>16384:raise ValueError('request_size')
                        raw+=part
                    if raw.count(b'\n')!=1 or raw[-1:]!=b'\n':raise ValueError('request_frame')
                    result=dict(ok=True,decision=broker.handle(json.loads(raw),uid))
                except (OSError,ValueError,KeyError,TypeError,sqlite3.Error):
                    result=dict(ok=False,error='Decisione non registrata: verificare password, scadenza e versione della proposta.')
                try:connection.sendall(json.dumps(result).encode()+b'\n')
                except OSError:pass
    finally:server.close();broker.store.close()


if __name__=='__main__':main()
