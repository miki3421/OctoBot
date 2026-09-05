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
        self.assertEqual(position["label"], "POSIZIONE APERTA")
        self.assertEqual(closed["kind"], "closed")
        self.assertEqual(closed["color"], "success")


if __name__ == "__main__":
    unittest.main()
