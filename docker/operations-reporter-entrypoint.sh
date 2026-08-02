#!/usr/bin/env bash

set -u

report_interval_seconds="${OPERATIONS_REPORT_INTERVAL_SECONDS:-3600}"
report_retry_seconds="${OPERATIONS_REPORT_RETRY_SECONDS:-60}"

case "${report_interval_seconds}" in
  ''|*[!0-9]*)
    echo "OPERATIONS_REPORT_INTERVAL_SECONDS must be a positive integer" >&2
    exit 2
    ;;
esac
if (( report_interval_seconds <= 0 )); then
  echo "OPERATIONS_REPORT_INTERVAL_SECONDS must be a positive integer" >&2
  exit 2
fi

sleep_until_next_interval() {
  local current_epoch
  local sleep_seconds

  current_epoch="$(date -u +%s)"
  sleep_seconds=$((
    report_interval_seconds
    - current_epoch % report_interval_seconds
  ))
  sleep "${sleep_seconds}"
}

while true; do
  if PYTHONPATH="${PYTHONPATH:-/workspace:/workspace/packages}" \
    python3 -m octobot.ai_strategy_lab.cli record-operational-report \
      --ai-database /sources/ai/ai_decisions.sqlite \
      --v5-database /sources/v5/binance/v5-paper.sqlite \
      --scalping-database /sources/scalping/btc-futures-level5.sqlite \
      --scalping-health /sources/scalping/health.json \
      --v5-health /sources/v5/binance/health.json \
      --shadow-health /sources/shadow/health.json \
      --market-health /sources/shadow/market/health.json \
      --market-evidence /sources/shadow/market/evidence.json \
      --current-output /operations/current.json \
      --daily-journal /operations/daily.jsonl \
      --backup-root /operations/backups \
      --scalping-protocol /operations/scalping-evaluation-protocol.json \
      --lock /operations/runner.lock \
      --main-host octobot \
      --main-port 5001 \
      --v5-host v5-broker \
      --v5-port 5001 >/tmp/operations-report.json; then
    python3 -c "
import json
value = json.load(open('/operations/current.json'))
print(
    'operational report', value['generated_at'], value['overall_status'],
    'backup_verified=' + str(value['backup']['verified']).lower(),
)
"
    sleep_until_next_interval
  else
    sleep "${report_retry_seconds}"
  fi
done
