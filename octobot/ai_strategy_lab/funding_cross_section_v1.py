"""Research-only cross-sectional perpetual-funding carry protocol V1."""

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


SCHEMA_VERSION = 1
PROTOCOL_VERSION = "crypto_futures_cross_sectional_funding_carry_v1"
PREREGISTRATION_DATE = "2026-08-28"
LOOKBACK_DAYS = 7
VOLATILITY_LOOKBACK_DAYS = 30
SELECTION_FRACTION = 0.25
SIDE_GROSS_EXPOSURE = 0.40
MAXIMUM_ASSET_EXPOSURE = 0.10
FEE_PER_TURNOVER = 0.0006
SLIPPAGE_PER_TURNOVER = 0.0002
STRESS_COST_MULTIPLIER = 3.0
DEVELOPMENT_START = datetime.date(2022, 7, 1)
DEVELOPMENT_END = datetime.date(2025, 1, 1)
CONFIRMATION_START = DEVELOPMENT_END
CONFIRMATION_END = datetime.date(2026, 1, 1)
LOCKED_START = CONFIRMATION_END
LOCKED_END = datetime.date(2026, 7, 1)
DEVELOPMENT_FOLDS = (
    (datetime.date(2022, 7, 1), datetime.date(2023, 1, 1)),
    (datetime.date(2023, 1, 1), datetime.date(2023, 7, 1)),
    (datetime.date(2023, 7, 1), datetime.date(2024, 1, 1)),
    (datetime.date(2024, 1, 1), datetime.date(2024, 7, 1)),
    (datetime.date(2024, 7, 1), datetime.date(2025, 1, 1)),
)


def frozen_protocol() -> dict:
    return {
        "schema_version": SCHEMA_VERSION,
        "protocol_version": PROTOCOL_VERSION,
        "preregistered_on": PREREGISTRATION_DATE,
        "status": "result_free_evaluation_protocol",
        "research_only": True,
        "public_data_only": True,
        "credentials_used": False,
        "orders_authorized": False,
        "paper_orders_authorized": False,
        "automatic_promotion": False,
        "hypothesis": {
            "name": "cross_sectional_funding_spread_harvest",
            "statement": (
                "a dollar-neutral portfolio long the lowest trailing funding "
                "perpetuals and short the highest trailing funding perpetuals "
                "can harvest a persistent funding spread after price basis "
                "risk, taker fees and slippage"
            ),
            "direction": "long low funding and short high funding only",
            "opposite_direction_tested": False,
            "one_configuration_only": True,
        },
        "signal": {
            "funding_lookback_days": LOOKBACK_DAYS,
            "ranking": "ascending sum of signed completed funding settlements",
            "selection_fraction_per_side": SELECTION_FRACTION,
            "long_side": "lowest funding quartile",
            "short_side": "highest funding quartile",
            "volatility_lookback_days": VOLATILITY_LOOKBACK_DAYS,
            "weighting": "inverse volatility within each side",
            "side_gross_exposure": SIDE_GROSS_EXPOSURE,
            "maximum_asset_exposure": MAXIMUM_ASSET_EXPOSURE,
            "dollar_neutral_after_caps": True,
            "rebalance": "Monday UTC close; weights apply to the next day",
            "future_funding_not_used": True,
        },
        "economics": {
            "price_pnl": "daily perpetual close-to-close on prior weights",
            "funding_pnl": "negative position weight times signed settlement",
            "fee_per_turnover": FEE_PER_TURNOVER,
            "slippage_per_turnover": SLIPPAGE_PER_TURNOVER,
            "stress_cost_multiplier": STRESS_COST_MULTIPLIER,
            "maker_fill_assumptions": False,
            "forced_flatten_at_each_evaluation_end": True,
            "maximum_portfolio_gross": 2.0 * SIDE_GROSS_EXPOSURE,
        },
        "validation": {
            "development": [
                DEVELOPMENT_START.isoformat(),
                DEVELOPMENT_END.isoformat(),
            ],
            "development_end_exclusive": True,
            "walk_forward_folds": [
                [start.isoformat(), end.isoformat()]
                for start, end in DEVELOPMENT_FOLDS
            ],
            "confirmation": [
                CONFIRMATION_START.isoformat(),
                CONFIRMATION_END.isoformat(),
            ],
            "confirmation_end_exclusive": True,
            "locked_final_test": [
                LOCKED_START.isoformat(),
                LOCKED_END.isoformat(),
            ],
            "locked_end_exclusive": True,
            "locked_policy": (
                "do not calculate confirmation unless development passes, "
                "and do not calculate the lock unless both prior gates pass"
            ),
            "survivorship_limitation": (
                "the fixed 18-asset archive contains contracts surviving to "
                "the archive end; a full pass still requires new prospective data"
            ),
        },
        "development_gate": {
            "minimum_rebalances": 100,
            "minimum_annualized_return": 0.05,
            "minimum_sharpe": 1.00,
            "maximum_drawdown": 0.10,
            "minimum_positive_month_ratio": 0.60,
            "minimum_positive_folds": 4,
            "required_folds": len(DEVELOPMENT_FOLDS),
            "funding_return_positive": True,
            "funding_return_exceeds_cost": True,
            "stress_total_return_positive": True,
            "minimum_stress_sharpe": 0.50,
        },
        "confirmation_gate": {
            "minimum_rebalances": 45,
            "minimum_annualized_return": 0.04,
            "minimum_sharpe": 0.75,
            "maximum_drawdown": 0.10,
            "minimum_positive_month_ratio": 0.55,
            "funding_return_positive": True,
            "funding_return_exceeds_cost": True,
            "stress_total_return_positive": True,
            "minimum_stress_sharpe": 0.25,
        },
        "locked_gate": {
            "minimum_rebalances": 20,
            "positive_total_return": True,
            "minimum_sharpe": 0.50,
            "maximum_drawdown": 0.10,
            "funding_return_positive": True,
            "stress_total_return_positive": True,
        },
        "multiple_testing_disclosure": (
            "one funding window, one rebalance frequency, one rank direction, "
            "one selection fraction and one volatility weighting are evaluated"
        ),
        "promotion_consequence": (
            "a complete pass permits only manually approved orderless shadow; "
            "paper and real orders remain unauthorized"
        ),
        "results": None,
    }


def write_or_verify_protocol(
    path_value: typing.Union[str, pathlib.Path],
) -> dict:
    path = pathlib.Path(path_value).resolve()
    protocol = frozen_protocol()
    payload = {**protocol, "protocol_sha256": common._json_hash(protocol)}
    if path.is_file():
        persisted = json.loads(path.read_text(encoding="utf-8"))
        if persisted != payload:
            raise ValueError("persisted funding cross-section V1 protocol differs")
        return persisted
    common._atomic_json(path, payload)
    return payload


def target_weights(market: dict, index: int) -> numpy.ndarray:
    """Use only completed funding and returns through ``index``."""

    if index < max(LOOKBACK_DAYS, VOLATILITY_LOOKBACK_DAYS):
        return numpy.zeros(len(market["symbols"]), dtype=numpy.float64)
    trailing_funding = numpy.sum(
        market["funding"][index - LOOKBACK_DAYS + 1 : index + 1], axis=0
    )
    volatilities = numpy.std(
        market["returns"][
            index - VOLATILITY_LOOKBACK_DAYS + 1 : index + 1
        ],
        axis=0,
        ddof=1,
    )
    eligible = [
        column
        for column in range(len(market["symbols"]))
        if math.isfinite(float(trailing_funding[column]))
        and math.isfinite(float(volatilities[column]))
        and volatilities[column] > 1e-12
    ]
    if len(eligible) < 7:
        return numpy.zeros(len(market["symbols"]), dtype=numpy.float64)
    ordered = sorted(
        eligible,
        key=lambda column: (
            float(trailing_funding[column]),
            market["symbols"][column],
        ),
    )
    count = max(1, int(math.ceil(len(ordered) * SELECTION_FRACTION)))
    long_columns = ordered[:count]
    short_columns = ordered[-count:]
    target = numpy.zeros(len(market["symbols"]), dtype=numpy.float64)
    _assign_side(target, long_columns, volatilities, direction=1.0)
    _assign_side(target, short_columns, volatilities, direction=-1.0)
    long_gross = float(numpy.sum(numpy.maximum(target, 0.0)))
    short_gross = float(numpy.sum(numpy.maximum(-target, 0.0)))
    matched = min(long_gross, short_gross)
    if long_gross > 0:
        target[target > 0] *= matched / long_gross
    if short_gross > 0:
        target[target < 0] *= matched / short_gross
    return target


def _assign_side(target, columns, volatilities, *, direction):
    inverse = numpy.asarray(
        [1.0 / float(volatilities[column]) for column in columns],
        dtype=numpy.float64,
    )
    allocations = SIDE_GROSS_EXPOSURE * inverse / float(numpy.sum(inverse))
    allocations = numpy.minimum(allocations, MAXIMUM_ASSET_EXPOSURE)
    for column, allocation in zip(columns, allocations):
        target[column] = direction * allocation


def _period_returns(dates, equity):
    endpoints = {}
    for date, value in zip(dates, equity):
        endpoints[date.strftime("%Y-%m")] = float(value)
    result = {}
    previous = 1.0
    for period, value in sorted(endpoints.items()):
        result[period] = value / previous - 1.0
        previous = value
    return result


def simulate_period(
    market: dict,
    start: datetime.date,
    end: datetime.date,
    *,
    cost_multiplier: float = 1.0,
) -> dict:
    if cost_multiplier < 1.0:
        raise ValueError("cost multiplier must be at least one")
    indices = [
        index
        for index, date in enumerate(market["dates"])
        if start <= date < end
    ]
    if not indices:
        raise ValueError("evaluation interval is absent from the market")
    first_index, final_index = indices[0], indices[-1]
    if first_index < max(LOOKBACK_DAYS, VOLATILITY_LOOKBACK_DAYS):
        raise ValueError("evaluation lacks signal warmup")
    weights = numpy.zeros(len(market["symbols"]), dtype=numpy.float64)
    equity = 1.0
    equities = []
    daily_returns = []
    applied_weights = []
    total_cost = 0.0
    total_funding = 0.0
    total_price = 0.0
    total_turnover = 0.0
    rebalance_events = 0
    contribution = numpy.zeros(len(weights), dtype=numpy.float64)
    long_contribution = 0.0
    short_contribution = 0.0
    per_turnover_cost = cost_multiplier * (
        FEE_PER_TURNOVER + SLIPPAGE_PER_TURNOVER
    )
    for index in range(first_index, final_index + 1):
        before = equity
        price = weights * market["returns"][index]
        funding = -weights * market["funding"][index]
        pnl = price + funding
        equity *= 1.0 + float(numpy.sum(pnl))
        contribution += pnl
        total_price += float(numpy.sum(price))
        total_funding += float(numpy.sum(funding))
        long_contribution += float(numpy.sum(pnl[weights > 0]))
        short_contribution += float(numpy.sum(pnl[weights < 0]))
        date = market["dates"][index]
        if date.weekday() == 0:
            target = target_weights(market, index)
            turnover = float(numpy.sum(numpy.abs(target - weights)))
            cost = turnover * per_turnover_cost
            equity *= 1.0 - cost
            if turnover:
                contribution -= numpy.abs(target - weights) / turnover * cost
                rebalance_events += 1
            total_cost += cost
            total_turnover += turnover
            weights = target
        if equity <= 0:
            raise ValueError("funding cross-section equity became non-positive")
        equities.append(equity)
        daily_returns.append(equity / before - 1.0)
        applied_weights.append(weights.copy())

    closing_turnover = float(numpy.sum(numpy.abs(weights)))
    closing_cost = closing_turnover * per_turnover_cost
    if closing_cost:
        equity *= 1.0 - closing_cost
        total_cost += closing_cost
        total_turnover += closing_turnover
        previous = equities[-2] if len(equities) > 1 else 1.0
        equities[-1] = equity
        daily_returns[-1] = equity / previous - 1.0
        contribution -= numpy.abs(weights) / closing_turnover * closing_cost
    equity_values = numpy.asarray(equities, dtype=numpy.float64)
    daily_values = numpy.asarray(daily_returns, dtype=numpy.float64)
    weights_array = numpy.asarray(applied_weights, dtype=numpy.float64)
    peaks = numpy.maximum.accumulate(
        numpy.concatenate((numpy.ones(1), equity_values))
    )[1:]
    drawdowns = 1.0 - equity_values / peaks
    dates = market["dates"][first_index : final_index + 1]
    monthly = _period_returns(dates, equity_values)
    elapsed_years = max((dates[-1] - dates[0]).days / 365.25, 0.0)
    return {
        "start_date": dates[0].isoformat(),
        "end_date": dates[-1].isoformat(),
        "days": len(dates),
        "cost_multiplier": cost_multiplier,
        "total_return": float(equity - 1.0),
        "annualized_return": (
            float(equity ** (1.0 / elapsed_years) - 1.0)
            if elapsed_years > 0 and equity > 0
            else 0.0
        ),
        "maximum_drawdown": float(numpy.max(drawdowns)),
        "annualized_volatility": float(numpy.std(daily_values) * math.sqrt(365.0)),
        "sharpe_zero_rate": (
            float(numpy.mean(daily_values) / numpy.std(daily_values) * math.sqrt(365.0))
            if numpy.std(daily_values) > 0
            else 0.0
        ),
        "positive_month_ratio": (
            sum(value > 0 for value in monthly.values()) / len(monthly)
            if monthly
            else 0.0
        ),
        "monthly_returns": monthly,
        "rebalance_events": rebalance_events,
        "total_turnover": float(total_turnover),
        "total_cost_return": float(total_cost),
        "total_price_return": float(total_price),
        "total_funding_return": float(total_funding),
        "long_additive_contribution": float(long_contribution),
        "short_additive_contribution": float(short_contribution),
        "average_gross_exposure": float(
            numpy.mean(numpy.sum(numpy.abs(weights_array), axis=1))
        ),
        "maximum_gross_exposure": float(
            numpy.max(numpy.sum(numpy.abs(weights_array), axis=1))
        ),
        "maximum_absolute_net_exposure": float(
            numpy.max(numpy.abs(numpy.sum(weights_array, axis=1)))
        ),
        "by_symbol_additive_contribution": {
            symbol: float(value)
            for symbol, value in zip(market["symbols"], contribution)
        },
        "trajectory_sha256": common._json_hash(
            {
                "dates": [date.isoformat() for date in dates],
                "equity": equity_values.tolist(),
            }
        ),
    }


def _base_gate(report: dict, gate: dict) -> dict:
    checks = {
        "minimum_rebalances": report["rebalance_events"]
        >= gate["minimum_rebalances"],
        "minimum_sharpe": report["sharpe_zero_rate"] >= gate["minimum_sharpe"],
        "maximum_drawdown": report["maximum_drawdown"] <= gate["maximum_drawdown"],
        "funding_return_positive": report["total_funding_return"] > 0,
    }
    if "minimum_annualized_return" in gate:
        checks["minimum_annualized_return"] = (
            report["annualized_return"] >= gate["minimum_annualized_return"]
        )
    if "positive_total_return" in gate:
        checks["positive_total_return"] = report["total_return"] > 0
    if "minimum_positive_month_ratio" in gate:
        checks["minimum_positive_month_ratio"] = (
            report["positive_month_ratio"] >= gate["minimum_positive_month_ratio"]
        )
    if gate.get("funding_return_exceeds_cost"):
        checks["funding_return_exceeds_cost"] = (
            report["total_funding_return"] > report["total_cost_return"]
        )
    return {
        "checks": checks,
        "passed_checks": sum(checks.values()),
        "total_checks": len(checks),
        "passed": all(checks.values()),
    }


def _finish_gate(gate, stress, specification, *, positive_folds=None):
    if positive_folds is not None:
        gate["checks"]["minimum_positive_folds"] = (
            positive_folds >= specification["minimum_positive_folds"]
        )
        gate["checks"]["required_folds_present"] = (
            specification["required_folds"] == len(DEVELOPMENT_FOLDS)
        )
    gate["checks"]["stress_total_return_positive"] = stress["total_return"] > 0
    if "minimum_stress_sharpe" in specification:
        gate["checks"]["minimum_stress_sharpe"] = (
            stress["sharpe_zero_rate"] >= specification["minimum_stress_sharpe"]
        )
    gate["passed_checks"] = sum(gate["checks"].values())
    gate["total_checks"] = len(gate["checks"])
    gate["passed"] = all(gate["checks"].values())
    return gate


def evaluate_prelock(
    protocol_value,
    futures_collectors,
    funding_paths,
    output_root_value,
) -> dict:
    protocol_path = pathlib.Path(protocol_value).resolve()
    protocol = write_or_verify_protocol(protocol_path)
    market, artifacts = common.load_market(futures_collectors, funding_paths)
    if market["dates"][0] > DEVELOPMENT_START - datetime.timedelta(
        days=VOLATILITY_LOOKBACK_DAYS
    ):
        raise ValueError("market does not provide the frozen signal warmup")
    if market["dates"][-1] < LOCKED_END - datetime.timedelta(days=1):
        raise ValueError("market does not contain the declared locked interval")

    development = simulate_period(market, DEVELOPMENT_START, DEVELOPMENT_END)
    development_stress = simulate_period(
        market,
        DEVELOPMENT_START,
        DEVELOPMENT_END,
        cost_multiplier=STRESS_COST_MULTIPLIER,
    )
    folds = [simulate_period(market, start, end) for start, end in DEVELOPMENT_FOLDS]
    positive_folds = sum(value["total_return"] > 0 for value in folds)
    development_gate = _finish_gate(
        _base_gate(development, protocol["development_gate"]),
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
        confirmation = simulate_period(
            market, CONFIRMATION_START, CONFIRMATION_END
        )
        confirmation_stress = simulate_period(
            market,
            CONFIRMATION_START,
            CONFIRMATION_END,
            cost_multiplier=STRESS_COST_MULTIPLIER,
        )
        confirmation_gate = _finish_gate(
            _base_gate(confirmation, protocol["confirmation_gate"]),
            confirmation_stress,
            protocol["confirmation_gate"],
        )

    locked_authorized = development_gate["passed"] and confirmation_gate["passed"]
    locked = None
    locked_stress = None
    locked_gate = {
        "passed": False,
        "not_evaluated": not locked_authorized,
        "reason": "prelock_gate_failed" if not locked_authorized else None,
    }
    if locked_authorized:
        locked = simulate_period(market, LOCKED_START, LOCKED_END)
        locked_stress = simulate_period(
            market,
            LOCKED_START,
            LOCKED_END,
            cost_multiplier=STRESS_COST_MULTIPLIER,
        )
        locked_gate = _finish_gate(
            _base_gate(locked, protocol["locked_gate"]),
            locked_stress,
            protocol["locked_gate"],
        )

    complete_pass = locked_authorized and locked_gate["passed"]
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
        "protocol_path": str(protocol_path),
        "protocol_file_sha256": common._sha256(protocol_path),
        "protocol_sha256": protocol["protocol_sha256"],
        "source_artifacts": artifacts,
        "symbols": market["symbols"],
        "market": {
            "start_date": market["dates"][0].isoformat(),
            "end_date": market["dates"][-1].isoformat(),
            "days": len(market["dates"]),
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
            "authorized_to_open": locked_authorized,
            "materialized": locked is not None,
            "report": locked,
            "stress_report": locked_stress,
            "gate": locked_gate,
        },
        "verdict": (
            "ELIGIBLE_FOR_MANUAL_ORDERLESS_SHADOW"
            if complete_pass
            else (
                "REJECTED_LOCKED_TEST"
                if locked is not None
                else "REJECTED_PRELOCK_LOCK_REMAINS_SEALED"
            )
        ),
        "results_do_not_authorize_orders": True,
    }
    output_root = pathlib.Path(output_root_value).resolve()
    experiment = output_root / (
        "funding-cross-section-v1-"
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
        "locked_test_materialized": locked is not None,
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
    evaluate.add_argument("--futures-collector", action="append", required=True)
    evaluate.add_argument("--funding-json", action="append", required=True)
    evaluate.add_argument("--output-root", required=True)
    return parser


def main(argv=None):
    args = _parser().parse_args(argv)
    if args.command == "write-protocol":
        print(json.dumps(write_or_verify_protocol(args.output), indent=2, sort_keys=True))
        return 0
    result = evaluate_prelock(
        args.protocol,
        args.futures_collector,
        args.funding_json,
        args.output_root,
    )
    print(json.dumps(common._json_safe(result), indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
