import json

import pytest

from octobot.ai_strategy_lab import expanded_training_long_confluence_v4_oos as oos


def _report(passes):
    value = 0.1 if passes else -0.1
    return {
        "blocks": 550,
        "invested_blocks": 150,
        "total_return": value,
        "annualized_return": value,
        "annualized_market_alpha": value,
        "sharpe_zero_rate": 1.0 if passes else -1.0,
        "profit_factor": 1.2 if passes else 0.8,
        "maximum_drawdown": 0.1,
        "positive_month_ratio": 0.5 if passes else 0.2,
        "market_beta": 0.2,
        "maximum_symbol_absolute_contribution_share": 0.2,
    }


def test_oos_gate_requires_base_and_stress_to_pass():
    specification = oos.parent.frozen_protocol()["oos_test"]["gate"]

    assert oos._oos_gate(
        _report(True), _report(True), specification
    )["passed"] is True
    failed = oos._oos_gate(_report(True), _report(False), specification)
    assert failed["passed"] is False
    assert failed["checks"]["stress_total_return_positive"] is False


def test_oos_gate_cannot_be_rescued_by_high_return_alone():
    specification = oos.parent.frozen_protocol()["oos_test"]["gate"]
    report = _report(True)
    report["sharpe_zero_rate"] = 0.1

    gate = oos._oos_gate(report, _report(True), specification)

    assert gate["passed"] is False
    assert gate["checks"]["minimum_sharpe"] is False


def test_lineage_rejects_tampered_files_before_loading_market(
    tmp_path, monkeypatch
):
    protocol = tmp_path / "protocol.json"
    report = tmp_path / "training-report.json"
    manifest = tmp_path / "manifest.json"
    model = tmp_path / "model.json"
    for path in (protocol, report, manifest, model):
        path.write_text(json.dumps({}), encoding="utf-8")
    monkeypatch.setattr(
        oos, "EXPECTED_PROTOCOL_FILE_SHA256", oos.common._sha256(protocol)
    )

    with pytest.raises(ValueError, match="lineage hash differs"):
        oos.verify_frozen_lineage(protocol, report, manifest, model)
