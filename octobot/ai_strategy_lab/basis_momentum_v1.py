"""Frozen seven-day basis-momentum factor replication V1.

This module is public-data-only, offline and incapable of creating orders. The
economic evaluator is added only after this result-free protocol is persisted
and committed.
"""

from __future__ import annotations

import argparse
import json
import pathlib
import typing

from octobot.ai_strategy_lab import basis_factor_v2 as execution_parent
from octobot.ai_strategy_lab import cointegration_pairs_v1 as common


SCHEMA_VERSION = 1
PROTOCOL_VERSION = "crypto_perpetual_basis_momentum_v1"
PREREGISTRATION_DATE = "2026-08-28"
PAPER_MANUSCRIPT_SHA256 = execution_parent.PAPER_MANUSCRIPT_SHA256
EXPECTED_SYMBOLS = execution_parent.EXPECTED_SYMBOLS
BLOCK_SECONDS = execution_parent.BLOCK_SECONDS
FORMATION_BLOCKS = 7 * 3
SELECTION_FRACTION = execution_parent.SELECTION_FRACTION
SELECTED_ASSETS_PER_SIDE = execution_parent.SELECTED_ASSETS_PER_SIDE
SIDE_GROSS_EXPOSURE = execution_parent.SIDE_GROSS_EXPOSURE
FEE_PER_TURNOVER = execution_parent.FEE_PER_TURNOVER
SLIPPAGE_PER_TURNOVER = execution_parent.SLIPPAGE_PER_TURNOVER
STRESS_COST_MULTIPLIER = execution_parent.STRESS_COST_MULTIPLIER
MAXIMUM_ABSOLUTE_MARKET_BETA = (
    execution_parent.MAXIMUM_ABSOLUTE_MARKET_BETA
)
MAXIMUM_SYMBOL_CONTRIBUTION_SHARE = (
    execution_parent.MAXIMUM_SYMBOL_CONTRIBUTION_SHARE
)
UTC = execution_parent.UTC
DEVELOPMENT_START = execution_parent.DEVELOPMENT_START
DEVELOPMENT_END = execution_parent.DEVELOPMENT_END
CONFIRMATION_START = execution_parent.CONFIRMATION_START
CONFIRMATION_END = execution_parent.CONFIRMATION_END
LOCKED_START = execution_parent.LOCKED_START
LOCKED_END = execution_parent.LOCKED_END
DEVELOPMENT_FOLDS = execution_parent.DEVELOPMENT_FOLDS
CONFIRMATION_QUARTERS = execution_parent.CONFIRMATION_QUARTERS
FORWARD_START_UTC = "2026-08-29T00:00:00+00:00"


def frozen_protocol() -> dict:
    """Return the single immutable, result-free basis-momentum protocol."""

    return {
        "schema_version": SCHEMA_VERSION,
        "protocol_version": PROTOCOL_VERSION,
        "preregistered_on": PREREGISTRATION_DATE,
        "status": "result_free_evaluation_protocol",
        "research_only": True,
        "public_data_only": True,
        "credentials_used": False,
        "orders_authorized": False,
        "paper_orders_authorized": False,
        "automatic_promotion": False,
        "external_hypothesis": {
            "title": "Anatomy of Cryptocurrency Perpetual Futures Returns",
            "authors": ["Yi Cao", "Jia Zhai", "Pengfei Luo"],
            "institutional_repository": (
                "https://era.ed.ac.uk/bitstream/handle/1842/43608/"
                "Luo2025.pdf?isAllowed=y&sequence=1"
            ),
            "thesis_doi": "10.7488/era/6141",
            "manuscript_sha256": PAPER_MANUSCRIPT_SHA256,
            "equation": 70,
            "table": 21,
            "source_selected_formation": "7*3 eight-hour intervals",
            "source_reported_high_minus_low_weekly_return": 0.0188,
            "source_reported_t_statistic": 8.50,
            "portfolio": "high-minus-low basis momentum quintiles",
            "holding": "following rolling period t to t+N",
            "n_definition": "one eight-hour Binance funding interval",
        },
        "hypothesis": {
            "name": "seven_day_spot_minus_perpetual_basis_momentum",
            "statement": (
                "assets whose spot outperformed their perpetual over the "
                "preceding seven days outperform the opposite quintile over "
                "the next eight-hour funding interval"
            ),
            "economic_mechanism": (
                "persistent spot premium and term-premium information in the "
                "relative spot/perpetual path"
            ),
            "direction": "long high basis momentum; short low basis momentum",
            "opposite_direction_tested": False,
            "long_only_variant_allowed": False,
            "one_configuration_only": True,
        },
        "signal": {
            "source": "checksummed Binance spot and USD-M 1h collectors",
            "basis_momentum": (
                "(spot_t/spot_t_minus_21-1) - "
                "(perpetual_t/perpetual_t_minus_21-1)"
            ),
            "formation_blocks": FORMATION_BLOCKS,
            "formation_days": 7,
            "formation_must_be_contiguous": True,
            "decision_boundaries_utc": ["00:00", "08:00", "16:00"],
            "completed_candles_only": True,
            "ranking": (
                "ascending basis momentum, deterministic symbol tie-break"
            ),
            "selection_fraction_per_side": SELECTION_FRACTION,
            "selected_assets_per_side": SELECTED_ASSETS_PER_SIDE,
            "long_side": "highest basis-momentum quintile",
            "short_side": "lowest basis-momentum quintile",
            "weighting": "equal weight within each side",
            "side_gross_exposure": SIDE_GROSS_EXPOSURE,
            "nominal_net_exposure": 0.0,
            "rebalance": "every completed eight-hour block",
            "holding_blocks": 1,
            "holding_hours": 8,
            "overlapping_vintages": False,
            "other_lookbacks": None,
            "filters": None,
            "thresholds": None,
            "spot_is_signal_only": True,
            "future_prices_or_funding_used": False,
        },
        "data_quality_policy": {
            "common_completed_blocks_only": True,
            "interpolation_or_forward_fill": False,
            "return_across_gap": False,
            "eligible_decision": (
                "decision and outcome closes must be exactly eight hours apart"
            ),
            "formation_after_gap": (
                "zero target until 21 consecutive historical intervals exist"
            ),
            "gap_boundary": (
                "flatten prior segment with cost and reopen next segment from "
                "flat with cost"
            ),
        },
        "period_boundary": {
            "opening": "open first causal nonzero target from flat with cost",
            "closing": "flatten final target with cost",
            "cross_period_pnl_imported": False,
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
            "maker_fill_assumptions": False,
            "cost_on_netted_weight_change": True,
            "maximum_portfolio_gross": 2.0 * SIDE_GROSS_EXPOSURE,
        },
        "validation": {
            "expected_symbols": EXPECTED_SYMBOLS,
            "development": [
                DEVELOPMENT_START.isoformat(),
                DEVELOPMENT_END.isoformat(),
            ],
            "development_status": "diagnostic_reuse",
            "development_folds": [
                [start.isoformat(), end.isoformat()]
                for start, end in DEVELOPMENT_FOLDS
            ],
            "confirmation": [
                CONFIRMATION_START.isoformat(),
                CONFIRMATION_END.isoformat(),
            ],
            "confirmation_status": "sealed_for_basis_momentum_family",
            "confirmation_quarters": [
                [start.isoformat(), end.isoformat()]
                for start, end in CONFIRMATION_QUARTERS
            ],
            "locked_final_test": [
                LOCKED_START.isoformat(),
                LOCKED_END.isoformat(),
            ],
            "locked_status": "sealed_for_basis_momentum_family",
            "locked_policy": (
                "do not calculate confirmation unless development passes; "
                "do not calculate lock unless confirmation also passes"
            ),
            "survivorship_limitation": (
                "fixed archive of contracts surviving to archive end"
            ),
        },
        "development_gate": {
            "minimum_blocks": 2000,
            "positive_total_return": True,
            "minimum_annualized_return": 0.08,
            "minimum_sharpe": 1.00,
            "maximum_drawdown": 0.15,
            "minimum_positive_month_ratio": 0.55,
            "minimum_positive_folds": 4,
            "required_folds": len(DEVELOPMENT_FOLDS),
            "both_side_contributions_nonnegative": True,
            "maximum_absolute_market_beta": MAXIMUM_ABSOLUTE_MARKET_BETA,
            "minimum_positive_leave_one_symbol_out": 15,
            "required_leave_one_symbol_out": EXPECTED_SYMBOLS,
            "stress_total_return_positive": True,
            "minimum_stress_sharpe": 0.50,
            "minimum_average_gross_exposure": 0.75,
            "maximum_symbol_absolute_contribution_share": (
                MAXIMUM_SYMBOL_CONTRIBUTION_SHARE
            ),
        },
        "confirmation_gate": {
            "minimum_blocks": 1000,
            "positive_total_return": True,
            "minimum_annualized_return": 0.04,
            "minimum_sharpe": 0.75,
            "maximum_drawdown": 0.15,
            "minimum_positive_month_ratio": 0.50,
            "minimum_positive_quarters": 3,
            "required_quarters": len(CONFIRMATION_QUARTERS),
            "both_side_contributions_nonnegative": True,
            "maximum_absolute_market_beta": MAXIMUM_ABSOLUTE_MARKET_BETA,
            "stress_total_return_positive": True,
            "minimum_stress_sharpe": 0.25,
        },
        "locked_gate": {
            "minimum_blocks": 500,
            "positive_total_return": True,
            "minimum_annualized_return": 0.04,
            "minimum_sharpe": 0.50,
            "maximum_drawdown": 0.15,
            "minimum_positive_month_ratio": 0.50,
            "both_side_contributions_nonnegative": True,
            "maximum_absolute_market_beta": MAXIMUM_ABSOLUTE_MARKET_BETA,
            "stress_total_return_positive": True,
        },
        "forward_gate": {
            "start_utc": FORWARD_START_UTC,
            "minimum_calendar_days": 180,
            "minimum_observed_blocks": 500,
            "no_refit": True,
            "same_signal_holding_and_costs": True,
            "required_before_shadow_or_paper": True,
        },
        "multiple_testing_disclosure": (
            "one externally selected seven-day formation, direction, quintile "
            "allocation, eight-hour holding and unchanged cost model"
        ),
        "promotion_consequence": (
            "historical pass identifies only a forward candidate; no shadow, "
            "paper or real order is authorized"
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
            raise ValueError("persisted basis-momentum V1 protocol differs")
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
    args = _parser().parse_args(argv)
    result = write_or_verify_protocol(args.output)
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
