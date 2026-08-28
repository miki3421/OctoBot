"""Quarter-hour opening-flow economic feasibility audit for BTC futures."""

from __future__ import annotations

import argparse
import datetime
import hashlib
import json
import math
import pathlib
import typing

import numpy

from octobot.ai_strategy_lab import cointegration_pairs_v1 as common
from octobot.ai_strategy_lab import scalping_strategy_search as scalping_v1
from octobot.ai_strategy_lab import scalping_strategy_search_v2 as scalping_v2


SCHEMA_VERSION = 1
PROTOCOL_VERSION = "btc_quarter_hour_opening_flow_markout_v1"
PREREGISTRATION_DATE = "2026-08-28"
SOURCE_START = scalping_v1.SOURCE_START
DEVELOPMENT_END = scalping_v2.DEVELOPMENT_END
CONFIRMATION_END = scalping_v2.DIAGNOSTIC_CONFIRMATION_END
LOCKED_END = scalping_v2.LOCKED_TEST_END
BOUNDARY_SECONDS = 15 * 60
OBSERVATION_SECONDS = 10
HORIZON_SECONDS = 4 * 60 * 60
PRIMARY_DELAY_SECONDS = 0
STRESS_DELAY_SECONDS = 1
FEE_BPS_PER_FILL = 6.0
SLIPPAGE_BPS_PER_FILL = 1.0
ROUND_TRIP_COST_BPS = 2 * (FEE_BPS_PER_FILL + SLIPPAGE_BPS_PER_FILL)
STRESS_COST_MULTIPLIER = 2.0
DEVELOPMENT_FOLDS = 5


def _epoch(value: str) -> int:
    return int(datetime.datetime.fromisoformat(value).timestamp())


def frozen_protocol() -> dict:
    return {
        "schema_version": SCHEMA_VERSION,
        "protocol_version": PROTOCOL_VERSION,
        "preregistered_on": PREREGISTRATION_DATE,
        "status": "result_free_economic_feasibility_protocol",
        "research_only": True,
        "public_data_only": True,
        "credentials_used": False,
        "orders_authorized": False,
        "paper_orders_authorized": False,
        "automatic_promotion": False,
        "hypothesis": {
            "name": "quarter_hour_opening_imbalance_four_hour_continuation",
            "statement": (
                "signed taker imbalance in the first ten seconds after a UTC "
                "quarter-hour boundary predicts same-direction BTC movement "
                "over four hours large enough to cover a taker round trip"
            ),
            "source_motivation": "Kim and Hansen arXiv:2607.09426v2",
            "direction": "sign of buy-size minus sell-size",
            "one_configuration_only": True,
        },
        "source": {
            "parent_snapshot_sha256": scalping_v1.SNAPSHOT_SHA256,
            "parent_cache_protocol_sha256": scalping_v2.PARENT_PROTOCOL_SHA256,
            "exchange": "kucoin_futures",
            "symbol": "XBTUSDTM",
            "source_start": SOURCE_START,
            "prelock_cache_end_exclusive": CONFIRMATION_END,
            "locked_end": LOCKED_END,
            "locked_rows_required_for_prelock": False,
            "diagnostic_reuse": True,
        },
        "event": {
            "boundary_seconds": BOUNDARY_SECONDS,
            "opening_observation_seconds": OBSERVATION_SECONDS,
            "minimum_trade_events": 1,
            "zero_imbalance_skipped": True,
            "entry": (
                "executable same-direction top-of-book 500ms into the first "
                "second after the ten-second observation"
            ),
            "exit": "executable opposite top-of-book after exactly four hours",
            "primary_extra_delay_seconds": PRIMARY_DELAY_SECONDS,
            "stress_extra_delay_seconds": STRESS_DELAY_SECONDS,
            "overlapping_markouts": True,
            "portfolio_claim": False,
        },
        "economics": {
            "fee_bps_per_fill": FEE_BPS_PER_FILL,
            "slippage_bps_per_fill": SLIPPAGE_BPS_PER_FILL,
            "round_trip_cost_bps": ROUND_TRIP_COST_BPS,
            "stress_cost_multiplier": STRESS_COST_MULTIPLIER,
            "maker_fill_assumptions": False,
            "funding_omitted": (
                "four-hour funding can only make selected events less stable; "
                "the feasibility gate first requires price markout to cover costs"
            ),
        },
        "validation": {
            "development": [SOURCE_START, DEVELOPMENT_END],
            "development_equal_time_folds": DEVELOPMENT_FOLDS,
            "fold_event_exit_must_precede_fold_end": True,
            "confirmation": [DEVELOPMENT_END, CONFIRMATION_END],
            "locked_final_test": [CONFIRMATION_END, LOCKED_END],
            "locked_policy": (
                "the source cache ends before the lock and no locked rows are "
                "loaded unless development and confirmation both pass"
            ),
        },
        "development_gate": {
            "minimum_events": 1500,
            "positive_mean_net_bps": True,
            "minimum_profit_factor": 1.25,
            "minimum_hit_rate": 0.52,
            "minimum_positive_day_ratio": 0.60,
            "minimum_positive_folds": 4,
            "both_directions_non_negative": True,
            "stress_mean_net_bps_positive": True,
            "minimum_stress_profit_factor": 1.05,
        },
        "confirmation_gate": {
            "minimum_events": 500,
            "positive_mean_net_bps": True,
            "minimum_profit_factor": 1.20,
            "minimum_hit_rate": 0.52,
            "minimum_positive_day_ratio": 0.55,
            "both_directions_non_negative": True,
            "stress_mean_net_bps_positive": True,
            "minimum_stress_profit_factor": 1.00,
        },
        "pass_consequence": (
            "a complete prelock pass permits only a new non-overlapping "
            "portfolio protocol; it does not permit shadow, paper or real orders"
        ),
        "multiple_testing_disclosure": (
            "one boundary, one observation window, one direction and one "
            "four-hour horizon are evaluated"
        ),
        "results": None,
    }


def write_or_verify_protocol(path_value) -> dict:
    path = pathlib.Path(path_value).resolve()
    protocol = frozen_protocol()
    payload = {**protocol, "protocol_sha256": common._json_hash(protocol)}
    if path.is_file():
        persisted = json.loads(path.read_text(encoding="utf-8"))
        if persisted != payload:
            raise ValueError("persisted quarter-hour V1 protocol differs")
        return persisted
    common._atomic_json(path, payload)
    return payload


def load_source_cache(path_value) -> dict:
    path = pathlib.Path(path_value).resolve()
    with numpy.load(path, allow_pickle=False) as archive:
        required = {
            "protocol_sha256",
            "source_snapshot_sha256",
            "start_second",
            "end_second",
            "value_buy_trade_size",
            "value_sell_trade_size",
            "value_trade_event_count",
            "value_entry_ask_500",
            "value_entry_bid_500",
        }
        if not required <= set(archive.files):
            raise ValueError("quarter-hour source cache schema is incomplete")
        protocol_sha = str(archive["protocol_sha256"][0])
        snapshot_sha = str(archive["source_snapshot_sha256"][0])
        if protocol_sha != scalping_v2.PARENT_PROTOCOL_SHA256:
            raise ValueError("unexpected parent source-cache protocol")
        if snapshot_sha != scalping_v1.SNAPSHOT_SHA256:
            raise ValueError("unexpected source snapshot")
        start = int(archive["start_second"][0])
        end = int(archive["end_second"][0])
        result = {
            "start_second": start,
            "end_second": end,
            "buy_size": archive["value_buy_trade_size"].astype(
                numpy.float64, copy=True
            ),
            "sell_size": archive["value_sell_trade_size"].astype(
                numpy.float64, copy=True
            ),
            "trade_count": archive["value_trade_event_count"].astype(
                numpy.int64, copy=True
            ),
            "ask": archive["value_entry_ask_500"].astype(
                numpy.float64, copy=True
            ),
            "bid": archive["value_entry_bid_500"].astype(
                numpy.float64, copy=True
            ),
        }
    expected = end - start + 1
    for name in ("buy_size", "sell_size", "trade_count", "ask", "bid"):
        if len(result[name]) != expected:
            raise ValueError(f"source-cache {name} is not second-dense")
    return result


def _quote(cache, name, second):
    if not cache["start_second"] <= second <= cache["end_second"]:
        return math.nan
    value = float(cache[name][second - cache["start_second"]])
    return value if math.isfinite(value) and value > 0 else math.nan


def build_events(cache, start_second, end_second, *, extra_delay_seconds=0):
    """Build events whose complete four-hour outcome stays inside the block."""

    if extra_delay_seconds < 0:
        raise ValueError("extra delay cannot be negative")
    first_boundary = (
        (start_second + BOUNDARY_SECONDS - 1) // BOUNDARY_SECONDS
    ) * BOUNDARY_SECONDS
    events = []
    boundary = first_boundary
    while boundary < end_second:
        observation_end = boundary + OBSERVATION_SECONDS
        entry_second = observation_end + extra_delay_seconds
        exit_second = entry_second + HORIZON_SECONDS
        if exit_second >= end_second:
            break
        begin = boundary - cache["start_second"]
        finish = observation_end - cache["start_second"]
        if begin < 0 or finish > len(cache["trade_count"]):
            boundary += BOUNDARY_SECONDS
            continue
        trades = int(numpy.sum(cache["trade_count"][begin:finish]))
        buy = float(numpy.sum(cache["buy_size"][begin:finish]))
        sell = float(numpy.sum(cache["sell_size"][begin:finish]))
        total = buy + sell
        if trades < 1 or total <= 0 or buy == sell:
            boundary += BOUNDARY_SECONDS
            continue
        direction = 1 if buy > sell else -1
        imbalance = (buy - sell) / total
        if direction > 0:
            entry = _quote(cache, "ask", entry_second)
            exit_price = _quote(cache, "bid", exit_second)
            gross_bps = (exit_price / entry - 1.0) * 10_000.0
        else:
            entry = _quote(cache, "bid", entry_second)
            exit_price = _quote(cache, "ask", exit_second)
            gross_bps = (entry / exit_price - 1.0) * 10_000.0
        if not all(math.isfinite(value) for value in (entry, exit_price, gross_bps)):
            boundary += BOUNDARY_SECONDS
            continue
        events.append(
            {
                "timestamp": boundary,
                "exit_timestamp": exit_second,
                "direction": direction,
                "imbalance": imbalance,
                "trades": trades,
                "gross_bps": gross_bps,
            }
        )
        boundary += BOUNDARY_SECONDS
    return events


def event_metrics(events, *, cost_bps=ROUND_TRIP_COST_BPS) -> dict:
    if cost_bps < 0:
        raise ValueError("cost cannot be negative")
    gross = numpy.asarray([value["gross_bps"] for value in events])
    net = gross - cost_bps
    gains = float(numpy.sum(net[net > 0]))
    losses = float(-numpy.sum(net[net < 0]))
    by_day = {}
    for event, value in zip(events, net):
        day = datetime.datetime.fromtimestamp(
            event["timestamp"], datetime.timezone.utc
        ).date().isoformat()
        by_day.setdefault(day, []).append(float(value))
    directions = {}
    for direction in (-1, 1):
        selected = net[
            numpy.asarray([value["direction"] == direction for value in events])
        ]
        directions[str(direction)] = {
            "events": len(selected),
            "mean_net_bps": float(numpy.mean(selected)) if len(selected) else 0.0,
        }
    return {
        "events": len(events),
        "mean_gross_bps": float(numpy.mean(gross)) if len(gross) else 0.0,
        "median_gross_bps": float(numpy.median(gross)) if len(gross) else 0.0,
        "mean_net_bps": float(numpy.mean(net)) if len(net) else 0.0,
        "median_net_bps": float(numpy.median(net)) if len(net) else 0.0,
        "hit_rate": float(numpy.mean(net > 0)) if len(net) else 0.0,
        "profit_factor": (
            gains / losses if losses > 0 else (math.inf if gains > 0 else 0.0)
        ),
        "positive_day_ratio": (
            sum(numpy.mean(values) > 0 for values in by_day.values()) / len(by_day)
            if by_day
            else 0.0
        ),
        "operating_days": len(by_day),
        "by_direction": directions,
    }


def _fold_ranges(start, end):
    span = end - start
    return [
        (
            start + span * index // DEVELOPMENT_FOLDS,
            start + span * (index + 1) // DEVELOPMENT_FOLDS,
        )
        for index in range(DEVELOPMENT_FOLDS)
    ]


def _gate(primary, stress, specification, *, positive_folds=None):
    checks = {
        "minimum_events": primary["events"] >= specification["minimum_events"],
        "positive_mean_net_bps": primary["mean_net_bps"] > 0,
        "minimum_profit_factor": primary["profit_factor"]
        >= specification["minimum_profit_factor"],
        "minimum_hit_rate": primary["hit_rate"] >= specification["minimum_hit_rate"],
        "minimum_positive_day_ratio": primary["positive_day_ratio"]
        >= specification["minimum_positive_day_ratio"],
        "both_directions_non_negative": all(
            primary["by_direction"][str(direction)]["events"] > 0
            and primary["by_direction"][str(direction)]["mean_net_bps"] >= 0
            for direction in (-1, 1)
        ),
        "stress_mean_net_bps_positive": stress["mean_net_bps"] > 0,
        "minimum_stress_profit_factor": stress["profit_factor"]
        >= specification["minimum_stress_profit_factor"],
    }
    if positive_folds is not None:
        checks["minimum_positive_folds"] = (
            positive_folds >= specification["minimum_positive_folds"]
        )
    return {
        "checks": checks,
        "passed_checks": sum(checks.values()),
        "total_checks": len(checks),
        "passed": all(checks.values()),
    }


def evaluate_prelock(protocol_value, cache_value, output_root_value):
    protocol_path = pathlib.Path(protocol_value).resolve()
    protocol = write_or_verify_protocol(protocol_path)
    cache_path = pathlib.Path(cache_value).resolve()
    cache = load_source_cache(cache_path)
    development_start = max(_epoch(SOURCE_START), cache["start_second"])
    development_end = _epoch(DEVELOPMENT_END)
    confirmation_end = _epoch(CONFIRMATION_END)
    if cache["end_second"] < confirmation_end - 1:
        raise ValueError("source cache does not contain the confirmation block")

    development_events = build_events(
        cache, development_start, development_end
    )
    development_stress_events = build_events(
        cache,
        development_start,
        development_end,
        extra_delay_seconds=STRESS_DELAY_SECONDS,
    )
    development = event_metrics(development_events)
    development_stress = event_metrics(
        development_stress_events,
        cost_bps=ROUND_TRIP_COST_BPS * STRESS_COST_MULTIPLIER,
    )
    folds = []
    for start, end in _fold_ranges(development_start, development_end):
        folds.append(event_metrics(build_events(cache, start, end)))
    positive_folds = sum(value["mean_net_bps"] > 0 for value in folds)
    development_gate = _gate(
        development,
        development_stress,
        protocol["development_gate"],
        positive_folds=positive_folds,
    )

    confirmation = None
    confirmation_stress = None
    confirmation_gate = {
        "passed": False,
        "not_evaluated": not development_gate["passed"],
        "reason": "development_gate_failed" if not development_gate["passed"] else None,
    }
    if development_gate["passed"]:
        confirmation_events = build_events(
            cache, development_end, confirmation_end
        )
        confirmation_stress_events = build_events(
            cache,
            development_end,
            confirmation_end,
            extra_delay_seconds=STRESS_DELAY_SECONDS,
        )
        confirmation = event_metrics(confirmation_events)
        confirmation_stress = event_metrics(
            confirmation_stress_events,
            cost_bps=ROUND_TRIP_COST_BPS * STRESS_COST_MULTIPLIER,
        )
        confirmation_gate = _gate(
            confirmation,
            confirmation_stress,
            protocol["confirmation_gate"],
        )

    authorized = development_gate["passed"] and confirmation_gate["passed"]
    report = {
        "schema_version": SCHEMA_VERSION,
        "protocol_version": PROTOCOL_VERSION,
        "created_at": datetime.datetime.now(datetime.timezone.utc).isoformat(),
        "research_only": True,
        "public_data_only": True,
        "credentials_used": False,
        "orders_authorized": False,
        "paper_orders_authorized": False,
        "automatic_promotion": False,
        "protocol_sha256": protocol["protocol_sha256"],
        "protocol_file_sha256": common._sha256(protocol_path),
        "source_cache": {
            "path": str(cache_path),
            "bytes": cache_path.stat().st_size,
            "sha256": common._sha256(cache_path),
            "snapshot_sha256": scalping_v1.SNAPSHOT_SHA256,
        },
        "development": development,
        "development_stress": development_stress,
        "development_folds": folds,
        "development_positive_folds": positive_folds,
        "development_gate": development_gate,
        "confirmation": confirmation,
        "confirmation_stress": confirmation_stress,
        "confirmation_gate": confirmation_gate,
        "locked_test": {
            "authorized_to_materialize": authorized,
            "materialized": False,
            "reason": (
                "separate locked source required"
                if authorized
                else "prelock_gate_failed"
            ),
        },
        "verdict": (
            "ELIGIBLE_FOR_LOCKED_SOURCE_AND_NONOVERLAP_PROTOCOL"
            if authorized
            else "REJECTED_PRELOCK_LOCK_REMAINS_SEALED"
        ),
        "overlapping_markouts_are_not_portfolio_returns": True,
        "results_do_not_authorize_orders": True,
    }
    output_root = pathlib.Path(output_root_value).resolve()
    experiment = output_root / (
        "quarter-hour-flow-v1-"
        + datetime.datetime.now(datetime.timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    )
    experiment.mkdir(parents=True, exist_ok=False)
    report_path = experiment / "report.json"
    common._atomic_json(report_path, report)
    manifest = {
        "schema_version": SCHEMA_VERSION,
        "protocol_sha256": protocol["protocol_sha256"],
        "report_path": str(report_path),
        "report_sha256": common._sha256(report_path),
        "locked_test_materialized": False,
        "orders_authorized": False,
        "paper_orders_authorized": False,
        "automatic_promotion": False,
    }
    manifest["content_sha256"] = common._json_hash(manifest)
    common._atomic_json(experiment / "manifest.json", manifest)
    return {"report": report, "manifest": manifest, "directory": str(experiment)}


def _parser():
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)
    write = subparsers.add_parser("write-protocol")
    write.add_argument("--output", required=True)
    evaluate = subparsers.add_parser("evaluate-prelock")
    evaluate.add_argument("--protocol", required=True)
    evaluate.add_argument("--source-cache", required=True)
    evaluate.add_argument("--output-root", required=True)
    return parser


def main(argv=None):
    args = _parser().parse_args(argv)
    if args.command == "write-protocol":
        print(json.dumps(write_or_verify_protocol(args.output), indent=2, sort_keys=True))
        return 0
    result = evaluate_prelock(args.protocol, args.source_cache, args.output_root)
    print(json.dumps(common._json_safe(result), indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
