"""Audit a relative-direction V5 veto over deterministic BTC decisions.

This V2 keeps the V1 data, execution and economic gates unchanged. The only
pre-registered change is that a veto does not require V5's autonomous-entry
threshold: it requires agreement with V5's preferred direction and the frozen
0.03 percentage-point expected-value margin. It remains research-only.
"""

from __future__ import annotations

import argparse
import datetime
import json
import pathlib
import typing

import numpy

from octobot.ai_strategy_lab import deterministic_v5_veto as v1_veto
from octobot.ai_strategy_lab import perfect_map_student_v5 as v5


SCHEMA_VERSION = 1
PROTOCOL_VERSION = "btc_deterministic_v5_direction_veto_v2"
PREREGISTRATION_DATE = "2026-07-28"


def frozen_protocol() -> dict:
    return {
        "schema_version": SCHEMA_VERSION,
        "protocol_version": PROTOCOL_VERSION,
        "preregistered_on": PREREGISTRATION_DATE,
        "status": "preregistered_design_only",
        "research_only": True,
        "diagnostic_reuse": True,
        "orders_authorized": False,
        "paper_orders_authorized": False,
        "automatic_promotion": False,
        "unchanged_from_v1": {
            "candidate_source": v1_veto.frozen_protocol()[
                "candidate_source"
            ],
            "primary_comparison": v1_veto.frozen_protocol()[
                "primary_comparison"
            ],
            "evidence": v1_veto.frozen_protocol()["evidence"],
            "gate_for_more_forward_observation": (
                v1_veto.frozen_protocol()[
                    "gate_for_more_forward_observation"
                ]
            ),
        },
        "single_change": {
            "v5_model": v5.PROTOCOL_VERSION,
            "same_direction_required": True,
            "minimum_relative_direction_margin_pct": (
                v1_veto.V5_DIRECTION_MARGIN_PCT
            ),
            "absolute_expected_net_threshold_required": False,
            "negative_values_can_create_signal": False,
            "interpretation": (
                "relative directional preference may only veto the recorded "
                "baseline action"
            ),
            "missing_or_invalid_input": "reject_entry_fail_closed",
        },
        "evidence_policy": {
            "all_dates_are_reused_or_short_initial_forward": True,
            "no_result_can_promote_to_shadow_or_paper": True,
            "margin_cannot_be_retuned_after_results": True,
            "new_forward_days_required": 30,
        },
        "implementation": {
            "protocol_file_required_before_audit": True,
            "persist_input_and_model_hashes": True,
            "persist_candidates_trades_and_report": True,
            "reloaded_v5_predictions_must_match_exactly": True,
            "results_in_this_protocol": False,
        },
    }


def write_protocol(
    output_value: typing.Union[str, pathlib.Path],
) -> pathlib.Path:
    output = pathlib.Path(output_value).resolve()
    output.mkdir(parents=True, exist_ok=True)
    protocol = frozen_protocol()
    path = output / "protocol.json"
    path.write_text(
        json.dumps(
            {
                **protocol,
                "protocol_sha256": v1_veto._json_hash(protocol),
            },
            indent=2,
            sort_keys=True,
        )
        + "\n",
        encoding="utf-8",
    )
    return path


def _verify_protocol(output: pathlib.Path) -> dict:
    path = output / "protocol.json"
    if not path.is_file():
        raise FileNotFoundError(
            "write protocol.json before running direction-veto V2"
        )
    expected = frozen_protocol()
    persisted = json.loads(path.read_text(encoding="utf-8"))
    if persisted.get("protocol_sha256") != v1_veto._json_hash(expected):
        raise ValueError("persisted direction-veto protocol hash differs")
    without_hash = {
        key: value
        for key, value in persisted.items()
        if key != "protocol_sha256"
    }
    if without_hash != expected:
        raise ValueError("persisted direction-veto protocol content differs")
    return persisted


def direction_veto_decision(
    *,
    direction: str,
    long_expected_net_pct: float,
    short_expected_net_pct: float,
) -> tuple[bool, str, str, float, float]:
    scores = {
        v5.DIRECTIONS[0]: float(long_expected_net_pct),
        v5.DIRECTIONS[1]: float(short_expected_net_pct),
    }
    if not all(numpy.isfinite(value) for value in scores.values()):
        return (
            False,
            "non_finite_v5_score",
            "NONE",
            float("nan"),
            float("nan"),
        )
    preferred = max(scores, key=scores.get)
    opposite_direction = (
        v5.DIRECTIONS[1]
        if direction == v5.DIRECTIONS[0]
        else v5.DIRECTIONS[0]
    )
    selected = scores[direction]
    margin = selected - scores[opposite_direction]
    if preferred != direction:
        return (
            False,
            "v5_prefers_opposite_direction",
            preferred,
            selected,
            margin,
        )
    if margin < v1_veto.V5_DIRECTION_MARGIN_PCT:
        return (
            False,
            "v5_direction_margin_below_threshold",
            preferred,
            selected,
            margin,
        )
    return True, "allowed", preferred, selected, margin


def run_audit(
    *,
    decision_db: typing.Union[str, pathlib.Path],
    collector: typing.Union[str, pathlib.Path],
    v5_model_directory: typing.Union[str, pathlib.Path],
    output_directory: typing.Union[str, pathlib.Path],
    funding_path: typing.Optional[
        typing.Union[str, pathlib.Path]
    ] = None,
) -> dict:
    result = v1_veto.run_audit(
        decision_db=decision_db,
        collector=collector,
        v5_model_directory=v5_model_directory,
        output_directory=output_directory,
        funding_path=funding_path,
        protocol_version=PROTOCOL_VERSION,
        protocol_verifier=_verify_protocol,
        veto_function=direction_veto_decision,
    )
    result["relative_direction_only"] = True
    return result


def main(argv: typing.Optional[list[str]] = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--decision-db")
    parser.add_argument("--collector")
    parser.add_argument("--funding")
    parser.add_argument("--v5-model")
    parser.add_argument("--output", required=True)
    parser.add_argument("--write-protocol", action="store_true")
    args = parser.parse_args(argv)
    if args.write_protocol:
        path = write_protocol(args.output)
        print(json.dumps({"protocol": str(path)}, indent=2))
        return 0
    required = {
        "--decision-db": args.decision_db,
        "--collector": args.collector,
        "--v5-model": args.v5_model,
    }
    missing = [name for name, value in required.items() if not value]
    if missing:
        parser.error(f"missing required arguments: {', '.join(missing)}")
    result = run_audit(
        decision_db=args.decision_db,
        collector=args.collector,
        funding_path=args.funding,
        v5_model_directory=args.v5_model,
        output_directory=args.output,
    )
    print(
        json.dumps(
            {
                "report": result["report_path"],
                "gate": result["gate_for_more_forward_observation"],
                "metrics": result["metrics"],
                "crash_case": result["crash_case"],
                "created_at": datetime.datetime.now(
                    datetime.timezone.utc
                ).isoformat(),
            },
            indent=2,
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
