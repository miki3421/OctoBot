# Storage attribution and Qwen retirement — 26 October 2026

The operator approved the next storage step and then explicitly requested
disabling the unused Qwen MoE model. This continuation preserves both required
OPS VMs, all paper strategies, original datasets and account history. Execution
is single-agent, with author verification and no new software downloads.

## Qwen disabled

`llama-moe.service` was idle before shutdown. Its cgroup accounted for about
13.1 GiB of RAM and 14.9 GiB of swap. The host had only about 0.13 GiB of swap
available. The model and `qwen-v13-analysis.timer` are now stopped and disabled
at host boot; the descriptive oneshot is inactive. No VM, collector, strategy or
paper account was stopped. The model files and the exact last report bytes are
retained. The existing BTC Qwen shadow remains suspended.

After shutdown, swap available increased to about 15.2 GiB. Remaining swap use
is principally associated with the two running VM processes; no global swapoff,
VM shutdown or guest configuration change was performed.

A root-owned descriptive stop record makes the public report state `disabled`,
with no future scheduled time. Even an accidental manual worker invocation
skips data/model requests and preserves historical report bytes. Malformed or
untrusted stop metadata fails closed. The UI explains that Qwen is disabled,
while quantitative per-symbol metrics remain available independently.

Forty-eight Qwen analysis tests pass, including disabled-state/cache preservation
and refusal to infer through an untrusted marker. The final immutable descriptive
runtime is `qwen-v13-analysis-v7`, source SHA-256
`261e0faef43e83931f8cf936006001b4af69ffff4adbe625c620674d34483df1`.
Only scoped patches to the pre-existing untracked worker/template are delivered;
unrelated local changes remain untouched. UI activation/readback is pending.

## Physical growth attribution

The larger filesystem is shared by lab data, Docker/containerd and VM images.
The earlier 15.79 GiB/day measurement was filesystem growth, not proof that
collectors alone generated that volume. A new bounded read-only probe records
physical allocated blocks, inode identity, filesystem free space, VM image
allocation and process write traffic separately. It collects no process
arguments, environment variables or guest data.

Over 305.5 seconds, filesystem growth was 48,324,608 bytes (46.09 MiB):

| Sampled source | Physical growth |
| --- | ---: |
| Active lab SQLite files and companions | 23.75 MiB |
| VM image files | 15.81 MiB |
| Lab container logs | 0.08 MiB |
| Untracked/transient residual | 6.45 MiB |

The probe retains the residual instead of assigning it to collectors. VM write
traffic was much larger than retained image growth: rewriting existing blocks
is not equivalent to consuming new disk space. This five-minute observation
cannot explain earlier allocation bursts or serve as a ninety-day forecast.

## Cold recovery verified

The existing compressed retired-account package was fully restored into a fresh
private directory on the root filesystem, leaving larger-disk originals intact.
All eleven files, 9,642,000,969 bytes, passed hash and metadata comparison. All
three restored SQLite databases (`account.sqlite`, `stress.sqlite`, and the
availability journal) passed full read-only `PRAGMA integrity_check`.
Post-check file hashes and metadata were unchanged. The recovery copy is retained
for inspection; it is not an active account or a new dataset in the live lab.
The complete restore and integrity verification took 43.2 seconds.

Two synthetic recovery tests also pass: real SQLite recovery preserves its
source and refuses an existing destination; traversal and archive symlinks are
refused. The recovery helper never deletes or changes originals.

## Archive preparation and remaining boundary

Four closed audit packages are being packaged losslessly with exact per-file
manifests. Generation rechecks original metadata, refuses open files and
symlinks, verifies every archived byte and metadata, and enforces at least 17%
free space. Existing hard links are accounted for when estimating recoverable
space. Every original path is retained during preparation.

Archive completion, final capacity and the concrete migration decision are
pending the final readback. No active journal, dataset, log or volume has been
removed. Replacing uncompressed cold copies with their verified archives is a
separate material step under the project's no-journal-deletion rule.
