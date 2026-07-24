"""Command-line interface for the offline AI strategy laboratory."""

from __future__ import annotations

import argparse
import dataclasses
import datetime
import hashlib
import json
import math
import pathlib
import sys
import time
import typing

import numpy

from octobot.ai_strategy_lab import dataset as dataset_module
from octobot.ai_strategy_lab import carry as carry_module
from octobot.ai_strategy_lab import carry_overlay as carry_overlay_module
from octobot.ai_strategy_lab import carry_robustness as carry_robustness_module
from octobot.ai_strategy_lab import carry_shadow_runner as carry_shadow_runner_module
from octobot.ai_strategy_lab import ensemble as ensemble_module
from octobot.ai_strategy_lab import funding as funding_module
from octobot.ai_strategy_lab import forward_evidence as forward_evidence_module
from octobot.ai_strategy_lab import forward_carry_dataset as forward_carry_dataset_module
from octobot.ai_strategy_lab import income_objective as income_objective_module
from octobot.ai_strategy_lab import experts as experts_module
from octobot.ai_strategy_lab import market_data as market_data_module
from octobot.ai_strategy_lab import microstructure as microstructure_module
from octobot.ai_strategy_lab import model as model_module
from octobot.ai_strategy_lab import paper_feedback as paper_feedback_module
from octobot.ai_strategy_lab import prefunded_income as prefunded_income_module
from octobot.ai_strategy_lab import relative_value as relative_value_module
from octobot.ai_strategy_lab import scalping_observer as scalping_observer_module
from octobot.ai_strategy_lab import shadow as shadow_module
from octobot.ai_strategy_lab import shadow_runner as shadow_runner_module
from octobot.ai_strategy_lab import shadow_performance as shadow_performance_module
from octobot.ai_strategy_lab import strategy_evidence as strategy_evidence_module
from octobot.ai_strategy_lab import trend as trend_module
from octobot.ai_strategy_lab import trend_meta as trend_meta_module
from octobot.ai_strategy_lab import withdrawal as withdrawal_module


def create_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="octobot-ai-lab",
        description=(
            "Offline research only: build point-in-time datasets and run "
            "purged walk-forward AI experiments. This command cannot place orders."
        ),
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    dataset_parser = subparsers.add_parser(
        "build-dataset", help="Build a versioned triple-barrier dataset."
    )
    dataset_parser.add_argument(
        "--input", action="append", required=True, help="OctoBot collector .data file."
    )
    dataset_parser.add_argument("--output", required=True, help="Output .npz path.")
    dataset_parser.add_argument("--candidate-stride", type=int, default=1)
    dataset_parser.add_argument("--atr-multiplier", type=float, default=1.5)
    dataset_parser.add_argument("--reward-risk", type=float, default=2.0)
    dataset_parser.add_argument("--min-stop-pct", type=float, default=0.005)
    dataset_parser.add_argument("--max-stop-pct", type=float, default=0.02)
    dataset_parser.add_argument("--horizon-bars", type=int, default=16)
    dataset_parser.add_argument("--fee-rate", type=float, default=0.0006)
    dataset_parser.add_argument("--slippage-rate", type=float, default=0.0002)
    dataset_parser.add_argument("--funding-rate-8h", type=float, default=0.0)
    dataset_parser.add_argument(
        "--funding-json",
        help="Versioned signed KuCoin funding history produced by fetch-funding.",
    )

    relabel_parser = subparsers.add_parser(
        "relabel-dataset",
        help="Reuse saved point-in-time features with a different barrier protocol.",
    )
    relabel_parser.add_argument("--base-dataset", required=True)
    relabel_parser.add_argument("--input", action="append", required=True)
    relabel_parser.add_argument("--output", required=True)
    relabel_parser.add_argument("--atr-multiplier", type=float, default=2.0)
    relabel_parser.add_argument("--reward-risk", type=float, default=1.5)
    relabel_parser.add_argument("--min-stop-pct", type=float, default=0.0075)
    relabel_parser.add_argument("--max-stop-pct", type=float, default=0.04)
    relabel_parser.add_argument("--horizon-bars", type=int, default=96)
    relabel_parser.add_argument("--fee-rate", type=float, default=0.0006)
    relabel_parser.add_argument("--slippage-rate", type=float, default=0.0002)
    relabel_parser.add_argument("--funding-rate-8h", type=float, default=0.0)
    relabel_parser.add_argument("--funding-json")

    funding_parser = subparsers.add_parser(
        "fetch-funding",
        help="Download public KuCoin funding settlements for reproducible research.",
    )
    funding_parser.add_argument(
        "--symbol",
        action="append",
        required=True,
        help="Mapping in OCTOBOT_SYMBOL=KUCOIN_SYMBOL form.",
    )
    funding_parser.add_argument("--from-date", required=True, help="UTC YYYY-MM-DD.")
    funding_parser.add_argument("--to-date", required=True, help="UTC YYYY-MM-DD inclusive.")
    funding_parser.add_argument("--output", required=True)

    archive_parser = subparsers.add_parser(
        "fetch-binance-archive",
        help=(
            "Build a research-only OctoBot collector from checksummed public "
            "Binance USD-M archives."
        ),
    )
    archive_parser.add_argument(
        "--symbol",
        action="append",
        required=True,
        help="Mapping in OCTOBOT_SYMBOL=BINANCE_SYMBOL form.",
    )
    archive_parser.add_argument("--from-date", required=True, help="UTC YYYY-MM-DD.")
    archive_parser.add_argument("--to-date", required=True, help="UTC YYYY-MM-DD inclusive.")
    archive_parser.add_argument("--output", required=True)
    archive_parser.add_argument("--funding-output")
    archive_parser.add_argument("--cache")
    archive_parser.add_argument(
        "--candle-interval",
        choices=("5m", "15m"),
        default="15m",
    )

    hourly_archive_parser = subparsers.add_parser(
        "fetch-binance-futures-hourly-archive",
        help="Build a research-only 1h collector from checksummed Binance USD-M archives.",
    )
    hourly_archive_parser.add_argument("--symbol", action="append", required=True)
    hourly_archive_parser.add_argument("--from-date", required=True)
    hourly_archive_parser.add_argument("--to-date", required=True)
    hourly_archive_parser.add_argument("--output", required=True)
    hourly_archive_parser.add_argument("--funding-output", required=True)
    hourly_archive_parser.add_argument("--cache")
    hourly_archive_parser.add_argument("--allowed-hourly-gaps", type=int, default=0)

    spot_parser = subparsers.add_parser(
        "fetch-binance-spot-archive",
        help="Build a research-only collector from checksummed Binance spot archives.",
    )
    spot_parser.add_argument(
        "--symbol",
        action="append",
        required=True,
        help="Mapping in OCTOBOT_SYMBOL=BINANCE_SYMBOL form.",
    )
    spot_parser.add_argument("--from-date", required=True, help="UTC YYYY-MM-DD.")
    spot_parser.add_argument("--to-date", required=True, help="UTC YYYY-MM-DD inclusive.")
    spot_parser.add_argument("--output", required=True)
    spot_parser.add_argument("--cache")
    spot_parser.add_argument("--allowed-15m-gaps", type=int, default=0)

    kucoin_spot_parser = subparsers.add_parser(
        "fetch-kucoin-spot-hourly",
        help="Build a research-only 1h collector from the public KuCoin spot API.",
    )
    kucoin_spot_parser.add_argument(
        "--symbol",
        action="append",
        required=True,
        help="Mapping in OCTOBOT_SYMBOL=KUCOIN_SYMBOL form.",
    )
    kucoin_spot_parser.add_argument("--from-date", required=True)
    kucoin_spot_parser.add_argument("--to-date", required=True)
    kucoin_spot_parser.add_argument("--output", required=True)
    kucoin_spot_parser.add_argument("--allowed-hourly-gaps", type=int, default=0)

    kucoin_futures_parser = subparsers.add_parser(
        "fetch-kucoin-futures-hourly",
        help="Build a research-only 1h collector from the public KuCoin futures API.",
    )
    kucoin_futures_parser.add_argument("--symbol", action="append", required=True)
    kucoin_futures_parser.add_argument("--from-date", required=True)
    kucoin_futures_parser.add_argument("--to-date", required=True)
    kucoin_futures_parser.add_argument("--output", required=True)
    kucoin_futures_parser.add_argument("--allowed-hourly-gaps", type=int, default=0)
    kucoin_futures_parser.add_argument(
        "--candle-interval",
        choices=("5m", "15m", "1h"),
        default="1h",
    )

    experiment_parser = subparsers.add_parser(
        "run-experiment",
        help="Train and evaluate the NumPy logistic baseline.",
    )
    experiment_parser.add_argument("--dataset", required=True)
    experiment_parser.add_argument("--output-root", required=True)
    experiment_parser.add_argument("--seed", type=int, default=42)
    experiment_parser.add_argument(
        "--model",
        choices=("logistic", "gradient_boosting"),
        default="logistic",
    )
    experiment_parser.add_argument("--epochs", type=int, default=12)
    experiment_parser.add_argument("--batch-size", type=int, default=8192)
    experiment_parser.add_argument("--learning-rate", type=float, default=0.01)
    experiment_parser.add_argument("--l2", type=float, default=0.001)
    experiment_parser.add_argument("--boosting-trees", type=int, default=32)
    experiment_parser.add_argument("--boosting-depth", type=int, default=2)
    experiment_parser.add_argument("--boosting-bins", type=int, default=16)
    experiment_parser.add_argument("--boosting-learning-rate", type=float, default=0.06)
    experiment_parser.add_argument("--folds", type=int, default=4)
    experiment_parser.add_argument("--minimum-validation-trades", type=int, default=20)
    experiment_parser.add_argument("--position-fraction", type=float, default=0.10)
    experiment_parser.add_argument(
        "--prediction-target",
        choices=("target", "profitable"),
        default="target",
        help="Classify target hits or net-profitable outcomes.",
    )
    experiment_parser.add_argument(
        "--locked-block-status",
        choices=("pristine", "diagnostic_reuse"),
        default="diagnostic_reuse",
        help="Declare whether the final chronological block has ever been inspected.",
    )
    experiment_parser.add_argument(
        "--training-stride",
        type=int,
        default=4,
        help="Train on one of every N 15m timestamps; all test timestamps remain evaluated.",
    )

    inspect_parser = subparsers.add_parser(
        "inspect-dataset", help="Validate and summarize a saved research dataset."
    )
    inspect_parser.add_argument("--dataset", required=True)

    experts_parser = subparsers.add_parser(
        "evaluate-experts",
        help="Evaluate frozen deterministic regime experts without fitting.",
    )
    experts_parser.add_argument("--dataset", required=True)
    experts_parser.add_argument("--output", required=True)
    experts_parser.add_argument("--position-fraction", type=float, default=0.10)
    experts_parser.add_argument("--folds", type=int, default=6)

    carry_parser = subparsers.add_parser(
        "evaluate-carry",
        help="Evaluate pre-registered delta-neutral spot/perpetual carry protocols.",
    )
    carry_parser.add_argument("--futures-collector", action="append", required=True)
    carry_parser.add_argument("--spot-collector", required=True)
    carry_parser.add_argument("--funding-json", required=True)
    carry_parser.add_argument("--output", required=True)
    carry_parser.add_argument("--initial-capital", type=float, default=10_000.0)
    carry_parser.add_argument("--cost-stress-multiplier", type=float, default=1.5)

    carry_overlay_parser = subparsers.add_parser(
        "evaluate-carry-overlay",
        help="Evaluate the pre-registered V5 idle-collateral carry overlay.",
    )
    carry_overlay_parser.add_argument(
        "--futures-collector", action="append", required=True
    )
    carry_overlay_parser.add_argument("--spot-collector", required=True)
    carry_overlay_parser.add_argument(
        "--funding-json", action="append", required=True
    )
    carry_overlay_parser.add_argument("--output", required=True)
    carry_overlay_parser.add_argument(
        "--initial-capital", type=float, default=10_000.0
    )
    carry_overlay_parser.add_argument(
        "--trend-cost-stress-multiplier", type=float, default=3.0
    )
    carry_overlay_parser.add_argument(
        "--carry-cost-stress-multiplier", type=float, default=3.0
    )
    carry_overlay_parser.add_argument(
        "--max-overlay-fraction", type=float, default=0.20
    )

    risk_budgeted_overlay_parser = subparsers.add_parser(
        "evaluate-risk-budgeted-carry-overlay",
        help="Evaluate the pre-registered V14 V13-plus-carry portfolio.",
    )
    risk_budgeted_overlay_parser.add_argument(
        "--futures-collector", action="append", required=True
    )
    risk_budgeted_overlay_parser.add_argument(
        "--spot-collector", required=True
    )
    risk_budgeted_overlay_parser.add_argument(
        "--funding-json", action="append", required=True
    )
    risk_budgeted_overlay_parser.add_argument("--output", required=True)
    risk_budgeted_overlay_parser.add_argument(
        "--initial-capital", type=float, default=10_000.0
    )
    risk_budgeted_overlay_parser.add_argument(
        "--trend-cost-stress-multiplier", type=float, default=3.0
    )
    risk_budgeted_overlay_parser.add_argument(
        "--carry-cost-stress-multiplier", type=float, default=3.0
    )
    risk_budgeted_overlay_parser.add_argument(
        "--max-overlay-fraction", type=float, default=0.20
    )
    risk_budgeted_overlay_parser.add_argument(
        "--positive-funding-realization", type=float, default=1.0
    )
    risk_budgeted_overlay_parser.add_argument(
        "--entry-delay-settlements", type=int, default=0
    )

    cost_aware_overlay_parser = subparsers.add_parser(
        "evaluate-cost-aware-carry-overlay",
        help="Evaluate the pre-registered V15 cost-aware carry portfolio.",
    )
    cost_aware_overlay_parser.add_argument(
        "--futures-collector", action="append", required=True
    )
    cost_aware_overlay_parser.add_argument(
        "--spot-collector", required=True
    )
    cost_aware_overlay_parser.add_argument(
        "--funding-json", action="append", required=True
    )
    cost_aware_overlay_parser.add_argument("--output", required=True)
    cost_aware_overlay_parser.add_argument(
        "--initial-capital", type=float, default=10_000.0
    )
    cost_aware_overlay_parser.add_argument(
        "--trend-cost-stress-multiplier", type=float, default=3.0
    )
    cost_aware_overlay_parser.add_argument(
        "--carry-cost-stress-multiplier", type=float, default=3.0
    )
    cost_aware_overlay_parser.add_argument(
        "--max-overlay-fraction", type=float, default=0.20
    )
    cost_aware_overlay_parser.add_argument(
        "--positive-funding-realization", type=float, default=1.0
    )

    execution_guarded_parser = subparsers.add_parser(
        "evaluate-execution-guarded-carry-overlay",
        help="Evaluate the pre-registered V16 execution-guarded carry.",
    )
    execution_guarded_parser.add_argument(
        "--futures-collector", action="append", required=True
    )
    execution_guarded_parser.add_argument(
        "--spot-collector", required=True
    )
    execution_guarded_parser.add_argument(
        "--funding-json", action="append", required=True
    )
    execution_guarded_parser.add_argument("--output", required=True)
    execution_guarded_parser.add_argument(
        "--initial-capital", type=float, default=10_000.0
    )
    execution_guarded_parser.add_argument(
        "--trend-cost-stress-multiplier", type=float, default=3.0
    )
    execution_guarded_parser.add_argument(
        "--carry-cost-stress-multiplier", type=float, default=3.0
    )
    execution_guarded_parser.add_argument(
        "--max-overlay-fraction", type=float, default=0.20
    )
    execution_guarded_parser.add_argument(
        "--positive-funding-realization", type=float, default=1.0
    )

    rotating_carry_parser = subparsers.add_parser(
        "evaluate-rotating-cost-aware-carry-overlay",
        help="Evaluate the pre-registered V17 rotating carry overlay.",
    )
    rotating_carry_parser.add_argument(
        "--futures-collector", action="append", required=True
    )
    rotating_carry_parser.add_argument(
        "--spot-collector", required=True
    )
    rotating_carry_parser.add_argument(
        "--funding-json", action="append", required=True
    )
    rotating_carry_parser.add_argument("--output", required=True)
    rotating_carry_parser.add_argument(
        "--initial-capital", type=float, default=10_000.0
    )
    rotating_carry_parser.add_argument(
        "--trend-cost-stress-multiplier", type=float, default=3.0
    )
    rotating_carry_parser.add_argument(
        "--carry-cost-stress-multiplier", type=float, default=3.0
    )
    rotating_carry_parser.add_argument(
        "--max-overlay-fraction", type=float, default=0.20
    )
    rotating_carry_parser.add_argument(
        "--positive-funding-realization", type=float, default=1.0
    )

    robustness_parser = subparsers.add_parser(
        "audit-v14-robustness",
        help="Audit the pre-registered V14-R1 adverse carry stress.",
    )
    for scenario in ("half", "zero"):
        for period in ("old", "recent", "kucoin"):
            robustness_parser.add_argument(
                f"--{scenario}-{period}-report", required=True
            )
        robustness_parser.add_argument(
            f"--{scenario}-evidence", required=True
        )
        robustness_parser.add_argument(
            f"--{scenario}-prefunded", required=True
        )
    robustness_parser.add_argument("--output", required=True)

    candidate_audit_parser = subparsers.add_parser(
        "audit-overlay-candidate",
        help="Audit frozen baseline and adverse carry-overlay scenarios.",
    )
    candidate_audit_parser.add_argument("--candidate-name", required=True)
    candidate_audit_parser.add_argument("--stress-name", required=True)
    for scenario in ("baseline", "stress"):
        for period in ("old", "recent", "kucoin"):
            candidate_audit_parser.add_argument(
                f"--{scenario}-{period}-report", required=True
            )
    candidate_audit_parser.add_argument(
        "--stress-evidence", required=True
    )
    candidate_audit_parser.add_argument(
        "--stress-prefunded", required=True
    )
    candidate_audit_parser.add_argument("--output", required=True)

    trend_parser = subparsers.add_parser(
        "evaluate-trend",
        help="Evaluate fixed low-frequency long/short trend portfolios.",
    )
    trend_parser.add_argument("--futures-collector", action="append", required=True)
    trend_parser.add_argument("--funding-json", action="append", required=True)
    trend_parser.add_argument("--output", required=True)
    trend_parser.add_argument("--initial-capital", type=float, default=10_000.0)
    trend_parser.add_argument("--cost-stress-multiplier", type=float, default=1.5)
    trend_parser.add_argument(
        "--strategy",
        action="append",
        help="Evaluate only the named base protocol; may be repeated.",
    )
    trend_parser.add_argument(
        "--skip-leave-one-asset-out",
        action="store_true",
        help="Skip LOAO only for explicitly diagnostic runs.",
    )

    trend_meta_parser = subparsers.add_parser(
        "evaluate-trend-meta",
        help="Evaluate the pre-registered V3 weekly logistic meta-filter.",
    )
    trend_meta_parser.add_argument(
        "--futures-collector", action="append", required=True
    )
    trend_meta_parser.add_argument(
        "--funding-json", action="append", required=True
    )
    trend_meta_parser.add_argument("--output", required=True)
    trend_meta_parser.add_argument(
        "--initial-capital", type=float, default=10_000.0
    )
    trend_meta_parser.add_argument(
        "--cost-stress-multiplier", type=float, default=3.0
    )

    relative_value_parser = subparsers.add_parser(
        "evaluate-relative-value",
        help="Evaluate the pre-registered V11 market-neutral sleeve.",
    )
    relative_value_parser.add_argument(
        "--futures-collector", action="append", required=True
    )
    relative_value_parser.add_argument(
        "--funding-json", action="append", required=True
    )
    relative_value_parser.add_argument("--output", required=True)
    relative_value_parser.add_argument(
        "--initial-capital", type=float, default=10_000.0
    )
    relative_value_parser.add_argument(
        "--cost-stress-multiplier", type=float, default=3.0
    )

    reversal_parser = subparsers.add_parser(
        "evaluate-residual-reversal",
        help="Evaluate the pre-registered V12 residual reversal sleeve.",
    )
    reversal_parser.add_argument(
        "--futures-collector", action="append", required=True
    )
    reversal_parser.add_argument(
        "--funding-json", action="append", required=True
    )
    reversal_parser.add_argument("--output", required=True)
    reversal_parser.add_argument(
        "--initial-capital", type=float, default=10_000.0
    )
    reversal_parser.add_argument(
        "--cost-stress-multiplier", type=float, default=3.0
    )

    evidence_parser = subparsers.add_parser(
        "evaluate-strategy-evidence",
        help="Bootstrap multi-horizon evidence for a fixed trend strategy.",
    )
    evidence_parser.add_argument(
        "--trend-report", action="append", required=True
    )
    evidence_parser.add_argument("--strategy", required=True)
    evidence_parser.add_argument("--output", required=True)
    evidence_parser.add_argument(
        "--initial-capital", type=float, default=10_000.0
    )
    evidence_parser.add_argument(
        "--horizon-months", action="append", type=int, default=None
    )
    evidence_parser.add_argument("--block-months", type=int, default=6)
    evidence_parser.add_argument("--simulations", type=int, default=10_000)
    evidence_parser.add_argument(
        "--annual-return-haircut",
        action="append",
        type=float,
        default=None,
    )
    evidence_parser.add_argument(
        "--random-seed", type=int, default=20_260_723
    )

    objective_parser = subparsers.add_parser(
        "audit-income-objective",
        help="Fail-closed audit of strategy, reserve policy and forward state.",
    )
    objective_parser.add_argument("--strategy-evidence", required=True)
    objective_parser.add_argument("--prefunded-research", required=True)
    objective_parser.add_argument("--shadow-performance", required=True)
    objective_parser.add_argument("--robustness-research")
    objective_parser.add_argument("--output", required=True)
    objective_parser.add_argument(
        "--monthly-amount", type=float, default=25.0
    )

    withdrawal_parser = subparsers.add_parser(
        "evaluate-withdrawals",
        help="Stress fixed-cash withdrawals from saved trend reports.",
    )
    withdrawal_parser.add_argument(
        "--trend-report", action="append", required=True
    )
    withdrawal_parser.add_argument("--strategy", required=True)
    withdrawal_parser.add_argument("--output", required=True)
    withdrawal_parser.add_argument(
        "--monthly-amount", action="append", type=float, required=True
    )
    withdrawal_parser.add_argument(
        "--initial-capital", type=float, default=10_000.0
    )
    withdrawal_parser.add_argument("--warmup-months", type=int, default=12)
    withdrawal_parser.add_argument("--horizon-months", type=int, default=60)
    withdrawal_parser.add_argument("--block-months", type=int, default=6)
    withdrawal_parser.add_argument("--simulations", type=int, default=5_000)
    withdrawal_parser.add_argument(
        "--safety-floor-fraction", type=float, default=0.80
    )
    withdrawal_parser.add_argument(
        "--annual-return-haircut",
        action="append",
        type=float,
        default=None,
    )
    withdrawal_parser.add_argument(
        "--random-seed", type=int, default=20_260_723
    )

    shadow_parser = subparsers.add_parser(
        "record-trend-shadow",
        help="Append a no-order trend target snapshot to a JSONL journal.",
    )
    shadow_parser.add_argument("--trend-report", required=True)
    shadow_parser.add_argument("--strategy", required=True)
    shadow_parser.add_argument("--journal", required=True)

    shadow_runner_parser = subparsers.add_parser(
        "run-trend-shadow",
        help="Run one atomic, public-data-only trend shadow cycle.",
    )
    shadow_runner_parser.add_argument("--output-root", required=True)
    shadow_runner_parser.add_argument("--journal", required=True)
    shadow_runner_parser.add_argument("--health", required=True)
    shadow_runner_parser.add_argument("--lock", required=True)
    shadow_runner_parser.add_argument("--history-days", type=int, default=264)
    shadow_runner_parser.add_argument(
        "--initial-capital", type=float, default=10_000.0
    )
    shadow_runner_parser.add_argument(
        "--cost-stress-multiplier", type=float, default=3.0
    )
    shadow_runner_parser.add_argument(
        "--strategy", default=shadow_runner_module.DEFAULT_STRATEGY
    )
    shadow_runner_parser.add_argument(
        "--rebalance-weekday-utc", type=int, default=6
    )
    shadow_runner_parser.add_argument(
        "--as-of-date", help="Fully closed UTC day, YYYY-MM-DD."
    )
    shadow_runner_parser.add_argument(
        "--catch-up-max-days",
        type=int,
        default=0,
        help="Sequentially recover at most this many missing days.",
    )

    carry_shadow_runner_parser = subparsers.add_parser(
        "run-risk-budgeted-carry-shadow",
        help="Run one atomic, public-data-only V14 shadow cycle.",
    )
    carry_shadow_runner_parser.add_argument("--output-root", required=True)
    carry_shadow_runner_parser.add_argument("--journal", required=True)
    carry_shadow_runner_parser.add_argument("--health", required=True)
    carry_shadow_runner_parser.add_argument("--lock", required=True)
    carry_shadow_runner_parser.add_argument(
        "--history-days", type=int, default=264
    )
    carry_shadow_runner_parser.add_argument(
        "--initial-capital", type=float, default=10_000.0
    )
    carry_shadow_runner_parser.add_argument(
        "--cost-stress-multiplier", type=float, default=3.0
    )
    carry_shadow_runner_parser.add_argument(
        "--max-overlay-fraction", type=float, default=0.20
    )
    carry_shadow_runner_parser.add_argument(
        "--rebalance-weekday-utc", type=int, default=6
    )
    carry_shadow_runner_parser.add_argument(
        "--as-of-date", help="Fully closed UTC day, YYYY-MM-DD."
    )
    carry_shadow_runner_parser.add_argument(
        "--catch-up-max-days",
        type=int,
        default=0,
        help="Sequentially recover at most this many missing days.",
    )

    microstructure_parser = subparsers.add_parser(
        "run-forward-market-observer",
        help=(
            "Append one public-data-only KuCoin funding, basis and "
            "microstructure observation."
        ),
    )
    microstructure_parser.add_argument("--journal", required=True)
    microstructure_parser.add_argument("--health", required=True)
    microstructure_parser.add_argument("--lock", required=True)
    microstructure_parser.add_argument("--archive-root")
    microstructure_parser.add_argument(
        "--interval-minutes", type=int, default=15
    )
    microstructure_parser.add_argument(
        "--timeout-seconds", type=float, default=30.0
    )
    microstructure_parser.add_argument(
        "--maximum-collection-seconds", type=float, default=300.0
    )

    scalping_observer_parser = subparsers.add_parser(
        "run-scalping-observer",
        help=(
            "Stream public KuCoin BTC Futures Level 5 and trades into "
            "a research-only SQLite journal."
        ),
    )
    scalping_observer_parser.add_argument("--database", required=True)
    scalping_observer_parser.add_argument("--health", required=True)
    scalping_observer_parser.add_argument(
        "--symbol", default=scalping_observer_module.DEFAULT_SYMBOL
    )
    scalping_observer_parser.add_argument(
        "--health-interval-seconds", type=float, default=5.0
    )
    scalping_observer_parser.add_argument(
        "--commit-interval-seconds", type=float, default=1.0
    )
    scalping_observer_parser.add_argument(
        "--stale-book-seconds", type=float, default=5.0
    )
    scalping_observer_parser.add_argument(
        "--startup-timeout-seconds", type=float, default=30.0
    )
    scalping_observer_parser.add_argument(
        "--run-seconds",
        type=float,
        help="Stop cleanly after N seconds; intended for diagnostics.",
    )

    forward_evidence_parser = subparsers.add_parser(
        "evaluate-forward-market-evidence",
        help=(
            "Audit append-only forward market coverage and strategy "
            "development readiness."
        ),
    )
    forward_evidence_parser.add_argument("--journal", required=True)
    forward_evidence_parser.add_argument("--output", required=True)

    forward_carry_dataset_parser = subparsers.add_parser(
        "build-forward-carry-dataset",
        help=(
            "Build execution-aware carry labels only after the frozen "
            "forward readiness gate passes."
        ),
    )
    forward_carry_dataset_parser.add_argument("--journal", required=True)
    forward_carry_dataset_parser.add_argument("--evidence", required=True)
    forward_carry_dataset_parser.add_argument("--output", required=True)
    forward_carry_dataset_parser.add_argument(
        "--horizon-hour", action="append", type=int, default=None
    )
    forward_carry_dataset_parser.add_argument(
        "--leg-quote", type=float, default=1_000.0
    )

    shadow_performance_parser = subparsers.add_parser(
        "evaluate-shadow-performance",
        help="Evaluate forward-only shadow P&L and manual-review gates.",
    )
    shadow_performance_parser.add_argument("--journal", required=True)
    shadow_performance_parser.add_argument("--output", required=True)
    shadow_performance_parser.add_argument(
        "--initial-capital", type=float, default=10_000.0
    )
    shadow_performance_parser.add_argument(
        "--fixed-monthly-amount", type=float, default=25.0
    )
    shadow_performance_parser.add_argument(
        "--strategy",
        help="Fail unless every journal record has this strategy identity.",
    )

    ensemble_parser = subparsers.add_parser(
        "evaluate-ensemble",
        help="Evaluate the pre-registered V4 multi-horizon ensemble.",
    )
    ensemble_parser.add_argument(
        "--futures-collector", action="append", required=True
    )
    ensemble_parser.add_argument(
        "--funding-json", action="append", required=True
    )
    ensemble_parser.add_argument("--output", required=True)
    ensemble_parser.add_argument(
        "--initial-capital", type=float, default=10_000.0
    )
    ensemble_parser.add_argument(
        "--cost-stress-multiplier", type=float, default=3.0
    )

    prefunded_parser = subparsers.add_parser(
        "evaluate-prefunded-income",
        help="Evaluate fixed income blocks fully funded from strategy surplus.",
    )
    prefunded_parser.add_argument(
        "--trend-report", action="append", required=True
    )
    prefunded_parser.add_argument("--strategy", required=True)
    prefunded_parser.add_argument("--output", required=True)
    prefunded_parser.add_argument(
        "--monthly-amount", action="append", type=float, required=True
    )
    prefunded_parser.add_argument(
        "--initial-capital", type=float, default=10_000.0
    )
    prefunded_parser.add_argument("--block-months", type=int, default=12)
    prefunded_parser.add_argument(
        "--horizon-months", type=int, default=120
    )
    prefunded_parser.add_argument(
        "--bootstrap-block-months", type=int, default=6
    )
    prefunded_parser.add_argument("--simulations", type=int, default=10_000)
    prefunded_parser.add_argument(
        "--annual-return-haircut",
        action="append",
        type=float,
        default=None,
    )
    prefunded_parser.add_argument(
        "--random-seed", type=int, default=20_260_723
    )

    feedback_parser = subparsers.add_parser(
        "export-paper-feedback",
        help="Export point-in-time decisions joined to closed paper outcomes.",
    )
    feedback_parser.add_argument("--journal", required=True)
    feedback_parser.add_argument("--output", required=True)
    return parser


def main(arguments: typing.Optional[list[str]] = None) -> int:
    args = create_parser().parse_args(arguments)
    if args.command == "build-dataset":
        return _build_dataset(args)
    if args.command == "relabel-dataset":
        return _relabel_dataset(args)
    if args.command == "run-experiment":
        return _run_experiment(args)
    if args.command == "fetch-funding":
        return _fetch_funding(args)
    if args.command == "fetch-binance-archive":
        return _fetch_binance_archive(args)
    if args.command == "fetch-binance-futures-hourly-archive":
        return _fetch_binance_futures_hourly_archive(args)
    if args.command == "fetch-binance-spot-archive":
        return _fetch_binance_spot_archive(args)
    if args.command == "fetch-kucoin-spot-hourly":
        return _fetch_kucoin_spot_hourly(args)
    if args.command == "fetch-kucoin-futures-hourly":
        return _fetch_kucoin_futures_hourly(args)
    if args.command == "inspect-dataset":
        return _inspect_dataset(args)
    if args.command == "evaluate-experts":
        return _evaluate_experts(args)
    if args.command == "evaluate-carry":
        return _evaluate_carry(args)
    if args.command == "evaluate-carry-overlay":
        return _evaluate_carry_overlay(args)
    if args.command == "evaluate-risk-budgeted-carry-overlay":
        return _evaluate_carry_overlay(args)
    if args.command == "evaluate-cost-aware-carry-overlay":
        return _evaluate_carry_overlay(args)
    if args.command == "evaluate-execution-guarded-carry-overlay":
        return _evaluate_carry_overlay(args)
    if args.command == "evaluate-rotating-cost-aware-carry-overlay":
        return _evaluate_carry_overlay(args)
    if args.command == "audit-v14-robustness":
        return _audit_v14_robustness(args)
    if args.command == "audit-overlay-candidate":
        return _audit_overlay_candidate(args)
    if args.command == "evaluate-trend":
        return _evaluate_trend(args)
    if args.command == "evaluate-trend-meta":
        return _evaluate_trend_meta(args)
    if args.command == "evaluate-relative-value":
        return _evaluate_relative_value(args)
    if args.command == "evaluate-residual-reversal":
        return _evaluate_residual_reversal(args)
    if args.command == "evaluate-strategy-evidence":
        return _evaluate_strategy_evidence(args)
    if args.command == "audit-income-objective":
        return _audit_income_objective(args)
    if args.command == "evaluate-withdrawals":
        return _evaluate_withdrawals(args)
    if args.command == "record-trend-shadow":
        return _record_trend_shadow(args)
    if args.command == "run-trend-shadow":
        return _run_trend_shadow(args)
    if args.command == "run-risk-budgeted-carry-shadow":
        return _run_risk_budgeted_carry_shadow(args)
    if args.command == "run-forward-market-observer":
        return _run_forward_market_observer(args)
    if args.command == "run-scalping-observer":
        return _run_scalping_observer(args)
    if args.command == "evaluate-forward-market-evidence":
        return _evaluate_forward_market_evidence(args)
    if args.command == "build-forward-carry-dataset":
        return _build_forward_carry_dataset(args)
    if args.command == "evaluate-shadow-performance":
        return _evaluate_shadow_performance(args)
    if args.command == "evaluate-ensemble":
        return _evaluate_ensemble(args)
    if args.command == "evaluate-prefunded-income":
        return _evaluate_prefunded_income(args)
    if args.command == "export-paper-feedback":
        return _export_paper_feedback(args)
    raise ValueError(f"unknown command: {args.command}")


def _build_dataset(args: argparse.Namespace) -> int:
    barriers = dataset_module.BarrierConfig(
        atr_multiplier=args.atr_multiplier,
        reward_risk_ratio=args.reward_risk,
        minimum_stop_pct=args.min_stop_pct,
        maximum_stop_pct=args.max_stop_pct,
        horizon_bars=args.horizon_bars,
        fee_rate_per_fill=args.fee_rate,
        slippage_rate_per_fill=args.slippage_rate,
        funding_rate_per_8h=args.funding_rate_8h,
    )
    config = dataset_module.DatasetBuildConfig(
        barriers=barriers,
        candidate_stride=args.candidate_stride,
    )
    started = time.monotonic()
    funding_rates = (
        funding_module.load_funding(args.funding_json)
        if args.funding_json
        else None
    )
    dataset = dataset_module.build_dataset(
        args.input,
        config,
        funding_rates=funding_rates,
    )
    manifest = dataset_module.save_dataset(
        dataset,
        args.output,
        collector_paths=args.input,
        config=config,
        funding_path=args.funding_json,
    )
    manifest["duration_seconds"] = round(time.monotonic() - started, 3)
    print(json.dumps(_json_safe(manifest), indent=2, sort_keys=True))
    return 0


def _relabel_dataset(args: argparse.Namespace) -> int:
    barriers = dataset_module.BarrierConfig(
        atr_multiplier=args.atr_multiplier,
        reward_risk_ratio=args.reward_risk,
        minimum_stop_pct=args.min_stop_pct,
        maximum_stop_pct=args.max_stop_pct,
        horizon_bars=args.horizon_bars,
        fee_rate_per_fill=args.fee_rate,
        slippage_rate_per_fill=args.slippage_rate,
        funding_rate_per_8h=args.funding_rate_8h,
    )
    base_path = pathlib.Path(args.base_dataset).resolve()
    base = dataset_module.load_dataset(base_path)
    funding_rates = (
        funding_module.load_funding(args.funding_json)
        if args.funding_json
        else None
    )
    started = time.monotonic()
    dataset = dataset_module.relabel_dataset(
        base,
        args.input,
        barriers,
        funding_rates=funding_rates,
    )
    config = dataset_module.DatasetBuildConfig(
        barriers=barriers,
        candidate_stride=4,
    )
    manifest = dataset_module.save_dataset(
        dataset,
        args.output,
        collector_paths=args.input,
        config=config,
        funding_path=args.funding_json,
    )
    manifest["base_dataset"] = {
        "path": str(base_path),
        "sha256": _sha256(base_path),
    }
    manifest["duration_seconds"] = round(time.monotonic() - started, 3)
    manifest_path = pathlib.Path(args.output).resolve().with_suffix(
        pathlib.Path(args.output).suffix + ".manifest.json"
    )
    manifest_path.write_text(
        json.dumps(_json_safe(manifest), indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    print(json.dumps(_json_safe(manifest), indent=2, sort_keys=True))
    return 0


def _fetch_funding(args: argparse.Namespace) -> int:
    mapping = {}
    for value in args.symbol:
        if "=" not in value:
            raise ValueError(f"invalid symbol mapping: {value}")
        octobot_symbol, kucoin_symbol = value.rsplit("=", 1)
        if not octobot_symbol or not kucoin_symbol:
            raise ValueError(f"invalid symbol mapping: {value}")
        mapping[octobot_symbol] = kucoin_symbol
    payload = funding_module.fetch_kucoin_funding(
        mapping,
        funding_module.parse_utc_date(args.from_date),
        funding_module.parse_utc_date(args.to_date, end_of_day=True),
    )
    artifact = funding_module.save_funding(payload, args.output)
    print(json.dumps(artifact, indent=2, sort_keys=True))
    return 0


def _parse_symbol_mapping(values: list[str]) -> dict[str, str]:
    mapping = {}
    for value in values:
        if "=" not in value:
            raise ValueError(f"invalid symbol mapping: {value}")
        octobot_symbol, remote_symbol = value.rsplit("=", 1)
        if not octobot_symbol or not remote_symbol:
            raise ValueError(f"invalid symbol mapping: {value}")
        mapping[octobot_symbol] = remote_symbol
    return mapping


def _fetch_binance_archive(args: argparse.Namespace) -> int:
    result = market_data_module.fetch_binance_archive(
        market_data_module.BinanceArchiveConfig(
            symbol_mapping=_parse_symbol_mapping(args.symbol),
            start_date=market_data_module.parse_date(args.from_date),
            end_date=market_data_module.parse_date(args.to_date),
        ),
        args.output,
        funding_output_value=args.funding_output,
        cache_value=args.cache,
        candle_interval=args.candle_interval,
    )
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0


def _fetch_binance_futures_hourly_archive(args: argparse.Namespace) -> int:
    result = market_data_module.fetch_binance_archive(
        market_data_module.BinanceArchiveConfig(
            symbol_mapping=_parse_symbol_mapping(args.symbol),
            start_date=market_data_module.parse_date(args.from_date),
            end_date=market_data_module.parse_date(args.to_date),
            allowed_15m_gaps=args.allowed_hourly_gaps,
        ),
        args.output,
        funding_output_value=args.funding_output,
        cache_value=args.cache,
        market_type="futures_um",
        candle_interval="1h",
    )
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0


def _fetch_binance_spot_archive(args: argparse.Namespace) -> int:
    result = market_data_module.fetch_binance_archive(
        market_data_module.BinanceArchiveConfig(
            symbol_mapping=_parse_symbol_mapping(args.symbol),
            start_date=market_data_module.parse_date(args.from_date),
            end_date=market_data_module.parse_date(args.to_date),
            allowed_15m_gaps=args.allowed_15m_gaps,
        ),
        args.output,
        cache_value=args.cache,
        market_type="spot",
    )
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0


def _fetch_kucoin_spot_hourly(args: argparse.Namespace) -> int:
    result = market_data_module.fetch_kucoin_spot_hourly(
        market_data_module.BinanceArchiveConfig(
            symbol_mapping=_parse_symbol_mapping(args.symbol),
            start_date=market_data_module.parse_date(args.from_date),
            end_date=market_data_module.parse_date(args.to_date),
            allowed_15m_gaps=args.allowed_hourly_gaps,
        ),
        args.output,
    )
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0


def _fetch_kucoin_futures_hourly(args: argparse.Namespace) -> int:
    result = market_data_module.fetch_kucoin_futures_hourly(
        market_data_module.BinanceArchiveConfig(
            symbol_mapping=_parse_symbol_mapping(args.symbol),
            start_date=market_data_module.parse_date(args.from_date),
            end_date=market_data_module.parse_date(args.to_date),
            allowed_15m_gaps=args.allowed_hourly_gaps,
        ),
        args.output,
        candle_interval=args.candle_interval,
    )
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0


def _evaluate_experts(args: argparse.Namespace) -> int:
    dataset_path = pathlib.Path(args.dataset).resolve()
    dataset = dataset_module.load_dataset(dataset_path)
    report = experts_module.evaluate_experts(
        dataset,
        position_fraction=args.position_fraction,
        folds=args.folds,
    )
    report["dataset"] = {
        "path": str(dataset_path),
        "sha256": _sha256(dataset_path),
    }
    report["created_at"] = datetime.datetime.now(
        datetime.timezone.utc
    ).isoformat()
    output = pathlib.Path(args.output).resolve()
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(
        json.dumps(_json_safe(report), indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    print(json.dumps({
        "path": str(output),
        "experts": {
            name: {
                "trades": value["trades"],
                "total_return": value["total_return"],
                "profit_factor": value["profit_factor"],
                "positive_month_ratio": value["calendar"]["positive_month_ratio"],
            }
            for name, value in report["experts"].items()
        },
        "combined_union": {
            "trades": report["combined_union"]["trades"],
            "total_return": report["combined_union"]["total_return"],
            "profit_factor": report["combined_union"]["profit_factor"],
            "positive_month_ratio": report["combined_union"]["calendar"]["positive_month_ratio"],
        },
    }, indent=2, sort_keys=True))
    return 0


def _evaluate_carry(args: argparse.Namespace) -> int:
    report = carry_module.evaluate_carry(
        args.futures_collector,
        args.spot_collector,
        args.funding_json,
        initial_capital=args.initial_capital,
        cost_stress_multiplier=args.cost_stress_multiplier,
    )
    report["created_at"] = datetime.datetime.now(
        datetime.timezone.utc
    ).isoformat()
    report["inputs"] = {
        "futures_collectors": [
            {
                "path": str(pathlib.Path(path).resolve()),
                "sha256": _sha256(pathlib.Path(path).resolve()),
            }
            for path in args.futures_collector
        ],
        "spot_collector": {
            "path": str(pathlib.Path(args.spot_collector).resolve()),
            "sha256": _sha256(pathlib.Path(args.spot_collector).resolve()),
        },
        "funding": {
            "path": str(pathlib.Path(args.funding_json).resolve()),
            "sha256": _sha256(pathlib.Path(args.funding_json).resolve()),
        },
    }
    output = pathlib.Path(args.output).resolve()
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(
        json.dumps(_json_safe(report), indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    print(
        json.dumps(
            {
                "path": str(output),
                "reports": {
                    name: {
                        key: value[key]
                        for key in (
                            "trades",
                            "total_return",
                            "annualized_return",
                            "profit_factor",
                            "max_drawdown",
                            "positive_month_ratio",
                            "median_month_income",
                        )
                    }
                    for name, value in report["reports"].items()
                },
            },
            indent=2,
            sort_keys=True,
        )
    )
    return 0


def _evaluate_carry_overlay(args: argparse.Namespace) -> int:
    if args.command == "evaluate-risk-budgeted-carry-overlay":
        evaluator = (
            carry_overlay_module.evaluate_risk_budgeted_carry_overlay
        )
    elif args.command == "evaluate-cost-aware-carry-overlay":
        evaluator = carry_overlay_module.evaluate_cost_aware_carry_overlay
    elif args.command == "evaluate-execution-guarded-carry-overlay":
        evaluator = (
            carry_overlay_module.evaluate_execution_guarded_carry_overlay
        )
    elif args.command == "evaluate-rotating-cost-aware-carry-overlay":
        evaluator = (
            carry_overlay_module.evaluate_rotating_cost_aware_carry_overlay
        )
    else:
        evaluator = carry_overlay_module.evaluate_carry_overlay
    scenario_arguments = {}
    if args.command == "evaluate-risk-budgeted-carry-overlay":
        scenario_arguments = {
            "positive_funding_realization": (
                args.positive_funding_realization
            ),
            "entry_delay_settlements": args.entry_delay_settlements,
        }
    elif args.command in (
        "evaluate-cost-aware-carry-overlay",
        "evaluate-execution-guarded-carry-overlay",
        "evaluate-rotating-cost-aware-carry-overlay",
    ):
        scenario_arguments = {
            "positive_funding_realization": (
                args.positive_funding_realization
            ),
        }
    report = evaluator(
        args.futures_collector,
        args.spot_collector,
        args.funding_json,
        initial_capital=args.initial_capital,
        trend_cost_stress_multiplier=(
            args.trend_cost_stress_multiplier
        ),
        carry_cost_stress_multiplier=(
            args.carry_cost_stress_multiplier
        ),
        max_overlay_fraction=args.max_overlay_fraction,
        **scenario_arguments,
    )
    report["created_at"] = datetime.datetime.now(
        datetime.timezone.utc
    ).isoformat()
    report["inputs"] = {
        "futures_collectors": [
            {
                "path": str(pathlib.Path(path).resolve()),
                "sha256": _sha256(pathlib.Path(path).resolve()),
            }
            for path in args.futures_collector
        ],
        "spot_collector": {
            "path": str(pathlib.Path(args.spot_collector).resolve()),
            "sha256": _sha256(
                pathlib.Path(args.spot_collector).resolve()
            ),
        },
        "funding": [
            {
                "path": str(pathlib.Path(path).resolve()),
                "sha256": _sha256(pathlib.Path(path).resolve()),
            }
            for path in args.funding_json
        ],
    }
    output = pathlib.Path(args.output).resolve()
    shadow_runner_module._write_json_atomic(output, _json_safe(report))
    print(
        json.dumps(
            {
                "path": str(output),
                "reports": {
                    name: {
                        key: values.get(key)
                        for key in (
                            "annualized_return",
                            "max_drawdown",
                            "sharpe_zero_rate",
                            "positive_month_ratio",
                            "worst_rolling_12_month_return",
                            "average_overlay_allocation",
                            "maximum_conservative_gross_exposure",
                        )
                    }
                    for name, values in report["reports"].items()
                },
            },
            indent=2,
            sort_keys=True,
        )
    )
    return 0


def _audit_v14_robustness(args: argparse.Namespace) -> int:
    report = carry_robustness_module.audit_v14_robustness(
        half_old_report=args.half_old_report,
        half_recent_report=args.half_recent_report,
        half_kucoin_report=args.half_kucoin_report,
        half_evidence=args.half_evidence,
        half_prefunded=args.half_prefunded,
        zero_old_report=args.zero_old_report,
        zero_recent_report=args.zero_recent_report,
        zero_kucoin_report=args.zero_kucoin_report,
        zero_evidence=args.zero_evidence,
        zero_prefunded=args.zero_prefunded,
    )
    output = pathlib.Path(args.output).resolve()
    shadow_runner_module._write_json_atomic(output, _json_safe(report))
    print(
        json.dumps(
            {
                "path": str(output),
                "robustness_gate": report["robustness_gate"],
                "zero_positive_funding_diagnostic": {
                    "edge_gate": report[
                        "zero_positive_funding_diagnostic"
                    ]["edge_gate"],
                    "income_gate": report[
                        "zero_positive_funding_diagnostic"
                    ]["income_gate"],
                },
            },
            indent=2,
            sort_keys=True,
        )
    )
    return 0


def _audit_overlay_candidate(args: argparse.Namespace) -> int:
    report = carry_robustness_module.audit_overlay_candidate(
        candidate_name=args.candidate_name,
        stress_name=args.stress_name,
        baseline_old_report=args.baseline_old_report,
        baseline_recent_report=args.baseline_recent_report,
        baseline_kucoin_report=args.baseline_kucoin_report,
        stress_old_report=args.stress_old_report,
        stress_recent_report=args.stress_recent_report,
        stress_kucoin_report=args.stress_kucoin_report,
        stress_evidence=args.stress_evidence,
        stress_prefunded=args.stress_prefunded,
    )
    output = pathlib.Path(args.output).resolve()
    shadow_runner_module._write_json_atomic(output, _json_safe(report))
    print(
        json.dumps(
            {
                "path": str(output),
                "candidate_gate": report["candidate_gate"],
                "baseline": {
                    "passed": report["baseline"]["passed"],
                    "checks": report["baseline"]["checks"],
                },
                "adverse_stress": {
                    "passed": report["adverse_stress"]["passed"],
                    "checks": report["adverse_stress"]["checks"],
                },
            },
            indent=2,
            sort_keys=True,
        )
    )
    return 0


def _evaluate_trend(args: argparse.Namespace) -> int:
    report = trend_module.evaluate_trend(
        args.futures_collector,
        args.funding_json,
        initial_capital=args.initial_capital,
        cost_stress_multiplier=args.cost_stress_multiplier,
        config_names=args.strategy,
        include_leave_one_asset_out=not args.skip_leave_one_asset_out,
    )
    report["created_at"] = datetime.datetime.now(
        datetime.timezone.utc
    ).isoformat()
    report["inputs"] = {
        "futures_collectors": [
            {
                "path": str(pathlib.Path(path).resolve()),
                "sha256": _sha256(pathlib.Path(path).resolve()),
            }
            for path in args.futures_collector
        ],
        "funding": [
            {
                "path": str(pathlib.Path(path).resolve()),
                "sha256": _sha256(pathlib.Path(path).resolve()),
            }
            for path in args.funding_json
        ],
    }
    output = pathlib.Path(args.output).resolve()
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(
        json.dumps(_json_safe(report), indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    print(
        json.dumps(
            {
                "path": str(output),
                "reports": {
                    name: {
                        key: value[key]
                        for key in (
                            "total_return",
                            "annualized_return",
                            "max_drawdown",
                            "annualized_volatility",
                            "sharpe_zero_rate",
                            "positive_month_ratio",
                        )
                    }
                    for name, value in report["reports"].items()
                },
            },
            indent=2,
            sort_keys=True,
        )
    )
    return 0


def _evaluate_trend_meta(args: argparse.Namespace) -> int:
    report = trend_meta_module.evaluate_trend_meta(
        args.futures_collector,
        args.funding_json,
        initial_capital=args.initial_capital,
        cost_stress_multiplier=args.cost_stress_multiplier,
    )
    report["created_at"] = datetime.datetime.now(
        datetime.timezone.utc
    ).isoformat()
    report["inputs"] = {
        "futures_collectors": [
            {
                "path": str(pathlib.Path(path).resolve()),
                "sha256": _sha256(pathlib.Path(path).resolve()),
            }
            for path in args.futures_collector
        ],
        "funding": [
            {
                "path": str(pathlib.Path(path).resolve()),
                "sha256": _sha256(pathlib.Path(path).resolve()),
            }
            for path in args.funding_json
        ],
    }
    output = pathlib.Path(args.output).resolve()
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(
        json.dumps(_json_safe(report), indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    print(
        json.dumps(
            {
                "path": str(output),
                "accepted_setups": report["walk_forward"][
                    "accepted_setups"
                ],
                "reports": {
                    name: {
                        key: values[key]
                        for key in (
                            "annualized_return",
                            "max_drawdown",
                            "sharpe_zero_rate",
                            "positive_month_ratio",
                            "total_return",
                        )
                    }
                    for name, values in report["reports"].items()
                },
            },
            indent=2,
            sort_keys=True,
        )
    )
    return 0


def _evaluate_relative_value(args: argparse.Namespace) -> int:
    report = relative_value_module.evaluate_relative_value(
        args.futures_collector,
        args.funding_json,
        initial_capital=args.initial_capital,
        cost_stress_multiplier=args.cost_stress_multiplier,
    )
    report["created_at"] = datetime.datetime.now(
        datetime.timezone.utc
    ).isoformat()
    report["inputs"] = {
        "futures_collectors": [
            {
                "path": str(pathlib.Path(path).resolve()),
                "sha256": _sha256(pathlib.Path(path).resolve()),
            }
            for path in args.futures_collector
        ],
        "funding": [
            {
                "path": str(pathlib.Path(path).resolve()),
                "sha256": _sha256(pathlib.Path(path).resolve()),
            }
            for path in args.funding_json
        ],
    }
    output = pathlib.Path(args.output).resolve()
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(
        json.dumps(_json_safe(report), indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    print(
        json.dumps(
            {
                "path": str(output),
                "reports": {
                    name: {
                        key: values.get(key)
                        for key in (
                            "annualized_return",
                            "max_drawdown",
                            "sharpe_zero_rate",
                            "positive_month_ratio",
                            "worst_rolling_12_month_return",
                            "daily_return_correlation",
                        )
                    }
                    for name, values in report["reports"].items()
                },
            },
            indent=2,
            sort_keys=True,
        )
    )
    return 0


def _evaluate_residual_reversal(args: argparse.Namespace) -> int:
    report = relative_value_module.evaluate_residual_reversal(
        args.futures_collector,
        args.funding_json,
        initial_capital=args.initial_capital,
        cost_stress_multiplier=args.cost_stress_multiplier,
    )
    report["created_at"] = datetime.datetime.now(
        datetime.timezone.utc
    ).isoformat()
    report["inputs"] = {
        "futures_collectors": [
            {
                "path": str(pathlib.Path(path).resolve()),
                "sha256": _sha256(pathlib.Path(path).resolve()),
            }
            for path in args.futures_collector
        ],
        "funding": [
            {
                "path": str(pathlib.Path(path).resolve()),
                "sha256": _sha256(pathlib.Path(path).resolve()),
            }
            for path in args.funding_json
        ],
    }
    output = pathlib.Path(args.output).resolve()
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(
        json.dumps(_json_safe(report), indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    print(
        json.dumps(
            {
                "path": str(output),
                "reports": {
                    name: {
                        key: values.get(key)
                        for key in (
                            "annualized_return",
                            "max_drawdown",
                            "sharpe_zero_rate",
                            "positive_month_ratio",
                            "worst_rolling_12_month_return",
                            "daily_return_correlation",
                        )
                    }
                    for name, values in report["reports"].items()
                },
            },
            indent=2,
            sort_keys=True,
        )
    )
    return 0


def _evaluate_strategy_evidence(args: argparse.Namespace) -> int:
    report = strategy_evidence_module.evaluate_strategy_evidence(
        args.trend_report,
        args.strategy,
        initial_capital=args.initial_capital,
        horizons=(
            args.horizon_months
            if args.horizon_months is not None
            else strategy_evidence_module.DEFAULT_HORIZONS
        ),
        block_months=args.block_months,
        simulations=args.simulations,
        annual_return_haircuts=(
            args.annual_return_haircut
            if args.annual_return_haircut is not None
            else strategy_evidence_module.DEFAULT_HAIRCUTS
        ),
        random_seed=args.random_seed,
    )
    report["created_at"] = datetime.datetime.now(
        datetime.timezone.utc
    ).isoformat()
    report["inputs"] = [
        {
            "path": str(pathlib.Path(path).resolve()),
            "sha256": _sha256(pathlib.Path(path).resolve()),
        }
        for path in args.trend_report
    ]
    output = pathlib.Path(args.output).resolve()
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(
        json.dumps(_json_safe(report), indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    print(
        json.dumps(
            {
                "path": str(output),
                "winning_edge_evidence_gate": report[
                    "winning_edge_evidence_gate"
                ],
                "five_percent_haircut": {
                    horizon: {
                        "probability_non_loss": values[
                            "probability_final_at_or_above_initial"
                        ],
                        "median_annualized_return": values[
                            "annualized_return_percentiles"
                        ]["p50"],
                        "p90_max_drawdown": values[
                            "max_drawdown_percentiles"
                        ]["p90"],
                    }
                    for horizon, values in report["scenarios"][
                        "5.00%"
                    ]["horizons"].items()
                },
            },
            indent=2,
            sort_keys=True,
        )
    )
    return 0


def _audit_income_objective(args: argparse.Namespace) -> int:
    report = income_objective_module.audit_income_objective(
        args.strategy_evidence,
        args.prefunded_research,
        args.shadow_performance,
        monthly_amount=args.monthly_amount,
        robustness_research_path=args.robustness_research,
    )
    report["created_at"] = datetime.datetime.now(
        datetime.timezone.utc
    ).isoformat()
    output = pathlib.Path(args.output).resolve()
    shadow_runner_module._write_json_atomic(output, _json_safe(report))
    print(
        json.dumps(
            {
                "path": str(output),
                "status": report["status"],
                "achieved": report["achieved"],
                "checks": report["checks"],
                "simulated_prefunded_monthly_income": report[
                    "simulated_prefunded_monthly_income"
                ],
                "simulated_guaranteed_payments_remaining": report[
                    "simulated_guaranteed_payments_remaining"
                ],
                "real_income_authorized": report[
                    "real_income_authorized"
                ],
            },
            indent=2,
            sort_keys=True,
        )
    )
    return 0


def _evaluate_withdrawals(args: argparse.Namespace) -> int:
    report = withdrawal_module.evaluate_withdrawals(
        args.trend_report,
        args.strategy,
        initial_capital=args.initial_capital,
        monthly_amounts=args.monthly_amount,
        warmup_months=args.warmup_months,
        horizon_months=args.horizon_months,
        block_months=args.block_months,
        simulations=args.simulations,
        safety_floor_fraction=args.safety_floor_fraction,
        annual_return_haircuts=(
            args.annual_return_haircut
            if args.annual_return_haircut is not None
            else withdrawal_module.DEFAULT_HAIRCUTS
        ),
        random_seed=args.random_seed,
    )
    report["created_at"] = datetime.datetime.now(
        datetime.timezone.utc
    ).isoformat()
    report["inputs"] = [
        {
            "path": str(pathlib.Path(path).resolve()),
            "sha256": _sha256(pathlib.Path(path).resolve()),
        }
        for path in args.trend_report
    ]
    output = pathlib.Path(args.output).resolve()
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(
        json.dumps(_json_safe(report), indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    summary = {}
    for scenario, values in report["scenarios"].items():
        summary[scenario] = {
            amount: {
                "all_payments": results["bootstrap"][
                    "probability_all_payments_made"
                ],
                "mean_coverage": results["bootstrap"][
                    "mean_payment_coverage"
                ],
                "final_at_or_above_initial": results["bootstrap"][
                    "probability_final_at_or_above_initial"
                ],
            }
            for amount, results in values["amounts"].items()
        }
    print(
        json.dumps(
            {"path": str(output), "scenarios": summary},
            indent=2,
            sort_keys=True,
        )
    )
    return 0


def _record_trend_shadow(args: argparse.Namespace) -> int:
    result = shadow_module.record_trend_shadow(
        args.trend_report,
        args.strategy,
        args.journal,
    )
    print(json.dumps(_json_safe(result), indent=2, sort_keys=True))
    return 0


def _run_trend_shadow(args: argparse.Namespace) -> int:
    as_of = (
        market_data_module.parse_date(args.as_of_date)
        if args.as_of_date
        else None
    )
    if as_of is not None and args.catch_up_max_days:
        raise ValueError("--as-of-date and --catch-up-max-days are exclusive")
    config = shadow_runner_module.ShadowRunnerConfig(
        output_root=pathlib.Path(args.output_root).resolve(),
        journal_path=pathlib.Path(args.journal).resolve(),
        health_path=pathlib.Path(args.health).resolve(),
        lock_path=pathlib.Path(args.lock).resolve(),
        history_days=args.history_days,
        initial_capital=args.initial_capital,
        cost_stress_multiplier=args.cost_stress_multiplier,
        strategy_name=args.strategy,
        rebalance_weekday_utc=args.rebalance_weekday_utc,
    )
    result = (
        shadow_runner_module.run_shadow_catchup(
            config,
            max_catchup_days=args.catch_up_max_days,
        )
        if args.catch_up_max_days
        else shadow_runner_module.run_shadow_once(
            config, as_of_date=as_of
        )
    )
    print(json.dumps(_json_safe(result), indent=2, sort_keys=True))
    return 0


def _run_risk_budgeted_carry_shadow(
    args: argparse.Namespace,
) -> int:
    as_of = (
        market_data_module.parse_date(args.as_of_date)
        if args.as_of_date
        else None
    )
    if as_of is not None and args.catch_up_max_days:
        raise ValueError("--as-of-date and --catch-up-max-days are exclusive")
    config = carry_shadow_runner_module.CarryShadowRunnerConfig(
        output_root=pathlib.Path(args.output_root).resolve(),
        journal_path=pathlib.Path(args.journal).resolve(),
        health_path=pathlib.Path(args.health).resolve(),
        lock_path=pathlib.Path(args.lock).resolve(),
        history_days=args.history_days,
        initial_capital=args.initial_capital,
        cost_stress_multiplier=args.cost_stress_multiplier,
        max_overlay_fraction=args.max_overlay_fraction,
        rebalance_weekday_utc=args.rebalance_weekday_utc,
    )
    result = (
        carry_shadow_runner_module.run_shadow_catchup(
            config,
            max_catchup_days=args.catch_up_max_days,
        )
        if args.catch_up_max_days
        else carry_shadow_runner_module.run_shadow_once(
            config, as_of_date=as_of
        )
    )
    print(json.dumps(_json_safe(result), indent=2, sort_keys=True))
    return 0


def _run_forward_market_observer(args: argparse.Namespace) -> int:
    result = microstructure_module.run_observation_once(
        microstructure_module.MicrostructureConfig(
            journal_path=pathlib.Path(args.journal).resolve(),
            health_path=pathlib.Path(args.health).resolve(),
            lock_path=pathlib.Path(args.lock).resolve(),
            archive_root=(
                pathlib.Path(args.archive_root).resolve()
                if args.archive_root
                else None
            ),
            interval_minutes=args.interval_minutes,
            timeout_seconds=args.timeout_seconds,
            maximum_collection_seconds=args.maximum_collection_seconds,
        )
    )
    print(json.dumps(_json_safe(result), indent=2, sort_keys=True))
    return 0


def _run_scalping_observer(args: argparse.Namespace) -> int:
    result = scalping_observer_module.run(
        scalping_observer_module.ScalpingObserverConfig(
            database_path=pathlib.Path(args.database).resolve(),
            health_path=pathlib.Path(args.health).resolve(),
            symbol=args.symbol,
            health_interval_seconds=args.health_interval_seconds,
            commit_interval_seconds=args.commit_interval_seconds,
            stale_book_seconds=args.stale_book_seconds,
            startup_timeout_seconds=args.startup_timeout_seconds,
            run_seconds=args.run_seconds,
        )
    )
    print(json.dumps(_json_safe(result), indent=2, sort_keys=True))
    return 0


def _evaluate_forward_market_evidence(
    args: argparse.Namespace,
) -> int:
    report = forward_evidence_module.evaluate_forward_market_evidence(
        args.journal
    )
    output = pathlib.Path(args.output).resolve()
    shadow_runner_module._write_json_atomic(output, _json_safe(report))
    print(
        json.dumps(
            {
                "path": str(output),
                "strategy_development_ready": report[
                    "strategy_development_ready"
                ],
                "checks": report["checks"],
                "observed_buckets": report["journal"][
                    "observed_buckets"
                ],
                "expected_buckets": report["journal"][
                    "expected_buckets"
                ],
                "coverage": report["journal"]["coverage"],
                "minimum_settled_funding_points": report[
                    "settled_funding"
                ]["minimum_unique_points"],
                "readiness_progress": report["readiness_progress"],
            },
            indent=2,
            sort_keys=True,
        )
    )
    return 0


def _build_forward_carry_dataset(args: argparse.Namespace) -> int:
    dataset = forward_carry_dataset_module.build_forward_carry_dataset(
        args.journal,
        args.evidence,
        horizon_hours=(
            args.horizon_hour
            if args.horizon_hour is not None
            else forward_carry_dataset_module.DEFAULT_HORIZON_HOURS
        ),
        leg_quote=args.leg_quote,
    )
    manifest = (
        forward_carry_dataset_module.save_forward_carry_dataset(
            dataset, args.output
        )
    )
    print(
        json.dumps(
            {
                "path": manifest["output"]["path"],
                "sha256": manifest["output"]["sha256"],
                "rows": manifest["row_count"],
                "horizon_hours": manifest["horizon_hours"],
                "leg_quote": manifest["leg_quote"],
                "exclusions": manifest["exclusions"],
                "orders_authorized": manifest["orders_authorized"],
            },
            indent=2,
            sort_keys=True,
        )
    )
    return 0


def _evaluate_shadow_performance(args: argparse.Namespace) -> int:
    report = shadow_performance_module.evaluate_shadow_performance(
        args.journal,
        initial_capital=args.initial_capital,
        fixed_monthly_amount=args.fixed_monthly_amount,
        expected_strategy_name=args.strategy,
    )
    output = pathlib.Path(args.output).resolve()
    shadow_runner_module._write_json_atomic(output, _json_safe(report))
    print(
        json.dumps(
            {
                "path": str(output),
                "observed_return_days": report["observed_return_days"],
                "paper_review_gate": report["paper_review_gate"],
                "income_evidence_gate": report["income_evidence_gate"],
            },
            indent=2,
            sort_keys=True,
        )
    )
    return 0


def _evaluate_ensemble(args: argparse.Namespace) -> int:
    report = ensemble_module.evaluate_ensemble(
        args.futures_collector,
        args.funding_json,
        initial_capital=args.initial_capital,
        cost_stress_multiplier=args.cost_stress_multiplier,
    )
    report["created_at"] = datetime.datetime.now(
        datetime.timezone.utc
    ).isoformat()
    report["inputs"] = {
        "futures_collectors": [
            {
                "path": str(pathlib.Path(path).resolve()),
                "sha256": _sha256(pathlib.Path(path).resolve()),
            }
            for path in args.futures_collector
        ],
        "funding": [
            {
                "path": str(pathlib.Path(path).resolve()),
                "sha256": _sha256(pathlib.Path(path).resolve()),
            }
            for path in args.funding_json
        ],
    }
    output = pathlib.Path(args.output).resolve()
    shadow_runner_module._write_json_atomic(output, _json_safe(report))
    print(
        json.dumps(
            {
                "path": str(output),
                "reports": {
                    name: {
                        key: value.get(key)
                        for key in (
                            "annualized_return",
                            "max_drawdown",
                            "sharpe_zero_rate",
                            "positive_month_ratio",
                            "worst_rolling_12_month_return",
                        )
                    }
                    for name, value in report["reports"].items()
                },
            },
            indent=2,
            sort_keys=True,
        )
    )
    return 0


def _evaluate_prefunded_income(args: argparse.Namespace) -> int:
    report = prefunded_income_module.evaluate_prefunded_income(
        args.trend_report,
        args.strategy,
        initial_capital=args.initial_capital,
        monthly_amounts=args.monthly_amount,
        block_months=args.block_months,
        horizon_months=args.horizon_months,
        bootstrap_block_months=args.bootstrap_block_months,
        simulations=args.simulations,
        annual_return_haircuts=(
            args.annual_return_haircut
            if args.annual_return_haircut is not None
            else prefunded_income_module.DEFAULT_HAIRCUTS
        ),
        random_seed=args.random_seed,
    )
    report["created_at"] = datetime.datetime.now(
        datetime.timezone.utc
    ).isoformat()
    report["inputs"] = [
        {
            "path": str(pathlib.Path(path).resolve()),
            "sha256": _sha256(pathlib.Path(path).resolve()),
        }
        for path in args.trend_report
    ]
    output = pathlib.Path(args.output).resolve()
    shadow_runner_module._write_json_atomic(output, _json_safe(report))
    summary = {
        haircut: {
            amount: {
                (
                    "first_block_"
                    f"{values['operational_gate']['first_block_horizon_months']}"
                    "m"
                ): values["bootstrap"][
                    "probability_first_block_within_"
                    f"{values['operational_gate']['first_block_horizon_months']}"
                    "_months"
                ],
                "no_pause": values["bootstrap"][
                    "conditional_probability_no_pause_after_start"
                ],
                "coverage": values["bootstrap"][
                    "conditional_mean_post_start_coverage"
                ],
                "gate": values["operational_gate"]["passed"],
            }
            for amount, values in scenario["amounts"].items()
        }
        for haircut, scenario in report["scenarios"].items()
    }
    print(
        json.dumps(
            {"path": str(output), "scenarios": summary},
            indent=2,
            sort_keys=True,
        )
    )
    return 0


def _export_paper_feedback(args: argparse.Namespace) -> int:
    report = paper_feedback_module.export_paper_feedback(args.journal)
    output = pathlib.Path(args.output).resolve()
    shadow_runner_module._write_json_atomic(output, _json_safe(report))
    print(
        json.dumps(
            {
                "path": str(output),
                "summary": report["summary"],
                "source_snapshot": report["source"]["snapshot"],
                "feature_count": len(report["feature_schema"]),
            },
            indent=2,
            sort_keys=True,
        )
    )
    return 0


def _run_experiment(args: argparse.Namespace) -> int:
    dataset_path = pathlib.Path(args.dataset).resolve()
    dataset = dataset_module.load_dataset(dataset_path)
    logistic_config = model_module.LogisticConfig(
        epochs=args.epochs,
        batch_size=args.batch_size,
        learning_rate=args.learning_rate,
        l2=args.l2,
        seed=args.seed,
    )
    validation_config = model_module.ValidationConfig(
        folds=args.folds,
        minimum_validation_trades=args.minimum_validation_trades,
        position_fraction=args.position_fraction,
        training_stride=args.training_stride,
    )
    boosting_config = model_module.BoostingConfig(
        trees=args.boosting_trees,
        max_depth=args.boosting_depth,
        bins=args.boosting_bins,
        learning_rate=args.boosting_learning_rate,
        seed=args.seed,
    )
    started = time.monotonic()
    result = model_module.run_experiment(
        dataset,
        logistic_config=logistic_config,
        boosting_config=boosting_config,
        validation_config=validation_config,
        prediction_target=args.prediction_target,
        model_type=args.model,
        locked_block_status=args.locked_block_status,
    )
    duration_seconds = time.monotonic() - started
    artifacts = _save_experiment(
        dataset_path,
        dataset,
        result,
        pathlib.Path(args.output_root).resolve(),
        duration_seconds=duration_seconds,
    )
    summary = {
        "experiment_id": artifacts["experiment_id"],
        "experiment_dir": artifacts["experiment_dir"],
        "duration_seconds": round(duration_seconds, 3),
        "walk_forward": result["walk_forward_aggregate"],
        "locked_test": result["locked_test"],
        "leave_one_asset_out": result["leave_one_asset_out"],
    }
    print(json.dumps(_json_safe(summary), indent=2, sort_keys=True))
    return 0


def _inspect_dataset(args: argparse.Namespace) -> int:
    dataset = dataset_module.load_dataset(args.dataset)
    summary = {
        "rows": len(dataset.label),
        "feature_count": len(dataset.feature_names),
        "symbols": sorted(str(value) for value in numpy.unique(dataset.symbol)),
        "start_timestamp": int(numpy.min(dataset.timestamp)),
        "end_timestamp": int(numpy.max(dataset.timestamp)),
        "target_rate": float(numpy.mean(dataset.label)),
        "profitable_rate": float(numpy.mean(dataset.profitable)),
        "outcomes": {
            "target": int(numpy.sum(dataset.outcome == dataset_module.OUTCOME_TARGET)),
            "stop": int(numpy.sum(dataset.outcome == dataset_module.OUTCOME_STOP)),
            "timeout": int(numpy.sum(dataset.outcome == dataset_module.OUTCOME_TIMEOUT)),
        },
        "average_duration_bars": float(numpy.mean(dataset.duration_bars)),
        "feature_names": list(dataset.feature_names),
    }
    print(json.dumps(summary, indent=2, sort_keys=True))
    return 0


def _save_experiment(
    dataset_path: pathlib.Path,
    dataset: dataset_module.ResearchDataset,
    result: dict,
    output_root: pathlib.Path,
    *,
    duration_seconds: float,
) -> dict:
    output_root.mkdir(parents=True, exist_ok=True)
    dataset_hash = _sha256(dataset_path)
    public_report = model_module.clean_report(result)
    identity_payload = json.dumps(
        {
            "dataset_sha256": dataset_hash,
            "prediction_target": public_report["prediction_target"],
            "model": public_report["model"],
            "locked_block_status": public_report["locked_block_status"],
            "logistic_config": public_report["logistic_config"],
            "boosting_config": public_report["boosting_config"],
            "validation_config": public_report["validation_config"],
        },
        sort_keys=True,
    ).encode("utf-8")
    short_hash = hashlib.sha256(identity_payload).hexdigest()[:12]
    timestamp = datetime.datetime.now(datetime.timezone.utc).strftime(
        "%Y%m%dT%H%M%SZ"
    )
    experiment_id = f"{timestamp}_{short_hash}"
    experiment_dir = output_root / experiment_id
    experiment_dir.mkdir()

    model_path = experiment_dir / "locked_model.npz"
    model_artifact = result["_locked_model"].save(model_path)
    if public_report["model"] == "numpy_gradient_boosting":
        loaded_model = model_module.NumpyGradientBoostingModel.load(model_path)
    else:
        loaded_model = model_module.NumpyLogisticModel.load(model_path)
    selected_indices = result["_locked_selected_indices"]
    reloaded_probabilities = loaded_model.predict_proba(
        dataset.features[selected_indices]
    )
    expected_probabilities = result["_locked_probabilities"]
    if not numpy.allclose(
        reloaded_probabilities,
        expected_probabilities,
        atol=1e-12,
        rtol=1e-10,
    ):
        raise RuntimeError("saved model does not reproduce locked-test probabilities")

    predictions_path = experiment_dir / "locked_predictions.npz"
    numpy.savez_compressed(
        predictions_path,
        indices=selected_indices,
        probabilities=expected_probabilities,
        timestamp=dataset.timestamp[selected_indices],
        exit_timestamp=dataset.exit_timestamp[selected_indices],
        symbol=dataset.symbol[selected_indices],
        direction=dataset.direction[selected_indices],
        net_return=dataset.net_return[selected_indices],
    )
    report_path = experiment_dir / "report.json"
    report_payload = _json_safe(
        {
            **public_report,
            "duration_seconds": round(duration_seconds, 3),
        }
    )
    report_path.write_text(
        json.dumps(report_payload, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )

    manifest = {
        "schema_version": 1,
        "experiment_id": experiment_id,
        "created_at": datetime.datetime.now(datetime.timezone.utc).isoformat(),
        "research_only": True,
        "can_place_orders": False,
        "dataset": {
            "path": str(dataset_path),
            "sha256": dataset_hash,
            "rows": len(dataset.label),
            "feature_schema_sha256": hashlib.sha256(
                "\n".join(dataset.feature_names).encode("utf-8")
            ).hexdigest(),
        },
        "model": model_artifact,
        "predictions": {
            "path": str(predictions_path),
            "sha256": _sha256(predictions_path),
            "rows": int(len(selected_indices)),
        },
        "report": {
            "path": str(report_path),
            "sha256": _sha256(report_path),
        },
        "code": {
            "dataset_schema_version": dataset_module.SCHEMA_VERSION,
            "model_schema_version": model_module.MODEL_SCHEMA_VERSION,
        },
    }
    manifest_path = experiment_dir / "manifest.json"
    manifest_path.write_text(
        json.dumps(manifest, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    registry_entry = {
        "experiment_id": experiment_id,
        "created_at": manifest["created_at"],
        "manifest": str(manifest_path),
        "manifest_sha256": _sha256(manifest_path),
        "dataset_sha256": dataset_hash,
        "locked_test": report_payload["locked_test"],
        "walk_forward_aggregate": report_payload["walk_forward_aggregate"],
    }
    with (output_root / "experiments.jsonl").open("a", encoding="utf-8") as registry:
        registry.write(json.dumps(registry_entry, sort_keys=True) + "\n")
    return {
        "experiment_id": experiment_id,
        "experiment_dir": str(experiment_dir),
    }


def _json_safe(value):
    if isinstance(value, dict):
        return {key: _json_safe(element) for key, element in value.items()}
    if isinstance(value, (list, tuple)):
        return [_json_safe(element) for element in value]
    if isinstance(value, numpy.generic):
        return _json_safe(value.item())
    if isinstance(value, float) and not math.isfinite(value):
        return None
    return value


def _sha256(path: pathlib.Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


if __name__ == "__main__":
    sys.exit(main())
