"""Quantity-accounted V13 paper execution on the existing KuCoin book archive.

No exchange client, credentials, or network. Signals are the frozen standalone
V13 component, not the diversified half-sleeve. A newly noticed target waits
for a later book: no fills at yesterday's close and no inherited research P/L.
Funding uses settled rates and the preceding observed mark (an explicit estimate).
"""
from __future__ import annotations

import argparse
from contextlib import ExitStack
import copy
import datetime as dt
import fcntl
import json
import hashlib
import math
import pathlib
import sqlite3
import time

from octobot.ai_strategy_lab import diversified_manual_paper_v1 as upstream
from octobot.ai_strategy_lab import v13_market, v13_exposure, v13_market_sanity
from octobot.ai_strategy_lab import paper_authorization, paper_runtime_authorization

MODE = "trend_v13_paper_v2"
INITIAL_EQUITY = 10_000.0
MAX_GROSS = 0.90
MAX_ASSET = 0.315
UTC = dt.timezone.utc
FUNDING_NOTE = (
    "Funding stimato: rate liquidate KuCoin × quantità detenuta × ultimo mark "
    "precedente osservato; non è il prezzo esatto del settlement."
)


def timestamp(value):
    parsed = dt.datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        raise ValueError("timezone missing")
    return parsed.astimezone(UTC)


def targets(payload):
    raw = payload.get("research_targets", {}).get("trend_component_weights")
    if not isinstance(raw, dict):
        raise ValueError("standalone V13 component targets missing")
    result = {}
    for symbol, value in raw.items():
        symbol = upstream._normalize_symbol(symbol)
        weight = float(value)
        if not math.isfinite(weight) or abs(weight) > MAX_ASSET + 1e-9:
            raise ValueError("invalid V13 asset risk budget")
        if symbol in result or not symbol.endswith("USDT"):
            raise ValueError("invalid or duplicated V13 symbol")
        if abs(weight) > 1e-12:
            result[symbol] = weight
    if sum(map(abs, result.values())) > MAX_GROSS + 1e-9:
        raise ValueError("V13 gross risk budget exceeded")
    return result


def new_position():
    return dict(quantity=0.0, entry_price=0.0, current_price=0.0,
                realized_pnl=0.0, fees=0.0, funding=0.0, last_mark_at=None)


def apply_fill(position, quantity, price, fee):
    """Average-cost linear USDT accounting, including reductions and reversals."""
    if not all(math.isfinite(v) for v in (quantity, price, fee)) or price <= 0 or fee < 0:
        raise ValueError("invalid fill")
    old = position["quantity"]
    new = old + quantity
    if old * quantity < 0:
        closed = min(abs(old), abs(quantity))
        position["realized_pnl"] += closed * (price - position["entry_price"]) * (1 if old > 0 else -1)
    if abs(new) < 1e-10:
        new = 0.0
        position["entry_price"] = 0.0
    elif old == 0 or old * new < 0:
        position["entry_price"] = price
    elif old * quantity > 0:
        position["entry_price"] = (abs(old) * position["entry_price"] + abs(quantity) * price) / abs(new)
    position["quantity"] = new
    position["fees"] += fee


def totals(state, *, require_positive=True):
    assets = list(state["positions"].values())
    realized = math.fsum(p["realized_pnl"] for p in assets)
    unrealized = math.fsum(p["quantity"] * (p["current_price"] - p["entry_price"]) for p in assets)
    fees = math.fsum(p["fees"] for p in assets)
    funding = math.fsum(p["funding"] for p in assets)
    equity = math.fsum((state["initial_equity"], realized, unrealized, funding, -fees))
    if not all(math.isfinite(x) for x in (equity, realized, unrealized, fees, funding)) or (require_positive and equity <= 0):
        raise ValueError("non-positive or invalid paper equity")
    return dict(equity=equity, pnl=equity-state["initial_equity"], realized_pnl=realized,
                unrealized_pnl=unrealized, fees=fees, funding=funding)


def init_db(path):
    path.parent.mkdir(parents=True, exist_ok=True)
    db = sqlite3.connect(path, timeout=15)
    # Refuse accidental use of a legacy account: never reinterpret old rows.
    tables = {r[0] for r in db.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    if tables and "account_version" not in tables:
        db.close()
        raise ValueError("refusing legacy/non-V2 paper database")
    if "account_version" in tables and list(db.execute("SELECT mode FROM account_version")) != [(MODE,)]:
        db.close()
        raise ValueError("paper account version differs")
    db.execute("PRAGMA journal_mode=WAL")
    db.execute("PRAGMA synchronous=FULL")
    db.executescript("""
        CREATE TABLE IF NOT EXISTS account_version(mode TEXT PRIMARY KEY);
        CREATE TABLE IF NOT EXISTS state(id INTEGER PRIMARY KEY CHECK(id=1), payload TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS orders(
            id INTEGER PRIMARY KEY, bar TEXT NOT NULL, symbol TEXT NOT NULL,
            action TEXT NOT NULL, weight REAL, notional REAL, fee REAL,
            status TEXT NOT NULL, quantity REAL, price REAL, recorded_at TEXT,
            decision_hash TEXT, market_hash TEXT, realized_pnl REAL);
        CREATE TABLE IF NOT EXISTS equity_history(bar TEXT PRIMARY KEY, equity REAL, pnl REAL);
        CREATE TABLE IF NOT EXISTS marks(bar TEXT, symbol TEXT, price REAL, PRIMARY KEY(bar,symbol));
        CREATE TABLE IF NOT EXISTS funding_events(symbol TEXT, timestamp_ms INTEGER, rate REAL,
            quantity REAL, reference_mark REAL, amount REAL, PRIMARY KEY(symbol,timestamp_ms));
        CREATE TABLE IF NOT EXISTS market_events(record_hash TEXT PRIMARY KEY, observed_at TEXT,
            processed_at TEXT, payload TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS risk_events(record_hash TEXT PRIMARY KEY, payload TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS intents(decision_hash TEXT PRIMARY KEY, noticed_at TEXT,
            bar TEXT, targets TEXT, status TEXT);
    """)
    modes = list(db.execute("SELECT mode FROM account_version"))
    if modes and modes != [(MODE,)]:
        db.close()
        raise ValueError("paper account version differs")
    db.execute("INSERT OR IGNORE INTO account_version VALUES (?)", (MODE,))
    db.commit()
    return db


def process_market(state, record, quotes, checked_at, *, authorization_stack=None, authorization_paths=(), authorization_scope=None):
    """Pure transactional tick: input remains unchanged if any leg is invalid."""
    if authorization_stack is None:
        with ExitStack() as stack:
            return process_market(state, record, quotes, checked_at,
                authorization_stack=stack, authorization_paths=authorization_paths,
                authorization_scope=authorization_scope)
    # Validate all symbols first: a bad later leg must not reach any fill.
    for symbol, quote in quotes.items():
        v13_market_sanity.structure_and_time(symbol, quote, record, checked_at)
    result = copy.deepcopy(state)
    fills, funding_rows, marks = [], [], []
    for symbol, quote in quotes.items():
        position = result["positions"].setdefault(symbol, new_position())
        quote_at = timestamp(quote["timestamp"])
        previous_at = position["last_mark_at"]
        if previous_at and quote_at <= timestamp(previous_at):
            raise ValueError("non-increasing market timestamp")
        if previous_at and position["quantity"]:
            if (quote_at-timestamp(previous_at)).total_seconds() > 20*3600:
                raise ValueError("funding coverage gap >20h; reconciliation required")
            start_ms = int(timestamp(previous_at).timestamp()*1000)
            end_ms = int(quote_at.timestamp()*1000)
            for event in quote["funding"]:
                if start_ms < event["timestamp_ms"] <= end_ms:
                    amount = -position["quantity"] * position["current_price"] * event["rate"]
                    position["funding"] += amount
                    funding_rows.append((symbol, event["timestamp_ms"], event["rate"],
                                         position["quantity"], position["current_price"], amount))
        position["current_price"] = v13_exposure.number(quote.get("mark_price"), "mark", positive=True)
        position["last_mark_at"] = quote["timestamp"]
        marks.append((quote["timestamp"], symbol, quote["mark_price"]))

    equity = totals(result, require_positive=False)["equity"]
    quantities, prices = v13_exposure.quantities_and_marks(result)
    exposure = v13_exposure.snapshot(quantities, prices, equity, MAX_GROSS, MAX_ASSET)
    result["risk"] = dict(reason="passive_exposure_limit" if exposure["breaches"] else None,
                          current=exposure, before_fill=exposure, action="mark_only", post_fills=[], checked_at=checked_at.isoformat())
    result["risk"]["market_policy"] = v13_market_sanity.asdict(v13_market_sanity.POLICY)
    result["risk"]["market_checks"] = []
    pending = result.get("pending")
    if pending and all(timestamp(q["timestamp"]) > timestamp(pending["noticed_at"]) for q in quotes.values()):
        def market_guard(symbol, quote, delta, protective):
            check = v13_market_sanity.preflight(symbol, quote, delta, protective)
            if check is not None:
                result["risk"]["market_checks"].append(check)

        try:
            if paper_runtime_authorization.increases(result, quotes, pending["targets"], equity):
                scope = authorization_scope or paper_runtime_authorization.entry_scope
                claim = authorization_stack.enter_context(scope(
                    "v13-paper-v2", pending["decision_hash"], context_paths=authorization_paths,
                    **({'marked_state': result} if authorization_scope is not None else {})))
                result["risk"]["global_authorization"] = claim
            legs, _, new_risk = v13_exposure.plan(result, quotes, pending["targets"], equity,
                                                 v13_market.fill_price, MAX_GROSS, MAX_ASSET, market_guard=market_guard)
        except paper_authorization.Denied as exc:
            result["risk"].update(action="authorization_veto", reason=exc.code,
                authorization_audit_persisted=exc.persisted, rejected_intent=pending["decision_hash"])
        except v13_exposure.Rejected as exc:
            if not isinstance(exc, v13_market_sanity.Veto) and any(
                    word in str(exc) for word in ("quantity step", "quantity precision", "contract multiplier", "price tick", "minimum quantity", "minimum notional", "fee rate")):
                code = "missing_market_metadata" if "missing" in str(exc) else "invalid_market_metadata"
                exc = v13_market_sanity.Veto(code, str(exc))
            # Persist valid marks/funding and the veto; no simulated execution.
            result["risk"]["action"] = "rejected_intent"
            result["risk"]["reason"] = str(exc)
            result["risk"]["rejected_intent"] = pending["decision_hash"]
            result["risk"]["rejected_projection"] = exc.exposure
            if isinstance(exc, v13_market_sanity.Veto):
                result["risk"]["market_veto"] = exc.evidence()
        else:
            result["risk"]["action"] = "new_risk" if new_risk else "risk_reduction"
            for leg in legs:
                symbol, delta, price, fee = (leg[k] for k in ("symbol", "quantity", "price", "fee"))
                quote, position = quotes[symbol], result["positions"][symbol]
                before_realized = position["realized_pnl"]
                apply_fill(position, delta, price, fee)
                if abs(position["quantity"] - leg["resulting_quantity"]) > 8 * math.ulp(max(1., abs(leg["resulting_quantity"]))):
                    raise ValueError("post-fill quantity mismatch")
                quantities, prices = v13_exposure.quantities_and_marks(result)
                actual = v13_exposure.snapshot(quantities, prices,
                    totals(result, require_positive=False)["equity"], MAX_GROSS, MAX_ASSET)
                expected = leg["exposure"]
                # A discrepancy is an accounting fault: discard the entire tick.
                for key in ("equity", "gross", "net"):
                    scale = max(abs(actual[key]), abs(expected[key]), 1.)
                    if abs(actual[key] - expected[key]) > 32 * math.ulp(scale):
                        raise ValueError("post-fill projection mismatch")
                if new_risk and actual["breaches"]:
                    raise ValueError("post-fill exposure limit")
                result["risk"]["post_fills"].append(actual)
                result["risk"]["current"] = actual
                result["risk"]["reason"] = "risk_reduction_above_limit" if actual["breaches"] else None
                fills.append(dict(bar=quote["timestamp"], symbol=symbol,
                    action="BUY" if delta > 0 else "SELL", weight=delta*price/equity if equity > 0 else None,
                    notional=delta*price, fee=fee, status="filled", quantity=delta,
                    price=price, recorded_at=checked_at.isoformat(),
                    decision_hash=pending["decision_hash"], market_hash=record["record_hash"],
                    realized_pnl=position["realized_pnl"]-before_realized))
            result["executed_targets"] = pending["targets"]
            result["pending"] = None
            result["order_count"] += len(fills)
    result["last_market_hash"] = record["record_hash"]
    result["last_market_at"] = record["observed_at_end"]
    totals(result, require_positive=False)  # Validate the identity before committing any leg.
    return result, fills, funding_rows, marks


def health_payload(state, checked_at, *, error=None):
    metrics = totals(state, require_positive=False)
    error = error or state.get("risk", {}).get("reason")
    positions = []
    for symbol, p in sorted(state["positions"].items()):
        if abs(p["quantity"]) < 1e-10:
            continue
        positions.append(dict(p, symbol=symbol, fee=p["fees"],
            notional=p["quantity"]*p["current_price"],
            weight_pct=p["quantity"]*p["current_price"]/metrics["equity"]*100 if metrics["equity"] > 0 else None,
            unrealized_pnl=p["quantity"]*(p["current_price"]-p["entry_price"])))
    return dict(metrics, risk=state.get("risk"), mode=MODE, status="blocked" if error else "healthy",
        phase="blocked" if error else ("awaiting_market" if state.get("pending") else "active"),
        reason=error or ("In attesa di un book successivo al nuovo segnale." if state.get("pending") else None),
        initial_equity=state["initial_equity"], activation_at=state["activation_at"],
        positions=positions, position_count=len(positions), order_count=state["order_count"],
        last_bar=state["last_bar"], last_market_at=state.get("last_market_at"),
        last_success_at=checked_at.isoformat() if not error else state.get("last_success_at"),
        last_check_at=checked_at.isoformat(), database_integrity="ok",
        funding_note=FUNDING_NOTE, funding_model="settled_rate_previous_observed_mark",
        execution_model="KuCoin observed depth VWAP + adverse 2bps; declared entry precision; conservative tick rounding when available",
        legacy_account_excluded=True, paper_only=True, orders_authorized=False,
        paper_orders_authorized=False, network_required=False, credentials_used=False,
        automatic_promotion=False)


def run_once(journal, protocol, implementation_lock, market_journal, database, health, *, checked_at=None):
    checked_at = checked_at or dt.datetime.now(UTC)
    records, _, _ = upstream._load_upstream(journal, protocol, implementation_lock)
    latest = records[-1]
    payload = latest["decision_payload"]
    available = max(timestamp(payload["decision_available_not_before_utc"]), timestamp(latest["recorded_at"]))
    age = (checked_at-available).total_seconds()
    if not 0 <= age <= 36*3600:
        raise ValueError("V13 signal unavailable or stale >36h")
    desired = targets(payload)
    db = init_db(database)
    try:
        if db.execute("PRAGMA quick_check").fetchone()[0] != "ok":
            raise ValueError("V13 database integrity failure")
        row = db.execute("SELECT payload FROM state WHERE id=1").fetchone()
        state = json.loads(row[0]) if row else dict(mode=MODE, initial_equity=INITIAL_EQUITY,
            activation_at=checked_at.isoformat(), positions={}, order_count=0,
            last_bar=payload["bar_date"], last_market_hash=None, executed_targets=None, pending=None)
        if state["mode"] != MODE:
            raise ValueError("wrong account mode")
        if state.get("last_source_hash") and state["last_source_hash"] not in {r["journal_record_hash"] for r in records}:
            raise ValueError("V13 source rollback or rewritten history")
        # Persist intents before attempting any fill. First-ever run starts flat NOW.
        pending_weights = state["pending"]["targets"] if state.get("pending") else state["executed_targets"]
        if desired != pending_weights:
            state["pending"] = dict(targets=desired, noticed_at=checked_at.isoformat(), decision_hash=latest["journal_record_hash"])
            db.execute("UPDATE intents SET status='superseded' WHERE status='pending'")
            db.execute("INSERT INTO intents VALUES (?,?,?,?,?)", (latest["journal_record_hash"],
                checked_at.isoformat(), payload["bar_date"], json.dumps(desired, sort_keys=True), "pending"))
        state["last_bar"] = payload["bar_date"]
        state["last_source_hash"] = latest["journal_record_hash"]
        db.execute("INSERT OR REPLACE INTO state VALUES (1,?)", (json.dumps(state, sort_keys=True),))
        if not row:
            db.execute("INSERT INTO equity_history VALUES (?,?,?)", (checked_at.isoformat(), INITIAL_EQUITY, 0))
        db.commit()
        record = candidate = None
        try:
            try:
                record = v13_market.load_latest_market(market_journal, checked_at)
            except (ValueError, KeyError, TypeError, OSError) as exc:
                raise v13_market_sanity.adapter_veto(exc) from exc
            symbols = set(desired) | {s for s, p in state["positions"].items() if p["quantity"]}
            if record["record_hash"] != state["last_market_hash"] and timestamp(record["observed_at_start"]) > timestamp(state["activation_at"]):
                try:
                    quotes = v13_market.market_quotes(record, symbols)
                except (ValueError, KeyError, TypeError) as exc:
                    raise v13_market_sanity.adapter_veto(exc) from exc
                with ExitStack() as authorization_stack:
                    candidate, fills, funding_rows, marks = process_market(state, record, quotes, checked_at,
                        authorization_stack=authorization_stack, authorization_paths=(protocol, implementation_lock))
                    with db:
                        for fill in fills:
                            fields = list(fill)
                            db.execute(f"INSERT INTO orders({','.join(fields)}) VALUES ({','.join('?' for _ in fields)})", tuple(fill.values()))
                        db.executemany("INSERT INTO funding_events VALUES (?,?,?,?,?,?)", funding_rows)
                        db.executemany("INSERT INTO marks VALUES (?,?,?)", marks)
                        # Persist the actual inputs, not just non-replayable API summaries.
                        db.execute("INSERT INTO market_events VALUES (?,?,?,?)", (record["record_hash"],
                            record["observed_at_end"], checked_at.isoformat(), json.dumps(record, sort_keys=True)))
                        if state.get("pending") and not candidate.get("pending"):
                            db.execute("UPDATE intents SET status='executed' WHERE decision_hash=?", (state["pending"]["decision_hash"],))
                        db.execute("INSERT INTO risk_events VALUES (?,?)", (record["record_hash"],
                            json.dumps(candidate["risk"], sort_keys=True, allow_nan=False)))
                        metrics = totals(candidate, require_positive=False)
                        db.execute("INSERT INTO equity_history VALUES (?,?,?)", (record["observed_at_end"], metrics["equity"], metrics["pnl"]))
                        db.execute("UPDATE state SET payload=? WHERE id=1", (json.dumps(candidate, sort_keys=True),))
                    state = candidate
            state["last_success_at"] = checked_at.isoformat()
            db.execute("UPDATE state SET payload=? WHERE id=1", (json.dumps(state, sort_keys=True),))
            db.commit()
            result = health_payload(state, checked_at)
        except v13_market_sanity.Veto as exc:
            candidate = copy.deepcopy(state)
            candidate["risk"] = dict(reason=str(exc), action="market_veto",
                market_veto=exc.evidence(), checked_at=checked_at.isoformat(),
                observed_record_hash=record.get("record_hash") if isinstance(record, dict) else None,
                rejected_intent=state.get("pending", {}).get("decision_hash") if state.get("pending") else None)
            event_json = json.dumps(candidate["risk"], sort_keys=True, allow_nan=False)
            event_id = "market-veto:" + hashlib.sha256(event_json.encode()).hexdigest()
            try:
                with db:
                    db.execute("INSERT OR IGNORE INTO risk_events VALUES (?,?)", (event_id, event_json))
                    db.execute("UPDATE state SET payload=? WHERE id=1", (json.dumps(candidate, sort_keys=True),))
                state = candidate
                result = health_payload(state, checked_at)
                result["risk_event_persisted"] = True
            except sqlite3.Error as storage_error:
                result = health_payload(state, checked_at, error="risk_event_persistence_failed")
                result.update(risk_event_persisted=False, market_veto=exc.evidence(), storage_error=str(storage_error))
        except (ValueError, OSError, KeyError, sqlite3.Error) as exc:
            result = health_payload(state, checked_at, error=str(exc))
            if isinstance(exc, sqlite3.Error):
                result["risk_event_persisted"] = False
                if candidate and candidate.get("risk", {}).get("market_veto"):
                    result["market_veto"] = candidate["risk"]["market_veto"]
        upstream._atomic_json(health, result)
        return result
    finally:
        db.close()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("journal", "protocol", "implementation-lock", "market-journal", "database", "health", "lock"):
        parser.add_argument(f"--{name}", type=pathlib.Path, required=True)
    parser.add_argument("--poll", type=float, default=60)
    parser.add_argument("--run-once", action="store_true")
    args = parser.parse_args()
    if args.poll <= 0:
        raise ValueError("poll must be positive")
    args.lock.parent.mkdir(parents=True, exist_ok=True)
    with args.lock.open("a+") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        while True:
            try:
                result = run_once(args.journal, args.protocol, args.implementation_lock,
                    args.market_journal, args.database, args.health)
            except (ValueError, OSError, KeyError, sqlite3.Error) as exc:
                # Old balances remain visible but explicitly blocked, never healthy.
                result = json.loads(args.health.read_text()) if args.health.exists() else {"mode": MODE, "paper_only": True, "orders_authorized": False}
                result.update(status="blocked", phase="blocked", reason=str(exc), last_check_at=dt.datetime.now(UTC).isoformat())
                upstream._atomic_json(args.health, result)
            print(json.dumps(result, sort_keys=True), flush=True)
            if args.run_once:
                return 0 if result["status"] == "healthy" else 1
            time.sleep(args.poll)


if __name__ == "__main__":
    raise SystemExit(main())
