import copy
from pathlib import Path
import sqlite3
import tempfile
import unittest
import v13_dynamic_cash as cash
from test_v13_dynamic_funding import START, NOW, estimate


def request(ident='initial', mark=None):
    fills=[dict(scope='SIMULATED_FILL_IMPORT_ONLY',id=a,arm=a,symbol='BTCUSDT',
                at='2026-10-08T01:00:00Z',quantity=q,price=100.,fee=.1)
           for a,q in [('A',2.),('B',-3.)]]
    return dict(scope=cash.SCOPE,id=ident,start=START,as_of=NOW,fills=fills,estimate=estimate(mark))


class CashTests(unittest.TestCase):
    def test_cash_fees_pending_and_late_funding(self):
        first=cash.advance(None,request())
        self.assertAlmostEqual(first['arms']['A']['cash'],9799.9)
        self.assertAlmostEqual(first['arms']['B']['cash'],10299.9)
        self.assertIsNone(first['arms']['A']['net_equity'])
        later=request('resolved',100.);later['fills']=[]
        resolved=cash.advance(first,later)
        self.assertAlmostEqual(resolved['arms']['A']['cash'],9799.7)
        self.assertAlmostEqual(resolved['arms']['B']['cash'],10300.2)
        self.assertEqual(resolved['arms']['C']['cash'],10000.)
        self.assertEqual(cash.advance(resolved,later)['arms'],resolved['arms'])
        self.assertEqual(first['arms']['A']['funding'],0.)

    def test_exact_settlement_close_uses_prior_quantity(self):
        r=request(mark=100.)
        r['fills'].append(dict(r['fills'][0],id='close',at='2026-10-08T08:00:00Z',quantity=-2.,price=110.))
        result=cash.advance(None,r)
        self.assertEqual(result['arms']['A']['positions']['BTCUSDT'],0.)
        self.assertAlmostEqual(result['arms']['A']['cash'],10019.6)
        self.assertAlmostEqual(result['arms']['A']['funding'],-.2)

    def test_cash_and_funding_rollback_restart_replay(self):
        with tempfile.TemporaryDirectory() as tmp:
            p=Path(tmp)/'cash.sqlite';store=cash.CashStore(p,create=True)
            original=store.commit(request());store.close()
            store=cash.CashStore(p)
            self.assertEqual(store.commit(request()),original)
            r=request('resolved',100.);r['fills']=[]
            store.db.execute("CREATE TRIGGER fail BEFORE INSERT ON batches BEGIN SELECT RAISE(ABORT,'failure'); END")
            with self.assertRaises(sqlite3.DatabaseError):store.commit(r)
            self.assertEqual(store.commit(request()),original)
            self.assertEqual(store.db.execute('SELECT COUNT(*) FROM batches').fetchone()[0],1)
            store.db.execute('DROP TRIGGER fail')
            resolved=store.commit(r);store.close();store=cash.CashStore(p)
            self.assertEqual(store.commit(r),resolved)
            r['id']='new-replay'
            self.assertEqual(store.commit(r)['arms'],resolved['arms'])
            self.assertEqual(store.db.execute('PRAGMA integrity_check').fetchone()[0],'ok')
            store.close()

    def test_late_fill_conflict_and_wrong_scope_denied(self):
        first=cash.advance(None,request());before=copy.deepcopy(first)
        for mode in ('conflict','late','scope'):
            r=request()
            if mode=='conflict':r['fills'][0]['price']=99.
            elif mode=='late':r['fills'][0]['id']='late'
            else:r['fills'][0]['scope']='REAL_ORDER'
            with self.assertRaises(ValueError):cash.advance(first,r)
        self.assertEqual(first,before)
