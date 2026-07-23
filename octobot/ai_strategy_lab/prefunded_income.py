"""Prefunded fixed-cash income blocks financed only from strategy surplus."""

from __future__ import annotations

import pathlib
import typing

import numpy

from octobot.ai_strategy_lab import withdrawal as withdrawal_module


PREFUNDED_SCHEMA_VERSION = 3
DEFAULT_HAIRCUTS = (0.0, 0.05, 0.10)


def evaluate_prefunded_income(
    trend_report_paths: typing.Iterable[typing.Union[str, pathlib.Path]],
    strategy_name: str,
    *,
    initial_capital: float = 10_000.0,
    monthly_amounts: typing.Iterable[float] = (25.0, 50.0),
    block_months: int = 12,
    horizon_months: int = 120,
    bootstrap_block_months: int = 6,
    simulations: int = 10_000,
    annual_return_haircuts: typing.Iterable[float] = DEFAULT_HAIRCUTS,
    random_seed: int = 20_260_723,
) -> dict:
    if initial_capital <= 0:
        raise ValueError("initial capital must be positive")
    amounts = tuple(float(value) for value in monthly_amounts)
    if not amounts or any(value <= 0 for value in amounts):
        raise ValueError("monthly amounts must be positive")
    haircuts = tuple(float(value) for value in annual_return_haircuts)
    if not haircuts or any(value < 0 or value >= 1 for value in haircuts):
        raise ValueError("annual return haircuts must be in [0, 1)")
    if block_months < 1 or horizon_months < 24:
        raise ValueError("invalid income block or horizon")
    if bootstrap_block_months < 1 or simulations < 100:
        raise ValueError("invalid bootstrap configuration")
    monthly_returns, sources = withdrawal_module._load_monthly_returns(
        trend_report_paths, strategy_name
    )
    values = numpy.asarray(
        [value for _, value in monthly_returns], dtype=numpy.float64
    )
    segment_lengths = withdrawal_module._bootstrap_segment_lengths(
        sources, len(values)
    )
    if len(values) < 24:
        raise ValueError("at least 24 non-overlapping months are required")

    scenarios = {}
    for haircut in haircuts:
        monthly_haircut = (1.0 + haircut) ** (1.0 / 12.0) - 1.0
        adjusted = values - monthly_haircut
        paths = withdrawal_module._moving_block_paths(
            adjusted,
            horizon_months=horizon_months,
            block_months=bootstrap_block_months,
            simulations=simulations,
            rng=numpy.random.default_rng(random_seed),
            segment_lengths=segment_lengths,
        )
        historical_segments = withdrawal_module._split_values_by_source(
            adjusted, sources
        )
        amount_reports = {}
        for amount in amounts:
            historical_by_source = [
                {
                    "source": source,
                    "result": simulate_prefunded_income(
                        segment,
                        initial_capital=initial_capital,
                        monthly_amount=amount,
                        block_months=block_months,
                    ),
                }
                for source, segment in zip(sources, historical_segments)
            ]
            results = [
                simulate_prefunded_income(
                    path,
                    initial_capital=initial_capital,
                    monthly_amount=amount,
                    block_months=block_months,
                )
                for path in paths
            ]
            summary = _summarize(results)
            gate_horizon_months = 36 if block_months >= 24 else 24
            first_block_probability_key = (
                f"probability_first_block_within_{gate_horizon_months}_months"
            )
            checks = {
                (
                    f"first_block_within_{gate_horizon_months}_months_"
                    "at_least_90pct"
                ): (
                    summary[first_block_probability_key] >= 0.90
                ),
                "conditional_no_pause_at_least_80pct": (
                    summary[
                        "conditional_probability_no_pause_after_start"
                    ]
                    >= 0.80
                ),
                "conditional_mean_coverage_at_least_95pct": (
                    summary["conditional_mean_post_start_coverage"]
                    >= 0.95
                ),
                "no_prefunding_guarantee_breach": (
                    summary["guarantee_breaches"] == 0
                ),
            }
            amount_reports[f"{amount:g}"] = {
                "monthly_amount": amount,
                "reserve_target": amount * block_months,
                "historical_sequences_by_source": historical_by_source,
                "bootstrap": summary,
                "operational_gate": {
                    "passed": all(checks.values()),
                    "first_block_horizon_months": gate_horizon_months,
                    "checks": checks,
                },
            }
        scenarios[f"{haircut:.2%}"] = {
            "annual_return_haircut": haircut,
            "monthly_additive_haircut": monthly_haircut,
            "amounts": amount_reports,
        }
    return {
        "schema_version": PREFUNDED_SCHEMA_VERSION,
        "research_only": True,
        "warning": (
            "Only a fully prefunded block is fixed. Future blocks and "
            "perpetual income are not guaranteed; custody loss is not modelled."
        ),
        "strategy_name": strategy_name,
        "initial_capital": initial_capital,
        "monthly_amounts": list(amounts),
        "block_months": block_months,
        "horizon_months": horizon_months,
        "bootstrap_block_months": bootstrap_block_months,
        "simulations": simulations,
        "random_seed": random_seed,
        "historical_months": len(monthly_returns),
        "historical_start_month": monthly_returns[0][0],
        "historical_end_month": monthly_returns[-1][0],
        "sources": sources,
        "bootstrap_segments": withdrawal_module._bootstrap_metadata(
            sources, segment_lengths
        ),
        "scenarios": scenarios,
        "real_withdrawals_authorized": False,
    }


def simulate_prefunded_income(
    monthly_returns,
    *,
    initial_capital,
    monthly_amount,
    block_months,
):
    trading_balance = float(initial_capital)
    reserve_balance = 0.0
    reserve_target = monthly_amount * block_months
    block_remaining = 0
    blocks_started = 0
    first_payment_month = None
    payments = 0
    pause_months_after_start = 0
    total_withdrawn = 0.0
    total_transferred = 0.0
    minimum_trading_balance = trading_balance
    minimum_reserve_during_active_block = reserve_target
    guarantee_breaches = 0

    for index, monthly_return in enumerate(monthly_returns):
        trading_balance *= 1.0 + float(monthly_return)
        minimum_trading_balance = min(
            minimum_trading_balance, trading_balance
        )
        available_surplus = max(0.0, trading_balance - initial_capital)
        reserve_gap = max(0.0, reserve_target - reserve_balance)
        transfer = min(available_surplus, reserve_gap)
        trading_balance -= transfer
        reserve_balance += transfer
        total_transferred += transfer

        if block_remaining == 0 and reserve_balance + 1e-9 >= reserve_target:
            reserve_balance = max(reserve_balance, reserve_target)
            block_remaining = block_months
            blocks_started += 1
        if block_remaining > 0:
            if reserve_balance + 1e-9 < monthly_amount:
                guarantee_breaches += 1
            else:
                reserve_balance -= monthly_amount
                total_withdrawn += monthly_amount
                payments += 1
                block_remaining -= 1
                if first_payment_month is None:
                    first_payment_month = index + 1
                minimum_reserve_during_active_block = min(
                    minimum_reserve_during_active_block,
                    reserve_balance,
                )
        elif first_payment_month is not None:
            pause_months_after_start += 1

    months_after_start = (
        len(monthly_returns) - first_payment_month + 1
        if first_payment_month is not None
        else 0
    )
    return {
        "reserve_target": reserve_target,
        "income_block_active": block_remaining > 0,
        "guaranteed_future_payments": block_remaining,
        "guaranteed_future_income": block_remaining * monthly_amount,
        "committed_reserve_balance": (
            block_remaining * monthly_amount
        ),
        "uncommitted_reserve_balance": max(
            0.0,
            reserve_balance - block_remaining * monthly_amount,
        ),
        "reserve_funding_progress": min(
            1.0, reserve_balance / reserve_target
        ),
        "next_block_shortfall": max(
            0.0, reserve_target - reserve_balance
        ),
        "first_payment_month": first_payment_month,
        "blocks_started": blocks_started,
        "payments": payments,
        "pause_months_after_start": pause_months_after_start,
        "post_start_payment_coverage": (
            payments / months_after_start if months_after_start else 0.0
        ),
        "no_pause_after_start": (
            first_payment_month is not None
            and pause_months_after_start == 0
        ),
        "total_withdrawn": total_withdrawn,
        "total_transferred_to_reserve": total_transferred,
        "final_trading_balance": trading_balance,
        "final_reserve_balance": reserve_balance,
        "final_total_wealth": trading_balance + reserve_balance,
        "minimum_trading_balance": minimum_trading_balance,
        "minimum_reserve_during_active_block": (
            minimum_reserve_during_active_block
            if blocks_started
            else None
        ),
        "guarantee_breaches": guarantee_breaches,
    }


def _summarize(results):
    funded = [
        value for value in results
        if value["first_payment_month"] is not None
    ]
    first_months = numpy.asarray(
        [value["first_payment_month"] for value in funded],
        dtype=numpy.float64,
    )
    payments = numpy.asarray(
        [value["payments"] for value in results], dtype=numpy.float64
    )
    withdrawals = numpy.asarray(
        [value["total_withdrawn"] for value in results],
        dtype=numpy.float64,
    )
    final_wealth = numpy.asarray(
        [value["final_total_wealth"] for value in results],
        dtype=numpy.float64,
    )
    return {
        "probability_any_prefunded_block": len(funded) / len(results),
        "probability_first_block_within_12_months": float(
            numpy.mean(
                [
                    value["first_payment_month"] is not None
                    and value["first_payment_month"] <= 12
                    for value in results
                ]
            )
        ),
        "probability_first_block_within_24_months": float(
            numpy.mean(
                [
                    value["first_payment_month"] is not None
                    and value["first_payment_month"] <= 24
                    for value in results
                ]
            )
        ),
        "probability_first_block_within_36_months": float(
            numpy.mean(
                [
                    value["first_payment_month"] is not None
                    and value["first_payment_month"] <= 36
                    for value in results
                ]
            )
        ),
        "conditional_probability_no_pause_after_start": (
            float(
                numpy.mean(
                    [value["no_pause_after_start"] for value in funded]
                )
            )
            if funded
            else 0.0
        ),
        "conditional_mean_post_start_coverage": (
            float(
                numpy.mean(
                    [
                        value["post_start_payment_coverage"]
                        for value in funded
                    ]
                )
            )
            if funded
            else 0.0
        ),
        "first_payment_month_percentiles": (
            withdrawal_module._percentiles(first_months)
            if len(first_months)
            else {}
        ),
        "payment_count_percentiles": withdrawal_module._percentiles(
            payments
        ),
        "total_withdrawn_percentiles": withdrawal_module._percentiles(
            withdrawals
        ),
        "final_total_wealth_percentiles": withdrawal_module._percentiles(
            final_wealth
        ),
        "guarantee_breaches": sum(
            value["guarantee_breaches"] for value in results
        ),
    }
