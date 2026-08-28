"""Frozen training-selected long confluence V3 protocol and model.

V3 openly uses V2 development metrics for model selection.  It freezes one
configuration before any 2025 outcome is queried and cannot create orders.
"""

from __future__ import annotations

import argparse
import json
import pathlib
import typing

from octobot.ai_strategy_lab import cointegration_pairs_v1 as common
from octobot.ai_strategy_lab import cost_aware_long_confluence_v2 as parent


SCHEMA_VERSION = 1
PROTOCOL_VERSION = "crypto_perpetual_training_selected_long_confluence_v3"
PREREGISTRATION_DATE = "2026-08-28"
SELECTED_CONFIGURATION_ID = "r3-ew_market_28d_positive"
EXPECTED_PARENT_PROTOCOL_SHA256 = (
    "5e080a7f96a80efbba0b3742d5e66f65f1039a85b74e07adefab5bd95be6aa55"
)
EXPECTED_PARENT_DESIGN_REPORT_SHA256 = (
    "12730365845fde08243919cd7b8fc444a9357f7b935ce2e757561d70ca42393f"
)
EXPECTED_PARENT_MANIFEST_SHA256 = (
    "7d2256c61a813926046d75b9839139c92d97b9bb30915a4ff627ba6cdfee073a"
)
EXPECTED_CANDIDATE_SUMMARY_SHA256 = (
    "c22a0cf5d0bec4d0b2e6eab48dbcfa2127b6e2cf1196d0f42520dd5bb5bff4cf"
)
EXPECTED_PARENT_SOURCE_BUNDLE_SHA256 = (
    "62610d94de2257ad0e7fdb91c5d3afdc85b8e16b172100aad5b729f7b1879d57"
)
DEVELOPMENT_END = parent.DEVELOPMENT_END
CONFIRMATION_START = parent.CONFIRMATION_START
CONFIRMATION_END = parent.CONFIRMATION_END
LOCKED_START = parent.LOCKED_START
LOCKED_END = parent.LOCKED_END
CONFIRMATION_QUARTERS = parent.CONFIRMATION_QUARTERS
FORWARD_START_UTC = parent.FORWARD_START_UTC


def frozen_protocol() -> dict:
    """Return the exact single-model OOS protocol."""

    return {
        "schema_version": SCHEMA_VERSION,
        "protocol_version": PROTOCOL_VERSION,
        "preregistered_on": PREREGISTRATION_DATE,
        "status": "single_training_selected_model_pre_oos",
        "research_only": True,
        "public_data_only": True,
        "credentials_used": False,
        "orders_authorized": False,
        "paper_orders_authorized": False,
        "automatic_promotion": False,
        "training_selection": {
            "parent_protocol_sha256": EXPECTED_PARENT_PROTOCOL_SHA256,
            "parent_design_report_sha256": (
                EXPECTED_PARENT_DESIGN_REPORT_SHA256
            ),
            "parent_manifest_sha256": EXPECTED_PARENT_MANIFEST_SHA256,
            "candidate_summary_sha256": EXPECTED_CANDIDATE_SUMMARY_SHA256,
            "parent_source_bundle_sha256": (
                EXPECTED_PARENT_SOURCE_BUNDLE_SHA256
            ),
            "selection_was_defined_after_training": True,
            "training_is_promotional_evidence": False,
            "selection_predicate": {
                "stress_total_return_positive": True,
                "minimum_positive_folds": 4,
                "minimum_training_sharpe": 0.75,
                "must_be_unique_among_six_parent_candidates": True,
            },
            "selected_configuration_id": SELECTED_CONFIGURATION_ID,
            "selection_interpretation": (
                "the unique robust-enough training compromise, not a V2 pass"
            ),
            "other_2025_configurations_allowed": False,
        },
        "frozen_model": {
            "entry_signal": "unchanged parent long three-factor intersection",
            "maximum_assets": parent.MAXIMUM_ASSETS,
            "portfolio_gross_exposure": parent.PORTFOLIO_GROSS_EXPOSURE,
            "rebalance_blocks": 3,
            "rebalance_hours": 24,
            "rebalance_anchor_utc": parent.REBALANCE_ANCHOR_UTC,
            "regime": "ew_market_28d_positive",
            "regime_blocks": parent.REGIME_BLOCKS,
            "target_between_boundaries": "unchanged",
            "early_exit": False,
            "stops_or_take_profit": False,
            "refit": False,
            "alternative_configuration": False,
        },
        "economics": {
            "traded_instrument": "perpetual only",
            "fee_per_turnover": parent.FEE_PER_TURNOVER,
            "slippage_per_turnover": parent.SLIPPAGE_PER_TURNOVER,
            "stress_cost_multiplier": parent.STRESS_COST_MULTIPLIER,
            "cost_on_netted_weight_change": True,
            "maker_fill_assumptions": False,
            "cost_reduction_relative_to_training": False,
        },
        "metric_definition": {
            "annualized_market_alpha": (
                "mean(strategy_block_return-beta*equal_weight_market_"
                "block_return)*1095"
            ),
            "beta": "population covariance divided by population variance",
            "zero_risk_free_rate": True,
        },
        "confirmation": {
            "period": [
                CONFIRMATION_START.isoformat(),
                CONFIRMATION_END.isoformat(),
            ],
            "status": "sealed_first_oos_for_v3",
            "quarters": [
                [start.isoformat(), end.isoformat()]
                for start, end in CONFIRMATION_QUARTERS
            ],
            "single_query": True,
            "gate": dict(parent.frozen_protocol()["confirmation"]["gate"]),
        },
        "locked_test": {
            "period": [LOCKED_START.isoformat(), LOCKED_END.isoformat()],
            "status": "sealed_until_confirmation_passes",
            "single_query": True,
            "gate": dict(parent.frozen_protocol()["locked_test"]["gate"]),
        },
        "forward_gate": {
            "start_utc": FORWARD_START_UTC,
            "minimum_calendar_days": 180,
            "minimum_observed_blocks": 500,
            "no_refit": True,
            "same_frozen_model_and_costs": True,
            "required_before_shadow_or_paper": True,
        },
        "multiple_testing_disclosure": (
            "one model selected after six training candidates; the untouched "
            "2025 period is queried once and failed gates are not relaxed"
        ),
        "promotion_consequence": (
            "confirmation and lock passes create only a forward candidate; no "
            "shadow, paper or real order is authorized"
        ),
        "results": None,
    }


def write_or_verify_protocol(
    path_value: typing.Union[str, pathlib.Path],
) -> dict:
    path = pathlib.Path(path_value).resolve()
    protocol = frozen_protocol()
    payload = {**protocol, "protocol_sha256": common._json_hash(protocol)}
    if path.is_file():
        persisted = json.loads(path.read_text(encoding="utf-8"))
        if persisted != payload:
            raise ValueError("persisted training-selected V3 protocol differs")
        return persisted
    common._atomic_json(path, payload)
    return payload


def verify_parent_design(
    report_value: typing.Union[str, pathlib.Path],
    manifest_value: typing.Union[str, pathlib.Path],
) -> tuple[dict, dict, dict]:
    """Verify the immutable six-candidate training lineage and unique choice."""

    report_path = pathlib.Path(report_value).resolve()
    manifest_path = pathlib.Path(manifest_value).resolve()
    if common._sha256(report_path) != EXPECTED_PARENT_DESIGN_REPORT_SHA256:
        raise ValueError("parent V2 design report hash differs")
    if common._sha256(manifest_path) != EXPECTED_PARENT_MANIFEST_SHA256:
        raise ValueError("parent V2 manifest hash differs")
    report = json.loads(report_path.read_text(encoding="utf-8"))
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    if (
        report.get("protocol_sha256") != EXPECTED_PARENT_PROTOCOL_SHA256
        or report.get("source_bundle_sha256")
        != EXPECTED_PARENT_SOURCE_BUNDLE_SHA256
        or report.get("candidate_summary_sha256")
        != EXPECTED_CANDIDATE_SUMMARY_SHA256
        or manifest.get("report_sha256")
        != EXPECTED_PARENT_DESIGN_REPORT_SHA256
        or report.get("confirmation_evaluated") is not False
        or report.get("locked_test_evaluated") is not False
    ):
        raise ValueError("parent V2 lineage or seals differ")
    matching = [
        candidate
        for candidate in report["candidates"]
        if candidate["stress"]["total_return"] > 0
        and candidate["positive_folds"] >= 4
        and candidate["development"]["sharpe_zero_rate"] >= 0.75
    ]
    if len(matching) != 1:
        raise ValueError("training selection predicate is not unique")
    selected = matching[0]
    if (
        selected["configuration"]["configuration_id"]
        != SELECTED_CONFIGURATION_ID
    ):
        raise ValueError("unique training candidate is not the frozen V3 model")
    return report, manifest, selected


def write_or_verify_selection(
    protocol_value: typing.Union[str, pathlib.Path],
    report_value: typing.Union[str, pathlib.Path],
    manifest_value: typing.Union[str, pathlib.Path],
    output_value: typing.Union[str, pathlib.Path],
) -> dict:
    protocol = write_or_verify_protocol(protocol_value)
    _report, _manifest, selected = verify_parent_design(
        report_value, manifest_value
    )
    output = pathlib.Path(output_value).resolve()
    training = selected["development"]
    model = {
        "schema_version": SCHEMA_VERSION,
        "protocol_sha256": protocol["protocol_sha256"],
        "parent_protocol_sha256": EXPECTED_PARENT_PROTOCOL_SHA256,
        "parent_design_report_sha256": EXPECTED_PARENT_DESIGN_REPORT_SHA256,
        "parent_candidate_summary_sha256": EXPECTED_CANDIDATE_SUMMARY_SHA256,
        "selected_configuration": selected["configuration"],
        "selection_predicate": protocol["training_selection"][
            "selection_predicate"
        ],
        "training_snapshot": {
            "total_return": training["total_return"],
            "stress_total_return": selected["stress"]["total_return"],
            "sharpe_zero_rate": training["sharpe_zero_rate"],
            "positive_folds": selected["positive_folds"],
            "maximum_drawdown": training["maximum_drawdown"],
            "positive_month_ratio": training["positive_month_ratio"],
            "annualized_market_alpha": training["annualized_market_alpha"],
        },
        "training_is_promotional_evidence": False,
        "maximum_training_outcome_utc": DEVELOPMENT_END.isoformat(),
        "confirmation_evaluated": False,
        "locked_test_evaluated": False,
        "orders_authorized": False,
        "paper_orders_authorized": False,
        "automatic_promotion": False,
    }
    model["content_sha256"] = common._json_hash(model)
    if output.is_file():
        persisted = json.loads(output.read_text(encoding="utf-8"))
        if persisted != model:
            raise ValueError("persisted training-selected V3 model differs")
        return persisted
    common._atomic_json(output, model)
    return model


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)
    write = subparsers.add_parser("write-protocol")
    write.add_argument("--output", required=True)
    selection = subparsers.add_parser("write-selection")
    selection.add_argument("--protocol", required=True)
    selection.add_argument("--parent-report", required=True)
    selection.add_argument("--parent-manifest", required=True)
    selection.add_argument("--output", required=True)
    return parser


def main(argv=None) -> int:
    arguments = _parser().parse_args(argv)
    if arguments.command == "write-protocol":
        print(json.dumps(write_or_verify_protocol(arguments.output), indent=2))
        return 0
    if arguments.command == "write-selection":
        print(
            json.dumps(
                write_or_verify_selection(
                    arguments.protocol,
                    arguments.parent_report,
                    arguments.parent_manifest,
                    arguments.output,
                ),
                indent=2,
            )
        )
        return 0
    raise AssertionError("unreachable command")


if __name__ == "__main__":
    raise SystemExit(main())
