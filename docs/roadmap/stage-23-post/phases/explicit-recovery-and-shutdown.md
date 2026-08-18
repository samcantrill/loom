# Phase 2 Execution Plan: Explicit Recovery And Shutdown

## Metadata

- Status: in_progress
- Roadmap stage and phase: 23-post, Phase 2
- Manifest: `docs/roadmap/stage-23-post/implementation-plan.md`
- Branch: `agent/stage-23-post-p2-explicit-recovery-and-shutdown`
- Worktree root and path: `../loom-worktrees`; `../loom-worktrees/stage-23-post-p2-explicit-recovery-and-shutdown`
- Base revision: `849157b50a2864f583cafb1d3e1c3f8c8b7db528`
- PR target: develop
- PR title: `Managed Local Operations - Phase 2: Recovery and Shutdown`
- Dependencies: Phase 1 remotely merged; branch must be based on refreshed `origin/develop`
- Requirement coverage: FR-6, FR-7, FR-8, and FR-9
- Workflow path: expanded because operator attestation authorizes a guarded terminal mutation after process-owner loss
- Blockers: none

## Objective And Context

- Vertical outcome: after an external supervisor has contained a crashed
  controller and its children, an operator can explicitly mark one foreign
  local attempt unknown without taking over its leases. A running controller
  can also stop in cancel mode with a bounded timeout while preserving
  process-exit-before-release safety.
- Earlier dependency: Phase 1 provides the pool-bound runtime, one-owner
  construction, current/foreign classification, recovery-required gate,
  reconciliation-only drain, health/status, and deadline-aware loop.
- Later work explicitly out of scope: reattachment, PID probing/killing,
  automatic crash resolution, retry/requeue, supervisor implementation,
  deployment docs, and bundle examples. Phase 3 documents and proves the
  operator workflow.

## Current Source And Harness

- Relevant files and symbols:
  - Phase 1 `src/loom/queue/managed_local.py`: runtime state, foreign-item
    classification, loop, drain, and status.
  - `src/loom/queue/controller.py`: guarded item completion, current-session
    cancellation, pending termination, and `_complete_unknown` precedent.
  - `src/loom/queue/service.py`, `repository.py`, and `_sqlite.py`: expected-
    snapshot completion and queue audit events.
  - `src/loom/queue/local.py`: missing in-memory handle behavior,
    process-group cancellation, termination polling, and release ordering.
  - Stage 23 durable managed-local evidence contains safe owner/session,
    process identifiers, scalar lease IDs/initial expiries, and assignment
    projections but intentionally omits fencing tokens and provider live state.
- Existing tests and seams:
  - `tests/integration/queue/test_service_lifecycle.py` recreates a service over
    the same queue database and observes recovery records.
  - `tests/unit/loom/queue/test_local_adapter.py` proves missing handles need
    recovery and pending termination keeps leases.
  - `tests/integration/queue/test_managed_local_controller.py` proves
    cancellation and release ordering.
  - Phase 1 runtime tests provide deterministic clock/wait and restart harnesses.
- Import, dependency, or harness constraints:
  - Recovery must operate only through queue service/repository guarded
    transitions; no direct SQL or authority implementation access.
  - Do not persist or reconstruct fencing tokens, process objects, provider
    tokens, commands, or environments.
  - Use fake/local coordination clocks to prove lease retention/expiry; no
    wall-clock sleep or real process killing is required for crash tests.

## Scope

In scope:

- Add one public
  `ManagedLocalQueueRuntime.resolve_recovery_unknown(queue_item_id, *, previous_processes_confirmed_stopped, requested_by, reason)`
  operation.
- Require a literal positive process-containment attestation, a non-empty
  operator identity/reason, runtime state `RECOVERY_REQUIRED`, one exact item
  in the selected pool, active status, and foreign ownership.
- Resolve `CLAIMED` and `DISPATCHED` foreign local attempts to `UNKNOWN` through
  expected-snapshot guarded transitions. Preserve or add the minimum synthetic
  recovery handle needed by existing queue invariants.
- Add safe completion audit evidence identifying explicit managed-local
  recovery, requesting operator, prior status/session where available, and the
  process-containment attestation. Do not copy arbitrary raw handle evidence.
- Never call the foreign adapter's inspect/cancel operations and never renew,
  release, fail, or reconstruct its scalar/assignment leases.
- Re-read runtime recovery state after each resolution; remain blocked while
  any foreign active item remains.
- Extend `serve(...)` with explicit `shutdown_mode="cancel"` and optional
  `shutdown_timeout_seconds`; add runtime state `CANCELLING`.
- On cancel shutdown, stop claims, cancel only current-session items, and
  continue reconciliation until process exit and lease cleanup are observed.
- Apply the optional timeout to drain and cancel. On timeout, raise a specific
  public managed-local shutdown error containing safe remaining item IDs,
  retain degraded/stopping status, and never force a queue terminal state or
  release.

Out of scope:

- Automatic resolution at startup, wildcard/all-items recovery, batch atomic
  resolution, or inference from PID existence or persisted expiry timestamps.
- Treating the attestation as hardware or authority lease proof.
- Releasing expired-looking leases, fencing-token persistence, ownership
  transfer, reattachment, or result inference other than `UNKNOWN`.
- Marking crash leftovers `CANCELLED`, `FAILED`, or `SUCCEEDED`; requeueing the
  same attempt; allocating a retry attempt; or changing run lifecycle state.
- Installing signal handlers, creating systemd units, running a daemon, or
  sending a second-stage kill after timeout.
- New queue/database schema or a public per-lease read on
  `WorkspaceCoordinationStore`.

Assumptions:

- The operator/supervisor can truthfully establish that the previous runtime's
  entire process containment group is stopped. Loom does not independently
  verify this assertion.
- Authority expiry and fencing safely retain resources after queue resolution;
  new admission may defer until those leases expire.
- One item per recovery call keeps guarded-transition and partial-failure
  semantics obvious. Downstream code can iterate the exact IDs returned by
  runtime status.
- A shutdown timeout is a reporting boundary, not permission to violate the
  Stage 23 cleanup order. The external supervisor decides what happens next.

## Fixed Contracts And Private Discretion

- Observable behavior:
  - Recovery without affirmative process containment is rejected without
    mutation.
  - Only an active, foreign, selected-pool item may be resolved.
  - The resolved item becomes `UNKNOWN`; audit evidence names the explicit
    recovery action and operator; foreign leases remain unchanged.
  - Recovery blocking clears only after no foreign active item remains.
  - Cancel shutdown starts no new work, acts only on current-session work,
    waits for exit/cleanup, and reports timeout without release.
- Public or durable shapes:
  - The recovery method name, one-item argument shape, required confirmation,
    operator, reason, and `UNKNOWN` result are fixed.
  - Add `CANCELLING` to the in-process state enum.
  - Add a specific managed-local shutdown-timeout error beneath
    `QueueServiceError`; expose it from `loom.queue.managed_local`, not the
    eager queue root.
  - Recovery audit evidence is allowlisted plain data. Existing item, config,
    assignment, database, and CLI schemas stay unchanged.
- Trust and failure boundaries:
  - `previous_processes_confirmed_stopped=True` is an explicit trusted
    operator assertion. The method documentation must say exactly that.
  - Expected-snapshot conflicts fail and leave the newer item untouched.
  - The runtime never treats persisted lease expiry as live authority truth.
- Cross-phase contracts:
  - Phase 3 documents an external supervisor and invokes the exact recovery
    method; it must not wrap it in automatic PID logic.
  - Phase 3's bundle example relies on the same no-foreign-lease-takeover rule.
- Reproducibility and compatibility:
  - Audit facts are durable and safe; process containment evidence remains an
    assertion, not a hardware observation.
  - Existing controller cancellation and normal completion keep their current
    audit shape unless a backward-compatible optional completion-evidence
    field is the smallest implementation.
- Private choices the executor may simplify:
  - Exact audit reason codes, internal helper placement, whether timeout uses a
    subclass carrying attributes or a typed result before raising, and how the
    loop computes the remaining duration.
  - The executor may extend existing completion audit APIs with one optional
    evidence mapping or add a narrow recovery completion method; it must choose
    the smaller contract and avoid DDL.

## Proportionality

- Existing seam reused: queue recovery scans identify candidates, expected
  snapshots fence mutation, existing controller/local cancellation handles
  current-session work, and authority leases already expire independently.
- Material additions and current justification:
  - One explicit recovery operation is necessary because Phase 1 would
    otherwise remain safely but permanently blocked after a crash.
  - Structured audit evidence is necessary because process-exit attestation is
    the trust decision authorizing terminal mutation.
  - Cancel/timeout is necessary for supervised deployments that cannot wait
    indefinitely for a drain.
- Optional hardening and future capability deferred: verifying cgroup/job
  identity, kill escalation, durable recovery acknowledgements, batch
  transactions, lease observation, reattachment, automatic retry, and daemon
  restart policy.

## Invariant Ownership

| Invariant | Owner | Reachable invalid producer or boundary | Consequence | Coverage |
| --- | --- | --- | --- | --- |
| Only externally contained foreign work may be resolved | Operator assertion validated by runtime | Caller passes false/missing confirmation or targets current work | Live work hidden as terminal | Rejection tests plus current/foreign cases |
| Recovery mutation is fenced to the observed attempt | Queue repository | Item changes between status and resolution | Newer attempt incorrectly completed | Expected-snapshot conflict integration |
| Recovery result is unknown and auditable | Runtime/service/repository | Caller guesses success/failure or free-text loses trust fact | False lifecycle claim or poor incident evidence | Exact status and audit allowlist assertions |
| Foreign leases are never mutated | Coordination authority; runtime abstains | Temptation to use persisted lease IDs | Fencing bypass or premature resource reuse | Store spy/no-call plus retained counters |
| Cancel shutdown touches only current session | Runtime/controller | Foreign recovery and current work coexist | Another controller's work is killed | Mixed-session selection test |
| Process exit precedes release and terminal stop | Local adapter | Timeout or kill request mistaken for exit | Overlapping resource use | Pending termination and timeout integration |

## Implementation Slices

1. Add the narrow guarded recovery-completion/audit seam in the repository,
   service, or controller without changing schemas or normal completion
   behavior.
2. Implement one-item `resolve_recovery_unknown` validation, mutation, status
   refresh, and safe error paths in the runtime.
3. Add cancel shutdown, shared drain/cancel timeout accounting, `CANCELLING`,
   and the specific timeout error while preserving reconciliation timing.
4. Build deterministic crash tests over a reused SQLite queue repository and
   coordination store, including a two-slot item whose scalar/member leases
   remain active after queue resolution.
5. Add stale-snapshot, mixed-session, pending-exit, timeout, audit-redaction,
   and compatibility tests; run full validation.

## Test And Validation Plan

| Suite | Required or deferred | Behavior or risk | Minimal assertions or reason |
| --- | --- | --- | --- |
| Package | required | New public error and method remain in explicit submodule | Import succeeds without changing eager root |
| Unit | required | Validation, state changes, timeout arithmetic, audit allowlist | False confirmation/no-op; exact target; cancel state; safe timeout fields |
| Contract | required | Guarded recovery/audit behavior | SQLite repository/service protocol retains expected snapshot and optional evidence compatibility |
| Integration | required | Crash/restart, leases, current/foreign, shutdown ordering | Second runtime blocks; resolution unknown; no foreign lease calls; cancel waits; timeout retains leases |
| E2E / opt-in | deferred to Phase 3 | Supervisor/operator journey and copyable code | Docs/example phase owns it |

Targeted commands:

    uv run --extra config pytest tests/unit/loom/queue/test_managed_local_runtime.py tests/unit/loom/queue/test_controller.py tests/unit/loom/queue/test_local_adapter.py -q
    uv run --extra config pytest tests/contracts/test_queue_repository_contract.py tests/contracts/test_queue_python_api_contract.py -q
    uv run --extra config pytest tests/integration/queue/test_managed_local_runtime.py tests/integration/queue/test_managed_local_controller.py tests/integration/queue/test_service_lifecycle.py tests/integration/queue/test_sqlite_repository.py -q

Final commands:

    make validate-pr
    make test-summary

## Risks, Review, And Stops

- Main risks: operator confirmation could be mistaken for automatic proof;
  recovery could release another session's leases; a CAS race could complete a
  newer attempt; timeout handling could violate terminal-before-release; or
  audit evidence could leak raw provider/launch data.
- Review focus: explicit trust wording, one-item exact target, expected
  snapshot, unknown-only result, no foreign adapter/store mutation, retained
  leases, current-session-only cancel, and safe audit/status fields.
- Stop if:
  - recovery requires PID probing, a persisted fencing token, provider live
    token, direct SQL, or an authority lease takeover;
  - an accepted invariant cannot be expressed without queue DB/schema DDL;
  - resolution would need to mutate run/stage authority lifecycle;
  - shutdown timeout cannot return control without releasing live resources;
  - Phase 1 current/foreign classification is not reliable for the supported
    selected-pool path.
- Accepted debt and revisit trigger: the operator assertion is not machine-
  verified. Revisit only when a real supervisor exposes durable job/cgroup
  identity that Loom can validate without PID reuse ambiguity.

## Executor Handoff

- Read section range: this entire phase plan, planning FR-6 through FR-9, and
  decisions FQ-4 through FQ-6/DQ-4 through DQ-5.
- Safe implementation slices: follow slices 1-5; test no-mutation paths before
  adding the positive recovery path.
- Decisions not to revisit: explicit one-item recovery, process-stop
  attestation, unknown-only outcome, no foreign lease mutation, no PID logic,
  cancel waits for cleanup, timeout is not force release.
- Conditions requiring manager action: any stop condition, a need for a new
  durable schema/public coordination method, or an API change that makes
  recovery automatic or less explicit.

## Workflow State

- Manager preparation: complete at
  `849157b50a2864f583cafb1d3e1c3f8c8b7db528`; Phase 1 PR #212 is remotely
  merged, the dedicated worktree is clean, and the guarded repository/service
  completion plus current/foreign classification seams remain available
- Expanded planning: not needed; Phase 1 leaves the approved exact-item foreign
  recovery target and current-session ownership boundary unambiguous
- Implementation: in progress with one `loom_phase_executor`
- Refiner: not needed unless a qualified blocker is found
- Pre-submit gate: pending
- Independent review: recommended because recovery attestation authorizes a
  durable terminal mutation and shutdown affects lease safety
- Blocker corrections: 0/3
- PR and merge: pending

## Completion Record

| Item | Result |
| --- | --- |
| Implementation and changed paths | pending |
| Tests added or updated | pending |
| Validated revision/tree state and evidence | pending |
| Validation-relevant changes after evidence | none / pending |
| PR, review, and merge | pending |
| Residual risk and cleanup | pending |
