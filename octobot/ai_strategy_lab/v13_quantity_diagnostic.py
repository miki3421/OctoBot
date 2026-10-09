"""Offline recosting of frozen V13 using quantities held between weekly trades.

This is a diagnostic reuse of observed training data, not a new holdout, model
selection or trading capability. No frozen source, input or result is modified.
Run in the existing observer image, which mounts the original input paths:
python3 -m octobot.ai_strategy_lab.v13_quantity_diagnostic --report REPORT.json
"""

from __future__ import annotations

import argparse
import dataclasses
import hashlib
import json
import pathlib

import numpy as np

from octobot.ai_strategy_lab import diversified_trend_cointegration_v1_research as trainer
from octobot.ai_strategy_lab import trend


def account_targets(market, targets, start_index, cost_rate, *, initial_equity=10000.0):
    """Account signed linear-USDT quantities; ``targets`` indexes weekly closes."""
    closes = np.asarray(market["closes"], dtype=float)
    funding = np.asarray(market["funding"], dtype=float)
    if (
        closes.ndim != 2 or funding.shape != closes.shape
        or len(market["dates"]) != len(closes)
        or not np.all(np.isfinite(closes)) or np.any(closes <= 0)
        or not np.all(np.isfinite(funding))
        or not 1 <= start_index < len(closes)
        or not np.isfinite(cost_rate) or cost_rate < 0
        or not np.isfinite(initial_equity) or initial_equity <= 0
    ):
        raise ValueError("invalid quantity diagnostic inputs")
    quantities = np.zeros(closes.shape[1])
    equity = float(initial_equity)
    trajectory = [equity]
    costs = funding_pnl = turnover = 0.0
    for index in range(start_index, len(closes)):
        equity += float(np.sum(quantities * (closes[index] - closes[index - 1])))
        daily_funding = float(np.sum(-quantities * closes[index - 1] * funding[index]))
        equity += daily_funding
        funding_pnl += daily_funding
        if index in targets:
            weights = np.asarray(targets[index], dtype=float)
            if weights.shape != quantities.shape or not np.all(np.isfinite(weights)):
                raise ValueError("invalid target weights")
            new_quantities = equity * weights / closes[index]
            traded = float(np.sum(np.abs(new_quantities - quantities) * closes[index]))
            cost = traded * cost_rate
            equity -= cost
            costs += cost
            turnover += traded
            quantities = new_quantities
        if not np.isfinite(equity) or equity <= 0:
            raise ValueError("non-positive quantity diagnostic equity")
        trajectory.append(equity)
    values = np.asarray(trajectory)
    returns = np.diff(values) / values[:-1]
    dates = market["dates"][start_index:]
    years = (dates[-1] - dates[0]).days / 365.25
    sigma = np.std(returns)
    return {
        "evaluation_start": str(dates[0]), "evaluation_end": str(dates[-1]),
        "evaluation_days": len(dates), "initial_equity": initial_equity,
        "final_equity": equity, "total_return": equity / initial_equity - 1,
        "annualized_return": (equity / initial_equity) ** (1 / years) - 1 if years else 0,
        "max_drawdown": float(np.max(1 - values / np.maximum.accumulate(values))),
        "sharpe_zero_rate": float(np.mean(returns) / sigma * np.sqrt(365)) if sigma else 0,
        "transaction_costs_usdt": costs, "funding_pnl_usdt": funding_pnl,
        "turnover_usdt": turnover, "rebalance_dates": len(targets),
    }


def run_diagnostic(report_path):
    # Existing loader verifies the report, config, frozen source and every raw
    # futures/funding input against the pre-existing hashes before computation.
    market, config, artifacts = trainer._load_trend_component(report_path)
    original = json.loads(pathlib.Path(report_path).read_text())
    signals = trend._signals(market["closes"], config, market["symbols"])
    covariance = trend._rolling_covariance(market["returns"], config.volatility_lookback_days)
    start = max(config.slow_days, config.volatility_lookback_days)
    targets = {
        index: trend._target_weights(signals[index], covariance[index], config)
        for index in range(start, len(market["dates"]), config.rebalance_days)
    }
    scenarios = []
    for multiplier in (1.0, 3.0):
        result = account_targets(
            market, targets, start,
            (config.fee_per_turnover + config.slippage_per_turnover) * multiplier,
        )
        result["cost_multiplier"] = multiplier
        reference_key = config.name + ("_cost_stress_3x" if multiplier == 3 else "")
        result["original_constant_weight_diagnostic"] = {
            key: original["reports"][reference_key][key]
            for key in ("total_return", "annualized_return", "max_drawdown", "sharpe_zero_rate")
        }
        scenarios.append(result)
    source = pathlib.Path(__file__)
    return {
        "schema_version": 1, "audit_date": "2026-09-12",
        "mode": "diagnostic_reuse_known_v13_training",
        "research_only": True, "new_out_of_sample_evidence": False,
        "parameters_tuned": False, "orders_authorized": False,
        "paper_orders_authorized": False, "automatic_promotion": False,
        "source_sha256": hashlib.sha256(source.read_bytes()).hexdigest(),
        "verified_inputs": artifacts, "configuration": dataclasses.asdict(config),
        "symbols": market["symbols"],
        "methodology": [
            "Frozen V13 signals and covariance sizing, unchanged weekly schedule.",
            "Linear USDT quantities held constant between scheduled rebalances; no free daily reweighting.",
            "Targets sized from pre-trade equity; transactions charged on actual absolute changed notional.",
            "Funding uses archived signed daily rates multiplied by held quantity and preceding daily close.",
            "Base fee 6bps plus slippage allowance 2bps per one-way turnover; both multiplied by 3 in stress.",
            "Initial equity 10000 USDT; no terminal liquidation, matching the original research horizon.",
        ],
        "limitations": [
            "Previously observed historical training data, not new forward validation or proof of profitability.",
            "Historical closes approximate execution; no historical depth, latency, contract-step or minimum-order model.",
            "Funding settlement mark approximated by preceding daily close.",
            "Binance research prices differ from the new KuCoin executable paper book snapshots.",
            "No promotion gate is reopened, lowered or claimed to pass by this diagnostic.",
        ],
        "scenarios": scenarios,
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--report", type=pathlib.Path, required=True)
    args = parser.parse_args()
    print(json.dumps(run_diagnostic(args.report), sort_keys=True, indent=2, allow_nan=False))


if __name__ == "__main__":
    main()
