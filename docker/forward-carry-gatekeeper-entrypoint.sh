#!/usr/bin/env bash

set -u

gate_interval_seconds="${CARRY_GATEKEEPER_INTERVAL_SECONDS:-900}"
gate_retry_seconds="${CARRY_GATEKEEPER_RETRY_SECONDS:-60}"

case "${gate_interval_seconds}:${gate_retry_seconds}" in
  *[!0-9:]*|:*|*:)
    echo "Carry gatekeeper intervals must be positive integers" >&2
    exit 2
    ;;
esac
if (( gate_interval_seconds <= 0 || gate_retry_seconds <= 0 )); then
  echo "Carry gatekeeper intervals must be positive integers" >&2
  exit 2
fi

while true; do
  if python3 -m octobot.ai_strategy_lab.forward_carry_gatekeeper \
    --protocol /protocol/protocol.json \
    --journal /shadow/market/microstructure.jsonl \
    --evidence /shadow/market/evidence.json \
    --market-health /shadow/market/health.json \
    --archive-root /shadow/market/records \
    --state-root /carry-gate >/dev/null; then
    sleep "${gate_interval_seconds}"
  else
    sleep "${gate_retry_seconds}"
  fi
done
