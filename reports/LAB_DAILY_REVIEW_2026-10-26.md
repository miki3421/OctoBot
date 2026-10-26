# Daily laboratory review — 26 October 2026

Observation window: approximately 10:05–10:15 CET (UTC+1). Read-only operational
audit with private evidence snapshots. No strategy, risk threshold, ledger,
scheduler, credential or active service was changed. No sealed research outcome
was evaluated or manual email sent.

## Outcome

All 12 running laboratory containers are healthy with zero restart counts.
Collectors and account projections are fresh, the passive monitor runs every
five minutes, and the SMTP alert job completes successfully. Nevertheless, the
monitor correctly reports three alert codes from two underlying problems:

1. `PAPER_ACCOUNT_BLOCKED:m1` and `PAPER_DAILY_NOT_EXECUTED:m1`: today's ordinary
   M1 slot was denied by the persistent `daily_identity` input error.
2. `FORK_RISK_MISMATCH`: FAST/HALF realized allocation risk differs by 4.0652%,
   exceeding the frozen 2% tolerance. This is a comparison-quality alert, not
   a 4% account loss or a stopped executor.

Qwen's descriptive report was also rejected by its validator. Storage capacity
on the large filesystem needs attention before its warning threshold is hit.

## Account performance

Common reporting cutoffs: 25 and 26 October, 10:05 CET. Each account uses its
latest actual observation at or before the cutoff, with no interpolation.
Maximum boundary lag is 296 seconds for FAST/HALF, 43 seconds for Original and
35 seconds for M1. These are descriptive approximately 24-hour changes, not a
scientific ranking of strategies with identical risk and inception dates.

| Paper account | Equity, USDT | Approx. 24h change, USDT | Approx. 24h return | Current gross exposure |
| --- | ---: | ---: | ---: | ---: |
| Original | 9740.16 | +15.40 | +0.158% | 25.44% |
| FAST | 9860.00 | +9.74 | +0.099% | 7.82% |
| HALF | 9850.63 | +7.36 | +0.075% | 7.62% |
| M1 gradual + SHORT | 9747.82 | +7.83 | +0.080% | 12.69% |
| BTC intraday SHORT control | 9998.94 | 0.00 | 0.000% | 0.00% |
| BTC intraday LONG + SHORT | 9998.94 | 0.00 | 0.000% | 0.00% |

The modest recovery does not erase cumulative losses. M1's 24-hour window
includes part of the retired version: the gradual successor started only on
25 October at 12:27:40 CET. Its own equity change is +3.92 USDT (+0.040%) from
the preserved 9743.91 USDT boundary, before a full day of observation. This is
insufficient evidence of an improvement, particularly with today's input fault.

Six LONGs remain in each V13-family account. M1 holds AAVE 1.37, BCH 0.55,
BTC 0.005, DOT 153, LTC 4.1 and NEAR 24.2. Its initial six half-reductions
remain recorded, with no additional fills since 25 October at 12:28:38 CET.

## M1: confirmed daily derivation defect

Today's 01:15 CET ordinary slot is `DENIED`, reason `daily_identity`.
The source proposal and closed daily history were available in time: the
18-symbol snapshot was published at 01:10:48 CET. The issue is not late bars,
a bearish economic decision or a breached daily-loss limit.

The managed runner narrows `self.universe` to the six held/budgeted execution
symbols. Its inherited `prepare_input()` passes that execution scope to
`v13_fork_runner.closes()`, which validates the original 18-symbol scientific
bundle. The first other symbol, ADAUSDT, therefore raises `daily_identity`.

An isolated, networkless reproduction using the exact published snapshot
produced:

```
full_universe 18 rows_each [61]
execution_universe 6 error daily_identity
```

This is a defect in the managed continuation and a gap in its qualification.
The previous full-copy control fixture stubbed ordinary baseline derivation
while exercising future mechanical stages, so it did not cover this production
scope combination. A repair must verify the complete original scientific
universe independently, then project approved targets onto the execution scope.
It must retain provenance checks, timestamps, no-repurchase rules, SHORT caps,
and explicit handling of newly admitted symbols. Merely ignoring extra source
symbols would weaken the wrong boundary.

The input error suspends new risk, including a potential SHORT entry. Protective
LONG reductions and SHORT covers can still execute on admissible books. All
110 observed M1 slots since UTC midnight were `NO_SIGNAL`, so no actual missed
SHORT opportunity is evidenced in this period. The missed ordinary slot must
remain in history; it must not be retroactively filled.

Automatic review renewed at 01:10:30 CET after the new closed daily history
arrived. The neutral wait from 01:00 until fresh history was published is
expected. No new symbol was admitted: LONG capacity is occupied. QNT and XMR
have positive two-day evidence, but budget checks prevent entry. Those scores
are not unconditional trading recommendations.

All six existing LONGs still fail the positive 30/120-day momentum condition
on fresh 25 October closes. Their next quantity stage is eligible no earlier
than **26 October 12:28:38 CET**, 24 hours after the actual first fills, and
still needs admissible execution data. SHORT capacity remains exactly
25.54583334%; the fixed LONG admission budget is 12.63964573%. A subsequent
admission would wait for a future ordinary slot and working baseline derivation.

## FAST/HALF and intraday

FAST and HALF both executed today's 01:15 CET slot. Their theoretical common
annualized volatility was 3.8360%; after execution the allocation estimates are
3.5824% and 3.7342%, respectively. This yields the 4.0652% relative gap. No
entry-block or skipped-leg note was recorded in that slot, consistent with
quantity rounding driving the residual mismatch. Seven of the 13 executed
slots currently fall within tolerance; the frozen protocol requires at least
95%. Preserve these observations and qualify the discrete allocation effect
before treating this comparison as evidence that FAST outperforms HALF.

Both intraday primary accounts have 289/289 warm-up rows, fresh data, no risk
or integrity halt, and `NO_SIGNAL`. Each is FLAT with two recorded fills and
unchanged equity in the reporting window. Gross realized P/L is -0.103 USDT
and fees are 0.9528 USDT: fees account for about 90% of the 1.0558 USDT loss.
The sample remains too small to prefer either strategy or loosen thresholds.
Independent stress scenarios are diagnostic paths, not additional live accounts.

The shared book reader logged four temporary `SQLITE_CANTOPEN` recovery episodes
since CET midnight, approximately 5.4–5.6 seconds each. The counter of 82 errors is
a retry count since runner start, not 82 separate outages or container restarts.
All recorded waits recovered; current source state is `AVAILABLE`.

## Storage, research and auxiliary components

- Root: about 88.6 GiB free; the large lab filesystem: 143.5 GiB free (17.70%).
  Passive telemetry measures 15.79 GiB additional use in the last 24 hours.
  At that unchanged rate, the 15%-free warning threshold would be reached in
  approximately 33 hours, during 27 October. This is an extrapolation from a
  single day, not a guaranteed exhaustion time.
- About 100 GiB is preserved audit evidence: roughly 51 GiB from the intraday
  latency qualification, 18 GiB from legacy retirement and 15 GiB from its I/O
  investigation. The live intraday pair uses about 28 GiB and scalping 29 GiB.
  Qualify compressed cold audit archives and payload deduplication for future
  ingestion; do not delete active journals or erase provenance to save space.
- Available memory is approximately 25.9 GiB. Swap is about 16.4 GiB used, with
  zero new swap-out in the latest sample and no sustained memory pressure.
- A/B/C remains `NOT_QUALIFIED`, with accounts not started. Public funding
  collection is fresh: the latest slot contains 29 valid receipts for 29
  symbols. Do not confuse this with a passed strategy comparison.
- The separate M1 observation records 2989/2989 due slots with no missing
  scheduled slots, 2700 usable feature windows (90.33%), and four completed
  entry/exit captures. Its 289 insufficient-input slots are retained. Research
  performance stays sealed and was not inspected.
- Qwen BTC shadow remains intentionally suspended; its scheduler warning is
  expected. The daily descriptive Qwen report attempted at 07:00 CET was
  rejected as `unsafe_or_invented_text` after about 67 seconds. It supplies no
  usable report and has no trading authority.
- Failed historical one-off deployment/security probes remain visible in
  systemd's failed-unit list. Active periodic monitor/collector jobs checked
  today completed successfully; no failed-unit history was cleared.

## Integrity, limits and next work

Coherent bounded read-only snapshots of Original, M1, the paired FAST/HALF
ledger and approvals passed full `PRAGMA integrity_check`. Original/M1 equity
reconciles with positions, fees and funding; filled order quantities reconcile
with held quantities. No live ledger was repaired or rewritten.

The intraday journals are much larger. Their bounded full-backup attempts did
not finish within the four-second capture budget and yielded unusable empty
temporary copies, which are not counted as evidence. The four active account
state tables passed limited read-only `integrity_check('state')`; this does not
certify every event page or the shared input archive. Full qualification belongs
on a coherent offline copy with a planned I/O budget.

Priority order, recorded against existing backlog cards:

1. Fix M1 scientific/execution universe separation, with an unmocked published
   daily-bundle regression and a full-account continuation check.
2. Control storage growth and qualify compressed cold evidence before the
   warning threshold is reached.
3. Qualify FAST/HALF discrete-risk mismatch; preserve frozen tolerances and
   unsuccessful comparison observations.
4. Diagnose rejected Qwen descriptive reports; do not publish invented text.

No new parallel strategy, promotion, deployment or threshold change is part of
this daily audit.
