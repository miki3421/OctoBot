# FAST/HALF discrete post-cost risk qualification — 26 October 2026

The inactive correction meets the unchanged 2% relative forecast-risk tolerance in all 13 independent retained slot contexts. It repairs the six mismatches by reducing eight quantity increments across those contexts. **The actual running history remains 7/13 matched (53.85%).** No active code, account, allocation, risk threshold, collector, schedule or dashboard was changed.

This is an engineering qualification on consumed evidence, not a profitability result, a new prospective backtest, an independent scientific validation or an activation approval. Execution mode: SINGLE_AGENT; focused implementation, test and review lenses were performed by the same agent. MMTech company baseline and the existing project contracts apply.

## Defect and candidate

Continuous weight matching preceded quantity rounding and execution costs. Coarse quantity steps, especially BTC and small residual positions, can therefore leave the actual allocations outside the existing tolerance. The tolerance and covariance formula have not changed: 60 closed daily returns, 80% sample covariance plus 20% its diagonal, annualized volatility from each post-cost equity and quantity vector.

The frozen engineering contract is `docs/research-protocols/fast-half-discrete-risk-candidate-v1.json`. For each proposed plan the pure candidate projects complete net symbol orders from the real pre-slot financial state. If the risk gap exceeds 2%, it tries one quantity increment less on the higher forecast-risk arm, keeps only strict gap improvements with no increase in that arm's forecast risk, and chooses the smallest gap with a lexical symbol tie-break. It never expands the proposed absolute quantity or reverses its sign. Every trial reprices the complete net order against the original book, avoiding successive reuse of the same depth.

The walk is bounded at 1,000 iterations. A lack of a permitted one-increment improvement is an explicit non-solution of this algorithm, not proof that no other mathematical allocation exists. It does not flatten both accounts simply to manufacture equality. The candidate is not imported by an active runner and has no persistence, network or execution interface. Its returned projected fills are calculations; `execution_authorized` and `orders_authorized` are always false.

## Retained evidence and reconstruction

The input consists of coherent, sealed offline copies of the common parent and paired ledger, plus the exact 13 retained market records. Both SQLite copies pass full `PRAGMA integrity_check`. Their hashes and book hashes match before and after the read-only run. The qualification used the existing local OctoBot image with no pull, network or added dependency, one CPU and a 1 GiB memory bound. Code, contract and execution-dependency hashes are recorded in the companion JSON.

All 13 original executed slots, 14–26 October, reproduce their quantities, fees, continuous weights and post-cost forecast volatilities within the declared numeric bounds (quantity/fee 1e-8, weight/volatility 1e-10). The reconstruction advances only the actual recorded fills and funding. Candidate states are never carried into the following historical day, and no later prices or P/L are used to select a trim. Already matched contexts remain unchanged.

Historical risk-policy permission outcomes are taken from the retained slot records. Intermediate high-water/daily-start/cooldown counters are not independently reconstructed from every passive observation. The real gate implementation is exercised separately in synthetic controls; the report does not claim a complete historical policy-state replay. Funding debt outcomes are likewise retained, while the candidate also checks provided funding points for missing, stale, future, duplicate and intervening-gap observations. This does not replace full held-quantity/cursor funding reconciliation.

The paired market/minimum veto recorded on 25 October remains binding, including on every candidate trial; no suppressed increase is reintroduced. No historical row was removed from the 13-slot denominator.

## Independent slot results

Gaps below are relative differences between the two annualized forecast volatilities, not returns. Execution drag is the incremental loss of equity from fees and adverse execution at the same reference marks in that isolated context.

| Slot UTC | Actual risk gap | Candidate risk gap | Quantity reductions | Incremental drag, USDT |
| --- | ---: | ---: | --- | ---: |
| 2026-10-14 | 0.0000% | 0.0000% | Unchanged | 0.000000 |
| 2026-10-15 | 7.3825% | 0.0024% | HALF BTCUSDT 0.001 -> 0.0; HALF ETHUSDT 0.03 -> 0.02 | 0.087389 |
| 2026-10-16 | 2.7791% | 0.3037% | FAST ZECUSDT 0.02 -> 0.01 | 0.011638 |
| 2026-10-17 | 0.5205% | 0.5205% | Unchanged | 0.000000 |
| 2026-10-18 | 6.3304% | 1.2711% | FAST ZECUSDT 0.01 -> 0.0; FAST ETHUSDT 0.01 -> 0.0 | 0.035456 |
| 2026-10-19 | 1.8012% | 1.8012% | Unchanged | 0.000000 |
| 2026-10-20 | 2.4438% | 0.2846% | FAST ZECUSDT 0.01 -> 0.0 | 0.010663 |
| 2026-10-21 | 1.7470% | 1.7470% | Unchanged | 0.000000 |
| 2026-10-22 | 0.8904% | 0.8904% | Unchanged | 0.000000 |
| 2026-10-23 | 2.0377% | 1.1770% | HALF BTCUSDT 0.005 -> 0.004 | 0.081483 |
| 2026-10-24 | 0.0815% | 0.0815% | Unchanged | 0.000000 |
| 2026-10-25 | 1.3906% | 1.3906% | Unchanged | 0.000000 |
| 2026-10-26 | 4.0652% | 1.2855% | HALF BTCUSDT 0.003 -> 0.002 | 0.050483 |

Across these independent diagnostics, the sum of incremental fees is 0.1957125 USDT and the sum of incremental execution drag is 0.2771125 USDT. These sums are neither realized trading results nor the costs of a continuous corrected historical path. The largest repaired-context gap is below 2%; 26 October moves from 4.0652% to 1.2855% by reducing the HALF BTC target from 0.003 to 0.002 BTC.

## Failure controls and verification

All 28 focused tests pass: 16 candidate tests and 12 existing fork-runner tests. The candidate tests cover deterministic output and unchanged inputs; exact post-cost accounting; one-arm daily-loss, drawdown, daily-entry and cooldown vetoes; paired spread, minimum and exposure vetoes; preserved protective exits; missing/debt/future/stale/intervening-gap funding; partial depth and substep reductions; full-close minimum exceptions; stale/altered market data; invalid/off-grid quantities and invalid covariance; indivisible mismatches; one-sided/degenerate risk; bounded iteration; short-sign preservation; and repricing a complete order from the original depth.

Missing funding receives no risk-match pass or assumed zero funding. Partial executions are not silently counted as matched. An indivisible synthetic mismatch remains exposed and unqualified rather than closing both sides. Risk/market vetoes remain paired for increases while valid protective reductions remain possible.

After qualification all 12 lab containers are healthy, with the same IDs, start times and automatic restart counts as before the task. The selected profile remains `local_ai_trading`, real trader disabled, simulator enabled and `deterministic_alignment` selected. No running service was restarted. The active FAST/HALF mismatch alert still refers to the actual uncorrected ledger and must not be cleared on the strength of this offline result.

## Decision and remaining work

The candidate is technically suitable for the next integration qualification. The scientific protocol still requires at least 80 paired executed slots and at least 95% matching over the evaluated executions; 13 consumed one-slot contexts do not satisfy that validation or establish FAST's superiority to HALF.

Before any operational change, integrate the pure projection into a versioned candidate using the full current risk-policy state and funding reconciliation, qualify complete atomic slot execution and restart recovery on copies, and declare an explicitly authorized future version boundary. Preserve the original observations and economic outcomes. Do not silently upgrade the frozen ongoing experiment or open another parallel account. There is no activation in this delivery.

Reproducibility artifacts: `octobot/ai_strategy_lab/v13_discrete_risk_candidate.py`, `scripts/qualify_fork_discrete_risk_candidate.py`, `tests/unit_tests/ai_strategy_lab/test_v13_discrete_risk_candidate.py`, the frozen contract, and the companion JSON report. Raw databases and observed books remain in private audit evidence outside Git.
