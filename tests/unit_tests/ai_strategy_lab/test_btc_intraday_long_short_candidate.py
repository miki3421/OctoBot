"""Synthetic offline evidence only: no strategy edge or exchange admissibility."""
import copy
from decimal import Decimal
import json
from pathlib import Path
import sys
import unittest

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "octobot/ai_strategy_lab"))
import btc_intraday_long_short_candidate as m


def window(multiplier="1.02", count=18):
    rows = []
    for i in range(289):
        at = (1000 + i) * m.GRID
        prices = {s: "100" for s in m.UNIVERSE}
        if i == 288:
            chosen = ["BTCUSDT"] + [s for s in m.UNIVERSE if s != "BTCUSDT"]
            for s in chosen[:count]:
                prices[s] = str(Decimal(100) * Decimal(multiplier))
        rows.append(dict(slot_ns=at, quotes={s: dict(price=prices[s], exchange_ns=at - 2 * m.NS,
                      received_ns=at - m.NS, available_ns=at - m.NS) for s in m.UNIVERSE}))
    return rows


def book():
    return {f"{s}_{k}_{i}": (100000 - i if s == "bid" else 100000 + i) if k == "price" else 100
            for s in ("bid", "ask") for k in ("price", "size") for i in range(1, 6)}


class SignalTests(unittest.TestCase):
    def run_signal(self, rows, **kw):
        at = rows[288]["slot_ns"]
        return m.signal(rows, at, at + 2 * m.NS, **kw)

    def test_long_is_only_in_candidate_and_short_in_both(self):
        self.assertEqual(self.run_signal(window())["status"], "LONG")
        self.assertEqual(self.run_signal(window(), short_only=True)["status"], "NO_SIGNAL")
        for short_only in (False, True):
            self.assertEqual(self.run_signal(window(".98"), short_only=short_only)["status"], "SHORT")

    def test_inclusive_btc_threshold_and_strict_breadth(self):
        for move, count, expected in [("1.01", 12, "LONG"), (".99", 12, "SHORT"),
                                       ("1.0099", 18, "NO_SIGNAL"), (".9901", 18, "NO_SIGNAL"),
                                       ("1.02", 11, "NO_SIGNAL"), ("1", 18, "NO_SIGNAL")]:
            with self.subTest(move=move, count=count):
                self.assertEqual(self.run_signal(window(move, count))["status"], expected)

    def test_future_prices_cannot_change_signal_or_identity(self):
        rows = window(); before = self.run_signal(rows)
        future = copy.deepcopy(rows[-1]); future["slot_ns"] += m.GRID
        future["quotes"]["BTCUSDT"]["price"] = "NaN"
        self.assertEqual(self.run_signal(rows + [future]), before)

    def test_non_feature_receipt_change_does_not_change_decision_identity(self):
        rows = window(); before = self.run_signal(rows)
        for row in rows:
            for q in row["quotes"].values():
                q["available_ns"] += 1
        self.assertEqual(self.run_signal(rows), before)

    def test_missing_symbol_row_duplicate_and_stale_deny(self):
        cases = []
        rows = window(); rows[70]["quotes"].pop("ETHUSDT"); cases.append(rows)
        rows = window(); rows.pop(80); cases.append(rows)
        rows = window(); rows.insert(0, copy.deepcopy(rows[0])); cases.append(rows)
        rows = window(); rows[90]["quotes"]["BTCUSDT"]["exchange_ns"] -= 121 * m.NS; cases.append(rows)
        for rows in cases:
            at = (1000 + 288) * m.GRID
            self.assertEqual(m.signal(rows, at, at)["status"], "MISSING")

    def test_late_persistence_is_not_retroactively_available(self):
        rows = window(); q = rows[-1]["quotes"]["BTCUSDT"]
        q["available_ns"] = rows[-1]["slot_ns"] + 1
        self.assertEqual(self.run_signal(rows)["reason"], "INPUT_NOT_CAUSAL_OR_STALE")

    def test_invalid_prices_never_produce_proposal(self):
        for price in ("NaN", "Infinity", "-1", "0", True, None):
            rows = window(); rows[-1]["quotes"]["BTCUSDT"]["price"] = price
            result = self.run_signal(rows)
            self.assertEqual(result["status"], "MISSING")
            self.assertNotIn("decision_id", result)

    def test_deadline_clock_and_no_issuance(self):
        rows = window(); at = rows[-1]["slot_ns"]
        self.assertEqual(m.signal(rows, at, at + 30 * m.NS + 1)["status"], "MISSED_DEADLINE")
        self.assertEqual(m.signal(rows, at, at - 1)["status"], "MISSING")
        self.assertEqual(m.signal(rows, at, at + 30 * m.NS)["status"], "LONG")
        result = self.run_signal(rows)
        self.assertTrue(result["research_only"]); self.assertFalse(result["issuable"])


class PricingTests(unittest.TestCase):
    def test_cost_parity_with_pinned_reference_for_both_sides_and_stress(self):
        fixture = json.loads((Path(__file__).parent / "fixtures/btc_intraday_ls_cost_reference_v1.json").read_text())
        self.assertEqual(fixture["reference_sha256"], "52e2d6843527c3ef1bdffc32ffef982a0e06adf7eea7fe8f1335f0480282e555")
        for case in fixture["cases"]:
            with self.subTest(q=case["quantity"], stress=case["stress"], partial=case["partial"]):
                value = m.execution(case["book"], case["quantity"], stress=case["stress"], partial=case["partial"])
                if case["expected"] is None:
                    self.assertIsNone(value)
                else:
                    for actual, expected in zip(value, case["expected"]):
                        self.assertAlmostEqual(float(actual), float(expected), places=10)

    def test_buy_and_sell_pay_costs_in_primary_and_stress(self):
        for stress in (False, True):
            bought = m.execution(book(), ".005", stress=stress)
            sold = m.execution(book(), "-.005", stress=stress)
            self.assertGreater(bought[1], 100001); self.assertLess(sold[1], 99999)
            self.assertGreater(bought[2], 0); self.assertGreater(sold[2], 0)
            self.assertLess(Decimal(".005") * (sold[1] - bought[1]) - sold[2] - bought[2], 0)

    def test_size_caps_and_round_toward_zero(self):
        self.assertEqual(m.quantity(10000, 80000), Decimal(".010"))
        self.assertEqual(m.quantity(100, 100000), 0)
        for e, p in [(10000, 200000), (1250, 80000)]:
            q = m.quantity(e, p)
            self.assertLessEqual(q * p, Decimal(".1") * e)
            self.assertLessEqual(q, Decimal(".010"))

    def test_sizing_parity_with_frozen_reference_cases(self):
        fixture = json.loads((Path(__file__).parent / "fixtures/btc_intraday_ls_cost_reference_v1.json").read_text())
        for case in fixture["sizing_cases"]:
            self.assertEqual(m.quantity(case["equity"], case["price"]), Decimal(case["expected"]))

    def test_bad_book_or_numeric_input_rejected(self):
        for field, value in [("ask_price_1", 1), ("bid_size_2", -1), ("ask_price_3", "NaN")]:
            b = book(); b[field] = value
            with self.assertRaises(ValueError): m.execution(b, ".005")
        with self.assertRaises(ValueError): m.execution(book(), True)

    def test_long_bid_and_short_ask_exits_with_priority(self):
        self.assertEqual(m.exit_trigger(".005", 100, 99, 101, 21600), "STOP_LOSS")
        self.assertEqual(m.exit_trigger("-.005", 100, 99, 101, 21600), "STOP_LOSS")
        self.assertEqual(m.exit_trigger(".005", 100, 102, 103, 21600), "TIME_EXIT")
        self.assertEqual(m.exit_trigger(".005", 100, 102, 103, 10), "TAKE_PROFIT")
        self.assertEqual(m.exit_trigger("-.005", 100, 97, 98, 10), "TAKE_PROFIT")
        self.assertIsNone(m.exit_trigger(".005", 100, 100, 102, 10))

    def test_signed_funding_unknown_and_stress(self):
        self.assertEqual(m.funding_cashflow(".01", 80000, ".001"), Decimal("-.80000"))
        self.assertEqual(m.funding_cashflow("-.01", 80000, ".001"), Decimal(".80000"))
        self.assertEqual(m.funding_cashflow(".01", 80000, "-.001"), Decimal(".80000"))
        self.assertEqual(m.funding_cashflow(".01", 80000, ".001", stress=True), Decimal("-1.60000"))
        self.assertEqual(m.funding_cashflow("-.01", 80000, ".001", stress=True), 0)
        self.assertIsNone(m.funding_cashflow(".01", 80000, None))


class ComparisonTests(unittest.TestCase):
    def series(self, last=10000):
        return [dict(at_ns=i*m.GRID, equity=10000 if i < 2 else last, complete=True) for i in range(3)]

    def test_same_window_zero_trade_control_and_net_difference(self):
        result = m.paired_equity(self.series(), self.series(10003), 0, 2*m.GRID)
        self.assertEqual(result["difference_usdt"], "3")
        self.assertEqual(result["control_net_usdt"], "0")
        self.assertEqual(result["points"], 3)

    def test_missing_duplicate_or_provisional_points_not_silently_removed(self):
        for kind in ("missing", "duplicate", "provisional", "nan", "different_seed"):
            rows = self.series()
            if kind == "missing": rows.pop(1)
            elif kind == "duplicate": rows.append(rows[1])
            elif kind == "provisional": rows[1]["complete"] = False
            elif kind == "nan": rows[1]["equity"] = "NaN"
            else: rows[0]["equity"] = 9999
            with self.assertRaises(ValueError): m.paired_equity(self.series(), rows, 0, 2*m.GRID)

    def test_out_of_window_history_is_not_candidate_pnl(self):
        rows = self.series(10003) + [dict(at_ns=3*m.GRID, equity=999999, complete=True)]
        self.assertEqual(m.paired_equity(self.series(), rows, 0, 2*m.GRID)["difference_usdt"], "3")

    def test_protocol_is_inert_and_uses_frozen_reference_costs(self):
        p = json.loads((ROOT / "docs/research-protocols/btc-intraday-long-short-comparison-candidate-v1.json").read_text())
        self.assertFalse(p["orders_authorized"]); self.assertFalse(p["paper_orders_authorized"])
        self.assertFalse(p["implementation_readiness"]["activation_authorized"])
        self.assertIsNone(p["comparison"]["start_utc"])
        self.assertEqual(p["execution"]["costs"]["taker_fee_bps_per_fill"], 6)
        self.assertEqual(p["research_contract"]["real_min_quantity"], "UNKNOWN")
        self.assertEqual(p["research_contract"]["real_min_notional"], "UNKNOWN")


if __name__ == "__main__":
    unittest.main()
