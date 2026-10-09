"""Synthetic producer contract and real UID filesystem isolation; no live source."""
import datetime as dt
import json
import hashlib
import os
import pathlib
import shutil
import sqlite3
import tempfile

import pytest

from octobot.ai_strategy_lab import paper_authorization as auth
from octobot.ai_strategy_lab import v13_btc_issuer as issuer, v13_btc_approval as approval

pytestmark=pytest.mark.skipif(os.geteuid()!=0,reason='isolated real-UID test requires root')
NOW=dt.datetime(2026,9,25,12,tzinfo=dt.timezone.utc)


def as_uid(uid,gid,callback):
    reader,writer=os.pipe()
    pid=os.fork()
    if pid==0:
        os.close(reader)
        try:
            os.setgroups([])
            os.setgid(gid)
            os.setuid(uid)
            outcome={'ok':True,'value':callback()}
        except BaseException as exc:
            outcome={'ok':False,'error':type(exc).__name__+':'+str(exc)}
        os.write(writer,json.dumps(outcome).encode())
        os._exit(0)
    os.close(writer)
    result=json.loads(os.read(reader,16384))
    os.close(reader)
    os.waitpid(pid,0)
    return result


@pytest.fixture
def setup():
    root=pathlib.Path(tempfile.mkdtemp(prefix='v13-issuer-isolated-'))
    root.chmod(0o755)
    try:
        producer=root/'producer'; producer.mkdir(); os.chown(producer,30010,30020); producer.chmod(0o750)
        approvals=root/'approvals'; approvals.mkdir(); os.chown(approvals,30020,30000); approvals.chmod(0o750)
        approvals_db=approvals/'approvals.sqlite'; approvals_db.touch(); os.chown(approvals_db,30020,30000); approvals_db.chmod(0o640)
        execution=root/'execution'; execution.mkdir(); os.chown(execution,30000,30000); execution.chmod(0o700)
        source=root/'synthetic_producer.py'; source.write_text('# synthetic unit contract only\n')
        protocol=json.loads(pathlib.Path('octobot/ai_strategy_lab/v13_btc_experiment_protocol_v1.json').read_text())
        protocol.update(producer_status='VALIDATED',producer_implementation=dict(
            path=str(source),sha256=hashlib.sha256(source.read_bytes()).hexdigest()))
        protocol_path=root/'protocol.json'; protocol_path.write_text(json.dumps(protocol)); protocol_path.chmod(0o644)
        proposal=dict(schema_version=1,experiment_id=protocol['experiment_id'],account=protocol['account'],
            symbol=protocol['symbol'],strategy=protocol['strategy'],strategy_lineage_hash=protocol['lineage_root'],
            direction='LONG',target_weight=.1,decision_timestamp=(NOW-dt.timedelta(minutes=2)).isoformat(),
            available_at=(NOW-dt.timedelta(minutes=3)).isoformat(),source_record_hash='a'*64)
        proposal['decision_id']=auth.digest(proposal)
        record=dict(proposal=proposal,previous_record_hash=None)
        record['record_hash']=auth.digest(record)
        journal=producer/'proposals.jsonl'; journal.write_text(json.dumps(record)+'\n')
        os.chown(journal,30010,30020); journal.chmod(0o640)
        config=dict(schema_version=1,protocol_path=str(protocol_path),protocol_sha256=auth.digest(protocol),
            journal_path=str(journal),producer_uid=30010,issuer_uid=30020,executor_gid=30000,
            approval_db=str(approvals_db))
        config_path=root/'issuer.json';config_path.write_text(json.dumps(config));config_path.chmod(0o644)
        yield root,config_path,proposal,record,config
    finally:
        shutil.rmtree(root)


def test_synthetic_issuer_and_distinct_uid_storage(setup):
    root,config_path,proposal,record,config=setup
    result=as_uid(30020,30020,lambda:issuer.issue(config_path,now=NOW))
    assert result['ok'] and result['value'][0][1:] == ['APPROVE','admissible']
    with sqlite3.connect(config['approval_db']) as db:
        token=db.execute('SELECT approval_id FROM approvals').fetchone()[0]
        assert db.execute('PRAGMA integrity_check').fetchone()[0]=='ok'
    intent=dict(schema_version=2,intent_id='intent-1',experiment_id=proposal['experiment_id'],
        account=proposal['account'],symbol='BTCUSDT',strategy=proposal['strategy'],
        strategy_lineage_hash=proposal['strategy_lineage_hash'],decision_id=proposal['decision_id'],
        direction=proposal['direction'],target_weight=proposal['target_weight'],
        decision_timestamp=proposal['decision_timestamp'],available_at=proposal['available_at'],
        source_record_hash=proposal['source_record_hash'],decision_authorization_id=token,
        intent_timestamp=NOW.isoformat())
    ledger=root/'execution'/'execution.sqlite'
    def consume(value=intent, at=NOW, protocol_hash=config['protocol_sha256']):
        with sqlite3.connect(ledger) as db:
            approval.initialize_claims(db)
            db.execute('BEGIN IMMEDIATE')
            approval.claim(config['approval_db'],db,value,protocol_hash=protocol_hash,now=at)
            db.commit()
            return db.execute('SELECT COUNT(*) FROM authorization_claims').fetchone()[0]
    forged=dict(intent,intent_id='copied-token',target_weight=.2)
    mismatch=as_uid(30000,30000,lambda:consume(forged))
    assert not mismatch['ok'] and 'approval_mismatch' in mismatch['error']
    changed_policy=as_uid(30000,30000,lambda:consume(protocol_hash='b'*64))
    assert not changed_policy['ok'] and 'approval_evidence_invalid' in changed_policy['error']
    expired=as_uid(30000,30000,lambda:consume(at=NOW+dt.timedelta(minutes=31)))
    assert not expired['ok'] and 'approval_expired_or_future' in expired['error']
    def interrupted_claim():
        with sqlite3.connect(ledger) as db:
            approval.initialize_claims(db)
            db.execute('BEGIN IMMEDIATE')
            approval.claim(config['approval_db'],db,intent,protocol_hash=config['protocol_sha256'],now=NOW)
            db.rollback()
            return db.execute('SELECT COUNT(*) FROM authorization_claims').fetchone()[0]
    assert as_uid(30000,30000,interrupted_claim)=={'ok':True,'value':0}
    claimed=as_uid(30000,30000,consume)
    assert claimed=={'ok':True,'value':1}
    replay=as_uid(30000,30000,consume)
    assert not replay['ok'] and 'approval_consumed' in replay['error']
    assert not as_uid(30010,30010,lambda:sqlite3.connect(config['approval_db']).execute('CREATE TABLE forged(x)'))['ok']
    assert not as_uid(30010,30010,lambda:sqlite3.connect(ledger).execute('CREATE TABLE forged(x)'))['ok']
    assert not as_uid(30020,30020,lambda:sqlite3.connect(ledger).execute('CREATE TABLE forged(x)'))['ok']
    assert not as_uid(30000,30000,lambda:sqlite3.connect(config['approval_db']).execute('CREATE TABLE forged(x)'))['ok']


def test_issuer_denies_modified_record_and_fake_lineage(setup):
    root,config_path,proposal,record,config=setup
    journal=pathlib.Path(config['journal_path'])
    altered=dict(record,proposal=dict(proposal,target_weight=.2))
    journal.write_text(json.dumps(altered)+'\n')
    assert not as_uid(30020,30020,lambda:issuer.issue(config_path,now=NOW))['ok']
    with sqlite3.connect(config['approval_db']) as db:
        assert 'producer_chain_invalid' in db.execute('SELECT reason_code FROM issuer_events ORDER BY id DESC LIMIT 1').fetchone()[0]
    forged=dict(proposal,strategy_lineage_hash='b'*64)
    forged['decision_id']=auth.digest({k:v for k,v in forged.items() if k!='decision_id'})
    fake_record=dict(proposal=forged,previous_record_hash=None)
    fake_record['record_hash']=auth.digest(fake_record)
    journal.write_text(json.dumps(fake_record)+'\n')
    result=as_uid(30020,30020,lambda:issuer.issue(config_path,now=NOW))
    assert result['ok'] and result['value'][0][1]=='DENY'
    journal.unlink()
    assert not as_uid(30020,30020,lambda:issuer.issue(config_path,now=NOW))['ok']
    with sqlite3.connect(config['approval_db']) as db:
        assert 'FileNotFoundError' in db.execute('SELECT reason_code FROM issuer_events ORDER BY id DESC LIMIT 1').fetchone()[0]
