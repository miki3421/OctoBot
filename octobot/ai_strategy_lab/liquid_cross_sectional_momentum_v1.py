"""Frozen liquid cross-sectional momentum V1 protocol.

This module only writes or verifies a result-free research protocol.  It has
no market-data client, cannot calculate economic outcomes and cannot create
shadow, paper or real orders.  Historical evaluation is a separate post-freeze
step and every historical date is explicitly diagnostic reuse.
"""

from __future__ import annotations

import argparse
import datetime
import json
import pathlib
import typing

from octobot.ai_strategy_lab import cointegration_pairs_v1 as common


SCHEMA_VERSION = 1
PROTOCOL_VERSION = "crypto_perpetual_liquid_cross_sectional_momentum_v1"
PREREGISTRATION_DATE = "2026-08-28"

SOURCE_SNAPSHOT_BUNDLE_SHA256 = (
    "03d744e12e0494c98f4dae8490e229ee524a66b3df4660ea6eb34a6ee286c55b"
)
SOURCE_SNAPSHOT_MANIFEST_CONTENT_SHA256 = (
    "db2949822559506c925979a687e4bac9640c2c26b006b680072bd1028d292346"
)
HISTORY_BUNDLE_SHA256 = (
    "4158e252768a92a9bece0bc0e801d4e9b3830a693628512c880b68538b14e2da"
)
HISTORY_MANIFEST_CONTENT_SHA256 = (
    "9448e0e36c9f52767e6805389749a17d6d0b6f2ad5a5798508d54125795bafba"
)
MARKET_PANEL_SHA256 = (
    "0214ef8f70e362009f69e405e6ac568e0f0518f8b29a7821bc1ee2a2cdcc8535"
)

UNIVERSE_ASSETS = 120
MINIMUM_CONTIGUOUS_HISTORY_DAYS = 180
MINIMUM_ELIGIBLE_ASSETS = 20
FORMATION_DAYS = 21
HOLDING_DAYS = 7
TAIL_FRACTION = 0.30
SIDE_GROSS_EXPOSURE = 0.40
FEE_PER_TURNOVER = 0.0006
SLIPPAGE_PER_TURNOVER = 0.0002
STRESS_COST_MULTIPLIER = 3.0
UTC = datetime.timezone.utc

TRAINING_START = datetime.datetime(2023, 1, 1, tzinfo=UTC)
TRAINING_END = datetime.datetime(2026, 7, 1, tzinfo=UTC)
TRAINING_FOLDS = tuple(
    (
        datetime.datetime(year, month, 1, tzinfo=UTC),
        (
            datetime.datetime(year + 1, 1, 1, tzinfo=UTC)
            if month == 7
            else datetime.datetime(year, 7, 1, tzinfo=UTC)
        ),
    )
    for year in range(2023, 2027)
    for month in (1, 7)
    if datetime.datetime(year, month, 1, tzinfo=UTC) < TRAINING_END
)
FORWARD_START_UTC = "2026-09-01T00:00:00+00:00"


def frozen_protocol() -> dict:
    """Return the immutable, result-free momentum research plan."""

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
            "title": "Common Risk Factors in Cryptocurrency",
            "authors": ["Yukun Liu", "Aleh Tsyvinski", "Xi Wu"],
            "journal_doi": "10.1111/jofi.13119",
            "nber_working_paper": "w25882",
            "public_manuscript": (
                "https://economics.yale.edu/sites/default/files/2022-10/"
                "LiuTsyvinskiWu2019%20COMMON%20RISK%20FACTORS.pdf"
            ),
            "source_method": (
                "weekly ranking by completed three-week return; top and "
                "bottom 30 percent define the momentum factor"
            ),
            "source_result_is_not_local_evidence": True,
            "implementation_differences": [
                "fixed liquid Binance perpetual universe instead of spot coins",
                "equal weights instead of unavailable point-in-time market caps",
                "explicit funding, fees, slippage and stress costs",
                "fixed 0.40 gross exposure per side",
            ],
        },
        "hypothesis": {
            "name": "liquid_three_week_cross_sectional_continuation",
            "statement": (
                "among already liquid perpetuals, the highest completed "
                "three-week returns outperform the lowest over the next week "
                "after observed funding and executable costs"
            ),
            "economic_mechanism": (
                "cross-sectional return continuation rather than an outright "
                "forecast of the market direction"
            ),
            "economically_distinct_from": [
                "time-series trend V13/V18",
                "category momentum V1",
                "basis and funding carry",
                "cointegration mean reversion",
                "directional Level-5 and taker scalping",
            ],
            "one_configuration_only": True,
            "opposite_direction_tested": False,
            "long_only_variant_allowed": False,
        },
        "data": {
            "venue": "Binance USD-M",
            "instrument": "USDT linear perpetual",
            "source_snapshot_bundle_sha256": SOURCE_SNAPSHOT_BUNDLE_SHA256,
            "source_snapshot_manifest_content_sha256": (
                SOURCE_SNAPSHOT_MANIFEST_CONTENT_SHA256
            ),
            "history_bundle_sha256": HISTORY_BUNDLE_SHA256,
            "history_manifest_content_sha256": (
                HISTORY_MANIFEST_CONTENT_SHA256
            ),
            "market_panel_sha256": MARKET_PANEL_SHA256,
            "universe_assets": UNIVERSE_ASSETS,
            "universe_frozen": True,
            "taxonomy_used": False,
            "minimum_contiguous_history_days": (
                MINIMUM_CONTIGUOUS_HISTORY_DAYS
            ),
            "minimum_eligible_assets": MINIMUM_ELIGIBLE_ASSETS,
            "interpolation_or_forward_fill": False,
            "historical_survivorship_present": True,
            "historical_universe_selection_is_point_in_time": False,
        },
        "signal": {
            "decision_boundary": (
                "Monday 00:00 UTC after the preceding daily close is complete"
            ),
            "formation_days": FORMATION_DAYS,
            "holding_days": HOLDING_DAYS,
            "score": "close_t / close_t_minus_21_days - 1",
            "ranking_tie_break": "symbol ascending",
            "tail_fraction": TAIL_FRACTION,
            "tail_count": "max(1, floor(eligible_assets * 0.30))",
            "long": "highest scores",
            "short": "lowest scores excluding selected longs",
            "within_side_weight": "equal",
            "side_gross_exposure": SIDE_GROSS_EXPOSURE,
            "maximum_portfolio_gross": 2 * SIDE_GROSS_EXPOSURE,
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
            "fee_per_turnover": FEE_PER_TURNOVER,
            "slippage_per_turnover": SLIPPAGE_PER_TURNOVER,
            "stress_cost_multiplier": STRESS_COST_MULTIPLIER,
            "cost_on_netted_weight_change": True,
            "period_opened_and_closed_flat": True,
            "maker_fill_assumptions": False,
            "learned_execution_saving_applied_to_backtest": False,
            "learned_execution_overlay_role": (
                "separate orderless forward evidence only; never alpha"
            ),
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
        },
        "training_eligibility_gate": {
            "minimum_outcomes": 1_277,
            "minimum_invested_days": 1_200,
            "minimum_rebalances": 175,
            "positive_total_return": True,
            "stress_total_return_positive": True,
            "minimum_annualized_return": 0.08,
            "minimum_stress_annualized_return": 0.04,
            "minimum_sharpe": 0.80,
            "minimum_stress_sharpe": 0.50,
            "minimum_profit_factor": 1.10,
            "maximum_drawdown": 0.20,
            "maximum_stress_drawdown": 0.25,
            "minimum_positive_month_ratio": 0.55,
            "minimum_positive_folds": 5,
            "required_folds": len(TRAINING_FOLDS),
            "minimum_worst_stress_fold_return": -0.10,
            "both_side_contributions_nonnegative": True,
            "stress_both_side_contributions_nonnegative": True,
            "maximum_absolute_market_beta": 0.20,
            "maximum_symbol_absolute_contribution_share": 0.25,
            "minimum_positive_leave_one_symbol_out_ratio": 0.80,
        },
        "forward_gate": {
            "start_utc": FORWARD_START_UTC,
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
            "both_side_contributions_nonnegative": True,
            "stress_both_side_contributions_nonnegative": True,
            "maximum_absolute_market_beta": 0.20,
            "same_universe_signal_costs_and_code": True,
            "append_only": True,
            "no_refit": True,
            "all_checks_conjunctive": True,
        },
        "multiple_testing_disclosure": (
            "one literature-specified three-week weekly momentum configuration; "
            "no local lookback, direction, threshold or weighting search"
        ),
        "advancement_consequence": (
            "a complete training eligibility pass permits only freezing an "
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
            raise ValueError("persisted cross-sectional momentum protocol differs")
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
