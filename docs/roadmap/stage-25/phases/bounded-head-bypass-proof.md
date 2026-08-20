# Phase 2 Execution Plan: Bounded Head-Bypass Proof

## Metadata

- Status: pending
- Roadmap stage and phase: v25 Phase 2
- Manifest: `docs/roadmap/stage-25/implementation-plan.md`
- Branch: `agent/stage-25-p2-bounded-head-bypass-proof`
- Worktree root and path:
  `/home/can134/work/active/loom-worktrees/stage-25-p2-bounded-head-bypass-proof`
- Base revision: current `origin/develop` after Phase 1 merges; record the exact
  revision before branch creation
- PR target: `develop`
- PR title: `Whole-Run Queue Selection - Phase 2: Bounded Head-Bypass Proof`
- Dependencies: Stage 25 Phase 1 remotely merged with its selection protocol,
  exact claim, default branch, and advisory-capacity contracts unchanged
- Workflow path: expanded because it composes typed deferral, repeated policy
  invocation, controller bounds, audit evidence, and concurrency e2e behavior
- Blockers: Phase 1 must merge before selection

## Objective And Context

- Vertical outcome: after a chosen item unexpectedly defers, the same cycle may
  omit it, ask again, and start another candidate within one hard bound. A
  downstream first-fit example proves the journey without changing defaults.
- Earlier dependency: Phase 1 supplies immutable policy inputs/results,
  managed-pool injection, advisory availability, exact claim/requeue safety,
  selected-claim audit, and the unchanged FIFO branch.
- Later work excludes built-in first-fit, fairness, durable history, priorities,
  reservations, discovery, and broader scheduling.

## Current Source And Harness

- Relevant files and symbols after Phase 1: selection contracts and controller
  injection; Stage 23 `QueueController.run_cycle`, deferred disposition,
  guarded requeue, cycle result, managed-local admission/assignment; queue audit
  and safe status evidence. Refresh exact names from merged code.
- Harnesses include Phase 1 policy/claim tests, Stage 23 cycle integration,
  fake process/clock/coordination seams, queue status contracts, and operations
  example conventions.
- Import constraints: the example defines its policy through public Python
  types; CLI/config gain no loader; default tests need no external system.

## Scope

In scope:

- A private attempted-ID set owned by one `run_cycle` invocation. The controller
  excludes attempted IDs before constructing each fresh policy context; policy
  never receives the set or previous decisions.
- Policy re-entry after a Stage 23 `DEFERRED` result only. The repository first
  completes Stage 23's guarded deferral and the adapter has proven no process
  started and partial resources were released.
- Use the manifest's one-counter rule: initialize `selection_steps_remaining`
  from the private positive `selection_limit`; each fresh bounded read plus at
  most one policy call spends one step. Claim-race or deferral refresh spends a
  new step. Each read returns at most `selection_limit` candidates; policy
  inspection spends no extra units. There are no separate selection counters.
- Stop conditions for empty filtered candidates, policy `stopped`, invalid
  output, policy exception, exhausted selection bound, Stage 23 active/dispatch
  budget, authority degradation, repository error, or no queued item.
- Allowlisted cycle evidence for policy stop/error and bound exhaustion. Policy
  exceptions use only `queue_selection.policy_error`; invalid output uses
  `queue_selection.invalid_decision`; exhaustion uses
  `queue_selection.selection_limit_exhausted`. No exception type/text, message,
  candidate dump, capacity snapshot, or policy-private state persists.
- A dependency-free operations example whose local `FirstFitPolicy` selects the
  oldest candidate whose logical request fits advisory availability.
- Documentation of default/custom behavior, advisory capacity, atomic claim,
  starvation risk, delegated boundary, and Python construction.
- Causal integration/e2e coverage for head bypass, stale observation,
  continuation, and bounded calls using SQLite plus short local processes.

Out of scope:

- Phase 1 public-record changes, another cycle type, DDL, skip audit, raw
  exceptions, policy config, core non-FIFO behavior, durable counters,
  pagination, retry, fairness, preemption, or delegated changes.

Assumptions:

- A candidate enters the attempted set after a successful exact claim, even if
  dispatch defers. A lost claim spends one step but adds no attempted ID.

## Fixed Contracts And Private Discretion

- Observable behavior: FIFO without injection still stops on its first capacity
  deferral. With injection, a deferred chosen candidate stays queued with order
  and attempt unchanged while the controller may select a different candidate.
  No ID is claimed twice in one cycle.
- Public or durable shapes: Phase 1 protocol/types do not change. Stage 23 cycle
  serialization gains only the narrow safe stop/error facts needed by planning
  `FR-9`, fitted into its existing convention and bounded safe-code grammar.
  Claim audit remains the only durable successful-selection fact.
- Trust and failure boundaries: only typed pre-start capacity deferral permits
  continuation. Invalid request, authority uncertainty, fencing loss, process
  start, or repository failures retain Stage 23 terminal/fail-closed behavior.
- Cross-phase contracts: this is the final Stage 25 phase. It must leave the
  queue-local seam adaptable but must not implement generic scheduler vocabulary.
- Reproducibility and compatibility: the example policy is deterministic over
  the supplied order and logical amounts. It is demonstrative downstream code,
  not a root export or default. Existing config, CLI, FIFO, SLURM, and queue
  records remain compatible.
- Private choices: attempted-set representation, positive bound value, loop
  arrangement, example command, evidence placement, and synchronization.

## Proportionality

- Existing seam reused: Stage 23 deferral/compensation and cycle budgets, Phase
  1 exact claims and policy context, queue audit, existing example harness.
- Material additions: private filtering prevents reclaim loops; repeated
  invocation handles stale/concrete capacity; one example proves the consumer.
- Optional hardening and future capability deferred: history exposed to policy,
  skip metrics, scheduling estimates, reservations, aging, pagination, and
  generic scheduler adapters.

## Invariant Ownership

| Invariant | Owner | Reachable invalid producer or boundary | Consequence | Coverage |
| --- | --- | --- | --- | --- |
| A deferred ID is not selected again in the same cycle. | Controller filtering | Requeued FIFO head reappears immediately. | Busy loop/audit churn. | Fake policy and real repository exact call counts. |
| Continuation follows only safe pre-start deferral. | Controller disposition handling | Failure/uncertainty is treated as spare capacity. | Unsafe retry or hidden failure. | Typed outcome matrix. |
| All selection work is bounded without weakening Stage 23 budgets. | Controller | Repeated stop/race/defer refresh. | Unbounded cycle or starvation of reconciliation. | Bound exhaustion at each reachable edge. |
| Evidence contains safe reasons only. | Controller/repository evidence builders | Policy exception or context is serialized raw. | Data disclosure/coupling. | Exact-key/value negative tests. |
| Head bypass cannot over-allocate logical or concrete resources. | Authority/provider acquisition | Advisory view races or static slot is occupied. | Concurrent resource use. | Real SQLite coordination plus stale observation. |

## Implementation Slices

1. Add private attempted filtering and single-bound accounting around the Phase
   1 custom-selection path while leaving FIFO and Stage 23 budgets untouched.
2. Compose repeated selection only after completed guarded capacity deferral;
   add all stop/error and typed-failure tests.
3. Add allowlisted cycle evidence and contract/redaction coverage without a new
   selection serialization layer.
4. Add the local first-fit example, feature docs, and deterministic causal
   integration/e2e scenarios.

## Test And Validation Plan

| Suite | Required or deferred | Behavior or risk | Minimal assertions or reason |
| --- | --- | --- | --- |
| Package | required | Phase 1 exports remain unchanged and cheap. | Example imports public facade; no new root policy implementation. |
| Unit | required | Filtering, continuation, one-counter accounting, stop/error, and FIFO split. | Deferred ID absent; one read/call pair per step; fixed reason codes; FIFO never continues. |
| Contract | required | Cycle and audit allowlists plus protocol stability. | No selection codec; no message/context leak; Phase 1 fields unchanged. |
| Integration | required | Real queue/coordination head bypass and races. | B-two/A-one; stale acquisition; unique claims/slots; terminal release/refill. |
| E2E / opt-in | dependency-free local e2e required; hardware/manual remains deferred | Public Python composition and observable completion order. | Local first-fit example runs without network/vendor tools; no default hardware profile. |

Targeted commands:

    uv run pytest tests/unit/loom/queue/test_controller.py tests/unit/loom/queue/test_scheduler.py
    uv run pytest tests/contracts/test_queue_python_api_contract.py tests/contracts/test_queue_repository_contract.py
    uv run pytest tests/integration/queue/test_sqlite_repository.py tests/integration/queue/test_managed_local_controller.py
    uv run python -m tools.test_harness run e2e

Final commands:

    make validate-pr
    make test-summary

## Risks, Review, And Stops

- Main risks: attempted-item reuse, continuation after non-capacity failure,
  bypassed Stage 23 limits, evidence leaks, or timing-based e2e tests.
- Review focus: exact disposition gate, deferral commit before reselection,
  private filtering, one bound, unchanged public protocol, redaction, and
  deterministic process/coordination synchronization.
- Stop if: Stage 23 cannot prove compensation before returning deferred; cycle
  evidence needs a parallel result schema; deterministic e2e requires sleeps;
  or head bypass needs durable history/fairness semantics. Return to manager.
- Accepted debt and revisit trigger: custom first-fit can starve large work and
  bounded lookahead can miss a fit; revisit only with demonstrated operator need
  for durable fairness or larger indexed candidate search.

## Executor Handoff

- Read section range: this plan plus planning `FR-5`, `FR-8` through `FR-11`,
  `FQ-3`, `FQ-5`, `FQ-6`, and `DQ-3` through `DQ-6`.
- Safe implementation slices: execute slices 1-4 with separate controller,
  evidence, and example/docs/test checkpoints.
- Decisions not to revisit: private attempted state, one selection bound,
  capacity-only continuation, no public-shape change, no built-in policy,
  fairness, config, registry, DDL, or generic scheduling.
- Conditions requiring manager action: any stop condition, Phase 1 contract
  drift, need for policy history, or inability to prove compensation before
  reselection.

## Workflow State

- Manager preparation: complete in Stage 25 planning; refresh after Phase 1 merge
- Expanded planning: required at phase selection for deferral/concurrency and
  public-evidence integration; unused
- Implementation: not started
- Refiner: optional only for a qualified implementation/test blocker; unused
- Pre-submit gate: not run
- Independent review: required after implementation; unused
- Blocker corrections: 0/3
- PR and merge: pending

## Completion Record

| Item | Result |
| --- | --- |
| Implementation and changed paths | pending |
| Tests added or updated | pending |
| Validated revision/tree state and evidence | pending |
| Validation-relevant changes after evidence | none recorded |
| PR, review, and merge | pending |
| Residual risk and cleanup | pending |
