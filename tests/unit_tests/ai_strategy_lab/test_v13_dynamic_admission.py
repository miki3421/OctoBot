import hashlib
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
import v13_dynamic_admission as a


class AdmissionTests(unittest.TestCase):
    def test_approval_binding_and_no_implicit_activation(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);(root/'code.py').write_text('new')
            contract=dict(scope='RESEARCH_SIMULATION_ONLY',code_sha256={'code.py':'oldhash'},funding={'settlement_schedule_evidence':'UNRESOLVED'})
            p=root/'contract.json';p.write_text(json.dumps(contract))
            approval=dict(kind='OWNER_CONTRACT_APPROVAL_NOT_ACTIVATION',decision='APPROVED',contract_path='contract.json',contract_file_sha256=hashlib.sha256(p.read_bytes()).hexdigest())
            receipt=root/'approval.json';receipt.write_text(json.dumps(approval));pin=hashlib.sha256(receipt.read_bytes()).hexdigest()
            with patch.object(a.qualification,'evaluate_bound',return_value={'status':'IN_PROGRESS'}) as verify:
                result=a.inspect(root,receipt,pin,'archive','activation')
                verify.assert_called_once()
                self.assertFalse(result['execution_ready'])
                self.assertIn('qualification_not_passed',result['blockers'])
                self.assertIn('final_bundle_not_frozen',result['blockers'])
                self.assertIn('comparison_activation_not_authorized',result['blockers'])
                p.write_text('{}')
                with self.assertRaisesRegex(ValueError,'contract_fingerprint_mismatch'):a.inspect(root,receipt,pin,'archive','activation')
                with self.assertRaisesRegex(ValueError,'approval_fingerprint_mismatch'):a.inspect(root,receipt,'bad','archive','activation')

    def test_migrated_parent_alias_and_foreign_archive(self):
        q=a.qualification;capture=q.capture
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);real=root/'disk';real.mkdir();alias=root/'srv';alias.symlink_to(real,target_is_directory=True)
            db=real/'qualification.sqlite';db.touch();activation=root/'activation.json'
            config=dict(plan_sha256=capture.PLAN_HASH,collector_sha256=capture.sha(Path(capture.__file__).read_bytes()),periodic_downloads_authorized=True,service_activation_authorized=True,orders_authorized=False,start_utc='2026-10-02T00:00:00Z',end_utc='2026-10-16T00:00:00Z',storage_root=str(alias))
            activation.write_text(json.dumps(config))
            with patch.object(capture,'load_plan',return_value={}),patch.object(capture,'safe_path'),patch.object(q,'evaluate',return_value={'status':'IN_PROGRESS'}) as check:
                self.assertEqual(q.evaluate_bound(root,db,activation,1),{'status':'IN_PROGRESS'})
                self.assertEqual(check.call_count,1)
                with self.assertRaisesRegex(ValueError,'archive_path_binding'):q.evaluate_bound(root,root/'other.sqlite',activation,1)
