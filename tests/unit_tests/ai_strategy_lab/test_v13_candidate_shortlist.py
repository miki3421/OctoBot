"""Offline synthetic tests; no exchange admissibility assertion or network."""
import copy
import datetime as dt
import json
from pathlib import Path
import tempfile
import shutil
import unittest
from unittest.mock import patch

import v13_candidate_shortlist as s
import v13_candidate_data as d

UTC=dt.timezone.utc


def candidate(symbol='TESTUSDTM', activity=6000000, age=400):
    return dict(symbol=symbol,group='candidate',age_days=age,turnover_24h=activity,turnover_currency='USDT')


def sample(day, rows):
    return dict(available=True,as_of='2026-09-'+str(day)+'T12:00:00+00:00',universe_hash='f'*64,
                capture_id=str(day)*32,raw_sha256='a'*64,rows=rows)


class ShortlistTests(unittest.TestCase):
    def build(self, rows1, rows2=None):
        return s.build([sample(28,rows1),sample(29,rows2 if rows2 is not None else rows1)],
                       dt.datetime(2026,9,30,tzinfo=UTC),'0'*64)

    def test_limit_ranking_and_ties(self):
        rows=[candidate('COIN%02dUSDTM'%i,6000000+i) for i in range(20)]
        result=self.build(rows)
        self.assertEqual(result['counts'],dict(examined=20,eligible=20,selected=12))
        self.assertEqual(result['rows'][0]['symbol'],'COIN19USDTM')
        self.assertFalse(result['paper_orders_authorized'])
        tied=self.build([candidate('ZUSDTM'),candidate('AUSDTM')])
        self.assertEqual(tied['rows'][0]['symbol'],'AUSDTM')

    def test_no_fill_to_limit_when_insufficient(self):
        result=self.build([candidate(age=364),candidate('OKUSDTM')])
        self.assertEqual(result['counts']['selected'],1)

    def test_thresholds_apply_to_every_date(self):
        result=self.build([candidate(activity=4900000)],[candidate(activity=50000000)])
        self.assertFalse(result['rows'][0]['selected'])
        self.assertEqual(result['rows'][0]['minimum_turnover_usdt'],4900000)

    def test_missing_is_unknown_not_zero(self):
        result=self.build([candidate(activity=None)])
        self.assertIsNone(result['rows'][0]['median_turnover_usdt'])
        self.assertFalse(result['rows'][0]['eligible'])
        result=self.build([], [candidate()])
        self.assertFalse(result['rows'][0]['eligible'])

    def test_changed_class_or_quote_is_not_eligible(self):
        row=candidate();row['group']='excluded'
        self.assertFalse(self.build([row],[candidate()])['rows'][0]['eligible'])
        row=candidate();row['turnover_currency']='USD'
        self.assertFalse(self.build([row],[candidate()])['rows'][0]['eligible'])

    def test_one_day_duplicate_dates_and_future_rejected(self):
        one=sample(28,[candidate()])
        for samples in ([one],[one,one],[one,sample(30,[candidate()])]):
            with self.assertRaises(ValueError):s.build(samples,dt.datetime(2026,9,29,tzinfo=UTC),'0'*64)

    def test_baseline_not_in_pool(self):
        row=candidate();row['group']='current'
        self.assertEqual(self.build([row])['counts']['examined'],0)


class MeasurementTests(unittest.TestCase):
    def setUp(self):
        self.end=int(dt.datetime(2026,9,30,tzinfo=UTC).timestamp()*1000)
        self.start=self.end-366*d.DAY
        self.rows=[[day,'1','2','0.5',str(100+i),'1',day+d.DAY-1] for i,day in enumerate(range(self.start,self.end,d.DAY))]

    def test_contiguous_returns_and_no_gap_fill(self):
        values=d.candles(self.rows,self.start,self.end)
        self.assertEqual(len(d.returns(values,self.end)),180)
        del values[self.end-20*d.DAY]
        self.assertIsNone(d.returns(values,self.end))

    def test_daily_duplicates_order_future_open_bar_and_nonfinite_rejected(self):
        for rows in [self.rows+self.rows[-1:],list(reversed(self.rows)),self.rows+[[self.end,'1','2','1','2','1',self.end+d.DAY-1]]]:
            with self.assertRaises(ValueError):d.candles(rows,self.start,self.end)
        for value in ('nan','inf','0','-1'):
            rows=copy.deepcopy(self.rows);rows[0][4]=value
            with self.assertRaises(ValueError):d.candles(rows,self.start,self.end)

    def test_missing_daily_is_countable_but_not_interpolated(self):
        values=d.candles(self.rows[1:],self.start,self.end)
        self.assertEqual(len(values),365)
        self.assertEqual(len(d.returns(values,self.end)),180)

    def test_correlation_sign_zero_variance_and_sample_size(self):
        a=[float(i) for i in range(180)]
        self.assertAlmostEqual(d.pearson(a,a),1)
        self.assertAlmostEqual(d.pearson(a,[-x for x in a]),-1)
        self.assertIsNone(d.pearson(a,[1.0]*180))
        self.assertIsNone(d.pearson(a,a[:-1]))

    def test_mapping_never_infers_token_multiplier(self):
        k={'baseCurrency':'PEPE'};b=dict(symbol='1000PEPEUSDT',baseAsset='1000PEPE',quoteAsset='USDT',marginAsset='USDT',contractType='PERPETUAL',status='TRADING')
        self.assertIsNone(d.mapping(k,[b]))
        b.update(symbol='PEPEUSDT',baseAsset='PEPE')
        self.assertEqual(d.mapping(k,[b]),'PEPEUSDT')
        b['status']='SETTLING';self.assertIsNone(d.mapping(k,[b]))

    def test_book_units_and_spread(self):
        book={'code':'200000','data':{'ts':self.end*1000000,'bids':[[99,2],[98,3]],'asks':[[101,4],[102,5]]}}
        result=d.book_metrics(book,{'multiplier':0.01},dt.datetime.fromtimestamp(self.end/1000+1,UTC).isoformat())
        self.assertAlmostEqual(result['spread_bps'],200)
        self.assertAlmostEqual(result['bid_depth_usdt'],4.92)
        for change in ('cross','order','stale','future'):
            b=copy.deepcopy(book);received=self.end/1000+1
            if change=='cross':b['data']['asks'][0][0]=99
            if change=='order':b['data']['bids'].reverse()
            if change=='stale':received+=65
            if change=='future':received-=5
            with self.assertRaises(ValueError):d.book_metrics(b,{'multiplier':0.01},dt.datetime.fromtimestamp(received,UTC).isoformat())

    def test_acquisition_has_no_redirect_or_arbitrary_host(self):
        with self.assertRaises(ValueError):d.acquire('https://example.com/',Path('/nonexistent'),[])
        with self.assertRaises(ValueError):d.NoRedirect().redirect_request(None,None,302,'',{},'https://example.com')

    def test_changed_shortlist_cannot_expand_download_scope(self):
        with tempfile.TemporaryDirectory() as tmp, patch.object(d.shortlist,'load_public',return_value={'report_sha256':'0'*64}), patch.object(d,'acquire') as fetch:
            with self.assertRaisesRegex(ValueError,'outside_authorized_shortlist'):
                d.collect('.',Path(tmp)/'output',fetch=fetch)
            fetch.assert_not_called()

    def test_public_reports_bound_to_shortlist_and_measurement_plan(self):
        repo=Path(__file__).resolve().parents[3]
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp)
            for name in (s.PROTOCOL,s.REPORT,d.PLAN,d.REPORT):
                p=root/name;p.parent.mkdir(parents=True,exist_ok=True);shutil.copyfile(repo/name,p)
            result=d.load_public(root);self.assertTrue(result['available']);self.assertNotIn('receipts',result)
            (root/d.PLAN).write_text('Changed plan')
            with self.assertRaisesRegex(ValueError,'binding'):d.load_public(root)

    def test_public_report_tamper_rejected(self):
        repo=Path(__file__).resolve().parents[3]
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);p=root/d.REPORT;p.parent.mkdir(parents=True)
            report=json.loads((repo/d.REPORT).read_text());report['report']['rows'][0]['daily_count']=0
            p.write_text(json.dumps(report))
            with self.assertRaisesRegex(ValueError,'report_changed'):d.load_public(root)


if __name__=='__main__':unittest.main()
