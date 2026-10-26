# FAST/HALF copied-ledger integration qualification — 26 October 2026

The discrete risk correction now has a complete **offline** integration adapter.
Funding, policy state, final fill accounting, atomic persistence and restart
recovery pass on synthetic controls and a complete current-account copy. No
running strategy, account, collector, service, schedule or UI was modified or
restarted. This is technical preparation, not an activation or profitability
finding. Work was SINGLE_AGENT with author verification, not independent QA.

## Inputs and inheritance

The paired and Original ledgers were captured by bounded read-only incremental
SQLite backup in approximately 0.084 and 0.273 seconds respectively. Their sealed
copies and the unchanged common parent pass full `PRAGMA integrity_check`.
The copied pair's last observation is **26 October 15:20:26 UTC / 16:20:26 CET**.
Both full initial states, including financial fields, order counts, position
generations, funding cursors and risk-policy counters, exactly match the copied
accounts. The legacy receipt remains byte-equivalent as JSON. No risk state,
capital, historical observation or inherited trade was reset.

The pinned legacy runner is unchanged. A separate adapter calls its ordinary
planning on copies, passes the resulting quantity vector through the qualified
post-cost repair from the same funded pre-slot states, and commits only the
final net fills. Position IDs/generations, order counts and daily increase/
cooldown state are updated only for those final fills. Provisional trials never
become orders or extra fees. Existing paired entry vetoes and protective
reductions are preserved; unresolved matching remains explicit.

An offline epoch records the adapter/candidate/base hashes, source-copy hash,
initial full-state digest and legacy receipt digest. Missing copies, altered
identities and attempted resets are refused. It does not replace the frozen
active protocol or confer authority to change a running account.

## Complete-copy cycle and real interruption

The complete copied-account exercise uses a deliberately synthetic mechanical
boundary of **27 October 00:15 UTC / 01:15 CET**. This is **not** a scheduled
activation. Original observed prices are held as explicit synthetic future
marks; synthetic funding points exercise reconciliation and atomic slot
funding. The actual cached 25 October input is explicitly relabelled as a
mechanical fixture. No actual 26 October closed scientific bundle yet exists
in this evidence, and future scientific-input qualification is false.

The real implementations perform book selection, passive grid recovery,
funding, risk checks, cached-input loading, planning and SQLite persistence.
Only the clock is controlled. This cycle does not test the live derivation of
an as-yet-unpublished future daily bundle and is not a corrected P/L backtest.

After valid passive recovery, an injected HALF-state write failure rolls back
both states and the slot's fills/funding. A second run abruptly exits the Python
process with code 91 during the decision transaction after forcing real SQLite
page writes. It leaves a **2,774,536-byte DELETE journal**. Reopening the work
copy lets SQLite roll back that transaction: both states and all decision rows
exactly match the pre-decision logical snapshot, and no forced spill-table
updates survive. No journal is manually unlinked.

The retry then commits exactly one slot, six final net fills and 36 slot funding
rows. A subsequent reopen and same-slot tick changes none of the compared
states, fills, funding, slots or observations. All original historical prefix
rows in inputs, slots, fills, funding and observations retain their exact
content hashes. Final held quantities reconcile to the parent plus all actual
copied and newly simulated work-copy fills. Full work-copy integrity is `ok`;
all sealed input hashes remain unchanged.

This complete-copy fixture already has a 1.0332% ordinary post-cost risk gap,
so it correctly remains `MATCHED_UNCHANGED`. A separate complete-slot control
forces a known coarse-grid mismatch: the ordinary gap exceeds 2%, repair cuts
HALF's proposed BTC quantity from 15 to 14 units, and only its final net BUY of
four units is committed. The discarded five-unit trial is neither charged nor
recorded. The resulting risk gap is within the original tolerance.

## Failure found and corrected in the inactive adapter

The first candidate constructor inspected identity through a mode=ro SQLite
connection. A real hot journal requires a physical rollback even for the first
SELECT, so the forced-page-write crash test failed with `attempt to write a
readonly database`. The adapter now permits SQLite recovery on the already
validated **offline work copy**, while identity queries remain query-only.
Sealed inputs remain read-only. The active legacy runner was not changed.

## Tests and retained boundaries

**45 focused tests pass**: 17 complete integration tests, 16 pure-candidate tests
and 12 existing fork-runner tests. Controls cover:

- Full inheritance, separate epoch, changed-identity/missing-copy refusal.
- Held settlement quantity and prior mark, exact cursors, debt without a cursor
  advance, debt recovery charged once and no duplicate funding on restart.
- Final corrected quantity, net fee accounting, generations, position identity,
  order counts and persisted one-arm entry veto.
- Paired market vetoes through the complete pipeline; missing inputs deny
  decision fills while independently valid funding remains accounted.
- HALF update failure, funding insert failure, abrupt process exit with a hot
  journal, rollback, successful retry and restart idempotency.
- Expired slots and a calculation crossing its execution deadline remain
  neutral; no late simulated fill is backdated.

The prior pure-candidate suite retains all funding, depth, off-grid, covariance,
indivisibility, risk-veto, fee/slippage and bounded-search controls. The earlier
13-slot engineering result is unchanged: the candidate matches 13/13 isolated
consumed contexts, while **actual ongoing FAST/HALF history remains 7/13**.
Neither this integration test nor those 13 contexts establish profitability or
satisfy the prospective minimum of 80 paired slots.

All 12 live lab containers remain healthy with identical IDs, start times and
automatic restart counts. The selected profile is still `local_ai_trading`,
real trader disabled, simulator enabled, `deterministic_alignment` selected.
No new dependency, image/model download or parallel research account was used.

## Delivery and remaining effect

The new code is `octobot/ai_strategy_lab/v13_fork_discrete_offline.py`, supported
by `scripts/qualify_fork_discrete_integration.py`, the versioned offline contract
and focused tests. The companion JSON records source/code identities and
sanitized qualification results. Raw copied journals, mechanical fixtures and
fault evidence stay in private audit storage outside Git.

The technical preparation requested here is complete. The harness has no
service entrypoint and is not deployed. A later operational handoff still needs
the final caller/configuration qualified against the real fresh daily bundle,
a coherent current-state handoff, and an explicitly authorized future version
boundary on the existing pair. Preserve the old observations and fixed horizon;
do not reinterpret the current mismatch alert as repaired. The concrete handoff
checks are in `docs/FAST_HALF_DISCRETE_INTEGRATION_RUNBOOK_V1.md`.
