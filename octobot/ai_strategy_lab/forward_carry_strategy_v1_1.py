"""Result-free feasibility correction for forward Carry V1.

V1 is preserved byte-for-byte.  V1.1 changes only the impossible development
trade-count gate and makes the already fixed confirmation end explicit.  No
economic outcome was read before this correction was frozen.
"""

from __future__ import annotations

import argparse
import copy
import json
import pathlib
import typing

from octobot.ai_strategy_lab import forward_carry_strategy_v1 as v1


SCHEMA_VERSION = 1
PROTOCOL_VERSION = "kucoin_spot_perpetual_forward_carry_v1_1"
PARENT_PROTOCOL_SHA256 = (
    "52fe792f3c5b3e0983ed265ca58aa59c4c1d5931caab4f59eecc03dbe1d39836"
)
MAXIMUM_DEVELOPMENT_CLOSED_PAIRS = 10
MINIMUM_DEVELOPMENT_CLOSED_PAIRS = 8


def frozen_protocol() -> dict:
    """Return V1.1 while leaving the original V1 protocol unchanged."""
    protocol = copy.deepcopy(v1.frozen_protocol())
    protocol["protocol_version"] = PROTOCOL_VERSION
    protocol["status"] = "result_free_preregistered_feasibility_correction"
    protocol["correction"] = {
        "parent_protocol_version": v1.PROTOCOL_VERSION,
        "parent_protocol_sha256": PARENT_PROTOCOL_SHA256,
        "parent_preserved": True,
        "economic_outcomes_read": False,
        "discovered_during_evaluator_implementation": True,
        "reason": (
            "Two continuous seven-day out-of-sample windows, a 168-hour "
            "holding period and five portfolio slots permit at most ten "
            "closed pairs, so the V1 minimum of fifteen was unreachable."
        ),
        "maximum_possible_development_closed_pairs": (
            MAXIMUM_DEVELOPMENT_CLOSED_PAIRS
        ),
        "old_minimum_development_closed_pairs": 15,
        "new_minimum_development_closed_pairs": (
            MINIMUM_DEVELOPMENT_CLOSED_PAIRS
        ),
        "other_candidate_parameters_changed": False,
    }
    protocol["development_gate"]["minimum_closed_pairs"] = (
        MINIMUM_DEVELOPMENT_CLOSED_PAIRS
    )
    confirmation = protocol["validation"]["locked_confirmation"]
    confirmation["entry_end_exclusive_utc"] = confirmation.pop(
        "entry_end_not_before_utc"
    )
    confirmation["entry_window_is_fixed"] = True
    protocol["results"] = None
    return protocol


def write_or_verify_protocol(
    path_value: typing.Union[str, pathlib.Path],
) -> dict:
    """Persist V1.1 atomically or reject any change to its content."""
    path = pathlib.Path(path_value).resolve()
    protocol = frozen_protocol()
    payload = {**protocol, "protocol_sha256": v1._json_hash(protocol)}
    if path.is_file():
        persisted = json.loads(path.read_text(encoding="utf-8"))
        if persisted != payload:
            raise ValueError("persisted forward Carry V1.1 protocol differs")
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
                "parent_protocol_sha256": PARENT_PROTOCOL_SHA256,
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
