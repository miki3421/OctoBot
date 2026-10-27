# Broader offline verification of the frozen M1 SHORT candidate

**Recommendation: do not activate this exit candidate.** Its earlier exits
reduce observed adverse exposure, but underperform the same reduced quantities
held six hours in the available historical diagnostic and all declared stress
scenarios. The candidate, its thresholds, and every active strategy remain
unchanged. This is SINGLE_AGENT author verification, not independent validation.

## Scope and evidence

The operator authorized broader offline verification against the sizing-only
six-hour control, with no change to frozen rules or active strategies. The
existing protocol remains
`a77bc705b996d5680c5dd9301351e64f0f58ab9e9dcc9a56795c3cb234351aa8`;
its sizing/exit modules and earlier evaluator retain their exact SHA-256
identities from the preparation lock. No fitting or parameter search occurred.

The reused coherent Original snapshot ends at **27 October 2026, 09:25:46 UTC
/ 10:25:46 CET**. Its complete 18-symbol price grid spans **28 September
20:10 UTC to 27 October 09:25 UTC**, with the first 24 hours reserved for
the unchanged volatility/signal context. There are 8224 five-minute rows,
six incomplete grid rows and **79 M1 trigger observations on 13 UTC dates**.
Contiguous-input checks remain mandatory: incomplete rows invalidate the
affected 289-row windows rather than being filled with favorable prices.

Two evidence levels are kept separate:

1. **Contemporary-basket event:** the prior 26 October conditional result
   remains unchanged: adaptive exit -9.04 USDT versus +0.88 for the same-size
   six-hour control, using the actual M1 entry context and its faster managed
   book stream. It is still only one historical event, not prospective proof.
2. **Broader fixed-basket diagnostic:** apply the unchanged current caps as
   an explicitly retrospective conditional fixture across the available
   historical records. The six-symbol basket was selected on 25 October;
   its use on earlier dates carries selection bias. This broader exercise
   tests exit behavior conditional on that basket. It does **not** claim
   that the basket, M1 account or authority existed on those earlier dates,
   or independently validate portfolio selection.

Each historical episode uses a **10000 USDT reference capital**, starts with
only the conditional SHORT exposure, and is scored independently. Equity is
not compounded between these episodes. These sums are neither the actual
M1 balance nor a monthly portfolio return; no account was created or reset.
Eight basket episodes are not 48 independent asset bets.

## Paired method and preregistration

The earlier sizing/exit policy was not edited. The extended evaluation plan
was separately recorded before accepted economic scoring, including:

- The unchanged M1 detector, 289-row past-only panel, 0.25% planned episode
  risk, volatility/depth/cost sizing and per-asset lot flooring.
- Both arms receive **identical entry quantities, entry book, fees, funding
  conventions and execution assumptions within each pair**. Only the exit
  controller differs. The control retains the existing six-hour deadline.
- First eligible M1 signal per UTC day, with a common conditional entry
  schedule respecting six hours after the slower completed six-hour control.
  Extra entries that an earlier candidate exit might permit are not scored.
  This isolates exits; it is not an endogenous replay of the complete account.
- Entry uses an observed book whose collection starts after the delayed due
  time and which is available within the existing 120-second entry window.
  Exit intents require a later collected book. Partial covers reduce only
  the remaining position and retain their costs and timestamps.
- A full six-hour comparison must have observation gaps no larger than 120
  seconds, with up to five additional minutes for a qualified exit. Missing
  entry/outcome data remain explicit and cannot score as zero profit.
- Funding uses observed settled rates only, each arm's quantity strictly
  before settlement, and a strictly earlier recorded mark no older than
  1800 seconds. These marks are simulator estimates. Late rate availability
  does not substitute the current post-cover quantity. Unknown funding at
  exit makes a case unqualified, rather than a favorable zero-cost result.

The declared scenarios are base processing latency of 20 seconds; latency of
60 seconds; and 60 seconds with doubled commissions plus 2 bp additional
adverse book widening per side, in addition to the existing 2 bp per-leg
slippage. Stress sizing is recomputed by the same frozen risk formula for
both arms, so cross-scenario quantities may differ. No stress parameters
were selected after observing their P/L.

The main comparison uses the intersection of episodes qualified in every
scenario. A transparently labeled coverage supplement also retains all
base-qualified cases; it does not replace or modify the main common sample.
It was added after inspection of the main result using the uniform rule
"include every selected case already qualified in base but excluded only
by another scenario", independent of the sign of its P/L.

### Collection and persistence clocks

The first extended reader equated an Original equity-row timestamp with the
source book's collection end. All 13 proposed episodes therefore failed its
timestamp check; it accepted **no economic pair**. The retained V1 result
is unavailable coverage, not an economic result to discard or optimize.

Inspection showed that Original timestamps represent **executor persistence
after collection**, for example 14:05:29 versus collection end 14:05:16.
Evaluation V2 retains both clocks, uses recorded persistence as a conservative
availability time, and independently binds every used book to its **exact
18-symbol persisted mark vector**, content hash and source collection times.
A later persistence time cannot turn a forecast funding point into a settled
source observation. A mismatched book, future component or stale quote fails
closed. No file mtime is treated as evidence of availability.

V1 and its exact hash-matching evaluator source are retained. V2 was frozen
before accepted scoring with evaluation ID
`31d614bd2e8d5502c4912c84dd8abce646249e2dca0fad941ff39d847513d808`.
Only the offline data reader changed; candidate rules, scenarios and cohort
criteria did not. The separate frozen evaluation revisions are committed as
`d55cbbd5` and `d2c5893f`.

## Results

### All eight base-qualified historical episodes

| SHORT exit | Total net USDT | Winning baskets | Worst final basket | Worst observed intermediate executable P/L | Mean hold |
| --- | ---: | ---: | ---: | ---: | ---: |
| Frozen candidate | **+53.25** | 5 / 8 | -11.00 | -21.59 | 1.95 h |
| Same quantities, six hours | **+106.39** | 6 / 8 | -26.89 | -40.66 | 6.01 h |

The candidate's incremental exit effect is **-53.13 USDT**. It improves three
events and worsens five. Its lower observed adverse P/L also reflects the
shorter time in the market; it is not by itself evidence of predictive skill.
Intermediate values include observed executable cover costs and are sampled,
not guaranteed continuous bounds.

| Signal date, UTC | Candidate | Same-size six hours | Difference | Candidate exit |
| --- | ---: | ---: | ---: | --- |
| 30 September | +19.20 | +25.39 | -6.19 | Profit giveback |
| 1 October | +4.88 | +20.90 | -16.02 | Signal invalidation |
| 2 October | +45.72 | +39.65 | +6.07 | Profit giveback |
| 14 October | +1.32 | +16.49 | -15.17 | Signal invalidation |
| 15 October | -11.00 | -16.80 | +5.80 | Signal invalidation |
| 16 October | +0.59 | +14.64 | -14.05 | Signal invalidation |
| 22 October | -2.17 | +33.01 | -35.18 | Signal invalidation |
| 24 October | -5.29 | -26.89 | +21.60 | Signal invalidation |

The main cause is **exit timing**, rather than extra commissions. Gross
price P/L differs by -52.82 USDT; candidate commissions exceed the control
by only 0.03, and recorded funding contributes another -0.28 difference.
Both arms make the same sized opening/cover round trip. All arithmetic
reconciles to realized cash flows, commissions and signed funding.

### Six episodes common to all declared scenarios

These six dates are 30 September and 1, 15, 16, 22 and 24 October. Results
below share the same event set, unlike totals across unequal coverage pools.

| Scenario | Candidate net | Same-size six-hour net | Incremental exit effect |
| --- | ---: | ---: | ---: |
| Base, 20 s | +6.21 | +50.25 | **-44.04** |
| 60 s | +2.39 | +41.19 | **-38.80** |
| Doubled commissions, wider book, 60 s | -15.15 | +21.00 | **-36.16** |

In base the candidate improves two of six exits. Five exits are signal
invalidations and one is profit giveback. No loss-stop outcome drives this
common sample. The adverse relative result persists after omitting any one
of the three represented UTC weeks: -21.83 to -35.79 USDT in the common
base sample, and -29.71 to -39.55 for all eight base-qualified events.
This is a descriptive sensitivity, not a statistical confidence interval.

## Missing cases and source limits

The 13 selected dates are all retained in the output, including failures:

- **5, 7, 19 and 26 October:** Original observation gaps exceed the declared
  120-second comparison bound somewhere in the required window.
- **8 October:** no entry book qualifies within the declared delayed entry
  window.
- **2 and 14 October:** qualify in base, but not with the 60-second entry
  delay. They appear in the eight-event coverage supplement and are absent
  from the six-event common stress pool.

There is no favorable gap filling, manufactured funding or zero-P/L imputation.
The faster managed M1 book stream supports the previous 26 October diagnostic
even though Original's slower persisted stream has a gap in that window.
Those two datasets and their capital contexts are not pooled or silently
substituted. All 4342 consumed book records were hash-checked and matched to
their recorded mark vectors; private copies preserve their provenance.

The historical basket selection, four-week duration, small number of events,
correlation inside each basket, missing periods, assumed execution delays and
independent reference-capital episodes prohibit a claim of general predictive
skill or robust account profitability. LONG closure/restoration effects,
future equity feedback, complete account risk counters, weekly selection and
candidate-only additional entry opportunities are outside this conditional
study. It also does not establish whether the sizing module beats the
original full quantities; that question is held constant within each pair.

## Interpretation and operational decision

The frozen recovery test can classify a temporary rebound as sufficient
reason to abandon the SHORT. On 22 October it closes a small loss before
the later decline that benefits the six-hour control. Conversely, on
24 October it limits damage during a rebound, and the 2 October profit
controller preserves more of the prior favorable move. The mechanics work;
the available tradeoff is not an improvement in net economic performance.

**Keep this candidate inactive and record it as not qualified for activation.**
The current evidence argues against these particular adaptive exits under
the project's net-performance objective. It does not establish that every
adaptive exit is unsuitable. Preserve this negative result and frozen rules;
any later recovery/regime hypothesis needs its own preregistration and new
qualification rather than an optimized threshold on these same cases.

Use the same-size six-hour branch as the offline reference for that future
work. This is not an instruction to deploy reduced quantities, retire the
active M1, or change Original. No account, approval, authority, trading rule,
collector, UI, monitoring service or schedule was changed here.

## Verification and delivery

- **89 focused tests passed:** 77 existing controller/runner/authority tests
  plus 12 evaluator tests, including delayed funding quantity, strict prior
  marks, partial cover cash flows, missing/future funding, source-versus-
  persistence time, exact mark-vector binding, future-price exclusion,
  stress-copy isolation and unknown exposure coverage.
- Original SQLite integrity is `ok` on the reused sealed copy; its content
  hash is unchanged. No integrity scan or full analytical query ran against
  an operating writer.
- Candidate protocol, sizing/exit implementation, adapter and prior evaluator
  hashes are unchanged. The accepted V2 evaluator and common-pool result also
  retain their pre-scoring hashes; the coverage supplement is separately
  timestamped and cannot overwrite that result.
- Twelve operating lab containers remain healthy with identical IDs, start
  times and automatic restart counts. The selected profile remains paper
  only. Temporary verification processes use existing images with no network,
  read-only source mounts and bounded CPU/RAM; no dependency was downloaded.
- Scoped and repository Git whitespace checks pass. Unrelated local changes
  were preserved. No strategy activation, account creation, promotion or
  operating restart occurred.

Sources: `scripts/qualify_m1_short_broader.py`, its evaluation contracts,
`scripts/supplement_m1_short_coverage.py` and the new evaluator tests. Private
evidence remains in `m1-broader-20261027`: sealed input references, inventory,
both evaluation revisions, original books, paths, common results, transparent
coverage supplement, test logs and final runtime/hash verification. The
companion JSON contains sanitized summary and episode results.

Work card: `work-card-0287a16d-6f2f-491e-8d17-bc27b23bf4ba`.
