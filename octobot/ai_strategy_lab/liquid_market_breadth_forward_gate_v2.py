"""Single-run fail-closed gate for liquid-market breadth forward V2.

The gate can report structural readiness before the frozen cutoff, but it
cannot calculate aggregate economic metrics until every official outcome is
mature.  It has no network, credential, paper-order or exchange-order surface.
"""

from __future__ import annotations

import argparse
import dataclasses
import datetime
import json
import math
import os
import pathlib
import shutil
import tempfile
import typing

import numpy

from octobot.ai_strategy_lab import cointegration_pairs_v1 as common
from octobot.ai_strategy_lab import (
    liquid_market_breadth_forward_runner as observer,
)
from octobot.ai_strategy_lab import (
    liquid_market_breadth_forward_v2 as forward_protocol,
)


SCHEMA_VERSION = 1
GATE_VERSION = "crypto_liquid_market_breadth_forward_gate_v2"
PREREGISTERED_ON = "2026-08-28"
UTC = datetime.timezone.utc
VARIANTS = ("breadth_v2", "parent_v1", "continuous")
SCENARIOS = ("base", "stress_3x_cost")

FORWARD_PROTOCOL_SHA256 = (
    "e70348d90fff8594401367065723dff543384c4920aab9f8f47ebb3e237117ba"
)
FORWARD_PROTOCOL_FILE_SHA256 = (
    "59a3a7327ddeef08a97aadb142f3172863d16615c9aa8171b790a58c44a55fd9"
)
OBSERVER_IMPLEMENTATION_LOCK_SHA256 = (
    "6cdf54608e0885e27afb39a0cf44fecfc281164b74d72c6922ce1458932db503"
)
OBSERVER_IMPLEMENTATION_LOCK_FILE_SHA256 = (
    "a5568b7d5e5d1ca4b606d188644ed9ac282d60116bdc276fa68c2c4eb13a7e4d"
)
OBSERVER_RUNNER_SHA256 = (
    "0ae77350a4ed3a88511d24650eeef0784f39fa73aefeeee9cc0b2b0572542950"
)

OFFICIAL_START = forward_protocol.FORWARD_START
OFFICIAL_END_EXCLUSIVE = forward_protocol.FORWARD_CUTOFF_EXCLUSIVE
OFFICIAL_DAYS = forward_protocol.FORWARD_CALENDAR_DAYS
MATURE_OUTCOMES = OFFICIAL_DAYS - 1
WARMUP_DAYS = (OFFICIAL_START - forward_protocol.WARMUP_START).days
EVALUATION_NOT_BEFORE = datetime.datetime.combine(
    OFFICIAL_END_EXCLUSIVE,
    datetime.time(
        minute=forward_protocol.DAILY_FINALIZATION_DELAY_MINUTES,
        tzinfo=UTC,
    ),
)


class GateNotReadyError(RuntimeError):
    """Raised before aggregate economic results may be calculated."""


class GateIntegrityError(observer.DataQualityError):
    """Raised when frozen lineage or forward evidence differs."""


@dataclasses.dataclass(frozen=True)
class GateConfig:
    gate_protocol_path: pathlib.Path
    gate_lock_path: pathlib.Path
    output_root: pathlib.Path
    gate_test_path: pathlib.Path
    entrypoint_path: pathlib.Path
    observer_config: observer.ForwardConfig

    def validate(self) -> None:
        paths = {
            self.gate_protocol_path.resolve(),
            self.gate_lock_path.resolve(),
            self.output_root.resolve(),
            self.gate_test_path.resolve(),
            self.entrypoint_path.resolve(),
        }
        if len(paths) != 5:
            raise ValueError("breadth gate paths must differ")


def _atomic_json(path: pathlib.Path, value: dict) -> None:
    common._atomic_json(path, value)


def frozen_gate_protocol() -> dict:
    forward = forward_protocol.protocol_payload()
    if forward["protocol_sha256"] != FORWARD_PROTOCOL_SHA256:
        raise RuntimeError("breadth forward protocol changed")
    gate = forward["forward_gate"]
    return {
        "schema_version": SCHEMA_VERSION,
        "gate_version": GATE_VERSION,
        "preregistered_on": PREREGISTERED_ON,
        "status": "result_free_single_run_gate_requires_pre_forward_lock",
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
            "observer_runner_sha256": OBSERVER_RUNNER_SHA256,
        },
        "timeline": {
            "official_start_bar": OFFICIAL_START.isoformat(),
            "official_end_exclusive_bar": OFFICIAL_END_EXCLUSIVE.isoformat(),
            "warmup_days_required": WARMUP_DAYS,
            "official_market_and_decision_days_required": OFFICIAL_DAYS,
            "mature_outcomes_required": MATURE_OUTCOMES,
            "evaluation_not_before_utc": EVALUATION_NOT_BEFORE.isoformat(),
            "first_decision_day_is_a_flat_non_return_day": True,
            "economic_metric_days": MATURE_OUTCOMES,
            "post_cutoff_outcomes_forbidden": True,
        },
        "accounting": {
            "variants": list(VARIANTS),
            "scenarios": list(SCENARIOS),
            "daily_net_returns_compound": True,
            "annualization_days": 365.25,
            "sharpe_scale_days": 365.0,
            "sharpe_risk_free_rate": 0.0,
            "standard_deviation_ddof": 0,
            "maximum_drawdown_includes_initial_equity": True,
            "monthly_returns_grouped_by_return_bearing_utc_month": True,
            "zero_month_is_not_positive": True,
            "profit_factor_uses_daily_net_returns": True,
            "no_negative_day_with_positive_gain_is_infinite_profit_factor": (
                True
            ),
            "gross_edge": "sum of price plus funding additive return",
            "symbol_contribution": (
                "cumulative price plus funding minus symbol-attributed "
                "turnover cost"
            ),
            "symbol_concentration": (
                "maximum absolute cumulative symbol contribution divided by "
                "sum absolute cumulative symbol contributions"
            ),
            "drawdown_ratio": "candidate drawdown divided by comparator drawdown",
            "zero_comparator_drawdown_passes_only_if_candidate_is_also_zero": (
                True
            ),
        },
        "bootstrap": {
            "daily_series": "breadth_v2 base net return",
            "statistic": "arithmetic daily mean multiplied by 365.25",
            "circular_blocks": True,
            "block_days": forward_protocol.BOOTSTRAP_BLOCK_DAYS,
            "simulations": forward_protocol.BOOTSTRAP_SIMULATIONS,
            "seed": forward_protocol.BOOTSTRAP_SEED,
            "lower_tail_probability": forward_protocol.PER_CANDIDATE_ALPHA,
            "quantile_method": "linear",
            "lower_bound_must_be_strictly_positive": True,
        },
        "pass_fail_gate": gate,
        "prerequisites": {
            "exact_warmup_prefix": True,
            "exact_official_market_panel": True,
            "exact_official_decision_journal": True,
            "all_raw_and_hash_chains_reverified": True,
            "all_decisions_recomputed_and_matched_exactly": True,
            "same_locked_signal_and_cost_code": True,
            "one_immutable_official_result": True,
        },
        "promotion_consequence": (
            "PASS permits only manual guarded-paper review and an independent "
            "confirmation; it cannot start paper or authorize an order"
        ),
        "results": None,
    }


def gate_protocol_payload() -> dict:
    frozen = frozen_gate_protocol()
    return {**frozen, "gate_protocol_sha256": observer._json_hash(frozen)}


def write_or_verify_gate_protocol(path: pathlib.Path) -> dict:
    expected = gate_protocol_payload()
    if path.is_file():
        persisted = json.loads(path.read_text(encoding="utf-8"))
        if persisted != expected:
            raise GateIntegrityError("breadth gate protocol differs")
        return persisted
    _atomic_json(path, expected)
    return expected


def _load_gate_protocol(path: pathlib.Path) -> dict:
    if not path.is_file():
        raise GateIntegrityError("breadth gate protocol is missing")
    return write_or_verify_gate_protocol(path)


def _source_artifacts(config: GateConfig) -> dict:
    values = {
        "gate": pathlib.Path(__file__).resolve(),
        "gate_test": config.gate_test_path.resolve(),
        "entrypoint": config.entrypoint_path.resolve(),
        "observer_runner": pathlib.Path(observer.__file__).resolve(),
        "forward_protocol": pathlib.Path(forward_protocol.__file__).resolve(),
    }
    result = {}
    for label, path in sorted(values.items()):
        if not path.is_file():
            raise GateIntegrityError(f"breadth gate source is absent: {label}")
        result[label] = {
            "bytes": path.stat().st_size,
            "sha256": common._sha256(path),
        }
    return result


def _verify_observer_lock(config: GateConfig) -> dict:
    lock = observer.verify_implementation_lock(config.observer_config)
    if (
        lock.get("implementation_lock_sha256")
        != OBSERVER_IMPLEMENTATION_LOCK_SHA256
        or common._sha256(config.observer_config.implementation_lock_path)
        != OBSERVER_IMPLEMENTATION_LOCK_FILE_SHA256
        or common._sha256(pathlib.Path(observer.__file__).resolve())
        != OBSERVER_RUNNER_SHA256
    ):
        raise GateIntegrityError("breadth observer lock lineage differs")
    return lock


def _existing_results(root: pathlib.Path, protocol_hash: str) -> list[pathlib.Path]:
    prefix = f"liquid-market-breadth-gate-v2-{protocol_hash[:12]}-"
    if not root.exists():
        return []
    return sorted(value for value in root.iterdir() if value.name.startswith(prefix))


def create_or_verify_gate_lock(
    config: GateConfig,
    *,
    now: datetime.datetime | None = None,
) -> dict:
    config.validate()
    observed_at = datetime.datetime.now(UTC) if now is None else now
    if observed_at.tzinfo is None:
        raise ValueError("gate lock time must be timezone-aware")
    observed_at = observed_at.astimezone(UTC)
    if config.gate_lock_path.is_file():
        return verify_gate_lock(config)["gate_lock"]
    if observed_at >= datetime.datetime.combine(
        OFFICIAL_START, datetime.time(), UTC
    ):
        raise GateNotReadyError("gate lock cannot be created after forward start")
    gate_protocol = _load_gate_protocol(config.gate_protocol_path)
    observer_lock = _verify_observer_lock(config)
    market, records = observer.load_extended_market(config.observer_config)
    journal = observer.load_journal(config.observer_config.journal_path)
    del market
    official = [
        value
        for value in records
        if datetime.date.fromisoformat(value["bar_date"]) >= OFFICIAL_START
    ]
    if official or journal:
        raise GateIntegrityError("gate lock requires zero official evidence")
    if _existing_results(
        config.output_root, gate_protocol["gate_protocol_sha256"]
    ):
        raise GateIntegrityError("official breadth gate result already exists")
    payload = {
        "schema_version": SCHEMA_VERSION,
        "gate_version": GATE_VERSION,
        "created_at": observed_at.isoformat(),
        "status": "immutable_result_free_pre_forward_gate_lock",
        "gate_protocol_sha256": gate_protocol["gate_protocol_sha256"],
        "gate_protocol_file_sha256": common._sha256(
            config.gate_protocol_path
        ),
        "observer_implementation_lock_sha256": observer_lock[
            "implementation_lock_sha256"
        ],
        "observer_implementation_lock_file_sha256": common._sha256(
            config.observer_config.implementation_lock_path
        ),
        "source_artifacts": _source_artifacts(config),
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
        "research_only": True,
        "credentials_used": False,
        "orders_authorized": False,
        "paper_orders_authorized": False,
        "automatic_promotion": False,
    }
    locked = {**payload, "gate_lock_sha256": observer._json_hash(payload)}
    _atomic_json(config.gate_lock_path, locked)
    return verify_gate_lock(config)["gate_lock"]


def verify_gate_lock(config: GateConfig) -> dict:
    config.validate()
    gate_protocol = _load_gate_protocol(config.gate_protocol_path)
    observer_lock = _verify_observer_lock(config)
    if not config.gate_lock_path.is_file():
        raise GateIntegrityError("breadth gate lock is missing")
    locked = json.loads(config.gate_lock_path.read_text(encoding="utf-8"))
    unsigned = {
        key: value for key, value in locked.items() if key != "gate_lock_sha256"
    }
    checks = (
        locked.get("gate_lock_sha256") == observer._json_hash(unsigned),
        locked.get("gate_protocol_sha256")
        == gate_protocol["gate_protocol_sha256"],
        locked.get("gate_protocol_file_sha256")
        == common._sha256(config.gate_protocol_path),
        locked.get("observer_implementation_lock_sha256")
        == observer_lock["implementation_lock_sha256"],
        locked.get("observer_implementation_lock_file_sha256")
        == common._sha256(config.observer_config.implementation_lock_path),
        locked.get("source_artifacts") == _source_artifacts(config),
        locked.get("runtime", {}).get("numpy_version") == numpy.__version__,
        locked.get("research_only") is True,
        locked.get("credentials_used") is False,
        locked.get("orders_authorized") is False,
        locked.get("paper_orders_authorized") is False,
        locked.get("automatic_promotion") is False,
    )
    if not all(checks):
        raise GateIntegrityError("breadth gate lock differs")
    return {
        "gate_protocol": gate_protocol,
        "gate_lock": locked,
        "observer_lock": observer_lock,
    }


def _dates(start: datetime.date, count: int) -> list[datetime.date]:
    return [start + datetime.timedelta(days=index) for index in range(count)]


def _partition_records(records: list[dict]) -> tuple[list[dict], list[dict]]:
    warmup = []
    official = []
    for value in records:
        date = datetime.date.fromisoformat(value["bar_date"])
        if date < OFFICIAL_START:
            warmup.append(value)
        elif date < OFFICIAL_END_EXCLUSIVE:
            official.append(value)
        else:
            raise GateIntegrityError("breadth archive contains post-cutoff bar")
    return warmup, official


def _structural_readiness(
    config: GateConfig,
    now: datetime.datetime,
) -> tuple[dict, dict, list[dict], list[dict]]:
    context = verify_gate_lock(config)
    market, records = observer.load_extended_market(config.observer_config)
    journal = observer.load_journal(config.observer_config.journal_path)
    warmup, official = _partition_records(records)
    expected_warmup = _dates(forward_protocol.WARMUP_START, WARMUP_DAYS)
    expected_official = _dates(OFFICIAL_START, OFFICIAL_DAYS)
    warmup_dates = [datetime.date.fromisoformat(v["bar_date"]) for v in warmup]
    official_dates = [datetime.date.fromisoformat(v["bar_date"]) for v in official]
    decision_dates = [
        datetime.date.fromisoformat(value["decision_payload"]["bar_date"])
        for value in journal
    ]
    mature = sum(
        value["decision_payload"]["matured_outcome"] is not None
        for value in journal
    )
    blockers = []
    if (
        warmup_dates != expected_warmup[: len(warmup_dates)]
        or len(warmup_dates) != WARMUP_DAYS
    ):
        blockers.append("warmup_market_records")
    if (
        official_dates != expected_official[: len(official_dates)]
        or len(official_dates) != OFFICIAL_DAYS
    ):
        blockers.append("official_market_records")
    if (
        decision_dates != expected_official[: len(decision_dates)]
        or len(decision_dates) != OFFICIAL_DAYS
    ):
        blockers.append("decision_records")
    if mature != MATURE_OUTCOMES:
        blockers.append("mature_outcomes")
    if now < EVALUATION_NOT_BEFORE:
        blockers.append("calendar_cutoff")
    if _existing_results(
        config.output_root,
        context["gate_protocol"]["gate_protocol_sha256"],
    ):
        blockers.append("official_result_already_exists")
    status = {
        "schema_version": SCHEMA_VERSION,
        "gate_version": GATE_VERSION,
        "observed_at": now.isoformat(),
        "status": "READY" if not blockers else "LOCKED",
        "warmup_records": len(warmup),
        "warmup_records_required": WARMUP_DAYS,
        "official_market_records": len(official),
        "official_market_records_required": OFFICIAL_DAYS,
        "decision_records": len(journal),
        "decision_records_required": OFFICIAL_DAYS,
        "mature_outcomes": mature,
        "mature_outcomes_required": MATURE_OUTCOMES,
        "evaluation_not_before_utc": EVALUATION_NOT_BEFORE.isoformat(),
        "blockers": blockers,
        "official_evaluation_authorized": not blockers,
        "economic_metrics_calculated": False,
        "economic_results_persisted": False,
        "research_only": True,
        "orders_authorized": False,
        "paper_orders_authorized": False,
        "automatic_promotion": False,
    }
    return status, market, records, journal


def readiness(
    config: GateConfig,
    *,
    now: datetime.datetime | None = None,
) -> dict:
    observed_at = datetime.datetime.now(UTC) if now is None else now
    if observed_at.tzinfo is None:
        raise ValueError("readiness time must be timezone-aware")
    observed_at = observed_at.astimezone(UTC)
    status, _market, _records, _journal = _structural_readiness(
        config, observed_at
    )
    return status


def _period_returns(
    dates: list[datetime.date], values: numpy.ndarray
) -> dict[str, float]:
    groups: dict[str, list[float]] = {}
    for date, value in zip(dates, values):
        groups.setdefault(date.strftime("%Y-%m"), []).append(float(value))
    return {
        key: float(numpy.prod(1.0 + numpy.asarray(group)) - 1.0)
        for key, group in sorted(groups.items())
    }


def return_metrics(dates: list[datetime.date], values: typing.Sequence[float]) -> dict:
    daily = numpy.asarray(values, dtype=numpy.float64)
    if (
        daily.shape != (len(dates),)
        or not len(daily)
        or numpy.any(~numpy.isfinite(daily))
        or numpy.any(daily <= -1.0)
    ):
        raise GateIntegrityError("breadth gate return series is invalid")
    equity = numpy.cumprod(1.0 + daily)
    with_initial = numpy.concatenate((numpy.ones(1), equity))
    peaks = numpy.maximum.accumulate(with_initial)[1:]
    drawdown = 1.0 - equity / peaks
    positive = float(numpy.sum(daily[daily > 0]))
    negative = float(-numpy.sum(daily[daily < 0]))
    infinite_pf = bool(negative == 0.0 and positive > 0.0)
    monthly = _period_returns(dates, daily)
    deviation = float(numpy.std(daily, ddof=0))
    years = len(daily) / 365.25
    return {
        "start": dates[0].isoformat(),
        "end": dates[-1].isoformat(),
        "days": len(daily),
        "total_return": float(equity[-1] - 1.0),
        "annualized_return": float(equity[-1] ** (1.0 / years) - 1.0),
        "sharpe_zero_rate": (
            float(numpy.mean(daily) / deviation * math.sqrt(365.0))
            if deviation > 0
            else 0.0
        ),
        "profit_factor": (positive / negative if negative > 0 else None),
        "profit_factor_is_infinite": infinite_pf,
        "maximum_drawdown": float(numpy.max(drawdown)),
        "positive_month_ratio": (
            sum(value > 0 for value in monthly.values()) / len(monthly)
            if monthly
            else 0.0
        ),
        "months": monthly,
        "_trajectory": {
            "daily_net_return": daily.tolist(),
            "equity": equity.tolist(),
        },
    }


def circular_block_bootstrap_lower(values: typing.Sequence[float]) -> float:
    daily = numpy.asarray(values, dtype=numpy.float64)
    if not len(daily) or numpy.any(~numpy.isfinite(daily)):
        raise GateIntegrityError("bootstrap series is invalid")
    simulations = forward_protocol.BOOTSTRAP_SIMULATIONS
    block = forward_protocol.BOOTSTRAP_BLOCK_DAYS
    blocks = math.ceil(len(daily) / block)
    generator = numpy.random.default_rng(forward_protocol.BOOTSTRAP_SEED)
    output = numpy.empty(simulations, dtype=numpy.float64)
    offsets = numpy.arange(block, dtype=numpy.int64)
    batch_size = 500
    for start in range(0, simulations, batch_size):
        count = min(batch_size, simulations - start)
        starts = generator.integers(0, len(daily), size=(count, blocks))
        indices = (starts[:, :, None] + offsets[None, None, :]) % len(daily)
        sampled = daily[indices.reshape(count, -1)[:, : len(daily)]]
        output[start : start + count] = numpy.mean(sampled, axis=1) * 365.25
    return float(
        numpy.quantile(
            output,
            forward_protocol.PER_CANDIDATE_ALPHA,
            interpolation="linear",
        )
    )


def _weights(payload: dict, variant: str, symbols: list[str]) -> numpy.ndarray:
    sparse = payload["research_targets"][variant]
    unknown = set(sparse) - set(symbols)
    if unknown:
        raise GateIntegrityError("breadth target contains an unknown symbol")
    return numpy.asarray(
        [float(sparse.get(symbol, 0.0)) for symbol in symbols],
        dtype=numpy.float64,
    )


def _symbol_contributions(
    market: dict,
    payloads: list[dict],
    variant: str,
    scenario: str,
) -> dict:
    symbols = list(market["symbols"])
    date_to_index = {date: index for index, date in enumerate(market["dates"])}
    cumulative = numpy.zeros(len(symbols), dtype=numpy.float64)
    multiplier = (
        1.0
        if scenario == "base"
        else forward_protocol.parent.STRESS_COST_MULTIPLIER
    )
    coefficient = multiplier * (
        forward_protocol.parent.FEE_PER_TURNOVER
        + forward_protocol.parent.SLIPPAGE_PER_TURNOVER
    )
    previous = numpy.zeros(len(symbols), dtype=numpy.float64)
    daily_sums = []
    for position in range(1, len(payloads)):
        target = _weights(payloads[position - 1], variant, symbols)
        date = datetime.date.fromisoformat(payloads[position]["bar_date"])
        index = date_to_index[date]
        contribution = (
            target * market["returns"][index]
            - target * market["funding"][index]
            - coefficient * numpy.abs(target - previous)
        )
        expected = payloads[position]["matured_outcome"][scenario][variant][
            "net_return"
        ]
        if not math.isclose(
            float(numpy.sum(contribution)),
            float(expected),
            rel_tol=0.0,
            abs_tol=1e-14,
        ):
            raise GateIntegrityError("symbol contributions do not reconcile")
        cumulative += contribution
        daily_sums.append(float(numpy.sum(contribution)))
        previous = target
    denominator = float(numpy.sum(numpy.abs(cumulative)))
    concentration = (
        float(numpy.max(numpy.abs(cumulative)) / denominator)
        if denominator > 0
        else None
    )
    return {
        "by_symbol": {
            symbol: float(cumulative[index])
            for index, symbol in enumerate(symbols)
        },
        "maximum_absolute_contribution_share": concentration,
        "daily_net_return": daily_sums,
    }


def _scenario_metrics(
    market: dict,
    payloads: list[dict],
    scenario: str,
) -> dict:
    dates = [
        datetime.date.fromisoformat(value["bar_date"])
        for value in payloads[1:]
    ]
    result = {}
    for variant in VARIANTS:
        outcomes = [
            value["matured_outcome"][scenario][variant]
            for value in payloads[1:]
        ]
        net = [float(value["net_return"]) for value in outcomes]
        contributions = _symbol_contributions(
            market, payloads, variant, scenario
        )
        if net != contributions["daily_net_return"]:
            if not numpy.allclose(
                net,
                contributions["daily_net_return"],
                rtol=0.0,
                atol=1e-14,
            ):
                raise GateIntegrityError("daily contribution path differs")
        metrics = return_metrics(dates, net)
        metrics.update(
            {
                "price_additive_return": float(
                    sum(value["price_return"] for value in outcomes)
                ),
                "funding_additive_return": float(
                    sum(value["funding_return"] for value in outcomes)
                ),
                "transaction_cost": float(
                    sum(value["transaction_cost"] for value in outcomes)
                ),
                "total_turnover": float(
                    sum(value["turnover"] for value in outcomes)
                ),
                "average_gross_exposure": float(
                    numpy.mean([value["gross_exposure"] for value in outcomes])
                ),
                "symbol_contributions": contributions["by_symbol"],
                "maximum_symbol_absolute_contribution_share": contributions[
                    "maximum_absolute_contribution_share"
                ],
            }
        )
        result[variant] = metrics
    return result


def _drawdown_ratio(candidate: float, comparator: float) -> float | None:
    if comparator > 0:
        return candidate / comparator
    return 0.0 if candidate == 0 else None


def _profit_factor_passes(metrics: dict, minimum: float) -> bool:
    return bool(
        metrics["profit_factor_is_infinite"]
        or (
            metrics["profit_factor"] is not None
            and metrics["profit_factor"] >= minimum
        )
    )


def gate_checks(
    base: dict,
    stress: dict,
    activity: dict,
    structural: dict,
    bootstrap_lower: float,
) -> dict:
    specification = forward_protocol.frozen_protocol()["forward_gate"]
    candidate = base["breadth_v2"]
    stressed = stress["breadth_v2"]
    continuous = base["continuous"]
    parent = base["parent_v1"]
    continuous_ratio = _drawdown_ratio(
        candidate["maximum_drawdown"], continuous["maximum_drawdown"]
    )
    parent_ratio = _drawdown_ratio(
        candidate["maximum_drawdown"], parent["maximum_drawdown"]
    )
    concentration = candidate[
        "maximum_symbol_absolute_contribution_share"
    ]
    checks = {
        "required_market_records": structural["official_market_records"]
        == specification["required_market_records"],
        "required_decision_records": structural["decision_records"]
        == specification["required_decision_records"],
        "minimum_mature_outcomes": structural["mature_outcomes"]
        >= specification["minimum_mature_outcomes"],
        "minimum_valid_signal_decisions": activity[
            "valid_signal_decisions"
        ]
        >= specification["minimum_valid_signal_decisions"],
        "minimum_active_vintage_decisions": activity[
            "active_vintage_decisions"
        ]
        >= specification["minimum_active_vintage_decisions"],
        "minimum_invested_days": activity["invested_days"]
        >= specification["minimum_invested_days"],
        "positive_total_return": candidate["total_return"] > 0,
        "stress_total_return_positive": stressed["total_return"] > 0,
        "minimum_annualized_return": candidate["annualized_return"]
        >= specification["minimum_annualized_return"],
        "minimum_stress_annualized_return": stressed["annualized_return"]
        >= specification["minimum_stress_annualized_return"],
        "minimum_sharpe": candidate["sharpe_zero_rate"]
        >= specification["minimum_sharpe"],
        "minimum_stress_sharpe": stressed["sharpe_zero_rate"]
        >= specification["minimum_stress_sharpe"],
        "minimum_profit_factor": _profit_factor_passes(
            candidate, specification["minimum_profit_factor"]
        ),
        "minimum_stress_profit_factor": _profit_factor_passes(
            stressed, specification["minimum_stress_profit_factor"]
        ),
        "maximum_drawdown": candidate["maximum_drawdown"]
        <= specification["maximum_drawdown"],
        "maximum_stress_drawdown": stressed["maximum_drawdown"]
        <= specification["maximum_stress_drawdown"],
        "minimum_positive_month_ratio": candidate["positive_month_ratio"]
        >= specification["minimum_positive_month_ratio"],
        "positive_annualized_alpha_vs_continuous": candidate[
            "annualized_return"
        ]
        - continuous["annualized_return"]
        > 0,
        "minimum_sharpe_improvement_vs_continuous": candidate[
            "sharpe_zero_rate"
        ]
        - continuous["sharpe_zero_rate"]
        >= specification["minimum_sharpe_improvement_vs_continuous"],
        "maximum_drawdown_ratio_vs_continuous": (
            continuous_ratio is not None
            and continuous_ratio
            <= specification["maximum_drawdown_ratio_vs_continuous"]
        ),
        "minimum_sharpe_improvement_vs_parent_v1": candidate[
            "sharpe_zero_rate"
        ]
        - parent["sharpe_zero_rate"]
        >= specification["minimum_sharpe_improvement_vs_parent_v1"],
        "maximum_drawdown_ratio_vs_parent_v1": (
            parent_ratio is not None
            and parent_ratio
            <= specification["maximum_drawdown_ratio_vs_parent_v1"]
        ),
        "gross_edge_exceeds_costs": candidate["price_additive_return"]
        + candidate["funding_additive_return"]
        > candidate["transaction_cost"],
        "stress_gross_edge_exceeds_costs": stressed[
            "price_additive_return"
        ]
        + stressed["funding_additive_return"]
        > stressed["transaction_cost"],
        "maximum_symbol_absolute_contribution_share": (
            concentration is not None
            and concentration
            <= specification["maximum_symbol_absolute_contribution_share"]
        ),
        "maximum_total_turnover": candidate["total_turnover"]
        <= specification["maximum_total_turnover"],
        "minimum_average_gross_exposure": candidate[
            "average_gross_exposure"
        ]
        >= specification["minimum_average_gross_exposure"],
        "maximum_post_net_gross": activity["maximum_post_net_gross"]
        <= specification["maximum_post_net_gross"],
        "bootstrap_lower_bound_positive": bootstrap_lower > 0,
        "complete_hash_chains_and_raw_lineage": structural[
            "complete_hash_chains_and_raw_lineage"
        ],
        "same_signal_costs_code_no_refit": structural[
            "same_signal_costs_code_no_refit"
        ],
    }
    return {
        "checks": checks,
        "passed_checks": sum(checks.values()),
        "total_checks": len(checks),
        "passed": bool(all(checks.values())),
        "derived": {
            "annualized_alpha_vs_continuous": candidate[
                "annualized_return"
            ]
            - continuous["annualized_return"],
            "sharpe_improvement_vs_continuous": candidate[
                "sharpe_zero_rate"
            ]
            - continuous["sharpe_zero_rate"],
            "drawdown_ratio_vs_continuous": continuous_ratio,
            "sharpe_improvement_vs_parent_v1": candidate[
                "sharpe_zero_rate"
            ]
            - parent["sharpe_zero_rate"],
            "drawdown_ratio_vs_parent_v1": parent_ratio,
            "bootstrap_annualized_mean_lower_98_75pct": bootstrap_lower,
        },
    }


def _compact(metrics: dict) -> dict:
    return {key: value for key, value in metrics.items() if key != "_trajectory"}


def evaluate(
    config: GateConfig,
    *,
    now: datetime.datetime | None = None,
) -> dict:
    evaluated_at = datetime.datetime.now(UTC) if now is None else now
    if evaluated_at.tzinfo is None:
        raise ValueError("evaluation time must be timezone-aware")
    evaluated_at = evaluated_at.astimezone(UTC)
    if evaluated_at < EVALUATION_NOT_BEFORE:
        raise GateNotReadyError(
            f"official evaluation locked until {EVALUATION_NOT_BEFORE.isoformat()}"
        )
    status, market, records, journal = _structural_readiness(
        config, evaluated_at
    )
    blockers = [
        value
        for value in status["blockers"]
        if value != "official_result_already_exists"
    ]
    if "official_result_already_exists" in status["blockers"]:
        raise FileExistsError("official breadth gate result already exists")
    if blockers:
        raise GateNotReadyError(f"breadth gate structural blockers: {blockers}")
    payloads = observer.build_decision_payloads(market, records)
    journal_payloads = [value["decision_payload"] for value in journal]
    if payloads != journal_payloads:
        raise GateIntegrityError("breadth decision journal does not replay")
    if len(payloads) != OFFICIAL_DAYS:
        raise GateIntegrityError("breadth decision count differs")
    base = _scenario_metrics(market, payloads, "base")
    stress = _scenario_metrics(market, payloads, "stress_3x_cost")
    candidate_outcomes = [
        value["matured_outcome"]["base"]["breadth_v2"]
        for value in payloads[1:]
    ]
    target_gross = [
        sum(abs(value) for value in payload["research_targets"]["breadth_v2"].values())
        for payload in payloads
    ]
    activity = {
        "valid_signal_decisions": sum(
            value["signal"]["decision_valid"] for value in payloads
        ),
        "active_vintage_decisions": sum(
            value["signal"]["breadth_v2_active"] for value in payloads
        ),
        "invested_days": sum(
            value["gross_exposure"] > 0 for value in candidate_outcomes
        ),
        "maximum_post_net_gross": max(target_gross),
    }
    bootstrap_lower = circular_block_bootstrap_lower(
        [value["net_return"] for value in candidate_outcomes]
    )
    structural = {
        **status,
        "complete_hash_chains_and_raw_lineage": True,
        "same_signal_costs_code_no_refit": True,
    }
    gate = gate_checks(base, stress, activity, structural, bootstrap_lower)
    verdict = (
        "PASS_MANUAL_GUARDED_PAPER_REVIEW"
        if gate["passed"]
        else "FAIL_REJECTED"
    )
    context = verify_gate_lock(config)
    gate_hash = context["gate_protocol"]["gate_protocol_sha256"]
    experiment_key = observer._json_hash(
        {
            "gate_protocol_sha256": gate_hash,
            "gate_lock_sha256": context["gate_lock"]["gate_lock_sha256"],
            "last_market_record_hash": records[-1]["record_hash"],
            "last_journal_hash": journal[-1]["journal_record_hash"],
        }
    )
    prefix = f"liquid-market-breadth-gate-v2-{gate_hash[:12]}-"
    experiment = config.output_root / f"{prefix}{experiment_key[:12]}"
    config.output_root.mkdir(parents=True, exist_ok=True)
    temporary = pathlib.Path(
        tempfile.mkdtemp(prefix=".breadth-forward-gate.", dir=config.output_root)
    )
    try:
        trajectory = {
            "schema_version": SCHEMA_VERSION,
            "gate_protocol_sha256": gate_hash,
            "dates": [value["bar_date"] for value in payloads[1:]],
            "scenarios": {
                scenario: {
                    variant: metrics[variant]["_trajectory"]
                    for variant in VARIANTS
                }
                for scenario, metrics in (
                    ("base", base),
                    ("stress_3x_cost", stress),
                )
            },
        }
        trajectory["content_sha256"] = observer._json_hash(trajectory)
        trajectory_path = temporary / "forward-trajectories.json"
        _atomic_json(trajectory_path, trajectory)
        report = {
            "schema_version": SCHEMA_VERSION,
            "gate_version": GATE_VERSION,
            "created_at": evaluated_at.isoformat(),
            "status": "official_single_run_complete",
            "verdict": verdict,
            "gate_protocol_sha256": gate_hash,
            "gate_protocol_file_sha256": common._sha256(
                config.gate_protocol_path
            ),
            "gate_lock_sha256": context["gate_lock"]["gate_lock_sha256"],
            "gate_lock_file_sha256": common._sha256(config.gate_lock_path),
            "input_evidence": {
                "warmup_records": status["warmup_records"],
                "official_market_records": status["official_market_records"],
                "decision_records": status["decision_records"],
                "mature_outcomes": status["mature_outcomes"],
                "last_market_record_hash": records[-1]["record_hash"],
                "last_journal_hash": journal[-1]["journal_record_hash"],
                "raw_and_hash_chains_verified": True,
                "exact_decision_replay_verified": True,
            },
            "activity": activity,
            "base": {variant: _compact(base[variant]) for variant in VARIANTS},
            "stress_3x_cost": {
                variant: _compact(stress[variant]) for variant in VARIANTS
            },
            "bootstrap": {
                "simulations": forward_protocol.BOOTSTRAP_SIMULATIONS,
                "block_days": forward_protocol.BOOTSTRAP_BLOCK_DAYS,
                "seed": forward_protocol.BOOTSTRAP_SEED,
                "confidence": forward_protocol.BOOTSTRAP_CONFIDENCE,
                "annualized_mean_lower_bound": bootstrap_lower,
            },
            "gate": gate,
            "manual_guarded_paper_review_permitted": gate["passed"],
            "paper_started": False,
            "results_do_not_authorize_orders": True,
            "trajectory": {
                "path": trajectory_path.name,
                "sha256": common._sha256(trajectory_path),
                "content_sha256": trajectory["content_sha256"],
            },
            "research_only": True,
            "credentials_used": False,
            "orders_authorized": False,
            "paper_orders_authorized": False,
            "automatic_promotion": False,
        }
        report["content_sha256"] = observer._json_hash(report)
        report_path = temporary / "report.json"
        _atomic_json(report_path, report)
        manifest = {
            "schema_version": SCHEMA_VERSION,
            "gate_protocol_sha256": gate_hash,
            "gate_lock_sha256": context["gate_lock"]["gate_lock_sha256"],
            "experiment_key": experiment_key,
            "report_sha256": common._sha256(report_path),
            "report_content_sha256": report["content_sha256"],
            "trajectory_sha256": common._sha256(trajectory_path),
            "trajectory_content_sha256": trajectory["content_sha256"],
            "verdict": verdict,
            "orders_authorized": False,
            "paper_orders_authorized": False,
            "automatic_promotion": False,
        }
        manifest["content_sha256"] = observer._json_hash(manifest)
        _atomic_json(temporary / "manifest.json", manifest)
        if experiment.exists():
            raise FileExistsError(f"official breadth gate exists: {experiment}")
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
    parser.add_argument("--gate-protocol", required=True)
    parser.add_argument("--gate-lock", required=True)
    parser.add_argument("--output-root", required=True)
    parser.add_argument("--gate-test", required=True)
    parser.add_argument("--gate-entrypoint", required=True)
    observer._add_paths(parser)


def _config(arguments) -> GateConfig:
    return GateConfig(
        gate_protocol_path=pathlib.Path(arguments.gate_protocol).resolve(),
        gate_lock_path=pathlib.Path(arguments.gate_lock).resolve(),
        output_root=pathlib.Path(arguments.output_root).resolve(),
        gate_test_path=pathlib.Path(arguments.gate_test).resolve(),
        entrypoint_path=pathlib.Path(arguments.gate_entrypoint).resolve(),
        observer_config=observer._config(arguments),
    )


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    protocol_parser = commands.add_parser("write-protocol")
    protocol_parser.add_argument("--gate-protocol", required=True)
    for name in ("freeze-gate", "readiness", "evaluate"):
        child = commands.add_parser(name)
        _add_paths(child)
    return parser


def main(argv=None) -> int:
    arguments = _parser().parse_args(argv)
    if arguments.command == "write-protocol":
        result = write_or_verify_gate_protocol(
            pathlib.Path(arguments.gate_protocol).resolve()
        )
    else:
        config = _config(arguments)
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
