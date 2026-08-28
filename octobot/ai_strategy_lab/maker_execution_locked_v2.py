"""One-shot locked audit for learned BTC passive execution V2.

The parent model and every pre-lock evidence artifact are content-bound before
this evaluator can read the 20--26 August lock.  The model is never refitted,
the feature and selection code is inherited unchanged, and the only possible
promotion is an orderless execution-overlay shadow.  This module has no
exchange client and cannot create paper or real orders.
"""

from __future__ import annotations

import argparse
import json
import pathlib
import sqlite3
import typing

import numpy

from octobot.ai_strategy_lab import maker_execution_v1 as v1
from octobot.ai_strategy_lab import maker_execution_v2 as v2


SCHEMA_VERSION = 1
PROTOCOL_VERSION = "btc_futures_learned_passive_execution_locked_v2"
PREREGISTRATION_DATE = "2026-08-28"

PARENT_PROTOCOL_SHA256 = (
    "70ec9868e208ae0a4c5666075044892bfb1fbee0a773af8c2d0ef4ff20444498"
)
PARENT_PROTOCOL_FILE_SHA256 = (
    "be3ebed52ac93b16338c9b0dd24b6395f9fda85deda41ce031b49ae829f1ce30"
)
PARENT_REPORT_SHA256 = (
    "6eb86811e4467b1e0fe0e48400619df08263d94d084314bc95cb09e78f8df715"
)
PARENT_MANIFEST_FILE_SHA256 = (
    "ba84c41cabbd9ce5702c9ebe9a777c659ce854eac59976082cd616fba5aa933a"
)
PARENT_MANIFEST_CONTENT_SHA256 = (
    "471b4c82c7eafc87888275eeb78ba0e3407091a7cd805d4b5c610f19656e7a84"
)
PARENT_MODEL_SHA256 = (
    "02f079d0784ada207762965dc1573d0b9e0cba0d03c0d3d8a2048f11481811bf"
)
PARENT_CONFIRMATION_PREDICTIONS_SHA256 = (
    "9e34f4449828d9b2a5a822a074f734bb80cb04a02fc8bef32ee448d4b9f2c941"
)

LOCK_START = v2.DIAGNOSTIC_CONFIRMATION_END
LOCK_END = v2.LOCKED_TEST_END


def frozen_protocol() -> dict:
    """Return the result-free, content-bound final-lock protocol."""

    return {
        "schema_version": SCHEMA_VERSION,
        "protocol_version": PROTOCOL_VERSION,
        "preregistered_on": PREREGISTRATION_DATE,
        "status": "result_free_final_lock_protocol",
        "research_only": True,
        "public_data_only": True,
        "credentials_used": False,
        "orders_authorized": False,
        "paper_orders_authorized": False,
        "automatic_promotion": False,
        "directional_alpha_claim": False,
        "parent_prelock": {
            "protocol_sha256": PARENT_PROTOCOL_SHA256,
            "protocol_file_sha256": PARENT_PROTOCOL_FILE_SHA256,
            "report_sha256": PARENT_REPORT_SHA256,
            "manifest_file_sha256": PARENT_MANIFEST_FILE_SHA256,
            "manifest_content_sha256": PARENT_MANIFEST_CONTENT_SHA256,
            "final_model_sha256": PARENT_MODEL_SHA256,
            "confirmation_predictions_sha256": (
                PARENT_CONFIRMATION_PREDICTIONS_SHA256
            ),
            "development_and_confirmation_results_inspected": True,
            "development_gate_pass_required": True,
            "confirmation_gate_pass_required": True,
        },
        "source": {
            "freeze_manifest_file_sha256": v1.FREEZE_MANIFEST_FILE_SHA256,
            "freeze_database_sha256": v1.FREEZE_DATABASE_SHA256,
            "freeze_database_bytes": v1.FREEZE_DATABASE_BYTES,
            "sqlite_open_mode": "read-only immutable",
            "only_queryable_interval": [LOCK_START, LOCK_END],
        },
        "model": {
            "artifact_sha256": PARENT_MODEL_SHA256,
            "refit": False,
            "feature_names": list(v2.FEATURE_NAMES),
            "features_changed": False,
            "hyperparameter_search": False,
            "threshold_search": False,
            "minimum_predicted_fill_probability": (
                v2.MINIMUM_PREDICTED_FILL_PROBABILITY
            ),
            "minimum_expected_saving_bps_strict": (
                v2.EXPECTED_SAVING_THRESHOLD_BPS
            ),
        },
        "execution": {
            "primary": v1.frozen_protocol()["primary_policy"],
            "stress": v1.frozen_protocol()["stress_policy"],
            "unconditional_labels": True,
            "cancellations_reduce_queue": False,
            "partial_fill_credit": False,
        },
        "locked_gate": {
            "minimum_source_coverage": 0.99,
            "minimum_usable_rows": 1_200,
            "minimum_selected_attempts": 200,
            "minimum_selected_attempts_per_side": 70,
            "minimum_selected_pct": 10.0,
            "maximum_selected_pct": 60.0,
            "minimum_selected_fill_rate": 0.10,
            "minimum_fill_auc": 0.52,
            "fill_brier_better_than_constant": True,
            "minimum_selected_mean_saving_bps": 0.25,
            "buy_selected_mean_saving_bps_strictly_positive": True,
            "sell_selected_mean_saving_bps_strictly_positive": True,
            "minimum_positive_operating_days_pct": 50.0,
            "bootstrap_lower_mean_saving_bps_strictly_positive": True,
            "stress_selected_mean_saving_bps_strictly_positive": True,
            "stress_each_side_mean_saving_bps_strictly_positive": True,
        },
        "evaluation": {
            "official_attempts": 1,
            "refit_before_or_after_lock": False,
            "locked_interval": [LOCK_START, LOCK_END],
            "result_artifacts": [
                "locked-predictions.npz",
                "report.json",
                "manifest.json",
            ],
            "existing_complete_run_does_not_requery_database": True,
            "interrupted_identical_run_is_resumable_without_policy_changes": (
                True
            ),
        },
        "advancement_consequence": (
            "a full pass permits only orderless forward shadow use as an "
            "execution overlay for an independently validated strategy; it "
            "does not authorize autonomous, paper or real orders"
        ),
        "results": None,
    }


def write_or_verify_protocol(
    path_value: typing.Union[str, pathlib.Path],
) -> dict:
    path = pathlib.Path(path_value).resolve()
    protocol = frozen_protocol()
    payload = {**protocol, "protocol_sha256": v2._json_hash(protocol)}
    if path.is_file():
        persisted = json.loads(path.read_text(encoding="utf-8"))
        if persisted != payload:
            raise ValueError("persisted locked-execution protocol differs")
        return persisted
    v2._atomic_json(path, payload)
    return payload


def _verify_content_manifest(manifest: dict) -> None:
    declared = manifest.get("content_sha256")
    unhashed = dict(manifest)
    unhashed.pop("content_sha256", None)
    if declared != v2._json_hash(unhashed):
        raise ValueError("parent learned-execution manifest content hash differs")


def _verify_parent(
    parent_protocol_path: pathlib.Path,
    parent_experiment: pathlib.Path,
) -> tuple[pathlib.Path, dict]:
    report_path = parent_experiment / "report.json"
    manifest_path = parent_experiment / "manifest.json"
    model_path = parent_experiment / "development-final-model.npz"
    confirmation_path = parent_experiment / "confirmation-predictions.npz"
    expected_hashes = {
        parent_protocol_path: PARENT_PROTOCOL_FILE_SHA256,
        report_path: PARENT_REPORT_SHA256,
        manifest_path: PARENT_MANIFEST_FILE_SHA256,
        model_path: PARENT_MODEL_SHA256,
        confirmation_path: PARENT_CONFIRMATION_PREDICTIONS_SHA256,
    }
    for path, expected in expected_hashes.items():
        if not path.is_file() or v2._sha256(path) != expected:
            raise ValueError(f"parent learned-execution artifact differs: {path.name}")

    parent_protocol = json.loads(parent_protocol_path.read_text(encoding="utf-8"))
    report = json.loads(report_path.read_text(encoding="utf-8"))
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    _verify_content_manifest(manifest)
    checks = (
        parent_protocol.get("protocol_sha256") == PARENT_PROTOCOL_SHA256,
        report.get("protocol_sha256") == PARENT_PROTOCOL_SHA256,
        report.get("verdict") == "PRELOCK_PASS_REQUIRES_SEPARATE_LOCKED_EVALUATION",
        report.get("development", {}).get("gate", {}).get("passed") is True,
        report.get("diagnostic_confirmation", {}).get("gate", {}).get("passed")
        is True,
        report.get("locked_test", {}).get("rows_queried") is False,
        manifest.get("content_sha256") == PARENT_MANIFEST_CONTENT_SHA256,
        manifest.get("final_model", {}).get("sha256") == PARENT_MODEL_SHA256,
        manifest.get("confirmation_predictions", {}).get("sha256")
        == PARENT_CONFIRMATION_PREDICTIONS_SHA256,
        manifest.get("locked_test_materialized") is False,
        manifest.get("orders_authorized") is False,
        manifest.get("paper_orders_authorized") is False,
    )
    if not all(checks):
        raise ValueError("parent learned-execution advancement evidence differs")
    return model_path, manifest


def build_locked_rows(connection: sqlite3.Connection) -> tuple[list[dict], dict]:
    """Build only the immutable final interval; callers cannot choose dates."""

    start_ns = v1._epoch_ns(LOCK_START)
    end_ns = v1._epoch_ns(LOCK_END)
    decisions = v1._decision_timestamps(start_ns, end_ns)
    rows = []
    exclusions: dict[str, int] = {}
    for decision_ns in decisions:
        window = v2._load_window(connection, decision_ns)
        for side in ("buy", "sell"):
            features = v2._features(window, side)
            primary = v2._unconditional_outcome(
                window, side, v1.PRIMARY_POLICY
            )
            stress = v2._unconditional_outcome(
                window, side, v1.STRESS_POLICY
            )
            reason = None
            if features is None:
                reason = "missing_causal_features"
            elif not primary["completed"]:
                reason = f"primary_{primary['exclusion']}"
            elif not stress["completed"]:
                reason = f"stress_{stress['exclusion']}"
            if reason is not None:
                exclusions[reason] = exclusions.get(reason, 0) + 1
                continue
            rows.append(
                {
                    "timestamp_ns": decision_ns,
                    "side": side,
                    "features": features,
                    "primary": primary,
                    "stress": stress,
                }
            )
    expected = len(decisions) * 2
    return rows, {
        "interval": [LOCK_START, LOCK_END],
        "expected_rows": expected,
        "usable_rows": len(rows),
        "coverage": len(rows) / expected if expected else 0.0,
        "exclusions": exclusions,
    }


def locked_gate(report: dict, protocol: dict) -> dict:
    gate = protocol["locked_gate"]
    source = report["source"]
    primary = report["primary"]
    stress = report["stress"]
    calibration = report["fill_calibration"]
    checks = {
        "minimum_source_coverage": (
            source["coverage"] >= gate["minimum_source_coverage"]
        ),
        "minimum_usable_rows": (
            source["usable_rows"] >= gate["minimum_usable_rows"]
        ),
        "minimum_selected_attempts": (
            primary["selected_attempts"] >= gate["minimum_selected_attempts"]
        ),
        "minimum_selected_attempts_per_side": all(
            primary["by_side"][side]["selected_attempts"]
            >= gate["minimum_selected_attempts_per_side"]
            for side in ("buy", "sell")
        ),
        "minimum_selected_pct": (
            primary["selected_pct"] >= gate["minimum_selected_pct"]
        ),
        "maximum_selected_pct": (
            primary["selected_pct"] <= gate["maximum_selected_pct"]
        ),
        "minimum_selected_fill_rate": (
            primary["selected_fill_rate"]
            >= gate["minimum_selected_fill_rate"]
        ),
        "minimum_fill_auc": (
            calibration["auc"] is not None
            and calibration["auc"] >= gate["minimum_fill_auc"]
        ),
        "fill_brier_better_than_constant": (
            calibration["brier"] < calibration["constant_brier"]
        ),
        "minimum_selected_mean_saving_bps": (
            primary["mean_selected_saving_bps"] is not None
            and primary["mean_selected_saving_bps"]
            >= gate["minimum_selected_mean_saving_bps"]
        ),
        "buy_selected_mean_saving_bps_strictly_positive": (
            primary["by_side"]["buy"]["mean_selected_saving_bps"] is not None
            and primary["by_side"]["buy"]["mean_selected_saving_bps"] > 0
        ),
        "sell_selected_mean_saving_bps_strictly_positive": (
            primary["by_side"]["sell"]["mean_selected_saving_bps"] is not None
            and primary["by_side"]["sell"]["mean_selected_saving_bps"] > 0
        ),
        "minimum_positive_operating_days_pct": (
            primary["positive_operating_days_pct"]
            >= gate["minimum_positive_operating_days_pct"]
        ),
        "bootstrap_lower_mean_saving_bps_strictly_positive": (
            primary["daily_bootstrap_lower_policy_saving_bps_90pct"] is not None
            and primary["daily_bootstrap_lower_policy_saving_bps_90pct"] > 0
        ),
        "stress_selected_mean_saving_bps_strictly_positive": (
            stress["mean_selected_saving_bps"] is not None
            and stress["mean_selected_saving_bps"] > 0
        ),
        "stress_each_side_mean_saving_bps_strictly_positive": all(
            stress["by_side"][side]["mean_selected_saving_bps"] is not None
            and stress["by_side"][side]["mean_selected_saving_bps"] > 0
            for side in ("buy", "sell")
        ),
    }
    return {
        "checks": checks,
        "passed_checks": sum(checks.values()),
        "total_checks": len(checks),
        "passed": all(checks.values()),
    }


def _artifact(path: pathlib.Path) -> dict:
    return {
        "file": path.name,
        "bytes": path.stat().st_size,
        "sha256": v2._sha256(path),
    }


def _write_or_verify_json(path: pathlib.Path, payload: dict) -> None:
    if path.is_file():
        if json.loads(path.read_text(encoding="utf-8")) != payload:
            raise ValueError(f"existing locked artifact differs: {path.name}")
        return
    v2._atomic_json(path, payload)


def _write_or_verify_npz(
    path: pathlib.Path, arrays: dict[str, numpy.ndarray]
) -> None:
    if path.is_file():
        with numpy.load(path, allow_pickle=False) as persisted:
            if set(persisted.files) != set(arrays):
                raise ValueError("existing locked prediction schema differs")
            for key, value in arrays.items():
                if not numpy.array_equal(persisted[key], value, equal_nan=True):
                    raise ValueError(
                        f"existing locked predictions differ: {key}"
                    )
        return
    v2._atomic_npz(path, arrays)


def _verify_complete_experiment(
    experiment: pathlib.Path,
    protocol: dict,
    identity: str,
) -> dict | None:
    report_path = experiment / "report.json"
    prediction_path = experiment / "locked-predictions.npz"
    manifest_path = experiment / "manifest.json"
    state_path = experiment / "run-state.json"
    if not all(path.is_file() for path in (
        report_path, prediction_path, manifest_path
    )):
        return None
    report = json.loads(report_path.read_text(encoding="utf-8"))
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    _verify_content_manifest(manifest)
    checks = (
        manifest.get("identity") == identity,
        manifest.get("protocol_sha256") == protocol["protocol_sha256"],
        manifest.get("report", {}).get("sha256") == v2._sha256(report_path),
        manifest.get("locked_predictions", {}).get("sha256")
        == v2._sha256(prediction_path),
        report.get("protocol_sha256") == protocol["protocol_sha256"],
        report.get("locked_test", {}).get("materialized") is True,
        report.get("orders_authorized") is False,
        report.get("paper_orders_authorized") is False,
    )
    if not all(checks):
        raise ValueError("completed locked-execution evidence differs")
    state = {
        "schema_version": SCHEMA_VERSION,
        "identity": identity,
        "protocol_sha256": protocol["protocol_sha256"],
        "model_sha256": PARENT_MODEL_SHA256,
        "source_database_sha256": v1.FREEZE_DATABASE_SHA256,
        "state": "COMPLETE",
    }
    _write_or_verify_json(state_path, state)
    return {
        "experiment": str(experiment),
        "report": report,
        "manifest": manifest,
        "requeried_database": False,
    }


def evaluate_locked(
    protocol_value,
    parent_protocol_value,
    parent_experiment_value,
    database_value,
    freeze_manifest_value,
    output_root_value,
) -> dict:
    protocol_path = pathlib.Path(protocol_value).resolve()
    parent_protocol_path = pathlib.Path(parent_protocol_value).resolve()
    parent_experiment = pathlib.Path(parent_experiment_value).resolve()
    database_path = pathlib.Path(database_value).resolve()
    freeze_manifest_path = pathlib.Path(freeze_manifest_value).resolve()
    output_root = pathlib.Path(output_root_value).resolve()

    protocol = write_or_verify_protocol(protocol_path)
    model_path, parent_manifest = _verify_parent(
        parent_protocol_path, parent_experiment
    )
    v1._verify_freeze(database_path, freeze_manifest_path)
    identity = (
        f"learned-passive-execution-locked-v2-"
        f"{protocol['protocol_sha256'][:12]}-{PARENT_MODEL_SHA256[:12]}-"
        f"{v1.FREEZE_MANIFEST_FILE_SHA256[:12]}"
    )
    experiment = output_root / identity
    if experiment.is_dir():
        complete = _verify_complete_experiment(experiment, protocol, identity)
        if complete is not None:
            return complete
    else:
        experiment.mkdir(parents=True, exist_ok=False)

    state_path = experiment / "run-state.json"
    open_state = {
        "schema_version": SCHEMA_VERSION,
        "identity": identity,
        "protocol_sha256": protocol["protocol_sha256"],
        "model_sha256": PARENT_MODEL_SHA256,
        "source_database_sha256": v1.FREEZE_DATABASE_SHA256,
        "state": "LOCK_OPENED",
    }
    if state_path.is_file():
        persisted_state = json.loads(state_path.read_text(encoding="utf-8"))
        if persisted_state != open_state:
            raise ValueError("locked-execution run state differs")
    else:
        v2._atomic_json(state_path, open_state)

    model = v2._load_model(model_path)
    connection = v1._open_database(database_path)
    try:
        rows, source = build_locked_rows(connection)
    finally:
        connection.close()
    metrics, predictions = v2._confirmation_report(rows, source, model)
    gate = locked_gate(metrics, protocol)
    verdict = (
        "LOCKED_PASS_EXECUTION_OVERLAY_SHADOW_ELIGIBLE"
        if gate["passed"]
        else "LOCKED_REJECTED"
    )
    report = v2._json_safe(
        {
            "schema_version": SCHEMA_VERSION,
            "protocol_version": PROTOCOL_VERSION,
            "protocol_sha256": protocol["protocol_sha256"],
            "research_only": True,
            "directional_alpha_claim": False,
            "orders_authorized": False,
            "paper_orders_authorized": False,
            "automatic_promotion": False,
            "source": {
                "database": str(database_path),
                "database_sha256_from_freeze": v1.FREEZE_DATABASE_SHA256,
                "freeze_manifest_file_sha256": v2._sha256(
                    freeze_manifest_path
                ),
            },
            "parent_prelock": {
                "protocol_sha256": PARENT_PROTOCOL_SHA256,
                "report_sha256": PARENT_REPORT_SHA256,
                "manifest_content_sha256": parent_manifest["content_sha256"],
                "model_sha256": v2._sha256(model_path),
                "model_refit": False,
            },
            "locked_test": {
                "interval": [LOCK_START, LOCK_END],
                "materialized": True,
                "single_frozen_policy": True,
                "report": metrics,
                "gate": gate,
            },
            "advancement": (
                "orderless_execution_overlay_shadow_only"
                if gate["passed"]
                else "none"
            ),
            "verdict": verdict,
        }
    )

    prediction_path = experiment / "locked-predictions.npz"
    report_path = experiment / "report.json"
    manifest_path = experiment / "manifest.json"
    _write_or_verify_npz(prediction_path, predictions)
    _write_or_verify_json(report_path, report)
    manifest = {
        "schema_version": SCHEMA_VERSION,
        "protocol_version": PROTOCOL_VERSION,
        "protocol_sha256": protocol["protocol_sha256"],
        "identity": identity,
        "parent_report_sha256": PARENT_REPORT_SHA256,
        "parent_model_sha256": PARENT_MODEL_SHA256,
        "source_database_sha256": v1.FREEZE_DATABASE_SHA256,
        "locked_predictions": _artifact(prediction_path),
        "report": _artifact(report_path),
        "locked_test_materialized": True,
        "model_refit": False,
        "orders_authorized": False,
        "paper_orders_authorized": False,
        "automatic_promotion": False,
    }
    manifest["content_sha256"] = v2._json_hash(manifest)
    _write_or_verify_json(manifest_path, manifest)
    complete_state = {**open_state, "state": "COMPLETE"}
    v2._atomic_json(state_path, complete_state)
    return {
        "experiment": str(experiment),
        "report": report,
        "manifest": manifest,
        "requeried_database": True,
    }


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)
    write = subparsers.add_parser("write-protocol")
    write.add_argument("--output", required=True)
    evaluate = subparsers.add_parser("evaluate-lock")
    evaluate.add_argument("--protocol", required=True)
    evaluate.add_argument("--parent-protocol", required=True)
    evaluate.add_argument("--parent-experiment", required=True)
    evaluate.add_argument("--database", required=True)
    evaluate.add_argument("--freeze-manifest", required=True)
    evaluate.add_argument("--output-root", required=True)
    return parser


def main(argv: typing.Sequence[str] | None = None) -> int:
    arguments = _parser().parse_args(argv)
    if arguments.command == "write-protocol":
        result = write_or_verify_protocol(arguments.output)
    else:
        result = evaluate_locked(
            arguments.protocol,
            arguments.parent_protocol,
            arguments.parent_experiment,
            arguments.database,
            arguments.freeze_manifest,
            arguments.output_root,
        )
    print(json.dumps(result, indent=2, sort_keys=True, allow_nan=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
