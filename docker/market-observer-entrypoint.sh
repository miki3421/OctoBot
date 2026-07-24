#!/usr/bin/env bash

set -u

observer_interval_seconds="${MARKET_OBSERVER_INTERVAL_SECONDS:-900}"
observer_retry_seconds="${MARKET_OBSERVER_RETRY_SECONDS:-60}"

while true; do
  if PYTHONPATH="${PYTHONPATH:-/workspace:/workspace/packages}" \
    python3 -m octobot.ai_strategy_lab.cli \
      run-forward-market-observer \
      --journal /shadow/market/microstructure.jsonl \
      --health /shadow/market/health.json \
      --lock /shadow/market/runner.lock \
      --archive-root /shadow/market/records \
      --interval-minutes 15 \
      --timeout-seconds 30 \
      --maximum-collection-seconds 300 \
    && PYTHONPATH="${PYTHONPATH:-/workspace:/workspace/packages}" \
    python3 -m octobot.ai_strategy_lab.cli \
      evaluate-forward-market-evidence \
      --journal /shadow/market/microstructure.jsonl \
      --output /shadow/market/evidence.json; then
    sleep "${observer_interval_seconds}"
  else
    sleep "${observer_retry_seconds}"
  fi
done
