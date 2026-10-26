# Approved storage cleanup — 26 October 2026

The operator explicitly requested removal of the obsolete 19 October Docker
rollback and retained LLM models, and deletion of container images only when
unused. This maintenance preserves current lab data, historical candidate and
test images, accounts, strategies, collectors and the two required OPS VMs.
Execution and review were SINGLE_AGENT; this is not independent assurance.

## Completed removal

| Target | Result | Space |
| --- | --- | ---: |
| Obsolete 19 October runtime rollback | Exact cold directory removed | 66.73 GiB allocated |
| Retained model weights | Qwen3.6 MoE 35B-A3B, Qwen3.8 27B and Bonsai2 27B removed | 43.89 GiB allocated |
| Obsolete unreferenced image builds | 860 explicit image IDs removed; zero Docker refusals | Approximately 11.31 GiB observed available-space increase |

The rollback was the inactive migration copy, not either mounted runtime
store. Before removal, checks found no overlapping container mounts, process
file descriptors, mapped model files or mounts in inspected process namespaces.
The three model files and their containing directories matched the inventory.
Qwen inference and its analysis timer remain inactive and disabled.

The image inventory included intermediate builds hidden by the default image
listing. The removal plan preserved all tagged or digest-addressed images,
images referenced by every running or stopped container, source-pinned image
IDs, all OctoBot-labelled historical builds, builds less than 24 hours old, and
the complete ancestry of those protected images. OPS source references were
checked as well. This retains the lab runtime, research candidates, browser and
test tools, and recent OPS work. The plan was refreshed against current Docker
metadata immediately before execution.

Deletion used only the pre-recorded IDs, in child-before-parent order, with
`docker image rm --no-prune`, without force. No container, Docker volume,
unlisted parent image, active containerd filesystem or raw layer was deleted.
Docker managed reference checks and layer reclamation. The final inventory
contains 604 images including retained intermediate layers; every protected ID
present in the original inventory remains present.

## Measured storage result

At 12:45:49 UTC / 13:45:49 CET, the data filesystem `/dev/md3`, mounted at
`/var/lib/libvirt`, has **306.41 GiB available**, compared with **184.50 GiB**
immediately before cold-target removal: **121.91 GiB recovered**, net of
concurrent writes. This is the same filesystem that contains the active
Docker/containerd stores through bind mounts; those aliases are not extra disks.

The root filesystem has approximately **79.19 GiB available**. It was not the
target of this cleanup. Ext4 reserved space, partitions and RAID configuration
were not changed. Sizes of images with shared layers must not be summed to
estimate physical recovery; the available-space measurements above are used.

## Continuity and validation

- All 12 running lab containers are healthy. All pre-existing containers retain
  their IDs, image IDs, states, start timestamps, restart counts and mounts.
  Mount lists were compared by destination because Docker does not return a
  stable list order.
- The complete VM list, including the two running OPS VMs, is unchanged.
- Dashboard comparison, intraday-pair, M1 review and original V13 pages return
  HTTP 200. The retired BTC account remains a read-only archive with six fills
  and `no_real_orders=true`.
- The selected profile remains paper-only: real trader disabled, simulator
  enabled, and `decision_mode=deterministic_alignment`.
- The earlier cold-archive catalog retains SHA-256
  `295b95ea72e3992dfd50b19747b9cac25f5c4ed7abc94a8bf120b2f1b469ba22`.
  Those compressed audit archives and their recovery pointers were preserved.
- The scheduled monitor at 12:45:06 UTC reports fresh market, paper and scalping
  sources. Its existing FAST/HALF risk-mismatch and missed M1 daily-slot alerts
  remain; cleanup does not resolve or suppress those separate findings.
- No service restart, account mutation, strategy adjustment, package install
  or model download was needed. No live SQLite integrity scan was introduced.
  `git diff --check` passes; no application code changed in this maintenance.

The retired runtime rollback and model weights have been intentionally deleted,
rather than moved into another copy on this disk. Operational data and current
runtime stores were not used as deletion targets. No recurring cleanup job was
created, and this authorization does not extend to other datasets or VM images.

Private execution evidence is retained under the task-specific
`audit-evidence/storage-cleanup-20261026` directory: exact image plan and
results, cold-target removal result, mount/reference checks, before/after
container and image inventories, VM lists, UI checks and final storage readings.
Work card: `work-card-e411018a-20e0-4fec-a7a2-f1f9c4768b38`.
