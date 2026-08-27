"""Read-only Carry V1.1 gate summary for local status interfaces."""

from __future__ import annotations

import datetime
import hashlib
import json


PROTOCOL_VERSION = "kucoin_spot_perpetual_forward_carry_v1_1"
PROTOCOL_SHA256 = (
    "f00225920e30dcb6bdd48be4be03487e78ee451cf076974e1340dc3bc3d5cff4"
)
EVIDENCE_MAXIMUM_AGE_SECONDS = 45 * 60


def _json_hash(value: object) -> str:
    return hashlib.sha256(
        json.dumps(value, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()


def _parse_utc(value: object) -> datetime.datetime | None:
    if not isinstance(value, str) or not value:
        return None
    try:
        parsed = datetime.datetime.fromisoformat(
            value.replace("Z", "+00:00")
        )
    except ValueError:
        return None
    if parsed.tzinfo is None:
        return None
    return parsed.astimezone(datetime.timezone.utc)


def _number(value: object, default: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _integer(value: object, default: int = 0) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _remaining_label(
    target: datetime.datetime | None,
    now: datetime.datetime,
) -> str:
    if target is None:
        return "data non disponibile"
    seconds = max(0, int((target - now).total_seconds()))
    if seconds == 0:
        return "requisito temporale raggiunto"
    days, remainder = divmod(seconds, 86_400)
    hours = remainder // 3_600
    return f"circa {days}g {hours}h"


def protocol_status(
    protocol: dict,
    *,
    expected_sha256: str = PROTOCOL_SHA256,
) -> dict:
    """Verify the content-addressed, orderless V1.1 protocol."""
    if not protocol:
        return {
            "valid": False,
            "claimed_sha256": None,
            "short_sha256": "-",
            "confirmation_at": None,
            "detail": "protocollo Carry V1.1 non disponibile",
        }
    claimed = protocol.get("protocol_sha256")
    unsigned = {
        key: value
        for key, value in protocol.items()
        if key != "protocol_sha256"
    }
    computed = _json_hash(unsigned)
    confirmation = protocol.get("validation", {}).get(
        "locked_confirmation", {}
    )
    safety = (
        protocol.get("research_only") is True
        and protocol.get("orders_authorized") is False
        and protocol.get("paper_orders_authorized") is False
        and protocol.get("automatic_promotion") is False
        and protocol.get("results") is None
    )
    valid = (
        protocol.get("protocol_version") == PROTOCOL_VERSION
        and claimed == expected_sha256
        and computed == expected_sha256
        and safety
    )
    if valid:
        detail = f"V1.1 verificato · {claimed[:12]}…"
    elif claimed != expected_sha256:
        detail = "hash protocollo inatteso o file non ufficiale"
    elif computed != claimed:
        detail = "contenuto protocollo modificato dopo il congelamento"
    else:
        detail = "invarianti research-only del protocollo non valide"
    return {
        "valid": valid,
        "claimed_sha256": claimed,
        "short_sha256": (
            f"{claimed[:12]}…" if isinstance(claimed, str) else "-"
        ),
        "confirmation_at": confirmation.get("earliest_open_utc"),
        "detail": detail,
    }


def readiness_summary(
    evidence: dict,
    market_health: dict,
    frozen_protocol: dict,
    *,
    now: datetime.datetime | None = None,
) -> dict:
    """Translate raw evidence gates into a stable dashboard view model."""
    now_utc = now or datetime.datetime.now(datetime.timezone.utc)
    if now_utc.tzinfo is None:
        raise ValueError("Carry dashboard time must be timezone-aware")
    now_utc = now_utc.astimezone(datetime.timezone.utc)
    journal = evidence.get("journal", {})
    thresholds = evidence.get("thresholds", {})
    audited_checks = evidence.get("checks", {})
    progress = evidence.get("readiness_progress", {})
    settled = evidence.get("settled_funding", {})
    evidence_created = _parse_utc(evidence.get("created_at"))
    evidence_age = (
        (now_utc - evidence_created).total_seconds()
        if evidence_created is not None
        else None
    )
    collector_last = _parse_utc(market_health.get("last_success_at"))
    collector_age = (
        (now_utc - collector_last).total_seconds()
        if collector_last is not None
        else None
    )
    collector_healthy = (
        market_health.get("status") == "healthy"
        and market_health.get("archive_consistent") is True
        and market_health.get("orders_authorized") is False
        and collector_age is not None
        and 0 <= collector_age <= EVIDENCE_MAXIMUM_AGE_SECONDS
    )
    evidence_fresh = (
        evidence_age is not None
        and 0 <= evidence_age <= EVIDENCE_MAXIMUM_AGE_SECONDS
    )
    safety_locked = (
        evidence.get("mode") == "forward_evidence_only"
        and evidence.get("orders_authorized") is False
        and evidence.get("automatic_promotion") is False
        and evidence.get("real_income_authorized") is False
    )
    span_days = _number(journal.get("covered_span_days"))
    minimum_span_days = _number(thresholds.get("minimum_span_days"))
    coverage_pct = _number(journal.get("coverage")) * 100
    minimum_coverage_pct = _number(
        thresholds.get("minimum_coverage")
    ) * 100
    maximum_gap_minutes = _number(
        journal.get("maximum_gap_seconds")
    ) / 60
    allowed_gap_minutes = _number(
        thresholds.get("maximum_gap_minutes")
    )
    symbol_count = _integer(journal.get("symbol_count"))
    expected_symbols = _integer(
        thresholds.get("expected_symbol_count")
    )
    observed_buckets = _integer(journal.get("observed_buckets"))
    required_buckets = _integer(progress.get("required_span_buckets"))
    minimum_funding = _integer(settled.get("minimum_unique_points"))
    required_funding = _integer(
        thresholds.get("minimum_settlements_per_symbol")
    )
    remaining_observed_buckets = _integer(
        progress.get("remaining_observed_buckets_at_minimum_span")
    )
    checks = [
        {
            "id": "protocol",
            "label": "Protocollo congelato",
            "passed": frozen_protocol.get("valid") is True,
            "detail": frozen_protocol.get("detail", "non disponibile"),
        },
        {
            "id": "collector",
            "label": "Collector e archivio",
            "passed": collector_healthy,
            "detail": (
                f"{market_health.get('status', 'non disponibile')} · "
                f"ultimo bucket "
                f"{market_health.get('bucket_start_utc', '-')}"
            ),
        },
        {
            "id": "evidence_fresh",
            "label": "Audit evidence aggiornato",
            "passed": evidence_fresh,
            "detail": evidence.get("created_at", "file non disponibile"),
        },
        {
            "id": "journal_has_records",
            "label": "Journal osservato",
            "passed": audited_checks.get("journal_has_records") is True,
            "detail": f"{observed_buckets} bucket validi",
        },
        {
            "id": "symbol_count_exact",
            "label": "Universo simboli",
            "passed": audited_checks.get("symbol_count_exact") is True,
            "detail": f"{symbol_count} / {expected_symbols} mercati",
        },
        {
            "id": "coverage_reached",
            "label": "Copertura minima",
            "passed": audited_checks.get("coverage_reached") is True,
            "detail": (
                f"{coverage_pct:.2f}% osservata · "
                f"minimo {minimum_coverage_pct:.2f}%"
            ),
        },
        {
            "id": "maximum_gap_respected",
            "label": "Continuità temporale",
            "passed": (
                audited_checks.get("maximum_gap_respected") is True
            ),
            "detail": (
                f"gap massimo {maximum_gap_minutes:.0f}m · "
                f"limite {allowed_gap_minutes:.0f}m"
            ),
        },
        {
            "id": "minimum_span_reached",
            "label": "Durata osservazione",
            "passed": audited_checks.get("minimum_span_reached") is True,
            "detail": (
                f"{span_days:.2f} / {minimum_span_days:.0f} giorni · "
                f"mancano almeno {remaining_observed_buckets} "
                f"bucket validi"
            ),
        },
        {
            "id": "settled_funding_reached",
            "label": "Funding settlement",
            "passed": (
                audited_checks.get("settled_funding_reached") is True
            ),
            "detail": (
                f"{minimum_funding} / {required_funding} per simbolo · "
                f"ne mancano almeno "
                f"{_integer(progress.get('minimum_remaining_settlements'))}"
            ),
        },
        {
            "id": "safety",
            "label": "Blocco operativo",
            "passed": safety_locked,
            "detail": "dataset, modello e ordini non autorizzati",
        },
    ]
    blockers = [value for value in checks if not value["passed"]]
    hard_failure = any(
        value["id"] in {"protocol", "collector", "evidence_fresh", "safety"}
        and not value["passed"]
        for value in checks
    )
    audited_ready = evidence.get("strategy_development_ready") is True
    ready = audited_ready and not blockers
    if ready:
        state = "PRONTO PER SVILUPPO"
        color = "success"
        state_detail = "Tutti i gate forward risultano verificati."
    elif hard_failure:
        state = "BLOCCATO — CONTROLLO OPERATIVO"
        color = "danger"
        state_detail = (
            f"{len(blockers)} controllo/i impediscono qualsiasi esecuzione."
        )
    else:
        state = "IN RACCOLTA — BLOCCATO"
        color = "warning"
        state_detail = (
            f"{len(blockers)} requisito/i quantitativi ancora incompleti."
        )
    estimated = _parse_utc(progress.get("earliest_span_ready_at_utc"))
    progress_fraction = min(
        1.0, max(0.0, _number(progress.get("overall_minimum_progress")))
    )
    return {
        "available": bool(evidence or market_health or frozen_protocol),
        "state": state,
        "state_detail": state_detail,
        "color": color,
        "ready": ready,
        "progress_pct": progress_fraction * 100,
        "estimated_at": estimated.isoformat() if estimated else None,
        "estimated_remaining": _remaining_label(estimated, now_utc),
        "confirmation_at": frozen_protocol.get("confirmation_at"),
        "protocol_sha256": frozen_protocol.get("short_sha256", "-"),
        "checks": checks,
        "blockers": blockers,
        "collector_status": market_health.get("status", "non disponibile"),
        "collector_last_success": market_health.get("last_success_at"),
        "symbol_count": symbol_count,
        "expected_symbol_count": expected_symbols,
        "observed_buckets": observed_buckets,
        "required_buckets": required_buckets,
        "minimum_funding": minimum_funding,
        "required_funding": required_funding,
        "coverage_pct": coverage_pct,
        "missing_buckets": _integer(journal.get("missing_buckets")),
        "span_days": span_days,
        "minimum_span_days": minimum_span_days,
        "maximum_gap_minutes": maximum_gap_minutes,
        "allowed_gap_minutes": allowed_gap_minutes,
        "evidence_created_at": evidence.get("created_at"),
        "orders_authorized": False,
    }
