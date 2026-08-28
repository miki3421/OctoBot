"""Post-lock fee-neutral diagnostic for passive-execution V2.

The frozen stress multiplied maker and taker fees together, increasing their
relative differential from four to six basis points.  This audit removes only
that two-basis-point-per-fill benefit from the already sealed aggregate report.
It never reads the market database and cannot promote or place orders.
"""

from __future__ import annotations

import argparse
import json
import pathlib
import typing

from octobot.ai_strategy_lab import maker_execution_v1 as v1
from octobot.ai_strategy_lab import maker_execution_v2 as v2


SCHEMA_VERSION = 1
PROTOCOL_VERSION = "btc_futures_learned_passive_execution_postlock_fee_audit_v1"
SOURCE_REPORT_SHA256 = (
    "bd6c85f0091050b95a2e7dc17e23a9038d6b355b62d893a8fb105d0068219fee"
)


def extra_relative_fee_advantage_bps() -> float:
    primary = v1.TAKER_FEE_BPS - v1.MAKER_FEE_BPS
    stress = (
        v1.TAKER_FEE_BPS * v1.STRESS_FEE_MULTIPLIER
        - v1.MAKER_FEE_BPS * v1.STRESS_FEE_MULTIPLIER
    )
    return stress - primary


def _adjust(group: dict) -> dict:
    attempts = int(group["selected_attempts"])
    fills = int(group["maker_fills"])
    original_mean = float(group["mean_selected_saving_bps"])
    adjustment = (
        extra_relative_fee_advantage_bps() * fills / attempts
        if attempts
        else 0.0
    )
    adjusted_mean = original_mean - adjustment
    return {
        "selected_attempts": attempts,
        "maker_fills": fills,
        "frozen_stress_mean_saving_bps": original_mean,
        "fee_advantage_adjustment_bps_per_selected_attempt": adjustment,
        "fee_neutral_stress_mean_saving_bps": adjusted_mean,
        "strictly_positive": adjusted_mean > 0,
    }


def audit_report(source_report: dict) -> dict:
    if source_report.get("verdict") != (
        "LOCKED_PASS_EXECUTION_OVERLAY_SHADOW_ELIGIBLE"
    ):
        raise ValueError("locked execution source verdict differs")
    locked = source_report.get("locked_test", {})
    if locked.get("materialized") is not True:
        raise ValueError("locked execution source is not materialized")
    stress = locked["report"]["stress"]
    overall = _adjust(stress)
    by_side = {
        side: _adjust(stress["by_side"][side]) for side in ("buy", "sell")
    }
    return {
        "schema_version": SCHEMA_VERSION,
        "protocol_version": PROTOCOL_VERSION,
        "audit_timing": "post_lock_structural_diagnostic",
        "source_report_sha256": SOURCE_REPORT_SHA256,
        "new_market_rows_queried": False,
        "model_refit": False,
        "selection_changed": False,
        "orders_authorized": False,
        "paper_orders_authorized": False,
        "automatic_promotion": False,
        "calculation": {
            "primary_maker_taker_fee_differential_bps": (
                v1.TAKER_FEE_BPS - v1.MAKER_FEE_BPS
            ),
            "frozen_stress_maker_taker_fee_differential_bps": (
                v1.TAKER_FEE_BPS * v1.STRESS_FEE_MULTIPLIER
                - v1.MAKER_FEE_BPS * v1.STRESS_FEE_MULTIPLIER
            ),
            "extra_relative_fee_advantage_per_maker_fill_bps": (
                extra_relative_fee_advantage_bps()
            ),
            "identity": (
                "adjusted_mean = frozen_mean - extra_advantage * "
                "maker_fills / selected_attempts"
            ),
        },
        "fee_neutral_stress": {"overall": overall, "by_side": by_side},
        "finding": {
            "aggregate_stress_remains_positive": overall["strictly_positive"],
            "each_side_stress_remains_positive": all(
                value["strictly_positive"] for value in by_side.values()
            ),
            "primary_locked_pass_mutated": False,
            "per_side_stress_robustness_demonstrated": all(
                value["strictly_positive"] for value in by_side.values()
            ),
            "required_next_step": (
                "orderless forward shadow with separate buy and sell gates"
            ),
        },
    }


def evaluate(source_value, output_value) -> dict:
    source = pathlib.Path(source_value).resolve()
    output = pathlib.Path(output_value).resolve()
    if v2._sha256(source) != SOURCE_REPORT_SHA256:
        raise ValueError("locked execution report hash differs")
    result = audit_report(json.loads(source.read_text(encoding="utf-8")))
    payload = {**result, "content_sha256": v2._json_hash(result)}
    if output.is_file():
        if json.loads(output.read_text(encoding="utf-8")) != payload:
            raise ValueError("persisted fee-neutral audit differs")
        return payload
    v2._atomic_json(output, payload)
    return payload


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-report", required=True)
    parser.add_argument("--output", required=True)
    return parser


def main(argv: typing.Sequence[str] | None = None) -> int:
    arguments = _parser().parse_args(argv)
    print(
        json.dumps(
            evaluate(arguments.source_report, arguments.output),
            indent=2,
            sort_keys=True,
            allow_nan=False,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
