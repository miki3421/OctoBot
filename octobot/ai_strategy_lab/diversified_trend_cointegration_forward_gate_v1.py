"""Frozen single-run gate for the diversified forward experiment.

This evaluator is intentionally separate from the daily observer.  It can
verify readiness at any time, but it refuses to calculate or persist economic
results before the frozen cutoff.  After the cutoff it replays every public
market record and research decision, applies the original component period-end
accounting, and emits exactly one immutable PASS/FAIL report.

Neither PASS nor any other command in this module can create an exchange or
paper order.  PASS only permits a later, manual guarded-paper review.
"""

from __future__ import annotations

import argparse
import dataclasses
import datetime
import hashlib
import json
import math
import os
import pathlib
import shutil
import tempfile
import typing

import numpy

from octobot.ai_strategy_lab import cointegration_pairs_v1 as common
from octobot.ai_strategy_lab import cointegration_pairs_v2_research as pairs
from octobot.ai_strategy_lab import (
    diversified_trend_cointegration_forward_runner as observer,
)
from octobot.ai_strategy_lab import (
    diversified_trend_cointegration_forward_v1 as forward_protocol,
)


SCHEMA_VERSION = 1
GATE_VERSION = "crypto_diversified_trend_cointegration_forward_gate_v1"
PREREGISTERED_ON = "2026-08-28"
UTC = datetime.timezone.utc

FORWARD_PROTOCOL_SHA256 = (
    "c2d1abbc716a4775d6cdac15774613f657009adab55984189bf2f2b1dc42e010"
)
FORWARD_PROTOCOL_FILE_SHA256 = (
    "4b46004584f352230339afccfc8c2c950d72ddbd5b126a82fe159483830cb616"
)
OBSERVER_IMPLEMENTATION_LOCK_SHA256 = (
    "9b3bda6f2771d55aa1d66b1c9148eec3feb222d50f70d7d47678eba7e7279de4"
)
OBSERVER_IMPLEMENTATION_LOCK_FILE_SHA256 = (
    "81b1a954c106e0ad8011a2686312e340acc0f6dc2f2477bbab786306fa52a0f2"
)

OFFICIAL_START = forward_protocol.FORWARD_START
OFFICIAL_END_EXCLUSIVE = forward_protocol.FORWARD_CUTOFF_EXCLUSIVE
OFFICIAL_DAYS = (OFFICIAL_END_EXCLUSIVE - OFFICIAL_START).days
WARMUP_DAYS = (OFFICIAL_START - forward_protocol.WARMUP_START).days
EVALUATION_NOT_BEFORE = datetime.datetime.combine(
    OFFICIAL_END_EXCLUSIVE,
    datetime.time(
        minute=forward_protocol.DAILY_FINALIZATION_DELAY_MINUTES,
        tzinfo=UTC,
    ),
)


class GateNotReadyError(RuntimeError):
    """Raised before any economic result is read or persisted."""


class GateIntegrityError(observer.DataQualityError):
    """Raised when frozen gate lineage or forward evidence differs."""


@dataclasses.dataclass(frozen=True)
class ForwardGateConfig:
    gate_protocol_path: pathlib.Path
    gate_lock_path: pathlib.Path
    output_root: pathlib.Path
    observer_config: observer.ForwardObserverConfig

    def validate(self) -> None:
        self.observer_config.validate()
        paths = {
            self.gate_protocol_path.resolve(),
            self.gate_lock_path.resolve(),
            self.output_root.resolve(),
        }
        if len(paths) != 3:
            raise ValueError("gate protocol, lock and output paths must differ")


def _sha256(path: pathlib.Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _atomic_json(path: pathlib.Path, value: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(
        prefix=f".{path.name}.", suffix=".tmp", dir=str(path.parent)
    )
    temporary = pathlib.Path(temporary_name)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
            json.dump(value, stream, indent=2, sort_keys=True)
            stream.write("\n")
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    finally:
        if temporary.exists():
            temporary.unlink()


def frozen_gate_protocol() -> dict:
    """Return the result-free, fully interpreted official gate."""

    forward = forward_protocol.frozen_protocol()
    forward_payload = forward_protocol.protocol_payload()
    if forward_payload["protocol_sha256"] != FORWARD_PROTOCOL_SHA256:
        raise RuntimeError("forward protocol source changed before gate freeze")
    parent_gate = forward["forward_gate"]
    return {
        "schema_version": SCHEMA_VERSION,
        "gate_version": GATE_VERSION,
        "preregistered_on": PREREGISTERED_ON,
        "status": "result_free_single_run_gate_requires_gate_lock",
        "research_only": True,
        "observation_only": True,
        "public_data_only": True,
        "credentials_used": False,
        "orders_authorized": False,
        "paper_orders_authorized": False,
        "automatic_promotion": False,
        "lineage": {
            "forward_protocol_sha256": FORWARD_PROTOCOL_SHA256,
            "forward_protocol_file_sha256": FORWARD_PROTOCOL_FILE_SHA256,
            "observer_implementation_lock_sha256": (
                OBSERVER_IMPLEMENTATION_LOCK_SHA256
            ),
            "observer_implementation_lock_file_sha256": (
                OBSERVER_IMPLEMENTATION_LOCK_FILE_SHA256
            ),
            "selected_configuration_id": "trend50_cointegration50",
            "trend_capital_weight": 0.5,
            "cointegration_capital_weight": 0.5,
        },
        "timeline": {
            "official_start_bar": OFFICIAL_START.isoformat(),
            "official_end_exclusive_bar": OFFICIAL_END_EXCLUSIVE.isoformat(),
            "official_days_required": OFFICIAL_DAYS,
            "warmup_days_required": WARMUP_DAYS,
            "evaluation_not_before_utc": EVALUATION_NOT_BEFORE.isoformat(),
            "post_cutoff_outcomes_forbidden": True,
        },
        "prerequisites": {
            "complete_contiguous_warmup_panel_required": True,
            "complete_contiguous_official_panel_required": True,
            "exact_official_market_records": OFFICIAL_DAYS,
            "exact_official_decision_records": OFFICIAL_DAYS,
            "all_content_addressed_raw_responses_verified": True,
            "market_record_hash_chain_verified": True,
            "decision_journal_hash_chain_verified": True,
            "every_decision_recomputed_and_matched_exactly": True,
            "minimum_observed_days_retained": parent_gate[
                "minimum_observed_days"
            ],
            "single_official_gate_run": True,
        },
        "economic_accounting": {
            "cost_multipliers": [1.0, 3.0],
            "funding_included": True,
            "fixed_initial_sleeve_weights": {
                "trend": 0.5,
                "cointegration": 0.5,
            },
            "component_equities_compound_independently": True,
            "combined_equity_formula": (
                "0.5 * trend_equity + 0.5 * cointegration_equity"
            ),
            "trend_cutoff_accounting": (
                "mark to market through final official bar; do not liquidate"
            ),
            "cointegration_cutoff_accounting": (
                "use frozen training simulate_period: realize the position "
                "selected on the prior bar, do not open a post-cutoff target, "
                "and charge one terminal liquidation on the final bar"
            ),
            "observer_cointegration_path_must_match_gate_path_before_final_bar": (
                True
            ),
            "terminal_accounting_difference_is_allowed_only_on_final_bar": True,
            "annualization_days": 365.25,
            "sharpe_scale_days": 365.0,
            "sharpe_risk_free_rate": 0.0,
            "standard_deviation_ddof": 0,
            "maximum_drawdown_includes_initial_equity": True,
            "monthly_returns_grouped_by_utc_bar_month": True,
            "zero_month_is_not_positive": True,
            "sleeve_contribution_formula": (
                "0.5 * (terminal_component_equity - 1.0)"
            ),
        },
        "pass_fail_gate": {
            "minimum_calendar_days": parent_gate["minimum_calendar_days"],
            "minimum_observed_days": parent_gate["minimum_observed_days"],
            "minimum_cointegration_closed_trades": parent_gate[
                "minimum_cointegration_closed_trades"
            ],
            "minimum_trend_invested_days": parent_gate[
                "minimum_trend_invested_days"
            ],
            "base_total_return_strictly_positive": parent_gate[
                "base_total_return_positive"
            ],
            "stress_total_return_strictly_positive": parent_gate[
                "stress_total_return_positive"
            ],
            "minimum_base_annualized_return": parent_gate[
                "minimum_base_annualized_return"
            ],
            "minimum_stress_annualized_return": parent_gate[
                "minimum_stress_annualized_return"
            ],
            "minimum_base_sharpe": parent_gate["minimum_base_sharpe"],
            "minimum_stress_sharpe": parent_gate["minimum_stress_sharpe"],
            "maximum_base_drawdown": parent_gate["maximum_base_drawdown"],
            "maximum_stress_drawdown": parent_gate[
                "maximum_stress_drawdown"
            ],
            "minimum_base_positive_month_ratio": parent_gate[
                "minimum_positive_month_ratio"
            ],
            "minimum_stress_positive_month_ratio": parent_gate[
                "minimum_positive_month_ratio"
            ],
            "base_both_sleeve_contributions_non_negative": parent_gate[
                "both_sleeve_additive_contributions_non_negative"
            ],
            "stress_both_sleeve_contributions_non_negative": parent_gate[
                "both_sleeve_additive_contributions_non_negative"
            ],
            "all_checks_required": True,
        },
        "official_result": {
            "one_immutable_report_and_manifest": True,
            "failed_gate_is_final_for_this_protocol_and_dataset": True,
            "passed_gate_permits_only_manual_guarded_paper_review": True,
            "passed_gate_does_not_start_paper": True,
            "passed_gate_does_not_authorize_orders": True,
            "repeated_official_evaluation_forbidden": True,
        },
        "results": None,
    }


def gate_protocol_payload() -> dict:
    frozen = frozen_gate_protocol()
    return {**frozen, "gate_protocol_sha256": observer._json_hash(frozen)}


def load_and_verify_gate_protocol(path_value: typing.Union[str, pathlib.Path]) -> dict:
    path = pathlib.Path(path_value).resolve()
    if not path.is_file():
        raise GateIntegrityError("gate protocol is missing")
    persisted = json.loads(path.read_text(encoding="utf-8"))
    if persisted != gate_protocol_payload():
        raise GateIntegrityError("persisted gate protocol differs")
    return persisted


def write_or_verify_gate_protocol(
    path_value: typing.Union[str, pathlib.Path],
) -> dict:
    path = pathlib.Path(path_value).resolve()
    if path.is_file():
        return load_and_verify_gate_protocol(path)
    expected = gate_protocol_payload()
    _atomic_json(path, expected)
    return load_and_verify_gate_protocol(path)


def _repo_root() -> pathlib.Path:
    return pathlib.Path(__file__).resolve().parents[2]


def _gate_source_paths() -> dict[str, pathlib.Path]:
    root = _repo_root()
    return {
        "gate_evaluator": pathlib.Path(__file__).resolve(),
        "gate_evaluator_tests": root
        / "tests/unit_tests/ai_strategy_lab/"
        "test_diversified_trend_cointegration_forward_gate_v1.py",
    }


def _gate_source_artifacts() -> dict[str, dict]:
    root = _repo_root()
    result = {}
    for label, path in sorted(_gate_source_paths().items()):
        resolved = path.resolve()
        if not resolved.is_file():
            raise GateIntegrityError(f"gate source is missing: {label}")
        result[label] = {
            "repo_relative_path": str(resolved.relative_to(root)),
            "bytes": resolved.stat().st_size,
            "sha256": _sha256(resolved),
        }
    return result


def _unsigned_hash(value: dict, signature_field: str) -> str:
    return observer._json_hash(
        {key: item for key, item in value.items() if key != signature_field}
    )


def _official_result_prefix(gate_protocol_sha256: str) -> str:
    return f"diversified-forward-gate-v1-{gate_protocol_sha256[:12]}-"


def _existing_official_results(
    output_root: pathlib.Path, gate_protocol_sha256: str
) -> list[pathlib.Path]:
    prefix = _official_result_prefix(gate_protocol_sha256)
    if not output_root.exists():
        return []
    return sorted(
        value
        for value in output_root.iterdir()
        if value.name.startswith(prefix)
    )


def create_or_verify_gate_lock(
    config: ForwardGateConfig,
    *,
    now: typing.Optional[datetime.datetime] = None,
) -> dict:
    """Bind evaluator sources while the official sample is still unseen."""

    config.validate()
    observed_at = now or datetime.datetime.now(UTC)
    if observed_at.tzinfo is None:
        raise ValueError("gate-lock time must be timezone-aware")
    observed_at = observed_at.astimezone(UTC)
    if config.gate_lock_path.is_file():
        return verify_gate_lock(config)["gate_lock"]
    if observed_at >= datetime.datetime.combine(
        OFFICIAL_START, datetime.time(), UTC
    ):
        raise GateNotReadyError("gate lock cannot be created after forward start")

    gate_protocol = load_and_verify_gate_protocol(config.gate_protocol_path)
    context = observer.verify_implementation_lock(config.observer_config)
    implementation_lock = context["implementation_lock"]
    if (
        implementation_lock["implementation_lock_sha256"]
        != OBSERVER_IMPLEMENTATION_LOCK_SHA256
        or _sha256(config.observer_config.implementation_lock_path)
        != OBSERVER_IMPLEMENTATION_LOCK_FILE_SHA256
    ):
        raise GateIntegrityError("observer implementation lock differs")
    records = observer.load_daily_records(
        config.observer_config.archive_root,
        expected_symbols=context["cointegration_market"]["symbols"],
    )
    decisions = observer.load_decision_journal(
        config.observer_config.journal_path
    )
    official_records = [
        value
        for value in records
        if datetime.date.fromisoformat(value["bar_date"]) >= OFFICIAL_START
    ]
    if official_records or decisions:
        raise GateIntegrityError(
            "gate lock requires zero official records and zero decisions"
        )
    if _existing_official_results(
        config.output_root, gate_protocol["gate_protocol_sha256"]
    ):
        raise GateIntegrityError("an official gate result already exists")

    payload = {
        "schema_version": SCHEMA_VERSION,
        "gate_version": GATE_VERSION,
        "created_at": observed_at.isoformat(),
        "status": "immutable_result_free_pre_forward_gate_lock",
        "research_only": True,
        "public_data_only": True,
        "credentials_used": False,
        "orders_authorized": False,
        "paper_orders_authorized": False,
        "automatic_promotion": False,
        "gate_protocol_sha256": gate_protocol["gate_protocol_sha256"],
        "gate_protocol_file_sha256": _sha256(config.gate_protocol_path),
        "forward_protocol_sha256": FORWARD_PROTOCOL_SHA256,
        "forward_protocol_file_sha256": FORWARD_PROTOCOL_FILE_SHA256,
        "observer_implementation_lock_sha256": (
            OBSERVER_IMPLEMENTATION_LOCK_SHA256
        ),
        "observer_implementation_lock_file_sha256": (
            OBSERVER_IMPLEMENTATION_LOCK_FILE_SHA256
        ),
        "source_files": _gate_source_artifacts(),
        "runtime": {
            "python_major_minor": [
                os.sys.version_info.major,
                os.sys.version_info.minor,
            ],
            "numpy_version": numpy.__version__,
        },
        "pre_forward_state": {
            "warmup_records": len(records),
            "official_records": 0,
            "decision_records": 0,
            "forward_economic_outcomes_read": 0,
            "official_results_present": 0,
        },
    }
    locked = {**payload, "gate_lock_sha256": observer._json_hash(payload)}
    _atomic_json(config.gate_lock_path, locked)
    return verify_gate_lock(config)["gate_lock"]


def verify_gate_lock(config: ForwardGateConfig) -> dict:
    config.validate()
    gate_protocol = load_and_verify_gate_protocol(config.gate_protocol_path)
    observer_context = observer.verify_implementation_lock(
        config.observer_config
    )
    path = config.gate_lock_path.resolve()
    if not path.is_file():
        raise GateIntegrityError("gate lock is missing")
    locked = json.loads(path.read_text(encoding="utf-8"))
    if (
        locked.get("gate_lock_sha256")
        != _unsigned_hash(locked, "gate_lock_sha256")
        or locked.get("gate_protocol_sha256")
        != gate_protocol["gate_protocol_sha256"]
        or locked.get("gate_protocol_file_sha256")
        != _sha256(config.gate_protocol_path)
        or locked.get("observer_implementation_lock_sha256")
        != OBSERVER_IMPLEMENTATION_LOCK_SHA256
        or locked.get("observer_implementation_lock_file_sha256")
        != _sha256(config.observer_config.implementation_lock_path)
        or locked.get("orders_authorized") is not False
        or locked.get("paper_orders_authorized") is not False
        or locked.get("automatic_promotion") is not False
    ):
        raise GateIntegrityError("gate lock content differs")
    if locked.get("source_files") != _gate_source_artifacts():
        raise GateIntegrityError("gate evaluator source changed after lock")
    return {
        **observer_context,
        "gate_protocol": gate_protocol,
        "gate_lock": locked,
    }


def _dates(start: datetime.date, end_exclusive: datetime.date) -> list[datetime.date]:
    return [
        start + datetime.timedelta(days=index)
        for index in range((end_exclusive - start).days)
    ]


def _panel_dates(records: list[dict]) -> list[datetime.date]:
    return [datetime.date.fromisoformat(value["bar_date"]) for value in records]


def _partition_panel(records: list[dict]) -> tuple[list[dict], list[dict]]:
    warmup = []
    official = []
    for value in records:
        date = datetime.date.fromisoformat(value["bar_date"])
        if date < OFFICIAL_START:
            warmup.append(value)
        elif date < OFFICIAL_END_EXCLUSIVE:
            official.append(value)
        else:
            raise GateIntegrityError("market archive contains a post-cutoff bar")
    return warmup, official


def _assert_complete_panel(records: list[dict]) -> tuple[list[dict], list[dict]]:
    warmup, official = _partition_panel(records)
    if _panel_dates(warmup) != _dates(
        forward_protocol.WARMUP_START, OFFICIAL_START
    ):
        raise GateIntegrityError("warmup panel is not exactly complete")
    if _panel_dates(official) != _dates(
        OFFICIAL_START, OFFICIAL_END_EXCLUSIVE
    ):
        raise GateIntegrityError("official panel is not exactly complete")
    return warmup, official


def readiness(
    config: ForwardGateConfig,
    *,
    now: typing.Optional[datetime.datetime] = None,
) -> dict:
    """Report structural progress without calculating economic metrics."""

    observed_at = now or datetime.datetime.now(UTC)
    if observed_at.tzinfo is None:
        raise ValueError("readiness time must be timezone-aware")
    observed_at = observed_at.astimezone(UTC)
    context = verify_gate_lock(config)
    records = observer.load_daily_records(
        config.observer_config.archive_root,
        expected_symbols=context["cointegration_market"]["symbols"],
    )
    decisions = observer.load_decision_journal(
        config.observer_config.journal_path
    )
    warmup, official = _partition_panel(records)
    expected_warmup = _dates(forward_protocol.WARMUP_START, OFFICIAL_START)
    expected_official = _dates(OFFICIAL_START, OFFICIAL_END_EXCLUSIVE)
    warmup_dates = _panel_dates(warmup)
    official_dates = _panel_dates(official)
    warmup_prefix = warmup_dates == expected_warmup[: len(warmup_dates)]
    official_prefix = official_dates == expected_official[: len(official_dates)]
    decision_dates = [
        datetime.date.fromisoformat(value["decision_payload"]["bar_date"])
        for value in decisions
    ]
    decision_prefix = decision_dates == expected_official[: len(decision_dates)]
    blockers = []
    if not warmup_prefix or len(warmup) != WARMUP_DAYS:
        blockers.append("warmup_panel")
    if not official_prefix or len(official) != OFFICIAL_DAYS:
        blockers.append("official_panel")
    if not decision_prefix or len(decisions) != OFFICIAL_DAYS:
        blockers.append("decision_journal")
    if observed_at < EVALUATION_NOT_BEFORE:
        blockers.append("calendar_cutoff")
    existing = _existing_official_results(
        config.output_root,
        context["gate_protocol"]["gate_protocol_sha256"],
    )
    if existing:
        blockers.append("official_result_already_exists")
    return {
        "schema_version": SCHEMA_VERSION,
        "gate_version": GATE_VERSION,
        "observed_at": observed_at.isoformat(),
        "status": "READY" if not blockers else "LOCKED",
        "research_only": True,
        "economic_metrics_calculated": False,
        "economic_results_persisted": False,
        "orders_authorized": False,
        "paper_orders_authorized": False,
        "warmup_records": len(warmup),
        "warmup_records_required": WARMUP_DAYS,
        "official_records": len(official),
        "official_records_required": OFFICIAL_DAYS,
        "decision_records": len(decisions),
        "decision_records_required": OFFICIAL_DAYS,
        "evaluation_not_before_utc": EVALUATION_NOT_BEFORE.isoformat(),
        "blockers": blockers,
        "official_evaluation_authorized": not blockers,
    }


def _period_returns(
    dates: list[datetime.date], values: numpy.ndarray
) -> dict[str, float]:
    grouped: dict[str, list[float]] = {}
    for date, value in zip(dates, values):
        grouped.setdefault(date.strftime("%Y-%m"), []).append(float(value))
    return {
        key: float(numpy.prod(1.0 + numpy.asarray(group)) - 1.0)
        for key, group in sorted(grouped.items())
    }


def portfolio_metrics(
    dates: list[datetime.date],
    trend_daily: typing.Sequence[float],
    cointegration_daily: typing.Sequence[float],
) -> dict:
    """Apply the frozen fixed-initial-capital portfolio accounting."""

    trend_values = numpy.asarray(trend_daily, dtype=numpy.float64)
    cointegration_values = numpy.asarray(
        cointegration_daily, dtype=numpy.float64
    )
    if (
        len(dates) != OFFICIAL_DAYS
        or trend_values.shape != (OFFICIAL_DAYS,)
        or cointegration_values.shape != (OFFICIAL_DAYS,)
        or numpy.any(~numpy.isfinite(trend_values))
        or numpy.any(~numpy.isfinite(cointegration_values))
        or numpy.any(trend_values <= -1.0)
        or numpy.any(cointegration_values <= -1.0)
    ):
        raise GateIntegrityError("component gate trajectories are invalid")
    trend_equity = numpy.cumprod(1.0 + trend_values)
    cointegration_equity = numpy.cumprod(1.0 + cointegration_values)
    combined_equity = 0.5 * trend_equity + 0.5 * cointegration_equity
    starting = numpy.concatenate((numpy.ones(1), combined_equity))
    combined_daily = numpy.diff(starting) / starting[:-1]
    if (
        numpy.any(~numpy.isfinite(combined_equity))
        or numpy.any(combined_equity <= 0)
        or numpy.any(combined_daily <= -1.0)
    ):
        raise GateIntegrityError("combined gate trajectory is invalid")
    peaks = numpy.maximum.accumulate(starting)[1:]
    drawdown = 1.0 - combined_equity / peaks
    monthly = _period_returns(dates, combined_daily)
    deviation = float(numpy.std(combined_daily))
    elapsed_years = OFFICIAL_DAYS / 365.25
    return {
        "start": dates[0].isoformat(),
        "end_exclusive": OFFICIAL_END_EXCLUSIVE.isoformat(),
        "days": OFFICIAL_DAYS,
        "total_return": float(combined_equity[-1] - 1.0),
        "annualized_return": float(
            combined_equity[-1] ** (1.0 / elapsed_years) - 1.0
        ),
        "sharpe_zero_rate": (
            float(numpy.mean(combined_daily) / deviation * math.sqrt(365.0))
            if deviation > 0
            else 0.0
        ),
        "maximum_drawdown": float(numpy.max(drawdown)),
        "positive_month_ratio": (
            sum(value > 0 for value in monthly.values()) / len(monthly)
            if monthly
            else 0.0
        ),
        "months": monthly,
        "trend_terminal_equity": float(trend_equity[-1]),
        "cointegration_terminal_equity": float(cointegration_equity[-1]),
        "trend_additive_contribution": float(
            0.5 * (trend_equity[-1] - 1.0)
        ),
        "cointegration_additive_contribution": float(
            0.5 * (cointegration_equity[-1] - 1.0)
        ),
        "_trajectory": {
            "trend_daily_return": trend_values.tolist(),
            "cointegration_daily_return": cointegration_values.tolist(),
            "combined_daily_return": combined_daily.tolist(),
            "combined_equity": combined_equity.tolist(),
        },
    }


def gate_checks(base: dict, stress: dict, activity: dict, gate: dict) -> dict:
    checks = {
        "minimum_calendar_days": OFFICIAL_DAYS
        >= gate["minimum_calendar_days"],
        "minimum_observed_days": activity["observed_days"]
        >= gate["minimum_observed_days"],
        "minimum_cointegration_closed_trades": activity[
            "cointegration_closed_trades"
        ]
        >= gate["minimum_cointegration_closed_trades"],
        "minimum_trend_invested_days": activity["trend_invested_days"]
        >= gate["minimum_trend_invested_days"],
        "base_total_return_strictly_positive": base["total_return"] > 0,
        "stress_total_return_strictly_positive": stress["total_return"] > 0,
        "minimum_base_annualized_return": base["annualized_return"]
        >= gate["minimum_base_annualized_return"],
        "minimum_stress_annualized_return": stress["annualized_return"]
        >= gate["minimum_stress_annualized_return"],
        "minimum_base_sharpe": base["sharpe_zero_rate"]
        >= gate["minimum_base_sharpe"],
        "minimum_stress_sharpe": stress["sharpe_zero_rate"]
        >= gate["minimum_stress_sharpe"],
        "maximum_base_drawdown": base["maximum_drawdown"]
        <= gate["maximum_base_drawdown"],
        "maximum_stress_drawdown": stress["maximum_drawdown"]
        <= gate["maximum_stress_drawdown"],
        "minimum_base_positive_month_ratio": base["positive_month_ratio"]
        >= gate["minimum_base_positive_month_ratio"],
        "minimum_stress_positive_month_ratio": stress[
            "positive_month_ratio"
        ]
        >= gate["minimum_stress_positive_month_ratio"],
        "base_trend_contribution_non_negative": base[
            "trend_additive_contribution"
        ]
        >= 0,
        "base_cointegration_contribution_non_negative": base[
            "cointegration_additive_contribution"
        ]
        >= 0,
        "stress_trend_contribution_non_negative": stress[
            "trend_additive_contribution"
        ]
        >= 0,
        "stress_cointegration_contribution_non_negative": stress[
            "cointegration_additive_contribution"
        ]
        >= 0,
    }
    return {"checks": checks, "passed": bool(all(checks.values()))}


def _compact_metrics(value: dict) -> dict:
    return {key: item for key, item in value.items() if key != "_trajectory"}


def _verify_exact_decision_replay(
    decisions: list[dict], expected_payloads: list[dict]
) -> None:
    if len(decisions) != OFFICIAL_DAYS or len(expected_payloads) != OFFICIAL_DAYS:
        raise GateIntegrityError("official decision count differs")
    for index, (record, expected) in enumerate(
        zip(decisions, expected_payloads)
    ):
        if record["decision_payload"] != expected:
            raise GateIntegrityError(
                f"official decision replay differs at index {index}"
            )


def _extract_trend_daily(payloads: list[dict], field: str) -> numpy.ndarray:
    return numpy.asarray(
        [value[field]["trend_daily_return"] for value in payloads],
        dtype=numpy.float64,
    )


def _cointegration_gate_periods(context: dict, market: dict) -> dict:
    cache = pairs.build_formation_cache(
        market,
        OFFICIAL_START,
        OFFICIAL_END_EXCLUSIVE,
        context["null"],
    )
    return {
        multiplier: pairs.simulate_period(
            market,
            cache,
            OFFICIAL_START,
            OFFICIAL_END_EXCLUSIVE,
            cost_multiplier=multiplier,
            include_trajectory=True,
            include_details=True,
        )
        for multiplier in (1.0, 3.0)
    }


def _verify_preterminal_cointegration(
    payloads: list[dict], reports: dict
) -> dict:
    differences = {}
    for multiplier, field in ((1.0, "base"), (3.0, "stress_3x_cost")):
        observed = numpy.asarray(
            [value[field]["cointegration_daily_return"] for value in payloads],
            dtype=numpy.float64,
        )
        terminal = numpy.asarray(
            reports[multiplier]["_trajectory"]["daily_return"],
            dtype=numpy.float64,
        )
        if observed.shape != (OFFICIAL_DAYS,) or terminal.shape != (
            OFFICIAL_DAYS,
        ):
            raise GateIntegrityError("cointegration gate path shape differs")
        maximum = float(numpy.max(numpy.abs(observed[:-1] - terminal[:-1])))
        if maximum > 1e-14:
            raise GateIntegrityError(
                "cointegration observer differs before terminal accounting"
            )
        differences[f"cost_{multiplier:g}x"] = {
            "days_compared": OFFICIAL_DAYS - 1,
            "maximum_daily_return_absolute_difference": maximum,
            "final_observer_daily_return": float(observed[-1]),
            "final_gate_daily_return": float(terminal[-1]),
            "final_difference_is_prescribed_terminal_accounting": True,
        }
    return differences


def evaluate(
    config: ForwardGateConfig,
    *,
    now: typing.Optional[datetime.datetime] = None,
) -> dict:
    """Run and persist the one official gate after every lock is satisfied."""

    evaluated_at = now or datetime.datetime.now(UTC)
    if evaluated_at.tzinfo is None:
        raise ValueError("evaluation time must be timezone-aware")
    evaluated_at = evaluated_at.astimezone(UTC)
    # This check deliberately precedes all archive/journal access.
    if evaluated_at < EVALUATION_NOT_BEFORE:
        raise GateNotReadyError(
            f"official evaluation is locked until {EVALUATION_NOT_BEFORE.isoformat()}"
        )

    context = verify_gate_lock(config)
    gate_protocol = context["gate_protocol"]
    existing = _existing_official_results(
        config.output_root, gate_protocol["gate_protocol_sha256"]
    )
    if existing:
        raise FileExistsError(
            f"official forward gate already exists: {existing[0]}"
        )

    symbols = list(context["cointegration_market"]["symbols"])
    records = observer.load_daily_records(
        config.observer_config.archive_root,
        raw_root=config.observer_config.raw_root,
        expected_symbols=symbols,
    )
    warmup, official = _assert_complete_panel(records)
    decisions = observer.load_decision_journal(
        config.observer_config.journal_path
    )
    if len(decisions) < gate_protocol["prerequisites"][
        "minimum_observed_days_retained"
    ]:
        raise GateIntegrityError("minimum official observations are absent")

    cointegration_market = observer.extend_cointegration_market(
        context["cointegration_market"], records
    )
    trend_market = observer.extend_trend_market(
        context["trend_market"], context["cointegration_market"], records
    )
    expected_payloads = observer._bind_decision_lineage(
        observer.build_decision_payloads(
            trend_market,
            cointegration_market,
            context["trend_config"],
            context["null"],
            records,
        ),
        context,
    )
    _verify_exact_decision_replay(decisions, expected_payloads)

    cointegration_reports = _cointegration_gate_periods(
        context, cointegration_market
    )
    terminal_audit = _verify_preterminal_cointegration(
        expected_payloads, cointegration_reports
    )
    dates = _dates(OFFICIAL_START, OFFICIAL_END_EXCLUSIVE)
    base = portfolio_metrics(
        dates,
        _extract_trend_daily(expected_payloads, "base"),
        cointegration_reports[1.0]["_trajectory"]["daily_return"],
    )
    stress = portfolio_metrics(
        dates,
        _extract_trend_daily(expected_payloads, "stress_3x_cost"),
        cointegration_reports[3.0]["_trajectory"]["daily_return"],
    )
    activity = {
        "calendar_days": OFFICIAL_DAYS,
        "observed_days": len(official),
        "trend_invested_days": expected_payloads[-1]["cumulative_activity"][
            "trend_invested_days"
        ],
        "cointegration_closed_trades": cointegration_reports[1.0][
            "closed_trades"
        ],
        "cointegration_terminally_closed_trades": sum(
            value["exit_reason"] == "period_end"
            for value in cointegration_reports[1.0]["trades"]
        ),
    }
    gate = gate_checks(
        base,
        stress,
        activity,
        gate_protocol["pass_fail_gate"],
    )
    verdict = "PASS_MANUAL_GUARDED_PAPER_REVIEW" if gate["passed"] else "FAIL_REJECTED"
    experiment_key = observer._json_hash(
        {
            "gate_protocol_sha256": gate_protocol["gate_protocol_sha256"],
            "gate_lock_sha256": context["gate_lock"]["gate_lock_sha256"],
            "last_market_record_hash": records[-1]["record_hash"],
            "last_journal_hash": decisions[-1]["journal_record_hash"],
        }
    )
    experiment = config.output_root / (
        f"{_official_result_prefix(gate_protocol['gate_protocol_sha256'])}"
        f"{experiment_key[:12]}"
    )
    config.output_root.mkdir(parents=True, exist_ok=True)
    temporary = pathlib.Path(
        tempfile.mkdtemp(prefix=".diversified-forward-gate.", dir=config.output_root)
    )
    try:
        trajectory = {
            "schema_version": SCHEMA_VERSION,
            "gate_protocol_sha256": gate_protocol["gate_protocol_sha256"],
            "dates": [value.isoformat() for value in dates],
            "base": base["_trajectory"],
            "stress_3x_cost": stress["_trajectory"],
        }
        trajectory["content_sha256"] = observer._json_hash(trajectory)
        trajectory_path = temporary / "forward-trajectories.json"
        _atomic_json(trajectory_path, trajectory)

        report = {
            "schema_version": SCHEMA_VERSION,
            "gate_version": GATE_VERSION,
            "created_at": evaluated_at.isoformat(),
            "status": "official_single_run_complete",
            "research_only": True,
            "public_data_only": True,
            "credentials_used": False,
            "orders_authorized": False,
            "paper_orders_authorized": False,
            "automatic_promotion": False,
            "gate_protocol_sha256": gate_protocol["gate_protocol_sha256"],
            "gate_protocol_file_sha256": _sha256(config.gate_protocol_path),
            "gate_lock_sha256": context["gate_lock"]["gate_lock_sha256"],
            "gate_lock_file_sha256": _sha256(config.gate_lock_path),
            "observer_implementation_lock_sha256": (
                OBSERVER_IMPLEMENTATION_LOCK_SHA256
            ),
            "input_evidence": {
                "warmup_records": len(warmup),
                "official_records": len(official),
                "decision_records": len(decisions),
                "last_market_record_hash": records[-1]["record_hash"],
                "last_journal_hash": decisions[-1]["journal_record_hash"],
                "raw_archive_verified": True,
                "market_hash_chain_verified": True,
                "decision_hash_chain_verified": True,
                "exact_decision_replay_verified": True,
            },
            "terminal_accounting_audit": terminal_audit,
            "activity": activity,
            "base": _compact_metrics(base),
            "stress_3x_cost": _compact_metrics(stress),
            "gate": gate,
            "verdict": verdict,
            "manual_guarded_paper_review_permitted": gate["passed"],
            "paper_started": False,
            "results_do_not_authorize_orders": True,
            "trajectory": {
                "path": trajectory_path.name,
                "sha256": _sha256(trajectory_path),
                "content_sha256": trajectory["content_sha256"],
            },
        }
        report["content_sha256"] = observer._json_hash(report)
        report_path = temporary / "report.json"
        _atomic_json(report_path, report)
        manifest = {
            "schema_version": SCHEMA_VERSION,
            "gate_protocol_sha256": gate_protocol["gate_protocol_sha256"],
            "gate_lock_sha256": context["gate_lock"]["gate_lock_sha256"],
            "experiment_key": experiment_key,
            "report_sha256": _sha256(report_path),
            "report_content_sha256": report["content_sha256"],
            "trajectory_sha256": _sha256(trajectory_path),
            "trajectory_content_sha256": trajectory["content_sha256"],
            "verdict": verdict,
            "orders_authorized": False,
            "paper_orders_authorized": False,
            "automatic_promotion": False,
        }
        manifest["content_sha256"] = observer._json_hash(manifest)
        _atomic_json(temporary / "manifest.json", manifest)
        if experiment.exists():
            raise FileExistsError(f"official gate exists: {experiment}")
        os.replace(temporary, experiment)
        return {
            "directory": str(experiment),
            "report": report,
            "manifest": manifest,
        }
    except Exception:
        if temporary.exists():
            shutil.rmtree(temporary)
        raise


def _add_paths(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--gate-protocol", type=pathlib.Path, required=True)
    parser.add_argument("--gate-lock", type=pathlib.Path, required=True)
    parser.add_argument("--output-root", type=pathlib.Path, required=True)
    observer._add_common_paths(parser)


def _config_from_arguments(arguments) -> ForwardGateConfig:
    return ForwardGateConfig(
        gate_protocol_path=arguments.gate_protocol,
        gate_lock_path=arguments.gate_lock,
        output_root=arguments.output_root,
        observer_config=observer._config_from_arguments(arguments),
    )


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)
    write = subparsers.add_parser("write-protocol")
    write.add_argument("--gate-protocol", type=pathlib.Path, required=True)
    for name in ("freeze-gate", "readiness", "evaluate"):
        child = subparsers.add_parser(name)
        _add_paths(child)
    return parser


def main(argv: typing.Optional[list[str]] = None) -> int:
    arguments = _parser().parse_args(argv)
    if arguments.command == "write-protocol":
        result = write_or_verify_gate_protocol(arguments.gate_protocol)
    else:
        config = _config_from_arguments(arguments)
        if arguments.command == "freeze-gate":
            result = create_or_verify_gate_lock(config)
        elif arguments.command == "readiness":
            result = readiness(config)
        else:
            result = evaluate(config)
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
