import datetime

import numpy
import pytest

from octobot.ai_strategy_lab import (
    diversified_trend_cointegration_v1_research as research,
)


def _component_reports(trend_daily, cointegration_daily, start="2024-01-01"):
    first = datetime.date.fromisoformat(start)
    dates = [
        (first + datetime.timedelta(days=index)).isoformat()
        for index in range(len(trend_daily))
    ]
    trend_daily = numpy.asarray(trend_daily, dtype=numpy.float64)
    cointegration_daily = numpy.asarray(
        cointegration_daily, dtype=numpy.float64
    )
    return (
        {
            "_daily_return": trend_daily,
            "trajectory": {
                "dates": list(dates),
                "equity": numpy.cumprod(1.0 + trend_daily).tolist(),
            },
        },
        {
            "_trajectory": {
                "dates": list(dates),
                "daily_return": cointegration_daily.tolist(),
            }
        },
    )


def test_fixed_initial_budgets_compound_independently_without_rebalancing():
    trend, cointegration = _component_reports(
        [0.10, -0.05, 0.02], [-0.02, 0.04, 0.01]
    )

    result = research.combine_trajectories(
        trend, cointegration, 0.65, 0.35, include_trajectory=True
    )

    trend_equity = numpy.cumprod(1.0 + numpy.asarray([0.10, -0.05, 0.02]))
    cointegration_equity = numpy.cumprod(
        1.0 + numpy.asarray([-0.02, 0.04, 0.01])
    )
    expected_equity = 0.65 * trend_equity + 0.35 * cointegration_equity
    expected_daily = numpy.diff(
        numpy.concatenate((numpy.ones(1), expected_equity))
    ) / numpy.concatenate((numpy.ones(1), expected_equity))[:-1]
    assert result["_trajectory"]["combined_daily_return"] == pytest.approx(
        expected_daily
    )
    assert result["total_return"] == pytest.approx(
        expected_equity[-1] - 1.0
    )
    assert result["trend_additive_contribution"] == pytest.approx(
        0.65 * (trend_equity[-1] - 1.0)
    )
    assert result["cointegration_additive_contribution"] == pytest.approx(
        0.35 * (cointegration_equity[-1] - 1.0)
    )


def test_combination_rejects_date_mismatch_and_invalid_allocation():
    trend, cointegration = _component_reports([0.01, 0.02], [0.0, 0.01])
    cointegration["_trajectory"]["dates"][1] = "2024-01-03"

    with pytest.raises(research.DataQualityError, match="dates differ"):
        research.combine_trajectories(trend, cointegration, 0.8, 0.2)
    with pytest.raises(ValueError, match="allocation"):
        research.combine_trajectories(trend, cointegration, 1.0, 0.0)


def _eligible_stress():
    return {
        "days": 1277,
        "total_return": 0.30,
        "annualized_return": 0.08,
        "sharpe_zero_rate": 1.0,
        "maximum_drawdown": 0.10,
        "positive_month_ratio": 0.60,
        "trend_additive_contribution": 0.20,
        "cointegration_additive_contribution": 0.10,
    }


def _eligible_folds(worst=0.01, median_sharpe=1.0):
    return [
        {
            "total_return": worst if index == 0 else 0.02,
            "sharpe_zero_rate": median_sharpe,
        }
        for index in range(7)
    ]


def test_candidate_eligibility_uses_all_frozen_checks():
    value = research.candidate_eligibility(
        _eligible_stress(), _eligible_folds()
    )

    assert value["passed"] is True
    assert all(type(item) is bool for item in value["checks"].values())

    changed = _eligible_stress()
    changed["cointegration_additive_contribution"] = -0.001
    rejected = research.candidate_eligibility(changed, _eligible_folds())
    assert rejected["passed"] is False
    assert not rejected["checks"][
        "both_sleeve_additive_contributions_positive"
    ]


def test_selection_uses_worst_fold_before_other_metrics():
    candidates = []
    for identifier, worst, median, sharpe, drawdown in (
        ("a", -0.02, 2.0, 2.0, 0.05),
        ("b", -0.01, 1.0, 1.0, 0.10),
    ):
        candidates.append(
            {
                "configuration_id": identifier,
                "stress": {
                    "sharpe_zero_rate": sharpe,
                    "maximum_drawdown": drawdown,
                },
                "eligibility": {
                    "passed": True,
                    "worst_stress_fold_return": worst,
                    "median_stress_fold_sharpe": median,
                },
            }
        )

    assert research.select_candidate(candidates)["configuration_id"] == "b"
    for value in candidates:
        value["eligibility"]["passed"] = False
    assert research.select_candidate(candidates) is None


def test_interval_indices_accept_exclusive_day_after_market_end():
    dates = [
        datetime.date(2024, 1, 1) + datetime.timedelta(days=index)
        for index in range(3)
    ]

    assert research._interval_indices(
        dates, datetime.date(2024, 1, 1), datetime.date(2024, 1, 4)
    ) == (0, 3)
