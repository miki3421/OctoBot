"""Economic cash-flow checks for the offline evaluator, independent of alpha."""
import copy
import gzip
import importlib.util
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

ROOT=Path(__file__).resolve().parents[3]
spec=importlib.util.spec_from_file_location('broader',ROOT/'scripts/qualify_m1_short_broader.py')
b=importlib.util.module_from_spec(spec);spec.loader.exec_module(b)
P=json.loads((ROOT/'docs/research-protocols/m1-short-risk-exits-candidate-v1.json').read_text())


def quote(price=100.,quantity=1000.):
    return dict(mark_price=price,quantity_step=.5,fee_rate=.0006,
                bids=[dict(price=price,base_quantity=quantity)],asks=[dict(price=price,base_quantity=quantity)],
                funding=[dict(timestamp_ms=0,rate=.001)],funding_interval_ms=28800000)


def row(at=400.,price=100.,quantity=1000.):
    return dict(observed_at_start=b.iso(at-2),observed_at_end=b.iso(at),
                quotes={'BTCUSDT':quote(price,quantity)})


def state():
    return dict(positions={'BTCUSDT':dict(quantity=-2.,entry_price=100.,funding=0.)},
                quantity_history={'BTCUSDT':[(100.,-2.)]},funding_cursor=100.,funding_events=[],
                realized=0.,entry_fees=.12,cover_fees=0.,pending=None,closed_at=None,
                exit_reason='CONTROL',episode=dict(at=100.),cover_fills=[],path=[])


class BroaderTests(unittest.TestCase):
    def test_late_funding_uses_settlement_quantity_and_strictly_prior_mark(self):
        s=state();s['positions']['BTCUSDT']['quantity']=-1.;s['quantity_history']['BTCUSDT'].append((250.,-1.))
        book=row();book['quotes']['BTCUSDT']['funding']=[dict(timestamp_ms=200000,rate=.001)]
        marks={'BTCUSDT':[(190.,100.),(200.,1000.),(210.,200.)]}
        self.assertTrue(b.funding(s,book,marks))
        self.assertAlmostEqual(s['positions']['BTCUSDT']['funding'],.2)
        self.assertEqual(s['funding_cursor'],400.)
        self.assertTrue(b.funding(s,book,marks));self.assertEqual(len(s['funding_events']),1)

    def test_unknown_funding_does_not_advance_cursor_or_pay_partial_batch(self):
        s=state();s['positions']['OTHER']=copy.deepcopy(s['positions']['BTCUSDT'])
        s['quantity_history']['OTHER']=[(100.,-2.)]
        book=row();book['quotes']['BTCUSDT']['funding']=[dict(timestamp_ms=200000,rate=.001)]
        book['quotes']['OTHER']=quote();book['quotes']['OTHER']['funding']=[]
        before=copy.deepcopy(s)
        self.assertFalse(b.funding(s,book,{'BTCUSDT':[(190.,100.)],'OTHER':[(190.,100.)]}))
        self.assertEqual(s,before)

    def test_future_or_unsorted_funding_is_not_usable(self):
        for points in ([dict(timestamp_ms=500000,rate=.001)],
                       [dict(timestamp_ms=200000,rate=.001),dict(timestamp_ms=100000,rate=.001)]):
            s=state();book=row();book['quotes']['BTCUSDT']['funding']=points
            self.assertFalse(b.funding(s,book,{'BTCUSDT':[(190.,100.)]}))

    def test_partial_covers_reconcile_two_prices_and_all_commissions(self):
        s=state();b.cover(s,row(at=400.,price=80.,quantity=1.2))
        self.assertEqual(s['positions']['BTCUSDT']['quantity'],-1.)
        self.assertIsNone(s['closed_at'])
        b.cover(s,row(at=500.,price=120.))
        self.assertEqual(s['positions']['BTCUSDT']['quantity'],0.)
        result=b.summarize(s)
        expected=200-80*1.0002-120*1.0002-.12-(80*1.0002+120*1.0002)*.0006
        self.assertAlmostEqual(result['net'],expected)
        self.assertEqual(result['cover_fills'],2)

    def test_unclosed_or_unfunded_result_cannot_be_scored_as_zero(self):
        with self.assertRaisesRegex(ValueError,'not_closed'):b.summarize(state())
        s=state();b.cover(s,row());s['debt_at_close']=True
        with self.assertRaisesRegex(ValueError,'funding_unknown'):b.summarize(s)

    def test_stress_costs_do_not_mutate_the_observed_book(self):
        book=row();old=copy.deepcopy(book)
        stressed=b.stressed(book,dict(fee_multiplier=2,extra_slippage_per_side=.0002))
        self.assertEqual(book,old);self.assertEqual(stressed['quotes']['BTCUSDT']['fee_rate'],.0012)
        self.assertGreater(stressed['quotes']['BTCUSDT']['asks'][0]['price'],100.)
        self.assertLess(stressed['quotes']['BTCUSDT']['bids'][0]['price'],100.)

    def test_grid_preserves_a_missing_price_as_a_gap(self):
        marks={s:[(0.,100.),(300.,100.),(600.,100.)] for s in b.R.SIGNALS}
        marks['BTCUSDT']=[(0.,100.),(600.,100.)]
        grid,missing=b.build_grid(marks)
        self.assertEqual(missing,[300]);self.assertFalse(grid[1]['valid'])

    def test_future_prices_cannot_change_earlier_signals(self):
        grid=[]
        for i in range(600):
            grid.append(dict(time=i*300,prices={s:100*(.998**i) for s in b.R.SIGNALS},
                             source_times={s:i*300 for s in b.R.SIGNALS},valid=True))
        before=b.signals(grid[:400]);future=copy.deepcopy(grid)
        for r in future[400:]:r['prices']={s:999999. for s in b.R.SIGNALS}
        after=[x for x in b.signals(future) if x['index']<400]
        self.assertEqual(before,after)

    def test_archive_index_hint_never_overrides_embedded_observation_time(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);source=root/'source';source.mkdir();out=root/'output';out.mkdir()
            book=dict(scope='RESEARCH_SIMULATION_ONLY',observed_at_start=b.iso(58),observed_at_end=b.iso(60),quotes={})
            h=b.R.digest(book);book['record_hash']=h
            (source/(h+'.json.gz')).write_bytes(gzip.compress(json.dumps(book).encode()))
            loader=b.Books(out,source,[dict(at=0,hash=h)],120)
            with self.assertRaisesRegex(ValueError,'index_or_universe'):loader.get(0)

    def test_persisted_availability_is_later_than_collection_and_binds_exact_marks(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);source=root/'source';source.mkdir();out=root/'output';out.mkdir()
            book=dict(scope='RESEARCH_SIMULATION_ONLY',observed_at_start=b.iso(58),observed_at_end=b.iso(60),
                      quotes={s:{**quote(), 'symbol':s,'market_identity':'kucoin_futures_usdt',
                                 'timestamp':b.iso(59),'mark_timestamp':b.iso(59),'metadata_observed_at':b.iso(59)} for s in b.R.SIGNALS})
            h=b.R.digest(book);book['record_hash']=h
            (source/(h+'.json.gz')).write_bytes(gzip.compress(json.dumps(book).encode()))
            marks={s:[(80.,100.)] for s in b.R.SIGNALS}
            loader=b.Books(out,source,[dict(at=80.,hash=h)],120,marks)
            loaded=loader.get(0)
            self.assertEqual(loaded['observed_at_end'],b.iso(60));self.assertEqual(b.availability(loaded),80.)
            marks['BTCUSDT']=[(80.,100.01)]
            loader=b.Books(out,source,[dict(at=80.,hash=h)],120,marks)
            with self.assertRaisesRegex(ValueError,'persisted_mark_vector'):loader.get(0)

    def test_processing_delay_cannot_turn_a_future_rate_into_a_settled_observation(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);source=root/'source';source.mkdir();out=root/'output';out.mkdir()
            book=dict(scope='RESEARCH_SIMULATION_ONLY',observed_at_start=b.iso(58),observed_at_end=b.iso(60),
                      quotes={s:{**quote(),'symbol':s,'market_identity':'kucoin_futures_usdt'} for s in b.R.SIGNALS})
            book['quotes']['BTCUSDT']['funding']=[dict(timestamp_ms=70000,rate=.001)]
            h=b.R.digest(book);book['record_hash']=h
            (source/(h+'.json.gz')).write_bytes(gzip.compress(json.dumps(book).encode()))
            loader=b.Books(out,source,[dict(at=80.,hash=h)],120)
            with self.assertRaisesRegex(ValueError,'not_settled'):loader.get(0)

    def test_summary_preserves_negative_outcomes_and_missing_exposure_coverage(self):
        def arm(net,missing=0):return dict(net=net,fees=1.,funding=0.,worst_executable_pnl=-5.,
                                        valuation_missing_points=missing,holding_seconds=3600.)
        rows=[dict(signal_at='2026-10-26T00:00:00+00:00',difference=-3.,
                   corrected={**arm(-2.,1),'reason':'LOSS_STOP'},six_hour=arm(1.))]
        total=b.aggregate(rows)
        self.assertEqual(total['difference'],-3.)
        self.assertIsNone(total['arms']['corrected']['worst_observed_executable_pnl'])
        self.assertEqual(total['arms']['corrected']['winners'],0)


if __name__=='__main__':unittest.main()
