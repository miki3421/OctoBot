"""Synthetic receipts exercise the existing validator, not a mocked trust verdict."""
import copy
import gzip
import unittest
import datetime as dt
import numpy as np
import v13_dynamic_data as d
from test_v13_dynamic_universe import fixture,START


class DataTests(unittest.TestCase):
    def row(self):
        slot=d.capture.utc(START)
        end=int(slot//86400*86400*1000)
        raw=d.capture.canonical([[end-86400000,'100','102','99','101','1',end-1]])
        collector=object.__new__(d.capture.Collector)
        r=dict(kind='daily',symbol='BTCUSDT',slot=slot,deadline=slot+60,started=slot,received=slot+1,
               state='valid',status=200,error=None,raw_gzip=gzip.compress(raw),raw_hash=d.capture.sha(raw))
        r['metrics']=d.capture.canonical(collector.validate(r,raw,r['received'],None)).decode()
        return collector,r

    def test_receipt_hash_metrics_and_cutoff(self):
        collector,r=self.row()
        self.assertEqual(d.project(collector,r,None,r['received'])['close'],101.)
        with self.assertRaises(ValueError):d.project(collector,r,None,r['slot'])
        for key,value in [('raw_hash','0'*64),('metrics','{}')]:
            bad=copy.deepcopy(r);bad[key]=value
            with self.assertRaises(ValueError):d.project(collector,bad,None,r['received'])

    def records(self):
        return [dict(bar,symbol=s,kind='daily',scope='VERIFIED_QUALIFICATION_RECEIPT') for s,bars in fixture().items() for bar in bars]

    def test_common_panel_covariance_matches_original(self):
        from octobot.ai_strategy_lab import trend
        result=d.causal_panel(self.records(),START)
        closes=np.asarray(result['closes']);returns=closes[1:]/closes[:-1]-1
        np.testing.assert_array_equal(result['covariance'],trend._rolling_covariance(returns,60)[-1])
        self.assertFalse(result['execution_ready'])

    def test_future_records_do_not_change_panel(self):
        records=self.records();before=d.causal_panel(records,START)
        records.append(dict(records[-1],day='2026-10-19',close=1e9))
        self.assertEqual(before,d.causal_panel(records,START))

    def test_missing_late_conflict(self):
        for kind in ('missing','late','conflict'):
            records=self.records()
            if kind=='missing':records.pop()
            elif kind=='late':records[-1]['received_at']='2026-10-19T00:16:00Z'
            else:records.append(dict(records[-1],close=999))
            with self.assertRaises(ValueError):d.causal_panel(records,START)

    def test_bridge_reports_gap_and_rejects_conflict(self):
        records=self.records();removed=records.pop()
        gap=d.bridge_daily(records,slot=START)
        self.assertFalse(gap['common_warmup_complete'])
        self.assertIn(removed['day'],gap['missing'][removed['symbol']])
        fixed=d.bridge_daily(records,[removed],slot=START)
        self.assertTrue(fixed['common_warmup_complete'])
        with self.assertRaisesRegex(ValueError,'conflicting_daily'):
            d.bridge_daily(records,[removed,dict(removed,close=999.)],slot=START)

    def test_calendar_fixed_weekly(self):
        slots=d.weekly_calendar(START)
        self.assertEqual(len(slots),26)
        self.assertEqual((d.selector.timestamp(slots[-1])-d.selector.timestamp(slots[0])).days,175)
        with self.assertRaises(ValueError):d.weekly_calendar(START,0)


if __name__=='__main__':unittest.main()


class FundingTests(unittest.TestCase):
    def inputs(self):
        at=int(d.selector.timestamp('2026-10-08T08:00:00Z').timestamp()*1000)
        receipts=[dict(scope='VERIFIED_QUALIFICATION_RECEIPT',kind='funding',symbol='BTCUSDT',received_at='2026-10-08T08:05:00Z',events=[dict(at=at,rate=.001)])]
        books=[dict(scope='VERIFIED_QUALIFICATION_RECEIPT',kind='books',symbol='BTCUSDT',at='2026-10-08T07:59:00Z',received_at='2026-10-08T07:59:02Z',bids=[[99,1]],asks=[[101,1]],raw_sha256='a'*64)]
        return receipts,books

    def test_prior_proxy_and_no_false_coverage(self):
        r,b=self.inputs();out=d.estimate_funding(r,b,as_of='2026-10-08T08:10:00Z')
        self.assertEqual(out['events'][0]['mark'],100)
        self.assertFalse(out['coverage_complete']);self.assertIsNone(out['expected_schedule_match'])

    def test_late_or_stale_mark_remains_unknown(self):
        for key,val in [('received_at','2026-10-08T08:00:01Z'),('at','2026-10-08T07:00:00Z')]:
            r,b=self.inputs();b[0][key]=val
            out=d.estimate_funding(r,b,as_of='2026-10-08T08:10:00Z')
            self.assertIsNone(out['events'][0]['mark'])

    def test_dedup_conflict_and_expected_missing(self):
        r,b=self.inputs();out=d.estimate_funding(r+r,b,as_of='2026-10-08T08:10:00Z',expected=[])
        self.assertEqual(len(out['events']),1);self.assertFalse(out['expected_schedule_match'])
        other=copy.deepcopy(r[0]);other['events'][0]['rate']=.002
        with self.assertRaises(ValueError):d.estimate_funding(r+[other],b,as_of='2026-10-08T08:10:00Z')


class FundingCoverageTests(unittest.TestCase):
    def rows(self):
        r,b=FundingTests().inputs()
        r[0].update(window_start='2026-10-08T00:00:00Z',window_end='2026-10-09T00:00:00Z',received_at='2026-10-09T00:10:00Z')
        return r,b

    def assess(self,r,b):
        return d.funding_readiness(r,b,symbols=['BTCUSDT'],start='2026-10-08T00:00:00Z',end='2026-10-09T00:00:00Z',as_of='2026-10-09T00:15:00Z')

    def test_complete_receipts_do_not_certify_settlements(self):
        r,b=self.rows();x=self.assess(r,b)
        self.assertTrue(x['all_daily_receipts_present'])
        self.assertTrue(x['all_observed_marks_estimated'])
        self.assertEqual(x['settlement_coverage'],'UNKNOWN')
        self.assertFalse(x['execution_ready'])

    def test_missing_receipt_and_missing_proxy_are_separate(self):
        r,b=self.rows()
        self.assertEqual(self.assess([],b)['symbols']['BTCUSDT']['missing_receipt_days'],['2026-10-08'])
        x=self.assess(r,[])
        self.assertTrue(x['all_daily_receipts_present'])
        self.assertFalse(x['all_observed_marks_estimated'])

    def test_rate_outside_declared_window_denied(self):
        r,b=self.rows();r[0]['events'][0]['at']-=86400000
        with self.assertRaises(ValueError):self.assess(r,b)

class PrecisionTests(unittest.TestCase):
    def test_decimal_precision_is_not_exchange_minimum(self):
        value=d.precision(dict(tickSize='0.05',lotSize=1,multiplier='0.001',takerFeeRate='0.0006'))
        self.assertEqual(value['price_tick'],'0.05')
        self.assertEqual(value['quantity_increment'],'0.001')
        self.assertIsNone(value['min_quantity'])
        self.assertIsNone(value['min_notional'])

    def test_missing_invalid_precision_denied(self):
        good=dict(tickSize='0.05',lotSize=1,multiplier='0.001',takerFeeRate='0.0006')
        for field in good:
            bad=dict(good);del bad[field]
            with self.assertRaises(ValueError):d.precision(bad)
            for invalid in (True,'NaN','Infinity',-1):
                bad=dict(good);bad[field]=invalid
                with self.assertRaises(ValueError):d.precision(bad)

class BookAdmissionTests(unittest.TestCase):
    def records(self):
        return [dict(kind='books',symbol=s,scope='VERIFIED_QUALIFICATION_RECEIPT',at='2026-10-08T00:16:00Z',received_at='2026-10-08T00:16:01Z',metadata_received_at='2026-10-08T00:00:00Z',raw_sha256='a'*64,metadata_hashes={'kucoin_metadata':'b'*64,'binance_metadata':'c'*64},precision={'price_tick':'0.05','quantity_increment':'0.001','public_taker_fee':'0.0006'},bids=[[99.,1.]],asks=[[101.,1.]]) for s in d.selector.UNIVERSE]
    def check(self, rows):
        return d.admit_books(rows,intent_persisted_at='2026-10-08T00:15:00Z',as_of='2026-10-08T00:16:30Z')
    def test_common_books_and_order_independence(self):
        rows=self.records()
        self.assertEqual(self.check(rows),self.check(list(reversed(rows))))
        self.assertFalse(self.check(rows)['execution_ready'])
        self.assertEqual(len(self.check(rows)['books']),29)
    def test_unavailable_stale_preintent_and_missing_denied(self):
        for field,value in [('received_at','2026-10-08T00:17:00Z'),('at','2026-10-08T00:15:20Z'),('at','2026-10-08T00:15:00Z')]:
            rows=self.records();rows[0][field]=value
            with self.assertRaisesRegex(ValueError,'common_fresh_books_required'):self.check(rows)
        with self.assertRaises(ValueError):self.check(self.records()[:-1])
    def test_provenance_clock_and_conflict_denied(self):
        for field,value in [('raw_sha256',''),('metadata_received_at','2026-10-08T00:16:01Z'),('received_at','2026-10-08T00:15:59Z')]:
            rows=self.records();rows[0][field]=value
            with self.assertRaises(ValueError):self.check(rows)
        rows=self.records();other=dict(rows[0],bids=[[98.,1.]])
        with self.assertRaisesRegex(ValueError,'conflicting_execution_book'):self.check(rows+[other])
