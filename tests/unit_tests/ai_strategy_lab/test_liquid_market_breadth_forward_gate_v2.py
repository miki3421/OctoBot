import datetime
import json
import pathlib

import numpy
import pytest

from octobot.ai_strategy_lab import (
    liquid_market_breadth_forward_gate_v2 as gate,
)


UTC = datetime.timezone.utc


def test_gate_protocol_interprets_the_forward_gate_and_is_orderless():
    value = gate.frozen_gate_protocol()

    assert value["results"] is None
    assert value["orders_authorized"] is False
    assert value["paper_orders_authorized"] is False
    assert value["automatic_promotion"] is False
    assert value["timeline"]["warmup_days_required"] == 61
    assert value["timeline"][
        "official_market_and_decision_days_required"
    ] == 180
    assert value["timeline"]["mature_outcomes_required"] == 179
    assert value["timeline"]["evaluation_not_before_utc"] == (
        "2027-02-28T00:25:00+00:00"
    )
    assert value["bootstrap"]["simulations"] == 20_000
    assert value["bootstrap"]["lower_tail_probability"] == pytest.approx(
        0.0125
    )


def test_gate_protocol_round_trip_rejects_mutation(tmp_path):
    path = tmp_path / "gate-protocol.json"
    first = gate.write_or_verify_gate_protocol(path)

    assert gate.write_or_verify_gate_protocol(path) == first
    changed = json.loads(path.read_text(encoding="utf-8"))
    changed["orders_authorized"] = True
    path.write_text(json.dumps(changed), encoding="utf-8")
    with pytest.raises(gate.GateIntegrityError, match="protocol differs"):
        gate.write_or_verify_gate_protocol(path)


def _minimal_config(tmp_path):
    return gate.GateConfig(
        gate_protocol_path=tmp_path / "gate-protocol",
        gate_lock_path=tmp_path / "gate-lock",
        output_root=tmp_path / "results",
        gate_test_path=tmp_path / "gate-test",
        entrypoint_path=tmp_path / "entrypoint",
        observer_config=None,
    )


def test_gate_lock_refuses_after_forward_start_before_lineage_access(
    tmp_path, monkeypatch
):
    called = False

    def unexpected(*_args, **_kwargs):
        nonlocal called
        called = True
        raise AssertionError("lineage must not be read")

    monkeypatch.setattr(gate, "_load_gate_protocol", unexpected)
    with pytest.raises(gate.GateNotReadyError, match="after forward start"):
        gate.create_or_verify_gate_lock(
            _minimal_config(tmp_path),
            now=datetime.datetime(2026, 9, 1, tzinfo=UTC),
        )
    assert called is False


def test_evaluation_refuses_before_cutoff_before_forward_access(monkeypatch):
    called = False

    def unexpected(*_args, **_kwargs):
        nonlocal called
        called = True
        raise AssertionError("forward outcomes must remain unread")

    monkeypatch.setattr(gate, "_structural_readiness", unexpected)
    with pytest.raises(gate.GateNotReadyError, match="locked until"):
        gate.evaluate(
            object(),
            now=datetime.datetime(2027, 2, 28, 0, 24, tzinfo=UTC),
        )
    assert called is False


def test_return_metrics_compound_and_use_daily_profit_factor():
    dates = [
        datetime.date(2026, 9, 2),
        datetime.date(2026, 9, 3),
    ]

    result = gate.return_metrics(dates, [0.10, -0.05])

    assert result["total_return"] == pytest.approx(1.10 * 0.95 - 1.0)
    assert result["profit_factor"] == pytest.approx(2.0)
    assert result["profit_factor_is_infinite"] is False
    assert result["maximum_drawdown"] == pytest.approx(0.05)
    assert result["positive_month_ratio"] == 1.0


def test_circular_bootstrap_is_deterministic_and_directional(monkeypatch):
    monkeypatch.setattr(gate.forward_protocol, "BOOTSTRAP_SIMULATIONS", 2_000)
    monkeypatch.setattr(gate.forward_protocol, "BOOTSTRAP_BLOCK_DAYS", 5)

    first = gate.circular_block_bootstrap_lower([0.001] * 179)
    second = gate.circular_block_bootstrap_lower([0.001] * 179)
    negative = gate.circular_block_bootstrap_lower([-0.001] * 179)

    assert first == second
    assert first > 0
    assert negative < 0


def _metric(
    *,
    total=0.05,
    annualized=0.10,
    sharpe=1.5,
    drawdown=0.05,
    cost=0.02,
):
    return {
        "total_return": total,
        "annualized_return": annualized,
        "sharpe_zero_rate": sharpe,
        "profit_factor": 2.0,
        "profit_factor_is_infinite": False,
        "maximum_drawdown": drawdown,
        "positive_month_ratio": 0.80,
        "price_additive_return": 0.15,
        "funding_additive_return": -0.01,
        "transaction_cost": cost,
        "total_turnover": 5.0,
        "average_gross_exposure": 0.20,
        "maximum_symbol_absolute_contribution_share": 0.10,
    }


def test_all_31_frozen_checks_are_conjunctive():
    base = {
        "breadth_v2": _metric(),
        "continuous": _metric(
            total=0.01, annualized=0.02, sharpe=0.5, drawdown=0.10
        ),
        "parent_v1": _metric(
            total=0.02, annualized=0.03, sharpe=1.0, drawdown=0.08
        ),
    }
    stress = {
        "breadth_v2": _metric(
            total=0.03,
            annualized=0.06,
            sharpe=1.0,
            drawdown=0.08,
            cost=0.05,
        ),
        "continuous": _metric(),
        "parent_v1": _metric(),
    }
    activity = {
        "valid_signal_decisions": 180,
        "active_vintage_decisions": 30,
        "invested_days": 100,
        "maximum_post_net_gross": 0.40,
    }
    structural = {
        "official_market_records": 180,
        "decision_records": 180,
        "mature_outcomes": 179,
        "complete_hash_chains_and_raw_lineage": True,
        "same_signal_costs_code_no_refit": True,
    }

    result = gate.gate_checks(base, stress, activity, structural, 0.01)

    assert result["passed"] is True
    assert result["passed_checks"] == result["total_checks"] == 31
    failed = gate.gate_checks(base, stress, activity, structural, -1e-12)
    assert failed["passed"] is False
    assert failed["checks"]["bootstrap_lower_bound_positive"] is False


def test_symbol_contributions_reconcile_target_returns_and_costs():
    dates = [
        datetime.date(2026, 9, 1) + datetime.timedelta(days=index)
        for index in range(3)
    ]
    market = {
        "dates": dates,
        "symbols": ["A", "B"],
        "returns": numpy.asarray([[0, 0], [0.01, 0.02], [-0.01, 0.03]]),
        "return_complete": numpy.ones((3, 2), dtype=bool),
        "funding": numpy.zeros((3, 2)),
        "funding_counts": numpy.ones((3, 2), dtype=numpy.int16),
    }
    target_0 = numpy.asarray([0.1, 0.2])
    target_1 = numpy.asarray([0.2, 0.0])
    zero = numpy.zeros(2)
    outcome_1 = gate.observer._outcome(market, 1, zero, target_0, 1.0)
    outcome_2 = gate.observer._outcome(
        market, 2, target_0, target_1, 1.0
    )
    payloads = [
        {
            "bar_date": dates[0].isoformat(),
            "research_targets": {"breadth_v2": {"A": 0.1, "B": 0.2}},
            "matured_outcome": None,
        },
        {
            "bar_date": dates[1].isoformat(),
            "research_targets": {"breadth_v2": {"A": 0.2}},
            "matured_outcome": {"base": {"breadth_v2": outcome_1}},
        },
        {
            "bar_date": dates[2].isoformat(),
            "research_targets": {"breadth_v2": {}},
            "matured_outcome": {"base": {"breadth_v2": outcome_2}},
        },
    ]

    result = gate._symbol_contributions(
        market, payloads, "breadth_v2", "base"
    )

    assert result["daily_net_return"] == pytest.approx(
        [outcome_1["net_return"], outcome_2["net_return"]]
    )
    assert sum(result["by_symbol"].values()) == pytest.approx(
        outcome_1["net_return"] + outcome_2["net_return"]
    )


def test_structural_readiness_exposes_counts_but_no_metrics(monkeypatch):
    warmup_dates = gate._dates(gate.forward_protocol.WARMUP_START, 61)
    official_dates = gate._dates(gate.OFFICIAL_START, 180)
    records = [
        {"bar_date": date.isoformat()} for date in warmup_dates + official_dates
    ]
    journal = [
        {
            "decision_payload": {
                "bar_date": date.isoformat(),
                "matured_outcome": None if index == 0 else {},
            }
        }
        for index, date in enumerate(official_dates)
    ]
    observer_config = type(
        "ObserverConfig", (), {"journal_path": pathlib.Path("/tmp/journal")}
    )
    config = type(
        "Config",
        (),
        {
            "observer_config": observer_config,
            "output_root": pathlib.Path("/tmp/x"),
        },
    )
    monkeypatch.setattr(
        gate,
        "verify_gate_lock",
        lambda _config: {
            "gate_protocol": {"gate_protocol_sha256": "a" * 64}
        },
    )
    monkeypatch.setattr(
        gate.observer,
        "load_extended_market",
        lambda _config: ({}, records),
    )
    monkeypatch.setattr(gate.observer, "load_journal", lambda _path: journal)
    monkeypatch.setattr(gate, "_existing_results", lambda *_args: [])

    result = gate.readiness(config, now=gate.EVALUATION_NOT_BEFORE)

    assert result["status"] == "READY"
    assert result["official_evaluation_authorized"] is True
    assert result["economic_metrics_calculated"] is False
    assert result["economic_results_persisted"] is False
    assert result["orders_authorized"] is False


def test_gate_source_lineage_is_mount_path_independent(tmp_path):
    originals = {
        "gate_test_path": pathlib.Path(__file__).resolve(),
        "entrypoint_path": pathlib.Path(__file__).resolve().parents[3]
        / "docker/breadth-forward-gatekeeper-entrypoint.sh",
    }
    copies = {}
    for name, source in originals.items():
        destination = tmp_path / name
        destination.write_bytes(source.read_bytes())
        copies[name] = destination
    host = type("Config", (), originals)
    container = type("Config", (), copies)

    assert gate._source_artifacts(host) == gate._source_artifacts(container)


def test_gate_surface_has_no_network_or_order_capability():
    source = pathlib.Path(gate.__file__).read_text(encoding="utf-8")

    assert "urllib.request" not in source
    assert "create_order" not in source
    assert "paper_orders_authorized\": True" not in source
    assert "orders_authorized\": True" not in source
