import copy,hashlib,json,tempfile,unittest
from pathlib import Path
import v13_release_preflight as p

class PreparationTests(unittest.TestCase):
    def setup(self,root):
        repo=Path(__file__).resolve().parents[3]
        plan=json.loads((repo/'docs/deployment/v13-abc-inactive-plan-v1.json').read_text())
        (root/'code.py').write_text('candidate')
        manifest=dict(comparison_active=False,files={'code.py':hashlib.sha256(b'candidate').hexdigest()})
        return plan,manifest
    def test_draft_passes_checks_but_never_opens_gates(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);plan,m=self.setup(root);result=p.assess(plan,m,root)
            self.assertTrue(result['technical_checks_passed']);self.assertFalse(result['execution_ready'])
            self.assertIn('assign_uid:executor',result['bindings_pending'])
            self.assertEqual(p.configurations(plan)['executor']['scope'],'DRAFT_NOT_RUNTIME_CONFIGURATION')
    def test_tamper_and_paths_are_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);plan,m=self.setup(root);(root/'code.py').write_text('changed')
            self.assertFalse(p.assess(plan,m,root)['technical_checks_passed'])
            m['files']={'../code.py':'a'*64};self.assertIn('unsafe_bundle_path',p.assess(plan,m,root)['errors'])
    def test_shared_writers_dates_and_fake_approvals_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);plan,m=self.setup(root)
            plan['uids']=dict(collector=1001,producer=1001,executor=True)
            plan['paths']['intents']=plan['paths']['forward']
            plan['start_utc']='2026-10-08T00:15:00Z';plan['gate_evidence']['qualification_pass']=True
            errors=p.assess(plan,m,root)['errors']
            for e in ('writers_not_separated','invalid_uid:executor','store_alias','writer_directory_overlap','invalid_common_start','draft_cannot_assert_gate:qualification_pass'):self.assertIn(e,errors)

    def test_sqlite_owner_directory_and_unsafe_files(self):
        import os
        from unittest.mock import patch
        import v13_dynamic_data as data
        with tempfile.TemporaryDirectory() as tmp:
            path=Path(tmp)/'data.sqlite';path.write_bytes(b'fixture')
            with patch.object(data.capture,'safe_path') as parents:
                data.store_path(path,os.getuid())
                parents.assert_called_with(path.parent,os.getuid(),directory=True)
                path.chmod(0o666)
                with self.assertRaisesRegex(ValueError,'untrusted_store_file'):data.store_path(path,os.getuid())
                link=Path(tmp)/'link';link.symlink_to(path)
                with self.assertRaisesRegex(ValueError,'untrusted_store_file'):data.store_path(link,os.getuid())
