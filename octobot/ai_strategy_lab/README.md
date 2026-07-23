# OctoBot AI Strategy Lab

Offline research tooling for the guarded paper-trading project.  The lab reads
OctoBot SQLite collector files and writes versioned datasets and experiment
artifacts.  It contains no authenticated exchange client and cannot place
orders. Public historical downloads are research inputs only.

## Research guarantees

- Features at a decision timestamp use only candles already closed at that time.
- Labels start on the following 15-minute candle.
- A candle touching stop and target is classified as a stop.
- ATR stops, reward/risk targets and the time horizon are actually enforced.
- Maker/taker costs, slippage and signed historical funding are explicit inputs.
- Temporal evaluation uses an anchored walk-forward with purge and embargo.
- Thresholds are selected on an inner validation block, never on the outer test.
- Candidate thresholds include fixed economic levels and predeclared inner-block
  probability quantiles, allowing differently calibrated models to be compared.
- The final block is reported separately and models are saved with hashes.
- Leave-one-asset-out reports test whether a model transfers to an unseen symbol.
- Accepted candidates cannot overlap on the same symbol.

These guarantees reduce common backtest errors.  They do not make a strategy
profitable and do not authorize paper or live execution.

## Commands

Run from the repository root:

```bash
python3 -m octobot.ai_strategy_lab fetch-funding \
  --symbol 'BTC/USDT:USDT=XBTUSDTM' \
  --from-date 2025-07-22 \
  --to-date 2026-07-21 \
  --output ../octobot-local/backtesting/research/kucoin_funding.json
```

```bash
python3 -m octobot.ai_strategy_lab fetch-binance-archive \
  --symbol 'BTC/USDT:USDT=BTCUSDT' \
  --symbol 'ETH/USDT:USDT=ETHUSDT' \
  --from-date 2022-01-01 \
  --to-date 2026-06-30 \
  --output ../octobot-local/backtesting/research/binance-um.data \
  --funding-output ../octobot-local/backtesting/research/binance-funding.json
```

This command downloads Binance USD-M monthly public archives, verifies every
official SHA-256 checksum, derives aligned 1h and 4h candles from 15m data, and
writes an OctoBot-compatible SQLite collector. It is intended only to test
whether an idea transfers across venues; the active KuCoin paper profile is not
modified.

```bash
python3 -m octobot.ai_strategy_lab build-dataset \
  --input ../octobot-local/backtesting/data/BTC.data \
  --input ../octobot-local/backtesting/data/ETH.data \
  --funding-json ../octobot-local/backtesting/research/kucoin_funding.json \
  --output ../octobot-local/backtesting/research/dataset.npz
```

```bash
python3 -m octobot.ai_strategy_lab run-experiment \
  --dataset ../octobot-local/backtesting/research/dataset.npz \
  --output-root ../octobot-local/backtesting/research/experiments
```

Frozen deterministic regime experts can be evaluated before any fitted model:

```bash
python3 -m octobot.ai_strategy_lab evaluate-experts \
  --dataset ../octobot-local/backtesting/research/dataset.npz \
  --output ../octobot-local/backtesting/research/experts.json
```

Expert thresholds are versioned constants. Change their version instead of
silently tuning them after observing a report. Calendar metrics include months
with zero trades, which prevents an inactive strategy from appearing to deliver
regular income.

The experiment directory contains a JSON report, a reproducible NumPy model,
the selected locked-test predictions and a manifest with SHA-256 hashes.  The
root `experiments.jsonl` is append-only and records every completed run.

## Interpretation

The initial models are a deterministic logistic regression and a small
histogram gradient boosting implementation, both built only with NumPy so
training and inference do not require a cloud service or a large runtime on
Raspberry Pi.  Their economic reports assume the configured fraction of
portfolio per accepted event.  They are candidate-filter evaluations, not yet
the final shared-margin OctoBot portfolio simulation.

A model is not eligible for shadow mode merely because the locked block is
positive.  It must also be stable across walk-forward folds, transfer to held
out assets, remain positive under cost stress, and pass the project gates in
`spec.md`.
