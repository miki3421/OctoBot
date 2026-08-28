"""Frozen three-factor relative-value confluence protocol V1.

The module is public-data-only, offline and incapable of creating orders.  At
preregistration time it can only persist the result-free protocol; the
economic evaluator is added in a later commit.
"""

from __future__ import annotations

import argparse
import json
import pathlib
import typing

from octobot.ai_strategy_lab import basis_momentum_v1 as parent
from octobot.ai_strategy_lab import cointegration_pairs_v1 as common


SCHEMA_VERSION = 1
PROTOCOL_VERSION = "crypto_perpetual_relative_value_confluence_v1"
PREREGISTRATION_DATE = "2026-08-28"
PAPER_MANUSCRIPT_SHA256 = parent.PAPER_MANUSCRIPT_SHA256
EXPECTED_SYMBOLS = parent.EXPECTED_SYMBOLS
BLOCK_SECONDS = parent.BLOCK_SECONDS
FORMATION_BLOCKS = 21
TERTILE_DIVISOR = 3
MAXIMUM_ASSETS_PER_SIDE = 3
SIDE_GROSS_EXPOSURE = parent.SIDE_GROSS_EXPOSURE
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


def frozen_protocol() -> dict:
    """Return the only permitted result-free confluence specification."""

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
            "source_tables": [19, 21, 29],
            "source_directions": {
                "log_basis": "long low; short high",
                "basis_momentum": "long high; short low",
                "signed_price_volume_imbalance": "long high; short low",
            },
            "source_selected_formation": "7*3 eight-hour intervals",
        },
        "hypothesis": {
            "name": "three_factor_relative_value_confluence",
            "statement": (
                "the documented gross relative-value effects become tradable "
                "after unchanged costs only when valuation, relative-path "
                "persistence and aggressive flow agree cross-sectionally"
            ),
            "economic_mechanism": (
                "a perpetual lagging spot is entered only when its seven-day "
                "relative path and aggressive order flow confirm convergence"
            ),
            "opposite_direction_tested": False,
            "long_only_variant_allowed": False,
            "one_configuration_only": True,
        },
        "signal": {
            "universe": "18 aligned Binance USD-M perpetual/spot pairs",
            "decision_boundaries_utc": ["00:00", "08:00", "16:00"],
            "completed_candles_only": True,
            "formation_blocks": FORMATION_BLOCKS,
            "formation_days": 7,
            "formation_must_be_contiguous": True,
            "features": {
                "log_basis": "log(perpetual_close_t)-log(spot_close_t)",
                "basis_momentum": (
                    "(spot_t/spot_t_minus_21-1)-"
                    "(perpetual_t/perpetual_t_minus_21-1)"
                ),
                "signed_flow": (
                    "sum over latest 21 blocks of "
                    "2*taker_buy_quote-total_quote_volume"
                ),
            },
            "ranking": (
                "independent ascending ranks with deterministic symbol "
                "tie-break; extreme set size floor(eligible/3)"
            ),
            "long_intersection": (
                "bottom log-basis tertile AND top basis-momentum tertile "
                "AND top signed-flow tertile"
            ),
            "short_intersection": (
                "top log-basis tertile AND bottom basis-momentum tertile "
                "AND bottom signed-flow tertile"
            ),
            "long_extremeness": (
                "(n-1-log_basis_rank)+basis_momentum_rank+signed_flow_rank"
            ),
            "short_extremeness": (
                "log_basis_rank+(n-1-basis_momentum_rank)+"
                "(n-1-signed_flow_rank)"
            ),
            "maximum_assets_per_side": MAXIMUM_ASSETS_PER_SIDE,
            "paired_side_requirement": (
                "flat unless both long and short intersections are nonempty"
            ),
            "weighting": "equal weight independently within each active side",
            "side_gross_exposure": SIDE_GROSS_EXPOSURE,
            "maximum_portfolio_gross": 2.0 * SIDE_GROSS_EXPOSURE,
            "nominal_net_exposure": 0.0,
            "rebalance": "every completed eight-hour block",
            "holding_blocks": 1,
            "overlapping_vintages": False,
            "learned_thresholds": None,
            "hysteresis": None,
            "normalization": None,
            "filters": None,
            "other_lookbacks": None,
            "spot_is_signal_only": True,
            "future_prices_or_funding_used": False,
        },
        "data_quality_policy": {
            "checksummed_raw_flow_archives": True,
            "checksummed_spot_and_perpetual_collectors": True,
            "common_completed_blocks_only": True,
            "interpolation_or_forward_fill": False,
            "return_across_gap": False,
            "eligible_decision": (
                "decision and outcome closes must be exactly eight hours apart"
            ),
            "formation_after_gap": (
                "flat until both 21-block formation windows are contiguous"
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
            "cost_reduction_relative_to_prior_tests": False,
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
            "confirmation_status": "sealed_for_confluence_family",
            "confirmation_quarters": [
                [start.isoformat(), end.isoformat()]
                for start, end in CONFIRMATION_QUARTERS
            ],
            "locked_final_test": [
                LOCKED_START.isoformat(),
                LOCKED_END.isoformat(),
            ],
            "locked_status": "sealed_for_confluence_family",
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
            "minimum_invested_blocks": 250,
            "positive_total_return": True,
            "minimum_annualized_return": 0.08,
            "minimum_sharpe": 1.00,
            "minimum_profit_factor": 1.10,
            "maximum_drawdown": 0.15,
            "minimum_positive_month_ratio": 0.55,
            "minimum_positive_folds": 4,
            "required_folds": len(DEVELOPMENT_FOLDS),
            "both_side_contributions_nonnegative": True,
            "maximum_absolute_market_beta": 0.20,
            "minimum_positive_leave_one_symbol_out": 15,
            "required_leave_one_symbol_out": EXPECTED_SYMBOLS,
            "stress_total_return_positive": True,
            "minimum_stress_sharpe": 0.50,
            "maximum_symbol_absolute_contribution_share": 0.35,
        },
        "confirmation_gate": {
            "minimum_blocks": 1000,
            "minimum_invested_blocks": 100,
            "positive_total_return": True,
            "minimum_annualized_return": 0.04,
            "minimum_sharpe": 0.75,
            "minimum_profit_factor": 1.05,
            "maximum_drawdown": 0.15,
            "minimum_positive_month_ratio": 0.50,
            "minimum_positive_quarters": 3,
            "required_quarters": len(CONFIRMATION_QUARTERS),
            "both_side_contributions_nonnegative": True,
            "maximum_absolute_market_beta": 0.20,
            "stress_total_return_positive": True,
            "minimum_stress_sharpe": 0.25,
        },
        "locked_gate": {
            "minimum_blocks": 500,
            "minimum_invested_blocks": 50,
            "positive_total_return": True,
            "minimum_annualized_return": 0.04,
            "minimum_sharpe": 0.50,
            "minimum_profit_factor": 1.05,
            "maximum_drawdown": 0.15,
            "minimum_positive_month_ratio": 0.50,
            "both_side_contributions_nonnegative": True,
            "maximum_absolute_market_beta": 0.20,
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
            "one fixed intersection of three externally documented factor "
            "directions; no thresholds, weights or holding periods are fitted"
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
    """Persist the immutable protocol or fail if an existing file differs."""

    path = pathlib.Path(path_value).resolve()
    protocol = frozen_protocol()
    payload = {**protocol, "protocol_sha256": common._json_hash(protocol)}
    if path.is_file():
        persisted = json.loads(path.read_text(encoding="utf-8"))
        if persisted != payload:
            raise ValueError("persisted confluence V1 protocol differs")
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
