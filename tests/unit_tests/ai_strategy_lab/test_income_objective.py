import json

import pytest

from octobot.ai_strategy_lab import income_objective


def _write(path, value):
    path.write_text(json.dumps(value), encoding="utf-8")
    return path


def _reports(tmp_path, *, edge=True, paper=True, funded=True):
    evidence = _write(
        tmp_path / "evidence.json",
        {
            "strategy_name": "v3",
            "initial_capital": 10_000,
            "winning_edge_evidence_gate": {
                "passed": edge,
                "checks": {},
            },
            "automatic_promotion": False,
        },
    )
    prefunded = _write(
        tmp_path / "prefunded.json",
        {
            "strategy_name": "v3",
            "initial_capital": 10_000,
            "block_months": 24,
            "real_withdrawals_authorized": False,
            "scenarios": {
                "5.00%": {
                    "amounts": {
                        "25": {
                            "reserve_target": 600,
                            "operational_gate": {
                                "passed": True,
                                "checks": {},
                            },
                        }
                    }
                }
            },
        },
    )
    shadow = _write(
        tmp_path / "shadow.json",
        {
            "strategy_name": "v3",
            "paper_review_gate": {"passed": paper},
            "automatic_promotion": False,
            "prefunded_income_readiness": {
                "monthly_amount": 25,
                "finite_block_guaranteed": funded,
                "guarantee_breaches": 0,
                "guaranteed_future_payments": 23 if funded else 0,
                "real_payments_authorized": False,
            },
        },
    )
    return evidence, prefunded, shadow


def test_objective_is_fail_closed_until_every_gate_passes(tmp_path):
    paths = _reports(tmp_path, edge=False, paper=False, funded=False)

    report = income_objective.audit_income_objective(*paths)

    assert report["status"] == "not_achieved"
    assert report["achieved"] is False
    assert report["simulated_prefunded_monthly_income"] == 0
    assert report["simulated_guaranteed_payments_remaining"] == 0
    assert report["real_income_authorized"] is False


def test_objective_reports_only_a_fully_backed_paper_block(tmp_path):
    paths = _reports(tmp_path)

    report = income_objective.audit_income_objective(*paths)

    assert report["status"] == "achieved_in_paper"
    assert report["achieved"] is True
    assert report["simulated_prefunded_monthly_income"] == 25
    assert report["simulated_guaranteed_payments_remaining"] == 23
    assert report["real_income_authorized"] is False


def test_objective_rejects_mismatched_strategy(tmp_path):
    evidence, prefunded, shadow = _reports(tmp_path)
    value = json.loads(prefunded.read_text(encoding="utf-8"))
    value["strategy_name"] = "other"
    prefunded.write_text(json.dumps(value), encoding="utf-8")

    with pytest.raises(ValueError, match="do not match"):
        income_objective.audit_income_objective(
            evidence, prefunded, shadow
        )


def test_objective_rejects_mismatched_shadow_strategy(tmp_path):
    evidence, prefunded, shadow = _reports(tmp_path)
    value = json.loads(shadow.read_text(encoding="utf-8"))
    value["strategy_name"] = "other"
    shadow.write_text(json.dumps(value), encoding="utf-8")

    with pytest.raises(ValueError, match="shadow performance"):
        income_objective.audit_income_objective(
            evidence, prefunded, shadow
        )


def test_v14_requires_successful_adverse_execution_audit(tmp_path):
    evidence, prefunded, shadow = _reports(tmp_path)
    for path in (evidence, prefunded, shadow):
        value = json.loads(path.read_text(encoding="utf-8"))
        value["strategy_name"] = income_objective.V14_STRATEGY_NAME
        path.write_text(json.dumps(value), encoding="utf-8")

    missing = income_objective.audit_income_objective(
        evidence, prefunded, shadow
    )
    assert missing["status"] == "not_achieved"
    assert (
        missing["checks"][
            "adverse_execution_robustness_gate_passed"
        ]
        is False
    )

    robustness = _write(
        tmp_path / "robustness.json",
        {
            "protocol": "V14-R1",
            "research_only": True,
            "orders_authorized": False,
            "real_income_authorized": False,
            "automatic_promotion": False,
            "robustness_gate": {"passed": True},
        },
    )
    passed = income_objective.audit_income_objective(
        evidence,
        prefunded,
        shadow,
        robustness_research_path=robustness,
    )
    assert passed["status"] == "achieved_in_paper"
