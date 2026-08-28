import json

import numpy
import pytest

from octobot.ai_strategy_lab import maker_execution_locked_v2 as locked
from octobot.ai_strategy_lab import maker_execution_v1 as v1
from octobot.ai_strategy_lab import maker_execution_v2 as v2


def test_protocol_is_result_free_content_bound_and_orderless():
    protocol = locked.frozen_protocol()
    assert protocol["results"] is None
    assert protocol["orders_authorized"] is False
    assert protocol["paper_orders_authorized"] is False
    assert protocol["model"]["refit"] is False
    assert protocol["model"]["feature_names"] == list(v2.FEATURE_NAMES)
    assert protocol["source"]["only_queryable_interval"] == [
        locked.LOCK_START,
        locked.LOCK_END,
    ]
    assert protocol["parent_prelock"]["final_model_sha256"] == (
        locked.PARENT_MODEL_SHA256
    )
    assert "orderless" in protocol["advancement_consequence"]


def test_protocol_write_is_idempotent_and_detects_mutation(tmp_path):
    path = tmp_path / "protocol.json"
    first = locked.write_or_verify_protocol(path)
    assert first == locked.write_or_verify_protocol(path)
    mutated = json.loads(path.read_text(encoding="utf-8"))
    mutated["locked_gate"]["minimum_selected_attempts"] = 199
    path.write_text(json.dumps(mutated), encoding="utf-8")
    with pytest.raises(ValueError, match="protocol differs"):
        locked.write_or_verify_protocol(path)


def test_locked_builder_has_no_caller_control_over_interval(monkeypatch):
    captured = {}

    def decisions(start, end):
        captured["start"] = start
        captured["end"] = end
        return [101, 202]

    monkeypatch.setattr(v1, "_decision_timestamps", decisions)
    monkeypatch.setattr(v2, "_load_window", lambda connection, timestamp: timestamp)
    monkeypatch.setattr(
        v2,
        "_features",
        lambda window, side: numpy.zeros(len(v2.FEATURE_NAMES)),
    )
    monkeypatch.setattr(
        v2,
        "_unconditional_outcome",
        lambda window, side, policy: {
            "completed": True,
            "filled": False,
            "saving_bps": 0.0,
            "exclusion": None,
        },
    )
    rows, source = locked.build_locked_rows(object())
    assert captured == {
        "start": v1._epoch_ns(locked.LOCK_START),
        "end": v1._epoch_ns(locked.LOCK_END),
    }
    assert len(rows) == 4
    assert source["expected_rows"] == 4
    assert source["interval"] == [locked.LOCK_START, locked.LOCK_END]


def _side(attempts=100, saving=0.6):
    return {
        "selected_attempts": attempts,
        "maker_fills": 40,
        "fill_rate": 0.4,
        "mean_selected_saving_bps": saving,
        "total_saving_bps": saving * attempts,
    }


def _passing_report():
    primary = {
        "selected_attempts": 300,
        "selected_pct": 30.0,
        "selected_fill_rate": 0.4,
        "mean_selected_saving_bps": 0.6,
        "positive_operating_days_pct": 75.0,
        "daily_bootstrap_lower_policy_saving_bps_90pct": 0.1,
        "by_side": {"buy": _side(150), "sell": _side(150)},
    }
    stress = {
        "mean_selected_saving_bps": 0.3,
        "by_side": {"buy": _side(150, 0.2), "sell": _side(150, 0.2)},
    }
    return {
        "source": {"coverage": 0.995, "usable_rows": 1_250},
        "primary": primary,
        "stress": stress,
        "fill_calibration": {"auc": 0.7, "brier": 0.12, "constant_brier": 0.18},
    }


def test_locked_gate_is_conjunctive_and_preserves_saving_margin():
    protocol = locked.frozen_protocol()
    passed = locked.locked_gate(_passing_report(), protocol)
    assert passed["passed"] is True
    assert passed["passed_checks"] == passed["total_checks"]

    report = _passing_report()
    report["primary"]["mean_selected_saving_bps"] = 0.249
    failed = locked.locked_gate(report, protocol)
    assert failed["passed"] is False
    assert failed["checks"]["minimum_selected_mean_saving_bps"] is False


def test_locked_gate_rejects_one_bad_side_even_when_total_is_positive():
    report = _passing_report()
    report["stress"]["by_side"]["sell"]["mean_selected_saving_bps"] = -0.01
    gate = locked.locked_gate(report, locked.frozen_protocol())
    assert gate["passed"] is False
    assert gate["checks"]["stress_each_side_mean_saving_bps_strictly_positive"] is False


def test_complete_experiment_is_verified_without_requery(tmp_path):
    protocol_path = tmp_path / "protocol.json"
    protocol = locked.write_or_verify_protocol(protocol_path)
    identity = "locked-test-identity"
    experiment = tmp_path / identity
    experiment.mkdir()
    prediction_path = experiment / "locked-predictions.npz"
    v2._atomic_npz(prediction_path, {"selected": numpy.asarray([True, False])})
    report = {
        "protocol_sha256": protocol["protocol_sha256"],
        "locked_test": {"materialized": True},
        "orders_authorized": False,
        "paper_orders_authorized": False,
    }
    report_path = experiment / "report.json"
    v2._atomic_json(report_path, report)
    manifest = {
        "identity": identity,
        "protocol_sha256": protocol["protocol_sha256"],
        "report": {"sha256": v2._sha256(report_path)},
        "locked_predictions": {"sha256": v2._sha256(prediction_path)},
    }
    manifest["content_sha256"] = v2._json_hash(manifest)
    v2._atomic_json(experiment / "manifest.json", manifest)

    result = locked._verify_complete_experiment(
        experiment, protocol, identity
    )
    assert result["requeried_database"] is False
    state = json.loads((experiment / "run-state.json").read_text())
    assert state["state"] == "COMPLETE"
    assert locked._verify_complete_experiment(
        experiment, protocol, identity
    )["requeried_database"] is False
