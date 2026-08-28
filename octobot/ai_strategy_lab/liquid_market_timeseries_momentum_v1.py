"""Frozen liquid-market time-series momentum V1 protocol.

This module can only materialize or verify a result-free research protocol.
It cannot read market outcomes, access an exchange or create any order.
"""

from __future__ import annotations

import argparse
import datetime
import json
import pathlib
import typing

from octobot.ai_strategy_lab import cointegration_pairs_v1 as common
from octobot.ai_strategy_lab import liquid_cross_sectional_momentum_v1 as data_parent


SCHEMA_VERSION = 1
PROTOCOL_VERSION = "crypto_perpetual_liquid_market_timeseries_momentum_v1"
PREREGISTRATION_DATE = "2026-08-28"

UNIVERSE_ASSETS = data_parent.UNIVERSE_ASSETS
MINIMUM_CONTIGUOUS_HISTORY_DAYS = 180
MINIMUM_ELIGIBLE_ASSETS = 20
LIQUID_BASKET_ASSETS = 30
LIQUIDITY_LOOKBACK_DAYS = 28
FORMATION_DAYS = 28
HOLDING_DAYS = 5
STAGGERED_VINTAGES = HOLDING_DAYS
MINIMUM_PRIOR_FORMATION_BLOCKS = 6
ENTRY_TAIL_FRACTION = 1.0 / 3.0
MAXIMUM_GROSS_EXPOSURE = 0.40
VINTAGE_GROSS_EXPOSURE = MAXIMUM_GROSS_EXPOSURE / STAGGERED_VINTAGES
FEE_PER_TURNOVER = data_parent.FEE_PER_TURNOVER
SLIPPAGE_PER_TURNOVER = data_parent.SLIPPAGE_PER_TURNOVER
STRESS_COST_MULTIPLIER = data_parent.STRESS_COST_MULTIPLIER
UTC = datetime.timezone.utc

TRAINING_START = data_parent.TRAINING_START
TRAINING_END = data_parent.TRAINING_END
TRAINING_FOLDS = data_parent.TRAINING_FOLDS
FORWARD_START_UTC = data_parent.FORWARD_START_UTC


def frozen_protocol() -> dict:
    """Return the single immutable local test of the external hypothesis."""

    return {
        "schema_version": SCHEMA_VERSION,
        "protocol_version": PROTOCOL_VERSION,
        "preregistered_on": PREREGISTRATION_DATE,
        "status": "result_free_training_protocol",
        "research_only": True,
        "public_data_only": True,
        "credentials_used": False,
        "orders_authorized": False,
        "paper_orders_authorized": False,
        "automatic_promotion": False,
        "external_hypothesis": {
            "title": (
                "Time-Series and Cross-Sectional Momentum in the "
                "Cryptocurrency Market: A Comprehensive Analysis under "
                "Realistic Assumptions"
            ),
            "authors": ["Chulwoo Han", "Byeongguk Kang", "Jehyeon Ryu"],
            "public_manuscript": (
                "https://acfr.aut.ac.nz/__data/assets/pdf_file/0009/918729/"
                "Time_Series_and_Cross_Sectional_Momentum_in_the_"
                "Cryptocurrency_Market_with_IA.pdf"
            ),
            "findings_used": [
                (
                    "time-series momentum evidence is stronger than "
                    "cross-sectional momentum under realistic assumptions"
                ),
                (
                    "the main long-only market strategy uses a 28-day "
                    "lookback, five-day holding period and top historical "
                    "tercile entry"
                ),
                "short-only momentum is unfavorable and losers often rebound",
                (
                    "the result is robust across market-portfolio weighting "
                    "schemes"
                ),
            ],
            "source_searches_multiple_horizons": True,
            "external_data_snooping_disclosed": True,
            "source_result_is_not_local_evidence": True,
            "implementation_differences": [
                "fixed current-survivor Binance USD-M universe",
                "causal trailing-volume top-30 basket instead of market cap",
                "five executable staggered vintages instead of averaging tests",
                "actual perpetual funding and project-standard costs",
                "fixed 0.40 maximum gross exposure",
            ],
        },
        "hypothesis": {
            "name": "liquid_market_bull_state_continuation",
            "statement": (
                "when the completed 28-day return of a causal liquid crypto "
                "market basket exceeds the upper tercile of its own prior "
                "non-overlapping history, a five-day long position has "
                "positive net expectancy and improves risk-adjusted results "
                "relative to continuously holding the same basket"
            ),
            "economic_mechanism": (
                "aggregate bullish overreaction persists briefly while cash "
                "avoids weak and bearish states"
            ),
            "economically_distinct_from": [
                (
                    "individual-asset dual momentum V13/V18 with covariance "
                    "sizing and conditional shorts"
                ),
                "cross-sectional winner/loser and winner/BTC momentum V1/V2",
                "category momentum",
                "basis, funding carry and cointegration",
                "directional Level-5 and taker scalping",
            ],
            "one_configuration_only": True,
            "short_variant_allowed": False,
            "cross_sectional_momentum_ranking_used": False,
        },
        "data": {
            "venue": "Binance USD-M",
            "instrument": "USDT linear perpetual",
            "source_snapshot_bundle_sha256": (
                data_parent.SOURCE_SNAPSHOT_BUNDLE_SHA256
            ),
            "source_snapshot_manifest_content_sha256": (
                data_parent.SOURCE_SNAPSHOT_MANIFEST_CONTENT_SHA256
            ),
            "history_bundle_sha256": data_parent.HISTORY_BUNDLE_SHA256,
            "history_manifest_content_sha256": (
                data_parent.HISTORY_MANIFEST_CONTENT_SHA256
            ),
            "market_panel_sha256": data_parent.MARKET_PANEL_SHA256,
            "universe_assets": UNIVERSE_ASSETS,
            "universe_frozen": True,
            "minimum_contiguous_history_days": (
                MINIMUM_CONTIGUOUS_HISTORY_DAYS
            ),
            "minimum_eligible_assets": MINIMUM_ELIGIBLE_ASSETS,
            "liquid_basket_assets": LIQUID_BASKET_ASSETS,
            "liquidity_measure": (
                "median daily quote volume over the preceding 28 completed days"
            ),
            "liquidity_tie_break": "symbol ascending",
            "interpolation_or_forward_fill": False,
            "historical_survivorship_present": True,
            "historical_universe_selection_is_point_in_time": False,
            "book_feature_in_alpha": False,
            "book_role": (
                "separate venue-specific execution and liquidity evidence"
            ),
        },
        "signal": {
            "decision_boundary": (
                "each 00:00 UTC boundary after the daily close is complete"
            ),
            "formation_days": FORMATION_DAYS,
            "holding_days": HOLDING_DAYS,
            "staggered_vintages": STAGGERED_VINTAGES,
            "vintage_anchor": "UTC epoch day modulo five",
            "vintage_gross_exposure": VINTAGE_GROSS_EXPOSURE,
            "maximum_gross_exposure": MAXIMUM_GROSS_EXPOSURE,
            "market_score": (
                "equal-weight mean of each selected asset close_t / "
                "close_t_minus_28 - 1"
            ),
            "historical_comparator": (
                "all valid prior scores t-28*k for integer k >= 1"
            ),
            "minimum_prior_formation_blocks": (
                MINIMUM_PRIOR_FORMATION_BLOCKS
            ),
            "entry_rule": (
                "current score strictly exceeds the deterministic upper-"
                "tercile order statistic of prior non-overlapping scores"
            ),
            "entry_tail_fraction": ENTRY_TAIL_FRACTION,
            "active_target": (
                "one vintage long equal-weight in its causal liquid basket"
            ),
            "inactive_target": "cash",
            "vintage_target_between_decisions": "unchanged for five days",
            "aggregate_vintages_before_costs": True,
            "future_data_used": False,
            "model_fitted": False,
            "parameter_search": False,
            "volatility_target": False,
            "stop_or_take_profit": False,
        },
        "benchmark": {
            "name": "continuous_same_basket",
            "construction": (
                "the same five staggered causal liquid-basket vintages are "
                "always long, without the historical-tercile timing gate"
            ),
            "same_gross_funding_costs_and_calendar": True,
            "minimum_sharpe_improvement": 0.10,
            "maximum_drawdown_ratio": 0.85,
        },
        "economics": {
            "price_pnl": "next completed daily perpetual close-to-close return",
            "funding_pnl": "actual signed settlements while target is active",
            "fee_per_turnover": FEE_PER_TURNOVER,
            "slippage_per_turnover": SLIPPAGE_PER_TURNOVER,
            "stress_cost_multiplier": STRESS_COST_MULTIPLIER,
            "cost_on_netted_aggregate_weight_change": True,
            "period_opened_and_closed_flat": True,
            "maker_fill_assumptions": False,
            "learned_execution_saving_applied_to_backtest": False,
        },
        "validation": {
            "historical_status": (
                "training_only_diagnostic_reuse_current_survivor_universe"
            ),
            "training": [TRAINING_START.isoformat(), TRAINING_END.isoformat()],
            "training_folds": [
                [start.isoformat(), end.isoformat()]
                for start, end in TRAINING_FOLDS
            ],
            "historical_pass_is_not_oos_evidence": True,
            "no_historical_confirmation_or_lock_claim": True,
            "first_promotional_evidence_must_be_new_forward": True,
        },
        "training_eligibility_gate": {
            "minimum_outcomes": 1_277,
            "minimum_signal_decisions": 1_200,
            "minimum_invested_days": 500,
            "minimum_active_vintage_decisions": 250,
            "positive_total_return": True,
            "stress_total_return_positive": True,
            "minimum_annualized_return": 0.08,
            "minimum_stress_annualized_return": 0.04,
            "minimum_sharpe": 0.90,
            "minimum_stress_sharpe": 0.65,
            "minimum_profit_factor": 1.10,
            "minimum_stress_profit_factor": 1.05,
            "maximum_drawdown": 0.20,
            "maximum_stress_drawdown": 0.25,
            "minimum_positive_month_ratio": 0.55,
            "minimum_positive_folds": 5,
            "minimum_positive_stress_folds": 5,
            "required_folds": len(TRAINING_FOLDS),
            "minimum_worst_stress_fold_return": -0.10,
            "gross_edge_exceeds_costs": True,
            "stress_gross_edge_exceeds_costs": True,
            "maximum_absolute_market_beta": 0.50,
            "minimum_annualized_market_alpha": 0.02,
            "minimum_sharpe_improvement_over_benchmark": 0.10,
            "maximum_drawdown_ratio_to_benchmark": 0.85,
            "maximum_symbol_absolute_contribution_share": 0.15,
            "minimum_positive_leave_one_symbol_out_ratio": 0.80,
            "maximum_total_turnover": 80.0,
            "minimum_average_gross_exposure": 0.10,
            "maximum_post_net_gross": 0.400000001,
        },
        "forward_gate": {
            "start_utc": FORWARD_START_UTC,
            "minimum_calendar_days": 180,
            "minimum_observed_days": 165,
            "minimum_signal_decisions": 165,
            "minimum_invested_days": 60,
            "positive_total_return": True,
            "stress_total_return_positive": True,
            "minimum_annualized_return": 0.04,
            "minimum_stress_annualized_return": 0.02,
            "minimum_sharpe": 0.75,
            "minimum_stress_sharpe": 0.50,
            "maximum_drawdown": 0.15,
            "maximum_stress_drawdown": 0.18,
            "minimum_positive_month_ratio": 0.50,
            "positive_annualized_market_alpha": True,
            "sharpe_exceeds_benchmark": True,
            "drawdown_below_benchmark": True,
            "same_universe_signal_costs_and_code": True,
            "append_only": True,
            "no_refit": True,
            "all_checks_conjunctive": True,
        },
        "multiple_testing_disclosure": (
            "the external paper selected 28/5 after testing multiple horizons; "
            "locally this is one fixed test, but all existing market history "
            "is training reuse and only new forward data may promote it"
        ),
        "advancement_consequence": (
            "a complete training eligibility pass permits only freezing one "
            "orderless 180-day forward observer before 2026-09-01; it does not "
            "authorize shadow targets, paper or real orders"
        ),
        "results": None,
    }


def write_or_verify_protocol(
    path_value: typing.Union[str, pathlib.Path],
) -> dict:
    """Create the protocol atomically or verify its immutable copy."""

    path = pathlib.Path(path_value).resolve()
    protocol = frozen_protocol()
    payload = {**protocol, "protocol_sha256": common._json_hash(protocol)}
    if path.is_file():
        persisted = json.loads(path.read_text(encoding="utf-8"))
        if persisted != payload:
            raise ValueError("persisted market time-series protocol differs")
        return persisted
    common._atomic_json(path, payload)
    return payload


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", required=True)
    return parser


def main(argv=None) -> int:
    args = _parser().parse_args(argv)
    protocol = write_or_verify_protocol(args.output)
    print(json.dumps(protocol, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
