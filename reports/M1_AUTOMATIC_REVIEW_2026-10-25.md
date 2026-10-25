# M1 delegated automatic reviews — 25 October 2026

The operator requested automatic weighted approvals instead of approving each
proposal in the browser. This continues the existing M1 successor account; it
does not create another strategy comparison or alter Original, FAST, HALF,
the intraday pair, the M1 research observation or any collector.

## Decision contract

- The explicit operator delegation is root-owned, read-only and SHA-256 pinned.
  It binds the account, successor genesis, rules, exact per-symbol SHORT caps
  and the LONG budget remaining after the first six reductions.
- The runner has no approval password, no writable broker database and no
  network. Browser authentication is not bypassed. A delegated automatic review
  is recorded as such, never as an authenticated manual operator decision.
- Data quality contributes 25 points, signal 30, liquidity 20, costs 15 and
  budget 10. Approval requires at least 80/100 **and every mandatory check**.
  The score measures compliance with the rules; it is not a calibrated chance
  of profit or evidence of a profitable strategy.
- A new LONG needs positive existing 30/120-day momentum on two consecutive
  closed daily observations, signal score at least 0.25, qualified observed
  book/funding, spread at most 0.10%, and estimated round-trip costs at most
  0.20%, including the existing 2 bp adverse slippage per leg and fees.
- At most two genuinely new symbols can be admitted in one weekly selection.
  Each receives at most 1% of equity, only within unused capacity in the fixed
  12.63964573% LONG budget. No cash redistribution or expansion of the exact
  25.54583334% SHORT budget occurs. The existing per-symbol limits remain.
- Legacy excluded/reduced assets and previously admitted assets cannot receive
  an automatic repurchase permission. Each admission has a single-use quantity
  allowance, expires after 48 hours and opens only at the ordinary daily slot.
  The signal, current budget and existing Risk Guard are checked again before
  execution on a later book. A rejected/partial entry does not become an
  unbounded retry or restoration of quantity.
- Existing six LONGs retain the agreed 50% / 25% / 0% remaining-quantity stages,
  at least 24 hours after actual completion and a fresh deteriorated daily
  observation. New admitted LONGs use the same gradual exit discipline after
  deterioration. Recovery holds the remaining ceiling without repurchasing.
- The M1 detector, six-hour SHORT holding/cooldown, ordinary 22-hour spacing,
  daily loss/drawdown and risk-batch limits remain unchanged.
- A valid causal daily review renews permission for new risk for seven days.
  Missing, altered or future input does not renew it or create an extra exit.
  Protective execution retains its existing validation. No research strategy
  or real trading permission is automatically promoted.

The first selection can run after activation. Later selections use the existing
Monday 00:15 UTC week boundary; qualified entries execute at an ordinary
00:15 UTC slot. A data or capacity failure may defer a selection. Released
capacity is reconsidered after actual position changes, within the same weekly
admission limit; a rejected snapshot never forces an entry.

## Audit and daily review

Append-only SQLite records contain the delegation ID, inputs, reasons, weighted
components, prior decision ID and approved policy snapshot. UPDATE/DELETE are
rejected by database triggers. Quantity ceilings may subsequently decrease;
they cannot exceed the approved snapshot. The existing intent and fill records
retain their policy/decision references.

The M1 review page shows automatic approvals, deferrals and rejections with
reasons, admitted-symbol status, gradual reduction progress and recent audit
records. A daily accounting summary shows fills, fees and realized P/L less
those fills' fees. It explicitly excludes open P/L, funding and earlier costs;
it is not the strategy's daily total return. Existing equity/funding views stay
the source for total performance. No new notification job is introduced.

KuCoin real minimum quantities/notional remain unknown where recorded as such.
This is the existing synthetic paper contract with separately declared
simulation minimums, not a claim of live exchange executability.

## Validation and delivery

Execution mode: SINGLE_AGENT; author implementation and verification, without
claiming independent QA. Tests use the existing installed images, no downloads.

- Targeted unit/contract suite, real-runner full-ledger control fixture and
  desktop/mobile GET-only browser journey are retained outside Git.
- The full-copy fixture preserves all 319 existing order rows, restarts the
  automatic runner, approves and actually buys a new controlled candidate,
  consumes its allowance once, exercises its three exit stages, rejects audit
  mutation and verifies no repurchase after closure. Synthetic future bars and
  the qualified-book control exercise mechanics, not historical profitability.
- Fresh cold backup, exact runtime/delegation manifests, scoped M1/UI restart,
  live readback and unchanged-service checks are required before delivery.

Prepared immutable release: `v13-m1-auto-v6`, manifest
`8f0b1c346d3117503975bed56c8233aa1e0840ac1c0419210d17d43ecf77d8df`.
Operational activation completed at 12:23:12 UTC (13:23:12 CET). The existing
account now reports `delegated_automatic_review`; its first causal renewal is
recorded and no new candidate was admitted because current LONG exposure uses
the fixed capacity. No new fills were forced at activation. Capacity is
reconsidered after actual reductions, within the unchanged weekly entry bound.

All 319 previous order rows compare exactly with the cold backup; SQLite
integrity is `ok`. SHORT caps are unchanged and `orders_authorized` is false.
The 70 targeted tests, full-copy control fixture (including new-symbol entry,
restart and actual three-stage exit) and both fixture/live desktop/mobile
browser journeys passed. Browser journeys performed no approval POSTs.

All 12 running lab containers are healthy. The passive monitor's 12:24:15 UTC
sample reports M1 healthy, no account issues and no alerts. Other container IDs,
start times and restart counts are unchanged; only M1 and the dashboard were
restarted. The previous M1 runtime is retained stopped with restart disabled;
no historical ledger restoration or deletion was performed. Code is delivered
on the existing project branch; operator acceptance remains a separate step.
