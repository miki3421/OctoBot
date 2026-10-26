"""Archive restoration safety and a real SQLite recovery, using synthetic data."""
import importlib.util
import json
from pathlib import Path
import shutil
import sqlite3
import subprocess
import sys
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

    def test_forensic_wal_restore_is_exact_without_claiming_database_integrity(self):
        with tempfile.TemporaryDirectory() as folder:
            p=Path(folder);db=p/'working.sqlite';connection=sqlite3.connect(db)
            connection.execute('PRAGMA journal_mode=WAL');connection.execute('PRAGMA wal_autocheckpoint=0')
            connection.execute('CREATE TABLE events(value TEXT)');connection.execute("INSERT INTO events VALUES('synthetic')");connection.commit()
            source=p/'source';source.mkdir()
            for name in ('working.sqlite','working.sqlite-wal','working.sqlite-shm'):
                shutil.copy2(p/name,source/name)
            connection.close()
            self.assertGreater((source/'working.sqlite-wal').stat().st_size,0)
            manifest={}
            for path in source.iterdir():
                s=path.stat();manifest[path.name]=dict(sha256=m.digest(path),before=dict(size=s.st_size,uid=s.st_uid,gid=s.st_gid,mode=s.st_mode&0o777,mtime_ns=s.st_mtime_ns))
            manifest_path=p/'manifest.json';manifest_path.write_text(json.dumps(manifest));tar=p/'archive.tar'
            with tarfile.open(tar,'w') as contents:
                for path in source.iterdir():contents.add(path,arcname=path.name)
            archive=p/'archive.tar.zst';subprocess.run(['zstd','-q','-o',str(archive),str(tar)],check=True)
            dest=p/'recovered';result=p/'result.json'
            subprocess.run([sys.executable,str(Path(m.__file__)), '--archive',str(archive),
                '--archive-sha256',m.digest(archive),'--manifest',str(manifest_path),
                '--destination',str(dest),'--result',str(result),'--files-only'],check=True,capture_output=True)
            record=json.loads(result.read_text());self.assertTrue(record['passed'])
            self.assertFalse(record['sqlite_integrity_checked']);self.assertIsNone(record['sqlite_integrity'])
            for name,item in manifest.items():self.assertEqual(m.digest(dest/name),item['sha256'])
            with self.assertRaisesRegex(ValueError,'nonempty_wal'):m.check_databases(dest,manifest)


if __name__=='__main__':unittest.main()
