"""Frozen eight-hour perpetual/spot log-basis factor replication V2.

The module is public-data-only, offline and incapable of creating orders.
The evaluation implementation is intentionally added only after the result-free
protocol has been persisted and committed.
"""

from __future__ import annotations

import argparse
import json
import pathlib
import typing

from octobot.ai_strategy_lab import basis_factor_v1 as parent
from octobot.ai_strategy_lab import cointegration_pairs_v1 as common
from octobot.ai_strategy_lab import signed_flow_factor_v1 as block_parent


SCHEMA_VERSION = 1
PROTOCOL_VERSION = "crypto_perpetual_spot_basis_factor_v2"
PREREGISTRATION_DATE = "2026-08-28"
PAPER_MANUSCRIPT_SHA256 = block_parent.PAPER_MANUSCRIPT_SHA256
EXPECTED_SYMBOLS = parent.EXPECTED_SYMBOLS
BLOCK_SECONDS = block_parent.BLOCK_SECONDS
SELECTION_FRACTION = 0.20
SELECTED_ASSETS_PER_SIDE = 3
SIDE_GROSS_EXPOSURE = parent.SIDE_GROSS_EXPOSURE
FEE_PER_TURNOVER = parent.FEE_PER_TURNOVER
SLIPPAGE_PER_TURNOVER = parent.SLIPPAGE_PER_TURNOVER
STRESS_COST_MULTIPLIER = parent.STRESS_COST_MULTIPLIER
MAXIMUM_ABSOLUTE_MARKET_BETA = 0.30
MAXIMUM_SYMBOL_CONTRIBUTION_SHARE = 0.35
UTC = block_parent.UTC
DEVELOPMENT_START = block_parent.DEVELOPMENT_START
DEVELOPMENT_END = block_parent.DEVELOPMENT_END
CONFIRMATION_START = block_parent.CONFIRMATION_START
CONFIRMATION_END = block_parent.CONFIRMATION_END
LOCKED_START = block_parent.LOCKED_START
LOCKED_END = block_parent.LOCKED_END
DEVELOPMENT_FOLDS = block_parent.DEVELOPMENT_FOLDS
CONFIRMATION_QUARTERS = block_parent.CONFIRMATION_QUARTERS
FORWARD_START_UTC = "2026-08-29T00:00:00+00:00"


def frozen_protocol() -> dict:
    """Return the single immutable, result-free V2 specification."""

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
        "parent_protocol": {
            "version": parent.PROTOCOL_VERSION,
            "development_result_known": True,
            "confirmation_materialized": False,
            "locked_test_materialized": False,
            "unchanged_elements": [
                "same 18-symbol Binance spot/perpetual survivor universe",
                "perpetual-only P&L with spot used only as a signal",
                "0.40 gross exposure per side",
                "signed funding accounting",
                "6-bps taker fee and 2-bps slippage per turnover",
                "3x cost stress",
                "sequential development, confirmation and lock gates",
            ],
            "source_identified_corrections": [
                "rank log(perpetual close)-log(spot close)",
                "use bottom and top quintile, three assets per side",
                "form and rebalance at each completed eight-hour funding block",
                "hold only the following t-to-t+N block where N is eight hours",
            ],
        },
        "external_hypothesis": {
            "title": "Anatomy of Cryptocurrency Perpetual Futures Returns",
            "authors": ["Yi Cao", "Jia Zhai", "Pengfei Luo"],
            "institutional_repository": (
                "https://era.ed.ac.uk/bitstream/handle/1842/43608/"
                "Luo2025.pdf?isAllowed=y&sequence=1"
            ),
            "thesis_doi": "10.7488/era/6141",
            "manuscript_sha256": PAPER_MANUSCRIPT_SHA256,
            "table": 19,
            "basis_equation": "log(perpetual close)-log(spot close)",
            "portfolio": "low-minus-high log-basis quintiles",
            "formation": "at each completed Binance funding interval",
            "holding": "following rolling period t to t+N",
            "n_definition": "one eight-hour Binance funding interval",
            "weekly_wording": "return reporting frequency, not holding length",
        },
        "hypothesis": {
            "name": "eight_hour_cross_sectional_log_basis",
            "statement": (
                "perpetuals with low log basis outperform perpetuals with "
                "high log basis over the next eight-hour funding interval"
            ),
            "economic_mechanism": (
                "cross-sectional compensation for futures basis and the "
                "spot-perpetual convergence mechanism"
            ),
            "direction": "long low log basis; short high log basis",
            "opposite_direction_tested": False,
            "long_only_variant_allowed": False,
            "one_configuration_only": True,
        },
        "signal": {
            "source": "checksummed Binance spot and USD-M 1h collectors",
            "basis": "log(perpetual_close)-log(spot_close)",
            "decision_boundaries_utc": ["00:00", "08:00", "16:00"],
            "completed_candles_only": True,
            "ranking": "ascending log basis, deterministic symbol tie-break",
            "selection_fraction_per_side": SELECTION_FRACTION,
            "selected_assets_per_side": SELECTED_ASSETS_PER_SIDE,
            "long_side": "lowest log-basis quintile",
            "short_side": "highest log-basis quintile",
            "weighting": "equal weight within each side",
            "side_gross_exposure": SIDE_GROSS_EXPOSURE,
            "nominal_net_exposure": 0.0,
            "rebalance": "every completed eight-hour block",
            "holding_blocks": 1,
            "holding_hours": 8,
            "overlapping_vintages": False,
            "lookback": None,
            "filters": None,
            "thresholds": None,
            "spot_is_signal_only": True,
            "future_prices_or_funding_used": False,
        },
        "period_boundary": {
            "opening": "open first causal target from flat with cost",
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
            "confirmation_status": "sealed_for_basis_family",
            "confirmation_quarters": [
                [start.isoformat(), end.isoformat()]
                for start, end in CONFIRMATION_QUARTERS
            ],
            "locked_final_test": [
                LOCKED_START.isoformat(),
                LOCKED_END.isoformat(),
            ],
            "locked_status": "sealed_for_basis_family",
            "locked_policy": (
                "do not calculate confirmation unless V2 development passes; "
                "do not calculate lock unless V2 confirmation passes"
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
            "V2 is the second basis implementation; only source-identified "
            "equation, quintile and eight-hour timing mismatches are corrected"
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
            raise ValueError("persisted basis-factor V2 protocol differs")
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
