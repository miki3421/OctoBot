import dataclasses
import datetime

import pytest

from octobot.ai_strategy_lab import carry_overlay


def _trajectory(days, gross):
    start = datetime.date(2024, 1, 1)
    return {
        "dates": [
            str(start + datetime.timedelta(days=index))
            for index in range(days)
        ],
        "equity": [1.0] * days,
        "gross_exposure": [gross] * days,
    }


def _carry_points(days, daily_return):
    start = datetime.datetime(
        2024, 1, 1, tzinfo=datetime.timezone.utc
    )
    return [
        (
            int((start + datetime.timedelta(days=index)).timestamp()),
            (1.0 + daily_return) ** index,
        )
        for index in range(days)
    ]


def _zero_cost_config():
    return dataclasses.replace(
        carry_overlay._stressed_carry_config(1),
        spot_fee_per_fill=0,
        futures_fee_per_fill=0,
        slippage_per_fill=0,
    )


def test_overlay_uses_only_idle_gross_capacity():
    result = carry_overlay._combine_paths(
        _trajectory(400, 0.90),
        _carry_points(400, 0.001),
        initial_capital=10_000,
        max_overlay_fraction=0.20,
        carry_config=_zero_cost_config(),
    )

    assert result["maximum_overlay_allocation"] == pytest.approx(0.10)
    assert result["maximum_conservative_gross_exposure"] <= 1.0


def test_overlay_return_is_additive_without_replacing_trend():
    result = carry_overlay._combine_paths(
        _trajectory(10, 0.50),
        _carry_points(10, 0.01),
        initial_capital=10_000,
        max_overlay_fraction=0.20,
        carry_config=_zero_cost_config(),
    )

    assert result["total_return"] == pytest.approx((1.002**9) - 1)
    assert result["maximum_overlay_allocation"] == pytest.approx(0.20)


def test_fully_allocated_trend_disables_overlay():
    result = carry_overlay._combine_paths(
        _trajectory(30, 1.0),
        _carry_points(30, 0.01),
        initial_capital=10_000,
        max_overlay_fraction=0.20,
        carry_config=_zero_cost_config(),
    )

    assert result["total_return"] == pytest.approx(0)
    assert result["maximum_overlay_allocation"] == 0
    assert result["overlay_additive_return_contribution"] == 0


def test_v14_uses_fixed_v13_risk_budget():
    config = carry_overlay._stressed_trend_config(
        3,
        config_name=carry_overlay.RISK_BUDGETED_TREND_CONFIG_NAME,
    )

    assert config.name == "risk_budgeted_bear_regime_v13_cost_stress_3x"
    assert config.target_annual_volatility == pytest.approx(0.135)
    assert config.maximum_gross_exposure == pytest.approx(0.90)
    assert config.maximum_asset_exposure == pytest.approx(0.315)
    assert config.fee_per_turnover == pytest.approx(0.0018)
    assert config.slippage_per_turnover == pytest.approx(0.0006)


def test_v14_r1_name_requires_exact_preregistered_stress():
    assert carry_overlay._risk_budgeted_overlay_name(
        5.0, 0.5, 1
    ) == "risk_budgeted_idle_carry_overlay_v14_r1_half_funding"
    assert carry_overlay._risk_budgeted_overlay_name(
        5.0, 0.0, 1
    ) == "risk_budgeted_idle_carry_overlay_v14_r1_zero_funding"
    with pytest.raises(ValueError, match="pre-registered"):
        carry_overlay._risk_budgeted_overlay_name(4.0, 0.5, 1)


def test_inactive_cost_aware_carry_has_no_resize_cost_or_gross():
    start = datetime.datetime(
        2024, 1, 1, tzinfo=datetime.timezone.utc
    )
    active_points = [
        (
            int((start + datetime.timedelta(days=index)).timestamp()),
            0.0,
        )
        for index in range(30)
    ]
    result = carry_overlay._combine_paths(
        _trajectory(30, 0.50),
        _carry_points(30, 0.0),
        initial_capital=10_000,
        max_overlay_fraction=0.20,
        carry_config=_zero_cost_config(),
        carry_active_points=active_points,
    )

    assert result["overlay_resize_cost_return"] == 0
    assert result["maximum_active_overlay_gross"] == 0
    assert result["maximum_conservative_gross_exposure"] == 0.50
