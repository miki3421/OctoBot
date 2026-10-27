"""Independent economic expectations for the frozen inactive SHORT controller."""
import copy
import importlib.util
import json
import math
from pathlib import Path
import unittest

ROOT=Path(__file__).resolve().parents[3]
spec=importlib.util.spec_from_file_location('short_risk',ROOT/'octobot/ai_strategy_lab/v13_m1_short_risk.py')
r=importlib.util.module_from_spec(spec);spec.loader.exec_module(r)
P=json.loads((ROOT/'docs/research-protocols/m1-short-risk-exits-candidate-v1.json').read_text())
SLOT=288*300


def rows(amplitude=.001):
    return [dict(time=i*300,prices={s:100*math.exp(amplitude*math.sin(i*.7+j*.03))
                                  for j,s in enumerate(r.SIGNALS)},
                 source_times={s:i*300-1 for s in r.SIGNALS}) for i in range(289)]


def quotes(price=100.):
    return {s:dict(mark_price=price,quantity_step=.01,fee_rate=.0006,
                   asks=[dict(price=price+.01,base_quantity=10000.)],
                   bids=[dict(price=price-.01,base_quantity=10000.)]) for s in r.SIGNALS}


def saved():
    return dict(protocol_id=r.PROTOCOL_ID,at=float(SLOT),risk_unit=1.,legs={
        'BTCUSDT':dict(quantity=-1.,entry=100.,opening_fee=.06,funding_anchor=0.)},
        peak=None,armed=False,last_at=float(SLOT),last_market=None,recovery_count=0,
        last_recovery_slot=None,exit_reason=None)


def positions(price=100.,funding=0.):
    return {'BTCUSDT':dict(quantity=-1.,entry_price=price,funding=funding)}


class ShortRiskTests(unittest.TestCase):
    def test_protocol_cannot_be_relaxed_or_relabelled(self):
        r.validate(P)
        p=copy.deepcopy(P);p['sizing']['risk_fraction_equity']=.01
        with self.assertRaisesRegex(ValueError,'frozen_protocol'):r.validate(p)

    def test_history_rejects_future_stale_gapped_and_incomplete_prices(self):
        for mutation in ('future','stale','gap','missing','nan'):
            x=rows()
            if mutation=='future':x[10]['source_times']['BTCUSDT']=x[10]['time']+1
            elif mutation=='stale':x[10]['source_times']['BTCUSDT']=x[10]['time']-121
            elif mutation=='gap':x[10]['time']+=300
            elif mutation=='missing':del x[10]['prices']['BTCUSDT']
            else:x[10]['prices']['BTCUSDT']=float('nan')
            with self.subTest(mutation=mutation),self.assertRaises(ValueError):r.model(x,SLOT)

    def test_history_is_independent_of_unconsumed_future_rows(self):
        x=rows();before=r.model(x,SLOT);future=copy.deepcopy(x[-1]);future['time']+=300
        panel=x+[future];future['prices']['BTCUSDT']=999999.
        self.assertEqual(before,r.model(panel[:289],SLOT))
        with self.assertRaises(ValueError):r.model(panel,SLOT)

    def test_size_preserves_every_authority_and_unused_cash(self):
        p=r.size(P,r.model(rows(),SLOT),10000.,P['short_caps'],quotes())
        self.assertLessEqual(p['planned_stopped_risk'],25.)
        self.assertLess(p['short_notional'],10000*sum(P['short_caps'].values()))
        for s,q in p['quantities'].items():
            self.assertLessEqual(abs(q)*100,10000*P['short_caps'][s]+1e-8)
            self.assertAlmostEqual(abs(q)/.01,round(abs(q)/.01))
        self.assertEqual(p['short_budget'],sum(P['short_caps'].values()))

    def test_higher_volatility_or_costs_cannot_create_more_nominal_risk(self):
        low=r.size(P,r.model(rows(.001),SLOT),10000.,P['short_caps'],quotes())
        high=r.size(P,r.model(rows(.03),SLOT),10000.,P['short_caps'],quotes())
        self.assertLess(high['short_notional'],low['short_notional'])
        q=quotes()
        for v in q.values():v['fee_rate']=.002
        costly=r.size(P,r.model(rows(.001),SLOT),10000.,P['short_caps'],q)
        self.assertLess(costly['short_notional'],low['short_notional'])

    def test_changed_caps_or_insufficient_depth_do_not_authorize_an_entry(self):
        caps=copy.deepcopy(P['short_caps']);caps['BTCUSDT']+=.01
        with self.assertRaises(ValueError):r.size(P,r.model(rows(),SLOT),10000.,caps,quotes())
        q=quotes();q['BTCUSDT']['asks'][0]['base_quantity']=.00001
        with self.assertRaisesRegex(ValueError,'depth'):r.size(P,r.model(rows(),SLOT),10000.,P['short_caps'],q)

    def test_no_executable_lot_is_explicit(self):
        q=quotes()
        for v in q.values():v['quantity_step']=100000.
        with self.assertRaisesRegex(ValueError,'no_executable_short_lot'):r.size(P,r.model(rows(),SLOT),10000.,P['short_caps'],q)

    def test_reversal_fee_uses_actual_short_fraction_not_half(self):
        plan=dict(protocol_id=r.PROTOCOL_ID,quantities={'BTCUSDT':-2.},risk_unit=25.,entry_equity=10000.)
        plan['plan_id']=r.digest(plan)
        before={'BTCUSDT':dict(quantity=.5)};after={'BTCUSDT':dict(quantity=-2.,entry_price=100.,funding=3.)}
        f=[dict(symbol='BTCUSDT',before=.5,after=-2.,quantity=-2.5,fee=.15)]
        e=r.episode(plan,before,after,f,SLOT,'test')
        self.assertAlmostEqual(e['legs']['BTCUSDT']['opening_fee'],.12)
        self.assertEqual(e['legs']['BTCUSDT']['funding_anchor'],3.)

    def test_executable_pnl_includes_both_fees_slippage_and_only_new_funding(self):
        e=saved();q=quotes(90.)
        net=r.liquidation(e,positions(funding=.3),q)
        expected=100-90.01*1.0002-.06-90.01*1.0002*.0006+.3
        self.assertAlmostEqual(net,expected)

    def test_loss_stop_is_sticky_across_restart_and_gaps(self):
        e,reason=r.watch(P,saved(),positions(),quotes(102),at=SLOT+20,market_id='a')
        self.assertEqual(reason,'LOSS_STOP')
        e=json.loads(json.dumps(e));e,reason=r.watch(P,e,positions(),quotes(90),at=SLOT+3600,market_id='b')
        self.assertEqual(reason,'LOSS_STOP')

    def test_profit_arms_at_one_R_and_retracement_is_half_R(self):
        e,reason=r.watch(P,saved(),positions(),quotes(98),at=SLOT+20,market_id='a')
        self.assertIsNone(reason);self.assertTrue(e['armed'])
        peak=e['peak'];e,reason=r.watch(P,e,positions(),quotes(99),at=SLOT+40,market_id='b')
        self.assertEqual(reason,'PROFIT_GIVEBACK');self.assertLess(e['last_liquidation_net'],peak-.5)

    def test_mark_only_profit_cannot_arm_before_exit_costs_are_paid(self):
        e,reason=r.watch(P,saved(),positions(),quotes(98.95),at=SLOT+20,market_id='a')
        self.assertIsNone(reason);self.assertFalse(e['armed'])

    def test_recovery_requires_two_distinct_consecutive_causal_slots(self):
        f=dict(btc_60m=0.,negative_breadth=.5)
        e,reason=r.watch(P,saved(),positions(),quotes(100),at=SLOT+1,market_id='a',feature_slot=SLOT,feature=f)
        self.assertIsNone(reason);self.assertEqual(e['recovery_count'],1)
        e,reason=r.watch(P,e,positions(),quotes(100),at=SLOT+2,market_id='b',feature_slot=SLOT,feature=f)
        self.assertIsNone(reason);self.assertEqual(e['recovery_count'],1)
        e,reason=r.watch(P,e,positions(),quotes(100),at=SLOT+301,market_id='c',feature_slot=SLOT+300,feature=f)
        self.assertEqual(reason,'SIGNAL_INVALIDATED')

    def test_missing_or_nonconsecutive_recovery_resets_confirmation(self):
        f=dict(btc_60m=.001,negative_breadth=.4)
        e,_=r.watch(P,saved(),positions(),quotes(100),at=SLOT+1,market_id='a',feature_slot=SLOT,feature=f)
        e,reason=r.watch(P,e,positions(),quotes(100),at=SLOT+301,market_id='b',feature_slot=SLOT+300,feature=None)
        self.assertIsNone(reason);self.assertEqual(e['recovery_count'],0)
        e,reason=r.watch(P,e,positions(),quotes(100),at=SLOT+901,market_id='c',feature_slot=SLOT+900,feature=f)
        self.assertIsNone(reason);self.assertEqual(e['recovery_count'],1)

    def test_depth_position_or_future_feature_failures_do_not_become_free_exits(self):
        q=quotes();q['BTCUSDT']['asks'][0]['base_quantity']=.01
        with self.assertRaises(ValueError):r.watch(P,saved(),positions(),q,at=SLOT+1,market_id='a')
        with self.assertRaises(ValueError):r.watch(P,saved(),positions(price=101),quotes(),at=SLOT+1,market_id='a')
        with self.assertRaises(ValueError):r.watch(P,saved(),positions(),quotes(),at=SLOT+1,market_id='a',feature_slot=SLOT+300,feature={})

    def test_duplicate_market_does_not_advance_peak_or_confirmation(self):
        e,_=r.watch(P,saved(),positions(),quotes(),at=SLOT+1,market_id='a')
        again,_=r.watch(P,e,positions(),quotes(90),at=SLOT+1,market_id='a')
        self.assertEqual(e,again)
        with self.assertRaises(ValueError):r.watch(P,e,positions(),quotes(),at=SLOT+1,market_id='b')


if __name__=='__main__':unittest.main()
