"""Inactive contemporary receipt mechanics on EXPLICIT synthetic streams only.

work-card-dec1a7e6-6650-416a-9a02-290af7af0272. No HTTP client, collector,
strategy evaluation, issuer, order, credential or runtime entrypoint.
Reception times are sampled by the custodian, never supplied in response JSON.
"""
from __future__ import annotations

from contextlib import closing
import fcntl
import hashlib
import os
from pathlib import Path
import sqlite3
import stat

from octobot.ai_strategy_lab import v13_original_portfolio as p
from octobot.ai_strategy_lab import v13_causal_publication_fixture as storage

VERSION = 'v13-contemporary-capture-review-v1'
SCOPE = 'SYNTHETIC_ARCHITECTURE_ONLY'
MARKER = (VERSION+'\n').encode()
ROLES = ('strategy', 'custodian', 'witness', 'verifier')
MAX_RAW = 16*1024*1024
REPO = Path(__file__).resolve().parents[2]
RECEIPT_FIELDS = {'version','scope','receipt_id','nonce','capture_epoch','account','scientific_lineage_ref',
    'universe_hash','collector_identity_fixture','component_bundle_sha256','request_key','request','request_started',
    'first_byte_received','response_completed','raw_payload_sha256','raw_payload_length','http_status_fixture',
    'transport_result','actual_http_request_performed','credentials_used','receipt_committed_at',
    'receipt_commit_confirmation','historical_capture_receipts_created','execution_approved','issuable'}


def sha(raw):
    return hashlib.sha256(raw).hexdigest()


def _code_pins():
    return {'capture': sha(Path(__file__).read_bytes()), 'portfolio': sha(Path(p.__file__).read_bytes()),
            'storage_helpers': sha(Path(storage.__file__).read_bytes())}


def _requests(mapping):
    """URLs already declared locally; labels are not exchange-authenticated evidence."""
    result = {'execution_contracts': {'purpose': 'EXECUTION_KUCOIN', 'kind': 'contracts',
        'method': 'GET', 'url': 'https://api-futures.kucoin.com/api/v1/contracts/active', 'symbol': None}}
    for item in mapping:
        symbol = item['symbol']
        result['scientific_daily:'+symbol] = {'purpose': 'SCIENTIFIC_BINANCE', 'kind': 'daily',
            'method': 'GET', 'url': 'https://fapi.binance.com/fapi/v1/klines?symbol='+symbol+'&interval=1d&limit=2',
            'symbol': symbol}
        result['scientific_funding:'+symbol] = {'purpose': 'SCIENTIFIC_BINANCE', 'kind': 'settled_funding',
            'method': 'GET', 'url': 'https://fapi.binance.com/fapi/v1/fundingRate?symbol='+symbol+'&limit=2',
            'symbol': symbol}
        result['execution_book:'+symbol] = {'purpose': 'EXECUTION_KUCOIN', 'kind': 'book',
            'method': 'GET', 'url': 'https://api-futures.kucoin.com/api/v1/level2/depth20?symbol='+item['exchange_symbol'],
            'symbol': symbol}
    return result


def init_review(root, *, uids, fixture_started_at):
    """Root-owned local fixture bootstrap, without installing identities or clocks."""
    if os.geteuid() != 0 or set(uids) != set(ROLES) or any(type(v) is not int or v < 0 for v in uids.values()):
        raise p.Rejected('root_fixture_bootstrap_required')
    root = Path(root).absolute(); p.timestamp(fixture_started_at)
    if 'octobot-local' in root.parts or '..' in root.parts:
        raise p.Rejected('operational_output_forbidden')
    contract, _ = p.load_contract(REPO)
    root.mkdir(mode=0o755); storage._path(root, root, directory=True)
    storage._write(root/'sandbox.marker', MARKER)
    for role in ROLES:
        directory = root/role; directory.mkdir(mode=0o755); os.chown(directory, uids[role], -1)
    evidence = {'kind': 'SYNTHETIC_CLOCK_EVIDENCE_ONLY', 'fixture_started_at': fixture_started_at,
        'clock_id': 'capture-fixture-clock-v1', 'fixture_error_bound_seconds': 0,
        'operational_error_bound_seconds': None, 'operational_clock_approved': False}
    config = {'version': VERSION, 'scope': SCOPE, 'root_owner': 0, 'uids': uids,
        'account': contract['account'], 'scientific_lineage_ref': contract['scientific_lineage_ref'],
        'universe_hash': contract['universe_hash'], 'mapping': contract['symbol_mapping_candidates'],
        'requests': _requests(contract['symbol_mapping_candidates']), 'code_pins': _code_pins(),
        'capture_epoch': p.digest({'version': VERSION, 'started': fixture_started_at, 'uids': uids}),
        'clock_evidence': evidence, 'clock_evidence_ref': p.digest(evidence),
        'operational_custody_approved': False, 'runtime_admission': False, 'issuable': False,
        'execution_approved': False, 'network_acquisition_enabled': False,
        'min_quantity': None, 'min_notional': None,
        'operational_policy': {name: None for name in ('daily_loss','drawdown','order_frequency','cooldown')}}
    storage._write(root/'config.json', p.canonical_bytes(config)); storage._fsync_dir(root)
    return p.digest(config)


def _config(root, pin, role=None):
    root = Path(root).absolute(); p.require_hash(pin)
    raw = storage._path(root, root/'config.json', owner=0).read_bytes()
    if sha(raw) != pin or stat.S_IMODE((root/'config.json').stat().st_mode) != 0o444:
        raise p.Rejected('external_config_pin_mismatch')
    c = p.read_json(raw); contract, _ = p.load_contract(REPO)
    if (c['version'] != VERSION or c['scope'] != SCOPE or c['code_pins'] != _code_pins()
            or c['root_owner'] != 0 or c['account'] != contract['account']
            or c['scientific_lineage_ref'] != contract['scientific_lineage_ref']
            or c['universe_hash'] != contract['universe_hash'] or c['mapping'] != contract['symbol_mapping_candidates']
            or c['requests'] != _requests(c['mapping']) or c['clock_evidence_ref'] != p.digest(c['clock_evidence'])
            or c['clock_evidence']['kind'] != 'SYNTHETIC_CLOCK_EVIDENCE_ONLY'
            or c['clock_evidence']['fixture_error_bound_seconds'] != 0
            or c['clock_evidence']['operational_error_bound_seconds'] is not None
            or c['clock_evidence']['operational_clock_approved'] is not False
            or any(c.get(k) is not False for k in ('operational_custody_approved','runtime_admission',
                'issuable','execution_approved','network_acquisition_enabled'))
            or c['min_quantity'] is not None or c['min_notional'] is not None
            or any(v is not None for v in c['operational_policy'].values())):
        raise p.Rejected('inactive_capture_contract_required')
    storage._path(root, root, owner=0, directory=True)
    if storage._path(root, root/'sandbox.marker', owner=0).read_bytes() != MARKER:
        raise p.Rejected('capture_marker_required')
    for name in ROLES: storage._path(root, root/name, owner=c['uids'][name], directory=True)
    if role and os.geteuid() != c['uids'][role]: raise p.Rejected('wrong_capture_role')
    return c


def _stamp(clock, c, previous=None):
    sample = clock()
    if (not isinstance(sample, dict) or set(sample) != {'utc','monotonic_ns','clock_evidence_ref'}
            or type(sample['monotonic_ns']) is not int or sample['monotonic_ns'] < 0
            or sample['clock_evidence_ref'] != c['clock_evidence_ref']):
        raise p.Rejected('clock_evidence_missing_or_invalid')
    instant = p.timestamp(sample['utc'])
    if instant < p.timestamp(c['clock_evidence']['fixture_started_at']):
        raise p.Rejected('clock_predates_fixture_epoch')
    if previous and (instant < p.timestamp(previous['utc']) or sample['monotonic_ns'] < previous['monotonic_ns']):
        raise p.Rejected('custodian_clock_regression')
    return dict(sample)


def capture(root, nonce, request_key, *, expected_config_hash, fixture_chunks, http_status,
            declared_length, clock, fault=None):
    """Consume a test stream now, retaining partial staging on failure.

    This interface cannot make HTTP requests. All supplied status/body data are
    fixtures. No caller-provided reception/publication timestamp is accepted.
    """
    root = Path(root).absolute(); c = _config(root, expected_config_hash, 'custodian')
    p.require_hash(nonce)
    if not isinstance(request_key, str) or request_key not in c['requests']:
        raise p.Rejected('request_not_in_pinned_registry')
    if type(http_status) is not int or not 100 <= http_status <= 599:
        raise p.Rejected('fixture_http_status_invalid')
    if type(declared_length) is not int or not 0 < declared_length <= MAX_RAW:
        raise p.Rejected('fixture_length_invalid')
    ident = p.digest({'domain': VERSION, 'capture_epoch': c['capture_epoch'], 'nonce': nonce, 'request_key': request_key})
    base = root/'custodian'/ident
    base.mkdir(mode=0o755)  # exclusive: nonce reuse never silently recaptures
    storage._path(root, base, owner=c['uids']['custodian'], directory=True)
    started = _stamp(clock, c); previous = started; first = None; count = 0; digest = hashlib.sha256()
    path = base/'raw.bin'
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
    with os.fdopen(fd, 'wb') as stream:
        for part in fixture_chunks:
            if type(part) is not bytes or not part: raise p.Rejected('fixture_chunk_invalid')
            count += len(part)
            if count > declared_length or count > MAX_RAW: raise p.Rejected('response_length_exceeded')
            sample = _stamp(clock, c, previous); previous = sample
            if first is None: first = sample
            stream.write(part); digest.update(part)
            if fault: fault('received_chunk')
        completed = _stamp(clock, c, previous)
        if count != declared_length or first is None: raise p.Rejected('incomplete_response')
        stream.flush(); os.fchmod(stream.fileno(), 0o444); os.fsync(stream.fileno())
    if fault: fault('after_raw_fsync')
    receipt = {'version': VERSION, 'scope': SCOPE, 'receipt_id': ident, 'nonce': nonce,
        'capture_epoch': c['capture_epoch'], 'account': c['account'], 'scientific_lineage_ref': c['scientific_lineage_ref'],
        'universe_hash': c['universe_hash'], 'collector_identity_fixture': c['uids']['custodian'],
        'component_bundle_sha256': p.digest(c['code_pins']), 'request_key': request_key,
        'request': c['requests'][request_key], 'request_started': started,
        'first_byte_received': first, 'response_completed': completed,
        'raw_payload_sha256': digest.hexdigest(), 'raw_payload_length': count, 'http_status_fixture': http_status,
        'transport_result': 'EXPLICIT_SYNTHETIC_STREAM_COMPLETE', 'actual_http_request_performed': False,
        'credentials_used': False, 'receipt_committed_at': None,
        'receipt_commit_confirmation': 'SEPARATE_WITNESS_ACK_REQUIRED',
        'historical_capture_receipts_created': False, 'execution_approved': False, 'issuable': False}
    storage._write(base/'capture.json', p.canonical_bytes(receipt))
    storage._fsync_dir(base); storage._fsync_dir(base.parent)
    if fault: fault('after_capture_fsync')
    return {'capture_id': ident, 'capture_hash': p.digest(receipt), 'raw_hash': digest.hexdigest(),
            'availability_operational': None, 'scope': SCOPE}


def _capture(root, ident, c, *, sync=False):
    p.require_hash(ident); base = Path(root)/'custodian'/ident
    paths = [storage._path(root, base/name, owner=c['uids']['custodian']) for name in ('raw.bin','capture.json')]
    if paths[0].stat().st_size > MAX_RAW: raise p.Rejected('raw_payload_size_exceeded')
    raw = paths[0].read_bytes(); value = p.read_json(paths[1].read_bytes())
    if not isinstance(value, dict) or set(value) != RECEIPT_FIELDS:
        raise p.Rejected('capture_receipt_schema_invalid')
    expected_id = p.digest({'domain': VERSION, 'capture_epoch': c['capture_epoch'], 'nonce': value['nonce'],
                            'request_key': value['request_key']})
    if (ident != expected_id or value['receipt_id'] != ident or value['version'] != VERSION or value['scope'] != SCOPE
            or value['capture_epoch'] != c['capture_epoch'] or value['account'] != c['account']
            or value['scientific_lineage_ref'] != c['scientific_lineage_ref'] or value['universe_hash'] != c['universe_hash']
            or value['request'] != c['requests'].get(value['request_key'])
            or value['collector_identity_fixture'] != c['uids']['custodian']
            or value['component_bundle_sha256'] != p.digest(c['code_pins'])
            or type(value['http_status_fixture']) is not int or not 100 <= value['http_status_fixture'] <= 599
            or type(value['raw_payload_length']) is not int
            or value['raw_payload_sha256'] != sha(raw) or value['raw_payload_length'] != len(raw)
            or value['transport_result'] != 'EXPLICIT_SYNTHETIC_STREAM_COMPLETE' or not 0 < len(raw) <= MAX_RAW
            or value['receipt_committed_at'] is not None or value['receipt_commit_confirmation'] != 'SEPARATE_WITNESS_ACK_REQUIRED'
            or any(value.get(k) is not False for k in ('actual_http_request_performed','credentials_used',
                'historical_capture_receipts_created','execution_approved','issuable'))):
        raise p.Rejected('capture_receipt_mismatch')
    previous = None
    for key in ('request_started','first_byte_received','response_completed'):
        previous = _stamp(lambda: value[key], c, previous)
    if sync:
        for path in paths:
            with path.open('rb') as stream: os.fsync(stream.fileno())
        storage._fsync_dir(base); storage._fsync_dir(base.parent)
    return value, raw


def _db(root, c, *, write=False):
    db = storage._witness_db(root, c, write=write)
    try:
        if [tuple(row) for row in db.execute('PRAGMA integrity_check')] != [('ok',)]:
            raise p.Rejected('capture_witness_integrity_failure')
        if ({row[0] for row in db.execute("SELECT name FROM sqlite_master WHERE type='table'")} != {'attestations'}
                or db.execute("SELECT count(*) FROM sqlite_master WHERE type IN ('trigger','view')").fetchone()[0]):
            raise p.Rejected('capture_witness_schema_invalid')
        storage._head(db)
        for row in db.execute('SELECT * FROM attestations'):
            event = p.read_json(row['payload'])
            if event['scope'] != SCOPE or event['stage'] != 'capture' or event['capture_epoch'] != c['capture_epoch']:
                raise p.Rejected('capture_witness_namespace_invalid')
        return db
    except BaseException: db.close(); raise


def attest(root, ident, *, expected_config_hash, expected_capture_hash, expected_witness_head, clock, fault=None):
    """Separate witness reconfirms files, commits event, then samples its UTC clock."""
    root = Path(root).absolute(); c = _config(root, expected_config_hash, 'witness')
    receipt, _ = _capture(root, ident, c, sync=True)
    if p.digest(receipt) != p.require_hash(expected_capture_hash): raise p.Rejected('external_capture_pin_mismatch')
    slot = c['capture_epoch']+':'+receipt['nonce']
    lock_path = root/'witness'/'writer.lock'
    fd = os.open(lock_path, os.O_RDWR | os.O_CREAT | os.O_NOFOLLOW, 0o600)
    try:
        storage._path(root, lock_path, owner=c['uids']['witness']); fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        with closing(_db(root, c, write=True)) as db:
            db.execute('BEGIN IMMEDIATE')
            try:
                previous = storage._head(db)
                if previous != expected_witness_head: raise p.Rejected('external_witness_head_mismatch')
                row = db.execute("SELECT payload FROM attestations WHERE stage='capture' AND slot=?", (slot,)).fetchone()
                if row:
                    event = p.read_json(row[0])
                    if event['publication_id'] != ident or event['object_hash'] != expected_capture_hash:
                        raise p.Rejected('capture_nonce_conflict')
                else:
                    sequence = db.execute('SELECT count(*) FROM attestations').fetchone()[0]+1
                    event = {'scope': SCOPE, 'stage': 'capture', 'slot': slot, 'publication_id': ident,
                        'capture_epoch': c['capture_epoch'], 'object_hash': expected_capture_hash,
                        'sequence': sequence, 'previous_hash': previous}
                    db.execute('INSERT INTO attestations VALUES (?,?,?,?,?,?)',
                        (sequence,'capture',slot,ident,p.canonical_bytes(event).decode(),p.digest(event)))
                if fault: fault('before_witness_commit', db)
                db.commit()
                if fault: fault('after_witness_commit', db)
            except BaseException: db.rollback(); raise
        storage._fsync_dir(root/'witness')
        ack_path = root/'witness'/(ident+'-capture.json')
        if ack_path.exists():
            ack = p.read_json(storage._path(root, ack_path, owner=c['uids']['witness']).read_bytes())
            if ack['event'] != event: raise p.Rejected('capture_ack_conflict')
            with ack_path.open('rb') as stream: os.fsync(stream.fileno())
            storage._fsync_dir(ack_path.parent)
        else:
            observed = _stamp(clock, c)
            # Cross-role comparison is UTC ONLY in a declared zero-error fixture.
            # Monotonic clocks from different processes/hosts are never compared.
            floor = p.timestamp(receipt['response_completed']['utc'])
            for path in (root/'witness').glob('*-capture.json'):
                older = p.read_json(path.read_bytes())
                floor = max(floor, p.timestamp(older['post_commit_observed']['utc']))
            if p.timestamp(observed['utc']) < floor: raise p.Rejected('witness_clock_regression')
            ack = {'version': VERSION, 'scope': SCOPE, 'event': event, 'event_hash': p.digest(event),
                'post_commit_observed': observed, 'attests': 'RAW_AND_CAPTURE_RECEIPT_ALREADY_PERSISTED',
                'own_ack_commit_time_known': False, 'operational_clock_approved': False}
            try:
                storage._write(ack_path, p.canonical_bytes(ack)); storage._fsync_dir(ack_path.parent)
                if fault: fault('after_ack_fsync', None)
            except BaseException:
                ack_path.unlink(missing_ok=True); raise
        return {'ack_hash': p.digest(ack), 'event_hash': p.digest(event), 'ack': ack}
    finally: os.close(fd)


def verify_dependency(root, ident, *, expected_config_hash, expected_capture_hash, expected_ack_hash,
                      expected_witness_head, checked_at):
    c = _config(root, expected_config_hash, 'verifier'); root = Path(root).absolute()
    receipt, raw = _capture(root, ident, c)
    ack = p.read_json(storage._path(root, root/'witness'/(ident+'-capture.json'), owner=c['uids']['witness']).read_bytes())
    with closing(_db(root, c)) as db:
        if storage._head(db) != p.require_hash(expected_witness_head): raise p.Rejected('external_witness_head_mismatch')
        row = db.execute("SELECT payload FROM attestations WHERE stage='capture' AND publication_id=?", (ident,)).fetchone()
    if (not row or p.read_json(row[0]) != ack['event'] or ack['event']['object_hash'] != expected_capture_hash
            or ack['event_hash'] != p.digest(ack['event']) or p.digest(receipt) != p.require_hash(expected_capture_hash)
            or p.digest(ack) != p.require_hash(expected_ack_hash) or ack['scope'] != SCOPE or ack['version'] != VERSION
            or ack['attests'] != 'RAW_AND_CAPTURE_RECEIPT_ALREADY_PERSISTED'
            or ack['own_ack_commit_time_known'] is not False or ack['operational_clock_approved'] is not False):
        raise p.Rejected('capture_ack_or_external_pin_mismatch')
    observed = _stamp(lambda: ack['post_commit_observed'], c)
    available = p.timestamp(observed['utc'])
    if available < p.timestamp(receipt['response_completed']['utc']) or p.timestamp(checked_at) < available:
        raise p.Rejected('capture_not_available_at_check')
    reason = None
    try:
        data = p.read_json(raw)
        if receipt['request']['purpose'] == 'EXECUTION_KUCOIN' and (not isinstance(data, dict) or data.get('code') != '200000'):
            reason = 'application_status_invalid'
    except (p.Rejected, ValueError): reason = 'invalid_json_response'
    if receipt['http_status_fixture'] != 200: reason = 'http_status_invalid'
    return {'status': 'CAPTURE_RECEIPT_VERIFIED_FIXTURE_ONLY', 'scope': SCOPE,
        'capture': receipt, 'commit_confirmation': ack, 'receipt_sequence': ack['event']['sequence'],
        'previous_receipt_hash': ack['event']['previous_hash'], 'receipt_committed_observed_at_fixture': observed['utc'],
        'response_framing_valid_fixture': reason is None, 'response_denial_reason': reason,
        'source_available_at_operational': None, 'historical_availability': 'UNRESOLVED',
        'independent_custody_operational': False, 'fixture_uids_distinct': len(set(c['uids'].values())) == len(ROLES),
        'execution_approved': False, 'issuable': False, 'kucoin_order_admissibility_proven': False,
        'readiness': 'BLOCKED'}


def execution_view(root, symbol, *, expected_config_hash, contract_dependency, book_dependency, checked_at):
    """Only a diagnostic field provenance view; never an executor market adapter."""
    c = _config(root, expected_config_hash, 'verifier')
    mapping = {m['symbol']: m for m in c['mapping']}
    if symbol not in mapping: raise p.Rejected('foreign_selected_symbol')
    values = []
    for dependency, request_key in ((contract_dependency, 'execution_contracts'),
                                    (book_dependency, 'execution_book:'+symbol)):
        result = verify_dependency(root, expected_config_hash=expected_config_hash, checked_at=checked_at, **dependency)
        if not result['response_framing_valid_fixture'] or result['capture']['request_key'] != request_key:
            raise p.Rejected('execution_dependency_purpose_or_response_invalid')
        values.append((result, p.read_json(_capture(root, dependency['ident'], c)[1])))
    contracts = values[0][1]['data']; book = values[1][1]['data']
    if not isinstance(contracts, list) or any(not isinstance(row, dict) for row in contracts) or not isinstance(book, dict):
        raise p.Rejected('contract_or_book_fixture_shape_invalid')
    if 'symbol' in book and book['symbol'] != mapping[symbol]['exchange_symbol']:
        raise p.Rejected('book_contract_identity_mismatch')
    matched = [row for row in contracts if row.get('symbol') == mapping[symbol]['exchange_symbol']]
    if len(matched) != 1: raise p.Rejected('contract_mapping_missing_or_duplicate')
    contract = matched[0]
    if contract.get('quoteCurrency') != 'USDT' or contract.get('settleCurrency') != 'USDT':
        raise p.Rejected('contract_currency_mismatch')
    instant = book.get('timestamp')
    if type(instant) is not int or instant <= 0: raise p.Rejected('book_measurement_timestamp_unknown')
    if instant > int(p.timestamp(values[1][0]['capture']['response_completed']['utc']).timestamp()*1000):
        raise p.Rejected('future_book_measurement')
    return {'scope': SCOPE, 'symbol': symbol, 'mapping': mapping[symbol],
        'mark': {'raw_value': contract.get('markPrice'), 'measurement_timestamp': None,
            'measurement_timestamp_status': 'UNKNOWN', 'value_source': 'contracts/active.data[].markPrice',
            'capture_receipt_ref': contract_dependency['expected_capture_hash']},
        'book': {'measurement_timestamp_ms': instant, 'timestamp_source': 'depth20.data.timestamp',
            'capture_receipt_ref': book_dependency['expected_capture_hash']},
        'minimums': {'min_quantity': None, 'min_notional': None, 'status': 'UNKNOWN'},
        'execution_gate': 'DENY_MARK_TIMESTAMP_UNKNOWN', 'unit_semantics_operational_approved': False,
        'source_available_at_operational': None, 'issuable': False, 'readiness': 'BLOCKED'}
