"""Fail-closed readiness audit for forward KuCoin market observations."""

from __future__ import annotations

import dataclasses
import datetime
import hashlib
import math
import pathlib

from octobot.ai_strategy_lab import microstructure as microstructure_module


EVIDENCE_SCHEMA_VERSION = 1


@dataclasses.dataclass(frozen=True)
class ForwardEvidenceConfig:
    interval_minutes: int = 15
    minimum_span_days: float = 60.0
    minimum_coverage: float = 0.95
    maximum_gap_minutes: int = 60
    minimum_settlements_per_symbol: int = 171
    expected_symbol_count: int = 19

    def validate(self) -> None:
        if self.interval_minutes < 1:
            raise ValueError("evidence interval must be positive")
        if self.minimum_span_days <= 0:
            raise ValueError("minimum evidence span must be positive")
        if not 0 < self.minimum_coverage <= 1:
            raise ValueError("minimum coverage must be in (0, 1]")
        if self.maximum_gap_minutes < self.interval_minutes:
            raise ValueError("maximum gap cannot be shorter than interval")
        if self.minimum_settlements_per_symbol < 1:
            raise ValueError("minimum settled funding count must be positive")
        if self.expected_symbol_count < 1:
            raise ValueError("expected symbol count must be positive")


def evaluate_forward_market_evidence(
    journal_path: str | pathlib.Path,
    *,
    config: ForwardEvidenceConfig | None = None,
) -> dict:
    """Audit journal integrity and readiness without fitting a strategy."""
    evidence_config = config or ForwardEvidenceConfig()
    evidence_config.validate()
    path = pathlib.Path(journal_path).resolve()
    records = microstructure_module.load_microstructure_records(path)
    report = _summarize(records, evidence_config)
    report["created_at"] = datetime.datetime.now(
        datetime.timezone.utc
    ).isoformat()
    report["source_journal"] = {
        "path": str(path),
        "exists": path.exists(),
        "bytes": path.stat().st_size if path.exists() else 0,
        "sha256": _sha256(path) if path.exists() else None,
    }
    return report


def _summarize(records, config):
    if not records:
        return _empty_report(config)
    interval_seconds = config.interval_minutes * 60
    buckets = [
        datetime.datetime.fromisoformat(record["bucket_start_utc"])
        for record in records
    ]
    if any(
        int(bucket.timestamp()) % (config.interval_minutes * 60)
        for bucket in buckets
    ):
        raise ValueError("forward journal bucket is not UTC interval-aligned")
    if any(
        int(record.get("interval_minutes", -1))
        != config.interval_minutes
        for record in records
    ):
        raise ValueError("forward journal interval changed")
    universes = [set(record.get("symbols", {})) for record in records]
    reference_universe = universes[0]
    if any(universe != reference_universe for universe in universes):
        raise ValueError("forward journal symbol universe changed")

    elapsed_seconds = (buckets[-1] - buckets[0]).total_seconds()
    expected_buckets = int(elapsed_seconds // interval_seconds) + 1
    if not math.isclose(
        elapsed_seconds % interval_seconds, 0.0, abs_tol=1e-6
    ):
        raise ValueError("forward journal bucket is not interval-aligned")
    observed_buckets = len(records)
    missing_buckets = expected_buckets - observed_buckets
    if missing_buckets < 0:
        raise ValueError("forward journal contains excess buckets")
    coverage = observed_buckets / expected_buckets
    gap_seconds = [
        int((current - previous).total_seconds())
        for previous, current in zip(buckets, buckets[1:])
    ]
    maximum_gap_seconds = max(gap_seconds, default=0)
    gaps_over_interval = [
        {
            "previous_bucket_utc": previous.isoformat(),
            "current_bucket_utc": current.isoformat(),
            "missing_buckets": (
                int((current - previous).total_seconds())
                // interval_seconds
                - 1
            ),
        }
        for previous, current in zip(buckets, buckets[1:])
        if (current - previous).total_seconds() > interval_seconds
    ]
    settled = {base: {} for base in sorted(reference_universe)}
    for record in records:
        for base, values in record["symbols"].items():
            points = values.get("funding", {}).get(
                "settled_last_24h", []
            )
            if not isinstance(points, list):
                raise ValueError(
                    f"settled funding is invalid in journal for {base}"
                )
            for point in points:
                timestamp = int(point["timestamp_ms"])
                rate = float(point["rate"])
                if timestamp < 0 or not math.isfinite(rate):
                    raise ValueError(
                        f"settled funding is invalid in journal for {base}"
                    )
                previous = settled[base].get(timestamp)
                if previous is not None and previous != rate:
                    raise ValueError(
                        f"settled funding changed for {base} at {timestamp}"
                    )
                settled[base][timestamp] = rate
    settlement_counts = {
        base: len(points) for base, points in settled.items()
    }
    minimum_settlement_count = min(
        settlement_counts.values(), default=0
    )
    required_span_buckets = int(
        math.ceil(
            config.minimum_span_days
            * 24
            * 60
            / config.interval_minutes
        )
    )
    required_observed_buckets = int(
        math.ceil(required_span_buckets * config.minimum_coverage)
    )
    covered_span_days = (
        expected_buckets * interval_seconds / (24 * 3600)
    )
    earliest_span_ready_at = buckets[0] + datetime.timedelta(
        seconds=(required_span_buckets - 1) * interval_seconds
    )
    checks = {
        "journal_has_records": True,
        "symbol_count_exact": (
            len(reference_universe) == config.expected_symbol_count
        ),
        "minimum_span_reached": (
            covered_span_days >= config.minimum_span_days
        ),
        "coverage_reached": coverage >= config.minimum_coverage,
        "maximum_gap_respected": (
            maximum_gap_seconds <= config.maximum_gap_minutes * 60
        ),
        "settled_funding_reached": (
            minimum_settlement_count
            >= config.minimum_settlements_per_symbol
        ),
    }
    ready = all(checks.values())
    return {
        "schema_version": EVIDENCE_SCHEMA_VERSION,
        "research_only": True,
        "mode": "forward_evidence_only",
        "orders_authorized": False,
        "automatic_promotion": False,
        "real_income_authorized": False,
        "strategy_development_ready": ready,
        "checks": checks,
        "thresholds": dataclasses.asdict(config),
        "journal": {
            "first_bucket_utc": buckets[0].isoformat(),
            "last_bucket_utc": buckets[-1].isoformat(),
            "observed_buckets": observed_buckets,
            "expected_buckets": expected_buckets,
            "missing_buckets": missing_buckets,
            "coverage": coverage,
            "covered_span_days": covered_span_days,
            "maximum_gap_seconds": maximum_gap_seconds,
            "gaps_over_interval": gaps_over_interval,
            "symbol_count": len(reference_universe),
            "symbols": sorted(reference_universe),
        },
        "settled_funding": {
            "unique_points_by_symbol": settlement_counts,
            "minimum_unique_points": minimum_settlement_count,
        },
        "readiness_progress": {
            "required_span_buckets": required_span_buckets,
            "required_observed_buckets_at_minimum_coverage": (
                required_observed_buckets
            ),
            "remaining_span_buckets": max(
                0, required_span_buckets - expected_buckets
            ),
            "remaining_observed_buckets_at_minimum_span": max(
                0, required_observed_buckets - observed_buckets
            ),
            "remaining_settlements_by_symbol": {
                base: max(
                    0,
                    config.minimum_settlements_per_symbol - count,
                )
                for base, count in settlement_counts.items()
            },
            "minimum_remaining_settlements": max(
                0,
                config.minimum_settlements_per_symbol
                - minimum_settlement_count,
            ),
            "earliest_span_ready_at_utc": (
                earliest_span_ready_at.isoformat()
            ),
            "span_progress": min(
                1.0, expected_buckets / required_span_buckets
            ),
            "settlement_progress": min(
                1.0,
                minimum_settlement_count
                / config.minimum_settlements_per_symbol,
            ),
            "overall_minimum_progress": min(
                min(1.0, expected_buckets / required_span_buckets),
                min(
                    1.0,
                    minimum_settlement_count
                    / config.minimum_settlements_per_symbol,
                ),
            ),
        },
        "interpretation": (
            "Readiness only permits offline hypothesis development; it does "
            "not prove profitability or authorize shadow, orders, or income."
        ),
    }


def _empty_report(config):
    checks = {
        "journal_has_records": False,
        "symbol_count_exact": False,
        "minimum_span_reached": False,
        "coverage_reached": False,
        "maximum_gap_respected": False,
        "settled_funding_reached": False,
    }
    return {
        "schema_version": EVIDENCE_SCHEMA_VERSION,
        "research_only": True,
        "mode": "forward_evidence_only",
        "orders_authorized": False,
        "automatic_promotion": False,
        "real_income_authorized": False,
        "strategy_development_ready": False,
        "checks": checks,
        "thresholds": dataclasses.asdict(config),
        "journal": {
            "first_bucket_utc": None,
            "last_bucket_utc": None,
            "observed_buckets": 0,
            "expected_buckets": 0,
            "missing_buckets": 0,
            "coverage": 0.0,
            "covered_span_days": 0.0,
            "maximum_gap_seconds": 0,
            "gaps_over_interval": [],
            "symbol_count": 0,
            "symbols": [],
        },
        "settled_funding": {
            "unique_points_by_symbol": {},
            "minimum_unique_points": 0,
        },
        "readiness_progress": {
            "required_span_buckets": int(
                math.ceil(
                    config.minimum_span_days
                    * 24
                    * 60
                    / config.interval_minutes
                )
            ),
            "required_observed_buckets_at_minimum_coverage": int(
                math.ceil(
                    config.minimum_span_days
                    * 24
                    * 60
                    / config.interval_minutes
                    * config.minimum_coverage
                )
            ),
            "remaining_span_buckets": int(
                math.ceil(
                    config.minimum_span_days
                    * 24
                    * 60
                    / config.interval_minutes
                )
            ),
            "remaining_observed_buckets_at_minimum_span": int(
                math.ceil(
                    config.minimum_span_days
                    * 24
                    * 60
                    / config.interval_minutes
                    * config.minimum_coverage
                )
            ),
            "remaining_settlements_by_symbol": {},
            "minimum_remaining_settlements": (
                config.minimum_settlements_per_symbol
            ),
            "earliest_span_ready_at_utc": None,
            "span_progress": 0.0,
            "settlement_progress": 0.0,
            "overall_minimum_progress": 0.0,
        },
        "interpretation": (
            "Readiness only permits offline hypothesis development; it does "
            "not prove profitability or authorize shadow, orders, or income."
        ),
    }


def _sha256(path):
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()
