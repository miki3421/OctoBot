import importlib.util
import json
from pathlib import Path
import shutil
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[3]
MODULE = ROOT / "octobot/ai_strategy_lab/v13_btc_candidate_lock.py"
LOCK = ROOT / "octobot/ai_strategy_lab/v13_btc_paper_candidate_designation_v1.json"
spec = importlib.util.spec_from_file_location("candidate_lock", MODULE)
candidate = importlib.util.module_from_spec(spec)
spec.loader.exec_module(candidate)


class CandidateLockTest(unittest.TestCase):
    def test_designation_is_bound_but_cannot_authorize(self):
        result = candidate.verify(ROOT, LOCK)
        self.assertTrue(result["artifacts_bound"])
        self.assertFalse(result["issuer_authorized"])
        self.assertFalse(result["paper_orders_authorized"])

    def test_code_tamper_and_status_flip_fail(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            for relative in candidate.PATHS.values():
                target = root / relative
                target.parent.mkdir(parents=True, exist_ok=True)
                shutil.copyfile(ROOT / relative, target)
            lock_path = root / "designation.json"
            shutil.copyfile(LOCK, lock_path)
            self.assertTrue(candidate.verify(root, lock_path)["identity_bound"])
            producer = root / candidate.PATHS["producer"]
            producer.write_bytes(producer.read_bytes() + b"\n# tampered\n")
            with self.assertRaisesRegex(ValueError, "candidate_artifact_hash_mismatch:producer"):
                candidate.verify(root, lock_path)
            shutil.copyfile(ROOT / candidate.PATHS["producer"], producer)
            lock = json.loads(lock_path.read_text())
            lock["issuer_authorized"] = True
            lock_path.write_text(json.dumps(lock))
            with self.assertRaisesRegex(ValueError, "candidate_status_invalid"):
                candidate.verify(root, lock_path)


if __name__ == "__main__":
    unittest.main()
