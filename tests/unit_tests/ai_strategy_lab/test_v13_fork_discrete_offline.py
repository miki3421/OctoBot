"""Complete-slot mechanical tests with explicit synthetic times and markets."""
import copy
import datetime as dt
import json
import os
from pathlib import Path
import sqlite3
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

import test_v13_fork_runner as fixture
from octobot.ai_strategy_lab import v13_fork_discrete_offline as d

f = d.f
T = fixture.T.replace(hour=0,minute=10)+dt.timedelta(days=1)
SLOT = T.replace(minute=15)
EVENT = SLOT+dt.timedelta(seconds=10)


def book(at, *, funding=True):
    record = fixture.record(at)
    for q in record['quotes'].values():
        q['funding_interval_ms']=86400000
        q['funding']=[dict(timestamp_ms=int(T.timestamp()*1000),rate=.0001)] if funding else []
        if funding and at>=EVENT:
            q['funding'].append(dict(timestamp_ms=int(EVENT.timestamp()*1000),rate=.001))
    record['record_hash']=f.p.digest({k:v for k,v in record.items() if k!='record_hash'})
    return record


def write_book(root, record):
    (root/'market.json').write_text(f.dump(record))
    path=root/'market'/(record['record_hash']+'.json');path.write_text(f.dump(record))
    at=f.p.timestamp(record['observed_at_end']).timestamp();os.utime(path,(at,at))


def tick(runner, instant):
    with patch.object(f.source,'now',return_value=instant):
        runner.tick(instant)


def tables(runner):
    return {name:[tuple(r) for r in runner.db.execute('SELECT * FROM '+name+' ORDER BY rowid')]
            for name in ('states','slots','fills','funding','observations')}


class Tests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.root=Path(self.tmp.name)
        (self.root/'work').mkdir();(self.root/'market').mkdir()
        seed=self.root/'seed.sqlite';c=sqlite3.connect(seed)
        c.executescript('CREATE TABLE state(id INTEGER PRIMARY KEY,payload TEXT); CREATE TABLE marks(bar TEXT,symbol TEXT,price REAL); CREATE TABLE funding_events(symbol TEXT,timestamp_ms INTEGER); CREATE TABLE equity_history(bar TEXT,equity REAL,pnl REAL);')
        state=fixture.state()
        state['risk_policy_state'].update(daily_day=T.date().isoformat())
        for p in state['positions'].values():p.update(funding_cursor=T.isoformat(),last_mark_at=T.isoformat())
        c.execute('INSERT INTO state VALUES(1,?)',(f.dump(state),));c.executemany('INSERT INTO marks VALUES(?,?,?)',[(T.isoformat(),s,100.) for s in fixture.SYMS]);c.execute('INSERT INTO equity_history VALUES(?,?,?)',(T.isoformat(),10000.,0));c.commit();c.close()
        original=self.root/'original.sqlite';original.write_bytes(seed.read_bytes());c=sqlite3.connect(original)
        c.executemany('INSERT INTO marks VALUES(?,?,?)',[(SLOT.isoformat(),s,100.) for s in fixture.SYMS]);c.commit();c.close()
        protocol=dict(universe=fixture.SYMS,activation=dict(t0=T.isoformat(),end_exclusive=(T+dt.timedelta(days=90)).isoformat()),fork=dict(parent_db_sha256=f.sha(seed),account_ids={'FAST':'offline-test-fast','HALF':'offline-test-half'}),source_code_pins={})
        path=self.root/'protocol.json';path.write_text(f.dump(protocol))
        self.config=dict(protocol=str(path),seed=str(seed),original=str(original),repo=str(self.root),db=str(self.root/'work/pair.sqlite'),derivation=dict(source=str(self.root)))
        with patch.object(f.source,'now',return_value=T):r=f.Runner(self.config,initialize=True)
        with r.db:r.db.execute('INSERT INTO inputs VALUES(?,?)',((SLOT.date()-dt.timedelta(days=1)).isoformat(),f.dump(dict(day=(SLOT.date()-dt.timedelta(days=1)).isoformat(),targets={s:.3 for s in fixture.SYMS},prices=fixture.series(),proposal_id='SYNTHETIC_MECHANICAL_INPUT',snapshot_id='SYNTHETIC_MECHANICAL_INPUT'))))
        self.inherited=r.states();self.receipt=copy.deepcopy(r.receipt);r.close()
        self.config['offline']=dict(scope=d.SCOPE,work_dir=str(self.root/'work'),boundary=SLOT.isoformat(),source_ledger_sha256=f.sha(self.config['db']))
        self.runner=d.OfflineRunner(self.config)
        self.initial_candidate_states=self.runner.states()
        write_book(self.root,book(SLOT-dt.timedelta(minutes=1)));tick(self.runner,SLOT-dt.timedelta(seconds=30))

    def tearDown(self):
        if self.runner:self.runner.close()
        self.tmp.cleanup()

    def action(self, **kwargs):
        write_book(self.root,book(SLOT+dt.timedelta(seconds=30),**kwargs));tick(self.runner,SLOT+dt.timedelta(seconds=45))

    def test_inheritance_and_separate_epoch_do_not_rewrite_legacy_receipt(self):
        self.assertEqual(self.runner.receipt,self.receipt)
        self.assertEqual(self.runner.meta('offline_discrete_boundary')['inherited_states_sha256'],f.p.digest(self.inherited))
        self.assertFalse(self.runner.meta('offline_discrete_boundary')['execution_authorized'])
        for a in f.ARMS:
            self.assertEqual(self.initial_candidate_states[a],self.inherited[a])

    def test_funding_quantity_reference_cursor_and_restart_are_exact(self):
        self.action();rows=[json.loads(r[0]) for r in self.runner.db.execute('SELECT payload FROM funding')]
        self.assertEqual(len(rows),4)
        for row in rows:
            self.assertEqual(row['quantity'],10.);self.assertEqual(row['reference_mark'],100.)
            self.assertEqual(row['reference_at'],SLOT.isoformat());self.assertAlmostEqual(row['amount'],-1.)
        after=tables(self.runner);self.runner.close();self.runner=d.OfflineRunner(self.config)
        tick(self.runner,SLOT+dt.timedelta(seconds=45));self.assertEqual(tables(self.runner),after)

    def test_counters_and_net_fills_persist_without_trial_charges(self):
        before=self.runner.states();self.action();after=self.runner.states()
        rows=[json.loads(r[0]) for r in self.runner.db.execute('SELECT payload FROM fills')]
        for a in f.ARMS:
            fs=[r for r in rows if r['arm']==a]
            self.assertEqual(after[a]['order_count'],before[a]['order_count']+len(fs))
            if any(not x['protective'] for x in fs):
                self.assertEqual(after[a]['risk_policy_state']['daily_entries'],1)
                self.assertEqual(after[a]['risk_policy_state']['last_increase_at'],(SLOT+dt.timedelta(seconds=30)).isoformat())
            self.assertAlmostEqual(sum(p['fees'] for p in after[a]['positions'].values())-sum(p['fees'] for p in before[a]['positions'].values()),sum(x['fee'] for x in fs))
        out=json.loads(self.runner.db.execute('SELECT payload FROM slots').fetchone()[0])
        self.assertIn(out['discrete_status'],('MATCHED','MATCHED_UNCHANGED'))
        self.assertLessEqual(out['risk_gap'],.02);self.assertFalse(out['execution_authorized'])

    def corrective_input(self):
        # Explicit mechanical fixture: different compositions plus whole-unit
        # steps create a known 2.36% post-cost mismatch before correction.
        item=json.loads(self.runner.db.execute('SELECT payload FROM inputs').fetchone()[0])
        item['prices']={'BTCUSDT':[200-i for i in range(61)],'ETHUSDT':[100+i for i in range(61)]}
        with self.runner.db:self.runner.db.execute('UPDATE inputs SET payload=?',(f.dump(item),))
        record=book(SLOT+dt.timedelta(seconds=30))
        for q in record['quotes'].values():q['quantity_step']=1.;q['funding'][-1]['rate']=0.
        return record

    def test_corrected_quantity_is_the_only_net_order_committed(self):
        record=self.corrective_input();record['record_hash']=f.p.digest({k:v for k,v in record.items() if k!='record_hash'})
        write_book(self.root,record);tick(self.runner,SLOT+dt.timedelta(seconds=45))
        out=json.loads(self.runner.db.execute('SELECT payload FROM slots').fetchone()[0])
        self.assertGreater(out['ordinary_risk_gap'],.02);self.assertLessEqual(out['risk_gap'],.02)
        self.assertEqual(out['discrete_status'],'MATCHED');self.assertTrue(out['quantity_adjustments'])
        fills=[json.loads(r[0]) for r in self.runner.db.execute("SELECT payload FROM fills WHERE arm='HALF' AND symbol='BTCUSDT'")]
        self.assertEqual(len(fills),1);self.assertEqual(fills[0]['quantity'],4.)
        self.assertEqual(self.runner.states()['HALF']['positions']['BTCUSDT']['quantity'],14.)
        self.assertAlmostEqual(self.runner.states()['HALF']['positions']['BTCUSDT']['fees'],fills[0]['fee'])

    def test_paired_market_veto_survives_complete_decision_pipeline(self):
        record=self.corrective_input();record['quotes']['ETHUSDT']['asks'][0]['price']=105.
        record['record_hash']=f.p.digest({k:v for k,v in record.items() if k!='record_hash'})
        write_book(self.root,record);tick(self.runner,SLOT+dt.timedelta(seconds=45))
        out=json.loads(self.runner.db.execute('SELECT payload FROM slots').fetchone()[0])
        self.assertTrue(out['paired_entry_veto']);self.assertEqual(out['shared_entry_block'],'paired_market_or_minimum_veto')
        self.assertTrue(all(json.loads(r[0])['protective'] for r in self.runner.db.execute('SELECT payload FROM fills')))

    def test_one_arm_risk_veto_is_preserved_across_restart(self):
        states=self.runner.states();states['FAST']['risk_policy_state']['daily_entries']=1
        with self.runner.db:self.runner.db.execute('UPDATE states SET payload=? WHERE arm=?',(f.dump(states['FAST']),'FAST'))
        self.runner.close();self.runner=d.OfflineRunner(self.config);self.action()
        out=json.loads(self.runner.db.execute('SELECT payload FROM slots').fetchone()[0])
        self.assertEqual(out['blocks']['FAST'],'one_risk_rebalance_per_UTC_day')
        self.assertTrue(all(json.loads(r[0])['protective'] for r in self.runner.db.execute('SELECT payload FROM fills')))

    def test_missing_funding_blocks_increases_and_does_not_advance_cursors(self):
        before=self.runner.states();self.action(funding=False)
        out=json.loads(self.runner.db.execute('SELECT payload FROM slots').fetchone()[0])
        self.assertEqual(out['discrete_status'],'UNQUALIFIED_FUNDING');self.assertIsNone(out['risk_gap'])
        self.assertEqual(self.runner.db.execute('SELECT COUNT(*) FROM funding').fetchone()[0],0)
        for a,state in self.runner.states().items():
            for s,p in state['positions'].items():self.assertEqual(p['funding_cursor'],before[a]['positions'][s]['funding_cursor'])
        self.assertTrue(all(json.loads(r[0])['protective'] for r in self.runner.db.execute('SELECT payload FROM fills')))

    def test_missing_funding_reference_is_neutral(self):
        c=sqlite3.connect(self.config['original']);c.execute('DELETE FROM marks');c.commit();c.close()
        before=self.runner.states();self.action()
        self.assertIn('funding_reference_missing',self.runner.meta('funding_debt'))
        self.assertEqual(self.runner.db.execute('SELECT COUNT(*) FROM funding').fetchone()[0],0)
        for a in f.ARMS:
            self.assertEqual(self.runner.states()[a]['positions']['BTCUSDT']['funding_cursor'],before[a]['positions']['BTCUSDT']['funding_cursor'])

    def test_funding_debt_recovers_original_settlement_quantity_exactly_once(self):
        self.action(funding=False)
        for _ in range(2):
            write_book(self.root,book(SLOT+dt.timedelta(minutes=5)))
            tick(self.runner,SLOT+dt.timedelta(minutes=5,seconds=10))
            self.runner.close();self.runner=d.OfflineRunner(self.config)
        self.assertIsNone(self.runner.meta('funding_debt'))
        rows=[json.loads(r[0]) for r in self.runner.db.execute('SELECT payload FROM funding')]
        self.assertEqual(len(rows),4)
        self.assertTrue(all(r['quantity']==10. and r['amount']==-1. for r in rows))

    def test_sql_failure_on_half_rolls_back_both_states_slot_fills_and_funding(self):
        before=tables(self.runner)
        self.runner.db.execute("CREATE TRIGGER break_half BEFORE UPDATE ON states WHEN new.arm='HALF' AND json_extract(new.payload,'$.last_discrete_plan_version') IS NOT NULL BEGIN SELECT RAISE(ABORT,'test storage fault'); END;")
        with self.assertRaises(sqlite3.IntegrityError):self.action()
        self.assertEqual(tables(self.runner),before)
        self.runner.db.execute('DROP TRIGGER break_half');self.runner.close();self.runner=d.OfflineRunner(self.config)
        self.action();self.assertEqual(self.runner.db.execute('SELECT COUNT(*) FROM slots').fetchone()[0],1)

    def test_sql_failure_on_funding_rolls_back_preceding_states_and_fills(self):
        before=tables(self.runner)
        self.runner.db.execute("CREATE TRIGGER break_funding BEFORE INSERT ON funding BEGIN SELECT RAISE(ABORT,'test funding storage fault'); END;")
        with self.assertRaises(sqlite3.IntegrityError):self.action()
        self.assertEqual(tables(self.runner),before)

    def test_process_kill_during_commit_recovers_without_half_state(self):
        before=tables(self.runner);self.runner.close();self.runner=None
        write_book(self.root,book(SLOT+dt.timedelta(seconds=30)))
        command='''import json,os,datetime,sys
from unittest.mock import patch
from octobot.ai_strategy_lab import v13_fork_discrete_offline as d
r=d.OfflineRunner(json.loads(sys.argv[1]))
r.db.execute('PRAGMA cache_size=1')
r.db.execute('CREATE TABLE crash_spill(id INTEGER PRIMARY KEY,payload TEXT)')
with r.db:r.db.executemany('INSERT INTO crash_spill VALUES(?,?)',[(i,'a'*8192) for i in range(256)])
r.db.create_function('die',0,lambda:os._exit(91))
r.db.execute("CREATE TRIGGER crash_half BEFORE UPDATE ON states WHEN new.arm='HALF' AND json_extract(new.payload,'$.last_discrete_plan_version') IS NOT NULL BEGIN UPDATE crash_spill SET payload=replace(payload,'a','b'); SELECT die(); END;")
at=datetime.datetime.fromisoformat(sys.argv[2])
with patch.object(d.f.source,'now',return_value=at):r.tick(at)
'''
        run=subprocess.run([sys.executable,'-c',command,json.dumps(self.config),(SLOT+dt.timedelta(seconds=45)).isoformat()],capture_output=True,text=True,timeout=15)
        self.assertEqual(run.returncode,91,run.stderr)
        journal=Path(self.config['db']+'-journal');self.assertTrue(journal.is_file());self.assertGreater(journal.stat().st_size,0)
        self.runner=d.OfflineRunner(self.config)
        self.assertEqual(tables(self.runner),before)
        self.assertEqual(self.runner.db.execute("SELECT COUNT(*) FROM crash_spill WHERE payload LIKE 'b%'").fetchone()[0],0)
        self.assertEqual(self.runner.db.execute('PRAGMA integrity_check').fetchone()[0],'ok')
        self.runner.db.execute('DROP TRIGGER crash_half');self.action()
        after=tables(self.runner);self.runner.close();self.runner=d.OfflineRunner(self.config)
        tick(self.runner,SLOT+dt.timedelta(seconds=45));self.assertEqual(tables(self.runner),after)

    def test_position_generation_and_identity_on_opening_are_persisted(self):
        states=self.runner.states()
        with self.runner.db:
            for a in f.ARMS:
                for pos in states[a]['positions'].values():pos['quantity']=0.
                self.runner.db.execute('UPDATE states SET payload=? WHERE arm=?',(f.dump(states[a]),a))
        self.action()
        for row in self.runner.db.execute('SELECT payload FROM fills'):
            fill=json.loads(row[0]);pos=self.runner.states()[fill['arm']]['positions'][fill['symbol']]
            self.assertEqual(pos['generation'],3)
            self.assertEqual(fill['position_id'],f.p.digest(dict(account=states[fill['arm']]['fork_account'],symbol=fill['symbol'],generation=3)))

    def test_missing_inputs_deny_fills_but_preserve_valid_funding(self):
        with self.runner.db:self.runner.db.execute('DELETE FROM inputs')
        self.action()
        self.assertEqual(self.runner.db.execute('SELECT status FROM slots').fetchone()[0],'DENIED')
        self.assertEqual(self.runner.db.execute('SELECT COUNT(*) FROM fills').fetchone()[0],0)
        self.assertEqual(self.runner.db.execute('SELECT COUNT(*) FROM funding').fetchone()[0],4)

    def test_late_slot_is_not_retroactively_executed(self):
        write_book(self.root,book(SLOT+dt.timedelta(minutes=3)));tick(self.runner,SLOT+dt.timedelta(minutes=3))
        self.assertEqual(self.runner.db.execute('SELECT status FROM slots').fetchone()[0],'MISSED')
        self.assertEqual(self.runner.db.execute('SELECT COUNT(*) FROM fills').fetchone()[0],0)

    def test_deadline_crossed_during_calculation_leaves_no_decision_effects(self):
        before=tables(self.runner);write_book(self.root,book(SLOT+dt.timedelta(seconds=30)))
        with patch.object(f.source,'now',return_value=SLOT+dt.timedelta(minutes=3)):
            with self.assertRaisesRegex(ValueError,'execution_deadline_expired'):
                self.runner.tick(SLOT+dt.timedelta(seconds=45))
        self.assertEqual(tables(self.runner),before)

    def test_scope_and_changed_epoch_identity_are_rejected(self):
        for mode in ('scope','boundary','source_hash','missing_copy'):
            c=copy.deepcopy(self.config)
            if mode=='scope':c.pop('offline')
            if mode=='boundary':c['offline']['boundary']=(SLOT+dt.timedelta(days=1)).isoformat()
            if mode=='source_hash':c['offline']['source_ledger_sha256']='0'*64
            if mode=='missing_copy':c['db']=str(self.root/'work/missing.sqlite')
            with self.subTest(mode=mode),self.assertRaises(ValueError):d.OfflineRunner(c)


if __name__=='__main__':unittest.main()
