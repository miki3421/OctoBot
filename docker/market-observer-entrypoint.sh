#!/usr/bin/env bash

set -u

observer_interval_seconds="${MARKET_OBSERVER_INTERVAL_SECONDS:-900}"
observer_retry_seconds="${MARKET_OBSERVER_RETRY_SECONDS:-60}"

case "${observer_interval_seconds}" in
  ''|*[!0-9]*)
    echo "MARKET_OBSERVER_INTERVAL_SECONDS must be a positive integer" >&2
    exit 2
    ;;
esac
if (( observer_interval_seconds <= 0 )); then
  echo "MARKET_OBSERVER_INTERVAL_SECONDS must be a positive integer" >&2
  exit 2
fi

sleep_until_next_interval() {
  local current_epoch
  local sleep_seconds

  current_epoch="$(date -u +%s)"
  sleep_seconds=$((
    observer_interval_seconds
    - current_epoch % observer_interval_seconds
  ))
  sleep "${sleep_seconds}"
}

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
    sleep_until_next_interval
  else
    sleep "${observer_retry_seconds}"
  fi
done
