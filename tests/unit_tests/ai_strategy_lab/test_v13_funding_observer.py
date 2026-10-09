import json,tempfile,unittest
from pathlib import Path
import v13_funding_observer as o

class ObserverTests(unittest.TestCase):
    def raw(self):return json.dumps(dict(code='200000',data=dict(symbol='.XBTUSDTMFPI8H',granularity=3600000,timePoint=3600000,fundingTime=7200000,value=.001,fundingRateCap=.01,fundingRateFloor=-.01))).encode()
    def test_restart_keeps_raw_and_never_repeats_slot(self):
        with tempfile.TemporaryDirectory() as tmp:
            path=Path(tmp)/'raw.sqlite';a=o.Archive(path);calls=[]
            def get(url):calls.append(url);return 200,self.raw()
            self.assertEqual(a.capture({'BTCUSDT':'XBTUSDTM'},lambda:4000,get)['valid'],1);a.close()
            a=o.Archive(path);self.assertEqual(a.capture({'BTCUSDT':'XBTUSDTM'},lambda:4001,get)['captured'],0)
            self.assertEqual(len(calls),1);self.assertEqual(a.db.execute('PRAGMA integrity_check').fetchone()[0],'ok');a.close()
    def test_rate_limit_persists_halt(self):
        with tempfile.TemporaryDirectory() as tmp:
            path=Path(tmp)/'raw.sqlite';a=o.Archive(path)
            a.capture({'BTCUSDT':'XBTUSDTM'},lambda:4000,lambda url:(429,b'limited'));a.close();a=o.Archive(path)
            with self.assertRaisesRegex(ValueError,'operator_review_required'):a.capture({},lambda:4300)
            a.close()
    def test_bad_identity_and_inconsistent_schedule_preserved_invalid(self):
        with tempfile.TemporaryDirectory() as tmp:
            a=o.Archive(Path(tmp)/'raw.sqlite');r=json.loads(self.raw());r['data']['fundingTime']=8000000
            self.assertEqual(a.capture({'BTCUSDT':'XBTUSDTM'},lambda:4000,lambda url:(200,json.dumps(r).encode()))['valid'],0)
            with self.assertRaises(ValueError):o.validate(self.raw(),'ETHUSDTM',4000,4000)
            self.assertEqual(a.db.execute('SELECT count(*) FROM receipts').fetchone()[0],1);a.close()
