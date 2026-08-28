"""Frozen Binance/KuCoin perpetual carry research protocol V1.

This module is offline, public-data-only and incapable of creating orders.
The protocol is intentionally persisted before any local economic outcome is
calculated.
"""

from __future__ import annotations

import datetime
import json
import pathlib
import typing

from octobot.ai_strategy_lab import cointegration_pairs_v1 as common


SCHEMA_VERSION = 1
PROTOCOL_VERSION = "binance_kucoin_cross_venue_carry_v1"
PREREGISTRATION_DATE = "2026-08-28"
SYMBOLS = (
    "AAVE/USDT:USDT",
    "ADA/USDT:USDT",
    "ATOM/USDT:USDT",
    "AVAX/USDT:USDT",
    "BCH/USDT:USDT",
    "BTC/USDT:USDT",
    "DOGE/USDT:USDT",
    "DOT/USDT:USDT",
    "ETH/USDT:USDT",
    "HBAR/USDT:USDT",
    "LINK/USDT:USDT",
    "LTC/USDT:USDT",
    "NEAR/USDT:USDT",
    "SOL/USDT:USDT",
    "UNI/USDT:USDT",
    "XLM/USDT:USDT",
    "XRP/USDT:USDT",
    "ZEC/USDT:USDT",
)
LOOKBACK_SETTLEMENTS = 90
LOOKBACK_DAYS = 30
MAXIMUM_PAIRS = 3
PAIR_LEG_EXPOSURE = 0.10
FEE_PER_TURNOVER = 0.0006
SLIPPAGE_PER_TURNOVER = 0.0002
STRESS_COST_MULTIPLIER = 3.0
ENTRY_THRESHOLD_ANNUALIZED = (
    2.0
    * (
        FEE_PER_TURNOVER
        + SLIPPAGE_PER_TURNOVER
        + FEE_PER_TURNOVER
        + SLIPPAGE_PER_TURNOVER
    )
    * STRESS_COST_MULTIPLIER
    * 365.0
    / LOOKBACK_DAYS
)
DEVELOPMENT_START = datetime.datetime(
    2025, 8, 25, 1, tzinfo=datetime.timezone.utc
)
DEVELOPMENT_END = datetime.datetime(
    2025, 12, 1, 1, tzinfo=datetime.timezone.utc
)
CONFIRMATION_START = DEVELOPMENT_END
CONFIRMATION_END = datetime.datetime(
    2026, 3, 2, 1, tzinfo=datetime.timezone.utc
)
LOCKED_START = CONFIRMATION_END
LOCKED_END = datetime.datetime(
    2026, 6, 29, 1, tzinfo=datetime.timezone.utc
)
DEVELOPMENT_FOLDS = (
    (
        datetime.datetime(2025, 8, 25, 1, tzinfo=datetime.timezone.utc),
        datetime.datetime(2025, 9, 29, 1, tzinfo=datetime.timezone.utc),
    ),
    (
        datetime.datetime(2025, 9, 29, 1, tzinfo=datetime.timezone.utc),
        datetime.datetime(2025, 11, 3, 1, tzinfo=datetime.timezone.utc),
    ),
    (
        datetime.datetime(2025, 11, 3, 1, tzinfo=datetime.timezone.utc),
        datetime.datetime(2025, 12, 1, 1, tzinfo=datetime.timezone.utc),
    ),
)


def frozen_protocol() -> dict:
    """Return the one immutable, result-free V1 specification."""

    per_venue_cost = FEE_PER_TURNOVER + SLIPPAGE_PER_TURNOVER
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
        "hypothesis": {
            "name": "persistent_cross_venue_funding_spread",
            "statement": (
                "the same perpetual can have a persistent Binance/KuCoin "
                "funding difference that survives relative-price risk and "
                "conservative execution costs in a delta-neutral position"
            ),
            "direction": (
                "long the lower trailing-funding venue and short the higher"
            ),
            "one_configuration_only": True,
            "opposite_direction_tested": False,
        },
        "universe": {
            "symbols": list(SYMBOLS),
            "required_symbol_count": len(SYMBOLS),
            "venues": ["Binance USD-M", "KuCoin Futures"],
            "fixed_survivor_universe_limitation": True,
        },
        "signal": {
            "completed_settlement_lookback": LOOKBACK_SETTLEMENTS,
            "lookback_days": LOOKBACK_DAYS,
            "decision_schedule": "Monday 00:00 UTC",
            "entry_schedule": "Monday 01:00 UTC close",
            "causal_delay_hours": 1,
            "annualization": "abs(sum_kucoin-sum_binance)*365/30",
            "minimum_annualized_spread": ENTRY_THRESHOLD_ANNUALIZED,
            "threshold_origin": (
                "3x stressed four-fill taker-plus-slippage round trip "
                "recovered over 30 days"
            ),
            "maximum_pairs": MAXIMUM_PAIRS,
            "ranking": "descending absolute spread, symbol tie-break",
            "pair_leg_exposure": PAIR_LEG_EXPOSURE,
            "maximum_portfolio_gross": (
                2.0 * MAXIMUM_PAIRS * PAIR_LEG_EXPOSURE
            ),
            "nominal_net_exposure": 0.0,
            "rebalance": "weekly full target replacement",
            "future_funding_not_used": True,
        },
        "economics": {
            "price_pnl": "hourly close-to-close on prior venue weights",
            "funding_pnl": (
                "negative venue weight times actual signed settlement"
            ),
            "fee_per_venue_turnover": FEE_PER_TURNOVER,
            "slippage_per_venue_turnover": SLIPPAGE_PER_TURNOVER,
            "per_venue_turnover_cost": per_venue_cost,
            "stress_cost_multiplier": STRESS_COST_MULTIPLIER,
            "maker_fill_assumptions": False,
            "forced_flatten_at_each_evaluation_end": True,
        },
        "data_quality": {
            "hourly_prices": (
                "strict consecutive and aligned Binance/KuCoin closes"
            ),
            "funding": (
                "exactly one finite point per required 8-hour grid"
            ),
            "partial_rows_allowed": False,
            "failure_policy": "fail closed before evaluating outcomes",
        },
        "validation": {
            "development": [
                DEVELOPMENT_START.isoformat(),
                DEVELOPMENT_END.isoformat(),
            ],
            "development_end_exclusive": True,
            "walk_forward_folds": [
                [start.isoformat(), end.isoformat()]
                for start, end in DEVELOPMENT_FOLDS
            ],
            "confirmation": [
                CONFIRMATION_START.isoformat(),
                CONFIRMATION_END.isoformat(),
            ],
            "confirmation_end_exclusive": True,
            "locked_final_test": [
                LOCKED_START.isoformat(),
                LOCKED_END.isoformat(),
            ],
            "locked_end_exclusive": True,
            "locked_policy": (
                "do not calculate confirmation unless development passes; "
                "do not calculate lock unless both prior gates pass"
            ),
            "historical_information_status": "diagnostic_reuse",
        },
        "development_gate": {
            "minimum_hours": 98 * 24,
            "minimum_weekly_decisions": 14,
            "minimum_invested_weeks": 6,
            "positive_total_return": True,
            "minimum_annualized_return": 0.04,
            "minimum_sharpe": 1.0,
            "maximum_drawdown": 0.08,
            "minimum_positive_week_ratio": 0.55,
            "minimum_positive_folds": 2,
            "required_folds": len(DEVELOPMENT_FOLDS),
            "funding_return_positive": True,
            "funding_return_exceeds_cost": True,
            "stress_total_return_positive": True,
            "minimum_stress_sharpe": 0.50,
            "maximum_absolute_market_beta": 0.10,
            "minimum_positive_leave_one_symbol_out": 15,
            "required_leave_one_symbol_out": len(SYMBOLS),
            "maximum_symbol_absolute_contribution_share": 0.50,
        },
        "confirmation_gate": {
            "minimum_hours": 91 * 24,
            "minimum_weekly_decisions": 13,
            "minimum_invested_weeks": 6,
            "positive_total_return": True,
            "minimum_annualized_return": 0.02,
            "minimum_sharpe": 0.50,
            "maximum_drawdown": 0.08,
            "minimum_positive_week_ratio": 0.50,
            "funding_return_positive": True,
            "stress_total_return_positive": True,
            "maximum_absolute_market_beta": 0.10,
        },
        "locked_gate": {
            "minimum_hours": 119 * 24,
            "minimum_weekly_decisions": 17,
            "minimum_invested_weeks": 8,
            "positive_total_return": True,
            "minimum_sharpe": 0.50,
            "maximum_drawdown": 0.08,
            "funding_return_positive": True,
            "stress_total_return_positive": True,
            "maximum_absolute_market_beta": 0.10,
        },
        "multiple_testing_disclosure": (
            "one lookback, threshold, schedule, rank direction, universe, "
            "portfolio size and cost model are evaluated"
        ),
        "forward_requirement": {
            "start_not_before": "2026-08-29T00:00:00+00:00",
            "minimum_calendar_days": 180,
            "minimum_observed_days": 165,
            "matched_point_in_time_books_required": True,
            "refit_allowed": False,
        },
        "promotion_consequence": (
            "a complete historical and new-forward pass permits only "
            "manually approved orderless shadow; paper and real orders "
            "remain unauthorized"
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
            raise ValueError("persisted cross-venue carry V1 protocol differs")
        return persisted
    common._atomic_json(path, payload)
    return payload
