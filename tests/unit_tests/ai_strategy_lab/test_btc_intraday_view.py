"""Bounded read-only UI projection contract; synthetic examples only."""
import importlib.util
import json
from pathlib import Path
import tempfile
import unittest

ROOT=Path(__file__).resolve().parents[3]
spec=importlib.util.spec_from_file_location('view',ROOT/'octobot/ai_strategy_lab/btc_intraday_view.py');v=importlib.util.module_from_spec(spec);spec.loader.exec_module(v)

class ViewTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.path=Path(self.temp.name)/'account.json'
        self.value=dict(schema=1,account='btc-intraday-m1-l5-paper-v1',scope='SYNTHETIC_RESEARCH_PAPER_NOT_KUCOIN_ORDER_ADMISSIBILITY',no_real_orders=True,checked_at_ns=1000000000)
    def tearDown(self):self.temp.cleanup()
    def write(self):self.path.write_text(json.dumps(self.value))
    def test_fresh_and_stale_are_explicit(self):
        self.write();self.assertFalse(v.public(self.path,2000000000)['stale']);self.assertTrue(v.public(self.path,32000000000)['stale'])
    def test_wrong_account_scope_and_future_rejected(self):
        self.write()
        with self.assertRaisesRegex(ValueError,'future'):v.public(self.path,0)
        self.value['account']='v13-paper-v2';self.write()
        with self.assertRaisesRegex(ValueError,'scope'):v.public(self.path,2000000000)
    def test_duplicate_nonfinite_and_oversize_rejected(self):
        self.path.write_text('{"schema":1,"schema":1}')
        with self.assertRaisesRegex(ValueError,'duplicate'):v.public(self.path)
        self.value['number']=float('nan');self.write()
        with self.assertRaises(ValueError):v.public(self.path)
        self.path.write_text('x'*(2*1024*1024+1))
        with self.assertRaisesRegex(ValueError,'file'):v.public(self.path)

if __name__=='__main__':unittest.main()
