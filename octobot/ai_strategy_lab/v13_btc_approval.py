"""Read-only issuer evidence and executor-owned, transactional claims."""
from __future__ import annotations

import datetime as dt
import os
import pathlib
import sqlite3

from octobot.ai_strategy_lab import paper_authorization as auth
from octobot.ai_strategy_lab.v13_btc_issuer import POLICY_VERSION


def initialize_claims(execution_db):
    execution_db.execute('''CREATE TABLE IF NOT EXISTS authorization_claims (
        approval_id TEXT PRIMARY KEY, decision_id TEXT NOT NULL UNIQUE,
        intent_id TEXT NOT NULL UNIQUE, claimed_at TEXT NOT NULL)''')


def claim(approval_db, execution_db, intent, *, protocol_hash, now):
    """Claim within the caller's economic transaction; never write approval DB."""
    if intent.get('schema_version') != 2:
        raise ValueError('intent_v2_required')
    approval_db = pathlib.Path(approval_db)
    if approval_db.is_symlink() or not approval_db.is_file():
        raise ValueError('approval_store_missing')
    uri = 'file:' + str(approval_db.resolve()) + '?mode=ro'
    with sqlite3.connect(uri,uri=True,timeout=0) as source:
        source.execute('PRAGMA query_only=ON')
        if source.execute('PRAGMA integrity_check').fetchone()[0] != 'ok':
            raise ValueError('approval_integrity_failure')
        row = source.execute('''SELECT decision_id,approval_id,experiment_id,account,symbol,
            strategy,lineage_hash,direction,target_weight,decision_at,available_at,
            source_hash,producer_record_hash,issuer_policy_version,protocol_hash,
            approved_at,expires_at,result,reason_code FROM approvals WHERE approval_id=?''',
            (intent['decision_authorization_id'],)).fetchone()
    if row is None:
        raise ValueError('approval_missing')
    keys = ('decision_id','decision_authorization_id','experiment_id','account','symbol',
            'strategy','strategy_lineage_hash','direction','target_weight','decision_timestamp',
            'available_at','source_record_hash')
    for key,value in zip(keys,row[:12]):
        if key == 'symbol' and value == 'BTC/USDT:USDT' and intent.get(key) == 'BTCUSDT':
            continue
        if intent.get(key) != value:
            raise ValueError('approval_mismatch')
    if (row[13] != POLICY_VERSION or row[14] != protocol_hash
        or row[17] != 'APPROVE' or row[18] != 'admissible'
        or not auth.sha(row[12])):
        raise ValueError('approval_evidence_invalid')
    decision_at, available, approved, expires = map(auth.timestamp,(row[9],row[10],row[15],row[16]))
    if not (available <= decision_at <= approved <= now < expires):
        raise ValueError('approval_expired_or_future')
    if execution_db.execute('SELECT 1 FROM authorization_claims WHERE approval_id=? OR decision_id=? OR intent_id=?',
                            (row[1],row[0],intent['intent_id'])).fetchone():
        raise ValueError('approval_consumed')
    execution_db.execute('INSERT INTO authorization_claims VALUES (?,?,?,?)',
                         (row[1],row[0],intent['intent_id'],now.isoformat()))
    return row[11]
