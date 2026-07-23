import json

from octobot.ai_strategy_lab import carry_robustness


def test_robustness_audit_fails_closed_on_one_direct_check(tmp_path):
    half_paths = _scenario_files(
        tmp_path,
        "half",
        carry_robustness.HALF_STRATEGY,
        0.5,
        recent_return=0.12,
    )
    zero_paths = _scenario_files(
        tmp_path,
        "zero",
        carry_robustness.ZERO_STRATEGY,
        0.0,
        recent_return=0.11,
    )

    report = carry_robustness.audit_v14_robustness(
        half_old_report=half_paths["old"],
        half_recent_report=half_paths["recent"],
        half_kucoin_report=half_paths["kucoin"],
        half_evidence=half_paths["evidence"],
        half_prefunded=half_paths["prefunded"],
        zero_old_report=zero_paths["old"],
        zero_recent_report=zero_paths["recent"],
        zero_kucoin_report=zero_paths["kucoin"],
        zero_evidence=zero_paths["evidence"],
        zero_prefunded=zero_paths["prefunded"],
    )

    assert report["robustness_gate"]["passed"] is False
    assert (
        report["robustness_gate"]["checks"][
            "recent_return_at_least_v13"
        ]
        is False
    )
    assert report["adverse_execution_scenario"]["edge_gate"] is True
    assert report["adverse_execution_scenario"]["income_gate"] is True
    assert (
        report["zero_positive_funding_diagnostic"]["is_promotion_gate"]
        is False
    )
    assert report["orders_authorized"] is False


def _scenario_files(
    root,
    prefix,
    strategy,
    realization,
    *,
    recent_return,
):
    paths = {}
    for period in ("old", "recent", "kucoin"):
        stress_return = 0.13
        if period == "recent":
            stress_return = recent_return
        payload = {
            "research_only": True,
            "orders_authorized": False,
            "carry_cost_stress_multiplier": 5.0,
            "positive_funding_realization": realization,
            "entry_delay_settlements": 1,
            "reports": {
                carry_robustness.TREND_STRATEGY: _metrics(0.13, 1.0),
                strategy: {
                    **_metrics(stress_return, 2.1),
                    "config": {
                        "netting_assumed": False,
                        "carry": {
                            "positive_funding_realization": realization,
                            "entry_delay_settlements": 1,
                        },
                    },
                },
            },
        }
        if period == "recent":
            payload["reports"][strategy]["sharpe_zero_rate"] = 0.94
        path = root / f"{prefix}-{period}.json"
        path.write_text(json.dumps(payload), encoding="utf-8")
        paths[period] = path

    evidence = root / f"{prefix}-evidence.json"
    evidence.write_text(
        json.dumps(
            {
                "strategy_name": strategy,
                "bootstrap_segments": {
                    "cross_source_blocks_allowed": False
                },
                "winning_edge_evidence_gate": {"passed": True},
            }
        ),
        encoding="utf-8",
    )
    prefunded = root / f"{prefix}-prefunded.json"
    prefunded.write_text(
        json.dumps(
            {
                "strategy_name": strategy,
                "bootstrap_segments": {
                    "cross_source_blocks_allowed": False
                },
                "scenarios": {
                    "5.00%": {
                        "amounts": {
                            "25": {
                                "operational_gate": {"passed": True}
                            }
                        }
                    }
                },
            }
        ),
        encoding="utf-8",
    )
    paths["evidence"] = evidence
    paths["prefunded"] = prefunded
    return paths


def _metrics(annualized_return, sharpe):
    return {
        "annualized_return": annualized_return,
        "max_drawdown": 0.10,
        "sharpe_zero_rate": sharpe,
        "positive_month_ratio": 0.60,
        "worst_rolling_12_month_return": 0.0,
    }
