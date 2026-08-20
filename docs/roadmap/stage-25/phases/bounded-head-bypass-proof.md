# Phase 2 Execution Plan: Bounded Head-Bypass Proof

## Metadata

- Status: pending
- Roadmap stage and phase: v25 Phase 2
- Manifest: `docs/roadmap/stage-25/implementation-plan.md`
- Branch: `agent/stage-25-p2-bounded-head-bypass-proof`
- Worktree root and path:
  `/home/can134/work/active/loom-worktrees/stage-25-p2-bounded-head-bypass-proof`
- Base revision: current `origin/develop` after Phase 1 merges; record exact
  revision before branch creation
- PR target: `develop`
- PR title: `Whole-Run Queue Selection - Phase 2: Bounded Head-Bypass Proof`
- Dependencies: Phase 1 merged with one eligibility/default/custom engine,
  exact local ownership, managed entrypoint parity, and advisory opportunity
  contracts unchanged
- Workflow path: expanded because typed deferral, repeated evaluation, bounds,
  evidence, and concurrency interact
- Blockers: Phase 1 merge only

## Objective And Context

- Vertical outcome: after a selected item unexpectedly defers before start, the
  current managed opportunity may omit it, recompute safe facts, and select
  another eligible item within one hard bound. A downstream custom-preference
  example proves extension without adding another scheduler.
- Earlier dependency: Phase 1 supplies immutable policy values, unified
  eligibility/default/custom evaluation, advisory local opportunity, exact
  local CAS, safe ownership evidence, and unchanged authority/provider safety.
- Later work: Stage 29 represents execution opportunities with agent offers and
  uses durable assignments plus the same selection engine. It may derive
  exclusions from coordinator-owned offer/assignment facts rather than this
  phase's local in-memory set.

## Current Source And Harness

- Relevant merged seams after Phase 1: selection evaluator, local opportunity
  construction, exact ownership service, `QueueController.run_cycle`, Stage 23
  deferred disposition/guarded requeue, cycle result, admission/provider,
  queue audit and safe status evidence.
- Harnesses include Phase 1 parity/claim tests, Stage 23 cycle integration,
  fake process/clock/coordination seams, status contracts, and operations
  example conventions.
- The example uses only public selection values. CLI/config gain no loader and
  default tests require no external service, hardware, or network.

## Scope

In scope:

- One private attempted-ID set per local managed scheduling opportunity. The
  controller excludes those IDs before each fresh evaluator call; policies
  never receive the set or prior decisions.
- Re-entry only after Stage 23 completes guarded `DEFERRED` compensation and
  proves no process/delegated work started, the item returned unchanged to
  `QUEUED`, and all partial admission/assignment ownership was released.
- One-counter accounting: initialize remaining steps from positive
  `selection_limit`; each bounded read plus eligibility/default/custom
  evaluation spends one. Stop, lost claim, or dispatch deferral consumes that
  step; refresh consumes another. Stage 23 active/dispatch bounds remain.
- Stop for no eligible candidates, policy `STOPPED`, invalid output, policy
  exception, exhausted selection bound, active/dispatch bound, degraded
  authority, repository error, or no queue work.
- Allowlisted cycle evidence for policy stop/error and limit exhaustion using
  fixed codes. Never persist raw exception text/type, candidates, opportunity
  capacity, policy state, or topology facts.
- A dependency-free example policy that deliberately prefers the smallest
  eligible logical request, demonstrating custom ordering beyond the default
  oldest-eligible behavior.
- Documentation of eligibility, default/custom ordering, advisory capacity,
  exact local ownership, starvation risk, Stage 29 handoff, delegated boundary,
  and Python construction.
- Causal SQLite/coordination/local-process tests for default bypass, custom
  ordering, stale observation, compensated continuation, races, and bounds.

Out of scope:

- Phase 1 public shape changes; assignment/offer/session/agent/client/HTTP
  records; durable attempted history; skip audit; policy config/discovery;
  fairness, reservation, priority, retry, pagination, preemption; delegated or
  Stage 29 implementation.

Assumptions:

- A candidate enters the local attempted set after successful exact ownership,
  even if dispatch then defers. A lost ownership race spends a step but adds no
  attempted ID.
- Stage 29 may supersede the local representation, but must preserve the
  observable rule: a declined/deferred candidate cannot be immediately
  reacquired from unchanged opportunity facts.

## Fixed Contracts And Private Discretion

- Observable behavior: oldest-eligible default and custom policies can continue
  only after safe capacity deferral. The deferred candidate remains queued with
  order and attempt unchanged; it is not selected twice in the same local
  opportunity.
- Public/durable shapes: Phase 1's five public types do not change. Stage 23
  cycle serialization gains only narrow safe stop/error facts; ownership audit
  remains the successful preference record in Stage 25.
- Trust boundary: only typed compensated pre-start capacity deferral permits
  continuation. Invalid request, authority uncertainty, fencing loss, process
  start, repository failure, or terminal outcomes do not become retries.
- Cross-stage: Stage 29 keeps evaluator behavior and evidence but moves managed
  ownership to `OFFERED`/`ACCEPTED` assignments. Selection never learns
  transport, agent, session, offer, journal, or slot facts.
- Reproducibility/compatibility: source order and eligibility are deterministic
  for supplied facts. Example policy is downstream code, not a root export or
  default. Existing config, records, delegated SLURM, and imports stay compatible.
- Private choices: attempted-set representation, loop arrangement, example
  command, evidence placement, synchronization, and exact positive limit.

## Proportionality

- Reuse Stage 23 compensation and budgets, Phase 1 evaluator/exact ownership,
  queue audit, and example harness.
- Private filtering prevents immediate loops; repeated shared evaluation handles
  stale capacity without exposing history.
- Defer durable history, offer/session modeling, skip metrics, estimates,
  reservations, aging, pagination, and generic scheduling.

## Invariant Ownership

| Invariant | Owner | Reachable invalid producer or boundary | Consequence | Coverage |
| --- | --- | --- | --- | --- |
| A deferred ID is not selected again from the same opportunity. | Controller filtering | guarded requeue makes it visible again | busy loop/audit churn | fake evaluator and real repository counts |
| Continuation follows only completed capacity compensation. | Controller disposition gate | failure/uncertainty treated as spare capacity | unsafe retry or hidden failure | typed outcome matrix |
| Every repeat uses the same selection engine. | Controller/evaluator composition | fallback direct claim after deferral | branch drift | call-path and parity assertions |
| All selection work is bounded independently of Stage 23 limits. | Controller | stop/race/defer refresh | unbounded cycle | exhaustion at reachable edges |
| Evidence contains safe reasons only. | Evidence builder | policy exception/context leak | disclosure/coupling | exact allowlist negatives |
| Bypass cannot over-allocate resources. | Authority/provider | stale advisory opportunity | concurrent use | real SQLite coordination race |

## Implementation Slices

1. Add private opportunity-attempt filtering and single-bound accounting around
   the shared Phase 1 evaluator, leaving active/dispatch budgets untouched.
2. Continue only after completed guarded capacity compensation; add all typed
   stop/failure/race tests.
3. Add allowlisted cycle evidence and redaction/contract coverage without a
   selection serialization layer.
4. Add custom smallest-eligible example, feature/design docs, and deterministic
   integration/E2E scenarios including Stage 29 handoff wording.

## Test And Validation Plan

| Suite | Required or deferred | Behavior or risk | Minimal assertions or reason |
| --- | --- | --- | --- |
| Package | required | Phase 1 exports unchanged and cheap. | Example imports public facade; no default policy/agent/route export. |
| Unit | required | Filtering, continuation, one-counter accounting, evidence, shared evaluator. | Deferred ID absent; one evaluation per step; fixed codes; no direct-claim fallback. |
| Contract | required | Cycle/ownership allowlists and protocol stability. | No codec/context/error leak; Phase 1 fields unchanged. |
| Integration | required | Real queue/coordination bypass and races. | B-two/A-one; stale admission; unique ownership/slots; terminal release/refill. |
| E2E / opt-in | dependency-free local required; hardware/network deferred | Public Python composition and completion order. | Local example runs without sleeps/network/vendor tools. |

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
  hidden direct scheduling branch, bypassed bounds, evidence leak, or timing-
  based tests.
- Review focus: exact disposition gate, compensation before reselection, shared
  evaluator invocation, private filtering, one bound, unchanged public API,
  redaction, and deterministic synchronization.
- Stop if Stage 23 cannot prove compensation, cycle evidence needs a parallel
  schema, deterministic E2E requires sleeps, or correct continuation requires
  durable history/fairness or Stage 29 records.
- Accepted debt: eligible FIFO/custom preference can starve large work and the
  bounded window can miss a fit. Revisit with demonstrated operator need.

## Executor Handoff

- Read this plan plus planning `FR-1`, `FR-5`, `FR-8` through `FR-12`, `FQ-1`,
  `FQ-5`, `FQ-6`, and `DQ-1`, `DQ-3` through `DQ-6`.
- Execute slices 1-4 with controller, evidence, example/docs, and causal-test
  checkpoints.
- Do not revisit one engine, oldest-eligible default, private attempt state,
  one bound, capacity-only continuation, public shapes, no durable history,
  no policy loader, and Stage 29 assignment ownership.
- Return for any stop condition, Phase 1 drift, need for policy-visible history,
  or inability to prove compensation before reselection.

## Workflow State

- Manager preparation: complete; refresh after Phase 1 merge
- Expanded planning: revised design approved; no additional spawned pass
- Implementation: not started
- Refiner: optional only for a qualified blocker; unused
- Pre-submit gate: not run
- Independent review: required after implementation due continuation risk
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
