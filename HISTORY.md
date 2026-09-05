# Trading Lab History

## Scope and evidence

This document reconstructs the history of the local trading laboratory on the
`feature/local-only` branch. It deliberately separates:

- upstream OctoBot history, which starts in 2018;
- local implementation history, based on 82 commits from 23 July to
  28 August 2026;
- experiment history, recorded append-only in `/root/auto_trading_sys/spec.md`;
- material runtime evidence in the SQLite and JSONL journals under
  `/root/auto_trading_sys/octobot-local/`.

The local Git branch starts from upstream commit `57d8afbb` dated 17 July
2026. The operational decision journal starts on 22 July 2026, one day before
the first local commit. Therefore, the first local commit is a large snapshot
of work already in progress, not the absolute beginning of the project.

The figures below are research or paper-trading results. They are not evidence
of future returns and never authorize real orders, deposits, withdrawals or
automatic promotion.

## Timeline

### 17-22 July 2026: project foundation

The project adopts OctoBot as a local web and trading framework. Its intended
operational profile is KuCoin Futures, `BTC/USDT:USDT`, a simulated 10,000 USDT
portfolio and an append-only SQLite decision journal.

An Ollama integration with `qwen3:8b` is proven technically, while
`deepseek-r1:8b` is rejected for unpredictable completion. The LLM is then
removed from the operational dependency chain. The live baseline becomes
`deterministic_alignment`: only aligned TA evaluations on `15m`, `1h` and `4h`
can propose a direction; missing, tied or conflicting evidence becomes HOLD.
A deterministic Risk Guard remains non-bypassable.

### 23 July 2026: first local release and research laboratory

Commit `fb57df2d` (`v0.0.1`) adds the local Docker runtime, guarded strategy,
SQLite audit UI and the first version of `octobot.ai_strategy_lab`. It is a
large import: 63 files and roughly 6,800 added lines.

The first regime-adaptive strategies and small ML models are evaluated. V1 and
V2 lose money; V3 improves the result but fails external multi-asset
robustness. Logistic regression, gradient boosting and four deterministic
experts also fail after costs.

### 23-24 July 2026: trend, carry and shadow governance

Commit `4eccc233` adds trend portfolios, funding carry, income simulations,
bootstrap audits and isolated shadow runners. The trend V3 family produces
strong historical results on several periods but does not satisfy the complete
risk and regularity requirements. V14, a risk-budgeted trend plus idle carry
overlay, passes its normal historical gates and then fails an adversarial audit
with delayed execution, higher costs and partial positive funding realization.

The project begins freezing protocols before results, hashing input and output
artifacts, preserving superseded locks and forbidding automatic promotion.

### 24-28 July 2026: market visualisation and the Perfect Map/V5 branch

The dashboard receives percentage maps, diagnostic signals, public market
overlays and forward-status pages. A succession of Perfect Map students tries
to learn causal rules from hindsight labels. The most developed model,
`btc_future_path_surface_student_v5`, is attached to a separate Binance Futures
paper account.

The persistent V5 paper journal ultimately contains five closed trades, no
wins and -54.32 USDT. It never uses a real trader.

### 23 July onward: public-data collectors

The KuCoin multi-market observer starts collecting 19 spot/perpetual pairs,
funding, basis, liquidity and aggregated books every 15 minutes. A separate BTC
Futures Level-5 collector stores raw book and trade information for scalping
and execution research. Cross-venue Binance/KuCoin observations are added
later.

### 31 July-2 August 2026: operational hardening

Fixed take profit is replaced by deterministic protected exits. Paper orders
gain restart persistence, the decision journal gains append-only order events
and position outcomes, collector shutdown becomes safer, the main web service
gets automatic restart and an operations reporter adds backups and data-quality
checks.

### 26 August 2026: retirement checkpoint

V5, V3/V14 shadow and the legacy directional baseline are marked retired for
insufficient forward evidence. Their code and journals are retained. The main
profile disables both buy and sell orders; collectors remain available for
research.

### 27-28 August 2026: frozen research expansion

The laboratory evaluates scalping, queue flow, cross-venue lead/lag, funding,
basis, signed flow, carry, confluence, category momentum, cointegration and
several liquid-momentum families. Most show some gross information but fail
after turnover, stress costs, unstable folds or a persistently weak short leg.

The Level-5 line produces one useful non-directional result: learned passive
execution V2 shows a small saving relative to taker execution. A stricter
fee-neutral audit leaves buy positive and sell negative, so it proceeds only
to an orderless forward execution shadow.

### 28 August-1 September 2026: current forward candidates

A fixed 50/50 portfolio combines risk-budgeted trend V13 and expanded
cointegration. Its training result is positive and diversified, but is not an
OOS pass. The forward protocol starts on 1 September 2026 and cannot be judged
before 28 February 2027.

Liquid Market Breadth Forward V2 is also frozen. It reuses the diversified
observer's verified daily archive, has no network access and cannot create
orders. Its first economic bar is 1 September 2026.

### 2 September 2026: first official forward records after migration

The migrated server records the first official daily observations for both
current forward candidates:

- diversified trend plus cointegration records the 1 September bar at
  00:10 UTC on 2 September;
- breadth V2 records the same bar at 00:25 UTC, with breadth active on 27 of
  30 assets;
- both journals retain `orders_authorized=false`,
  `paper_orders_authorized=false` and `automatic_promotion=false`.

## Strategy and experiment ledger

| Family / version | Main result | Final status |
| --- | --- | --- |
| `deterministic_alignment` | TA agreement on 15m/1h/4h; operational journal baseline | Retired for new entries; audit history retained |
| Semantic Trend V2 | Correct physical trend semantics; +0.039% base, -0.694% at 3x costs on 46 trades | Rejected diagnostic; never deployed |
| `regime_adaptive` V1 | -7.387% training | Rejected |
| `regime_adaptive_v2` | -3.345%, PF 0.782 | Rejected |
| `regime_adaptive_v3` | +1.283% train, +0.876% OOS; multi-asset PF 0.992 | Rejected / research only |
| AI logistic target model | Negative walk-forward and final block | Rejected |
| AI logistic net-return model | -0.962%, PF 0.443 | Rejected |
| AI gradient boosting | Weak walk-forward; no final trades | Rejected |
| Four intraday experts V1 | PF 0.628-0.760 | Rejected |
| Four swing experts V1 | Best PF 0.833 | Rejected |
| Funding carry V1, Binance | Positive but irregular, low income capacity | Research only |
| KuCoin same-venue carry / rotation | +0.178% / +0.268%; expanded universe negative | Rejected |
| Trend portfolio V1/V2 | V2 transferability weak | Rejected |
| Trend portfolio V3 | Strong multi-period history; long drawdowns and weak regularity | Shadow evidence only, later retired |
| Trend V4 two-sleeve | Fails transferability and risk gates | Rejected |
| Trend V5 carry overlay | Fails regularity improvement | Rejected |
| Trend V6 drawdown governor | Risk falls but return and Sharpe collapse | Rejected |
| Trend V7 breadth filter | Return and regularity collapse | Rejected |
| Trend V8 strength ranking | Diversification and economics worsen | Rejected |
| Trend V9 multi-horizon | Late reaction; all principal gates fail | Rejected |
| Trend V10 logistic meta-filter | Better OOS risk metrics but temporally concentrated | Rejected |
| Trend V11 residual momentum | 0.141% annualized, 25.9% drawdown | Rejected |
| Trend V12 residual reversal | -16.0% annualized | Rejected |
| Trend V13 risk-budgeted | Good direct tests; narrowly fails final bootstrap/income gates | Training component only |
| Trend V14 idle carry overlay | Passes normal gates; fails V14-R1 adversarial audit | Not promoted; later retired |
| Trend V15 cost-aware carry | Fails stressed direct gates | Rejected |
| Trend V16 execution-guarded carry | Fails stressed drawdown and Sharpe | Rejected |
| Trend V17 rotating carry | Fails stressed direct gates; carry tuning stopped | Rejected |
| Trend V18 volatility brake | Keeps only 79.4% of V13 return and misses risk gates | Rejected |
| Income policy V1 | Fails no-pause gate under 5% haircut | Rejected |
| Income policy V2 | Passes simulation with prefunded finite blocks | Research policy only; no payments |
| Visual H1 percentage LONG | Diagnostic visual hypothesis | Archived |
| Visual H2 LONG/SHORT | Negative/insufficient diagnostic evidence | Archived |
| Perfect Map students V1-V4 | Hindsight imitation does not transfer reliably | Rejected / archived |
| Future-path student V5 | Five paper trades, zero wins, -54.32 USDT | Retired; journal retained |
| Perfect Map student V6 / precursor | Causal research extensions | Not promoted |
| Perfect Map forecaster V2 | Research forecast overlay | Not promoted |
| Price-path forecaster V1 | Research forecast overlay | Not promoted |
| Deterministic V5 veto V1 | Does not establish a robust improvement | Rejected |
| Deterministic direction veto V2 | Does not establish a robust improvement | Rejected |
| Deterministic event meta V3 | Audit/meta experiment | Rejected |
| Scalping micro-momentum V1 | No target classes in training | Rejected before final test |
| Scalping cost-aware V2 | PF 0.215 development, PF 0.417 diagnostic | Rejected |
| Queue-flow scalping V3 | Predictions remain net negative; zero trades | Rejected |
| Cross-venue lead/lag V4 | PF 0.098 development | Rejected |
| Microstructure regime V1 | Book features fail to improve price baseline | Rejected |
| Microstructure activity/direction V2 | No sufficient economic improvement | Rejected |
| Absorption markout V3 | Gross edge does not cover 14 bps | Rejected; directional book family closed |
| Passive execution V1 | Mechanistic maker-vs-taker baseline | Superseded by V2 |
| Learned passive execution V2 | Locked test passes; strict audit leaves sell negative | Active orderless execution shadow |
| Forward carry V1.1 | Evidence not ready before 21 September 2026 | Active gatekeeper, no economics yet |
| Cross-sectional funding carry | Funding gain offset by relative price and turnover | Rejected |
| Spot/perpetual basis V1 | -32.0%; turnover dominates | Rejected |
| Spot/perpetual basis V2 | -78.7%; extreme turnover | Rejected |
| Signed price-volume flow V1 | Insufficient economic robustness | Rejected |
| Signed price-volume flow V2 | +8.81% base, negative at 3x costs | Rejected |
| Cross-venue carry V1 | Gross edge below costs, net negative | Rejected |
| Basis momentum V1 | -85.3%; turnover dominates | Rejected |
| Relative-value confluence V1 | -54.8%; short leg and turnover dominate | Rejected |
| Cost-aware long confluence V2 | No candidate passes all training gates | Rejected |
| Training-selected long confluence V3 | Positive 2025, fails stress and stability | Rejected OOS |
| Expanded-training long confluence V4 | Strong training, -17.9% in 2026 lock | Rejected |
| Category momentum V1 | +8.2% base, -10.4% at 3x costs | Rejected |
| Cointegration pairs V1 | Promising but only nine trades | Training information only |
| Expanded cointegration pairs V2 | +9.92%, PF 2.158; fails count, months and one direction | Rejected as standalone |
| Diversified trend/cointegration 50/50 | +11.52% annualized training; +10.07% at 3x costs | Active forward OOS; gate no earlier than 28 Feb 2027 |
| Liquid cross-sectional momentum V1 | +20.74% annualized; short-loser sleeve negative | Rejected; training information only |
| Winner/BTC-hedged momentum V2 | Positive, but weak Sharpe/folds/drawdown | Rejected |
| Liquid market time-series momentum V1 | Positive and better than benchmark; misses four gates | Rejected |
| Liquid winners momentum V1 | Weak edge, large drawdown | Rejected |
| Liquid market breadth V2 | No historical reuse allowed; first record 1 Sep 2026 | Active forward OOS; gate no earlier than 28 Feb 2027 |
| TimesFM 3 multivariate zero-shot V1 | Calibrated q10-q90 interval, but price MAE 3.09% worse than unchanged and 49.51% direction accuracy | Rejected as directional/economic strategy; risk-calibration evidence only |

## Persistent evidence as of 2 September 2026

- Main guarded journal: more than 11,000 decisions, 33 closed paper
  positions, 15 wins and -87.21 USDT net P&L excluding funding.
- V5 paper journal: more than 3,600 decisions, five closed trades, no wins and
  -54.32 USDT.
- BTC Level-5 store: approximately 13 GB, over 35 million book events and
  approximately 3 million trade events.
- Public 19-market journal: approximately 700 MB, more than 3,800 archived
  15-minute records and about 98.2% coverage.
- Execution shadow: more than 950 completed outcomes; official evaluation is
  not due before 27 September 2026.
- Diversified and breadth journals: one official record each.

## Current interpretation

The laboratory has not demonstrated a strategy suitable for real trading. Its
strongest achievement is methodological: rejected strategies remain recorded,
forward blocks are protected from repeated tuning, runtime processes fail
closed and research services cannot authorize orders. The current useful work
is evidence collection for diversified trend/cointegration, breadth V2,
passive execution and forward carry. Everything else should be treated as an
archive unless a new, preregistered hypothesis explicitly depends on it.

## Post-migration operational cleanup — 2 September 2026

After the server migration audit, the retired Trend V3/V14 shadow and V5
Binance paper runtimes were stopped without deleting their evidence. The main
KuCoin paper simulator and the market, cross-venue, diversified, breadth,
Level-5, execution, carry-gate and operations collectors remained active.

The web interface was reorganized around current decisions:

- **Operations** now shows only safety, the paper account, persistence,
  collector freshness and the four active forward experiments;
- **Research Archive** contains the retired/rejected families and links to the
  permanent history and migration audit;
- **Decision Audit** shows 25 compact rows and loads raw JSON only for one
  selected decision; each row now distinguishes signal approval from an actual
  paper order, open position or closed trade with linked P/L;
- the operational chart no longer exposes rejected/hindsight overlays or the
  unvalidated ETH comparison;
- local paper profiles no longer expose a real-trading switch, and the server
  rejects attempts to enable the real trader for those profile IDs.

The cleanup changed presentation and runtime selection only. It did not alter
research protocols, model locks, gate cutoffs, risk parameters or persistent
journals.

### 3 September 2026: guarded paper reactivation

At the user's explicit request, the retired deterministic directional baseline
was reactivated for KuCoin Futures simulation only, to generate fresh execution
feedback. Approved long and short entries use an explicit 10% simulated
portfolio size while preserving the existing exposure cap, deterministic exits
and append-only audit journal. This is a paper experiment, not a research
promotion; the real trader remains disabled and no exchange credentials are
used.

The first new entry exposed a weakness of the vote-counting baseline. Decision
11177 opened a 0.012 BTC short at 78,032.8 after weak bearish majorities across
4h, 1h and 15m, then closed at the configured 1% stop of 78,813.1 for
-10.49289048 USDT including known fees. The baseline counts every directional
evaluator equally and the audit rationale displays the opposing bullish count
for bearish decisions. This event is retained as paper evidence; it did not
trigger a post-hoc configuration change.

### 3 September 2026: TimesFM 3 diagnostic

The user explicitly accepted the TimesFM 3 non-commercial license for private,
non-production research. The pinned 1.322 GB checkpoint was downloaded and
verified, then evaluated once inside a CPU-only, networkless container. The
preregistered multivariate query used 1,536 hourly observations, 25 variates,
four liquid assets and a 24-hour horizon at 1,130 daily origins.

TimesFM 3 terminal MAE was 254.637 bps versus 247.009 bps for unchanged price,
for -3.088% skill. Every asset had negative skill and pooled direction accuracy
was 49.513%. The q10-q90 interval covered 79.978% of outcomes, almost exactly
its nominal 80%, showing useful uncertainty calibration despite weak point and
directional forecasts. The frozen cost-aware translation generated only three
trades, far below the minimum 100, so its positive return, Sharpe and profit
factor are not credible evidence of an economic edge. Six of ten gates passed;
the conclusive verdict is `REJECTED_HISTORICAL_DIAGNOSTIC`. No forward observer,
paper strategy, order authority or automatic promotion was created.

### 4 September 2026: semantic audit and useful forward display

A second reactivation trade confirmed that the legacy BTC vote was not merely
unlucky. Decision 11195 opened another 0.012 BTC short at 81,157.3 and hit its
1% stop at 81,968.8 for -10.91250792 USDT net of known fees. Together, the two
fresh shorts lost -21.40539840 USDT. Inspection then found a semantic defect in
the strategy design: positive Double Moving Average and ADX values describe a
physical uptrend, but the generic vote converter interpreted every positive
evaluator value as bearish. The rationale counter for bearish decisions was
also displaying the opposing support count; that audit-only display defect was
fixed.

Both BUY and SELL entries of `deterministic_alignment` were suspended again.
It continues to write decisions for audit, but cannot open a new simulated
position. Existing positions are not silently deleted and the real trader
remains disabled.

A single offline Semantic Trend V2 diagnostic reused the existing frozen
Binance futures archive and a 6,695-row snapshot of the already-recorded input
matrices. It did not download data, start a collector, contact an exchange or
gain order capability. The candidate improved materially over the same legacy
execution, but still failed costs: 46 trades produced +0.039499% base with PF
1.0194 and -0.694142% under 3x costs with PF 0.7206. Long-only stress was
-0.178596%; short-only stress was -0.516468%. Four of nine gates passed, so the
immutable verdict is `REJECTED_HISTORICAL_DIAGNOSTIC` and no runtime was
created. Report file SHA-256 is
`e4ac62790a713cac9c3fb0ab16e7437abdb4926d35e011b908d5c3e69a762d49`;
trade artifact SHA-256 is
`df126bb7dcd40882a4ea8a8d0d509dbbb3f24ba4a8fb8d79d829d7b4a351cd35`.

The Operations page now reads the existing Diversified Trend 50% +
Cointegration 50% journal directly and shows its cumulative base/stress
return, latest daily return, gross target exposure and current theoretical
allocations. No extra process or duplicate data store was added. After its
first three official decisions the displayed cumulative result is +0.640166%
base and +0.600682% at 3x costs. This is explicitly labelled preliminary and
does not change its orderless status or its 28 February 2027 gate date.

### 4 September 2026: manually activated diversified paper account

At the user's explicit request, a separate `10,000 USDT` paper account is
armed for the frozen Diversified Trend 50% + Cointegration 50% targets. The
official observer and gatekeeper remain immutable and orderless; the manual
paper mirror has no network, credentials, exchange adapter or real-order
capability. It records simulated weight-rebalance fills and persists its own
SQLite ledger.

Activation is causal. The account is anchored after the already-known 3
September record, credits none of the prior `+0.640166%` forward result, starts
flat at exactly `10,000 USDT`, and opens its first target portfolio only after
the next new daily decision. Its initial state is therefore `ARMED`, with zero
positions and zero simulated orders. This sandbox is not an official forward
PASS and cannot alter the 28 February 2027 gate.

The hypothesis that the entire legacy strategy only needed to be inverted was
also tested. Across all 35 closed operational positions, actual gross P/L is
-68.4895 USDT and known fees are 40.13036994 USDT, producing the observed
-108.61986994 USDT net. Merely changing the sign at the same recorded exits
would produce only +28.35913006 USDT, not +108.62, because fees do not reverse.
The loss is concentrated in shorts: their same-exit inverse is +52.65614626
USDT, while inverting the longs is -24.29701620 USDT.

A path-correct inverse simulation on the frozen April--June matrix snapshot
uses the opposite entry side but recalculates each stop, profit lock, timeout
and cooldown. Its 58 trades return +0.222063% at base costs with PF 1.0850, but
-0.703735% at 3x costs with PF 0.7689 and zero positive active months. The
semantic error was real for Double Moving Average and ADX, especially in the
short votes, but other evaluators are intentionally contrarian. Consequently,
blindly reversing every signal creates a weak gross effect rather than a
cost-robust winning strategy.

### 4 September 2026: separate V13 portfolio chart

Operations now includes a dedicated read-only equity chart for the active
Diversified Trend 50% + Cointegration 50% experiment. It plots Trend V13,
Cointegration V2 and their combined forward equity on a common 10,000 USDT
index. The separately authorized paper account starts at its true activation
boundary and never inherits the already-observed forward return; its activation
and future virtual rebalances are shown as distinct markers with turnover and
estimated-cost details.

The chart reads the existing hash-chained decision journal and paper SQLite
ledger, creates no collector or duplicate archive, and validates chronological
order, finite positive equity, frozen lineage and disabled real-order
authority. The current display contains three OOS decisions plus the 10,000
USDT paper activation point. All 22 Operations controller tests pass, the live
page responds HTTP 200, and active services remain healthy.
