import json

from octobot.ai_strategy_lab import trend_volatility_brake


def _trend_report(multiplier, *, recent=False, max_drawdown=0.10):
    suffix = f"_cost_stress_{multiplier}x"
    baseline = {
        "annualized_return": 0.10,
        "max_drawdown": 0.12,
        "sharpe_zero_rate": 2.0,
        "positive_month_ratio": 0.60,
        "worst_rolling_12_month_return": 0.01,
        "total_turnover": 10.0,
        "total_cost_return": 0.02,
        "average_gross_exposure": 0.20,
        "volatility_brake_events": 0,
        "volatility_brake_turnover": 0.0,
        "average_volatility_brake_multiplier": 1.0,
        "minimum_volatility_brake_multiplier": 1.0,
    }
    candidate = {
        **baseline,
        "annualized_return": 0.095,
        "max_drawdown": max_drawdown,
        "sharpe_zero_rate": 2.1,
        "volatility_brake_events": 3,
        "volatility_brake_turnover": 0.2,
        "average_volatility_brake_multiplier": 0.98,
        "minimum_volatility_brake_multiplier": 0.7,
    }
    if recent:
        candidate["leave_one_asset_out"] = {
            "ETH": {"total_return": 0.1},
            "SOL": {"total_return": 0.2},
        }
    return {
        "reports": {
            trend_volatility_brake.BASELINE_CONFIG + suffix: baseline,
            trend_volatility_brake.CANDIDATE_CONFIG + suffix: candidate,
        }
    }


def test_protocol_is_content_addressed_and_idempotent(tmp_path):
    first = trend_volatility_brake.write_protocol(tmp_path)
    second = trend_volatility_brake.write_protocol(tmp_path)

    assert first == second
    payload = json.loads(first.read_text(encoding="utf-8"))
    assert payload["protocol_version"] == (
        trend_volatility_brake.PROTOCOL_VERSION
    )
    assert payload["orders_authorized"] is False
    assert payload["automatic_promotion"] is False
    assert payload["protocol_sha256"] == trend_volatility_brake._json_hash(
        trend_volatility_brake.frozen_protocol()
    )


def test_audit_requires_every_frozen_gate(tmp_path):
    output = tmp_path / "output"
    trend_volatility_brake.write_protocol(output)
    reports = {}
    for name in ("recent", "old", "kucoin"):
        path = tmp_path / f"{name}.json"
        path.write_text(
            json.dumps(
                _trend_report(
                    3,
                    recent=name == "recent",
                    max_drawdown=0.05 if name == "kucoin" else 0.10,
                )
            ),
            encoding="utf-8",
        )
        reports[name] = path
    stress_reports = {}
    for name in ("recent", "old", "kucoin"):
        path = tmp_path / f"{name}-stress.json"
        path.write_text(
            json.dumps(_trend_report(5)),
            encoding="utf-8",
        )
        stress_reports[name] = path
    evidence = tmp_path / "evidence.json"
    evidence.write_text(
        json.dumps(
            {
                "winning_edge_evidence_gate": {
                    "passed": True,
                    "checks": {"example": True},
                }
            }
        ),
        encoding="utf-8",
    )

    path = trend_volatility_brake.audit_reports(
        output,
        recent_report=reports["recent"],
        old_report=reports["old"],
        kucoin_report=reports["kucoin"],
        recent_stress_report=stress_reports["recent"],
        old_stress_report=stress_reports["old"],
        kucoin_stress_report=stress_reports["kucoin"],
        strategy_evidence=evidence,
    )

    audit = json.loads(path.read_text(encoding="utf-8"))
    assert audit["candidate_gate"]["passed"] is True, audit[
        "candidate_gate"
    ]["checks"]
    assert all(audit["candidate_gate"]["checks"].values())
    assert audit["research_only"] is True
    assert audit["diagnostic_reuse"] is True
    assert audit["orders_authorized"] is False
