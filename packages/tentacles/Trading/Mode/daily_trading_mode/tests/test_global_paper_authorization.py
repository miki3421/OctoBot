"""P0-04 + actual P0-01 journal in isolated storage; never operational grants."""
import datetime as dt
import pathlib
import sqlite3
import tempfile
import types
import unittest
from unittest import mock

from octobot.ai_strategy_lab import paper_authorization as auth, paper_runtime_authorization as wiring
from octobot.ai_strategy_lab.paper_authorization_admin import Admin
from octobot.ai_strategy_lab import v13_paper_v2 as paper
from tentacles.Evaluator.Strategies.ai_strategies_evaluator.guarded_llm import (
    DeterministicRiskGuard, LLMTradingDecision, RiskGuardSettings, SQLiteDecisionJournal)
from tentacles.Trading.Mode.daily_trading_mode.daily_trading import DailyTradingMode, DailyTradingModeConsumer
import octobot_trading.enums as enums


class GlobalPaperAuthorizationTest(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        directory=tempfile.TemporaryDirectory();self.addCleanup(directory.cleanup)
        self.root=pathlib.Path(directory.name)
        created=auth.now()
        self.admin=Admin(self.root/'control',clock=lambda:created);self.admin.initialize()
        self.policy={k:{'fixture_only':True} for k in auth.REQUIRED_CONTROLS}
        self.identity=auth.Identity('fixture-native-paper','fixture-strategy','a'*64,'fixture-policy',auth.digest(self.policy),'fixture-grant')
        self.admin.grant(self.identity,valid_from=created.isoformat());self.admin.set_kill(False)
        self.registry=auth.Registry(self.admin.root,self.root/'authorization.sqlite')
        self.journal=SQLiteDecisionJournal(str(self.root/'decision.sqlite'))
        proposal=LLMTradingDecision(action='BUY',confidence=.8,signal_strength=.45,stop_loss_pct=1,take_profit_pct=2,horizon_minutes=240,rationale='test',invalidation='test')
        guarded=DeterministicRiskGuard(RiskGuardSettings()).evaluate(proposal)
        decision=self.journal.record(context=dict(exchange_name='kucoin',symbol='BTC/USDT:USDT'),model='test',prompt_version='test',input_data={},output_data=proposal.model_dump(),guarded=guarded)
        self.token=self.journal.authorize_entry(decision)
        mode=object.__new__(DailyTradingMode)
        mode.trading_config=dict(required_strategies=['GuardedLLMStrategyEvaluator'],record_ai_trade_events=True,entry_quarantine=False)
        mode.exchange_manager=types.SimpleNamespace(is_trader_simulated=True,is_backtesting=False,is_future=True,exchange_name='kucoin')
        mode._ai_decision_journal=self.journal;mode.logger=mock.Mock()
        self.consumer=object.__new__(DailyTradingModeConsumer);self.consumer.trading_mode=mode
        self.consumer.DISABLE_BUY_ORDERS=self.consumer.DISABLE_SELL_ORDERS=False
        self.consumer._create_new_orders=mock.AsyncMock(return_value=['paper-order'])
        self.addCleanup(mock.patch.stopall)
        mock.patch.object(wiring,'entry_scope',side_effect=lambda account,entry,**kwargs:self.registry.global_entry(self.identity,entry,self.policy)).start()

    async def enter(self,token=None,**data):
        data[SQLiteDecisionJournal.ENTRY_AUTHORIZATION_KEY]=self.token if token is None else token
        return await self.consumer.create_new_orders('BTC/USDT:USDT',-.45,enums.EvaluatorStates.LONG.value,data=data)

    async def test_global_then_real_decision_authorization(self):
        self.assertEqual(await self.enter(),['paper-order'])
        self.consumer._create_new_orders.assert_awaited_once()
        self.consumer._create_new_orders.reset_mock()
        self.assertEqual(await self.enter(),[])
        self.consumer._create_new_orders.assert_not_awaited()

    async def test_kill_precedes_decision_claim_and_execution(self):
        self.admin.set_kill(True)
        with mock.patch.object(self.journal,'validate_entry_authorization',wraps=self.journal.validate_entry_authorization) as decision:
            self.assertEqual(await self.enter(),[])
            decision.assert_not_called()
        self.consumer._create_new_orders.assert_not_awaited()

    async def test_invalid_p001_cannot_use_valid_global_grant(self):
        self.assertEqual(await self.enter(token={'authorization_id':'wrong','decision_id':1}),[])
        self.consumer._create_new_orders.assert_not_awaited()

    async def test_audit_failure_precedes_native_execution(self):
        self.registry.audit=self.root/'absent'/'audit.sqlite'
        self.assertEqual(await self.enter(),[])
        self.consumer._create_new_orders.assert_not_awaited()

    async def test_kill_does_not_disable_reduce_only(self):
        self.admin.set_kill(True)
        for flag in (self.consumer.REDUCE_ONLY_KEY,self.consumer.STOP_ONLY):
            self.consumer._create_new_orders.reset_mock()
            self.assertEqual(await self.enter(**{flag:True}),['paper-order'])
            self.assertIs(self.consumer._create_new_orders.call_args.kwargs['data'][self.consumer.REDUCE_ONLY_KEY],True)

    async def test_kill_cannot_activate_inside_native_async_effect(self):
        async def effect(*args,**kwargs):
            with self.assertRaises(BlockingIOError):self.admin.set_kill(True)
            return ['paper-order']
        self.consumer._create_new_orders.side_effect=effect
        self.assertEqual(await self.enter(),['paper-order'])
        self.admin.set_kill(True)
        self.consumer._create_new_orders.reset_mock()
        self.assertEqual(await self.enter(),[])
        self.consumer._create_new_orders.assert_not_awaited()

    async def test_real_p001_then_market_then_exposure_then_fill(self):
        def claim():
            return self.journal.validate_entry_authorization(self.token,'kucoin','BTC/USDT:USDT',-.45,consume=True) is not None
        mock.patch.object(wiring,'entry_scope',side_effect=lambda account,entry,**kwargs:self.registry.entry(self.identity,entry,self.policy,claim)).start()
        stamp=auth.now();event=stamp+dt.timedelta(seconds=1)
        account=dict(mode=paper.MODE,initial_equity=10000.,positions={},order_count=0,pending=dict(targets={'BTCUSDT':.1},noticed_at=stamp.isoformat(),decision_hash='fixture-decision'))
        quote=dict(symbol='BTCUSDT',market_identity='kucoin_futures_usdt',timestamp=event.isoformat(),mark_price=100.,step=.01,quantity_step=.01,contract_multiplier=.01,price_tick=.01,min_quantity=.01,min_notional=0.,fee_rate=.001,funding=[],bids=[dict(price=99.9,base_quantity=100.)],asks=[dict(price=100.1,base_quantity=100.)])
        record=dict(record_hash='fixture-market',observed_at_start=event.isoformat(),observed_at_end=event.isoformat())
        result,fills,_,_=paper.process_market(account,record,{'BTCUSDT':quote},event)
        self.assertEqual(len(fills),1)
        self.assertIsNone(result['risk']['reason'])
        with mock.patch.object(paper,'apply_fill',wraps=paper.apply_fill) as execution:
            again=paper.process_market(account,record,{'BTCUSDT':quote},event)[0]
            execution.assert_not_called()
        self.assertEqual(again['risk']['reason'],'entry_already_claimed')

    async def test_direct_v5_broker_cannot_bypass_missing_grant(self):
        import importlib.util
        path=pathlib.Path(__file__).resolve().parents[4]/'Services/Interfaces/web_interface/models/v5_paper_bridge.py'
        spec=importlib.util.spec_from_file_location('isolated_v5_bridge',path)
        bridge=importlib.util.module_from_spec(spec);spec.loader.exec_module(bridge)
        manager=types.SimpleNamespace(trader=types.SimpleNamespace(create_order=mock.AsyncMock()))
        # Replace the fixture grant wiring with the real absent-registry reader.
        absent=auth.Registry(self.root/'absent-control',self.root/'absent-audit.sqlite')
        with mock.patch.object(wiring,'entry_scope',side_effect=lambda *a,**k:absent.entry(self.identity,'fixture-broker',self.policy,None)):
            with self.assertRaises(bridge.V5PaperBridgeError):
                await bridge._open(manager,{'event_id':'fixture-open'})
        manager.trader.create_order.assert_not_awaited()
