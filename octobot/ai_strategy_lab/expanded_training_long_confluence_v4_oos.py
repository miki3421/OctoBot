"""Single-query January-June 2026 evaluator for frozen V4.

The evaluator verifies the expanded-training lineage and one selected model,
never refits or recomputes training, and has no order path.
"""

from __future__ import annotations

import argparse
import datetime
import json
import pathlib

from octobot.ai_strategy_lab import cointegration_pairs_v1 as common
from octobot.ai_strategy_lab import expanded_training_long_confluence_v4 as parent


SCHEMA_VERSION = 1
PROTOCOL_VERSION = parent.PROTOCOL_VERSION
EXPECTED_PROTOCOL_FILE_SHA256 = (
    "6b163e3221911e048e18c95f5fa7697e64fe426b89950086faccb9470ad7872a"
)
EXPECTED_TRAINING_REPORT_SHA256 = (
    "1d0eb3af30646939d5c88d4a641f0fb4fcccf0b7abc7889c4821562b1653c8b2"
)
EXPECTED_TRAINING_MANIFEST_SHA256 = (
    "3dd95af1f4e56293857f42bac753ce3558d26028ac6e5e1e986bb4c1ef3c083d"
)
EXPECTED_MODEL_FILE_SHA256 = (
    "6d17aae4e351679667bd440603d27fceabe2b534bfb11bc0646feb1a190fee2e"
)
EXPECTED_MODEL_CONTENT_SHA256 = (
    "7af7b1b2345622ca01d2f6cbd273fce050d71e7571d46f5b4c73b264816e6687"
)


def _artifact(path: pathlib.Path) -> dict:
    return {
        "path": str(path),
        "bytes": path.stat().st_size,
        "sha256": common._sha256(path),
    }


def verify_frozen_lineage(
    protocol_value,
    training_report_value,
    training_manifest_value,
    model_value,
) -> tuple[dict, dict, dict]:
    protocol_path = pathlib.Path(protocol_value).resolve()
    report_path = pathlib.Path(training_report_value).resolve()
    manifest_path = pathlib.Path(training_manifest_value).resolve()
    model_path = pathlib.Path(model_value).resolve()
    expected = {
        protocol_path: EXPECTED_PROTOCOL_FILE_SHA256,
        report_path: EXPECTED_TRAINING_REPORT_SHA256,
        manifest_path: EXPECTED_TRAINING_MANIFEST_SHA256,
        model_path: EXPECTED_MODEL_FILE_SHA256,
    }
    for path, digest in expected.items():
        if common._sha256(path) != digest:
            raise ValueError(f"frozen V4 lineage hash differs: {path.name}")
    protocol = parent.write_or_verify_protocol(protocol_path)
    report = json.loads(report_path.read_text(encoding="utf-8"))
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    model = json.loads(model_path.read_text(encoding="utf-8"))
    model_content = {
        key: value for key, value in model.items() if key != "content_sha256"
    }
    if (
        protocol["protocol_sha256"] != common._json_hash(parent.frozen_protocol())
        or report.get("protocol_sha256") != protocol["protocol_sha256"]
        or manifest.get("report_sha256") != EXPECTED_TRAINING_REPORT_SHA256
        or manifest.get("selected_model_sha256") != EXPECTED_MODEL_FILE_SHA256
        or report.get("selected_model_sha256") != EXPECTED_MODEL_FILE_SHA256
        or model.get("content_sha256") != EXPECTED_MODEL_CONTENT_SHA256
        or common._json_hash(model_content) != EXPECTED_MODEL_CONTENT_SHA256
        or model.get("protocol_sha256") != protocol["protocol_sha256"]
        or model.get("oos_2026_evaluated") is not False
        or report.get("oos_2026_evaluated") is not False
        or manifest.get("oos_2026_evaluated") is not False
        or model.get("orders_authorized") is not False
        or model.get("paper_orders_authorized") is not False
    ):
        raise ValueError("frozen V4 lineage content or seals differ")
    if model["selected_configuration"] not in parent.candidate_configurations():
        raise ValueError("frozen V4 model is outside the preregistered grid")
    return protocol, report, model


def _finish_checks(checks: dict) -> dict:
    return {
        "checks": checks,
        "passed_checks": sum(checks.values()),
        "total_checks": len(checks),
        "passed": all(checks.values()),
    }


def _oos_gate(report: dict, stress: dict, specification: dict) -> dict:
    profit_factor = report["profit_factor"]
    profit_factor_pass = (
        report["total_return"] > 0
        if profit_factor is None
        else profit_factor >= specification["minimum_profit_factor"]
    )
    return _finish_checks(
        {
            "minimum_blocks": report["blocks"] >= specification["minimum_blocks"],
            "minimum_invested_blocks": (
                report["invested_blocks"]
                >= specification["minimum_invested_blocks"]
            ),
            "positive_total_return": report["total_return"] > 0,
            "stress_total_return_positive": stress["total_return"] > 0,
            "minimum_annualized_return": (
                report["annualized_return"]
                >= specification["minimum_annualized_return"]
            ),
            "minimum_annualized_market_alpha": (
                report["annualized_market_alpha"]
                >= specification["minimum_annualized_market_alpha"]
            ),
            "minimum_sharpe": (
                report["sharpe_zero_rate"] >= specification["minimum_sharpe"]
            ),
            "minimum_profit_factor": profit_factor_pass,
            "maximum_drawdown": (
                report["maximum_drawdown"] <= specification["maximum_drawdown"]
            ),
            "minimum_positive_month_ratio": (
                report["positive_month_ratio"]
                >= specification["minimum_positive_month_ratio"]
            ),
            "maximum_absolute_market_beta": (
                abs(report["market_beta"])
                <= specification["maximum_absolute_market_beta"]
            ),
            "maximum_symbol_absolute_contribution_share": (
                report["maximum_symbol_absolute_contribution_share"]
                <= specification["maximum_symbol_absolute_contribution_share"]
            ),
        }
    )


def evaluate_oos(
    protocol_value,
    training_report_value,
    training_manifest_value,
    model_value,
    futures_values,
    spot_values,
    flow_manifest_values,
    flow_cache_value,
    funding_values,
    output_root_value,
) -> dict:
    protocol_path = pathlib.Path(protocol_value).resolve()
    training_report_path = pathlib.Path(training_report_value).resolve()
    training_manifest_path = pathlib.Path(training_manifest_value).resolve()
    model_path = pathlib.Path(model_value).resolve()
    protocol, _training_report, model = verify_frozen_lineage(
        protocol_path,
        training_report_path,
        training_manifest_path,
        model_path,
    )
    market, artifacts = parent.engine.parent.load_market(
        futures_values,
        spot_values,
        flow_manifest_values,
        flow_cache_value,
        funding_values,
    )
    dependencies = {
        "frozen_v4_trainer_and_targets": pathlib.Path(parent.__file__).resolve(),
        "v2_simulation_engine": pathlib.Path(parent.engine.__file__).resolve(),
        "confluence_market_loader": pathlib.Path(
            parent.engine.parent.__file__
        ).resolve(),
        "accounting": pathlib.Path(
            parent.engine.parent.parent.execution_parent.__file__
        ).resolve(),
    }
    artifacts["oos_evaluator"] = _artifact(pathlib.Path(__file__).resolve())
    artifacts["dependencies"] = {
        name: _artifact(path) for name, path in sorted(dependencies.items())
    }
    artifacts["frozen_protocol"] = _artifact(protocol_path)
    artifacts["training_report"] = _artifact(training_report_path)
    artifacts["training_manifest"] = _artifact(training_manifest_path)
    artifacts["selected_model"] = _artifact(model_path)
    source_bundle_sha256 = common._json_hash(artifacts)

    targets = parent.build_target_matrix(
        market, model["selected_configuration"]
    )
    oos = parent.engine.simulate_period(
        market,
        parent.OOS_START,
        parent.OOS_END,
        target_matrix=targets,
        include_trajectory=True,
    )
    trajectory = oos.pop("_trajectory")
    stress = parent.engine.simulate_period(
        market,
        parent.OOS_START,
        parent.OOS_END,
        target_matrix=targets,
        cost_multiplier=parent.engine.STRESS_COST_MULTIPLIER,
    )
    gate = _oos_gate(oos, stress, protocol["oos_test"]["gate"])

    output_root = pathlib.Path(output_root_value).resolve()
    experiment = output_root / (
        "expanded-training-long-confluence-v4-oos-"
        + protocol["protocol_sha256"][:12]
        + "-"
        + source_bundle_sha256[:12]
    )
    experiment.mkdir(parents=True, exist_ok=False)
    trajectory_path = experiment / "oos-trajectory.json"
    common._atomic_json(
        trajectory_path,
        {
            "schema_version": SCHEMA_VERSION,
            "protocol_sha256": protocol["protocol_sha256"],
            "source_bundle_sha256": source_bundle_sha256,
            **trajectory,
        },
    )
    report = {
        "schema_version": SCHEMA_VERSION,
        "protocol_version": PROTOCOL_VERSION,
        "created_at": datetime.datetime.now(
            parent.engine.parent.parent.UTC
        ).isoformat(),
        "research_only": True,
        "public_data_only": True,
        "credentials_used": False,
        "orders_authorized": False,
        "paper_orders_authorized": False,
        "automatic_promotion": False,
        "protocol_path": str(protocol_path),
        "protocol_file_sha256": common._sha256(protocol_path),
        "protocol_sha256": protocol["protocol_sha256"],
        "training_report_path": str(training_report_path),
        "training_report_sha256": common._sha256(training_report_path),
        "training_manifest_path": str(training_manifest_path),
        "training_manifest_sha256": common._sha256(training_manifest_path),
        "selected_model_path": str(model_path),
        "selected_model_file_sha256": common._sha256(model_path),
        "selected_model_content_sha256": model["content_sha256"],
        "selected_configuration": model["selected_configuration"],
        "source_bundle_sha256": source_bundle_sha256,
        "source_artifacts": artifacts,
        "training_recomputed": False,
        "oos": oos,
        "oos_stress": stress,
        "oos_gate": gate,
        "oos_trajectory": {
            "path": str(trajectory_path),
            "sha256": common._sha256(trajectory_path),
        },
        "historical_candidate": gate["passed"],
        "replacement_model_authorized": False,
        "forward_validation": {
            **protocol["forward_gate"],
            "started": False,
            "passed": False,
            "automatic_promotion": False,
        },
        "verdict": (
            "HISTORICAL_CANDIDATE_REQUIRES_180D_FORWARD"
            if gate["passed"]
            else "REJECTED_2026_OOS_NO_REPLACEMENT_MODEL"
        ),
        "results_do_not_authorize_orders": True,
    }
    report_path = experiment / "report.json"
    common._atomic_json(report_path, report)
    manifest = {
        "schema_version": SCHEMA_VERSION,
        "protocol_sha256": protocol["protocol_sha256"],
        "selected_model_file_sha256": common._sha256(model_path),
        "source_bundle_sha256": source_bundle_sha256,
        "report_path": str(report_path),
        "report_sha256": common._sha256(report_path),
        "oos_trajectory_path": str(trajectory_path),
        "oos_trajectory_sha256": common._sha256(trajectory_path),
        "historical_candidate": gate["passed"],
        "replacement_model_authorized": False,
        "orders_authorized": False,
        "paper_orders_authorized": False,
        "automatic_promotion": False,
    }
    manifest["content_sha256"] = common._json_hash(manifest)
    common._atomic_json(experiment / "manifest.json", manifest)
    return {
        "directory": str(experiment),
        "report": report,
        "manifest": manifest,
    }


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--protocol", required=True)
    parser.add_argument("--training-report", required=True)
    parser.add_argument("--training-manifest", required=True)
    parser.add_argument("--selection-model", required=True)
    parser.add_argument("--futures-collector", action="append", required=True)
    parser.add_argument("--spot-collector", action="append", required=True)
    parser.add_argument("--flow-manifest", action="append", required=True)
    parser.add_argument("--flow-cache", required=True)
    parser.add_argument("--funding", action="append", required=True)
    parser.add_argument("--output-root", required=True)
    return parser


def main(argv=None) -> int:
    arguments = _parser().parse_args(argv)
    result = evaluate_oos(
        arguments.protocol,
        arguments.training_report,
        arguments.training_manifest,
        arguments.selection_model,
        arguments.futures_collector,
        arguments.spot_collector,
        arguments.flow_manifest,
        arguments.flow_cache,
        arguments.funding,
        arguments.output_root,
    )
    print(json.dumps(result, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
