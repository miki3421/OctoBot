"""Run only the isolated ABC and qualification regression suite; no downloads."""
import sys
import unittest
from pathlib import Path

root=Path(__file__).resolve().parents[1]
sys.path[:0]=[str(root),str(root/'octobot/ai_strategy_lab'),str(root/'tests/unit_tests/ai_strategy_lab')]
modules=['test_v13_dynamic_universe','test_v13_dynamic_comparison','test_v13_dynamic_data',
         'test_v13_dynamic_runner','test_v13_science_bridge','test_v13_dynamic_preview',
         'test_v13_dynamic_funding','test_v13_dynamic_cash','test_v13_dynamic_linked',
         'test_v13_dynamic_intent','test_v13_dynamic_admission','test_v13_dynamic_consumer',
         'test_v13_dynamic_coverage','test_v13_dynamic_forward','test_v13_dynamic_service','test_v13_dynamic_producer','test_v13_funding_observer','test_v13_funding_continuity','test_v13_release_preflight',
         'test_v13_funding_history_review','test_v13_universe_qualification_evaluate']
if __name__=='__main__':
    result=unittest.TextTestRunner(verbosity=1).run(unittest.defaultTestLoader.loadTestsFromNames(modules))
    raise SystemExit(0 if result.wasSuccessful() else 1)
