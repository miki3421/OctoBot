# FAST/HALF discrete repair: offline integration and future handoff

This delivery qualifies copied-ledger mechanics only. `v13_fork_discrete_offline`
has no service entrypoint and refuses a configuration without the explicit
offline work-copy scope. Do not deploy the harness or turn its synthetic inputs
into observations of a running strategy.

## Repeat the offline qualification

Use the existing pinned OctoBot image, no network or image pull, read-only source
and input mounts, and a separate writable output mount. Bound execution to one
CPU and 1 GiB RAM. Inputs must be coherent sealed copies of the current paired
ledger, Original reference ledger, unchanged common parent and observed market
record, with the `SEALED_OFFLINE_COPIES` SHA-256 manifest.

Run:

```bash
python scripts/qualify_fork_discrete_integration.py \
  --evidence /input \
  --work /output/fresh-work \
  --output /output/qualification.json
```

The work directory must not already exist. Keep the original evidence mounted
read-only. The script constructs explicitly labelled future mechanical marks,
funding points and cached daily inputs on work copies, interrupts a decision,
recovers the hot journal and checks idempotent restart. Those generated inputs
cannot qualify an actual future scientific day or support a profitability claim.
Only the clock is controlled; funding, planning, risk, storage, book selection,
passive recovery and cached-input loading use the real implementations.

Run the three focused unittest suites for `test_v13_fork_discrete_offline.py`,
`test_v13_discrete_risk_candidate.py` and `test_v13_fork_runner.py`. Preserve
failed controls as diagnostics; do not suppress failures or relax thresholds.

## What is qualified

- Exact initial full-state/receipt inheritance and unchanged historical rows.
- Ordinary planning followed by discrete post-cost repair from the same funded
  pre-slot state; only the final net orders incur fees and become fills.
- Preserved 2% daily-loss, 10% drawdown, one daily increase, 22-hour cooldown,
  31.5% asset and 90% gross limits, plus paired market/entry vetoes.
- Held-quantity funding, prior causal reference marks, non-advancing debt
  cursors, settlement deduplication and subsequent debt recovery.
- One atomic slot transaction for both states, fills, funding and filters;
  rollback after a HALF write failure, a funding insert failure, or an abrupt
  process exit after real SQLite page writes.
- Reopening with retained counters and position generations, without repeated
  fills or funding, and neutral handling of expired/missing decisions.

Cached daily input and valid passive observations may be saved before the
decision transaction, as in the pinned legacy runner. The guarantee concerns
the decision transaction, not removal of valid preceding observations.

## Separate future activation work

No service, collector, account, UI, threshold or existing protocol is changed
here. The ongoing actual FAST/HALF history remains 7/13 within tolerance at the
26 October checkpoint, regardless of offline qualification results.

A later authorized handoff must pin the final operational caller and exact
configuration, declare a real future version boundary on the existing paired
accounts, and qualify that caller against the actual freshly published daily
bundle, full funding history and current coherent states. Preserve all legacy
receipts and rows, counters, capital and fixed horizon. Label the version split
in projections/monitoring so original results are not silently reclassified.

Do not reuse a synthetic cached input, reset the accounts, open another parallel
pair, retrofit the 13 historical slots, widen the 2% matching tolerance or clear
the actual mismatch alert merely because this offline harness passes.

Before such a handoff, prepare a coherent backup and explicit recovery procedure.
After any eventual authorized service change, verify actual container/process
health, paper-only profile, fresh projections, exact source identities and
retained historical outcomes. None of those future effects is authorized by
this runbook itself.
