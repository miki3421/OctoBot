import datetime
import importlib
import gzip
import json
import pathlib
import tempfile
import unittest

MODULE_PATH = pathlib.Path(__file__).resolve().parents[3] / "octobot" / "ai_strategy_lab" / "diversified_manual_paper_v1.py"
spec = importlib.util.spec_from_file_location(
    "diversified_manual_paper_v1_testable",
    MODULE_PATH,
)
paper = importlib.util.module_from_spec(spec)
assert spec and spec.loader
spec.loader.exec_module(paper)


class TestDiversifiedManualPaperV1(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.root = pathlib.Path(self.temporary.name)
        self.protocol = self.root / "protocol.json"
        self.lock = self.root / "lock.json"
        self.journal = self.root / "decisions.jsonl"
        self.database = self.root / "paper.sqlite"
        self.health = self.root / "health.json"
        self.protocol.write_text(
            json.dumps(
                {
                    "protocol_version": paper.UPSTREAM_PROTOCOL_VERSION,
                    "protocol_sha256": "protocol",
                    "orders_authorized": False,
                    "paper_orders_authorized": False,
                    "automatic_promotion": False,
                    "results": None,
                }
            ),
            encoding="utf-8",
        )
        self.lock.write_text(
            json.dumps(
                {
                    "observer_type": (
                        "diversified_trend_cointegration_forward_observer_v1"
                    ),
                    "protocol_sha256": "protocol",
                    "implementation_lock_sha256": "lock",
                    "orders_authorized": False,
                    "paper_orders_authorized": False,
                    "automatic_promotion": False,
                }
            ),
            encoding="utf-8",
        )

    def tearDown(self):
        self.temporary.cleanup()

    def _record(self, date, equity, previous_hash, trend=None, coin=None):
        payload = {
            "bar_date": date,
            "target_return_bearing_bar": (
                datetime.date.fromisoformat(date) + datetime.timedelta(days=1)
            ).isoformat(),
            "mode": "forward_research_target_only",
            "research_only": True,
            "orders_authorized": False,
            "paper_orders_authorized": False,
            "automatic_promotion": False,
            "credentials_used": False,
            "lineage": {
                "forward_protocol_sha256": "protocol",
                "implementation_lock_sha256": "lock",
            },
            "base": {"portfolio_equity": equity},
            "research_targets": {
                "cross_sleeve_netting_applied": False,
                "trend_effective_portfolio_weights": trend or {},
                "cointegration_effective_portfolio_weights": coin or {},
            },
        }
        payload["decision_payload_sha256"] = paper._json_hash(payload)
        record = {
            "decision_payload": payload,
            "previous_journal_hash": previous_hash,
        }
        record["journal_record_hash"] = paper._json_hash(record)
        return record

    def _write_records(self, records):
        self.journal.write_text(
            "".join(json.dumps(record, sort_keys=True) + "\n" for record in records),
            encoding="utf-8",
        )

    def _write_daily(self, bar_date: str, symbols: dict[str, tuple[float, float]]):
        path = self.root / "daily" / f"{bar_date}.json.gz"
        path.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "bar_date": bar_date,
            "symbols": {
                symbol: {
                    "close": close,
                    "funding_rate_sum": funding,
                }
                for symbol, (close, funding) in symbols.items()
            },
        }
        with gzip.open(path, "wt", encoding="utf-8") as stream:
            json.dump(payload, stream)

    def test_first_run_arms_without_crediting_prior_forward_return(self):
        first = self._record("2026-09-03", 1.0064, None, {"SOL": 0.1})
        self._write_records([first])

        health = paper.run_once(
            self.journal, self.protocol, self.lock, self.database, self.health
        )

        self.assertEqual(health["phase"], "armed_waiting_next_decision")
        self.assertEqual(health["paper_equity"], 10_000.0)
        self.assertFalse(health["prior_forward_return_credited"])
        self.assertEqual(health["order_event_count"], 0)

    def test_next_record_activates_and_later_record_does_not_track_upstream(self):
        first = self._record("2026-09-03", 1.0064, None)
        self._write_records([first])
        paper.run_once(
            self.journal, self.protocol, self.lock, self.database, self.health
        )
        second = self._record(
            "2026-09-04",
            1.01,
            first["journal_record_hash"],
            {"SOL": 0.1},
            {"PAIR": -0.05},
        )
        self._write_daily("2026-09-03", {"SOL": (100.0, 0.0), "PAIR": (50.0, 0.0)})
        self._write_records([first, second])

        active = paper.run_once(
            self.journal, self.protocol, self.lock, self.database, self.health
        )

        self.assertEqual(active["phase"], "active")
        self.assertAlmostEqual(active["paper_equity"], 9_998.8)
        self.assertEqual(active["order_event_count"], 2)
        third = self._record(
            "2026-09-05",
            1.02,
            second["journal_record_hash"],
            {"SOL": 0.1},
            {"PAIR": -0.05},
        )
        self._write_daily("2026-09-04", {"SOL": (100.0, 0.0), "PAIR": (50.0, 0.0)})
        self._write_daily("2026-09-05", {"SOL": (100.0, 0.0), "PAIR": (50.0, 0.0)})
        self._write_records([first, second, third])

        updated = paper.run_once(
            self.journal, self.protocol, self.lock, self.database, self.health
        )

        self.assertAlmostEqual(updated["paper_equity"], 9_998.8)
        self.assertEqual(updated["decision_count"], 2)
        self.assertEqual(updated["order_event_count"], 2)

    def test_price_and_funding_returns_become_paper_changes(self):
        first = self._record("2026-09-03", 1.0064, None)
        self._write_records([first])
        paper.run_once(
            self.journal, self.protocol, self.lock, self.database, self.health
        )
        second = self._record(
            "2026-09-04",
            1.01,
            first["journal_record_hash"],
            {"BTC/USDT:USDT": 1.0},
            {},
        )
        self._write_daily("2026-09-03", {"BTCUSDT": (100.0, 0.0)})
        self._write_records([first, second])
        paper.run_once(
            self.journal, self.protocol, self.lock, self.database, self.health
        )

        third = self._record(
            "2026-09-05",
            1.02,
            second["journal_record_hash"],
            {"BTC/USDT:USDT": 1.0},
            {},
        )
        self._write_daily(
            "2026-09-04",
            {"BTCUSDT": (100.0, 0.001)},
        )
        self._write_daily(
            "2026-09-05",
            {"BTCUSDT": (110.0, 0.002)},
        )
        self._write_records([first, second, third])

        updated = paper.run_once(
            self.journal, self.protocol, self.lock, self.database, self.health
        )

        expected_after_activation = 10_000.0 - 10_000.0 * 0.0008
        expected_after_active = expected_after_activation * (1.0 + 0.1 - 0.002)
        self.assertAlmostEqual(updated["paper_equity"], expected_after_active)

    def test_partial_close_and_inversion_use_rebalance_turnover_only(self):
        first = self._record("2026-09-03", 1.0064, None)
        self._write_records([first])
        paper.run_once(
            self.journal, self.protocol, self.lock, self.database, self.health
        )
        second = self._record(
            "2026-09-04",
            1.01,
            first["journal_record_hash"],
            {"BTC/USDT:USDT": 0.60},
            {},
        )
        self._write_daily("2026-09-03", {"BTCUSDT": (80.0, 0.0)})
        self._write_records([first, second])
        paper.run_once(
            self.journal, self.protocol, self.lock, self.database, self.health
        )

        third = self._record(
            "2026-09-05",
            1.02,
            second["journal_record_hash"],
            {"BTC/USDT:USDT": 0.50},
            {},
        )
        self._write_daily(
            "2026-09-04",
            {"BTCUSDT": (80.0, 0.0)},
        )
        self._write_daily(
            "2026-09-05",
            {"BTCUSDT": (80.0, 0.0)},
        )
        self._write_records([first, second, third])

        after_partial = paper.run_once(
            self.journal, self.protocol, self.lock, self.database, self.health
        )

        fourth = self._record(
            "2026-09-06",
            1.03,
            third["journal_record_hash"],
            {"BTC/USDT:USDT": -0.40},
            {},
        )
        self._write_daily(
            "2026-09-06",
            {"BTCUSDT": (80.0, 0.0)},
        )
        self._write_records([first, second, third, fourth])

        final_health = paper.run_once(
            self.journal, self.protocol, self.lock, self.database, self.health
        )

        expected_after_activation = 10_000.0 - 10_000.0 * 0.60 * 0.0008
        expected_after_partial = expected_after_activation * (1.0 - 0.10 * 0.0008)
        expected_after_inversion = expected_after_partial * (1.0 - 0.9 * 0.0008)

        self.assertAlmostEqual(after_partial["paper_equity"], expected_after_partial)
        self.assertAlmostEqual(final_health["paper_equity"], expected_after_inversion)
        self.assertEqual(final_health["order_event_count"], 3)

    def test_active_mark_to_market_skipped_when_snapshot_missing(self):
        first = self._record("2026-09-03", 1.0064, None)
        self._write_records([first])
        paper.run_once(
            self.journal, self.protocol, self.lock, self.database, self.health
        )
        second = self._record(
            "2026-09-04",
            1.01,
            first["journal_record_hash"],
            {"BTC": 0.40},
            {},
        )
        self._write_daily("2026-09-03", {"BTC": (100.0, 0.0)})
        self._write_records([first, second])
        paper.run_once(
            self.journal, self.protocol, self.lock, self.database, self.health
        )

        third = self._record(
            "2026-09-05",
            1.02,
            second["journal_record_hash"],
            {"BTC": 0.40},
            {},
        )
        self._write_daily("2026-09-04", {"BTC": (100.0, 0.0)})
        # Intentionally omit 2026-09-05 snapshot: mark-to-market should be deferred.
        self._write_records([first, second, third])

        missing = paper.run_once(
            self.journal, self.protocol, self.lock, self.database, self.health
        )

        expected_after_activation = 10_000.0 - 10_000.0 * 0.40 * 0.0008
        self.assertFalse(missing["market_data_available"])
        self.assertIn("daily market snapshot missing: 2026-09-05", missing["market_data_warning"])
        self.assertAlmostEqual(missing["paper_equity"], expected_after_activation)

    def test_reprocess_does_not_duplicate_orders_on_restart(self):
        first = self._record("2026-09-03", 1.0064, None, {"BTC": 1.0}, {})
        self._write_records([first])
        paper.run_once(
            self.journal, self.protocol, self.lock, self.database, self.health
        )
        second = self._record(
            "2026-09-04",
            1.01,
            first["journal_record_hash"],
            {"BTC": 1.0},
            {},
        )
        self._write_daily("2026-09-03", {"BTC": (100.0, 0.0)})
        third = self._record(
            "2026-09-05",
            1.02,
            second["journal_record_hash"],
            {"BTC": 1.0},
            {},
        )
        self._write_daily("2026-09-04", {"BTC": (100.0, 0.0)})
        self._write_daily("2026-09-05", {"BTC": (100.0, 0.0)})
        self._write_records([first, second, third])

        initial = paper.run_once(
            self.journal, self.protocol, self.lock, self.database, self.health
        )
        repeat = paper.run_once(
            self.journal, self.protocol, self.lock, self.database, self.health
        )

        self.assertEqual(initial["decision_count"], repeat["decision_count"])
        self.assertEqual(initial["order_event_count"], repeat["order_event_count"])
        self.assertEqual(initial["paper_equity"], repeat["paper_equity"])

    def test_upstream_paper_authorization_fails_closed(self):
        first = self._record("2026-09-03", 1.0, None)
        first["decision_payload"]["paper_orders_authorized"] = True
        first["decision_payload"]["decision_payload_sha256"] = paper._json_hash(
            {
                key: value
                for key, value in first["decision_payload"].items()
                if key != "decision_payload_sha256"
            }
        )
        first["journal_record_hash"] = paper._json_hash(
            {
                key: value
                for key, value in first.items()
                if key != "journal_record_hash"
            }
        )
        self._write_records([first])

        with self.assertRaisesRegex(paper.PaperMirrorError, "safety invariant"):
            paper.run_once(
                self.journal,
                self.protocol,
                self.lock,
                self.database,
                self.health,
            )


if __name__ == "__main__":
    unittest.main()
import importlib
