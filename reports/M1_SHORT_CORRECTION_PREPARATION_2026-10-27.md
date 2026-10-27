# M1 SHORT sizing and exits: frozen candidate and qualification

**Prepared, mechanically qualified, economically unproven; not activated.**
The operator requested a correction on the existing M1 account, preserving
the maximum SHORT budget, anti-repurchase and gradual LONG reductions, with
rules fixed before verification and Original unchanged. This delivery prepares
that candidate and reports the first unfavorable economic result without
retuning it. SINGLE_AGENT, author verification, no independent acceptance claim.

## Preregistration

The complete policy was frozen at **27 October 2026, 09:20:28 UTC / 10:20:28 CET**,
before candidate tests, new ledger captures or the economic replay. It was
committed separately as `13c89e0a`.

- Version: `m1-short-risk-exits-candidate-v1`.
- Protocol ID: `a77bc705b996d5680c5dd9301351e64f0f58ab9e9dcc9a56795c3cb234351aa8`.
- Protocol file SHA-256: `f0aec307f7fb6fa2f15d5727bb4dfa34fab70d8abd1ef553717da4d9d864514b`.
- The separate implementation/evaluation lock, sealed before the first
  economic evaluation, is SHA-256
  `7786c66f9c8c5fea042b15ed0d79b7a0d52fae3eaf503de000feb8a3a179c40a`.
- Protocol, controller, adapter and evaluator identities were rechecked after
  the results. **No threshold, parameter or candidate code was changed in
  response to those results.** Subsequent additions were further mechanical
  tests and reporting only.

The previously examined historical events are not independent test data.
Freezing today does not turn earlier market outcomes into prospective evidence.

## Exact rules

### Quantity and authority

The account remains `v13-m1-short-paper-v1-5e761f0cedac`. The original six
per-symbol SHORT authority caps remain identical, totaling
**25.5458333431% of equity**. Unused capacity is not redistributed.

At each qualified entry, define a planned episode loss unit
**R = 0.25% of current account equity**, including inherited profits/losses.
This is a sizing budget, not a promised loss limit under gaps or unavailable
liquidity. No capital or risk high-water mark is reset.

The volatility model consumes exactly 289 consecutive five-minute rows
(24 hours) for the unchanged 18-symbol M1 panel. Every price is positive and
finite, observed at or before its grid time, and no more than 120 seconds old.
There are 288 past five-minute returns. Covariance uses the sample matrix
with 20% diagonal shrinkage; variance is scaled by 12 to an hourly horizon.
For the proposed weighted SHORT basket:

`stop distance = max(1%, 2 × estimated hourly basket volatility)`.

Start from the existing capped allocations and apply one common downward
scale so that:

`basket notional × stop distance + estimated round-trip costs <= R`.

Costs use observed two-sided depth VWAP, 2 bp adverse slippage per leg and
the existing observed fee. Quantities are floored separately to each contract
step. Actual rounded weights, covariance and costs are recalculated and the
budget rechecked, with at most 16 downward iterations. No iteration can
increase the common scale or any authority cap. Full-authority depth is
checked conservatively before sizing; missing depth does not become a free
or guessed execution.

No executable lot or invalid model/book rejects new SHORT risk. Existing
authorized protective LONG closing remains possible, following the same M1
entry-veto behavior. The existing Risk Guard, funding debt, policy validity,
per-asset/gross caps and dedicated daily limits still apply.

### Exit control

The episode is anchored to **actual filled SHORT quantities and entry prices**.
A reversal allocates commissions proportionally between the LONG quantity
closed and SHORT quantity opened; it does not assume equal halves after the
gradual reductions. Prior LONG realization and inherited funding are excluded
from the SHORT episode's profit/loss.

The monitored value is the net P/L of covering the current SHORT on the
observed asks: price P/L plus recorded episode funding, less the opening
SHORT commission, current cover VWAP/slippage and projected cover commission.

Exit priority is fixed:

1. **Loss stop:** executable episode net P/L is at or below `-R`.
2. **Profit preservation:** arm only after executable net P/L reaches `+R`;
   exit after giving back `0.5R` from the observed executable peak.
3. **Signal invalidation:** BTC's past-hour return is at least zero and no
   more than half of the unchanged 18-symbol panel is declining, on two
   distinct consecutive five-minute slots. Missing data or a slot gap resets
   confirmation. Repeated reads of one slot cannot count twice.
4. **Maximum hold:** retain the existing six-hour deadline.

An exit decision persists as an intent. It cannot execute on the same book
used to decide it: a later observed book is required. The first exit reason
remains sticky through restart and rebound. Partial exits retry only the
remaining protective reduction, without waiting for the original six-hour
deadline after an early exit decision.

Missing executable valuation or funding prevents an adaptive decision and
remains explicit; the existing timeout path remains available on qualified
books. The candidate does not invent liquidity or treat unknown funding as
zero. Consequently neither the stop budget nor a profitable peak guarantees
an executable price or maximum realized loss.

### Preserved behavior

The M1 entry detector, five-minute entry delay, one episode per UTC day,
six-hour post-exit cooldown, daily loss/drawdown vetoes and risk-batch limits
remain unchanged. The existing 50% / 25% / remainder LONG stages keep their
fresh daily confirmation and at least 24 hours between completions. The
anti-repurchase rule continues to prevent automatic restoration of closed
LONGs. Covering a SHORT may not open or restore a LONG.

## Implementation and confinement

- `v13_m1_short_risk.py` is pure deterministic calculation, without I/O,
  exchange clients, service management or execution capabilities.
- `v13_m1_short_candidate.py` is an **offline-only** subclass of the existing
  automatic M1 runner. It has no main or activation entrypoint. A sealed
  work marker and paths under a private audit work copy are mandatory before
  it opens the account. Operating modes, outside/symlink write paths and
  writable Original/seed sources are rejected.
- The existing single-writer transaction is retained. Plans, episode anchors,
  peak/confirmation state, intents, fills and audit events commit or roll back
  together. There is no second account, broker decision or delegated authority
  expansion.
- A new candidate may start only in NORMAL phase with no pending intent and
  no legacy SHORT. An already open old episode must finish under its existing
  rules; this preparation cannot adopt it retrospectively.
- The operating immutable runtime was not changed. Candidate code and test
  configuration exist only in the fork and private qualification artifacts.

## Mechanical qualification

**77 focused tests passed:** 16 new pure-controller tests, five new offline
confinement tests and 56 existing M1 paper/weekly/successor/automatic tests.
They cover future/stale/missing prices, grid gaps, volatility and cost sizing,
per-symbol caps, lot floors, fee splits, executable profit versus mark-only
profit, clock/duplicate handling, consecutive recovery, sticky exits,
read-only sources, anti-repurchase and existing gradual/authority behavior.

The real candidate runner also passed a complete-copy control fixture using
all **337 existing orders**:

- The existing account and successor epoch remain unchanged; all old order
  rows compare exactly, not just by count.
- It actually opens the risk-scaled synthetic SHORT on a subsequent book.
- A deliberate exception after fill/episode recording rolls back the plan,
  fills, state and control atomically; restart safely retries once.
- A simulated adverse move persists a loss-stop intent without a same-book
  fill. Restart preserves it; a thin next book causes an actual partial cover.
- A fresh intent covers the remainder promptly on another book, before the
  original six-hour deadline. Later reentry/trigger cycles produce no LONG
  repurchases or extra fills.
- Exact SHORT authority, inherited epoch and account history survive; copied
  SQLite integrity is `ok`. A deliberately large adverse gap demonstrates
  why planned R is not a guaranteed realized-loss ceiling.

These are synthetic mechanics, not return claims. Three coherent source
backups took about 0.26 seconds for M1, 0.23 seconds for Original and 0.04
seconds for approvals. Integrity was checked only on private coherent copies.
Qualification used existing local images, disabled networking, bounded
CPU/RAM, read-only runtime/source mounts and private audit outputs. No
dependency or image was downloaded. Initial test-launch issues were missing
pytest and bootstrap/custody-test capabilities; the final unittest and
confined full-copy runs passed. Those earlier logs remain retained.

## First economic diagnostic: unfavorable incremental exit result

Only the closed **26 October** episode is eligible for a conditional replay
using this successor's existing authority. Applying the six-symbol portfolio
chosen on 25 October to older events would introduce retrospective portfolio
selection. Those earlier episodes were therefore excluded.

All **618 required archived book records** were found, copied and hash-verified.
The replay uses the episode's exact consumed past-only signal panel and
pre-fill equity, observed later books, identical costs and fixed quantities
for the sizing-only control. It assumes 20 seconds of processing after
observed availability, followed by a strictly later book. This is an explicit
execution assumption, not measured counterfactual latency.

| SHORT path for the 26 October event | Net USDT |
| --- | ---: |
| Actual existing M1, original quantities and six-hour exit | +0.49 |
| Candidate reduced quantities, unchanged six-hour exit | +0.88 |
| Same reduced quantities with candidate adaptive exits | **-9.04** |
| Incremental effect of adaptive exit versus same-size control | **-9.92** |

The entry plan has R **24.37 USDT**, notional **1871.65 USDT**, and estimated
stopped risk including round-trip costs **23.83 USDT**. It uses about 19.2%
of equity while leaving the maximum 25.5458% authority intact. Its rounded
quantities are 2.16 AAVE, 0.88 BCH, 0.007 BTC, 244 DOT, 6.4 LTC and 36.1 NEAR,
all SHORT.

The adaptive branch exits for **SIGNAL_INVALIDATED** at 14:40:45 UTC /
15:40:45 CET. The same-size six-hour control exits at 19:40:49 UTC /
20:40:49 CET. The price subsequently recovered enough to leave that control
slightly positive. The actual episode, which was still losing in yesterday's
18:47 CET photograph, also eventually closed slightly positive. An interim
loss must therefore not be reported as the final episode outcome.

A descriptive excursion supplement, using the same quantities and executable
cover costs, observes a worst P/L of **-16.13 USDT before the corrected exit**,
versus **-30.75 USDT over the full six-hour control**. The observed maximum
was +8.65 in both windows, below R; profit protection did not arm. Early exit
reduced the observed adverse exposure but sacrificed the later recovery.
These extrema are sampled observations, not continuously executable bounds.

This is one conditional event, not a full portfolio backtest or independent
validation. It excludes hypothetical LONG closure/reentry changes and does
not propagate altered equity into future risk counters, selections or sizes.
Funding uses the simulator's recorded settlement reference marks and verifies
rate availability in the observed book. Risk, funding and execution limitations
remain explicit. **No economic edge or profitable correction has been shown.**

## Recommendation and handoff

Keep the candidate inactive. The implementation is ready for review and
further offline qualification, but its first eligible economic diagnostic
does not justify activating this exit rule. Do not silently tune the recovery
confirmation, stop budget or trailing threshold to rescue this event.

The next review must distinguish risk reduction from timing quality: retain
the sizing-only control and assess both adverse exposure and net return over
a broader causally qualified sample before proposing a same-account update.
No new parallel account is required. Any later operating handoff must bind
the exact candidate, existing account and authority, a coherent stopped
backup, unchanged historical prefix and a future NORMAL-phase boundary.
This prepared offline adapter deliberately provides no production loader.

Original, FAST, HALF, intraday accounts, approvals/delegation files, collectors,
operating ledgers and existing scheduled checks were not altered or restarted.
The current M1 continues under its prior rules. All twelve lab containers
were checked through Docker; the paper-only profile remains selected.

Reproduction artifacts: the frozen protocol JSON, both new modules,
`tests/integration_tests/m1_short_candidate_full_copy.py` and
`scripts/qualify_m1_short_episode.py`. Private evidence is retained as
`m1-short-correction-20261027`: coherent copies, exact books, freeze/verification
locks, synthetic full-copy results, unit logs and conditional replay output.
The companion report JSON contains sanitized aggregate results only.

Work card: `work-card-220efad0-fc3d-4564-82d5-a7a3a6568376`.
