import copy
import unittest
import v13_dynamic_preview as preview
import v13_dynamic_runner as runner
from test_v13_dynamic_universe import fixture, START


def receipts():
    return [dict(b,symbol=s,kind='daily',scope='VERIFIED_QUALIFICATION_RECEIPT',raw_sha256='a'*64)
            for s,rows in fixture().items() for b in rows]


def run(records, **kwargs):
    return preview.preview(records,slot=START,start=START,lineage='test-preview',as_of=START,**kwargs)


class PreviewTests(unittest.TestCase):
    def test_shared_derivation_parity_and_no_execution_authority(self):
        result=run(receipts())
        expected=runner.derive(fixture(),slot=START,start=START,lineage='test-preview')
        self.assertEqual(result['derived'],expected)
        self.assertFalse(result['execution_ready'])
        self.assertFalse(result['paper_orders_authorized'])
        with self.assertRaisesRegex(ValueError,'synthetic_runner_only'):
            runner.run_tick(None,result)

    def test_late_recovery_cannot_retroactively_complete_slot(self):
        records=receipts()
        records[0]['received_at']='2026-10-19T10:00:00Z'
        with self.assertRaisesRegex(ValueError,'common_warmup_incomplete'):
            run(records)

    def test_future_and_duplicate_receipts_do_not_change_decision(self):
        records=receipts();expected=run(records)
        late=copy.deepcopy(records[0]);late.update(close=999999,received_at='2026-10-20T00:00:00Z',raw_sha256='b'*64)
        self.assertEqual(run(list(reversed(records))+[records[0],late]),expected)
        altered=copy.deepcopy(records[0]);altered['close']*=2
        with self.assertRaisesRegex(ValueError,'conflicting_close'):
            run(records+[altered])

    def test_bad_custody_fields_and_future_slot_denied(self):
        for key,value in [('scope','SYNTHETIC_ONLY'),('raw_sha256',''),('received_at','2020-01-01T00:00:00Z')]:
            records=receipts();records[0][key]=value
            with self.assertRaises(ValueError):run(records)
        with self.assertRaisesRegex(ValueError,'future_decision_slot'):
            preview.preview(receipts(),slot=START,start=START,lineage='test',as_of='2026-10-18T00:00:00Z')
