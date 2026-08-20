# Phase 1 Execution Plan: Real Interruption And Cancellation

## Metadata

- Status: in_progress
- Roadmap stage and phase: Stage 24, Phase 1
- Manifest: `docs/roadmap/stage-24/implementation-plan.md`
- Branch: `agent/stage-24-p1-real-interruption-and-cancellation`
- Worktree root and path: `/home/can134/work/active/loom-worktrees` and
  `/home/can134/work/active/loom-worktrees/stage-24-p1-real-interruption-and-cancellation`
- Base revision: `314e418192c3d46635b7f4754ea29ef736809f7d`, the current
  local `develop` revision when the phase worktree was created
- PR target: `develop`
- PR title: `Operational Lifecycle Validation - Phase 1: Real Interruption And Cancellation`
- Dependencies: completed Stage 23-post and the confirmed Stage 24 planning
  contract
- Workflow path: fast; refine only if a qualified process-cleanup or durable-
  cancellation blocker satisfies the repository blocker definition
- Blockers: PR submission is pending remote-base alignment. Local `develop` is
  one user-authored commit ahead of `origin/develop`, and that base commit also
  contains unrelated terminal-monitor work. Preserve it and do not push or open
  this phase PR until the remote base can be aligned without widening the PR.

## Objective And Context

- Vertical outcome: while Loom is alive, a cooperative stop, Ctrl-C, timeout,
  or managed-local cancellation leaves process liveness, CLI behavior, durable
  state, artifacts, downstream scheduling, and leases in agreement.
- Earlier dependency: Stage 23-post owns managed-local runtime recovery,
  shutdown, lease, and fake-process ordering. Existing runner, lifecycle,
  executor, CLI, reliability, and early-stop contracts own all other behavior.
- Later work explicitly out of scope: uncatchable coordinator loss, old-active
  recovery, service-authority loss, artifact corruption, public repair,
  reattachment, external runtimes, and Stage 25 candidate selection.

## Current Source And Harness

- Relevant files and symbols:
  - `src/loom/pipeline/execution/runner.py` catches `(Exception,
    KeyboardInterrupt)` in serial/prepared execution and currently records a
    failed stage/run. Its parallel path uses `ThreadPoolExecutor`, whose running
    in-process stages cannot be safely preempted.
  - `src/loom/pipeline/execution/lifecycle.py` already owns cancelled result and
    durable cancellation writers.
  - `src/loom/cli/main.py` and `src/loom/cli/errors.py` already map a propagated
    `KeyboardInterrupt` to exit 130.
  - `src/loom/pipeline/executors/subprocess.py` owns worker launch, enforced
    timeout, result handoff, and process metadata.
  - `src/loom/queue/managed_local.py` owns real process-group lifecycle and
    shutdown/cancel behavior for managed-local work.
- Existing tests and seams:
  - `tests.support.pipeline_execution_stages` already supplies
    `EarlyStopStage`, `KeyboardInterruptStage`, `SleepStage`, and a bounded
    coordinated stage. Extend these only when a PID/exit marker is materially
    needed.
  - Runner units already prove early-stop cancellation; the parallel
    interruption integration currently locks the incorrect failure outcome and
    must be changed with the production fix.
  - Subprocess integration already proves real success/failure against the
    local authority service; its timeout unit injects `TimeoutExpired`.
  - Managed-local runtime integration exhaustively proves ordering with fake
    process handles; the queue example proves a real success path.
- Import, dependency, or harness constraints: keep test support domain-neutral;
  do not add `psutil`, a signal helper package, production test hooks, or a new
  marker. Use the standard library, temporary paths, existing CLI/project
  factories, and default Linux POSIX behavior.

## Scope

In scope:

- Separate `KeyboardInterrupt` from ordinary exception handling. Serial and
  prepared-worker paths cancel an identifiable uncommitted active stage and the
  run, complete cleanup, block later work, and re-raise the original interrupt.
- In bounded parallel local execution, stop submitting work on coordinator or
  stage interruption, cancel the triggering stage when identifiable, settle
  other already-running stages truthfully, block unresolved work, cancel the
  run, and re-raise. Preserve any output that was validly committed by an
  already-running independent stage; never claim the thread was preempted.
- Preserve authored `StageContext.stop_early()` as a returned cancelled result
  and retain ordinary exception/failure behavior.
- Add real CLI `SIGINT` scenarios for serial local, subprocess, and bounded-
  parallel local execution. The parallel case uses a release barrier so active
  work settles deterministically and proves that no later stage starts.
- Ensure subprocess interruption terminates and observes the owned worker; add
  the smallest private executor/process-runner cleanup change if the real test
  demonstrates an orphan.
- Add one real enforced-timeout integration scenario using the production
  subprocess path, short configured timeout, long-running stage, and worker PID
  evidence.
- Add one real managed-local cancel scenario proving child exit before item
  cancellation and scalar/member lease release, with pending and foreign work
  protected.
- Add or consolidate private test helpers for monotonic condition polling,
  fixture-owned PID/process-group validation, liveness checks, and `finally`
  cleanup.
- Update execution/state/testing/queue documentation only where the implemented
  behavior or test command needs to be made authoritative.

Out of scope:

- Turning `SIGTERM` or every platform signal into graceful cancellation;
  Windows process-control parity; daemonization; reattachment; PID adoption;
  public cancellation APIs; new statuses, schemas, config fields, dependencies,
  or failure/reliability categories.
- Forcibly stopping Python worker threads or adding a public cooperative-
  cancellation token solely for parallel execution.
- Hard-kill recovery, live-owner expiry, authority process loss, corruption,
  retry redesign, external runtime acceptance, or rewriting deterministic fake
  process coverage.
- A full local/subprocess/Docker/Apptainer/SLURM by signal/timeout/cancel matrix.

Assumptions:

- Default CI runs on a POSIX-capable Linux environment. A platform guard may
  skip the real-signal cases elsewhere with a clear reason while all portable
  focused tests continue to run.
- Existing cancellation writers can represent keyboard interruption without a
  new durable field. If not, stop and request manager review rather than adding
  schema or public metadata ad hoc.
- A test may signal only the process or process group created by its own
  fixture; process identity is captured before any signal and cleanup is
  unconditional.

## Fixed Contracts And Private Discretion

- Observable behavior:
  - `stop_early()` returns run/stage `CANCELLED` through the established API.
  - A real serial Ctrl-C persists run/stage `CANCELLED`, records keyboard-interrupt
    reason evidence, publishes no active-stage output, starts no dependent
    stage, completes cleanup, re-raises, and makes a serial CLI exit 130.
  - Parallel Ctrl-C exits 130 after active stages settle; no later stage starts,
    the run cancels, and active stages retain their actual success/failure/
    cancellation and any corresponding valid commit.
  - A normal exception remains run/stage `FAILED` with failure metadata.
  - A real subprocess timeout remains run/stage `FAILED`, reports existing
    timeout facts, leaves the worker dead, and commits no output.
  - Managed-local cancel observes the owned process dead before terminal item
    state and resource release; queued and foreign work are not mutated.
- Public or durable shapes: none added. Reuse current status, cancellation
  detail/event/audit, reliability facts, queue item, process evidence, output
  index, and lease records. If a new shape appears necessary, stop.
- Trust and failure boundaries: runner decides lifecycle; executor/runtime owns
  process cleanup; authority owns state/leases; CLI owns exit mapping. A signal
  request is not proof of exit.
- Cross-phase contracts: Phase 2 may assume caught interrupts are no longer
  failures and that shared process fixtures can start, synchronize, inspect, and
  clean a test-owned process tree.
- Reproducibility and compatibility: existing success, ordinary failure,
  authored early stop, timeout-policy selection, queue fake-process cases,
  delegated pools, and public imports remain unchanged.
- Private choices the executor may simplify: helper/file names, whether signal
  e2e lives in a new lifecycle file, marker content, poll cadence, executor
  cleanup helper nesting, and how exact process liveness is checked on POSIX.

## Proportionality

- Existing seam reused: lifecycle cancellation writers; CLI exit mapping;
  subprocess timeout metadata; managed-local process-group termination;
  authority lease release; current dummy stages, project builders, and pytest
  markers.
- Material additions and current justification: one runner interrupt branch is
  required by a demonstrated contract mismatch; private real-process fixtures
  are required to cross the OS boundary; any subprocess cleanup adjustment is
  justified only if a child is observably left alive.
- Optional hardening and future capability deferred: broad signal handling,
  reusable production supervisor abstraction, child adoption, cross-platform
  process trees, cleanup retries, environmental runtime profiles, and more than
  one representative test per causally distinct execution owner.

## Invariant Ownership

| Invariant | Owner | Reachable invalid producer or boundary | Consequence | Coverage |
| --- | --- | --- | --- | --- |
| Caught keyboard interruption is cancellation, not failure. | Runner lifecycle | Current broad exception handlers. | Misleading state and wrong retry/diagnostic semantics. | Serial/prepared and stage-raised parallel focused tests. |
| CLI exits 130 only after durable cancellation/cleanup. | Runner then CLI | Signal arrives during executor wait. | Exit says interrupted while state says failed/running or child survives. | Local and subprocess real-signal e2e. |
| Parallel interruption never invents preemption. | Parallel scheduler | Signal reaches coordinator while worker threads run. | False cancelled state or lost valid commit. | Release-barrier signal test: settle active, block unscheduled, cancel run. |
| Success/output commit never follows cancellation or timeout. | Runner commit boundary | Late worker result or broad exception normalization. | False reusable artifact. | Output/index/downstream assertions in both paths. |
| Subprocess timeout/interrupt leaves no worker alive. | Subprocess executor/process runner | OS child process. | Orphaned computation and later output writes. | PID marker plus bounded non-liveness assertion. |
| Managed item cancellation/resource release follows observed exit. | Managed-local runtime/adapter | Real child/process group. | Resource reuse while work is still active. | Real cancel with item, scalar/member lease, and process assertions. |
| Test cleanup cannot signal unrelated processes. | Test fixture | Reused or unvalidated PID. | Host/CI damage. | Fixture ownership validation and unconditional `finally`. |

## Implementation Slices

1. Replace broad keyboard-interrupt failure normalization with serial/prepared
   cancellation and parallel stop-and-settle flows. Update the incorrect
   focused expectation and retain ordinary exception/early-stop behavior.
2. Add the smallest test-private bounded wait and process ownership/liveness
   support, plus any minimal marker/PID behavior needed in existing dummy stages.
3. Add serial local, subprocess, and bounded-parallel CLI Ctrl-C workflows; if
   the subprocess worker survives, fix cleanup privately and prove exit.
4. Add real production-path subprocess timeout coverage and verify reliability,
   logs, output/index absence, and worker non-liveness.
5. Add the real managed-local cancellation workflow, update affected feature
   docs, then run targeted and repository validation.

## Test And Validation Plan

| Suite | Required or deferred | Behavior or risk | Minimal assertions or reason |
| --- | --- | --- | --- |
| Package | required if imports change; otherwise existing gate | No accidental public lifecycle/process helper. | Public imports unchanged and cheap. |
| Unit | required | Runner interrupt branch; early-stop and ordinary failure compatibility; helper safety where useful. | Cancel writes/propagation and cleanup ordering without duplicating integration. |
| Contract | existing gate | No executor/status public contract change planned. | Existing executor/store contracts pass; add only if an existing contract was wrong. |
| Integration | required | Parallel stage interrupt, real subprocess timeout, and managed-local cancel. | Truthful in-flight results; actual child exit; status/reason, logs, output/index, item/lease ordering. |
| E2E / opt-in | required default POSIX e2e | Serial local, subprocess, and bounded-parallel CLI `SIGINT`. | Exit 130, durable cancellation, parallel settlement, downstream stop, no orphan. External runtimes deferred. |

Targeted commands:

    uv run pytest tests/unit/loom/pipeline/execution/test_runner.py
    uv run pytest tests/integration/pipeline/test_parallel_execution.py
    uv run pytest tests/integration/pipeline/test_subprocess_executor_integration.py
    uv run pytest tests/integration/queue/test_managed_local_runtime.py
    uv run pytest tests/e2e/test_execution_lifecycle.py

If the e2e filename differs, run the implemented lifecycle test path explicitly.

Final commands:

    make validate-pr
    make test-summary

## Risks, Review, And Stops

- Main risks: swallowing the interrupt; relabelling an in-flight parallel
  success; releasing resources before process exit; signalling the wrong PID;
  flaky timing; late worker output; changing early stop; broadening durable
  shapes.
- Review focus: status/reason/exit agreement, both broad runner catch sites,
  parallel cleanup, subprocess worker liveness, process ownership validation,
  managed item/lease ordering, downstream/output absence, and absence of fixed-
  sleep assertions.
- Stop if: existing durable cancellation has no safe reason/evidence surface; a
  new schema/public record is required; subprocess cleanup cannot be owned
  without a new process abstraction; a real test cannot identify its exact
  child safely; or correct behavior conflicts with an accepted executor API.
- Accepted debt and revisit trigger: POSIX-only signal proof, no broad `SIGTERM`
  policy, and no preemptive/cooperative parallel stage cancellation. Revisit
  when a supported platform, supervisor signal, or cancellation consumer makes
  one current.

## Executor Handoff

- Read section range: this document in full, then planning `FR-1` through
  `FR-5`, `FR-10`, `FR-11`, and the behavior baseline.
- Safe implementation slices: the five slices above in order; do not begin
  crash recovery or artifact work.
- Decisions not to revisit: Ctrl-C cancels/re-raises; parallel in-flight work
  settles truthfully; timeout fails; exit precedes release; no public shape,
  Cartesian matrix, or fixed-sleep oracle.
- Conditions requiring manager action: any stop condition, unavoidable durable
  migration, need for an external dependency/service, or a discovered supported
  path whose accepted status semantics differ materially.

## Workflow State

- Manager preparation: complete on 2026-08-20 from the recorded local base;
  remote-base alignment remains a pre-submit condition
- Expanded planning: not needed; current contracts and demonstrated mismatch
  make the lean path sufficient
- Implementation: complete locally; awaiting manager pre-submit work after the
  remote-base blocker is resolved
- Refiner: not needed unless the executor returns a qualified blocker
- Pre-submit gate: pending
- Independent review: not needed on current fast path; reconsider only for a
  material residual process-safety risk
- Blocker corrections: 0/3
- PR and merge: pending

## Completion Record

| Item | Result |
| --- | --- |
| Implementation and changed paths | Separated `KeyboardInterrupt` from ordinary runner failures in serial, prepared-worker, and bounded-parallel flows; durable stage/run cancellation now precedes re-raise, parallel stops submissions while settling active results, and cancelled stages release their authority lease. Added private marker/PID/release test stages. Changed `src/loom/pipeline/execution/runner.py`, `src/loom/pipeline/execution/authority_adapter.py`, `tests/support/pipeline_execution_stages.py`, `tests/integration/pipeline/test_parallel_execution.py`, `tests/integration/pipeline/test_subprocess_executor_integration.py`, `tests/integration/queue/test_managed_local_runtime.py`, and `tests/e2e/test_execution_lifecycle.py`. |
| Tests added or updated | Updated the stage-raised parallel interrupt regression. Added real subprocess timeout/worker-exit coverage, real managed-local cancel/process-exit/lease coverage, and POSIX CLI SIGINT coverage for local, subprocess, and bounded-parallel execution. |
| Validated revision/tree state and evidence | Prepared revision `fb8e9a2`; implementation tree validated before this completion-record-only update. Targeted suites passed: runner (29), parallel (10), subprocess (5), managed-local (14), lifecycle e2e (3). `make validate-pr` passed (Ruff, Pyright, default/config tests, build). `make test-summary` passed: 2,277 passed, 3 skipped, 2,254 deselected; receipt `build/test-summary.md`. |
| Validation-relevant changes after evidence | None; only this completion record was added after the successful validation receipt. |
| PR, review, and merge | pending |
| Residual risk and cleanup | POSIX signal/process-group evidence is intentionally Linux-oriented; no broader signal policy, Python-thread preemption, reattachment, or crash recovery was added. The prepared remote-base blocker remains: do not push or open a PR until the manager can align `develop` without the unrelated user-authored commit. |
