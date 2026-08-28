#!/usr/bin/env bash

set -u

shadow_interval_seconds="${EXECUTION_SHADOW_INTERVAL_SECONDS:-1}"
shadow_retry_seconds="${EXECUTION_SHADOW_RETRY_SECONDS:-5}"

while true; do
  if PYTHONPATH="${PYTHONPATH:-/workspace:/workspace/packages}" \
    python3 -m octobot.ai_strategy_lab.execution_shadow_v1 run-once \
      --protocol /execution-shadow/protocol.json \
      --model /evidence/prelock/development-final-model.npz \
      --locked-report /evidence/locked/report.json \
      --locked-manifest /evidence/locked/manifest.json \
      --fee-audit /evidence/locked/postlock-fee-neutral-audit.json \
      --source-database /scalping/btc-futures-level5.sqlite \
      --collector-health /scalping/health.json \
      --journal /execution-shadow/journal.sqlite \
      --health /execution-shadow/health.json \
      --lock /execution-shadow/runner.lock \
      --evaluation /execution-shadow/forward-evaluation.json \
      >/dev/null; then
    sleep "${shadow_interval_seconds}"
  else
    sleep "${shadow_retry_seconds}"
  fi
done
