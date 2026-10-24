# BTC intraday: technical latency continuation

Prepared and explicitly authorized/deployed on 24 October 2026 for the existing
SHORT control and LONG + SHORT pair. See the dated report for live evidence.
This is a technical correction, not a new strategy or a new account. Production
deployment and operator acceptance remain separate from local qualification.
Technical verification passed; the delivery remains in Test for operator acceptance.

## Fixed scope

- Persist the existing shared public Level 5 stream every 100 ms instead of
  every second. Subscription, polling source, rows, timestamps, hashes and
  one-second aggregates are unchanged. There is no additional public acquisition.
- Use an external `FastValuationPair` subclass for the existing five-minute
  valuation. Its method differs from the frozen method only by the SQLite
  `NOT INDEXED` query-plan hint. Cutoffs, commit acknowledgments, ordering,
  funding predicates and output are identical.
- Reserve 2 GiB instead of 512 MiB for the pair's full-history startup audit.
  The CPU quota remains 0.75. Startup health grace is ten minutes; trading
  freshness, execution deadlines and risk limits are not extended.

The original `intraday_pair/` package, activation receipt, I/O continuation and
old runtime remain byte-identical. The new wrapper checks both existing layers
of authority, then a separate exact technical continuation. Initialization and
changes to sources or account paths are forbidden. There is no network in the
pair runner, no credential, real order, reset, fabricated quote or late fill.

## Prepared immutable artifact

Manifest SHA-256:
`e08c51daef896bbaeb16d3b34eb6c52b57b1d07852eeba442ecd55060466199a`.

The release is `octobot-local/btc-intraday-pair-latency-v1/`; the runtime is
separate from the old version. The first staging candidate, superseded after
memory qualification, is preserved with a `before-memory-qualification` suffix.
It was never deployed.

The preparation script never stops or starts a service. The activation script
defaults to verification only and requires the exact manifest plus an explicit
manual operator reference for mutation. New receipt files are written only by
that manual deployment path. Preparation is not production consent.

## Manual deployment batch

Only `octobot-btc-intraday-pair` and `octobot-scalping-observer` are restarted.
The collector is shared with the older intraday account: its collection has a
brief interruption and subsequent availability improves; the older account's
code, state, signals and thresholds are not edited or restarted. All other
containers, the dashboard, monitoring and notification services stay running.

1. Recheck exact runtime, Compose, helper, configuration and image pins, free
   storage and the absence of existing continuation files.
2. Wait until all four paired scenarios are flat without pending intents.
   Never force a position closed for maintenance.
3. Stop the pair before the collector. Preserve the stopped containers, their
   logs and the complete cold state tree. Compare stopped account identities
   and history anchors; do not restore, truncate or edit the trading ledgers.
4. Publish only the exact prepared technical configuration and separately
   authenticated continuation. Start the collector and pair from pinned local
   images, without building or downloading anything.
5. Allow the ordinary full-history startup verification to complete. Verify
   healthy containers, common input cursors and hash, new raw book writes,
   preserved identities/history anchors and the live UI.
6. Recover interrupted transactions only on another private copy of the cold
   backup, then run read-only integrity checks there. Heavy scans are never run
   against the live collector or accounts.

The account audit may take several minutes. A gap in the 289 consecutive
five-minute points can require about 24 hours of new contiguous data before
entry is possible again. Missing slots remain visible; no historic opportunity
is reclaimed. A maintenance window is not evidence of strategy performance.

Verification-only command, from the canonical repository root:

```bash
python3 -B scripts/activate_intraday_pair_latency.py \
  --manifest-sha256 e08c51daef896bbaeb16d3b34eb6c52b57b1d07852eeba442ecd55060466199a
```

The corresponding manual command additionally requires
`--manual-operator-deploy --operator-reference` with the actual operator's
technical authorization. Do not infer that authorization from a successful
verification or use a fabricated reference.

## Failure and rollback

After a partial stop or failure, inspect the state and saved receipt before
continuing; there is no blind retry. Old containers and runtime remain stopped
and available for rollback. Stop only the new pair and collector, preserve them
and their logs, and restore the previous names/configurations. Reuse the current
ledgers; never restore an older database over newly recorded history. Both
implementations use the same frozen engine and schema. Reverting the collector
also restores the old one-second persistence behavior and its known limitation.

The previous M1 v2 technical authorization remains separate. Its one-shot
continuation is rearmed with the final project checkpoint and the unchanged
NORMAL/no-pending gate; this package cannot approve an M1 rebalance.
