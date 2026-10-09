"""Synthetic control tests only; no market admissibility or profitability claim."""
import copy
import datetime as dt
import json
import math
import unittest

import v13_dynamic_universe as m

START = '2026-10-19T00:15:00+00:00'


def fixture():
    start = dt.date(2026, 10, 18) - dt.timedelta(days=120)
    return {s: [dict(day=(start + dt.timedelta(days=i)).isoformat(),
                     close=100 * math.exp(.002*i + .001*math.sin(i)),
                     received_at=(dt.datetime.combine(start+dt.timedelta(days=i+1), dt.time(), m.UTC)).isoformat())
                for i in range(121)] for s in m.UNIVERSE}


class SelectorTests(unittest.TestCase):
    def decide(self, data=None, **kwargs):
        return m.decide(data or fixture(), slot=START, start=START, lineage='synthetic-v1', **kwargs)

    def test_initial_stable_order_and_no_authority(self):
        data = fixture()
        a = self.decide(data)
        b = self.decide(dict(reversed(list(data.items()))))
        self.assertEqual(a, b)
        self.assertEqual(a['selected'], sorted(m.UNIVERSE)[:18])
        self.assertFalse(a['paper_orders_authorized'])

    def test_future_invariance(self):
        data = fixture()
        a = self.decide(data)
        for bars in data.values():
            bars.append(dict(day='2026-10-19', close=1e100, received_at='2026-10-20T00:00:00Z'))
        self.assertEqual(a, self.decide(data))

    def test_missing_duplicate_and_late_common_data(self):
        for kind in ('missing','duplicate','late'):
            data = fixture(); bars=data[m.UNIVERSE[0]]
            if kind=='missing': bars.pop()
            elif kind=='duplicate': bars.append(copy.deepcopy(bars[-1]))
            else: bars[-1]['received_at']='2026-10-19T00:16:00Z'
            with self.assertRaises(ValueError): self.decide(data)

    def test_restart_replay_conflict_and_binding(self):
        a = self.decide(); state=json.loads(json.dumps(a))
        self.assertEqual(a,self.decide(previous=state,expected_previous_id=a['decision_id']))
        bad=fixture();bad[m.UNIVERSE[0]][-1]['close'] *= 1.01
        with self.assertRaisesRegex(ValueError,'slot_conflict'):
            self.decide(bad,previous=state,expected_previous_id=a['decision_id'])
        state['selected']=[]
        with self.assertRaisesRegex(ValueError,'binding'):
            self.decide(previous=state,expected_previous_id=a['decision_id'])

    def test_margin_and_two_admissions(self):
        prior=list(m.UNIVERSE[:18]); rows={s:dict(signal=1,score=1.) for s in m.UNIVERSE}
        for value, expected in [(1.19,0),(1.20,0),(1.21,2)]:
            for s in m.UNIVERSE[18:]:rows[s]['score']=value
            picked,events=m.select(rows,prior)
            self.assertEqual(len(set(picked)-set(prior)),expected)
        for s in prior[:3]:rows[s]['signal']=0
        picked,events=m.select(rows,prior)
        self.assertEqual(len(set(picked)-set(prior)),2)
        self.assertEqual(len(picked),17)
        self.assertEqual(sum(e['reason']=='mandatory_exit' for e in events),3)

    def test_short_regime_and_flat(self):
        data=fixture()
        for b in data['ETHUSDT']:b['close']=10000/b['close']
        a=self.decide(data)
        self.assertEqual(a['rows']['ETHUSDT']['signal'],0)
        for b in data['BTCUSDT']:b['close']=10000/b['close']
        self.assertEqual(self.decide(data)['rows']['ETHUSDT']['signal'],-1)
        for bars in data.values():
            for b in bars:b['close']=100
        self.assertEqual(self.decide(data)['selected'],[])

    def test_weekly_calendar_and_missing_state(self):
        with self.assertRaises(ValueError):m.slot_index('2026-10-20T00:15:00Z',START)
        with self.assertRaises(ValueError):m.slot_index('2026-10-19T00:15:00',START)
        with self.assertRaises(ValueError):self.decide(expected_previous_id='missing')

    def test_next_week_and_skipped_slot_do_not_reset_selection(self):
        first=self.decide()
        data=fixture()
        for bars in data.values():
            for n in range(1,15):
                day=dt.date(2026,10,18)+dt.timedelta(days=n)
                bars.append(dict(day=day.isoformat(),close=bars[-1]['close']*1.002,
                                 received_at=dt.datetime.combine(day+dt.timedelta(days=1),dt.time(),m.UTC).isoformat()))
        args=dict(slot='2026-11-02T00:15:00+00:00',start=START,lineage='synthetic-v1')
        with self.assertRaisesRegex(ValueError,'previous_state_required'):
            m.decide(data,**args)
        next_week=m.decide(data,previous=first,expected_previous_id=first['decision_id'],**args)
        self.assertEqual(next_week['parent_id'],first['decision_id'])
        self.assertLessEqual(len(set(next_week['selected'])-set(first['selected'])),2)

    def test_unmasked_allocator_parity_and_mask(self):
        import numpy as np
        from octobot.ai_strategy_lab import trend
        conf=next(c for c in trend.TREND_CONFIGS if c.name=='risk_budgeted_bear_regime_v13')
        signals=np.array([1.,-1.,1.]);cov=np.diag([.04,.09,.16]);syms=['A','B','C']
        np.testing.assert_array_equal(m.target_weights(signals,cov,syms,syms),trend._target_weights(signals,cov,conf))
        masked=m.target_weights(signals,cov,syms,['A','B'])
        np.testing.assert_array_equal(masked,trend._target_weights(np.array([1.,-1.,0.]),cov,conf))
        self.assertEqual(masked[2],0)
        cov[0,0]=float('nan')
        with self.assertRaises(ValueError):m.target_weights(signals,cov,syms,syms)


if __name__=='__main__':unittest.main()
