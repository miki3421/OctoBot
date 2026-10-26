# Daily-check remediations — 26 October 2026

Scope: the operator authorized the M1 input correction, storage-growth work,
FAST/HALF risk qualification and Qwen descriptive-report investigation. Work is
single-agent, with author verification, preserving active signals, thresholds,
account history and the Original strategy. No sealed research outcome is used.

## M1 input scope

The managed six-symbol execution universe was incorrectly passed to validation
of the original frozen eighteen-symbol daily scientific bundle. It rejected
genuine input with `daily_identity`. The corrected runner verifies all eighteen
scientific symbols, then projects targets onto the separately authorized
execution universe. It does not skip receipts or grant new asset weights.

The immutable continuation is active after a restart of only the M1 runner.
The live baseline is now 25 October, with no input error. The complete 319-order
account copy passed the real published derivation and restart checks; 75 targeted
tests passed. Equity, quantities, history, SHORT capacity, no-rebuy rules and the
automatic delegation were preserved. The denied 26 October daily slot remains
visible; no retroactive daily execution was performed. See
`M1_SCIENTIFIC_SCOPE_FIX_2026-10-26.md`.

## FAST/HALF execution risk

The offline diagnostic reconstructs all thirteen executed slots from the common
seed, exact archived books, causal price covariance, funding, permission
outcomes and actual fills. Reconstructed continuous weights, rounded quantities
and recorded allocation volatility agree for every slot (zero reconstruction
error at the retained numerical precision).

Only seven of thirteen slots (53.85%) meet the frozen relative risk-gap tolerance
of 2%; the protocol requires 95%. At the 26 October slot, continuous common
volatility is 0.03836037. Realized allocation estimates after discrete fills and
costs are 0.03582402 for FAST and 0.03734204 for HALF: a 4.0652% relative gap.
No risk rejection or skipped leg explains that latest slot. Earlier suspended
new-risk legs are retained in the reconstruction, rather than assumed executed.

This is a genuine execution-rounding/cost limitation of the continuous matching
method. The comparison is not qualified as an equal-risk scientific test.
The UI adds a notice based on the recorded latest slot. Active allocations and
the 2% threshold remain frozen. A concrete future correction would check risk
on the rounded, post-cost portfolio before committing a plan and iteratively
reduce the higher-risk side; that changes allocation rules and requires a
separate decision, not a relabelling of current results.

Reproducible diagnostic: `scripts/qualify_fork_discrete_risk.py`; private evidence:
the daily coherent fork snapshot and `fork-discrete-risk.json`.

## Qwen descriptive report

A bounded actual local inference reproduced the rejection. The validator treated
the phrase “copertura completa non è garantita” as a positive guarantee because
it banned the word stem globally. The reply cited measured incomplete windows;
this rejection was a false positive, not a model timeout.

The correction permits only the exact negated coverage clause, with a cited
measured incomplete window. Positive guarantees, invented numbers, unknown
symbols and trading instructions still fail closed. It does not alter model
output or trading authority. The existing 41-test suite passed; two standalone
regressions additionally exercise the precise exception and unsafe alternatives.

The deployed worker uses the immutable `qwen-v13-analysis-v4` runtime. The
baseline source SHA-256 is
`c67f41bf12f1e3973d5da9457c04ad3208b7b46cca42a4faff83d6188247f3fd`;
the corrected source is
`a4bef22c7026efeb5cc0a9a3029724e15f5e8ee6b5c90fb37f8c596878d66ca2`.
`patches/qwen-v13-coverage-negation-20261026.patch` records only this change
against the installed baseline, isolating the pre-existing untracked legacy
module and test file. Existing worker confinement, timer, model and local
endpoint are retained. The suspended BTC Qwen shadow remains suspended.

A fresh actual inference completed successfully at 09:41:29 UTC (10:41:29 CET),
in 66.694 seconds, with status `ready`. No previous rejected record was erased.
Dashboard readback is part of the final delivery check.

## Storage

The daily telemetry measured 15.79 GiB of net growth in 24 hours. Root has about
88.6 GiB available; the larger lab filesystem had about 143.5 GiB at the daily
check. At that growth rate its 15%-free warning, not disk exhaustion, was about
33 hours away. Live intraday ledgers and retained audit copies are major users.

The approved bounded operation coalesces fourteen pairs of byte-identical,
closed SQLite audit copies. It preserves all 28 named regular-file paths and
every byte; no journal, log, dataset, volume or live directory is removed.
Full SHA-256 equality, unchanged metadata, owner/group compatibility, filesystem
boundary and absence of open descriptors are checked before each pair. Shared
copies become read-only. Future recovery must first make an independent private
copy; source per-path timestamps and modes remain in the retained plan.

The exact plan SHA-256 is
`d32cded821ce031ff36b9d9f204c8c9e53ffe9046bfd5b7003cdaaa9bd639953`.
Three filesystem invariant tests passed. All fourteen pairs were coalesced and
read back successfully: 30.740 GiB of duplicate physical storage was released.
The measured net available-space increase was 30.717 GiB while collectors
continued writing. The larger filesystem now has 173.325 GiB available (21.39%).
Root is unchanged at about 88.6 GiB free. No Docker prune or VM change is involved. Deduplication frees headroom but does not remove ongoing ingestion
growth. The next storage action is a measured cold-archive compression/retention
proposal, keeping causal receipts and account history recoverable.

## Delivery and residual checks

Final browser, resource monitor, runtime and storage readbacks are recorded in
the private `lab-fixes-20261026` audit package. Project cards remain separate from
operator acceptance. Legitimate historical missed-slot and unequal-risk alerts
are not suppressed merely to produce a green dashboard.
