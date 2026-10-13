"""Offline clone tests: exact history preservation and overwrite rejection."""
import hashlib
import json
from pathlib import Path
import sqlite3
import subprocess
import sys
import tempfile
import unittest

SCRIPT=Path(__file__).resolve().parents[3]/'octobot/ai_strategy_lab/v13_fork_snapshot.py'

class ForkTest(unittest.TestCase):
    def test_exact_separate_copies_and_refuse_overwrite(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);(root/'original').mkdir();source=root/'original/source.sqlite';dest=root/'fork'
            db=sqlite3.connect(source)
            db.execute('create table state(id integer primary key,payload text)')
            state={'positions':{'TEST':{'quantity':3}},'risk_policy_state':{'high_water':11000,'daily_entries':1},'last_success_at':'2026-10-13T00:00:00+00:00'}
            db.execute('insert into state values(1,?)',(json.dumps(state),))
            db.execute('create table history(id integer primary key,amount real)')
            db.executemany('insert into history values(?,?)',[(1,12.5),(2,-3.25)])
            db.commit();db.close();before=source.read_bytes()
            args=[sys.executable,str(SCRIPT),'--source',str(source),'--destination',str(dest)]
            first=subprocess.run(args,capture_output=True,text=True)
            self.assertEqual(first.returncode,0,first.stderr)
            self.assertEqual(before,source.read_bytes())
            paths=[dest/'parent-snapshot.sqlite',dest/'fast/execution.sqlite',dest/'half/execution.sqlite']
            self.assertEqual(len({p.stat().st_ino for p in paths}),3)
            self.assertEqual(len({hashlib.sha256(p.read_bytes()).hexdigest() for p in paths}),1)
            for path in paths:
                c=sqlite3.connect(path.as_uri()+'?mode=ro',uri=True)
                self.assertEqual(json.loads(c.execute('select payload from state').fetchone()[0]),state)
                self.assertEqual(c.execute('select * from history order by id').fetchall(),[(1,12.5),(2,-3.25)])
                c.close()
            original=paths[0].read_bytes()
            second=subprocess.run(args,capture_output=True,text=True)
            self.assertNotEqual(second.returncode,0)
            self.assertEqual(original,paths[0].read_bytes())
            self.assertEqual(before,source.read_bytes())

if __name__=='__main__':unittest.main()
