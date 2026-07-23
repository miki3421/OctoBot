#!/usr/bin/env bash

set -u

shadow_interval_seconds="${SHADOW_INTERVAL_SECONDS:-86400}"
shadow_history_days="${SHADOW_HISTORY_DAYS:-264}"
shadow_retry_seconds="${SHADOW_RETRY_SECONDS:-900}"

while true; do
  if PYTHONPATH="${PYTHONPATH:-/workspace:/workspace/packages}" \
    python3 -m octobot.ai_strategy_lab.cli run-trend-shadow \
      --output-root /octobot/backtesting/research/shadow-forward \
      --journal /shadow/trend_shadow.jsonl \
      --health /shadow/health.json \
      --lock /shadow/runner.lock \
      --history-days "${shadow_history_days}" \
      --cost-stress-multiplier 3 \
      --catch-up-max-days 7 \
    && PYTHONPATH="${PYTHONPATH:-/workspace:/workspace/packages}" \
    python3 -m octobot.ai_strategy_lab.cli evaluate-shadow-performance \
      --journal /shadow/trend_shadow.jsonl \
      --output /shadow/performance.json \
      --initial-capital 10000 \
      --fixed-monthly-amount 25 \
      --strategy \
        bear_regime_short_filter_dual_momentum_30_120_weekly_v3_cost_stress_3x \
    && PYTHONPATH="${PYTHONPATH:-/workspace:/workspace/packages}" \
    python3 -m octobot.ai_strategy_lab.cli audit-income-objective \
      --strategy-evidence \
        /octobot/backtesting/research/strategy_evidence_v3_cost3x_68months.json \
      --prefunded-research \
        /octobot/backtesting/research/prefunded_income_v2_v3_cost3x_10y.json \
      --shadow-performance /shadow/performance.json \
      --output /shadow/income-objective.json \
      --monthly-amount 25 \
    && PYTHONPATH="${PYTHONPATH:-/workspace:/workspace/packages}" \
    python3 -m octobot.ai_strategy_lab.cli \
      run-risk-budgeted-carry-shadow \
      --output-root /octobot/backtesting/research/shadow-forward-v14 \
      --journal /shadow/v14/trend_carry_shadow.jsonl \
      --health /shadow/v14/health.json \
      --lock /shadow/v14/runner.lock \
      --history-days "${shadow_history_days}" \
      --cost-stress-multiplier 3 \
      --max-overlay-fraction 0.20 \
      --catch-up-max-days 7 \
    && PYTHONPATH="${PYTHONPATH:-/workspace:/workspace/packages}" \
    python3 -m octobot.ai_strategy_lab.cli evaluate-shadow-performance \
      --journal /shadow/v14/trend_carry_shadow.jsonl \
      --output /shadow/v14/performance.json \
      --initial-capital 10000 \
      --fixed-monthly-amount 25 \
      --strategy risk_budgeted_idle_carry_overlay_v14 \
    && PYTHONPATH="${PYTHONPATH:-/workspace:/workspace/packages}" \
    python3 -m octobot.ai_strategy_lab.cli audit-income-objective \
      --strategy-evidence \
        /octobot/backtesting/research/strategy_evidence_v14_cost3x_68months.json \
      --prefunded-research \
        /octobot/backtesting/research/prefunded_income_v2_v14_cost3x_10y.json \
      --robustness-research \
        /octobot/backtesting/research/v14_r1_adverse_execution_robustness.json \
      --shadow-performance /shadow/v14/performance.json \
      --output /shadow/v14/income-objective.json \
      --monthly-amount 25; then
    sleep "${shadow_interval_seconds}"
  else
    sleep "${shadow_retry_seconds}"
  fi
done
