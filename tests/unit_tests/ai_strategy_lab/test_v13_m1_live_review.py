"""Cash-flow and period expectations independent of the new publisher."""
import copy
import datetime as dt
import importlib.util
import json
import os
from pathlib import Path
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[3]


def load(name):
    spec = importlib.util.spec_from_file_location(name, ROOT/'octobot/ai_strategy_lab'/(name+'.py'))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


r = load('v13_m1_symbol_review')
v = load('v13_m1_live_review')
T = dt.datetime(2026, 10, 17, tzinfo=dt.timezone.utc).timestamp()


def fill(i, at, quantity, price, fee):
    return dict(id=i, bar=r.iso(at), symbol='BTCUSDT', quantity=quantity,
                price=price, fee=fee, action='BUY' if quantity>0 else 'SELL')


def inputs():
    epoch, end = T+86400, T+172800
    inherited = dict(quantity=2., entry_price=100., current_price=100.,
                     last_mark_at=r.iso(T), realized_pnl=0., fees=2., funding=-1.)
    old = fill(1,T-86400,2,100,2)
    marks = [(T,100),(epoch,100),(epoch+3600,110),(end,100)]
    initial_funding = dict(symbol='BTCUSDT',timestamp_ms=(T-100)*1000,quantity=2,amount=-1)
    original = dict(state=dict(initial_equity=10000,positions={'BTCUSDT':copy.deepcopy(inherited)},last_market_at=r.iso(end+60)),
                    fills=[old],funding=[initial_funding],marks={'BTCUSDT':marks},
                    equity_observation=dict(bar=r.iso(end+60),equity=9997))
    current = dict(quantity=-1.,entry_price=110.,current_price=100.,last_mark_at=r.iso(end),realized_pnl=20.,fees=5.,funding=-2.5)
    m1 = dict(state=dict(initial_equity=10000,positions={'BTCUSDT':current},m1_last_market_at=r.iso(end),fork_account=v.ACCOUNT),
              fills=[old,fill(2,epoch+3600,-3,110,3)],
              funding=[initial_funding,dict(symbol='BTCUSDT',timestamp_ms=(epoch+100)*1000,quantity=2,amount=-2),
                       dict(symbol='BTCUSDT',timestamp_ms=(epoch+4000)*1000,quantity=-1,amount=.5)],
              marks={'BTCUSDT':marks},equity_observation=dict(bar=r.iso(end),equity=10022.5))
    receipt=dict(account_id=v.ACCOUNT,economic_t0=r.iso(T),inherited_positions={'BTCUSDT':inherited},inherited_metrics={'equity':9997},seed_sha256='fixture-seed')
    successor=dict(activated_at=r.iso(epoch),boundary_metrics={'equity':9997},activation_id='fixture-epoch')
    return m1,original,receipt,successor,dt.datetime.fromtimestamp(end+120,dt.timezone.utc)


class LiveReviewTests(unittest.TestCase):
    def report(self):
        return v.calculate(*inputs(),r)

    def test_current_epoch_reconciles_split_reversal_fees_and_funding(self):
        result=self.report();total=result['m1']['totals']['since_version']
        self.assertAlmostEqual(total['net'],25.5)
        self.assertAlmostEqual(total['long_net'],16)
        self.assertAlmostEqual(total['short_net'],9.5)
        self.assertAlmostEqual(total['fees'],3)
        self.assertAlmostEqual(total['funding'],-1.5)
        self.assertAlmostEqual(total['end_equity']-total['baseline_equity'],25.5)
        self.assertEqual(result['default_window'],'since_version')
        self.assertEqual(result['original']['totals']['since_version']['net'],0)

    def test_previous_version_and_common_cutoff_are_explicit(self):
        result=self.report()
        self.assertEqual(result['m1']['totals']['legacy']['net'],0)
        self.assertEqual(result['cutoff_skew_seconds'],60)
        self.assertEqual(result['periods']['since_version']['start'],r.iso(T+86400))
        self.assertTrue(result['periods']['48h']['crosses_version_boundary'])

    def test_unknown_boundary_is_not_zero_or_partial_account_total(self):
        args=list(inputs());args[0]['marks']['BTCUSDT']=[(T,100),(T+86400+3600,110),(T+172800,100)]
        result=v.calculate(*args,r)
        self.assertFalse(result['m1']['totals']['since_version']['available'])
        self.assertIsNone(result['m1']['totals']['since_version']['net'])
        self.assertEqual(result['m1']['symbols']['BTCUSDT']['windows']['since_version']['reason'],'BOUNDARY_MARK_UNAVAILABLE')
        self.assertTrue(result['m1']['totals']['since_clone']['available'])

    def test_tampered_state_and_economic_anchor_are_rejected(self):
        args=list(inputs());args[0]['state']['positions']['BTCUSDT']['quantity']=-2
        with self.assertRaisesRegex(ValueError,'state_reconciliation'):v.calculate(*args,r)
        args=list(inputs());args[3]['boundary_metrics']['equity']=1
        with self.assertRaisesRegex(ValueError,'economic_anchor'):v.calculate(*args,r)

    def test_missing_funding_cannot_be_hidden(self):
        args=list(inputs());args[0]['funding']=args[0]['funding'][:-1]
        with self.assertRaisesRegex(ValueError,'funding_reconciliation'):v.calculate(*args,r)

    def test_future_fills_and_marks_do_not_leak_into_common_period(self):
        before=self.report();args=list(inputs())
        # Original's state can be newer while M1 defines the common cutoff.
        original=args[1];end=T+172800
        original['fills'].append(fill(2,end+30,-2,105,1))
        original['state']['positions']['BTCUSDT'].update(quantity=0.,entry_price=0.,realized_pnl=10.,fees=3.)
        original['equity_observation']['equity']=10006
        original['marks']['BTCUSDT'].append((end+60,105))
        after=v.calculate(*args,r)
        self.assertEqual(before['original'],after['original'])

    def test_public_projection_rejects_tamper_staleness_and_bad_side_math(self):
        data=self.report();now=inputs()[-1]
        with tempfile.TemporaryDirectory() as folder:
            p=Path(folder)/'current.json';p.write_text(json.dumps(data));p.chmod(0o444)
            self.assertTrue(v.public_view(p,now,os.getuid())['available'])
            self.assertFalse(v.public_view(p,now,os.getuid())['stale'])
            self.assertTrue(v.public_view(p,now+dt.timedelta(minutes=20),os.getuid())['stale'])
            self.assertFalse(v.public_view(p,now-dt.timedelta(seconds=1),os.getuid())['available'])
            p.chmod(0o644);data['m1']['symbols']['BTCUSDT']['windows']['since_version']['sides']['LONG']['net']+=1
            data['snapshot_id']=v.digest({k:x for k,x in data.items() if k!='snapshot_id'})
            p.write_text(json.dumps(data));p.chmod(0o444)
            self.assertFalse(v.public_view(p,now,os.getuid())['available'])

    def test_writeable_or_symlink_projection_is_not_trusted(self):
        with tempfile.TemporaryDirectory() as folder:
            p=Path(folder)/'current.json';p.write_text(json.dumps(self.report()));p.chmod(0o666)
            self.assertFalse(v.public_view(p,inputs()[-1],os.getuid())['available'])
            p.chmod(0o444);link=Path(folder)/'link';link.symlink_to(p)
            self.assertFalse(v.public_view(link,inputs()[-1],os.getuid())['available'])

    def test_failed_refresh_marks_last_good_report_stale(self):
        data=self.report();now=inputs()[-1]
        with tempfile.TemporaryDirectory() as folder:
            p=Path(folder)/'current.json';p.write_text(json.dumps(data));p.chmod(0o444)
            status=p.with_name('status.json');status.write_text(json.dumps(dict(scope=v.SCOPE,status='ERROR',checked_at=now.isoformat())));status.chmod(0o444)
            result=v.public_view(p,now,os.getuid())
            self.assertTrue(result['available']);self.assertTrue(result['stale']);self.assertTrue(result['refresh_failed'])
            self.assertEqual(result['review']['snapshot_id'],data['snapshot_id'])

    def test_new_m1_asset_is_explicitly_untraded_in_original(self):
        args=list(inputs());epoch=T+86400;end=T+172800
        args[0]['fills'].append(dict(id=3,bar=r.iso(epoch+3600),symbol='NEWUSDT',quantity=1.,price=50.,fee=.1,action='BUY'))
        args[0]['state']['positions']['NEWUSDT']=dict(quantity=1.,entry_price=50.,current_price=55.,last_mark_at=r.iso(end),realized_pnl=0.,fees=.1,funding=0.)
        args[0]['marks']['NEWUSDT']=[(epoch+3600,50.),(end,55.)]
        args[0]['equity_observation']['equity']+=4.9
        result=v.calculate(*args,r)
        self.assertAlmostEqual(result['m1']['symbols']['NEWUSDT']['windows']['since_version']['net'],4.9)
        reference=result['original']['symbols']['NEWUSDT']
        self.assertFalse(reference['in_universe']);self.assertEqual(reference['windows']['since_version']['net'],0.)


if __name__=='__main__':unittest.main()
