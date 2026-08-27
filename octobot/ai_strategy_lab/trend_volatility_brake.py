"""Pre-registered audit for the V18 fast-volatility brake.

The candidate keeps the V13 directional signal and static risk budget.  Its
only change is a causal 20-day volatility brake that may reduce, but never
increase, exposure between weekly signal rebalances.  Every historical market
used by this audit has already been observed and is diagnostic only.
"""

from __future__ import annotations

import argparse
import datetime
import hashlib
import json
import pathlib
import typing


SCHEMA_VERSION = 1
PROTOCOL_VERSION = "crypto_trend_fast_volatility_brake_v18"
BASELINE_CONFIG = "risk_budgeted_bear_regime_v13"
CANDIDATE_CONFIG = "fast_volatility_brake_bear_regime_v18"
PRIMARY_COST_MULTIPLIER = 3
ADVERSE_COST_MULTIPLIER = 5


def frozen_protocol() -> dict:
    return {
        "schema_version": SCHEMA_VERSION,
        "protocol_version": PROTOCOL_VERSION,
        "research_only": True,
        "orders_authorized": False,
        "automatic_promotion": False,
        "thesis": (
            "V13 under-reacts to abrupt volatility and correlation changes. "
            "A short-window ex-ante risk brake can reduce tail losses without "
            "altering or retrospectively filtering its directional signal."
        ),
        "baseline_config": BASELINE_CONFIG,
        "candidate": {
            "config": CANDIDATE_CONFIG,
            "signal": "V13 dual momentum 30/120 with BTC short-regime gate",
            "signal_rebalance_days": 7,
            "base_covariance_days": 60,
            "volatility_brake_days": 20,
            "target_annual_volatility": 0.135,
            "maximum_gross_exposure": 0.90,
            "maximum_asset_exposure": 0.315,
            "brake_rule": (
                "After each closed daily candle, estimate candidate portfolio "
                "volatility from the trailing 20 daily returns. If it exceeds "
                "13.5%, multiply all current target weights by 13.5% divided "
                "by predicted volatility. The multiplier is capped at one, "
                "so risk cannot increase before the next weekly rebalance."
            ),
            "funding": "signed historical settlements",
            "same_day_execution": (
                "close-t information changes weights for day t+1"
            ),
        },
        "evaluation": {
            "primary_cost_multiplier": PRIMARY_COST_MULTIPLIER,
            "adverse_cost_multiplier": ADVERSE_COST_MULTIPLIER,
            "diagnostic_reuse_scenarios": {
                "recent_binance": "18 assets, 2022-05 through 2026-06",
                "old_binance": "7 assets, 2020-02 through 2022-01",
                "kucoin": "19 assets, 2025-07 through 2026-07",
            },
            "known_forward_excluded_from_gate": (
                "KuCoin V3/V14 shadow from 2026-07-22 onward"
            ),
            "leave_one_asset_out": "all evaluable recent Binance omissions",
            "bootstrap": {
                "segments": ["old_binance", "recent_binance"],
                "block_months": 6,
                "simulations": 10_000,
                "seed": 20_260_827,
                "annual_return_haircut": 0.05,
            },
        },
        "direct_gate": {
            "recent_binance": {
                "annualized_return_retention_vs_v13": 0.90,
                "maximum_drawdown": 0.15,
                "sharpe_not_below_v13": True,
                "positive_month_ratio_not_below_v13": True,
                "all_leave_one_asset_out_positive": True,
            },
            "old_binance": {
                "annualized_return_retention_vs_v13": 0.80,
                "maximum_drawdown": 0.11,
                "minimum_sharpe": 2.0,
            },
            "kucoin": {
                "annualized_return_retention_vs_v13": 0.85,
                "maximum_drawdown": 0.06,
                "minimum_sharpe": 1.0,
            },
            "adverse_5x_costs": "annualized return positive in all scenarios",
        },
        "bootstrap_gate": {
            "source": "existing winning_edge_evidence_gate",
            "must_pass_all_checks": True,
        },
        "evidence_policy": {
            "diagnostic_pass_is_not_validation": True,
            "minimum_new_forward_calendar_days": 365,
            "minimum_new_forward_observed_days": 330,
            "new_forward_dates_required": True,
            "parameter_changes_create_a_new_version": True,
        },
    }


def write_protocol(output_value: typing.Union[str, pathlib.Path]) -> pathlib.Path:
    output = pathlib.Path(output_value).resolve()
    output.mkdir(parents=True, exist_ok=True)
    path = output / "protocol.json"
    protocol = frozen_protocol()
    payload = {
        **protocol,
        "protocol_sha256": _json_hash(protocol),
    }
    if path.exists():
        existing = json.loads(path.read_text(encoding="utf-8"))
        if existing != payload:
            raise ValueError("persisted V18 protocol differs from frozen code")
        return path
    path.write_text(
        json.dumps(payload, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return path


def audit_reports(
    output_value: typing.Union[str, pathlib.Path],
    *,
    recent_report: typing.Union[str, pathlib.Path],
    old_report: typing.Union[str, pathlib.Path],
    kucoin_report: typing.Union[str, pathlib.Path],
    recent_stress_report: typing.Union[str, pathlib.Path],
    old_stress_report: typing.Union[str, pathlib.Path],
    kucoin_stress_report: typing.Union[str, pathlib.Path],
    strategy_evidence: typing.Union[str, pathlib.Path],
) -> pathlib.Path:
    output = pathlib.Path(output_value).resolve()
    protocol_path = output / "protocol.json"
    if not protocol_path.is_file():
        raise FileNotFoundError("write protocol.json before auditing V18")
    protocol = frozen_protocol()
    persisted = json.loads(protocol_path.read_text(encoding="utf-8"))
    if persisted.get("protocol_sha256") != _json_hash(protocol):
        raise ValueError("persisted V18 protocol differs from frozen code")

    primary_paths = {
        "recent_binance": pathlib.Path(recent_report).resolve(),
        "old_binance": pathlib.Path(old_report).resolve(),
        "kucoin": pathlib.Path(kucoin_report).resolve(),
    }
    stress_paths = {
        "recent_binance": pathlib.Path(recent_stress_report).resolve(),
        "old_binance": pathlib.Path(old_stress_report).resolve(),
        "kucoin": pathlib.Path(kucoin_stress_report).resolve(),
    }
    primary = {
        name: _read_pair(path, PRIMARY_COST_MULTIPLIER)
        for name, path in primary_paths.items()
    }
    stress = {
        name: _read_pair(path, ADVERSE_COST_MULTIPLIER)
        for name, path in stress_paths.items()
    }
    evidence_path = pathlib.Path(strategy_evidence).resolve()
    evidence = json.loads(evidence_path.read_text(encoding="utf-8"))
    evidence_gate = evidence.get("winning_edge_evidence_gate", {})

    recent = primary["recent_binance"]
    old = primary["old_binance"]
    kucoin = primary["kucoin"]
    recent_loao = recent["candidate"].get("leave_one_asset_out", {})
    checks = {
        "recent_return_retention_at_least_90pct": _retention(
            recent
        ) >= 0.90,
        "recent_drawdown_at_most_15pct": (
            recent["candidate"]["max_drawdown"] <= 0.15
        ),
        "recent_sharpe_not_below_v13": (
            recent["candidate"]["sharpe_zero_rate"]
            >= recent["baseline"]["sharpe_zero_rate"]
        ),
        "recent_positive_month_ratio_not_below_v13": (
            recent["candidate"]["positive_month_ratio"]
            >= recent["baseline"]["positive_month_ratio"]
        ),
        "recent_all_leave_one_asset_out_positive": bool(recent_loao)
        and all(value["total_return"] > 0 for value in recent_loao.values()),
        "old_return_retention_at_least_80pct": _retention(old) >= 0.80,
        "old_drawdown_at_most_11pct": (
            old["candidate"]["max_drawdown"] <= 0.11
        ),
        "old_sharpe_at_least_2": (
            old["candidate"]["sharpe_zero_rate"] >= 2.0
        ),
        "kucoin_return_retention_at_least_85pct": (
            _retention(kucoin) >= 0.85
        ),
        "kucoin_drawdown_at_most_6pct": (
            kucoin["candidate"]["max_drawdown"] <= 0.06
        ),
        "kucoin_sharpe_at_least_1": (
            kucoin["candidate"]["sharpe_zero_rate"] >= 1.0
        ),
        "positive_at_5x_costs_all_scenarios": all(
            values["candidate"]["annualized_return"] > 0
            for values in stress.values()
        ),
        "bootstrap_winning_edge_gate_passed": bool(
            evidence_gate.get("passed")
        ),
    }
    summary = {
        name: {
            "baseline": _summary(values["baseline"]),
            "candidate": _summary(values["candidate"]),
            "annualized_return_retention": _retention(values),
        }
        for name, values in primary.items()
    }
    stress_summary = {
        name: {
            "baseline": _summary(values["baseline"]),
            "candidate": _summary(values["candidate"]),
        }
        for name, values in stress.items()
    }
    report = {
        "schema_version": SCHEMA_VERSION,
        "protocol_version": PROTOCOL_VERSION,
        "protocol_sha256": _json_hash(protocol),
        "created_at": datetime.datetime.now(datetime.timezone.utc).isoformat(),
        "research_only": True,
        "diagnostic_reuse": True,
        "orders_authorized": False,
        "automatic_promotion": False,
        "candidate_gate": {
            "passed": all(checks.values()),
            "checks": checks,
            "interpretation": (
                "A pass would justify only a new forward shadow. These "
                "historical periods have already been observed."
            ),
        },
        "primary_3x": summary,
        "adverse_5x": stress_summary,
        "bootstrap_winning_edge_evidence_gate": evidence_gate,
        "artifacts": {
            "protocol": _artifact(protocol_path),
            "primary_reports": {
                name: _artifact(path) for name, path in primary_paths.items()
            },
            "stress_reports": {
                name: _artifact(path) for name, path in stress_paths.items()
            },
            "strategy_evidence": _artifact(evidence_path),
        },
    }
    path = output / "audit.json"
    path.write_text(
        json.dumps(report, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return path


def _read_pair(path: pathlib.Path, multiplier: int) -> dict:
    report = json.loads(path.read_text(encoding="utf-8"))
    reports = report.get("reports", {})
    suffix = f"_cost_stress_{multiplier}x"
    baseline_name = BASELINE_CONFIG + suffix
    candidate_name = CANDIDATE_CONFIG + suffix
    missing = [
        name for name in (baseline_name, candidate_name) if name not in reports
    ]
    if missing:
        raise ValueError(f"trend report is missing V18 pair: {missing}")
    return {
        "baseline": reports[baseline_name],
        "candidate": reports[candidate_name],
    }


def _retention(values: dict) -> float:
    baseline = values["baseline"]["annualized_return"]
    candidate = values["candidate"]["annualized_return"]
    if baseline <= 0:
        raise ValueError("V18 retention baseline must be positive")
    return candidate / baseline


def _summary(report: dict) -> dict:
    return {
        key: report.get(key)
        for key in (
            "annualized_return",
            "max_drawdown",
            "sharpe_zero_rate",
            "positive_month_ratio",
            "worst_rolling_12_month_return",
            "total_turnover",
            "total_cost_return",
            "average_gross_exposure",
            "volatility_brake_events",
            "volatility_brake_turnover",
            "average_volatility_brake_multiplier",
            "minimum_volatility_brake_multiplier",
        )
    }


def _artifact(path: pathlib.Path) -> dict:
    return {
        "path": str(path),
        "sha256": _file_hash(path),
    }


def _file_hash(path: pathlib.Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _json_hash(value: dict) -> str:
    encoded = json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-directory", required=True)
    parser.add_argument("--write-protocol-only", action="store_true")
    parser.add_argument("--recent-report")
    parser.add_argument("--old-report")
    parser.add_argument("--kucoin-report")
    parser.add_argument("--recent-stress-report")
    parser.add_argument("--old-stress-report")
    parser.add_argument("--kucoin-stress-report")
    parser.add_argument("--strategy-evidence")
    return parser.parse_args()


def main() -> int:
    args = _parse_args()
    protocol_path = write_protocol(args.output_directory)
    if args.write_protocol_only:
        print(json.dumps({"protocol_path": str(protocol_path)}, indent=2))
        return 0
    required = {
        "recent_report": args.recent_report,
        "old_report": args.old_report,
        "kucoin_report": args.kucoin_report,
        "recent_stress_report": args.recent_stress_report,
        "old_stress_report": args.old_stress_report,
        "kucoin_stress_report": args.kucoin_stress_report,
        "strategy_evidence": args.strategy_evidence,
    }
    missing = [name for name, value in required.items() if not value]
    if missing:
        raise ValueError(f"missing V18 audit arguments: {missing}")
    audit_path = audit_reports(
        args.output_directory,
        **required,
    )
    print(json.dumps({"audit_path": str(audit_path)}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
