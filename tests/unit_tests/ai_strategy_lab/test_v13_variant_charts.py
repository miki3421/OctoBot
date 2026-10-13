"""Synthetic branch accounting and read-only source tests, no strategy changes."""
import copy
import datetime as dt
import json
import os
from pathlib import Path
import sqlite3
import tempfile
import unittest
from octobot.ai_strategy_lab import v13_variant_charts as c

UTC=dt.timezone.utc
NOW=dt.datetime(2032,5,10,12,tzinfo=UTC)
FORK='2032-05-10T11:00:00+00:00'
AT='2032-05-10T11:30:00+00:00'

class VariantCharts(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.root=Path(self.tmp.name)
        (self.root/'forks-ui').mkdir();self.directory=self.root/'research/execution';self.directory.mkdir(parents=True)
        self.path=self.directory/'execution.sqlite'
        orders=[]
        for i,(q,price) in enumerate([(2,100),(-.5,110)],1):
            orders.append(dict(id=i,bar=f'2032-05-10T{8+i:02}:00:00+00:00',recorded_at=f'2032-05-10T{8+i:02}:00:00+00:00',symbol='BTCUSDT',action='BUY' if q>0 else 'SELL',quantity=q,price=price,fee=.1,status='filled'))
        state=dict(mode='trend_v13_paper_v2',activation_at='2032-05-10T08:00:00+00:00',positions={'BTCUSDT':{'quantity':999}},research_epoch='original')
        with sqlite3.connect(self.path) as db:
            db.executescript('CREATE TABLE state(id INTEGER,payload TEXT);CREATE TABLE orders(id INTEGER,bar TEXT,recorded_at TEXT,symbol TEXT,action TEXT,quantity REAL,price REAL,fee REAL,status TEXT);CREATE TABLE marks(bar TEXT,symbol TEXT,price REAL);')
            db.execute('INSERT INTO state VALUES(1,?)',(json.dumps(state),))
            db.executemany('INSERT INTO orders VALUES(:id,:bar,:recorded_at,:symbol,:action,:quantity,:price,:fee,:status)',orders)
            # A different original order after the fork must not enter either branch.
            other=dict(orders[-1],id=3,bar='2032-05-10T11:45:00+00:00',recorded_at='2032-05-10T11:45:00+00:00',quantity=-1.5)
            db.execute('INSERT INTO orders VALUES(:id,:bar,:recorded_at,:symbol,:action,:quantity,:price,:fee,:status)',other)
            db.executemany('INSERT INTO marks VALUES(?,?,?)',[(o['bar'],'BTCUSDT',o['price']+1) for o in orders]+[(NOW.isoformat(),'BTCUSDT',121),('2032-05-10T13:00:00+00:00','BTCUSDT',999999)])
        db.close()
        inherited=[{k:o[k] for k in c.SIGNATURE} for o in orders]
        market=dict(scope='RESEARCH_SIMULATION_ONLY',observed_at_end=AT,quotes={'BTCUSDT':{'mark_price':119}})
        h=c.canonical_hash(market);market['record_hash']=h
        archive=self.root/'research/source/market';archive.mkdir(parents=True);self.market_path=archive/(h+'.json');self.market_path.write_text(json.dumps(market))
        self.value=dict(available=True,schema=1,generated_at=NOW.isoformat(),health={'checked_at':NOW.isoformat()},
            receipt=dict(parent_snapshot_sha256='a'*64,scope='RESEARCH_SIMULATION_ONLY_NO_EXECUTOR_LINK',economic_t0=FORK,account_ids={}),variants={},inherited_fills=inherited)
        for arm,qty,entry,delta,realized in [('FAST',1,100,-.5,10),('HALF',2,97.5,.5,0)]:
            account='v13-risk-matched-clone-v2-'+arm.lower()+'-'+'a'*12
            self.value['receipt']['account_ids'][arm]=account
            self.value['variants'][arm]=dict(account_id=account,label=arm,observed_at=NOW.isoformat(),positions=[{'symbol':'BTCUSDT','quantity':qty,'entry':entry}],historical_order_count=2,post_fork_order_count=1,
                fills=[dict(arm=arm,symbol='BTCUSDT',at=AT,quantity=delta,price=120 if arm=='FAST' else 90,fee=.1,before=1.5,after=qty,realized_delta=realized,market_hash=h)])
        self.projection=self.root/'forks-ui/comparison.json';self.write()
    def write(self):
        self.projection.write_text(json.dumps(self.value));os.chown(self.projection,30934,-1);self.projection.chmod(0o640)
    def tearDown(self):self.tmp.cleanup()
    def load(self,variant='fast',**kwargs):return c.load(variant,root=self.root,now=NOW,**kwargs)
    def test_full_prefix_branch_isolation_and_sale_accounting(self):
        before=self.path.read_bytes();projection=self.projection.read_bytes()
        fast=self.load();half=self.load('half')
        self.assertEqual([f['quantity'] for f in fast['fills']],[2,-.5,-.5]);self.assertEqual([f['quantity'] for f in half['fills']],[2,-.5,.5])
        self.assertEqual([f['origin'] for f in fast['fills']],['inherited','inherited','post_fork'])
        self.assertEqual(fast['fills'][-1]['realized_pnl'],10);self.assertAlmostEqual(fast['fills'][-1]['realized_less_fill_fee'],9.9)
        self.assertAlmostEqual(fast['fills'][-1]['equity_impact'],.4)
        self.assertEqual(fast['quantity'],1);self.assertEqual(half['quantity'],2)
        self.assertEqual(self.path.read_bytes(),before);self.assertEqual(self.projection.read_bytes(),projection)
        self.assertNotIn(999999,[p['price'] for p in fast['points']])
    def test_inherited_sale_is_not_summed_as_cumulative(self):
        data=self.load();self.assertEqual([f['realized_pnl'] for f in data['fills']],[0,5,10])
        self.assertEqual(data['fills'][1]['label'],'Riduzione long');self.assertEqual(data['fills'][-1]['before'],1.5)
    def test_wrong_arm_and_inconsistent_position_refused(self):
        for mutation in ['arm','qty','entry','realized','before','count','identity']:
            original=copy.deepcopy(self.value);a=self.value['variants']['FAST']
            if mutation=='arm':a['fills'][0]['arm']='HALF'
            if mutation=='qty':a['positions'][0]['quantity']=2
            if mutation=='entry':a['positions'][0]['entry']=98
            if mutation=='realized':a['fills'][0]['realized_delta']=15
            if mutation=='before':a['fills'][0]['before']=0
            if mutation=='count':a['post_fork_order_count']=2
            if mutation=='identity':a['account_id']=self.value['variants']['HALF']['account_id']
            self.write()
            with self.subTest(mutation=mutation),self.assertRaises(ValueError):self.load()
            self.value=original;self.write()
    def test_missing_or_changed_inherited_history_refused(self):
        self.value['inherited_fills'][1]['quantity']=-.4;self.write()
        with self.assertRaisesRegex(ValueError,'inherited_history'):self.load()
    def test_missing_market_mark_unknown_without_substitution(self):
        self.market_path.unlink();data=self.load();f=data['fills'][-1]
        self.assertIsNone(f['reference_mark']);self.assertIsNone(f['equity_impact']);self.assertEqual(f['realized_pnl'],10)
    def test_market_hash_or_time_tampering_refused(self):
        v=json.loads(self.market_path.read_text());v['quotes']['BTCUSDT']['mark_price']=999;self.market_path.write_text(json.dumps(v))
        with self.assertRaisesRegex(ValueError,'archive_tampered'):self.load()
    def test_future_and_duplicate_fills_refused(self):
        old=copy.deepcopy(self.value)
        self.value['variants']['FAST']['fills'][0]['at']='2032-05-11T11:30:00+00:00';self.write()
        with self.assertRaises(ValueError):self.load()
        self.value=old;self.value['variants']['FAST']['fills']*=2;self.write()
        with self.assertRaisesRegex(ValueError,'time_or_replay'):self.load()
    def test_missing_ledger_never_created_and_invalid_input_refused(self):
        for variant,symbol,period in [('unknown',None,'all'),('fast',"BTCUSDT' OR 1=1",'all'),('fast','BTCUSDT','forever')]:
            with self.assertRaises(ValueError):c.load(variant,symbol,period,self.root,NOW)
        self.path.unlink()
        with self.assertRaises(FileNotFoundError):self.load()
        self.assertFalse(self.path.exists())
    def test_observation_cadence_and_staleness(self):
        data=c.load('fast',root=self.root,now=NOW+dt.timedelta(seconds=240));self.assertTrue(data['stale'])
        self.value['generated_at']=(NOW+dt.timedelta(seconds=240)).isoformat();self.value['health']['checked_at']=self.value['generated_at'];self.write()
        data=c.load('fast',root=self.root,now=NOW+dt.timedelta(seconds=240));self.assertFalse(data['stale'])
        data=c.load('fast',root=self.root,now=NOW+dt.timedelta(seconds=421));self.assertTrue(data['stale'])
    def test_overview_matches_detail_and_period_filter(self):
        detail=self.load();overview=self.load(overview=True)
        self.assertEqual(overview['charts'][0]['fills'],detail['fills']);self.assertEqual(overview['variant'],'fast')
        self.assertEqual(overview['charts'][0]['total_fills'],3);self.assertEqual(overview['charts'][0]['fork_at'],FORK)
    def test_projection_custody_and_symlink_refused(self):
        self.projection.chmod(0o666)
        with self.assertRaisesRegex(ValueError,'custody'):self.load()
        self.projection.chmod(0o640);target=self.projection.with_suffix('.backup');self.projection.rename(target);self.projection.symlink_to(target)
        with self.assertRaises(ValueError):self.load()

if __name__=='__main__':unittest.main()
