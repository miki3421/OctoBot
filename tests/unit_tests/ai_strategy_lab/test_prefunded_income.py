import numpy

from octobot.ai_strategy_lab import prefunded_income


def test_income_block_starts_only_after_twelve_rates_are_reserved():
    result = prefunded_income.simulate_prefunded_income(
        [0.01] * 24,
        initial_capital=10_000,
        monthly_amount=25,
        block_months=12,
    )
    assert result["reserve_target"] == 300
    assert result["first_payment_month"] == 3
    assert result["blocks_started"] >= 1
    assert result["payments"] >= 12
    assert result["guarantee_breaches"] == 0
    assert result["total_transferred_to_reserve"] >= 300


def test_flat_strategy_never_starts_income_block():
    result = prefunded_income.simulate_prefunded_income(
        [0.0] * 36,
        initial_capital=10_000,
        monthly_amount=25,
        block_months=12,
    )
    assert result["first_payment_month"] is None
    assert result["payments"] == 0
    assert result["total_withdrawn"] == 0


def test_prefunded_block_survives_trading_drawdown():
    result = prefunded_income.simulate_prefunded_income(
        [0.03] + [-0.10] * 12,
        initial_capital=10_000,
        monthly_amount=25,
        block_months=12,
    )
    assert result["first_payment_month"] == 1
    assert result["payments"] == 12
    assert result["guarantee_breaches"] == 0
    assert result["minimum_trading_balance"] < 10_000
    assert result["income_block_active"] is False
    assert result["guaranteed_future_payments"] == 0
    assert result["guaranteed_future_income"] == 0


def test_active_block_reports_only_already_prefunded_future_payments():
    result = prefunded_income.simulate_prefunded_income(
        [0.06],
        initial_capital=10_000,
        monthly_amount=25,
        block_months=24,
    )

    assert result["income_block_active"] is True
    assert result["payments"] == 1
    assert result["guaranteed_future_payments"] == 23
    assert result["guaranteed_future_income"] == 575
    assert result["committed_reserve_balance"] == 575
    assert result["final_reserve_balance"] >= 575
    assert result["guarantee_breaches"] == 0


def test_gate_horizon_matches_prefunded_block_duration(monkeypatch):
    monkeypatch.setattr(
        prefunded_income.withdrawal_module,
        "_load_monthly_returns",
        lambda *_: (
            [(f"2024-{month + 1:02d}", 0.01) for month in range(24)],
            [],
        ),
    )
    monkeypatch.setattr(
        prefunded_income.withdrawal_module,
        "_moving_block_paths",
        lambda *_, **__: numpy.asarray([[0.01] * 48] * 100),
    )

    twelve_month = prefunded_income.evaluate_prefunded_income(
        [],
        "test",
        monthly_amounts=(25,),
        block_months=12,
        horizon_months=48,
        simulations=100,
        annual_return_haircuts=(0,),
    )
    twenty_four_month = prefunded_income.evaluate_prefunded_income(
        [],
        "test",
        monthly_amounts=(25,),
        block_months=24,
        horizon_months=48,
        simulations=100,
        annual_return_haircuts=(0,),
    )

    assert (
        twelve_month["scenarios"]["0.00%"]["amounts"]["25"][
            "operational_gate"
        ]["first_block_horizon_months"]
        == 24
    )
    assert (
        twenty_four_month["scenarios"]["0.00%"]["amounts"]["25"][
            "operational_gate"
        ]["first_block_horizon_months"]
        == 36
    )
    assert (
        twenty_four_month["bootstrap_segments"][
            "cross_source_blocks_allowed"
        ]
        is False
    )
