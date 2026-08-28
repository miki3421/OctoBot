#!/usr/bin/env bash

set -u

retry_seconds="${DIVERSIFIED_FORWARD_RETRY_SECONDS:-900}"
research_root="/usr/ext_hd/auto_trading_sys/octobot-local/backtesting/research"
training_root="${research_root}/diversified-trend-cointegration-v1/training/diversified-trend-cointegration-v1-36f7b0106d97-3d7dcbc873cb"
observer_root="/diversified-forward"

case "${retry_seconds}" in
  ''|*[!0-9]*)
    echo "DIVERSIFIED_FORWARD_RETRY_SECONDS must be a positive integer" >&2
    exit 2
    ;;
esac
if (( retry_seconds <= 0 )); then
  echo "DIVERSIFIED_FORWARD_RETRY_SECONDS must be a positive integer" >&2
  exit 2
fi

runner_arguments=(
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

sleep_until_next_finalization() {
  local current_epoch
  local current_midnight
  local next_epoch
  local sleep_seconds

  current_epoch="$(date -u +%s)"
  current_midnight=$((current_epoch - current_epoch % 86400))
  next_epoch=$((current_midnight + 600))
  if (( current_epoch >= next_epoch )); then
    next_epoch=$((next_epoch + 86400))
  fi
  sleep_seconds=$((next_epoch - current_epoch))
  sleep "${sleep_seconds}"
}

while true; do
  if python3 -m \
    octobot.ai_strategy_lab.diversified_trend_cointegration_forward_runner \
    run-once "${runner_arguments[@]}" >/dev/null; then
    sleep_until_next_finalization
  else
    sleep "${retry_seconds}"
  fi
done
