import copy
import json
import tempfile
import unittest
from pathlib import Path
from urllib.parse import urlencode
import v13_funding_history_review as r


class HistoryReviewTests(unittest.TestCase):
    def fixture(self, root, events):
        # Explicit synthetic funding boundary, no real exchange-admissibility claim.
        observation=dict(start=300,end=1200,status='OBSERVATIONS_COMPLETE',symbols={
            'BTCUSDT':dict(announced_events_due=[900000],transitions=[])})
        raw=r.capture.canonical(dict(code='200000',data=events))
        item=dict(url='https://api-futures.kucoin.com/api/v1/contract/funding-rates?'+urlencode(
            dict(symbol='XBTUSDTM',**{'from':300000,'to':1200000})),
            status=200,started_at='1970-01-01T00:21:00Z',received_at='1970-01-01T00:21:01Z',raw_sha256=r.capture.sha(raw))
        item['receipt_id']=r.capture.sha(r.capture.canonical(item))
        (root/'raw').mkdir();(root/'raw'/(item['receipt_id']+'.raw')).write_bytes(raw)
        report=dict(scope='PUBLIC_FUNDING_HISTORY_REVIEW',receipts=[item])
        (root/'report.json').write_bytes(r.capture.canonical(dict(report=report,report_sha256=r.capture.sha(r.capture.canonical(report)))))
        return observation

    def run_review(self, root, observations):
        return r.reconcile(observations,root,{'BTCUSDT':'XBTUSDTM'},as_of=1300)

    def test_match_never_certifies_calendar(self):
        with tempfile.TemporaryDirectory() as tmp:
            p=Path(tmp);o=self.fixture(p,[dict(timepoint=900000,fundingRate=.001)])
            result=self.run_review(p,o)
            self.assertEqual(result['status'],'MATCHED_OBSERVED_ANNOUNCEMENTS_NOT_CERTIFIED')
            self.assertFalse(result['funding_coverage_certified']);self.assertFalse(result['execution_ready'])
            o['status']='OBSERVATION_GAPS'
            self.assertEqual(self.run_review(p,o)['status'],'REVIEW_REQUIRED')

    def test_missing_and_null_never_mean_zero(self):
        for values in ([],None):
            with tempfile.TemporaryDirectory() as tmp:
                p=Path(tmp);o=self.fixture(p,values);result=self.run_review(p,o)
                self.assertEqual(result['status'],'REVIEW_REQUIRED')
                self.assertEqual(result['symbols']['BTCUSDT']['missing'],[900000])
                if values is None:self.assertIsNone(result['symbols']['BTCUSDT']['observed_settlements'])

    def test_unannounced_and_duplicate_events(self):
        for values in ([dict(timepoint=1000000,fundingRate=.001)],
                       [dict(timepoint=900000,fundingRate=.001)]*2):
            with tempfile.TemporaryDirectory() as tmp:
                p=Path(tmp);o=self.fixture(p,values)
                if len(values)==2:
                    with self.assertRaisesRegex(ValueError,'history_event_time'):self.run_review(p,o)
                else:self.assertEqual(self.run_review(p,o)['status'],'REVIEW_REQUIRED')

    def test_tamper_future_and_discontinuous_window(self):
        with tempfile.TemporaryDirectory() as tmp:
            p=Path(tmp);o=self.fixture(p,[dict(timepoint=900000,fundingRate=.001)])
            with self.assertRaisesRegex(ValueError,'history_time_or_status'):
                r.reconcile(o,p,{'BTCUSDT':'XBTUSDTM'},as_of=1201)
            o['symbols']['BTCUSDT']['transitions']=[dict(interval_changed=True,contiguous_boundary=False)]
            self.assertEqual(self.run_review(p,o)['status'],'REVIEW_REQUIRED')
            next((p/'raw').iterdir()).write_text('{}')
            with self.assertRaisesRegex(ValueError,'history_raw_hash'):self.run_review(p,o)
