"""Frozen expanded-training long confluence V4 protocol.

V4 treats July 2022 through December 2025 as training, selects one of exactly
16 cost-aware candidates, and reserves January through June 2026 as its only
historical OOS query.  This initial module persists only the result-free
protocol and cannot create orders.
"""

from __future__ import annotations

import argparse
import datetime
import json
import pathlib
import typing

from octobot.ai_strategy_lab import cointegration_pairs_v1 as common
from octobot.ai_strategy_lab import cost_aware_long_confluence_v2 as engine


SCHEMA_VERSION = 1
PROTOCOL_VERSION = "crypto_perpetual_expanded_training_long_confluence_v4"
PREREGISTRATION_DATE = "2026-08-28"
TRAINING_START = datetime.datetime(2022, 7, 1, tzinfo=datetime.timezone.utc)
TRAINING_END = datetime.datetime(2026, 1, 1, tzinfo=datetime.timezone.utc)
OOS_START = datetime.datetime(2026, 1, 1, tzinfo=datetime.timezone.utc)
OOS_END = datetime.datetime(2026, 7, 1, tzinfo=datetime.timezone.utc)
TRAINING_FOLDS = tuple(
    (
        datetime.datetime(year, month, 1, tzinfo=datetime.timezone.utc),
        (
            datetime.datetime(year + 1, 1, 1, tzinfo=datetime.timezone.utc)
            if month == 7
            else datetime.datetime(year, 7, 1, tzinfo=datetime.timezone.utc)
        ),
    )
    for year, month in (
        (2022, 7),
        (2023, 1),
        (2023, 7),
        (2024, 1),
        (2024, 7),
        (2025, 1),
        (2025, 7),
    )
)
REBALANCE_BLOCKS = (3, 9, 21, 42)
REGIMES = (
    "always_on",
    "ew_28d_positive",
    "ew_84d_positive",
    "ew_28d_and_84d_positive",
)
REGIME_28D_BLOCKS = 28 * 3
REGIME_84D_BLOCKS = 84 * 3
FORWARD_START_UTC = "2026-08-29T00:00:00+00:00"


def candidate_configurations() -> list[dict]:
    return [
        {
            "configuration_id": f"r{blocks}-{regime}",
            "rebalance_blocks": blocks,
            "rebalance_hours": blocks * 8,
            "regime": regime,
        }
        for blocks in REBALANCE_BLOCKS
        for regime in REGIMES
    ]


def frozen_protocol() -> dict:
    return {
        "schema_version": SCHEMA_VERSION,
        "protocol_version": PROTOCOL_VERSION,
        "preregistered_on": PREREGISTRATION_DATE,
        "status": "expanded_training_pre_2026_oos",
        "research_only": True,
        "public_data_only": True,
        "credentials_used": False,
        "orders_authorized": False,
        "paper_orders_authorized": False,
        "automatic_promotion": False,
        "lineage": {
            "v3_2025_result_is_training_information": True,
            "v3_report_sha256": (
                "977836cacc3c17c006cfac0b65bb804abb406870b94efe83c3d6e27fe573ee6b"
            ),
            "2025_is_oos_for_v4": False,
            "first_and_only_v4_oos": "2026-01-01 through 2026-07-01",
            "other_models_may_query_2026": False,
        },
        "signal": {
            "entry": "unchanged long three-factor confluence",
            "maximum_assets": engine.MAXIMUM_ASSETS,
            "portfolio_gross_exposure": engine.PORTFOLIO_GROSS_EXPOSURE,
            "weighting": "equal weight",
            "spot_is_signal_only": True,
            "completed_blocks_only": True,
            "early_exit": False,
            "stops_or_take_profit": False,
            "additional_features": False,
        },
        "training_grid": {
            "configurations": candidate_configurations(),
            "configuration_count": len(candidate_configurations()),
            "rebalance_anchor_utc": engine.REBALANCE_ANCHOR_UTC,
            "target_between_boundaries": "unchanged",
            "regimes": {
                "always_on": "no market gate",
                "ew_28d_positive": (
                    "equal-weight 84-block cumulative return strictly positive"
                ),
                "ew_84d_positive": (
                    "equal-weight 252-block cumulative return strictly positive"
                ),
                "ew_28d_and_84d_positive": (
                    "both 84-block and 252-block conditions strictly positive"
                ),
            },
            "regime_28d_blocks": REGIME_28D_BLOCKS,
            "regime_84d_blocks": REGIME_84D_BLOCKS,
            "other_configurations": False,
        },
        "data_quality_policy": {
            "reuse_checksummed_parent_inputs": True,
            "common_completed_blocks_only": True,
            "interpolation_or_forward_fill": False,
            "return_across_gap": False,
            "signal_after_gap": "flat until 21 intervals are contiguous",
            "regime_after_gap": (
                "filtered targets remain flat until their full lookback is contiguous"
            ),
            "gap_boundary": "flatten and reopen with explicit cost",
        },
        "economics": {
            "traded_instrument": "perpetual only",
            "fee_per_turnover": engine.FEE_PER_TURNOVER,
            "slippage_per_turnover": engine.SLIPPAGE_PER_TURNOVER,
            "stress_cost_multiplier": engine.STRESS_COST_MULTIPLIER,
            "cost_on_netted_weight_change": True,
            "maker_fill_assumptions": False,
            "cost_reduction_relative_to_v3": False,
        },
        "metric_definition": {
            "annualized_market_alpha": (
                "mean(strategy_block_return-beta*equal_weight_market_"
                "block_return)*1095"
            ),
            "beta": "population covariance divided by population variance",
            "zero_risk_free_rate": True,
        },
        "training": {
            "period": [TRAINING_START.isoformat(), TRAINING_END.isoformat()],
            "status": "training_only_including_observed_2025",
            "folds": [
                [start.isoformat(), end.isoformat()]
                for start, end in TRAINING_FOLDS
            ],
            "eligibility": {
                "minimum_invested_blocks": 400,
                "minimum_invested_blocks_per_fold": 30,
                "required_folds": len(TRAINING_FOLDS),
                "all_metrics_finite": True,
            },
            "selection": {
                "eligible_candidates_only": True,
                "order": [
                    "maximum positive 3x-cost folds",
                    "maximum minimum 3x-cost fold total return",
                    "maximum median 3x-cost fold Sharpe",
                    "maximum full-training base annualized market alpha",
                    "minimum full-training base turnover",
                    "lexicographically smallest configuration_id",
                ],
                "selection_count": 1,
                "selection_is_economic_pass": False,
            },
        },
        "oos_test": {
            "period": [OOS_START.isoformat(), OOS_END.isoformat()],
            "status": "sealed_single_query",
            "gate": {
                "minimum_blocks": 500,
                "minimum_invested_blocks": 100,
                "positive_total_return": True,
                "stress_total_return_positive": True,
                "minimum_annualized_return": 0.04,
                "minimum_annualized_market_alpha": 0.04,
                "minimum_sharpe": 0.50,
                "minimum_profit_factor": 1.05,
                "maximum_drawdown": 0.20,
                "minimum_positive_month_ratio": 0.50,
                "maximum_absolute_market_beta": 0.50,
                "maximum_symbol_absolute_contribution_share": 0.50,
            },
            "failed_model_replacement": False,
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
            "16 expanded-training candidates; one frozen winner may query "
            "January-June 2026 once"
        ),
        "promotion_consequence": (
            "an OOS pass creates only a forward candidate; no shadow, paper "
            "or real order is authorized"
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
            raise ValueError("persisted expanded-training V4 protocol differs")
        return persisted
    common._atomic_json(path, payload)
    return payload


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)
    write = subparsers.add_parser("write-protocol")
    write.add_argument("--output", required=True)
    return parser


def main(argv=None) -> int:
    arguments = _parser().parse_args(argv)
    print(json.dumps(write_or_verify_protocol(arguments.output), indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
