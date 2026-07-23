"""Multi-horizon bootstrap evidence audit for a fixed strategy."""

from __future__ import annotations

import pathlib
import typing

import numpy

from octobot.ai_strategy_lab import withdrawal as withdrawal_module


EVIDENCE_SCHEMA_VERSION = 2
DEFAULT_HORIZONS = (12, 36, 60, 120)
DEFAULT_HAIRCUTS = (0.0, 0.05, 0.10)
GATE_PROBABILITIES = {
    12: 0.60,
    36: 0.75,
    60: 0.85,
    120: 0.90,
}


def evaluate_strategy_evidence(
    trend_report_paths: typing.Iterable[
        typing.Union[str, pathlib.Path]
    ],
    strategy_name: str,
    *,
    initial_capital: float = 10_000.0,
    horizons: typing.Iterable[int] = DEFAULT_HORIZONS,
    block_months: int = 6,
    simulations: int = 10_000,
    annual_return_haircuts: typing.Iterable[float] = DEFAULT_HAIRCUTS,
    random_seed: int = 20_260_723,
) -> dict:
    if initial_capital <= 0:
        raise ValueError("initial capital must be positive")
    horizon_values = tuple(sorted(set(int(value) for value in horizons)))
    if not horizon_values or any(
        value < 12 or value % 12 for value in horizon_values
    ):
        raise ValueError("horizons must be positive whole years")
    if block_months < 1 or simulations < 100:
        raise ValueError("invalid bootstrap configuration")
    haircuts = tuple(float(value) for value in annual_return_haircuts)
    if not haircuts or any(value < 0 or value >= 1 for value in haircuts):
        raise ValueError("annual return haircuts must be in [0, 1)")
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
    for haircut_index, haircut in enumerate(haircuts):
        monthly_haircut = (1.0 + haircut) ** (1.0 / 12.0) - 1.0
        adjusted = values - monthly_haircut
        horizon_reports = {}
        for horizon in horizon_values:
            paths = withdrawal_module._moving_block_paths(
                adjusted,
                horizon_months=horizon,
                block_months=block_months,
                simulations=simulations,
                rng=numpy.random.default_rng(
                    random_seed + haircut_index * 10_000 + horizon
                ),
                segment_lengths=segment_lengths,
            )
            horizon_reports[str(horizon)] = _summarize_paths(
                paths,
                initial_capital=initial_capital,
            )
        scenarios[f"{haircut:.2%}"] = {
            "annual_return_haircut": haircut,
            "monthly_additive_haircut": monthly_haircut,
            "horizons": horizon_reports,
        }

    gate_scenario = scenarios.get("5.00%")
    gate_checks = {}
    if gate_scenario is None:
        gate_checks["five_percent_haircut_present"] = False
    else:
        gate_checks["five_percent_haircut_present"] = True
        for horizon, required in GATE_PROBABILITIES.items():
            report = gate_scenario["horizons"].get(str(horizon))
            gate_checks[
                f"probability_non_loss_{horizon}_months_at_least_"
                f"{required:.0%}"
            ] = (
                report is not None
                and report["probability_final_at_or_above_initial"]
                >= required
            )
        decade = gate_scenario["horizons"].get("120")
        gate_checks["median_decade_cagr_at_least_5pct"] = (
            decade is not None
            and decade["annualized_return_percentiles"]["p50"] >= 0.05
        )
        gate_checks["p90_decade_max_drawdown_at_most_30pct"] = (
            decade is not None
            and decade["max_drawdown_percentiles"]["p90"] <= 0.30
        )
    return {
        "schema_version": EVIDENCE_SCHEMA_VERSION,
        "research_only": True,
        "strategy_name": strategy_name,
        "initial_capital": initial_capital,
        "historical_months": len(monthly_returns),
        "historical_start_month": monthly_returns[0][0],
        "historical_end_month": monthly_returns[-1][0],
        "horizons_months": list(horizon_values),
        "bootstrap_block_months": block_months,
        "simulations": simulations,
        "random_seed": random_seed,
        "sources": sources,
        "bootstrap_segments": withdrawal_module._bootstrap_metadata(
            sources, segment_lengths
        ),
        "scenarios": scenarios,
        "winning_edge_evidence_gate": {
            "passed": bool(gate_checks) and all(gate_checks.values()),
            "interpretation": (
                "Bootstrap evidence for a positive edge under the observed "
                "sample; not a guarantee of profit or monthly income."
            ),
            "checks": gate_checks,
        },
        "automatic_promotion": False,
        "real_withdrawals_authorized": False,
    }


def _summarize_paths(paths, *, initial_capital):
    equity = numpy.cumprod(1.0 + paths, axis=1)
    peaks = numpy.maximum.accumulate(
        numpy.concatenate(
            (
                numpy.ones((len(paths), 1), dtype=numpy.float64),
                equity,
            ),
            axis=1,
        ),
        axis=1,
    )[:, 1:]
    drawdowns = 1.0 - equity / peaks
    maximum_drawdowns = numpy.max(drawdowns, axis=1)
    final_multiples = equity[:, -1]
    horizon_months = paths.shape[1]
    annualized_returns = (
        numpy.power(final_multiples, 12.0 / horizon_months) - 1.0
    )
    annual_blocks = paths.reshape(len(paths), horizon_months // 12, 12)
    annual_returns = numpy.prod(1.0 + annual_blocks, axis=2) - 1.0
    positive_year_ratios = numpy.mean(annual_returns > 0, axis=1)
    final_capital = initial_capital * final_multiples
    return {
        "horizon_months": horizon_months,
        "probability_final_at_or_above_initial": float(
            numpy.mean(final_capital >= initial_capital)
        ),
        "probability_every_year_positive": float(
            numpy.mean(numpy.all(annual_returns > 0, axis=1))
        ),
        "final_capital_percentiles": _percentiles(final_capital),
        "annualized_return_percentiles": _percentiles(
            annualized_returns
        ),
        "max_drawdown_percentiles": _percentiles(maximum_drawdowns),
        "positive_year_ratio_percentiles": _percentiles(
            positive_year_ratios
        ),
    }


def _percentiles(values):
    return {
        f"p{percentile:02d}": float(numpy.percentile(values, percentile))
        for percentile in (5, 10, 25, 50, 75, 90, 95)
    }
