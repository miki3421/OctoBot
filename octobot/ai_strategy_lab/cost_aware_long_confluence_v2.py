"""Frozen cost-aware long confluence design protocol V2.

Development is explicitly training data.  This initial module can only persist
the result-free six-candidate design protocol; it cannot evaluate outcomes or
create orders.
"""

from __future__ import annotations

import argparse
import json
import pathlib
import typing

from octobot.ai_strategy_lab import cointegration_pairs_v1 as common
from octobot.ai_strategy_lab import relative_value_confluence_v1 as parent


SCHEMA_VERSION = 1
PROTOCOL_VERSION = "crypto_perpetual_cost_aware_long_confluence_v2"
PREREGISTRATION_DATE = "2026-08-28"
EXPECTED_SYMBOLS = parent.EXPECTED_SYMBOLS
BLOCK_SECONDS = parent.BLOCK_SECONDS
FORMATION_BLOCKS = parent.FORMATION_BLOCKS
REGIME_BLOCKS = 28 * 3
REBALANCE_ANCHOR_UTC = "2022-05-02T00:00:00+00:00"
REBALANCE_BLOCKS = (3, 9, 21)
REGIMES = ("always_on", "ew_market_28d_positive")
MAXIMUM_ASSETS = 3
PORTFOLIO_GROSS_EXPOSURE = parent.SIDE_GROSS_EXPOSURE
FEE_PER_TURNOVER = parent.FEE_PER_TURNOVER
SLIPPAGE_PER_TURNOVER = parent.SLIPPAGE_PER_TURNOVER
STRESS_COST_MULTIPLIER = parent.STRESS_COST_MULTIPLIER
DEVELOPMENT_START = parent.DEVELOPMENT_START
DEVELOPMENT_END = parent.DEVELOPMENT_END
CONFIRMATION_START = parent.CONFIRMATION_START
CONFIRMATION_END = parent.CONFIRMATION_END
LOCKED_START = parent.LOCKED_START
LOCKED_END = parent.LOCKED_END
DEVELOPMENT_FOLDS = parent.DEVELOPMENT_FOLDS
CONFIRMATION_QUARTERS = parent.CONFIRMATION_QUARTERS
FORWARD_START_UTC = "2026-08-29T00:00:00+00:00"


def candidate_configurations() -> list[dict]:
    """Return the complete, deterministically ordered training grid."""

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
    """Return the only allowed result-free V2 training/OOS specification."""

    return {
        "schema_version": SCHEMA_VERSION,
        "protocol_version": PROTOCOL_VERSION,
        "preregistered_on": PREREGISTRATION_DATE,
        "status": "result_free_training_and_oos_protocol",
        "research_only": True,
        "public_data_only": True,
        "credentials_used": False,
        "orders_authorized": False,
        "paper_orders_authorized": False,
        "automatic_promotion": False,
        "design_disclosure": {
            "parent_family": parent.PROTOCOL_VERSION,
            "parent_result_used_for_design": (
                "development cost-allocated long contribution was positive "
                "while the short contribution was strongly negative"
            ),
            "development_is_evidence": False,
            "first_promotional_evidence": "sealed calendar year 2025",
            "long_only_is_post_parent_design": True,
            "short_variant_in_v2": None,
        },
        "hypothesis": {
            "name": "cost_aware_long_relative_value_confluence",
            "statement": (
                "slow scheduled reselection can retain the documented long "
                "confluence while raising gross edge per unit turnover"
            ),
            "economic_mechanism": (
                "spot/perpetual convergence confirmed by persistent relative "
                "path and aggressive flow, with turnover controlled by design"
            ),
            "long_only": True,
            "opposite_direction_tested": False,
        },
        "entry_signal": {
            "identical_to_parent_long_intersection": True,
            "log_basis": "bottom cross-sectional third",
            "basis_momentum_7d": "top cross-sectional third",
            "signed_flow_7d": "top cross-sectional third",
            "all_three_required": True,
            "maximum_assets": MAXIMUM_ASSETS,
            "weighting": "equal weight among selected assets",
            "portfolio_gross_exposure": PORTFOLIO_GROSS_EXPOSURE,
            "spot_is_signal_only": True,
            "completed_blocks_only": True,
        },
        "training_grid": {
            "configurations": candidate_configurations(),
            "configuration_count": len(candidate_configurations()),
            "rebalance_anchor_utc": REBALANCE_ANCHOR_UTC,
            "rebalance_policy": (
                "select only on anchored boundaries and keep the target "
                "unchanged until the next boundary"
            ),
            "regime_policy": {
                "always_on": "no market-direction gate",
                "ew_market_28d_positive": (
                    "new target allowed only when the equal-weight cumulative "
                    "return of all 18 perpetuals over the preceding 84 "
                    "contiguous blocks is strictly positive"
                ),
            },
            "regime_blocks": REGIME_BLOCKS,
            "early_exit": False,
            "stops_or_take_profit": False,
            "learned_numeric_thresholds": False,
            "additional_features": False,
            "other_configurations": False,
        },
        "data_quality_policy": {
            "reuse_parent_checksummed_inputs": True,
            "common_completed_blocks_only": True,
            "interpolation_or_forward_fill": False,
            "return_across_gap": False,
            "signal_formation_after_gap": (
                "flat until the 21 confluence intervals are contiguous"
            ),
            "regime_formation_after_gap": (
                "the filtered candidates remain flat until 84 market "
                "intervals are contiguous"
            ),
            "gap_boundary": (
                "flatten prior segment with cost and reopen the next segment "
                "from flat with cost"
            ),
        },
        "economics": {
            "traded_instrument": "perpetual only",
            "price_pnl": "next eight-hour perpetual close-to-close return",
            "funding_pnl": (
                "negative target weight times actual signed next settlement"
            ),
            "fee_per_turnover": FEE_PER_TURNOVER,
            "slippage_per_turnover": SLIPPAGE_PER_TURNOVER,
            "stress_cost_multiplier": STRESS_COST_MULTIPLIER,
            "cost_on_netted_weight_change": True,
            "maker_fill_assumptions": False,
            "cost_reduction_relative_to_parent": False,
        },
        "training": {
            "period": [
                DEVELOPMENT_START.isoformat(),
                DEVELOPMENT_END.isoformat(),
            ],
            "status": "training_reuse_not_promotional_evidence",
            "folds": [
                [start.isoformat(), end.isoformat()]
                for start, end in DEVELOPMENT_FOLDS
            ],
            "candidate_gate": {
                "minimum_invested_blocks": 250,
                "positive_total_return": True,
                "stress_total_return_positive": True,
                "minimum_annualized_return": 0.05,
                "minimum_annualized_market_alpha": 0.05,
                "minimum_sharpe": 0.75,
                "minimum_profit_factor": 1.05,
                "maximum_drawdown": 0.25,
                "minimum_positive_month_ratio": 0.50,
                "minimum_positive_folds": 4,
                "required_folds": len(DEVELOPMENT_FOLDS),
                "maximum_absolute_market_beta": 0.50,
                "maximum_symbol_absolute_contribution_share": 0.40,
            },
            "selection": {
                "eligible_candidates_only": True,
                "order": [
                    "maximum minimum fold total return",
                    "maximum median fold Sharpe",
                    "minimum total turnover",
                    "lexicographically smallest configuration_id",
                ],
                "selection_count": 1,
                "no_eligible_candidate": (
                    "freeze no model and leave confirmation sealed"
                ),
            },
            "design_artifacts_content_addressed": True,
        },
        "confirmation": {
            "period": [
                CONFIRMATION_START.isoformat(),
                CONFIRMATION_END.isoformat(),
            ],
            "status": "sealed_first_oos_for_v2",
            "quarters": [
                [start.isoformat(), end.isoformat()]
                for start, end in CONFIRMATION_QUARTERS
            ],
            "open_policy": (
                "open exactly once only after one immutable training winner"
            ),
            "gate": {
                "minimum_blocks": 1000,
                "minimum_invested_blocks": 200,
                "positive_total_return": True,
                "stress_total_return_positive": True,
                "minimum_annualized_return": 0.05,
                "minimum_annualized_market_alpha": 0.05,
                "minimum_sharpe": 0.75,
                "minimum_profit_factor": 1.10,
                "maximum_drawdown": 0.20,
                "minimum_positive_month_ratio": 0.55,
                "minimum_positive_quarters": 3,
                "required_quarters": len(CONFIRMATION_QUARTERS),
                "maximum_absolute_market_beta": 0.50,
                "maximum_symbol_absolute_contribution_share": 0.50,
            },
        },
        "locked_test": {
            "period": [LOCKED_START.isoformat(), LOCKED_END.isoformat()],
            "status": "sealed_until_confirmation_passes",
            "open_policy": "open exactly once without refit after confirmation pass",
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
            "six development-training configurations; only one frozen winner "
            "may query the untouched 2025 confirmation"
        ),
        "promotion_consequence": (
            "even confirmation and lock passes create only a forward candidate; "
            "no shadow, paper or real order is authorized"
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
            raise ValueError("persisted cost-aware long V2 protocol differs")
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
    if arguments.command == "write-protocol":
        print(json.dumps(write_or_verify_protocol(arguments.output), indent=2))
        return 0
    raise AssertionError("unreachable command")


if __name__ == "__main__":
    raise SystemExit(main())
