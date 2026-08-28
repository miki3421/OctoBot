#!/usr/bin/env bash

set -u

observer_interval_seconds="${CROSS_VENUE_INTERVAL_SECONDS:-900}"
observer_retry_seconds="${CROSS_VENUE_RETRY_SECONDS:-60}"

case "${observer_interval_seconds}" in
  ''|*[!0-9]*)
    echo "CROSS_VENUE_INTERVAL_SECONDS must be a positive integer" >&2
    exit 2
    ;;
esac
if (( observer_interval_seconds <= 0 )); then
  echo "CROSS_VENUE_INTERVAL_SECONDS must be a positive integer" >&2
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
    python3 -m octobot.ai_strategy_lab.cross_venue_observer run-once \
      --archive-root /cross-venue/records \
      --index /cross-venue/index.jsonl \
      --health /cross-venue/health.json \
      --lock /cross-venue/runner.lock \
      --interval-minutes 15 \
      --timeout-seconds 20 \
      --maximum-collection-seconds 180 \
      --maximum-client-midpoint-skew-seconds 1 \
      --maximum-server-book-age-seconds 30 \
      --maximum-server-future-skew-seconds 5; then
    sleep_until_next_interval
  else
    sleep "${observer_retry_seconds}"
  fi
done
