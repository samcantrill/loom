# Phase 10 Execution Plan: Global Scheduler And Assignment Concurrency

## Metadata

- Status: pending
- Roadmap stage and phase: Stage 29, Phase 10
- Manifest: `docs/roadmap/stage-29/implementation-plan.md`
- Branch: `agent/stage-29-p10-global-scheduler-assignment-concurrency`
- Worktree root and path: `/home/can134/work/active/loom-worktrees`; phase path is `<root>/stage-29-p10-global-scheduler-assignment-concurrency`
- Base revision: current `origin/develop` when the worktree is created
- PR target: `develop`
- PR title: `feat(scheduling): run the global assignment scheduler`
- Dependencies: merged Phase 9F baseline `a6cd482` and current `develop`
- Workflow path: fast; approved contracts are explicit despite durable/concurrency scope
- Blockers: none

## Objective And Context

- Vertical outcome: one coordinator cycle projects every nonterminal admission,
  reads one globally ordered ready-work window, selects/reserves one safe work and
  candidate pair, starts it without waiting for completion, and repeats while
  capacity remains. Independent stages from the same or different runs may be
  simultaneously active.
- Earlier dependency: preserve the merged scheduling kernel, assignment CAS,
  authority fences, agent journal/provider truth, remote delivery, SLURM submit,
  cancellation, restart, and guarded-recovery behavior.
- Later work explicitly out of scope: execution-profile compatibility and worker
  environment/provider composition are Phase 11; bounded public status/polls,
  time recovery, root initialization, and deployment are Phase 12.

## Current Source And Harness

- Relevant files and symbols: `LocalDaemon.reconcile_once`,
  `LocalDaemon._assignment_futures`, `LocalDaemonExecution.advance`,
  `LocalDaemonExecution._remote_run_in_flight`, `RunOrchestrator`,
  `StageWorkRecord`, `SQLiteStageWorkStore`, `SchedulingKernel`, coordinator
  reservation operations in `loom.queue._managed_local`, and explicit SLURM
  assignment stores.
- Existing tests and seams: scheduling kernel safe bypass and limits; stage-work
  store parity; atomic `max_parallel_stages`; local/remote/SLURM production paths;
  restart/cancellation/unknown recovery suites under unit and integration queue
  tests.
- Import, dependency, or harness constraints: `loom.pipeline.orchestration` owns
  readiness projection and stage-work persistence; `loom.scheduling` stays pure
  and imports no queue/pipeline runtime; queue application code owns admissions,
  ordering policy resolution, candidate collection, reservation, launch, and
  reconciliation.

## Scope

In scope:

- Add a protected-policy-resolved, range-checked integer run priority and a
  coordinator-allocated durable monotonic enqueue sequence to each admission.
- Carry those admission values into schedulable work without changing the
  immutable semantic stage-work identity. Bump the fresh-only daemon and
  stage-work schemas; reject previous roots/stores.
- Give `SQLiteStageWorkStore` a real ordered ready-window query bounded at 256,
  ordered by priority descending, enqueue sequence, ready time, topological
  order, stage name, attempt, and stable work identity. Keep total pipeline size
  unbounded by this scheduler window.
- Replace per-admission scheduling with a coordinator-wide cycle: first project
  and reconcile all active admissions, then reconcile nonterminal assignments,
  then select/reserve/start globally while capacity permits.
- Key background work by `assignment_id`, not admission. Return from launch after
  durable local supervisor acceptance, remote targeting, or durable SLURM submit
  acceptance/unknown barrier; observe/finalize separately.
- Remove the run-wide remote-in-flight guard. Preserve the atomic reservation
  transaction as final enforcement of `max_parallel_stages` across local,
  remote, and SLURM assignments.
- Store reconciliation failure health per admission so one admission success
  cannot clear another admission failure. Shared owner/store failure may still
  degrade the service globally; public shaping is Phase 12.

Out of scope:

- Pipeline-size admission limits, fair-share, preemption, batching, gang work,
  speculative dispatch, automatic route fallback, or migration of an old root.
- Changes to scheduling-kernel complete-search correctness or to authority and
  provider ownership.
- General module splitting unrelated to the new cycle/assignment owner seams.

Assumptions:

- Authored configs are trusted, but client payloads do not grant priority. A
  protected site policy resolves priority before the admission transaction.
- A local supervisor `STARTED` receipt is durable launch acceptance; stage result
  completion remains an independently reconciled fact.

## Fixed Contracts And Private Discretion

- Observable behavior: higher-priority work wins globally; equal-priority FIFO
  is stable across restart; exhausted/infeasible early work may be bypassed;
  stage 257 eventually enters the window; two dependency-independent stages in
  one run overlap when the run limit and capacity allow.
- Public or durable shapes: `LocalDaemonAdmission` exposes priority and enqueue
  sequence; stage-work durable rows contain indexed scheduling order fields; all
  touched schemas hard-cut to new exact versions.
- Trust and failure boundaries: priority is protected-policy output; readiness
  comes only from per-run authority; reservation remains the concurrency CAS;
  launch/result uncertainty retains ownership and is never retried as a new
  assignment.
- Cross-phase contracts: Phase 11 may add execution identity to the same work and
  candidate/target shapes but must not restore per-run scheduling. Phase 12
  queries per-admission health and nonterminal assignments without invoking a
  full status join.
- Reproducibility and compatibility: enqueue sequence is a durable integer, not
  a timestamp. No migration, fallback field default, or old-schema reader.
- Private choices the executor may simplify: exact private helper/class layout,
  executor-pool mechanics, batch size below the fixed 256 maximum, and whether
  local completion observation uses futures or the supervisor query path, so
  long as assignment identity and durability remain authoritative.

## Proportionality

- Existing seam reused: `WorkItem.order_key`, `SchedulingKernel`,
  `RunOrchestrator`, the coordinator reservation CAS, and target-specific
  lifecycle owners.
- Material additions and current justification: indexed ready-window fields,
  durable enqueue allocation, a coordinator-wide cycle, assignment task tracking,
  and per-admission health are required by reachable starvation/concurrency/error
  failures in the current production path.
- Optional hardening and future capability deferred: fairness, arbitrary window
  tuning APIs, multi-coordinator HA, and a generic task queue.

## Invariant Ownership

| Invariant | Owner | Reachable invalid producer or boundary | Consequence | Coverage |
| --- | --- | --- | --- | --- |
| Priority/enqueue order is durable and globally deterministic | coordinator admission store | protected policy and concurrent/restarted admission | wrong global order or FIFO drift | cross-run priority and restart FIFO tests |
| Ready window is ordered and bounded, not a pipeline-size rejection | stage-work store | more than 256 ready/persisted stages | permanent reconciliation wait | 257-stage progress and exact order tests |
| One background task names one assignment | daemon assignment runner | local stage blocks admission future or remote run guard | lost same-run concurrency | local and remote overlap tests |
| Per-run active work never exceeds its limit | coordinator reservation CAS | racing scheduler cycles | resource over-admission | parallel reservation race test |
| One admission cannot erase another failure | coordinator reconciliation-health store | later successful reconciliation | false healthy service/admission | two-admission failure isolation test |

## Implementation Slices

1. Hard-cut admission/stage-work schemas; add protected priority resolution,
   durable enqueue allocation, indexed scheduling columns, and ordered window.
2. Separate all-admission projection/reconciliation from global placement and
   adapt work items to exact admission order fields.
3. Introduce assignment-keyed start/observe/finalize orchestration for local,
   remote, and SLURM targets; remove the run-wide remote guard.
4. Add durable per-admission reconciliation health and preserve shared failure
   classification.
5. Add causal concurrency/window/restart/failure tests and update contract docs.

## Test And Validation Plan

| Suite | Required or deferred | Behavior or risk | Minimal assertions or reason |
| --- | --- | --- | --- |
| Package | required | intentional public imports remain cheap | import boundary unchanged or explicitly updated |
| Unit | required | order/window/schema/health/task identity | exact ordering, 256 bound, old-schema rejection, isolated health |
| Contract | required | admission/stage-work serialization and atomic run limit | exact new fields and no over-reservation under race |
| Integration | required | local/remote overlap and large DAG progress | simultaneous independent assignments and stage 257 starts |
| E2E / opt-in | required where existing harness supports it | daemon restart FIFO and production path | same order after reopen without external services |

Targeted commands:

    pytest -q tests/unit/loom/scheduling/test_kernel.py tests/unit/loom/queue/test_managed_local.py tests/unit/loom/queue/test_local_daemon.py
    pytest -q tests/integration/queue/test_managed_local_controller.py tests/integration/queue/test_local_daemon_production.py tests/integration/queue/test_agent_session_transport.py tests/integration/queue/test_slurm_ready_stage.py

Final commands:

    make validate-pr
    make test-summary

## Risks, Review, And Stops

- Main risks: accidentally creating two readiness owners, treating launch as
  completion, releasing capacity after ambiguous launch, or weakening the
  reservation CAS while extracting the global loop.
- Review focus: durable ordering across restart, every supported target's
  start/observe boundary, and same-run concurrency without double launch.
- Stop if: required global behavior needs changing authority lifecycle truth,
  safe local launch cannot return before stage completion without a new durable
  supervisor fact, or the implementation needs compatibility/migration.
- Accepted debt and revisit trigger: 256 is a fixed deployment bound; tune only
  after measured scheduling latency/throughput evidence.

## Executor Handoff

- Read section range: this complete phase plan, especially Scope through Risks.
- Safe implementation slices: the five numbered slices in order.
- Decisions not to revisit: one global order; durable integer enqueue sequence;
  256 is a ready window; assignment is the background unit; no remote run guard;
  no old-root compatibility.
- Conditions requiring manager action: any product/public choice beyond the
  fixed admission fields, inability to preserve target lifecycle safety, or a
  qualified blocker meeting AGENTS.md criteria.

## Workflow State

- Manager preparation: planning draft complete; exact base/worktree pending setup
- Expanded planning: not needed; correction contracts are maintainer-supplied
- Implementation: pending
- Refiner: not needed
- Pre-submit gate: pending
- Independent review: not needed unless a material residual risk remains
- Blocker corrections: 0/3
- PR and merge: pending

## Completion Record

| Item | Result |
| --- | --- |
| Implementation and changed paths | pending |
| Tests added or updated | pending |
| Validated revision/tree state and evidence | pending |
| Validation-relevant changes after evidence | none |
| PR, review, and merge | pending |
| Residual risk and cleanup | pending |
