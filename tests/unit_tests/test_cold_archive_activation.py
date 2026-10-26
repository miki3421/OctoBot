"""Scoped archival replacement safety; only synthetic temporary files."""
import importlib.util
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest import mock

spec=importlib.util.spec_from_file_location('activate',Path(__file__).resolve().parents[2]/'scripts/activate_cold_archives.py')
m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m)


@unittest.skipUnless(os.geteuid()==0,'root-owned catalog policy')
class ActivationTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.root=Path(self.tmp.name).resolve()
        self.names=('cold-one','cold-two');self.controls=self.root/'controls';self.controls.mkdir()
        self.entries=[];common=None
        for name in self.names:
            root=self.root/name;root.mkdir();(root/'raw').mkdir()
            path=root/'raw/account.sqlite'
            if common is None:path.write_bytes(b'synthetic historical state');common=path
            else:os.link(common,path)
            (root/'description.json').write_text('{}\n')
        for name in self.names:
            root=self.root/name;manifest={}
            for path in sorted(p for p in root.rglob('*') if p.is_file()):
                manifest[str(path.relative_to(root))]=dict(before=m.d.info(path),sha256=m.d.digest(path))
            manifest_path=self.controls/(name+'.manifest.json');manifest_path.write_text(json.dumps(manifest))
            archive=self.controls/(name+'.tar.zst');archive.write_bytes(b'PINNED PREPARATION ARTIFACT')
            self.entries.append(dict(package=name,manifest=str(manifest_path),archive=str(archive),
                manifest_sha256=m.d.digest(manifest_path),archive_sha256=m.d.digest(archive),
                archive_bytes=archive.stat().st_size,byte_metadata_roundtrip=True,files=len(manifest)))
        self.catalog=self.controls/'catalog.json'
        self.catalog.write_text(json.dumps(dict(scope='COLD_ARCHIVAL_PREPARATION_ONLY_NO_SOURCE_REMOVAL',packages=self.entries)))
        self.sha=m.d.digest(self.catalog)
        self.patch_root=mock.patch.object(m.d,'ROOT',self.root);self.patch_names=mock.patch.object(m.d,'COLD',self.names)
        self.patch_root.start();self.patch_names.start()
    def tearDown(self):
        self.patch_names.stop();self.patch_root.stop();self.tmp.cleanup()

    def test_valid_preflight_is_read_only_and_apply_handles_cross_package_links(self):
        originals={str(p):p.read_bytes() for name in self.names for p in (self.root/name).rglob('*') if p.is_file()}
        _,items=m.preflight(self.catalog,self.sha)
        self.assertEqual(originals,{path:Path(path).read_bytes() for path in originals})
        outcome=m.apply(items,self.catalog,self.root/'activation.json')
        self.assertTrue(outcome['completed']);self.assertEqual(len(outcome['packages']),2)
        for entry in self.entries:
            root=self.root/entry['package'];self.assertEqual([p.name for p in root.iterdir()],['ARCHIVED.json'])
            self.assertEqual(m.d.digest(Path(entry['archive'])),entry['archive_sha256'])
            self.assertEqual(json.loads((root/'ARCHIVED.json').read_text())['file_count'],2)
        self.assertFalse(list(self.root.glob('repack-staging-*')))

    def test_open_source_and_same_metadata_content_tampering_refuse_all_removal(self):
        source=self.root/self.names[0]/'raw/account.sqlite'
        with source.open('rb'):
            with self.assertRaisesRegex(ValueError,'changed_or_open'):m.preflight(self.catalog,self.sha)
        old=source.stat();source.write_bytes(b'X'*old.st_size);os.utime(source,ns=(old.st_atime_ns,old.st_mtime_ns))
        with self.assertRaisesRegex(ValueError,'digest_changed'):m.preflight(self.catalog,self.sha)
        self.assertTrue((self.root/self.names[1]/'raw/account.sqlite').exists())
        self.assertFalse((self.root/self.names[0]/'ARCHIVED.json').exists())

    def test_archive_tampering_and_outside_scope_are_refused(self):
        archive=Path(self.entries[0]['archive']);old=archive.read_bytes();archive.write_bytes(b'bad')
        with self.assertRaisesRegex(ValueError,'archive_or_manifest_digest'):m.preflight(self.catalog,self.sha)
        archive.write_bytes(old)
        data=json.loads(self.catalog.read_text());data['packages'][0]['package']='../live'
        self.catalog.write_text(json.dumps(data))
        with self.assertRaisesRegex(ValueError,'exact_four_package_scope'):m.preflight(self.catalog,m.d.digest(self.catalog))
        self.assertTrue((self.root/self.names[0]/'raw/account.sqlite').exists())


if __name__=='__main__':unittest.main()
