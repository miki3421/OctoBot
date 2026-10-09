import copy
import datetime as dt
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
import v13_dynamic_runner as runner
from test_v13_dynamic_comparison import tick
from test_v13_dynamic_universe import fixture,START


def request(offset):
    at=(dt.datetime(2026,10,19,0,16,tzinfo=dt.timezone.utc)+dt.timedelta(days=offset)).isoformat()
    prev=(dt.datetime(2026,10,19,0,16,tzinfo=dt.timezone.utc)+dt.timedelta(days=offset-1)).isoformat() if offset else None
    t=tick(str(offset),at,prev,False)
    t.update(contract_scope='SYNTHETIC_ONLY',price_ticks={s:1e-12 for s in runner.selector.UNIVERSE},quantity_steps={s:.000001 for s in runner.selector.UNIVERSE},
             books={s:dict(at=at,bids=[[99.99,10000.]],asks=[[100.01,10000.]]) for s in runner.selector.UNIVERSE})
    bars=fixture()
    for values in bars.values():
        for n in range(1,offset+1):
            day=dt.date(2026,10,18)+dt.timedelta(days=n)
            values.append(dict(day=day.isoformat(),close=values[-1]['close']*1.002,
                               received_at=dt.datetime.combine(day+dt.timedelta(days=1),dt.time(),dt.timezone.utc).isoformat()))
    return dict(id=str(offset),scope=runner.SCOPE,start=START,lineage='synthetic-runner',tick=t,bars=bars)


class RunnerTests(unittest.TestCase):
    def test_two_slots_and_atomic_derivation_failure(self):
        with tempfile.TemporaryDirectory() as tmp:
            store=runner.accounting.FixtureStore(Path(tmp)/'fixture.sqlite',create=True)
            first,_=runner.run_tick(store,request(0));firstid=first['selection']['decision_id']
            for day in range(1,7):
                state,_=runner.run_tick(store,request(day))
                self.assertEqual(state['selection']['decision_id'],firstid)
            broken=request(7);broken['bars']['BTCUSDT'].pop()
            with self.assertRaises(ValueError):runner.run_tick(store,broken)
            self.assertEqual(store.db.execute('SELECT COUNT(*) FROM ticks').fetchone()[0],7)
            last,_=runner.run_tick(store,request(7))
            self.assertEqual(last['selection']['parent_id'],firstid)
            self.assertEqual(last['last_rebalance'],'2026-10-26T00:15:00+00:00')
            store.close()

    def test_fresh_process_restart_and_replay(self):
        with tempfile.TemporaryDirectory() as tmp:
            p=Path(tmp);req=p/'input.json';db=p/'fixture.sqlite'
            req.write_text(json.dumps([request(0)]))
            command=[sys.executable,'-B',runner.__file__,'--fixture',str(req),'--store',str(db)]
            first=subprocess.run(command+['--create'],capture_output=True,text=True)
            self.assertEqual(first.returncode,0,first.stderr)
            second=subprocess.run(command,capture_output=True,text=True)
            self.assertEqual(second.returncode,0,second.stderr)
            self.assertEqual(json.loads(first.stdout),json.loads(second.stdout))

    def test_reject_real_labels_and_injected_targets(self):
        with tempfile.TemporaryDirectory() as tmp:
            store=runner.accounting.FixtureStore(Path(tmp)/'fixture.sqlite',create=True)
            for mode in ('real','target'):
                r=request(0)
                if mode=='real':r['scope']='VERIFIED_QUALIFICATION_RECEIPT'
                else:r['tick']['targets']={}
                with self.assertRaises(ValueError):runner.run_tick(store,r)
            self.assertEqual(store.db.execute('SELECT COUNT(*) FROM ticks').fetchone()[0],0)
            store.close()
