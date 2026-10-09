"""Author checks for card work-card-18e8d8a5-cae0-4e42-9771-9822e53e87ab.

All contract rows and receipts below are synthetic fixtures, not market evidence.
Run with PYTHONPATH=octobot/ai_strategy_lab python3 -m unittest discover ...
"""
import copy
import datetime as dt
import gzip
import hashlib
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import v13_universe_view as v

REPO = Path(__file__).resolve().parents[3]
CONTRACT_PATH = 'docs/contracts/v13-original-portfolio-adapter-candidate-v1.json'
NOW = dt.datetime(2026, 9, 30, 12, 0, tzinfo=dt.timezone.utc)


def row(symbol='NEWUSDTM', **changes):
    value = dict(symbol=symbol, status='Open', quoteCurrency='USDT', settleCurrency='USDT',
                 isInverse=False, assetClass='CRYPTO', marketStage='NORMAL', expireDate=None,
                 turnoverOf24h=500000, firstOpenDate=1704067200000,
                 lotSize=1, minRiskLimit=10000)
    value.update(changes)
    return value


def fixture(rows):
    raw = json.dumps({'code': '200000', 'data': rows}).encode()
    receipt = dict(kind='LIVE_PUBLIC_HTTPS_CAPTURE', url=v.SOURCE_URL, status=200,
                   started_at='2026-09-30T11:59:00+00:00', received_at='2026-09-30T11:59:01+00:00',
                   raw_hex=raw.hex(), raw_sha256=hashlib.sha256(raw).hexdigest())
    receipt['capture_id'] = v.digest(receipt)
    market = dict(scope='RESEARCH_SIMULATION_ONLY', capture_ids=[receipt['capture_id']],
                  observed_at_start='2026-09-30T11:59:00+00:00', observed_at_end='2026-09-30T11:59:02+00:00')
    market['record_hash'] = v.digest(market)
    return market, receipt


def resign(market, receipt):
    receipt.pop('capture_id', None); receipt['capture_id'] = v.digest(receipt)
    market['capture_ids'] = [receipt['capture_id']]
    market.pop('record_hash', None); market['record_hash'] = v.digest(market)


class UniverseTests(unittest.TestCase):
    def setUp(self):
        self.contract = json.loads((REPO / CONTRACT_PATH).read_text())
        self.market, self.receipt = fixture([row('XBTUSDTM'), row()])

    def project(self, now=NOW):
        return v.project(self.market, self.receipt, self.contract, now)

    def test_scope_and_baseline_preserved_with_absent_current_symbols(self):
        original = copy.deepcopy(self.contract)
        result = self.project()
        self.assertEqual(result['counts'], dict(current=18, candidate=1, excluded=0, incomplete=0))
        self.assertEqual(original, self.contract)
        self.assertFalse(result['automatic_selection'])
        self.assertFalse(result['admissibility_assessed'])
        missing = next(x for x in result['rows'] if x['symbol'] == 'ETHUSDTM')
        self.assertIn('assente', missing['reasons'][0])
        self.assertIsNone(missing['turnover_24h'])

    def test_wrong_contracts_and_missing_metadata_have_distinct_reasons(self):
        absent = row('MISSUSDTM'); del absent['expireDate']
        rows = [row('STOCKUSDTM', assetClass='STOCK'), row('COINUSD', isInverse=True, settleCurrency='BTC'),
                row('FUTUREUSDTM', expireDate=1798185600000), row('PREUSDTM', marketStage='PRE_MARKET'),
                row('CLOSEDUSDTM', status='Closed'), absent, row('NULLUSDTM', assetClass=None)]
        self.market, self.receipt = fixture(rows)
        result = self.project()
        self.assertEqual(result['counts']['excluded'], 5)
        self.assertEqual(result['counts']['incomplete'], 2)
        self.assertEqual(result['counts']['candidate'], 0)
        self.assertTrue(all(r['reasons'] for r in result['rows']))

    def test_missing_metrics_remain_unknown_and_minimums_are_not_inferred(self):
        self.market, self.receipt = fixture([row(turnoverOf24h=None, firstOpenDate=None,
                                               min_quantity=0, min_notional=1)])
        r = next(r for r in self.project()['rows'] if r['group'] == 'candidate')
        for field in ('turnover_24h', 'first_open_date', 'age_days', 'min_quantity', 'min_notional'):
            self.assertIsNone(r[field])
        self.assertEqual(len(r['checks_pending']), 4)

    def test_zero_activity_is_distinct_from_missing(self):
        self.market, self.receipt = fixture([row(turnoverOf24h=0)])
        self.assertEqual(next(r for r in self.project()['rows'] if r['group'] == 'candidate')['turnover_24h'], 0)

    def test_bad_opening_date_is_not_history(self):
        for value in (1e300, True, -1, '2020-01-01', 9999999999999):
            with self.subTest(value=value):
                self.market, self.receipt = fixture([row(firstOpenDate=value)])
                r = next(r for r in self.project()['rows'] if r['group'] == 'candidate')
                self.assertIsNone(r['first_open_date'])

    def test_stale_is_explicit_and_future_capture_rejected(self):
        self.assertFalse(self.project()['stale'])
        self.assertTrue(self.project(NOW + dt.timedelta(hours=1))['stale'])
        with self.assertRaisesRegex(ValueError, 'clock'):
            self.project(NOW - dt.timedelta(hours=1))

    def test_market_tampering(self):
        self.market['observed_at_end'] = NOW.isoformat()
        with self.assertRaisesRegex(ValueError, 'market_hash'):
            self.project()

    def test_receipt_tampering(self):
        self.receipt['raw_hex'] += '20'
        with self.assertRaisesRegex(ValueError, 'capture_identity'):
            self.project()

    def test_raw_tampering_even_if_envelope_rehashed(self):
        self.receipt['raw_hex'] += '20'; resign(self.market, self.receipt)
        with self.assertRaisesRegex(ValueError, 'raw_hash'):
            self.project()

    def test_wrong_url_http_or_kind(self):
        for field, value in [('url', 'https://example.com/contracts'), ('status', 500), ('kind', 'FIXTURE')]:
            with self.subTest(field=field):
                self.market, self.receipt = fixture([row()]); self.receipt[field] = value
                resign(self.market, self.receipt)
                with self.assertRaisesRegex(ValueError, 'wrong_capture_source'):
                    self.project()

    def test_duplicate_and_unsafe_symbol_rejected(self):
        for rows in ([row(), row()], [row('<script>')]):
            self.market, self.receipt = fixture(rows)
            with self.assertRaisesRegex(ValueError, 'symbol'):
                self.project()

    def test_partial_custody_chain_rejected(self):
        self.market['capture_ids'] = ['0' * 64]
        self.market['record_hash'] = v.digest({k: val for k, val in self.market.items() if k != 'record_hash'})
        with self.assertRaisesRegex(ValueError, 'capture_identity'):
            self.project()

    def test_non_boolean_inverse_is_unknown(self):
        self.market, self.receipt = fixture([row(isInverse=0)])
        self.assertEqual(self.project()['counts']['incomplete'], 1)

    def test_duplicate_keys_and_nonfinite_json_rejected(self):
        for raw in [b'{"a":1,"a":2}', b'{"a":NaN}', b'{"a":1e999}']:
            with self.assertRaises(ValueError):
                v.decode(raw)

    def test_universe_tamper_rejected(self):
        self.contract['universe'][0] = 'NEWUSDT'
        with self.assertRaisesRegex(ValueError, 'universe_identity'):
            self.project()

    def test_loader_read_only_and_custody_checks(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp); (root / 'raw').mkdir()
            market_path = root / 'market.json'; market_path.write_text(json.dumps(self.market))
            receipt_path = root / 'raw' / (self.receipt['capture_id'] + '.json.gz')
            receipt_path.write_bytes(gzip.compress(json.dumps(self.receipt).encode()))
            before = {p: p.read_bytes() for p in (market_path, receipt_path)}
            with patch.object(v, 'CAPTURE_UID', os.getuid()):
                self.assertTrue(v.load_view(root, REPO, NOW)['available'])
                self.assertEqual(before, {p: p.read_bytes() for p in before})
                market_path.chmod(0o666)
                with self.assertRaisesRegex(ValueError, 'file_owner'):
                    v.load_view(root, REPO, NOW)
                market_path.chmod(0o600)
                with patch.object(v, 'CONTRACT_HASH', '0' * 64):
                    with self.assertRaisesRegex(ValueError, 'baseline_contract_changed'):
                        v.load_view(root, REPO, NOW)
            with patch.object(v, 'CAPTURE_UID', os.getuid() + 1):
                with self.assertRaisesRegex(ValueError, 'file_owner'):
                    v.load_view(root, REPO, NOW)

    def test_loader_rejects_traversal_and_corrupt_gzip(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp); (root / 'raw').mkdir()
            self.market['capture_ids'] = ['../../outside']
            (root / 'market.json').write_text(json.dumps(self.market))
            with patch.object(v, 'CAPTURE_UID', os.getuid()):
                with self.assertRaisesRegex(ValueError, 'capture_path'):
                    v.load_view(root, REPO, NOW)
                bad = root / 'bad.gz'; bad.write_bytes(b'not gzip')
                with self.assertRaises((ValueError, OSError)):
                    v._read(bad, os.getuid())


if __name__ == '__main__':
    unittest.main()
