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

Alternative barrier protocols can reuse the saved point-in-time features:

```bash
python3 -m octobot.ai_strategy_lab relabel-dataset \
  --base-dataset ../octobot-local/backtesting/research/intraday.npz \
  --input ../octobot-local/backtesting/research/binance-um.data \
  --funding-json ../octobot-local/backtesting/research/binance-funding.json \
  --atr-multiplier 2.0 \
  --reward-risk 1.5 \
  --min-stop-pct 0.0075 \
  --max-stop-pct 0.04 \
  --horizon-bars 96 \
  --output ../octobot-local/backtesting/research/swing.npz
```

This keeps the original feature matrix and provenance but recomputes every
entry, exit, cost, funding payment and label. It avoids the expensive indicator
pass without reusing future outcomes.

The separate delta-neutral carry screen needs same-venue spot, perpetual and
funding history:

```bash
python3 -m octobot.ai_strategy_lab fetch-binance-spot-archive \
  --symbol 'BTC/USDT=BTCUSDT' \
  --from-date 2022-05-01 \
  --to-date 2026-06-30 \
  --allowed-15m-gaps 1 \
  --output ../octobot-local/backtesting/research/binance-spot.data

python3 -m octobot.ai_strategy_lab evaluate-carry \
  --futures-collector ../octobot-local/backtesting/research/binance-um.data \
  --spot-collector ../octobot-local/backtesting/research/binance-spot.data \
  --funding-json ../octobot-local/backtesting/research/binance-funding.json \
  --initial-capital 10000 \
  --cost-stress-multiplier 1.5 \
  --output ../octobot-local/backtesting/research/carry.json
```

The carry simulator uses equal spot-long/perpetual-short notionals, historical
signed funding and real basis changes. It charges all four fills and reports a
second pass with stressed fees and slippage. This is a screening model: it does
not include tax, exchange default, withdrawal latency or unmodelled order-book
impact, and it cannot guarantee regular income.

For same-venue validation the lab can also download public KuCoin hourly spot
and futures candles. Repeated `--futures-collector` arguments merge independently
validated collectors; a symbol with an unexplained gap can therefore be
excluded without weakening continuity checks for the rest of the basket.

The low-frequency futures trend screen accepts one collector and funding file
per asset. It uses only closed daily candles, rebalances weekly, volatility
targets the whole covariance matrix, caps gross and per-asset exposure, and
charges signed funding, fees and slippage:

```bash
python3 -m octobot.ai_strategy_lab evaluate-trend \
  --futures-collector ../octobot-local/backtesting/research/BTC.data \
  --futures-collector ../octobot-local/backtesting/research/ETH.data \
  --funding-json ../octobot-local/backtesting/research/BTC-funding.json \
  --funding-json ../octobot-local/backtesting/research/ETH-funding.json \
  --initial-capital 10000 \
  --cost-stress-multiplier 3 \
  --output ../octobot-local/backtesting/research/trend.json
```

Protocols in `trend.py` are append-only hypotheses: an observed configuration
must not be silently edited. The V3 bear-regime short filter preserves
asset-specific long signals but permits an altcoin short only while BTC's
30/120-day dual-momentum signal is bearish. Reports include long/short and
per-symbol attribution, calendar returns, drawdown duration, withdrawal
capacity and leave-one-asset-out stress.

The V10 diagnostic meta-filter evaluates only V3 weekly candidates. It trains
a small logistic model in four expanding, seven-day-purged folds and compares
the filtered portfolio with V3 on exactly the same out-of-sample dates:

```bash
python3 -m octobot.ai_strategy_lab evaluate-trend-meta \
  --futures-collector ../octobot-local/backtesting/research/BTC.data \
  --futures-collector ../octobot-local/backtesting/research/ETH.data \
  --funding-json ../octobot-local/backtesting/research/BTC-funding.json \
  --funding-json ../octobot-local/backtesting/research/ETH-funding.json \
  --cost-stress-multiplier 3 \
  --output ../octobot-local/backtesting/research/trend-meta.json
```

The threshold and model configuration are frozen constants. Missing
probabilities abstain, the command is research-only, and a successful
diagnostic still cannot authorize shadow or paper orders.

Two pre-registered market-neutral diagnostics test whether cross-sectional
altcoin dispersion can diversify V3:

```bash
python3 -m octobot.ai_strategy_lab evaluate-relative-value \
  --futures-collector ../octobot-local/backtesting/research/BTC.data \
  --futures-collector ../octobot-local/backtesting/research/ETH.data \
  --funding-json ../octobot-local/backtesting/research/BTC-funding.json \
  --funding-json ../octobot-local/backtesting/research/ETH-funding.json \
  --cost-stress-multiplier 3 \
  --output ../octobot-local/backtesting/research/relative-value.json

python3 -m octobot.ai_strategy_lab evaluate-residual-reversal \
  --futures-collector ../octobot-local/backtesting/research/BTC.data \
  --futures-collector ../octobot-local/backtesting/research/ETH.data \
  --funding-json ../octobot-local/backtesting/research/BTC-funding.json \
  --funding-json ../octobot-local/backtesting/research/ETH-funding.json \
  --cost-stress-multiplier 3 \
  --output ../octobot-local/backtesting/research/residual-reversal.json
```

Both sleeves remain beta-residual, net-neutral and capped at 0.5x gross. They
also report a conservative 75% V3 / 25% relative-value combination with costs
kept separate. These commands are reproducible negative protocols, not runtime
strategies.

The local futures paper profile also enforces `max_currency_percent` against
entry notional. At the configured 10% limit and 10,000 USDT starting equity,
each new increasing-position order is capped at 1,000 USDT; reduce-only exits
remain unaffected. The append-only AI journal reconciles paper orders missing
after a process restart with an `interrupted` event, visible on the
`AI Decisions` page.

V13 is the fixed 90%-risk-budget version of V3. V14 uses no more than 20% of
the remaining gross capacity for the persistent same-venue spot/perpetual
carry sleeve, with every leg and its costs kept separate:

```bash
python3 -m octobot.ai_strategy_lab evaluate-risk-budgeted-carry-overlay \
  --futures-collector ../octobot-local/backtesting/research/futures.data \
  --spot-collector ../octobot-local/backtesting/research/spot.data \
  --funding-json ../octobot-local/backtesting/research/funding.json \
  --trend-cost-stress-multiplier 3 \
  --carry-cost-stress-multiplier 3 \
  --max-overlay-fraction 0.20 \
  --output ../octobot-local/backtesting/research/v14.json
```

V14 passes the pre-registered diagnostic edge and prefunded-income gates, but
the samples had already been observed. The bootstrap treats the 21-month and
47-month source histories as separate segments: a six-month moving block can
wrap only within its source and can never cross the unobserved February-July
2022 gap. Historical income sequences are likewise evaluated per source. At a
5% annual return haircut, the corrected 10-year non-loss probability is
99.73%, median CAGR is 14.997%, and P90 maximum drawdown is 28.907%. The
25-unit policy funds its first 24-month block within 36 months in 97.09% of
paths, with 83.87% conditional no-pause probability, 97.90% mean coverage,
and zero prefunding breaches. These remain diagnostic results: V14 is a
forward shadow candidate and cannot replace the live paper profile or
authorize orders.

The pre-registered V14-R1 adverse-execution audit cuts positive funding
receipts in half, keeps negative funding charges whole, delays entry by one
settlement, and stresses carry fees and slippage to 5x. V14-R1 fails the
frozen direct gate: recent Binance annualized return is 12.428%, drawdown is
16.844%, and Sharpe is 0.908; KuCoin Sharpe is 0.99899. The combined
segment-aware edge and prefunded-income gates still pass narrowly. When all
positive funding receipts are removed, however, P90 decade drawdown rises to
30.436% and conditional no-pause probability falls to 77.34%, failing both
gates. This identifies funding realization as a material dependency. V14 may
continue in shadow to collect forward evidence, but it is not classified as
execution-robust and cannot be promoted.

Three frozen follow-up candidates test economically qualified carry without
selecting assets by historical performance. V15 requires 30 positive
settlements and enough half-realized funding to repay a 1% adverse round trip
within 60 days. V16 revalidates the complete signal after its one-settlement
execution delay. V17 concentrates the same 20% cap in the highest currently
qualified pair. All three baseline scenarios pass, and all three adverse
5x-cost/50%-funding scenarios retain the combined edge and prefunded-income
gates. They nevertheless fail the frozen recent-period direct drawdown and
Sharpe limits. Their machine-readable candidate gates are therefore false;
none is added to shadow. Further carry selection requires new forward funding,
basis, spread and execution evidence rather than more tuning on these samples.

Fixed-cash income is evaluated separately from strategy selection. The
withdrawal command resamples contiguous blocks of monthly results, applies
predeclared annual return haircuts, and skips a payment if it would cross the
capital floor:

```bash
python3 -m octobot.ai_strategy_lab evaluate-withdrawals \
  --trend-report ../octobot-local/backtesting/research/trend-old.json \
  --trend-report ../octobot-local/backtesting/research/trend-new.json \
  --strategy bear_regime_short_filter_dual_momentum_30_120_weekly_v3_cost_stress_3x \
  --monthly-amount 25 \
  --monthly-amount 50 \
  --warmup-months 24 \
  --horizon-months 120 \
  --block-months 6 \
  --simulations 10000 \
  --safety-floor-fraction 0.80 \
  --output ../octobot-local/backtesting/research/withdrawals.json
```

This produces probabilities and payment coverage, not guaranteed income. A
skippable guarded payment is deliberately distinguished from a contractual
monthly payment.

Finite fixed-payment blocks can instead be fully prefunded from strategy
surplus:

```bash
python3 -m octobot.ai_strategy_lab evaluate-prefunded-income \
  --trend-report ../octobot-local/backtesting/research/trend-old.json \
  --trend-report ../octobot-local/backtesting/research/trend-new.json \
  --strategy bear_regime_short_filter_dual_momentum_30_120_weekly_v3_cost_stress_3x \
  --monthly-amount 25 \
  --block-months 24 \
  --horizon-months 120 \
  --bootstrap-block-months 6 \
  --simulations 10000 \
  --output ../octobot-local/backtesting/research/prefunded-income.json
```

This policy keeps a 10,000-unit trading core, transfers only surplus to a
separate reserve, and starts a 24-month payment block only after all 600 units
are reserved. The V2 research result passes its predeclared 5% annual-haircut
gate, but only an already funded finite block is fixed. Funding future blocks,
perpetual income, custody safety and future strategy returns remain
unguaranteed, and the report does not authorize real withdrawals.

A fixed strategy can be audited across multiple investment horizons using the
same non-overlapping monthly history:

```bash
python3 -m octobot.ai_strategy_lab evaluate-strategy-evidence \
  --trend-report ../octobot-local/backtesting/research/trend-old.json \
  --trend-report ../octobot-local/backtesting/research/trend-new.json \
  --strategy bear_regime_short_filter_dual_momentum_30_120_weekly_v3_cost_stress_3x \
  --horizon-months 12 \
  --horizon-months 36 \
  --horizon-months 60 \
  --horizon-months 120 \
  --annual-return-haircut 0.05 \
  --simulations 10000 \
  --output ../octobot-local/backtesting/research/strategy-evidence.json
```

This reports bootstrap probabilities, return and drawdown percentiles. Its
winning-edge gate is deliberately separate from the prefunded-income gate:
neither one can turn a backtest into a guarantee.

An evaluated report can be recorded in the append-only shadow journal without
granting any order capability:

```bash
python3 -m octobot.ai_strategy_lab record-trend-shadow \
  --trend-report ../octobot-local/backtesting/research/trend.json \
  --strategy bear_regime_short_filter_dual_momentum_30_120_weekly_v3_cost_stress_3x \
  --journal ../octobot-local/user/trend_shadow.jsonl
```

Identical report/strategy pairs are deduplicated. Every record carries source
and record hashes, signals, current and target weights, gross/net exposure, and
the explicit flags `mode=shadow_only` and `orders_authorized=false`.

The autonomous runner refreshes 19 public KuCoin futures/funding histories,
validates zero candle gaps, evaluates V3 with costs stressed 3x, and publishes
the dated report, journal record and health file atomically:

```bash
python3 -m octobot.ai_strategy_lab run-trend-shadow \
  --output-root ../octobot-local/backtesting/research/shadow-forward \
  --journal ../octobot-local/shadow/trend_shadow.jsonl \
  --health ../octobot-local/shadow/health.json \
  --lock ../octobot-local/shadow/runner.lock \
  --history-days 264 \
  --rebalance-weekday-utc 6 \
  --catch-up-max-days 7
```

The `trend-shadow` service in `docker-compose.local.yml` runs this once per day
and retries a failed public-data cycle after 15 minutes. It mounts no active
OctoBot user profile: user, tentacles and log paths are empty read-only binds;
Linux capabilities are dropped and only research data plus the dedicated
shadow directory are writable.

The same service also runs V14 in an independent journal. It downloads public
KuCoin spot data in addition to futures and funding, reconstructs the
persistent carry state, and represents trend, carry-futures and carry-spot as
separate instruments so no netting or common execution cost is assumed:

```bash
python3 -m octobot.ai_strategy_lab run-risk-budgeted-carry-shadow \
  --output-root ../octobot-local/backtesting/research/shadow-forward-v14 \
  --journal ../octobot-local/shadow/v14/trend_carry_shadow.jsonl \
  --health ../octobot-local/shadow/v14/health.json \
  --lock ../octobot-local/shadow/v14/runner.lock \
  --history-days 264 \
  --max-overlay-fraction 0.20 \
  --catch-up-max-days 7
```

Catch-up mode processes missing fully closed UTC days chronologically. It
refuses mixed, duplicate, out-of-order or already-gapped journals and fails if
more than seven days are missing; it never silently jumps to the latest day.

The separate `market-observer` service captures evidence that was unavailable
to the historical carry tests. Every 15-minute UTC bucket it reads public
KuCoin ticker, contract, current-funding and 20-level order-book endpoints for
the same 19 research pairs:

```bash
python3 -m octobot.ai_strategy_lab.cli run-forward-market-observer \
  --journal ../octobot-local/shadow/market/microstructure.jsonl \
  --health ../octobot-local/shadow/market/health.json \
  --lock ../octobot-local/shadow/market/runner.lock
```

Each append-only record contains executable spot-ask/futures-bid entry basis,
spot-bid/futures-ask exit basis, spread, quote depth, delta-neutral capacity,
contract multiplier, open interest, mark/index prices and current/predicted
funding. It also retrieves the preceding 24 hours of actually settled funding
for every perpetual, so future P&L labels do not rely on the displayed current
or predicted value. Futures depth is converted from contracts to quote
notional. Execution curves report book-derived VWAP and capacity at 100, 500
and 1,000 USDT for every spot/futures bid/ask side. Public taker fees are stored
alongside conservative floors of 0.10% spot and 0.06% futures per side. This
prevents a future 1,000-USDT label from using an infinitesimal top-of-book
price. A missing symbol, missing settlement, invalid book or non-finite
economic field rejects the entire bucket; same-bucket retries are deduplicated
and every row is linked by SHA-256.

The independent `scalping-observer` is a higher-frequency, BTC-only research
stream. It requests a public Classic Futures WebSocket token, subscribes once
to the `XBTUSDTM` Level 5 book and public execution topics, then receives
server-pushed updates without REST polling:

```bash
python3 -m octobot.ai_strategy_lab.cli run-scalping-observer \
  --database ../octobot-local/scalping/btc-futures-level5.sqlite \
  --health ../octobot-local/scalping/health.json \
  --symbol XBTUSDTM
```

Level 5 can update every 100 ms when the book changes; executions are
real-time. SQLite stores exchange and Raspberry receive timestamps, sequence,
all five bid/ask levels, spread, microprice, five-level imbalance and public
trade aggressor/size. A second append-only table materializes one-second book
and trade-flow buckets. Unique exchange sequence/timestamp and trade IDs
deduplicate reconnect overlap, while WAL plus one-second commits bound the
uncommitted tail.

The known 27 July BTC sell-off can be reproduced as a diagnostic case study
without stopping the live collector or opening orders:

```bash
python3 -m octobot.ai_strategy_lab.scalping_crash_case_study \
  write-protocol \
  --output ../octobot-local/backtesting/research/scalping_crash_case_v1
python3 -m octobot.ai_strategy_lab.scalping_crash_case_study \
  evaluate \
  --database ../octobot-local/scalping/btc-futures-level5.sqlite \
  --output ../octobot-local/backtesting/research/scalping_crash_case_v1
```

The evaluator takes one read-only SQLite snapshot, persists its complete
15-minute extraction and explicitly treats the observed sell-off as
development evidence. Its post-event hypothesis is only a future long-entry
veto; it cannot be interpreted as a short signal or connected to paper
trading before the frozen 30-day forward gate.

The sidecar has no operational profile, API keys or order code. Its live
health file verifies fresh books and lightweight SQLite operability and always
declares
`public_data_only=true`, `credentials_used=false`,
`orders_authorized=false` and `automatic_promotion=false`. The frozen first
hypothesis is taker micro-momentum with 5/15/30/60-second features, 1-minute
context and a 5-minute regime filter. It cannot be evaluated before 30 forward
days and its simulator must cross the recorded spread, apply conservative
fees/slippage, stress 250/500/1,000-ms latency and prohibit retroactive fills.

Before a row is appended to the JSONL index it is persisted through an atomic
rename as a content-addressed file under `shadow/market/records`. Every cycle
backfills missing archive copies and verifies that archive and journal are the
same hash chain. A complete archived tail left by a crash between the two
writes is re-indexed without network access; a mismatch, fork or tampered file
fails closed without deleting either copy.

Coverage and readiness are audited independently:

```bash
python3 -m octobot.ai_strategy_lab.cli \
  evaluate-forward-market-evidence \
  --journal ../octobot-local/shadow/market/microstructure.jsonl \
  --output ../octobot-local/shadow/market/evidence.json
```

Hypothesis development remains locked until the journal covers 60 days with at
least 95% of the expected 15-minute buckets, no gap over 60 minutes, all 19
symbols and at least 171 unique settled funding points per symbol. Passing this
gate permits only offline dataset construction. The observer has no user
profile, credentials or order endpoint and always records
`orders_authorized=false`; it cannot promote V14 or turn a funding snapshot
into an expected annual return. The report also exposes remaining span buckets,
remaining settlements per symbol and the earliest theoretical timestamp at
which the temporal requirement could pass. That timestamp is collection
readiness, not a profitability or income ETA.

After readiness, and never before it, generic execution-aware labels can be
built at fixed 8-hour, 24-hour and 168-hour horizons:

```bash
python3 -m octobot.ai_strategy_lab.cli build-forward-carry-dataset \
  --journal ../octobot-local/shadow/market/microstructure.jsonl \
  --evidence ../octobot-local/shadow/market/evidence.json \
  --output ../octobot-local/backtesting/research/forward-carry.npz
```

The builder verifies the journal hash and recomputes readiness. For each exact
entry/exit pair it opens 1,000 USDT per leg from the normalized books, then
closes the exact spot and futures base quantities against the future books.
Four conservative taker fees use their actual entry/exit notionals; only
funding settlements after entry and through exit are credited. It refuses a
stale audit, an unready sample, missing exact exit buckets, incomplete levels,
or insufficient depth. The compressed dataset and manifest remain
research-only and contain no signal or order authorization. Loading the NPZ
rechecks its SHA-256, byte size, feature schema, row alignment, exact horizons,
finite values and the accounting identity
`net = 0.5 * (spot + futures + funding) - fees` before exposing any row to a
model.

Applied shadow weights change only on Sunday UTC. Daily candidate weights,
closed prices and signed funding remain recorded separately, allowing strictly
forward P&L:

```bash
python3 -m octobot.ai_strategy_lab evaluate-shadow-performance \
  --journal ../octobot-local/shadow/trend_shadow.jsonl \
  --output ../octobot-local/shadow/performance.json \
  --fixed-monthly-amount 25 \
  --strategy bear_regime_short_filter_dual_momentum_30_120_weekly_v3_cost_stress_3x
```

The paper-review gate requires at least 330 observed days over 12 calendar
months, no missing forward day, at least 8% annualized return, at most 15%
drawdown and 60% positive months. The income-evidence gate additionally
requires 700 observed days over 24 months and every guarded 25-unit monthly
payment after a 12-month warm-up. Passing either gate only permits manual
review; `automatic_promotion` is always false.

The same forward report includes `prefunded_income_readiness`. It tracks the
simulated 600-unit reserve needed to cover 24 fixed payments of 25, and reports
the current shortfall and the number of future payments already backed by
segregated simulated cash. It never transfers funds: real payments remain
unauthorized, and no payment is described as guaranteed before the complete
finite block has been prefunded. Only complete calendar months, observed from
day one through month-end without gaps, can fund the reserve or count toward
monthly gates. Partial month-to-date returns remain visible but excluded.

The daily sidecar consolidates all requirements in one fail-closed audit:

```bash
python3 -m octobot.ai_strategy_lab audit-income-objective \
  --strategy-evidence ../octobot-local/backtesting/research/strategy-evidence.json \
  --prefunded-research ../octobot-local/backtesting/research/prefunded-income.json \
  --shadow-performance ../octobot-local/shadow/performance.json \
  --monthly-amount 25 \
  --output ../octobot-local/shadow/income-objective.json
```

`achieved_in_paper` requires the strategy evidence gate, a forward report with
the exact same strategy identity, forward review, policy gate and an already
funded finite block simultaneously. Real income and automatic promotion remain
disabled in every state.

The experiment directory contains a JSON report, a reproducible NumPy model,
the selected locked-test predictions and a manifest with SHA-256 hashes.  The
root `experiments.jsonl` is append-only and records every completed run.

Closed paper outcomes can be exported from the operational journal without
writing to it:

```bash
python3 -m octobot.ai_strategy_lab export-paper-feedback \
  --journal ../octobot-local/user/ai_decisions.sqlite \
  --output ../octobot-local/backtesting/research/paper_feedback_latest.json
```

The export keeps HOLD, rejected and still-open decisions as unlabelled controls.
Only an approved decision linked to a closed simulated position is eligible for
supervised training. Economic labels include known order fees and explicitly
exclude funding until it is available in the OctoBot order event. The command
cannot create an order or promote a model. Its `training_readiness` gate also
requires at least 200 closed outcomes over 365 days, at least 50 outcomes per
direction, 40 per economic class, valid features and funding-complete labels.
Automatic fitting remains disabled even after every evidence check passes.

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
