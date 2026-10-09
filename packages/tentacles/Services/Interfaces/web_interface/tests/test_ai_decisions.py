import pathlib
import sqlite3
import tempfile
import unittest

import tentacles.Services.Interfaces.web_interface.controllers.ai_decisions as audit


class TestDecisionAudit(unittest.TestCase):
    def test_list_is_compact_and_detail_loads_raw_json_lazily(self):
        with tempfile.TemporaryDirectory() as directory:
            path = pathlib.Path(directory) / "ai.sqlite"
            with sqlite3.connect(path) as connection:
                connection.execute(
                    """
                    CREATE TABLE ai_decisions (
                        id INTEGER PRIMARY KEY,
                        created_at TEXT,
                        exchange_name TEXT,
                        cryptocurrency TEXT,
                        symbol TEXT,
                        model TEXT,
                        prompt_version TEXT,
                        input_json TEXT,
                        output_json TEXT,
                        action TEXT,
                        confidence REAL,
                        signal_strength REAL,
                        eval_note REAL,
                        approved INTEGER,
                        guard_reason TEXT,
                        rationale TEXT,
                        invalidation TEXT,
                        horizon_minutes INTEGER
                    )
                    """
                )
                connection.execute(
                    """
                    INSERT INTO ai_decisions VALUES (
                        1, '2026-09-02T00:00:00+00:00', 'kucoin', 'BTC',
                        'BTC/USDT:USDT', 'deterministic', 'v1',
                        '{"value":1}', '{"action":"HOLD"}', 'HOLD',
                        0.5, 0.0, 0.0, 0, 'neutral', 'no consensus',
                        'alignment changes', 15
                    )
                    """
                )

            decisions, summary = audit._read_decisions(str(path))
            detail = audit._read_decision_detail(str(path), 1)

            self.assertEqual(summary["total"], 1)
            self.assertNotIn("input_json", decisions[0])
            self.assertNotIn("output_json", decisions[0])
            self.assertEqual(
                decisions[0]["paper_execution"]["kind"], "not_executed"
            )
            self.assertIn('"value": 1', detail["input_json"])
            self.assertIn('"action": "HOLD"', detail["output_json"])
            self.assertIsNone(audit._read_decision_detail(str(path), 2))

    def test_paper_execution_distinguishes_signal_position_and_outcome(self):
        decision = {"approved": 1, "action": "BUY"}

        signal = audit._paper_execution_summary(decision)
        position = audit._paper_execution_summary(
            decision,
            {
                "status": "filled",
                "reduce_only": 0,
                "side": "buy",
                "order_type": "market",
                "quantity": 0.01,
            },
        )
        closed = audit._paper_execution_summary(
            decision,
            outcome={
                "net_pnl_excluding_funding": 5.25,
                "side": "long",
            },
        )

        self.assertEqual(signal["kind"], "signal_only")
        self.assertEqual(position["kind"], "order")
        self.assertEqual(position["label"], "INGRESSO ESEGUITO")
        self.assertEqual(closed["kind"], "closed")
        self.assertEqual(closed["color"], "success")

    def test_skips_are_explicit_and_unknown_history_is_not_an_execution_error(self):
        decision = {"approved": 1, "action": "BUY"}
        for reason, label in [
            ("strategy_quarantined", "STRATEGIA SOSPESA"),
            ("side_disabled", "LATO DISABILITATO"),
            ("state_unchanged", "SEGNALE RIPETUTO"),
            ("position_already_open", "POSIZIONE GIÀ APERTA"),
            ("execution_error", "ERRORE DI ESECUZIONE"),
        ]:
            with self.subTest(reason=reason):
                self.assertEqual(audit._paper_execution_summary(decision, attempt={"reason": reason})["label"], label)
        unknown = audit._paper_execution_summary(decision)
        self.assertEqual(unknown["label"], "ESITO NON TRACCIATO")
        context = audit._paper_execution_summary(decision, covering_position={"decision_id": 8})
        self.assertIn("#8", context["detail"])
        self.assertIn("non fu registrato", context["detail"])

    def test_actual_fill_takes_precedence_over_skip_notification(self):
        result = audit._paper_execution_summary(
            {"approved": 1, "action": "BUY"},
            latest_event={"status": "filled", "reduce_only": 0, "side": "buy"},
            attempt={"reason": "state_unchanged"},
        )
        self.assertEqual(result["label"], "INGRESSO ESEGUITO")

    def test_entry_not_protective_sell_and_fee_arithmetic_from_full_journal(self):
        from tentacles.Evaluator.Strategies.ai_strategies_evaluator.guarded_llm import (
            SQLiteDecisionJournal, DeterministicRiskGuard, RiskGuardSettings, LLMTradingDecision,
        )
        with tempfile.TemporaryDirectory() as directory:
            path = pathlib.Path(directory) / "audit.sqlite"
            journal = SQLiteDecisionJournal(str(path))
            decision = LLMTradingDecision(action="BUY", confidence=.8, signal_strength=.45,
                stop_loss_pct=1, take_profit_pct=2, horizon_minutes=1440,
                rationale="test", invalidation="test")
            decision_id = journal.record(
                context={"exchange_name": "kucoin", "symbol": "BTC/USDT:USDT"}, model="test",
                prompt_version="test", input_data={}, output_data={},
                guarded=DeterministicRiskGuard(RiskGuardSettings()).evaluate(decision),
            )
            def event(order):
                journal.record_order_event(exchange_name="kucoin", symbol="BTC/USDT:USDT",
                    order=order, is_from_bot=True)
            event({"id": "entry", "status": "filled", "type": "market", "side": "buy",
                   "amount": .01, "filled": .01, "price": 10000, "average": 10000,
                   "fee": {"cost": .1, "currency": "USDT"}})
            event({"id": "stop", "status": "open", "type": "stop_loss", "side": "sell",
                   "amount": .01, "price": 9900, "reduceOnly": True})
            journal.record_execution_attempt(decision_id, "state_unchanged")
            rows, _ = audit._read_decisions(str(path))
            detail = audit._read_decision_detail(str(path), decision_id)
            for summary in [rows[0]["paper_execution"], detail["paper_execution"]]:
                self.assertEqual(summary["label"], "INGRESSO ESEGUITO")
                self.assertIn("BUY", summary["detail"])
            event({"id": "stop", "status": "filled", "type": "stop_loss", "side": "sell",
                   "amount": .01, "filled": .01, "price": 9900, "average": 9900,
                   "reduceOnly": True, "fee": {"cost": .1, "currency": "USDT"}})
            _, totals = audit._read_outcomes(str(path))
            self.assertAlmostEqual(totals["gross_price_pnl"], -1)
            self.assertAlmostEqual(totals["known_fees"], .2)
            self.assertAlmostEqual(totals["net_pnl_excluding_funding"], -1.2)
            self.assertAlmostEqual(totals["same_exit_inverse"], .8)
            self.assertEqual(totals["profit_factor"], 0)
            journal.record_execution_policy("kucoin", "BTC/USDT:USDT", True, "audit")
            self.assertEqual(audit._read_execution_policy(str(path))["entries_quarantined"], 1)
            with sqlite3.connect(path) as db:
                self.assertEqual(db.execute("pragma integrity_check").fetchone()[0], "ok")


if __name__ == "__main__":
    unittest.main()
