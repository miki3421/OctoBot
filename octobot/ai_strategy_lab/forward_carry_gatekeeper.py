"""Automatic fail-closed, orderless gatekeeper for frozen Carry V1.1.

The process may publish status before readiness, but it cannot build labels or
fit a model.  Once readiness passes it binds one immutable journal prefix to
each official phase, so an operational retry cannot silently move the sample.
"""

from __future__ import annotations

import argparse
import datetime
import fcntl
import hashlib
import json
import os
import pathlib
import shutil
import tempfile
import typing

from octobot.ai_strategy_lab import forward_carry_dataset
from octobot.ai_strategy_lab import forward_carry_evaluator_v1
from octobot.ai_strategy_lab import forward_evidence


SCHEMA_VERSION = 1
GATEKEEPER_VERSION = "kucoin_forward_carry_gatekeeper_v1"
MAXIMUM_INPUT_AGE_SECONDS = 45 * 60
EXPECTED_EVIDENCE_CHECKS = {
    "journal_has_records",
    "symbol_count_exact",
    "minimum_span_reached",
    "coverage_reached",
    "maximum_gap_respected",
    "settled_funding_reached",
}
HARD_OPERATIONAL_CHECKS = {
    "protocol",
    "safety",
    "collector",
    "evidence_fresh",
    "thresholds_frozen",
    "journal_prefix_available",
}


class GatekeeperError(RuntimeError):
    """Raised when an operational or integrity gate fails closed."""


class GatekeeperBusy(GatekeeperError):
    """Raised when another gatekeeper instance owns the exclusive lock."""


def _json_hash(value: object) -> str:
    return hashlib.sha256(
        json.dumps(value, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()


def _sha256(path_value: str | pathlib.Path) -> str:
    digest = hashlib.sha256()
    with pathlib.Path(path_value).open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _parse_utc(value: object) -> datetime.datetime | None:
    if not isinstance(value, str) or not value:
        return None
    try:
        result = datetime.datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    if result.tzinfo is None:
        return None
    return result.astimezone(datetime.timezone.utc)


def _read_json(path_value: str | pathlib.Path) -> dict:
    path = pathlib.Path(path_value)
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise GatekeeperError(f"expected a JSON object: {path}")
    return value


def _atomic_json(path: pathlib.Path, value: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + ".tmp")
    with temporary.open("w", encoding="utf-8") as stream:
        json.dump(value, stream, indent=2, sort_keys=True)
        stream.write("\n")
        stream.flush()
        os.fsync(stream.fileno())
    temporary.replace(path)


def _write_hashed_json(path: pathlib.Path, value: dict, hash_key: str) -> dict:
    payload = dict(value)
    payload[hash_key] = _json_hash(payload)
    _atomic_json(path, payload)
    persisted = _read_json(path)
    claimed = persisted.pop(hash_key, None)
    if claimed != _json_hash(persisted):
        raise GatekeeperError(f"persisted hash mismatch: {path}")
    persisted[hash_key] = claimed
    return persisted


def _load_hashed_json(path: pathlib.Path, hash_key: str) -> dict:
    value = _read_json(path)
    claimed = value.pop(hash_key, None)
    if claimed != _json_hash(value):
        raise GatekeeperError(f"hash mismatch: {path}")
    value[hash_key] = claimed
    return value


class GatekeeperConfig(typing.NamedTuple):
    protocol_path: pathlib.Path
    journal_path: pathlib.Path
    evidence_path: pathlib.Path
    market_health_path: pathlib.Path
    archive_root: pathlib.Path
    state_root: pathlib.Path
    maximum_input_age_seconds: int = MAXIMUM_INPUT_AGE_SECONDS

    def resolved(self) -> "GatekeeperConfig":
        return GatekeeperConfig(
            protocol_path=self.protocol_path.resolve(),
            journal_path=self.journal_path.resolve(),
            evidence_path=self.evidence_path.resolve(),
            market_health_path=self.market_health_path.resolve(),
            archive_root=self.archive_root.resolve(),
            state_root=self.state_root.resolve(),
            maximum_input_age_seconds=self.maximum_input_age_seconds,
        )


def run_once(
    config: GatekeeperConfig,
    *,
    now: datetime.datetime | None = None,
) -> dict:
    """Run one idempotent state transition and publish an atomic status."""
    settings = config.resolved()
    now_utc = now or datetime.datetime.now(datetime.timezone.utc)
    if now_utc.tzinfo is None:
        raise ValueError("gatekeeper time must be timezone-aware")
    now_utc = now_utc.astimezone(datetime.timezone.utc)
    settings.state_root.mkdir(parents=True, exist_ok=True)
    lock_path = settings.state_root / "runner.lock"
    with lock_path.open("a+", encoding="utf-8") as lock_stream:
        try:
            fcntl.flock(
                lock_stream.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB
            )
        except BlockingIOError as error:
            raise GatekeeperBusy("forward Carry gatekeeper is already active") from error
        try:
            return _run_locked(settings, now_utc)
        except Exception as error:  # fail closed and expose only operational detail
            status = _base_status(now_utc)
            status.update(
                {
                    "healthy": False,
                    "phase": "BLOCKED_OPERATIONAL",
                    "phase_detail": f"{type(error).__name__}: {error}",
                    "blockers": [
                        {
                            "id": "operational_integrity",
                            "detail": str(error),
                        }
                    ],
                }
            )
            _atomic_json(settings.state_root / "status.json", status)
            return status


def _run_locked(settings: GatekeeperConfig, now_utc: datetime.datetime) -> dict:
    protocol = forward_carry_evaluator_v1.load_protocol(settings.protocol_path)
    evidence = _read_json(settings.evidence_path)
    health = _read_json(settings.market_health_path)
    checks = _readiness_checks(settings, protocol, evidence, health, now_utc)
    blockers = [value for value in checks if value["passed"] is not True]
    hard_blockers = [
        value
        for value in blockers
        if value["id"] in HARD_OPERATIONAL_CHECKS
    ]
    development_latch = _load_optional_latch(settings, "development")
    confirmation_latch = _load_optional_latch(settings, "confirmation")
    for latch in (development_latch, confirmation_latch):
        if (
            latch is not None
            and latch.get("protocol_sha256") != protocol["protocol_sha256"]
        ):
            raise GatekeeperError("latched Carry protocol differs from V1.1")
    if confirmation_latch is not None:
        status = _latched_status(
            now_utc,
            evidence,
            checks,
            development_latch,
            confirmation_latch,
        )
        _atomic_json(settings.state_root / "status.json", status)
        return status
    if development_latch is not None:
        if development_latch["passed"] is not True:
            status = _latched_status(
                now_utc, evidence, checks, development_latch, None
            )
            _atomic_json(settings.state_root / "status.json", status)
            return status
        confirmation = protocol["validation"]["locked_confirmation"]
        earliest = _parse_utc(confirmation["earliest_open_utc"])
        if earliest is None:
            raise GatekeeperError("invalid confirmation wall-clock gate")
        if now_utc < earliest:
            status = _waiting_status(
                now_utc,
                evidence,
                checks,
                phase="WAITING_CONFIRMATION",
                detail=(
                    "Development passed; confirmation remains sealed until "
                    f"{earliest.isoformat()}."
                ),
                development_latch=development_latch,
            )
            _atomic_json(settings.state_root / "status.json", status)
            return status
        if blockers:
            status = _waiting_status(
                now_utc,
                evidence,
                checks,
                phase=(
                    "BLOCKED_OPERATIONAL" if hard_blockers else "WAITING_CONFIRMATION"
                ),
                detail="Confirmation input is not currently safe to freeze.",
                development_latch=development_latch,
            )
            status["healthy"] = not hard_blockers
            _atomic_json(settings.state_root / "status.json", status)
            return status
        _write_running_status(
            settings,
            now_utc,
            evidence,
            checks,
            "RUNNING_CONFIRMATION",
            development_latch,
        )
        confirmation_latch = _execute_phase(
            settings,
            protocol,
            evidence,
            health,
            phase="confirmation",
            development_latch=development_latch,
            now_utc=now_utc,
        )
        status = _latched_status(
            now_utc,
            evidence,
            checks,
            development_latch,
            confirmation_latch,
        )
        _atomic_json(settings.state_root / "status.json", status)
        return status
    if blockers:
        status = _waiting_status(
            now_utc,
            evidence,
            checks,
            phase=("BLOCKED_OPERATIONAL" if hard_blockers else "WAITING_READINESS"),
            detail=(
                "Input operational integrity failed."
                if hard_blockers
                else "Forward evidence is still accumulating."
            ),
            development_latch=None,
        )
        status["healthy"] = not hard_blockers
        _atomic_json(settings.state_root / "status.json", status)
        return status
    _write_running_status(
        settings,
        now_utc,
        evidence,
        checks,
        "RUNNING_DEVELOPMENT",
        None,
    )
    development_latch = _execute_phase(
        settings,
        protocol,
        evidence,
        health,
        phase="development",
        development_latch=None,
        now_utc=now_utc,
    )
    status = _latched_status(
        now_utc, evidence, checks, development_latch, None
    )
    _atomic_json(settings.state_root / "status.json", status)
    return status


def _readiness_checks(settings, protocol, evidence, health, now_utc):
    source = evidence.get("source_journal", {})
    thresholds = evidence.get("thresholds", {})
    protocol_source = protocol.get("source", {})
    evidence_created = _parse_utc(evidence.get("created_at"))
    health_created = _parse_utc(health.get("last_success_at"))
    expected_thresholds = {
        "minimum_span_days": protocol_source.get("minimum_span_days"),
        "minimum_coverage": protocol_source.get("minimum_coverage"),
        "maximum_gap_minutes": protocol_source.get("maximum_gap_minutes"),
        "minimum_settlements_per_symbol": protocol_source.get(
            "minimum_settled_funding_points_per_symbol"
        ),
        "expected_symbol_count": protocol_source.get("expected_symbols"),
        "interval_minutes": 15,
    }
    evidence_checks = evidence.get("checks", {})
    live_size = settings.journal_path.stat().st_size if settings.journal_path.is_file() else 0
    source_bytes = int(source.get("bytes", 0) or 0)
    source_hash = source.get("sha256")
    return [
        {
            "id": "protocol",
            "passed": True,
            "detail": f"protocol {protocol.get('protocol_sha256', '-')}",
        },
        {
            "id": "safety",
            "passed": (
                protocol.get("research_only") is True
                and protocol.get("orders_authorized") is False
                and protocol.get("paper_orders_authorized") is False
                and protocol.get("automatic_promotion") is False
                and evidence.get("research_only") is True
                and evidence.get("orders_authorized") is False
                and evidence.get("automatic_promotion") is False
                and evidence.get("real_income_authorized") is False
                and health.get("mode") == "observation_only"
                and health.get("public_data_only") is True
                and health.get("credentials_used") is False
                and health.get("orders_authorized") is False
            ),
            "detail": "research-only; paper e real orders disabilitati",
        },
        {
            "id": "collector",
            "passed": (
                health.get("status") == "healthy"
                and health.get("archive_consistent") is True
                and health_created is not None
                and 0
                <= (now_utc - health_created).total_seconds()
                <= settings.maximum_input_age_seconds
            ),
            "detail": health.get("last_success_at", "health assente"),
        },
        {
            "id": "evidence_fresh",
            "passed": (
                evidence_created is not None
                and 0
                <= (now_utc - evidence_created).total_seconds()
                <= settings.maximum_input_age_seconds
            ),
            "detail": evidence.get("created_at", "evidence assente"),
        },
        {
            "id": "thresholds_frozen",
            "passed": thresholds == expected_thresholds,
            "detail": "threshold evidence uguali al protocollo V1.1",
        },
        {
            "id": "journal_prefix_available",
            "passed": (
                source_bytes > 0
                and isinstance(source_hash, str)
                and len(source_hash) == 64
                and live_size >= source_bytes
            ),
            "detail": f"{source_bytes} byte dichiarati; {live_size} disponibili",
        },
        {
            "id": "journal_has_records",
            "passed": evidence_checks.get("journal_has_records") is True,
            "detail": str(evidence.get("journal", {}).get("observed_buckets", 0)),
        },
        {
            "id": "symbol_count_exact",
            "passed": evidence_checks.get("symbol_count_exact") is True,
            "detail": str(evidence.get("journal", {}).get("symbol_count", 0)),
        },
        {
            "id": "coverage_reached",
            "passed": evidence_checks.get("coverage_reached") is True,
            "detail": f"{100 * float(evidence.get('journal', {}).get('coverage', 0)):.3f}%",
        },
        {
            "id": "maximum_gap_respected",
            "passed": evidence_checks.get("maximum_gap_respected") is True,
            "detail": str(evidence.get("journal", {}).get("maximum_gap_seconds", 0)),
        },
        {
            "id": "minimum_span_reached",
            "passed": evidence_checks.get("minimum_span_reached") is True,
            "detail": f"{float(evidence.get('journal', {}).get('covered_span_days', 0)):.3f} giorni",
        },
        {
            "id": "settled_funding_reached",
            "passed": evidence_checks.get("settled_funding_reached") is True,
            "detail": str(
                evidence.get("settled_funding", {}).get("minimum_unique_points", 0)
            ),
        },
        {
            "id": "readiness_latch",
            "passed": (
                evidence.get("strategy_development_ready") is True
                and set(evidence_checks) == EXPECTED_EVIDENCE_CHECKS
                and all(value is True for value in evidence_checks.values())
            ),
            "detail": "all evidence checks must be exactly true",
        },
    ]


def _execute_phase(
    settings,
    protocol,
    evidence,
    health,
    *,
    phase,
    development_latch,
    now_utc,
):
    source_lock = _get_or_create_source_lock(
        settings, protocol, evidence, health, phase=phase, now_utc=now_utc
    )
    journal_hash = source_lock["source_journal"]["sha256"]
    final_name = (
        f"{phase}-{protocol['protocol_sha256'][:12]}-{journal_hash[:12]}"
    )
    final_directory = settings.state_root / "runs" / final_name
    if final_directory.exists():
        return _recover_latch(settings, final_directory, protocol, phase)
    runs_root = settings.state_root / "runs"
    runs_root.mkdir(parents=True, exist_ok=True)
    temporary = pathlib.Path(
        tempfile.mkdtemp(prefix=f".{phase}-tmp-", dir=runs_root)
    ).resolve()
    try:
        journal = temporary / "market-journal.jsonl"
        _copy_prefix(
            settings.journal_path,
            journal,
            int(source_lock["source_journal"]["bytes"]),
            journal_hash,
        )
        _verify_archive_tail(journal, settings.archive_root)
        original_evidence = source_lock["evidence"]
        evidence_config = forward_evidence.ForwardEvidenceConfig(
            **original_evidence["thresholds"]
        )
        recomputed = forward_evidence.evaluate_forward_market_evidence(
            journal, config=evidence_config
        )
        if (
            recomputed.get("strategy_development_ready") is not True
            or recomputed.get("checks") != original_evidence.get("checks")
            or recomputed.get("thresholds") != original_evidence.get("thresholds")
            or recomputed.get("source_journal", {}).get("sha256") != journal_hash
        ):
            raise GatekeeperError("frozen journal readiness does not reproduce")
        evidence_path = temporary / "evidence.json"
        _atomic_json(evidence_path, recomputed)
        protocol_copy = temporary / "protocol.json"
        shutil.copyfile(settings.protocol_path, protocol_copy)
        forward_carry_evaluator_v1.load_protocol(protocol_copy)
        validation = protocol["validation"]
        if phase == "development":
            entry_start = None
            entry_end = validation["development"][
                "last_entry_exclusive_utc"
            ]
        else:
            confirmation = validation["locked_confirmation"]
            entry_start = confirmation["entry_start_utc"]
            entry_end = confirmation["entry_end_exclusive_utc"]
        horizons = tuple(
            sorted(
                {
                    int(protocol["dataset"]["primary_horizon_hours"]),
                    *(
                        int(value)
                        for value in protocol["dataset"][
                            "diagnostic_horizons_hours"
                        ]
                    ),
                }
            )
        )
        dataset_value = forward_carry_dataset.build_forward_carry_dataset(
            journal,
            evidence_path,
            horizon_hours=horizons,
            leg_quote=float(protocol["dataset"]["leg_quote_usdt"]),
            entry_start_utc=entry_start,
            entry_end_exclusive_utc=entry_end,
            evidence_config=evidence_config,
        )
        dataset_path = temporary / f"{phase}-dataset.npz"
        dataset_manifest = forward_carry_dataset.save_forward_carry_dataset(
            dataset_value, dataset_path
        )
        expected_window = {
            "start_inclusive_utc": entry_start,
            "end_exclusive_utc": entry_end,
        }
        if dataset_manifest.get("entry_window") != expected_window:
            raise GatekeeperError("Carry dataset entry window differs")
        forward_carry_dataset.load_forward_carry_dataset(dataset_path)
        if phase == "development":
            report_path = (
                forward_carry_evaluator_v1.evaluate_development_files(
                    protocol_path=protocol_copy,
                    dataset_path=dataset_path,
                    evidence_path=evidence_path,
                    journal_path=journal,
                    output_directory=temporary,
                )
            )
            gate_name = "development_gate"
        else:
            if development_latch is None or development_latch["passed"] is not True:
                raise GatekeeperError("confirmation lacks a passing development latch")
            development_directory = _latch_directory(settings, development_latch)
            report_path = (
                forward_carry_evaluator_v1.evaluate_confirmation_files(
                    protocol_path=protocol_copy,
                    dataset_path=dataset_path,
                    evidence_path=evidence_path,
                    journal_path=journal,
                    development_report_path=(
                        development_directory / "development-report.json"
                    ),
                    model_path=development_directory / "frozen-model.json",
                    output_directory=temporary,
                )
            )
            gate_name = "confirmation_gate"
        report = _load_hashed_json(report_path, "report_sha256")
        if (
            report.get("phase") != phase
            or report.get("protocol_sha256") != protocol["protocol_sha256"]
            or report.get("orders_authorized") is not False
            or report.get("paper_orders_authorized") is not False
            or report.get("automatic_promotion") is not False
            or not isinstance(report.get(gate_name, {}).get("passed"), bool)
        ):
            raise GatekeeperError(f"invalid official {phase} report")
        passed = report[gate_name]["passed"] is True
        manifest = _run_manifest(
            temporary,
            phase=phase,
            protocol=protocol,
            source_lock=source_lock,
            report=report,
            passed=passed,
            dataset_manifest=dataset_manifest,
        )
        _write_hashed_json(
            temporary / "run-manifest.json", manifest, "manifest_sha256"
        )
        if final_directory.exists():
            raise GatekeeperError("official Carry run directory appeared concurrently")
        temporary.replace(final_directory)
        temporary = None
        return _write_latch(
            settings,
            phase=phase,
            run_directory=final_directory,
            report=report,
            passed=passed,
            protocol=protocol,
            source_lock=source_lock,
        )
    finally:
        if temporary is not None and temporary.exists():
            _remove_temporary(settings.state_root / "runs", temporary, phase)


def _get_or_create_source_lock(
    settings, protocol, evidence, health, *, phase, now_utc
):
    path = settings.state_root / f"{phase}-source-lock.json"
    if path.exists():
        value = _load_hashed_json(path, "source_lock_sha256")
        if (
            value.get("phase") != phase
            or value.get("protocol_sha256") != protocol["protocol_sha256"]
            or value.get("orders_authorized") is not False
        ):
            raise GatekeeperError(f"invalid {phase} source lock")
        return value
    source = evidence.get("source_journal", {})
    value = {
        "schema_version": SCHEMA_VERSION,
        "gatekeeper_version": GATEKEEPER_VERSION,
        "phase": phase,
        "created_at": now_utc.isoformat(),
        "protocol_sha256": protocol["protocol_sha256"],
        "source_journal": {
            "bytes": int(source["bytes"]),
            "sha256": source["sha256"],
        },
        "evidence": evidence,
        "market_health_record_hash": health.get("record_hash"),
        "archive_consistent": health.get("archive_consistent") is True,
        "research_only": True,
        "orders_authorized": False,
        "paper_orders_authorized": False,
        "automatic_promotion": False,
    }
    return _write_hashed_json(path, value, "source_lock_sha256")


def _copy_prefix(source, destination, byte_count, expected_sha256):
    if byte_count <= 0 or len(expected_sha256) != 64:
        raise GatekeeperError("invalid journal prefix identity")
    digest = hashlib.sha256()
    remaining = byte_count
    with pathlib.Path(source).open("rb") as input_stream, destination.open("xb") as output:
        while remaining:
            chunk = input_stream.read(min(1024 * 1024, remaining))
            if not chunk:
                raise GatekeeperError("live journal is shorter than frozen prefix")
            output.write(chunk)
            digest.update(chunk)
            remaining -= len(chunk)
        output.flush()
        os.fsync(output.fileno())
    if destination.stat().st_size != byte_count:
        raise GatekeeperError("frozen journal prefix size mismatch")
    if digest.hexdigest() != expected_sha256:
        raise GatekeeperError("frozen journal prefix SHA-256 mismatch")
    with destination.open("rb") as stream:
        stream.seek(-1, os.SEEK_END)
        if stream.read(1) != b"\n":
            raise GatekeeperError("frozen journal prefix ends mid-record")


def _verify_archive_tail(journal, archive_root):
    last = None
    with pathlib.Path(journal).open("r", encoding="utf-8") as stream:
        for line in stream:
            if line.strip():
                last = json.loads(line)
    if last is None:
        raise GatekeeperError("frozen journal is empty")
    record_hash = last.get("record_hash")
    matches = list(pathlib.Path(archive_root).glob(f"*-{record_hash}.json"))
    if len(matches) != 1 or _read_json(matches[0]) != last:
        raise GatekeeperError("frozen journal tail does not match archive")


def _run_manifest(directory, *, phase, protocol, source_lock, report, passed, dataset_manifest):
    files = {}
    for path in sorted(directory.iterdir()):
        if path.is_file() and path.name != "run-manifest.json":
            files[path.name] = {
                "bytes": path.stat().st_size,
                "sha256": (
                    source_lock["source_journal"]["sha256"]
                    if path.name == "market-journal.jsonl"
                    else _sha256(path)
                ),
            }
    return {
        "schema_version": SCHEMA_VERSION,
        "gatekeeper_version": GATEKEEPER_VERSION,
        "phase": phase,
        "protocol_sha256": protocol["protocol_sha256"],
        "source_lock_sha256": source_lock["source_lock_sha256"],
        "journal_prefix_bytes": source_lock["source_journal"]["bytes"],
        "journal_sha256": source_lock["source_journal"]["sha256"],
        "dataset_sha256": dataset_manifest["output"]["sha256"],
        "dataset_manifest_sha256": dataset_manifest["manifest_sha256"],
        "report_sha256": report["report_sha256"],
        "passed": passed,
        "files": files,
        "research_only": True,
        "orders_authorized": False,
        "paper_orders_authorized": False,
        "automatic_promotion": False,
    }


def _write_latch(
    settings, *, phase, run_directory, report, passed, protocol, source_lock
):
    path = settings.state_root / f"{phase}-latch.json"
    value = {
        "schema_version": SCHEMA_VERSION,
        "gatekeeper_version": GATEKEEPER_VERSION,
        "phase": phase,
        "protocol_sha256": protocol["protocol_sha256"],
        "source_lock_sha256": source_lock["source_lock_sha256"],
        "run_directory": run_directory.name,
        "report_sha256": report["report_sha256"],
        "passed": passed,
        "research_only": True,
        "orders_authorized": False,
        "paper_orders_authorized": False,
        "automatic_promotion": False,
    }
    if path.exists():
        existing = _load_hashed_json(path, "latch_sha256")
        expected = dict(value)
        expected["latch_sha256"] = _json_hash(expected)
        if existing != expected:
            raise GatekeeperError(f"official {phase} latch already differs")
        return existing
    return _write_hashed_json(path, value, "latch_sha256")


def _recover_latch(settings, directory, protocol, phase):
    manifest = _load_hashed_json(
        directory / "run-manifest.json", "manifest_sha256"
    )
    report_path = directory / f"{phase}-report.json"
    report = _load_hashed_json(report_path, "report_sha256")
    if (
        manifest.get("phase") != phase
        or manifest.get("protocol_sha256") != protocol["protocol_sha256"]
        or manifest.get("report_sha256") != report["report_sha256"]
        or manifest.get("passed") is not report[f"{phase}_gate"]["passed"]
    ):
        raise GatekeeperError(f"cannot recover official {phase} run")
    source_lock = _load_hashed_json(
        settings.state_root / f"{phase}-source-lock.json",
        "source_lock_sha256",
    )
    return _write_latch(
        settings,
        phase=phase,
        run_directory=directory,
        report=report,
        passed=manifest["passed"],
        protocol=protocol,
        source_lock=source_lock,
    )


def _load_optional_latch(settings, phase):
    path = settings.state_root / f"{phase}-latch.json"
    if not path.exists():
        return None
    latch = _load_hashed_json(path, "latch_sha256")
    if (
        latch.get("phase") != phase
        or latch.get("orders_authorized") is not False
        or latch.get("paper_orders_authorized") is not False
        or latch.get("automatic_promotion") is not False
        or not isinstance(latch.get("passed"), bool)
    ):
        raise GatekeeperError(f"invalid {phase} latch")
    directory = _latch_directory(settings, latch)
    manifest = _load_hashed_json(
        directory / "run-manifest.json", "manifest_sha256"
    )
    if (
        manifest.get("report_sha256") != latch.get("report_sha256")
        or manifest.get("passed") is not latch.get("passed")
        or manifest.get("protocol_sha256") != latch.get("protocol_sha256")
    ):
        raise GatekeeperError(f"{phase} latch does not match run manifest")
    return latch


def _latch_directory(settings, latch):
    name = latch.get("run_directory")
    if not isinstance(name, str) or not name or pathlib.Path(name).name != name:
        raise GatekeeperError("invalid latched run directory")
    directory = (settings.state_root / "runs" / name).resolve()
    if directory.parent != (settings.state_root / "runs").resolve() or not directory.is_dir():
        raise GatekeeperError("latched run directory is unavailable")
    return directory


def _remove_temporary(runs_root, path, phase):
    root = pathlib.Path(runs_root).resolve()
    target = pathlib.Path(path).resolve()
    if (
        target.parent != root
        or not target.name.startswith(f".{phase}-tmp-")
    ):
        raise GatekeeperError("refusing unsafe gatekeeper temporary cleanup")
    shutil.rmtree(target)


def _base_status(now_utc):
    return {
        "schema_version": SCHEMA_VERSION,
        "gatekeeper_version": GATEKEEPER_VERSION,
        "updated_at": now_utc.isoformat(),
        "healthy": True,
        "research_only": True,
        "orders_authorized": False,
        "paper_orders_authorized": False,
        "automatic_promotion": False,
        "real_income_authorized": False,
        "blockers": [],
        "development": None,
        "confirmation": None,
    }


def _evidence_progress(evidence):
    progress = evidence.get("readiness_progress", {})
    journal = evidence.get("journal", {})
    settled = evidence.get("settled_funding", {})
    return {
        "progress_pct": 100 * float(progress.get("overall_minimum_progress", 0)),
        "earliest_readiness_utc": progress.get("earliest_span_ready_at_utc"),
        "span_days": float(journal.get("covered_span_days", 0)),
        "coverage_pct": 100 * float(journal.get("coverage", 0)),
        "funding_points_minimum": int(settled.get("minimum_unique_points", 0)),
    }


def _waiting_status(
    now_utc,
    evidence,
    checks,
    *,
    phase,
    detail,
    development_latch,
):
    status = _base_status(now_utc)
    status.update(
        {
            "phase": phase,
            "phase_detail": detail,
            "checks": checks,
            "blockers": [value for value in checks if value["passed"] is not True],
            **_evidence_progress(evidence),
            "development": development_latch,
            "artifacts_created": development_latch is not None,
        }
    )
    if development_latch is not None:
        status["official_verdict"] = (
            "DEVELOPMENT_PASS"
            if development_latch.get("passed") is True
            else "DEVELOPMENT_FAIL"
        )
    return status


def _write_running_status(
    settings, now_utc, evidence, checks, phase, development_latch
):
    status = _waiting_status(
        now_utc,
        evidence,
        checks,
        phase=phase,
        detail="Official one-shot evaluation is running.",
        development_latch=development_latch,
    )
    status["blockers"] = []
    status["artifacts_created"] = True
    _atomic_json(settings.state_root / "status.json", status)


def _latched_status(
    now_utc, evidence, checks, development_latch, confirmation_latch
):
    status = _base_status(now_utc)
    if confirmation_latch is not None:
        phase = "COMPLETE"
        detail = (
            "Confirmation PASS; only manual orderless-shadow review is eligible."
            if confirmation_latch["passed"]
            else "Confirmation FAIL; Carry V1.1 is rejected."
        )
        verdict = "CONFIRMATION_PASS" if confirmation_latch["passed"] else "CONFIRMATION_FAIL"
    elif development_latch["passed"]:
        phase = "WAITING_CONFIRMATION"
        detail = "Development PASS; confirmation remains wall-clock sealed."
        verdict = "DEVELOPMENT_PASS"
    else:
        phase = "COMPLETE"
        detail = "Development FAIL; confirmation remains permanently sealed."
        verdict = "DEVELOPMENT_FAIL"
    status.update(
        {
            "phase": phase,
            "phase_detail": detail,
            "official_verdict": verdict,
            "checks": checks,
            "blockers": [],
            **_evidence_progress(evidence),
            "development": development_latch,
            "confirmation": confirmation_latch,
            "artifacts_created": True,
        }
    )
    return status


def _parse_args():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--protocol", required=True)
    parser.add_argument("--journal", required=True)
    parser.add_argument("--evidence", required=True)
    parser.add_argument("--market-health", required=True)
    parser.add_argument("--archive-root", required=True)
    parser.add_argument("--state-root", required=True)
    return parser.parse_args()


def main() -> int:
    arguments = _parse_args()
    status = run_once(
        GatekeeperConfig(
            protocol_path=pathlib.Path(arguments.protocol),
            journal_path=pathlib.Path(arguments.journal),
            evidence_path=pathlib.Path(arguments.evidence),
            market_health_path=pathlib.Path(arguments.market_health),
            archive_root=pathlib.Path(arguments.archive_root),
            state_root=pathlib.Path(arguments.state_root),
        )
    )
    print(json.dumps(status, indent=2, sort_keys=True))
    return 0 if status.get("healthy") is True else 1


if __name__ == "__main__":
    raise SystemExit(main())
