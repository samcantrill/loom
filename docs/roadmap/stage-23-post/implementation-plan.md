# Roadmap Stage 23-post Implementation Plan

Status: confirmed; ready for implementation
Roadmap stage: 23-post
Planning document: docs/roadmap/stage-23-post/planning.md
Artifact layout: manifest-and-phase-plans-v1
Target branch: develop
Current phase: Phase 2 (`explicit-recovery-and-shutdown`)
Blockers: none

## Summary

- Goal: give downstream projects one safe, pool-bound Python runtime for
  managed-local queue construction, lease maintenance, health, shutdown,
  restart recovery, and truthful status.
- Approved behavior and requirement IDs: FR-1 through FR-12 in the planning
  document, approved by the maintainer on 2026-08-18.
- Key design constraints and decision IDs: one spec-owned owner and one pool
  (FQ-1, DQ-1); existing components remain authoritative for their own
  invariants (DQ-2 through DQ-4); persisted, live, and unobserved facts remain
  distinct (DQ-5); physical member leases own bundles (DQ-6).
- Minimum useful change: construct established Stage 23 objects once, keep
  their in-memory state alive, run cycles before maintenance deadlines, block
  on degraded/foreign work, and provide explicit stop/recovery operations.
- Complexity deliberately excluded: Loom-owned daemon/service transport,
  distributed leader or item semaphore, PID recovery, process reattachment,
  hardware discovery, per-lease live reads, automatic limit provisioning,
  weighted core slots, generic scheduling, and GPU-specific core behavior.
- Validation and phase-shaping source: planning sections `Examples And
  Validation` and `Phase Shaping`.
- Out of scope: Stage 24 candidate-policy implementation and the broader Stage
  25 downstream-operations topics such as notifications, generic scheduling,
  resume policy, and resource-usage telemetry.

## Shared Constraints

- Architecture and dependency direction:
  - `loom.queue.managed_local` may compose queue-local modules and public
    `loom.pipeline.stores` contracts.
  - Controller, service, repository, config, and assignment modules must not
    import the new high-level runtime.
  - The explicit managed-local submodule is public; `import loom.queue` remains
    lightweight and does not eagerly import local execution.
  - CLI remains presentation/control over existing services and gains no
    background-process behavior in this stage.
- Shared public and durable contracts:
  - `ManagedLocalQueueRuntime.from_spec(...)` binds exactly one managed pool
    and derives owner identity only from `spec.controller.owner_id`.
  - `start`, `run_cycle`, `serve`, `status`, and
    `resolve_recovery_unknown` are the proposed public operations.
  - Runtime state values are `READY`, `DEGRADED`, `RECOVERY_REQUIRED`,
    `DRAINING`, `CANCELLING`, and `STOPPED`.
  - Existing queue config v1/v2, queue record schema, assignment evidence,
    SQLite schema, and CLI status envelope do not change.
  - Recovery resolution is guarded, records safe operator attestation in queue
    audit evidence, and produces only `UNKNOWN`.
- Shared reproducibility, compatibility, and import constraints:
  - Runtime/process/provider state remains in memory and is never presented as
    durable reattachment state.
  - Fake, delegated SLURM, CPU-only, direct-controller, and schema-v1 behavior
    remains unchanged.
  - Stage 24 policy may influence candidate selection inside a cycle; the
    runtime neither selects candidates nor interprets policy decisions.
  - No new runtime dependency is allowed.
- Shared invariant ownership:
  - Runtime: construction identity, object lifetime, wake timing, health,
    recovery gate, and shutdown mode.
  - Controller: reconcile-before-fill, active counts, dispatch bounds, and
    policy interaction.
  - Local adapter: process/log/lease/assignment ordering, renewal,
    termination, and release.
  - Assignment provider: concrete placement and member lease lifecycle.
  - Coordination authority: capacity, fencing, expiry, and exclusivity.
  - Queue repository: guarded durable transitions and audit facts.
  - External supervisor/operator: prior process-tree containment after crash.
- Decisions no phase may reopen:
  - No automatic PID kill, lease takeover, reattachment, or requeue.
  - No foreign lease release or renewal.
  - No independent adapter/controller owner override.
  - No eager queue-root export.
  - No weighted core slot; amount-two is the default multi-device model.
  - No synthetic bundle ownership that does not acquire physical member keys.
- Worktree root for implementation: the `loom-worktrees` sibling of the
  control checkout; each phase uses the path recorded in its phase plan.

## Phase Index

| Phase | Slug | Status | Phase plan | Branch | PR | Ownership | Goal |
| --- | --- | --- | --- | --- | --- | --- | --- |
| 1 | `safe-managed-local-runtime` | merged | `docs/roadmap/stage-23-post/phases/safe-managed-local-runtime.md` | `agent/stage-23-post-p1-safe-managed-local-runtime` | [#212](https://github.com/samcantrill/loom/pull/212) | Managed-local runtime construction, timing, health, startup gate, drain, and minimal controller/resource seams | Provide a safe normal-operation runtime that cannot silently miss maintenance or refill across degraded/foreign work. |
| 2 | `explicit-recovery-and-shutdown` | in_progress | `docs/roadmap/stage-23-post/phases/explicit-recovery-and-shutdown.md` | `agent/stage-23-post-p2-explicit-recovery-and-shutdown` | pending | Guarded recovery resolution/audit and cancel/timeout shutdown | Let an operator resolve externally contained crash leftovers without taking over leases, and stop current work predictably. |
| 3 | `downstream-operations-proof` | pending | `docs/roadmap/stage-23-post/phases/downstream-operations-proof.md` | `agent/stage-23-post-p3-downstream-operations-proof` | pending | Canonical example, bundle-provider pattern, e2e proof, queue docs, deployment/recovery guide, and small Stage 23 fixes | Make the safe path easy to copy and prove single-item two-slot assignment, live status, logs, refill, and bundle ownership. |

## Quality Gate

- Planning gate: manager-local evidence, functionality, minimum-design,
  proportionality, validation, and phase-shaping checks pass; the maintainer
  approved the plan on 2026-08-18.
- Manager review: passed on the draft. Requirements map to phases, every
  high-consequence mutation has an owner and a failure-closed test, and no
  durable schema or dependency is added.
- Optional independent review: not used. The expanded route was triggered by
  the public recovery trust boundary; a local removal-first review resolved it
  by requiring external process-exit attestation and prohibiting foreign lease
  mutation.
- Correction: not needed.
- Ready for implementation: yes; Phase 1 is merged and Phase 2 implementation
  is in progress.
- Accepted risks: deployment still relies on one externally supervised runtime
  per pool; an unkillable process can outlive a shutdown timeout; custom
  providers can be incorrect; status does not observe hardware health.
- Revisit triggers: a current unattended reattachment consumer; exact shared
  controller quota; repeated generic bundle-provider use; required live lease
  or hardware observation; Loom-owned daemon lifecycle.

## Completion

| Phase | PR and merge | Implementation and validation | Residual risk | Cleanup |
| --- | --- | --- | --- | --- |
| 1 | PR [#212](https://github.com/samcantrill/loom/pull/212) merged into `develop` as `895d45cedcef1010ba8d57253ae08f3938cf6673` | Implementation, manager review, GitHub CI, `make validate-pr`, and `make test-summary` passed | Accepted one-runtime-per-pool deployment rule and deliberately unobserved hardware health | dedicated worktree and local/remote branch removed |
| 2 | pending | pending | pending | pending |
| 3 | pending | pending | pending | pending |
