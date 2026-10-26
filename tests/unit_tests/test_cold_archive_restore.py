"""Archive restoration safety and a real SQLite recovery, using synthetic data."""
import importlib.util
from pathlib import Path
import shutil
import sqlite3
import subprocess
import tarfile
import tempfile
import unittest

spec=importlib.util.spec_from_file_location('restore',Path(__file__).resolve().parents[2]/'scripts/verify_cold_archive.py')
m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m)


@unittest.skipUnless(shutil.which('zstd'), 'existing local Zstandard required')
class RestoreTests(unittest.TestCase):
    def test_complete_sqlite_restore_preserves_source_and_refuses_existing_destination(self):
        with tempfile.TemporaryDirectory() as folder:
            p=Path(folder);source=p/'source';source.mkdir();db=source/'account.sqlite'
            with sqlite3.connect(db) as connection:
                connection.execute('CREATE TABLE positions(symbol TEXT,quantity REAL)')
                connection.execute("INSERT INTO positions VALUES('SYNTHETIC',2)")
            db.chmod(0o440);s=db.stat();sha=m.digest(db)
            manifest={'account.sqlite':dict(sha256=sha,before=dict(size=s.st_size,uid=s.st_uid,gid=s.st_gid,mode=0o440,mtime_ns=s.st_mtime_ns))}
            tar=p/'archive.tar'
            with tarfile.open(tar,'w') as contents:contents.add(db,arcname='account.sqlite')
            archive=p/'archive.tar.zst';subprocess.run(['zstd','-q','-o',str(archive),str(tar)],check=True)
            dest=p/'restored';m.restore(archive,manifest,dest)
            self.assertEqual(m.check_databases(dest,manifest),{'account.sqlite':'ok'})
            self.assertEqual(m.digest(db),sha);self.assertEqual(db.stat().st_mtime_ns,s.st_mtime_ns)
            self.assertNotEqual(db.stat().st_ino,(dest/'account.sqlite').stat().st_ino)
            with self.assertRaisesRegex(ValueError,'fresh_restore_required'):m.restore(archive,manifest,dest)

    def test_traversal_manifest_and_archive_symlink_are_refused(self):
        with tempfile.TemporaryDirectory() as folder:
            p=Path(folder)
            with self.assertRaisesRegex(ValueError,'unsafe_archive_path'):
                m.restore(p/'unused',{'../outside':{}},p/'restore')
            self.assertFalse((p/'restore').exists())
            tar=p/'link.tar'
            with tarfile.open(tar,'w') as contents:
                item=tarfile.TarInfo('account.sqlite');item.type=tarfile.SYMTYPE;item.linkname='/etc/passwd';contents.addfile(item)
            archive=p/'link.tar.zst';subprocess.run(['zstd','-q','-o',str(archive),str(tar)],check=True)
            with self.assertRaisesRegex(ValueError,'undeclared_or_linked_member'):
                m.restore(archive,{'account.sqlite':{'before':{'size':0}}},p/'restore-link')
            self.assertFalse((p/'restore-link/account.sqlite').exists())


if __name__=='__main__':unittest.main()
