"""Frozen long-only liquid-winners momentum V1 protocol.

This module can only materialize or verify a result-free research protocol.
It cannot read market outcomes, access an exchange or create an order.
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
PROTOCOL_VERSION = "crypto_perpetual_liquid_winners_momentum_v1"
PREREGISTRATION_DATE = "2026-08-28"

UNIVERSE_ASSETS = data_parent.UNIVERSE_ASSETS
MINIMUM_CONTIGUOUS_HISTORY_DAYS = 180
MINIMUM_ELIGIBLE_ASSETS = 30
LIQUID_FRACTION = 0.30
WINNER_FRACTION = 0.30
LIQUIDITY_LOOKBACK_DAYS = 14
FORMATION_DAYS = 14
HOLDING_DAYS = 14
REBALANCE_ANCHOR = datetime.date(1970, 1, 5)
MAXIMUM_GROSS_EXPOSURE = 0.40
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
            "title": "Momentum and liquidity in cryptocurrencies",
            "authors": ["Stjepan Begusic", "Zvonko Kostanjcar"],
            "public_manuscript": "https://arxiv.org/abs/1904.00890",
            "findings_used": [
                (
                    "momentum is statistically strongest within the most "
                    "liquid cryptocurrencies"
                ),
                (
                    "the exact bivariate sort uses fourteen-day momentum, "
                    "fourteen-day Amihud illiquidity and thirty-percent tails"
                ),
                (
                    "the long-only liquid-winners portfolio improves "
                    "risk-adjusted performance over the market benchmark"
                ),
                "the portfolios are equal-weighted and rebalanced biweekly",
            ],
            "external_sample": "spot cryptocurrencies, 2015-01 through 2019-01",
            "external_result_is_not_local_evidence": True,
            "implementation_differences": [
                "fixed current-survivor Binance USD-M perpetual universe",
                "quote volume from the frozen futures panel",
                "fixed 0.40 gross exposure",
                "actual perpetual funding and project-standard costs",
                "same-liquid-bucket equal-weight benchmark",
            ],
        },
        "local_development_disclosure": {
            "shared_history_has_been_reused": True,
            "known_prior_result": (
                "the 21/7 all-eligible cross-sectional V1 winner leg was "
                "positive while its loser short leg was negative"
            ),
            "known_prior_result_is_not_oos": True,
            "exact_14_14_liquidity_bivariate_outcome_seen": False,
            "parameter_choice_source": "external manuscript, not local search",
            "historical_pass_is_only_screening": True,
        },
        "hypothesis": {
            "name": "liquid_winner_continuation",
            "statement": (
                "among causally eligible perpetuals, the most liquid prior "
                "winners continue to outperform the same liquid universe "
                "over the next fourteen days after funding and costs"
            ),
            "economic_mechanism": (
                "under-reaction and positive-feedback trading persist in "
                "liquid assets, while liquidity limits implementation drag"
            ),
            "economically_distinct_from": [
                "long-short winner/loser and winner/BTC momentum V1/V2",
                "aggregate market-state timing",
                "V13 covariance-sized dual momentum with conditional shorts",
                "basis, funding carry and cointegration",
                "directional Level-5 and taker scalping",
            ],
            "one_configuration_only": True,
            "short_variant_allowed": False,
            "market_state_filter_allowed": False,
            "volatility_scaling_allowed": False,
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
                "each anchored second Monday 00:00 UTC after the daily close"
            ),
            "rebalance_anchor": REBALANCE_ANCHOR.isoformat(),
            "rebalance_rule": "integer UTC days from anchor modulo fourteen",
            "formation_days": FORMATION_DAYS,
            "holding_days": HOLDING_DAYS,
            "liquidity_lookback_days": LIQUIDITY_LOOKBACK_DAYS,
            "amihud_measure": (
                "mean(abs(close_s / close_s_minus_1 - 1) / quote_volume_s) "
                "over the fourteen completed daily intervals"
            ),
            "liquid_fraction": LIQUID_FRACTION,
            "liquid_count": (
                "max(1, floor(eligible_assets * liquid_fraction))"
            ),
            "liquidity_order": "Amihud ascending, symbol ascending tie-break",
            "momentum_score": "close_t / close_t_minus_14 - 1",
            "winner_fraction": WINNER_FRACTION,
            "winner_count": (
                "max(1, floor(liquid_assets * winner_fraction))"
            ),
            "winner_order": "momentum descending, symbol ascending tie-break",
            "active_target": (
                "long equal-weight liquid winners at 0.40 aggregate gross"
            ),
            "target_between_rebalances": "unchanged for fourteen days",
            "future_data_used": False,
            "model_fitted": False,
            "parameter_search": False,
            "stop_or_take_profit": False,
        },
        "benchmark": {
            "name": "same_liquid_bucket_equal_weight",
            "construction": (
                "long equal-weight every asset in the same causal liquid "
                "thirty-percent bucket at the same 0.40 gross exposure"
            ),
            "same_funding_costs_calendar_and_rebalance": True,
            "minimum_annualized_excess_return": 0.03,
            "minimum_sharpe_improvement": 0.10,
            "maximum_drawdown_ratio": 0.90,
        },
        "economics": {
            "price_pnl": "next completed daily perpetual close-to-close return",
            "funding_pnl": "actual signed settlements while target is active",
            "fee_per_turnover": FEE_PER_TURNOVER,
            "slippage_per_turnover": SLIPPAGE_PER_TURNOVER,
            "stress_cost_multiplier": STRESS_COST_MULTIPLIER,
            "cost_on_netted_weight_change": True,
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
            "minimum_invested_days": 1_200,
            "minimum_rebalances": 90,
            "minimum_active_rebalances": 90,
            "positive_total_return": True,
            "stress_total_return_positive": True,
            "minimum_annualized_return": 0.10,
            "minimum_stress_annualized_return": 0.06,
            "minimum_sharpe": 0.90,
            "minimum_stress_sharpe": 0.70,
            "minimum_profit_factor": 1.10,
            "minimum_stress_profit_factor": 1.05,
            "maximum_drawdown": 0.30,
            "maximum_stress_drawdown": 0.35,
            "minimum_positive_month_ratio": 0.55,
            "minimum_positive_folds": 5,
            "minimum_positive_stress_folds": 5,
            "required_folds": len(TRAINING_FOLDS),
            "minimum_worst_stress_fold_return": -0.15,
            "gross_edge_exceeds_costs": True,
            "stress_gross_edge_exceeds_costs": True,
            "maximum_absolute_market_beta": 1.25,
            "minimum_annualized_market_alpha": 0.03,
            "minimum_annualized_excess_return_over_benchmark": 0.03,
            "minimum_sharpe_improvement_over_benchmark": 0.10,
            "maximum_drawdown_ratio_to_benchmark": 0.90,
            "maximum_symbol_absolute_contribution_share": 0.25,
            "minimum_positive_leave_one_symbol_out_ratio": 0.80,
            "maximum_total_turnover": 60.0,
            "minimum_average_gross_exposure": 0.35,
            "maximum_post_net_gross": 0.400000001,
        },
        "forward_gate": {
            "start_utc": FORWARD_START_UTC,
            "minimum_calendar_days": 180,
            "minimum_observed_days": 165,
            "minimum_rebalances": 11,
            "minimum_active_rebalances": 11,
            "minimum_invested_days": 150,
            "positive_total_return": True,
            "stress_total_return_positive": True,
            "minimum_annualized_return": 0.06,
            "minimum_stress_annualized_return": 0.03,
            "minimum_sharpe": 0.75,
            "minimum_stress_sharpe": 0.50,
            "maximum_drawdown": 0.25,
            "maximum_stress_drawdown": 0.30,
            "minimum_positive_month_ratio": 0.50,
            "positive_annualized_market_alpha": True,
            "positive_annualized_excess_return_over_benchmark": True,
            "sharpe_exceeds_benchmark": True,
            "drawdown_below_benchmark": True,
            "gross_edge_exceeds_costs": True,
            "same_universe_signal_costs_and_code": True,
            "append_only": True,
            "no_refit": True,
            "all_checks_conjunctive": True,
        },
        "multiple_testing_disclosure": (
            "the shared historical panel and prior winner-leg result are "
            "known; this one externally fixed 14/14 bivariate sort is only a "
            "screen, and only new forward data may promote it"
        ),
        "advancement_consequence": (
            "a complete training eligibility pass permits only freezing one "
            "orderless 180-day forward observer before 2026-09-01; it does "
            "not authorize shadow targets, paper or real orders"
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
            raise ValueError("persisted liquid-winners protocol differs")
        return persisted
    common._atomic_json(path, payload)
    return payload


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", required=True)
    return parser


def main(argv=None) -> int:
    args = _parser().parse_args(argv)
    result = write_or_verify_protocol(args.output)
    print(
        json.dumps(
            {
                "path": str(pathlib.Path(args.output).resolve()),
                "protocol_sha256": result["protocol_sha256"],
                "results": None,
                "orders_authorized": False,
            },
            indent=2,
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
