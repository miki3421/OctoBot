import datetime as dt
import hashlib
import json
import os
from pathlib import Path
import tempfile
import unittest
import v13_dynamic_data as d
from octobot.ai_strategy_lab import v13_research_source as source

ROOT=Path(__file__).resolve().parents[3]


class ScienceBridgeTests(unittest.TestCase):
    def make(self,root):
        contract,_=source.p.load_contract(ROOT)
        rawdir=root/'raw';rawdir.mkdir()
        opened=int(dt.datetime(2026,9,30,tzinfo=dt.timezone.utc).timestamp()*1000)
        receipts=[]
        for symbol in contract['universe']:
            raw=json.dumps([[opened,'100','102','99','101','1',opened+86400000-1]]).encode()
            r=dict(kind='LIVE_PUBLIC_HTTPS_CAPTURE',url=f'https://fapi.binance.com/fapi/v1/klines?symbol={symbol}&interval=1d&startTime={opened}&endTime={opened+86400000-1}',started_at='2026-10-01T00:10:00Z',received_at='2026-10-01T00:10:01Z',status=200,raw_hex=raw.hex(),raw_sha256=hashlib.sha256(raw).hexdigest())
            r['capture_id']=source.p.digest(r);p=rawdir/(r['capture_id']+'.json');p.write_bytes(source.p.canonical_bytes(r));p.chmod(0o600);receipts.append(r)
        s=dict(scope=source.SCOPE,lineage=contract['scientific_lineage_ref'],universe=contract['universe'],day='2026-09-30',published_at='2026-10-01T00:11:00Z',requests=receipts)
        s['snapshot_id']=source.p.digest(s);p=root/'snapshot.json';p.write_bytes(source.p.canonical_bytes(s));p.chmod(0o600)
        return p

    def test_bridge_uses_publication_availability(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);p=self.make(root)
            records=d.read_science_day(root,p,ROOT,expected_uid=os.getuid(),day='2026-09-30',as_of='2026-10-08T00:15:00Z')
            self.assertEqual(len(records),18)
            self.assertTrue(all(r['received_at']=='2026-10-01T00:11:00Z' for r in records))
            with self.assertRaises(ValueError):d.read_science_day(root,p,ROOT,expected_uid=os.getuid(),day='2026-09-30',as_of='2026-10-01T00:10:00Z')

    def test_wrong_custodian_or_modified_receipt_denied(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);p=self.make(root)
            with self.assertRaises(ValueError):d.read_science_day(root,p,ROOT,expected_uid=os.getuid()+1,day='2026-09-30',as_of='2026-10-08T00:15:00Z')
            receipt=next((root/'raw').glob('*.json'));r=json.loads(receipt.read_text());r['status']=500;receipt.write_text(json.dumps(r))
            with self.assertRaises(ValueError):d.read_science_day(root,p,ROOT,expected_uid=os.getuid(),day='2026-09-30',as_of='2026-10-08T00:15:00Z')
