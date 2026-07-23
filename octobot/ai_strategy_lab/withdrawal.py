"""Fixed-cash withdrawal robustness analysis for trend research reports."""

from __future__ import annotations

import json
import pathlib
import typing

import numpy


WITHDRAWAL_SCHEMA_VERSION = 2
DEFAULT_HAIRCUTS = (0.0, 0.05, 0.10)


def evaluate_withdrawals(
    trend_report_paths: typing.Iterable[typing.Union[str, pathlib.Path]],
    strategy_name: str,
    *,
    initial_capital: float = 10_000.0,
    monthly_amounts: typing.Iterable[float] = (50.0, 100.0, 150.0, 200.0),
    warmup_months: int = 12,
    horizon_months: int = 60,
    block_months: int = 6,
    simulations: int = 5_000,
    safety_floor_fraction: float = 0.80,
    annual_return_haircuts: typing.Iterable[float] = DEFAULT_HAIRCUTS,
    random_seed: int = 20_260_723,
) -> dict:
    """Evaluate guarded fixed withdrawals without implying a guaranteed yield."""
    if not strategy_name:
        raise ValueError("strategy name is required")
    if initial_capital <= 0:
        raise ValueError("initial capital must be positive")
    amounts = tuple(float(value) for value in monthly_amounts)
    if not amounts or any(value <= 0 for value in amounts):
        raise ValueError("monthly amounts must be positive")
    haircuts = tuple(float(value) for value in annual_return_haircuts)
    if not haircuts or any(value < 0 or value >= 1 for value in haircuts):
        raise ValueError("annual return haircuts must be in [0, 1)")
    if warmup_months < 0 or horizon_months < 12:
        raise ValueError("invalid warmup or horizon")
    if block_months < 1 or simulations < 100:
        raise ValueError("invalid bootstrap configuration")
    if not 0 < safety_floor_fraction <= 1:
        raise ValueError("safety floor fraction must be in (0, 1]")

    monthly_returns, sources = _load_monthly_returns(
        trend_report_paths, strategy_name
    )
    segment_lengths = _bootstrap_segment_lengths(
        sources, len(monthly_returns)
    )
    if len(monthly_returns) < max(24, block_months * 2):
        raise ValueError("at least 24 non-overlapping months are required")
    values = numpy.asarray(
        [value for _, value in monthly_returns], dtype=numpy.float64
    )
    if numpy.any(values <= -1) or not numpy.all(numpy.isfinite(values)):
        raise ValueError("monthly returns contain invalid values")

    results = {}
    for haircut in haircuts:
        monthly_haircut = (1.0 + haircut) ** (1.0 / 12.0) - 1.0
        adjusted = values - monthly_haircut
        rng = numpy.random.default_rng(random_seed)
        paths = _moving_block_paths(
            adjusted,
            horizon_months=horizon_months,
            block_months=block_months,
            simulations=simulations,
            rng=rng,
            segment_lengths=segment_lengths,
        )
        historical_segments = _split_values_by_source(
            values - monthly_haircut, sources
        )
        by_amount = {}
        for amount in amounts:
            historical_by_source = [
                {
                    "source": source,
                    "result": _simulate_guarded_withdrawal(
                        segment,
                        initial_capital=initial_capital,
                        monthly_amount=amount,
                        warmup_months=warmup_months,
                        safety_floor_fraction=safety_floor_fraction,
                    ),
                }
                for source, segment in zip(sources, historical_segments)
            ]
            bootstrapped = [
                _simulate_guarded_withdrawal(
                    path,
                    initial_capital=initial_capital,
                    monthly_amount=amount,
                    warmup_months=warmup_months,
                    safety_floor_fraction=safety_floor_fraction,
                )
                for path in paths
            ]
            by_amount[f"{amount:g}"] = {
                "historical_sequences_by_source": historical_by_source,
                "bootstrap": _summarize_simulations(bootstrapped),
            }
        results[f"{haircut:.2%}"] = {
            "annual_return_haircut": haircut,
            "monthly_additive_haircut": monthly_haircut,
            "amounts": by_amount,
        }

    return {
        "schema_version": WITHDRAWAL_SCHEMA_VERSION,
        "research_only": True,
        "warning": (
            "Simulation, not a guaranteed payment. The guard can skip a "
            "withdrawal when capital is below its safety threshold."
        ),
        "strategy_name": strategy_name,
        "initial_capital": initial_capital,
        "monthly_amounts": list(amounts),
        "warmup_months": warmup_months,
        "horizon_months": horizon_months,
        "block_months": block_months,
        "simulations": simulations,
        "safety_floor_fraction": safety_floor_fraction,
        "random_seed": random_seed,
        "historical_months": len(monthly_returns),
        "historical_start_month": monthly_returns[0][0],
        "historical_end_month": monthly_returns[-1][0],
        "sources": sources,
        "bootstrap_segments": _bootstrap_metadata(
            sources, segment_lengths
        ),
        "scenarios": results,
    }


def _load_monthly_returns(paths, strategy_name):
    seen_periods = set()
    segments = []
    resolved_paths = [pathlib.Path(value).resolve() for value in paths]
    if not resolved_paths:
        raise ValueError("at least one trend report is required")
    for path in resolved_paths:
        data = json.loads(path.read_text(encoding="utf-8"))
        try:
            report = data["reports"][strategy_name]
            monthly = report["monthly_returns"]
        except KeyError as error:
            raise ValueError(
                f"{path} does not contain strategy {strategy_name}"
            ) from error
        if not isinstance(monthly, dict) or not monthly:
            raise ValueError(f"{path} contains no monthly returns")
        normalized = []
        for period, value in monthly.items():
            ordinal = _month_ordinal(period)
            normalized.append((ordinal, period, float(value)))
        normalized.sort()
        for previous, current in zip(normalized, normalized[1:]):
            if current[0] != previous[0] + 1:
                raise ValueError(
                    f"{path} contains a gap between "
                    f"{previous[1]} and {current[1]}"
                )
        periods = {period for _, period, _ in normalized}
        overlaps = seen_periods & periods
        if overlaps:
            raise ValueError(
                f"trend reports contain overlapping months: {sorted(overlaps)}"
            )
        seen_periods.update(periods)
        source = {
                "path": str(path),
                "evaluation_start_date": report["evaluation_start_date"],
                "evaluation_end_date": report["evaluation_end_date"],
                "months": len(normalized),
                "first_month": normalized[0][1],
                "last_month": normalized[-1][1],
            }
        segments.append(
            (
                normalized[0][0],
                source,
                [(period, value) for _, period, value in normalized],
            )
        )
    segments.sort(key=lambda value: value[0])
    sources = [source for _, source, _ in segments]
    merged = [
        monthly_return
        for _, _, segment in segments
        for monthly_return in segment
    ]
    return merged, sources


def _month_ordinal(period):
    if (
        not isinstance(period, str)
        or len(period) != 7
        or period[4] != "-"
        or not period[:4].isdigit()
        or not period[5:].isdigit()
    ):
        raise ValueError(f"invalid monthly period: {period}")
    year = int(period[:4])
    month = int(period[5:])
    if year < 1 or not 1 <= month <= 12:
        raise ValueError(f"invalid monthly period: {period}")
    return year * 12 + month - 1


def _bootstrap_segment_lengths(sources, total_months):
    """Return source segment lengths, with compatibility for mocked loaders."""
    if total_months < 1:
        raise ValueError("monthly returns are empty")
    if not sources or any("months" not in source for source in sources):
        return (total_months,)
    lengths = tuple(int(source["months"]) for source in sources)
    if any(length < 1 for length in lengths) or sum(lengths) != total_months:
        raise ValueError("source segment lengths do not match monthly returns")
    return lengths


def _split_values_by_source(values, sources):
    lengths = _bootstrap_segment_lengths(sources, len(values))
    output = []
    offset = 0
    for length in lengths:
        output.append(values[offset:offset + length])
        offset += length
    return output


def _bootstrap_metadata(sources, segment_lengths):
    return {
        "method": "source_segment_aware_circular_moving_block",
        "segment_lengths_months": list(segment_lengths),
        "cross_source_blocks_allowed": False,
        "circular_wrap_within_source": True,
        "start_probability": "equal_per_observed_month",
        "segments": [
            {
                "path": source.get("path"),
                "first_month": source.get("first_month"),
                "last_month": source.get("last_month"),
                "months": source.get("months"),
            }
            for source in sources
        ],
    }


def _moving_block_paths(
    values,
    *,
    horizon_months,
    block_months,
    simulations,
    rng,
    segment_lengths=None,
):
    values = numpy.asarray(values, dtype=numpy.float64)
    if values.ndim != 1 or not len(values):
        raise ValueError("bootstrap values must be a non-empty vector")
    if segment_lengths is None:
        segment_lengths = (len(values),)
    segment_lengths = tuple(int(length) for length in segment_lengths)
    if (
        any(length < 1 for length in segment_lengths)
        or sum(segment_lengths) != len(values)
    ):
        raise ValueError("invalid bootstrap segment lengths")
    offsets = numpy.cumsum((0,) + segment_lengths)
    result = numpy.empty(
        (simulations, horizon_months), dtype=numpy.float64
    )
    for simulation in range(simulations):
        output = []
        while len(output) < horizon_months:
            start = int(rng.integers(0, len(values)))
            segment_index = int(
                numpy.searchsorted(offsets[1:], start, side="right")
            )
            segment_start = int(offsets[segment_index])
            segment_length = segment_lengths[segment_index]
            local_start = start - segment_start
            output.extend(
                values[
                    segment_start
                    + (local_start + offset) % segment_length
                ]
                for offset in range(block_months)
            )
        result[simulation] = output[:horizon_months]
    return result


def _simulate_guarded_withdrawal(
    monthly_returns,
    *,
    initial_capital,
    monthly_amount,
    warmup_months,
    safety_floor_fraction,
):
    balance = float(initial_capital)
    floor = initial_capital * safety_floor_fraction
    minimum_balance = balance
    scheduled = 0
    paid = 0
    total_withdrawn = 0.0
    for index, monthly_return in enumerate(monthly_returns):
        balance *= 1.0 + float(monthly_return)
        minimum_balance = min(minimum_balance, balance)
        if index >= warmup_months:
            scheduled += 1
            if balance - monthly_amount >= floor:
                balance -= monthly_amount
                paid += 1
                total_withdrawn += monthly_amount
                minimum_balance = min(minimum_balance, balance)
    return {
        "scheduled_payments": scheduled,
        "paid_payments": paid,
        "skipped_payments": scheduled - paid,
        "payment_coverage": paid / scheduled if scheduled else 1.0,
        "all_payments_made": paid == scheduled,
        "total_withdrawn": total_withdrawn,
        "final_balance": balance,
        "minimum_balance": minimum_balance,
        "market_breached_safety_floor": minimum_balance < floor,
        "final_at_or_above_initial": balance >= initial_capital,
    }


def _summarize_simulations(results):
    final_balances = numpy.asarray(
        [value["final_balance"] for value in results], dtype=numpy.float64
    )
    withdrawals = numpy.asarray(
        [value["total_withdrawn"] for value in results],
        dtype=numpy.float64,
    )
    coverage = numpy.asarray(
        [value["payment_coverage"] for value in results],
        dtype=numpy.float64,
    )
    return {
        "probability_all_payments_made": float(
            numpy.mean([value["all_payments_made"] for value in results])
        ),
        "mean_payment_coverage": float(numpy.mean(coverage)),
        "probability_market_never_breaches_floor": float(
            numpy.mean(
                [
                    not value["market_breached_safety_floor"]
                    for value in results
                ]
            )
        ),
        "probability_final_at_or_above_initial": float(
            numpy.mean(
                [value["final_at_or_above_initial"] for value in results]
            )
        ),
        "final_balance_percentiles": _percentiles(final_balances),
        "total_withdrawn_percentiles": _percentiles(withdrawals),
        "payment_coverage_percentiles": _percentiles(coverage),
    }


def _percentiles(values):
    return {
        f"p{percentile:02d}": float(numpy.percentile(values, percentile))
        for percentile in (5, 25, 50, 75, 95)
    }
