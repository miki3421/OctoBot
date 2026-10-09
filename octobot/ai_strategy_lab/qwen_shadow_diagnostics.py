"""Read-only operational diagnosis, outside the frozen Qwen scientific bundle.

Reads the public status projection and allowlisted timing events only. No
inference, database, outcome, scheduler, retry, or publication interface.
Work card: work-card-e4f0c070-b3b7-4e4d-9318-89602e956265.
"""
import argparse
import datetime as dt
import importlib.util
import json
import math
from pathlib import Path
import re
import subprocess

_SPEC = importlib.util.spec_from_file_location(
    "_qwen_public_view", Path(__file__).with_name("qwen_shadow_view.py"))
_VIEW = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(_VIEW)
UNITS = {"runner": "qwen-btc-shadow-decide.service", "server": "llama-moe.service"}
MAX_BYTES = 2_000_000


def number(value, limit=600):
    if type(value) not in (int, float) or not math.isfinite(value) or not 0 <= value <= limit:
        raise ValueError("INVALID_TIMING")
    return float(value)


def events(records, role):
    """Discard arbitrary log content; never return messages or model text."""
    if role not in UNITS or len(records) > 10_000:
        raise ValueError("LOG_LIMIT")
    result = []
    for row in records:
        if not isinstance(row, dict) or row.get("_SYSTEMD_UNIT") != UNITS[role]:
            continue
        message = row.get("MESSAGE")
        stamp = row.get("__REALTIME_TIMESTAMP")
        pid, boot = row.get("_PID"), row.get("_BOOT_ID")
        if (not isinstance(message, str) or len(message) > 8192
                or not isinstance(stamp, str) or not re.fullmatch(r"\d{1,18}", stamp)
                or not isinstance(pid, str) or not re.fullmatch(r"\d{1,10}", pid)
                or not isinstance(boot, str) or not re.fullmatch(r"[0-9a-f]{32}", boot)):
            continue
        base = dict(at=int(stamp) / 1_000_000, instance=(boot, pid))
        if role == "runner":
            try:
                payload = json.loads(message)
                if (set(payload) != {"status", "decision", "seconds"}
                        or payload["status"] != "RECORDED"
                        or payload["decision"] not in {"LONG", "SHORT", "NO_PROPOSAL", "MISSING"}):
                    continue
                result.append(dict(base, kind="terminal", missing=payload["decision"] == "MISSING",
                                   seconds=number(payload["seconds"], 60)))
            except (ValueError, TypeError):
                continue
        else:
            task = re.search(r"\bid\s+(\d+)\s+\|\s+task\s+(\d+)\s+\|", message)
            if task and "slot launch_slot_:" in message and "processing task, is_child = 0" in message:
                result.append(dict(base, kind="launch", task=task.group(2)))
            elif task and "slot print_timing:" in message:
                timing = re.search(
                    r"prompt processing, n_tokens\s*=\s*(\d+), progress\s*=\s*([0-9.]+), "
                    r"t\s*=\s*([0-9.]+) s / ([0-9.]+) tokens per second", message)
                if timing:
                    try:
                        if float(timing.group(2)) != 1:
                            continue
                        result.append(dict(base, kind="prompt_complete", task=task.group(2),
                                           seconds=number(float(timing.group(3))),
                                           tokens=int(timing.group(1)),
                                           tokens_per_second=number(float(timing.group(4)), 1_000_000)))
                    except ValueError:
                        continue
            else:
                cancel = re.search(r"\bsrv\s+stop: cancel task, id_task = (\d+)\s*$", message)
                if cancel:
                    result.append(dict(base, kind="cancel", task=cancel.group(1)))
    return result


def diagnose(status, slot, runner_records, server_records, *, now=None):
    now = now or dt.datetime.now(dt.timezone.utc)
    status = _VIEW.validate(status, now=now)
    selected = next((r for r in status["calendar"] if r["slot_utc"] == slot), None)
    if selected is None:
        raise ValueError("SLOT_OUTSIDE_CALENDAR")
    start = _VIEW.instant(slot).timestamp()
    arm = selected["qwen"]
    report = dict(schema_version=1, scope="OPERATIONAL_DIAGNOSTIC_ONLY",
                  slot_utc=slot, source_generated_at=status["generated_at"],
                  performance_sealed=True, execution_approved=False,
                  recorded_state="MISSING" if arm["state"] == "MISSING" else
                  "RECORDED_VALID" if arm["state"] in {"LONG", "SHORT", "NO_PROPOSAL"} else arm["state"],
                  reason_codes=arm["reason_codes"] if arm["state"] == "MISSING" else [],
                  client_budget_seconds=status["timeout_seconds"],
                  recorded_latency_seconds=arm["latency_seconds"],
                  diagnosis="UNCLASSIFIED", confidence="UNKNOWN", timing_evidence={},
                  transport_exit_code=None,
                  limitations=["FROZEN_CLIENT_DOES_NOT_RECORD_TRANSPORT_EXIT_CODE"])
    if status["integrity"] != "OK" or status["conflicts"] or "MONITOR_STALE" in status["issues"]:
        report.update(diagnosis="STATUS_UNVERIFIABLE")
        return report
    missing = report["recorded_state"] == "MISSING"
    if not missing:
        report.update(diagnosis=report["recorded_state"], confidence="OBSERVED")
        if report["recorded_state"] != "RECORDED_VALID":
            return report
    reasons = set(arm["reason_codes"])
    if missing and reasons != {"MODEL_UNAVAILABLE"}:
        report.update(diagnosis=next(iter(reasons)) if len(reasons) == 1 else "MULTIPLE_RECORDED_REASONS",
                      confidence="OBSERVED")
        return report
    if missing:
        report["diagnosis"] = "MODEL_UNAVAILABLE_UNCLASSIFIED"
    runners = [e for e in events(runner_records, "runner")
               if start <= e["at"] <= start + 600 and e["missing"] == missing]
    servers = [e for e in events(server_records, "server") if start <= e["at"] <= start + 600]
    if len(runners) != 1 or arm["latency_seconds"] is None:
        report["limitations"].append("RUNNER_CORRELATION_UNAVAILABLE")
        return report
    runner = runners[0]
    budget = status["timeout_seconds"]
    if abs(runner["seconds"] - arm["latency_seconds"]) > .5:
        report["limitations"].append("RUNNER_LATENCY_MISMATCH")
        return report
    inferred_start = runner["at"] - runner["seconds"]
    launches = [e for e in servers if e["kind"] == "launch" and abs(e["at"] - inferred_start) <= 3]
    if len(launches) != 1:
        report["limitations"].append("SERVER_TASK_AMBIGUOUS_OR_UNAVAILABLE")
        return report
    launch = launches[0]
    matched = [e for e in servers if e["task"] == launch["task"]
               and e["instance"] == launch["instance"] and launch["at"] <= e["at"] <= runner["at"] + 2]
    cancels = [e for e in matched if e["kind"] == "cancel"]
    prompts = [e for e in matched if e["kind"] == "prompt_complete"]
    report["timing_evidence"]["runner_wall_seconds"] = runner["seconds"]
    if len(prompts) == 1:
        prompt = prompts[0]
        report["timing_evidence"].update(prompt_processing_seconds=prompt["seconds"],
            prompt_tokens=prompt["tokens"], prompt_tokens_per_second=prompt["tokens_per_second"],
            generation_headroom_upper_bound_seconds=round(max(0, budget-prompt["seconds"]), 3))
    if (missing and len(cancels) == 1 and abs(cancels[0]["at"]-inferred_start-budget) <= 2
            and abs(runner["seconds"]-budget) <= 2):
        report.update(diagnosis="CLIENT_TIMEOUT_LIKELY", confidence="INFERRED")
        report["timing_evidence"]["server_task_cancelled"] = True
    return report


def read_logs(path):
    if Path(path).suffix != ".jsonl":
        raise ValueError("JSONL_LOG_REQUIRED")
    with Path(path).open("rb") as stream:
        raw = stream.read(MAX_BYTES + 1)
    if len(raw) > MAX_BYTES:
        raise ValueError("LOG_LIMIT")
    return [json.loads(line) for line in raw.splitlines() if line.strip()]


def system_logs(role, slot):
    start = _VIEW.instant(slot)
    result = subprocess.run(["/usr/bin/journalctl", "--unit", UNITS[role], "--since", start.isoformat(),
        "--until", (start+dt.timedelta(minutes=10)).isoformat(), "--no-pager", "--output=json"],
        capture_output=True, timeout=15)
    if result.returncode or len(result.stdout) > MAX_BYTES:
        raise ValueError("SYSTEM_JOURNAL_UNAVAILABLE")
    return [json.loads(line) for line in result.stdout.splitlines() if line.strip()]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--status", required=True, type=Path)
    parser.add_argument("--slot", required=True)
    source = parser.add_mutually_exclusive_group(required=True)
    source.add_argument("--system-journal", action="store_true")
    source.add_argument("--runner-log", type=Path)
    parser.add_argument("--server-log", type=Path)
    args = parser.parse_args()
    if args.status.name != "status.json" or (args.runner_log is not None) != (args.server_log is not None):
        parser.error("status.json and either system journal or both JSONL logs are required")
    try:
        status = _VIEW.public_view(args.status)
        # Validate slot and projection before reading any journal window.
        diagnose(status, args.slot, [], [])
        runner, server = ([system_logs(role, args.slot) for role in ("runner", "server")]
                          if args.system_journal else [read_logs(args.runner_log), read_logs(args.server_log)])
        print(json.dumps(diagnose(status, args.slot, runner, server), allow_nan=False, sort_keys=True))
    except (OSError, ValueError, TypeError, KeyError, subprocess.SubprocessError):
        parser.exit(2, "Diagnostic evidence unavailable or invalid.\n")


if __name__ == "__main__":
    main()
