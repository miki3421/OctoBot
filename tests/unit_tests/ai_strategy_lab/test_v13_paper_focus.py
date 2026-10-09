"""Focused status checks for the read-only V13 dashboard projection."""

import datetime
import importlib.util
import pathlib
import unittest


VIEW_PATH = pathlib.Path(__file__).resolve().parents[3] / "octobot/ai_strategy_lab/v13_paper_view.py"
SPEC = importlib.util.spec_from_file_location("v13_paper_view_focus", VIEW_PATH)
VIEW = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(VIEW)


class V13PaperFocusTest(unittest.TestCase):
    def setUp(self):
        self.now = datetime.datetime(2026, 9, 27, 14, 0, tzinfo=datetime.timezone.utc)
        self.paper = {
            "available": True,
            "legacy": False,
            "status": "healthy",
            "phase": "active",
            "last_check_at": self.now.isoformat(),
            "last_success_at": self.now.isoformat(),
            "last_market_at": self.now.isoformat(),
        }

    def test_missing_locked_model_keeps_existing_account_paused(self):
        source = {
            "status": "failed",
            "error": "selected model hash mismatch",
            "last_success_at": "2026-09-20T00:10:00+00:00",
        }

        focus = VIEW.paper_focus(self.paper, source, self.now)

        self.assertEqual(focus["title"], "PAPER IN PAUSA")
        self.assertIn("artefatto originale", focus["next_action"])

    def test_old_heartbeat_never_displays_active_paper(self):
        source = {"status": "healthy", "last_success_at": self.now.isoformat()}
        self.paper["last_check_at"] = "2026-09-21T12:00:00+00:00"
        self.assertEqual(VIEW.paper_focus(self.paper, source, self.now)["title"], "DATI SCADUTI")
        self.paper["last_check_at"] = self.now.isoformat()
        self.assertEqual(VIEW.paper_focus(self.paper, source, self.now)["title"], "PAPER ATTIVO")

    def test_old_market_quote_never_displays_active_paper(self):
        source = {"status": "healthy", "last_success_at": self.now.isoformat()}
        self.paper["last_market_at"] = "2026-09-21T12:00:00+00:00"
        self.assertEqual(VIEW.paper_focus(self.paper, source, self.now)["title"], "DATI SCADUTI")


if __name__ == "__main__":
    unittest.main()
