# M1 successor: economic attribution and correction priorities

Evidence cutoff: **26 October 2026, 17:47:05 UTC / 18:47:05 CET**.
This is the economic review requested after the disappointing results, not an
implementation, new comparison account or strategy approval. SINGLE_AGENT,
author verification only. Accounts, thresholds, services, collectors and the
future dated operational checks were left unchanged.

The central finding is that the old LONG portfolio caused nearly all the loss
since the copy. The successor has stopped replenishing those LONGs, but has
not changed the SHORT entry, holding or exit logic. Its current loss comes
from the still-open SHORT episode. Maintaining the SHORT authority while
reducing LONGs also changes the balance between the two sides substantially.

## Reconciled economics

| Recorded period | LONG net | SHORT net | Account change | Commissions | Net funding |
| --- | ---: | ---: | ---: | ---: | ---: |
| Retired predecessor: 17 October to 25 October 11:27:40 UTC | -175.21 | +11.82 | -163.40 | 18.40 | -2.13 |
| Current successor: 25 October 11:27:40 UTC to cutoff | +2.80 | -10.42 | -7.62 | 2.97 | -0.05 |
| Whole M1 period since the copy | -172.41 | +1.40 | **-171.01** | 21.37 | -2.19 |
| Last 24 hours | -18.03 | -10.42 | -28.45 | 2.23 | +0.05 |

All values are virtual USDT. Side and account changes already include their
commissions and recorded funding; the two cost columns must not be subtracted
again. Realization of a previously open loss is not another equity loss.

The copy began at 9907.300220 USDT; the successor inherited 9743.905210;
cutoff equity is **9736.290109**. The successor has about 30.32 hours of history,
one open SHORT episode and no completed successor SHORT episode. Its -7.62
cannot be described as either a definitive rejection or a successful repair.

The apparently promising peak on 21 October was 9981.463526 USDT. Its gain
from the copy, +74.16, consisted of **+78.22 LONG and -4.05 SHORT**. It was not
evidence of successful SHORT forecasting. From that peak to this cutoff,
equity declined by 245.17 USDT.

The price component, measured using the actual recorded fill prices before
commissions and funding, is -147.46 USDT over the whole M1 period. Costs
aggravate the loss; price exposure explains most of its absolute size.

## What has changed, and what has not

The successor has recorded **12 protective maintenance fills and six M1 entry
fills**, with **zero LONG openings or replenishments**. The first two agreed
reduction stages completed. At the current SHORT entry, the remaining six
LONGs were closed and reversed; the recorded account is now SHORT, not still
holding the reduced LONG quantities shown by its policy ceilings.

The anti-repurchase rule remains active. After covering these SHORTs, the
old six LONGs cannot automatically be restored, even if a positive ceiling
remains in the policy. The third maintenance stage only concerns a LONG
that still exists and meets its fresh-data conditions; it must not sell an
already absent LONG or accidentally enlarge a SHORT.

The per-symbol SHORT authority remains exactly **25.5458333431%** in total.
This is an authority ceiling, not a calibrated prediction confidence or
a promise that the full allocation is appropriate for every event.

At today's entry:

| Exposure valued at the actual entry fill prices | Notional | Approximate share of entry equity |
| --- | ---: | ---: |
| Remaining LONG immediately before the reversal | 572.10 USDT | 5.87% |
| SHORT after the reversal | 2478.18 USDT | 25.44% |

The nominal exposure becomes **4.33 times** the preceding LONG exposure.
This is not a volatility-risk ratio: the assets, covariance and path matter.
It does demonstrate that preserving the original SHORT budget while cutting
LONGs makes the SHORT an independent directional position rather than a
similarly sized hedge of the remaining LONGs. This behavior follows the
approved preservation rule; no unauthorized budget increase was found.

## SHORT episodes: continuation and rebound are not distinguished

| Signal date, UTC | Status at cutoff | SHORT net | Best observed intermediate P/L | Worst observed intermediate P/L |
| --- | --- | ---: | ---: | ---: |
| 19 October | Closed | -4.05 | +20.01 | -18.60 |
| 22 October | Closed | +42.19 | +45.22 | -5.06 |
| 24 October | Closed | -26.31 | +15.93 | -39.94 |
| 26 October | **Open, not final** | -10.42 | +13.69 | -38.27 |

Intermediate values include SHORT opening commissions and funding recorded
up to that point, but omit a hypothetical closing commission, spread and
depth. They are observed mark valuations, not executable exits or promised
recoverable profit. The 19 October path has a maximum observed gap of
348.85 seconds; no unobserved intragap extrema are invented.

The three closed baskets total +11.82 USDT; **one basket supplies the entire
positive aggregate result**, offsetting two losing baskets. Individual
symbols inside the same event are correlated exposures, not independent
statistical replications. Three closed events cannot establish an edge.

The signal requires a past-hour BTC decline of at least 1% and broad market
weakness. It does not estimate whether selling will continue, exhaust itself
or reverse. All four admitted events had 18/18 negative breadth. The existing
`new_24h_low` feature differs across events, but these four observations do not
justify adopting it as a new profitable discriminator.

The scheduled five-minute delay was followed by 15-58 seconds of observed
entry lag; completed exits followed their six-hour deadline by 53-66 seconds.
No entry veto, partial basket or missing exit explains the three completed
outcomes. A five-minute deliberate delay and smaller execution latency can
affect prices, but this review does not invent alternative entry books or
claim a faster fill would have prevented the losses.

The current episode entered at **13:40:32 UTC / 14:40:32 CET**. Its unchanged
exit is due at **19:40 UTC / 20:40 CET**, subject to the observed-book checks.
At cutoff it has already moved from +13.69 to a -38.27 observed trough and
then back to -10.42. The six-hour timeout has no earlier signal-invalidation,
position stop or profit-preservation exit. The inherited daily/drawdown
guards veto new risk; they are not substitutes for those position exits.

The retired predecessor restored LONGs 35-64 seconds after closing SHORTs.
Its next six hours of recorded LONG contribution were -1.96, -1.51 and
+17.91 USDT for the three events. Therefore simply waiting six more hours
would not consistently have helped. The successor's anti-repurchase rule
already addresses the automatic restoration problem; it does not address
SHORT rebound exposure.

## Symbol attribution and turnover

| Symbol | LONG net since copy | SHORT net since copy | LONG net under successor | SHORT net under successor |
| --- | ---: | ---: | ---: | ---: |
| AAVE | -48.68 | +1.91 | -1.18 | -1.48 |
| DOT | -43.13 | -0.81 | -0.11 | +1.22 |
| LTC | -40.21 | -3.46 | +0.85 | -1.95 |
| BTC | -25.44 | -3.34 | -2.26 | -4.74 |
| NEAR | -20.77 | +6.68 | +2.89 | +1.61 |
| BCH | -7.17 | -2.85 | +2.62 | -5.06 |

AAVE, DOT and LTC account for **76.57% of the net aggregate LONG loss**.
This identifies where the loss occurred, not permanent unprofitability of
those assets or a reason to ban their SHORT side. For example DOT's current
SHORT and LONG contributions have opposite signs. The complete symbol and
period table is in the companion JSON.

Original over the same accounting interval lost **162.56 USDT**, compared
with M1's 171.01. Their 8.45 USDT difference decomposes as follows:

| M1 minus Original, common copy-to-cutoff period | USDT |
| --- | ---: |
| Price component before commissions and funding | +9.59 |
| Additional commissions | -19.46 |
| Difference in recorded funding | +1.43 |
| **Net difference** | **-8.45** |

The measured gross advantage is insufficient to finance the added turnover.
This price component already uses actual execution prices, so it includes
their embedded spread/slippage; it is not clean forecasting alpha. No
second deduction for those embedded execution effects is appropriate.
Actual quantities and rules differ, so this is accounting attribution,
not a controlled causal estimate of the SHORT filter alone.

## Why new coins have not entered

The latest recorded automatic review, **26 October 11:29:57 UTC**, admitted
no symbol. Recalculation from its exact retained, hash-verified market record
gives:

| Candidate | Reviewed notional | Observed spread | Estimated round-trip cost | Recorded reason |
| --- | ---: | ---: | ---: | --- |
| QNT | 96.03 USDT | 0.0872% | 0.2897% | Cost above 0.20% |
| XMR | 94.27 USDT | 0.1052% | 0.2756% | Spread above 0.10%; cost also exceeds 0.20% |
| PUMP | 93.48 USDT | 0.0706% | 0.2531% | Weak signal and excessive cost |

Costs include the same depth VWAP, 2 bp adverse slippage per leg and
commissions as the automatic assessment. The candidate score measures rule
compliance, not predicted profitability. New entries are therefore being
evaluated and rejected for observable reasons; lowering the cost barrier
to manufacture portfolio activity has no economic support in this review.

## Decisions and next correction

1. **Maintain the anti-repurchase and gradual-exit controller.** It has
   performed its intended quantity-control function. Do not restore the
   old six LONGs or redistribute their released cash automatically. Do not
   label this narrow mechanical success proof of profitable timing.
2. **Correct SHORT position management next, on this same account.** Prepare
   one explicit rule family for position loss, signal invalidation and
   volatility-scaled profit preservation, with six hours as a maximum holding
   period rather than the only normal exit. Its parameters must be declared
   before evaluation, use only information available at each decision, and
   include the real observed exit costs, gaps and adverse rebounds. Do not
   select the threshold that captures these four observed peaks.
3. **Separate SHORT authority from deployed quantity.** Keep the approved
   ceiling intact, but prepare a usage rule tied to a declared episode risk
   target and observed volatility/depth, rather than automatically deploying
   the old LONG-derived capacity after the LONG portfolio has contracted.
   Compare any claimed timing improvement against the effect of simply
   taking less risk. No allocation or sizing rule is changed by this report.
4. **Price every extra round trip before admission or reentry.** The next
   corrected candidate must improve net results, not just mark-only timing,
   and remain viable with worse execution assumptions. Keep the current
   rejected admissions visible; no model download or replacement-symbol
   purchase follows from this analysis.
5. **Review the economic controller, not only service health.** The existing
   reporting should make active episode net P/L, adverse excursion, profit
   giveback, exposure before/after entry and incremental cost visible.
   These are proposed monitoring improvements, not new services installed
   here. Unknown coverage must remain unknown, and an open trade cannot
   count as a completed win or loss.

The retired M1 predecessor remains retired. The current successor is
**economically unproven and requires a SHORT-management correction proposal**;
its repaired LONG controller should not be discarded solely because the
unchanged SHORT module is losing in its first active episode. Neither
increasing SHORT frequency nor adding a larger model is supported by the
present evidence. No other existing strategy is approved or retired here.

## Operational confounders and verification

- DAILY slots on 18 and 19 October remain MISSED; 26 October remains DENIED
  by the historical `daily_identity` error corrected later that day. No
  missed decision is retroactively filled or its opportunity cost invented.
- One M1 slot was missed, 288 had insufficient inputs, 12 additional
  triggers occurred during cooldown/active episodes, and four episodes were
  admitted. No evidence points to the one-episode-per-day cap as the cause
  of these realized losses.
- Both source ledgers were captured by incremental read-only SQLite backups
  in less than 0.30 seconds each. `PRAGMA integrity_check` was `ok` on the
  private copies, never scanned against the live writer.
- All fills reconcile to copied quantities, entry prices, realized P/L,
  commissions and funding; totals reconcile to equity and the independently
  recorded clone/successor anchors. Reversal commissions are split by actual
  closing/opening quantities, not assumed to be half after the staged cuts.
- Episode SHORT results reconcile to the total SHORT contribution; successive
  successor phases sum to the current-version change. Exact common time
  boundaries use prior observed marks for at most 180 seconds, without future
  interpolation. Funding remains the simulator's recorded estimate.
- **24 focused accounting tests passed**: 14 attribution and ten current-window
  tests. The initial attribution-test invocation lacked its module search
  path; the corrected invocation passed. Real evidence checks fail closed
  on source/copy identity, unavailable boundaries or inconsistent totals.
- Twelve lab containers remain healthy. No production restart, deployment,
  new account, approval, model download, trade or threshold change was made.

Reproduction: `scripts/analyze_m1_successor_economics.py --evidence` with the
private `m1-economic-20261026` evidence directory. The full private capture
contains two sealed ledgers, the clone receipt, UI/cache evidence, the exact
previously retained admission book, aggregate calculations and observed
episode paths. The companion JSON contains sanitized aggregate results.

Work card: `work-card-b23d7d70-7b83-490a-9174-2572ed5ff3e3`.
