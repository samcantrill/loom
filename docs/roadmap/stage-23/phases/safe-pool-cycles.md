# Phase 1 Execution Plan: Safe Pool Cycles

## Metadata

- Status: in_progress
- Roadmap stage and phase: v23 Phase 1
- Manifest: `docs/roadmap/stage-23/implementation-plan.md`
- Branch: `agent/stage-23-p1-safe-pool-cycles`
- Worktree root and path:
  `/home/can134/work/active/loom-worktrees/stage-23-p1-safe-pool-cycles`
- Base revision: `origin/develop` at
  `91e772e9e1874a2f44dcba47b19b165ab4602f17`
- PR target: `develop`
- PR title: `Managed Local Concurrency - Phase 1: Safe Pool Cycles`
- Dependencies: completed v11 queue/resource contracts and confirmed Stage 23
  planning; no Stage 23 implementation dependency
- Workflow path: expanded because this phase changes a public dispatch result,
  SQLite concurrency and mutation fencing, and coordination failure semantics
- Blockers: five review findings are under one maintainer-authorized bounded
  correction beyond the normal 3/3 budget; no PR may open until all five and
  any fresh audit blocker are resolved

## Objective And Context

- Vertical outcome: one controller cycle safely reconciles every active item in
  one selected pool and dispatches additional work up to explicit budgets.
  Ordinary scalar-capacity pressure defers the FIFO head, while concurrent local
  work renews scalar leases and cannot release them before process exit.
- Earlier dependency: reuse the v11 `QueueController`, `QueueService`,
  `QueueRepository`, SQLite queue, dispatch adapters, resource admission, and
  workspace coordination stores.
- Later work explicitly out of scope: concrete slot assignment/renewal,
  environment binding, queue-owned process logs, pool summary/CLI rendering,
  dynamic discovery, and general scheduler policy.

## Current Source And Harness

- Relevant files and symbols:
  - `src/loom/queue/controller.py`: `QueueDispatchResult`, adapter protocols,
    `QueueControllerStep`, `QueueController.run_once()`, and
    `reconcile_active()`.
  - `src/loom/queue/repository.py`, `src/loom/queue/_sqlite.py`, and
    `src/loom/queue/service.py`: FIFO claim, handle recording, completion,
    cancellation, recovery scans, and audit events.
  - `src/loom/queue/config.py`: schema-v1-only `QueueControllerSpec` and
    `QueueServiceSpec`.
  - `src/loom/pipeline/execution/resource_admission.py`: admission decisions
    and current exception-message classification.
  - `src/loom/pipeline/stores/coordination.py`, `sqlite_coordination.py`, and
    `service_coordination.py`: public coordination protocol and built-in lease
    backends.
  - `src/loom/queue/local.py`: scalar admission, in-memory process ownership,
    cancellation/release ordering, and the process-runner seam.
- Existing tests and seams: controller and fake-adapter unit tests, queue record
  and repository contracts, SQLite repository integration, managed-local
  integration, and the three-backend workspace-coordination contract matrix.
- Import, dependency, or harness constraints: queue may import public pipeline
  execution/store contracts; those layers must not import queue. Use SQLite,
  barriers/fake clocks, and existing in-memory test stores; add no dependency.

## Scope

In scope:

- Canonical started, completed, and deferred-before-start dispatch outcomes,
  with compatibility for existing `QueueDispatchResult` construction and
  synchronous/custom adapters.
- Stable coordination failure kinds for capacity, invalid/unsupported input,
  unavailable authority, lost ownership, and internal acquisition failure;
  resource admission preserves these kinds without parsing messages.
- Atomic SQLite FIFO claiming and guarded deferral, handle commit, completion,
  and cancellation using the applicable status, claim owner/id, attempt,
  adapter, and handle identity in one transaction.
- A fresh, non-reusable claim identity for every claim/reclaim across controller
  sessions, including same-owner and unchanged-attempt deferral. Tests may
  inject identity generation, but production identity cannot be reconstructed
  from a reset counter or timestamp.
- A guarded deferral operation that clears claim/incomplete dispatch state,
  preserves enqueue order and attempt, and appends one reason-code audit event.
- `QueueController.run_cycle(...)`, a serializable cycle result, reconcile-all
  behavior, all-owner active counting, FIFO capacity stop, positive active and
  dispatch budgets, and a returned next-maintenance time.
- Schema-v2 normalization for positive controller limits while schema-v1 config
  remains valid with effective values of one. The per-cycle dispatch budget
  defaults to the active limit.
- Managed-local adapter-session ownership and scalar lease maintenance. Renew at
  50% of the last successful TTL; retry typed transient unavailability on later
  cycles only until the 80% safety deadline. Definitive ownership loss acts
  immediately. Loss/deadline stops fill and starts process-group termination.
- Terminal-before-release behavior for local success, non-zero exit,
  cancellation, lease loss, and process-start/handle-commit failure. A rejected
  commit for a started process uses the existing cancellable adapter boundary
  with the new handle; resources remain held until process exit is observed.
- New local handles persist a schema-tagged `managed_local` evidence projection
  containing owner/session, PID/PGID, scalar lease IDs/expiry, and dispatch
  timing. They stop writing command, cwd, full admission records, or fencing
  tokens; legacy records remain readable.
- Existing `run_once()` and foreground drain compatibility, including delegated
  handoff behavior and at most one newly dispatched item per `run_once()` call.

Out of scope:

- Concrete assignments/bindings/log capture, new queue DDL, cross-controller
  item semaphore, retry policy, fairness, multiple-pool cycles, background
  services, and process reattachment.

Assumptions:

- One cycle selects exactly one pool. An omitted pool continues to use the
  configured default/candidate behavior only on compatibility operations.
- `CLAIMED` and `DISPATCHED` records count as active. Foreign owner/session
  records are counted but not mutated; current-session recovery retains
  explicit uncertainty handling.
- A deferred result proves no external work started and any adapter-owned
  partial acquisition was already compensated.

## Fixed Contracts And Private Discretion

- Observable behavior: reconciliation visits all eligible active records even
  when one item produces an item-local failure. Authority/ownership degradation
  blocks new starts. Dispatch stops on the first deferred FIFO head, empty
  queue, active limit, dispatch budget, or fatal repository/controller error.
- Public or durable shapes: the canonical disposition values are `started`,
  `completed`, and `deferred`; deferred has no handle. The cycle result exposes
  reconciliation and dispatch step tuples, final active count,
  `capacity_blocked`, and `next_maintenance_at: str | None`, with `to_dict()`.
  The timestamp is canonical UTC and is the earliest maintenance deadline from
  owned started results/inspections; `None` means no owned active dispatch needs
  timed maintenance. The config keys are `max_active_items` and
  `max_dispatches_per_cycle` under `controller`.
  `QueueDispatchResult` and `QueueDispatchInspection` each carry the optional
  timestamp so the controller can aggregate it without interpreting adapter
  leases. Existing result construction that omits a disposition is normalized
  from today's `complete`/status combination; new results emit an explicit
  disposition. Validation rejects a deferred handle, a started terminal status,
  and a completed active status rather than guessing between them.
- Trust and failure boundaries: coordination stores are the sole classifier and
  expose `capacity`, `invalid_or_unsupported`, `unavailable`, `ownership_lost`,
  or `internal` on the public coordination error. SQLite, service, and test
  backends assign that kind where the failure originates; service rejection
  codes are mapped there, not parsed later. Admission copies the kind into its
  decision. Only `capacity` can become queue deferral, and only after no process
  was started and every partially acquired lease was confirmed released. A
  failed or uncertain compensation is `internal`/`unavailable`, blocks fill,
  and must not requeue the item as ordinary capacity. Invalid/unsupported work
  terminates as failed under existing ownership wording. Unavailable,
  ownership-loss, and internal truth fails closed for the cycle and is not
  silently retried as queue policy.
- Cross-phase contracts: Phase 2 may supply concrete assignment deferral
  and renewal through the same disposition, local lifecycle, and maintenance
  aggregation. Phase 3 consumes a pool snapshot but cannot weaken guards.
- Reproducibility and compatibility: deferral preserves `enqueued_at`,
  `queue_item_id`, and `dispatch_attempt`; audit details contain only stable
  codes/identities. Legacy config and `run_once()` results remain readable.
- Private choices the executor may simplify: exact enum/class names if existing
  public compatibility is clearer, SQL transaction strategy, internal step and
  termination-state helpers, concrete UUID/token encoding, compensation result
  plumbing, and compatibility constructor/normalizer. Do not add a second
  admission result hierarchy, repository revision column, or recovery callback.
  Identity non-reuse, dispositions, deadlines, and guarded semantics are fixed.

## Proportionality

- Existing seam reused: the controller, repository protocol, persisted
  `QueueClaim`, dispatch handle, audit table, recovery scan, and resource
  admission decision remain authoritative.
- Material additions and current justification: one cycle record is required
  to return multiple outcomes; one deferred disposition is required to model
  normal capacity; typed coordination errors are required to decide that safely;
  guarded mutations are required by reachable multi-connection races.
- Optional hardening and future capability deferred: repository revision
  columns, distributed controller quotas, generic retry policy, scheduler
  plugins, backfilling, and queue-notification machinery.

## Invariant Ownership

| Invariant | Owner | Reachable invalid producer or boundary | Consequence | Coverage |
| --- | --- | --- | --- | --- |
| One queued row is claimed by at most one concurrent SQLite connection. | SQLite repository | Two controllers select the same FIFO head before either unguarded update commits. | Duplicate external work. | Barrier race with separate connections and repeated claims. |
| A stale owner cannot defer, attach a handle, complete, or cancel a newer attempt. | Repository transaction guards | Delayed controller mutation after claim/attempt ownership changed. | New work is lost or misreported. | Stale claim, owner, attempt, adapter, and handle cases. |
| Same-owner reclaim at the same attempt still has a distinct claim identity. | Controller identity generation and repository | Controller restart resets its counter after a deferral. | Stale writer becomes indistinguishable from current owner. | Injected restart/reclaim test with unchanged owner and attempt. |
| Only pre-start capacity pressure requeues an item. | Coordination classification, admission, then controller | Backend errors or text changes are mistaken for capacity. | Unsafe retry or hidden uncertainty. | Backend contract matrix and controller disposition tests. |
| Capacity deferral proves partial acquisition was fully compensated. | Resource admission | `_release_partial()` currently suppresses release failures before returning a capacity-coded decision. | A leaked lease is hidden behind a normal FIFO retry. | Inject capacity after one acquisition, then cover confirmed release and release failure separately. |
| A cycle never exceeds its single-controller active or dispatch budget. | Controller | Synchronous completions and repeated claims bypass a loop bound. | Unbounded cycle or excess managed work. | Mixed started/completed/deferred unit and integration cases. |
| FIFO deferral cannot immediately reclaim the same item in one cycle. | Controller | Loop resumes after guarded requeue. | Busy loop and audit churn. | One deferral, one audit event, no later dispatch calls. |
| Local scalar leases renew or the process is stopped before safe reuse; release follows observed exit. | Local adapter | Long runtime, cancellation, lease loss, or failed handle commit. | Overlapping or unrecorded local process. | Fake-clock renewal plus terminate/exit/commit-failure tests. |

## Implementation Slices

1. Add one structured kind to the public coordination error across SQLite,
   authority-service, and the in-memory contract harness; map failures at those
   boundaries, make admission preserve the kind, and replace its message-based
   classification. Make partial-release outcome explicit enough that capacity
   is returned only after confirmed compensation; do not add a parallel error
   hierarchy or generic retry layer.
2. Introduce the three canonical dispatch dispositions and compatibility
   normalization for existing fake, synchronous, custom, and delegated
   adapters.
3. Harden repository operations without DB schema changes. Claim begins the
   SQLite write transaction before FIFO selection. Deferral, handle commit,
   active completion, and active cancellation receive the expected snapshot
   identity from the acting controller and compare the applicable status,
   claim ID/owner/attempt, adapter, and handle ID in that same transaction;
   zero affected rows is a conflict. Queued operator cancellation remains a
   compatibility path and has no fabricated claim/handle expectations.
4. Harden managed-local scalar lifecycle with session ownership, 50%/80%
   renewal scheduling, terminal-before-release cancellation, and post-start
   handle-commit compensation. A rejected handle commit must address the live
   process by the newly returned handle even though it was never persisted,
   using private wiring around the existing cancellable adapter contract. Send
   termination, escalate privately if needed, and retain leases until
   `poll()` observes exit; an unconfirmed exit degrades the cycle. Aggregate the
   earliest maintenance timestamp without persisting renewal updates.
5. Add controller config/cycle behavior, preserve `run_once()`/foreground
   semantics, and prove the full path with unit, contract, and SQLite/local
   integration coverage.

## Test And Validation Plan

| Suite | Required or deferred | Behavior or risk | Minimal assertions or reason |
| --- | --- | --- | --- |
| Package | required | Public dispatch/cycle/config imports stay intentional and cheap. | Expected exports import without CLI, concrete store, or optional config imports. |
| Unit | required | Dispositions, controller budgets, config, admission kinds, scalar renewal, and local compensation. | Valid/invalid result combinations; legacy construction and `run_once()`; reconcile/fill and replacement; confirmed versus failed partial release; deadline/loss; exit-before-release. |
| Contract | required | Repository guards, result/evidence serialization, and coordination parity. | Round trips; no deferred handle; safe local keys only; acquire and renew failures retain the same kind across backends without message dependence. |
| Integration | required | Real SQLite claim/defer/refill and managed-local scalar concurrency. | Barrier claim has one winner; same-owner reclaim changes identity; stale defer/commit/complete/cancel each conflict; capacity queues only after compensation; renewal/termination prevents overlap. |
| E2E / opt-in | deferred to Phase 3 | User-visible status and subprocess proof require assignment/logging. | Phase 1 has no standalone user journey beyond existing queue compatibility tests. |

Targeted commands:

    uv run pytest tests/unit/loom/queue/test_controller.py tests/unit/loom/queue/test_local_adapter.py tests/unit/loom/pipeline/execution/test_resource_admission.py
    uv run pytest tests/contracts/test_queue_python_api_contract.py tests/contracts/test_queue_repository_contract.py tests/contracts/test_workspace_coordination_contract.py
    uv run pytest tests/integration/queue/test_fake_controller.py tests/integration/queue/test_sqlite_repository.py tests/integration/queue/test_managed_local_controller.py
    uv run --extra config pytest tests/contracts/test_queue_config_contract.py

Final commands:

    make validate-pr
    make test-summary

## Risks, Review, And Stops

- Main risks: non-atomic SQLite guards; reusable runtime identities; invalid
  disposition/field combinations; backend category drift; treating uncertain
  compensation as capacity; releasing a scalar lease before exit; and
  overstating a controller-local limit.
- Review focus: transactions/affected rows, identity non-reuse, dispositions,
  boundary-owned classification, compensation-before-deferral, every cycle stop
  condition, scalar renewal/termination ordering, and delegated and legacy
  one-step compatibility. Do not require a Cartesian backend-by-lifecycle matrix:
  backend contracts prove kinds, while focused admission/controller tests prove
  their consequences.
- Stop if: guards require queue DDL; a backend cannot expose a stable kind
  without reopening the public agreement; partial release cannot report enough
  truth to distinguish safe deferral from uncertainty; process exit cannot be
  confirmed through the runner seam; or compatibility requires changing locked
  behavior. Record evidence and return to the manager.
- Accepted debt and revisit trigger: active limit remains controller-local;
  revisit only for a demonstrated multi-controller quota requirement.

## Executor Handoff

- Read section range: this plan plus planning requirements `FR-1` through
  `FR-5`, `FR-8`, `FR-9`, `FR-12`, and decisions `A-1`, `A-2`, `A-5` through
  `A-7`.
- Safe implementation slices: execute slices 1-5 in order and commit coherent
  contract/repository/controller/test checkpoints.
- Decisions not to revisit: no queue migration, distributed semaphore, retry
  scheduler, concrete assignment, release-before-exit, or changed `run_once()`.
- Conditions requiring manager action: any stop condition above, an unavoidable
  public breaking change, or evidence that `origin/develop` changed a reviewed
  boundary.

## Workflow State

- Manager preparation: complete on 2026-08-17 against current `origin/develop`
- Expanded planning: complete on 2026-08-17 at `a3a80ca`; current-source review
  clarified result compatibility, caller-supplied SQLite mutation expectations,
  boundary-owned failure kinds, and compensation-before-deferral without adding
  schema, retry, or recovery machinery
- Implementation: completed at `2df89ce`; repository/controller/config cycle,
  typed coordination/admission classification, guarded SQLite mutations, and
  managed-local scalar lifecycle are implemented with phase-scoped coverage
- Refiner: completed on 2026-08-17. Final scoped correction repairs fail-closed
  cycle handling, current-session-only mutation, both handle-commit compensation
  paths, and cancellation-until-exit behavior without schema or public-surface
  expansion.
- Pre-submit gate: passed at `2df89ce`. Ruff and full-project Pyright passed;
  the isolated default harness passed 2,020 tests, config-extra passed 128
  tests with 3 skips, and source/wheel builds succeeded.
- Independent review: completed once on 2026-08-17. Its delayed-exit process,
  service-backed failure-kind, renewal escalation/proof, evidence redaction,
  and delegated restart findings are resolved at `2df89ce`.
- Blocker corrections: normal 3/3 budget was exhausted; the maintainer
  authorized one additional bounded correction on 2026-08-17. It is complete
  at `2df89ce`, including the five recorded findings and manager-audit repairs
  for legacy config opt-in, guarded active mutations, multi-lease timing and
  cleanup, cycle budgets, and pending-start cancellation.
- PR and merge: pending. The authorized correction, current final gates, and
  fresh manager blocker audit pass; no remaining Phase 1 blocker is known.

## Completion Record

| Item | Result |
| --- | --- |
| Implementation and changed paths | Correction spans queue controller/config/repository/service/SQLite/local lifecycle plus authority-service classification. It preserves legacy schema-v1 opt-in, guards active mutations, retains delayed-start cleanup until exit, renews from the earliest lease, attempts every release, redacts local evidence, and preserves delegated restart recovery. |
| Tests added or updated | Phase matrix passed 94 tests: 46 unit, 22 contract, 20 integration, and 6 config-extra. Coverage includes dispositions, cycle limits, reconcile-all, stale guards, backend failure kinds, compensation, fake-clock renewal/escalation, release retry, redaction, and delegated compatibility. |
| Validated revision/tree state and evidence | `make validate-pr` passed at `2df89ce`: Ruff, Pyright, 2,020 default tests, 128 config-extra tests with 3 skips, and both package builds. `make test-summary` reports 2,148 passed, 3 skipped, and no failures or errors. |
| Validation-relevant changes after evidence | None; only this phase metadata is updated after the passing receipt. |
| PR, review, and merge | Fresh manager review found no remaining blocker. PR creation, CI, and merge remain pending. |
| Residual risk and cleanup | Accepted stage risks remain: controller-local item limits, controller death or an unkillable process, and no durable per-renewal evidence. Worktree and branch remain active until merge. |
