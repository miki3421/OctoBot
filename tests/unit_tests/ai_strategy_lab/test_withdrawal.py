import json

import numpy

from octobot.ai_strategy_lab import withdrawal


def test_guard_skips_payment_that_would_cross_floor():
    result = withdrawal._simulate_guarded_withdrawal(
        [-0.15, 0.0],
        initial_capital=10_000,
        monthly_amount=1_000,
        warmup_months=0,
        safety_floor_fraction=0.80,
    )
    assert result["scheduled_payments"] == 2
    assert result["paid_payments"] == 0
    assert result["skipped_payments"] == 2


def test_moving_block_bootstrap_is_seed_deterministic():
    values = numpy.asarray([0.01, -0.02, 0.03, 0.04])
    first = withdrawal._moving_block_paths(
        values,
        horizon_months=12,
        block_months=2,
        simulations=100,
        rng=numpy.random.default_rng(7),
    )
    second = withdrawal._moving_block_paths(
        values,
        horizon_months=12,
        block_months=2,
        simulations=100,
        rng=numpy.random.default_rng(7),
    )
    assert numpy.array_equal(first, second)


def test_moving_block_bootstrap_never_crosses_source_boundary():
    values = numpy.asarray([0.0, 1.0, 10.0, 11.0])
    paths = withdrawal._moving_block_paths(
        values,
        horizon_months=40,
        block_months=2,
        simulations=100,
        rng=numpy.random.default_rng(17),
        segment_lengths=(2, 2),
    )
    allowed_blocks = {
        (0.0, 1.0),
        (1.0, 0.0),
        (10.0, 11.0),
        (11.0, 10.0),
    }
    for path in paths:
        assert all(
            tuple(path[index:index + 2]) in allowed_blocks
            for index in range(0, len(path), 2)
        )


def test_evaluate_withdrawals_rejects_overlapping_months(tmp_path):
    payload = {
        "reports": {
            "strategy": {
                "evaluation_start_date": "2020-01-01",
                "evaluation_end_date": "2021-12-31",
                "monthly_returns": {
                    f"{year}-{month:02d}": 0.01
                    for year in (2020, 2021)
                    for month in range(1, 13)
                },
            }
        }
    }
    first = tmp_path / "first.json"
    second = tmp_path / "second.json"
    first.write_text(json.dumps(payload), encoding="utf-8")
    second.write_text(json.dumps(payload), encoding="utf-8")
    try:
        withdrawal.evaluate_withdrawals(
            [first, second],
            "strategy",
            simulations=100,
        )
    except ValueError as error:
        assert "overlapping months" in str(error)
    else:
        raise AssertionError("overlapping reports must be rejected")


def test_load_monthly_returns_rejects_gap_inside_source(tmp_path):
    payload = {
        "reports": {
            "strategy": {
                "evaluation_start_date": "2020-01-01",
                "evaluation_end_date": "2020-03-31",
                "monthly_returns": {
                    "2020-01": 0.01,
                    "2020-03": 0.02,
                },
            }
        }
    }
    path = tmp_path / "gapped.json"
    path.write_text(json.dumps(payload), encoding="utf-8")

    try:
        withdrawal._load_monthly_returns([path], "strategy")
    except ValueError as error:
        assert "contains a gap" in str(error)
    else:
        raise AssertionError("gapped source must be rejected")
