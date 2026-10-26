"""Cold evidence filesystem invariants; no real journals or Docker access."""
import importlib.util
from pathlib import Path
import tempfile
import unittest

spec=importlib.util.spec_from_file_location('cold_dedup',Path(__file__).resolve().parents[2]/'scripts/deduplicate_cold_audit.py')
m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m)


class ColdDedupTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.root=Path(self.temp.name);self.a=self.root/'raw.sqlite';self.b=self.root/'checked.sqlite'
        for p in (self.a,self.b):p.write_bytes(b'fixture journal bytes\x00'*100);p.chmod(0o640)
        self.plan=dict(sha256=m.digest(self.a),files=[dict(path=str(p),before=m.info(p)) for p in (self.a,self.b)])
    def tearDown(self):self.temp.cleanup()

    def test_all_paths_bytes_and_owners_retained_as_read_only_files(self):
        before=self.a.read_bytes();out=m.apply_group(self.plan,[self.root])
        self.assertEqual(self.a.read_bytes(),before);self.assertEqual(self.b.read_bytes(),before)
        self.assertEqual(self.a.stat().st_ino,self.b.stat().st_ino)
        self.assertEqual(self.a.stat().st_mode&0o222,0);self.assertEqual(out['linked_paths'],1)
        self.assertEqual(self.a.stat().st_uid,self.plan['files'][0]['before']['uid'])

    def test_open_journal_is_refused_before_changes(self):
        with self.a.open('rb'):
            with self.assertRaisesRegex(ValueError,'changed_or_open'):m.apply_group(self.plan,[self.root])
        self.assertNotEqual(self.a.stat().st_ino,self.b.stat().st_ino)

    def test_changed_content_and_wrong_root_are_refused(self):
        self.b.write_bytes(b'changed')
        with self.assertRaises(ValueError):m.apply_group(self.plan,[self.root])
        with self.assertRaisesRegex(ValueError,'cold_boundary'):m.apply_group(self.plan,[self.root/'another'])


if __name__=='__main__':unittest.main()
