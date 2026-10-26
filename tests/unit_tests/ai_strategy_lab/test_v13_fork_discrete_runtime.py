"""Authority/boundary tests; all accounts and dates here are synthetic."""
import copy
import datetime as dt
import json
from pathlib import Path
import sqlite3
import unittest
from unittest.mock import patch

import test_v13_fork_discrete_offline as fixture
from octobot.ai_strategy_lab import v13_fork_discrete_runtime as r

f=r.f


class Tests(unittest.TestCase):
    def setUp(self):
        self.fixture=fixture.Tests(methodName='runTest');self.fixture.setUp()
        self.fixture.runner.close();self.fixture.runner=None
        self.c=copy.deepcopy(self.fixture.config);self.c.pop('offline')
        self.c['repo']=str(Path(f.__file__).resolve().parents[2])
        db=sqlite3.connect(self.c['db'])
        db.execute("DELETE FROM meta WHERE key IN ('offline_discrete_identity','offline_discrete_boundary')")
        db.commit();db.close()
        self.boundary=fixture.SLOT+dt.timedelta(days=1)
        self.path=self.fixture.root/'grant.json'
        db=f.ro(self.c['db']);self.states={row['arm']:json.loads(row['payload']) for row in db.execute('SELECT * FROM states')}
        self.receipt=json.loads(db.execute("SELECT payload FROM meta WHERE key='receipt'").fetchone()[0])
        identity=json.loads(db.execute("SELECT payload FROM meta WHERE key='identity'").fetchone()[0]);db.close()
        self.g=dict(schema=1,version=r.VERSION,scope=r.SCOPE,operator_action='AUTHORIZE_EXISTING_PAIR_DISCRETE_REVISION',
                    real_orders_authorized=False,new_accounts=False,boundary=self.boundary.isoformat(),issued_at=fixture.T.isoformat(),
                    legacy_identity=identity,account_ids=self.receipt['account_ids'],end_exclusive=self.receipt['end_exclusive'],
                    stopped_ledger_sha256=f.sha(self.c['db']),states_sha256=f.p.digest(self.states),
                    code_pins={'octobot/ai_strategy_lab/v13_fork_discrete_runtime.py':f.sha(r.__file__)})
        self.save_grant();self.runner=None

    def save_grant(self):
        if self.path.exists():self.path.chmod(0o644)
        self.path.write_text(f.dump(self.g));self.path.chmod(0o444)
        self.c['discrete_revision']=dict(grant=str(self.path),grant_sha256=f.sha(self.path))

    def open(self,at=None):
        with patch.object(f.source,'now',return_value=at or fixture.SLOT):self.runner=r.Runner(self.c)
        return self.runner

    def tearDown(self):
        if self.runner:self.runner.close()
        self.fixture.tearDown()

    def test_install_preserves_full_states_legacy_identity_and_receipt(self):
        runner=self.open();self.assertEqual(runner.states(),self.states);self.assertEqual(runner.receipt,self.receipt)
        self.assertEqual(runner.meta('discrete_revision')['inherited_states_sha256'],f.p.digest(self.states))

    def test_boundary_keeps_legacy_before_and_corrects_only_after(self):
        runner=self.open();prices={'BTCUSDT':[200-i for i in range(61)],'ETHUSDT':[100+i for i in range(61)]}
        targets={s:.3 for s in fixture.fixture.SYMS};filters={s:'FULL' for s in targets}
        for at in (self.boundary-dt.timedelta(days=1),self.boundary):
            states=copy.deepcopy(self.states)
            for s in states.values():s['risk_policy_state'].update(daily_day=at.date().isoformat(),daily_entries=0)
            record=fixture.book(at)
            for q in record['quotes'].values():q['quantity_step']=1.;q['funding']=[dict(timestamp_ms=int(at.timestamp()*1000),rate=0.)]
            record['record_hash']=f.p.digest({k:v for k,v in record.items() if k!='record_hash'})
            args=(states,targets,prices,filters,record,at,None)
            result=runner.apply_decision(*args)
            if at<self.boundary:self.assertEqual(result,f.apply_pair(*args))
            else:
                self.assertEqual(result[3]['policy_revision'],r.VERSION);self.assertEqual(result[3]['discrete_status'],'MATCHED')
                self.assertLessEqual(result[3]['risk_gap'],.02);self.assertTrue(result[3]['quantity_adjustments'])

    def test_reopening_preserves_new_counters_without_requiring_old_file_hash(self):
        runner=self.open();s=runner.states();s['FAST']['risk_policy_state']['daily_entries']=1
        with runner.db:runner.db.execute('UPDATE states SET payload=? WHERE arm=?',(f.dump(s['FAST']),'FAST'))
        runner.close();self.runner=None;self.assertEqual(self.open(at=self.boundary).states(),s)

    def test_late_initial_install_is_rejected_without_any_reset(self):
        with self.assertRaisesRegex(ValueError,'cannot_start_retroactively'):self.open(at=self.boundary)
        db=f.ro(self.c['db']);self.assertIsNone(db.execute("SELECT 1 FROM meta WHERE key='discrete_revision'").fetchone());db.close()

    def test_stopped_copy_binding_changed_is_rejected(self):
        db=sqlite3.connect(self.c['db']);db.execute("INSERT INTO meta VALUES('unexpected','{}')");db.commit();db.close()
        with self.assertRaisesRegex(ValueError,'handoff_ledger_changed'):self.open()

    def test_offline_harness_ledger_cannot_be_promoted(self):
        db=sqlite3.connect(self.c['db']);db.execute("INSERT INTO meta VALUES('offline_discrete_identity','{}')");db.commit();db.close()
        with self.assertRaisesRegex(ValueError,'offline_work_ledger'):self.open()

    def test_foreign_account_or_legacy_identity_is_rejected(self):
        for kind in ('account','identity','horizon','state'):
            original=copy.deepcopy(self.g)
            if kind=='account':self.g['account_ids']['FAST']='foreign'
            if kind=='identity':self.g['legacy_identity']['runner_sha256']='0'*64
            if kind=='horizon':self.g['end_exclusive']=self.boundary.isoformat()
            if kind=='state':self.g['states_sha256']='0'*64
            self.g['stopped_ledger_sha256']=f.sha(self.c['db']);self.save_grant()
            with self.subTest(kind=kind),self.assertRaises(ValueError):self.open()
            self.g=original

    def test_changed_grant_and_writable_or_symlinked_grant_are_rejected(self):
        self.path.chmod(0o644);self.path.write_text('{}')
        with self.assertRaisesRegex(ValueError,'grant_hash'):self.open()
        self.save_grant();self.path.chmod(0o666)
        with self.assertRaisesRegex(ValueError,'root_owned_release'):self.open()

    def test_changed_revision_after_install_is_rejected(self):
        self.open().close();self.runner=None;self.g['boundary']=(self.boundary+dt.timedelta(days=1)).isoformat();self.save_grant()
        with self.assertRaisesRegex(ValueError,'continuation_changed'):self.open()

    def test_missing_ledger_is_not_created(self):
        self.c['db']=str(self.fixture.root/'missing.sqlite')
        with self.assertRaisesRegex(ValueError,'existing_pair_required'):self.open()
        self.assertFalse(Path(self.c['db']).exists())

    def test_cached_synthetic_or_malformed_input_is_not_trading_authority(self):
        runner=self.open()
        with self.assertRaises(ValueError):runner.prepare_input(fixture.SLOT)
        item=json.loads(runner.db.execute('SELECT payload FROM inputs').fetchone()[0]);item.update(proposal_id='a'*64,snapshot_id='b'*64)
        with runner.db:runner.db.execute('UPDATE inputs SET payload=?',(f.dump(item),))
        self.assertEqual(runner.prepare_input(fixture.SLOT),item)
        item['fixture_role']='SYNTHETIC'
        with runner.db:runner.db.execute('UPDATE inputs SET payload=?',(f.dump(item),))
        with self.assertRaisesRegex(ValueError,'real_daily_input'):runner.prepare_input(fixture.SLOT)

    def test_projection_counts_preserve_legacy_and_new_denominators(self):
        runner=self.open()
        with runner.db:
            runner.db.execute('INSERT INTO slots VALUES(?,?,?)',((self.boundary-dt.timedelta(days=1)).isoformat(),'EXECUTED',f.dump(dict(risk_matched=False))))
            runner.db.execute('INSERT INTO slots VALUES(?,?,?)',(self.boundary.isoformat(),'EXECUTED',f.dump(dict(risk_matched=True,policy_revision=r.VERSION))))
        with patch.object(f.source,'now',return_value=self.boundary+dt.timedelta(minutes=1)):value=r.revision_summary(runner)
        self.assertEqual(value['legacy']['evaluated'],1);self.assertEqual(value['legacy']['matched'],0)
        self.assertEqual(value['current']['evaluated'],1);self.assertEqual(value['current']['matched'],1)
        self.assertTrue(value['history_preserved']);self.assertEqual(value['account_ids'],self.receipt['account_ids'])


if __name__=='__main__':unittest.main()
