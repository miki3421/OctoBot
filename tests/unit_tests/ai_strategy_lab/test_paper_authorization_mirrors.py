"""Mirror entry boundaries with real missing registry and isolated consumer DB."""
import gzip
import json
import sqlite3
import types
from unittest import mock

import numpy
import pytest
from octobot.ai_strategy_lab import paper_authorization as auth, v13_paper, v5_paper
from tests.unit_tests.ai_strategy_lab import test_diversified_manual_paper_v1 as diversified_fixture


@pytest.fixture
def absent_registry(tmp_path, monkeypatch):
    registry = auth.Registry(tmp_path/'missing-control', tmp_path/'authorization.sqlite')
    monkeypatch.setattr(auth, 'Registry', lambda: registry)
    return registry


def test_legacy_v13_cannot_create_orders_on_start(tmp_path, absent_registry):
    payload = dict(bar_date='2026-09-06', research_targets=dict(trend_effective_portfolio_weights={'BTCUSDT': .1}))
    journal = tmp_path/'decisions.jsonl'
    journal.write_text(json.dumps(dict(decision_payload=payload))+'\n')
    (tmp_path/'daily').mkdir()
    with gzip.open(tmp_path/'daily/2026-09-06.json.gz', 'wt') as stream:
        json.dump(dict(symbols={'BTCUSDT':dict(close=100000.,funding_rate_sum=0.)}),stream)
    database = tmp_path/'paper.sqlite'
    with pytest.raises(auth.Denied):
        v13_paper.run_once(journal,database,tmp_path/'health.json')
    with sqlite3.connect(database) as db:
        assert db.execute('SELECT COUNT(*) FROM orders').fetchone()[0] == 0


def test_diversified_start_does_not_grant_authorization(absent_registry):
    fixture = diversified_fixture.TestDiversifiedManualPaperV1()
    fixture.setUp()
    try:
        paper = diversified_fixture.paper
        first=fixture._record('2026-09-03',1.,None)
        fixture._write_records([first])
        args=(fixture.journal,fixture.protocol,fixture.lock,fixture.database,fixture.health)
        paper.run_once(*args)
        second=fixture._record('2026-09-04',1.01,first['journal_record_hash'],{'SOL':.1})
        fixture._write_records([first,second])
        with pytest.raises(auth.Denied):paper.run_once(*args)
        with sqlite3.connect(fixture.database) as db:
            assert db.execute('SELECT COUNT(*) FROM orders').fetchone()[0] == 0
    finally:fixture.tearDown()


def test_v5_new_trade_never_reaches_simulation_or_broker(absent_registry):
    runner=object.__new__(v5_paper.V5PaperRunner)
    runner.state={'open_trade':None,'equity':10000.}
    runner.model=types.SimpleNamespace(predict=mock.Mock(return_value=None),expected_net_threshold_pct=.1)
    runner.config=types.SimpleNamespace(broker_url='unused')
    runner._broker_command=mock.Mock()
    with mock.patch.object(v5_paper,'prediction_to_decision',return_value={'action':'LONG'}), mock.patch.object(v5_paper,'open_trade_from_decision') as execution:
        with pytest.raises(auth.Denied):runner._process_candle(numpy.array([0,100,101,99,100]),numpy.array([1.]))
        execution.assert_not_called()
    runner._broker_command.assert_not_called()
    assert runner.state['open_trade'] is None
