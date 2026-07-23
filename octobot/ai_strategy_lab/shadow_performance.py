"""Forward-only performance and promotion gates for the trend shadow."""

from __future__ import annotations

import datetime
import math
import pathlib
import typing

import numpy

from octobot.ai_strategy_lab import shadow as shadow_module
from octobot.ai_strategy_lab import prefunded_income as prefunded_income_module
from octobot.ai_strategy_lab import trend as trend_module
from octobot.ai_strategy_lab import withdrawal as withdrawal_module


PERFORMANCE_SCHEMA_VERSION = 1


def evaluate_shadow_performance(
    journal_path: typing.Union[str, pathlib.Path],
    *,
    initial_capital: float = 10_000.0,
    fixed_monthly_amount: float = 25.0,
    expected_strategy_name: typing.Optional[str] = None,
) -> dict:
    if initial_capital <= 0 or fixed_monthly_amount <= 0:
        raise ValueError("capital and fixed monthly amount must be positive")
    records = shadow_module.load_shadow_records(journal_path)
    strategy_name = _validate_strategy_identity(
        records, expected_strategy_name
    )
    usable = [
        value
        for value in records
        if value.get("latest_close")
        and value.get("latest_daily_funding") is not None
        and (
            value.get("cost_per_turnover") is not None
            or value.get("cost_per_turnover_by_instrument") is not None
        )
    ]
    usable.sort(key=lambda value: value["market_end_date"])
    dates = [
        datetime.date.fromisoformat(value["market_end_date"])
        for value in usable
    ]
    if len(dates) != len(set(dates)):
        raise ValueError("shadow journal contains duplicate market dates")

    daily_dates = []
    daily_returns = []
    equities = []
    equity = 1.0
    gap_days = 0
    skipped_intervals = 0
    total_turnover = 0.0
    total_cost_return = 0.0
    total_funding_return = 0.0
    if usable:
        opening_turnover = sum(
            abs(float(value)) for value in usable[0]["target_weights"].values()
        )
        opening_cost = _turnover_cost(
            usable[0],
            {
                symbol: abs(
                    float(usable[0]["target_weights"][symbol])
                )
                for symbol in usable[0]["target_weights"]
            },
        )
        equity *= 1.0 - opening_cost
        daily_dates.append(dates[0])
        daily_returns.append(-opening_cost)
        equities.append(equity)
        total_turnover += opening_turnover
        total_cost_return += opening_cost

    for previous, current, previous_date, current_date in zip(
        usable, usable[1:], dates, dates[1:]
    ):
        elapsed_days = (current_date - previous_date).days
        if elapsed_days != 1:
            if elapsed_days > 1:
                gap_days += elapsed_days - 1
            skipped_intervals += 1
            continue
        symbols = set(previous["target_weights"])
        if (
            symbols != set(current["target_weights"])
            or symbols != set(previous["latest_close"])
            or symbols != set(current["latest_close"])
            or symbols != set(current["latest_daily_funding"])
        ):
            raise ValueError("shadow record symbol universes are inconsistent")
        market_return = 0.0
        funding_return = 0.0
        for symbol in symbols:
            previous_close = float(previous["latest_close"][symbol])
            current_close = float(current["latest_close"][symbol])
            if (
                previous_close <= 0
                or current_close <= 0
                or not math.isfinite(previous_close)
                or not math.isfinite(current_close)
            ):
                raise ValueError("shadow closes must be positive and finite")
            weight = float(previous["target_weights"][symbol])
            market_return += weight * (
                current_close / previous_close - 1.0
            )
            funding_return -= weight * float(
                current["latest_daily_funding"][symbol]
            )
        turnover = sum(
            abs(
                float(current["target_weights"][symbol])
                - float(previous["target_weights"][symbol])
            )
            for symbol in symbols
        )
        turnover_by_symbol = {
            symbol: abs(
                float(current["target_weights"][symbol])
                - float(previous["target_weights"][symbol])
            )
            for symbol in symbols
        }
        cost = _turnover_cost(current, turnover_by_symbol)
        gross_return = market_return + funding_return
        net_return = (1.0 + gross_return) * (1.0 - cost) - 1.0
        equity *= 1.0 + net_return
        daily_dates.append(current_date)
        daily_returns.append(net_return)
        equities.append(equity)
        total_turnover += turnover
        total_cost_return += cost
        total_funding_return += funding_return

    metrics = _metrics(
        daily_dates,
        daily_returns,
        equities,
        initial_capital=initial_capital,
        fixed_monthly_amount=fixed_monthly_amount,
    )
    span_days = (dates[-1] - dates[0]).days + 1 if dates else 0
    paper_checks = {
        "at_least_330_observed_days": len(daily_returns) >= 330,
        "at_least_365_calendar_days": span_days >= 365,
        "at_least_12_calendar_months": metrics["calendar_months"] >= 12,
        "no_missing_forward_days": gap_days == 0,
        "annualized_return_at_least_8pct": (
            metrics["annualized_return"] >= 0.08
        ),
        "max_drawdown_at_most_15pct": metrics["max_drawdown"] <= 0.15,
        "positive_month_ratio_at_least_60pct": (
            metrics["positive_month_ratio"] >= 0.60
        ),
    }
    income_checks = {
        **paper_checks,
        "at_least_700_observed_days": len(daily_returns) >= 700,
        "at_least_24_calendar_months": metrics["calendar_months"] >= 24,
        "all_guarded_fixed_payments_made": metrics[
            "guarded_fixed_withdrawal"
        ]["all_payments_made"],
        "capital_after_payments_at_or_above_initial": metrics[
            "guarded_fixed_withdrawal"
        ]["final_at_or_above_initial"],
        "prefunded_guarantee_breaches_zero": metrics[
            "prefunded_income_24_month_block"
        ]["guarantee_breaches"] == 0,
    }
    return {
        "schema_version": PERFORMANCE_SCHEMA_VERSION,
        "mode": "shadow_only",
        "orders_authorized": False,
        "warning": (
            "Forward observations can support a manual paper review; they "
            "cannot guarantee future income or authorize orders."
        ),
        "journal_path": str(pathlib.Path(journal_path).resolve()),
        "strategy_name": strategy_name,
        "records": len(records),
        "usable_records": len(usable),
        "observed_return_days": len(daily_returns),
        "calendar_span_days": span_days,
        "missing_forward_days": gap_days,
        "skipped_intervals": skipped_intervals,
        "total_turnover": total_turnover,
        "total_cost_return": total_cost_return,
        "total_funding_return": total_funding_return,
        "metrics": metrics,
        "paper_review_gate": {
            "passed": all(paper_checks.values()),
            "checks": paper_checks,
        },
        "income_evidence_gate": {
            "passed": all(income_checks.values()),
            "fixed_monthly_amount": fixed_monthly_amount,
            "checks": income_checks,
        },
        "prefunded_income_readiness": _prefunded_readiness(
            metrics["prefunded_income_24_month_block"],
            monthly_amount=fixed_monthly_amount,
            block_months=24,
        ),
        "automatic_promotion": False,
    }


def _validate_strategy_identity(records, expected_strategy_name):
    names = {
        value.get("strategy_name")
        for value in records
        if value.get("strategy_name") is not None
    }
    missing = sum(
        value.get("strategy_name") is None for value in records
    )
    if expected_strategy_name is not None:
        if not expected_strategy_name:
            raise ValueError("expected strategy name cannot be empty")
        if missing or names != {expected_strategy_name}:
            raise ValueError(
                "shadow journal strategy does not match expected strategy"
            )
        return expected_strategy_name
    if len(names) > 1 or (names and missing):
        raise ValueError("shadow journal contains mixed strategy identities")
    return next(iter(names), None)


def _turnover_cost(record, turnover_by_symbol):
    cost_map = record.get("cost_per_turnover_by_instrument")
    if cost_map is not None:
        if set(cost_map) != set(turnover_by_symbol):
            raise ValueError(
                "shadow turnover cost universe is inconsistent"
            )
        costs = {
            symbol: float(value) for symbol, value in cost_map.items()
        }
    else:
        flat_cost = float(record["cost_per_turnover"])
        costs = {
            symbol: flat_cost for symbol in turnover_by_symbol
        }
    if any(
        value < 0 or not math.isfinite(value)
        for value in costs.values()
    ):
        raise ValueError("shadow turnover costs must be finite and nonnegative")
    return sum(
        float(turnover_by_symbol[symbol]) * costs[symbol]
        for symbol in turnover_by_symbol
    )


def _metrics(
    dates,
    daily_returns,
    equities,
    *,
    initial_capital,
    fixed_monthly_amount,
):
    if not equities:
        monthly_returns = {}
        month_to_date_returns = {}
        excluded_incomplete_months = []
        annualized_return = 0.0
        max_drawdown = 0.0
        annualized_volatility = 0.0
        sharpe = 0.0
    else:
        equity_values = numpy.asarray(equities, dtype=numpy.float64)
        peaks = numpy.maximum.accumulate(
            numpy.concatenate((numpy.ones(1), equity_values))
        )[1:]
        max_drawdown = float(
            numpy.max(1.0 - equity_values / peaks)
        )
        return_values = numpy.asarray(
            daily_returns, dtype=numpy.float64
        )
        annualized_volatility = float(
            numpy.std(return_values) * numpy.sqrt(365.0)
        )
        sharpe = (
            float(
                numpy.mean(return_values)
                / numpy.std(return_values)
                * numpy.sqrt(365.0)
            )
            if numpy.std(return_values) > 0
            else 0.0
        )
        elapsed_years = (
            (dates[-1] - dates[0]).days / 365.25
            if len(dates) > 1
            else 0.0
        )
        annualized_return = (
            equity_values[-1] ** (1.0 / elapsed_years) - 1.0
            if elapsed_years > 0 and equity_values[-1] > 0
            else 0.0
        )
        month_to_date_returns = trend_module._period_returns(
            dates, equity_values, "%Y-%m"
        )
        monthly_returns, excluded_incomplete_months = (
            _complete_month_returns(
                dates,
                month_to_date_returns,
            )
        )
    guarded = withdrawal_module._simulate_guarded_withdrawal(
        list(monthly_returns.values()),
        initial_capital=initial_capital,
        monthly_amount=fixed_monthly_amount,
        warmup_months=12,
        safety_floor_fraction=0.80,
    )
    prefunded = prefunded_income_module.simulate_prefunded_income(
        list(monthly_returns.values()),
        initial_capital=initial_capital,
        monthly_amount=fixed_monthly_amount,
        block_months=24,
    )
    return {
        "total_return": equities[-1] - 1.0 if equities else 0.0,
        "annualized_return": annualized_return,
        "max_drawdown": max_drawdown,
        "annualized_volatility": annualized_volatility,
        "sharpe_zero_rate": sharpe,
        "calendar_months": len(monthly_returns),
        "positive_months": sum(
            value > 0 for value in monthly_returns.values()
        ),
        "positive_month_ratio": (
            sum(value > 0 for value in monthly_returns.values())
            / len(monthly_returns)
            if monthly_returns
            else 0.0
        ),
        "monthly_returns": monthly_returns,
        "month_to_date_returns": month_to_date_returns,
        "excluded_incomplete_months": excluded_incomplete_months,
        "guarded_fixed_withdrawal": guarded,
        "prefunded_income_24_month_block": prefunded,
    }


def _complete_month_returns(dates, month_to_date_returns):
    dates_by_month = {}
    for date in dates:
        dates_by_month.setdefault(date.strftime("%Y-%m"), []).append(date)
    complete = {}
    excluded = []
    for month, monthly_return in month_to_date_returns.items():
        month_dates = dates_by_month.get(month, [])
        consecutive = all(
            current - previous == datetime.timedelta(days=1)
            for previous, current in zip(month_dates, month_dates[1:])
        )
        covers_full_month = bool(month_dates) and (
            month_dates[0].day == 1
            and (
                month_dates[-1] + datetime.timedelta(days=1)
            ).month
            != month_dates[-1].month
            and consecutive
        )
        if covers_full_month:
            complete[month] = monthly_return
        else:
            excluded.append(month)
    return complete, excluded


def _prefunded_readiness(result, *, monthly_amount, block_months):
    active = bool(result["income_block_active"])
    return {
        "status": (
            "finite_block_fully_prefunded"
            if active
            else "accumulating_uncommitted_reserve"
        ),
        "monthly_amount": monthly_amount,
        "block_months": block_months,
        "reserve_target": monthly_amount * block_months,
        "reserve_balance": result["final_reserve_balance"],
        "reserve_funding_progress": result["reserve_funding_progress"],
        "next_block_shortfall": result["next_block_shortfall"],
        "guaranteed_future_payments": result[
            "guaranteed_future_payments"
        ],
        "guaranteed_future_income": result[
            "guaranteed_future_income"
        ],
        "guarantee_breaches": result["guarantee_breaches"],
        "finite_block_guaranteed": (
            active and result["guarantee_breaches"] == 0
        ),
        "real_payments_authorized": False,
        "warning": (
            "Only already segregated simulated cash backs the finite block; "
            "future blocks and real payments are not guaranteed or authorized."
        ),
    }
