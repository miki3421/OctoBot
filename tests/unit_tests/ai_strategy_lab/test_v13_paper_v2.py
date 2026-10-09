"""Accounting and runtime regressions for the separately versioned V13 account."""

import copy
import datetime as dt
import json
import sqlite3

import pytest

from octobot.ai_strategy_lab import v13_paper_v2 as paper


UTC = dt.timezone.utc
START = dt.datetime(2026, 9, 12, 10, 0, tzinfo=UTC)


def quote(at, *, symbol="BTCUSDT", price=100.0, step=0.01, fee=0.001, funding=()):
    return {
        "symbol": symbol,
        "market_identity": "kucoin_futures_usdt",
        "timestamp": at.isoformat(),
        "mark_price": price,
        "step": step,
        "contract_multiplier": step,
        "quantity_step": step,
        "price_tick": 0.00000001,
        "min_quantity": step,
        "min_notional": 0.0,
        "fee_rate": fee,
        "funding": list(funding),
        "bids": [{"price": price - 0.1, "base_quantity": 100_000.0}],
        "asks": [{"price": price + 0.1, "base_quantity": 100_000.0}],
    }


def market(at, name="market-1"):
    return {
        "record_hash": name,
        "observed_at_start": at.isoformat(),
        "observed_at_end": at.isoformat(),
    }


def state(*, targets=None, noticed_at=START):
    return {
        "mode": paper.MODE,
        "initial_equity": paper.INITIAL_EQUITY,
        "activation_at": START.isoformat(),
        "positions": {},
        "order_count": 0,
        "last_bar": "2026-09-11",
        "last_market_hash": None,
        "executed_targets": None,
        "pending": {
            "targets": {"BTCUSDT": 0.1} if targets is None else targets,
            "noticed_at": noticed_at.isoformat(),
            "decision_hash": "decision-1",
        },
    }


def decision(weights=None, *, name="decision-1", available=None):
    available = available or START - dt.timedelta(hours=9)
    return {
        "journal_record_hash": name,
        "recorded_at": available.isoformat(),
        "decision_payload": {
            "bar_date": "2026-09-11",
            "decision_available_not_before_utc": available.isoformat(),
            "base": {"trend_daily_return": 999.0, "trend_equity": 1000.0},
            "research_targets": {
                "trend_component_weights": {"BTC/USDT:USDT": 0.1}
                if weights is None else weights,
                "trend_effective_portfolio_weights": {"BTC/USDT:USDT": 0.05},
            },
        },
    }


def counts(database):
    with sqlite3.connect(database) as connection:
        return {
            table: connection.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
            for table in (
                "orders", "funding_events", "marks", "market_events", "intents",
                "equity_history",
            )
        }


@pytest.fixture
def runtime(tmp_path, monkeypatch):
    current = {
        "records": [decision()],
        "market": market(START - dt.timedelta(minutes=15), "old-market"),
        "quotes": {"BTCUSDT": quote(START - dt.timedelta(minutes=15))},
    }
    monkeypatch.setattr(
        paper.upstream, "_load_upstream",
        lambda *args: (copy.deepcopy(current["records"]), {}, {}),
    )
    monkeypatch.setattr(
        paper.v13_market, "load_latest_market",
        lambda *args: copy.deepcopy(current["market"]),
    )

    def get_quotes(record, symbols):
        return {symbol: copy.deepcopy(current["quotes"][symbol]) for symbol in symbols}

    monkeypatch.setattr(paper.v13_market, "market_quotes", get_quotes)
    database, health = tmp_path / "v13-v2.sqlite", tmp_path / "health-v2.json"

    def run(at=START):
        return paper.run_once(
            tmp_path / "decisions.jsonl", tmp_path / "protocol.json",
            tmp_path / "lock.json", tmp_path / "market.jsonl", database, health,
            checked_at=at,
        )

    def tick(at, *, name="market-1", prices=None, funding=()):
        current["market"] = market(at, name)
        current["quotes"] = {
            symbol: quote(at, symbol=symbol, price=price, funding=funding)
            for symbol, price in (prices or {"BTCUSDT": 100.0}).items()
        }

    return current, database, health, run, tick


@pytest.mark.parametrize("direction", [1, -1])
def test_average_cost_add_reduce_reverse_and_close(direction):
    position = paper.new_position()
    paper.apply_fill(position, direction * 2, 100, 0.2)
    paper.apply_fill(position, direction * 2, 120, 0.24)
    assert position["quantity"] == direction * 4
    assert position["entry_price"] == 110
    paper.apply_fill(position, -direction, 130, 0.13)
    assert position["quantity"] == direction * 3
    assert position["entry_price"] == 110
    assert position["realized_pnl"] == direction * 20
    paper.apply_fill(position, -direction * 5, 90, 0.45)
    assert position["quantity"] == -direction * 2
    assert position["entry_price"] == 90
    assert position["realized_pnl"] == -direction * 40
    paper.apply_fill(position, direction * 2, 80, 0.16)
    assert position["quantity"] == 0
    assert position["entry_price"] == 0
    assert position["realized_pnl"] == -direction * 20
    assert position["fees"] == pytest.approx(1.18)


@pytest.mark.parametrize("quantity,price,fee", [
    (float("nan"), 100, 0), (1, float("inf"), 0), (1, 0, 0),
    (1, 100, -0.01), (1, 100, float("nan")),
])
def test_apply_fill_rejects_invalid_inputs_without_mutating(quantity, price, fee):
    position = paper.new_position()
    before = copy.deepcopy(position)
    with pytest.raises(ValueError):
        paper.apply_fill(position, quantity, price, fee)
    assert position == before


def test_totals_reconcile_open_and_closed_positions_without_losing_realized():
    account = state()
    account["positions"] = {
        "BTCUSDT": dict(paper.new_position(), quantity=2, entry_price=100,
                        current_price=110, realized_pnl=5, fees=1, funding=-0.5),
        "ETHUSDT": dict(paper.new_position(), realized_pnl=7, fees=0.2,
                        funding=-0.1),
    }
    metrics = paper.totals(account)
    assert metrics == pytest.approx({
        "equity": 10030.2, "pnl": 30.2, "realized_pnl": 12,
        "unrealized_pnl": 20, "fees": 1.2, "funding": -0.6,
    })
    assert metrics["equity"] == pytest.approx(
        10000 + metrics["realized_pnl"] + metrics["unrealized_pnl"]
        + metrics["funding"] - metrics["fees"]
    )


def test_standalone_component_weights_not_half_sleeve():
    assert paper.targets(decision()["decision_payload"]) == {"BTCUSDT": 0.1}


@pytest.mark.parametrize("weights,reason", [
    ({"BTCUSDT": 0.316}, "asset risk"),
    ({"BTCUSDT": float("nan")}, "asset risk"),
    ({"BTCUSDT": float("inf")}, "asset risk"),
    ({"BTCUSDT": 0.31, "ETHUSDT": 0.31, "SOLUSDT": -0.31}, "gross risk"),
    ({"BTC/USDT:USDT": 0.1, "BTCUSDT": 0.1}, "duplicated"),
    ({"BTCUSD": 0.1}, "symbol"),
])
def test_target_risk_guards(weights, reason):
    with pytest.raises(ValueError, match=reason):
        paper.targets(decision(weights)["decision_payload"])


def test_missing_component_targets_are_not_assumed_flat():
    with pytest.raises(ValueError, match="component targets missing"):
        paper.targets({"research_targets": {"trend_effective_portfolio_weights": {}}})


@pytest.mark.parametrize("offset", [-1, 0])
def test_fill_waits_until_quote_strictly_after_intent(offset):
    account = state()
    at = START + dt.timedelta(seconds=offset)
    result, fills, funding, _ = paper.process_market(
        account, market(at), {"BTCUSDT": quote(at)}, START,
    )
    assert result["pending"] is not None
    assert result["order_count"] == 0
    assert not fills and not funding
    assert account["positions"] == {}


def test_later_book_fills_quantity_at_adverse_price_and_reconciles_cost():
    account = state()
    at = START + dt.timedelta(minutes=15)
    result, fills, _, _ = paper.process_market(
        account, market(at), {"BTCUSDT": quote(at)}, at,
    )
    fill, = fills
    assert fill["quantity"] == 10
    assert fill["price"] == pytest.approx(100.1 * 1.0002)
    assert fill["fee"] == pytest.approx(10 * fill["price"] * 0.001)
    assert fill["decision_hash"] == "decision-1"
    assert result["pending"] is None
    assert result["executed_targets"] == {"BTCUSDT": 0.1}
    metrics = paper.totals(result)
    assert metrics["unrealized_pnl"] == pytest.approx(10 * (100 - fill["price"]))
    assert metrics["equity"] == pytest.approx(10000 + metrics["unrealized_pnl"] - fill["fee"])
    assert account["positions"] == {}


def test_quantity_is_rounded_down_without_minimum_inflation():
    account = state(targets={"BTCUSDT": 0.00009})
    at = START + dt.timedelta(minutes=15)
    result, fills, _, _ = paper.process_market(
        account, market(at), {"BTCUSDT": quote(at, step=0.01)}, at,
    )
    assert fills == []
    assert result["positions"]["BTCUSDT"]["quantity"] == 0
    assert paper.totals(result)["equity"] == 10000


@pytest.mark.parametrize("direction", [1, -1])
def test_funding_is_signed_and_each_settlement_is_applied_once(direction):
    account = state()
    account["pending"] = None
    account["positions"]["BTCUSDT"] = dict(
        paper.new_position(), quantity=direction * 2, entry_price=100,
        current_price=100, last_mark_at=START.isoformat(),
    )
    at = START + dt.timedelta(minutes=15)
    settlement = {"timestamp_ms": int((START + dt.timedelta(minutes=5)).timestamp() * 1000), "rate": 0.001}
    ignored = {"timestamp_ms": int(START.timestamp() * 1000), "rate": 0.2}
    quotes = {"BTCUSDT": quote(at, price=110, funding=[ignored, settlement])}
    result, fills, funding_rows, _ = paper.process_market(account, market(at), quotes, at)
    assert not fills
    assert len(funding_rows) == 1
    assert funding_rows[0][3:] == pytest.approx((direction * 2, 100, -direction * 0.2))
    assert result["positions"]["BTCUSDT"]["funding"] == pytest.approx(-direction * 0.2)
    later = at + dt.timedelta(minutes=15)
    again, _, repeated_funding, _ = paper.process_market(
        result, market(later, "later"),
        {"BTCUSDT": quote(later, price=112, funding=[ignored, settlement])}, later,
    )
    assert repeated_funding == []
    assert again["positions"]["BTCUSDT"]["funding"] == pytest.approx(-direction * 0.2)


def test_funding_history_gap_blocks_without_mutating_state():
    account = state()
    account["pending"] = None
    account["positions"]["BTCUSDT"] = dict(
        paper.new_position(), quantity=1, entry_price=100, current_price=100,
        last_mark_at=START.isoformat(),
    )
    before = copy.deepcopy(account)
    at = START + dt.timedelta(hours=20, seconds=1)
    with pytest.raises(ValueError, match="funding coverage gap"):
        paper.process_market(account, market(at), {"BTCUSDT": quote(at)}, at)
    assert account == before


def test_flat_account_can_wait_longer_than_funding_window():
    account = state(noticed_at=START)
    account["positions"]["BTCUSDT"] = dict(paper.new_position(), last_mark_at=START.isoformat())
    at = START + dt.timedelta(hours=21)
    result, fills, funding_rows, _ = paper.process_market(
        account, market(at), {"BTCUSDT": quote(at)}, at,
    )
    assert len(fills) == 1
    assert funding_rows == []
    assert result["positions"]["BTCUSDT"]["quantity"] > 0


def test_bad_second_leg_does_not_modify_first_leg_or_input(monkeypatch):
    account = state(targets={"BTCUSDT": 0.1, "ETHUSDT": -0.1})
    before = copy.deepcopy(account)
    at = START + dt.timedelta(minutes=15)
    original = paper.v13_market.fill_price

    def bad_second_leg(value, quantity):
        if value["mark_price"] == 200:
            raise ValueError("second leg has insufficient depth")
        return original(value, quantity)

    monkeypatch.setattr(paper.v13_market, "fill_price", bad_second_leg)
    with pytest.raises(ValueError, match="second leg"):
        paper.process_market(account, market(at), {
            "BTCUSDT": quote(at), "ETHUSDT": quote(at, symbol="ETHUSDT", price=200),
        }, at)
    assert account == before


def test_run_once_activation_later_quote_idempotence_and_restart(runtime):
    current, database, health, run, tick = runtime
    first = run()
    assert first["phase"] == "awaiting_market"
    assert first["equity"] == 10000
    assert first["order_count"] == 0
    assert counts(database)["orders"] == 0
    assert counts(database)["equity_history"] == 1
    at = START + dt.timedelta(minutes=15)
    tick(at)
    filled = run(at + dt.timedelta(seconds=2))
    assert filled["phase"] == "active"
    assert filled["positions"][0]["quantity"] == 10
    assert filled["equity"] < 10000  # The absurd upstream +999 return is ignored.
    before_counts = counts(database)
    for later in (at + dt.timedelta(minutes=1), at + dt.timedelta(minutes=2)):
        restarted = run(later)
        assert restarted["equity"] == filled["equity"]
        assert restarted["order_count"] == 1
        assert restarted["last_check_at"] == later.isoformat()
    assert counts(database) == before_counts
    assert json.loads(health.read_text())["mode"] == paper.MODE
    with sqlite3.connect(database) as connection:
        assert connection.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
        assert connection.execute("SELECT status FROM intents").fetchone()[0] == "executed"


def test_same_component_targets_on_new_decision_do_not_churn(runtime):
    current, database, _, run, tick = runtime
    run()
    at = START + dt.timedelta(minutes=15)
    tick(at)
    filled = run(at + dt.timedelta(seconds=2))
    current["records"].append(decision(name="decision-2", available=START + dt.timedelta(minutes=30)))
    current["records"][-1]["decision_payload"]["research_targets"]["trend_effective_portfolio_weights"] = {"BTC/USDT:USDT": 0.08}
    later = START + dt.timedelta(minutes=45)
    tick(later, name="market-2", prices={"BTCUSDT": 110})
    marked = run(later + dt.timedelta(seconds=2))
    assert marked["positions"][0]["quantity"] == 10
    assert marked["order_count"] == filled["order_count"] == 1
    assert marked["equity"] == pytest.approx(filled["equity"] + 100)
    assert counts(database)["intents"] == 1


def test_changed_targets_wait_for_new_book_then_close_and_preserve_realized(runtime):
    current, database, _, run, tick = runtime
    run()
    at = START + dt.timedelta(minutes=15)
    tick(at)
    opened = run(at + dt.timedelta(seconds=2))
    entry = opened["positions"][0]["entry_price"]
    current["records"].append(decision({}, name="flat-target", available=START + dt.timedelta(minutes=30)))
    notice = START + dt.timedelta(minutes=31)
    waiting = run(notice)
    assert waiting["phase"] == "awaiting_market"
    assert waiting["order_count"] == 1
    later = START + dt.timedelta(minutes=45)
    tick(later, name="market-close", prices={"BTCUSDT": 110})
    closed = run(later + dt.timedelta(seconds=2))
    assert closed["position_count"] == 0
    assert closed["unrealized_pnl"] == 0
    assert closed["order_count"] == 2
    with sqlite3.connect(database) as connection:
        exit_price = connection.execute("SELECT price FROM orders ORDER BY id DESC").fetchone()[0]
    assert closed["realized_pnl"] == pytest.approx(10 * (exit_price - entry))
    assert closed["equity"] == pytest.approx(10000 + closed["realized_pnl"] - closed["fees"])


def test_run_once_bad_leg_rolls_back_entire_tick_then_recovers(runtime, monkeypatch):
    current, database, _, run, tick = runtime
    current["records"] = [decision({"BTCUSDT": 0.1, "ETHUSDT": -0.1})]
    run()
    before = counts(database)
    at = START + dt.timedelta(minutes=15)
    tick(at, prices={"BTCUSDT": 100, "ETHUSDT": 200})
    original = paper.v13_market.fill_price

    def fail_second(value, quantity):
        if value["mark_price"] == 200:
            raise ValueError("second leg rejected")
        return original(value, quantity)

    monkeypatch.setattr(paper.v13_market, "fill_price", fail_second)
    blocked = run(at + dt.timedelta(seconds=2))
    assert blocked["status"] == "blocked"
    assert "second leg rejected" in blocked["reason"]
    assert blocked["equity"] == 10000 and blocked["order_count"] == 0
    assert counts(database) == before
    monkeypatch.setattr(paper.v13_market, "fill_price", original)
    recovered = run(at + dt.timedelta(seconds=3))
    assert recovered["status"] == "healthy"
    assert recovered["order_count"] == 2
    assert counts(database)["market_events"] == 1


def test_settled_funding_is_persisted_once_across_ticks_and_restarts(runtime):
    _, database, _, run, tick = runtime
    run()
    opened_at = START + dt.timedelta(minutes=15)
    tick(opened_at)
    opened = run(opened_at + dt.timedelta(seconds=2))
    settlement = {
        "timestamp_ms": int((START + dt.timedelta(minutes=20)).timestamp() * 1000),
        "rate": 0.001,
    }
    marked_at = START + dt.timedelta(minutes=30)
    tick(marked_at, name="funding-market", funding=[settlement])
    funded = run(marked_at + dt.timedelta(seconds=2))
    assert funded["funding"] == pytest.approx(-1)
    assert funded["equity"] == pytest.approx(opened["equity"] - 1)
    run(marked_at + dt.timedelta(minutes=1))
    later = START + dt.timedelta(minutes=45)
    tick(later, name="after-funding", funding=[settlement])
    repeated = run(later + dt.timedelta(seconds=2))
    assert repeated["funding"] == pytest.approx(-1)
    assert counts(database)["funding_events"] == 1
    with sqlite3.connect(database) as connection:
        saved = connection.execute(
            "SELECT quantity, reference_mark, amount FROM funding_events"
        ).fetchone()
    assert saved == pytest.approx((10, 100, -1))


def test_stale_quote_error_preserves_last_good_account_and_marks_blocked(runtime, monkeypatch):
    _, database, _, run, tick = runtime
    run()
    at = START + dt.timedelta(minutes=15)
    tick(at)
    opened = run(at + dt.timedelta(seconds=2))
    before = counts(database)

    def stale(*args):
        raise ValueError("stale market observation")

    monkeypatch.setattr(paper.v13_market, "load_latest_market", stale)
    blocked = run(at + dt.timedelta(hours=1))
    assert blocked["status"] == "blocked"
    assert blocked["reason"] == "stale_market_data"
    assert blocked["risk"]["market_veto"]["detail"] == "stale market observation"
    assert blocked["equity"] == opened["equity"]
    assert blocked["positions"] == opened["positions"]
    assert blocked["last_success_at"] == opened["last_success_at"]
    assert counts(database) == before


def test_new_target_supersedes_pending_intent_without_using_old_quote(runtime):
    current, database, _, run, tick = runtime
    run()
    changed_at = START + dt.timedelta(minutes=5)
    current["records"].append(decision(
        {"BTCUSDT": -0.2}, name="decision-short", available=changed_at,
    ))
    waiting = run(changed_at)
    assert waiting["equity"] == 10000 and waiting["order_count"] == 0
    at = START + dt.timedelta(minutes=15)
    tick(at)
    filled = run(at + dt.timedelta(seconds=2))
    assert filled["positions"][0]["quantity"] == -20
    assert filled["order_count"] == 1
    with sqlite3.connect(database) as connection:
        statuses = dict(connection.execute("SELECT decision_hash,status FROM intents"))
        source = connection.execute("SELECT decision_hash FROM orders").fetchone()[0]
    assert statuses == {"decision-1": "superseded", "decision-short": "executed"}
    assert source == "decision-short"


@pytest.mark.parametrize("change", ["truncate", "replace"])
def test_source_rollback_or_replacement_is_rejected_before_account_mutation(runtime, change):
    current, database, health, run, tick = runtime
    run()
    at = START + dt.timedelta(minutes=15)
    tick(at)
    run(at + dt.timedelta(seconds=2))
    updated_at = START + dt.timedelta(minutes=30)
    current["records"].append(decision(name="decision-2", available=updated_at))
    run(updated_at)
    before_counts = counts(database)
    health_before = health.read_bytes()
    with sqlite3.connect(database) as connection:
        state_before = connection.execute("SELECT payload FROM state").fetchone()[0]
    assert json.loads(state_before)["last_source_hash"] == "decision-2"
    if change == "truncate":
        current["records"].pop()
    else:
        current["records"][-1]["journal_record_hash"] = "replacement-hash"
    with pytest.raises(ValueError, match="source.*(rollback|rewrite|chain)|upstream.*(rollback|rewrite|chain)|continuity"):
        run(updated_at + dt.timedelta(minutes=1))
    assert counts(database) == before_counts
    assert health.read_bytes() == health_before  # CLI is responsible for the blocked health on raised preflight errors.
    with sqlite3.connect(database) as connection:
        assert connection.execute("SELECT payload FROM state").fetchone()[0] == state_before


def test_sql_failure_rolls_back_orders_marks_and_account_atomically(runtime):
    current, database, _, run, tick = runtime
    run()
    before = counts(database)
    with sqlite3.connect(database) as connection:
        connection.execute("""CREATE TRIGGER reject_tick BEFORE INSERT ON market_events
                              BEGIN SELECT RAISE(ABORT, 'test transaction abort'); END""")
    at = START + dt.timedelta(minutes=15)
    tick(at)
    blocked = run(at + dt.timedelta(seconds=2))
    assert blocked["status"] == "blocked"
    assert "test transaction abort" in blocked["reason"]
    assert blocked["equity"] == 10000
    assert counts(database) == before
    with sqlite3.connect(database) as connection:
        saved = json.loads(connection.execute("SELECT payload FROM state").fetchone()[0])
    assert saved["order_count"] == 0 and saved["positions"] == {}


@pytest.mark.parametrize("available", [
    START + dt.timedelta(seconds=1), START - dt.timedelta(hours=36, seconds=1),
])
def test_future_or_stale_signal_cannot_create_account(runtime, available):
    current, database, _, run, _ = runtime
    current["records"] = [decision(available=available)]
    with pytest.raises(ValueError, match="signal unavailable or stale"):
        run()
    assert not database.exists()


def test_legacy_database_refusal_does_not_mutate_legacy_file(tmp_path):
    database = tmp_path / "legacy.sqlite"
    with sqlite3.connect(database) as connection:
        connection.execute("CREATE TABLE state(id INTEGER PRIMARY KEY, payload TEXT)")
        connection.execute("INSERT INTO state VALUES(1, 'legacy evidence')")
    original = database.read_bytes()
    with pytest.raises(ValueError, match="legacy/non-V2"):
        paper.init_db(database)
    assert database.read_bytes() == original
    with sqlite3.connect(f"file:{database}?mode=ro", uri=True) as connection:
        assert connection.execute("PRAGMA journal_mode").fetchone()[0] == "delete"
        assert connection.execute("SELECT payload FROM state").fetchone()[0] == "legacy evidence"


def test_wrong_account_version_is_rejected(tmp_path):
    database = tmp_path / "wrong-version.sqlite"
    with sqlite3.connect(database) as connection:
        connection.execute("CREATE TABLE account_version(mode TEXT PRIMARY KEY)")
        connection.execute("INSERT INTO account_version VALUES('not_v13_v2')")
    with pytest.raises(ValueError, match="account version differs"):
        paper.init_db(database)


def test_health_never_authorizes_real_trading_and_includes_model_limitations(runtime):
    _, _, _, run, _ = runtime
    result = run()
    assert result["paper_only"] is True
    assert result["paper_orders_authorized"] is False
    for field in ("orders_authorized", "network_required", "credentials_used", "automatic_promotion"):
        assert result[field] is False
    assert result["legacy_account_excluded"] is True
    assert result["funding_model"] == "settled_rate_previous_observed_mark"
    assert "stimato" in result["funding_note"]


@pytest.fixture(autouse=True)
def isolate_global_gate_for_pre_p004_regression(monkeypatch):
    """Keep this earlier-stage unit suite isolated; real global gates have their own suite."""
    import contextlib
    from octobot.ai_strategy_lab import paper_runtime_authorization
    monkeypatch.setattr(paper_runtime_authorization, 'entry_scope', lambda *a, **k: contextlib.nullcontext({"test_only": True}))
