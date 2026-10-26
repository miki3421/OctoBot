# Existing FAST/HALF v3 activation — 26 October 2026

The prequalified discrete-risk caller is loaded on the **same two existing
FAST/HALF accounts**, with correction beginning at **27 October 00:15 UTC /
01:15 CET**. Installed at 16:58:08 UTC / 17:58:08 CET on 26 October. Before the
boundary, the caller retains the legacy planner. There is no new account,
capital reset, retrospective fill or change to Original, M1, intraday accounts
or collectors. Work was SINGLE_AGENT with author verification, not independent QA.

## Exact released candidate

- Candidate commit: `9376115ac0b778289ec37fd9875d475e4b9f15de`.
- Runtime manifest SHA-256:
  `dd813acbadc246dc9e2c53f255733c9971758a8b0af42f152307e843c23e95ea`.
- Root-owned stopped-state grant SHA-256:
  `3cf131249f735af7a248ea03ebde769965b51a3b54bcd2443386eb7c6cc8da58`.
- Final configuration SHA-256:
  `0f1462f19760b2b836dc5ae9f6ae0ed9b702215d7b5b792659a62099f6dee1d7`.
- Existing pinned image, UID 30934/GID 30910, network disabled, read-only root,
  memory/CPU limits and all existing data mounts retained. Runtime code is
  immutable under `/opt/trading-lab-forks-discrete-v3`.

The initial packaging candidate was explicitly rejected by the real scientific
source derivation because three frozen provenance files were missing. The
final manifest includes those unchanged files and was requalified, not silently
rebuilt during activation. Its immutable caller reproduced the actual published
18-symbol input exactly as UID 30934, without mocking derivation or networking.

## Stopped handoff and retained state

Only `octobot-v13-forks` was stopped and recreated. The installed legacy Compose
has the known missing-image-ContainerConfig incompatibility when directly
recreating a previous container; the batch therefore removed only the stopped
target container, without removing volumes, before creating its replacement.
The existing compose project remains `v13-forks` and the existing paired SQLite
file stays in its original data directory. The old compose/configuration are
retained for recovery.

SQLite was allowed to perform normal journal recovery if needed. A stopped,
coherent backup and complete row-prefix hashes were captured before installing
the new epoch. Integrity passed. No journal was manually deleted and no backup
was restored over live history.

A bounded post-start read-only backup passed full `PRAGMA integrity_check`.
Every old row in slots, fills, funding, observations and cached daily inputs
retains its exact content hash. Legacy identity and receipt are unchanged. The
new epoch's inherited-state digest exactly matches the complete stopped states.
Risk daily start, daily entries, last increase, position quantities, generations
and order counts are preserved; high-water state is not reset. Held quantities
reconcile to inherited quantities plus recorded fills. The future correction
has not generated an early trade.

All **12 live laboratory containers are healthy**, with zero automatic restart
counts. The other eleven containers retain their IDs, images and exact start
times. The selected profile remains `local_ai_trading`: real trader disabled,
simulator enabled and `deterministic_alignment` selected. No real-order authority,
exchange credential, image pull, package installation or new parallel account
was introduced.

## UI and passive monitoring

The comparison and FAST/HALF detail pages now show the revision date and separate
risk-matching counts: **legacy 7/13**, **v3 0/0**. Real USDT equity curves, inherited
history, M1 lifecycle information and the other accounts are preserved. A version
marker appears when its boundary falls inside the selected equity-chart window.
Unknown risk is displayed as unverifiable, not zero. A valid observed no-fill
slot can supersede an older mismatch in the display.

The exact previewed static asset was published without restarting the dashboard.
Live GET-only browser checks passed comparison, FAST, HALF, Original and M1,
24h/7d/all-history controls and mobile layout, with no JavaScript errors.

Passive monitor **v6** preserves the v5 configuration, retirement checks,
notification intervals and existing SMTP notifier. It additionally validates
revision/account/calendar identity and separate denominators. A future slot
cannot claim v3 after running the old planner; unknown or partial risk remains
an alert even with a numerically small gap. The actual current alert remains
`FORK_RISK_MISMATCH`, because the last natural daily slot is still the legacy
26 October slot with a 4.0652% gap. It was not cleared by a test or new label.
The separate historical M1 denied-slot alert is also retained.

## Qualification and next natural check

**79 targeted tests passed**: 57 runtime/candidate/legacy tests plus 22 passive
monitor and dated-check tests. Copied-ledger qualification also passed full
inheritance, exact funding, paired vetoes, final net-order accounting, deliberate
HALF/funding write failures, forced process exit with a hot SQLite journal,
rollback, retry and restart idempotency. Synthetic mechanical tests are clearly
separate from the actual-source derivation; they do not certify future market
inputs or profitability.

The one-date read-only checker is enabled for **27 October 00:25 UTC / 01:25
CET**. Its actual confined preflight returned `WAITING_FOR_NATURAL_SLOT` with
no issues. It checks the real first v3 slot after its execution deadline,
including account/version binding, fresh publication, funding coverage and the
2% matching tolerance. Actual fills and a legitimate no-fill are distinct
completed outcomes. Missing, denied or unqualified results require review.
It cannot trade, mutate SQLite, access the network or send mail. The existing
M1 checker remains enabled for the same time and was not modified.

The first natural v3 result is **not yet qualified** at this delivery. The
fixed horizon remains 11 January 2027. Fewer than 80 corrected future daily
slots remain, so this segment cannot independently earn the frozen 80-slot
scientific qualification; results remain descriptive and cannot be pooled with
legacy slots to erase old mismatches or justify promotion.

Recovery before the boundary uses the retained base compose/configuration on
the same ledger, preserving new observations and the epoch record. After any
corrected economic fills, reverting allocation semantics requires another
explicit future version decision. Never rewind the database to erase results.
The scoped procedure is `docs/deployment/FAST_HALF_DISCRETE_V3_RELEASE_PLAN.md`.
Raw backups, grants, prefix hashes and runtime/browser evidence stay in private
audit storage outside Git; the companion JSON contains sanitized verification.
