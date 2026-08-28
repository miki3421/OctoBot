"""Frozen seven-day overlapping signed-flow factor replication V2.

V2 corrects only the V1 holding horizon to match the external manuscript. It
is public-data-only, offline and incapable of creating orders.
"""

from __future__ import annotations

import datetime
import json
import pathlib
import typing

from octobot.ai_strategy_lab import cointegration_pairs_v1 as common
from octobot.ai_strategy_lab import signed_flow_factor_v1 as parent


SCHEMA_VERSION = 1
PROTOCOL_VERSION = "crypto_perpetual_signed_price_volume_flow_v2"
PREREGISTRATION_DATE = "2026-08-28"
HOLDING_BLOCKS = 7 * 3
VINTAGE_FRACTION = 1.0 / HOLDING_BLOCKS
MAXIMUM_ABSOLUTE_MARKET_BETA = 0.20
FORWARD_START_UTC = "2026-08-29T00:00:00+00:00"
UTC = datetime.timezone.utc
DEVELOPMENT_START = parent.DEVELOPMENT_START
DEVELOPMENT_END = parent.DEVELOPMENT_END
CONFIRMATION_START = parent.CONFIRMATION_START
CONFIRMATION_END = parent.CONFIRMATION_END
LOCKED_START = parent.LOCKED_START
LOCKED_END = parent.LOCKED_END
DEVELOPMENT_FOLDS = parent.DEVELOPMENT_FOLDS
CONFIRMATION_QUARTERS = parent.CONFIRMATION_QUARTERS


def frozen_protocol() -> dict:
    """Return the one immutable, result-free V2 specification."""

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
                "18-symbol Binance USD-M survivor universe",
                "signed aggressive quote-flow definition",
                "seven-day formation",
                "long high flow and short low flow",
                "three assets per side",
                "0.40 gross per side",
                "funding accounting",
                "6-bps fee and 2-bps slippage per turnover",
                "3x cost stress",
            ],
            "single_correction": (
                "replace V1 next-eight-hour holding with the external "
                "manuscript's following weekly holding period"
            ),
        },
        "external_hypothesis": {
            "title": "Anatomy of Cryptocurrency Perpetual Futures Returns",
            "authors": ["Yi Cao", "Jia Zhai", "Pengfei Luo"],
            "institutional_repository": (
                "https://era.ed.ac.uk/bitstream/handle/1842/43608/"
                "Luo2025.pdf?isAllowed=y&sequence=1"
            ),
            "thesis_doi": "10.7488/era/6141",
            "manuscript_sha256": parent.PAPER_MANUSCRIPT_SHA256,
            "table": 29,
            "formation": "7*3 completed eight-hour blocks",
            "holding": "following rolling weekly period t to t+N",
            "portfolio": "high-minus-low signed price-volume imbalance",
        },
        "hypothesis": {
            "name": "overlapping_weekly_signed_flow_continuation",
            "statement": (
                "seven-day signed quote flow predicts the relative return "
                "of the following seven days rather than only the next block"
            ),
            "direction": "long high signed flow; short low signed flow",
            "opposite_direction_tested": False,
            "long_only_variant_allowed": False,
            "one_configuration_only": True,
        },
        "signal": {
            "source": "same checksummed Binance USD-M raw 1h archives",
            "block_flow": (
                "sum(2 * taker_buy_quote_volume - total_quote_volume)"
            ),
            "formation_blocks": parent.FORMATION_BLOCKS,
            "formation_days": 7,
            "ranking": "ascending flow, deterministic symbol tie-break",
            "selected_assets_per_side": 3,
            "long_side": "highest flow quintile",
            "short_side": "lowest flow quintile",
            "weighting": "equal weight within each vintage side",
            "full_portfolio_side_gross": parent.SIDE_GROSS_EXPOSURE,
            "new_vintage_fraction": VINTAGE_FRACTION,
            "new_vintage_side_gross": (
                parent.SIDE_GROSS_EXPOSURE * VINTAGE_FRACTION
            ),
            "vintage_created": "every completed eight-hour block",
            "holding_blocks": HOLDING_BLOCKS,
            "holding_days": 7,
            "active_vintages_at_steady_state": HOLDING_BLOCKS,
            "aggregate_target": "sum of active vintage weights",
            "opposite_orders_netted_before_cost": True,
            "maximum_portfolio_gross": 2.0 * parent.SIDE_GROSS_EXPOSURE,
            "nominal_net_exposure": 0.0,
            "normalization": None,
            "filters": None,
            "future_values_used": False,
        },
        "period_boundary": {
            "opening": (
                "reconstruct 21 live vintages from completed pre-period "
                "signals, then open aggregate target from flat with cost"
            ),
            "closing": "flatten aggregate target with cost",
            "cross_period_pnl_imported": False,
        },
        "economics": {
            "traded_instrument": "perpetual only",
            "price_pnl": "next-block close-to-close on aggregate prior target",
            "funding_pnl": (
                "negative aggregate weight times actual signed settlement"
            ),
            "fee_per_turnover": parent.FEE_PER_TURNOVER,
            "slippage_per_turnover": parent.SLIPPAGE_PER_TURNOVER,
            "stress_cost_multiplier": parent.STRESS_COST_MULTIPLIER,
            "maker_fill_assumptions": False,
            "cost_on_netted_weight_change": True,
        },
        "validation": {
            "expected_symbols": parent.EXPECTED_SYMBOLS,
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
            "confirmation_status": "sealed_for_signed_flow_family",
            "confirmation_quarters": [
                [start.isoformat(), end.isoformat()]
                for start, end in CONFIRMATION_QUARTERS
            ],
            "locked_final_test": [
                LOCKED_START.isoformat(),
                LOCKED_END.isoformat(),
            ],
            "locked_status": "sealed_for_signed_flow_family",
            "locked_policy": (
                "do not calculate confirmation unless V2 development passes; "
                "do not calculate lock unless V2 confirmation passes"
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
            "maximum_absolute_market_beta": (
                MAXIMUM_ABSOLUTE_MARKET_BETA
            ),
            "minimum_positive_leave_one_symbol_out": 15,
            "required_leave_one_symbol_out": parent.EXPECTED_SYMBOLS,
            "stress_total_return_positive": True,
            "minimum_stress_sharpe": 0.50,
            "minimum_average_gross_exposure": 0.50,
            "maximum_symbol_absolute_contribution_share": 0.35,
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
            "maximum_absolute_market_beta": (
                MAXIMUM_ABSOLUTE_MARKET_BETA
            ),
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
            "maximum_absolute_market_beta": (
                MAXIMUM_ABSOLUTE_MARKET_BETA
            ),
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
            "V2 is the second signed-flow implementation; only the externally "
            "specified weekly holding horizon changes, and promotion relies "
            "on the still-sealed 2025 and 2026 periods"
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
            raise ValueError("persisted signed-flow V2 protocol differs")
        return persisted
    common._atomic_json(path, payload)
    return payload
