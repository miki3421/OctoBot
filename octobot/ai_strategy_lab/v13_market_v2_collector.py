"""Forward-only V13 schema-2 enrichment of a fresh public KuCoin observation.

Runs in the collector trust domain, never in the paper executor or strategy.
The legacy schema-1 journal and its hashes are read-only inputs.
"""
from __future__ import annotations

import argparse
import copy
import datetime as dt
from decimal import Decimal, InvalidOperation
import fcntl
import json
import hashlib
import os
import pathlib
import urllib.request

from octobot.ai_strategy_lab import v13_market
from octobot.ai_strategy_lab.microstructure import _record_hash

CONTRACT_ENDPOINT = 'https://api-futures.kucoin.com/api/v1/contracts/XBTUSDTM'
MARK_ENDPOINT = 'https://api-futures.kucoin.com/api/v1/mark-price/XBTUSDTM/current'
UTC = dt.timezone.utc


def _positive(value, field):
    try:
        number = Decimal(str(value))
    except (TypeError, InvalidOperation) as exc:
        raise ValueError(f'invalid {field}') from exc
    if not number.is_finite() or number <= 0:
        raise ValueError(f'invalid {field}')
    return number


def enrich(legacy, response, mark_response, *, contract_started_at, contract_received_at,
           mark_started_at, mark_received_at):
    """Join distinct public observations at their actual availability times."""
    observed_at = max(contract_received_at, mark_received_at)
    if legacy.get('schema_version') != 1:
        raise ValueError('expected_legacy_schema_v1')
    v13_market._validate_record(legacy, observed_at, v13_market.MAX_QUOTE_AGE_SECONDS)
    if not isinstance(response, dict) or response.get('code') != '200000' or not isinstance(response.get('data'), dict):
        raise ValueError('contract_response_invalid')
    contract = response['data']
    if not isinstance(mark_response, dict) or mark_response.get('code') != '200000' or not isinstance(mark_response.get('data'), dict):
        raise ValueError('mark_response_invalid')
    mark = mark_response['data']
    if mark.get('symbol') != 'XBTUSDTM' or mark.get('granularity') != 1000:
        raise ValueError('mark_identity_invalid')
    published_ms = v13_market._millis(mark.get('timePoint'), 'mark timePoint')
    mark_at = dt.datetime.fromtimestamp(published_ms / 1000, UTC)
    if (mark_started_at > mark_received_at or contract_started_at > contract_received_at
        or mark_at > mark_received_at or mark_received_at > contract_started_at):
        raise ValueError('market_observation_causality_invalid')
    if (observed_at-mark_at).total_seconds() > v13_market.MAX_QUOTE_AGE_SECONDS:
        raise ValueError('stale_mark')
    if contract.get('symbol') != 'XBTUSDTM' or contract.get('status') != 'Open' or contract.get('settleCurrency') != 'USDT' or contract.get('isInverse') is not False:
        raise ValueError('contract_identity_invalid')
    multiplier = _positive(contract.get('multiplier'), 'multiplier')
    lot = _positive(contract.get('lotSize'), 'lotSize')
    tick = _positive(contract.get('tickSize'), 'tickSize')
    base_step = lot * multiplier  # lotSize is CONTRACTS, multiplier BASE/CONTRACT.
    record = copy.deepcopy(legacy)
    record['schema_version'] = 2
    record['observed_at_end'] = observed_at.isoformat()
    record['source_schema_v1_hash'] = legacy['record_hash']
    record['metadata_endpoint'] = CONTRACT_ENDPOINT
    record['contract_request_started_at'] = contract_started_at.isoformat()
    record['mark_request_started_at'] = mark_started_at.isoformat()
    record['mark_received_at'] = mark_received_at.isoformat()
    record['mark_endpoint'] = MARK_ENDPOINT
    future = record['symbols'].get('BTC')
    if not isinstance(future, dict) or future.get('futures_remote_symbol') != 'XBTUSDTM':
        raise ValueError('legacy_symbol_mismatch')
    record['symbols'] = {'BTC': future}
    record['symbol_count'] = 1
    f = future['futures']
    if Decimal(str(f.get('contract_multiplier'))) != multiplier:
        raise ValueError('contract_multiplier_changed_since_book')
    f['raw_contract_metadata'] = copy.deepcopy(contract)
    f['metadata_source_endpoint'] = CONTRACT_ENDPOINT
    f['metadata_observed_at'] = contract_received_at.isoformat()
    record['metadata_observed_at'] = contract_received_at.isoformat()
    f['contract_metadata_sha256'] = hashlib.sha256(json.dumps(contract,sort_keys=True,separators=(',',':'),allow_nan=False).encode()).hexdigest()
    f['contract_multiplier'] = float(multiplier)
    f['contract_lot_size'] = float(lot)
    f['quantity_step'] = float(base_step)
    # lotSize specifies a size increment, not an independently documented order minimum.
    f['min_quantity'] = None
    f['price_tick'] = float(tick)
    f['mark_price'] = float(_positive(mark.get('value'), 'mark value'))
    f['min_notional'] = None
    f['raw_mark'] = copy.deepcopy(mark)
    f['mark_sha256'] = hashlib.sha256(json.dumps(mark,sort_keys=True,separators=(',',':'),allow_nan=False).encode()).hexdigest()
    f['mark_source_endpoint'] = MARK_ENDPOINT
    f['mark_timestamp'] = mark_at.isoformat()
    f['mark_timestamp_source'] = 'kucoin_timePoint_ms'
    f['mark_received_at'] = mark_received_at.isoformat()
    record['record_hash'] = _record_hash(record)
    v13_market._validate_record(record, observed_at, v13_market.MAX_QUOTE_AGE_SECONDS)
    return record


def fetch_public_contract(timeout=10):
    request = urllib.request.Request(CONTRACT_ENDPOINT, headers={'User-Agent':'v13-paper-market-observer/2'})
    with urllib.request.urlopen(request, timeout=timeout) as response:
        if response.status != 200:
            raise ValueError('contract_http_status')
        return json.load(response)


def fetch_public_mark(timeout=10):
    request = urllib.request.Request(MARK_ENDPOINT, headers={'User-Agent':'v13-paper-market-observer/2'})
    with urllib.request.urlopen(request, timeout=timeout) as response:
        if response.status != 200:
            raise ValueError('mark_http_status')
        return json.load(response)


def append_new_record(legacy_journal, v2_journal, *, clock=None,
                      fetch_contract=fetch_public_contract, fetch_mark=fetch_public_mark):
    clock = clock or (lambda: dt.datetime.now(UTC))
    legacy = v13_market.load_latest_market(legacy_journal, clock())
    mark_started = clock()
    mark = fetch_mark()
    mark_received = clock()
    contract_started = clock()
    contract = fetch_contract()
    contract_received = clock()
    record = enrich(legacy, contract, mark, contract_started_at=contract_started,
                    contract_received_at=contract_received, mark_started_at=mark_started,
                    mark_received_at=mark_received)
    path = pathlib.Path(v2_journal)
    path.parent.mkdir(parents=True, exist_ok=True)
    fd = os.open(path, os.O_RDWR|os.O_APPEND|os.O_CREAT|os.O_NOFOLLOW, 0o640)
    try:
        fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        size = os.lseek(fd, 0, os.SEEK_END)
        previous = None
        if size:
            if size > 4*1024*1024:
                raise ValueError('schema-2 journal exceeds bounded collector scan')
            os.lseek(fd, 0, os.SEEK_SET)
            data = os.read(fd, size)
            if not data.endswith(b'\n'):
                raise ValueError('partial schema-2 journal tail')
            previous = json.loads(data.splitlines()[-1])
            v13_market._verify_hash(previous)
            if previous.get('schema_version') != 2:
                raise ValueError('mixed schema-2 journal')
            previous = previous['record_hash']
        record['previous_record_hash'] = previous
        record['record_hash'] = _record_hash(record)
        line = (json.dumps(record, sort_keys=True, separators=(',', ':'), allow_nan=False)+'\n').encode()
        os.write(fd, line)
        os.fsync(fd)
    finally:
        os.close(fd)
    return record


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--legacy-journal',required=True,type=pathlib.Path)
    p.add_argument('--v2-journal',required=True,type=pathlib.Path)
    args = p.parse_args()
    print(append_new_record(args.legacy_journal,args.v2_journal)['record_hash'])


if __name__ == '__main__':
    main()
