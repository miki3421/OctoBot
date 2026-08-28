import json

import pytest

from octobot.ai_strategy_lab import maker_execution_fee_audit_v1 as audit


def _source_report():
    return {
        "verdict": "LOCKED_PASS_EXECUTION_OVERLAY_SHADOW_ELIGIBLE",
        "locked_test": {
            "materialized": True,
            "report": {
                "stress": {
                    "selected_attempts": 100,
                    "maker_fills": 25,
                    "mean_selected_saving_bps": 1.0,
                    "by_side": {
                        "buy": {
                            "selected_attempts": 60,
                            "maker_fills": 10,
                            "mean_selected_saving_bps": 0.8,
                        },
                        "sell": {
                            "selected_attempts": 40,
                            "maker_fills": 15,
                            "mean_selected_saving_bps": 0.5,
                        },
                    },
                }
            },
        },
    }


def test_fee_neutral_audit_is_exact_and_cannot_promote():
    report = audit.audit_report(_source_report())
    assert audit.extra_relative_fee_advantage_bps() == 2.0
    assert report["fee_neutral_stress"]["overall"][
        "fee_neutral_stress_mean_saving_bps"
    ] == pytest.approx(0.5)
    assert report["fee_neutral_stress"]["by_side"]["buy"][
        "fee_neutral_stress_mean_saving_bps"
    ] == pytest.approx(0.8 - 20 / 60)
    assert report["fee_neutral_stress"]["by_side"]["sell"][
        "fee_neutral_stress_mean_saving_bps"
    ] == pytest.approx(-0.25)
    assert report["finding"]["each_side_stress_remains_positive"] is False
    assert report["automatic_promotion"] is False
    assert report["new_market_rows_queried"] is False


def test_audit_rejects_nonlocked_source():
    source = _source_report()
    source["verdict"] = "LOCKED_REJECTED"
    with pytest.raises(ValueError, match="verdict differs"):
        audit.audit_report(source)


def test_evaluate_binds_source_hash_and_is_idempotent(tmp_path, monkeypatch):
    source = tmp_path / "report.json"
    source.write_text(json.dumps(_source_report()), encoding="utf-8")
    monkeypatch.setattr(audit, "SOURCE_REPORT_SHA256", audit.v2._sha256(source))
    output = tmp_path / "audit.json"
    first = audit.evaluate(source, output)
    assert first == audit.evaluate(source, output)
    mutated = json.loads(output.read_text(encoding="utf-8"))
    mutated["model_refit"] = True
    output.write_text(json.dumps(mutated), encoding="utf-8")
    with pytest.raises(ValueError, match="audit differs"):
        audit.evaluate(source, output)
