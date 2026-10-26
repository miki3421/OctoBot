# M1 scientific/execution scope correction — 26 October 2026

The managed M1 continuation previously supplied its reduced execution universe
to the frozen original scientific derivation. With six held/budgeted symbols,
the genuine 18-symbol daily bundle failed with `daily_identity`. Today's
ordinary slot was denied and new-risk execution remained suspended.

The correction verifies the complete frozen signal universe through a shallow
runner view sharing the established input cache. It does not mutate execution
membership, skip other symbols' receipts, change the original model, or grant
weights to a newly admitted asset outside its separate policy. Cached scientific
prices and targets must still cover the complete scientific universe.

Signals, thresholds, risk rules, automatic-review delegation, SHORT capacity,
quantity ceilings, equity, positions and all ledger history are preserved.
Today's denied slot is retained; there is no retroactive fill or daily retry.
Only the M1 runner needs a scoped restart; collectors, dashboard, broker and
other strategies do not need restarting.

Verification:

- 75 targeted tests passed, including five new scope regressions: reduced
  execution membership, newly admitted execution symbol, tampered excluded
  receipt, future scientific snapshot and incomplete cached scientific scope.
- A complete copy of the current 319-order M1 ledger passed the real published
  daily derivation, without mocking the baseline or source derivation. The full
  18-symbol science was verified and targets projected onto six execution
  symbols. Funding/accounting remained real; only detector-window input was
  isolated to avoid inventing a control-fixture M1 episode.
- Positions, SHORT budget, quantity ceilings, denied-slot evidence and existing
  orders remained intact. The corrected runner restarted idempotently and the
  copied SQLite ledger passed integrity checking.

Prepared release: `v13-m1-scope-fix-v1`, manifest
`25d15fdda2a0b3ac183f0120c0c4e66d339883dd8361ce3008d91e6e6b68794e`.
The predecessor's exact delegation and genesis authority bytes are carried
forward; a new root-owned runtime-upgrade record binds a fresh cold backup.
Operational activation/readback is pending at preparation time.
