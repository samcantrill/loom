# Phase 7 Execution Plan: Runner Lifecycle Decomposition

## Metadata

- Status: `pr_open`; serial human merge gate active and awaiting human review
  and human merge into `develop`
- Branch: `codex/v0-post-runner-lifecycle`
- Worktree: `/home/samcantrill/work/loom-worktrees/v0-post-runner-lifecycle`
- Phase execution plan path: `docs/phases/v0-post-runner-lifecycle.md`
- Full plan: `docs/implementation-plans/implementation-plan-v0-post.md`
- Source phase: `Phase 7 - Runner Lifecycle Decomposition`
- PR: [#21](https://github.com/samcantrill/loom/pull/21)
- Stack predecessor: none
- Base branch: `develop` at `8741c73a6b0b2dd2f94213fbb143fe7400bd9257`
- Target branch: `develop`
- Serial human merge gate: active. The Phase 7 implementation PR must target
  `develop`, request review from `samcantrill` when GitHub allows it, and
  mention `@samcantrill` in the PR body or an immediate fallback PR comment.
  Codex must not approve or merge the PR. No successor phase may start until
  the Phase 7 PR is human-merged into `develop` and verified as `MERGED`.
- Merge eligibility: root serial phase. The PR is merge-eligible only after
  human review and human merge into `develop`; there is no stack predecessor
  to retarget from.
- Successor dependency notes: Phase 8 must not start while Phase 7 is only
  `pr_open` or `approved`; Phase 8 may start only after the Phase 7 PR is
  verified as `MERGED` into `develop` and this implementation plan records
  Phase 7 as `merged`.
- Plan quality gate: passed in
  `docs/implementation-plans/implementation-plan-v0-post.md`; no blocking
  plan-review findings remain.
- Plan quality gate loop budget: initial plan review used, automated plan
  refinement pass used, confirmation review used. Do not consume another
  plan-quality review loop without explicit manager instruction.
- Draft pass: completed by `loom_phase_planner` in commit `0096ffe`.
- Refine pass: completed by `loom_phase_planner` in this planning pass. This
  document is decision-complete for executor handoff.
- Phase implementation refinement budget: used by this bounded refinement pass.
- PR review budget: unused.
- PR verification: `gh pr view 21 --json
  baseRefName,headRefName,state,url,mergedAt,statusCheckRollup` returned
  `baseRefName=develop`, `headRefName=codex/v0-post-runner-lifecycle`,
  `state=OPEN`, `mergedAt=null`, and CI `checks` completed with `SUCCESS`.
- Review request: `gh pr edit 21 --add-reviewer samcantrill` was attempted,
  but GitHub CLI/API rejected it with a GraphQL
  `repository.pullRequest.projectCards` deprecation error. Fallback comment
  mentioning `@samcantrill` was added immediately:
  https://github.com/samcantrill/loom/pull/21#issuecomment-4371996188.
- Setup limitations: local `develop` matched the manager-provided Phase 7 base
  commit `8741c73`. No remote synchronization was attempted during planning
  because the assignment provided the updated base. Creating the
  slash-namespaced branch and worktree required approved Git worktree
  permissions after the sandbox could not create the branch ref directory.
  Staging and committing in the worktree also required approved Git index
  permissions because the shared worktree metadata lives under the control
  checkout `.git/worktrees/` directory.
- Blockers: none.

## Objective

Preserve `PipelineRunner` as the public facade while splitting its run and
stage lifecycle responsibilities into smaller internal collaborators that can be
tested independently. The implementation should use the contracts already
created by Phases 2 through 5: stage-author `StageContext`, run-scoped artifact
stores, explicit stage factories, planner policy helpers, and the event, lock,
and blocked-outcome foundations from Phase 4.

The implementation must make failed local runs more durable by persisting
blocked descendant stage outcomes after a failure, emitting local lifecycle
events for run and stage facts, and acquiring and releasing the run-store lock
around mutating execution. It must not add subprocess, SLURM, container, retry,
timeout, cleanup, parallel execution, or remote-store behavior.

## Full-Plan Context

Phase 1 is merged and established recursive immutability, shared strict schema
helpers, and no-extra/config-extra validation evidence. Phase 2 is merged and
established capability-oriented stores, run-scoped artifact stores,
`ArtifactAddress`, and the narrower stage-author `StageContext` facade. Phase 3
is merged and established explicit stage factories plus semantic fingerprint
policy v2. Phase 4 is merged and established runtime/resource/event/lock
foundations plus durable blocked status vocabulary. Phase 5 is merged and
established planner policy helpers and `PlanExplanation`. Phase 6 is merged and
established explicit recipe catalogs and fresh composition paths.

Phase 7 resolves finding 3 from the implementation plan and completes finding 9
by integrating durable blocked outcomes into runner failure paths. It may
reorganize execution internals and update execution/state/reliability docs, but
it must keep the public runner facade stable and must not implement the deferred
executor and reliability roadmap items reserved for later versions. Phase 8
will handle final hardening, migration notes, and closeout coverage after Phase
7 is human-merged.

## Stack Context

- Root or stacked phase: root serial phase.
- Current predecessor branch or PR: none; Phase 6 was human-merged into
  `develop`.
- Why this base branch is correct: serial human-merge-gate mode starts each
  phase from updated `develop`; Phase 6 merge notes say Phase 7 must continue
  from updated `develop`, and this worktree records `develop` at
  `8741c73a6b0b2dd2f94213fbb143fe7400bd9257`.
- Retarget/rebase plan after predecessor merge: not applicable because there is
  no unmerged predecessor and the PR target is already `develop`.
- Branch cleanup constraints: keep the phase branch and worktree until the
  human-owned PR has merged into `develop` and no successor branch depends on
  it.

## Source Phase Summary

- Goal: preserve `PipelineRunner` as the public facade while splitting
  lifecycle concerns into smaller internal coordinators.
- Required scope:
  - Split runner internals around run creation/opening, lock acquire/release,
    planning invocation, provenance recording, stage coordination, artifact
    commits, event emission, failure recording, blocked-outcome persistence,
    and result construction.
  - Update local execution to use the stage-author context facade,
    run-scoped artifact store, explicit stage factory, event/outcome
    foundations, and store lock capability.
  - Persist blocked descendant outcomes after a failed stage.
  - Emit local run/stage lifecycle events for planned, started, completed,
    failed, skipped, reused, and blocked outcomes where applicable.
  - Keep executor-specific subprocess, SLURM, container, retry, and timeout
    behavior out of this phase.
  - Update `docs/structure.md`, `docs/features/execution.md`,
    `docs/features/state.md`, and `docs/features/reliability.md`.
- Acceptance criteria:
  - Success, failure, skip, reuse, and blocked-result integration tests still
    pass through `PipelineRunner`.
  - Failed runs persist complete downstream blocked outcomes.
  - Local event records are written deterministically enough for tests and human
    inspection.
  - Local run locking is acquired and released around mutating run execution.
  - Runner unit tests can target lifecycle subcomponents without constructing
    an entire synthetic pipeline for every concern.

## Current Source And Harness Findings

- `src/loom/pipeline/execution/runner.py` currently owns the full run method:
  run creation/opening, status writes, config/provenance persistence, planning,
  artifact-store construction, stage loop, stage construction, input binding,
  executor invocation, output validation, artifact-index updates, failure
  recording, in-memory blocked results, and final result construction.
- `src/loom/pipeline/execution/lifecycle.py` already exposes status helpers,
  including `write_stage_blocked`, but runner failure paths do not yet use
  durable blocked status for downstream stages.
- `src/loom/pipeline/events.py` defines strict `PipelineEvent` and
  `PipelineEventRecord`; `LocalRunStore.append_event()` persists append-only
  `events.jsonl`, but `PipelineRunner` does not emit events yet.
- `src/loom/pipeline/locks.py` defines `RunLockRecord`; `RunStore` includes
  `RunLockStore`, and `LocalRunStore` can acquire/read/release `lock.json`, but
  runner execution does not acquire or release a lock.
- `src/loom/pipeline/status.py` has durable `StageStatus.BLOCKED` and strict
  status records. The current in-memory `_blocked_after_failure()` helper
  returns `status=None` and no attempt.
- `src/loom/pipeline/executors/local.py` remains a local in-process executor.
  It should continue to execute a single stage request and report facts; it
  should not start making lifecycle, retry, timeout, or blocked decisions.
- `src/loom/pipeline/execution/models.py` allows `StageRunResult.status` and
  `attempt` to be `None`; Phase 7 can continue allowing `None` for defensive
  failures, but persisted blocked descendants returned by normal failure paths
  must use `StageStatus.BLOCKED` and an attempt number.
- Integration tests in `tests/integration/pipeline/test_local_execution*.py`
  cover success, selector skip, factory init separation, same-run resume/reuse,
  stage exceptions, output validation, and failure persistence. They do not yet
  assert runner events, runner lock acquire/release, or persisted blocked
  descendants.
- Unit tests already cover event model serialization, lock model/store
  behavior, store protocols, and `write_stage_blocked`. New unit coverage
  should target extracted execution collaborators directly.

## Decision-Complete Contract

### Public API

Keep these public surfaces stable:

```python
PipelineRunner(
    *,
    run_store: RunStore,
    executor: Executor | None = None,
    artifact_store_factory: ArtifactStoreFactory | None = None,
    clock: Callable[[], str] = utc_timestamp,
)

PipelineRunner.run(request: RunRequest) -> RunResult

run_pipeline(
    request: RunRequest,
    *,
    run_store: RunStore,
    executor: Executor | None = None,
    artifact_store_factory: ArtifactStoreFactory | None = None,
) -> RunResult
```

Do not add required constructor parameters, change `RunRequest`, change
`ExecutionPlan`, or expose new public lifecycle customization hooks in this
phase. New execution modules should be private or package-internal unless a
test needs to import a focused helper from `loom.pipeline.execution`.

### Internal Module Boundaries

Preserve `runner.py` as the facade and top-level orchestrator, but move
single-purpose logic out of the monolithic `PipelineRunner.run()` path. The
executor should prefer these internal boundaries:

- `src/loom/pipeline/execution/eventing.py`
  - Owns lifecycle event construction and append calls.
  - Uses `PipelineEvent`, `EventScope`, and `RunEventStore.append_event()`.
  - Accepts the runner clock and passes explicit timestamps so tests can be
    deterministic.
- `src/loom/pipeline/execution/run_locks.py`
  - Owns acquire/release as a small context manager or helper.
  - Calls `RunLockStore.acquire_run_lock()` and `release_run_lock()`.
  - Does not implement stale-lock cleanup, force unlock, or distributed lock
    policy.
- `src/loom/pipeline/execution/stage_coordinator.py`
  - Owns dispatch for `PlanAction.RUN`, `REUSE`, `SKIP`, `BLOCKED`, and
    `STALE`.
  - Builds `StageExecutionRequest`, invokes the executor for `RUN`, validates
    outputs, and returns `StageRunResult`.
  - Delegates status writes, artifact commits, provenance, failures, blocked
    outcomes, and events to narrower helpers instead of inlining all logic.
- `src/loom/pipeline/execution/failures.py`
  - Owns `ExecutionFailure` construction from exceptions and failed plan
    actions.
  - Owns failure-type mapping that is currently private in `runner.py`.
- `src/loom/pipeline/execution/artifact_commits.py`
  - Owns stage output persistence and artifact-index merge/write helpers for
    `RUN` and `REUSE`.
- `src/loom/pipeline/execution/run_setup.py`
  - Owns create/open, config/spec resolution, config snapshots, provenance
    document writes, and run created/planned/running/final status helpers.

If implementation reveals a simpler naming split that preserves these
responsibilities without expanding public API, it is acceptable. It is not
acceptable to move the current monolithic method wholesale into one new class
without making lifecycle branches unit-testable.

### Locking Behavior

The runner must acquire the store lock once per mutating run execution and
release it exactly once after finalization.

- For a new run, call `create_run()` first because the current local lock
  implementation requires an existing run directory, then acquire the lock
  before writing run status, config snapshots, provenance, plans, stage state,
  events, artifact indexes, or stage logs.
- For `open_existing=True`, call `open_run()` first to validate the run, then
  acquire the lock before any mutating write.
- Lock owner metadata should be plain data and include at least:
  - `"component": "PipelineRunner"`
  - `"run_id": run_id`
  - `"executor": executor.name` when available
- If lock acquisition fails, propagate the store lock error and do not write
  failed status because another owner may be mutating the run.
- Use `try`/`finally` or an equivalent context manager so success, stage
  failure, output validation failure, plan-execution failure, event-write
  failure, and store-commit failure paths all attempt release when a lock was
  acquired.
- If release fails, do not silently swallow it. Preserve the original execution
  failure when one exists, but surface the release failure to the caller or
  record it in a clearly testable lifecycle failure path when there is no
  prior failure.
- Do not add stale-lock cleanup, liveness checks, lock stealing, force unlock,
  stage-level locks, distributed locks, or retry loops.

### Lifecycle Event Contract

Emit events only after the corresponding durable state change has succeeded.
Use explicit event timestamps from `PipelineRunner.clock` rather than relying
on `LocalRunStore.append_event()` to generate timestamps. Tests should assert
sequence, scope, event type, and stable payload fields rather than exact
wall-clock values from `LocalExecutor`.

Required event types:

| Event type | Scope | Emit after | Required stable payload |
| --- | --- | --- | --- |
| `run.created` | run | new run is created and lock is acquired | `{"open_existing": False}` |
| `run.opened` | run | existing run is opened and lock is acquired | `{"open_existing": True}` |
| `run.planned` | run | plan is persisted and run status is `PLANNED` | `{"summary": plan.summary}` |
| `stage.planned` | stage | `run.planned`, once for each ordered stage plan | `{"action": action, "reason_codes": [...]}` |
| `run.started` | run | run status is `RUNNING` | `{}` or `{"stage_count": n}` |
| `stage.started` | stage | stage status is `RUNNING` | `{"attempt": attempt, "action": "RUN"}` |
| `stage.completed` | stage | outputs, artifact index, provenance, and `SUCCEEDED` status are committed | `{"attempt": attempt, "action": "RUN", "status": "SUCCEEDED"}` |
| `stage.failed` | stage | failure document and `FAILED` status are committed | `{"attempt": attempt, "failure_type": failure.failure_type}` |
| `stage.skipped` | stage | `SKIPPED` status is committed | `{"attempt": attempt, "action": "SKIP", "reason_codes": [...]}` |
| `stage.reused` | stage | reusable outputs are resolved and artifact index is updated | `{"action": "REUSE", "reason_codes": [...]}` |
| `stage.blocked` | stage | `BLOCKED` status is committed | `{"attempt": attempt, "blocked_by": [...], "reason_codes": [...]}` |
| `run.completed` | run | final run status is `SUCCEEDED` | `{"status": "SUCCEEDED"}` |
| `run.failed` | run | final run status is `FAILED` | `{"status": "FAILED", "failed_stage": ..., "failure_type": ...}` |

Do not emit retry, timeout, cleanup, subprocess, SLURM, container, plugin-sink,
or notification events in this phase. Do not build an event callback registry.

Event emission is a strict local lifecycle commit. If `append_event()` fails,
the runner should follow the existing store-commit failure path where a stage is
active, or fail the run setup/finalization path clearly when no stage is
active. Do not let event write failures pass silently.

### Stage Action Behavior

`PlanAction.RUN`:

- Bind planned inputs without recomputing planner policy.
- Compute and persist the stage fingerprint.
- Persist inputs and fingerprint before execution.
- Prepare the stage workspace.
- Write `RUNNING` status and emit `stage.started`.
- Construct the stage through the explicit stage factory helper.
- Build `StageContext` using the stage-author facade, run-scoped artifact
  store, declared outputs, local output path, and local workspace path.
- Invoke the configured `Executor`.
- If the executor reports failed, persist failure and `FAILED` status, emit
  `stage.failed`, and stop further execution.
- If the executor reports succeeded, validate outputs, persist outputs, update
  artifact index with replacement for that stage, write stage provenance, write
  `SUCCEEDED` status, emit `stage.completed`, and continue.

`PlanAction.REUSE`:

- Resolve reusable outputs from the stage plan or prior persisted stage outputs.
- Update the artifact index without replacing unrelated existing entries.
- Return `StageRunResult(action=REUSE)` with prior status/attempt when present,
  or `StageStatus.SUCCEEDED` and `attempt=None` when prior status is absent.
- Emit `stage.reused` after artifact index update.
- Do not write a new stage status solely for reuse in this phase.

`PlanAction.SKIP`:

- Write `SKIPPED` status using `next_stage_attempt()`.
- Return `StageRunResult(action=SKIP, status=StageStatus.SKIPPED, attempt=...)`.
- Emit `stage.skipped`.
- Do not write inputs, outputs, fingerprints, provenance, failure metadata, or
  logs for skipped stages.

`PlanAction.BLOCKED`:

- Treat a blocked stage from the final execution plan as non-executable.
- Write status-only `StageStatus.BLOCKED` with `write_stage_blocked()`.
- Return `StageRunResult(action=BLOCKED, status=StageStatus.BLOCKED,
  attempt=...)`.
- Emit `stage.blocked`.
- Mark the run failed with an `ExecutionFailure` of
  `failure_type="plan_execution"` for the first blocked stage that prevents a
  complete run. Do not invoke the executor.

`PlanAction.STALE`:

- Treat stale in the final executable plan as a planner/execution consistency
  failure.
- Persist an `ExecutionFailure` and `FAILED` status for that stage with
  `failure_type="plan_execution"`, emit `stage.failed`, mark the run failed,
  and persist later descendants as `BLOCKED`.
- Do not execute a stale stage directly.

### Failure And Blocked Descendant Persistence

After the first failed stage or failed plan action:

- Preserve `RunResult.failed_stage` and `RunResult.failure` as the first
  actual failure, not a downstream blocked stage.
- For every remaining ordered stage not already represented in
  `stage_results`, write status-only `StageStatus.BLOCKED` with
  `write_stage_blocked()`.
- Use `next_stage_attempt()` for each blocked descendant so same-run reruns do
  not reuse stale attempt numbers.
- Include stable blocked metadata:
  - `blocked_by`: the failed stage name, or a list containing that stage name;
  - `reason_code`: `"upstream_failed"` for downstream blockage after a failed
    stage, or `"plan_blocked"` for an explicit blocked plan action;
  - `reasons`: serialized `PlanReason` values from the descendant stage plan.
- Emit `stage.blocked` after each blocked status write.
- Do not write inputs, outputs, fingerprints, provenance, failure metadata, or
  logs for blocked descendants that did not execute.
- Return blocked descendant results with `StageStatus.BLOCKED`, attempt,
  reasons, `finished_at` or blocked time, and empty outputs.

The current `_blocked_after_failure()` helper can be removed or reduced to a
small result builder that receives the already-persisted blocked status record.
Normal Phase 7 failure paths must not leave blocked descendants as
`status=None`.

### Run Finalization And Result Construction

- `RunResult.stage_results` must still contain every planned stage.
- `RunResult.artifact_index` should be read after the final stage loop and
  after all artifact-index updates.
- Successful runs write final `RunStatus.SUCCEEDED`, emit `run.completed`, and
  release the lock.
- Failed runs write final `RunStatus.FAILED` once with the first failure's
  message and metadata, emit `run.failed`, persist blocked descendants, and
  release the lock.
- If a store commit failure happens while recording a stage failure, preserve
  the original inspectable failure document when it was already written and use
  the store-commit failure as the run failure only when that matches the
  existing runner behavior.
- Do not introduce continue-on-failure. `FailurePolicy.stop_on_first_failure`
  remains the only supported mode, and `False` remains rejected.

### Documentation Contract

Update only docs that this phase owns:

- `docs/structure.md`: describe the new execution internal files and clarify
  that runner lifecycle uses existing event/lock/status foundations.
- `docs/features/execution.md`: update the v0-post runner lifecycle flow so it
  includes run locks, events, and durable blocked descendants; remove or update
  older text that says v0 does not acquire a run lock by default where it would
  contradict Phase 7.
- `docs/features/state.md`: update Phase 4 deferral text to say runner failure
  paths now persist blocked descendants.
- `docs/features/reliability.md`: clarify that local lifecycle events and
  blocked outcomes are now emitted/persisted, while retry, timeout, cleanup,
  and event sinks remain deferred.

Do not perform broad migration-note cleanup; Phase 8 owns final hardening docs.

## In-Scope Work

- Extract internal execution collaborators while preserving the public
  `PipelineRunner` constructor, `PipelineRunner.run()`, and `run_pipeline()`
  facade.
- Keep stage execution serial and local-first. Use the existing `Executor`
  protocol and `LocalExecutor` behavior.
- Acquire a run lock after creating or opening the run and release it in all
  success and failure paths after final run status/result construction.
- Emit local lifecycle events through `RunEventStore.append_event()` using the
  event types and ordering defined above.
- Persist blocked descendant outcomes after the first failed stage using
  `write_stage_blocked()` and return `StageRunResult` records with
  `StageStatus.BLOCKED`.
- Preserve failure recording order: write inspectable failure metadata before
  marking the failed stage and run failed, then persist downstream blocked
  statuses.
- Keep artifact commits, stage output validation, provenance writes, and
  artifact-index updates scoped to run, reuse, and success cases.
- Update docs that own changed execution/state/reliability boundaries.

## Out-of-Scope Work

- No subprocess worker, subprocess command contract, SLURM submission,
  container execution, remote executor, remote store, run catalog, bundle,
  sweep, plugin discovery, retry, timeout, cleanup, retention, or parallel
  execution behavior.
- No public runner API replacement and no new public lifecycle plugin or event
  sink registry.
- No planner policy changes, `ExecutionPlan` persistence changes, selector
  semantics changes, semantic fingerprint policy changes, or config composition
  changes.
- No distributed locking, stale-lock cleanup, force unlock, process liveness
  detection, or lock ownership policy beyond using the existing store lock.
- No change that makes runtime/resource operational hints semantic for
  fingerprints.
- No standalone migration notes or final roadmap closeout; Phase 8 owns those.

## Assumptions

- `PipelineRunner` may continue to require a run store that provides
  `LocalRunStorePaths` for the local-only execution paths and log/workspace
  path allocation.
- A run lock cannot be acquired until the local run directory exists with the
  current Phase 4 API, so new-run `create_run()` remains the only mutating
  operation outside the lock. All later execution mutations must be inside the
  lock.
- Event payloads should contain stable plain data such as stage name, action,
  status, attempt, reason codes, and failure type, but not unstable filesystem
  internals unless already public through model fields.
- The implementation should prefer deterministic unit tests with a fake clock
  for event timestamps and lifecycle helper behavior.

## Design Impact

- Maintainability: this phase removes the large monolithic runner control path
  and gives status, planning, stage execution, artifact commit, event, lock,
  failure, blocked-outcome, and result construction concerns smaller homes.
- Extensibility: later executors, event sinks, reliability policies, and
  cleanup work can attach to lifecycle boundaries instead of editing one large
  method.
- Domain neutrality: lifecycle events and statuses remain generic pipeline
  facts and do not encode ML, data-science, scheduler, or storage-vendor
  semantics.
- Source-tree boundaries: execution owns lifecycle decisions, stores persist
  state/events/locks, planning owns actions/reasons, executors invoke stages,
  and project code remains inside stage implementations.

## Future Compatibility

- Future subprocess and submitted executors can reuse the same stage
  coordination and status/event commit boundaries.
- Future retry and timeout policies can consume structured failure facts and
  event records without changing the `PipelineRunner` facade.
- Future CLI/status/catalog work can inspect `status.json` and `events.jsonl`
  without reconstructing blocked descendants from plan state.
- Future event sinks can subscribe to the same event vocabulary without
  changing current local JSONL records.

## Alternatives Rejected

| Alternative | Reason rejected |
| --- | --- |
| Replace `PipelineRunner` with a new public lifecycle engine | The implementation plan requires preserving `PipelineRunner` as the facade before v1. |
| Add event emission directly throughout the current monolithic `run()` method without decomposition | This would meet part of the event requirement while preserving the maintainability problem this phase exists to fix. |
| Implement subprocess/retry/timeout policy while touching lifecycle | These are explicitly deferred roadmap items and would make the Phase 7 PR too large to review. |
| Persist blocked descendants only in `RunResult` | This fails the implementation plan requirement that failed runs have durable blocked outcome records. |
| Write failure documents for blocked descendants | A blocked descendant did not execute or fail directly; Phase 4 chose status-only blocked outcomes. |
| Treat lock conflict as a failed run status write | A lock conflict means another owner may be mutating the run, so writing failed status would violate the lock boundary. |

## Debt Introduced

| Debt | Reason accepted | Revisit trigger |
| --- | --- | --- |
| New-run directory creation happens before lock acquisition | The existing local lock API requires an existing run directory; create-run remains an atomic setup operation before mutating execution state. | Revisit when lock acquisition can reserve a run ID before directory creation or when concurrent controllers require pre-create locking. |
| `PipelineRunner` may still require local path helpers for local execution artifacts, logs, and workspaces | Phase 7 is local execution lifecycle work; generic remote execution is deferred. | Revisit when subprocess workers or remote stores need a non-local path allocation contract. |
| Event emission is local store append-only JSONL without plugin sinks | Phase 4 intentionally created event records and local persistence only; plugin sinks are later work. | Revisit when plugin discovery or event sink APIs are implemented. |

## Reviewability

- Expected PR size and shape: medium internal execution refactor with focused
  tests and docs. It should be reviewable as internal extraction plus behavior
  additions for lock, events, and blocked outcomes.
- Files and areas to inspect:
  - `src/loom/pipeline/execution/runner.py`
  - new internal modules under `src/loom/pipeline/execution/`
  - `src/loom/pipeline/execution/lifecycle.py`
  - `src/loom/pipeline/execution/models.py` only if blocked results need
    stricter status/attempt representation
  - `tests/unit/loom/pipeline/execution/`
  - `tests/integration/pipeline/test_local_execution.py`
  - `tests/integration/pipeline/test_local_execution_resume.py`
  - `tests/integration/pipeline/test_local_execution_failures.py`
  - `docs/structure.md`
  - `docs/features/execution.md`
  - `docs/features/state.md`
  - `docs/features/reliability.md`
- Scope-control checks: no changes under config composition, planner semantics,
  executor backends beyond local request handling, remote stores, subprocess,
  SLURM, container, retry, timeout, cleanup, plugin discovery, catalogs, or
  bundles.
- Review trap: a diff that adds lifecycle abstractions but leaves blocked
  descendants unpersisted, events untested, or lock release untested is not
  complete.

## Implementation Steps

1. Add focused tests that characterize the required lock, event, reuse, skip,
   failure, and blocked-descendant runner facts before broad refactoring.
2. Add internal eventing and run-lock helpers that use existing Phase 4 store
   capabilities and deterministic runner clock timestamps.
3. Extract failure construction and artifact commit helpers from
   `PipelineRunner` while preserving current failure-type and artifact-index
   behavior.
4. Extract stage action coordination for `RUN`, `REUSE`, `SKIP`, `BLOCKED`,
   and `STALE` actions without changing planner semantics.
5. Centralize failure finalization and persist status-only blocked outcomes for
   all downstream planned descendants after the first failure.
6. Rework `PipelineRunner.run()` into a short facade orchestration path that
   creates or opens the run, acquires the lock, plans, executes ordered stage
   actions, finalizes status/events/results, and releases the lock.
7. Update Phase 7-owned docs and run targeted package, unit, contract, and
   integration tests before PR preparation.

## Detailed Implementation Slices

### Slice 1: Characterize Expected Runner Facts

- Add or prepare focused tests for:
  - lock file is removed after successful run;
  - lock file is removed after stage failure;
  - failed stage persists downstream `StageStatus.BLOCKED`;
  - success emits `run.planned`, stage planned/started/completed events, and
    `run.completed`;
  - failure emits `stage.failed`, downstream `stage.blocked`, and `run.failed`;
  - selector skip emits `stage.skipped`;
  - same-run reuse emits `stage.reused`.
- Keep assertions stable: event type sequence, scope kind/stage, action/status,
  and reason codes. Do not assert incidental timestamp values unless using a
  fake clock.

### Slice 2: Add Eventing And Lock Helpers

- Add `execution/eventing.py` with a small helper that appends `PipelineEvent`
  records with explicit timestamps from the runner clock.
- Add `execution/run_locks.py` with a context manager or helper that acquires
  and releases the store lock once per run.
- Unit-test both helpers with fake stores before integrating them into
  `PipelineRunner`.

### Slice 3: Extract Failure And Artifact Commit Helpers

- Move failure-type mapping and `ExecutionFailure` construction out of
  `runner.py`.
- Move artifact index merge/write helpers into an internal artifact commit
  helper.
- Preserve current behavior for output validation failures, store commit
  failures, target construction failures, and executor infrastructure failures.

### Slice 4: Extract Stage Action Coordination

- Move RUN, REUSE, SKIP, BLOCKED, and STALE dispatch into
  `stage_coordinator.py` or an equivalent internal helper.
- Keep planner action semantics unchanged.
- Ensure RUN still constructs stages through `construct_stage()` and uses the
  stage-author `StageContext` facade with run-scoped artifact stores.
- Ensure executor-specific behavior stays inside `LocalExecutor` and the
  generic `Executor` protocol.

### Slice 5: Persist Blocked Descendants

- Centralize failure finalization so downstream blocked outcomes are written
  once per failed run.
- Use `write_stage_blocked()` and return blocked `StageRunResult` values with
  `StageStatus.BLOCKED`, attempt, reasons, and stable metadata.
- Add integration assertions for persisted blocked descendant status files and
  absence of inputs/outputs/fingerprints/provenance/failure/log files for
  blocked descendants.

### Slice 6: Integrate Run Lifecycle

- Keep `PipelineRunner.run()` as a short orchestration path:
  validate request, create/open run, acquire lock, prepare config/spec,
  plan, mark running, execute ordered stage actions, finalize run, release
  lock, return `RunResult`.
- Ensure all final status writes and event emissions happen before lock
  release.
- Ensure lock release is attempted in `finally` after all body paths.

### Slice 7: Documentation And Focused Validation

- Update only the Phase 7-owned docs listed in the documentation contract.
- Run targeted unit/integration/contract tests before PR preparation.
- PR preparation later must run `make validate-pr` and `make test-summary`.

## Implementation Commit Guidance

- Commit 1: eventing and lock helper tests/helpers.
- Commit 2: failure/artifact commit extraction and runner wiring without
  behavior changes beyond helper integration.
- Commit 3: blocked descendant persistence and lifecycle events with focused
  integration tests.
- Commit 4: documentation updates and validation-driven cleanup.

This grouping is guidance, not a mandate. Keep commits coherent and avoid
mixing docs-only cleanup with behavior changes when that would make review
harder.

## Test Plan

### Package Suite

- Status: required.
- Expected paths:
  - `tests/package/test_import_boundaries.py`
  - package export tests only if a public export changes, which is not expected
- Required assertions or deferral reason:
  - `import loom` remains cheap.
  - Runner decomposition does not import optional config dependencies through
    package top-level imports.
  - New internal modules do not force config extras, subprocess, SLURM, or
    container imports.

### Unit Suite

- Status: required.
- Expected paths:
  - `tests/unit/loom/pipeline/execution/test_runner.py`
  - `tests/unit/loom/pipeline/execution/test_lifecycle.py`
  - new `tests/unit/loom/pipeline/execution/test_eventing.py` if an eventing
    helper is added
  - new `tests/unit/loom/pipeline/execution/test_run_locks.py` if a lock helper
    is added
  - new tests for `stage_coordinator.py`, `failures.py`, or
    `artifact_commits.py` if those helpers are added
- Required assertions or deferral reason:
  - Lock release is attempted on success and stage failure.
  - Event helper emits required event types with deterministic timestamps and
    plain-data payloads.
  - Blocked outcome helper writes status-only blocked records with expected
    metadata.
  - Failure construction preserves current failure-type mapping.
  - Stage action coordinator handles RUN, REUSE, SKIP, BLOCKED, and STALE
    without needing a full synthetic pipeline for every branch.

### Contract Suite

- Status: required.
- Expected paths:
  - `tests/contracts/test_executor_contract.py`
  - `tests/contracts/test_store_contract.py`
- Required assertions or deferral reason:
  - Existing executor and store protocols remain valid.
  - Add or update contract tests only if implementation changes protocol
    boundaries, which is not expected.
  - Verify no lifecycle helper starts requiring a concrete `LocalRunStore`
    where the existing `RunEventStore` or `RunLockStore` protocol is enough.

### Integration Suite

- Status: required.
- Expected paths:
  - `tests/integration/pipeline/test_local_execution.py`
  - `tests/integration/pipeline/test_local_execution_resume.py`
  - `tests/integration/pipeline/test_local_execution_failures.py`
- Required assertions:
  - Successful local run still persists plan, status, stage inputs/outputs, and
    artifact index.
  - Successful local run releases `lock.json`.
  - Successful local run emits required run and stage events.
  - Selector skip persists `SKIPPED` and emits `stage.skipped`.
  - Same-run rerun still reuses unchanged stages and emits `stage.reused`.
  - Stage exception and invalid output failures persist failed stage failure
    metadata and `FAILED` status.
  - After stage failure, every planned downstream descendant has status-only
    `StageStatus.BLOCKED` persisted, no execution side files, and a
    `StageRunResult` with `StageStatus.BLOCKED`.
  - Failure paths release `lock.json`.
  - Store commit failure tests still preserve inspectable state and failed run
    semantics.

### E2E Suite

- Status: deferred for new coverage, existing suite required in PR validation.
- Expected paths: existing `tests/e2e/`.
- Required assertions or deferral reason: Phase 7 changes internal local runner
  lifecycle and integration tests are the right behavioral level. Add e2e only
  if implementation changes user-visible end-to-end behavior not covered by
  integration tests.

### Opt-In Suites

- Status: required.
- Markers affected: `optional_dependency`, especially config-extra pipeline
  integration tests.
- Required assertions or deferral reason:
  - Local runner integration tests rely on config extras.
  - Preserve the no-extra/config-extra split and report both through
    `make validate-pr` and `make test-summary`.
  - Do not add subprocess, SLURM, container, retry, timeout, cleanup, or remote
    store opt-in suites in this phase.

## Suite-Level Test Obligations

- Package: required. Preserve no-extra import boundaries and package lazy
  imports. Add package export checks only if the implementation deliberately
  exports new public execution helpers.
- Unit: required. New internal collaborators must be unit-testable, especially
  event emission, lock release, failure construction, blocked writing, and
  stage action dispatch.
- Contract: required. Existing store and executor protocols must remain green;
  protocol changes are not expected.
- Integration: required. This is the main behavioral evidence for success,
  failure, skip, reuse, lock, event, and blocked descendant runner behavior.
- E2E: no new e2e required unless user-visible local run behavior changes
  outside the existing integration surface. Existing e2e must still pass during
  PR validation.
- Opt-in: required through the existing config-extra pipeline tests and
  `make test-summary`; no new optional runtime backend suites are allowed.

## Acceptance Checklist

- `PipelineRunner` and `run_pipeline` public signatures remain stable.
- Runner internals are split into unit-testable lifecycle collaborators.
- Run lock is acquired after create/open and released on success and failure.
- Lock conflicts do not write failed status into a run owned by another
  process.
- Required lifecycle events are appended to local `events.jsonl` after matching
  durable state changes.
- Event tests assert stable event type/scope/payload behavior without brittle
  timestamp assumptions.
- Success, skip, reuse, stage failure, output validation failure, and store
  commit failure behavior remains compatible with existing tests.
- Failed runs persist status-only blocked outcomes for all unexecuted
  downstream planned stages.
- Blocked descendants are returned with `StageStatus.BLOCKED`, not
  `status=None`, on normal failure paths.
- Docs reflect runner lock/event/blocked integration without claiming retry,
  timeout, cleanup, subprocess, SLURM, container, plugin, or remote-store
  behavior exists.

## Risks

- Event emission can make tests brittle if assertions rely on exact timestamps
  or incidental payload fields. Tests should assert event types, scopes,
  sequences, and stable payload keys.
- Lock acquire/release failures can mask original stage failures if error
  handling is not explicit.
- Internal extraction can accidentally change planning, fingerprint, resume, or
  artifact commit semantics.
- Blocked descendants can be double-written or assigned inconsistent attempts
  if failure paths are not centralized.
- Moving helpers into too many public-looking modules can create accidental API
  promises. Keep new surfaces internal unless deliberately exported.

## Validation Commands

Targeted development commands:

```sh
uv run pytest tests/unit/loom/pipeline/execution/test_lifecycle.py
uv run pytest tests/unit/loom/pipeline/execution/test_runner.py
uv run pytest tests/unit/loom/pipeline/execution
uv run pytest tests/integration/pipeline/test_local_execution.py
uv run pytest tests/integration/pipeline/test_local_execution_resume.py
uv run pytest tests/integration/pipeline/test_local_execution_failures.py
uv run pytest tests/contracts/test_store_contract.py tests/contracts/test_executor_contract.py
uv run pytest tests/package/test_import_boundaries.py
```

Final PR-preparation commands:

```sh
make validate-pr
make test-summary
```

## Handoff Notes For `loom_phase_executor`

- Safe implementation slices:
  - eventing and run lock helpers;
  - failure construction and artifact commit extraction;
  - stage action coordination extraction;
  - blocked descendant persistence;
  - runner orchestration cleanup;
  - docs and focused test updates.
- Tests to run with each slice:
  - eventing/lock helpers: new focused unit tests plus
    `tests/unit/loom/pipeline/test_events.py` and
    `tests/unit/loom/pipeline/test_locks.py` if touched;
  - stage/failure extraction:
    `uv run pytest tests/unit/loom/pipeline/execution`;
  - blocked and event integration:
    `uv run pytest tests/integration/pipeline/test_local_execution.py tests/integration/pipeline/test_local_execution_failures.py`;
  - reuse changes:
    `uv run pytest tests/integration/pipeline/test_local_execution_resume.py`;
  - protocol/import confidence:
    `uv run pytest tests/contracts/test_store_contract.py tests/contracts/test_executor_contract.py tests/package/test_import_boundaries.py`.
- Decisions the executor must not revisit:
  - `PipelineRunner` remains the public facade.
  - Execution remains serial and local in this phase.
  - Stage construction uses explicit stage factories.
  - Artifact stores remain run-scoped.
  - Planner action semantics and semantic fingerprint policy remain unchanged.
  - Events use `loom.pipeline.events` models and local append-only JSONL
    persistence.
  - Locks use the existing store lock capability.
  - Blocked descendants are status-only records.
  - Subprocess, SLURM, container, retry, timeout, cleanup, plugin, remote-store,
    catalog, bundle, and sweep behavior stays deferred.
- Conditions that require stopping for the manager:
  - preserving public runner signatures becomes impossible;
  - lock release cannot be guaranteed in normal success/failure paths;
  - blocked descendants cannot be persisted without changing the store
    protocol;
  - event emission requires a public plugin/callback API;
  - implementation would need planner semantics or deferred executor/reliability
    features.

## Refinement And Review Budget Status

- Phase implementation refinement: used
- PR review: unused

## Completion Notes

- Draft plan: completed by `loom_phase_planner` in commit `0096ffe`.
- Final phase execution plan: refined by `loom_phase_planner` in this planning
  pass; this document is decision-complete for executor handoff.
- Implementation summary: added focused eventing and run-lock helpers, wired
  `PipelineRunner` to acquire and release the run-store lock around mutating
  execution, emit local lifecycle events after durable state commits, persist
  status-only blocked descendant records after the first failure, keep reuse
  and skip non-executing, and update Phase 7-owned execution, state,
  reliability, and structure docs. The public `PipelineRunner` and
  `run_pipeline` signatures remain unchanged.
- Implementation validation: `UV_CACHE_DIR=/tmp/uv-cache uv run pytest
  tests/unit/loom/pipeline/execution/test_eventing.py
  tests/unit/loom/pipeline/execution/test_run_locks.py` passed with 5 tests;
  `UV_CACHE_DIR=/tmp/uv-cache uv run --extra config pytest
  tests/unit/loom/pipeline/execution
  tests/integration/pipeline/test_local_execution.py
  tests/integration/pipeline/test_local_execution_resume.py
  tests/integration/pipeline/test_local_execution_failures.py
  tests/contracts/test_store_contract.py tests/contracts/test_executor_contract.py
  tests/package/test_import_boundaries.py` passed with 50 tests; and
  `UV_CACHE_DIR=/tmp/uv-cache uv run --extra config pyright` reported 0
  errors, 0 warnings, and 0 informations.
- Refinement summary: one bounded implementation refinement pass completed.
  The pass kept scope to runner lifecycle correctness: event records for
  run-created/opened, stage-completed, stage-failed, and run-failed now use the
  runner clock rather than executor wall-clock failure/completion timestamps;
  the obsolete `_blocked_after_failure()` helper that returned non-durable
  `status=None` blocked results was removed; integration coverage now asserts
  runner-clock event timestamps and the `run.opened` payload; and
  `docs/features/execution.md` now uses the implemented dot-name event
  vocabulary consistently.
- Refinement validation: `UV_CACHE_DIR=/tmp/uv-cache uv run --extra config
  pytest tests/integration/pipeline/test_local_execution.py
  tests/integration/pipeline/test_local_execution_resume.py
  tests/integration/pipeline/test_local_execution_failures.py
  tests/unit/loom/pipeline/execution/test_eventing.py
  tests/unit/loom/pipeline/execution/test_run_locks.py` passed with 15 tests;
  `UV_CACHE_DIR=/tmp/uv-cache uv run ruff check
  src/loom/pipeline/execution/runner.py
  tests/integration/pipeline/test_local_execution.py
  tests/integration/pipeline/test_local_execution_resume.py` passed; and
  `UV_CACHE_DIR=/tmp/uv-cache uv run --extra config pyright` reported 0
  errors, 0 warnings, and 0 informations.
- PR preparation: drafted `docs/phases/v0-post-runner-lifecycle-pr-body.md`;
  documented manager-provided `UV_CACHE_DIR=/tmp/uv-cache make validate-pr`
  evidence from refiner commit `8c91e73` (Ruff clean, Pyright 0 errors,
  default harness 406 passed / 9 skipped, config-extra 108 passed / 407
  deselected, build passed); and ran `UV_CACHE_DIR=/tmp/uv-cache make
  test-summary`, which passed and wrote `build/test-summary.md` with package,
  unit, contract, integration, e2e, and config-extra suites passing. Opened
  PR #21 against `develop`, verified `baseRefName=develop`,
  `headRefName=codex/v0-post-runner-lifecycle`, `state=OPEN`, and
  `mergedAt=null`; CI `checks` completed with `SUCCESS`. Reviewer
  request through `gh pr edit 21 --add-reviewer samcantrill` was rejected by
  GitHub CLI/API, so fallback comment
  https://github.com/samcantrill/loom/pull/21#issuecomment-4371996188 was
  added mentioning `@samcantrill`.
- Stack maintenance: root serial phase; PR must target `develop`; Phase 8 must
  not start until Phase 7 is human-merged into `develop`.
- Remaining blockers: none.
