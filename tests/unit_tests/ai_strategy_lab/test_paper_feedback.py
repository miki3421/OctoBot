import datetime
import pathlib
import sqlite3

import pytest

from octobot.ai_strategy_lab import paper_feedback
from tentacles.Evaluator.Strategies.ai_strategies_evaluator.guarded_llm import (
    DeterministicRiskGuard,
    LLMTradingDecision,
    RiskGuardSettings,
    SQLiteDecisionJournal,
)


def _decision(action):
    return LLMTradingDecision(
        action=action,
        confidence=0.8 if action != "HOLD" else 0,
        signal_strength=0.45 if action != "HOLD" else 0,
        stop_loss_pct=2 if action != "HOLD" else 0,
        take_profit_pct=4 if action != "HOLD" else 0,
        horizon_minutes=60,
        rationale="test",
        invalidation="test",
    )


def _record_decision(journal, action):
    decision = _decision(action)
    return journal.record(
        context={
            "exchange_name": "kucoin",
            "cryptocurrency": "Bitcoin",
            "symbol": "BTC/USDT:USDT",
            "triggered_at": 1_700_000_000,
        },
        model=None,
        prompt_version="test-v1",
        input_data={
            "15m": [
                {
                    "evaluator": "RSI",
                    "eval_note": -0.5,
                    "bias": "BULLISH",
                    "metadata": {"atr_pct": 0.01, "ready": True},
                }
            ]
        },
        output_data=decision.model_dump(mode="json"),
        guarded=DeterministicRiskGuard(
            RiskGuardSettings()
        ).evaluate(decision),
    )


def test_export_keeps_unlabelled_controls_and_only_labels_closed_trade(tmp_path):
    path = tmp_path / "journal.sqlite"
    journal = SQLiteDecisionJournal(str(path))
    buy_id = _record_decision(journal, "BUY")
    hold_id = _record_decision(journal, "HOLD")
    now = datetime.datetime.now(datetime.timezone.utc)
    journal.record_order_event(
        exchange_name="kucoin",
        symbol="BTC/USDT:USDT",
        order={
            "id": "entry",
            "status": "filled",
            "side": "buy",
            "type": "market",
            "filled": 1,
            "average": 100,
            "fee": {"cost": 0.1, "currency": "USDT"},
        },
        is_from_bot=True,
        occurred_at=now + datetime.timedelta(seconds=1),
    )
    journal.record_order_event(
        exchange_name="kucoin",
        symbol="BTC/USDT:USDT",
        order={
            "id": "exit",
            "status": "filled",
            "side": "sell",
            "type": "sell_limit",
            "filled": 1,
            "average": 110,
            "fee": {"cost": 0.1, "currency": "USDT"},
            "reduceOnly": True,
        },
        is_from_bot=True,
        occurred_at=now + datetime.timedelta(seconds=2),
    )

    report = paper_feedback.export_paper_feedback(path)

    assert report["source"]["integrity_check"] == "ok"
    assert report["summary"] == {
        "exported_rows": 2,
        "eligible_training_rows": 1,
        "unlabelled_rows": 1,
        "invalid_input_json_rows": 0,
    }
    assert report["source"]["snapshot"]["order_event_rows"] == 2
    assert "15m.RSI.eval_note" in report["feature_schema"]
    assert "15m.RSI.metadata.atr_pct" in report["feature_schema"]
    rows = {row["decision_id"]: row for row in report["rows"]}
    assert rows[buy_id]["eligible_for_supervised_training"] is True
    assert rows[buy_id]["label"]["profitable_excluding_funding"] is True
    assert rows[buy_id]["label"]["net_pnl_excluding_funding"] == pytest.approx(
        9.8
    )
    assert rows[hold_id]["eligible_for_supervised_training"] is False
    assert rows[hold_id]["label"] is None
    readiness = report["training_readiness"]
    assert readiness["passed"] is False
    assert readiness["automatic_training_authorized"] is False
    assert readiness["observed"]["closed_outcomes"] == 1
    assert readiness["observed"]["long_outcomes"] == 1
    assert readiness["observed"]["short_outcomes"] == 0
    assert readiness["checks"][
        "funding_included_in_economic_labels"
    ] is False


def test_export_rejects_incomplete_feedback_schema(tmp_path):
    path = pathlib.Path(tmp_path) / "incomplete.sqlite"
    with sqlite3.connect(path) as connection:
        connection.execute("CREATE TABLE ai_decisions (id INTEGER)")

    with pytest.raises(ValueError, match="schema is incomplete"):
        paper_feedback.export_paper_feedback(path)
