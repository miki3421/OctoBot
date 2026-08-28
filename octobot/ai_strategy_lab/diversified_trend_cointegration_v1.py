"""Frozen diversified trend/cointegration portfolio V1 protocol.

This module writes or verifies a result-free, training-informed protocol. It
cannot load market outcomes, fit a model, create targets or place orders.
"""

from __future__ import annotations

import argparse
import datetime
import json
import pathlib
import typing

from octobot.ai_strategy_lab import cointegration_pairs_v1 as common


SCHEMA_VERSION = 1
PROTOCOL_VERSION = "crypto_diversified_trend_cointegration_v1"
PREREGISTRATION_DATE = "2026-08-28"
TRAINING_START = datetime.date(2023, 1, 1)
TRAINING_END = datetime.date(2026, 7, 1)
TRAINING_FOLDS = (
    (datetime.date(2023, 1, 1), datetime.date(2023, 7, 1)),
    (datetime.date(2023, 7, 1), datetime.date(2024, 1, 1)),
    (datetime.date(2024, 1, 1), datetime.date(2024, 7, 1)),
    (datetime.date(2024, 7, 1), datetime.date(2025, 1, 1)),
    (datetime.date(2025, 1, 1), datetime.date(2025, 7, 1)),
    (datetime.date(2025, 7, 1), datetime.date(2026, 1, 1)),
    (datetime.date(2026, 1, 1), datetime.date(2026, 7, 1)),
)
FORWARD_START_UTC = "2026-09-01T00:00:00+00:00"

TREND_REPORT_SHA256 = (
    "0880041064ded1b9c5d797410674d73f176f2587cfd5e7a3da1ae13369104bd9"
)
TREND_INPUTS_SHA256 = (
    "89c661f4be6613fb994541231c132cfd7a39cb3c627590055e4cccf2abaa1b42"
)
TREND_CONFIG_SHA256 = (
    "981c9c8dca2d3bf844fe6750b9ac1a60bfe4f20a3dff8a4e887b11331a77c8df"
)
TREND_SOURCE_SHA256 = (
    "ec07dc6c6fb74a9763a3251cb4b9c5753b3625566f8fb2d63fa41361c43a57f9"
)
COINTEGRATION_PROTOCOL_SHA256 = (
    "7718dd8e2f55d74101c977a6c5dc3f139590bf8184e63bb80c2720ac8ff19628"
)
COINTEGRATION_REPORT_SHA256 = (
    "e6b725a3a9c39393e729df9bf536675969c47d615011250c138ae837e7129e1b"
)
COINTEGRATION_NULL_SHA256 = (
    "ebe2539cf125bddd1ca20bfb5e4c0b25a13880774a6d64a8febd32e7ee867167"
)
COINTEGRATION_SOURCE_SHA256 = (
    "c685456cfe42bd4273ab9daeaab544dc6a3852beaf4fae69f31024f0fd63098d"
)
SOURCE_SNAPSHOT_BUNDLE_SHA256 = (
    "03d744e12e0494c98f4dae8490e229ee524a66b3df4660ea6eb34a6ee286c55b"
)
HISTORY_BUNDLE_SHA256 = (
    "4158e252768a92a9bece0bc0e801d4e9b3830a693628512c880b68538b14e2da"
)

ALLOCATIONS = (
    {
        "configuration_id": "trend80_cointegration20",
        "trend_capital_weight": 0.80,
        "cointegration_capital_weight": 0.20,
    },
    {
        "configuration_id": "trend65_cointegration35",
        "trend_capital_weight": 0.65,
        "cointegration_capital_weight": 0.35,
    },
    {
        "configuration_id": "trend50_cointegration50",
        "trend_capital_weight": 0.50,
        "cointegration_capital_weight": 0.50,
    },
)


def frozen_protocol() -> dict:
    """Return the immutable protocol without outcomes or a selected model."""

    return {
        "schema_version": SCHEMA_VERSION,
        "protocol_version": PROTOCOL_VERSION,
        "preregistered_on": PREREGISTRATION_DATE,
        "status": "result_free_meta_protocol_before_combined_trajectories",
        "research_only": True,
        "public_data_only": True,
        "credentials_used": False,
        "orders_authorized": False,
        "paper_orders_authorized": False,
        "automatic_promotion": False,
        "hypothesis": {
            "name": "fixed_capital_trend_plus_relative_value_diversification",
            "statement": (
                "a fixed allocation to low-beta convergence can improve the "
                "temporal stability and drawdown of an unchanged trend sleeve"
            ),
            "mechanisms": [
                "medium-horizon directional momentum",
                "market-neutral cointegrated-spread convergence",
            ],
            "training_informed": True,
            "cointegration_v2_outcome_seen_before_protocol": True,
            "all_component_outcomes_seen_before_protocol": True,
            "historical_results_are_selection_not_evidence": True,
            "one_forward_model_only": True,
        },
        "lineage": {
            "trend": {
                "configuration": "risk_budgeted_bear_regime_v13",
                "report_sha256": TREND_REPORT_SHA256,
                "inputs_sha256": TREND_INPUTS_SHA256,
                "configuration_sha256": TREND_CONFIG_SHA256,
                "source_sha256": TREND_SOURCE_SHA256,
                "internal_parameters_unchanged": True,
                "base_cost_multiplier": 1.0,
                "stress_cost_multiplier": 3.0,
            },
            "cointegration": {
                "configuration": (
                    "crypto_futures_expanded_cointegration_pairs_v2"
                ),
                "protocol_sha256": COINTEGRATION_PROTOCOL_SHA256,
                "report_sha256": COINTEGRATION_REPORT_SHA256,
                "null_sha256": COINTEGRATION_NULL_SHA256,
                "source_sha256": COINTEGRATION_SOURCE_SHA256,
                "source_snapshot_bundle_sha256": (
                    SOURCE_SNAPSHOT_BUNDLE_SHA256
                ),
                "history_bundle_sha256": HISTORY_BUNDLE_SHA256,
                "internal_parameters_unchanged": True,
                "both_spread_directions_retained": True,
                "base_cost_multiplier": 1.0,
                "stress_cost_multiplier": 3.0,
                "v2_rejected": True,
            },
        },
        "portfolio": {
            "capital_allocations": [dict(value) for value in ALLOCATIONS],
            "allocation_sum": 1.0,
            "sleeve_returns_combined_linearly_before_compounding": True,
            "daily_reallocation_turnover_assumed": False,
            "capital_budgets_fixed": True,
            "cross_sleeve_netting_assumed": False,
            "extra_leverage": False,
            "maximum_gross_bound_by_weighted_component_gross": True,
            "component_signals_costs_funding_and_stops_unchanged": True,
            "carry_component": False,
            "book_filter": False,
            "parameter_search_inside_components": False,
        },
        "training": {
            "status": "diagnostic_training_only_no_historical_holdout",
            "start": TRAINING_START.isoformat(),
            "end_exclusive": TRAINING_END.isoformat(),
            "folds": [
                [start.isoformat(), end.isoformat()]
                for start, end in TRAINING_FOLDS
            ],
            "required_folds": len(TRAINING_FOLDS),
            "evaluate_base_and_three_x_costs": True,
            "eligibility": {
                "minimum_observed_days": 1277,
                "stress_total_return_positive": True,
                "minimum_stress_annualized_return": 0.06,
                "minimum_stress_sharpe": 0.75,
                "maximum_stress_drawdown": 0.18,
                "minimum_stress_positive_month_ratio": 0.50,
                "minimum_positive_stress_folds": 5,
                "maximum_worst_stress_fold_loss": 0.10,
                "both_sleeve_additive_contributions_positive": True,
            },
            "selection_order": [
                "highest worst stress fold return",
                "highest median stress fold Sharpe",
                "highest full-period stress Sharpe",
                "lowest full-period stress drawdown",
                "configuration_id ascending",
            ],
            "no_eligible_configuration_consequence": (
                "close family without selected model or forward observer"
            ),
            "selected_model_must_be_content_addressed": True,
        },
        "forward_gate": {
            "start_utc": FORWARD_START_UTC,
            "minimum_calendar_days": 180,
            "minimum_observed_days": 165,
            "append_only": True,
            "no_refit_or_reselection": True,
            "same_selected_allocation_components_costs_and_code": True,
            "minimum_cointegration_closed_trades": 3,
            "minimum_trend_invested_days": 60,
            "base_total_return_positive": True,
            "stress_total_return_positive": True,
            "minimum_base_annualized_return": 0.04,
            "minimum_stress_annualized_return": 0.02,
            "minimum_base_sharpe": 0.75,
            "minimum_stress_sharpe": 0.50,
            "maximum_base_drawdown": 0.12,
            "maximum_stress_drawdown": 0.15,
            "minimum_positive_month_ratio": 0.50,
            "both_sleeve_additive_contributions_non_negative": True,
            "required_before_shadow_or_paper": True,
            "automatic_promotion": False,
        },
        "multiple_testing_disclosure": (
            "three disclosed capital allocations are training candidates; "
            "only one deterministically selected model may enter one forward"
        ),
        "promotion_consequence": (
            "a forward pass permits only manual review for guarded paper; it "
            "does not authorize an order or live trading"
        ),
        "selected_model": None,
        "results": None,
    }


def write_or_verify_protocol(
    path_value: typing.Union[str, pathlib.Path],
) -> dict:
    """Create the protocol atomically or verify the immutable existing file."""

    path = pathlib.Path(path_value).resolve()
    frozen = frozen_protocol()
    payload = {**frozen, "protocol_sha256": common._json_hash(frozen)}
    if path.is_file():
        persisted = json.loads(path.read_text(encoding="utf-8"))
        if persisted != payload:
            raise ValueError("persisted diversified protocol differs")
        return persisted
    common._atomic_json(path, payload)
    return payload


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", required=True)
    return parser


def main(argv=None) -> int:
    args = _parser().parse_args(argv)
    value = write_or_verify_protocol(args.output)
    print(json.dumps(value, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
