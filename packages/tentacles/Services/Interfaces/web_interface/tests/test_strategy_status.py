import json
import pathlib
import sqlite3
import tempfile
import unittest

import tentacles.Services.Interfaces.web_interface.controllers.strategy_status as status


class TestV5ForwardSummary(unittest.TestCase):
    def test_shadow_applied_and_candidate_weights_are_distinct(self):
        record = {
            "target_weights": {"LINK": 0.06, "ETH": 0.0},
            "candidate_target_weights": {"ETH": -0.04},
        }

        applied = status._shadow_allocations(record)
        candidates = status._shadow_allocations(
            record, "candidate_target_weights"
        )

        self.assertEqual(applied[0]["symbol"], "LINK")
        self.assertEqual(applied[0]["side"], "LONG")
        self.assertEqual(candidates[0]["symbol"], "ETH")
        self.assertEqual(candidates[0]["side"], "SHORT")

    def test_last_shadow_rebalance_date_uses_only_due_rows(self):
        with tempfile.TemporaryDirectory() as directory:
            path = pathlib.Path(directory) / "shadow.jsonl"
            path.write_text(
                '{"market_end_date":"2026-07-26","rebalance_due":true}\n'
                '{"market_end_date":"2026-07-27","rebalance_due":false}\n',
                encoding="utf-8",
            )

            self.assertEqual(
                status._shadow_last_rebalance_date(path), "2026-07-26"
            )

    def test_reads_forward_journal_without_writing(self):
        with tempfile.TemporaryDirectory() as directory:
            path = pathlib.Path(directory) / "v5.sqlite"
            connection = sqlite3.connect(path)
            connection.executescript(
                """
                CREATE TABLE decisions (
                    id INTEGER PRIMARY KEY,
                    close_timestamp INTEGER,
                    action TEXT,
                    accepted INTEGER,
                    reason TEXT,
                    expected_net_pct REAL,
                    target_profit_pct REAL,
                    horizon_hours INTEGER
                );
                CREATE TABLE trades (
                    id INTEGER PRIMARY KEY,
                    net_return_pct REAL,
                    pnl REAL,
                    direction TEXT,
                    exit_reason TEXT,
                    prediction_json TEXT
                );
                INSERT INTO decisions VALUES
                    (1, 1000, 'HOLD', 0, 'below_gate', -0.10, 1.5, 24),
                    (2, 1900, 'LONG', 1, 'accepted', 0.09, 1.0, 8);
                """
            )
            prediction = (
                '{"target_probability_pct":60,'
                '"stop_probability_pct":25,'
                '"timeout_probability_pct":15}'
            )
            connection.execute(
                "INSERT INTO trades VALUES (?, ?, ?, ?, ?, ?)",
                (1, 1.0, 10.0, "LONG", "profit_lock", prediction),
            )
            connection.execute(
                "INSERT INTO trades VALUES (?, ?, ?, ?, ?, ?)",
                (2, -1.0, -5.0, "SHORT", "initial_stop", prediction),
            )
            connection.commit()
            connection.close()

            result = status._v5_forward_summary(str(path), 0.075)

            self.assertTrue(result["available"])
            self.assertEqual(result["integrity"], "ok")
            self.assertEqual(result["decisions"], 2)
            self.assertEqual(result["accepted"], 1)
            self.assertEqual(result["acceptance_rate_pct"], 50.0)
            self.assertEqual(result["positive_expected_net"], 1)
            self.assertAlmostEqual(result["span_hours"], 0.25)
            self.assertEqual(result["trades"], 2)
            self.assertEqual(result["win_rate_pct"], 50.0)
            self.assertEqual(result["profit_factor"], 2.0)
            self.assertEqual(result["total_pnl"], 5.0)
            self.assertEqual(result["accepted_by_direction"]["LONG"], 1)
            self.assertEqual(result["accepted_by_direction"]["SHORT"], 0)
            self.assertEqual(result["trades_by_direction"]["LONG"], 1)
            self.assertEqual(result["trades_by_direction"]["SHORT"], 1)
            self.assertEqual(
                result["calibration"]["mature_accepted_trades"], 2
            )
            self.assertEqual(result["target_distribution"][0]["count"], 1)
            self.assertEqual(
                result["ev_series"]["expected_net_pct"], [-0.10, 0.09]
            )
            self.assertEqual(
                result["ev_series"]["accepted"], [False, True]
            )
            self.assertEqual(
                result["ev_series"]["threshold_pct"], 0.075
            )

    def test_missing_journal_is_not_an_error(self):
        result = status._v5_forward_summary(
            "/definitely/missing/v5.sqlite", 0.075
        )

        self.assertEqual(result, {"available": False})

    def test_microstructure_summary_keeps_failed_research_orderless(self):
        with tempfile.TemporaryDirectory() as directory:
            root = pathlib.Path(directory)
            (root / "experiments" / "v1-20260827").mkdir(parents=True)
            (root / "protocol.json").write_text(
                json.dumps(
                    {
                        "protocol_sha256": "frozen",
                        "results": None,
                        "orders_authorized": False,
                        "paper_orders_authorized": False,
                    }
                ),
                encoding="utf-8",
            )
            (root / "diagnostic-dataset.manifest.json").write_text(
                json.dumps(
                    {
                        "first_decision": "2026-07-24T00:00:00Z",
                        "last_decision": "2026-08-17T00:00:00Z",
                    }
                ),
                encoding="utf-8",
            )
            report = {
                "protocol": {"sha256": "frozen"},
                "orders_authorized": False,
                "paper_orders_authorized": False,
                "dataset": {
                    "rows": 1508,
                    "locked_test_materialized": False,
                },
                "models": {
                    name: {
                        "probability": {"auc": auc},
                        "probability_distribution": {
                            "both_directions": {"maximum": 0.58}
                        },
                    }
                    for name, auc in (
                        ("price_only", 0.76),
                        ("book_only", 0.60),
                        ("combined", 0.66),
                    )
                },
                "primary_task": {"probability_threshold": 0.60},
                "diagnostics_only": {
                    "horizons": [
                        {"horizon_seconds": 14400, "target_rate": 0.049},
                        {"horizon_seconds": 28800, "target_rate": 0.129},
                    ]
                },
                "diagnostic_advancement_gate": {
                    "passed": False,
                    "passed_checks": 6,
                    "total_checks": 15,
                    "book_improvement_folds": 0,
                    "relative_brier_improvement_vs_price": -0.059,
                },
                "conclusion": "incremental_book_value_not_demonstrated",
            }
            report_path = (
                root / "experiments" / "v1-20260827" / "report.json"
            )
            report_path.write_text(json.dumps(report), encoding="utf-8")

            result = status._microstructure_summary(root)

            self.assertTrue(result["available"])
            self.assertEqual(result["state"], "V1 RESPINTA")
            self.assertEqual(result["rows"], 1508)
            self.assertEqual(result["price_auc"], 0.76)
            self.assertAlmostEqual(result["target_rate_8h_pct"], 12.9)
            self.assertFalse(result["orders_authorized"])

    def test_microstructure_summary_rejects_order_authorization(self):
        with tempfile.TemporaryDirectory() as directory:
            root = pathlib.Path(directory)
            experiment = root / "experiments" / "v1"
            experiment.mkdir(parents=True)
            (root / "protocol.json").write_text(
                json.dumps(
                    {
                        "protocol_sha256": "frozen",
                        "results": None,
                        "orders_authorized": False,
                        "paper_orders_authorized": False,
                    }
                ),
                encoding="utf-8",
            )
            (experiment / "report.json").write_text(
                json.dumps(
                    {
                        "protocol": {"sha256": "frozen"},
                        "orders_authorized": True,
                        "paper_orders_authorized": False,
                        "dataset": {"locked_test_materialized": False},
                    }
                ),
                encoding="utf-8",
            )

            with self.assertRaisesRegex(ValueError, "authorizes orders"):
                status._microstructure_summary(root)


if __name__ == "__main__":
    unittest.main()
