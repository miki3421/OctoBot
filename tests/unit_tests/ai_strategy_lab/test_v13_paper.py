import gzip
import json

from octobot.ai_strategy_lab import v13_paper


def test_v13_paper_creates_only_trend_positions_and_is_idempotent(tmp_path, monkeypatch):
    # Historical accounting unit fixture, not an operational authorization.
    monkeypatch.setattr(v13_paper.paper_runtime_authorization, "unsupported_execution", lambda *args: None)
    payload = {
        "bar_date": "2026-09-06",
        "research_targets": {
            "trend_effective_portfolio_weights": {"BTC/USDT:USDT": 0.1},
            "cointegration_effective_portfolio_weights": {"ETH/USDT:USDT": -0.2},
        },
    }
    journal = tmp_path / "decisions.jsonl"
    journal.write_text(json.dumps({"decision_payload": payload}) + "\n")
    (tmp_path / "daily").mkdir()
    with gzip.open(tmp_path / "daily" / "2026-09-06.json.gz", "wt") as stream:
        json.dump({"symbols": {"BTCUSDT": {"close": 100000.0, "funding_rate_sum": 0.0}}}, stream)
    database, health = tmp_path / "v13.sqlite", tmp_path / "health.json"

    first = v13_paper.run_once(journal, database, health)
    second = v13_paper.run_once(journal, database, health)

    assert first == second
    assert first["order_count"] == 1
    assert first["position_count"] == 1
    assert first["positions"][0]["symbol"] == "BTCUSDT"
    assert first["positions"][0]["entry_price"] == 100000.0
    assert first["positions"][0]["unrealized_pnl"] == 0.0
    assert first["paper_only"] is True
    assert first["orders_authorized"] is False
