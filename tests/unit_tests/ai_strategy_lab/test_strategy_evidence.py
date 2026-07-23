import numpy

from octobot.ai_strategy_lab import strategy_evidence


def test_constant_positive_paths_pass_edge_gate(monkeypatch):
    monkeypatch.setattr(
        strategy_evidence.withdrawal_module,
        "_load_monthly_returns",
        lambda *_: (
            [(f"{2020 + index // 12}-{index % 12 + 1:02d}", 0.02)
             for index in range(60)],
            [],
        ),
    )
    monkeypatch.setattr(
        strategy_evidence.withdrawal_module,
        "_moving_block_paths",
        lambda values, *, horizon_months, simulations, **_: numpy.tile(
            numpy.asarray(values[:1]), (simulations, horizon_months)
        ),
    )

    report = strategy_evidence.evaluate_strategy_evidence(
        ["unused"],
        "test",
        simulations=100,
    )

    assert report["historical_months"] == 60
    assert report["winning_edge_evidence_gate"]["passed"] is True
    decade = report["scenarios"]["5.00%"]["horizons"]["120"]
    assert decade["probability_final_at_or_above_initial"] == 1.0
    assert decade["max_drawdown_percentiles"]["p90"] == 0.0
    assert report["automatic_promotion"] is False
    assert report["real_withdrawals_authorized"] is False
    assert report["bootstrap_segments"]["cross_source_blocks_allowed"] is False


def test_negative_paths_fail_edge_gate(monkeypatch):
    monkeypatch.setattr(
        strategy_evidence.withdrawal_module,
        "_load_monthly_returns",
        lambda *_: (
            [(f"{2020 + index // 12}-{index % 12 + 1:02d}", -0.01)
             for index in range(60)],
            [],
        ),
    )
    monkeypatch.setattr(
        strategy_evidence.withdrawal_module,
        "_moving_block_paths",
        lambda values, *, horizon_months, simulations, **_: numpy.tile(
            numpy.asarray(values[:1]), (simulations, horizon_months)
        ),
    )

    report = strategy_evidence.evaluate_strategy_evidence(
        ["unused"],
        "test",
        simulations=100,
    )

    assert report["winning_edge_evidence_gate"]["passed"] is False
    assert (
        report["scenarios"]["5.00%"]["horizons"]["120"][
            "probability_final_at_or_above_initial"
        ]
        == 0.0
    )


def test_path_summary_reports_tail_drawdown_and_year_consistency():
    paths = numpy.asarray(
        [
            [0.01] * 24,
            [0.02, -0.10] * 12,
        ]
    )

    summary = strategy_evidence._summarize_paths(
        paths, initial_capital=10_000
    )

    assert summary["horizon_months"] == 24
    assert 0 <= summary["probability_final_at_or_above_initial"] <= 1
    assert summary["max_drawdown_percentiles"]["p90"] > 0
    assert 0 <= summary["probability_every_year_positive"] <= 1
