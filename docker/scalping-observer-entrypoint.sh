#!/usr/bin/env bash

set -u

observer_retry_seconds="${SCALPING_OBSERVER_RETRY_SECONDS:-5}"

while true; do
  if PYTHONPATH="${PYTHONPATH:-/workspace:/workspace/packages}" \
    python3 -m octobot.ai_strategy_lab.cli \
      run-scalping-observer \
      --database /scalping/btc-futures-level5.sqlite \
      --health /scalping/health.json \
      --symbol XBTUSDTM \
      --health-interval-seconds 5 \
      --commit-interval-seconds 1 \
      --stale-book-seconds 5 \
      --startup-timeout-seconds 30; then
    sleep "${observer_retry_seconds}"
  else
    sleep "${observer_retry_seconds}"
  fi
done
