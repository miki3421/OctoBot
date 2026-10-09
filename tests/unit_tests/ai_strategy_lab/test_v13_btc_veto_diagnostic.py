"""Explicit synthetic books and minima; no KuCoin order-admissibility claim."""
import gzip
import hashlib
import importlib.util
import json
from pathlib import Path
import sqlite3
import tempfile
import unittest

spec = importlib.util.spec_from_file_location('veto', Path(__file__).resolve().parents[3] / 'scripts/analyze_v13_btc_veto.py')
veto = importlib.util.module_from_spec(spec)
spec.loader.exec_module(veto)


class VetoTests(unittest.TestCase):
    def fixture(self, root, future_book=False):
        execution = root / 'execution.sqlite'
        approvals = root / 'approvals.sqlite'
        books = root / 'books'
        books.mkdir()
        names = ['BTCUSDT','ALTUSDT','NEWUSDT']
        quote = dict(bids=[dict(price=100.,base_quantity=100)],asks=[dict(price=100.02,base_quantity=100)],
            price_tick=.01,quantity_step=.001,fee_rate=.0006,timestamp='2026-01-02T00:00:10Z')
        book = dict(scope='RESEARCH_SIMULATION_ONLY',observed_at_start='2026-01-02T00:00:10Z',
            observed_at_end='2026-01-02T00:01:00Z' if future_book else '2026-01-02T00:00:15Z',
            quotes={s:quote for s in names})
        digest = hashlib.sha256(json.dumps(book,sort_keys=True,separators=(',',':')).encode()).hexdigest()
        book['record_hash'] = digest
        (books/(digest+'.json.gz')).write_bytes(gzip.compress(json.dumps(book).encode()))
        with sqlite3.connect(execution) as db:
            db.executescript('CREATE TABLE orders(id,bar,symbol,quantity,price,fee,status,market_hash,decision_hash);'
                'CREATE TABLE equity_history(bar,equity);CREATE TABLE funding_events(symbol,timestamp_ms,rate,reference_mark,quantity,amount);'
                'CREATE TABLE marks(bar,symbol,price);CREATE TABLE state(id,payload);')
            fills=[(1,'2026-01-01T00:00:30Z','BTCUSDT',3,100,.18,'filled',None,'initial'),
                (2,'2026-01-01T00:00:30Z','ALTUSDT',2,100,.12,'filled',None,'initial'),
                (3,'2026-01-02T00:00:30Z','BTCUSDT',-1,100,.06,'filled',digest,'drop'),
                (4,'2026-01-02T00:00:30Z','NEWUSDT',1,100,.06,'filled',digest,'drop')]
            db.executemany('INSERT INTO orders VALUES(?,?,?,?,?,?,?,?,?)',fills)
            db.executemany('INSERT INTO equity_history VALUES(?,?)',[
                ('2026-01-01T00:00:30Z',9999.7),('2026-01-02T00:00:30Z',9999.58),
                ('2026-01-03T00:00:30Z',9899.58)])
            for day,price in [('2026-01-01',100),('2026-01-02',100),('2026-01-03',80)]:
                db.executemany('INSERT INTO marks VALUES(?,?,?)',[(day+'T00:00:30Z',s,price) for s in names])
            db.execute('INSERT INTO state VALUES(1,?)',(json.dumps(dict(mode='trend_v13_paper_v2',research_epoch='SYNTHETIC',positions={s:{} for s in names})),))
        db.close()
        with sqlite3.connect(approvals) as db:
            db.execute('CREATE TABLE approvals(payload)')
            for at,day,decision,weights in [('2026-01-01T00:00:05Z','2025-12-31','initial',dict(zip(names,[.03,.02,0]))),
                ('2026-01-02T00:00:05Z','2026-01-01','drop',dict(zip(names,[.02,.02,.01])))]:
                db.execute('INSERT INTO approvals VALUES(?)',(json.dumps(dict(issued_at=at,day=day,decision_id=decision,
                    targets=weights,scope='RESEARCH_SIMULATION_ONLY',epoch='SYNTHETIC')),))
        db.close()
        return execution,approvals,books

    def test_matched_orders_preserve_bounds(self):
        self.assertEqual(veto.matched_quantity(1,-2,True),-1)
        self.assertEqual(veto.matched_quantity(0,2,True),0)
        self.assertEqual(veto.matched_quantity(1,2,False),2)
        with self.assertRaises(ValueError):veto.matched_quantity(-1,1,True)

    def test_replay_costs_and_read_only_inputs(self):
        with tempfile.TemporaryDirectory() as tmp:
            files=self.fixture(Path(tmp));before=[hashlib.sha256(p.read_bytes()).hexdigest() for p in files[:2]]
            result=veto.study(*files)
            self.assertEqual(result['baseline_final_error'],0)
            self.assertAlmostEqual(result['arms']['baseline']['equity'],9899.58)
            self.assertAlmostEqual(result['arms']['veto_entries']['equity'],9919.64)
            self.assertGreater(result['arms']['veto_exit']['equity'],9998)
            self.assertGreater(result['arms']['veto_exit']['fees'],.3)
            self.assertEqual(result['triggers'][0]['closed_symbols'],['ALTUSDT','BTCUSDT'])
            self.assertEqual(before,[hashlib.sha256(p.read_bytes()).hexdigest() for p in files[:2]])

    def test_future_book_is_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            files=self.fixture(Path(tmp),future_book=True)
            with self.assertRaisesRegex(ValueError,'noncausal_trigger_book'):veto.study(*files)

    def test_funding_follows_actual_held_quantities(self):
        with tempfile.TemporaryDirectory() as tmp:
            files=self.fixture(Path(tmp))
            db=sqlite3.connect(files[0])
            at=int(veto.timestamp('2026-01-02T12:00:00Z')*1000)
            db.execute('INSERT INTO funding_events VALUES(?,?,?,?,?,?)',('BTCUSDT',at,.001,100,2,-.2))
            db.execute('UPDATE equity_history SET equity=equity-.2 WHERE bar="2026-01-03T00:00:30Z"')
            db.commit();db.close()
            result=veto.study(*files)
            self.assertAlmostEqual(result['arms']['baseline']['funding'],-.2)
            self.assertAlmostEqual(result['arms']['veto_entries']['funding'],-.2)
            self.assertEqual(result['arms']['veto_exit']['funding'],0)

    def test_tampered_book_is_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            files=self.fixture(Path(tmp));path=next(files[2].iterdir());value=json.loads(gzip.decompress(path.read_bytes()));value['scope']='OPERATIONAL'
            path.write_bytes(gzip.compress(json.dumps(value).encode()))
            with self.assertRaisesRegex(ValueError,'market_binding'):veto.study(*files)
