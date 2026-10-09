import tempfile
import unittest
from unittest.mock import patch
from pathlib import Path
import v13_dynamic_coverage as c
import test_v13_dynamic_data as fixtures


class CoverageTests(unittest.TestCase):
    def calendar(self,tmp):
        path=Path(tmp)/'calendar.json'
        settlements={s:[] for s in c.data.selector.UNIVERSE};settlements['BTCUSDT']=['2026-10-08T08:00:00Z']
        value=dict(scope='REVIEWED_EXPLICIT_FUNDING_CALENDAR_V1',evidence_sha256=['a'*64],
                   **{'from':'2026-10-08T00:00:00Z','to':'2026-10-09T00:00:00Z'},settlements=settlements)
        raw=c.data.capture.canonical(value);path.write_bytes(raw)
        return c.CoverageVerifier(path,c.data.capture.sha(raw))

    def test_exact_calendar_missing_rate_and_missing_mark(self):
        with tempfile.TemporaryDirectory() as tmp, patch.object(c.data.capture,'safe_path'):
            # Synthetic calendar in world-writable /tmp; custody is tested separately.
            verifier=self.calendar(tmp);r,b=fixtures.FundingTests().inputs()
            kwargs=dict(previous_at='2026-10-08T07:00:00Z',as_of='2026-10-08T08:10:00Z')
            result=verifier.verify(r,b,**kwargs)
            self.assertTrue(result['interval']['coverage_complete'])
            self.assertEqual(result['interval']['events'][0]['mark'],100)
            with self.assertRaisesRegex(ValueError,'funding_settlement_coverage_gap'):verifier.verify([],b,**kwargs)
            with self.assertRaisesRegex(ValueError,'funding_mark_unresolved'):verifier.verify(r,[],**kwargs)

    def test_pin_window_and_flat_initial_interval(self):
        with tempfile.TemporaryDirectory() as tmp, patch.object(c.data.capture,'safe_path'):
            # Synthetic calendar in world-writable /tmp; custody is tested separately.
            verifier=self.calendar(tmp)
            result=verifier.verify([],[],previous_at=None,as_of='2026-10-08T08:10:00Z')
            self.assertEqual(result['interval']['events'],[])
            with self.assertRaisesRegex(ValueError,'funding_calendar_does_not_cover_interval'):
                verifier.verify([],[],previous_at=None,as_of='2026-10-10T08:10:00Z')
            verifier.path.write_bytes(b'{}')
            with self.assertRaisesRegex(ValueError,'funding_calendar_pin'):verifier.calendar()
