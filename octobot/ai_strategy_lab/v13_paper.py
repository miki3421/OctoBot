"""Standalone paper mirror for the frozen Trend V13 sleeve."""
import argparse, datetime, fcntl, json, math, pathlib, sqlite3, time
from octobot.ai_strategy_lab import diversified_manual_paper_v1 as market_data

MODE = "trend_v13_paper_v1"
INITIAL_EQUITY = 10000.0
COST_RATE = 0.0015

def now(): return datetime.datetime.now(datetime.timezone.utc).isoformat()
def read_records(path):
    out=[]
    for line in path.open(encoding="utf-8"):
        if line.strip(): out.append(json.loads(line))
    return out
def targets(payload):
    values = payload.get("research_targets", {}).get("trend_effective_portfolio_weights", {})
    if not isinstance(values, dict): raise ValueError("trend V13 targets missing")
    return {market_data._normalize_symbol(str(k)): float(v) for k,v in values.items() if math.isfinite(float(v)) and abs(float(v)) > 1e-12}
def init_db(path):
    path.parent.mkdir(parents=True, exist_ok=True)
    db=sqlite3.connect(path); db.executescript("""
      CREATE TABLE IF NOT EXISTS state (id INTEGER PRIMARY KEY CHECK(id=1), payload TEXT NOT NULL);
      CREATE TABLE IF NOT EXISTS orders (id INTEGER PRIMARY KEY AUTOINCREMENT, bar TEXT, symbol TEXT, action TEXT, weight REAL, notional REAL, fee REAL, status TEXT);
      CREATE TABLE IF NOT EXISTS equity_history (bar TEXT PRIMARY KEY, equity REAL NOT NULL, pnl REAL NOT NULL);
    """); db.commit(); return db
def run_once(journal, database, health):
    records=read_records(journal)
    if not records: raise ValueError("V13 journal is empty")
    db=init_db(database); row=db.execute("SELECT payload FROM state WHERE id=1").fetchone()
    state=json.loads(row[0]) if row else {"equity":INITIAL_EQUITY,"positions":{},"last_bar":None,"orders":0,"position_pnl":{},"entry_prices":{}}
    record=records[-1]; payload=record["decision_payload"]; bar=payload["bar_date"]
    migration = state["last_bar"] == bar and "position_pnl" not in state
    if state["last_bar"] == bar and not migration:
        db.execute("INSERT OR IGNORE INTO equity_history(bar,equity,pnl) VALUES(?,?,?)", (bar, state["equity"], state["equity"] - INITIAL_EQUITY))
        db.commit()
        db.close(); return json.loads(health.read_text()) if health.exists() else {}
    new=targets(payload); old={market_data._normalize_symbol(k): v for k, v in state["positions"].items()}; deltas={k:new.get(k,0)-old.get(k,0) for k in set(old)|set(new)}
    position_pnl = dict(state.get("position_pnl", {})); entry_prices = dict(state.get("entry_prices", {})); current_prices = {}
    snapshot = market_data._load_daily_snapshot(journal.parent, bar, {})
    for symbol in new:
        current_prices[symbol] = snapshot[symbol]["close"]
        if symbol not in old or symbol not in entry_prices:
            entry_prices[symbol] = current_prices[symbol]
            position_pnl[symbol] = 0.0
    if state["last_bar"]:
        previous = market_data._load_daily_snapshot(journal.parent, state["last_bar"], {})
        for symbol, weight in old.items():
            price_return = snapshot[symbol]["close"] / previous[symbol]["close"] - 1.0
            funding_return = -weight * snapshot[symbol]["funding_rate_sum"]
            position_pnl[symbol] = position_pnl.get(symbol, 0.0) + state["equity"] * (weight * price_return + funding_return)
    position_pnl = {k: position_pnl.get(k, 0.0) for k in new}
    entry_prices = {k: entry_prices[k] for k in new}
    daily_return = float(payload.get("base", {}).get("trend_daily_return", 0.0)) if state["last_bar"] and not migration else 0.0
    if not math.isfinite(daily_return) or daily_return <= -1:
        raise ValueError("invalid V13 daily return")
    marked_equity=state["equity"]*(1.0+daily_return)
    turnover=sum(abs(v) for v in deltas.values()); fees=marked_equity*turnover*COST_RATE
    equity=marked_equity-fees
    for symbol, weight in deltas.items():
        if abs(weight)>1e-12: db.execute("INSERT INTO orders(bar,symbol,action,weight,notional,fee,status) VALUES(?,?,?,?,?,?,?)",(bar,symbol,"BUY" if weight>0 else "SELL",weight,marked_equity*weight,abs(marked_equity*weight)*COST_RATE,"filled"))
    state={"equity":equity,"positions":new,"last_bar":bar,"orders":state["orders"]+sum(abs(v)>1e-12 for v in deltas.values()),"position_pnl":position_pnl,"entry_prices":entry_prices}
    db.execute("INSERT OR REPLACE INTO state(id,payload) VALUES(1,?)",(json.dumps(state,sort_keys=True),)); db.commit(); db.close()
    db=init_db(database); db.execute("INSERT OR REPLACE INTO equity_history(bar,equity,pnl) VALUES(?,?,?)",(bar,equity,equity-INITIAL_EQUITY)); db.commit(); db.close()
    result={"mode":MODE,"status":"healthy","paper_only":True,"orders_authorized":False,"paper_orders_authorized":True,"credentials_used":False,"network_required":False,"equity":equity,"pnl":equity-INITIAL_EQUITY,"order_count":state["orders"],"position_count":len(new),"last_bar":bar,"positions":[{"symbol":k,"weight_pct":v*100,"notional":equity*v,"entry_price":entry_prices[k],"current_price":current_prices[k],"unrealized_pnl":position_pnl[k]} for k,v in sorted(new.items())],"last_success_at":now()}
    health.parent.mkdir(parents=True,exist_ok=True); health.write_text(json.dumps(result,indent=2,sort_keys=True)+"\n"); return result
def main():
    p=argparse.ArgumentParser(); p.add_argument("--journal",type=pathlib.Path,required=True); p.add_argument("--database",type=pathlib.Path,required=True); p.add_argument("--health",type=pathlib.Path,required=True); p.add_argument("--lock",type=pathlib.Path,required=True); p.add_argument("--poll",type=float,default=60); p.add_argument("--run-once",action="store_true"); a=p.parse_args()
    with a.lock.open("a+") as f:
        fcntl.flock(f,fcntl.LOCK_EX|fcntl.LOCK_NB)
        while True:
            print(json.dumps(run_once(a.journal,a.database,a.health),sort_keys=True),flush=True)
            if a.run_once:return 0
            time.sleep(a.poll)
if __name__ == "__main__": raise SystemExit(main())
