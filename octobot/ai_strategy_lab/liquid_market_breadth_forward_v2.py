"""Frozen forward-only breadth-confirmed market momentum V2 protocol.

V2 is explicitly derived from the rejected historical V1 diagnosis.  It may
only be evaluated on new bars from September 2026.  This module cannot read
market data, calculate a target, use credentials or place an order.
"""

from __future__ import annotations

import argparse
import datetime
import json
import pathlib
import typing

from octobot.ai_strategy_lab import cointegration_pairs_v1 as common
from octobot.ai_strategy_lab import (
    liquid_market_timeseries_momentum_v1 as parent,
)


SCHEMA_VERSION = 1
PROTOCOL_VERSION = "crypto_liquid_market_breadth_forward_v2"
PREREGISTERED_ON = "2026-08-28"

PARENT_PROTOCOL_SHA256 = (
    "1fee1e99ec42521c7cdad84f42c61d23da1d2a8be38845dda19aba6ae7794913"
)
PARENT_PROTOCOL_FILE_SHA256 = (
    "5b9b0df1f936d72c48783bd4f494fc01a194ee7038f33a9bb255558a30ab7cba"
)
PARENT_IMPLEMENTATION_LOCK_FILE_SHA256 = (
    "d360f2849893ec36a457c7e612a591acb6f2236791fa3ba80d463f6c25555f90"
)
PARENT_IMPLEMENTATION_LOCK_CONTENT_SHA256 = (
    "e9d40a2e9e4c2a3666a9f3b597b9768c597efad30b93f9d979eab5e67be55351"
)
PARENT_REPORT_SHA256 = (
    "470b0b7f5ed909919607f2f6be4fda94a9bbd75941b908789f005eeb537060a1"
)
PARENT_TRAJECTORY_SHA256 = (
    "70656149ab5b23e3d41aabb343aa538057090336593a30cf227cf05844d36385"
)
PARENT_MANIFEST_FILE_SHA256 = (
    "e1d38c505eeaddab3ef25ed9827d9248555befe0310365436706302b527b5d0c"
)
PARENT_MANIFEST_CONTENT_SHA256 = (
    "c14af4d8fb7e31a3a8cbdc332d72c2f675af7ad56d5f7b8a0723746a3ebe65f5"
)

UPSTREAM_PROTOCOL_FILE_SHA256 = (
    "4b46004584f352230339afccfc8c2c950d72ddbd5b126a82fe159483830cb616"
)
UPSTREAM_PROTOCOL_SHA256 = (
    "c2d1abbc716a4775d6cdac15774613f657009adab55984189bf2f2b1dc42e010"
)
UPSTREAM_IMPLEMENTATION_LOCK_FILE_SHA256 = (
    "81b1a954c106e0ad8011a2686312e340acc0f6dc2f2477bbab786306fa52a0f2"
)
UPSTREAM_IMPLEMENTATION_LOCK_SHA256 = (
    "9b3bda6f2771d55aa1d66b1c9148eec3feb222d50f70d7d47678eba7e7279de4"
)
UPSTREAM_RUNNER_SHA256 = (
    "63f9f58609a9e227cdd70455d91839634d6aef7d03aac14803bec506178632eb"
)

WARMUP_START = datetime.date(2026, 7, 2)
FORWARD_START = datetime.date(2026, 9, 1)
FORWARD_CALENDAR_DAYS = 180
FORWARD_CUTOFF_EXCLUSIVE = FORWARD_START + datetime.timedelta(
    days=FORWARD_CALENDAR_DAYS
)
DAILY_FINALIZATION_DELAY_MINUTES = 25
MINIMUM_POSITIVE_BREADTH = 2.0 / 3.0
BOOTSTRAP_SIMULATIONS = 20_000
BOOTSTRAP_BLOCK_DAYS = 14
BOOTSTRAP_SEED = 20_260_828
FAMILYWISE_HYPOTHESES = 4
FAMILYWISE_ALPHA = 0.05
PER_CANDIDATE_ALPHA = FAMILYWISE_ALPHA / FAMILYWISE_HYPOTHESES
BOOTSTRAP_CONFIDENCE = 1.0 - PER_CANDIDATE_ALPHA


def frozen_protocol() -> dict:
    """Return the result-free, forward-only V2 protocol."""

    if common._json_hash(parent.frozen_protocol()) != PARENT_PROTOCOL_SHA256:
        raise RuntimeError("parent market time-series protocol changed")
    return {
        "schema_version": SCHEMA_VERSION,
        "protocol_version": PROTOCOL_VERSION,
        "preregistered_on": PREREGISTERED_ON,
        "status": "result_free_forward_only_protocol_requires_lock",
        "research_only": True,
        "observation_only": True,
        "public_data_only": True,
        "credentials_used": False,
        "orders_authorized": False,
        "paper_orders_authorized": False,
        "automatic_promotion": False,
        "historical_evaluation_allowed": False,
        "lineage": {
            "parent_protocol_sha256": PARENT_PROTOCOL_SHA256,
            "parent_protocol_file_sha256": PARENT_PROTOCOL_FILE_SHA256,
            "parent_implementation_lock_file_sha256": (
                PARENT_IMPLEMENTATION_LOCK_FILE_SHA256
            ),
            "parent_implementation_lock_content_sha256": (
                PARENT_IMPLEMENTATION_LOCK_CONTENT_SHA256
            ),
            "parent_report_sha256": PARENT_REPORT_SHA256,
            "parent_trajectory_sha256": PARENT_TRAJECTORY_SHA256,
            "parent_manifest_file_sha256": PARENT_MANIFEST_FILE_SHA256,
            "parent_manifest_content_sha256": (
                PARENT_MANIFEST_CONTENT_SHA256
            ),
            "parent_verdict": "REJECTED_TRAINING_NO_FORWARD",
            "parent_passed_checks": 26,
            "parent_total_checks": 30,
        },
        "derivation_disclosure": {
            "parent_outcomes_read_before_v2": True,
            "post_hoc_diagnosis_read_before_v2": True,
            "observed_failure_regime": (
                "2026 active signals had materially narrower positive "
                "cross-sectional breadth than earlier years"
            ),
            "historical_v2_outcome_must_not_be_calculated": True,
            "breadth_threshold_source": (
                "fixed two-thirds supermajority, not a local threshold search"
            ),
            "first_economic_evidence_is_forward": True,
        },
        "market_evidence": {
            "venue": "Binance USD-M public futures API",
            "frozen_universe_assets": parent.UNIVERSE_ASSETS,
            "source_snapshot_bundle_sha256": (
                parent.data_parent.SOURCE_SNAPSHOT_BUNDLE_SHA256
            ),
            "history_bundle_sha256": parent.data_parent.HISTORY_BUNDLE_SHA256,
            "market_panel_sha256": parent.data_parent.MARKET_PANEL_SHA256,
            "history_last_bar": "2026-07-01",
            "warmup_start_bar": WARMUP_START.isoformat(),
            "upstream_archive": {
                "observer": "diversified_trend_cointegration_forward_v1",
                "protocol_file_sha256": UPSTREAM_PROTOCOL_FILE_SHA256,
                "protocol_sha256": UPSTREAM_PROTOCOL_SHA256,
                "implementation_lock_file_sha256": (
                    UPSTREAM_IMPLEMENTATION_LOCK_FILE_SHA256
                ),
                "implementation_lock_sha256": (
                    UPSTREAM_IMPLEMENTATION_LOCK_SHA256
                ),
                "runner_sha256": UPSTREAM_RUNNER_SHA256,
                "daily_and_raw_mounted_read_only": True,
                "no_second_download_or_collector": True,
            },
            "quote_volume_source": (
                "field seven of each hash-verified Binance daily kline row"
            ),
            "complete_contiguous_120_symbol_panel_required": True,
            "missing_or_mutated_upstream_record_fails_closed": True,
        },
        "timeline": {
            "warmup_start_bar_utc": WARMUP_START.isoformat(),
            "warmup_end_exclusive_bar_utc": FORWARD_START.isoformat(),
            "warmup_is_never_an_economic_outcome": True,
            "official_first_decision_bar": FORWARD_START.isoformat(),
            "official_first_decision_not_before_utc": (
                "2026-09-02T00:25:00+00:00"
            ),
            "official_first_mature_outcome_bar": "2026-09-02",
            "minimum_calendar_days": FORWARD_CALENDAR_DAYS,
            "cutoff_exclusive_bar": FORWARD_CUTOFF_EXCLUSIVE.isoformat(),
            "earliest_gate_evaluation_not_before_utc": (
                f"{FORWARD_CUTOFF_EXCLUSIVE.isoformat()}T00:25:00+00:00"
            ),
            "daily_finalization_delay_minutes": (
                DAILY_FINALIZATION_DELAY_MINUTES
            ),
        },
        "signal": {
            "parent_signal_reused_exactly": True,
            "formation_days": parent.FORMATION_DAYS,
            "holding_days": parent.HOLDING_DAYS,
            "staggered_vintages": parent.STAGGERED_VINTAGES,
            "vintage_anchor": "UTC epoch day modulo five",
            "vintage_gross_exposure": parent.VINTAGE_GROSS_EXPOSURE,
            "maximum_gross_exposure": parent.MAXIMUM_GROSS_EXPOSURE,
            "liquid_basket_assets": parent.LIQUID_BASKET_ASSETS,
            "liquidity_lookback_days": parent.LIQUIDITY_LOOKBACK_DAYS,
            "parent_upper_tercile_rule": (
                parent.frozen_protocol()["signal"]["entry_rule"]
            ),
            "breadth_measure": (
                "fraction of the current causal liquid basket with strictly "
                "positive completed 28-day return"
            ),
            "minimum_positive_breadth": MINIMUM_POSITIVE_BREADTH,
            "entry_rule": (
                "parent signal is active and positive breadth is at least "
                "two-thirds"
            ),
            "inactive_vintage": "cash",
            "no_other_filter_or_parameter_change": True,
            "historical_v2_simulation_forbidden": True,
        },
        "counterfactuals": {
            "parent_v1": (
                "same market score and five vintages without breadth gate"
            ),
            "continuous_benchmark": (
                "same five causal liquid-basket vintages always long"
            ),
            "same_gross_funding_costs_and_calendar": True,
            "evaluated_from_same_flat_forward_start": True,
        },
        "economics": {
            "price_pnl": "next completed daily perpetual close-to-close return",
            "funding_pnl": "actual signed settlements while target is active",
            "fee_per_turnover": parent.FEE_PER_TURNOVER,
            "slippage_per_turnover": parent.SLIPPAGE_PER_TURNOVER,
            "stress_cost_multiplier": parent.STRESS_COST_MULTIPLIER,
            "cost_on_netted_aggregate_weight_change": True,
            "first_official_decision_starts_flat": True,
            "maker_fill_assumptions": False,
            "learned_execution_saving_applied": False,
        },
        "multiple_testing_control": {
            "prospective_hypotheses_accounted": FAMILYWISE_HYPOTHESES,
            "familywise_alpha": FAMILYWISE_ALPHA,
            "bonferroni_per_candidate_alpha": PER_CANDIDATE_ALPHA,
            "required_bootstrap_confidence": BOOTSTRAP_CONFIDENCE,
            "bootstrap_simulations": BOOTSTRAP_SIMULATIONS,
            "circular_block_days": BOOTSTRAP_BLOCK_DAYS,
            "seed": BOOTSTRAP_SEED,
            "lower_bound_of_annualized_mean_return_must_exceed_zero": True,
        },
        "forward_gate": {
            "required_market_records": FORWARD_CALENDAR_DAYS,
            "required_decision_records": FORWARD_CALENDAR_DAYS,
            "minimum_mature_outcomes": FORWARD_CALENDAR_DAYS - 1,
            "minimum_valid_signal_decisions": 165,
            "minimum_active_vintage_decisions": 25,
            "minimum_invested_days": 50,
            "positive_total_return": True,
            "stress_total_return_positive": True,
            "minimum_annualized_return": 0.04,
            "minimum_stress_annualized_return": 0.02,
            "minimum_sharpe": 0.75,
            "minimum_stress_sharpe": 0.50,
            "minimum_profit_factor": 1.05,
            "minimum_stress_profit_factor": 1.02,
            "maximum_drawdown": 0.15,
            "maximum_stress_drawdown": 0.18,
            "minimum_positive_month_ratio": 0.50,
            "positive_annualized_alpha_vs_continuous": True,
            "minimum_sharpe_improvement_vs_continuous": 0.10,
            "maximum_drawdown_ratio_vs_continuous": 0.85,
            "minimum_sharpe_improvement_vs_parent_v1": 0.05,
            "maximum_drawdown_ratio_vs_parent_v1": 0.90,
            "gross_edge_exceeds_costs": True,
            "stress_gross_edge_exceeds_costs": True,
            "maximum_symbol_absolute_contribution_share": 0.15,
            "maximum_total_turnover": 25.0,
            "minimum_average_gross_exposure": 0.08,
            "maximum_post_net_gross": 0.400000001,
            "bootstrap_lower_bound_positive": True,
            "complete_hash_chains_and_raw_lineage": True,
            "same_signal_costs_code_no_refit": True,
            "all_checks_conjunctive": True,
        },
        "journal": {
            "one_decision_per_official_bar": True,
            "matured_outcome_attached_to_following_bar": True,
            "append_only_hash_chain": True,
            "recompute_all_prior_payloads_exactly_each_run": True,
            "targets_are_research_observations_not_orders": True,
        },
        "implementation_lock": {
            "required_before_first_official_record": True,
            "must_bind_protocol_parent_upstream_sources_and_tests": True,
            "source_change_after_lock_fails_closed": True,
        },
        "promotion_consequence": (
            "a complete PASS permits only manual guarded-paper review and a "
            "second independent confirmation; it never authorizes an order"
        ),
        "results": None,
    }


def protocol_payload() -> dict:
    frozen = frozen_protocol()
    return {**frozen, "protocol_sha256": common._json_hash(frozen)}


def write_or_verify_protocol(
    path_value: typing.Union[str, pathlib.Path],
) -> dict:
    path = pathlib.Path(path_value).resolve()
    payload = protocol_payload()
    if path.is_file():
        persisted = json.loads(path.read_text(encoding="utf-8"))
        if persisted != payload:
            raise ValueError("persisted breadth-forward V2 protocol differs")
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
                "historical_evaluation_allowed": False,
                "orders_authorized": False,
            },
            indent=2,
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
