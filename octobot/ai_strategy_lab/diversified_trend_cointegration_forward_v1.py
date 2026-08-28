"""Frozen orderless forward protocol for the selected diversified model.

The historical selector chose one fixed-capital 50/50 combination of the
unchanged Trend V13 and Cointegration Pairs V2 sleeves.  Historical results
are training evidence only.  This module freezes the causal clock and the
promotion gate before the first official forward bar can be observed.

It cannot download market data, calculate a target, use credentials or place
an order.  A separate implementation lock must bind the executable observer
before any official forward record is accepted.
"""

from __future__ import annotations

import argparse
import datetime
import json
import os
import pathlib
import tempfile
import typing

from octobot.ai_strategy_lab import cointegration_pairs_v1 as common
from octobot.ai_strategy_lab import diversified_trend_cointegration_v1 as parent


SCHEMA_VERSION = 1
PROTOCOL_VERSION = "crypto_diversified_trend_cointegration_forward_v1"
PREREGISTERED_ON = "2026-08-28"

PARENT_PROTOCOL_SHA256 = (
    "36f7b0106d978099f3e3d850a38461fba6d9d6b75c5e366ffc66e854878fdcd9"
)
PARENT_PROTOCOL_FILE_SHA256 = (
    "5b40fa0706f6f1fe06dad25647b371df3abd29fe141ef4beeaa37410d3301e7b"
)
TRAINING_REPORT_SHA256 = (
    "d001af1c41879d04475def970a1ae84777a7c7ce17b6053f7ab1b1eaf715976a"
)
TRAINING_MANIFEST_SHA256 = (
    "379cf96b6b69da12e0cb9e6e10f2197f12f32a96387cafcb464a186d65959b72"
)
TRAINING_MANIFEST_CONTENT_SHA256 = (
    "440c856385e3d1ddfbea647b4c4f04fb5241643e2789a4f49499be3a5930f3bf"
)
TRAINING_TRAJECTORY_SHA256 = (
    "b9191b6082578de0638eb4f1a27f247e5ecef488313d6014e07a581f74e1199c"
)
SELECTED_MODEL_SHA256 = (
    "c191d1122d1c9031354aa55a0b5cb2fbf242efe7484e6265ca11681dbfb5fac2"
)
SELECTED_MODEL_CONTENT_SHA256 = (
    "f0fd009e4c401a2f907888439209f3513386941e08b9f27b310925aab77fc76b"
)

WARMUP_START = datetime.date(2026, 7, 2)
FORWARD_START = datetime.date(2026, 9, 1)
FORWARD_MINIMUM_CALENDAR_DAYS = 180
FORWARD_CUTOFF_EXCLUSIVE = FORWARD_START + datetime.timedelta(
    days=FORWARD_MINIMUM_CALENDAR_DAYS
)
DAILY_FINALIZATION_DELAY_MINUTES = 10


def frozen_protocol() -> dict:
    """Return the result-free forward protocol."""

    parent_gate = parent.frozen_protocol()["forward_gate"]
    if common._json_hash(parent.frozen_protocol()) != PARENT_PROTOCOL_SHA256:
        raise RuntimeError("parent diversified protocol source changed")
    return {
        "schema_version": SCHEMA_VERSION,
        "protocol_version": PROTOCOL_VERSION,
        "preregistered_on": PREREGISTERED_ON,
        "status": "result_free_forward_protocol_requires_implementation_lock",
        "research_only": True,
        "observation_only": True,
        "public_data_only": True,
        "credentials_used": False,
        "orders_authorized": False,
        "paper_orders_authorized": False,
        "automatic_promotion": False,
        "historical_results_are_training_only": True,
        "lineage": {
            "parent_protocol_sha256": PARENT_PROTOCOL_SHA256,
            "parent_protocol_file_sha256": PARENT_PROTOCOL_FILE_SHA256,
            "training_report_sha256": TRAINING_REPORT_SHA256,
            "training_manifest_sha256": TRAINING_MANIFEST_SHA256,
            "training_manifest_content_sha256": (
                TRAINING_MANIFEST_CONTENT_SHA256
            ),
            "training_trajectory_sha256": TRAINING_TRAJECTORY_SHA256,
            "selected_model_sha256": SELECTED_MODEL_SHA256,
            "selected_model_content_sha256": (
                SELECTED_MODEL_CONTENT_SHA256
            ),
            "selected_configuration_id": "trend50_cointegration50",
            "trend_capital_weight": 0.5,
            "cointegration_capital_weight": 0.5,
            "component_lineage": parent.frozen_protocol()["lineage"],
        },
        "timeline": {
            "warmup_start_bar_utc": WARMUP_START.isoformat(),
            "warmup_end_exclusive_bar_utc": FORWARD_START.isoformat(),
            "warmup_is_never_an_economic_outcome": True,
            "official_first_bar_open_utc": (
                f"{FORWARD_START.isoformat()}T00:00:00+00:00"
            ),
            "official_first_decision_not_before_utc": (
                "2026-09-02T00:10:00+00:00"
            ),
            "official_first_return_bearing_bar": "2026-09-02",
            "minimum_calendar_days": FORWARD_MINIMUM_CALENDAR_DAYS,
            "earliest_gate_cutoff_exclusive_bar": (
                FORWARD_CUTOFF_EXCLUSIVE.isoformat()
            ),
            "earliest_gate_evaluation_not_before_utc": (
                f"{FORWARD_CUTOFF_EXCLUSIVE.isoformat()}T00:10:00+00:00"
            ),
            "daily_finalization_delay_minutes": (
                DAILY_FINALIZATION_DELAY_MINUTES
            ),
        },
        "causal_clock": {
            "bar_identifier": "UTC daily kline open date",
            "kline_close_timestamp": (
                "next UTC midnight minus one millisecond"
            ),
            "bar_data_available_only_after_next_utc_midnight": True,
            "target_calculated_after_bar_close": True,
            "target_applies_to_next_daily_price_return": True,
            "transaction_cost_charged_on_target_decision_bar": True,
            "first_forward_bar_price_return_uses_flat_start": True,
            "first_forward_bar_may_contain_only_opening_cost": True,
            "funding_assignment": (
                "a funding settlement belongs to UTC date(timestamp-1ms)"
            ),
            "funding_window_for_bar": "(bar_open, next_bar_open]",
            "same_bar_or_future_close_cannot_enter_earlier_decision": True,
        },
        "market_evidence": {
            "venue": "Binance USD-M public futures API",
            "approved_hosts": ["fapi.binance.com"],
            "approved_https_get_paths": [
                "/fapi/v1/klines",
                "/fapi/v1/fundingRate",
            ],
            "daily_kline_interval": "1d",
            "frozen_universe_assets": 120,
            "universe_bound_by_source_snapshot_bundle_sha256": (
                parent.SOURCE_SNAPSHOT_BUNDLE_SHA256
            ),
            "history_bound_by_bundle_sha256": parent.HISTORY_BUNDLE_SHA256,
            "history_last_bar": "2026-07-01",
            "warmup_and_forward_sources_identical": True,
            "complete_close_for_every_frozen_symbol_required": True,
            "finite_positive_close_required": True,
            "at_least_one_funding_settlement_per_symbol_day_required": True,
            "raw_responses_content_addressed_and_gzip_compressed": True,
            "normalized_daily_records_hash_chained": True,
            "missing_days_must_be_backfilled_not_interpolated": True,
            "delisted_or_unavailable_required_symbol_fails_closed": True,
            "private_api_headers_or_parameters_forbidden": True,
        },
        "strategy_execution": {
            "initial_state": "both sleeves flat at official first bar",
            "trend": {
                "configuration": "risk_budgeted_bear_regime_v13",
                "first_scheduled_rebalance": "official first bar close",
                "subsequent_rebalance_spacing_days": 7,
                "implementation_reused_without_parameter_change": True,
                "position_applies_from_following_bar": True,
            },
            "cointegration": {
                "configuration": (
                    "crypto_futures_expanded_cointegration_pairs_v2"
                ),
                "rolling_formation_is_prescribed_not_hyperparameter_refit": (
                    True
                ),
                "formation_lookback_days": 180,
                "formation_schedule": "every UTC calendar day with day == 1",
                "formation_includes_current_closed_bar": True,
                "existing_pairs_closed_at_monthly_formation_close": True,
                "new_pair_target_applies_from_following_bar": True,
                "both_spread_directions_retained": True,
                "maximum_pairs": 4,
                "entry_absolute_z": 2.0,
                "exit_absolute_z": 0.5,
                "stop_absolute_z": 4.0,
            },
            "cost_multipliers": [1.0, 3.0],
            "funding_included": True,
            "fixed_initial_sleeve_budgets": True,
            "sleeve_equities_compound_independently": True,
            "capital_weights_drift_after_initial_allocation": True,
            "daily_cross_sleeve_rebalance": False,
            "cross_sleeve_netting": False,
            "extra_leverage": False,
            "no_refit_reselection_or_threshold_change": True,
        },
        "daily_observer": {
            "recompute_from_frozen_initial_state": True,
            "append_only_decision_journal": True,
            "decision_payload_content_addressed": True,
            "prior_decision_hashes_must_reproduce_exactly": True,
            "one_payload_per_complete_official_bar": True,
            "targets_are_research_observations_not_orders": True,
            "no_exchange_or_simulator_order_adapter": True,
            "health_report_cannot_promote": True,
        },
        "official_cutoff_accounting": {
            "observer_does_not_liquidate_positions_daily": True,
            "trend_marked_to_market_without_terminal_liquidation": True,
            "cointegration_terminal_liquidation_cost_applied_once_at_gate": True,
            "reason": (
                "match the frozen training component accounting at the one "
                "official gate cutoff without contaminating daily targets"
            ),
            "no_post_cutoff_outcome_used": True,
        },
        "forward_gate": dict(parent_gate),
        "data_quality_additions": {
            "complete_contiguous_calendar_panel_required_before_gate": True,
            "minimum_observed_days_is_retained_from_parent": (
                parent_gate["minimum_observed_days"]
            ),
            "protocol_file_and_implementation_lock_hashes_must_match": True,
            "single_official_gate_run": True,
            "gate_may_run_only_after_cutoff_and_maturity": True,
        },
        "implementation_lock": {
            "required_before_first_official_record": True,
            "must_bind_protocol_selected_model_training_inputs_sources_tests": (
                True
            ),
            "source_change_after_lock_fails_closed": True,
            "may_be_created_before_official_start_only": True,
        },
        "promotion_consequence": (
            "a complete PASS permits only manual review for guarded paper; "
            "it never authorizes an order or live trading"
        ),
        "results": None,
    }


def protocol_payload() -> dict:
    frozen = frozen_protocol()
    return {**frozen, "protocol_sha256": common._json_hash(frozen)}


def load_and_verify_protocol(
    path_value: typing.Union[str, pathlib.Path],
) -> dict:
    path = pathlib.Path(path_value).resolve()
    persisted = json.loads(path.read_text(encoding="utf-8"))
    expected = protocol_payload()
    if persisted != expected:
        raise ValueError("persisted diversified forward protocol differs")
    return persisted


def write_or_verify_protocol(
    path_value: typing.Union[str, pathlib.Path],
) -> dict:
    """Write the protocol atomically once, or verify its exact identity."""

    path = pathlib.Path(path_value).resolve()
    expected = protocol_payload()
    if path.is_file():
        return load_and_verify_protocol(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(
        prefix=f".{path.name}.", suffix=".tmp", dir=str(path.parent)
    )
    temporary = pathlib.Path(temporary_name)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
            json.dump(expected, stream, indent=2, sort_keys=True)
            stream.write("\n")
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    finally:
        if temporary.exists():
            temporary.unlink()
    return expected


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--protocol", required=True)
    return parser


def main(argv: typing.Optional[list[str]] = None) -> int:
    arguments = _parser().parse_args(argv)
    payload = write_or_verify_protocol(arguments.protocol)
    print(json.dumps(payload, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
