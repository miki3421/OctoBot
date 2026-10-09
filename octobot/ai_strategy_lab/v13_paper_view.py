"""Read-only, version-aware dashboard projection of the V13 paper ledger."""

import datetime
import json
import math
import pathlib
import sqlite3


V2_MODE = "trend_v13_paper_v2"
LEGACY_MODE = "trend_v13_paper_v1"


def paper_focus(paper, source, now=None):
    """Summarize the current V13 account without trusting stale health files."""
    now = now or datetime.datetime.now(datetime.timezone.utc)

    def recent(value, maximum_age):
        try:
            observed = datetime.datetime.fromisoformat(str(value))
            if observed.tzinfo is None:
                return False
            age = (now - observed).total_seconds()
            return 0 <= age < maximum_age
        except (TypeError, ValueError):
            return False

    if paper.get("execution_scope") == "RESEARCH_SIMULATION_ONLY":
        source = {"status": paper.get("source_status"), "last_success_at": paper.get("source_last_success_at")}
    available = paper.get("available") is True and paper.get("legacy") is False
    source_ready = (source.get("status") == "healthy" and
                    recent(source.get("last_success_at"), 172800))
    account_fresh = recent(paper.get("last_check_at"), 180)
    accounting_fresh = recent(paper.get("last_success_at"), 180)
    market_fresh = recent(paper.get("last_market_at"), 1800 if paper.get("execution_scope") == "RESEARCH_SIMULATION_ONLY" else 36 * 3600)
    active = (available and source_ready and account_fresh and
              accounting_fresh and market_fresh and
              paper.get("status") == "healthy" and paper.get("phase") == "active")
    if active and paper.get("execution_scope") == "RESEARCH_SIMULATION_ONLY":
        if paper.get("entry_gate") == "one_risk_rebalance_per_UTC_day":
            next_action = "Ribilanciamento giornaliero completato; il conto continua ad aggiornarsi."
        elif paper.get("entry_gate") == "cooldown_22_hours":
            next_action = "Conto in osservazione; nuovo rischio dopo almeno 22 ore dall’ultimo ribilanciamento."
        else:
            next_action = "Nuovi ingressi sospesi: " + {"daily_loss_2_percent": "limite di perdita giornaliera del 2%", "drawdown_10_percent": "limite di drawdown del 10%"}.get(paper.get("entry_gate"), "verifica dei dati o dell’autorizzazione richiesta") if paper.get("entry_gate") else "Un ribilanciamento al giorno; monitorare posizioni e fill."
        return {"title": "PAPER DI RICERCA ATTIVO", "color": "success",
                "description": "V13 originale: prezzi pubblici, fill simulati e conto aggiornato.",
                "next_action": next_action}
    if active:
        return {
            "title": "PAPER ATTIVO", "color": "success",
            "description": "Conto V13 V2 aggiornato; segnali e quotazioni disponibili.",
            "next_action": "Monitorare segnali, fill simulati e contabilità del conto.",
        }
    if not available:
        return {
            "title": "CONTO NON DISPONIBILE", "color": "danger",
            "description": "Il conto V13 V2 non è verificabile dalla UI.",
            "next_action": "Verificare health e ledger senza creare un nuovo conto.",
        }
    if not account_fresh:
        return {
            "title": "DATI SCADUTI", "color": "danger",
            "description": "Il conto esiste, ma il suo aggiornamento non è recente.",
            "next_action": "Verificare il processo paper e la sorgente; nessun nuovo fill è confermato.",
        }
    if not source_ready:
        missing_model = "selected model hash mismatch" in str(source.get("error", ""))
        return {
            "title": "PAPER IN PAUSA", "color": "warning",
            "description": "Il conto V13 V2 esiste, ma la sorgente dei segnali non è verificata.",
            "next_action": (
                "Recuperare l'artefatto originale verificato o scegliere una nuova "
                "lineage; conservare il conto V2."
                if missing_model else
                "Verificare la sorgente V13 prima di consentire nuovi fill."
            ),
        }
    if not accounting_fresh or not market_fresh:
        return {
            "title": "DATI SCADUTI", "color": "danger",
            "description": "Il conto esiste, ma quotazioni o contabilità non sono aggiornate.",
            "next_action": "Verificare collector e aggiornamento del ledger prima di considerare attivo il paper.",
        }
    return {
        "title": "PAPER IN PAUSA", "color": "warning",
        "description": "Il conto V13 V2 è bloccato o attende una quotazione valida.",
        "next_action": "Esaminare il motivo del blocco e l'ultimo segnale prima di riprendere.",
    }


def _number(value, name):
    if isinstance(value, bool):
        raise ValueError(f"invalid V13 {name}")
    result = float(value)
    if not math.isfinite(result):
        raise ValueError(f"non-finite V13 {name}")
    return result


def _timestamp(value):
    parsed = datetime.datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=datetime.timezone.utc)
    return parsed.timestamp()


def summarize_health(health):
    if not health:
        return {"available": False}
    required = {"paper_only": True, "orders_authorized": False,
                "paper_orders_authorized": True, "credentials_used": False,
                "network_required": False}
    if any(health.get(key) is not value for key, value in required.items()):
        raise ValueError("V13 paper safety invariant differs")
    if health.get("mode") not in {V2_MODE, LEGACY_MODE}:
        raise ValueError("V13 paper mode differs")
    if health.get("status") not in {"healthy", "blocked"}:
        raise ValueError("V13 paper status differs")
    legacy = health["mode"] == LEGACY_MODE
    result = {**health, "available": True, "legacy": legacy,
              "initial_equity": _number(health.get("initial_equity", 10000), "initial equity"),
              "equity": _number(health["equity"], "equity"),
              "pnl": _number(health["pnl"], "pnl"),
              "phase": health.get("phase", "legacy"),
              "reason": str(health.get("reason") or ""),
              "order_count": int(health.get("order_count", 0)),
              "position_count": int(health.get("position_count", 0)),
              "positions": health.get("positions", []),
              "label": "V13 · LEGACY NON RICONCILIATO" if legacy else "V13 V2 · Paper trading"}
    if result["initial_equity"] <= 0:
        raise ValueError("V13 initial equity must be positive")
    if not isinstance(result["positions"], list):
        raise ValueError("V13 positions must be a list")
    if not legacy:
        if health.get("automatic_promotion") is not False or health.get("legacy_account_excluded") is not True:
            raise ValueError("V13 account isolation invariant differs")
        _timestamp(health["activation_at"])
        for key in ("realized_pnl", "unrealized_pnl", "fees", "funding"):
            result[key] = _number(health[key], key)
        expected = result["realized_pnl"] + result["unrealized_pnl"] + result["funding"] - result["fees"]
        if (abs(result["pnl"] - expected) > 1e-6
                or abs(result["equity"] - result["initial_equity"] - result["pnl"]) > 1e-6):
            raise ValueError("V13 paper P/L does not reconcile")
        for position in result["positions"]:
            for key in ("quantity", "entry_price", "current_price", "unrealized_pnl", "notional", "weight_pct"):
                if (key == "weight_pct" and position[key] is None
                        and health.get("execution_scope") == "RESEARCH_SIMULATION_ONLY"
                        and result["equity"] <= 0):
                    continue
                _number(position[key], f"position {key}")
            if position["entry_price"] <= 0 or position["current_price"] <= 0:
                raise ValueError("V13 position prices must be positive")
    if health.get("execution_scope") == "RESEARCH_SIMULATION_ONLY":
        if health.get("exchange_faithful_readiness") != "BLOCKED" or health.get("min_quantity") != "UNKNOWN" or health.get("min_notional") != "UNKNOWN" or _number(health.get("simulated_min_notional_usdt"), "simulated minimum") <= 0:
            raise ValueError("V13 research simulation boundary differs")
        result["label"] = "V13 V2 · Paper di ricerca"
    return result


def _read_tables(database, legacy):
    if not database.is_file():
        raise FileNotFoundError(f"V13 ledger missing: {database.name}")

    def read(uri):
        with sqlite3.connect(uri, uri=True, timeout=2) as connection:
            connection.row_factory = sqlite3.Row
            connection.execute("BEGIN")
            history = [dict(row) for row in connection.execute(
                "SELECT bar, equity, pnl FROM equity_history ORDER BY bar")]
            columns = "bar, symbol, action, notional, fee" + ("" if legacy else ", quantity, price")
            fills = [dict(row) for row in connection.execute(
                f"SELECT {columns} FROM orders WHERE status='filled' ORDER BY bar, id")]
            marks = [] if legacy else [dict(row) for row in connection.execute(
                "SELECT bar, symbol, price FROM marks ORDER BY bar, symbol")]
            return history, fills, marks

    uri = database.resolve().as_uri() + "?mode=ro"
    try:
        return read(uri)
    except sqlite3.OperationalError:
        wal = pathlib.Path(f"{database}-wal")
        if wal.exists() and wal.stat().st_size:
            raise
        # A read-only mount cannot create an absent WAL shared-memory file.
        # Immutable is safe only if there are no uncheckpointed WAL bytes.
        return read(uri + "&immutable=1")


def load_paper_view(root="/v13-paper"):
    root = pathlib.Path(root)
    research = root / "research" / "execution"
    if (research / "health-research.json").exists():
        health_path, database = research / "health-research.json", research / "execution.sqlite"
        v2 = True
    else:
        health_path = database = None
    v2 = v2 if health_path else ((root / "health-v2.json").exists() or (root / "v13-v2.sqlite").exists())
    health_path = health_path or root / ("health-v2.json" if v2 else "health.json")
    database = database or root / ("v13-v2.sqlite" if v2 else "v13.sqlite")
    result = summarize_health(json.loads(health_path.read_text(encoding="utf-8")))
    if result["legacy"] == v2:
        raise ValueError("V13 health and ledger version differ")
    history, fills, marks = _read_tables(database, result["legacy"])
    result["history"] = []
    previous = None
    for point in history:
        timestamp = _timestamp(point["bar"])
        if previous is not None and timestamp <= previous:
            raise ValueError("V13 equity timestamps are not ordered")
        if not result["legacy"] and timestamp < _timestamp(result["activation_at"]):
            raise ValueError("V13 equity predates account activation")
        result["history"].append({"time": point["bar"], "value": _number(point["equity"], "history equity")})
        previous = timestamp
    result["fills"] = []
    for fill in fills:
        if fill["action"] not in {"BUY", "SELL"}:
            raise ValueError("V13 fill side differs")
        timestamp = _timestamp(fill["bar"])
        if not result["legacy"] and timestamp < _timestamp(result["activation_at"]):
            raise ValueError("V13 fill predates account activation")
        normalized = {**fill, "time": fill["bar"]}
        for key in ("notional", "fee") + (() if result["legacy"] else ("quantity", "price")):
            normalized[key] = _number(fill[key], f"fill {key}")
        if not result["legacy"] and normalized["price"] <= 0:
            raise ValueError("V13 fill price must be positive")
        result["fills"].append(normalized)
    result["symbol_charts"] = []
    if not result["legacy"]:
        positions = {position["symbol"]: position for position in result["positions"]}
        symbols = set(positions) | {fill["symbol"] for fill in result["fills"]}
        for symbol in sorted(symbols):
            position = positions.get(symbol, {})
            points = [{"time": mark["bar"], "value": _number(mark["price"], "mark price")}
                      for mark in marks if mark["symbol"] == symbol]
            result["symbol_charts"].append({
                "symbol": symbol, "points": points,
                "pnl": position.get("unrealized_pnl"),
                "entry_price": position.get("entry_price"),
                "fills": [fill for fill in result["fills"] if fill["symbol"] == symbol],
            })
    return result
