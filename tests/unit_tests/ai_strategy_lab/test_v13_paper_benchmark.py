"""Offline benchmark coverage: replay identity, distinct controls, fail-closed inputs."""
import copy
import datetime as dt
import hashlib
import json
import sqlite3

import pytest

from octobot.ai_strategy_lab import v13_paper_benchmark as benchmark
from octobot.ai_strategy_lab import v13_paper_v2 as paper


START = dt.datetime(2026, 9, 12, 10, 0, tzinfo=paper.UTC)
SYMBOLS = [f"ASSET{i}USDT" for i in range(19)]


def record(at, *, previous=None, prices=None, price_tick=0.00000001):
    book_at = int((at - dt.timedelta(seconds=1)).timestamp() * 1000)
    interval = 8 * 3600 * 1000
    settlement = book_at // interval * interval
    result = dict(schema_version=1, mode="observation_only", public_data_only=True,
        credentials_used=False, orders_authorized=False, symbol_count=19,
        completeness=1, observed_at_start=(at-dt.timedelta(seconds=2)).isoformat(),
        observed_at_end=at.isoformat(), previous_record_hash=previous, symbols={})
    for symbol in SYMBOLS:
        price = (prices or {}).get(symbol, 100)
        result["symbols"][symbol] = dict(futures_symbol=symbol,
            futures=dict(mark_price=price, contract_multiplier=0.1,
                # Explicit synthetic constraints; no archived evidence is amended.
                quantity_step=0.1, price_tick=price_tick,
                min_quantity=0.1, min_notional=0.0,
                conservative_taker_fee_rate=0.0006, book_timestamp_ms=book_at,
                normalized_bids=[dict(price=price-0.01, base_quantity=100000)],
                normalized_asks=[dict(price=price+0.01, base_quantity=100000)]),
            funding=dict(granularity_ms=interval, time_point_ms=settlement,
                funding_time_ms=settlement+interval,
                settled_last_24h=[dict(timestamp_ms=settlement-interval, rate=0.0002),
                                   dict(timestamp_ms=settlement, rate=0.0002)]))
    result["record_hash"] = hashlib.sha256(json.dumps(result, sort_keys=True,
        separators=(",", ":"), allow_nan=False).encode()).hexdigest()
    return result


def build_account(path, *, rebalance=False, price_tick=0.00000001):
    db = paper.init_db(path)
    state = benchmark.fresh_state(dict(initial_equity=10000, activation_at=START.isoformat()))
    state["last_bar"] = "2026-09-11"
    db.execute("INSERT INTO equity_history VALUES (?,?,?)", (START.isoformat(), 10000, 0))
    first = record(START+dt.timedelta(minutes=15), price_tick=price_tick)
    second = record(START+dt.timedelta(hours=8), previous=first["record_hash"], prices={SYMBOLS[0]:110})
    third = record(START+dt.timedelta(hours=9), previous=second["record_hash"], prices={SYMBOLS[0]:120, SYMBOLS[1]:90})
    for index, event in enumerate((first, second, third)):
        if index == 0 or (index == 1 and rebalance):
            decision_hash = f"decision-{index}"
            noticed = START if index == 0 else START+dt.timedelta(hours=7)
            targets = {SYMBOLS[index]:0.2}
            state["pending"] = dict(targets=targets, noticed_at=noticed.isoformat(), decision_hash=decision_hash)
            db.execute("INSERT INTO intents VALUES (?,?,?,?,?)", (decision_hash,
                noticed.isoformat(), "2026-09-11", json.dumps(targets), "executed"))
        checked = paper.timestamp(event["observed_at_end"])+dt.timedelta(seconds=10)
        state, fills, funding, marks = paper.process_market(state, event,
            paper.v13_market.market_quotes(event, SYMBOLS), checked)
        for fill in fills:
            fields = list(fill)
            db.execute(f"INSERT INTO orders({','.join(fields)}) VALUES ({','.join('?' for _ in fields)})", tuple(fill.values()))
        db.executemany("INSERT INTO funding_events VALUES (?,?,?,?,?,?)", funding)
        db.executemany("INSERT INTO marks VALUES (?,?,?)", marks)
        db.execute("INSERT INTO market_events VALUES (?,?,?,?)", (event["record_hash"],
            event["observed_at_end"], checked.isoformat(), json.dumps(event)))
        total = paper.totals(state)
        db.execute("INSERT INTO equity_history VALUES (?,?,?)", (event["observed_at_end"], total["equity"], total["pnl"]))
    db.execute("INSERT INTO state VALUES (1,?)", (json.dumps(state),))
    db.commit()
    db.close()
    return path


def test_initial_hold_is_exact_negative_control_and_ew_is_independent(tmp_path):
    source = build_account(tmp_path / "source.sqlite")
    before = benchmark.sha256(source)
    result = benchmark.replay(source)
    assert benchmark.sha256(source) == before
    actual = result["accounts"]["actual_v13_v2"]
    held = result["accounts"]["hold_actual_initial_v13_quantities"]
    basket = result["accounts"]["buy_hold_all_19_equal_weight_initial_v13_target_gross"]
    assert actual["equity_curve"] == held["equity_curve"]
    assert actual["fills"] == held["fills"]
    assert actual["pnl"] > basket["pnl"]
    assert basket["fill_count"] == 19
    assert basket["initial_target_gross_usdt"] == actual["initial_target_gross_usdt"] == 2000
    assert basket["rounding_unallocated_budget_usdt"] > actual["rounding_unallocated_budget_usdt"]
    for item in (actual, held, basket):
        assert item["equity"] == pytest.approx(10000+item["price_pnl"]+item["funding"]-item["fees"])
        assert item["funding"] < 0
        assert item["annualized_return"] is None
        assert item["realized_annual_volatility"] is None
        assert sum(p["net_pnl_usdt"] for p in item["asset_attribution"].values()) == pytest.approx(item["pnl"])
        assert len(item["equity_curve"]) == 4


def test_hold_keeps_original_quantities_after_actual_rebalance(tmp_path):
    result = benchmark.replay(build_account(tmp_path/"source.sqlite", rebalance=True))
    actual = result["accounts"]["actual_v13_v2"]
    held = result["accounts"]["hold_actual_initial_v13_quantities"]
    assert actual["fill_count"] == 3
    assert held["fill_count"] == 1
    assert actual["asset_attribution"][SYMBOLS[0]]["quantity"] == 0
    assert held["asset_attribution"][SYMBOLS[0]]["quantity"] == 20
    assert actual["pnl"] != held["pnl"]
    assert result["actual_rebalance_fill_batches"] == 1


@pytest.mark.parametrize("statement,reason", [
    ("UPDATE equity_history SET equity=equity+1 WHERE pnl != 0", "tick equity"),
    ("UPDATE orders SET quantity=quantity+0.01 WHERE id=1", "one-contract quantity"),
    ("UPDATE orders SET price=price+1 WHERE id=1", "depth VWAP fill"),
    ("UPDATE intents SET noticed_at='2026-09-12T11:00:00+00:00'", "noncausal"),
    ("DELETE FROM funding_events", "funding event missing"),
    ("UPDATE funding_events SET amount=0", "funding amount"),
    ("UPDATE account_version SET mode='trend_v13_paper_v1'", "not a V13 V2"),
])
def test_corrupt_ledger_is_not_a_benchmark(statement, reason, tmp_path):
    source = build_account(tmp_path/"source.sqlite")
    with sqlite3.connect(source) as db:
        db.execute(statement)
    with pytest.raises(ValueError, match=reason):
        benchmark.replay(source)


def test_hash_corruption_fails_even_if_price_would_be_favorable(tmp_path):
    source = build_account(tmp_path/"source.sqlite")
    with sqlite3.connect(source) as db:
        row = db.execute("SELECT record_hash,payload FROM market_events ORDER BY observed_at LIMIT 1").fetchone()
        payload = json.loads(row[1])
        payload["symbols"][SYMBOLS[0]]["futures"]["mark_price"] = 1000
        db.execute("UPDATE market_events SET payload=? WHERE record_hash=?", (json.dumps(payload), row[0]))
    with pytest.raises(ValueError, match="record hash"):
        benchmark.replay(source)


def test_snapshot_reads_committed_wal_and_replay_is_reproducible(tmp_path):
    source = build_account(tmp_path/"source.sqlite")
    # Keep WAL open during backup; the source never needs a checkpoint/write.
    writer = sqlite3.connect(source)
    writer.execute("PRAGMA journal_mode=WAL")
    writer.execute("UPDATE intents SET bar='2026-09-12'")
    writer.commit()
    snapshot = benchmark.capture_snapshot(source, tmp_path)
    try:
        capture = json.loads((snapshot.parent/"capture.json").read_text())
        assert capture["snapshot_sha256"] == benchmark.sha256(snapshot)
        assert benchmark.replay(snapshot)["first_intent"]["bar"] == "2026-09-12"
        assert benchmark.replay(snapshot) == benchmark.replay(snapshot)
        assert snapshot.parent != source.parent
    finally:
        writer.close()


def test_report_output_never_overwrites_an_existing_file(tmp_path):
    destination = tmp_path/"report.json"
    benchmark.write_new_json(destination, {"first":True})
    with pytest.raises(FileExistsError):
        benchmark.write_new_json(destination, {"first":False})
    assert json.loads(destination.read_text()) == {"first":True}


@pytest.mark.parametrize("section,field,value", [
    (None, "automatic_promotion", True),
    (None, "automatic_promotion", None),
    (None, "results", {}),
    ("paper", "initial_equity", 9999),
    ("paper", "cost_multiplier", 3),
    ("paper", "cost_multiplier", True),
])
def test_unsupported_or_authorizing_method_rejected_before_reading_account(tmp_path, section, field, value):
    method = dict(id="v13_benchmark_comparison_v1", orders_authorized=False,
        paper_orders_authorized=False, automatic_promotion=False, results=None,
        paper=dict(initial_equity=10000, cost_multiplier=1))
    target = method if section is None else method[section]
    target[field] = value
    path = tmp_path / "method.json"
    benchmark.write_new_json(path, method)
    with pytest.raises(ValueError, match="unexpected benchmark method"):
        benchmark.run_comparison(tmp_path / "unread-account.sqlite", path)


def test_replay_verifies_adverse_tick_rounding(tmp_path):
    result = benchmark.replay(build_account(tmp_path/'rounded.sqlite', price_tick=.1))
    assert result['accounts']['actual_v13_v2']['fill_count'] == 1
    assert result['accounts']['buy_hold_all_19_equal_weight_initial_v13_target_gross']['fill_count'] == 19


def test_missing_counterfactual_metadata_is_not_reported_as_cash_control(tmp_path, monkeypatch):
    source = build_account(tmp_path/'source.sqlite')
    original = benchmark.market.market_quotes
    def missing_constraints(*args):
        quotes = original(*args)
        for q in quotes.values():
            q.pop('quantity_step')
        return quotes
    monkeypatch.setattr(benchmark.market, 'market_quotes', missing_constraints)
    with pytest.raises(ValueError, match='counterfactual exposure preflight rejected'):
        benchmark.replay(source)


@pytest.fixture(autouse=True)
def isolate_global_gate_for_pre_p004_regression(monkeypatch):
    """Keep this earlier-stage unit suite isolated; real global gates have their own suite."""
    import contextlib
    from octobot.ai_strategy_lab import paper_runtime_authorization
    monkeypatch.setattr(paper_runtime_authorization, 'entry_scope', lambda *a, **k: contextlib.nullcontext({"test_only": True}))
