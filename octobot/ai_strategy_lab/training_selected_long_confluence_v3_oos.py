"""Single-query 2025/2026 evaluator for frozen long confluence V3.

The module has no order path.  It verifies the immutable training selection,
evaluates 2025 once, and opens the 2026 lock only after every confirmation gate
passes.
"""

from __future__ import annotations

import argparse
import datetime
import json
import pathlib
import typing

from octobot.ai_strategy_lab import cointegration_pairs_v1 as common
from octobot.ai_strategy_lab import training_selected_long_confluence_v3 as selection


SCHEMA_VERSION = 1
PROTOCOL_VERSION = selection.PROTOCOL_VERSION
EXPECTED_PROTOCOL_FILE_SHA256 = (
    "29c82016f9648073c474783b36fbecfcb72869572e0cf4277effd98ea7434ba9"
)
EXPECTED_SELECTION_MODEL_FILE_SHA256 = (
    "995c3250f61c65db17c468a732abbc57adcf2acf7020427b75cfb8f771e9ed2c"
)
EXPECTED_SELECTION_MODEL_CONTENT_SHA256 = (
    "97ecf3192e227255944eedad5726fb4bd99d5c4a4388f36b3a6a2aa5fded4ef9"
)
trainer = selection.parent
market_loader = trainer.parent


def _artifact(path: pathlib.Path) -> dict:
    return {
        "path": str(path),
        "bytes": path.stat().st_size,
        "sha256": common._sha256(path),
    }


def verify_frozen_inputs(protocol_value, model_value) -> tuple[dict, dict]:
    protocol_path = pathlib.Path(protocol_value).resolve()
    model_path = pathlib.Path(model_value).resolve()
    if common._sha256(protocol_path) != EXPECTED_PROTOCOL_FILE_SHA256:
        raise ValueError("V3 protocol file hash differs")
    if common._sha256(model_path) != EXPECTED_SELECTION_MODEL_FILE_SHA256:
        raise ValueError("V3 selection-model file hash differs")
    protocol = selection.write_or_verify_protocol(protocol_path)
    model = json.loads(model_path.read_text(encoding="utf-8"))
    if protocol["protocol_sha256"] != common._json_hash(
        selection.frozen_protocol()
    ):
        raise ValueError("V3 logical protocol hash differs")
    content = {key: value for key, value in model.items() if key != "content_sha256"}
    if (
        model.get("content_sha256") != EXPECTED_SELECTION_MODEL_CONTENT_SHA256
        or common._json_hash(content) != EXPECTED_SELECTION_MODEL_CONTENT_SHA256
        or model.get("protocol_sha256") != protocol["protocol_sha256"]
        or model.get("selected_configuration", {}).get("configuration_id")
        != selection.SELECTED_CONFIGURATION_ID
        or model.get("confirmation_evaluated") is not False
        or model.get("locked_test_evaluated") is not False
        or model.get("orders_authorized") is not False
        or model.get("paper_orders_authorized") is not False
    ):
        raise ValueError("V3 selection-model content or seals differ")
    return protocol, model


def _finish_checks(checks: dict) -> dict:
    return {
        "checks": checks,
        "passed_checks": sum(checks.values()),
        "total_checks": len(checks),
        "passed": all(checks.values()),
    }


def _base_gate(report: dict, specification: dict) -> dict:
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
    model_value,
    futures_values,
    spot_values,
    flow_manifest_values,
    flow_cache_value,
    funding_values,
    output_root_value,
) -> dict:
    """Evaluate the frozen model sequentially without any refit."""

    protocol_path = pathlib.Path(protocol_value).resolve()
    model_path = pathlib.Path(model_value).resolve()
    protocol, model = verify_frozen_inputs(protocol_path, model_path)
    market, artifacts = market_loader.load_market(
        futures_values,
        spot_values,
        flow_manifest_values,
        flow_cache_value,
        funding_values,
    )
    dependencies = {
        "selection": pathlib.Path(selection.__file__).resolve(),
        "trainer_and_frozen_targets": pathlib.Path(trainer.__file__).resolve(),
        "confluence_and_market_loader": pathlib.Path(
            market_loader.__file__
        ).resolve(),
        "accounting": pathlib.Path(
            market_loader.parent.execution_parent.__file__
        ).resolve(),
    }
    artifacts["oos_evaluator"] = _artifact(pathlib.Path(__file__).resolve())
    artifacts["dependencies"] = {
        name: _artifact(path) for name, path in sorted(dependencies.items())
    }
    artifacts["frozen_protocol"] = _artifact(protocol_path)
    artifacts["frozen_selection_model"] = _artifact(model_path)
    source_bundle_sha256 = common._json_hash(artifacts)
    targets = trainer.build_target_matrix(
        market, model["selected_configuration"]
    )

    confirmation = trainer.simulate_period(
        market,
        selection.CONFIRMATION_START,
        selection.CONFIRMATION_END,
        target_matrix=targets,
        include_trajectory=True,
    )
    confirmation_trajectory = confirmation.pop("_trajectory")
    confirmation_stress = trainer.simulate_period(
        market,
        selection.CONFIRMATION_START,
        selection.CONFIRMATION_END,
        target_matrix=targets,
        cost_multiplier=trainer.STRESS_COST_MULTIPLIER,
    )
    confirmation_quarters = [
        trainer.simulate_period(market, start, end, target_matrix=targets)
        for start, end in selection.CONFIRMATION_QUARTERS
    ]
    positive_quarters = sum(
        report["total_return"] > 0 for report in confirmation_quarters
    )
    confirmation_specification = protocol["confirmation"]["gate"]
    base_confirmation_gate = _base_gate(
        confirmation, confirmation_specification
    )
    confirmation_gate = _finish_checks(
        {
            **base_confirmation_gate["checks"],
            "stress_total_return_positive": (
                confirmation_stress["total_return"] > 0
            ),
            "minimum_positive_quarters": (
                positive_quarters
                >= confirmation_specification["minimum_positive_quarters"]
            ),
            "required_quarters_present": (
                len(confirmation_quarters)
                == confirmation_specification["required_quarters"]
            ),
        }
    )

    locked = None
    locked_stress = None
    locked_trajectory = None
    locked_gate = {
        "passed": False,
        "not_evaluated": not confirmation_gate["passed"],
        "reason": (
            "confirmation_gate_failed" if not confirmation_gate["passed"] else None
        ),
    }
    if confirmation_gate["passed"]:
        locked = trainer.simulate_period(
            market,
            selection.LOCKED_START,
            selection.LOCKED_END,
            target_matrix=targets,
            include_trajectory=True,
        )
        locked_trajectory = locked.pop("_trajectory")
        locked_stress = trainer.simulate_period(
            market,
            selection.LOCKED_START,
            selection.LOCKED_END,
            target_matrix=targets,
            cost_multiplier=trainer.STRESS_COST_MULTIPLIER,
        )
        locked_specification = protocol["locked_test"]["gate"]
        base_locked_gate = _base_gate(locked, locked_specification)
        locked_gate = _finish_checks(
            {
                **base_locked_gate["checks"],
                "stress_total_return_positive": locked_stress["total_return"] > 0,
            }
        )
    historical_candidate = confirmation_gate["passed"] and locked_gate["passed"]

    output_root = pathlib.Path(output_root_value).resolve()
    experiment = output_root / (
        "training-selected-long-confluence-v3-oos-"
        + protocol["protocol_sha256"][:12]
        + "-"
        + source_bundle_sha256[:12]
    )
    experiment.mkdir(parents=True, exist_ok=False)
    confirmation_trajectory_path = experiment / "confirmation-trajectory.json"
    common._atomic_json(
        confirmation_trajectory_path,
        {
            "schema_version": SCHEMA_VERSION,
            "protocol_sha256": protocol["protocol_sha256"],
            "source_bundle_sha256": source_bundle_sha256,
            **confirmation_trajectory,
        },
    )
    locked_trajectory_path = None
    if locked_trajectory is not None:
        locked_trajectory_path = experiment / "locked-trajectory.json"
        common._atomic_json(
            locked_trajectory_path,
            {
                "schema_version": SCHEMA_VERSION,
                "protocol_sha256": protocol["protocol_sha256"],
                "source_bundle_sha256": source_bundle_sha256,
                **locked_trajectory,
            },
        )
    report = {
        "schema_version": SCHEMA_VERSION,
        "protocol_version": PROTOCOL_VERSION,
        "created_at": datetime.datetime.now(market_loader.parent.UTC).isoformat(),
        "research_only": True,
        "public_data_only": True,
        "credentials_used": False,
        "orders_authorized": False,
        "paper_orders_authorized": False,
        "automatic_promotion": False,
        "protocol_path": str(protocol_path),
        "protocol_file_sha256": common._sha256(protocol_path),
        "protocol_sha256": protocol["protocol_sha256"],
        "selection_model_path": str(model_path),
        "selection_model_file_sha256": common._sha256(model_path),
        "selection_model_content_sha256": model["content_sha256"],
        "selected_configuration": model["selected_configuration"],
        "source_bundle_sha256": source_bundle_sha256,
        "source_artifacts": artifacts,
        "development_recomputed": False,
        "confirmation": confirmation,
        "confirmation_stress": confirmation_stress,
        "confirmation_quarters": confirmation_quarters,
        "confirmation_positive_quarters": positive_quarters,
        "confirmation_gate": confirmation_gate,
        "confirmation_trajectory": {
            "path": str(confirmation_trajectory_path),
            "sha256": common._sha256(confirmation_trajectory_path),
        },
        "locked_test": {
            "authorized_to_open": confirmation_gate["passed"],
            "materialized": locked is not None,
            "report": locked,
            "stress_report": locked_stress,
            "gate": locked_gate,
            "trajectory": (
                {
                    "path": str(locked_trajectory_path),
                    "sha256": common._sha256(locked_trajectory_path),
                }
                if locked_trajectory_path is not None
                else None
            ),
        },
        "historical_candidate": historical_candidate,
        "forward_validation": {
            **protocol["forward_gate"],
            "started": False,
            "passed": False,
            "automatic_promotion": False,
        },
        "verdict": (
            "HISTORICAL_CANDIDATE_REQUIRES_180D_FORWARD"
            if historical_candidate
            else (
                "REJECTED_LOCKED_TEST"
                if locked is not None
                else "REJECTED_CONFIRMATION_LOCK_REMAINS_SEALED"
            )
        ),
        "results_do_not_authorize_orders": True,
    }
    report_path = experiment / "report.json"
    common._atomic_json(report_path, report)
    manifest = {
        "schema_version": SCHEMA_VERSION,
        "protocol_sha256": protocol["protocol_sha256"],
        "selection_model_file_sha256": common._sha256(model_path),
        "source_bundle_sha256": source_bundle_sha256,
        "report_path": str(report_path),
        "report_sha256": common._sha256(report_path),
        "confirmation_trajectory_path": str(confirmation_trajectory_path),
        "confirmation_trajectory_sha256": common._sha256(
            confirmation_trajectory_path
        ),
        "locked_test_materialized": locked is not None,
        "locked_trajectory_path": (
            str(locked_trajectory_path) if locked_trajectory_path else None
        ),
        "locked_trajectory_sha256": (
            common._sha256(locked_trajectory_path)
            if locked_trajectory_path
            else None
        ),
        "historical_candidate": historical_candidate,
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
    subparsers = parser.add_subparsers(dest="command", required=True)
    evaluate = subparsers.add_parser("evaluate-oos")
    evaluate.add_argument("--protocol", required=True)
    evaluate.add_argument("--selection-model", required=True)
    evaluate.add_argument("--futures-collector", action="append", required=True)
    evaluate.add_argument("--spot-collector", action="append", required=True)
    evaluate.add_argument("--flow-manifest", action="append", required=True)
    evaluate.add_argument("--flow-cache", required=True)
    evaluate.add_argument("--funding", action="append", required=True)
    evaluate.add_argument("--output-root", required=True)
    return parser


def main(argv=None) -> int:
    arguments = _parser().parse_args(argv)
    result = evaluate_oos(
        arguments.protocol,
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
