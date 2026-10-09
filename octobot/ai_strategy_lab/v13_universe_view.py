"""Observational candidate list; never imported by strategy/issuer/executor.

Card work-card-ffc3d4a5-a843-4c3a-9a24-f9eaf2fd5893. No network or writes.
Contract metadata describe the scope of this list, not trading admissibility.
"""
import datetime as dt
import gzip
import hashlib
import json
import math
import os
from pathlib import Path
import re
import stat
import zlib

UTC = dt.timezone.utc
MAX_BYTES = 16 * 1024 * 1024
CAPTURE_UID = 30911
CONTRACT_HASH = '5dfa8ade1eb8b22bf92fe6c88658d4a433be80def181b97d73f4f9bd380911b8'
SOURCE_URL = 'https://api-futures.kucoin.com/api/v1/contracts/active'
FRESH_SECONDS = 900  # UI freshness only; no execution gate uses this value.
MISSING = ['Storico daily e funding continuo da verificare',
           'Spread e profondità nel tempo da misurare',
           'Corrispondenza con i dati Binance da verificare',
           'Costi e correlazioni con la V13 da valutare']


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(',', ':'),
                                    ensure_ascii=False, allow_nan=False).encode()).hexdigest()


def _pairs(items):
    result = {}
    for key, value in items:
        if key in result:
            raise ValueError('duplicate_key')
        result[key] = value
    return result


def decode(raw):
    if len(raw) > MAX_BYTES:
        raise ValueError('oversize_json')
    value = json.loads(raw, object_pairs_hook=_pairs)
    digest(value)  # Reject non-finite numbers, including overflow to infinity.
    return value


def timestamp(value):
    result = dt.datetime.fromisoformat(value.replace('Z', '+00:00'))
    if result.tzinfo is None:
        raise ValueError('timezone_required')
    return result.astimezone(UTC)


def _read(path, uid):
    # fstat and O_NOFOLLOW bind custody checks to the opened file.
    fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW)
    with os.fdopen(fd, 'rb') as stream:
        info = os.fstat(stream.fileno())
        if not stat.S_ISREG(info.st_mode) or info.st_uid != uid or info.st_mode & 0o022:
            raise ValueError('unverified_file_owner')
        if str(path).endswith('.gz'):
            try:
                with gzip.GzipFile(fileobj=stream) as zipped:
                    raw = zipped.read(MAX_BYTES + 1)
            except (zlib.error, EOFError) as error:
                raise ValueError('invalid_compressed_receipt') from error
        else:
            raw = stream.read(MAX_BYTES + 1)
    return decode(raw)


def _nonnegative(value):
    if isinstance(value, bool) or not isinstance(value, (float, int)):
        return None
    return value if math.isfinite(value) and value >= 0 else None


def _classify(item):
    excluded, missing = [], []
    expected = [('status', 'Open', 'Contratto non aperto'),
                ('quoteCurrency', 'USDT', 'Quotazione diversa da USDT'),
                ('settleCurrency', 'USDT', 'Regolamento diverso da USDT'),
                ('isInverse', False, 'Contratto inverso'),
                ('assetClass', 'CRYPTO', 'Classe diversa da crypto'),
                ('marketStage', 'NORMAL', 'Mercato in fase preliminare')]
    for key, target, reason in expected:
        value = item.get(key)
        if value is None or (key == 'isInverse' and type(value) is not bool):
            missing.append('Metadata mancante o non valido: ' + key)
        elif value != target:
            excluded.append(reason)
    if 'expireDate' not in item:
        missing.append('Scadenza non dichiarata')
    elif item['expireDate'] is not None:
        excluded.append('Contratto con scadenza')
    return excluded, missing


def project(market, receipt, contract, now=None):
    """Verify a single recorded acquisition, then describe every returned symbol."""
    now = now or dt.datetime.now(UTC)
    if market.get('scope') != 'RESEARCH_SIMULATION_ONLY':
        raise ValueError('wrong_scope')
    if market.get('record_hash') != digest({k: v for k, v in market.items() if k != 'record_hash'}):
        raise ValueError('market_hash_mismatch')
    if (receipt.get('url') != SOURCE_URL or receipt.get('status') != 200
            or receipt.get('kind') != 'LIVE_PUBLIC_HTTPS_CAPTURE'):
        raise ValueError('wrong_capture_source')
    capture_id = digest({k: v for k, v in receipt.items() if k != 'capture_id'})
    if receipt.get('capture_id') != capture_id or market['capture_ids'][0] != capture_id:
        raise ValueError('capture_identity_mismatch')
    started, received = timestamp(receipt['started_at']), timestamp(receipt['received_at'])
    if not timestamp(market['observed_at_start']) <= started <= received <= timestamp(market['observed_at_end']) <= now:
        raise ValueError('capture_clock_invalid')
    raw = bytes.fromhex(receipt['raw_hex'])
    if hashlib.sha256(raw).hexdigest() != receipt['raw_sha256']:
        raise ValueError('raw_hash_mismatch')
    body = decode(raw)
    if body.get('code') != '200000' or not isinstance(body.get('data'), list) or not 1 <= len(body['data']) <= 5000:
        raise ValueError('invalid_contract_list')
    universe = contract['universe']
    if len(universe) != 18 or len(set(universe)) != 18 or digest(universe) != contract['universe_hash']:
        raise ValueError('universe_identity_mismatch')
    current = {x['exchange_symbol']: x['symbol'] for x in contract['symbol_mapping_candidates']}
    if len(current) != 18 or set(current.values()) != set(universe):
        raise ValueError('universe_mapping_mismatch')
    rows, seen = [], set()
    for item in body['data']:
        symbol = item.get('symbol')
        if not isinstance(symbol, str) or not re.fullmatch(r'[A-Z0-9_\-]{2,40}', symbol) or symbol in seen:
            raise ValueError('invalid_or_duplicate_symbol')
        seen.add(symbol)
        excluded, missing = _classify(item)
        is_current = symbol in current
        group = 'current' if is_current else 'excluded' if excluded else 'incomplete' if missing else 'candidate'
        reasons = (['Fa già parte dei 18 asset della V13 originale'] if is_current else
                   excluded if excluded else missing if missing else
                   ['Crypto aperta, lineare USDT, senza scadenza dichiarata; da approfondire'])
        opened = _nonnegative(item.get('firstOpenDate'))
        try:
            opening = dt.datetime.fromtimestamp(opened / 1000, UTC) if opened is not None else None
            opening = opening if opening and opening <= received else None
        except (ValueError, OverflowError, OSError):
            opening = None
        rows.append({'symbol': symbol, 'baseline_symbol': current.get(symbol), 'group': group,
                     'reasons': reasons, 'metadata_issues': excluded + missing,
                     'checks_pending': list(MISSING) if group in ('candidate', 'incomplete') else [],
                     'turnover_24h': _nonnegative(item.get('turnoverOf24h')),
                     'turnover_currency': item.get('quoteCurrency'),
                     'first_open_date': opening.date().isoformat() if opening else None,
                     'age_days': (received - opening).days if opening else None,
                     'min_quantity': None, 'min_notional': None})
    # A missing current symbol must remain visible; absence never removes it.
    for symbol in sorted(set(current) - seen):
        rows.append({'symbol': symbol, 'baseline_symbol': current[symbol], 'group': 'current',
                     'reasons': ['Nella V13 originale, assente da questa risposta pubblica'],
                     'metadata_issues': ['Contratto non presente nella cattura'], 'checks_pending': [],
                     'turnover_24h': None, 'turnover_currency': None, 'first_open_date': None,
                     'age_days': None, 'min_quantity': None, 'min_notional': None})
    rows.sort(key=lambda row: row['symbol'])
    age = (now - received).total_seconds()
    return {'available': True, 'view_version': 'v13-universe-observation-v1',
            'as_of': received.isoformat(), 'stale': age > FRESH_SECONDS,
            'age_seconds': int(age), 'capture_id': capture_id, 'raw_sha256': receipt['raw_sha256'],
            'universe_hash': contract['universe_hash'], 'source_url': SOURCE_URL,
            'counts': {g: sum(r['group'] == g for r in rows) for g in ('current', 'candidate', 'excluded', 'incomplete')},
            'rows': rows, 'automatic_selection': False, 'admissibility_assessed': False}


def load_view(root='/v13-paper/research/source', repo='/workspace', now=None):
    root = Path(root)
    market = _read(root / 'market.json', CAPTURE_UID)
    capture_id = market['capture_ids'][0]
    if not isinstance(capture_id, str) or not re.fullmatch(r'[a-f0-9]{64}', capture_id):
        raise ValueError('invalid_capture_path')
    receipt = _read(root / 'raw' / (capture_id + '.json.gz'), CAPTURE_UID)
    path = Path(repo) / 'docs/contracts/v13-original-portfolio-adapter-candidate-v1.json'
    raw = path.read_bytes()
    if hashlib.sha256(raw).hexdigest() != CONTRACT_HASH:
        raise ValueError('baseline_contract_changed')
    return project(market, receipt, decode(raw), now)
