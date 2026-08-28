#!/usr/bin/env bash

set -u

research_root="/usr/ext_hd/auto_trading_sys/octobot-local/backtesting/research"
training_root="${research_root}/diversified-trend-cointegration-v1/training/diversified-trend-cointegration-v1-36f7b0106d97-3d7dcbc873cb"
observer_root="/diversified-forward"
runtime_root="/gate-runtime"
cutoff_epoch=1803773400
pre_cutoff_check_seconds="${DIVERSIFIED_GATE_PRE_CUTOFF_CHECK_SECONDS:-86400}"
retry_seconds="${DIVERSIFIED_GATE_RETRY_SECONDS:-900}"

for value in "${pre_cutoff_check_seconds}" "${retry_seconds}"; do
  case "${value}" in
    ''|*[!0-9]*)
      echo "gatekeeper intervals must be positive integers" >&2
      exit 2
      ;;
  esac
  if (( value <= 0 )); then
    echo "gatekeeper intervals must be positive integers" >&2
    exit 2
  fi
done

gate_arguments=(
  --gate-protocol "${research_root}/diversified-trend-cointegration-v1/forward-gate-protocol-v1.json"
  --gate-lock "${observer_root}/gate-lock.json"
  --output-root "${observer_root}/official-gate"
  --protocol "${research_root}/diversified-trend-cointegration-v1/forward-protocol-v1.json"
  --implementation-lock "${observer_root}/implementation-lock.json"
  --parent-protocol "${research_root}/diversified-trend-cointegration-v1/protocol-v1_2.json"
  --selected-model "${training_root}/selected-model.json"
  --training-report "${training_root}/report.json"
  --training-manifest "${training_root}/manifest.json"
  --training-trajectory "${training_root}/training-trajectories.json"
  --snapshot "${research_root}/category-momentum-v1/sources/source-snapshot-b0204985b9fa-03d744e12e04"
  --history "${research_root}/category-momentum-v1/history/history-b0204985b9fa-4158e252768a"
  --null "${research_root}/expanded-cointegration-pairs-v2/evaluations/expanded-cointegration-pairs-v2-7718dd8e2f55-cfe3d78a318b/monte-carlo-null.npy"
  --archive-root "${observer_root}/daily"
  --raw-root "${observer_root}/raw"
  --journal "${observer_root}/decisions.jsonl"
  --health "${observer_root}/health.json"
  --runner-lock "${observer_root}/runner.lock"
  --timeout-seconds 45
  --maximum-workers 8
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
    "service": "diversified_forward_gatekeeper_v1",
    "status": sys.argv[2],
    "phase": sys.argv[3],
    "detail": sys.argv[4],
    "last_success_at": datetime.datetime.now(datetime.timezone.utc).isoformat(),
    "evaluation_not_before_utc": "2027-02-28T00:10:00+00:00",
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
  current_epoch="$(date -u +%s)"
  if (( current_epoch < cutoff_epoch )); then
    remaining_seconds=$((cutoff_epoch - current_epoch))
    sleep_seconds="${pre_cutoff_check_seconds}"
    if (( remaining_seconds < sleep_seconds )); then
      sleep_seconds="${remaining_seconds}"
    fi
    write_health \
      "healthy" \
      "waiting_for_cutoff" \
      "no economic metric is calculated before the frozen cutoff"
    sleep "${sleep_seconds}"
    continue
  fi

  if python3 - "${observer_root}/official-gate" <<'PY'
import pathlib
import sys

root = pathlib.Path(sys.argv[1])
matches = list(root.glob("diversified-forward-gate-v1-bddf74829641-*"))
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
    sleep "${pre_cutoff_check_seconds}"
    continue
  fi

  readiness_temporary="$(mktemp "${runtime_root}/.readiness.XXXXXX")"
  if python3 -m \
    octobot.ai_strategy_lab.diversified_trend_cointegration_forward_gate_v1 \
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
        "all frozen readiness gates passed"
      if python3 -m \
        octobot.ai_strategy_lab.diversified_trend_cointegration_forward_gate_v1 \
        evaluate "${gate_arguments[@]}" >/dev/null; then
        write_health \
          "healthy" \
          "official_evaluation_complete" \
          "single immutable result created; no automatic promotion"
        sleep "${pre_cutoff_check_seconds}"
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
        "cutoff passed but one or more structural gates remain false"
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
