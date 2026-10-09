"""Offline V13 comparison, following the recorded benchmark calculation method.

Uses only the already-observed frozen Binance panel. No strategy selection,
exchange client, account mutations, or newly claimed out-of-sample evidence.
"""
from __future__ import annotations

import argparse
import calendar
import dataclasses
import datetime as dt
import hashlib
import json
import math
import pathlib

import numpy as np

from octobot.ai_strategy_lab import diversified_trend_cointegration_v1_research as trainer
from octobot.ai_strategy_lab import trend

NAMES = ("v13_quantities", "ew_v13_gross", "ew_vol_budget", "buy_hold_90pct", "cash")


def _market_arrays(market):
    closes = np.asarray(market["closes"], dtype=float)
    funding = np.asarray(market["funding"], dtype=float)
    dates, symbols = market["dates"], market["symbols"]
    if (closes.ndim != 2 or len(closes) < 2 or closes.shape[1] == 0
            or funding.shape != closes.shape or len(dates) != len(closes)
            or len(symbols) != closes.shape[1] or len(set(symbols)) != len(symbols)
            or not np.isfinite(closes).all() or (closes <= 0).any()
            or not np.isfinite(funding).all()):
        raise ValueError("invalid market arrays")
    if any(right-left != dt.timedelta(days=1) for left, right in zip(dates, dates[1:])):
        raise ValueError("market calendar must be consecutive daily observations")
    return closes, funding


def build_targets(market, config):
    closes, _ = _market_arrays(market)
    config.validate()
    start = max(config.slow_days, config.volatility_lookback_days)
    if start >= len(closes):
        raise ValueError("insufficient warmup history")
    returns = np.zeros_like(closes)
    returns[1:] = closes[1:]/closes[:-1]-1
    covariance = trend._rolling_covariance(returns, config.volatility_lookback_days)
    signals = trend._signals(closes, config, market["symbols"])
    unit = np.ones(closes.shape[1]) / closes.shape[1]
    result = {name: {} for name in NAMES}
    for index in range(start, len(closes), config.rebalance_days):
        weights = trend._target_weights(signals[index], covariance[index], config)
        result["v13_quantities"][index] = weights
        result["ew_v13_gross"][index] = unit * float(np.abs(weights).sum())
        variance = float(unit @ covariance[index] @ unit)
        if not math.isfinite(variance) or variance < -1e-12:
            raise ValueError("invalid ex-ante benchmark covariance")
        sigma = math.sqrt(max(variance, 0))
        # Zero estimated volatility does not authorize an infinite risk budget.
        scale = min(config.maximum_gross_exposure,
                    config.target_annual_volatility/sigma,
                    len(unit)*config.maximum_asset_exposure) if sigma > 0 else 0.0
        result["ew_vol_budget"][index] = unit * scale
    result["buy_hold_90pct"][start] = unit * config.maximum_gross_exposure
    return result


def _periods(dates, returns, pattern):
    groups = {}
    for date, value in zip(dates, returns):
        groups.setdefault(date.strftime(pattern), []).append((date, float(value)))
    result = []
    for label, values in sorted(groups.items()):
        first, last = values[0][0], values[-1][0]
        if pattern == "%Y-%m":
            full_start = dt.date(first.year, first.month, 1)
            full_end = dt.date(last.year, last.month, calendar.monthrange(last.year, last.month)[1])
        else:
            full_start, full_end = dt.date(first.year, 1, 1), dt.date(last.year, 12, 31)
        result.append(dict(period=label, net_return=float(np.prod([1+x[1] for x in values])-1),
                           observations=len(values), partial=first != full_start or last != full_end))
    return result


def simulate(market, targets, start_index, fee_rate, slippage_rate, delay_days=0, initial_equity=10000.0):
    closes, funding = _market_arrays(market)
    if (isinstance(start_index, bool) or not isinstance(start_index, int)
            or not 1 <= start_index < len(closes)
            or isinstance(delay_days, bool) or not isinstance(delay_days, int) or delay_days < 0
            or not all(math.isfinite(v) for v in (fee_rate, slippage_rate, initial_equity))
            or min(fee_rate, slippage_rate) < 0 or initial_equity <= 0):
        raise ValueError("invalid simulation configuration")
    schedule = {}
    for index, target in targets.items():
        weights = np.asarray(target, dtype=float)
        if (isinstance(index, bool) or not isinstance(index, int)
                or not start_index <= index < len(closes)
                or weights.shape != (closes.shape[1],) or not np.isfinite(weights).all()):
            raise ValueError("invalid target schedule")
        schedule[index+delay_days] = weights.copy()
    quantity = np.zeros(closes.shape[1])
    price_pnl = np.zeros_like(quantity)
    funding_pnl = np.zeros_like(quantity)
    fees = np.zeros_like(quantity)
    slippage = np.zeros_like(quantity)
    turnover = np.zeros_like(quantity)
    equity, equities = float(initial_equity), [float(initial_equity)]
    gross, net, fills, rebalances = [], [], 0, 0
    for index in range(start_index, len(closes)):
        price_change = quantity * (closes[index]-closes[index-1])
        funding_change = -quantity * closes[index-1] * funding[index]
        price_pnl += price_change
        funding_pnl += funding_change
        equity += float((price_change+funding_change).sum())
        if equity <= 0 or not math.isfinite(equity):
            raise ValueError(f"portfolio insolvent at {market['dates'][index]}")
        if index in schedule:
            new_quantity = equity * schedule[index] / closes[index]
            delta = new_quantity-quantity
            traded = np.abs(delta) * closes[index]
            turnover += traded
            fees += traded * fee_rate
            slippage += traded * slippage_rate
            equity -= float(traded.sum())*(fee_rate+slippage_rate)
            quantity = new_quantity
            fills += int(np.count_nonzero(np.abs(delta) > 1e-12))
            rebalances += 1
        if equity <= 0 or not math.isfinite(equity):
            raise ValueError(f"portfolio insolvent after costs at {market['dates'][index]}")
        gross.append(float(np.sum(np.abs(quantity)*closes[index])/equity))
        net.append(float(np.sum(quantity*closes[index])/equity))
        equities.append(equity)
    values = np.asarray(equities)
    returns = np.diff(values)/values[:-1]
    dates = market["dates"][start_index:]
    years = (dates[-1]-dates[0]).days/365.25
    sigma = float(np.std(returns))
    months, calendar_years = _periods(dates, returns, "%Y-%m"), _periods(dates, returns, "%Y")
    full_months = [month for month in months if not month["partial"]]
    attributed = price_pnl+funding_pnl-fees-slippage
    residual = equity-initial_equity-float(attributed.sum())
    if abs(residual) > 1e-7:
        raise ValueError("portfolio attribution fails reconciliation")
    return dict(
        evaluation_start=str(dates[0]), evaluation_end=str(dates[-1]), evaluation_days=len(dates),
        initial_equity=initial_equity, final_equity=equity, net_pnl=equity-initial_equity,
        net_total_return=equity/initial_equity-1,
        annualized_return=(equity/initial_equity)**(1/years)-1 if years else None,
        realized_annualized_volatility=sigma*math.sqrt(365),
        max_drawdown=float(np.max(1-values/np.maximum.accumulate(values))),
        sharpe_zero_rate=float(np.mean(returns)/sigma*math.sqrt(365)) if sigma else None,
        price_pnl=float(price_pnl.sum()), funding_pnl=float(funding_pnl.sum()),
        fees=float(fees.sum()), slippage=float(slippage.sum()), transaction_costs=float((fees+slippage).sum()),
        turnover_usdt=float(turnover.sum()), fills=fills, rebalance_dates_executed=rebalances,
        delayed_targets_outside_window=sum(index >= len(closes) for index in schedule),
        reconciliation_residual=residual,
        mean_actual_gross_exposure=float(np.mean(gross)), max_actual_gross_exposure=max(gross),
        mean_actual_net_exposure=float(np.mean(net)), min_actual_net_exposure=min(net), max_actual_net_exposure=max(net),
        hypothetical_terminal_cost_excluded=float(np.sum(np.abs(quantity)*closes[-1])*(fee_rate+slippage_rate)),
        positive_full_month_fraction=sum(m["net_return"] > 0 for m in full_months)/len(full_months) if full_months else None,
        months=months, years=calendar_years,
        assets=[dict(symbol=symbol, price_pnl=float(price_pnl[i]), funding_pnl=float(funding_pnl[i]),
                     fees=float(fees[i]), slippage=float(slippage[i]), net_pnl=float(attributed[i]),
                     turnover_usdt=float(turnover[i]), final_quantity=float(quantity[i]))
                for i, symbol in enumerate(market["symbols"])],
        trajectory=dict(dates=list(map(str, dates)), equity=equities, daily_return=returns.tolist(), gross=gross, net=net),
    )


def paired_spread(v13, control):
    v = np.asarray(v13["trajectory"]["daily_return"])
    b = np.asarray(control["trajectory"]["daily_return"])
    if v.shape != b.shape or v13["trajectory"]["dates"] != control["trajectory"]["dates"]:
        raise ValueError("unpaired comparison calendar")
    variance = float(np.var(b))
    beta = float(np.mean((v-v.mean())*(b-b.mean()))/variance) if variance > 1e-20 else None
    correlation = float(np.corrcoef(v, b)[0, 1]) if variance > 1e-20 and np.var(v) > 1e-20 else None
    monthly_spreads = [a["net_return"]-c["net_return"] for a, c in zip(v13["months"], control["months"])
                       if not a["partial"] and not c["partial"]]
    return dict(net_total_return_spread=v13["net_total_return"]-control["net_total_return"],
                annualized_return_spread=v13["annualized_return"]-control["annualized_return"] if v13["annualized_return"] is not None else None,
                beta_descriptive=beta, correlation=correlation,
                annualized_regression_intercept_descriptive=float((v.mean()-beta*b.mean())*365) if beta is not None else None,
                full_months_beating_control=sum(value > 0 for value in monthly_spreads), full_month_count=len(monthly_spreads),
                inference="descriptive only: neither causal alpha nor a significance/profitability test")


def compare(market, config):
    schedules = build_targets(market, config)
    start = max(config.slow_days, config.volatility_lookback_days)
    scenarios = []
    for delay in (0, 1):
        for multiplier in (1, 3):
            portfolios = {name: simulate(market, schedule, start,
                config.fee_per_turnover*multiplier, config.slippage_per_turnover*multiplier, delay)
                for name, schedule in schedules.items()}
            spreads = {name: paired_spread(portfolios["v13_quantities"], portfolios[name]) for name in NAMES[1:]}
            for result in portfolios.values():
                del result["trajectory"]  # Report periods and attribution; no duplicate giant daily arrays.
            scenarios.append(dict(execution_convention="same_close_diagnostic" if delay == 0 else "next_close_delayed",
                                  delay_days=delay, cost_multiplier=multiplier, portfolios=portfolios, v13_minus_control=spreads))
    return dict(scenarios=scenarios)


def run_comparison(report_path, method_path):
    method_bytes = pathlib.Path(method_path).read_bytes()
    method = json.loads(method_bytes)
    if (method.get("id") != "v13_benchmark_comparison_v1" or "results" not in method or method["results"] is not None
            or any(method.get(key) is not False for key in ("orders_authorized", "paper_orders_authorized", "automatic_promotion"))):
        raise ValueError("comparison method safety/identity differs")
    expected = method["historical"]
    if (expected.get("initial_equity") != 10000
            or expected.get("cost_multipliers") != [1, 3]
            or any(type(value) is not int for value in expected["cost_multipliers"])
            or expected.get("execution_conventions") != ["same_close_diagnostic", "next_close_delayed"]):
        raise ValueError("unsupported frozen comparison scenarios/capital")
    market, config, artifacts = trainer._load_trend_component(report_path)
    for field, value in (("target_volatility", config.target_annual_volatility),
                         ("maximum_gross", config.maximum_gross_exposure), ("maximum_asset", config.maximum_asset_exposure),
                         ("covariance_lookback_days", config.volatility_lookback_days), ("rebalance_days", config.rebalance_days),
                         ("fee_rate", config.fee_per_turnover), ("slippage_rate", config.slippage_per_turnover)):
        if expected[field] != value:
            raise ValueError(f"frozen method/config mismatch: {field}")
    result = compare(market, config)
    return dict(result, schema_version=1, audit_date="2026-09-13", mode="diagnostic_reuse_known_historical_panel",
                research_only=True, orders_authorized=False, paper_orders_authorized=False, automatic_promotion=False,
                parameters_tuned=False, new_out_of_sample_evidence=False,
                method_sha256=hashlib.sha256(method_bytes).hexdigest(),
                source_sha256=hashlib.sha256(pathlib.Path(__file__).read_bytes()).hexdigest(),
                verified_inputs=artifacts, configuration=dataclasses.asdict(config), symbols=market["symbols"],
                limitations=method["limitations"]+[
                    "No independent point-in-time delisting/universe or settlement coverage audit added; inherited zero funding convention retained.",
                    "Next daily close is a delay sensitivity, not a reconstruction of 15-minute KuCoin paper fills.",
                    "Exposures can drift above target caps while quantities are held; observed risk is reported, not forced equal retrospectively.",
                    "The buy-hold reference is a USDT perpetual-futures basket including funding, not a spot investment.",
                    "Calendar edge months/years are flagged partial; no terminal liquidation is charged in any scenario.",
                ])


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--report", type=pathlib.Path, required=True)
    parser.add_argument("--method", type=pathlib.Path, required=True)
    args = parser.parse_args()
    print(json.dumps(run_comparison(args.report, args.method), indent=2, sort_keys=True, allow_nan=False))


if __name__ == "__main__":
    main()
