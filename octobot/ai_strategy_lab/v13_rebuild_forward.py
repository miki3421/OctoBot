"""Orderless readiness observer for the standalone V13 rebuild.

It deliberately emits no target and no order. Until a continuous post-rebuild
daily panel exists, the only valid state is ``awaiting_warmup``.
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import pathlib
import time

from octobot.ai_strategy_lab import v13_market

UTC = dt.timezone.utc


def atomic(path: pathlib.Path, value: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(value, sort_keys=True, indent=2) + "\n")
    temporary.replace(path)


def once(protocol_path: pathlib.Path, market_path: pathlib.Path, health_path: pathlib.Path) -> None:
    checked = dt.datetime.now(UTC)
    protocol = json.loads(protocol_path.read_text())
    base = {
        "mode": "v13_standalone_rebuild_forward_v1",
        "observer_type": "v13_standalone_rebuild_observer_v1",
        "protocol_sha256": protocol.get("protocol_sha256"),
        "research_only": True,
        "public_data_only": True,
        "credentials_used": False,
        "orders_authorized": False,
        "paper_orders_authorized": False,
        "automatic_promotion": False,
        "checked_at": checked.isoformat(),
    }
    try:
        record = v13_market.load_latest_market(market_path, checked)
        base.update({
            "status": "awaiting_warmup",
            "phase": "awaiting_continuous_post_rebuild_panel",
            "reason": "Nuova lineage pronta; servono dati daily continui dopo il 2026-06-30 prima di emettere segnali.",
            "last_market_at": record["observed_at_end"],
            "symbol_count": record["symbol_count"],
            "decision_count": 0,
        })
    except Exception as error:
        base.update({"status": "blocked", "phase": "blocked", "reason": str(error), "decision_count": 0})
    atomic(health_path, base)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--protocol", type=pathlib.Path, required=True)
    parser.add_argument("--market-journal", type=pathlib.Path, required=True)
    parser.add_argument("--health", type=pathlib.Path, required=True)
    parser.add_argument("--poll", type=int, default=900)
    args = parser.parse_args()
    while True:
        once(args.protocol, args.market_journal, args.health)
        time.sleep(max(30, args.poll))


if __name__ == "__main__":
    main()
