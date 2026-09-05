#!/usr/bin/env bash

set -u

research_root="/usr/ext_hd/auto_trading_sys/octobot-local/backtesting/research"
parent_root="${research_root}/liquid-market-timeseries-momentum-v1"
parent_experiment="${parent_root}/experiments/liquid-market-timeseries-momentum-v1-1fee1e99ec42-f9fb49bd7309"
observer_root="/breadth-forward"
upstream_root="/diversified-forward"
runtime_root="/gate-runtime"
cutoff_epoch=1803774300
pre_cutoff_seconds="${BREADTH_GATE_PRE_CUTOFF_SECONDS:-86400}"
retry_seconds="${BREADTH_GATE_RETRY_SECONDS:-900}"

for interval_value in "${pre_cutoff_seconds}" "${retry_seconds}"; do
  case "${interval_value}" in
    ''|*[!0-9]*)
      echo "breadth gate intervals must be positive integers" >&2
      exit 2
      ;;
  esac
  if (( interval_value <= 0 )); then
    echo "breadth gate intervals must be positive integers" >&2
    exit 2
  fi
done

gate_arguments=(
  --gate-protocol "${research_root}/liquid-market-breadth-forward-v2/gate-protocol.json"
  --gate-lock "${observer_root}/gate-lock.json"
  --output-root "${observer_root}/official-gate"
  --gate-test "/workspace/tests/unit_tests/ai_strategy_lab/test_liquid_market_breadth_forward_gate_v2.py"
  --gate-entrypoint "/workspace/docker/breadth-forward-gatekeeper-entrypoint.sh"
  --protocol "${research_root}/liquid-market-breadth-forward-v2/protocol.json"
  --implementation-lock "${observer_root}/implementation-lock.json"
  --parent-protocol "${parent_root}/protocol.json"
  --parent-implementation-lock "${parent_root}/implementation-lock.json"
  --parent-report "${parent_experiment}/report.json"
  --parent-manifest "${parent_experiment}/manifest.json"
  --parent-trajectory "${parent_experiment}/training-trajectory.npz"
  --upstream-protocol "${research_root}/diversified-trend-cointegration-v1/forward-protocol-v1.json"
  --upstream-implementation-lock "${upstream_root}/implementation-lock.json"
  --snapshot "${research_root}/category-momentum-v1/sources/source-snapshot-b0204985b9fa-03d744e12e04"
  --history "${research_root}/category-momentum-v1/history/history-b0204985b9fa-4158e252768a"
  --upstream-daily "${upstream_root}/daily"
  --upstream-raw "${upstream_root}/raw"
  --upstream-health "${upstream_root}/health.json"
  --journal "${observer_root}/decisions.jsonl"
  --health "${observer_root}/health.json"
  --runner-lock "${observer_root}/runner.lock"
  --runner-test "/workspace/tests/unit_tests/ai_strategy_lab/test_liquid_market_breadth_forward_runner.py"
  --protocol-test "/workspace/tests/unit_tests/ai_strategy_lab/test_liquid_market_breadth_forward_v2.py"
  --entrypoint "/workspace/docker/breadth-forward-observer-entrypoint.sh"
)

write_health() {
  local status="$1"
  local phase="$2"
  local detail="$3"
  local temporary
  temporary="$(mktemp "${runtime_root}/.health.XXXXXX")"
  python3 - "${temporary}" "${status}" "${phase}" "${detail}" <<'PY'
import datetime
import json
import pathlib
import sys

path = pathlib.Path(sys.argv[1])
value = {
    "schema_version": 1,
    "service": "liquid_market_breadth_forward_gatekeeper_v2",
    "status": sys.argv[2],
    "phase": sys.argv[3],
    "detail": sys.argv[4],
    "last_success_at": datetime.datetime.now(datetime.timezone.utc).isoformat(),
    "evaluation_not_before_utc": "2027-02-28T00:25:00+00:00",
    "research_only": True,
    "pre_cutoff_economic_metrics_calculated": False,
    "orders_authorized": False,
    "paper_orders_authorized": False,
    "automatic_promotion": False,
}
with path.open("w", encoding="utf-8") as stream:
    json.dump(value, stream, indent=2, sort_keys=True)
    stream.write("\n")
    stream.flush()
PY
  mv "${temporary}" "${runtime_root}/health.json"
}

while true; do
  if [[ ! -f "${observer_root}/gate-lock.json" ]]; then
    write_health "failed" "missing_gate_lock" "pre-forward gate lock is absent"
    sleep "${retry_seconds}"
    continue
  fi
  current_epoch="$(date -u +%s)"
  if (( current_epoch < cutoff_epoch )); then
    remaining_seconds=$((cutoff_epoch - current_epoch))
    sleep_seconds="${pre_cutoff_seconds}"
    if (( remaining_seconds < sleep_seconds )); then
      sleep_seconds="${remaining_seconds}"
    fi
    write_health \
      "healthy" \
      "waiting_for_cutoff" \
      "no aggregate economic metric is calculated before the frozen cutoff"
    sleep "${sleep_seconds}"
    continue
  fi
  if python3 - "${observer_root}/official-gate" <<'PY'
import pathlib
import sys

root = pathlib.Path(sys.argv[1])
matches = list(root.glob("liquid-market-breadth-gate-v2-*-*"))
valid = [
    value
    for value in matches
    if value.is_dir()
    and (value / "report.json").is_file()
    and (value / "manifest.json").is_file()
]
raise SystemExit(0 if len(matches) == len(valid) == 1 else 1)
PY
  then
    write_health \
      "healthy" \
      "official_evaluation_complete" \
      "single immutable result exists; no automatic promotion"
    sleep "${pre_cutoff_seconds}"
    continue
  fi
  readiness_temporary="$(mktemp "${runtime_root}/.readiness.XXXXXX")"
  if python3 -m \
    octobot.ai_strategy_lab.liquid_market_breadth_forward_gate_v2 \
    readiness "${gate_arguments[@]}" >"${readiness_temporary}"; then
    mv "${readiness_temporary}" "${runtime_root}/readiness.json"
    if python3 - "${runtime_root}/readiness.json" <<'PY'
import json
import sys

with open(sys.argv[1], encoding="utf-8") as stream:
    value = json.load(stream)
raise SystemExit(0 if value.get("official_evaluation_authorized") is True else 1)
PY
    then
      write_health \
        "healthy" \
        "official_evaluation_running" \
        "all frozen structural gates passed"
      if python3 -m \
        octobot.ai_strategy_lab.liquid_market_breadth_forward_gate_v2 \
        evaluate "${gate_arguments[@]}" >/dev/null; then
        write_health \
          "healthy" \
          "official_evaluation_complete" \
          "single immutable result created; no automatic promotion"
        sleep "${pre_cutoff_seconds}"
      else
        write_health \
          "failed" \
          "official_evaluation_failed_closed" \
          "no official result was accepted"
        sleep "${retry_seconds}"
      fi
    else
      write_health \
        "healthy" \
        "waiting_for_complete_evidence" \
        "cutoff passed but structural gates remain false"
      sleep "${retry_seconds}"
    fi
  else
    rm -f -- "${readiness_temporary}"
    write_health \
      "failed" \
      "readiness_failed_closed" \
      "gate lineage or evidence verification failed"
    sleep "${retry_seconds}"
  fi
done
