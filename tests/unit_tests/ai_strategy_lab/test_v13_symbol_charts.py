"""Position semantics and read-only source checks, including synthetic shorts."""
import copy
import datetime as dt
import json
from pathlib import Path
import sqlite3
import tempfile
import unittest
import v13_symbol_charts as c

NOW = dt.datetime(2032, 5, 10, 12, tzinfo=dt.timezone.utc)


def fixture():
    state = {'mode':'trend_v13_paper_v2','research_epoch':'synthetic-test',
             'activation_at':'2032-05-10T08:00:00+00:00','last_success_at':NOW.isoformat(),
             'order_count':2,'positions':{'BTCUSDT':{'quantity':0.6},'ETHUSDT':{'quantity':0}}}
    fills = [{'id':i+1,'symbol':'BTCUSDT','action':'BUY' if q>0 else 'SELL','quantity':q,'price':100+i,
              'bar':f'2032-05-10T{9+i:02}:00:00+00:00',
              'recorded_at':f'2032-05-10T{9+i:02}:00:02+00:00'} for i,q in enumerate([1.,-.4])]
    marks = [{'bar':f'2032-05-10T{h:02}:00:00+00:00','price':100+h} for h in [9,10,11]]
    return state,fills,marks


class ChartTests(unittest.TestCase):
    def test_all_long_short_and_reversal_transitions(self):
        for old,delta,kind,label,after in [
            (0,1,'open','Apertura long',1),(0,-1,'open','Apertura short',-1),
            (1,1,'increase','Aumento long',2),(-1,-1,'increase','Aumento short',-2),
            (1,-.4,'reduce','Riduzione long',.6),(-1,.4,'reduce','Riduzione short',-.6),
            (1,-1,'close','Chiusura long',0),(-1,1,'close','Chiusura short',0),
            (1,-1.5,'reverse','Chiusura long + apertura short',-.5),
            (-1,1.5,'reverse','Chiusura short + apertura long',.5)]:
            with self.subTest(old=old,delta=delta):
                r=c.transition(old,delta);self.assertEqual((r['kind'],r['label'],r['after']),(kind,label,after))
                self.assertAlmostEqual(r['closed_quantity']+r['opened_quantity'],abs(delta))

    def test_small_positions_and_float_closure(self):
        self.assertEqual(c.transition(0,1e-12)['kind'],'open')
        self.assertEqual(c.transition(.30000000000000004,-.3)['after'],0)
        for q in [0,float('nan'),float('inf'),True]:
            with self.assertRaises(ValueError):c.transition(0,q)

    def test_sell_reduces_long_with_exact_execution_time_and_gaps(self):
        s,f,m=fixture();r=c.project(s,f,m,'BTCUSDT',NOW)
        self.assertEqual(r['fills'][1]['label'],'Riduzione long')
        self.assertEqual(r['fills'][1]['before'],1);self.assertEqual(r['fills'][1]['after'],.6)
        self.assertEqual(r['fills'][1]['time'],f[1]['recorded_at'])
        self.assertEqual(r['gaps'],2);self.assertTrue(r['points'][1]['gap_before'])

    def test_bad_history_and_values_fail_closed(self):
        for kind in ['missing','side','price','mark','scope','future','ids','quantity']:
            s,f,m=fixture()
            if kind=='missing':f=f[1:]
            if kind=='side':f[1]['action']='BUY'
            if kind=='price':f[0]['price']=float('nan')
            if kind=='mark':m[0]['price']=-1
            if kind=='scope':s['mode']='LIVE'
            if kind=='future':f[0]['recorded_at']='2032-05-11T00:00:00+00:00'
            if kind=='ids':f[1]['id']=f[0]['id']
            if kind=='quantity':s['positions']['BTCUSDT']['quantity']=2
            with self.subTest(kind=kind),self.assertRaises(ValueError):c.project(s,f,m,'BTCUSDT',NOW)

    def test_empty_prices_and_no_fills_are_explicit_not_fabricated(self):
        s,f,m=fixture();r=c.project(s,[],[],'ETHUSDT',NOW)
        self.assertEqual(r['points'],[]);self.assertEqual(r['fills'],[]);self.assertEqual(r['position'],'FLAT')
        r=c.project(s,f,[],'BTCUSDT',NOW);self.assertEqual(len(r['fills']),2);self.assertEqual(r['points'],[])

    def test_stale_history_and_missing_execution_timestamp_are_labelled(self):
        s,f,m=fixture();f[0]['recorded_at']=None
        r=c.project(s,f,m,'BTCUSDT',NOW+dt.timedelta(hours=1))
        self.assertTrue(r['stale']);self.assertEqual(r['fills'][0]['time_basis'],'quote_only')

    def test_read_only_parameterized_loading_and_count_check(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);p=root/'research/execution';p.mkdir(parents=True)
            (p/'health-research.json').write_text(json.dumps({'execution_scope':'RESEARCH_SIMULATION_ONLY','orders_authorized':False}))
            s,f,m=fixture();db=p/'execution.sqlite'
            with sqlite3.connect(db) as conn:
                conn.executescript('CREATE TABLE state(id INTEGER,payload TEXT);CREATE TABLE orders(id INTEGER,bar TEXT,recorded_at TEXT,symbol TEXT,action TEXT,quantity REAL,price REAL,status TEXT,fee REAL);CREATE TABLE marks(bar TEXT,symbol TEXT,price REAL);')
                conn.execute('INSERT INTO state VALUES(1,?)',(json.dumps(s),))
                conn.executemany('INSERT INTO orders VALUES(:id,:bar,:recorded_at,:symbol,:action,:quantity,:price,:status,:fee)',[dict(x,status='filled',fee=.1) for x in f])
                conn.executemany('INSERT INTO marks VALUES(:bar,:symbol,:price)',[dict(x,symbol='BTCUSDT') for x in m])
            before=db.read_bytes();r=c.load('BTCUSDT',root,NOW);self.assertEqual(len(r['fills']),2);self.assertEqual(before,db.read_bytes())
            overview=c.load_overview('all',root,NOW)
            self.assertEqual(overview['symbols'],['BTCUSDT','ETHUSDT'])
            self.assertEqual(len(overview['charts']),2)
            self.assertEqual(overview['charts'][0]['fills'],r['fills'])
            self.assertEqual(overview['charts'][1]['position'],'FLAT')
            self.assertEqual(overview['charts'][1]['points'],[])
            self.assertEqual(before,db.read_bytes())
            with self.assertRaises(ValueError):c.load_overview('unbounded',root,NOW)
            self.assertEqual(r['fills'][0]['reference_mark'],109)
            with sqlite3.connect(db) as conn:conn.execute("DELETE FROM marks WHERE bar=?",(f[0]['bar'],))
            r=c.load('BTCUSDT',root,NOW)
            self.assertIsNone(r['fills'][0]['equity_impact'])  # No nearest/next mark substituted.
            with self.assertRaises(ValueError):c.load("BTCUSDT' OR 1=1--",root,NOW)
            with sqlite3.connect(db) as conn:conn.execute('DELETE FROM orders')
            with self.assertRaisesRegex(ValueError,'incomplete_fill_history'):c.load('BTCUSDT',root,NOW)

    def test_missing_database_is_never_created(self):
        with tempfile.TemporaryDirectory() as folder:
            with self.assertRaises(FileNotFoundError):c.load(root=folder)
            self.assertEqual(list(Path(folder).iterdir()),[])

    def test_overview_compaction_preserves_extrema_and_gap(self):
        start=NOW-dt.timedelta(seconds=2000)
        points=[dict(time=(start+dt.timedelta(seconds=i)).isoformat(),price=100+(i%9),gap_before=False) for i in range(2000)]
        points[799]['price']=1000;points[1201]['price']=1;points[1001]['gap_before']=True
        result=c.compact_points(points,80)
        self.assertLessEqual(len(result),80)
        self.assertEqual(result[0]['time'],points[0]['time']);self.assertEqual(result[-1]['time'],points[-1]['time'])
        self.assertEqual(max(p['price'] for p in result),1000);self.assertEqual(min(p['price'] for p in result),1)
        self.assertTrue(any(p['gap_before'] for p in result))
        self.assertTrue(all(any(p['time']==original['time'] and p['price']==original['price'] for original in points) for p in result))

    def test_equity_effect_is_not_realized_profit(self):
        # Expected values from cash transfer plus marked holdings, including reversals.
        for old,entry,q,price,fee,mark,realized,impact in [
            (0,0,2,101,.2,100,0,-2.2),(0,0,-2,99,.2,100,0,-2.2),
            (2,90,-2,100,.2,101,20,-2.2),(-2,110,2,100,.2,99,20,-2.2),
            (2,90,-.5,100,.1,101,5,-.6),
            (2,90,-3,100,.3,101,20,-3.3),(-2,110,3,100,.3,99,20,-3.3),
            (1,90,1,100,.1,101,0,.9)]:
            with self.subTest(old=old,q=q):
                r=c.fill_accounting(old,entry,q,price,fee,mark)
                self.assertAlmostEqual(r['realized_pnl'],realized)
                self.assertAlmostEqual(r['equity_impact'],impact)
                self.assertAlmostEqual(r['realized_pnl']+r['unrealized_change']-fee,impact)

    def test_missing_mark_or_fee_stays_unknown(self):
        r=c.fill_accounting(2,90,-1,100,.1,None)
        self.assertEqual(r['realized_pnl'],10);self.assertIsNone(r['equity_impact']);self.assertIsNone(r['unrealized_change'])
        r=c.fill_accounting(2,90,-1,100,None,101)
        self.assertIsNone(r['fee']);self.assertIsNone(r['equity_impact']);self.assertIsNone(r['realized_less_fill_fee'])
        for fee,mark in [(-1,100),(.1,-1),(.1,float('nan'))]:
            with self.assertRaises(ValueError):c.fill_accounting(2,90,-1,100,fee,mark)

    def test_replay_ignores_mixed_cumulative_order_field_and_reconciles_state(self):
        state,_,_=fixture();state['positions']['BTCUSDT'].update(quantity=1,entry_price=100,realized_pnl=15,fees=.3)
        fills=[]
        for i,(qty,price,cumulative) in enumerate([(2,100,0),(-.5,110,5),(-.5,120,15)]):
            fills.append({'id':i+1,'symbol':'BTCUSDT','quantity':qty,'action':'BUY' if qty>0 else 'SELL',
                          'price':price,'bar':f'2032-05-10T{9+i:02}:00:00+00:00',
                          'fee':.1,'reference_mark':price,'realized_pnl':cumulative})
        r=c.project(state,fills,[],'BTCUSDT',NOW)
        self.assertEqual([f['realized_pnl'] for f in r['fills']],[0,5,10])
        for key in ['realized_pnl','fees','entry_price']:
            bad=copy.deepcopy(state);bad['positions']['BTCUSDT'][key]+=1
            with self.subTest(key=key),self.assertRaisesRegex(ValueError,'fill_accounting_does_not_reconcile'):
                c.project(bad,fills,[],'BTCUSDT',NOW)


if __name__=='__main__':unittest.main()
