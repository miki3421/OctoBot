"""Explicit pre-T0 implementation continuation preserves primary accounting identity."""
import hashlib
import json
from pathlib import Path
import sys
import tempfile
import time
import unittest

HERE=Path(__file__).parent;sys.path.insert(0,str(HERE))
import test_btc_intraday_paper as fixture
m=fixture.m;ROOT=fixture.ROOT;LAB=fixture.LAB

class ContinuationTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.root=Path(self.temp.name)
        self.activation=dict(account=m.ACCOUNT,scope=m.SCOPE,protocol_sha256=m.receipt.PROTOCOL_SHA,paper_activation_authorized=True,real_orders=False,operational_grants=False,exchange_credentials=False,t0_ns=time.time_ns()+86400*m.NS,code_pins={'old-code':'preserved'})
        self.write('protocol.json',(ROOT/'docs/research-protocols/btc-intraday-m1-l5-paper-candidate-v2.json').read_bytes())
        self.write('activation.json',m.canonical(self.activation))
        snapshot=self.root/'snapshot.sqlite';e=m.Engine(snapshot,self.activation['t0_ns'],m.digest(self.activation),initialize=True);e.close();snapshot.chmod(0o440)
        self.cont=dict(account=m.ACCOUNT,base_activation_sha256=hashlib.sha256((self.root/'activation.json').read_bytes()).hexdigest(),protocol_sha256=m.receipt.PROTOCOL_SHA,recorded_ns=time.time_ns(),scope='PRE_T0_ZERO_FILL_PROTOCOL_CONFORMANCE_FIX',primary_snapshot_sha256=hashlib.sha256(snapshot.read_bytes()).hexdigest(),code_pins={n:hashlib.sha256((LAB/n).read_bytes()).hexdigest() for n in ['btc_intraday_paper.py','btc_intraday_availability.py','btc_intraday_source_qualification.py','btc_intraday_admin.py']})
        self.config=dict(protocol=str(self.root/'protocol.json'),activation=str(self.root/'activation.json'),continuation=str(self.root/'continuation.json'),continuation_snapshot=str(snapshot))
    def write(self,name,raw):
        p=self.root/name;p.write_bytes(raw);p.chmod(0o440)
    def tearDown(self):self.temp.cleanup()
    def check(self):self.write('continuation.json',m.canonical(self.cont));return m.authority(self.config)
    def test_valid_prestart_continuation_keeps_original_identity(self):
        raw,a=self.check();self.assertEqual(m.digest(a),m.digest(self.activation))
        self.assertEqual(a['code_pins'],{'old-code':'preserved'})
    def test_wrong_parent_or_post_t0_receipt_denied(self):
        self.cont['base_activation_sha256']='0'*64
        with self.assertRaisesRegex(ValueError,'continuation_identity'):self.check()
        self.cont['base_activation_sha256']=hashlib.sha256((self.root/'activation.json').read_bytes()).hexdigest();self.cont['recorded_ns']=self.activation['t0_ns']
        with self.assertRaisesRegex(ValueError,'continuation_identity'):self.check()
    def test_snapshot_tampering_detected(self):
        self.cont['primary_snapshot_sha256']='0'*64
        with self.assertRaisesRegex(ValueError,'snapshot_hash'):self.check()
    def test_missing_runtime_pin_is_not_a_waiver(self):
        del self.cont['code_pins']['btc_intraday_paper.py']
        with self.assertRaisesRegex(ValueError,'pin_set'):self.check()

if __name__=='__main__':unittest.main()
