"""Synthetic accounting fixtures only, no exchange admissibility claim."""
import copy
import tempfile
from pathlib import Path
import sqlite3
import unittest
import v13_dynamic_comparison as c


def tick(key='one', at='2026-10-19T00:16:00Z', previous=None, targets=True):
    x=dict(id=key,scope=c.SCOPE,at=at,marks={s:100. for s in c.selector.UNIVERSE},fee_rate=.0006,
           funding={'from':previous,'to':at,'coverage_complete':True,'events':[]})
    if targets:
        x.update(contract_scope='SYNTHETIC_ONLY',price_ticks={s:1e-12 for s in c.selector.UNIVERSE},quantity_steps={s:.000001 for s in c.selector.UNIVERSE},
                 books={s:dict(at=at,bids=[[99.999,100000.]],asks=[[100.001,100000.]]) for s in c.selector.UNIVERSE},decision_at='2026-10-19T00:15:00Z',targets={a:{'BTCUSDT':.1} for a in c.ARMS})
    return x


class AccountingTests(unittest.TestCase):
    def test_adverse_ticks_and_missing_metadata(self):
        self.assertEqual(c.adverse_price(100.021,1,.05),100.05)
        self.assertEqual(c.adverse_price(99.979,-1,.05),99.95)
        self.assertEqual(c.adverse_price(100.05,1,.05),100.05)
        for invalid in (0,-1,float('nan'),True):
            with self.assertRaises(ValueError):c.adverse_price(100,1,invalid)
        for direction in (1,-1):
            t=tick();t['price_ticks']={s:.05 for s in c.selector.UNIVERSE}
            t['targets']={a:{'BTCUSDT':direction*.1} for a in c.ARMS}
            state,trades=c.advance(c.initial_state(),t)
            for trade in trades:
                self.assertEqual(trade['price'],100.05 if direction>0 else 99.95)
                self.assertAlmostEqual(trade['fee'],abs(trade['quantity'])*trade['price']*.0006)
        t=tick();del t['price_ticks']
        with self.assertRaisesRegex(ValueError,'common_books_required'):c.advance(c.initial_state(),t)

    def test_common_capital_fee_slippage_and_mark_profit(self):
        s,trades=c.advance(c.initial_state(),tick())
        for a in c.ARMS:
            self.assertAlmostEqual(s['arms'][a]['equity'],10000 - 10*(100.001*1.0002-100) - 10*100.001*1.0002*.0006)
        second=tick('two','2026-10-20T00:16:00Z',s['last_at'],False)
        second['marks']['BTCUSDT']=110
        final,_=c.advance(s,second)
        self.assertAlmostEqual(final['arms']['A']['equity']-s['arms']['A']['equity'],100)
        self.assertEqual(final['arms']['A'],final['arms']['C'])

    def test_signed_funding_uses_old_position(self):
        first=tick();first['targets']['B']['BTCUSDT']=-.1
        state,_=c.advance(c.initial_state(),first)
        second=tick('two','2026-10-20T00:16:00Z',state['last_at'],False)
        second['funding']['events']=[dict(id='fund1',at='2026-10-20T00:00:00Z',symbol='BTCUSDT',rate=.001,mark=100)]
        final,_=c.advance(state,second)
        self.assertAlmostEqual(final['arms']['A']['funding'],-1)
        self.assertAlmostEqual(final['arms']['B']['funding'],1)
        third=tick('three','2026-10-21T00:16:00Z',final['last_at'],False)
        third['funding']['events']=second['funding']['events']
        with self.assertRaises(ValueError):c.advance(final,third)

    def test_reversal_has_two_charged_legs(self):
        first=tick();state,_=c.advance(c.initial_state(),first)
        for day in range(20,26):
            state,_=c.advance(state,tick(str(day),'2026-10-%02dT00:16:00Z'%day,state['last_at'],False))
        second=tick('two','2026-10-26T00:16:00Z',state['last_at'])
        second['decision_at']='2026-10-26T00:15:00Z'
        second['targets']={a:{'BTCUSDT':-.1} for a in c.ARMS}
        final,trades=c.advance(state,second)
        self.assertEqual(len(trades),6)
        self.assertTrue(all(t['fee']>0 for t in trades))
        self.assertLess(final['arms']['A']['positions']['BTCUSDT'],0)

    def test_deny_missing_funding_future_decision_limits_and_no_mutation(self):
        for mode in ['coverage','decision','limits','scope','marks']:
            t=tick();state=c.initial_state();before=copy.deepcopy(state)
            if mode=='coverage':t['funding']['coverage_complete']=False
            if mode=='decision':t['decision_at']=t['at']
            if mode=='limits':t['targets']['C']['BTCUSDT']=.5
            if mode=='scope':t['scope']='REAL'
            if mode=='marks':t['marks'].pop('BTCUSDT')
            with self.assertRaises(ValueError):c.advance(state,t)
            self.assertEqual(state,before)

    def test_atomic_restart_idempotence_conflict_and_sql_failure(self):
        with tempfile.TemporaryDirectory() as tmp:
            path=Path(tmp)/'fixture.sqlite'
            store=c.FixtureStore(path,create=True)
            first=store.commit(tick());store.close()
            store=c.FixtureStore(path)
            self.assertEqual(first,store.commit(tick()))
            bad=tick();bad['marks']['BTCUSDT']=101
            with self.assertRaises(ValueError):store.commit(bad)
            store.db.execute("CREATE TRIGGER fail_tick BEFORE INSERT ON ticks BEGIN SELECT RAISE(ABORT,'synthetic storage failure'); END")
            with self.assertRaises(sqlite3.DatabaseError):store.commit(tick('two','2026-10-20T00:16:00Z',tick()['at'],False))
            self.assertEqual(store.db.execute('SELECT COUNT(*) FROM ticks').fetchone()[0],1)
            self.assertEqual(store.db.execute('PRAGMA integrity_check').fetchone()[0],'ok')
            store.close()
            with self.assertRaises(FileExistsError):c.FixtureStore(path,create=True)

    def test_partial_depth_and_protective_close_cannot_reverse(self):
        state,_=c.advance(c.initial_state(),tick())
        t=tick('close','2026-10-20T00:16:00Z',state['last_at'])
        t['decision_at']='2026-10-20T00:15:00Z';t['protective_only']=True
        t['targets']={a:{'BTCUSDT':-.1} for a in c.ARMS}
        for book in t['books'].values():book['bids']=[[99.,2.],[98.,1.]]
        after,trades=c.advance(state,t)
        self.assertEqual(len(trades),3)
        self.assertTrue(all(t['protective'] and t['partial'] for t in trades))
        self.assertAlmostEqual(after['arms']['A']['positions']['BTCUSDT'],7.)
        self.assertAlmostEqual(trades[0]['price'],(2*99+98)/3*.9998)
        self.assertEqual(after['last_rebalance'],state['last_rebalance'])

    def test_loss_drawdown_and_frequency_survive_state_restore(self):
        import json
        state=c.initial_state()
        for a in c.ARMS:
            state['arms'][a].update(cash=7000.,positions={'BTCUSDT':30.})
            state['arms'][a]['risk'].update(day='2026-10-19',last_increase='2026-10-19T00:16:00Z')
        state['last_at']='2026-10-19T00:16:00Z'
        state=json.loads(json.dumps(state))
        t=tick('loss','2026-10-19T01:11:00Z',state['last_at'])
        t['decision_at']='2026-10-19T01:10:00Z'
        t['marks']={s:50. for s in c.selector.UNIVERSE}
        for book in t['books'].values():book.update(bids=[[49.99,100.]],asks=[[50.01,100.]])
        t['targets']={a:{'BTCUSDT':.3,'ETHUSDT':.2} for a in c.ARMS}
        after,trades=c.advance(state,t)
        for a in c.ARMS:
            self.assertTrue({'daily_loss','drawdown','daily_frequency','cooldown'}<=set(after['arms'][a]['denials']))
            self.assertNotIn('ETHUSDT',after['arms'][a]['positions'])
        self.assertFalse(trades)

    def test_minimum_steps_and_stale_book(self):
        t=tick()
        t['quantity_steps']={s:3. for s in c.selector.UNIVERSE}
        after,trades=c.advance(c.initial_state(),t)
        self.assertEqual(after['arms']['A']['positions']['BTCUSDT'],9.)
        t['books']['BTCUSDT']['at']='2026-10-19T00:09:00Z'
        with self.assertRaisesRegex(ValueError,'book'):c.advance(c.initial_state(),t)

    def test_delayed_funding_uses_settlement_position_after_close_and_replay(self):
        state,_=c.advance(c.initial_state(),tick())
        close=tick('close','2026-10-20T00:16:00Z',state['last_at'])
        close.update(protective_only=True,decision_at='2026-10-20T00:15:00Z',targets={a:{} for a in c.ARMS})
        state,_=c.advance(state,close)
        self.assertFalse(state['arms']['A']['positions'])
        later=tick('late','2026-10-21T00:16:00Z',state['last_at'],False)
        event=dict(id='late1',at='2026-10-19T08:00:00Z',symbol='BTCUSDT',rate=.001,mark=100.)
        later['delayed_funding']=[event]
        after,_=c.advance(state,later)
        self.assertEqual(after['arms']['A']['funding'],-1.)
        self.assertTrue(after['funding_adjustments'][0]['delayed'])
        again=tick('again','2026-10-22T00:16:00Z',after['last_at'],False);again['delayed_funding']=[dict(event,id='different-transport-id')]
        replay,_=c.advance(after,again)
        self.assertEqual(replay['arms']['A']['funding'],-1.)
        again['delayed_funding']=[dict(event,rate=.002)]
        with self.assertRaisesRegex(ValueError,'conflict'):c.advance(after,again)

    def test_settlement_at_fill_time_precedes_fill(self):
        state,_=c.advance(c.initial_state(),tick())
        later=tick('late','2026-10-20T00:16:00Z',state['last_at'],False)
        later['delayed_funding']=[dict(id='boundary',at=state['last_at'],symbol='BTCUSDT',rate=.001,mark=100.)]
        after,_=c.advance(state,later)
        self.assertEqual(after['arms']['A']['funding'],0.)
        later['delayed_funding'][0]['at']='2026-10-18T00:00:00Z'
        with self.assertRaisesRegex(ValueError,'history_missing'):c.advance(state,later)

    def test_full_selector_to_weights_to_atomic_accounting(self):
        import numpy as np
        from test_v13_dynamic_universe import fixture,START
        decision=c.selector.decide(fixture(),slot=START,start=START,lineage='fixture')
        weights=c.build_targets(decision,np.eye(29)*.04)
        self.assertEqual(len(weights['A']),18)
        self.assertEqual(sum(v!=0 for v in weights['C'].values()),18)
        t=tick();t['targets']=weights;t['selection']=decision;t['covariance']=(np.eye(29)*.04).tolist()
        with tempfile.TemporaryDirectory() as tmp:
            store=c.FixtureStore(Path(tmp)/'abc.sqlite',create=True)
            state,trades=store.commit(t)
            self.assertEqual(len(state['arms']['A']['positions']),18)
            self.assertEqual(len(state['arms']['B']['positions']),29)
            self.assertEqual(len(state['arms']['C']['positions']),18)
            self.assertEqual(len(trades),65)
            self.assertEqual(state['selection'],decision)
            store.close()
            store=c.FixtureStore(Path(tmp)/'abc.sqlite')
            self.assertEqual(store.commit(t),(state,trades))
            store.close()


if __name__=='__main__':unittest.main()
