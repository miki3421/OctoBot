import importlib.util
from pathlib import Path
import unittest
p=Path(__file__).resolve().parents[3]/'scripts/scalping_archive_checks.py';s=importlib.util.spec_from_file_location('checks',p);m=importlib.util.module_from_spec(s);s.loader.exec_module(m)
class Checks(unittest.TestCase):
 def test_distinguishes_clock_and_session_reset(self):
  rows=[(1,'a',10,100,200),(2,'a',9,99,190),(3,'b',1,1,210)]
  r=m.chronology(rows);self.assertEqual(r['received_timestamp_regressions'],1);self.assertEqual(r['maximum_receive_regression_ns'],10);self.assertEqual(r['sequence_regressions_same_session'],1);self.assertEqual(r['session_switches'],1)
 def test_monotonic_and_no_false_replay(self):
  r=m.chronology([(1,'a',1,1,2),(2,'a',2,2,3)]);self.assertEqual(r['rows'],2);self.assertEqual(r['received_timestamp_regressions'],0)
 def test_bad_id_order_rejected(self):
  with self.assertRaisesRegex(ValueError,'row_id_order'):m.chronology([(2,'a',1,1,2),(1,'a',2,2,3)])
if __name__=='__main__':unittest.main()
