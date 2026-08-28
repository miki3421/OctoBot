import datetime
import json

import numpy
import pytest

from octobot.ai_strategy_lab import (
    diversified_trend_cointegration_forward_gate_v1 as gate,
)
from octobot.ai_strategy_lab import (
    diversified_trend_cointegration_forward_runner as observer,
)


UTC = datetime.timezone.utc


def _observer_config(tmp_path):
    names = iter(
        [
            "forward-protocol",
            "implementation-lock",
            "parent-protocol",
            "selected-model",
            "training-report",
            "training-manifest",
            "training-trajectory",
            "snapshot",
            "history",
            "null",
            "archive",
            "raw",
            "journal",
            "health",
            "runner-lock",
        ]
    )
    paths = [tmp_path / next(names) for _index in range(15)]
    return observer.ForwardObserverConfig(
        protocol_path=paths[0],
        implementation_lock_path=paths[1],
        parent_protocol_path=paths[2],
        selected_model_path=paths[3],
        training_report_path=paths[4],
        training_manifest_path=paths[5],
        training_trajectory_path=paths[6],
        snapshot_path=paths[7],
        history_path=paths[8],
        null_path=paths[9],
        archive_root=paths[10],
        raw_root=paths[11],
        journal_path=paths[12],
        health_path=paths[13],
        runner_lock_path=paths[14],
    )


def _config(tmp_path):
    return gate.ForwardGateConfig(
        gate_protocol_path=tmp_path / "gate-protocol.json",
        gate_lock_path=tmp_path / "gate-lock.json",
        output_root=tmp_path / "results",
        observer_config=_observer_config(tmp_path),
    )


def test_frozen_gate_interprets_every_parent_threshold_and_remains_orderless():
    value = gate.frozen_gate_protocol()

    assert value["orders_authorized"] is False
    assert value["paper_orders_authorized"] is False
    assert value["automatic_promotion"] is False
    assert value["timeline"]["official_days_required"] == 180
    assert value["timeline"]["warmup_days_required"] == 61
    assert value["timeline"]["evaluation_not_before_utc"] == (
        "2027-02-28T00:10:00+00:00"
    )
    assert value["pass_fail_gate"][
        "minimum_base_positive_month_ratio"
    ] == 0.5
    assert value["pass_fail_gate"][
        "minimum_stress_positive_month_ratio"
    ] == 0.5
    assert value["economic_accounting"]["cointegration_cutoff_accounting"].startswith(
        "use frozen training simulate_period"
    )
    assert value["official_result"][
        "passed_gate_does_not_authorize_orders"
    ]


def test_gate_protocol_write_is_idempotent_and_detects_mutation(tmp_path):
    path = tmp_path / "gate-protocol.json"

    first = gate.write_or_verify_gate_protocol(path)
    second = gate.write_or_verify_gate_protocol(path)

    assert first == second == gate.gate_protocol_payload()
    changed = json.loads(path.read_text(encoding="utf-8"))
    changed["orders_authorized"] = True
    path.write_text(json.dumps(changed), encoding="utf-8")
    with pytest.raises(gate.GateIntegrityError, match="protocol differs"):
        gate.load_and_verify_gate_protocol(path)


def test_gate_lock_refuses_after_forward_start_before_lineage_access(
    tmp_path, monkeypatch
):
    config = _config(tmp_path)
    called = False

    def unexpected(*_args, **_kwargs):
        nonlocal called
        called = True
        raise AssertionError("lineage must remain unread")

    monkeypatch.setattr(gate, "load_and_verify_gate_protocol", unexpected)
    with pytest.raises(gate.GateNotReadyError, match="after forward start"):
        gate.create_or_verify_gate_lock(
            config,
            now=datetime.datetime(2026, 9, 1, tzinfo=UTC),
        )
    assert called is False


def test_evaluation_refuses_before_cutoff_before_any_archive_access(monkeypatch):
    called = False

    def unexpected(*_args, **_kwargs):
        nonlocal called
        called = True
        raise AssertionError("forward outcomes must remain unread")

    monkeypatch.setattr(gate, "verify_gate_lock", unexpected)
    with pytest.raises(gate.GateNotReadyError, match="locked until"):
        gate.evaluate(
            object(),
            now=datetime.datetime(2027, 2, 28, 0, 9, tzinfo=UTC),
        )
    assert called is False


def test_exact_panel_requires_all_warmup_and_official_dates():
    records = [
        {"bar_date": value.isoformat()}
        for value in gate._dates(
            gate.forward_protocol.WARMUP_START,
            gate.OFFICIAL_END_EXCLUSIVE,
        )
    ]

    warmup, official = gate._assert_complete_panel(records)

    assert len(warmup) == 61
    assert len(official) == 180
    missing = records[:80] + records[81:]
    with pytest.raises(gate.GateIntegrityError, match="exactly complete"):
        gate._assert_complete_panel(missing)
    with pytest.raises(gate.GateIntegrityError, match="post-cutoff"):
        gate._assert_complete_panel(
            records
            + [{"bar_date": gate.OFFICIAL_END_EXCLUSIVE.isoformat()}]
        )


def test_portfolio_metrics_use_independent_sleeve_compounding():
    dates = gate._dates(gate.OFFICIAL_START, gate.OFFICIAL_END_EXCLUSIVE)
    trend = numpy.zeros(gate.OFFICIAL_DAYS)
    cointegration = numpy.zeros(gate.OFFICIAL_DAYS)
    trend[0] = 0.10
    cointegration[0] = -0.02
    trend[1] = -0.05
    cointegration[1] = 0.04

    result = gate.portfolio_metrics(dates, trend, cointegration)

    trend_final = 1.10 * 0.95
    cointegration_final = 0.98 * 1.04
    expected_final = 0.5 * trend_final + 0.5 * cointegration_final
    assert result["total_return"] == pytest.approx(expected_final - 1.0)
    assert result["trend_additive_contribution"] == pytest.approx(
        0.5 * (trend_final - 1.0)
    )
    assert result["cointegration_additive_contribution"] == pytest.approx(
        0.5 * (cointegration_final - 1.0)
    )
    assert result["_trajectory"]["combined_equity"][1] == pytest.approx(
        expected_final
    )


def test_all_frozen_checks_are_required_for_pass():
    dates = gate._dates(gate.OFFICIAL_START, gate.OFFICIAL_END_EXCLUSIVE)
    base = gate.portfolio_metrics(
        dates,
        numpy.full(gate.OFFICIAL_DAYS, 0.0004),
        numpy.full(gate.OFFICIAL_DAYS, 0.0002),
    )
    stress = gate.portfolio_metrics(
        dates,
        numpy.full(gate.OFFICIAL_DAYS, 0.0002),
        numpy.full(gate.OFFICIAL_DAYS, 0.0001),
    )
    activity = {
        "observed_days": 180,
        "cointegration_closed_trades": 3,
        "trend_invested_days": 60,
    }
    specification = gate.frozen_gate_protocol()["pass_fail_gate"]

    passed = gate.gate_checks(base, stress, activity, specification)

    assert passed["passed"] is True
    assert all(passed["checks"].values())
    stress["cointegration_additive_contribution"] = -1e-12
    failed = gate.gate_checks(base, stress, activity, specification)
    assert failed["passed"] is False
    assert failed["checks"][
        "stress_cointegration_contribution_non_negative"
    ] is False


def test_decision_replay_requires_exactly_180_identical_payloads():
    payloads = [
        {"bar_date": value.isoformat(), "orders_authorized": False}
        for value in gate._dates(gate.OFFICIAL_START, gate.OFFICIAL_END_EXCLUSIVE)
    ]
    records = [{"decision_payload": value} for value in payloads]

    gate._verify_exact_decision_replay(records, payloads)

    changed = list(payloads)
    changed[17] = {**changed[17], "orders_authorized": True}
    with pytest.raises(gate.GateIntegrityError, match="index 17"):
        gate._verify_exact_decision_replay(records, changed)
    with pytest.raises(gate.GateIntegrityError, match="count differs"):
        gate._verify_exact_decision_replay(records[:-1], payloads)


def test_cointegration_may_differ_only_on_prescribed_final_bar():
    payloads = []
    zeros = [0.0] * gate.OFFICIAL_DAYS
    terminal = list(zeros)
    terminal[-1] = -0.001
    for value in zeros:
        payloads.append(
            {
                "base": {"cointegration_daily_return": value},
                "stress_3x_cost": {"cointegration_daily_return": value},
            }
        )
    reports = {
        1.0: {"_trajectory": {"daily_return": terminal}},
        3.0: {"_trajectory": {"daily_return": terminal}},
    }

    result = gate._verify_preterminal_cointegration(payloads, reports)

    assert result["cost_1x"][
        "final_difference_is_prescribed_terminal_accounting"
    ]
    reports[1.0]["_trajectory"]["daily_return"][3] = 1e-6
    with pytest.raises(gate.GateIntegrityError, match="before terminal"):
        gate._verify_preterminal_cointegration(payloads, reports)


def test_existing_official_result_prevents_a_second_run(tmp_path):
    protocol_hash = "a" * 64
    root = tmp_path / "results"
    root.mkdir()
    unrelated = root / "notes"
    unrelated.mkdir()
    result = root / f"{gate._official_result_prefix(protocol_hash)}first"
    result.mkdir()

    assert gate._existing_official_results(root, protocol_hash) == [result]
