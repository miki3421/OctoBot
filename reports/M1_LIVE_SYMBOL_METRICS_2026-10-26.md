# Current M1 per-symbol accounting UI — 26 October 2026

The operator accepted the next proposed priority: replace the fixed 23 October
M1 symbol-review table with current accounting. Delivery is SINGLE_AGENT with
author verification, not independent QA. No strategy, allocation rule, SHORT
authority, approval decision or operational ledger was changed.

## Result

The existing M1 review page now defaults to **the current successor period,
starting 25 October**. It also provides the last 24 hours, last 48 hours, the
period since the original M1 copy, and the retired predecessor's period. The
actual start/end and Italian local timezone are shown for every selection.
Rolling windows explicitly indicate when they cross the version boundary or
have less history than requested.

Each symbol shows net contribution, separate LONG/SHORT results, fees, recorded
funding, the Original reference and position at the selected period end.
Details retain realized P/L, initial/final open P/L, exposure, mark coverage,
observed drawdown and episode counts. The cards follow the selected period.
These are equity changes in virtual USDT, not reset or normalized account values.

Current automatic selection and approvals remain in the existing top section.
The obsolete initial reduction suggestions are no longer shown as pending
current actions. The unchanged 23 October report, including its original
proposals and SHA-256 identity, remains downloadable through the guarded archive
query on the same read-only endpoint.

## Accounting and publication

A separate, stdlib-only publisher reads the existing M1 and Original ledgers
through bounded incremental SQLite backups. It never performs a full scan or
integrity check on the live writer and has no ledger-write or trading interface.
Only its own generated temporary scratch copies and JSON cache are replaced.
Operational journals, retained audit evidence and collector data are untouched.

Calculation occurs on the private coherent copies. Filled-order replay,
average cost, realized P/L, fees and recorded funding reconcile to each copied
state and equity observation before publication. LONG/SHORT reversals allocate
realization to the closing side and fees proportionally between closing and
opening exposure.

For each account, symbol and window:

`net = realized delta + final open P/L - initial open P/L - fees + recorded funding`.

The symbol sum and side totals reconcile against the window's equity change.
The M1 clone and successor baselines also reconcile to their independently
recorded economic equity anchors, so inherited open P/L is not counted twice.
Both accounts use the same exact interval, ending at the earlier coherent
source cutoff. The prior observed mark may be carried for at most 180 seconds;
there is no future interpolation. A missing held-position boundary produces
unknown per-symbol results and an unavailable account total, not zero or a
favorable partial sum. Newly admitted M1 assets outside the Original universe
are explicitly marked as untraded on Original.

Funding remains the simulator's recorded settlement estimate. Historical
observation delay is not reconstructed. Exposure, control rules and the retained
missed/denied ordinary slots differ between accounts; this is descriptive
accounting, not proof that the new strategy is profitable or scientifically
superior. Any inconsistent ledger or economic anchor fails publication.

`trading-lab-m1-live-review.timer` publishes every five minutes, at minutes
02/07/12/17/… plus 30 seconds, outside the ordinary 00:15–00:17 execution window.
The web route reads only the small validated JSON projection. It verifies
custody, schema/account, content identity, periods, side arithmetic and totals.
It retains the last valid result with explicit stale/refresh-failed status if a
refresh fails. A future, altered or untrusted projection is not displayed.

The publisher is an independent oneshot with private networking, strict
filesystem protection, read-only operational inputs, a 768 MiB memory ceiling,
50% of one CPU, low priority and a 120-second service deadline. Each source copy
has its own four-second capture budget. No package, model or image download was
needed. Its immutable root-owned runtime is `trading-lab-m1-live-review-v1`;
code and configuration are SHA-256 checked before every invocation.

## Validation

- **35 focused tests passed**, covering independent cash-flow expectations,
  inherited P/L, reversals and fees, funding reconciliation, unknown boundaries,
  future-data exclusion, explicit predecessor/common periods, new symbols,
  stale/failed/tampered projections, custody, unchanged archive identity and
  existing profile/terms/method guards.
- Real account snapshots reproduced all five windows for M1 and Original.
  Every available total reconciled at numerical roundoff. The current-period
  baseline exactly matches the successor's recorded 9743.905210263938 USDT.
- GET-only browser journeys passed on both isolated preview and the actual
  dashboard, on desktop and mobile. They checked the default current epoch,
  all five windows, displayed/API totals, side detail, archive download and
  unchanged automatic-review section. Injected stale/missing/unavailable
  responses are explicitly browser-only controls. No approval POST, other
  write request or JavaScript error occurred.
- The confined publisher completed its initial publication. Its first natural
  timer refresh at **14:17:30 UTC / 15:17:30 CET** also succeeded. Source copying
  took about 0.39 seconds for M1 and 0.33 seconds for Original; complete bounded
  calculation took about 12.43 seconds under its CPU limit.
- Only `octobot-local` was restarted to load the route/read model. All twelve
  lab containers are healthy with the same IDs/images/mounts; every other
  container retains its exact start time and automatic restart count.
- The exact 25.54583334% SHORT authority and paper-only profile are unchanged.
  The separate one-date daily-slot checker remains enabled for 27 October,
  **00:25 UTC / 01:25 CET**.
- `systemd-analyze verify` passed, apart from an unrelated existing OPS browser
  unit warning. Final scoped Git whitespace checks pass.

## Delivery and recovery

The publisher and UI read model are separate from the pinned M1 runner. No
runner or collector upgrade is required. Source changes include the accounting
publication module, minimal publisher entrypoint, read model, UI assets, tests
and the two dedicated systemd unit templates.

The pre-existing dirty shared controller is preserved. Its one-line route
change is delivered separately as `patches/m1-live-metrics-route-20261026.patch`;
the complete unrelated working-tree changes are not swept into this delivery.

If a future UI/publication regression requires rollback, stop only the new
publisher timer, restore the prior review assets and reverse that scoped route
change, then reload only the dashboard. Preserve generated evidence and the
Original/M1 ledgers; no account state restoration is needed or authorized.

Private evidence is retained under `m1-live-metrics-20261026`: coherent snapshots,
unit log, publisher manifest, preview/live browser results and screenshots,
validated JSON readback and before/after runtime checks. The scratch publisher
does not retain another growing set of database copies on every refresh.

Work card: `work-card-3c4c8974-02fa-4f97-81c5-670381fab790`.
This delivery completes the first selected priority; FAST/HALF qualification,
archive-growth planning and the weekly OSS review remain separate work.
