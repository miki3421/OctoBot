# M1 SHORT structural invalidation — offline study, 27 October 2026

The new rule improves the historical total over the previous experimental
invalidation, but it does **not** establish reliable reversal detection or
justify activation. Waiting for structure prevents several premature exits;
it also delays two useful exits. Its advantage over six hours disappears in
the combined cost/latency stress. All operating strategies remain unchanged.

## Frozen hypothesis and custody

- Hypothesis frozen in commit `0aa8b14e`, before implementation, tests or new
  economic scoring. The implementation/evaluator is committed as `1ef64ed1`.
- Protocol: `docs/research-protocols/m1-short-structural-invalidation-v1.json`.
  Protocol ID: `b4474ccad3bb59d91f107674c3fb768b6b141fc2cdc88e7af76bbe6bf9cb7814`.
- The code, tests and previous input/result files were sealed before scoring.
  Verification lock: `78ef45523aab03589a7c80b5e56cea85bfdb0f0b9a64b3b829f382f250e9a618`.
- No parameter search, new downloads, live ledger scan, deployment or new
  account. The parent policy, adapters, evaluators and previous results remain
  byte-identical. Evaluation uses the previous coherent read-only SQLite copy
  and verified archive cache; integrity check returned `ok`.
- Execution mode: single agent; author verification, not independent QA.

## The rule

An invalidation needs **all** of the following, using only the latest complete
289-point panel on the five-minute grid:

1. BTC price above its slow EMA (24 bars, approximately two hours).
2. BTC fast EMA (six bars, approximately 30 minutes) above its slow EMA by at
   least `max(0.1%, 0.25 × estimated BTC hourly volatility)`. Volatility uses
   the sample variance of the preceding 288 five-minute returns, scaled by 12.
3. BTC slow EMA above its value three bars earlier, and BTC one-hour return
   nonnegative.
4. At least 12 of the fixed 18 symbols each above its own slow EMA, with that
   EMA rising over three bars and a strictly positive one-hour return.
5. These conditions confirmed on three distinct consecutive five-minute
   observations. First to third confirmation spans ten minutes. Missing or
   gapped data reset the count; duplicates cannot advance it.

EMAs start at the oldest price of each validated 24-hour window. No future
prices or subsequent outcome labels enter these features. This is a causal
proxy for structural recovery, not a guarantee of a lasting reversal.

Only invalidation changes. The parent sizing, SHORT authority, loss protection
at minus R, profit arming at plus R, half-R giveback and six-hour deadline stay
fixed. Funding, executable book depth, fees, slippage, delayed fills and partial
cover accounting are reused unchanged. The new module has no account or order
interface and is not imported by the operating runner.

## Matched comparison

Four arms share the same entry time, quantities and costs within each scenario:

- **Old invalidation:** the previous offline candidate, requiring BTC hourly
  recovery and at most half the symbols declining for two observations.
- **Structural:** the new invalidation plus unchanged parent protections.
- **Protection only:** parent loss/profit protection with invalidation disabled.
  This separates the structural rule's contribution from simply holding longer.
- **Six hours:** the same reduced entry quantities with the six-hour exit.

The old and six-hour outputs reproduce the prior study within `1e-8`, including
cashflows, fees, funding, clocks, quantities and exit reasons. The previous
eligibility/cohorts are reused rather than selected from the new outcomes.

Eight base episodes qualified: 30 September; 1, 2, 14, 15, 16, 22 and 24 October.
The six common stress episodes omit 2 and 14 October because the earlier
study could not obtain a timely entry book at 60-second latency. Five other
previously selected signals remain unavailable; they are not counted as zero
returns. The contemporary managed-account episode of 26 October remains outside
this Original-source cohort because of its previously documented coverage gap.

### Base scenario, all eight episodes

Amounts are **sums of isolated episode net P/L in USDT**, with a separate
10,000-USDT sizing reference per episode. These are not a compounded account
return, a full M1 portfolio backtest, or percentages to apply to current equity.

| Exit rule | Net P/L | Worst final episode | Worst observed intermediate P/L | Average hold |
| --- | ---: | ---: | ---: | ---: |
| Old invalidation | +53.25 | -11.00 | -21.59 | 1.95 h |
| Structural | **+117.28** | -17.66 | -21.59 | 3.67 h |
| Protection only | +93.17 | -27.74 | -27.74 | 3.84 h |
| Six hours | +106.39 | -26.89 | -40.66 | 6.01 h |

Structural improves four episodes, worsens two and leaves two unchanged versus
old invalidation: total difference **+64.02 USDT**. All three weekly differences
against old invalidation are positive. Against protection only it improves two
and leaves six unchanged: **+24.11 USDT**. These two interventions occur before
the protection-only loss stop. Against six hours it improves two, worsens three
and leaves three unchanged: **+10.89 USDT**. Removing week 43 changes that last
advantage to **-4.51 USDT**. Thus the small aggregate edge over six hours is
concentrated, despite the broader improvement over the old invalidation.

| Signal date (UTC) | Old | Structural | Protection only | Six hours |
| --- | ---: | ---: | ---: | ---: |
| 30 September | +19.20 | +19.20 | +19.20 | +25.39 |
| 1 October | +4.88 | +20.90 | +20.90 | +20.90 |
| 2 October | +45.72 | +45.72 | +45.72 | +39.65 |
| 14 October | +1.32 | +16.49 | +16.49 | +16.49 |
| 15 October | -11.00 | **-17.66** | -25.51 | -16.80 |
| 16 October | +0.59 | +11.10 | +11.10 | +14.64 |
| 22 October | -2.17 | **+33.01** | +33.01 | +33.01 |
| 24 October | -5.29 | **-11.49** | -27.74 | -26.89 |

On 22 October, old invalidation closed at 04:21 UTC. At that decision the
structural recovery count across symbols was zero: BTC remained below its slow
EMA, with negative slow slope and fast/slow gap. The new arm held to the
six-hour exit at 08:21 UTC and captured the later decline. Holding longer alone
produced the same result in this episode; this is not evidence of additional
predictive value from the structural exit itself.

On 15 and 24 October, the early old exits were useful: subsequent one-hour
BTC recovery was approximately +0.70% and +0.48%, with 17 and 16 symbols rising.
Structural confirmation delayed exits by approximately 55 and 51 minutes,
respectively, losing an additional 6.66 and 6.20 USDT versus old invalidation.
It nevertheless avoided the larger protection-only losses. The rule trades
false early exits for later recognition of some recoveries.

### Same six episodes in all stress scenarios

| Scenario | Old | Structural | Protection only | Six hours | Structural minus six hours |
| --- | ---: | ---: | ---: | ---: | ---: |
| Base, common six | +6.21 | +55.07 | +30.96 | +50.25 | +4.82 |
| 60-second latency | +2.39 | +43.50 | +22.90 | +41.19 | +2.32 |
| Doubled fees, doubled slippage, 60-second latency | -15.15 | +9.94 | +9.65 | +21.00 | **-11.06** |

Costs affect the existing risk-aware entry sizing; within each scenario all
four arms still have exactly the same entry quantities. Under combined stress,
the structural contribution over protection only is just **+0.29 USDT**. An
additional structural exit on 30 September gives up 18.01 USDT versus holding
with protections. The base result therefore fails the economic robustness
test against the six-hour control.

## Rebound versus reversal labels

The predeclared descriptive label observes the following hour from the last
closed five-minute grid at each actual invalidation decision. Continuation
requires BTC moving by at least `max(0.1%, half its causal hourly volatility)`
and at least 12 symbols moving in the same direction. Anything less is
ambiguous; missing future coverage is unknown, never imputed.

The six old base invalidations yield two failed rebounds, two continuing
recoveries and two ambiguous outcomes. The two structural invalidations both
have ambiguous subsequent-hour labels. Their later decision times mean these
are not matched precision/recall samples. They do **not** demonstrate accurate
prediction of a true reversal: much of the recovery has already happened by
the time the slow structure confirms it. Future labels are calculated only
after simulated execution and never affect features, eligibility or fills.

## Decision and limits

Retain this as a **promising but unqualified offline hypothesis**. Do not activate
it or tune it further on these outcomes. A useful next verification would be
on genuinely new episodes, preserving the four-arm controls and examining both
avoided early exits and delayed loss exits; this report schedules or starts
no such service. No reliable model of a lasting reversal has been established.

All these historical outcomes were already inspected. There is no untouched
holdout. The six-symbol basket was selected on 25 October, so earlier events
have basket-selection bias. Eight base events in three weeks are correlated
and too few for a promotion decision. Whole-account LONG exposure, gradual
reductions, daily guard state and endogenous entry/cooldown feedback are not
simulated. Intermediate loss figures use observed executable valuations, not
continuous market extrema or full-portfolio drawdown. Historical source/book
availability allowances remain those of the previous evaluator; this is not
evidence that the old pipeline met today's execution latency requirements.

## Verification and delivery

- **106 tests passed**, including causal windows, synthetic rebound rejection,
  breadth threshold, persistent confirmation, missing/gapped/duplicate data,
  loss/profit preservation, exact two-control reproduction, future-label
  isolation and existing M1 policy/successor/weekly regressions.
- Sealed source SQLite integrity `ok`; all 2,752 used compressed book records
  match the previous archive's bytes. All parent and previous study hashes match.
- `git diff --check` passed. Paper-only profile remains deterministic alignment.
- All 12 operating containers retain their identities, start times and restart
  counts, and remain healthy. No active account, collector or strategy changed.
- Full sanitized results and causal decision diagnostics are in the companion
  `reports/M1_SHORT_STRUCTURAL_INVALIDATION_2026-10-27.json`. The private evidence
  bundle retains the pre-scoring lock, four-arm paths, used-book manifest, test
  output and runtime verification.
