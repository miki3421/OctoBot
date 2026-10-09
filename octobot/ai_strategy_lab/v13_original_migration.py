"""Inactive copy-only migration/restore preparation; never a runtime writer.

work-card-cae0c451-c40c-41f6-a0fb-9ecdf1d48008.
No issuer approval, operational epoch, grants, network or deployment.
"""
from __future__ import annotations

import argparse
from contextlib import closing
import copy
import hashlib
import math
import os
from pathlib import Path
import re
import sqlite3
import stat

from octobot.ai_strategy_lab import v13_original_portfolio as p
from octobot.ai_strategy_lab import v13_paper_v2 as paper

MARKER = b'v13-original-migration-review-sandbox-v1\n'
SCOPE = 'COPIED_ACCOUNT_REVIEW_ONLY'
FIXTURE = 'SYNTHETIC_ARCHITECTURE_ONLY'
LEGACY_TABLES = {'account_version', 'state', 'orders', 'equity_history', 'marks',
                 'funding_events', 'market_events', 'intents'}
ACCOUNT = 'v13-paper-v2'


def _safe(root, path, *, directory=False):
    root, path = Path(root).absolute(), Path(path).absolute()
    if '..' in root.parts or '..' in path.parts:
        raise p.Rejected('parent_path_forbidden')
    if 'octobot-local' in root.parts or 'octobot-local' in path.parts:
        raise p.Rejected('operational_path_forbidden')
    if path != root and root not in path.parents:
        raise p.Rejected('outside_review_sandbox')
    for item in (path, *path.parents):
        info = item.lstat()
        if stat.S_ISLNK(info.st_mode):
            raise p.Rejected('symlink_forbidden')
        if item == root:
            if not stat.S_ISDIR(info.st_mode) or info.st_mode & 0o077:
                raise p.Rejected('private_review_sandbox_required')
            break
    info = path.lstat()
    if directory:
        if not stat.S_ISDIR(info.st_mode):
            raise p.Rejected('not_directory')
    elif not stat.S_ISREG(info.st_mode) or info.st_nlink != 1:
        raise p.Rejected('unsafe_review_file')
    marker = root/'sandbox.marker'
    if not stat.S_ISREG(marker.lstat().st_mode) or marker.lstat().st_nlink != 1 or marker.read_bytes() != MARKER:
        raise p.Rejected('review_marker_required')
    return path


def _hash(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def _db(root, path):
    path = _safe(root, path)
    # Only already sealed offline copies: immutable must never ignore live WAL.
    for suffix in ('-wal', '-journal'):
        sidecar = Path(str(path)+suffix)
        if sidecar.exists() and sidecar.stat().st_size:
            raise p.Rejected('offline_checkpoint_required')
    db = sqlite3.connect(path.as_uri()+'?mode=ro&immutable=1', uri=True)
    db.row_factory = sqlite3.Row
    db.execute('PRAGMA query_only=ON')
    if [tuple(row) for row in db.execute('PRAGMA integrity_check')] != [('ok',)]:
        db.close()
        raise p.Rejected('sqlite_integrity_failure')
    return db


def _tables(db):
    return {row[0] for row in db.execute("SELECT name FROM sqlite_master WHERE type='table'")}


def _table_digest(db, name):
    if not re.fullmatch('[a-z_]+', name):
        raise p.Rejected('unexpected_table_name')
    rows = sorted((p.canonical_bytes(list(row)).decode() for row in db.execute('SELECT * FROM '+name)))
    ddl = db.execute('SELECT sql FROM sqlite_master WHERE name=?', (name,)).fetchone()[0]
    return {'rows': len(rows), 'sha256': p.digest({'ddl': ddl, 'rows': rows})}


def _number(value, *, positive=False):
    if type(value) not in (float, int) or not math.isfinite(value) or (positive and value <= 0):
        raise p.Rejected('invalid_economic_number')
    return value


def _same(left, right):
    # Existing float ledger arithmetic, bounded by its existing 8-ULP rule.
    if abs(_number(left)-_number(right)) > 8*math.ulp(max(1., abs(left), abs(right))):
        raise p.Rejected('ledger_state_mismatch')


def inspect_legacy(root, source, *, checkpoint_at, universe):
    checked = p.timestamp(checkpoint_at)
    with closing(_db(root, source)) as db:
        tables = _tables(db)
        if tables not in (LEGACY_TABLES, LEGACY_TABLES | {'risk_events'}):
            raise p.Rejected('not_unmigrated_v13_v2')
        if [tuple(row) for row in db.execute('SELECT mode FROM account_version')] != [(paper.MODE,)]:
            raise p.Rejected('wrong_account_mode')
        states = list(db.execute('SELECT id,payload FROM state'))
        if len(states) != 1 or states[0]['id'] != 1:
            raise p.Rejected('invalid_state_rows')
        state = p.read_json(states[0]['payload'])
        if state['mode'] != paper.MODE or state.get('pending') is not None:
            raise p.Rejected('pending_or_wrong_mode_requires_reconciliation')
        if set(state['positions']) - set(universe):
            raise p.Rejected('unknown_position_symbol')
        if state['order_count'] != db.execute('SELECT count(*) FROM orders').fetchone()[0]:
            raise p.Rejected('order_count_mismatch')
        if type(state['order_count']) is not int or state['order_count'] <= 0:
            raise p.Rejected('existing_funded_account_required')
        if p.timestamp(state['activation_at']) > checked:
            raise p.Rejected('checkpoint_before_account')
        if state.get('last_success_at') and p.timestamp(state['last_success_at']) > checked:
            raise p.Rejected('future_account_cursor')
        replay = {symbol: paper.new_position() for symbol in state['positions']}
        latest_fill = None
        for row in db.execute('SELECT * FROM orders ORDER BY id'):
            if row['symbol'] not in replay or row['status'] != 'filled':
                raise p.Rejected('unknown_or_unsettled_order')
            when = p.timestamp(row['recorded_at'])
            if when > checked or when < p.timestamp(state['activation_at']):
                raise p.Rejected('invalid_order_time')
            latest_fill = max(latest_fill or when, when)
            pos = replay[row['symbol']]
            old_realized = pos['realized_pnl']
            paper.apply_fill(pos, _number(row['quantity']), _number(row['price'], positive=True), _number(row['fee']))
            _same(pos['realized_pnl']-old_realized, row['realized_pnl'])
        cursors = {}
        for symbol, pos in state['positions'].items():
            if 'position_id' in pos or 'generation' in pos:
                raise p.Rejected('already_identified_position')
            for key in ('quantity', 'entry_price', 'realized_pnl', 'fees'):
                _same(pos[key], replay[symbol][key])
            _number(pos['current_price'], positive=True)
            at = p.timestamp(pos['last_mark_at'])
            if at > checked:
                raise p.Rejected('future_mark')
            mark = db.execute('SELECT price FROM marks WHERE bar=? AND symbol=?', (pos['last_mark_at'], symbol)).fetchone()
            if mark is None or mark[0] != pos['current_price']:
                raise p.Rejected('mark_cursor_mismatch')
            funding = list(db.execute('SELECT * FROM funding_events WHERE symbol=? ORDER BY timestamp_ms', (symbol,)))
            for row in funding:
                if row['timestamp_ms'] > int(at.timestamp()*1000):
                    raise p.Rejected('funding_ahead_of_mark')
                _same(row['amount'], -row['quantity']*row['reference_mark']*row['rate'])
            _same(pos['funding'], math.fsum(row['amount'] for row in funding))
            cursors[symbol] = {'last_observed_mark_at': pos['last_mark_at'],
                'last_observed_mark': pos['current_price'],
                'last_ledger_settlement_ms': funding[-1]['timestamp_ms'] if funding else None,
                'coverage_after_mark': 'UNKNOWN' if pos['quantity'] else 'NOT_HELD',
                'unreconciled_interval_end': checkpoint_at if pos['quantity'] else None,
                'gap_exceeds_existing_20h_guard': bool(pos['quantity'] and (checked-at).total_seconds() > 20*3600)}
        if db.execute('SELECT count(*) FROM funding_events WHERE symbol NOT IN ('+
                ','.join('?' for _ in replay)+')', tuple(replay)).fetchone()[0]:
            raise p.Rejected('funding_unknown_symbol')
        market = db.execute('SELECT observed_at FROM market_events WHERE record_hash=?', (state['last_market_hash'],)).fetchone()
        if market is None or market[0] != state['last_market_at']:
            raise p.Rejected('market_cursor_mismatch')
        totals = paper.totals(state)
        equity = db.execute('SELECT equity,pnl FROM equity_history WHERE bar=?', (state['last_market_at'],)).fetchone()
        if equity is None:
            raise p.Rejected('equity_checkpoint_missing')
        _same(totals['equity'], equity['equity']); _same(totals['pnl'], equity['pnl'])
        return state, {'history': {name: _table_digest(db, name) for name in sorted(tables)},
            'totals_at_last_observed_marks': totals, 'funding_cursors': cursors,
            'latest_historical_fill_at': latest_fill.isoformat(),
            'legacy_authorization_history': 'NOT_PRESENT_NOT_RECONSTRUCTED',
            'funding_method': paper.FUNDING_NOTE,
            'funding_method_human_approval': 'PENDING',
            'risk_counters': {'status': 'LEGACY_HISTORY_PRESERVED_NEW_POLICY_UNCONFIGURED',
                'historical_peak_equity': db.execute('SELECT max(equity) FROM equity_history').fetchone()[0],
                'checkpoint_day_equity_rows': db.execute('SELECT count(*) FROM equity_history WHERE substr(bar,1,10)=?',
                    (checked.date().isoformat(),)).fetchone()[0],
                'new_policy_day_opening': None, 'new_policy_batch_frequency': None,
                'new_policy_cooldown_origin': 'HUMAN_DECISION_REQUIRED_NOT_RESET'},
            'checkpoint_is_new_observation': False}


def _new_dir(root, name):
    _safe(root, root, directory=True)
    if not re.fullmatch('[a-zA-Z0-9_-]{1,100}', name):
        raise p.Rejected('invalid_bundle_name')
    destination = Path(root)/name
    destination.mkdir(mode=0o700)  # exclusive; never overwrite a prior attempt
    return destination


def _write(path, payload):
    with open(path, 'xb') as stream:
        stream.write(payload); stream.flush(); os.fsync(stream.fileno())
    path.chmod(0o600)


def _backup(root, source, target):
    with closing(_db(root, source)) as db:
        _write(target, b'')
        with closing(sqlite3.connect(target)) as dest:
            db.backup(dest)
            dest.execute('PRAGMA journal_mode=DELETE')
            dest.execute('PRAGMA synchronous=FULL')
            dest.commit()


def _publish(destination, manifest):
    # Manifest last: interrupted directories remain evidence, not committed bundles.
    manifest = p.seal_receipt(manifest)
    _write(destination/'manifest.json', p.canonical_bytes(manifest))
    fd = os.open(destination, os.O_RDONLY | os.O_DIRECTORY)
    try:
        os.fsync(fd)
    finally:
        os.close(fd)
    return {'manifest_sha256': _hash(destination/'manifest.json'),
            'manifest_receipt_hash': manifest['receipt_hash'], 'readiness': 'BLOCKED',
            'runtime_admission': False, 'operational_apply': False}


def prepare(root, source, name, *, checkpoint_at, nonce, repo_root):
    """Preserve legacy state; proposed identities live only in new review tables."""
    source = _safe(root, source)
    source_hash = _hash(source)
    contract, _ = p.load_contract(repo_root)
    p.require_hash(nonce)
    state, reconciliation = inspect_legacy(root, source, checkpoint_at=checkpoint_at, universe=contract['universe'])
    destination = _new_dir(root, name)
    _backup(root, source, destination/'original.sqlite')
    _backup(root, source, destination/'execution-copy.sqlite')
    epoch = p.digest({'kind': 'UNAPPROVED_MIGRATION_EPOCH_CANDIDATE', 'account': ACCOUNT,
        'source_snapshot_sha256': source_hash, 'checkpoint_at': checkpoint_at, 'nonce': nonce})
    current = copy.deepcopy(state)
    identities = {}
    for symbol, pos in current['positions'].items():
        if pos['quantity']:
            identity = {'position_id': p.digest({'account': ACCOUNT, 'epoch_candidate': epoch, 'symbol': symbol}),
                'generation': 1, 'identity_origin': 'MIGRATION_CANDIDATE_AT_CHECKPOINT',
                'historical_identity_known': False, 'assigned_at': checkpoint_at}
            identities[symbol] = identity
            pos.update(position_id=identity['position_id'], generation=identity['generation'])
    receipt = p.seal_receipt({'version': 'v13-original-migration-review-v1', 'scope': SCOPE,
        'account': ACCOUNT, 'epoch_candidate': epoch, 'checkpoint_at': checkpoint_at,
        'source_snapshot_sha256': source_hash, 'original_state_sha256': p.digest(state),
        'candidate_state_sha256': p.digest(current), 'identities': identities,
        'reconciliation': reconciliation, 'runtime_admission': False,
        'operational_approval': False, 'new_fills': 0, 'new_equity_points': 0,
        'required_before_apply': ['human_binding_epoch_policy_topology', 'funding_gap_reconciliation',
            'real_market_provenance', 'independent_review', 'exclusive_writer_cutover',
            'external_restore_witness_and_coherent_authorization_stores'],
        'ownership_plan': {'approvals_writer': 'issuer_only', 'execution_claims_ledger_writer': 'executor_only',
            'strategy_trusted_write': False, 'legacy_runner_must_be_disabled': True,
            'topology_installed': False, 'filesystem_table_isolation': False},
        'authorization_stores': {'approvals': 'UNINITIALIZED', 'P0_04_audit': 'UNINITIALIZED',
            'claims': 'UNINITIALIZED'}, 'policy_values': {k: None for k in
                ('daily_loss', 'drawdown', 'order_frequency', 'cooldown')},
        'min_quantity': 'UNKNOWN', 'min_notional': 'UNKNOWN'})
    with closing(sqlite3.connect(destination/'execution-copy.sqlite')) as db:
        db.execute('PRAGMA synchronous=FULL')
        db.execute('BEGIN IMMEDIATE')
        db.execute('CREATE TABLE migration_review (receipt_hash TEXT PRIMARY KEY, receipt TEXT NOT NULL, candidate_state TEXT NOT NULL)')
        db.execute('INSERT INTO migration_review VALUES (?,?,?)',
            (receipt['receipt_hash'], p.canonical_bytes(receipt).decode(), p.canonical_bytes(current).decode()))
        db.commit()
    _write(destination/'migration-receipt.json', p.canonical_bytes(receipt))
    if _hash(source) != source_hash:
        raise p.Rejected('source_changed_during_preparation')
    return _publish(destination, {'version': 'v13-inactive-review-bundle-v1', 'scope': SCOPE,
        'account': ACCOUNT, 'epoch_candidate': epoch,
        'files': {n: _hash(destination/n) for n in ('original.sqlite', 'execution-copy.sqlite', 'migration-receipt.json')},
        'runtime_admission': False, 'operational_apply': False})


def verify(root, bundle, *, expected_manifest_sha256):
    """Pin MUST come from outside the restored bundle; it is not human approval."""
    bundle = _safe(root, bundle, directory=True)
    manifest_path = _safe(root, bundle/'manifest.json')
    if _hash(manifest_path) != p.require_hash(expected_manifest_sha256):
        raise p.Rejected('external_witness_mismatch')
    manifest = p.read_json(manifest_path.read_bytes()); p.check_receipt(manifest, manifest['receipt_hash'])
    if manifest.get('runtime_admission') is not False or manifest.get('operational_apply') is not False:
        raise p.Rejected('inactive_bundle_required')
    required = ({'original.sqlite', 'execution-copy.sqlite', 'migration-receipt.json'} if manifest['scope'] == SCOPE
                else {'approvals.sqlite', 'execution.sqlite', 'P004-audit.sqlite'} if manifest['scope'] == FIXTURE else set())
    if not required or set(manifest['files']) != required:
        raise p.Rejected('incomplete_restore_bundle')
    for name in required:
        path = _safe(root, bundle/name)
        if _hash(path) != p.require_hash(manifest['files'][name]):
            raise p.Rejected('restore_file_hash_mismatch')
        if name.endswith('.sqlite'):
            with closing(_db(root, path)):
                pass
    if manifest['scope'] == SCOPE:
        receipt = p.read_json((bundle/'migration-receipt.json').read_bytes()); p.check_receipt(receipt, receipt['receipt_hash'])
        with closing(_db(root, bundle/'original.sqlite')) as original, closing(_db(root, bundle/'execution-copy.sqlite')) as candidate:
            if _tables(candidate) != _tables(original) | {'migration_review'}:
                raise p.Rejected('unexpected_migration_tables')
            for name in _tables(original):
                if _table_digest(original, name) != _table_digest(candidate, name):
                    raise p.Rejected('historical_ledger_changed')
            rows = list(candidate.execute('SELECT * FROM migration_review'))
            if len(rows) != 1 or p.read_json(rows[0]['receipt']) != receipt or rows[0]['receipt_hash'] != receipt['receipt_hash']:
                raise p.Rejected('migration_receipt_mismatch')
            current = p.read_json(rows[0]['candidate_state'])
            if p.digest(current) != receipt['candidate_state_sha256'] or receipt['epoch_candidate'] != manifest['epoch_candidate']:
                raise p.Rejected('migration_identity_mismatch')
    else:
        _fixture_coherence(root, bundle)
        with closing(_db(root, bundle/'execution.sqlite')) as db:
            if dict(db.execute('SELECT * FROM execution_namespace'))['account_epoch'] != manifest['epoch_candidate']:
                raise p.Rejected('restore_manifest_epoch_mismatch')
    return manifest


def _fixture_coherence(root, directory):
    with closing(_db(root, directory/'execution.sqlite')) as execution, closing(_db(root, directory/'P004-audit.sqlite')) as audit, closing(_db(root, directory/'approvals.sqlite')) as approvals:
        namespace = dict(execution.execute('SELECT * FROM execution_namespace'))
        if namespace != dict(audit.execute('SELECT * FROM audit_namespace')) or namespace['scope'] != FIXTURE:
            raise p.Rejected('restore_epoch_or_namespace_mismatch')
        if dict(approvals.execute('SELECT * FROM store_metadata')).get('fixture_label') != FIXTURE:
            raise p.Rejected('not_fixture_approvals')
        if execution.execute("SELECT count(*) FROM portfolio_claims WHERE status='RESERVED'").fetchone()[0] or execution.execute("SELECT count(*) FROM portfolio_attempts WHERE status='STARTED'").fetchone()[0]:
            raise p.Rejected('pending_claim_requires_reconciliation')
        for claim in execution.execute('SELECT * FROM portfolio_claims'):
            approved = approvals.execute('SELECT body FROM approvals WHERE approval_id=?', (claim['approval_id'],)).fetchone()
            if approved is None:
                raise p.Rejected('restore_approval_missing')
            body = p.read_json(approved[0]); p.check_receipt(body, body['receipt_hash'])
            proposal = body['proposal']
            for key in ('account', 'account_epoch', 'proposal_id'):
                if proposal[key] != claim[key]:
                    raise p.Rejected('restore_approval_binding_mismatch')
            if (claim['account'] != namespace['account'] or claim['account_epoch'] != namespace['account_epoch']
                    or claim['binding_ref'] != namespace['binding_ref']
                    or proposal['execution_binding_ref'] != claim['binding_ref']
                    or p.digest(proposal) != body['proposal_hash']):
                raise p.Rejected('restore_approval_binding_mismatch')
            attempt = execution.execute('SELECT status FROM portfolio_attempts WHERE proposal_id=? AND intent_id=?',
                (claim['proposal_id'], claim['intent_id'])).fetchone()
            if attempt is None or attempt[0] != claim['status']:
                raise p.Rejected('restore_attempt_mismatch')
            batch = execution.execute('SELECT result FROM portfolio_batches WHERE proposal_id=? AND approval_id=? AND intent_id=?',
                (claim['proposal_id'], claim['approval_id'], claim['intent_id'])).fetchone()
            if claim['status'] == 'COMMITTED' and batch is None:
                raise p.Rejected('restore_batch_missing')
            if claim['global_claim_required']:
                row = audit.execute('SELECT payload FROM claims WHERE account=? AND entry_id=?',
                    (claim['account'], claim['proposal_id'])).fetchone()
                if row is None:
                    raise p.Rejected('restore_global_claim_missing')
                payload = p.read_json(row[0])
                if (payload['result'] != 'GLOBAL_CLAIM' or payload['entry_id'] != claim['proposal_id']
                        or payload['identity']['account'] != claim['account']):
                    raise p.Rejected('restore_global_claim_invalid')


def checkpoint_fixture(root, files, name):
    """Only quiescent, sealed synthetic stores; no snapshot of running writers."""
    if set(files) != {'approvals.sqlite', 'execution.sqlite', 'P004-audit.sqlite'}:
        raise p.Rejected('incomplete_restore_bundle')
    before = {n: _hash(_safe(root, path)) for n, path in files.items()}
    destination = _new_dir(root, name)
    for n, path in files.items():
        _backup(root, path, destination/n)
    if before != {n: _hash(path) for n, path in files.items()}:
        raise p.Rejected('checkpoint_sources_changed')
    _fixture_coherence(root, destination)
    with closing(_db(root, destination/'execution.sqlite')) as db:
        epoch = dict(db.execute('SELECT * FROM execution_namespace'))['account_epoch']
    return _publish(destination, {'version': 'v13-inactive-fixture-restore-v1', 'scope': FIXTURE,
        'epoch_candidate': epoch, 'files': {n: _hash(destination/n) for n in files},
        'runtime_admission': False, 'operational_apply': False})


def restore_review(root, bundle, name, *, expected_manifest_sha256):
    """New diagnostic folder only, NEVER install or replace runtime files."""
    manifest = verify(root, bundle, expected_manifest_sha256=expected_manifest_sha256)
    destination = _new_dir(root, name)
    for filename in (*manifest['files'], 'manifest.json'):
        _write(destination/filename, (Path(bundle)/filename).read_bytes())
    verify(root, destination, expected_manifest_sha256=expected_manifest_sha256)
    return {'status': 'RESTORED_REVIEW_COPY', 'readiness': 'BLOCKED', 'runtime_admission': False,
        'epoch_candidate': manifest['epoch_candidate'], 'operational_apply': False}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--sandbox-root', required=True)
    sub = parser.add_subparsers(dest='action', required=True)
    prepare_args = sub.add_parser('prepare')
    for name in ('source', 'name', 'checkpoint-at', 'nonce', 'repo-root'):
        prepare_args.add_argument('--'+name, required=True)
    verify_args = sub.add_parser('verify')
    restore_args = sub.add_parser('restore-review')
    for arg in (verify_args, restore_args):
        arg.add_argument('--bundle', required=True); arg.add_argument('--expected-manifest-sha256', required=True)
    restore_args.add_argument('--name', required=True)
    args = vars(parser.parse_args()); root = args.pop('sandbox_root'); action = args.pop('action')
    try:
        if action == 'prepare':
            result = prepare(root, **args)
        elif action == 'verify':
            manifest = verify(root, **args)
            result = {'status': 'VERIFIED_REVIEW_COPY', 'scope': manifest['scope'], 'runtime_admission': False, 'readiness': 'BLOCKED'}
        else:
            result = restore_review(root, **args)
        print(p.canonical_bytes(result).decode())
        return 0
    except (p.Rejected, OSError, sqlite3.Error, KeyError, ValueError) as error:
        print(p.canonical_bytes({'status': 'DENY', 'reason': str(error), 'runtime_admission': False}).decode())
        return 2


if __name__ == '__main__':
    raise SystemExit(main())
