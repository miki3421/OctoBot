"""Frozen winner-basket versus BTC momentum V2 protocol.

V2 is explicitly informed by the rejected V1 training result.  This module
only persists the next result-free hypothesis; it cannot read prices, evaluate
returns, access an exchange, or create any kind of order.
"""

from __future__ import annotations

import argparse
import json
import pathlib
import typing

from octobot.ai_strategy_lab import cointegration_pairs_v1 as common
from octobot.ai_strategy_lab import liquid_cross_sectional_momentum_v1 as parent


SCHEMA_VERSION = 1
PROTOCOL_VERSION = "crypto_perpetual_winner_btc_hedged_momentum_v2"
PREREGISTRATION_DATE = "2026-08-28"
HEDGE_SYMBOL = "BTCUSDT"

PARENT_PROTOCOL_SHA256 = (
    "b6d015feb077f61eec7f280bbc6864a0b66ee5bff8718329aedc918b617689a0"
)
PARENT_REPORT_SHA256 = (
    "30d62bd5d9d965fa87149ad20576dc4589875e22369fc67ebcaa2db8eb571996"
)
PARENT_TRAJECTORY_SHA256 = (
    "bf3a22a2b062d3eefb1c855e22e77726cd1ee9882d853a73884098003a9c5673"
)
PARENT_MANIFEST_CONTENT_SHA256 = (
    "79df99dba97f45c9c61e5c35bc825a75886f7e5cff0addde0db02f47a8835dd1"
)


def frozen_protocol() -> dict:
    """Return the single immutable V2 training-informed hypothesis."""

    return {
        "schema_version": SCHEMA_VERSION,
        "protocol_version": PROTOCOL_VERSION,
        "preregistered_on": PREREGISTRATION_DATE,
        "status": "result_free_training_informed_protocol",
        "research_only": True,
        "public_data_only": True,
        "credentials_used": False,
        "orders_authorized": False,
        "paper_orders_authorized": False,
        "automatic_promotion": False,
        "parent_v1": {
            "protocol_sha256": PARENT_PROTOCOL_SHA256,
            "report_sha256": PARENT_REPORT_SHA256,
            "trajectory_sha256": PARENT_TRAJECTORY_SHA256,
            "manifest_content_sha256": PARENT_MANIFEST_CONTENT_SHA256,
            "verdict": "REJECTED_TRAINING_NO_FORWARD",
            "passed_checks": 19,
            "total_checks": 21,
            "training_total_return": 0.9327203492553464,
            "training_stress_total_return": 0.6073255833583777,
            "winner_long_contribution": 0.9815149697980796,
            "loser_short_contribution": -0.2788574740356482,
            "stress_winner_long_contribution": 0.894816475260245,
            "stress_loser_short_contribution": -0.37642381508237754,
            "observed_before_v2": True,
            "not_reinterpreted_as_pass": True,
            "v2_change": (
                "replace only the short-loser basket with the preregistered "
                "fixed BTC hedge; retain the winner signal and all costs"
            ),
        },
        "external_hypothesis": {
            "title": "Common Risk Factors in Cryptocurrency",
            "authors": ["Yukun Liu", "Aleh Tsyvinski", "Xi Wu"],
            "journal_doi": "10.1111/jofi.13119",
            "nber_working_paper": "w25882",
            "source_findings_used": [
                "three-week momentum is the main momentum factor",
                "weekly top-minus-bottom sorts exhibit continuation",
                (
                    "shorting Bitcoin instead of the loser portfolio is a "
                    "reported robustness test"
                ),
                "momentum is stronger among larger coins",
            ],
            "source_results_are_not_local_evidence": True,
        },
        "hypothesis": {
            "name": "liquid_winner_basket_outperforms_btc",
            "statement": (
                "the top 30 percent of liquid perpetuals by completed "
                "three-week return outperform a fixed short BTC hedge over "
                "the following week after funding and executable costs"
            ),
            "economic_mechanism": (
                "cross-sectional winner continuation measured relative to the "
                "most liquid crypto market hedge"
            ),
            "one_configuration_only": True,
            "opposite_direction_tested": False,
            "unhedged_long_only_variant_allowed": False,
            "loser_short_variant_is_closed_parent_v1": True,
        },
        "data": {
            "venue": "Binance USD-M",
            "instrument": "USDT linear perpetual",
            "source_snapshot_bundle_sha256": (
                parent.SOURCE_SNAPSHOT_BUNDLE_SHA256
            ),
            "history_bundle_sha256": parent.HISTORY_BUNDLE_SHA256,
            "market_panel_sha256": parent.MARKET_PANEL_SHA256,
            "universe_assets": parent.UNIVERSE_ASSETS,
            "universe_frozen": True,
            "taxonomy_used": False,
            "minimum_contiguous_history_days": (
                parent.MINIMUM_CONTIGUOUS_HISTORY_DAYS
            ),
            "minimum_eligible_assets": parent.MINIMUM_ELIGIBLE_ASSETS,
            "historical_survivorship_present": True,
            "interpolation_or_forward_fill": False,
        },
        "signal": {
            "decision_boundary": (
                "Monday 00:00 UTC after the preceding daily close is complete"
            ),
            "formation_days": parent.FORMATION_DAYS,
            "holding_days": parent.HOLDING_DAYS,
            "score": "close_t / close_t_minus_21_days - 1",
            "ranking_tie_break": "symbol ascending",
            "winner_fraction": parent.TAIL_FRACTION,
            "winner_count": "max(1, floor(eligible_assets * 0.30))",
            "winner_weighting": "equal",
            "winner_gross_exposure": parent.SIDE_GROSS_EXPOSURE,
            "hedge_symbol": HEDGE_SYMBOL,
            "hedge_direction": "short",
            "hedge_gross_exposure_before_netting": parent.SIDE_GROSS_EXPOSURE,
            "btc_if_also_a_winner": "aggregate and net before costs",
            "maximum_post_net_gross": 2 * parent.SIDE_GROSS_EXPOSURE,
            "target_between_rebalances": "unchanged",
            "future_data_used": False,
            "model_fitted": False,
            "parameter_search": False,
            "regime_filter": False,
            "volatility_target": False,
            "stop_or_take_profit": False,
            "book_feature_in_alpha": False,
        },
        "economics": {
            "price_pnl": "next completed daily perpetual close-to-close return",
            "funding_pnl": "actual signed settlements while target is active",
            "fee_per_turnover": parent.FEE_PER_TURNOVER,
            "slippage_per_turnover": parent.SLIPPAGE_PER_TURNOVER,
            "stress_cost_multiplier": parent.STRESS_COST_MULTIPLIER,
            "cost_on_netted_weight_change": True,
            "period_opened_and_closed_flat": True,
            "maker_fill_assumptions": False,
            "kucoin_btc_execution_model_transfers_to_binance": False,
            "learned_execution_saving_applied_to_backtest": False,
            "book_role": (
                "separate venue-specific execution research; no alpha or cost "
                "credit until independently validated on Binance"
            ),
        },
        "validation": {
            "historical_status": (
                "training_only_after_parent_v1_current_survivor_universe"
            ),
            "training": [
                parent.TRAINING_START.isoformat(),
                parent.TRAINING_END.isoformat(),
            ],
            "training_folds": [
                [start.isoformat(), end.isoformat()]
                for start, end in parent.TRAINING_FOLDS
            ],
            "historical_pass_is_not_oos_evidence": True,
            "no_historical_confirmation_or_lock_claim": True,
            "first_promotional_evidence_must_be_new_forward": True,
        },
        "training_eligibility_gate": {
            "minimum_outcomes": 1_277,
            "minimum_invested_days": 1_200,
            "minimum_rebalances": 175,
            "minimum_btc_hedged_days": 1_200,
            "positive_total_return": True,
            "stress_total_return_positive": True,
            "minimum_annualized_return": 0.08,
            "minimum_stress_annualized_return": 0.04,
            "minimum_sharpe": 0.80,
            "minimum_stress_sharpe": 0.50,
            "minimum_profit_factor": 1.10,
            "minimum_stress_profit_factor": 1.05,
            "maximum_drawdown": 0.20,
            "maximum_stress_drawdown": 0.25,
            "minimum_positive_month_ratio": 0.55,
            "minimum_positive_folds": 5,
            "minimum_positive_stress_folds": 5,
            "required_folds": len(parent.TRAINING_FOLDS),
            "minimum_worst_stress_fold_return": -0.10,
            "combined_gross_edge_exceeds_costs": True,
            "stress_combined_gross_edge_exceeds_costs": True,
            "maximum_absolute_market_beta": 0.20,
            "maximum_non_hedge_symbol_absolute_contribution_share": 0.25,
            "maximum_btc_absolute_contribution_share": 0.60,
            "minimum_positive_leave_one_winner_symbol_out_ratio": 0.80,
            "maximum_total_turnover": 130.0,
            "maximum_post_net_gross": 0.80,
            "individual_hedge_contribution_may_be_negative": True,
        },
        "forward_gate": {
            "start_utc": parent.FORWARD_START_UTC,
            "minimum_calendar_days": 180,
            "minimum_observed_days": 165,
            "minimum_rebalances": 24,
            "positive_total_return": True,
            "stress_total_return_positive": True,
            "minimum_annualized_return": 0.04,
            "minimum_stress_annualized_return": 0.02,
            "minimum_sharpe": 0.75,
            "minimum_stress_sharpe": 0.50,
            "maximum_drawdown": 0.12,
            "maximum_stress_drawdown": 0.15,
            "minimum_positive_month_ratio": 0.50,
            "combined_gross_edge_exceeds_costs": True,
            "stress_combined_gross_edge_exceeds_costs": True,
            "maximum_absolute_market_beta": 0.20,
            "same_universe_signal_costs_and_code": True,
            "append_only": True,
            "no_refit": True,
            "all_checks_conjunctive": True,
        },
        "multiple_testing_disclosure": (
            "one V2 hedge specified after observing V1; no local hedge ratio, "
            "lookback, threshold, direction or weight search, and all history "
            "is training-only"
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
    path = pathlib.Path(path_value).resolve()
    protocol = frozen_protocol()
    payload = {**protocol, "protocol_sha256": common._json_hash(protocol)}
    if path.is_file():
        persisted = json.loads(path.read_text(encoding="utf-8"))
        if persisted != payload:
            raise ValueError("persisted winner/BTC momentum protocol differs")
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
