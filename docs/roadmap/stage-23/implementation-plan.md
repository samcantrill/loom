# Roadmap Stage 23 Implementation Plan: Managed Local Concurrency And Resource Assignment

Status: ready; plan quality gate passed
Roadmap stage: `v23`
Planning document: `docs/roadmap/stage-23/planning.md`
Artifact layout: `manifest-and-phase-plans-v1`
Target branch: `develop`
Current phase: Phase 1 in progress
Blockers: five Phase 1 product blockers are under one maintainer-authorized
bounded correction beyond the normal 3/3 budget

## Summary

- Goal: let one long-lived managed-local controller reconcile and run several
  whole-run queue items in one pool while scalar authority leases and exclusive
  concrete assignments remain safe, observable, and domain-neutral.
- Approved behavior and requirement IDs: `FR-1` through `FR-12` in the planning
  document are locked. They cover pool cycles, opt-in concurrency, typed
  deferral, guarded persistence, static slots, local lifecycle composition,
  renewal, logs/status, preflight, and compatibility.
- Key design constraints and decision IDs: `A-1` through `A-7` keep scheduling
  policy in the controller, assignment policy in a queue-local structural
  provider, coordination classification at the store boundary, and logical
  resource requests portable.
- Minimum useful change: a public pool-cycle operation reconciles all active
  work and fills to a positive controller limit; the built-in local adapter can
  bind deterministic static slots and renew their leases; status proves the
  resulting activity without exposing launch secrets.
- Complexity deliberately excluded: a second scheduler, resource-instance
  schema, distributed item semaphore, provider registry/recovery hook, dynamic
  discovery, watchdog or reattachment service, arbitrary launch rewriting,
  configurable external logs, retries, priorities, and multi-pool fairness.
- Validation and phase-shaping source: the planning document's `Examples And
  Validation` and `Phase Shaping` sections. Causal combinations are limited to
  claim/defer/FIFO stop, acquire/start/commit compensation, and
  reconcile/renew/terminal/refill.
- Implementation-base refresh: `origin/develop` at
  `a6bd1ef54523ac394b6a875c7486f9d8d7f68b95` has no changes from the original
  `main` evidence revision in the queue, resource-admission, coordination,
  queue CLI, or queue-test paths. Each phase must re-resolve `origin/develop`
  before creating its branch.
- Out of scope: all planning-document deferrals, downstream experiment
  semantics, accelerator-vendor code, new background services, and product code
  outside the selected phase.

## Shared Constraints

- Architecture and dependency direction: `loom.queue` may consume import-light
  public resource-admission and `WorkspaceCoordinationStore` contracts.
  Pipeline planning, coordination stores, and authority code must not import
  queue. CLI only constructs and renders queue services; it owns no scheduling
  or assignment policy. Core imports no downstream, accelerator, container, or
  cluster package.
- Shared public and durable contracts:
  - Dispatch has three canonical dispositions: started asynchronously,
    completed synchronously, and deferred before external work starts. Deferred
    work has no handle and carries a stable, non-secret reason code.
  - `QueueController.run_cycle(...)` is the new pool-scoped operation and returns
    one plain-data-serializable cycle record with reconciliation steps, dispatch
    steps, active count, capacity-blocked state, and the next required
    maintenance time. `run_once()` remains a one-step compatibility operation.
    The maintenance value is the earliest UTC Loom timestamp supplied by any
    current-session started result or active inspection; `None` means no owned
    active dispatch requires timed maintenance.
  - Schema-v1 queue config remains accepted. New settings use schema v2;
    `controller.max_active_items` is positive and defaults to one, while the
    positive per-cycle dispatch budget defaults to the active limit.
  - Assignment uses a structural queue-local provider and immutable request and
    discriminated decision records. A success separates provider-owned live
    state from a schema-tagged, allowlisted plain-data projection and launch
    bindings.
  - Every claim/reclaim receives a non-reusable identity across controller
    sessions, even when owner and dispatch attempt are unchanged. Runtime
    generation may be injected for deterministic tests but cannot be derived
    only from owner, attempt, a reset counter, or a timestamp.
  - Existing `QueueItem`, `LaunchContract.resources`, and queue DB schema v1
    remain unchanged unless a phase stops with concrete evidence that an index
    or guarded-transition field cannot be implemented safely without DDL.
    Assignment evidence is stored under `DispatchHandle.evidence`.
  - Pool status retains the existing service/item fields, adds filtered counts
    and safe active-attempt facts, and uses the existing CLI JSON envelope. Any
    incompatible envelope change advances that envelope to v2 rather than
    inventing a second status schema.
- Shared reproducibility, compatibility, and import constraints: FIFO order is
  `(enqueued_at, queue_item_id)`; deferral preserves both values and the current
  dispatch attempt. Fake, synchronous, custom, CPU-only, and delegated SLURM
  adapters keep existing behavior. New root exports must be intentional,
  typed, and cheap to import. No runtime dependency is added.
- Shared invariant ownership:
  - The repository owns atomic claims and guarded durable transitions.
  - The controller owns reconcile/fill ordering, budgets, FIFO stop, and active
    counting.
  - Coordination stores own failure classification and fenced lease mutation;
    admission and assignment preserve those categories.
  - The assignment provider owns only concrete assignment leases and bindings.
  - The local adapter owns scalar/assignment/process/log ordering, renewal, and
    compensation.
  - The status read model owns allowlisting and persisted-versus-live labels;
    CLI formatters only render it.
- Decisions no phase may reopen: `max_active_items` is not a distributed
  semaphore; queue never provisions authority limits; live-owner renewal does
  not imply crash-time safety; no provider-private recovery data becomes
  durable; v23 does not define v25 scheduler policy.

## Phase Index

| Phase | Slug | Status | Phase plan | Branch | PR | Ownership | Goal |
| --- | --- | --- | --- | --- | --- | --- | --- |
| 1 | `safe-pool-cycles` | in_progress | `docs/roadmap/stage-23/phases/safe-pool-cycles.md` | `agent/stage-23-p1-safe-pool-cycles` | pending | Queue controller/repository, typed coordination/admission, and scalar local-process safety | Atomically reconcile/fill one pool with deferral, scalar renewal, terminal-before-release, and post-start compensation. |
| 2 | `managed-local-assignments` | pending | `docs/roadmap/stage-23/phases/managed-local-assignments.md` | `agent/stage-23-p2-managed-local-assignments` | pending | Queue-local assignment/config/preflight and integration with the established local lifecycle | Exclusively bind and renew static slots, apply safe bindings, capture logs, and preserve Phase 1 compensation. |
| 3 | `operator-status-proof` | pending | `docs/roadmap/stage-23/phases/operator-status-proof.md` | `agent/stage-23-p3-operator-status-proof` | pending | Repository read model, status/CLI rendering, docs, examples, and end-to-end proof | Expose redacted pool summaries and prove twelve items over three generic slots. |

The phases are vertical rather than module-only. Phase 1 includes scalar lease
renewal, local termination-before-release, session ownership, and post-start
compensation so concurrent local work is never exposed without its base safety
contract. Phase 2 adds concrete assignment and logs to that lifecycle. Phase 3
adds the operator contract and public proof without scheduling in CLI.

## Quality Gate

- Planning gate: Stage 23 functionality and design were explicitly confirmed
  by the user on 2026-08-17 after one expanded design-safety review resolved all
  findings.
- Manager review: confirmation completed on 2026-08-17 after checking every
  independent finding against the corrected manifest and phase plans; mapping,
  dependencies, invariants, coverage, and base seams are coherent.
- Optional independent review: completed once on 2026-08-17; initial verdict
  was not ready because Phase 1 exposed concurrency before scalar renewal and
  compensation, and claim identity could be reused across controller sessions.
- Correction: applied once. Scalar renewal, safe local termination,
  session ownership, and post-start commit compensation moved into Phase 1;
  claim identities are non-reusable; workflow statuses/refiner wording and the
  Phase 3 read surface were narrowed. Provider and maintenance contracts were
  made explicit.
- Ready for implementation: yes; Phase 1 remains pending and must begin through
  the normal expanded phase workflow.
- Accepted risks: exact item-count enforcement does not span controllers;
  controller death and an unkillable process can outlive a lease; acquisition
  evidence is not refreshed durably on every renewal; static authored inventory
  can become stale operationally.
- Revisit triggers: a required cross-controller item quota; unattended process
  survival/reattachment; a demonstrated status or recovery consumer for richer
  durable assignment state; dynamic or multi-host inventory; measured SQLite
  query/CAS pressure; v25's reviewed cross-contract scheduling design.

## Completion

| Phase | PR and merge | Implementation and validation | Residual risk | Cleanup |
| --- | --- | --- | --- | --- |
| 1 | Pending; no PR opened | Implementation, 94-test phase matrix, `make validate-pr`, test summary, and fresh manager review pass at `2df89ce` | No known blocker; accepted controller-death, unkillable-process, controller-local-limit, and non-durable-renewal risks remain | Active worktree retained pending PR/merge |
| 2 | pending | pending | pending | pending |
| 3 | pending | pending | pending | pending |
