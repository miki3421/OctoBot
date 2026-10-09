"""Paper-only V13 BTC issuer. No strategy import, ledger or control writer."""
from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import json
import math
import os
import pathlib
import secrets
import sqlite3
import stat

from octobot.ai_strategy_lab import paper_authorization as auth

UTC = dt.timezone.utc
PROPOSAL_KEYS = frozenset(('schema_version','experiment_id','account','symbol','strategy',
    'strategy_lineage_hash','decision_id','direction','target_weight','decision_timestamp',
    'available_at','source_record_hash'))
RECORD_KEYS = frozenset(('proposal','previous_record_hash','record_hash'))
MAX_AGE = dt.timedelta(minutes=30)
POLICY_VERSION = 'v13-btc-admissibility-v1'
CONFIG_V1_KEYS = {'schema_version','protocol_path','protocol_sha256','journal_path',
                  'producer_uid','issuer_uid','executor_gid','approval_db'}
CONFIG_V2_EXTRA = {'archive_path','archive_uid','research_contract_path',
                   'research_contract_sha256','producer_code_sha256','verifier_code_sha256'}


def _read_json(path, *, owner=None):
    if owner == 0:
        parent=pathlib.Path(path).parent
        info=parent.stat()
        if parent.is_symlink() or info.st_uid != 0 or info.st_mode & 0o022:
            raise ValueError('trusted_config_directory_invalid')
    fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW)
    try:
        info = os.fstat(fd)
        if not stat.S_ISREG(info.st_mode) or info.st_mode & 0o022 or (owner is not None and info.st_uid != owner):
            raise ValueError('source_ownership_invalid')
        with os.fdopen(fd) as stream:
            return json.load(stream, object_pairs_hook=auth.unique_object)
    except BaseException:
        try: os.close(fd)
        except OSError: pass
        raise


def _root_config(path):
    doc = _read_json(path, owner=0)
    version = doc.get('schema_version')
    if (type(version) is not int or version not in (1,2)
        or set(doc) != CONFIG_V1_KEYS | (CONFIG_V2_EXTRA if version == 2 else set())):
        raise ValueError('issuer_config_invalid')
    paths = ('protocol_path','journal_path','approval_db') + (
        ('archive_path','research_contract_path') if version == 2 else ())
    if not all(isinstance(doc[k],str) and pathlib.Path(doc[k]).is_absolute() for k in paths):
        raise ValueError('issuer_paths_invalid')
    if (not auth.sha(doc['protocol_sha256']) or type(doc['producer_uid']) is not int
        or type(doc['issuer_uid']) is not int or type(doc['executor_gid']) is not int):
        raise ValueError('issuer_config_invalid')
    if version == 2 and (type(doc['archive_uid']) is not int
        or doc['archive_uid'] in (doc['producer_uid'],doc['issuer_uid']) or not all(
        auth.sha(doc[k]) for k in ('research_contract_sha256','producer_code_sha256',
                                   'verifier_code_sha256'))):
        raise ValueError('issuer_source_config_invalid')
    if os.geteuid() != doc['issuer_uid']:
        raise ValueError('issuer_uid_invalid')
    protocol = _read_json(doc['protocol_path'], owner=0)
    if auth.digest(protocol) != doc['protocol_sha256']:
        raise ValueError('protocol_hash_mismatch')
    if (protocol.get('schema_version') != 1 or protocol.get('account') != 'v13-paper-v2'
        or protocol.get('symbol') != 'BTC/USDT:USDT' or protocol.get('exchange_symbol') != 'XBTUSDTM'
        or protocol.get('risk_policy_version') != 'risk-policy-v13-btc-paper-v1'
        or not auth.sha(protocol.get('lineage_root'))
        or protocol.get('inherited_authorizations') is not False
        or protocol.get('inherited_performance') is not False):
        raise ValueError('protocol_identity_invalid')
    if protocol.get('producer_status') == 'VALIDATED':
        implementation = protocol.get('producer_implementation')
        if (not isinstance(implementation,dict) or set(implementation) != {'path','sha256'}
            or not isinstance(implementation['path'],str)
            or not pathlib.Path(implementation['path']).is_absolute()
            or not auth.sha(implementation['sha256'])):
            raise ValueError('producer_implementation_invalid')
        fd = os.open(implementation['path'],os.O_RDONLY|os.O_NOFOLLOW)
        try:
            info = os.fstat(fd)
            if not stat.S_ISREG(info.st_mode) or info.st_uid != 0 or info.st_mode & 0o022:
                raise ValueError('producer_implementation_ownership_invalid')
            with os.fdopen(fd,'rb') as stream:
                digest = hashlib.sha256(stream.read()).hexdigest()
        except BaseException:
            try: os.close(fd)
            except OSError: pass
            raise
        if digest != implementation['sha256']:
            raise ValueError('producer_implementation_hash_mismatch')
        if version == 2 and digest != doc['producer_code_sha256']:
            raise ValueError('producer_code_binding_mismatch')
    return doc, protocol


def _journal_records(path, owner, *, research=False):
    parent = pathlib.Path(path).parent
    directory = parent.stat()
    if parent.is_symlink() or directory.st_uid != owner or directory.st_mode & 0o027:
        raise ValueError('producer_directory_ownership_invalid')
    fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW)
    try:
        info = os.fstat(fd)
        if not stat.S_ISREG(info.st_mode) or info.st_uid != owner or info.st_mode & 0o022:
            raise ValueError('producer_journal_ownership_invalid')
        if info.st_size > 64*1024*1024:
            raise ValueError('producer_journal_too_large')
        with os.fdopen(fd,'rb') as stream:
            data = stream.read()
    except BaseException:
        try: os.close(fd)
        except OSError: pass
        raise
    if not data.endswith(b'\n'):
        raise ValueError('producer_journal_partial')
    previous = None
    keys = frozenset(('result' if research else 'proposal','previous_record_hash','record_hash'))
    value_key = 'result' if research else 'proposal'
    for line in data.splitlines():
        record = json.loads(line, object_pairs_hook=auth.unique_object)
        if not isinstance(record,dict) or set(record) != keys:
            raise ValueError('producer_record_schema_invalid')
        if record['previous_record_hash'] != previous or record['record_hash'] != auth.digest(
                {value_key:record[value_key],'previous_record_hash':previous}):
            raise ValueError('producer_chain_invalid')
        previous = record['record_hash']
        yield record


def _source_archive(config):
    root = pathlib.Path(config['archive_path'])
    for path in (root,root/'raw',root/'snapshots'):
        info = path.stat()
        if path.is_symlink() or not stat.S_ISDIR(info.st_mode) or info.st_uid != config['archive_uid'] or info.st_mode & 0o022:
            raise ValueError('source_archive_ownership_invalid')
    for directory in (root/'raw',root/'snapshots'):
        for file in directory.iterdir():
            info = file.lstat()
            if not stat.S_ISREG(info.st_mode) or info.st_uid != config['archive_uid'] or info.st_mode & 0o022:
                raise ValueError('source_archive_file_ownership_invalid')
    return root


def _pinned_root_json(path, expected_hash):
    parent = pathlib.Path(path).parent
    parent_info = parent.stat()
    if parent.is_symlink() or parent_info.st_uid != 0 or parent_info.st_mode & 0o022:
        raise ValueError('trusted_config_directory_invalid')
    fd = os.open(path,os.O_RDONLY|os.O_NOFOLLOW)
    try:
        info = os.fstat(fd)
        if not stat.S_ISREG(info.st_mode) or info.st_uid != 0 or info.st_mode & 0o022 or info.st_size > 1024*1024:
            raise ValueError('trusted_source_invalid')
        with os.fdopen(fd,'rb') as stream:
            data = stream.read()
    except BaseException:
        try: os.close(fd)
        except OSError: pass
        raise
    if hashlib.sha256(data).hexdigest() != expected_hash:
        raise ValueError('research_contract_hash_mismatch')
    return json.loads(data,object_pairs_hook=auth.unique_object)


def _research_proposal(config, protocol, result):
    from octobot.ai_strategy_lab import v13_btc_research_verify as verifier
    contract = _pinned_root_json(config['research_contract_path'],
                                 config['research_contract_sha256'])
    verifier_path = pathlib.Path(verifier.__file__)
    verifier_info = verifier_path.lstat()
    if (not stat.S_ISREG(verifier_info.st_mode) or verifier_info.st_uid != 0
        or verifier_info.st_mode & 0o022 or hashlib.sha256(verifier_path.read_bytes()).hexdigest()
        != config['verifier_code_sha256']):
        raise ValueError('verifier_code_hash_mismatch')
    archive = _source_archive(config)
    verified = verifier.verify(archive,config['research_contract_path'],
        verifier.producer.digest(contract),config['producer_code_sha256'],result)
    if verified['status'] != 'PROPOSAL':
        raise ValueError('research_no_proposal')
    source = result['payload']
    if source.get('research_only') is not True or source.get('execution_approved') is not False:
        raise ValueError('research_flags_invalid')
    proposal = dict(schema_version=1,experiment_id=source['experiment_id'],
        account=source['account'],symbol=source['symbol'],strategy=source['strategy'],
        strategy_lineage_hash=source['strategy_lineage_hash'],direction=source['direction'],
        target_weight=float(source['target_weight']),
        decision_timestamp=source['decision_timestamp'],available_at=source['available_at'],
        source_record_hash=source['source_record_hash'])
    proposal['decision_id']=auth.digest(proposal)
    if contract.get('status') != 'PAPER_CANDIDATE_APPROVED_FOR_ISSUER':
        raise ValueError('research_only_not_issuable')
    return proposal


def _validate_proposal(record, protocol, now):
    proposal = record['proposal']
    if not isinstance(proposal,dict) or set(proposal) != PROPOSAL_KEYS or type(proposal['schema_version']) is not int or proposal['schema_version'] != 1:
        raise ValueError('proposal_schema_invalid')
    for key, expected in (('experiment_id',protocol['experiment_id']),('account',protocol['account']),
                          ('symbol',protocol['symbol']),('strategy',protocol['strategy']),
                          ('strategy_lineage_hash',protocol['lineage_root'])):
        if proposal[key] != expected:
            raise ValueError('proposal_identity_invalid')
    if not auth.sha(proposal['source_record_hash']) or not auth.sha(proposal['decision_id']):
        raise ValueError('proposal_source_invalid')
    basis = {key:value for key,value in proposal.items() if key != 'decision_id'}
    if auth.digest(basis) != proposal['decision_id']:
        raise ValueError('proposal_decision_hash_invalid')
    at, available = auth.timestamp(proposal['decision_timestamp']), auth.timestamp(proposal['available_at'])
    if available > at or at > now or now-at > MAX_AGE:
        raise ValueError('proposal_time_invalid')
    weight = proposal['target_weight']
    if type(weight) not in (int,float) or not math.isfinite(weight) or abs(weight) > .315:
        raise ValueError('proposal_target_invalid')
    if (proposal['direction'],weight) not in (('FLAT',0),) and not (
        (proposal['direction']=='LONG' and weight>0) or (proposal['direction']=='SHORT' and weight<0)):
        raise ValueError('proposal_direction_invalid')
    return proposal


def initialize(db_path):
    path = pathlib.Path(db_path)
    path.parent.mkdir(parents=True,exist_ok=True)
    with sqlite3.connect(path) as db:
        # A different UID opens this database read-only. Rollback journal mode
        # avoids requiring write access to the issuer directory for WAL/-shm.
        db.execute('PRAGMA journal_mode=DELETE')
        db.execute('PRAGMA synchronous=FULL')
        db.executescript('''CREATE TABLE IF NOT EXISTS approvals (
            decision_id TEXT PRIMARY KEY, approval_id TEXT UNIQUE, experiment_id TEXT,
            account TEXT, symbol TEXT, strategy TEXT, lineage_hash TEXT,
            direction TEXT, target_weight REAL, decision_at TEXT, available_at TEXT,
            source_hash TEXT, producer_record_hash TEXT, issuer_policy_version TEXT,
            protocol_hash TEXT, approved_at TEXT, expires_at TEXT,
            result TEXT NOT NULL CHECK(result IN ('APPROVE','DENY')), reason_code TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS issuer_events (
            id INTEGER PRIMARY KEY, checked_at TEXT NOT NULL, result TEXT NOT NULL, reason_code TEXT NOT NULL,
            record_hash TEXT);
        ''')


def issue(config_path, *, now=None):
    now = now or dt.datetime.now(UTC)
    config, protocol = _root_config(config_path)
    if protocol.get('producer_status') != 'VALIDATED' or not protocol.get('producer_implementation'):
        raise ValueError('producer_unresolved')
    approval_path = pathlib.Path(config['approval_db'])
    directory = approval_path.parent.stat()
    file_info = approval_path.stat()
    if (approval_path.is_symlink() or approval_path.parent.is_symlink()
        or directory.st_uid != config['issuer_uid'] or directory.st_gid != config['executor_gid']
        or directory.st_mode & 0o027 or not directory.st_mode & stat.S_IRGRP
        or not directory.st_mode & stat.S_IXGRP
        or file_info.st_uid != config['issuer_uid']
        or file_info.st_gid != config['executor_gid'] or file_info.st_mode & 0o137
        or not file_info.st_mode & stat.S_IRGRP or not file_info.st_mode & stat.S_IWUSR):
        raise ValueError('approval_storage_ownership_invalid')
    initialize(config['approval_db'])
    try:
        records = list(_journal_records(config['journal_path'],config['producer_uid'],
                                        research=config['schema_version']==2))
    except (ValueError,OSError,json.JSONDecodeError) as exc:
        with sqlite3.connect(config['approval_db']) as db:
            db.execute('INSERT INTO issuer_events(checked_at,result,reason_code,record_hash) VALUES (?,?,?,NULL)',
                       (now.isoformat(),'DENY',type(exc).__name__+':'+str(exc)))
        raise
    outcomes = []
    with sqlite3.connect(config['approval_db']) as db:
        db.execute('PRAGMA synchronous=FULL')
        for record in records:
            proposal = record.get('proposal',{})
            try:
                if config['schema_version']==2:
                    proposal = _research_proposal(config,protocol,record['result'])
                proposal = _validate_proposal({'proposal':proposal},protocol,now)
                result, reason = 'APPROVE','admissible'
            except (ValueError,KeyError,TypeError,OSError) as exc:
                result, reason = 'DENY',str(exc)
            decision_id = proposal.get('decision_id') if isinstance(proposal,dict) else None
            if not auth.sha(decision_id):
                db.execute('INSERT INTO issuer_events(checked_at,result,reason_code,record_hash) VALUES (?,?,?,?)',
                           (now.isoformat(),'DENY',reason,record['record_hash']))
                outcomes.append((record['record_hash'],'DENY',reason))
                continue
            if db.execute('SELECT 1 FROM approvals WHERE decision_id=?',(decision_id,)).fetchone():
                db.execute('INSERT INTO issuer_events(checked_at,result,reason_code,record_hash) VALUES (?,?,?,?)',
                           (now.isoformat(),'DENY','duplicate_decision',record['record_hash']))
                outcomes.append((decision_id,'DENY','duplicate_decision'))
                continue
            approval_id = secrets.token_hex(32) if result == 'APPROVE' else None
            expires = (auth.timestamp(proposal['decision_timestamp'])+MAX_AGE).isoformat() if result == 'APPROVE' else None
            db.execute('INSERT INTO approvals VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)',
                (decision_id,approval_id,proposal.get('experiment_id'),proposal.get('account'),
                 proposal.get('symbol'),proposal.get('strategy'),proposal.get('strategy_lineage_hash'),
                 proposal.get('direction'),proposal.get('target_weight'),proposal.get('decision_timestamp'),
                 proposal.get('available_at'),proposal.get('source_record_hash'),record['record_hash'],
                 POLICY_VERSION,config['protocol_sha256'],now.isoformat(),expires,result,reason))
            db.execute('INSERT INTO issuer_events(checked_at,result,reason_code,record_hash) VALUES (?,?,?,?)',
                       (now.isoformat(),result,reason,record['record_hash']))
            outcomes.append((decision_id,result,reason))
    return outcomes


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--config',required=True,type=pathlib.Path)
    args=parser.parse_args()
    print(json.dumps(issue(args.config)))


if __name__ == '__main__':
    main()
