"""Append-only, no-order journal for trend portfolio shadow snapshots."""

from __future__ import annotations

import datetime
import hashlib
import json
import pathlib
import typing


SHADOW_SCHEMA_VERSION = 3


def record_trend_shadow(
    trend_report_path: typing.Union[str, pathlib.Path],
    strategy_name: str,
    journal_path: typing.Union[str, pathlib.Path],
) -> dict:
    source = pathlib.Path(trend_report_path).resolve()
    journal = pathlib.Path(journal_path).resolve()
    data = json.loads(source.read_text(encoding="utf-8"))
    if not data.get("research_only"):
        raise ValueError("trend report is not marked research_only")
    try:
        report = data["reports"][strategy_name]
    except KeyError as error:
        raise ValueError(
            f"trend report does not contain strategy {strategy_name}"
        ) from error
    required = (
        "ending_weights",
        "latest_rebalance_target_weights",
        "latest_signal",
        "evaluation_end_date",
        "days_until_next_rebalance",
    )
    missing = [key for key in required if key not in report]
    if missing:
        raise ValueError(f"trend report lacks shadow fields: {missing}")

    source_sha256 = _sha256(source)
    identity = f"{strategy_name}:{report['evaluation_end_date']}"
    runner = data.get("shadow_runner", {})
    applied_weights = report.get(
        "shadow_applied_weights",
        report["latest_rebalance_target_weights"],
    )
    record = {
        "schema_version": SHADOW_SCHEMA_VERSION,
        "recorded_at": datetime.datetime.now(
            datetime.timezone.utc
        ).isoformat(),
        "mode": "shadow_only",
        "orders_authorized": False,
        "strategy_name": strategy_name,
        "identity": identity,
        "source": {
            "path": str(source),
            "sha256": source_sha256,
        },
        "market_end_date": report["evaluation_end_date"],
        "days_until_next_rebalance": report[
            "days_until_next_rebalance"
        ],
        "signals": report["latest_signal"],
        "ending_weights": report["ending_weights"],
        "candidate_target_weights": report[
            "latest_rebalance_target_weights"
        ],
        "target_weights": applied_weights,
        "latest_close": report.get("latest_close"),
        "latest_daily_funding": report.get("latest_daily_funding"),
        "rebalance_weekday_utc": runner.get("rebalance_weekday_utc"),
        "rebalance_due": runner.get("rebalance_due"),
        "initialized": runner.get("initialized"),
        "cost_per_turnover": runner.get("cost_per_turnover"),
        "cost_per_turnover_by_instrument": runner.get(
            "cost_per_turnover_by_instrument"
        ),
        "target_gross_exposure": sum(
            abs(float(value))
            for value in applied_weights.values()
        ),
        "target_net_exposure": sum(
            float(value) for value in applied_weights.values()
        ),
    }
    record["record_sha256"] = hashlib.sha256(
        json.dumps(record, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()

    journal.parent.mkdir(parents=True, exist_ok=True)
    if journal.exists():
        for line_number, raw_line in enumerate(
            journal.read_text(encoding="utf-8").splitlines(), start=1
        ):
            try:
                existing = json.loads(raw_line)
            except json.JSONDecodeError as error:
                raise ValueError(
                    f"invalid shadow journal line {line_number}"
                ) from error
            if existing.get("identity") == identity:
                if (
                    existing.get("target_weights")
                    != record["target_weights"]
                    or existing.get("candidate_target_weights")
                    != record["candidate_target_weights"]
                    or existing.get("signals") != record["signals"]
                ):
                    raise ValueError(
                        "conflicting shadow snapshot for strategy and market date"
                    )
                return {"appended": False, "record": existing}
    with journal.open("a", encoding="utf-8") as stream:
        stream.write(json.dumps(record, sort_keys=True) + "\n")
    return {"appended": True, "record": record}


def load_shadow_records(
    journal_path: typing.Union[str, pathlib.Path],
) -> list[dict]:
    journal = pathlib.Path(journal_path).resolve()
    if not journal.exists():
        return []
    result = []
    for line_number, raw_line in enumerate(
        journal.read_text(encoding="utf-8").splitlines(), start=1
    ):
        try:
            record = json.loads(raw_line)
        except json.JSONDecodeError as error:
            raise ValueError(
                f"invalid shadow journal line {line_number}"
            ) from error
        if not isinstance(record, dict) or not record.get("market_end_date"):
            raise ValueError(f"invalid shadow record line {line_number}")
        result.append(record)
    return result


def _sha256(path):
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()
