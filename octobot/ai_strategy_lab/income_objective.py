"""Consolidated, fail-closed audit of the fixed-income project objective."""

from __future__ import annotations

import json
import pathlib
import typing


OBJECTIVE_SCHEMA_VERSION = 2
V14_STRATEGY_NAME = "risk_budgeted_idle_carry_overlay_v14"


def audit_income_objective(
    strategy_evidence_path: typing.Union[str, pathlib.Path],
    prefunded_research_path: typing.Union[str, pathlib.Path],
    shadow_performance_path: typing.Union[str, pathlib.Path],
    *,
    monthly_amount: float = 25.0,
    robustness_research_path: typing.Optional[
        typing.Union[str, pathlib.Path]
    ] = None,
) -> dict:
    if monthly_amount <= 0:
        raise ValueError("monthly amount must be positive")
    evidence_path, evidence = _load_json(strategy_evidence_path)
    prefunded_path, prefunded = _load_json(prefunded_research_path)
    shadow_path, shadow = _load_json(shadow_performance_path)
    if evidence.get("strategy_name") != prefunded.get("strategy_name"):
        raise ValueError("strategy evidence and income policy do not match")
    if float(evidence.get("initial_capital", 0)) != float(
        prefunded.get("initial_capital", -1)
    ):
        raise ValueError("strategy evidence and income capital do not match")
    scenario = prefunded.get("scenarios", {}).get("5.00%")
    if scenario is None:
        raise ValueError("prefunded report is missing the 5% haircut")
    amount_key = f"{monthly_amount:g}"
    amount_report = scenario.get("amounts", {}).get(amount_key)
    if amount_report is None:
        raise ValueError(
            f"prefunded report is missing monthly amount {amount_key}"
        )
    readiness = shadow.get("prefunded_income_readiness")
    if readiness is None:
        raise ValueError("shadow report is missing prefunded readiness")
    if shadow.get("strategy_name") != evidence.get("strategy_name"):
        raise ValueError("shadow performance and strategy evidence do not match")
    if float(readiness.get("monthly_amount", -1)) != monthly_amount:
        raise ValueError("shadow readiness monthly amount does not match")
    robustness_required = evidence.get("strategy_name") == V14_STRATEGY_NAME
    robustness_path = None
    robustness = None
    if robustness_research_path is not None:
        robustness_path, robustness = _load_json(
            robustness_research_path
        )
    robustness_identity_valid = (
        robustness is not None
        and robustness.get("protocol") == "V14-R1"
        and robustness.get("research_only") is True
        and robustness.get("orders_authorized") is False
        and robustness.get("real_income_authorized") is False
        and robustness.get("automatic_promotion") is False
    )
    robustness_gate_passed = (
        robustness_identity_valid
        and bool(
            robustness.get("robustness_gate", {}).get("passed", False)
        )
    )

    checks = {
        "strategy_winning_edge_gate_passed": bool(
            evidence.get("winning_edge_evidence_gate", {}).get(
                "passed", False
            )
        ),
        "prefunded_policy_research_gate_passed": bool(
            amount_report.get("operational_gate", {}).get("passed", False)
        ),
        **(
            {
                "adverse_execution_robustness_gate_passed": (
                    robustness_gate_passed
                )
            }
            if robustness_required or robustness is not None
            else {}
        ),
        "forward_paper_review_gate_passed": bool(
            shadow.get("paper_review_gate", {}).get("passed", False)
        ),
        "finite_block_fully_prefunded_forward": bool(
            readiness.get("finite_block_guaranteed", False)
        ),
        "zero_prefunding_guarantee_breaches": (
            int(readiness.get("guarantee_breaches", -1)) == 0
        ),
        "automatic_promotion_disabled": (
            evidence.get("automatic_promotion") is False
            and shadow.get("automatic_promotion") is False
        ),
        "real_withdrawals_disabled": (
            prefunded.get("real_withdrawals_authorized") is False
            and readiness.get("real_payments_authorized") is False
        ),
    }
    achieved = all(checks.values())
    guaranteed_payments = int(
        readiness.get("guaranteed_future_payments", 0)
    )
    return {
        "schema_version": OBJECTIVE_SCHEMA_VERSION,
        "objective": (
            "Positive strategy edge plus a forward, fully prefunded finite "
            f"income block of {monthly_amount:g} per month."
        ),
        "status": "achieved_in_paper" if achieved else "not_achieved",
        "achieved": achieved,
        "checks": checks,
        "strategy": {
            "name": evidence["strategy_name"],
            "initial_capital": evidence["initial_capital"],
            "winning_edge_evidence_gate": evidence[
                "winning_edge_evidence_gate"
            ],
        },
        "income_policy": {
            "monthly_amount": monthly_amount,
            "block_months": prefunded["block_months"],
            "reserve_target": amount_report["reserve_target"],
            "research_gate": amount_report["operational_gate"],
        },
        "forward_readiness": readiness,
        "simulated_prefunded_monthly_income": (
            monthly_amount if achieved else 0.0
        ),
        "simulated_guaranteed_payments_remaining": (
            guaranteed_payments if achieved else 0
        ),
        "real_income_authorized": False,
        "guarantee_scope": (
            "A finite block is guaranteed only by cash already segregated in "
            "the simulated reserve. Strategy returns, future blocks, custody "
            "and real payments are never guaranteed by this audit."
        ),
        "sources": {
            "strategy_evidence": str(evidence_path),
            "prefunded_research": str(prefunded_path),
            "shadow_performance": str(shadow_path),
            **(
                {
                    "robustness_research": (
                        str(robustness_path)
                        if robustness_path is not None
                        else None
                    )
                }
                if robustness_required or robustness is not None
                else {}
            ),
        },
    }


def _load_json(path_value):
    path = pathlib.Path(path_value).resolve()
    if not path.is_file():
        raise FileNotFoundError(path)
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"JSON report is not an object: {path}")
    return path, value
