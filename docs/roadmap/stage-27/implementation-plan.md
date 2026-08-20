# Roadmap Stage 27 Implementation Plan: Auto-Configured Local GPU Pools

Status: ready; manager quality gate and maintainer approval passed
Roadmap stage: 27
Planning document: docs/roadmap/stage-27/planning.md
Artifact layout: manifest-and-phase-plans-v1
Target branch: develop
Current phase: Phase 1 pending
Blockers: roadmap predecessor completion before Phase 1 implementation

## Summary

- Goal: let a Python caller discover or supply local GPUs, select a whole,
  shared, or grouped layout, safely prepare authority capacity, and run the
  existing managed-local queue lifecycle without hand-authored slots.
- Approved behavior and requirement IDs: FR-1 through FR-12; the maintainer's
  implementation-workflow request confirms implementation authority.
- Key design constraints and decision IDs: integer shares/groups (FQ-1/FQ-2),
  Python-first preparation (FQ-3), explicit atomic provisioning (FQ-4), frozen
  startup discovery (FQ-5), explicit NVIDIA adapter (FQ-6), and DQ-1 through
  DQ-7 in planning.
- Minimum useful change: manual inventory plus one-GPU and N-share layouts,
  an atomic create-or-match authority operation, and a prepared runtime helper.
- Complexity deliberately excluded: queue config schema v3, float amounts,
  live inventory/health/utilization, plugin loading, mixed layouts over the same
  device set, overlapping group packing, MIG administration, and multi-host use.
- Validation and phase-shaping source: planning sections `Examples And
  Validation` and `Phase Shaping`.
- Out of scope: Stage 25 selection-policy changes. Generic scheduling and
  usage observation remain deferred beyond Stage 26.

## Shared Constraints

- Architecture and dependency direction:
  - Public GPU behavior lives under explicit `loom.queue.gpu` imports.
  - Existing queue/controller/local/store modules never import NVIDIA code.
  - The GPU layer composes `QueueServiceSpec`, `ResourceAssignmentProvider`,
    `ManagedLocalQueueRuntime`, and public store contracts; it does not replace
    their lifecycle ownership.
  - `loom.queue.gpu.nvidia` uses only the standard library and an injected
    command runner. Importing `loom` or `loom.queue` never probes hardware.
- Shared public and durable contracts:
  - `LocalGpuDevice`, `LocalGpuLink`, `LocalGpuInventory`,
    `LocalGpuInventoryProvider`, `LocalGpuPoolLayout`, `LocalGpuPoolPlan`,
    `plan_local_gpu_pool`, `ensure_local_gpu_pool_limits`, and
    `build_managed_local_gpu_runtime` form the proposed public Python surface.
  - Layout factories are `whole_gpus()`, `shares_per_gpu(n)`, and
    `grouped(n, grouping=..., groups=...)`.
  - `NvidiaSmiGpuInventoryProvider` is public only from
    `loom.queue.gpu.nvidia`.
  - `LocalGpuPoolPlan` exposes its prepared `queue_spec`, immutable
    `required_limits`, deterministic `fingerprint`, `operator_summary()`,
    `safe_summary()`, and provider-construction behavior used by the public
    runtime helper. Operator summary may include binding/topology details;
    safe summary never does.
  - `WorkspaceCoordinationStore.ensure_resource_limits(...)` atomically creates
    missing positive limits or accepts exact matches; a mismatch performs no
    mutation.
  - Existing queue record, queue SQLite, assignment evidence, and queue config
    schema v1/v2 shapes do not change.
- Shared reproducibility, compatibility, and import constraints:
  - Discovery is resolved once; the plan and its fingerprint are deterministic
    for the same normalized inventory/layout.
  - Device binding values and raw topology are operator-local and never appear
    in ordinary queue status or durable assignment evidence.
  - Static/manual, CPU-only, delegated SLURM, and direct custom-provider paths
    behave exactly as before.
  - Default tests use fake inventory and fake external commands; real NVIDIA
    evidence remains opt-in.
- Shared invariant ownership:
  - Discovery provider: external observation and normalization.
  - GPU planner: layout validation, deterministic placements, capacity, keys,
    and plan fingerprint.
  - GPU assignment provider: physical member acquisition/renewal/release.
  - Coordination authority: atomic limit creation/matching, leases, fencing,
    capacity, and expiry.
  - Managed-local runtime/adapter: process lifecycle, recovery, logs, renewal
    deadlines, termination-before-release, and redacted status.
- Decisions no phase may reopen:
  - No float queue resources or claim that shares isolate hardware.
  - No runtime-start mutation of authority limits.
  - No synthetic group ownership without every member lease.
  - No discovery side effects during import or config parsing.
  - No silent topology fallback, hot refresh, or queue schema migration.
  - No mixed layouts over the same physical device set in this stage.

## Phase Index

| Phase | Slug | Status | Phase plan | Branch | PR | Ownership | Goal |
| --- | --- | --- | --- | --- | --- | --- | --- |
| 1 | `gpu-plans-safe-bootstrap` | pending | `docs/roadmap/stage-27/phases/gpu-plans-safe-bootstrap.md` | `agent/stage-27-p1-gpu-plans-safe-bootstrap` | pending | GPU inventory/layout/plan API, atomic authority ensure, whole/share composition | Run a manually supplied whole/share GPU pool safely without authored slots. |
| 2 | `grouped-gpu-placement` | pending | `docs/roadmap/stage-27/phases/grouped-gpu-placement.md` | `agent/stage-27-p2-grouped-gpu-placement` | pending | Deterministic disjoint groups and member-backed assignment lifecycle | Allocate N strongly connected GPUs as one logical unit without member overlap. |
| 3 | `nvidia-auto-discovery` | pending | `docs/roadmap/stage-27/phases/nvidia-auto-discovery.md` | `agent/stage-27-p3-nvidia-auto-discovery` | pending | Explicit NVIDIA command adapter, diagnostics, docs, examples, acceptance | Turn installed NVIDIA hardware into the same reviewed plan automatically. |

## Quality Gate

- Planning gate: manager evidence, functionality, minimum-design,
  proportionality, validation, and phase-shaping checks passed on `314e418`.
- Manager review: passed; each requested mode maps to one authoritative owner,
  and high-consequence interactions are covered without a Cartesian matrix.
- Optional independent review: not used for the plan; reconsider before Phase
  1 only if authority/backend contracts change before implementation.
- Correction: not needed.
- Ready for implementation: yes; Phase 1 remains execution-blocked until the
  normal roadmap predecessor gate is satisfied.
- Accepted risks: shares provide no isolation; one layout owns a device set;
  topology grouping is deterministic/disjoint rather than globally optimal;
  NVIDIA parsing remains an explicit external-command boundary.
- Revisit triggers: declarative service startup, mixed layouts, overlapping
  groups, MIG lifecycle, another vendor, or required live health/utilization.

## Completion

| Phase | PR and merge | Implementation and validation | Residual risk | Cleanup |
| --- | --- | --- | --- | --- |
| 1 | pending | pending | pending | pending |
| 2 | pending | pending | pending | pending |
| 3 | pending | pending | pending | pending |
