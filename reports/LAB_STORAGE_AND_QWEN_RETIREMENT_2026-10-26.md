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
unrelated local changes remain untouched. UI activation is complete. The GET-only
browser journey passed: disabled badge/title visible, no next scheduled report,
quantitative symbol metrics still available, no JavaScript errors or write
requests. All twelve lab containers remain healthy with zero automatic restarts;
only the dashboard was restarted for publication. M1 still reports no baseline
error. The model port is no longer served. The immutable patch reproduces the
worker from its pinned predecessor; the worker patch uses zero context and can
be applied with `git apply --unidiff-zero`.

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

Four closed audit packages have been packaged losslessly with exact per-file
manifests. Generation rechecks original metadata, refuses open files and
symlinks, verifies every archived byte and metadata, and enforces at least 17%
free space. Existing hard links are accounted for when estimating recoverable
space. Every original path is retained during preparation.

All four packages passed complete streaming hash and file-metadata verification.
Preparation took 437 seconds. The 350 files contain 88.66 GiB of logical data;
existing hard links reduce current physical original allocation to 57.92 GiB.
The four compressed archives total 12.80 GiB. Replacing the cold originals would
therefore provide a net 45.12 GiB benefit compared with the pre-preparation
state; from the present state it would release the 57.92 GiB occupied by the
originals. No active Docker container mounts one of the four cold packages.

| Cold audit package | Files | Compressed size |
| --- | ---: | ---: |
| Old source IO, 23 October | 91 | 1.86 GiB |
| Legacy account retirement, 24 October | 46 | 2.33 GiB |
| Pair latency intervention, 24 October | 118 | 7.76 GiB |
| Pair source IO intervention, 22 October | 95 | 0.85 GiB |

The exact private catalog SHA-256 is
`295b95ea72e3992dfd50b19747b9cac25f5c4ed7abc94a8bf120b2f1b469ba22`.
The catalog contains source identity/ownership metadata, archive hashes, manifests
and exact file counts. Every original was retained through preparation and until the operator's
specific replacement decision. The subsequent explicit approval covered only
these four packages, not any operational journal or general retention policy.

At 10:31:38 UTC the large filesystem had 146.95 GiB available (18.13%), including
the newly prepared 12.80 GiB archives. Root had 79.53 GiB available after retaining
the independent restore copy. Host swap available was 14.92 GiB and memory
available 35.70 GiB. The automatic monitor no longer reports high swap activity;
the historical M1 missed slot and genuine FAST/HALF risk mismatch remain.

`AGENTS.md` prohibits deleting SQLite journals, datasets, logs or volumes. The
conservative boundary for this continuation is to request explicit permission
before removing even the uncompressed cold SQLite copies; preservation in
verified archives does not silently waive that instruction. No original journal,
dataset, log or volume has been removed. Completing the approved cold replacement
will not require stopping an account, collector or VM.


## Approved cold replacement continuation

The operator subsequently explicitly authorized only the four prepared cold
copies to be replaced by their verified archives. The authorization is bound to
the exact 350-file catalog above; it does not permit general cleanup or removal
of any operational journal, dataset, log or volume.

The scoped activation helper defaults to read-only preflight. It verifies the
pinned catalog, archive/manifest hashes, complete source membership, file hashes
and identities, absence of open descriptors and absence of overlapping active
container mounts. All four sources are rechecked before any removal. Sources
are first moved into private staging, rechecked again, and only manifest-listed
files are unlinked. Shared inode link counts are tracked across packages.
Archive/manifest files are synchronized before replacement. Original package
locations retain root-owned `ARCHIVED.json` records with hashes and restore
instructions. No account or service restart is required.

Nine focused archival tests pass, including real synthetic SQLite restoration,
refusal of traversal/symlinks, archive tampering, open sources, same-metadata
content tampering, scope changes, replacement of cross-package hard links, and
byte-exact forensic restoration of a nonempty WAL without an integrity claim.

The final source/archive preflight passed and replacement completed from
10:58:17 to 10:58:21 UTC (11:58 CET). All 350 original files in the four approved
cold packages were replaced by the already verified archives. The original
package directories now contain only `ARCHIVED.json` records identifying the
archive, exact hashes, manifest, catalog and recovery tool. Private staging was
removed after becoming empty. All four archives and manifests remain intact.

At 10:59:02 UTC available space increased from 137.86 GiB immediately before
activation to 195.76 GiB (24.15% of the filesystem). The measured increase was
57.91 GiB while other writers continued; original-file allocation was 57.92 GiB.
The overall storage-format benefit remains 45.12 GiB after accounting for the
12.80 GiB compressed archives, which were already present before activation.
These two figures use different baselines and must not be added together.

All twelve containers retained exactly their identities, start times, restart
counts and healthy state. Both required OPS VMs retained their states and IDs.
Qwen remains inactive and disabled at boot, and its UI remains explicitly
disabled. M1 reports `OBSERVING` with no baseline error. No service restart or
change to an operational database, account, collector or VM was needed.

### Recovery instructions

Open the retained `ARCHIVED.json` at the old audit-package location. It provides
the archive/manifest paths and the pinned archive SHA-256. Restore into a fresh
private directory with `scripts/verify_cold_archive.py`, supplying its `--archive`,
`--archive-sha256`, `--manifest`, `--destination` and `--result` arguments.

Some original forensic snapshots intentionally include nonempty WAL companions.
For byte-exact recovery of the whole forensic package, also pass `--files-only`.
This restores and verifies every file and its metadata, including WAL/SHM, but
sets `sqlite_integrity_checked=false` and makes no claim that a raw pre-repair
snapshot is a clean runnable account. Investigate those snapshots only on a
private copy. Without that option, the helper requires empty WALs and performs
full read-only SQLite integrity checks. The earlier separate eleven-file
checked-state recovery passed all three database integrity checks.

Restore one package at a time and retain the helper's free-space reserve.
Do not restore over a live directory, merge into an existing account or restart
an old strategy as part of evidence recovery. The compressed originals,
manifests and catalog are root-owned and read-only in the private audit area.


Post-replacement readback at 11:01:11 UTC rehashed all four archives and manifests
against the exact approved catalog and verified every restoration pointer. All
350 files and their WAL companions remain represented by the verified manifests.
The retired BTC account is still accessible in its read-only UI with all six
historical fills. The operational profile remains `local_ai_trading`, with the
real trader disabled, simulator enabled and `deterministic_alignment` unchanged.
Affected account/chart pages respond successfully.

The final passive monitor confirms the larger filesystem's recovered headroom.
It still records the pre-existing FAST/HALF risk mismatch and M1 missed-daily-slot
finding, plus intermittent swap traffic while the required VMs remain active.
Qwen is off and about 14.9 GiB of swap is available; no claim of zero swap IO is
made. This one-time cold replacement reduces retained storage, not ongoing data
or VM growth, and grants no periodic deletion authority.
