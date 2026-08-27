"""Result-free preregistration for KuCoin spot/perpetual Carry V1.

The protocol deliberately contains no market outcome.  It freezes one
research-only long-spot/short-perpetual hypothesis before the forward evidence
is ready, and it cannot create paper or real orders.
"""

from __future__ import annotations

import argparse
import datetime
import hashlib
import json
import pathlib
import typing

from octobot.ai_strategy_lab import forward_carry_dataset


SCHEMA_VERSION = 1
PROTOCOL_VERSION = "kucoin_spot_perpetual_forward_carry_v1"
PREREGISTERED_ON = "2026-08-27"
PREREGISTRATION_CUTOFF_UTC = datetime.datetime(
    2026, 8, 27, 12, 0, tzinfo=datetime.timezone.utc
)
PRIMARY_HORIZON_HOURS = 168
DIAGNOSTIC_HORIZON_HOURS = (8, 24)
DEVELOPMENT_ENTRY_END_UTC = (
    PREREGISTRATION_CUTOFF_UTC
    - datetime.timedelta(hours=PRIMARY_HORIZON_HOURS)
)
CONFIRMATION_ENTRY_DAYS = 30
CONFIRMATION_ENTRY_END_UTC = (
    PREREGISTRATION_CUTOFF_UTC
    + datetime.timedelta(days=CONFIRMATION_ENTRY_DAYS)
)
EARLIEST_CONFIRMATION_OPEN_UTC = (
    CONFIRMATION_ENTRY_END_UTC
    + datetime.timedelta(hours=PRIMARY_HORIZON_HOURS)
)
LEG_QUOTE_USDT = 1_000
INITIAL_CAPITAL_USDT = 10_000
MAXIMUM_CONCURRENT_PAIRS = 5
MINIMUM_PREDICTED_NET_RETURN = 0.001
MINIMUM_ENTRY_CAPACITY_USDT = 3_000
RIDGE_ALPHA = 10.0


def _iso(value: datetime.datetime) -> str:
    return value.isoformat()


def _json_hash(value: object) -> str:
    return hashlib.sha256(
        json.dumps(value, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()


def frozen_protocol() -> dict:
    """Return the immutable Carry V1 protocol without any result."""
    return {
        "schema_version": SCHEMA_VERSION,
        "protocol_version": PROTOCOL_VERSION,
        "preregistered_on": PREREGISTERED_ON,
        "preregistration_cutoff_utc": _iso(
            PREREGISTRATION_CUTOFF_UTC
        ),
        "status": "result_free_preregistered_design",
        "research_only": True,
        "public_data_only": True,
        "credentials_used": False,
        "orders_authorized": False,
        "paper_orders_authorized": False,
        "real_income_authorized": False,
        "automatic_promotion": False,
        "hypothesis": {
            "name": "positive_funding_and_basis_persistence",
            "statement": (
                "Across liquid KuCoin pairs, a small fixed ridge model using "
                "only point-in-time funding, executable basis, liquidity and "
                "open-interest features can identify long-spot/short-"
                "perpetual positions whose 168-hour net return remains "
                "positive after four conservative taker fees."
            ),
            "direction": "long spot and short USDT perpetual only",
            "reverse_carry_allowed": False,
            "reason_reverse_is_excluded": (
                "short-spot borrow availability, borrow cost and recalls are "
                "not present in the forward observer"
            ),
            "selection_candidates": 1,
        },
        "source": {
            "observer_protocol": "kucoin_forward_microstructure_v1",
            "journal": "/shadow/market/microstructure.jsonl",
            "evidence": "/shadow/market/evidence.json",
            "first_complete_schema_bucket_utc": (
                "2026-07-23T12:45:00+00:00"
            ),
            "expected_symbols": 19,
            "minimum_span_days": 60,
            "minimum_coverage": 0.95,
            "maximum_gap_minutes": 60,
            "minimum_settled_funding_points_per_symbol": 171,
            "journal_hash_must_match_evidence": True,
            "archive_chain_must_be_consistent": True,
            "readiness_must_be_recomputed": True,
        },
        "dataset": {
            "builder": "forward_carry_dataset",
            "schema_version": (
                forward_carry_dataset.DATASET_SCHEMA_VERSION
            ),
            "feature_names": list(forward_carry_dataset.FEATURE_NAMES),
            "feature_schema_sha256": _json_hash(
                list(forward_carry_dataset.FEATURE_NAMES)
            ),
            "leg_quote_usdt": LEG_QUOTE_USDT,
            "paired_gross_capital_usdt": 2 * LEG_QUOTE_USDT,
            "primary_horizon_hours": PRIMARY_HORIZON_HOURS,
            "diagnostic_horizons_hours": list(
                DIAGNOSTIC_HORIZON_HOURS
            ),
            "diagnostic_horizons_can_select_candidate": False,
            "exact_exit_bucket_required": True,
            "interpolation_allowed": False,
            "mid_price_fill_assumed": False,
            "maximum_excluded_future_exit_fraction": 0.01,
            "outcome_identity": (
                "net = 0.5 * (spot + futures + settled funding) - "
                "four conservative taker fees"
            ),
        },
        "candidate": {
            "decision_times_utc": ["00:15", "08:15", "16:15"],
            "eligibility": {
                "current_funding_rate_strictly_positive": True,
                "predicted_funding_non_negative_when_available": True,
                "minimum_entry_capacity_usdt": (
                    MINIMUM_ENTRY_CAPACITY_USDT
                ),
                "minimum_instant_exit_capacity_usdt": (
                    MINIMUM_ENTRY_CAPACITY_USDT
                ),
                "future_exit_information_used": False,
            },
            "model": {
                "type": "ridge_regression",
                "target": "168-hour net_pair_return",
                "alpha": RIDGE_ALPHA,
                "fit_intercept": True,
                "symbol_identity_feature": False,
                "hyperparameter_search": False,
                "feature_selection": False,
                "log1p_features": [
                    "entry_capacity_usdt_depth20",
                    "instant_exit_capacity_usdt_depth20",
                    "open_interest_quote",
                ],
                "winsorization": (
                    "training-only 1st/99th percentiles; apply frozen bounds "
                    "to validation"
                ),
                "scaling": (
                    "training-only median/IQR; replace zero IQR with one"
                ),
                "random_seed": 20_260_827,
            },
            "entry_gate": {
                "minimum_predicted_net_return": (
                    MINIMUM_PREDICTED_NET_RETURN
                ),
                "interpretation": (
                    "10 basis points above all modeled execution costs"
                ),
            },
            "portfolio": {
                "initial_capital_usdt": INITIAL_CAPITAL_USDT,
                "fixed_leg_quote_usdt": LEG_QUOTE_USDT,
                "maximum_concurrent_pairs": MAXIMUM_CONCURRENT_PAIRS,
                "maximum_gross_exposure": 1.0,
                "full_futures_notional_reserved": True,
                "compounding": False,
                "same_symbol_overlap": False,
                "holding_period_hours": PRIMARY_HORIZON_HOURS,
                "early_exit": False,
                "ranking": "descending predicted net return",
                "tie_break": "lexicographic base symbol",
                "mark_to_market": (
                    "every 15 minutes using executable unwind VWAP, accrued "
                    "settled funding and exit fees"
                ),
            },
        },
        "validation": {
            "purge_embargo_hours": PRIMARY_HORIZON_HOURS,
            "development": {
                "last_entry_exclusive_utc": _iso(
                    DEVELOPMENT_ENTRY_END_UTC
                ),
                "all_labels_mature_by_utc": _iso(
                    PREREGISTRATION_CUTOFF_UTC
                ),
                "diagnostic_reuse": True,
                "walk_forward_folds": [
                    {
                        "test_start_utc": "2026-08-06T12:00:00+00:00",
                        "test_end_exclusive_utc": (
                            "2026-08-13T12:00:00+00:00"
                        ),
                        "training_entry_end_exclusive_utc": (
                            "2026-07-30T12:00:00+00:00"
                        ),
                    },
                    {
                        "test_start_utc": "2026-08-13T12:00:00+00:00",
                        "test_end_exclusive_utc": (
                            "2026-08-20T12:00:00+00:00"
                        ),
                        "training_entry_end_exclusive_utc": (
                            "2026-08-06T12:00:00+00:00"
                        ),
                    },
                ],
                "final_fit_entry_end_exclusive_utc": _iso(
                    DEVELOPMENT_ENTRY_END_UTC
                ),
            },
            "locked_confirmation": {
                "entry_start_utc": _iso(
                    PREREGISTRATION_CUTOFF_UTC
                ),
                "minimum_entry_span_days": CONFIRMATION_ENTRY_DAYS,
                "entry_end_not_before_utc": _iso(
                    CONFIRMATION_ENTRY_END_UTC
                ),
                "earliest_open_utc": _iso(
                    EARLIEST_CONFIRMATION_OPEN_UTC
                ),
                "development_gate_must_pass_first": True,
                "development_model_sha256_must_be_frozen": True,
                "refit_on_confirmation": False,
                "confirmation_outcomes_must_remain_unread": True,
            },
            "leave_one_symbol_out": {
                "refit_without_held_out_symbol": True,
                "parameters_unchanged": True,
                "minimum_non_negative_omissions": 12,
                "total_omissions": 19,
            },
        },
        "benchmarks": {
            "cash": "zero return",
            "structural_carry": (
                "same eligibility and portfolio rules, ranked only by "
                "current funding rate; diagnostic and not promotable"
            ),
        },
        "cost_and_execution_stress": {
            "primary": "recorded VWAP plus four conservative taker fees",
            "stress_fee_multiplier": 2.0,
            "stress_entry_delay_minutes": 15,
            "stress_exit_delay_minutes": 15,
            "stress_must_remain_positive": True,
            "maker_fill_assumptions": False,
        },
        "development_gate": {
            "minimum_closed_pairs": 15,
            "total_return_strictly_positive": True,
            "minimum_profit_factor": 1.25,
            "minimum_win_rate": 0.55,
            "maximum_mark_to_market_drawdown": 0.05,
            "minimum_positive_operating_weeks": 0.60,
            "positive_walk_forward_folds_required": 2,
            "minimum_selected_symbols": 4,
            "maximum_single_symbol_trade_fraction": 0.50,
            "maximum_single_symbol_gross_profit_fraction": 0.60,
            "return_not_below_structural_benchmark": True,
            "drawdown_not_above_structural_benchmark": True,
            "minimum_stress_profit_factor": 1.05,
            "stress_total_return_strictly_positive": True,
            "leave_one_symbol_out_gate_must_pass": True,
        },
        "confirmation_gate": {
            "minimum_entry_span_days": CONFIRMATION_ENTRY_DAYS,
            "minimum_closed_pairs": 15,
            "total_return_strictly_positive": True,
            "minimum_profit_factor": 1.20,
            "minimum_win_rate": 0.52,
            "maximum_mark_to_market_drawdown": 0.05,
            "minimum_positive_operating_weeks": 0.50,
            "minimum_selected_symbols": 4,
            "minimum_stress_profit_factor": 1.00,
            "stress_total_return_non_negative": True,
            "missing_forward_intervals": 0,
        },
        "evidence_policy": {
            "multiple_testing_disclosure": (
                "one primary horizon, one fixed model, one prediction "
                "threshold and one portfolio policy"
            ),
            "parameter_change_creates_new_version": True,
            "failed_development_keeps_confirmation_sealed": True,
            "complete_pass_consequence": (
                "manual approval of an orderless shadow for at least 90 "
                "additional days"
            ),
            "paper_or_real_trading_consequence": False,
        },
        "known_unmodeled_risks": [
            "spot/perpetual legging risk",
            "exchange default or withdrawal suspension",
            "perpetual margin and liquidation mechanics",
            "spot custody and transfer constraints",
            "fees or contract specifications changing after observation",
        ],
        "results": None,
    }


def write_or_verify_protocol(
    path_value: typing.Union[str, pathlib.Path],
) -> dict:
    """Persist the content-addressed protocol or reject any mutation."""
    path = pathlib.Path(path_value).resolve()
    protocol = frozen_protocol()
    payload = {**protocol, "protocol_sha256": _json_hash(protocol)}
    if path.is_file():
        persisted = json.loads(path.read_text(encoding="utf-8"))
        if persisted != payload:
            raise ValueError("persisted forward Carry V1 protocol differs")
        return persisted
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(
        json.dumps(payload, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    temporary.replace(path)
    return payload


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", required=True)
    return parser.parse_args()


def main() -> int:
    arguments = _parse_args()
    payload = write_or_verify_protocol(arguments.output)
    print(
        json.dumps(
            {
                "protocol_path": str(pathlib.Path(arguments.output).resolve()),
                "protocol_sha256": payload["protocol_sha256"],
                "results": payload["results"],
                "orders_authorized": payload["orders_authorized"],
            },
            indent=2,
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
