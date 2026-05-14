# Phase 3 Execution Plan: Early Stop And Direct Dispatch

## Metadata

- Status: merged
- Feature focus: Deterministic Sweeps
- PR title: `Deterministic Sweeps - Phase 3: Early Stop And Direct Dispatch`
- Branch: `codex/early-stop-direct-dispatch`
- Worktree:
  `/home/samcantrill/work/loom-worktrees/early-stop-direct-dispatch`
- Phase execution plan path:
  `docs/roadmap/stage-13/phases/early-stop-direct-dispatch.md`
- Full plan: `docs/roadmap/stage-13/implementation-plan.md`
- Source phase: Phase 3, `early-stop-direct-dispatch`
- Stack predecessor: none; Phases 1 and 2 are merged into `develop`.
- Base branch:
  `origin/develop` at `058de1d4d6ec0c9c87dceaa46d3847b577d86364`
- Target branch: `develop`
- PR: [#153](https://github.com/samcantrill/loom/pull/153), merged at
  `a047ed27f1108367aeb6911ea5c622147394b6a1`
- Merge eligibility: complete; root phase PR targeted `develop`, validation
  passed, automated manager review passed after one local blocker fix, GitHub
  CI passed, and the PR was squash-merged.
- Workflow path: expanded path
- Successor dependency notes: Phase 4 should branch from
  `codex/early-stop-direct-dispatch` if Phase 3 is `pr_open` or `approved`
  but not merged; otherwise Phase 4 should branch from updated `develop`.
- Plan quality gate: passed in the implementation plan on 2026-05-14.
- Plan quality gate loop budget: implementation-plan review, refinement, and
  confirmation were used before Phase 1; no blocking findings remain.
- Draft pass: complete for this phase execution plan.
- Refine pass: complete for this expanded-path phase; the artifact is final
  for implementation.
- Setup limitations: the original control checkout has unrelated dirty and
  untracked files; phase work is isolated in the worktree above.
- Blockers: none.

## Objective

Implement cooperative early stopping as a controlled cancellation in ordinary
pipeline execution, then add direct sequential sweep dispatch that runs finite
planned trials through `PipelineRunner`, continues after failed trials, reports
aggregate sweep failure when any required trial fails, and preserves manifest
compatibility checks for resume or open-existing behavior.

## Full-Plan Context

Phase 1 established sweep contracts, dispatch records, feedback records,
unsupported extraction diagnostics, and versioned manifests. Phase 2 added
trusted grid/manual specs, finite providers, deterministic trial IDs, run URI
mapping, and plan-only manifest read/write. Phase 3 now connects those planned
trials to existing ordinary-run execution and lands the early-stop lifecycle
mapping that Phase 4 status aggregation and Phase 5 CLI/collection will read.

Future-phase work must remain out of scope: no queue dispatch, no authority
coordination projection, no full status aggregation, no collection, no
`loom sweep` CLI, no retry/rerun/filter policy, no bounded local concurrency,
and no executor-forced active-stage termination.

## Stack Context

- Root or stacked phase: root phase.
- Current predecessor branch or PR: none; Phase 2 PR
  [#152](https://github.com/samcantrill/loom/pull/152) was squash-merged into
  `develop` and recorded by `058de1d`.
- Why this base branch is correct: Phase 3 depends on the Phase 2 planning
  APIs and manifests, and the current `origin/develop` tip includes the Phase
  2 merge and metadata updates.
- Retarget/rebase plan after predecessor merge: none for this root phase.
- Branch cleanup constraints: this branch can be deleted after merge only if no
  successor phase still targets or branches from it.

## Source Phase Summary

- Goal: implement cooperative early-stop lifecycle mapping and direct
  sequential sweep dispatch through ordinary `PipelineRunner` runs.
- Required scope: `context.stop_early(...)`, a typed early-stop signal,
  lifecycle helpers for `CANCELLED` run/stage records with
  `LifecycleReason(code="early_stop")`, runner/executor handling that does not
  treat early stop as generic failure, direct dispatch over planned-trial
  dispatch records, continuation after failed trials, failed aggregate result
  when any required trial fails, and compatible manifest open-existing checks.
- Required checkpoints: synthetic stages can stop early and persist
  cancellation reason metadata; direct dispatch builds one `RunRequest` per
  trial using planned run URIs and metadata; failed trials do not prevent later
  trials from running; incompatible manifests block open-existing dispatch.
- Acceptance criteria: focused unit, contract, and integration evidence covers
  helper/signal validation, lifecycle mapping, direct dispatch success/failure,
  early-stop outcomes, manifest compatibility, and run request metadata.

## Current Source And Harness Findings

- Existing files or modules that constrain this phase:
  - `src/loom/pipeline/context.py` owns `StageContext`; it currently validates
    plain-data mappings and has no early-stop helper.
  - `src/loom/pipeline/executors/local.py` catches stage exceptions and turns
    them into `StageExecutionResult(status=FAILED)`, so early stop needs an
    explicit executor path before generic exception handling.
  - `src/loom/pipeline/execution/stage_worker.py` wraps durable worker
    execution and writes `StageWorkerResult`; subprocess-worker behavior may
    need the same early-stop result shape if the current model allows it
    without broad worker protocol churn.
  - `src/loom/pipeline/execution/models.py` currently allows
    `StageExecutionResult` and `StageWorkerResult` statuses of only
    `SUCCEEDED` or `FAILED`; this phase may narrow-expand those result models
    to allow `CANCELLED` for the early-stop signal only.
  - `src/loom/pipeline/execution/lifecycle.py` has failed/succeeded/skipped/
    blocked status writers but no cancelled writer or run cancellation helper.
  - `src/loom/pipeline/execution/runner.py` currently writes failed run status
    when an execution outcome carries `ExecutionFailure`; early stop should
    produce a non-failure controlled cancellation outcome that blocks remaining
    dependent stages in the ordinary run but is not an `ExecutionFailure`.
  - `src/loom/pipeline/sweep/dispatch.py` has adapter-neutral dispatch request
    and result records but no direct adapter behavior yet.
  - `src/loom/pipeline/sweep/runner.py` has plan-only APIs, manifest
    compatibility checks, and stable trial/run URI helpers from Phase 2.
- Existing tests or harness behavior:
  - `tests/unit/loom/pipeline/execution/test_runner.py` already exercises
    runner behavior with authority-backed local stores and fake executors.
  - Existing sweep tests live under `tests/unit/loom/pipeline/sweep/`,
    `tests/contracts/`, and `tests/integration/pipeline/sweep/`.
  - Package tests lock `loom.pipeline.sweep.__all__` and import-boundary
    behavior.
- Import-boundary or dependency constraints:
  - Keep `loom.pipeline.sweep` import-light and below CLI, queue controllers,
    authority services, and project code.
  - Do not import optimizer, metric, queue-controller, SLURM, remote service,
    or downstream project packages.
  - Use ordinary `RunRequest`, `RunResult`, `RunStatus`, `StageStatus`, and
    `LifecycleReason` vocabulary instead of adding core lifecycle states.

## In-Scope Work

- Add a typed `EarlyStopSignal` and helper function in
  `src/loom/pipeline/sweep/early_stopping.py` with message and plain-data
  detail validation.
- Add `StageContext.stop_early(message, detail=None)` that raises the same
  typed signal and remains domain-neutral.
- Add lifecycle helpers that write `StageStatus.CANCELLED` and
  `RunStatus.CANCELLED` records with structured reason metadata containing
  `LifecycleReason(code="early_stop")`, preserving the user message and detail.
- Update local runner/executor paths to catch the typed signal before generic
  failure handling and persist controlled cancellation rather than
  `ExecutionFailure`.
- Preserve ordinary runner behavior for non-early-stop exceptions and output
  validation failures.
- Implement a direct sequential sweep dispatcher that consumes
  `SweepDispatchRequest` records derived from `SweepPlan` trials, builds one
  `RunRequest` per trial with stable `run_uri`, `open_existing` when requested,
  `failure_policy=FailurePolicy(stop_on_first_failure=True)`, and sweep/trial
  metadata, then delegates each trial to `PipelineRunner`.
- Add sweep run result records that summarize direct dispatch results and
  aggregate success, failed, and early-stopped trial counts without becoming
  full Phase 4 status aggregation.
- Implement manifest compatibility checks for direct dispatch open-existing or
  resume paths by reusing Phase 2 `check_existing_sweep_plan`.
- Add focused package, unit, contract, and integration tests for the behavior
  above.

## Out-of-Scope Work

- Queue dispatch, queue enqueue shape, queue status, or queue controller loops.
- Authority-backed sweep/trial coordination writes.
- Full status aggregation from run, queue, coordination, or catalog read
  models.
- Collection APIs, artifact payload extraction, concrete metrics, or objective
  semantics.
- `loom sweep` CLI commands and output formatting.
- Retry, rerun, failed-only filtering, from-trial selection, scheduled-trial
  cancellation, active executor termination, bounded local concurrency,
  distributed controllers, or SLURM per-trial submission.
- New core lifecycle statuses such as `STOPPED` or `EARLY_STOPPED`.

## Assumptions

- Existing `RunStatus.CANCELLED`, `StageStatus.CANCELLED`, and
  `LifecycleReason` metadata are sufficient to represent early stop.
- Early stop is a controlled cancellation of the current ordinary run, not an
  execution failure and not a successful stage with missing outputs.
- For multi-stage ordinary runs, downstream unresolved stages may be marked
  blocked after an early-stopped stage because the run cannot produce required
  outputs; Phase 4/5 sweep presentation will derive trial-level
  `early_stopped` from reason metadata.
- Direct dispatch receives a finite `SweepPlan`; adaptive or unsized providers
  remain out of scope.
- Direct dispatch can accept a caller-provided `RunRequest` template or
  equivalent request inputs, but must set the planned trial `run_uri` and
  sweep/trial metadata per trial.

## Scope Contract

- `context.stop_early(...)` must raise a typed signal and must not change the
  `Stage.run()` return contract.
- Early-stop detail must be plain-data-compatible. The helper must reject
  invalid detail before raising the signal.
- The persisted lifecycle representation is `CANCELLED` plus structured reason
  metadata with code `early_stop`; no new core status enum value may be added.
- The typed early-stop signal must be caught before generic exception handling
  in in-process execution. Any subprocess-worker support added in this phase
  must preserve the worker handoff schema's backward compatibility and stay
  limited to `CANCELLED`.
- Direct dispatch must consume adapter-neutral dispatch records and Phase 2
  plan/manifests. It must not read provider internals or perform config merge.
- Direct dispatch must run remaining trials after a trial returns `FAILED` or
  `CANCELLED`; aggregate sweep success requires every required trial to
  complete without a failed ordinary run.
- Compatible existing manifests may be opened for dispatch; incompatible
  manifests must surface structured diagnostics and must not silently overwrite.

## Design Impact

- Maintainability: early-stop behavior stays isolated to a typed signal,
  lifecycle helpers, and the existing execution result path; direct dispatch
  stays in sweep modules and delegates ordinary-run execution to
  `PipelineRunner`.
- Extensibility: future retry/timeout/scheduler policies can distinguish
  controlled cancellation from generic failures through reason metadata without
  changing trial manifests.
- Domain neutrality: messages and detail are generic plain data; no metric,
  objective, optimizer, or project-specific semantics are required.
- Source-tree boundaries: context and execution lifecycle handle ordinary-run
  cancellation; sweep dispatch builds `RunRequest` values but does not execute
  stages directly; queue/status/CLI remain later-phase owners.

## Future Compatibility

- Phase 4 can derive `early_stopped` from `CANCELLED` status plus
  `early_stop` reason metadata without reworking core runner behavior.
- Phase 4 queue dispatch can reuse the same `SweepDispatchRequest` records and
  sweep/trial metadata that direct dispatch writes into `RunRequest`.
- Phase 5 CLI can call public direct dispatch APIs without parsing manifests
  directly.
- V19 reliability can add retry/timeout/cancellation policies around the
  controlled-cancellation reason instead of depending on exception text.

## Alternatives Rejected

| Alternative | Reason rejected |
| --- | --- |
| Add a new `EARLY_STOPPED` core run or stage status | The full plan explicitly keeps early stop as `CANCELLED` plus structured reason metadata to avoid broad lifecycle churn. |
| Treat early stop as `StageStatus.FAILED` with a special failure type | That would make cooperative user intent indistinguishable from errors for retry/status consumers and would violate the controlled-cancellation design. |
| Change `Stage.run()` to return a stage outcome envelope | This would broaden every stage implementation and is unnecessary for a narrow cooperative stop helper. |
| Let sweep dispatch execute stage objects directly | This would duplicate `PipelineRunner` lifecycle, provenance, planning, artifact, and store behavior. |
| Stop the direct sweep after the first failed trial | The approved v13 behavior requires failed-trial visibility while still running remaining trials. |

## Debt Introduced

| Debt | Reason accepted | Revisit trigger |
| --- | --- | --- |
| Aggregate direct sweep status is intentionally simple and dispatch-result based | Phase 4 owns full status aggregation from run, queue, coordination, and catalog read models | Phase 4 cannot derive accurate counts from the Phase 3 run result and lifecycle records |
| Subprocess early-stop support may be limited to the existing worker handoff surface | This phase must avoid broad worker protocol refactors | A real subprocess early-stop path cannot persist `CANCELLED` without schema-compatible worker result widening |

## Reviewability

- Expected PR size and shape: medium, with one early-stop/lifecycle slice, one
  direct-dispatch slice, and focused tests.
- Files and areas to inspect:
  - `src/loom/pipeline/context.py`
  - `src/loom/pipeline/executors/local.py`
  - `src/loom/pipeline/execution/lifecycle.py`
  - `src/loom/pipeline/execution/models.py`
  - `src/loom/pipeline/execution/runner.py`
  - `src/loom/pipeline/execution/stage_worker.py` if worker result widening is
    needed
  - `src/loom/pipeline/sweep/early_stopping.py`
  - `src/loom/pipeline/sweep/dispatch.py`
  - `src/loom/pipeline/sweep/runner.py`
  - matching package, unit, contract, and integration tests
- Scope-control checks: no queue dispatch, no coordination projection, no CLI,
  no collection, no new lifecycle enum values, no metric/objective semantics,
  and no stage-return contract change.

## Implementation Steps

1. Add early-stop signal/helper exports and `StageContext.stop_early(...)`
   with plain-data validation and unit tests.
2. Add `CANCELLED` lifecycle helpers and update execution result models and
   local execution handling so early stop persists structured cancellation
   metadata instead of generic failure.
3. Update `PipelineRunner` handling for cancelled stage outcomes, including
   run-level `CANCELLED` status, blocked unresolved stages where needed, and
   result objects that expose cancellation without `ExecutionFailure`.
4. Implement direct sweep dispatch and sweep run result models over
   `SweepPlan`, `SweepDispatchRequest`, `SweepDispatchResult`, `RunRequest`,
   and `PipelineRunner`.
5. Add compatible open-existing checks for direct dispatch and tests for
   incompatible manifests, run request metadata, success, failure continuation,
   and early-stop trials.
6. Refresh public exports and package/import-boundary assertions without
   pulling CLI, queue, authority services, optimizer packages, or project code
   into `loom.pipeline.sweep`.

## Test Plan

### Package Suite

- Status: required
- Expected paths:
  - `tests/package/test_pipeline_api.py`
  - `tests/package/test_import_boundaries.py`
- Required assertions or deferral reason: new public sweep exports are stable
  and import-light; no optional optimizer, CLI, queue-controller, or project
  imports are introduced.

### Unit Suite

- Status: required
- Expected paths:
  - `tests/unit/loom/pipeline/test_context.py` or existing context unit path
  - `tests/unit/loom/pipeline/execution/test_runner.py`
  - `tests/unit/loom/pipeline/sweep/test_direct_dispatch.py`
- Required assertions or deferral reason: early-stop helper validates message
  and plain-data detail; local executor and runner persist `CANCELLED` plus
  `early_stop`; direct dispatch builds expected `RunRequest` metadata and
  continues after failed trials.

### Contract Suite

- Status: required
- Expected paths:
  - `tests/contracts/test_sweep_dispatch_contract.py`
  - existing sweep manifest/provider contract tests as affected
- Required assertions or deferral reason: direct dispatch consumes
  adapter-neutral dispatch records and returns structured dispatch/run results
  without provider internals.

### Integration Suite

- Status: required
- Expected paths:
  - `tests/integration/pipeline/test_pipeline_execution.py` or focused
    execution integration path
  - `tests/integration/pipeline/sweep/test_direct_dispatch.py`
- Required assertions or deferral reason: synthetic pipeline stages run through
  `PipelineRunner`; one stage can call `context.stop_early(...)`; direct sweep
  dispatch runs success, failure, and early-stop trials as ordinary runs.

### E2E Suite

- Status: deferred
- Expected paths: none for this phase.
- Required assertions or deferral reason: Phase 5 owns CLI/e2e workflow
  coverage after status, collection, and CLI commands exist.

### Opt-In Suites

- Status: deferred
- Markers affected: none expected.
- Required assertions or deferral reason: no network, cluster, remote store,
  optimizer, or external service behavior is in scope.

## Risks

- Early-stop signal handling could be swallowed by the local executor or worker
  paths and recorded as a generic stage exception.
- Allowing `CANCELLED` in execution result models could broaden more behavior
  than intended if not limited to early stop tests and reason metadata.
- Direct dispatch could accidentally become status aggregation or retry policy
  if aggregate result behavior is not kept simple.
- `open_existing` trial execution must not overwrite incompatible manifests.

## Validation Commands

Targeted development commands:

```sh
uv run pytest tests/unit/loom/pipeline/test_context.py tests/unit/loom/pipeline/execution/test_runner.py tests/unit/loom/pipeline/sweep tests/contracts/test_sweep_dispatch_contract.py tests/integration/pipeline/sweep
uv run ruff check src/loom/pipeline/context.py src/loom/pipeline/executors/local.py src/loom/pipeline/execution/lifecycle.py src/loom/pipeline/execution/models.py src/loom/pipeline/execution/runner.py src/loom/pipeline/sweep tests/unit/loom/pipeline tests/contracts/test_sweep_dispatch_contract.py tests/integration/pipeline/sweep
```

Final PR-preparation commands:

```sh
make validate-pr
make test-summary
```

## Handoff Notes For `loom_phase_executor`

- Safe implementation slices: early-stop signal/context helper first,
  lifecycle/runner cancellation second, direct dispatch third, tests and export
  cleanup last.
- Tests to run with each slice: context/signal tests after slice 1;
  runner/executor tests after slices 2 and 3; sweep direct-dispatch tests after
  slice 4; package/import and integration tests before PR prep.
- Decisions the executor must not revisit: no new core statuses, no
  `Stage.run()` outcome envelope, no first-failure stop for direct sweeps, no
  queue/coordination/status/CLI/collection behavior.
- Conditions that require stopping for the manager: controlled cancellation
  cannot be represented without broad lifecycle enum changes; direct dispatch
  requires config merge semantics inside sweep; `PipelineRunner` cannot expose
  enough trial outcome information without duplicating runner internals.

## Refinement And Review Budget Status

- Phase implementation refinement: not needed; targeted and final validation
  passed after the implementation slice.
- PR review: used by manager before merge; one subprocess-worker CLI
  cancellation handling blocker was found and fixed locally.
- Blocker resolution: 1/3 used for the subprocess worker CLI cancellation
  exit-code blocker.

## Completion Notes

- Draft plan: completed locally on 2026-05-14.
- Final phase execution plan: completed locally on 2026-05-14.
- Implementation summary: Added a typed early-stop signal and context helper,
  persisted early stop as `CANCELLED` plus `LifecycleReason(code="early_stop")`,
  widened execution result handling for controlled cancellation, preserved
  local/subprocess worker propagation, and added direct sequential sweep
  dispatch over Phase 1 dispatch records and Phase 2 plans.
- Implementation validation: Targeted Phase 3 suite passed (`52 passed`);
  adjacent execution/executor suites passed (`71 passed`); package/import
  boundary suite passed (`45 passed`); `make validate-pr` passed; `make
  test-summary` passed and wrote `build/test-summary.md`.
- Refinement summary: Not needed; targeted Ruff, targeted Pyright, targeted
  pytest, full PR validation, and suite summary all passed after the
  implementation commit.
- Review summary: Manager review found that subprocess-worker early-stop
  results were propagated as `CANCELLED` but the stage CLI still returned a
  nonzero exit for worker `CANCELLED`. The fix updates the CLI to treat
  `SUCCEEDED` and `CANCELLED` worker results as successful handoff outcomes and
  adds unit coverage.
- Blocker-resolution summary: 1/3 used for the subprocess worker CLI
  cancellation exit-code blocker; final `make validate-pr` and `make
  test-summary` passed after the fix.
- PR preparation: PR body drafted in
  `docs/roadmap/stage-13/phases/early-stop-direct-dispatch-pr-body.md`; PR
  [#153](https://github.com/samcantrill/loom/pull/153) opened against
  `develop` and verified with `baseRefName=develop`,
  `headRefName=codex/early-stop-direct-dispatch`, `state=OPEN`.
- Merge verification: Before merge, PR
  [#153](https://github.com/samcantrill/loom/pull/153) was verified with
  `baseRefName=develop`, `headRefName=codex/early-stop-direct-dispatch`,
  `state=OPEN`, clean merge state, and GitHub CI `checks` success on
  `c2068e0131682740fca616b2946efc724419d32d`.
- Merge result: Squash-merged into `develop` at
  `a047ed27f1108367aeb6911ea5c622147394b6a1`.
- Stack maintenance: No successor depended on
  `codex/early-stop-direct-dispatch`; the remote branch was deleted after
  merge. Phase 4 should branch from updated `develop`.
- Remaining blockers: none.
