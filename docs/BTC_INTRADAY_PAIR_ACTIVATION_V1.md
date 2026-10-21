# BTC intraday paired paper activation v1

Cards: work-card-8fd80afc-9599-40ca-abf9-68d2d2d082a9 (activation), work-card-f96c38d0-c015-4ecc-880f-769ccc48f055 (UI), work-card-0ad819dc-076f-4cba-888a-4266e41f9d93 (monitor), work-card-79f8f65b-8eb4-4659-a7b6-990b89002850 (checks), work-card-aef0dcc2-df33-4f8f-ba4f-99d0acee29ae (delivery).

The operator authorized activation of the two new paired synthetic accounts, their UI and monitoring on 21 October 2026. This is technical paper activation, not scientific acceptance, real trading authority or KuCoin order admissibility. Existing accounts and qualified research evidence are preserved.

## Frozen strategy and additional deployment surface

The package `octobot/ai_strategy_lab/intraday_pair/` remains byte-for-byte identical to qualified bundle `92a5b4d1c23e2373ce7ce3e858e01c8646a3c3797d7021e4bdd409da3f38dc31`. The protocol SHA remains `06c8fa9aa85ecb5ea9fae49fd1b9cbe81178f14b85a033bb2b3dda4e8413caeb`. The historical approval template remains inert. No entry, exit, size, cost, risk or source verification gate changes.

The separate `btc_intraday_pair_live.py` wrapper verifies its own SHA in addition to the qualified package pins, delegates all trading to that package, and publishes bounded observations from its own ledgers. Initialization is a distinct one-time command and cannot occur on service restart. Missing state fails closed. The wrapper calls the existing common-grid observation at most once per slot; it does not create missed observations or backdated entries. The new deployment manifest records all added runtime and UI code.

A root-owned receipt pins the exact qualified code and wrapper, new destination, account IDs and future common UTC midnight T0; T1 is T0 plus 90 days. Four new ledgers start flat at 10,000 virtual USDT: control/candidate, primary/stress. The previous intraday account is not the paired control. No historical PnL is inherited. Prospective 289-point warm-up can finish after T0, in which case opportunities before completion remain unavailable.

## Isolation and UI

`docker-compose.btc-intraday-pair.yml` starts only the new service, using an already installed immutable image, UID 30943, no network, no credentials, read-only root and inputs, new private state and public projection only. It never mounts old ledgers or approval stores. Root control is close-only and has no web endpoint.

`/btc_intraday_pair` and its GET data route use the existing login, accepted-terms and local-profile boundary. The reader rejects wrong identity, writable/unowned files, symlinks, duplicates, nonfinite accounting and future timestamps. It reads a public JSON projection, never any ledger. Side/effect, funding incompleteness, initial collection, UTC dates, actual virtual equity and independent stress are explicit. At most 5,000 recent 30-second equity points and 100 trades per arm are published. Missing observations interrupt the chart. This is a descriptive view, not early scientific evaluation. The sidebar links to the page.

## Monitor and release

Monitor v4 preserves all v3 checks and config values, adding only the new container and projection. It validates read-completion time, exact identities, common input cursor/hash, accounting and integrity, heartbeat and source freshness. Prestart/warm-up alone never alert. Existing PAPER_ACCOUNT alert IDs allow the unchanged mail notifier to explain faults with its existing cooldown/reminder state. No SMTP test mail, reset or credential change is required.

Install v4 as a separate immutable directory, update only the monitor unit WorkingDirectory, preserve the v3 directory and telemetry/notifier state, then read back a manual and a natural timer cycle. UI Python routes require a narrow restart of the shared web container; separate old collectors and executors must not restart. Existing runtime/config hashes and container start/restart metadata are retained before and after.

The repository has unrelated dirty and untracked historical features. The release stages only its bounded new files, monitor delta, new home routes/import and the sidebar partial needed for navigation. It does not claim a clean-main reproducible build or independent QA. Author checks and live readback are distinct from final operator acceptance.

## Reversal

Stop only compose project `btc-intraday-pair` service `btc-intraday-pair` if this release fails. Preserve every new ledger, receipt, projection and log. Restore the saved v3 monitor unit, daemon-reload and start only the passive monitor. Remove the new UI route/link using the recorded preimage, retaining all unrelated local edits, and reload only the web service if required. Never prune images/volumes, delete databases, reset seed or replay missed signals. Forward observation is not valid merely because the service is healthy; storage growth and causal data coverage remain monitored throughout.
