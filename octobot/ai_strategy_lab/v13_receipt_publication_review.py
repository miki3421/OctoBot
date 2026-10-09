"""Inactive receipt/publication integration; SYNTHETIC_ARCHITECTURE_ONLY.

work-card-6f157fda-6e1c-47e4-af41-88368045c0f6. No HTTP or issuance path.
Original reconstruction is delegated to the frozen archive verifier. Matching
fixture receipts attest a test capture, NEVER a historical exchange acquisition.
"""
from contextlib import closing
import fcntl
import hashlib
import os
from pathlib import Path
import stat
from urllib.parse import parse_qs, urlsplit

from octobot.ai_strategy_lab import v13_capture_receipt_review as capture
from octobot.ai_strategy_lab import v13_original_publication_review as archive
from octobot.ai_strategy_lab import v13_original_portfolio as p
from octobot.ai_strategy_lab import v13_causal_publication_fixture as storage

VERSION = 'v13-receipt-publication-review-v1'
SCOPE = capture.SCOPE
ROLES = archive.ROLES
MARKER = (VERSION+'\n').encode()
FLAGS = {'research_only': True, 'execution_approved': False, 'issuable': False,
         'historical_capture_receipts_created': False, 'operational_custody_approved': False,
         'operational_clock_approved': False, 'kucoin_order_admissibility_proven': False}


def _pins():
    return {name: hashlib.sha256(Path(module.__file__).read_bytes()).hexdigest() for name, module in
            [('integration', __import__(__name__, fromlist=[''])), ('capture', capture),
             ('archive', archive), ('portfolio', p), ('storage', storage)]}


def init_review(root, *, capture_root, capture_config_hash, capture_head, archive_root,
                archive_config_hash, inventory_hash, archive_publication_ack_hash,
                dependency_bindings, uids, fixture_cutoff_at):
    """Pin an explicit dependency plan in a new root-owned sandbox, not a grant."""
    if os.geteuid() != 0 or set(uids) != set(ROLES) or any(type(v) is not int or v < 0 for v in uids.values()):
        raise p.Rejected('root_fixture_bootstrap_required')
    root = Path(root).absolute(); cr = Path(capture_root).absolute(); ar = Path(archive_root).absolute()
    if any('octobot-local' in x.parts or '..' in x.parts for x in (root, cr, ar)):
        raise p.Rejected('operational_output_forbidden')
    if root == cr or root == ar or root.is_relative_to(cr) or root.is_relative_to(ar) or cr == ar:
        raise p.Rejected('overlapping_review_roots')
    for pin in (capture_config_hash, capture_head, archive_config_hash, inventory_hash, archive_publication_ack_hash):
        p.require_hash(pin)
    p.timestamp(fixture_cutoff_at)
    cc = capture._config(cr, capture_config_hash); ac = archive._config(ar, archive_config_hash)
    if any(cc['uids'][role] != uids[role] for role in capture.ROLES) or ac['uids'] != uids:
        raise p.Rejected('role_binding_mismatch')
    if ac['expected_inventory_hash'] != inventory_hash:
        raise p.Rejected('archive_inventory_pin_mismatch')
    if not isinstance(dependency_bindings, dict): raise p.Rejected('dependency_plan_invalid')
    # Validate paths before persisting configuration. Exact coverage is checked
    # against the independently inventoried archive before publication.
    for path, dep in dependency_bindings.items():
        if (not isinstance(path, str) or not path.startswith('raw/') or Path(path).is_absolute()
                or '..' in Path(path).parts or not isinstance(dep, dict)
                or set(dep) != {'ident', 'expected_capture_hash', 'expected_ack_hash'}):
            raise p.Rejected('dependency_plan_invalid')
        for pin in dep.values(): p.require_hash(pin)
    root.mkdir(mode=0o755); storage._path(root, root, owner=0, directory=True)
    storage._write(root/'sandbox.marker', MARKER)
    for role in ROLES:
        d = root/role; d.mkdir(mode=0o755); os.chown(d, uids[role], -1)
    config = {'version': VERSION, 'scope': SCOPE, 'root_owner': 0, 'uids': uids, 'code_pins': _pins(),
              'capture_root': str(cr), 'capture_config_hash': capture_config_hash, 'capture_head': capture_head,
              'archive_root': str(ar), 'archive_config_hash': archive_config_hash, 'inventory_hash': inventory_hash,
              'archive_publication_ack_hash': archive_publication_ack_hash,
              'dependency_bindings': dependency_bindings, 'fixture_cutoff_at': fixture_cutoff_at,
              'account': ac['account'], 'scientific_lineage_ref': ac['scientific_lineage_ref'],
              'universe_hash': ac['universe_hash'], 'min_quantity': None, 'min_notional': None,
              'operational_policy': {k: None for k in ('daily_loss', 'drawdown', 'order_frequency', 'cooldown')},
              **FLAGS}
    storage._write(root/'config.json', p.canonical_bytes(config)); storage._fsync_dir(root)
    return p.digest(config)


def _config(root, pin, role=None):
    root = Path(root).absolute(); p.require_hash(pin)
    path = storage._path(root, root/'config.json', owner=0)
    c = p.read_json(path.read_bytes())
    if (p.digest(c) != pin or stat.S_IMODE(path.stat().st_mode) != 0o444
            or c['version'] != VERSION or c['scope'] != SCOPE or c['code_pins'] != _pins()
            or any(c.get(k) is not v for k, v in FLAGS.items())
            or c['min_quantity'] is not None or c['min_notional'] is not None
            or any(v is not None for v in c['operational_policy'].values())):
        raise p.Rejected('inactive_integration_contract_required')
    storage._path(root, root, owner=0, directory=True)
    if storage._path(root, root/'sandbox.marker', owner=0).read_bytes() != MARKER:
        raise p.Rejected('integration_marker_required')
    for name in ROLES: storage._path(root, root/name, owner=c['uids'][name], directory=True)
    if role and os.geteuid() != c['uids'][role]: raise p.Rejected('wrong_integration_role')
    return c


def _capture_proof(c, dep, *, sync=False):
    """Read-only proof for publisher/witness too; no writer role impersonation.

    Uses frozen capture validators, plus strict ACK/event membership and framing.
    This cannot bypass verify_dependency's verifier role to perform a write.
    """
    root = Path(c['capture_root']); cc = capture._config(root, c['capture_config_hash'])
    receipt, raw = capture._capture(root, dep['ident'], cc, sync=sync)
    ack_path = storage._path(root, root/'witness'/(dep['ident']+'-capture.json'), owner=cc['uids']['witness'])
    ack = p.read_json(ack_path.read_bytes())
    event = ack['event']
    with closing(capture._db(root, cc)) as db:
        if storage._head(db) != c['capture_head']: raise p.Rejected('capture_head_mismatch')
        row = db.execute('SELECT payload FROM attestations WHERE event_hash=?', (ack['event_hash'],)).fetchone()
    if (set(ack) != {'version','scope','event','event_hash','post_commit_observed','attests',
                     'own_ack_commit_time_known','operational_clock_approved'}
            or ack['version'] != capture.VERSION or ack['scope'] != SCOPE
            or not row or p.read_json(row[0]) != event or ack['event_hash'] != p.digest(event)
            or event['stage'] != 'capture' or event['scope'] != SCOPE
            or event['publication_id'] != dep['ident'] or event['capture_epoch'] != cc['capture_epoch']
            or event['slot'] != cc['capture_epoch']+':'+receipt['nonce']
            or event['object_hash'] != dep['expected_capture_hash']
            or p.digest(receipt) != dep['expected_capture_hash'] or p.digest(ack) != dep['expected_ack_hash']
            or ack['attests'] != 'RAW_AND_CAPTURE_RECEIPT_ALREADY_PERSISTED'
            or ack['own_ack_commit_time_known'] is not False or ack['operational_clock_approved'] is not False):
        raise p.Rejected('capture_proof_mismatch')
    observed = capture._stamp(lambda: ack['post_commit_observed'], cc)
    if not p.timestamp(receipt['response_completed']['utc']) <= p.timestamp(observed['utc']) <= p.timestamp(c['fixture_cutoff_at']):
        raise p.Rejected('capture_unavailable_at_fixture_cutoff')
    if receipt['http_status_fixture'] != 200 or not isinstance(p.read_json(raw), list):
        raise p.Rejected('scientific_response_framing_invalid')
    if sync:
        with ack_path.open('rb') as f: os.fsync(f.fileno())
        storage._fsync_dir(ack_path.parent)
    return receipt, ack


def _manifest(c, *, sync=False):
    ar = Path(c['archive_root']); ac = archive._config(ar, c['archive_config_hash'])
    manifest, inv = archive._publication(ar, c['inventory_hash'], ac)
    if sync: archive._inventory(ar, c['inventory_hash'], ac, sync=True)
    pa = archive._ack(ar, c['inventory_hash'], 'publication', ac)
    if p.digest(pa) != c['archive_publication_ack_hash'] or pa['event']['object_hash'] != p.digest(manifest):
        raise p.Rejected('archive_publication_ack_mismatch')
    if p.timestamp(pa['post_commit_observed_at']) > p.timestamp(c['fixture_cutoff_at']):
        raise p.Rejected('archive_publication_unavailable_at_fixture_cutoff')
    raw_items = {x['path']: x for x in inv['dependencies'] if x['kind'] == 'raw_response'}
    if not raw_items or set(raw_items) != set(c['dependency_bindings']):
        raise p.Rejected('capture_dependency_coverage_mismatch')
    bindings = []
    for path, item in sorted(raw_items.items()):
        dep = c['dependency_bindings'][path]; receipt, ack = _capture_proof(c, dep, sync=sync)
        request = receipt['request']; url = urlsplit(item['request_url']); query = parse_qs(url.query)
        kind = {'/fapi/v1/klines': 'daily', '/fapi/v1/fundingRate': 'settled_funding'}.get(url.path)
        if (request['purpose'] != 'SCIENTIFIC_BINANCE' or request['kind'] != kind
                or kind is None or query.get('symbol') != [request['symbol']]
                or request['method'] != item['request_method'] or request['url'] != item['request_url']
                or item['research_exchange'] != 'BINANCE_FUTURES'
                or receipt['raw_payload_sha256'] != item['response_sha256']):
            raise p.Rejected('capture_request_or_payload_binding_mismatch')
        bindings.append({'archive_path': path, 'archive_artifact_hash': item['sha256'],
                         'raw_response_hash': item['response_sha256'], **dep,
                         'capture_observed_at_fixture': ack['post_commit_observed']['utc']})
    if {parse_qs(urlsplit(x['request_url']).query)['symbol'][0] for x in raw_items.values()} != set(p.load_contract(capture.REPO)[0]['universe']):
        raise p.Rejected('scientific_universe_coverage_mismatch')
    return {'version': VERSION, 'scope': SCOPE, 'inventory_hash': c['inventory_hash'],
            'archive_publication_hash': p.digest(manifest), 'archive_publication_ack_hash': p.digest(pa),
            'capture_config_hash': c['capture_config_hash'], 'capture_head': c['capture_head'],
            'source_bar_date': inv['source_bar_date'], 'account': c['account'],
            'scientific_lineage_ref': c['scientific_lineage_ref'], 'universe_hash': c['universe_hash'],
            'dependencies': inv['dependencies'], 'capture_bindings_fixture': bindings,
            'historical_availability_status': 'UNRESOLVED', **FLAGS}


def publish(root, *, expected_config_hash, fault=None):
    c = _config(root, expected_config_hash, 'publisher'); obj = _manifest(c, sync=True); ident = p.digest(obj)
    storage._write(Path(root)/'publisher'/(ident+'.json'), p.canonical_bytes(obj))
    storage._fsync_dir(Path(root)/'publisher')
    if fault: fault('after_publication_fsync', None)
    return ident


def _publication(root, ident, c):
    p.require_hash(ident)
    obj = p.read_json(storage._path(root, Path(root)/'publisher'/(ident+'.json'), owner=c['uids']['publisher']).read_bytes())
    if p.digest(obj) != ident or obj != _manifest(c): raise p.Rejected('integration_publication_mismatch')
    return obj


def _db(root, c, *, write=False):
    db = storage._witness_db(root, c, write=write)
    try:
        if db.execute('PRAGMA integrity_check').fetchone()[0] != 'ok': raise p.Rejected('witness_integrity_failure')
        if ({x[0] for x in db.execute("SELECT name FROM sqlite_master WHERE type='table'")} != {'attestations'}
                or db.execute("SELECT count(*) FROM sqlite_master WHERE type IN ('trigger','view')").fetchone()[0]):
            raise p.Rejected('witness_schema_invalid')
        storage._head(db)
        for row in db.execute('SELECT payload FROM attestations'):
            e = p.read_json(row[0])
            if e['scope'] != SCOPE or e['version'] != VERSION or e['stage'] not in ('publication','derivation'):
                raise p.Rejected('witness_namespace_mismatch')
        return db
    except BaseException: db.close(); raise


def _ack(root, ident, stage, c):
    path = storage._path(root, Path(root)/'witness'/(ident+'-'+stage+'.json'), owner=c['uids']['witness'])
    ack = p.read_json(path.read_bytes()); event = ack['event']
    with closing(_db(root, c)) as db:
        row = db.execute('SELECT payload FROM attestations WHERE event_hash=?', (ack['event_hash'],)).fetchone()
    if (ack['version'] != VERSION or ack['scope'] != SCOPE or ack['event_hash'] != p.digest(event)
            or event['publication_id'] != ident or event['slot'] != c['inventory_hash'] or event['stage'] != stage
            or event['version'] != VERSION or event['scope'] != SCOPE
            or not row or p.read_json(row[0]) != event or ack['own_ack_commit_time_known'] is not False
            or ack['operational_clock_approved'] is not False):
        raise p.Rejected('integration_ack_mismatch')
    p.timestamp(ack['post_commit_observed_at_fixture'])
    return ack


def _wrap(c, ident, pa, derived):
    contract, _ = p.load_contract(capture.REPO)
    p.check_receipt(derived, derived['receipt_hash'])
    if (derived['derivation_status'] != 'VERIFIED' or derived['source_available_at'] is not None
            or derived['availability_status'] != 'UNRESOLVED' or derived['research_only'] is not True
            or derived['execution_approved'] is not False or derived['issuable'] is not False
            or derived['scientific_lineage_ref'] != c['scientific_lineage_ref']
            or derived['universe_hash'] != c['universe_hash'] or set(derived['targets']) != set(contract['universe'])):
        raise p.Rejected('original_derivation_identity_mismatch')
    # Acquisition/ACK identities are provenance, not the scientific snapshot.
    snapshot = p.digest({'domain': VERSION, 'lineage': c['scientific_lineage_ref'],
                         'universe': c['universe_hash'], 'slot': derived['source_bar_date'],
                         'causal_input_hash': derived['causal_input_hash']})
    return {'version': VERSION, 'scope': SCOPE, 'publication_hash': ident, 'publication_ack_hash': p.digest(pa),
            'original_derivation': derived, 'snapshot_id': snapshot,
            'source_available_at_operational': None, 'historical_availability_status': 'UNRESOLVED', **FLAGS}


def _derivation(root, ident, c):
    pa = _ack(root, ident, 'publication', c)
    if pa['event']['object_hash'] != ident: raise p.Rejected('publication_object_mismatch')
    ar = Path(c['archive_root']); ac = archive._config(ar, c['archive_config_hash'])
    am, _ = archive._publication(ar, c['inventory_hash'], ac)
    old = archive._derivation(ar, c['inventory_hash'], ac, am)['original_derivation']
    if p.timestamp(old['verified_at']) < p.timestamp(pa['post_commit_observed_at_fixture']):
        raise p.Rejected('derivation_predates_publication')
    result = p.read_json(storage._path(root, Path(root)/'verifier'/(ident+'.json'), owner=c['uids']['verifier']).read_bytes())
    if result != _wrap(c, ident, pa, old): raise p.Rejected('integration_derivation_mismatch')
    return result


def derive(root, ident, *, expected_config_hash, expected_publication_ack_hash, fault=None):
    c = _config(root, expected_config_hash, 'verifier'); _publication(root, ident, c)
    pa = _ack(root, ident, 'publication', c)
    if p.digest(pa) != expected_publication_ack_hash or pa['event']['object_hash'] != ident:
        raise p.Rejected('publication_ack_pin_mismatch')
    # Frozen original code recomputes from preserved inputs; never caller targets.
    ar = Path(c['archive_root']); ac = archive._config(ar, c['archive_config_hash'])
    archive.derive(ar, c['inventory_hash'], expected_config_hash=c['archive_config_hash'],
                   expected_publication_ack_hash=c['archive_publication_ack_hash'])
    am, _ = archive._publication(ar, c['inventory_hash'], ac)
    derived = archive._derivation(ar, c['inventory_hash'], ac, am)['original_derivation']
    if p.timestamp(derived['verified_at']) < p.timestamp(pa['post_commit_observed_at_fixture']):
        raise p.Rejected('derivation_predates_publication')
    _publication(root, ident, c)  # detect input changes during reconstruction
    result = _wrap(c, ident, pa, derived)
    path = Path(root)/'verifier'/(ident+'.json'); storage._write(path, p.canonical_bytes(result)); storage._fsync_dir(path.parent)
    if fault: fault('after_derivation_fsync', None)
    return p.digest(result)


def attest(root, ident, *, stage, expected_config_hash, expected_witness_head, clock, fault=None):
    root = Path(root); c = _config(root, expected_config_hash, 'witness'); manifest = _publication(root, ident, c)
    if stage not in ('publication','derivation'): raise p.Rejected('invalid_stage')
    obj = manifest if stage == 'publication' else _derivation(root, ident, c)
    path = root/('publisher' if stage == 'publication' else 'verifier')/(ident+'.json')
    _manifest(c, sync=True)
    with path.open('rb') as f: os.fsync(f.fileno())
    storage._fsync_dir(path.parent)
    fd = os.open(root/'witness/writer.lock', os.O_RDWR | os.O_CREAT | os.O_NOFOLLOW, 0o600)
    try:
        storage._path(root, root/'witness/writer.lock', owner=c['uids']['witness']); fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        with closing(_db(root, c, write=True)) as db:
            db.execute('BEGIN IMMEDIATE')
            try:
                previous = storage._head(db)
                if previous != expected_witness_head: raise p.Rejected('external_witness_head_mismatch')
                row = db.execute('SELECT payload FROM attestations WHERE stage=? AND slot=?', (stage,c['inventory_hash'])).fetchone()
                if row:
                    event = p.read_json(row[0])
                    if event['publication_id'] != ident or event['object_hash'] != p.digest(obj): raise p.Rejected('slot_conflict')
                else:
                    event = {'version': VERSION, 'scope': SCOPE, 'stage': stage, 'slot': c['inventory_hash'],
                             'publication_id': ident, 'object_hash': p.digest(obj),
                             'sequence': db.execute('SELECT count(*) FROM attestations').fetchone()[0]+1, 'previous_hash': previous}
                    db.execute('INSERT INTO attestations VALUES (?,?,?,?,?,?)',
                               (event['sequence'],stage,c['inventory_hash'],ident,p.canonical_bytes(event).decode(),p.digest(event)))
                if fault: fault('before_commit', db)
                db.commit()
                if fault: fault('after_commit', db)
            except BaseException: db.rollback(); raise
        storage._fsync_dir(root/'witness')
        ack_path = root/'witness'/(ident+'-'+stage+'.json')
        if ack_path.exists():
            ack = _ack(root, ident, stage, c)
            if ack['event'] != event: raise p.Rejected('ack_conflict')
            with ack_path.open('rb') as f: os.fsync(f.fileno())
            storage._fsync_dir(ack_path.parent)
        else:
            observed = clock(); instant = p.timestamp(observed)
            floor = max(p.timestamp(c['fixture_cutoff_at']), p.timestamp(manifest['source_bar_date']+'T00:00:00Z'))
            for older in (root/'witness').glob('*-*.json'):
                floor = max(floor, p.timestamp(p.read_json(older.read_bytes())['post_commit_observed_at_fixture']))
            if stage == 'derivation': floor = max(floor, p.timestamp(obj['original_derivation']['verified_at']))
            if instant < floor: raise p.Rejected('integration_clock_regression')
            ack = {'version': VERSION, 'scope': SCOPE, 'event': event, 'event_hash': p.digest(event),
                   'post_commit_observed_at_fixture': observed, 'own_ack_commit_time_known': False,
                   'operational_clock_approved': False}
            try:
                storage._write(ack_path, p.canonical_bytes(ack)); storage._fsync_dir(ack_path.parent)
                if fault: fault('after_ack_fsync', None)
            except BaseException: ack_path.unlink(missing_ok=True); raise
        return {'ack_hash': p.digest(ack), 'event_hash': p.digest(event), 'ack': ack}
    finally: os.close(fd)


def verify_review(root, ident, *, expected_config_hash, expected_publication_ack_hash,
                  expected_derivation_ack_hash, expected_witness_head, checked_at):
    c = _config(root, expected_config_hash, 'verifier'); manifest = _publication(root, ident, c)
    derived = _derivation(root, ident, c); a = _ack(root, ident, 'publication', c); b = _ack(root, ident, 'derivation', c)
    with closing(_db(root, c)) as db:
        if storage._head(db) != p.require_hash(expected_witness_head): raise p.Rejected('external_witness_head_mismatch')
    if (p.digest(a) != p.require_hash(expected_publication_ack_hash) or p.digest(b) != p.require_hash(expected_derivation_ack_hash)
            or b['event']['object_hash'] != p.digest(derived)):
        raise p.Rejected('external_ack_pin_mismatch')
    times = [x['capture_observed_at_fixture'] for x in manifest['capture_bindings_fixture']]
    times += [a['post_commit_observed_at_fixture'], b['post_commit_observed_at_fixture'], derived['original_derivation']['verified_at']]
    available = max(map(p.timestamp, times))
    if (p.timestamp(checked_at) < available or p.timestamp(a['post_commit_observed_at_fixture']) < p.timestamp(c['fixture_cutoff_at'])
            or p.timestamp(b['post_commit_observed_at_fixture']) < p.timestamp(a['post_commit_observed_at_fixture'])
            or p.timestamp(b['post_commit_observed_at_fixture']) < p.timestamp(derived['original_derivation']['verified_at'])):
        raise p.Rejected('integration_not_available_at_check')
    return {'version': VERSION, 'scope': SCOPE, 'status': 'RECEIPT_PUBLICATION_DERIVATION_VERIFIED_FIXTURE_ONLY',
            'snapshot_id': derived['snapshot_id'], 'publication_hash': ident,
            'causal_input_hash': derived['original_derivation']['causal_input_hash'],
            'targets': derived['original_derivation']['targets'], 'capture_dependency_count': len(times)-3,
            'current_fixture_bundle_available_at': available.isoformat(),
            'source_available_at_operational': None, 'historical_availability_status': 'UNRESOLVED',
            'fixture_uids_distinct': len(set(c['uids'].values())) == len(ROLES), 'readiness': 'BLOCKED', **FLAGS}
