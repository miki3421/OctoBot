"""Frozen expanded-universe cointegration pairs V2 protocol.

This module can only write or verify the result-free protocol.  It has no
market-data client, cannot evaluate economic outcomes and cannot create shadow,
paper or real orders.  Acquisition and evaluation live in separate code that
must be committed after this protocol is frozen.
"""

from __future__ import annotations

import argparse
import datetime
import json
import math
import pathlib
import typing

from octobot.ai_strategy_lab import cointegration_pairs_v1 as parent


SCHEMA_VERSION = 1
PROTOCOL_VERSION = "crypto_futures_expanded_cointegration_pairs_v2"
PREREGISTRATION_DATE = "2026-08-28"
PARENT_PROTOCOL_SHA256 = parent._json_hash(parent.frozen_protocol())
SOURCE_SNAPSHOT_BUNDLE_SHA256 = (
    "03d744e12e0494c98f4dae8490e229ee524a66b3df4660ea6eb34a6ee286c55b"
)
HISTORY_BUNDLE_SHA256 = (
    "4158e252768a92a9bece0bc0e801d4e9b3830a693628512c880b68538b14e2da"
)
UNIVERSE_ASSETS = 120
MAXIMUM_PAIR_TESTS = math.comb(UNIVERSE_ASSETS, 2)
MONTE_CARLO_SIMULATIONS = 1_500_000
MONTE_CARLO_SEED = parent.MONTE_CARLO_SEED
MINIMUM_MONTE_CARLO_RESOLUTION_MULTIPLE = (
    (MONTE_CARLO_SIMULATIONS + 1) * parent.FDR_Q / MAXIMUM_PAIR_TESTS
)
MAXIMUM_ABSOLUTE_MARKET_BETA = 0.30
MAXIMUM_PAIR_ABSOLUTE_CONTRIBUTION_SHARE = 0.35
MINIMUM_POSITIVE_LEAVE_ONE_SYMBOL_OUT_RATIO = 0.80
FORWARD_START_UTC = "2026-09-01T00:00:00+00:00"


def frozen_protocol() -> dict:
    """Return the immutable, result-free V2 research plan."""

    return {
        "schema_version": SCHEMA_VERSION,
        "protocol_version": PROTOCOL_VERSION,
        "preregistered_on": PREREGISTRATION_DATE,
        "status": "result_free_protocol_before_v2_outcomes",
        "research_only": True,
        "public_data_only": True,
        "credentials_used": False,
        "orders_authorized": False,
        "paper_orders_authorized": False,
        "automatic_promotion": False,
        "parent_research": {
            "protocol_version": parent.PROTOCOL_VERSION,
            "protocol_sha256": PARENT_PROTOCOL_SHA256,
            "outcome_observed_before_v2": True,
            "development_closed_trades": 9,
            "development_profit_factor": 2.2906822291360798,
            "development_maximum_drawdown": 0.02891070638662041,
            "development_stress_positive": True,
            "rejection_reason": "insufficient activity and temporal stability",
            "v2_change": (
                "expand the frozen liquid universe without changing the "
                "economic signal or trading thresholds"
            ),
        },
        "external_basis": {
            "references": [
                {
                    "title": "On cointegration and cryptocurrency dynamics",
                    "doi": "10.1007/s42521-021-00027-5",
                    "use": "mechanism and out-of-sample caution",
                },
                {
                    "title": (
                        "Evaluation of Dynamic Cointegration-Based Pairs "
                        "Trading Strategy in the Cryptocurrency Market"
                    ),
                    "arxiv": "2109.10662",
                    "use": "dynamic formation precedent, not parameter tuning",
                },
            ],
            "local_results_are_not_external_evidence": True,
        },
        "hypothesis": {
            "name": "expanded_rolling_cointegrated_futures_mean_reversion",
            "statement": (
                "the unchanged V1 convergence mechanism can produce enough "
                "independent trades when pair discovery uses a larger frozen "
                "liquid perpetual universe"
            ),
            "economic_mechanism": (
                "relative-value convergence with no outright market forecast"
            ),
            "one_configuration_only": True,
            "opposite_direction_tested": False,
        },
        "data": {
            "venue": "Binance USD-M",
            "instrument": "USDT linear perpetual",
            "source_snapshot_bundle_sha256": SOURCE_SNAPSHOT_BUNDLE_SHA256,
            "history_bundle_sha256": HISTORY_BUNDLE_SHA256,
            "universe_assets": UNIVERSE_ASSETS,
            "universe_frozen": True,
            "taxonomy_used": False,
            "daily_close_and_quote_volume_present": True,
            "signed_funding_present": True,
            "minimum_contiguous_history_days": parent.FORMATION_DAYS,
            "interpolation_or_forward_fill": False,
            "historical_survivorship_present": True,
        },
        "formation": {
            "lookback_days": parent.FORMATION_DAYS,
            "interval": parent.FORMATION_INTERVAL,
            "test": (
                "Engle-Granger log-price OLS residual ADF(0) against a "
                "deterministic independent-random-walk Monte Carlo null"
            ),
            "monte_carlo_simulations": MONTE_CARLO_SIMULATIONS,
            "monte_carlo_seed": MONTE_CARLO_SEED,
            "maximum_pair_tests": MAXIMUM_PAIR_TESTS,
            "minimum_empirical_p_value": 1.0 / (MONTE_CARLO_SIMULATIONS + 1),
            "strictest_bh_first_rank": parent.FDR_Q / MAXIMUM_PAIR_TESTS,
            "resolution_multiple_inside_strictest_bh": (
                MINIMUM_MONTE_CARLO_RESOLUTION_MULTIPLE
            ),
            "multiple_testing": "Benjamini-Hochberg",
            "false_discovery_rate": parent.FDR_Q,
            "bh_denominator": (
                "all eligible pairs before beta, stationarity, half-life or "
                "zero-crossing filters"
            ),
            "failed_prefilters_implicit_p_value": 1.0,
            "beta_bounds": [parent.MINIMUM_BETA, parent.MAXIMUM_BETA],
            "half_life_days": [
                parent.MINIMUM_HALF_LIFE_DAYS,
                parent.MAXIMUM_HALF_LIFE_DAYS,
            ],
            "minimum_zero_crossings": parent.MINIMUM_ZERO_CROSSINGS,
            "maximum_pairs": parent.MAXIMUM_PAIRS,
            "pair_overlap_allowed": False,
            "ranking": "ascending p-value then half-life then pair name",
        },
        "trading": {
            "entry_absolute_z": parent.ENTRY_Z,
            "exit_absolute_z": parent.EXIT_Z,
            "stop_absolute_z": parent.STOP_Z,
            "stopped_pair_reentry": "next monthly formation only",
            "hedge": "positive OLS beta, gross-normalized two-leg weights",
            "allocation": "one quarter gross per selected pair",
            "maximum_portfolio_gross": 1.0,
            "decision_time": "daily close; target applies to next daily return",
            "monthly_refit": "close every old model before replacement",
            "funding": "signed observed perpetual settlements",
            "fee_per_turnover": parent.FEE_PER_TURNOVER,
            "slippage_per_turnover": parent.SLIPPAGE_PER_TURNOVER,
            "stress_cost_multiplier": parent.STRESS_COST_MULTIPLIER,
            "maker_fill_assumptions": False,
            "book_filter": False,
            "regime_filter": False,
            "parameter_search": False,
        },
        "validation": {
            "all_historical_periods_status": (
                "diagnostic_reuse_current_survivor_universe_and_known_prices"
            ),
            "development": [
                parent.DEVELOPMENT_START.isoformat(),
                parent.DEVELOPMENT_END.isoformat(),
            ],
            "development_folds": [
                [start.isoformat(), end.isoformat()]
                for start, end in parent.DEVELOPMENT_FOLDS
            ],
            "confirmation": [
                parent.CONFIRMATION_START.isoformat(),
                parent.CONFIRMATION_END.isoformat(),
            ],
            "confirmation_status": "sealed_until_development_passes",
            "locked_final_test": [
                parent.LOCKED_START.isoformat(),
                parent.LOCKED_END.isoformat(),
            ],
            "locked_status": "sealed_until_confirmation_passes",
            "historical_pass_cannot_promote": True,
        },
        "development_gate": {
            "minimum_closed_trades": 24,
            "positive_total_return": True,
            "stress_total_return_positive": True,
            "minimum_annualized_return": 0.04,
            "minimum_profit_factor": 1.25,
            "minimum_stress_profit_factor": 1.05,
            "minimum_sharpe": 0.75,
            "maximum_drawdown": 0.10,
            "minimum_positive_month_ratio": 0.50,
            "minimum_positive_folds": 3,
            "required_folds": len(parent.DEVELOPMENT_FOLDS),
            "both_spread_directions_non_negative": True,
            "maximum_absolute_market_beta": MAXIMUM_ABSOLUTE_MARKET_BETA,
            "maximum_pair_absolute_contribution_share": (
                MAXIMUM_PAIR_ABSOLUTE_CONTRIBUTION_SHARE
            ),
            "minimum_positive_leave_one_symbol_out_ratio": (
                MINIMUM_POSITIVE_LEAVE_ONE_SYMBOL_OUT_RATIO
            ),
        },
        "confirmation_gate": {
            "minimum_closed_trades": 8,
            "positive_total_return": True,
            "stress_total_return_positive": True,
            "minimum_annualized_return": 0.02,
            "minimum_profit_factor": 1.20,
            "minimum_stress_profit_factor": 1.00,
            "minimum_sharpe": 0.50,
            "maximum_drawdown": 0.10,
            "minimum_positive_month_ratio": 0.50,
            "both_spread_directions_non_negative": True,
            "maximum_absolute_market_beta": MAXIMUM_ABSOLUTE_MARKET_BETA,
        },
        "locked_gate": {
            "minimum_closed_trades": 4,
            "positive_total_return": True,
            "stress_total_return_positive": True,
            "minimum_annualized_return": 0.02,
            "minimum_profit_factor": 1.20,
            "minimum_stress_profit_factor": 1.00,
            "minimum_sharpe": 0.50,
            "maximum_drawdown": 0.10,
            "both_spread_directions_non_negative": True,
            "maximum_absolute_market_beta": MAXIMUM_ABSOLUTE_MARKET_BETA,
        },
        "forward_gate": {
            "start_utc": FORWARD_START_UTC,
            "minimum_calendar_days": 180,
            "minimum_observed_days": 165,
            "append_only": True,
            "no_refit": True,
            "same_universe_signal_costs_and_code": True,
            "required_before_shadow_or_paper": True,
        },
        "multiple_testing_disclosure": (
            "one unchanged V1 signal configuration; the expanded universe is "
            "the only economic hypothesis change and all V2 historical data "
            "are non-promotional diagnostic reuse"
        ),
        "promotion_consequence": (
            "three historical passes authorize only an immutable orderless "
            "forward observer; no shadow, paper or real order"
        ),
        "results": None,
    }


def write_or_verify_protocol(
    path_value: typing.Union[str, pathlib.Path],
) -> dict:
    """Create the protocol atomically or verify the existing immutable copy."""

    path = pathlib.Path(path_value).resolve()
    protocol = frozen_protocol()
    payload = {**protocol, "protocol_sha256": parent._json_hash(protocol)}
    if path.is_file():
        persisted = json.loads(path.read_text(encoding="utf-8"))
        if persisted != payload:
            raise ValueError("persisted Cointegration Pairs V2 protocol differs")
        return persisted
    parent._atomic_json(path, payload)
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
