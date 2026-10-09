"""Isolated V13 paper executor candidate. Never import this in a strategy process.

The strategy may submit untrusted JSON. Only this process owns the decision
claim, P0-04 consumer audit and V13 ledger. This module is not a credential or
an in-process sandbox: OS identity and mounts supply the security boundary.
"""
from __future__ import annotations

import argparse
from contextlib import ExitStack, closing
import datetime as dt
import fcntl
import hashlib
import json
import math
import os
import pathlib
import re
import secrets
import sqlite3
import time

from octobot.ai_strategy_lab import paper_authorization as auth
from octobot.ai_strategy_lab import paper_runtime_authorization as wiring
from octobot.ai_strategy_lab import v13_market, v13_paper_v2 as paper
from octobot.ai_strategy_lab import v13_btc_approval, v13_btc_risk_policy, v13_btc_issuer

UTC = dt.timezone.utc
ACCOUNT = 'v13-paper-v2'
INTENT_FIELDS = frozenset({'schema_version', 'intent_id', 'account', 'symbol',
    'direction', 'target_weight', 'decision_id', 'decision_authorization_id',
    'strategy', 'strategy_lineage_hash', 'decision_timestamp', 'intent_timestamp'})
INTENT_V2_FIELDS = INTENT_FIELDS | {'experiment_id','available_at','source_record_hash'}
IDENTIFIER = re.compile(r'[A-Za-z0-9_.:-]{1,160}\Z')
MAX_INTENT_AGE = dt.timedelta(minutes=30)


def _instant(value):
    value = auth.timestamp(value)
    return value


def validate_intent(raw, now):
    if not isinstance(raw, dict) or raw.get('schema_version') not in (1,2) or set(raw) != (INTENT_FIELDS if raw['schema_version']==1 else INTENT_V2_FIELDS):
        raise ValueError('intent_schema_invalid')
    for key in ('intent_id', 'decision_id', 'decision_authorization_id', 'account', 'symbol', 'direction', 'strategy'):
        if not isinstance(raw[key], str) or not IDENTIFIER.fullmatch(raw[key]):
            raise ValueError('intent_identity_invalid')
    if raw['account'] != ACCOUNT or raw['symbol'] != 'BTCUSDT' or raw['direction'] not in ('LONG', 'SHORT', 'FLAT'):
        raise ValueError('intent_scope_invalid')
    if not auth.sha(raw['strategy_lineage_hash']):
        raise ValueError('intent_lineage_invalid')
    if raw['schema_version'] == 2:
        if (raw['experiment_id'] != 'v13-btc-paper-new-v1'
            or not auth.sha(raw['source_record_hash'])):
            raise ValueError('intent_experiment_invalid')
    weight = raw['target_weight']
    if type(weight) not in (int, float) or not math.isfinite(weight) or not -paper.MAX_ASSET <= weight <= paper.MAX_ASSET:
        raise ValueError('intent_target_invalid')
    if (weight > 0) != (raw['direction'] == 'LONG') or (weight < 0) != (raw['direction'] == 'SHORT'):
        if not (weight == 0 and raw['direction'] == 'FLAT'):
            raise ValueError('intent_direction_mismatch')
    decision_at, intent_at = _instant(raw['decision_timestamp']), _instant(raw['intent_timestamp'])
    if decision_at > intent_at or intent_at > now or now-intent_at > MAX_INTENT_AGE:
        raise ValueError('intent_stale_or_future')
    if raw['schema_version']==2 and not (_instant(raw['available_at']) <= decision_at <= intent_at):
        raise ValueError('intent_availability_invalid')
    return dict(raw)


class DecisionStore:
    """Trusted, persisted P0-01 approval table. Strategy has no write mount.

    The issuer is deliberately absent from the strategy CLI. A real trusted
    issuer/guard integration remains a deployment prerequisite; tests seed
    only isolated fixture approvals.
    """
    def __init__(self, path):
        self.path = pathlib.Path(path)

    def initialize(self):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with sqlite3.connect(self.path) as db:
            db.execute('PRAGMA synchronous=FULL')
            db.executescript('''CREATE TABLE IF NOT EXISTS approvals (
                decision_id TEXT PRIMARY KEY, token TEXT NOT NULL UNIQUE,
                account TEXT NOT NULL, strategy TEXT NOT NULL, lineage_hash TEXT NOT NULL,
                symbol TEXT NOT NULL, direction TEXT NOT NULL, target_weight REAL NOT NULL,
                decision_at TEXT NOT NULL, source_hash TEXT NOT NULL, approved INTEGER NOT NULL CHECK(approved=1));
                CREATE TABLE IF NOT EXISTS claims (
                token TEXT PRIMARY KEY REFERENCES approvals(token), claimed_at TEXT NOT NULL,
                intent_id TEXT NOT NULL UNIQUE);
            ''')

    def issue_fixture_only(self, row):
        """Explicit test seeding, never called by the deployed executor."""
        if os.environ.get('V13_ISOLATED_FIXTURE_ISSUER') != '1':
            raise ValueError('fixture_issuer_disabled')
        keys = ('decision_id','token','account','strategy','lineage_hash','symbol',
                'direction','target_weight','decision_at','source_hash')
        if (set(row) != set(keys) or not auth.sha(row['source_hash'])
            or row['decision_id'] != row['source_hash']):
            raise ValueError('approval_schema_invalid')
        with sqlite3.connect(self.path) as db:
            db.execute('INSERT INTO approvals VALUES (?,?,?,?,?,?,?,?,?,?,1)',
                tuple(row[k] for k in keys))

    def exact(self, intent, *, consume=False, now=None):
        now = now or dt.datetime.now(UTC)
        uri = self.path.resolve().as_uri() + '?mode=rw'
        with sqlite3.connect(uri, uri=True, timeout=0) as db:
            db.execute('PRAGMA synchronous=FULL')
            db.execute('BEGIN IMMEDIATE' if consume else 'BEGIN')
            row = db.execute('SELECT decision_id,token,account,strategy,lineage_hash,symbol,direction,target_weight,decision_at,source_hash FROM approvals WHERE token=?',
                (intent['decision_authorization_id'],)).fetchone()
            if row is None:
                raise ValueError('decision_authorization_missing')
            if row[0] != row[9] or not auth.sha(row[9]):
                raise ValueError('decision_source_identity_mismatch')
            keys = ('decision_id','decision_authorization_id','account','strategy','strategy_lineage_hash','symbol','direction','target_weight','decision_timestamp')
            for expected, observed in zip(keys, row[:9]):
                if intent[expected] != observed:
                    raise ValueError('decision_authorization_mismatch')
            if _instant(row[8]) > now or now-_instant(row[8]) > MAX_INTENT_AGE:
                raise ValueError('decision_authorization_stale')
            if db.execute('SELECT 1 FROM claims WHERE token=? OR intent_id=?',
                    (row[1], intent['intent_id'])).fetchone():
                raise ValueError('decision_authorization_consumed')
            if consume:
                db.execute('INSERT INTO claims VALUES (?,?,?)',
                    (row[1], now.isoformat(), intent['intent_id']))
            return row[9]


def _policy_limit(policy, name, key):
    item = policy.get(name)
    if (not isinstance(item, dict) or type(item.get(key)) not in (int,float)
        or not math.isfinite(item[key]) or item[key] < 0):
        raise auth.Denied('risk_policy_incomplete')
    return item[key]


def enforce_policy(policy, ledger, state, now):
    """Durable equity/order history is the authority, not an intent field."""
    metrics = paper.totals(state, require_positive=False)
    equity = metrics['equity']
    day = now.date().isoformat()
    start = ledger.execute('SELECT equity FROM equity_history WHERE bar >= ? ORDER BY bar LIMIT 1', (day,)).fetchone()
    opening = start[0] if start else state['initial_equity']
    peak = ledger.execute('SELECT MAX(equity) FROM equity_history').fetchone()[0]
    peak = max(peak or opening, opening)
    if equity < opening * (1-_policy_limit(policy,'daily_loss','limit_fraction')):
        raise auth.Denied('daily_loss_limit')
    if equity < peak * (1-_policy_limit(policy,'drawdown','limit_fraction')):
        raise auth.Denied('drawdown_limit')
    frequency = policy.get('order_frequency')
    if not isinstance(frequency, dict):
        raise auth.Denied('risk_policy_incomplete')
    max_orders = _policy_limit(policy,'order_frequency','max_orders')
    window = _policy_limit(policy,'order_frequency','window_seconds')
    if window <= 0 or max_orders < 1:
        raise auth.Denied('risk_policy_incomplete')
    since = (now-dt.timedelta(seconds=window)).isoformat()
    count = ledger.execute('SELECT COUNT(*) FROM orders WHERE recorded_at >= ?', (since,)).fetchone()[0]
    if count >= max_orders:
        raise auth.Denied('order_frequency_limit')
    cooldown = _policy_limit(policy,'cooldown','seconds')
    latest = ledger.execute('SELECT MAX(recorded_at) FROM orders').fetchone()[0]
    if latest and now-_instant(latest) < dt.timedelta(seconds=cooldown):
        raise auth.Denied('cooldown_active')


def _read_intent(path):
    fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW)
    try:
        if os.fstat(fd).st_size > 8192:
            raise ValueError('intent_too_large')
        with os.fdopen(fd) as stream:
            return json.load(stream, object_pairs_hook=auth.unique_object,
                parse_constant=lambda value: (_ for _ in ()).throw(ValueError('intent_nonfinite_number')))
    except BaseException:
        try: os.close(fd)
        except OSError: pass
        raise


def _state(db, now):
    row = db.execute('SELECT payload FROM state WHERE id=1').fetchone()
    if row:
        state = json.loads(row[0])
        if state.get('mode') != paper.MODE:
            raise ValueError('wrong_account_mode')
        return state
    return dict(mode=paper.MODE, initial_equity=paper.INITIAL_EQUITY,
        activation_at=(now-dt.timedelta(minutes=30)).isoformat(), positions={},
        order_count=0,last_bar=None,last_market_hash=None,executed_targets=None,pending=None)


def execute(intent_path, *, decision_db=None, approval_db=None, protocol_path=None,
            ledger_path, market_journal, control_root, consumer_audit,
            policy_path, identity_path, lock_path, now=None):
    """One trusted serialized tick. A denial commits no economic ledger row."""
    now = now or dt.datetime.now(UTC)
    raw = _read_intent(intent_path)
    intent = validate_intent(raw, now)
    identity_doc = json.loads(pathlib.Path(identity_path).read_text(), object_pairs_hook=auth.unique_object)
    if set(identity_doc) != set(auth.Identity.__dataclass_fields__):
        raise ValueError('identity_schema_invalid')
    identity = auth.Identity(**identity_doc)
    identity.validate()
    policy = json.loads(pathlib.Path(policy_path).read_text(), object_pairs_hook=auth.unique_object)
    if identity.account != ACCOUNT or identity.strategy != intent['strategy'] or identity.lineage_hash != intent['strategy_lineage_hash'] or identity.risk_policy_hash != auth.digest(policy):
        raise ValueError('trusted_identity_mismatch')
    if policy.get('per_asset_exposure') != paper.MAX_ASSET or policy.get('gross_exposure') != paper.MAX_GROSS:
        raise auth.Denied('risk_policy_exposure_mismatch')
    fixture_mode = approval_db is None and os.environ.get('V13_ISOLATED_FIXTURE_ISSUER') == '1'
    if fixture_mode:
        decisions = DecisionStore(decision_db)
        decisions.exact(intent, now=now)
    else:
        if approval_db is None or protocol_path is None or intent['schema_version'] != 2:
            raise ValueError('trusted_approval_required')
        protocol = v13_btc_issuer._read_json(protocol_path, owner=0)
        if (protocol.get('producer_status') != 'VALIDATED'
            or protocol.get('account') != ACCOUNT
            or protocol.get('lineage_root') != identity.lineage_hash
            or protocol.get('risk_policy_version') != identity.risk_policy
            or protocol.get('experiment_id') != intent['experiment_id']):
            raise ValueError('trusted_protocol_mismatch')
        protocol_hash = auth.digest(protocol)
        v13_btc_risk_policy.validate(policy)
    lock_path = pathlib.Path(lock_path)
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    with lock_path.open('a+') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        with closing(paper.init_db(pathlib.Path(ledger_path))) as db:
            if not fixture_mode:
                v13_btc_approval.initialize_claims(db)
                v13_btc_risk_policy.initialize(db)
                db.execute('''CREATE TABLE IF NOT EXISTS decision_checks (
                    id INTEGER PRIMARY KEY, decision_id TEXT NOT NULL, checked_at TEXT NOT NULL,
                    result TEXT NOT NULL, reason_code TEXT NOT NULL)''')
            if db.execute('PRAGMA integrity_check').fetchone()[0] != 'ok':
                raise ValueError('ledger_integrity_failure')
            state = _state(db, now)
            if state.get('pending'):
                raise ValueError('unresolved_prior_intent')
            if db.execute('SELECT 1 FROM intents WHERE decision_hash=?',(intent['decision_id'],)).fetchone():
                raise ValueError('intent_replay')
            record = v13_market.load_latest_market(market_journal, now)
            if record.get('schema_version') != 2:
                raise ValueError('market_schema_v2_required')
            symbols = {intent['symbol']} | {s for s,p in state['positions'].items() if p['quantity']}
            quotes = v13_market.market_quotes(record, symbols)
            state['pending'] = dict(targets={intent['symbol']: intent['target_weight']},
                noticed_at=intent['intent_timestamp'], decision_hash=intent['decision_id'])
            registry = auth.Registry(control_root, consumer_audit, clock=lambda: now)
            def scope(account, entry_id, **kwargs):
                if account != ACCOUNT or entry_id != intent['decision_id']:
                    raise auth.Denied('entry_identity_invalid')
                def claim():
                    if fixture_mode:
                        enforce_policy(policy, db, state, now)
                        decisions.exact(intent, consume=True, now=now)
                    else:
                        try:
                            v13_btc_risk_policy.check(policy,db,kwargs['marked_state'],now)
                            v13_btc_approval.claim(approval_db,db,intent,protocol_hash=protocol_hash,now=now)
                        except (ValueError,sqlite3.Error) as exc:
                            db.execute('INSERT INTO decision_checks(decision_id,checked_at,result,reason_code) VALUES (?,?,?,?)',
                                       (intent['decision_id'],now.isoformat(),'DENY',str(exc)))
                            raise
                        db.execute('INSERT INTO decision_checks(decision_id,checked_at,result,reason_code) VALUES (?,?,?,?)',
                                   (intent['decision_id'],now.isoformat(),'ALLOW','admissible'))
                    return True
                return registry.entry(identity, intent['intent_id'], policy, claim)
            db.execute('BEGIN IMMEDIATE')
            try:
              with ExitStack() as stack:
                candidate, fills, funding, marks = paper.process_market(state, record, quotes, now,
                    authorization_stack=stack, authorization_scope=scope)
                # A veto is final for this exact intent. The durable claim, if
                # made, is never retried; a later safe reduction may proceed.
                if not fills:
                    candidate['pending'] = None
                for fill in fills:
                    symbol = fill['symbol']
                    old_position = state['positions'].get(symbol,{})
                    new_position = candidate['positions'][symbol]
                    if old_position.get('quantity',0) == 0 and new_position['quantity'] != 0:
                        new_position['position_generation'] = old_position.get('position_generation',0)+1
                        new_position['position_id'] = secrets.token_hex(16)
                    elif old_position.get('quantity',0)*new_position['quantity'] < 0:
                        new_position['position_generation'] = old_position.get('position_generation',0)+1
                        new_position['position_id'] = secrets.token_hex(16)
                with db:
                    for fill in fills:
                        fields = tuple(fill)
                        db.execute(f"INSERT INTO orders({','.join(fields)}) VALUES ({','.join('?' for _ in fields)})", tuple(fill.values()))
                    db.executemany('INSERT INTO funding_events VALUES (?,?,?,?,?,?)', funding)
                    db.executemany('INSERT INTO marks VALUES (?,?,?)', marks)
                    db.execute('INSERT INTO market_events VALUES (?,?,?,?)',
                        (record['record_hash'],record['observed_at_end'],now.isoformat(),json.dumps(record,sort_keys=True)))
                    db.execute('INSERT INTO risk_events VALUES (?,?)',
                        (record['record_hash'],json.dumps(candidate['risk'],sort_keys=True,allow_nan=False)))
                    db.execute('INSERT INTO intents VALUES (?,?,?,?,?)',
                        (intent['decision_id'],intent['intent_timestamp'],now.date().isoformat(),
                         json.dumps(state['pending']['targets'],sort_keys=True),'executed' if fills else 'denied'))
                    if fills and candidate['risk'].get('action') == 'new_risk' and not fixture_mode:
                        v13_btc_risk_policy.record_new_risk(db,intent['decision_id'],now)
                    metrics = paper.totals(candidate, require_positive=False)
                    db.execute('INSERT INTO equity_history VALUES (?,?,?)',
                        (record['observed_at_end'],metrics['equity'],metrics['pnl']))
                    db.execute('INSERT OR REPLACE INTO state VALUES (1,?)',(json.dumps(candidate,sort_keys=True),))
            except BaseException:
                db.rollback()
                raise
            return dict(accepted=bool(fills),reason=candidate['risk'].get('reason'),
                orders=len(fills),position=candidate['positions'].get(intent['symbol'],{}).get('quantity',0),
                equity=paper.totals(candidate,require_positive=False)['equity'])


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ('ledger','market-journal','control-root','consumer-audit',
                 'policy','identity','lock'):
        parser.add_argument('--'+name,required=True,type=pathlib.Path)
    for name in ('decision-db','approval-db','protocol'):
        parser.add_argument('--'+name,type=pathlib.Path)
    parser.add_argument('--intent',type=pathlib.Path)
    parser.add_argument('--inbox',type=pathlib.Path)
    parser.add_argument('--poll',type=float,default=10)
    args = parser.parse_args()
    if (args.intent is None) == (args.inbox is None) or args.poll <= 0:
        parser.error('select exactly one of --intent and --inbox; poll must be positive')
    def attempt(path):
        try:
            result = execute(path, decision_db=args.decision_db, ledger_path=args.ledger,
                approval_db=args.approval_db, protocol_path=args.protocol,
                market_journal=args.market_journal,control_root=args.control_root,
                consumer_audit=args.consumer_audit,policy_path=args.policy,
                identity_path=args.identity,lock_path=args.lock)
        except (ValueError, OSError, sqlite3.Error) as exc:
            result = dict(accepted=False,reason=str(exc),orders=0)
        print(json.dumps(dict(result,intent_file=path.name),sort_keys=True),flush=True)
        return result
    if args.intent:
        return 0 if attempt(args.intent)['accepted'] else 1
    seen = set()
    while True:
        for path in sorted(args.inbox.glob('*.json')):
            if path.name not in seen:
                attempt(path)
                seen.add(path.name)
        time.sleep(args.poll)


if __name__ == '__main__':
    raise SystemExit(main())
