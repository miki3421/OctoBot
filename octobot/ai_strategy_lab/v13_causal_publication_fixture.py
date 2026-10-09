"""Inactive causal publication / input verification on synthetic fixtures only.

work-card-2a3f3bb2-0af0-4957-88d8-26d739083829.
No capture client, strategy evaluation, issuer bridge or runtime configuration.
Post-commit acknowledgements are separate from the objects they attest.
"""
from __future__ import annotations

from contextlib import closing
import datetime as dt
import fcntl
import hashlib
import math
import os
from pathlib import Path
import sqlite3
import stat

from octobot.ai_strategy_lab import v13_original_portfolio as p

SCOPE = 'SYNTHETIC_ARCHITECTURE_ONLY'
VERSION = 'v13-original-causal-publication-fixture-v1'
MARKER = (VERSION+'\n').encode()
ROLES = ('strategy', 'publisher', 'verifier', 'witness')


def _hash(raw):
    return hashlib.sha256(raw).hexdigest()


def _fsync_dir(path):
    fd = os.open(path, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    try:
        os.fsync(fd)
    finally:
        os.close(fd)


def _path(root, path, *, exists=True, owner=None, directory=False):
    root, path = Path(root).absolute(), Path(path).absolute()
    if '..' in root.parts or '..' in path.parts or 'octobot-local' in path.parts:
        raise p.Rejected('operational_or_traversal_path_forbidden')
    if path != root and root not in path.parents:
        raise p.Rejected('outside_fixture_root')
    for item in (path, *path.parents):
        if item == path and not exists and not path.exists() and not path.is_symlink():
            continue
        info = item.lstat()
        if stat.S_ISLNK(info.st_mode):
            raise p.Rejected('symlink_forbidden')
        if item != path and not stat.S_ISDIR(info.st_mode):
            raise p.Rejected('unsafe_parent')
    if exists:
        info = path.stat()
        if (not (stat.S_ISDIR(info.st_mode) if directory else stat.S_ISREG(info.st_mode))
                or (not directory and info.st_nlink != 1)
                or (owner is not None and info.st_uid != owner) or info.st_mode & 0o022):
            raise p.Rejected('unsafe_fixture_object')
    return path


def _write(path, raw):
    """No overwrite; restart can only complete byte-identical staging."""
    if path.exists() or path.is_symlink():
        if path.is_symlink() or not path.is_file() or path.stat().st_nlink != 1 or path.read_bytes() != raw:
            raise p.Rejected('artifact_conflict')
        with path.open('rb') as stream:
            os.fchmod(stream.fileno(), 0o444)
            os.fsync(stream.fileno())
        return
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
    with os.fdopen(fd, 'wb') as stream:
        stream.write(raw); stream.flush(); os.fchmod(stream.fileno(), 0o444); os.fsync(stream.fileno())


def init_fixture(root, repo_root, *, uids):
    """Explicit local fixture bootstrap, never an installer of OS identities."""
    root = Path(root).absolute()
    if set(uids) != set(ROLES) or any(type(v) is not int or v < 0 for v in uids.values()):
        raise p.Rejected('invalid_fixture_roles')
    if 'octobot-local' in root.parts or '..' in root.parts:
        raise p.Rejected('operational_or_traversal_path_forbidden')
    contract, _ = p.load_contract(repo_root)
    root.mkdir(mode=0o755)  # exclusive; no replacing an existing directory
    _path(root, root, directory=True)
    _write(root/'sandbox.marker', MARKER)
    for role in ROLES:
        directory = root/role; directory.mkdir(mode=0o755)
        os.chown(directory, uids[role], -1)
    config = {'version': VERSION, 'scope': SCOPE, 'root_owner': os.geteuid(), 'uids': uids,
        'account': contract['account'], 'scientific_lineage_ref': contract['scientific_lineage_ref'],
        'universe_hash': contract['universe_hash'], 'mapping': contract['symbol_mapping_candidates'],
        'component_sha256': _hash(Path(__file__).read_bytes()), 'fixture_epoch': 'a'*64,
        'clock_id': 'synthetic-fixture-clock-v1', 'fixture_clock_error_seconds': 0,
        'fixture_market_age_seconds': 600, 'fixture_cross_asset_skew_seconds': 60,
        'operational_clock_policy_approved': False, 'execution_approved': False, 'issuable': False}
    raw = p.canonical_bytes(config)
    _write(root/'config.json', raw); _fsync_dir(root)
    return _hash(raw)


def _config(root, expected_config_hash, *, role=None):
    p.require_hash(expected_config_hash)
    root = Path(root).absolute()
    _path(root, root, directory=True)
    raw = _path(root, root/'config.json').read_bytes()
    if _hash(raw) != expected_config_hash:
        raise p.Rejected('external_config_pin_mismatch')
    config = p.read_json(raw)
    _path(root, root, directory=True, owner=config['root_owner'])
    if (config['version'] != VERSION or config['scope'] != SCOPE
            or config.get('execution_approved') is not False or config.get('issuable') is not False
            or config.get('operational_clock_policy_approved') is not False
            or _path(root, root/'sandbox.marker', owner=config['root_owner']).read_bytes() != MARKER
            or config['component_sha256'] != _hash(Path(__file__).read_bytes())):
        raise p.Rejected('fixture_contract_mismatch')
    _path(root, root/'config.json', owner=config['root_owner'])
    if role is not None and os.geteuid() != config['uids'][role]:
        raise p.Rejected('wrong_fixture_role')
    for name in ROLES:
        _path(root, root/name, directory=True, owner=config['uids'][name])
    return config


def _number(value):
    if type(value) not in (int, float) or not math.isfinite(value):
        raise p.Rejected('invalid_fixture_number')
    return value


def normalize(raw, config):
    """Recompute consumed inputs, not V13 targets or scientific validity."""
    data = p.read_json(raw)
    if (data.get('scope') != SCOPE or type(data.get('schema_version')) is not int or data.get('schema_version') != 1
            or data.get('account') != config['account'] or data.get('fixture_epoch') != config['fixture_epoch']
            or data.get('credentials_used') is not False or data.get('research_only') is not True
            or data.get('orders_authorized') is not False or data.get('paper_orders_authorized') is not False
            or data.get('clock_id') != config['clock_id']):
        raise p.Rejected('not_pinned_synthetic_input')
    cutoff = p.timestamp(data['cutoff_at'])
    start, received = p.timestamp(data['request_started_at']), p.timestamp(data['response_completed_at'])
    if start > received or received > cutoff:
        raise p.Rejected('input_not_available_at_cutoff')
    p.bar_date(data['source_bar_date'])
    if p.timestamp(data['source_bar_date']+'T00:00:00Z')+dt.timedelta(days=1) > cutoff:
        raise p.Rejected('source_bar_not_closed')
    mapping = {m['symbol']: m for m in config['mapping']}
    if set(data['symbols']) != set(mapping):
        raise p.Rejected('portfolio_incomplete_or_foreign')
    selected, measured = {}, []
    for symbol, identity in mapping.items():
        value = data['symbols'][symbol]
        if any(value.get(k) != identity[k] for k in ('research_symbol','exchange_symbol')):
            raise p.Rejected('symbol_mapping_mismatch')
        if value.get('mark_unit') != 'USDT_per_base' or value.get('quantity_unit') != 'base':
            raise p.Rejected('unit_mismatch')
        closes = {}
        for bar in value['daily']:
            at = p.timestamp(bar['closed_at'])
            if at > cutoff:
                continue  # preserve future bytes in raw, exclude them from identity
            close = _number(bar['close'])
            key = at.isoformat()
            if close <= 0 or (key in closes and closes[key] != close):
                raise p.Rejected('invalid_or_conflicting_close')
            closes[key] = close
        if not closes:
            raise p.Rejected('causal_bars_missing')
        funding = {}
        for event in value['settled_funding']:
            ms = event['timestamp_ms']
            if type(ms) is not int or ms <= 0:
                raise p.Rejected('invalid_settlement_time')
            if ms > int(cutoff.timestamp()*1000):
                continue
            rate = _number(event['rate'])
            if ms in funding and funding[ms] != rate:
                raise p.Rejected('raw_funding_duplicate_conflict')
            funding[ms] = rate
        mark = value['mark']
        if mark.get('measurement_at') is None:
            raise p.Rejected('mark_measurement_unknown')
        at, mark_received = p.timestamp(mark['measurement_at']), p.timestamp(mark['received_at'])
        price = _number(mark['price'])
        if (price <= 0 or at > mark_received or mark_received > received
                or (cutoff-at).total_seconds() > config['fixture_market_age_seconds']):
            raise p.Rejected('invalid_or_stale_mark')
        book = value['book']; book_at = p.timestamp(book['measurement_at'])
        if book_at > received or (cutoff-book_at).total_seconds() > config['fixture_market_age_seconds']:
            raise p.Rejected('invalid_or_stale_book')
        for side in ('bids','asks'):
            if not book[side] or any(len(row) != 2 or any(_number(v) <= 0 for v in row) for row in book[side]):
                raise p.Rejected('invalid_depth')
        if max(row[0] for row in book['bids']) >= min(row[0] for row in book['asks']):
            raise p.Rejected('crossed_book')
        if value.get('min_quantity') is not None or value.get('min_notional') is not None:
            raise p.Rejected('minimums_must_remain_unknown')
        measured += [at, book_at]
        selected[symbol] = {'daily': sorted(closes.items()), 'settled_funding': sorted(funding.items()),
            'mark': {'price': price, 'measurement_at': at.isoformat()},
            'book': {'measurement_at': book_at.isoformat(), 'bids': book['bids'], 'asks': book['asks']},
            'mark_unit': 'USDT_per_base', 'quantity_unit': 'base', 'min_quantity': None, 'min_notional': None}
    if (max(measured)-min(measured)).total_seconds() > config['fixture_cross_asset_skew_seconds']:
        raise p.Rejected('cross_asset_skew')
    causal = {'version': VERSION, 'account': config['account'], 'scientific_lineage_ref': config['scientific_lineage_ref'],
        'source_bar_date': data['source_bar_date'], 'universe_hash': config['universe_hash'], 'symbols': selected}
    snapshot_id = p.digest({'domain': VERSION, 'causal_input_hash': p.digest(causal),
                            'source_bar_date': data['source_bar_date'], 'universe_hash': config['universe_hash']})
    return causal, snapshot_id, data


def publish(root, source, *, expected_config_hash, expected_raw_hash, _fault=None):
    config = _config(root, expected_config_hash, role='publisher'); root = Path(root)
    raw = _path(root, source, owner=config['uids']['strategy']).read_bytes()
    if _hash(raw) != expected_raw_hash:
        raise p.Rejected('raw_pin_mismatch')
    causal, snapshot, data = normalize(raw, config)
    publication_id = p.digest({'snapshot_id': snapshot, 'raw_sha256': expected_raw_hash})
    directory = root/'publisher'/publication_id
    manifest = {'version': VERSION, 'scope': SCOPE, 'publication_id': publication_id,
        'snapshot_id': snapshot, 'raw_sha256': expected_raw_hash, 'causal_input_hash': p.digest(causal),
        'account': config['account'], 'fixture_epoch': config['fixture_epoch'], 'source_bar_date': data['source_bar_date'],
        'response_completed_at_declared_fixture': data['response_completed_at'],
        'execution_approved': False, 'issuable': False}
    if not directory.exists():
        _path(root, directory, exists=False); directory.mkdir(mode=0o755)
    _path(root, directory, directory=True, owner=config['uids']['publisher'])
    for name, content in [('raw.json',raw),('inputs.json',p.canonical_bytes(causal)),('manifest.json',p.canonical_bytes(manifest))]:
        _write(directory/name, content)
        if _fault:
            _fault(name)
    _fsync_dir(directory); _fsync_dir(directory.parent)
    if _fault:
        _fault('after_bundle_fsync')
    return {'publication_id': publication_id, 'snapshot_id': snapshot, 'manifest_hash': p.digest(manifest)}


def _bundle(root, publication_id, config):
    p.require_hash(publication_id)
    directory = Path(root)/'publisher'/publication_id
    _path(root, directory, directory=True, owner=config['uids']['publisher'])
    raw = _path(root, directory/'raw.json', owner=config['uids']['publisher']).read_bytes()
    causal, snapshot, data = normalize(raw, config)
    stored = _path(root, directory/'inputs.json', owner=config['uids']['publisher']).read_bytes()
    manifest = p.read_json(_path(root, directory/'manifest.json', owner=config['uids']['publisher']).read_bytes())
    expected = {'version': VERSION, 'scope': SCOPE, 'publication_id': publication_id,
        'snapshot_id': snapshot, 'raw_sha256': _hash(raw), 'causal_input_hash': p.digest(causal),
        'account': config['account'], 'fixture_epoch': config['fixture_epoch'], 'source_bar_date': data['source_bar_date'],
        'response_completed_at_declared_fixture': data['response_completed_at'],
        'execution_approved': False, 'issuable': False}
    if stored != p.canonical_bytes(causal) or manifest != expected or publication_id != p.digest({'snapshot_id':snapshot,'raw_sha256':_hash(raw)}):
        raise p.Rejected('bundle_derivation_mismatch')
    return manifest, causal


def _witness_db(root, config, *, write=False):
    path = Path(root)/'witness'/'witness.sqlite'
    if path.exists():
        _path(root, path, owner=config['uids']['witness'])
    elif not write:
        raise p.Rejected('witness_missing')
    for suffix in ('-journal','-wal','-shm'):
        sidecar = Path(str(path)+suffix)
        if sidecar.exists() or sidecar.is_symlink():
            _path(root, sidecar, owner=config['uids']['witness'])
            if suffix != '-journal' and sidecar.stat().st_size:
                raise p.Rejected('witness_wal_not_supported')
    db = sqlite3.connect(path if write else path.as_uri()+'?mode=ro', uri=not write, timeout=1)
    db.row_factory = sqlite3.Row
    if write:
        # Other fixture roles may read. Only the witness can write either this
        # file or its parent; SQLite permissions do not separate tables.
        path.chmod(0o644); db.execute('PRAGMA journal_mode=DELETE'); db.execute('PRAGMA synchronous=FULL')
        db.execute('CREATE TABLE IF NOT EXISTS attestations (sequence INTEGER PRIMARY KEY, stage TEXT NOT NULL, slot TEXT NOT NULL, publication_id TEXT NOT NULL, payload TEXT NOT NULL, event_hash TEXT NOT NULL UNIQUE, UNIQUE(stage,slot))')
        db.commit()
    else:
        db.execute('PRAGMA query_only=ON')
    return db


def _head(db):
    previous = None
    for number, row in enumerate(db.execute('SELECT * FROM attestations ORDER BY sequence'),1):
        payload = p.read_json(row['payload'])
        if (row['sequence'] != number or payload['sequence'] != number or payload['previous_hash'] != previous
                or row['stage'] != payload['stage'] or row['slot'] != payload['slot']
                or row['publication_id'] != payload['publication_id'] or p.digest(payload) != row['event_hash']):
            raise p.Rejected('witness_chain_mismatch')
        previous = row['event_hash']
    return previous


def attest(root, publication_id, *, stage, expected_config_hash, clock, _fault=None):
    """Witness commits first, then samples a separate synthetic post-commit clock."""
    config = _config(root, expected_config_hash, role='witness'); root = Path(root)
    if stage not in ('publication','derivation'):
        raise p.Rejected('invalid_attestation_stage')
    manifest, causal = _bundle(root, publication_id, config)
    # A visible staging file is insufficient. Independently confirm persistence
    # before committing the event, also when the publisher crashed mid-stage.
    directory = root/'publisher'/publication_id
    for name in ('raw.json', 'inputs.json', 'manifest.json'):
        with (directory/name).open('rb') as stream:
            os.fsync(stream.fileno())
    _fsync_dir(directory); _fsync_dir(directory.parent)
    object_hash = p.digest(manifest)
    if stage == 'derivation':
        derivation = _derivation(root, publication_id, config, manifest, causal)
        with (root/'verifier'/(publication_id+'.json')).open('rb') as stream:
            os.fsync(stream.fileno())
        _fsync_dir(root/'verifier')
        object_hash = p.digest(derivation)
    slot = config['fixture_epoch']+':'+manifest['source_bar_date']
    lockpath = root/'witness'/'writer.lock'
    fd = os.open(lockpath, os.O_RDWR | os.O_CREAT | os.O_NOFOLLOW, 0o600)
    try:
        _path(root, lockpath, owner=config['uids']['witness']); fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        with closing(_witness_db(root, config, write=True)) as db:
            db.execute('BEGIN IMMEDIATE')
            try:
                previous = _head(db)
                row = db.execute('SELECT * FROM attestations WHERE stage=? AND slot=?',(stage,slot)).fetchone()
                if row:
                    event = p.read_json(row['payload'])
                    if event['publication_id'] != publication_id or event['object_hash'] != object_hash:
                        raise p.Rejected('slot_or_receipt_conflict')
                else:
                    if stage == 'derivation' and db.execute('SELECT count(*) FROM attestations WHERE stage=? AND slot=? AND publication_id=?',('publication',slot,publication_id)).fetchone()[0] != 1:
                        raise p.Rejected('publication_attestation_missing')
                    sequence = db.execute('SELECT count(*) FROM attestations').fetchone()[0]+1
                    event = {'scope': SCOPE, 'stage': stage, 'slot': slot, 'publication_id': publication_id,
                             'object_hash': object_hash, 'sequence': sequence, 'previous_hash': previous}
                    db.execute('INSERT INTO attestations VALUES (?,?,?,?,?,?)',(sequence,stage,slot,publication_id,p.canonical_bytes(event).decode(),p.digest(event)))
                if _fault:
                    _fault('before_witness_commit',db)
                db.commit()
                if _fault:
                    _fault('after_witness_commit',db)
            except BaseException:
                db.rollback(); raise
        _fsync_dir(root/'witness')
        ackpath = root/'witness'/(publication_id+'-'+stage+'.json')
        if ackpath.exists():
            ack = p.read_json(_path(root,ackpath,owner=config['uids']['witness']).read_bytes())
            if ack['event'] != event:
                raise p.Rejected('ack_conflict')
        else:
            # This timestamp is sampled after the attested SQLite commit. It
            # does not pretend to be the completion time of its own file fsync.
            observed = clock()
            when = p.timestamp(observed)
            lower = p.timestamp(manifest['response_completed_at_declared_fixture'])
            if stage == 'derivation':
                puback = _ack(root,publication_id,'publication',config)
                lower = max(lower,p.timestamp(puback['post_commit_observed_at_fixture']))
            if when < lower:
                raise p.Rejected('witness_clock_regression')
            ack = {'scope': SCOPE, 'event': event, 'event_hash': p.digest(event),
                   'clock_id': config['clock_id'], 'post_commit_observed_at_fixture': observed}
            try:
                _write(ackpath,p.canonical_bytes(ack)); _fsync_dir(ackpath.parent)
            except BaseException:
                # No acknowledgement pin is returned on a failed write/fsync.
                # The committed event remains recoverable by the sole writer.
                ackpath.unlink(missing_ok=True)
                raise
        return {'ack_hash': p.digest(ack), 'event_hash': p.digest(event), 'ack': ack}
    finally:
        os.close(fd)


def _ack(root, publication_id, stage, config):
    path = Path(root)/'witness'/(publication_id+'-'+stage+'.json')
    ack = p.read_json(_path(root,path,owner=config['uids']['witness']).read_bytes())
    if (ack['scope'] != SCOPE or ack['event']['stage'] != stage or ack['clock_id'] != config['clock_id']
            or ack['event']['publication_id'] != publication_id or ack['event_hash'] != p.digest(ack['event'])):
        raise p.Rejected('ack_identity_mismatch')
    with closing(_witness_db(root,config)) as db:
        _head(db)
        row = db.execute('SELECT payload FROM attestations WHERE event_hash=?',(ack['event_hash'],)).fetchone()
        if row is None or p.read_json(row[0]) != ack['event']:
            raise p.Rejected('uncommitted_ack')
    return ack


def derive(root, publication_id, *, expected_config_hash, expected_publication_ack_hash, _fault=None):
    config = _config(root,expected_config_hash,role='verifier')
    manifest, causal = _bundle(root,publication_id,config)
    ack = _ack(root,publication_id,'publication',config)
    if p.digest(ack) != expected_publication_ack_hash or ack['event']['object_hash'] != p.digest(manifest):
        raise p.Rejected('publication_ack_pin_mismatch')
    receipt = {'version': VERSION, 'scope': SCOPE, 'publication_id': publication_id,
        'snapshot_id': manifest['snapshot_id'], 'causal_input_hash': p.digest(causal),
        'manifest_hash': p.digest(manifest), 'publication_ack_hash': p.digest(ack),
        'derivation_status': 'NORMALIZED_INPUTS_RECOMPUTED_FIXTURE_ONLY',
        'original_v13_strategy_recomputed': False, 'execution_approved': False, 'issuable': False}
    path = Path(root)/'verifier'/(publication_id+'.json')
    _write(path,p.canonical_bytes(receipt)); _fsync_dir(path.parent)
    if _fault:
        _fault('after_derivation_fsync')
    return p.digest(receipt)


def _derivation(root, publication_id, config, manifest, causal):
    path = Path(root)/'verifier'/(publication_id+'.json')
    receipt = p.read_json(_path(root,path,owner=config['uids']['verifier']).read_bytes())
    ack = _ack(root,publication_id,'publication',config)
    expected = {'version': VERSION, 'scope': SCOPE, 'publication_id': publication_id,
        'snapshot_id': manifest['snapshot_id'], 'causal_input_hash': p.digest(causal),
        'manifest_hash': p.digest(manifest), 'publication_ack_hash': p.digest(ack),
        'derivation_status': 'NORMALIZED_INPUTS_RECOMPUTED_FIXTURE_ONLY',
        'original_v13_strategy_recomputed': False, 'execution_approved': False, 'issuable': False}
    if receipt != expected:
        raise p.Rejected('derivation_receipt_mismatch')
    return receipt


def verify(root, publication_id, *, expected_config_hash, expected_publication_ack_hash,
           expected_derivation_ack_hash, expected_witness_head, checked_at):
    config = _config(root,expected_config_hash)
    manifest, causal = _bundle(root,publication_id,config)
    receipt = _derivation(root,publication_id,config,manifest,causal)
    publication = _ack(root,publication_id,'publication',config)
    derivation = _ack(root,publication_id,'derivation',config)
    with closing(_witness_db(root,config)) as db:
        if _head(db) != expected_witness_head:
            raise p.Rejected('external_witness_head_mismatch')
    if (p.digest(publication) != expected_publication_ack_hash or p.digest(derivation) != expected_derivation_ack_hash
            or publication['event']['object_hash'] != p.digest(manifest)
            or derivation['event']['object_hash'] != p.digest(receipt)):
        raise p.Rejected('external_ack_pin_mismatch')
    available = max(p.timestamp(manifest['response_completed_at_declared_fixture']),
                    p.timestamp(publication['post_commit_observed_at_fixture']),
                    p.timestamp(derivation['post_commit_observed_at_fixture']))
    if (p.timestamp(checked_at) < available
            or p.timestamp(publication['post_commit_observed_at_fixture']) < p.timestamp(manifest['response_completed_at_declared_fixture'])
            or p.timestamp(derivation['post_commit_observed_at_fixture']) < p.timestamp(publication['post_commit_observed_at_fixture'])):
        raise p.Rejected('source_not_available')
    return {'scope': SCOPE, 'status': 'CAUSAL_PUBLICATION_VERIFIED_FIXTURE_ONLY',
        'snapshot_id': manifest['snapshot_id'], 'raw_sha256': manifest['raw_sha256'],
        'causal_input_hash': manifest['causal_input_hash'], 'source_available_at_fixture': available.isoformat(),
        'source_available_at_operational': None, 'independent_custody_verified_operational': False,
        'fixture_roles_distinct': len(set(config['uids'].values())) == len(ROLES),
        'original_v13_strategy_recomputed': False, 'execution_approved': False, 'issuable': False,
        'kucoin_order_admissibility_proven': False, 'readiness': 'BLOCKED'}
