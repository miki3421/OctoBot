import copy
import json
import unittest
import tempfile
import sqlite3
from pathlib import Path
import v13_dynamic_funding as funding

START='2026-10-08T00:15:00Z'
AT='2026-10-08T08:00:00Z'
NOW='2026-10-08T09:00:00Z'


def history():
    return [dict(at=START,positions={'A':{'BTCUSDT':2.},'B':{'BTCUSDT':-3.},'C':{}}),
            dict(at=AT,positions={'A':{},'B':{},'C':{}})]


def estimate(mark=None):
    return dict(scope='FUNDING_ESTIMATE_DIAGNOSTIC_ONLY',events=[dict(
        id='transport-id',symbol='BTCUSDT',at=AT,rate=.001,mark=mark,
        status='ESTIMATED_PRIOR_BOOK_MIDPOINT' if mark is not None else 'MARK_UNRESOLVED',
        mark_source_hash='a'*64,mark_observed_at='2026-10-08T07:59:00Z')])


class FundingTests(unittest.TestCase):
    def test_store_restart_replay_and_failed_write(self):
        with tempfile.TemporaryDirectory() as tmp:
            path=Path(tmp)/'offline.sqlite'
            store=funding.OfflineStore(path,create=True)
            request=dict(id='pending',scope=funding.SCOPE,estimate=estimate(),history=history(),start=START,as_of=NOW)
            pending=store.commit(request)
            store.close()
            store=funding.OfflineStore(path)
            self.assertEqual(store.commit(request),pending)
            changed=copy.deepcopy(request);changed['estimate']=estimate(100.)
            with self.assertRaisesRegex(ValueError,'batch_conflict'):store.commit(changed)
            changed['id']='resolved'
            store.db.execute("CREATE TRIGGER fail_write BEFORE INSERT ON batches BEGIN SELECT RAISE(ABORT,'simulated storage failure'); END")
            with self.assertRaises(sqlite3.DatabaseError):store.commit(changed)
            self.assertFalse(store.db.in_transaction)
            self.assertEqual(store.db.execute('SELECT COUNT(*) FROM batches').fetchone()[0],1)
            self.assertEqual(store.commit(request),pending)
            store.db.execute('DROP TRIGGER fail_write')
            resolved=store.commit(changed)
            self.assertEqual(len(resolved['adjustments']),1)
            store.close()
            store=funding.OfflineStore(path)
            self.assertEqual(store.commit(changed),resolved)
            changed['id']='repeat-event'
            self.assertEqual(store.commit(changed)['adjustments'],[])
            self.assertEqual(store.db.execute('PRAGMA integrity_check').fetchone()[0],'ok')
            store.close()

    def test_store_refuses_overwrite_missing_and_foreign_database(self):
        with tempfile.TemporaryDirectory() as tmp:
            path=Path(tmp)/'foreign.sqlite'
            with self.assertRaisesRegex(ValueError,'offline_store_missing'):funding.OfflineStore(path)
            db=sqlite3.connect(path);db.execute('CREATE TABLE marker(scope TEXT)');db.execute("INSERT INTO marker VALUES ('operational')");db.commit();db.close()
            before=path.read_bytes()
            with self.assertRaises(FileExistsError):funding.OfflineStore(path,create=True)
            with self.assertRaisesRegex(ValueError,'not_offline_funding_store'):funding.OfflineStore(path)
            self.assertEqual(path.read_bytes(),before)

    def test_pending_is_not_zero_and_flat_has_no_cost(self):
        result=funding.reconcile(None,estimate(),history(),start=START,as_of=NOW)
        amounts=next(iter(result['entries'].values()))['amounts']
        self.assertEqual(amounts,{'A':None,'B':None,'C':0.})
        for arm in result['arms'].values():
            self.assertIsNone(arm['net_funding'])
            self.assertFalse(arm['net_equity_complete'])
        self.assertFalse(result['risk_increase_allowed'])

    def test_late_resolution_restart_and_economic_replay(self):
        pending=funding.reconcile(None,estimate(),history(),start=START,as_of=NOW)
        restored=json.loads(json.dumps(pending))
        result=funding.reconcile(restored,estimate(100.),history(),start=START,as_of=NOW)
        self.assertEqual(result['adjustments'][0]['amounts'],{'A':-.2,'B':.3,'C':0.})
        self.assertTrue(result['adjustments'][0]['resolves_pending'])
        self.assertEqual(pending,restored)
        replay=estimate(100.);replay['events'][0]['id']='different-transport'
        replay['events'][0]['at']='2026-10-08T08:00:00+00:00'
        again=funding.reconcile(result,replay,history(),start=START,as_of=NOW)
        self.assertEqual(again['adjustments'],[])
        self.assertEqual(again['arms'],result['arms'])
        self.assertEqual(again['settlement_coverage'],'UNKNOWN')

    def test_conflicts_history_rewrite_and_tamper_rejected(self):
        result=funding.reconcile(None,estimate(100.),history(),start=START,as_of=NOW)
        before=copy.deepcopy(result)
        with self.assertRaisesRegex(ValueError,'funding_conflict'):
            funding.reconcile(result,estimate(101.),history(),start=START,as_of=NOW)
        h=history();h[0]['positions']['A']['BTCUSDT']=5.
        with self.assertRaisesRegex(ValueError,'position_history_rewritten'):
            funding.reconcile(result,estimate(),h,start=START,as_of=NOW)
        bad=copy.deepcopy(result);bad['entries']={}
        with self.assertRaisesRegex(ValueError,'invalid_previous_state'):
            funding.reconcile(bad,estimate(),history(),start=START,as_of=NOW)
        self.assertEqual(result,before)

    def test_prestart_excluded_and_future_or_noncausal_rejected(self):
        e=estimate();e['events'][0]['at']=START
        self.assertFalse(funding.reconcile(None,e,history(),start=START,as_of=NOW)['entries'])
        e=estimate(100.);e['events'][0]['mark_observed_at']=AT
        with self.assertRaisesRegex(ValueError,'noncausal_mark'):
            funding.reconcile(None,e,history(),start=START,as_of=NOW)
        e=estimate();e['events'][0]['at']='2026-10-09T00:00:00Z'
        with self.assertRaisesRegex(ValueError,'future_settlement'):
            funding.reconcile(None,e,history(),start=START,as_of=NOW)
