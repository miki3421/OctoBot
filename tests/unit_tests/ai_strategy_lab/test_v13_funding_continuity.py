import tempfile,unittest
from pathlib import Path
import v13_funding_continuity as c
import test_v13_funding_observer as fixture

class ContinuityTests(unittest.TestCase):
    def test_missing_future_and_tampered_samples(self):
        with tempfile.TemporaryDirectory() as tmp:
            p=Path(tmp)/'raw.sqlite';a=c.observer.Archive(p)
            a.capture({'BTCUSDT':'XBTUSDTM'},lambda:4000,lambda url:(200,fixture.ObserverTests().raw()))
            r=c.inspect(p,{'BTCUSDT':'XBTUSDTM'},start=3900,end=4200,as_of=4200)
            self.assertEqual(r['status'],'OBSERVATIONS_COMPLETE');self.assertFalse(r['funding_coverage_certified'])
            self.assertEqual(c.inspect(p,{'BTCUSDT':'XBTUSDTM'},start=3900,end=4500,as_of=4500)['status'],'OBSERVATION_GAPS')
            with self.assertRaises(ValueError):c.inspect(p,{'BTCUSDT':'XBTUSDTM'},start=3900,end=4500,as_of=4400)
            a.db.execute("UPDATE receipts SET raw_sha256='tampered'")
            self.assertEqual(c.inspect(p,{'BTCUSDT':'XBTUSDTM'},start=3900,end=4200,as_of=4200)['verified'],0)
            a.db.execute("UPDATE receipts SET state='invalid'")
            self.assertEqual(c.inspect(p,{'BTCUSDT':'XBTUSDTM'},start=3900,end=4200,as_of=4200)['verified'],0);a.close()
