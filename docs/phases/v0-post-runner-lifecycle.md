# Phase 7 Execution Plan: Runner Lifecycle Decomposition

## Metadata

- Status: draft phase execution plan
- Branch: `codex/v0-post-runner-lifecycle`
- Worktree: `/home/samcantrill/work/loom-worktrees/v0-post-runner-lifecycle`
- Phase execution plan path: `docs/phases/v0-post-runner-lifecycle.md`
- Full plan: `docs/implementation-plans/implementation-plan-v0-post.md`
- Source phase: `Phase 7 - Runner Lifecycle Decomposition`
- PR: pending
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
- Draft pass: completed by `loom_phase_planner` in this planning pass.
- Refine pass: pending. This draft captures the high-level scope and must be
  refined before executor handoff.
- Phase implementation refinement budget: unused.
- PR review budget: unused.
- Setup limitations: local `develop` matched the manager-provided Phase 7 base
  commit `8741c73`. No remote synchronization was attempted during planning
  because the assignment provided the updated base. Creating the
  slash-namespaced branch and worktree required approved Git worktree
  permissions after the sandbox could not create the branch ref directory.
- Blockers: none.

## Objective

Preserve `PipelineRunner` as the public facade while splitting its run and
stage lifecycle responsibilities into smaller internal collaborators that can be
tested independently. The phase should use the contracts already created by
Phases 2 through 5: stage-author `StageContext`, run-scoped artifact stores,
explicit stage factories, planner policy helpers, and the event, lock, and
blocked-outcome foundations from Phase 4.

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
executor and reliability roadmap items reserved for later versions.

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
  should not start making lifecycle or retry decisions.
- Integration tests in `tests/integration/pipeline/test_local_execution*.py`
  cover success, selector skip, factory init separation, same-run resume/reuse,
  stage exceptions, output validation, and failure persistence. They do not yet
  assert runner events, runner lock acquire/release, or persisted blocked
  descendants.
- Unit tests already cover event model serialization, lock model/store
  behavior, store protocols, and `write_stage_blocked`. New unit coverage can
  target extracted execution collaborators directly.

## In-Scope Work

- Extract internal execution collaborators while preserving the public
  `PipelineRunner` constructor, `PipelineRunner.run()`, and `run_pipeline()`
  facade.
- Keep stage execution serial and local-first. Use the existing `Executor`
  protocol and `LocalExecutor` behavior.
- Acquire a run lock after creating or opening the run and release it in all
  success and failure paths after final run status/result construction.
- Emit local lifecycle events through `RunEventStore.append_event()` for run
  creation/opening, planning, run start/completion/failure, stage planned,
  stage started, stage completed, stage failed, stage skipped, stage reused,
  and stage blocked where applicable.
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

## Assumptions

- `PipelineRunner` may continue to require a run store that provides
  `LocalRunStorePaths` for the local-only execution paths and log/workspace
  path allocation.
- Event emission failures and lock release failures are lifecycle/store
  failures that should be represented as failed run results where possible
  rather than silently ignored.
- Blocked descendants should use the next stage attempt number if a prior
  status exists, and attempt `1` otherwise.
- Event payloads should contain stable plain data such as stage name, action,
  status, attempt, reason codes, and failure type, but not unstable filesystem
  internals unless already public through model fields.

## Decision-Complete Contract

The refine pass must make this section implementation-ready. The final contract
should define the internal collaborators, event names, blocked-outcome
persistence behavior, lock acquire/release boundaries, error handling, and
tests by suite.

## Design Impact

- Maintainability: the phase should remove the large monolithic runner control
  path and give status, planning, stage execution, artifact commit, event, lock,
  failure, blocked-outcome, and result construction concerns smaller homes.
- Extensibility: later executors, event sinks, reliability policies, and cleanup
  work can attach to lifecycle boundaries instead of editing one large method.
- Domain neutrality: lifecycle events and statuses must remain generic pipeline
  facts and must not encode ML, data-science, scheduler, or storage-vendor
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

## Alternatives Rejected

| Alternative | Reason rejected |
| --- | --- |
| Replace `PipelineRunner` with a new public lifecycle engine | The implementation plan requires preserving `PipelineRunner` as the facade before v1. |
| Add event emission directly throughout the current monolithic `run()` method without decomposition | This would meet part of the event requirement while preserving the maintainability problem this phase exists to fix. |
| Implement subprocess/retry/timeout policy while touching lifecycle | These are explicitly deferred roadmap items and would make the Phase 7 PR too large to review. |
| Persist blocked descendants only in `RunResult` | This fails the implementation plan requirement that failed runs have durable blocked outcome records. |

## Debt Introduced

| Debt | Reason accepted | Revisit trigger |
| --- | --- | --- |
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

## Implementation Steps

1. Extract run lifecycle setup and finalization helpers from
   `PipelineRunner.run()`.
2. Extract planning invocation and artifact-store setup behind an internal
   coordinator without changing `ExecutionPlan`.
3. Extract stage coordination for RUN, REUSE, SKIP, BLOCKED, and STALE plan
   actions.
4. Add run lock acquire/release around mutating execution.
5. Add lifecycle event emission through the existing run-store event API.
6. Persist blocked descendants after failed stages using existing blocked
   status records.
7. Update integration/unit tests and docs.

## Test Plan

### Package Suite

- Status: required.
- Expected paths: `tests/package/test_import_boundaries.py` and package export
  tests if public exports change.
- Required assertions or deferral reason: `import loom` must remain cheap and
  runner decomposition must not import optional config dependencies through
  package top-level imports.

### Unit Suite

- Status: required.
- Expected paths: `tests/unit/loom/pipeline/execution/`.
- Required assertions or deferral reason: extracted lifecycle collaborators can
  be tested for lock release, event emission ordering, blocked status writing,
  failure conversion, and result construction without full synthetic pipeline
  setup for every branch.

### Contract Suite

- Status: required.
- Expected paths: `tests/contracts/test_executor_contract.py` and
  `tests/contracts/test_store_contract.py`.
- Required assertions or deferral reason: existing executor and store protocols
  remain valid. Add contract coverage only if implementation changes protocol
  boundaries, which is not expected.

### Integration Suite

- Status: required.
- Expected paths:
  `tests/integration/pipeline/test_local_execution.py`,
  `tests/integration/pipeline/test_local_execution_resume.py`, and
  `tests/integration/pipeline/test_local_execution_failures.py`.
- Required assertions or deferral reason: success, skip, reuse, stage failure,
  invalid outputs, and store commit failures still pass through
  `PipelineRunner`; events are persisted; locks are released; blocked
  descendants are durable.

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
- Required assertions or deferral reason: local runner integration tests rely
  on config extras. Preserve the no-extra/config-extra split and report both
  through `make validate-pr` and `make test-summary`.

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

## Validation Commands

Targeted development commands:

```sh
uv run pytest tests/unit/loom/pipeline/execution/test_lifecycle.py
uv run pytest tests/unit/loom/pipeline/execution/test_runner.py
uv run pytest tests/integration/pipeline/test_local_execution.py
uv run pytest tests/integration/pipeline/test_local_execution_resume.py
uv run pytest tests/integration/pipeline/test_local_execution_failures.py
uv run pytest tests/contracts/test_store_contract.py tests/contracts/test_executor_contract.py
```

Final PR-preparation commands:

```sh
make validate-pr
make test-summary
```

## Handoff Notes For `loom_phase_executor`

- Safe implementation slices:
  - lifecycle/run setup extraction;
  - stage action coordination extraction;
  - lock integration;
  - event integration;
  - blocked descendant persistence;
  - docs and focused test updates.
- Tests to run with each slice: use the targeted unit/integration tests listed
  above; run the contract store/executor tests after lock/event integration.
- Decisions the executor must not revisit: public `PipelineRunner` facade,
  serial local execution, explicit stage factory semantics, run-scoped artifact
  stores, planner action semantics, semantic fingerprint policy, and deferral
  of subprocess/SLURM/container/retry/timeout/cleanup work.
- Conditions that require stopping for the manager: inability to preserve
  existing success/failure/reuse behavior, need for public API changes,
  missing lock release in unavoidable exception paths, or a blocker that would
  require implementing deferred executor/reliability features.

## Refinement And Review Budget Status

- Phase implementation refinement: unused
- PR review: unused

## Completion Notes

- Draft plan: completed by `loom_phase_planner` in this planning pass.
- Final phase execution plan: pending refinement.
- Implementation summary:
- Implementation validation:
- Refinement summary:
- PR preparation:
- Stack maintenance:
- Remaining blockers: none.
