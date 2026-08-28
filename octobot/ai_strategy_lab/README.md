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

V18 tests one causal daily volatility brake on the unchanged V13 trend
signal. It improves old-Binance and KuCoin drawdown and Sharpe, remains
positive at 5x costs and passes the existing bootstrap edge gate. It is still
rejected: on recent Binance it retains only 79.398% of V13 annualized return,
drawdown remains 16.173% instead of the required 15%, and Sharpe falls from
0.921 to 0.832. No brake threshold or lookback is retuned on these observed
samples, and V18 is not eligible for shadow or paper trading.

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
`orders_authorized=false` and `automatic_promotion=false`. The frozen Level 5
sample has now been evaluated. Aggregate micro-momentum V1a, cost-aware V2 and
event-level queue-flow V3 all fail before the sealed 20--26 August block. V3
uses 109 causal features and more than 23.6 million book snapshots, yet its
best descriptive gross edge is only about 1.3 bps against a 14-bps taker round
trip. The single-venue KuCoin taker family is therefore closed rather than
retuned.

V4 changes the information set once by adding checksummed public Binance USD-M
aggregate trades. Its result-free protocol fixes a five-second Binance impulse,
one-second information delay, KuCoin lag and agreeing taker-flow rule before
downloading any pre-test archive:

```bash
python3 -m octobot.ai_strategy_lab.scalping_cross_venue_v4 write-protocol \
  --output ../octobot-local/backtesting/research/scalping-evaluation-v4/protocol.json
python3 -m octobot.ai_strategy_lab.scalping_cross_venue_v4 fetch-pretest \
  --protocol ../octobot-local/backtesting/research/scalping-evaluation-v4/protocol.json \
  --cache-root ../octobot-local/backtesting/research/scalping-evaluation-v4/cache \
  --manifest ../octobot-local/backtesting/research/scalping-evaluation-v4/archive-manifest.json
```

Across 20.9 million Binance pre-test trades, V4 also fails decisively: 110
development trades produce PF 0.098 and -1.429%, with zero positive folds; the
13--19 August diagnostic confirmation produces 65 trades, PF 0.323 and
-0.613%. Gross expectancy is about 0.9 and 4.5 bps respectively, still below
the unchanged 14-bps KuCoin taker cost. The locked 20--26 August Binance data
is not downloaded or evaluated, and V4 cannot authorize orders.

The `operations-reporter` sidecar publishes an hourly read-only data-quality
snapshot under `shadow/operations/current.json` and one hash-chained record per
UTC day in `shadow/operations/daily.jsonl`. The Strategy Status page exposes
port reachability, data freshness, Level 5 coverage and gaps, collector
restarts, disk space, V5 frequency/calibration and the difference between V3
weights already applied and current candidates. It also creates and verifies
daily SQLite backups of the smaller KuCoin and V5 journals. These backups are
on the same volume by default and therefore do not protect against physical
disk failure.

The live multi-gigabyte Level 5 database is deliberately not copied or fully
integrity-scanned every hour. After the frozen 30-day gate, stop the collector
cleanly and run the explicit offline freeze:

```bash
python3 -m octobot.ai_strategy_lab.cli freeze-scalping-forward-dataset \
  --scalping-database ../octobot-local/scalping/btc-futures-level5.sqlite \
  --scalping-health ../octobot-local/scalping/health.json \
  --destination-root ../octobot-local/backtesting/research/scalping-freezes \
  --scalping-protocol ../octobot-local/shadow/operations/scalping-evaluation-protocol.json \
  --lock ../octobot-local/shadow/operations/scalping-freeze.lock \
  --collector-confirmed-stopped
```

The command refuses a health state other than a graceful stop, less than 30
days, coverage below 95% or a failed database check. A successful run writes a
verified SQLite copy, full gap audit, protocol hash and immutable manifest; it
still cannot authorize paper or real orders.

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
rechecks its SHA-256, the manifest SHA-256, byte size, feature schema, row
alignment, exact horizons, finite values and the accounting identity
`net = 0.5 * (spot + futures + funding) - fees` before exposing any row to a
model. The manifest also records every excluded point-in-time candidate by
timestamp, horizon, symbol and reason. This makes missing future buckets and
insufficient future unwind depth auditable instead of silently dropping rows
that could bias the result.

The first strategy protocol using this dataset is frozen before readiness and
contains no result:

```bash
python3 -m octobot.ai_strategy_lab.forward_carry_strategy_v1 \
  --output ../octobot-local/backtesting/research/forward-carry-v1/protocol.json
```

`kucoin_spot_perpetual_forward_carry_v1` tests one long-spot/short-perpetual
candidate only. Its primary holding period is 168 hours; 8 and 24 hours are
diagnostic and cannot be selected retrospectively. A fixed ridge regression
with no feature or hyperparameter search ranks eligible pairs at 00:15, 08:15
and 16:15 UTC. Each leg is 1,000 USDT, at most five pairs may overlap, and the
portfolio is marked to executable unwind VWAP every 15 minutes. Development
entries end seven days before the preregistration cutoff. Confirmation starts
at `2026-08-27T12:00:00Z`, spans at least 30 entry days and cannot be opened
before all outcomes mature at `2026-10-03T12:00:00Z`. A failed development
gate leaves confirmation sealed. Even a complete pass permits only manual
review for an orderless 90-day shadow; paper and real orders remain disabled.
The frozen protocol SHA-256 is
`52fe792f3c5b3e0983ed265ca58aa59c4c1d5931caab4f59eecc03dbe1d39836`.

While implementing the evaluator, before the cutoff and without reading any
economic outcome, a feasibility contradiction was found in V1: two contiguous
seven-day out-of-sample windows, a 168-hour hold and five slots permit at most
ten closed pairs, while the development gate required fifteen. V1 remains
unchanged. The result-free V1.1 correction changes only that minimum from 15
to 8 and makes the already fixed confirmation end explicit:

```bash
python3 -m octobot.ai_strategy_lab.forward_carry_strategy_v1_1 \
  --output ../octobot-local/backtesting/research/forward-carry-v1_1/protocol.json
```

The V1.1 protocol SHA-256 is
`f00225920e30dcb6bdd48be4be03487e78ee451cf076974e1340dc3bc3d5cff4`;
its parent hash is stored in the artifact and `results` remains null.

The frozen offline evaluator can expose its locks at any time:

```bash
python3 -m octobot.ai_strategy_lab.forward_carry_evaluator_v1 phase-status \
  --protocol ../octobot-local/backtesting/research/forward-carry-v1_1/protocol.json \
  --evidence ../octobot-local/shadow/market/evidence.json
```

The local read-only `Strategy Status` page exposes the same Carry V1.1 gate as
a progress bar, a conditional earliest evaluation date, the full checklist and
only the currently active blocker reasons. It verifies the frozen protocol
hash, evidence freshness, collector health and the orderless safety locks. The
page never builds a dataset, fits a model, opens confirmation or creates an
order.

Only after forward readiness may the development report be created:

```bash
python3 -m octobot.ai_strategy_lab.forward_carry_evaluator_v1 \
  evaluate-development \
  --protocol ../octobot-local/backtesting/research/forward-carry-v1_1/protocol.json \
  --dataset ../octobot-local/backtesting/research/forward-carry.npz \
  --evidence ../octobot-local/shadow/market/evidence.json \
  --journal ../octobot-local/shadow/market/microstructure.jsonl \
  --output-directory ../octobot-local/backtesting/research/forward-carry-v1_1
```

The evaluator applies the frozen purged walk-forward folds, structural-funding
benchmark, all 19 leave-one-symbol-out refits, 15-minute delayed/double-fee
stress and executable 15-minute mark-to-market. Dataset, manifest, model and
reports are content-bound and revalidated on load. The model is persisted only
if every development gate passes. Confirmation additionally requires that
exact passing report and model, remains wall-clock locked until
`2026-10-03T12:00:00Z`, never refits, and uses the predeclared entry window.
Neither command contains exchange access or can create paper or real orders.

The deployed `forward-carry-gatekeeper` service performs those same transitions
automatically and fail-closed. It has no network, mounts the live market journal
and the exact V1.1 protocol read-only, and can write only below the dedicated
`forward-carry-v1_1/gatekeeper` directory. Before readiness it writes just
`status.json` and a process lock: no journal copy, dataset, label, model or
economic report exists. At the first complete gate it binds the evidence byte
count and journal SHA-256 in a one-shot source lock, copies exactly that
append-only prefix, verifies the content-addressed archive tail, recomputes
readiness and executes development once. Operational retries remain bound to
the first source lock.

The development dataset is explicitly cut before
`2026-08-20T12:00:00Z`, so confirmation entries are absent even though newer
records are needed to prove 60-day readiness. A failed development report is
also latched and permanently keeps confirmation sealed. Only a passing frozen
model can reach the second one-shot phase after `2026-10-03T12:00:00Z`; that
dataset is separately limited to the preregistered 30-day confirmation entry
window. Runs are built in temporary directories, verified, renamed atomically
and content-addressed. No result grants automatic shadow, paper or live access.
The same state, blockers and absence/presence of economic artifacts are shown
on the read-only `Strategy Status` page.

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

## BTC microstructure beyond scalping

`microstructure_regime_v1` tests whether the collected BTC Futures Level-5
book adds information to a slower 15-minute price/volume baseline. The frozen
primary label is a directional `+1%` target before a `-1%` stop within four
hours; one and eight hours remain descriptive. Features are available only at
a closed 15-minute boundary. Standard 15-minute indicators use a fixed causal
54-candle warmup, while book and queue-flow features come from the already
audited scalping V3 dataset. The locked 20--26 August block is never loaded.

Freeze the result-free protocol before building labels:

```bash
python3 -m octobot.ai_strategy_lab.microstructure_regime_v1 write-protocol \
  --output ../octobot-local/backtesting/research/microstructure-regime-v1/protocol.json
```

Build the diagnostic-reuse dataset and run the fixed comparison:

```bash
python3 -m octobot.ai_strategy_lab.microstructure_regime_v1 build-dataset \
  --protocol ../octobot-local/backtesting/research/microstructure-regime-v1/protocol.json \
  --parent-v3-dataset ../octobot-local/backtesting/research/scalping-evaluation-v3/pretest-dataset.npz \
  --parent-v3-manifest ../octobot-local/backtesting/research/scalping-evaluation-v3/pretest-dataset.manifest.json \
  --source-cache ../octobot-local/backtesting/research/scalping-evaluation-v1/pretest-dataset-source-cache.npz \
  --output ../octobot-local/backtesting/research/microstructure-regime-v1/diagnostic-dataset.npz

python3 -m octobot.ai_strategy_lab.microstructure_regime_v1 evaluate-discovery \
  --protocol ../octobot-local/backtesting/research/microstructure-regime-v1/protocol.json \
  --dataset ../octobot-local/backtesting/research/microstructure-regime-v1/diagnostic-dataset.npz \
  --dataset-manifest ../octobot-local/backtesting/research/microstructure-regime-v1/diagnostic-dataset.manifest.json \
  --output-root ../octobot-local/backtesting/research/microstructure-regime-v1/experiments
```

V1 did not demonstrate incremental book value. Price/volume plus indicators
reached AUC `0.765805`; the combined model reached `0.660596` and worsened
Brier score by `5.921%` relative to price-only, with zero improved folds out of
four. The primary target base rate was only `4.9403%`, and the frozen 60%
threshold selected no combined trades. This is a rejected diagnostic, not a
claim that the price baseline is tradable. Each experiment persists hashed
predictions and all fold models and verifies their predictions after reload.
No artifact authorizes paper or real orders.

V2 tests the narrower lesson from V1 without changing the four-hour horizon.
It first estimates whether either barrier will be touched, then estimates
up-first versus down-first only on historical barrier events. Price retains
directional responsibility. Instead of all 92 book columns, 24 fixed
volatility/liquidity features can apply a centered activity-logit correction
with frozen weight `0.25`; an 18-feature directional book correction is a
diagnostic challenger only. The protocol must be frozen before evaluation:

```bash
python3 -m octobot.ai_strategy_lab.microstructure_regime_v2 write-protocol \
  --output ../octobot-local/backtesting/research/microstructure-regime-v2/protocol.json

python3 -m octobot.ai_strategy_lab.microstructure_regime_v2 evaluate-discovery \
  --protocol ../octobot-local/backtesting/research/microstructure-regime-v2/protocol.json \
  --parent-protocol ../octobot-local/backtesting/research/microstructure-regime-v1/protocol.json \
  --dataset ../octobot-local/backtesting/research/microstructure-regime-v1/diagnostic-dataset.npz \
  --dataset-manifest ../octobot-local/backtesting/research/microstructure-regime-v1/diagnostic-dataset.manifest.json \
  --output-root ../octobot-local/backtesting/research/microstructure-regime-v2/experiments
```

V2 is also rejected. On 905 walk-forward decisions, price activity reaches AUC
`0.708113`; the filtered activity reaches `0.701944` and worsens Brier by
`0.3916%`, improving only two folds out of four. Conditional price direction
reaches AUC `0.163095` on 88 out-of-sample barrier events, so it does not
transfer chronologically. The primary book-filter arm selects 16
counterfactual trades, with win rate `12.5%`, profit factor `0.142`, average
instrument return `-39.75` bps and portfolio return `-0.6343%`; double-cost
stress is `-0.8567%`. Only 7 of 18 gates pass. This diagnostic reuse cannot
validate an inverted signal, trigger another same-sample correction, open the
20--26 August lock or authorize orders. Protocol SHA-256 is
`67201b63edba8c9d2a13679661087bb17f9cac5b2db7f772212c252ddcb27535`.

V3 isolates one sequential motif that the generic V3 queue-flow regression
could hide: absorption. The result-free protocol selects extreme 60-second
aggressor pressure only when displayed refill/order-flow opposes it, price
response remains muted and the five-second microprice turns against it. All
quantiles are fitted from past features only. The sole eligible direction is
the reversal, and the economic screen is an executable 15-minute markout with
500 ms latency and a 14-bps taker round trip; there is no take profit, stop or
maker-fill assumption.

```bash
python3 -m octobot.ai_strategy_lab.microstructure_absorption_v3 \
  write-protocol \
  --output ../octobot-local/backtesting/research/microstructure-absorption-v3/protocol.json

python3 -m octobot.ai_strategy_lab.microstructure_absorption_v3 \
  evaluate-pretest \
  --protocol ../octobot-local/backtesting/research/microstructure-absorption-v3/protocol.json \
  --dataset ../octobot-local/backtesting/research/scalping-evaluation-v3/pretest-dataset.npz \
  --dataset-manifest ../octobot-local/backtesting/research/scalping-evaluation-v3/pretest-dataset.manifest.json \
  --source-cache ../octobot-local/backtesting/research/scalping-evaluation-v1/pretest-dataset-source-cache.npz \
  --output-root ../octobot-local/backtesting/research/microstructure-absorption-v3/experiments
```

V3 is rejected before the locked test. Its five development walk-forward
folds select 25 non-overlapping events, all five lose, mean net markout is
`-17.1595` bps, profit factor is `0.0453` and only `7.69%` of operating days
are positive. Both long and short contributions are negative and doubled-cost
stress is `-0.7745%`. The reused 13--19 August confirmation selects 20 events,
mean net markout `-9.8483` bps, profit factor `0.3388` and `20%` positive
operating days; its gross mean is only about `+4.15` bps before the fixed
14-bps cost. The protocol hash is
`dad8e2c29fa75c1a740937b3896c883a314261ed692db5376a53200e49d3639c`
and the report hash is
`2578446590684ce2c774756967457d5265110a0cb76ce7a6f7013ed8d903d53b`.
The 20--26 August block remains unmaterialized and unauthorized. Reversing or
retuning this motif on the same rows is explicitly disallowed.

## Cointegration pairs V1

`cointegration_pairs_v1` tests a separate market-neutral mechanism on the
existing 18-asset Binance futures history.  Every calendar month it fits log
price pairs on the preceding 180 closed daily observations.  Residual ADF(0)
statistics are compared with a deterministic 20,000-path independent-random-
walk Monte Carlo null, followed by Benjamini--Hochberg FDR control at 5%.
Selected pairs must also satisfy frozen beta, half-life and zero-crossing
requirements; no asset can appear in two of the maximum four pairs.  Trades
use fixed z-score entry/exit/stop thresholds, next-day weights, signed funding
and taker fee/slippage.  There is no maker-fill assumption or exchange client.

Freeze the result-free protocol and run the pre-lock evaluator:

```bash
python3 -m octobot.ai_strategy_lab.cointegration_pairs_v1 write-protocol \
  --output ../octobot-local/backtesting/research/cointegration-pairs-v1/protocol.json

python3 -m octobot.ai_strategy_lab.cointegration_pairs_v1 evaluate-prelock \
  --protocol ../octobot-local/backtesting/research/cointegration-pairs-v1/protocol.json \
  --futures-collector BINANCE_FUTURES_FILE ... \
  --funding-json BINANCE_FUNDING_FILE ... \
  --output-root ../octobot-local/backtesting/research/cointegration-pairs-v1/experiments
```

V1 is rejected for insufficient activity and temporal stability.  Development
from November 2022 through December 2024 returns `+3.2534%`, with profit factor
`2.2907`, maximum drawdown `2.8911%` and both spread directions positive.
Triple-cost stress remains positive at `+2.5123%`.  However, only 9 trades are
closed, pairs are available in 7 of 26 monthly formations, just two of four
folds are positive, Sharpe is `0.6668`, and only `15.38%` of months are
positive.  Seven of eleven gates pass.  The confirmation year 2025 and locked
January--June 2026 interval are not evaluated.  Protocol SHA-256 is
`d7187da7c0c6f218b95b26e73c7586a553b5cd9a33b277f06c341e369d20a898`;
report SHA-256 is
`1c485d36402a6ab5cb890f01e556743c51b6d50063c929f547de59103a5608e0`.
The same rows cannot be used to relax FDR, formation or z-score thresholds.

## Funding cross-section V1

`funding_cross_section_v1` tests whether the funding spread can be harvested
without a spot hedge.  At each Monday UTC close it ranks the trailing seven
days of completed funding settlements, goes long the lowest quartile and short
the highest quartile, and applies inverse-volatility dollar-neutral weights
from the following day.  The gross cap is 80%; funding, perpetual price P&L,
taker fees, slippage and a triple-cost stress are accounted separately.

The frozen protocol is written and evaluated with:

```bash
python3 -m octobot.ai_strategy_lab.funding_cross_section_v1 write-protocol \
  --output ../octobot-local/backtesting/research/funding-cross-section-v1/protocol.json

python3 -m octobot.ai_strategy_lab.funding_cross_section_v1 evaluate-prelock \
  --protocol ../octobot-local/backtesting/research/funding-cross-section-v1/protocol.json \
  --futures-collector BINANCE_FUTURES_FILE ... \
  --funding-json BINANCE_FUNDING_FILE ... \
  --output-root ../octobot-local/backtesting/research/funding-cross-section-v1/experiments
```

V1 is rejected in development.  It collects `+9.2048%` additive funding, but
the relative perpetual-price component is `-9.1836%`; `7.4993%` modeled
turnover cost then leaves a compounded `-9.3332%`, Sharpe `-0.2196` and maximum
drawdown `20.0977%`.  Triple-cost return is `-21.9757%`; only two of five
six-month folds are positive and four of eleven gates pass.  The near-offset
between price and funding means mechanically reversing the same portfolio is
not a new edge: it reverses both components while retaining the cost.  The
2025 confirmation and 2026 lock remain uncomputed.  Protocol SHA-256 is
`deb97bc02c55cf270d5f9e613c855c858e7114c7434a863e55cde0f11fb8fddf`;
report SHA-256 is
`592bd65ebd850234b0b06450df7bfb7a4d588fb866aed0693da2b1e03d4a4d80`.

## Quarter-hour opening flow V1

`quarter_hour_flow_v1` is an economic-feasibility audit motivated by Kim and
Hansen's quarter-hour effect.  On every UTC quarter-hour it observes only the
first ten seconds of KuCoin BTC aggressor flow, trades its sign at executable
top-of-book 500 ms after that observation, and measures the executable
four-hour markout.  Fee plus slippage is fixed at 14 bps round trip; stress
adds one second and doubles costs.  Markouts overlap and are explicitly not
reported as a portfolio return.

```bash
python3 -m octobot.ai_strategy_lab.quarter_hour_flow_v1 write-protocol \
  --output ../octobot-local/backtesting/research/quarter-hour-flow-v1/protocol.json

python3 -m octobot.ai_strategy_lab.quarter_hour_flow_v1 evaluate-prelock \
  --protocol ../octobot-local/backtesting/research/quarter-hour-flow-v1/protocol.json \
  --source-cache ../octobot-local/backtesting/research/scalping-evaluation-v1/pretest-dataset-source-cache.npz \
  --output-root ../octobot-local/backtesting/research/quarter-hour-flow-v1/experiments
```

V1 is decisively rejected in development.  Across 1,560 events, gross mean is
only `+0.7677` bps versus the 14-bps round trip, leaving `-13.2323` bps net,
profit factor `0.5214`, hit rate `35%` and `4.76%` positive operating days.
Both directions lose and zero of five folds has positive mean net markout.
One-second/double-cost stress is `-27.2675` bps with PF `0.2729`.  Confirmation
is not read and the 20--26 August lock is absent from the source cache and
unmaterialized.  Protocol SHA-256 is
`386ddd211bd26de86eb66980e630397d5106b5251f6c413e700b08a9a6968b53`;
report SHA-256 is
`11b0a22bb28dbe2afb3a338e750b30f299f722135b59d1ec22d521d18caa82a8`.

## Passive execution V1

`maker_execution_v1` uses the frozen BTC Futures Level-5 database as an
execution diagnostic rather than a directional signal. At each UTC quarter
hour it evaluates a virtual 1,000-USDT buy and sell. The benchmark takes the
top-five VWAP after 500 ms. The candidate attempts a best-quote post-only order
only when signed queue imbalance is favorable, puts 125% of displayed size in
front of itself, grants no queue improvement from cancellations and requires
observed aggressor volume to consume that queue plus its whole integer-contract
quantity. An unfilled order falls back to taker after 60 seconds. Official
XBTUSDTM contract size (`0.001 BTC`) and conservative base-tier fees (2-bps
maker, 6-bps taker) are frozen in the protocol.

```bash
python3 -m octobot.ai_strategy_lab.maker_execution_v1 write-protocol \
  --output ../octobot-local/backtesting/research/passive-execution-v1/protocol.json

python3 -m octobot.ai_strategy_lab.maker_execution_v1 evaluate-prelock \
  --protocol ../octobot-local/backtesting/research/passive-execution-v1/protocol.json \
  --database ../octobot-local/backtesting/research/scalping-freezes/SCALPING_FREEZE/btc-futures-level5.sqlite \
  --freeze-manifest ../octobot-local/backtesting/research/scalping-freezes/SCALPING_FREEZE/manifest.json \
  --output-root ../octobot-local/backtesting/research/passive-execution-v1/experiments
```

V1 is rejected in development. It completes 3,897 of 3,918 rows (`99.464%`
coverage), attempts 1,548 passive orders and conservatively fills only 108
(`6.977%`). Mean saving versus immediate taker is `-0.1327` bps: buy loses
`-0.1044` bps and sell `-0.1609` bps. All five temporal folds are negative,
only `14.286%` of operating days improve and the 90% daily-bootstrap lower
bound is `-0.1689` bps. Filled orders show roughly `-5` bps of adverse
selection at five and sixty seconds. The doubled-queue/short-timeout/1.5x-fee
stress also loses (`-0.1150` bps) and fills only `2.536%` of attempts. Three of
eleven gates pass. Confirmation and the 20--26 August lock remain unread. The
protocol SHA-256 is
`079e58fa244f8266bfe99a22f1f87880b9e3aa86cce7faace88887319c45e646`;
report SHA-256 is
`b5f8e00f32788316fa921c9a4f19671d30267f8a17749914e29e86013a1923d1`.
This closes the fixed imbalance-gated policy, not all learned execution models.

## Learned passive execution V2 and final lock

`maker_execution_v2` keeps the conservative V1 queue/fallback simulation but
learns two quantities from development only: maker fill probability and saving
when the maker order does not fill. Its fixed 17-feature causal model attempts
maker execution only when predicted fill probability is at least `10%` and
expected saving is strictly above `0.25` bps. There is no feature,
hyperparameter or threshold search. Five expanding purged folds all pass;
development saving is `+1.1725` bps over 1,061 selected attempts. The untouched
13--20 August confirmation also passes with `+1.2119` bps over 469 attempts.

The separate `maker_execution_locked_v2` binds the pre-lock protocol, report,
manifest, model, confirmation predictions and immutable Level-5 freeze by hash.
It never refits and is the only code path allowed to query 20--26 August:

```bash
python3 -m octobot.ai_strategy_lab.maker_execution_locked_v2 write-protocol \
  --output ../octobot-local/backtesting/research/learned-passive-execution-locked-v2/protocol.json

python3 -m octobot.ai_strategy_lab.maker_execution_locked_v2 evaluate-lock \
  --protocol ../octobot-local/backtesting/research/learned-passive-execution-locked-v2/protocol.json \
  --parent-protocol ../octobot-local/backtesting/research/learned-passive-execution-v2/protocol.json \
  --parent-experiment ../octobot-local/backtesting/research/learned-passive-execution-v2/experiments/learned-passive-execution-v2-70ec9868e208-7c999831e0d4 \
  --database ../octobot-local/backtesting/research/scalping-freezes/scalping-freeze-1784815309-1787753457/btc-futures-level5.sqlite \
  --freeze-manifest ../octobot-local/backtesting/research/scalping-freezes/scalping-freeze-1784815309-1787753457/manifest.json \
  --output-root ../octobot-local/backtesting/research/learned-passive-execution-locked-v2/experiments
```

The final lock passes all 16 frozen gates. It retains 1,258 of 1,266 rows
(`99.368%` coverage), selects 639 attempts (`50.795%`), fills 374 (`58.529%`)
and saves `+0.5826` bps per selected attempt versus immediate taker execution.
Buy is `+0.6673` bps and sell `+0.5018` bps; `85.714%` of operating days are
positive and the 90% daily-bootstrap lower bound is `+0.1659` bps. Fill AUC is
`0.7906`; Brier is `0.1798` versus `0.2649` for the frozen constant.
Protocol SHA-256 is
`0d6c1cd814799280358c350f9bec6917fb61f1e92e4c3a42842e5ffc5310789e`;
report SHA-256 is
`bd6c85f0091050b95a2e7dc17e23a9038d6b355b62d893a8fb105d0068219fee`.

This is an execution edge, not directional alpha. It can only advance to an
orderless forward shadow overlay for an independently validated strategy. A
post-lock structural audit also records that the frozen `1.5x` fee stress is
not monotonic: multiplying both fees expands the maker/taker differential by
2 bps per fill. Removing only that benefit leaves aggregate stress at
`+0.1868` bps and buy at `+0.6142` bps, but sell at `-0.2209` bps. Therefore
per-side stress robustness is not established and forward gates must remain
separate. The audit content SHA-256 is
`6979eb6f00009d06450a3fbd7748e73d62a780276b8800ac2a0436832398b711`.

## Execution V2 forward shadow

`execution_shadow_v1` observes the same live Level-5 SQLite/WAL in read-only
mode and never starts a second collector. The frozen model records buy and sell
predictions no later than 15 seconds after each UTC quarter hour. Missing or
late predictions are permanently journaled as `MISSED`; they cannot be
backfilled. Primary, frozen-stress and fee-neutral-stress outcomes are appended
to a separate table only after 125 seconds. SQLite triggers forbid updates and
deletes, and prediction/outcome tables have independent record-hash chains.

The service is deployed as `octobot-execution-shadow` with no network, a
read-only root filesystem, all capabilities dropped and read-only source and
evidence mounts. Only `/execution-shadow` is writable. Its protocol starts at
`2026-08-28T09:30:00Z`, ends at `2026-09-27T09:30:00Z` and has logical hash
`e2e1b6264e70863f96f1efd763c4464d740507fcdcad8b730df46078f4539f9a`.
The live status is written to
`../octobot-local/execution-shadow/health.json`; the compact journal is
`journal.sqlite`. After the fixed 30-day cutoff the official verdict is
latched once and mirrored in `forward-evaluation.json`. Even a pass authorizes
only later paper integration with an independently validated parent signal.

## Binance/KuCoin cross-venue carry V1

`cross_venue_carry_v1` evaluates one frozen, delta-neutral funding-spread
hypothesis across the same 18 perpetuals on Binance USD-M and KuCoin Futures.
Every Monday at 00:00 UTC it ranks only the preceding 90 completed funding
settlements. It enters one hour later, long on the lower-funding venue and
short on the higher-funding venue, for at most three pairs. The 11.68%
annualized entry threshold is derived from a four-fill taker-plus-slippage
round trip stressed threefold and amortized over 30 days; it is not fitted.

```bash
python3 -m octobot.ai_strategy_lab.cross_venue_carry_v1 write-protocol \
  --output ../octobot-local/backtesting/research/cross-venue-carry-v1/protocol.json

python3 -m octobot.ai_strategy_lab.cross_venue_carry_v1 evaluate-prelock \
  --protocol ../octobot-local/backtesting/research/cross-venue-carry-v1/protocol.json \
  --binance-collector BINANCE_1H_FILE ... \
  --kucoin-collector KUCOIN_1H_FILE ... \
  --binance-funding BINANCE_FUNDING_FILE ... \
  --kucoin-funding KUCOIN_FUNDING_FILE \
  --output-root ../octobot-local/backtesting/research/cross-venue-carry-v1/experiments
```

V1 is rejected in development without reading confirmation or lock. Over 98
days, its actual funding contribution is `+0.1313%` and relative-price
contribution is `-0.0370%`, but base execution costs are `0.1600%`; compounded
net return is `-0.0666%`, Sharpe `-0.3004` and triple-cost return `-0.3860%`.
All three folds and all 18 leave-one-symbol-out runs are negative. This result
rules out the frozen weekly rule; it does not rule out collecting synchronized
cross-venue books as a new point-in-time execution and dislocation dataset.
Protocol SHA-256 is
`5cfc44dc9bf02a545a3c2af82249874d07c2009609332d2c6915fcd1b20a1af9`;
report SHA-256 is
`624607f00e2247c2b37d4fed42c74ebd8dad1148c7a012426ff2c90cf4a2fd18`.

## Synchronized cross-venue forward observer

`cross_venue_observer` is a separate public-data-only collector, not a V1
continuation and not a strategy. Every 15 minutes it requests 20-level Binance
and KuCoin perpetual books concurrently for the 18 common symbols, plus public
mark/index, current funding, funding interval, open interest and timing. It
stores equal-base executable curves for 100, 500 and 1,000 USDT per leg and
marks a row forward-eligible only when client request midpoints differ by at
most one second and both server books are no more than 30 seconds old (or five
seconds in the future). Cross-server timestamp skew remains diagnostic because
an unchanged but valid book naturally has an older last-update timestamp.

The canonical records are atomic `json.gz` files linked by SHA-256. A compact
JSONL index is rebuildable from those records and does not duplicate the full
payload. A full archive/index/hash/safety audit runs at least daily. Records
before `2026-08-29T00:00:00Z` remain warm-up only. The deployed
`octobot-cross-venue-observer` service mounts no OctoBot user data or private
credentials and exposes no order path. Its local health file is
`../octobot-local/cross-venue/health.json`.

## Retracted interpretation: overlapping weekly signed-flow factor V2

`signed_flow_factor_v2` forms a new high-minus-low vintage every eight hours
and holds 21 overlapping `1/21` sleeves. A source audit performed before any
further variant found that this is not the manuscript's Table 29 holding rule:
there, `N` is the single eight-hour funding interval and "weekly" describes the
reported return frequency. The frozen V2 artifacts remain immutable evidence
of a distinct experiment, but V2 is retracted as a faithful replication and
must not be used to select another signed-flow variant. V1 is the relevant
seven-day-formation/next-eight-hour test.

V2 is rejected in development despite a clear improvement. Net return is
`+8.8083%`, annualized `+3.4272%`, with four of five folds and 16 of 18
leave-one-symbol-out runs positive. Sharpe is only `0.2936`, drawdown is
`29.4891%`, half the months are positive and triple-cost return is `-7.6777%`.
The 2025 confirmation and 2026 lock remain unmaterialized. Protocol SHA-256 is
`c1ae4642b55a1e5bf4f702d7ebc1693ce5b898261e45f2b442ccdcae58b54de4`;
report SHA-256 is
`d1a82dd1b8d6a3ac0cf3b06fafb79f9cc3efe00629f0720c436ac64bc5b916ee`.
The separate `RETRACTED_INTERPRETATION_AUDIT.md` alongside the report records
the correction without changing the protocol, report or trajectory.

## Eight-hour spot/perpetual log-basis factor V2

`basis_factor_v2` is preregistered before outcome evaluation as the faithful
timing correction of basis V1. At each completed 00:00, 08:00 and 16:00 UTC
boundary it ranks `log(perpetual close)-log(spot close)`, buys the bottom three
and sells the top three for the next eight-hour block. Spot remains signal-only;
only perpetual returns and signed funding enter P&L. There is no weekly holding,
overlap, inversion, filter, threshold or long-only variant. The unchanged 8-bps
turnover cost and 3x stress apply to every net target change. Development is
diagnostic reuse; the basis-family 2025 confirmation and 2026 lock remain
sequentially sealed. The frozen logical protocol SHA-256 is
`15339149fb30d26bf64ca03e5b92a74007738ec106f5ce22121474c997c2639d`
before the pre-outcome data-quality addendum. A structural input check found a
missing eight-hour block. The amended policy never interpolates or bridges a
return across a gap: it flattens the prior segment with cost and reopens the
next segment from flat with cost. No signal, gate or economic parameter changes.
The amended logical protocol SHA-256 is
`d0946c23e1cb76ae5d4158f5dc6c38bbeb6c200b137e306c2fead1cda6532015`.

V2 is rejected in development. Across 2,743 valid outcomes it returns
`-78.6796%` (`-46.0647%` annualized), with Sharpe `-3.0781`, drawdown
`79.6015%`, zero positive folds out of five and zero positive leave-one-symbol-
out audits out of 18. Price and funding contribute an additive `+81.4716%` and
`+10.6408%`, but `3,022.9333x` turnover costs `241.8347%`; triple-cost return
is `-99.8324%`. Confirmation and lock remain unmaterialized. No post-result
inversion, long-only conversion or cost reduction is permitted. Report SHA-256
is `8e58bbf90bb963c5b5274ef91fff287d315558b760a5b230698da71e1677be64`.

## Seven-day basis-momentum factor V1

`basis_momentum_v1` is preregistered before outcome evaluation from Equation 70
and the first row of Table 21 in the institutional manuscript. At each completed
eight-hour boundary it computes the preceding seven-day cumulative spot return
minus perpetual return, buys the highest three values and sells the lowest
three for the next block. The source-selected 21-block formation is fixed; no
other lookback, inversion, filter, threshold, overlap or long-only variant is
tested. Spot is signal-only, while perpetual price, signed funding, unchanged
8-bps turnover cost and 3x stress determine P&L. A 21-block contiguous history
is mandatory after a data gap. Development is diagnostic reuse and the 2025
confirmation plus 2026 lock are sequentially sealed.
The frozen logical protocol SHA-256 is
`eb678d81a0434138b36a765a1817a1f3a16188b23858ab84cb12c7d8c2e315dd`.

V1 is rejected in development. Across 2,743 valid outcomes it returns
`-85.2584%` (`-53.4567%` annualized), with Sharpe `-3.6241`, profit factor
`0.7102`, drawdown `85.3881%`, zero positive folds out of five and zero
positive leave-one-symbol-out audits out of 18. Price and funding contribute
an additive `+61.4682%` and `+6.1537%`, but `3,171.4667x` turnover costs
`253.7173%`; triple-cost return is `-99.9087%`. Confirmation and lock remain
unmaterialized, forward validation does not start and no orders are authorized.
No post-result inversion, alternate formation horizon, filter, overlapping
holding, long-only conversion or cost reduction is permitted on this sample.
Report SHA-256 is
`64b87a8ea24c299a14e9ac6d9e1a48036dc342ad0a7e29cbc801e1b323b642dc`;
development trajectory SHA-256 is
`9010caa427c2a2ba4284c20b2426463ce38eb8b235181603efc5a91ac6445db1`.

## Three-factor relative-value confluence V1

`relative_value_confluence_v1` is preregistered before outcome evaluation as a
fixed intersection of three directions documented by the same institutional
manuscript. At every complete eight-hour boundary, a long must be
simultaneously in the lowest log-basis third, highest seven-day basis-momentum
third and highest seven-day signed-flow third; a short must satisfy all three
opposite conditions. The strategy stays flat unless both sides are present,
selects at most three names per side and allocates `0.40x` gross to each active
side. There are no fitted thresholds, alternate lookbacks, filters, hysteresis,
overlapping holdings, inversion or long-only variant. Perpetual price, signed
funding, unchanged 8-bps turnover cost and 3x stress determine P&L. Development
is diagnostic reuse; 2025 confirmation and 2026 lock remain sequentially
sealed. The frozen logical protocol SHA-256 is
`75f9ee9f4890ab7df216f2daeeb715901dbc3d7d1926614420b1cedd90dd3add`;
the protocol file SHA-256 is
`0b59f83e29d757a9840775a658eb4486b26b1fbc20d11dffcaf04fb838b37761`.

V1 is rejected in development. It is invested in 1,643 of 2,743 blocks
(`59.90%`) and returns `-54.8458%` (`-27.2117%` annualized), with Sharpe
`-1.1025`, profit factor `0.8637`, drawdown `72.2011%`, one positive fold out
of five and zero positive leave-one-symbol-out audits out of 18. Price and
funding contribute an additive `+94.6108%` and `+7.6818%`, but `2,169.4667x`
turnover costs `173.5573%`. The cost-allocated long side is positive
(`+14.7587%`) while short is `-86.0234%`; triple-cost return is `-98.6048%`.
That asymmetry is training evidence for a separately preregistered long-only
family, not permission to rewrite V1. Confirmation and lock remain
unmaterialized and no orders are authorized. Report SHA-256 is
`6f65a37bb3e627bc8fa61ecf0f108e6619682f232635558a5863cdda92b33d6a`.

## Cost-aware long confluence V2

`cost_aware_long_confluence_v2` explicitly treats the positive development
long leg of V1 as training information, not OOS evidence. It freezes exactly
six candidates before reusing development: the unchanged long three-factor
intersection, `0.40x` gross, crossed with reselection every 3, 9 or 21
eight-hour blocks and either no regime gate or a causal positive 28-day
equal-weight perpetual-market gate. Targets remain unchanged between anchored
boundaries; costs stay at 8 bps per net turnover with 3x stress. Only a
candidate passing the frozen full-development and five-fold training gates may
be selected, using maximin fold return, median fold Sharpe, lower turnover and
configuration id in that order. If none passes, no model is frozen and 2025
stays sealed. If one passes, that immutable winner alone may query 2025 as the
first OOS evidence, followed conditionally by the 2026 lock. The logical
protocol SHA-256 is
`5e080a7f96a80efbba0b3742d5e66f65f1039a85b74e07adefab5bd95be6aa55`;
the protocol file SHA-256 is
`20454ac84db7e2e9807059957f985e34bca2697a474e445a204f722b55784000`.

The official training run freezes no winner and does not open 2025. All six
candidates are positive at base cost, ranging from `+7.6573%` to `+91.4956%`,
but none passes all 13 training gates. Daily `always_on` returns `+91.4956%`
with Sharpe `0.9206` and four positive folds, yet loses `-9.6969%` under 3x
cost and exceeds the drawdown limit. Daily reselection with the 28-day market
gate is the only candidate combining 4/5 positive folds, Sharpe at least
`0.75` and positive 3x-cost return (`+5.5882%`); it returns `+54.4810%`, but
misses alpha (`4.7960% < 5%`), drawdown (`27.4316% > 25%`) and positive months
(`40%`). Consequently no `selected-model.json` exists, confirmation access is
false and no orders are authorized. The six results are declared training
information for a separately frozen V3; V2 gates are not relaxed. Design
report SHA-256 is
`12730365845fde08243919cd7b8fc444a9357f7b935ce2e757561d70ca42393f`.

## Training-selected long confluence V3

V3 openly selects a model after observing V2 training: daily reselection with
the positive 28-day equal-weight market gate was the unique one of six with
positive 3x-cost return, at least four positive folds and training Sharpe at
least `0.75`. This is not treated as evidence and does not turn V2 into a pass.
It freezes that exact configuration, signal, `0.40x` gross, calendar, costs and
regime before a single query of the still-sealed 2025 period. No other V2
candidate may be tried on 2025. The unchanged confirmation gates require
positive base and stress returns, at least 5% annual return and market alpha,
Sharpe `0.75`, profit factor `1.10`, drawdown no more than `20%`, temporal
stability and concentration controls. Only a full pass may open the 2026 lock;
even a double pass still requires 180 forward days. The V3 logical protocol
SHA-256 is
`0609925613459dd8b1b904df9c2b96b13987cee64853a21fdac23c90221e437d`;
the immutable selection-model file SHA-256 is
`995c3250f61c65db17c468a732abbc57adcf2acf7020427b75cfb8f771e9ed2c`.

The single 2025 OOS query is positive but rejected. Across 1,095 blocks, 414
invested, V3 returns `+5.0293%`, annualized `+5.0328%`, with annualized market
alpha `+8.4369%`, beta `0.1363` and drawdown `19.3845%`. It fails Sharpe
(`0.3284`), profit factor (`1.0484`), positive months (`25%`), positive
quarters (`2/4`) and 3x-cost return (`-8.7387%`). Nine of 14 gates pass. The
2026 lock remains unmaterialized and no orders are authorized. Calendar 2025
is now training-only for any later family; V3 cannot be retuned and retested on
it. Report SHA-256 is
`977836cacc3c17c006cfac0b65bb804abb406870b94efe83c3d6e27fe573ee6b`.

## Expanded-training long confluence V4

V4 declares July 2022 through December 2025—including the now-observed V3
confirmation—as training only and reserves January through June 2026 for one
OOS query. Before reading 2026 it freezes exactly 16 candidates: reselection
every 3, 9, 21 or 42 blocks crossed with no market gate, positive 28-day
equal-weight market return, positive 84-day return, or both. Signal, `0.40x`
gross, calendar anchor, 8-bps turnover cost and 3x stress remain unchanged.
One structurally eligible candidate is always selected by positive stress-fold
count, worst stress-fold return, median stress-fold Sharpe, base alpha, lower
turnover and configuration id, in that order. Selection is training, not an
economic pass. The frozen winner alone may query 2026; a failure cannot be
replaced on that block. The logical protocol SHA-256 is
`9e209d306143e31dd74499b757912cd62e912579994043f5a97e1ef0e2775d69`;
the protocol file SHA-256 is
`6b163e3221911e048e18c95f5fa7697e64fe426b89950086faccb9470ad7872a`.

Expanded training freezes `r9-always_on`: the unchanged long confluence,
`0.40x` gross, no market gate and reselection every nine blocks (`72h`). Twelve
of 16 candidates are structurally eligible. The winner has four positive
3x-cost half-year folds, worst stress fold `-17.2751%` and median stress-fold
Sharpe `0.4385`. Across 2022--2025 it returns `+121.4017%`, with annualized
market alpha `+10.3851%`, Sharpe `0.8916`, drawdown `30.7009%` and
`227.4667x` turnover; 3x-cost return remains `+53.8014%`. These are training
metrics, not a pass. The selected-model file SHA-256 is
`6d17aae4e351679667bd440603d27fceabe2b534bfb11bc0646feb1a190fee2e`.
The 2026 OOS period remains sealed and no orders are authorized.

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
