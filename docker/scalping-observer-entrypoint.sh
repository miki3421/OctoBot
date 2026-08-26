#!/usr/bin/env bash

set -u

observer_retry_seconds="${SCALPING_OBSERVER_RETRY_SECONDS:-5}"
observer_pid=""

stop_observer() {
  if [[ -n "${observer_pid}" ]] && kill -0 "${observer_pid}" 2>/dev/null; then
    kill -TERM "${observer_pid}"
    wait "${observer_pid}"
  fi
  exit 0
}

trap stop_observer TERM INT

while true; do
  PYTHONPATH="${PYTHONPATH:-/workspace:/workspace/packages}" \
    python3 -m octobot.ai_strategy_lab.cli \
      run-scalping-observer \
      --database /scalping/btc-futures-level5.sqlite \
      --health /scalping/health.json \
      --symbol XBTUSDTM \
      --health-interval-seconds 5 \
      --commit-interval-seconds 1 \
      --stale-book-seconds 5 \
      --startup-timeout-seconds 30 &
  observer_pid="$!"
  if wait "${observer_pid}"; then
    observer_pid=""
    sleep "${observer_retry_seconds}"
  else
    observer_pid=""
    sleep "${observer_retry_seconds}"
  fi
done
