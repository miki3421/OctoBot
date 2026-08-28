#!/usr/bin/env bash

set -u

retry_seconds="${BREADTH_FORWARD_RETRY_SECONDS:-900}"
research_root="/usr/ext_hd/auto_trading_sys/octobot-local/backtesting/research"
parent_root="${research_root}/liquid-market-timeseries-momentum-v1"
parent_experiment="${parent_root}/experiments/liquid-market-timeseries-momentum-v1-1fee1e99ec42-f9fb49bd7309"
upstream_root="/diversified-forward"
observer_root="/breadth-forward"

case "${retry_seconds}" in
  ''|*[!0-9]*)
    echo "BREADTH_FORWARD_RETRY_SECONDS must be a positive integer" >&2
    exit 2
    ;;
esac
if (( retry_seconds <= 0 )); then
  echo "BREADTH_FORWARD_RETRY_SECONDS must be a positive integer" >&2
  exit 2
fi

runner_arguments=(
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

sleep_until_next_finalization() {
  local current_epoch
  local current_midnight
  local next_epoch
  local sleep_seconds

  current_epoch="$(date -u +%s)"
  current_midnight=$((current_epoch - current_epoch % 86400))
  next_epoch=$((current_midnight + 1500))
  if (( current_epoch >= next_epoch )); then
    next_epoch=$((next_epoch + 86400))
  fi
  sleep_seconds=$((next_epoch - current_epoch))
  sleep "${sleep_seconds}"
}

if [[ ! -f "${observer_root}/implementation-lock.json" ]]; then
  python3 -m \
    octobot.ai_strategy_lab.liquid_market_breadth_forward_runner \
    write-lock "${runner_arguments[@]}" || exit $?
fi

while true; do
  if python3 -m \
    octobot.ai_strategy_lab.liquid_market_breadth_forward_runner \
    run-once "${runner_arguments[@]}" >/dev/null; then
    sleep_until_next_finalization
  else
    sleep "${retry_seconds}"
  fi
done
