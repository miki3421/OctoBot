"""Fail-closed robustness audit for the pre-registered V14-R1 stress."""

from __future__ import annotations

import hashlib
import json
import pathlib
import typing


ROBUSTNESS_SCHEMA_VERSION = 1
HALF_STRATEGY = (
    "risk_budgeted_idle_carry_overlay_v14_r1_half_funding"
)
ZERO_STRATEGY = (
    "risk_budgeted_idle_carry_overlay_v14_r1_zero_funding"
)
TREND_STRATEGY = "risk_budgeted_bear_regime_v13_cost_stress_3x"


def audit_v14_robustness(
    *,
    half_old_report,
    half_recent_report,
    half_kucoin_report,
    half_evidence,
    half_prefunded,
    zero_old_report,
    zero_recent_report,
    zero_kucoin_report,
    zero_evidence,
    zero_prefunded,
) -> dict:
    half = _load_scenario(
        half_old_report,
        half_recent_report,
        half_kucoin_report,
        half_evidence,
        half_prefunded,
        expected_strategy=HALF_STRATEGY,
        expected_realization=0.5,
    )
    zero = _load_scenario(
        zero_old_report,
        zero_recent_report,
        zero_kucoin_report,
        zero_evidence,
        zero_prefunded,
        expected_strategy=ZERO_STRATEGY,
        expected_realization=0.0,
    )

    old = half["reports"]["old"]
    recent = half["reports"]["recent"]
    kucoin = half["reports"]["kucoin"]
    checks = {
        "scenario_identity_and_assumptions_exact": (
            half["identity_valid"]
        ),
        "recent_return_at_least_v13": (
            recent["stress"]["annualized_return"]
            >= recent["trend"]["annualized_return"]
        ),
        "recent_drawdown_at_most_16_8pct": (
            recent["stress"]["max_drawdown"] <= 0.168
        ),
        "recent_sharpe_at_least_0_93": (
            recent["stress"]["sharpe_zero_rate"] >= 0.93
        ),
        "recent_positive_month_ratio_at_least_v13": (
            recent["stress"]["positive_month_ratio"]
            >= recent["trend"]["positive_month_ratio"]
        ),
        "recent_worst_rolling_12m_at_least_minus_3pct": (
            recent["stress"]["worst_rolling_12_month_return"] >= -0.03
        ),
        "old_return_at_least_95pct_of_v13": (
            old["stress"]["annualized_return"]
            >= 0.95 * old["trend"]["annualized_return"]
        ),
        "old_drawdown_at_most_11pct": (
            old["stress"]["max_drawdown"] <= 0.11
        ),
        "old_sharpe_at_least_2": (
            old["stress"]["sharpe_zero_rate"] >= 2.0
        ),
        "kucoin_return_at_least_12_7pct": (
            kucoin["stress"]["annualized_return"] >= 0.127
        ),
        "kucoin_drawdown_at_most_6pct": (
            kucoin["stress"]["max_drawdown"] <= 0.06
        ),
        "kucoin_sharpe_at_least_1": (
            kucoin["stress"]["sharpe_zero_rate"] >= 1.0
        ),
        "segment_aware_edge_gate_passed": half["edge_gate"],
        "prefunded_income_gate_passed": half["income_gate"],
    }
    return {
        "schema_version": ROBUSTNESS_SCHEMA_VERSION,
        "research_only": True,
        "orders_authorized": False,
        "real_income_authorized": False,
        "automatic_promotion": False,
        "protocol": "V14-R1",
        "warning": (
            "Diagnostic reuse stress, not forward evidence or a guarantee."
        ),
        "adverse_execution_scenario": {
            "strategy_name": HALF_STRATEGY,
            "positive_funding_realization": 0.5,
            "negative_funding_realization": 1.0,
            "carry_cost_stress_multiplier": 5.0,
            "entry_delay_settlements": 1,
            "reports": half["reports"],
            "edge_gate": half["edge_gate"],
            "income_gate": half["income_gate"],
        },
        "robustness_gate": {
            "passed": all(checks.values()),
            "checks": checks,
        },
        "zero_positive_funding_diagnostic": {
            "strategy_name": ZERO_STRATEGY,
            "positive_funding_realization": 0.0,
            "negative_funding_realization": 1.0,
            "carry_cost_stress_multiplier": 5.0,
            "entry_delay_settlements": 1,
            "identity_valid": zero["identity_valid"],
            "reports": zero["reports"],
            "edge_gate": zero["edge_gate"],
            "income_gate": zero["income_gate"],
            "is_promotion_gate": False,
        },
        "sources": half["sources"] + zero["sources"],
    }


def audit_overlay_candidate(
    *,
    candidate_name,
    stress_name,
    baseline_old_report,
    baseline_recent_report,
    baseline_kucoin_report,
    stress_old_report,
    stress_recent_report,
    stress_kucoin_report,
    stress_evidence,
    stress_prefunded,
) -> dict:
    if not candidate_name or not stress_name:
        raise ValueError("candidate and stress names are required")
    baseline = _load_candidate_reports(
        baseline_old_report,
        baseline_recent_report,
        baseline_kucoin_report,
        candidate_name,
        expected_cost=3.0,
        expected_realization=1.0,
    )
    stress = _load_candidate_reports(
        stress_old_report,
        stress_recent_report,
        stress_kucoin_report,
        stress_name,
        expected_cost=5.0,
        expected_realization=0.5,
    )
    evidence_source, evidence = _load_json(stress_evidence)
    prefunded_source, prefunded = _load_json(stress_prefunded)
    stress_identity = (
        evidence.get("strategy_name") == stress_name
        and prefunded.get("strategy_name") == stress_name
        and evidence.get("bootstrap_segments", {}).get(
            "cross_source_blocks_allowed"
        )
        is False
        and prefunded.get("bootstrap_segments", {}).get(
            "cross_source_blocks_allowed"
        )
        is False
    )
    amount = (
        prefunded.get("scenarios", {})
        .get("5.00%", {})
        .get("amounts", {})
        .get("25", {})
    )
    baseline_checks = _direct_checks(baseline["reports"])
    stress_checks = _direct_checks(stress["reports"])
    stress_checks.update(
        {
            "scenario_identity_and_assumptions_exact": (
                stress["identity_valid"] and stress_identity
            ),
            "segment_aware_edge_gate_passed": bool(
                evidence.get("winning_edge_evidence_gate", {}).get(
                    "passed", False
                )
            ),
            "prefunded_income_gate_passed": bool(
                amount.get("operational_gate", {}).get(
                    "passed", False
                )
            ),
        }
    )
    baseline_checks[
        "scenario_identity_and_assumptions_exact"
    ] = baseline["identity_valid"]
    baseline_passed = all(baseline_checks.values())
    stress_passed = all(stress_checks.values())
    return {
        "schema_version": ROBUSTNESS_SCHEMA_VERSION,
        "research_only": True,
        "orders_authorized": False,
        "real_income_authorized": False,
        "automatic_promotion": False,
        "candidate_name": candidate_name,
        "stress_name": stress_name,
        "baseline": {
            "reports": baseline["reports"],
            "checks": baseline_checks,
            "passed": baseline_passed,
        },
        "adverse_stress": {
            "reports": stress["reports"],
            "checks": stress_checks,
            "passed": stress_passed,
        },
        "candidate_gate": {
            "passed": baseline_passed and stress_passed,
            "interpretation": (
                "Diagnostic reuse only; passing permits at most a separate "
                "forward shadow."
            ),
        },
        "sources": (
            baseline["sources"]
            + stress["sources"]
            + [evidence_source, prefunded_source]
        ),
    }


def _load_candidate_reports(
    old_report,
    recent_report,
    kucoin_report,
    strategy_name,
    *,
    expected_cost,
    expected_realization,
):
    reports = {}
    sources = []
    identity_valid = True
    for label, path in (
        ("old", old_report),
        ("recent", recent_report),
        ("kucoin", kucoin_report),
    ):
        source, payload = _load_json(path)
        candidate = payload.get("reports", {}).get(strategy_name)
        trend = payload.get("reports", {}).get(TREND_STRATEGY)
        if not isinstance(candidate, dict) or not isinstance(trend, dict):
            raise ValueError(
                f"{source['path']} is missing the candidate reports"
            )
        identity_valid = identity_valid and (
            payload.get("research_only") is True
            and payload.get("orders_authorized") is False
            and float(payload.get("trend_cost_stress_multiplier", -1))
            == 3.0
            and float(payload.get("carry_cost_stress_multiplier", -1))
            == expected_cost
            and float(payload.get("positive_funding_realization", -1))
            == expected_realization
            and int(payload.get("entry_delay_settlements", -1)) == 1
            and candidate.get("config", {}).get("netting_assumed") is False
        )
        reports[label] = {
            "trend": _metrics(trend),
            "candidate": _metrics(candidate),
        }
        sources.append(source)
    return {
        "reports": reports,
        "sources": sources,
        "identity_valid": identity_valid,
    }


def _direct_checks(reports):
    old = reports["old"]
    recent = reports["recent"]
    kucoin = reports["kucoin"]
    return {
        "recent_return_at_least_v13": (
            recent["candidate"]["annualized_return"]
            >= recent["trend"]["annualized_return"]
        ),
        "recent_drawdown_at_most_16_8pct": (
            recent["candidate"]["max_drawdown"] <= 0.168
        ),
        "recent_sharpe_at_least_0_93": (
            recent["candidate"]["sharpe_zero_rate"] >= 0.93
        ),
        "recent_positive_month_ratio_at_least_v13": (
            recent["candidate"]["positive_month_ratio"]
            >= recent["trend"]["positive_month_ratio"]
        ),
        "recent_worst_rolling_12m_at_least_minus_3pct": (
            recent["candidate"]["worst_rolling_12_month_return"]
            >= -0.03
        ),
        "old_return_at_least_95pct_of_v13": (
            old["candidate"]["annualized_return"]
            >= 0.95 * old["trend"]["annualized_return"]
        ),
        "old_drawdown_at_most_11pct": (
            old["candidate"]["max_drawdown"] <= 0.11
        ),
        "old_sharpe_at_least_2": (
            old["candidate"]["sharpe_zero_rate"] >= 2.0
        ),
        "kucoin_return_at_least_12_7pct": (
            kucoin["candidate"]["annualized_return"] >= 0.127
        ),
        "kucoin_drawdown_at_most_6pct": (
            kucoin["candidate"]["max_drawdown"] <= 0.06
        ),
        "kucoin_sharpe_at_least_1": (
            kucoin["candidate"]["sharpe_zero_rate"] >= 1.0
        ),
    }


def _load_scenario(
    old_report,
    recent_report,
    kucoin_report,
    evidence_path,
    prefunded_path,
    *,
    expected_strategy,
    expected_realization,
):
    loaded_reports = {
        "old": _load_json(old_report),
        "recent": _load_json(recent_report),
        "kucoin": _load_json(kucoin_report),
    }
    evidence_source, evidence = _load_json(evidence_path)
    prefunded_source, prefunded = _load_json(prefunded_path)
    reports = {}
    identity_valid = True
    sources = []
    for label, (source, payload) in loaded_reports.items():
        stress = payload.get("reports", {}).get(expected_strategy)
        trend = payload.get("reports", {}).get(TREND_STRATEGY)
        if not isinstance(stress, dict) or not isinstance(trend, dict):
            raise ValueError(
                f"{source['path']} is missing the expected V14-R1 reports"
            )
        config = stress.get("config", {})
        carry_config = config.get("carry", {})
        identity_valid = identity_valid and (
            payload.get("research_only") is True
            and payload.get("orders_authorized") is False
            and float(payload.get("carry_cost_stress_multiplier", -1))
            == 5.0
            and float(payload.get("positive_funding_realization", -1))
            == expected_realization
            and int(payload.get("entry_delay_settlements", -1)) == 1
            and config.get("netting_assumed") is False
            and float(
                carry_config.get("positive_funding_realization", -1)
            )
            == expected_realization
            and int(carry_config.get("entry_delay_settlements", -1)) == 1
        )
        reports[label] = {
            "trend": _metrics(trend),
            "stress": _metrics(stress),
        }
        sources.append(source)

    identity_valid = identity_valid and (
        evidence.get("strategy_name") == expected_strategy
        and prefunded.get("strategy_name") == expected_strategy
        and evidence.get("bootstrap_segments", {}).get(
            "cross_source_blocks_allowed"
        )
        is False
        and prefunded.get("bootstrap_segments", {}).get(
            "cross_source_blocks_allowed"
        )
        is False
    )
    amount = (
        prefunded.get("scenarios", {})
        .get("5.00%", {})
        .get("amounts", {})
        .get("25", {})
    )
    sources.extend((evidence_source, prefunded_source))
    return {
        "identity_valid": identity_valid,
        "reports": reports,
        "edge_gate": bool(
            evidence.get("winning_edge_evidence_gate", {}).get(
                "passed", False
            )
        ),
        "income_gate": bool(
            amount.get("operational_gate", {}).get("passed", False)
        ),
        "sources": sources,
    }


def _metrics(report):
    keys = (
        "annualized_return",
        "max_drawdown",
        "sharpe_zero_rate",
        "positive_month_ratio",
        "worst_rolling_12_month_return",
        "average_overlay_allocation",
        "maximum_conservative_gross_exposure",
        "overlay_additive_return_contribution",
        "overlay_resize_cost_return",
    )
    return {key: report.get(key) for key in keys}


def _load_json(path_value: typing.Union[str, pathlib.Path]):
    path = pathlib.Path(path_value).resolve()
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError(f"JSON report is not an object: {path}")
    digest = hashlib.sha256(path.read_bytes()).hexdigest()
    return {
        "path": str(path),
        "sha256": digest,
    }, payload
