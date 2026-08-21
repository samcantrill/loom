# Phase 1 Execution Plan: Safe Managed-Local Runtime

## Metadata

- Status: merged
- Roadmap stage and phase: 23-post, Phase 1
- Manifest: `docs/roadmap/stage-23-post/implementation-plan.md`
- Branch: `agent/stage-23-post-p1-safe-managed-local-runtime`
- Worktree root and path: `../loom-worktrees`; `../loom-worktrees/stage-23-post-p1-safe-managed-local-runtime`
- Base revision: `e0b22c23978435f4a45bfbf2e4f3de8cbdce80b6`
- PR target: develop
- PR title: `Managed Local Operations - Phase 1: Safe Runtime Loop`
- Dependencies: completed Stage 23; no Stage 25 implementation dependency
- Requirement coverage: FR-1, FR-2, FR-3, FR-4, FR-5, FR-6, FR-7, FR-9, and FR-12
- Workflow path: expanded because one new public runtime owns timing across process and lease boundaries
- Blockers: none

## Objective And Context

- Vertical outcome: a downstream project can construct one managed-local
  runtime from a queue spec and coordination store, run it through a safe
  maintenance loop, observe its health, stop by draining, and receive a clear
  recovery block instead of silently operating across foreign active work.
- Earlier dependency: Stage 23 already provides atomic claims, reconcile-before-
  fill cycles, scalar and assignment leases, process groups, safe logs,
  same-session status, and concrete provider injection.
- Later work explicitly out of scope: explicit foreign-item resolution,
  cancel/timeout shutdown, example migration, bundle-provider guidance,
  daemon/service transport, and process reattachment.

## Current Source And Harness

- Relevant files and symbols:
  - `src/loom/queue/config.py`: `QueueServiceSpec`,
    `QueueControllerSpec`, and authored `local_assignments`.
  - `src/loom/queue/service.py`: `QueueService.from_spec`, lifecycle,
    pool snapshots, and recovery scans.
  - `src/loom/queue/controller.py`: `QueueController.run_cycle`,
    current-session fencing, active counting, and cancellation.
  - `src/loom/queue/local.py`: `LocalQueueDispatchAdapter`, process runner,
    maintenance deadlines, renewal, and cleanup.
  - `src/loom/queue/assignments.py`: no-op/static providers and bindings.
  - `src/loom/queue/resources.py` and `preflight.py`: read-only authority
    reconciliation.
  - `src/loom/queue/status.py`: persistence-first pool status and
    same-session live observation.
- Existing tests and seams:
  - `tests/unit/loom/queue/test_controller.py` proves degraded cycles do not
    refill and exposes `next_maintenance_at`.
  - `tests/unit/loom/queue/test_local_adapter.py` proves renewal and
    termination-before-release behavior.
  - `tests/integration/queue/test_managed_local_controller.py` proves bounded
    concurrency/refill over real queue transitions.
  - `tests/unit/loom/queue/test_queue_status.py` proves owner/session matching.
  - Package import tests require the queue root and controller modules to
    avoid eager local-execution dependencies.
- Import, dependency, or harness constraints:
  - Put the facade in new `src/loom/queue/managed_local.py`; do not eagerly
    import it from `loom.queue.__init__`.
  - Use public `loom.pipeline.stores` contracts only. Do not import private
    authority implementations.
  - Deterministic loop tests must inject or privately seam clock/wait behavior;
    they must not depend on wall-clock sleeps.
  - Preserve unrelated dirty work by implementing in the dedicated worktree.

## Scope

In scope:

- Add public `loom.queue.managed_local.ManagedLocalQueueRuntime` plus typed
  in-process state/status records.
- Add `from_spec(...)` construction for one selected managed pool using
  `spec.controller.owner_id` for both controller and adapter.
- Auto-construct the selected pool's authored static assignment provider;
  otherwise use no-op or one explicitly injected custom provider. Reject an
  authored-plus-explicit provider ambiguity.
- Preserve useful existing adapter options such as current drift inputs,
  lease TTL, wait timeout, process-runner injection, and log directory without
  adding config-schema fields.
- Revalidate selected logical limits, static member limits, coordination
  capabilities, pool mode, and built-in platform support at `start()` without
  provisioning authority state.
- Add the smallest controller seam for reconciling all current-session items
  without filling and for classifying current versus foreign recovery work.
- Add `run_cycle()` bound to the selected pool and `serve(stop_event, ...)`
  with bounded polling and deadline-aware wake-up.
- Make `serve()` default to a drain shutdown that stops claims but continues
  renewal/reconciliation until owned items are terminal.
- Add `status()` that reports runtime state, owner, pool, last-cycle time,
  next maintenance time, degraded/foreign item IDs, existing pool status, and
  observation scope (`persisted`, `same_session_or_unavailable`,
  `not_observed`).
- Make any pre-existing active item in the selected pool set
  `RECOVERY_REQUIRED`; do not claim new work while blocked.

Out of scope:

- Resolving or mutating foreign recovery items.
- Cancel-on-stop and shutdown timeouts.
- PID lookup, signal delivery to foreign process groups, lease takeover,
  reattachment, or automatic requeue.
- Multiple pools in one runtime, controller leader election, or changing the
  controller-local meaning of `max_active_items`.
- CLI or daemon commands, status-envelope changes, hardware discovery, or
  provider registries.
- Stage 25 candidate reads/policy decisions.

Assumptions:

- The recommended deployment runs one runtime process per pool. Authority
  leases still prevent resource overlap if that rule is violated, but the
  numeric active-item limit remains controller-local.
- `threading.Event` or a structural equivalent is sufficient for the
  foreground stop signal; signal-handler installation remains downstream.
- The runtime may expose its established `QueueService` for enqueue/status
  composition, but it does not duplicate `QueueClient` operations.
- Custom assignment providers own provider-specific startup checks; the
  runtime still validates selected logical resource limits.

## Fixed Contracts And Private Discretion

- Observable behavior:
  - The configured owner is used consistently at every construction point.
  - `start()` fails before dispatch on selected-pool/authority mismatch.
  - `serve()` always reconciles before fill and wakes by the controller's
    reported maintenance time or its shorter poll interval.
  - Degradation stops refill and remains visible until a fully healthy
    reconciliation.
  - Foreign startup work returns `RECOVERY_REQUIRED` and leaves queued items
    unchanged.
  - Drain stops new claims, maintains owned work, and stops only after owned
    active work reaches a terminal state.
- Public or durable shapes:
  - Public module path and class name are fixed.
  - Public methods for this phase are `from_spec`, `start`, `run_cycle`,
    `serve`, and `status`.
  - Runtime state values fixed for this phase are `READY`, `DEGRADED`,
    `RECOVERY_REQUIRED`, `DRAINING`, and `STOPPED`; Phase 2 may add
    `CANCELLING` compatibly.
  - Runtime status is plain-data serializable but is not persisted and is not a
    new CLI or durable schema.
  - Existing queue/config/evidence/database shapes are unchanged.
- Trust and failure boundaries:
  - Authored config is trusted project code; coordination results are mutable
    external state and are revalidated.
  - Runtime catches cycle-level operational failure only to mark degraded and
    retry reconciliation; it does not invent a successful result.
  - A foreign item cannot be inspected or resolved by this phase.
- Cross-phase contracts:
  - Phase 2 builds recovery resolution and cancel shutdown on the runtime
    state/classification and reconciliation-only path established here.
  - Phase 3 uses this public facade in the canonical example.
- Reproducibility and compatibility:
  - Direct `QueueController` use and existing adapters retain behavior.
  - Object/session state is never serialized as restart state.
  - Schema-v1 and pools without static assignments remain accepted.
- Private choices the executor may simplify:
  - Exact helper class names, internal lock usage, status-record nesting,
    deadline arithmetic helpers, and test-only clock/wait seams.
  - Whether reconciliation-only behavior is a new controller method or a
    backward-compatible mode, provided the public controller default remains
    unchanged and no fill can occur during drain.

## Proportionality

- Existing seam reused: the runtime calls the established controller cycle,
  local adapter, assignment providers, resource reconciliation, and pool
  status. It does not reimplement dispatch or leases.
- Material additions and current justification:
  - One public facade is required because no existing owner spans object
    lifetime, owner identity, timing, health, and shutdown.
  - One reconciliation-only seam is required because `run_cycle()` can refill
    and `reconcile_active()` processes only one item.
  - One runtime status record is required because a pool snapshot cannot
    describe current loop health or recovery blocking.
- Optional hardening and future capability deferred: thread-safe remote
  control, signal registration, metrics, daemonization, leader election,
  reattachment, hardware checks, and automatic backoff policy.

## Invariant Ownership

| Invariant | Owner | Reachable invalid producer or boundary | Consequence | Coverage |
| --- | --- | --- | --- | --- |
| Controller and adapter share one owner | Runtime factory | Independent manual constructor arguments | Live status mismatch and ambiguous cleanup ownership | Factory unit plus same-session integration |
| Selected authority limits match authored capacity | Coordination authority plus runtime startup validation | Mutable external limits after config parsing | Deferral/failure inconsistent with authored inventory | No-mutation mismatch tests |
| Active work is maintained before deadline | Runtime schedules; adapter renews | Downstream sleep/loop timing | Lease loss and process termination | Fake clock/wait over scalar and slot renewal |
| Degraded work prevents refill | Controller, surfaced by runtime | Renewal/inspection exception | New work starts while existing work is uncertain | Combined degrade/recover/refill integration |
| Foreign work prevents startup fill | Runtime recovery gate | Fresh process has no live adapter/provider state | Overlapping or falsely completed local work | Restart over same SQLite repository |
| Drain never claims new work | Runtime plus reconciliation-only controller path | Calling normal cycle during stop | Shutdown extends workload or starts surprise work | Active-plus-queued drain test |
| Status does not claim hardware truth | Runtime status/read model | Persisted lease projection mistaken as live availability | Operator makes unsafe inference | Exact observation-scope assertions |

## Implementation Slices

1. Add the managed-local runtime module, state/status types, pool validation,
   and construction that derives one owner and preserves the queue-root import
   boundary.
2. Extract/reuse the smallest read-only logical/static authority checks and
   build authored static assignments without changing config or provisioning
   limits.
3. Add controller current-session classification and reconcile-all-without-fill
   behavior with focused compatibility tests for existing cycles.
4. Implement `start`, `run_cycle`, deadline-aware `serve`, degraded/recovery
   health, and drain shutdown using deterministic wait/clock seams.
5. Add package, unit, and SQLite/in-memory integration coverage, then verify
   no eager imports or behavior changes in fake/delegated/direct paths.

## Test And Validation Plan

| Suite | Required or deferred | Behavior or risk | Minimal assertions or reason |
| --- | --- | --- | --- |
| Package | required | Public submodule and import direction | Managed-local import works; queue root remains lightweight; no private authority import |
| Unit | required | Construction, validation, states, deadline waits, no-fill, status | One owner; static/custom rules; no provisioning; exact wake/state/source behavior |
| Contract | required | Public managed-local API remains typed and intentional | Add a focused Python API contract without changing root exports |
| Integration | required | Real queue transitions plus coordination leases | Same-session status, renewal, degraded recovery, restart gate, drain ordering |
| E2E / opt-in | deferred to Phase 3 | Canonical downstream script migration | Phase 1 has no example behavior change |

Targeted commands:

    uv run --extra config pytest tests/package/test_import.py tests/package/test_import_boundaries.py -q
    uv run --extra config pytest tests/unit/loom/queue/test_managed_local_runtime.py tests/unit/loom/queue/test_controller.py tests/unit/loom/queue/test_local_adapter.py tests/unit/loom/queue/test_queue_status.py -q
    uv run --extra config pytest tests/contracts/test_queue_python_api_contract.py tests/contracts/test_queue_managed_resources_contract.py -q
    uv run --extra config pytest tests/integration/queue/test_managed_local_runtime.py tests/integration/queue/test_managed_local_controller.py -q

Final commands:

    make validate-pr
    make test-summary

## Risks, Review, And Stops

- Main risks: an apparently helpful facade could hide maintenance deadlines,
  expose false hardware truth, import heavyweight execution from the queue
  root, or call a fill cycle during drain.
- Review focus: one-owner construction; no authority provisioning; exact
  deadline behavior; degraded and foreign no-fill; terminal-before-release;
  queue-root import cost; unchanged Stage 23/25 ownership.
- Stop if:
  - normal operation needs a new queue/config/database schema;
  - runtime correctness requires persisted process/provider-private tokens;
  - a controller change alters default `run_cycle()` selection or dispatch;
  - selected-pool startup cannot be validated without provisioning authority;
  - current Stage 25 implementation has changed the cycle contract in a way
    not covered by the manifest.
- Accepted debt and revisit trigger: the phase detects but cannot resolve
  foreign work. Phase 2 owns explicit resolution; durable survival remains
  deferred until a real reattachment consumer exists.

## Executor Handoff

- Read section range: this entire phase plan, plus planning requirements FR-1
  through FR-7, FR-9, and FR-12 and decisions DQ-1 through DQ-5.
- Safe implementation slices: follow slices 1-5 in order; preserve unrelated
  changes and do not edit Stage 25 planning artifacts.
- Decisions not to revisit: one pool, spec-owned owner, explicit submodule,
  no provisioning, no foreign mutation, default drain, no schema/dependency.
- Conditions requiring manager action: any stop condition above, a public API
  shape materially different from the fixed contracts, or a validation failure
  caused by an actual Stage 25 cycle-contract change.

## Workflow State

- Manager preparation: complete at `e0b22c23978435f4a45bfbf2e4f3de8cbdce80b6`;
  the dedicated worktree is clean and based on current `origin/develop`, the
  manifest remains approved, and Stage 25 has not changed the controller cycle
  contract
- Expanded planning: not needed unless the recheck finds a changed public cycle
  or import-boundary risk
- Implementation: complete at final validation-relevant revision
  `3aacfc30b0afe27acc16f66f64c0af1ce396fe3b`
- Refiner: completed blocker correction 1; recovery-classification failures now
  fail closed as `DEGRADED` in both startup and cycles
- Pre-submit gate: passed manager-locally at `3aacfc3`; scope, fixed contracts,
  import direction, failure behavior, tests, and proportionality match the
  approved phase
- Independent review: not used; the implementation adds only the approved
  explicit submodule and leaves controller default behavior unchanged, with no
  material residual risk beyond the accepted plan risks
- Blocker corrections: 3/3; manager correction 2 separates runtime, persisted
  queue, same-session process, and unobserved hardware/lease status scopes;
  manager correction 3 adds missing spec-owner/static-provider and read-only
  static-boundary proof
- PR and merge: PR [#212](https://github.com/samcantrill/loom/pull/212)
  passed GitHub CI and was squash-merged into `develop` as
  `895d45cedcef1010ba8d57253ae08f3938cf6673`

## Completion Record

| Item | Result |
| --- | --- |
| Implementation and changed paths | Added `loom.queue.managed_local.ManagedLocalQueueRuntime`, its typed runtime state/status, selected-pool startup validation, deadline-aware drain serving, recovery gating, and controller current-session classification/reconciliation in `src/loom/queue/managed_local.py` and `src/loom/queue/controller.py`. The first blocker correction additionally wraps startup and cycle recovery classification plus both cycle execution paths in failure-closed `DEGRADED` transitions. The second correction reports runtime, queue, process, and hardware/lease observation scopes independently. Kept `loom.queue` root imports unchanged. |
| Tests added or updated | Added managed-local package/API, unit, and SQLite integration coverage; added controller no-fill reconciliation coverage; added `tests/integration/queue/__init__.py` so same-named unit/integration test modules collect together. The first blocker correction adds startup/cycle recovery-scan failure, earlier-of-poll/deadline wait, and degraded-to-healthy refill causal coverage; the second adds exact safe status-scope wording; the third proves spec-owner live status, authored static binding, and read-only static-limit failure. |
| Validated revision/tree state and evidence | `3aacfc30b0afe27acc16f66f64c0af1ce396fe3b` is the final validation-relevant revision. Targeted queue/package/contract/integration suites: 143 passed before the final construction tests; the final managed-local unit/integration slice then passed 10 tests. `make validate-pr`: passed (Ruff, Pyright 0 errors, default 2,113 passed, config-extra 128 passed/3 skipped, build). `make test-summary`: passed; `build/test-summary.md` records package 113, unit 1,494, contract 270, integration 187, e2e 49, and config-extra 128 passed with 3 skipped. |
| Validation-relevant changes after evidence | none; only this completion-evidence update follows the validated implementation revision |
| PR, review, and merge | PR [#212](https://github.com/samcantrill/loom/pull/212) correctly targeted `develop`, passed manager review and GitHub CI, and was squash-merged as `895d45cedcef1010ba8d57253ae08f3938cf6673`. |
| Residual risk and cleanup | The recovery-scan false-`READY` and ambiguous observation-scope blockers are resolved. Foreign recovery remains intentionally visible as `RECOVERY_REQUIRED` without mutation; Phase 2 owns explicit resolution. The dedicated worktree and local/remote feature branch were removed. |
