import json
import pathlib
import sqlite3

import pytest

from octobot.ai_strategy_lab import v13_paper_view as view


ACTIVATION = "2026-09-12T12:00:00+00:00"
QUOTE = "2026-09-12T12:15:12+00:00"


def health(**changes):
    return dict(mode=view.V2_MODE, status="healthy", paper_only=True,
                orders_authorized=False, paper_orders_authorized=True,
                credentials_used=False, network_required=False,
                automatic_promotion=False, legacy_account_excluded=True,
                initial_equity=10000.0, equity=10000.0, pnl=0.0,
                activation_at=ACTIVATION, realized_pnl=0.0, unrealized_pnl=0.0,
                fees=0.0, funding=0.0, positions=[], order_count=0,
                position_count=0, phase="awaiting_market", **changes)


def create_account(root, payload=None, *, legacy=False):
    payload = payload or health()
    (root / ("health.json" if legacy else "health-v2.json")).write_text(json.dumps(payload))
    database = root / ("v13.sqlite" if legacy else "v13-v2.sqlite")
    with sqlite3.connect(database) as db:
        db.executescript("""
            CREATE TABLE equity_history(bar TEXT PRIMARY KEY, equity REAL, pnl REAL);
            CREATE TABLE orders(id INTEGER PRIMARY KEY, bar TEXT, symbol TEXT,
                action TEXT, notional REAL, fee REAL, status TEXT, quantity REAL, price REAL);
            CREATE TABLE marks(bar TEXT, symbol TEXT, price REAL);
        """)
        db.execute("INSERT INTO equity_history VALUES (?,?,?)", (ACTIVATION, 10000, 0))
    return database


def test_new_flat_account_preserves_only_actual_activation_point(tmp_path):
    database = create_account(tmp_path)
    original = database.read_bytes()
    result = view.load_paper_view(tmp_path)
    assert result["history"] == [{"time": ACTIVATION, "value": 10000}]
    assert result["fills"] == result["symbol_charts"] == []
    assert result["legacy"] is False
    assert database.read_bytes() == original


def test_exact_fill_timestamp_and_price_do_not_use_chart_mark(tmp_path):
    database = create_account(tmp_path)
    with sqlite3.connect(database) as db:
        db.execute("INSERT INTO marks VALUES (?,?,?)", (QUOTE, "SOLUSDT", 100))
        db.execute("INSERT INTO orders VALUES (1,?,?,?,?,?,?,?,?)",
                   (QUOTE, "SOLUSDT", "BUY", 101, .06, "filled", 1, 101))
    result = view.load_paper_view(tmp_path)
    chart = result["symbol_charts"][0]
    assert chart["points"] == [{"time": QUOTE, "value": 100}]
    assert chart["fills"][0]["time"] == QUOTE
    assert chart["fills"][0]["price"] == 101
    assert chart["pnl"] is None  # Closed/missing position never fabricates zero profit.


def test_v2_is_preferred_without_legacy_history_or_positions(tmp_path):
    legacy = health()
    legacy.update(mode=view.LEGACY_MODE, equity=12345, pnl=2345,
                  positions=[{"symbol": "OLDUSDT"}])
    create_account(tmp_path, legacy, legacy=True)
    create_account(tmp_path)
    result = view.load_paper_view(tmp_path)
    assert result["equity"] == 10000
    assert result["positions"] == []
    assert "OLDUSDT" not in json.dumps(result)


def test_legacy_is_explicitly_unreconciled_and_has_no_fabricated_price_charts(tmp_path):
    legacy = health()
    legacy.update(mode=view.LEGACY_MODE, equity=12345, pnl=2345)
    create_account(tmp_path, legacy, legacy=True)
    result = view.load_paper_view(tmp_path)
    assert result["legacy"] is True
    assert "LEGACY NON RICONCILIATO" in result["label"]
    assert result["symbol_charts"] == []


def test_invalid_v2_does_not_silently_fall_back_to_legacy(tmp_path):
    legacy = health()
    legacy["mode"] = view.LEGACY_MODE
    create_account(tmp_path, legacy, legacy=True)
    (tmp_path / "health-v2.json").write_text("invalid json")
    with pytest.raises(ValueError):
        view.load_paper_view(tmp_path)


def test_absent_database_is_never_created_by_view(tmp_path):
    (tmp_path / "health-v2.json").write_text(json.dumps(health()))
    with pytest.raises(FileNotFoundError):
        view.load_paper_view(tmp_path)
    assert not (tmp_path / "v13-v2.sqlite").exists()


@pytest.mark.parametrize("field", ["orders_authorized", "credentials_used", "network_required"])
def test_rejects_unsafe_health(field):
    payload = health()
    payload[field] = True
    with pytest.raises(ValueError, match="safety"):
        view.summarize_health(payload)


def test_rejects_unreconciled_v2_and_nonfinite_equity():
    for changes in ({"pnl": 100, "equity": 10100}, {"equity": float("nan")}):
        payload = health()
        payload.update(changes)
        with pytest.raises(ValueError):
            view.summarize_health(payload)


@pytest.mark.parametrize("changes", [
    {"automatic_promotion": True}, {"legacy_account_excluded": False},
])
def test_v2_requires_isolation_and_no_automatic_promotion(changes):
    payload = health()
    payload.update(changes)
    with pytest.raises(ValueError, match="isolation"):
        view.summarize_health(payload)


def test_blocked_account_keeps_balances_and_reason_visible():
    payload = health()
    payload.update(status="blocked", phase="blocked", reason="stale market")
    result = view.summarize_health(payload)
    assert result["available"] is True
    assert result["equity"] == 10000
    assert result["reason"] == "stale market"


def test_reads_uncheckpointed_wal_data(tmp_path):
    database = create_account(tmp_path)
    writer = sqlite3.connect(database)
    try:
        writer.execute("PRAGMA journal_mode=WAL")
        writer.execute("INSERT INTO equity_history VALUES (?,?,?)", (QUOTE, 10000, 0))
        writer.commit()
        assert len(view.load_paper_view(tmp_path)["history"]) == 2
    finally:
        writer.close()


def test_rejects_preactivation_fills(tmp_path):
    database = create_account(tmp_path)
    with sqlite3.connect(database) as db:
        db.execute("INSERT INTO orders VALUES (1,?,?,?,?,?,?,?,?)",
                   ("2026-09-11", "SOLUSDT", "BUY", 100, .06, "filled", 1, 100))
    with pytest.raises(ValueError, match="predates"):
        view.load_paper_view(tmp_path)


def test_chart_source_uses_recorded_fill_prices_and_no_invented_capital_point():
    root = pathlib.Path(__file__).resolve().parents[3]
    interface = root / "packages/tentacles/Services/Interfaces/web_interface"
    chart_js = (interface / "static/js/common/portfolio_history.js").read_text()
    template = (interface / "templates/index.html").read_text()
    assert "history[0].time - 86400" not in chart_js
    assert "mode: 'lines+markers'" in chart_js
    assert "fills.map((f) => f.price)" in template
    assert "closeByDate" not in template


@pytest.mark.parametrize("phase,status,reason", [
    ("awaiting_market", "healthy", "In attesa del prossimo book"),
    ("active", "healthy", None),
    ("blocked", "blocked", "Quotazioni troppo vecchie"),
])
def test_paper_panel_renders_flat_waiting_active_and_blocked(tmp_path, phase, status, reason):
    from jinja2 import Environment, StrictUndefined
    payload = health()
    payload.update(phase=phase, status=status, reason=reason,
                   last_market_at=None, last_check_at=ACTIVATION,
                   last_bar="2026-09-11", execution_model="Observed depth",
                   funding_note="Approximation disclosed")
    create_account(tmp_path, payload)
    root = pathlib.Path(__file__).resolve().parents[3]
    source = (root / "packages/tentacles/Services/Interfaces/web_interface/templates/strategy_status.html").read_text()
    panel = source.split('<div id="lab-paper"', 1)[1].split("                <hr>", 1)[0]
    rendered = Environment(undefined=StrictUndefined).from_string(panel).render(
        v13_paper=view.load_paper_view(tmp_path), v13_paper_focus=view.paper_focus(view.load_paper_view(tmp_path), {}), metric_card=lambda *args: " | ".join(map(str, args)))
    assert "Nessuna posizione aperta" in rendered
    assert "Nessun fill" in rendered
    assert "Approximation disclosed" in rendered
    if status == "blocked":
        assert "BLOCCATO" in rendered
