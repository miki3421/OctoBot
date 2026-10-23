"""Synthetic tests of causal extraction and shared cost/funding semantics."""
import argparse,json,tempfile,unittest
from pathlib import Path
from octobot.ai_strategy_lab import timestral_offline_v1 as t

class CausalTests(unittest.TestCase):
 def rows(self):
  return [dict(time=i*300,valid=True,prices={s:100+i*.01 for s in t.SYMBOLS},source_times={s:i*300-30 for s in t.SYMBOLS}) for i in range(365)]
 def test_future_prices_never_change_past_input_or_m1(self):
  a=self.rows();before=t.causal_input(a,288)
  for row in a[289:]:row['prices']={s:1e15 for s in t.SYMBOLS};row['valid']=False
  self.assertEqual(before,t.causal_input(a,288))
 def test_missing_stale_or_future_source_blocks_whole_context(self):
  for kind in ('missing','stale','future'):
   a=self.rows()
   if kind=='missing':a[100]['valid']=False
   else:a[100]['source_times']['BTCUSDT']=a[100]['time']+1 if kind=='future' else a[100]['time']-121
   self.assertIsNone(t.causal_input(a,288))
 def test_receipt_asof_does_not_backfill_a_later_quote(self):
  records=[(100,s,100.) for s in t.SYMBOLS]+[(301,s,999.) for s in t.SYMBOLS]
  rows=t.grids(records,300,600,max_age=250)
  self.assertEqual(rows[0]['prices']['BTCUSDT'],100.)
  self.assertFalse(rows[1]['valid'])
 def test_past_breadth_starts_missing_and_has_no_future_values(self):
  a=self.rows();v=t.causal_input(a,288);self.assertEqual(v['breadth'][:12],[None]*12);self.assertTrue(all(x==0 for x in v['breadth'][12:]));self.assertEqual(len(v['btc']),289)

class EconomicTests(unittest.TestCase):
 def q(self,at,price=100.,size=1e6):return dict(received_ns=int((at+.1)*1e9),bid=[[price,size]],ask=[[price+.01,size]])
 def protocol(self):return dict(execution=dict(entry_delay_seconds=300,holding_seconds=21600,fixed_notional_per_episode=1000,quantity_step_btc=.001,synthetic_base_per_native_unit=.001,adverse_slippage_bps_per_fill=2,fee_bps_per_fill=6))
 def data(self):return dict(quotes={'300':self.q(300),'21900':self.q(21900,99.)},funding=[dict(time=0,rate=.0001,mark=100.)])
 def test_costs_and_stress_reduce_same_short_return(self):
  d=self.data();base=t.episode(d,self.protocol(),0);stress=t.episode(d,self.protocol(),0,2)
  self.assertEqual(base['status'],'COMPLETE');self.assertGreater(base['net'],stress['net']);self.assertGreater(stress['fees'],base['fees']);self.assertEqual(base['funding'],0)
 def test_missing_exit_cannot_be_profitable_or_zero_filled(self):
  d=self.data();del d['quotes']['21900'];v=t.episode(d,self.protocol(),0);self.assertEqual(v['status'],'EXIT_UNAVAILABLE');self.assertNotIn('net',v)
 def test_depth_shortfall_is_not_extrapolated(self):
  d=self.data();d['quotes']['300']['bid'][0][1]=1;v=t.episode(d,self.protocol(),0);self.assertEqual(v['status'],'insufficient_L5_depth');self.assertNotIn('net',v)
  self.assertFalse(v['unresolved_position'])
 def test_exit_depth_shortfall_keeps_position_unresolved(self):
  d=self.data();d['quotes']['21900']['ask'][0][1]=1;v=t.episode(d,self.protocol(),0)
  self.assertEqual(v['status'],'insufficient_L5_depth');self.assertTrue(v['unresolved_position']);self.assertNotIn('net',v)
 def test_unknown_funding_is_not_zero(self):
  d=self.data();d['funding']=[];v=t.episode(d,self.protocol(),0);self.assertEqual(v['status'],'funding_start_unknown');self.assertNotIn('net',v)
 def test_signed_funding_and_missing_expected_settlement(self):
  points=[dict(time=0,rate=.001,mark=100.),dict(time=28800,rate=-.002,mark=110.)]
  self.assertAlmostEqual(t.settlement_value(points,100,30000,2),-.44)
  with self.assertRaisesRegex(ValueError,'funding_gap'):t.settlement_value(points[:1],100,30000,2)

class LicenseTests(unittest.TestCase):
 def test_unconfirmed_eligibility_blocks_before_model_or_data_access(self):
  with tempfile.TemporaryDirectory() as directory:
   receipt=Path(directory)/'eligibility.json';receipt.write_text(json.dumps({'operator_confirmed_eligibility':False}))
   with self.assertRaisesRegex(ValueError,'model_license_eligibility_not_confirmed'):
    t.infer(argparse.Namespace(license_confirmation=str(receipt)))

class M1ReferenceTests(unittest.TestCase):
 def test_m1_requires_both_inclusive_thresholds(self):
  for btc,breadth,expected in [(-.01,12/18,True),(-.009,18/18,False),(-.02,11/18,False),(-.02,18/18,True)]:
   self.assertEqual(t.detector.signal(dict(btc_60m=btc,negative_breadth=breadth),'momentum_breadth'),expected)

if __name__=='__main__':unittest.main()
