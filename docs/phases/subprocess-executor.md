# Phase 3 Execution Plan: Subprocess Executor And Serial Run Integration

## Metadata

- Status: pr_open
- Feature focus: Stage Worker
- PR title: `Stage Worker - Phase 3: Subprocess Executor and Serial Run Integration`
- Branch: `codex/subprocess-executor`
- Worktree: `/home/samcantrill/work/loom-worktrees/subprocess-executor`
- Phase execution plan path: `docs/phases/subprocess-executor.md`
- Full plan: `docs/implementation-plans/implementation-plan-v5.md`
- Source phase: Phase 3 - Subprocess Executor And Serial Run Integration
- Stack predecessor: none
- Base branch: `develop`
- Target branch: `develop`
- Merge eligibility: root phase PR, merge-eligible when automated review, validation, CI, and scope gates pass
- Workflow path: expanded path, because this phase adds real process launch, whole-run executor selection, parent/worker failure normalization, and CLI integration across execution, executors, runtime capabilities, and tests
- Successor dependency notes: Phase 4 must build selected-executor preflight and diagnostics UX on the subprocess executor metadata and failure records from this phase. Phase 5 must harden examples and docs without changing the subprocess execution contract.
- Plan quality gate: passed on 2026-05-07 after initial review, one refinement pass, and confirmation review
- Plan quality gate loop budget: consumed as recorded in `docs/implementation-plans/implementation-plan-v5.md`
- Draft pass: completed by manager on 2026-05-07
- Refine pass: completed by manager on 2026-05-07 for expanded path
- Setup limitations: none; Phases 1 and 2 are merged on `develop`, and this worktree was created from `develop`.
- Blockers: none known

## Objective

Implement a production `SubprocessExecutor` that runs each prepared stage attempt through the public `loom stage run` worker command, then returns a normal `StageExecutionResult` for the parent runner to finalize through the existing lifecycle. Wire `loom run CONFIG --executor subprocess` into the current CLI path for serial whole-run execution.

## Full-Plan Context

V5 Phase 1 created the prepared attempt and worker result persistence contract. Phase 2 added direct durable worker execution and the `loom stage run` command. Phase 3 proves that contract through real process isolation while preserving parent-owned commit semantics. Phase 4 remains responsible for selected-executor Python/worker-command preflight and concise failure diagnostics UX. Phase 5 remains responsible for broader examples, docs, and hardening.

## Stack Context

- Root or stacked phase: root phase
- Current predecessor branch or PR: none; Phase 2 PR #78 is merged
- Why this base branch is correct: all earlier v5 phases are merged into `develop`
- Retarget/rebase plan after predecessor merge: none
- Branch cleanup constraints: branch may be deleted after the Phase 3 PR is merged if no successor branch depends on it

## Source Phase Summary

- Goal: add production subprocess execution and serial whole-run integration through the normal parent runner lifecycle.
- Required scope: subprocess command construction, worker process launch, stdout/stderr capture, process metadata, result-file readback, executor descriptor registration, CLI executor selection, serial stage orchestration, conflict handling, signal metadata, fake process runner tests, and real subprocess integration tests.
- Required checkpoints: local and subprocess success runs produce equivalent final persisted outputs/status/result metadata; failure runs preserve structured failure, log paths, traceback path when present, and redacted executor metadata; missing, invalid, stale, and conflicting worker results fail explicitly; nonzero exits and signal terminations always fail.
- Acceptance criteria: `loom run --executor subprocess` runs a small pipeline end to end, current run preflight recognizes the selected subprocess executor, and parent finalization remains the only code path that writes final outputs, failures, provenance, stage status, and run status.

## Current Source And Harness Findings

- Existing files or modules that constrain this phase: `PipelineRunner._run_stage` currently prepares inputs/fingerprints/log paths, calls `self.executor.execute()`, and owns final output validation, artifact index, provenance, stage status, and run status finalization. `prepare_stage_attempt` writes `worker_request.json`, latest-compatible inputs/fingerprint records, workspace, and PENDING prepared status. `stage_worker.py` can reconstruct and run one prepared attempt and refuses duplicate `worker_result.json`. `LocalExecutor` returns `StageExecutionResult` and captures stage stdout/stderr when requested. `RunStore` exposes worker request/result APIs and local path helpers.
- Existing CLI constraints: `loom run` currently rejects every executor other than `local` before preflight and constructs `PipelineRunner` without an explicit executor. `loom stage run` is already registered and supports `--run-uri`, `--stage`, `--attempt`, `--format json`, and direct-worker exit codes.
- Existing runtime/preflight constraints: `DEFAULT_EXECUTOR_DESCRIPTOR_REGISTRY` currently recognizes `local` only, so Phase 3 must register a subprocess descriptor to avoid generic unknown-executor rejection. Phase 4 owns actual worker-command/Python availability preflight.
- Existing tests or harness behavior: package tests assert executor public exports and import boundaries; unit tests cover local executor, runner finalization, CLI run parsing, runtime capabilities, stage worker behavior, and store result validation; integration/e2e tests cover local CLI runs and direct worker integration.
- Import-boundary or dependency constraints: `loom.pipeline.executors.subprocess` may import standard-library `subprocess`; `loom.pipeline.execution` must remain CLI-free; `loom.cli` may select executor factories lazily; no heavyweight runtime dependency is needed.

## In-Scope Work

- Add `SubprocessExecutor` and small process-result helpers under `loom.pipeline.executors`, using standard-library `subprocess`.
- Build a worker command that invokes the current Python interpreter and `loom.cli.main:main` with `stage run --run-uri RUN_URI --stage STAGE --attempt N --format json`.
- Capture subprocess stdout/stderr in the parent process, preserve redacted command/process metadata, and avoid persisting full environment values.
- Read and validate `worker_result.json` through run-store APIs after the worker exits.
- Normalize missing, invalid, mismatched, stale, process-failed, signal-terminated, and structured/process-conflict outcomes into failed `StageExecutionResult` values with `ExecutionFailure` metadata.
- Update `PipelineRunner` so subprocess execution prepares one durable attempt with `prepare_stage_attempt`, marks it running, delegates to `SubprocessExecutor`, and then uses the existing parent finalization path.
- Keep local executor behavior stable except for narrow helper extraction needed to avoid duplicating preparation/finalization logic.
- Register subprocess executor exports and runtime descriptor/capability metadata.
- Wire `loom run CONFIG --executor subprocess` through the existing CLI run path and pass `SubprocessExecutor` into the runner.
- Update focused source docs for the implemented whole-run subprocess path.

## Out-of-Scope Work

- Worker command or Python executable availability preflight beyond descriptor registration required for normal selected-executor recognition.
- New diagnostics command families or rich CLI failure formatting; Phase 4 owns diagnostics UX.
- Parallel scheduling, worker pools, retries, timeout enforcement, leases, and multi-coordinator safety.
- SLURM/container command construction, plugin-discovered executors, remote stores, and cleanup policy.
- Worker-side finalization or any second runner in the subprocess executor.
- Full attempt archive directories or retry history layout.

## Assumptions

- Phase 3 may use `sys.executable` plus a small Python `-c` command that calls `loom.cli.main.main()` for deterministic worker launch in source-tree and installed environments.
- The direct worker JSON stdout is only a process diagnostic; the parent's source of truth is the persisted `worker_result.json` read through `RunStore`.
- Current latest-stage-compatible `worker_result.json` layout supports one active attempt per stage, which is enough for serial subprocess execution.
- Subprocess process stdout/stderr capture is recorded as redacted metadata and snippets/counts where useful; stage stdout/stderr paths remain the worker result's `stdout_path` and `stderr_path`.
- If the worker writes a valid failure result and exits nonzero as documented, parent finalization should use that structured worker failure while adding process metadata.

## Scope Contract

`SubprocessExecutor` is an `Executor`: its only public execution method is `execute(StageExecutionRequest) -> StageExecutionResult`. It must launch exactly one `loom stage run` worker for the request's `(run_uri, stage.name, attempt)`, then read the worker handoff from durable store state. The subprocess executor must not construct or run stage objects directly, validate final outputs, write final stage outputs/failure/provenance/status, write run status, or plan additional stages. The parent runner remains responsible for final commits, artifact indexing, and run failure handling. Nonzero exit codes, signal terminations, missing results, invalid results, identity mismatches, and structured-success/process-failure conflicts all produce failed `StageExecutionResult` values.

## Design Impact

- Maintainability: subprocess behavior lives behind the existing executor protocol while parent lifecycle code remains the single finalization authority.
- Extensibility: future SLURM and container executors can reuse command construction, process/result normalization policy, and worker handoff validation.
- Domain neutrality: subprocess metadata contains Loom command/process/runtime facts only.
- Source-tree boundaries: `loom.pipeline.executors` owns process launch/readback; `loom.pipeline.execution` owns preparation and parent lifecycle; `loom.pipeline.stores` owns durable files; `loom.cli` only selects the executor and presents existing run results.

## Future Compatibility

- The process runner should be injectable so later scheduler/container adapters and deterministic tests can reuse normalization without launching real workers.
- Signal facts must remain separate from exit codes for later diagnostics and reliability policies.
- Descriptor registration should remain import-light and independent of executor implementation imports.
- Metadata should leave room for future worker command variants without committing to SLURM/container command construction now.

## Alternatives Rejected

| Alternative | Reason rejected |
| --- | --- |
| Subprocess executor directly imports and runs stage code | Creates a second runner and bypasses the public worker command. |
| Parent parses worker JSON stdout as the source of truth | Durable result handoff is the stable executor contract; stdout is not reliable enough for finalization. |
| Accepting structured success despite nonzero process exit | Violates the plan's conflict policy and hides process-level failures. |
| Deferring subprocess descriptor registration to Phase 4 | `loom run --executor subprocess` must pass the current selected-executor gate in Phase 3. |
| Rewriting all local runner preparation around worker requests | Broader than needed; Phase 3 should change only the subprocess path unless a narrow helper extraction prevents duplication. |

## Debt Introduced

| Debt | Reason accepted | Revisit trigger |
| --- | --- | --- |
| No timeout enforcement | Timeout policy belongs to later reliability/executor work. | Reliability roadmap or executor-specific timeout configuration is introduced. |
| No parallel subprocess scheduling | V5 validates serial process isolation first. | A later roadmap adds parallel scheduling or worker pools. |
| Process stdout/stderr are metadata rather than first-class log streams | Existing stage log contract has stdout/stderr paths owned by worker execution. | Diagnostics work needs first-class parent process log files. |
| Current interpreter launch command is local/Python-specific | Phase 3 targets the local subprocess executor only. | Scheduler, container, or plugin executors need command adapters. |

## Reviewability

- Expected PR size and shape: medium-to-large executor/runner/CLI/test PR with no Phase 4 diagnostics UX.
- Files and areas to inspect: new subprocess executor module, executor exports, runner preparation branch, CLI run executor factory, runtime descriptor registration, source docs, package/unit/contract/integration/e2e tests.
- Scope-control checks: subprocess executor does not import stage factories or run user code directly; execution does not import `loom.cli`; CLI does not mutate store state beyond invoking runner; worker-command/Python preflight checks remain out of scope; no attempt archive layout; no parallel scheduling.

## Implementation Steps

1. Add subprocess process-result models/helpers, command construction, redaction, and result readback/normalization in `loom.pipeline.executors.subprocess`.
2. Update executor exports and runtime descriptor metadata so `subprocess` is importable and recognized by selected-executor validation.
3. Add the parent runner subprocess path: prepare durable attempt, mark it running, call the executor, and reuse existing success/failure finalization.
4. Wire `loom run --executor subprocess` through CLI executor selection/factory and keep unsupported executor errors for unknown names.
5. Add package, unit, contract, integration, and e2e coverage for subprocess launch, process/result conflicts, signal mapping, CLI selection, and persisted run equivalence.
6. Update focused execution/CLI docs and phase completion notes.

## Test Plan

### Package Suite

- Status: required
- Expected paths: `tests/package/test_pipeline_execution_api.py` and package executor/import-boundary coverage as needed.
- Required assertions or deferral reason: `SubprocessExecutor` is exported intentionally, executor package imports stay cheap, and runtime capability metadata remains import-light.

### Unit Suite

- Status: required
- Expected paths: new `tests/unit/loom/pipeline/executors/test_subprocess_executor.py`, updates to `tests/unit/loom/pipeline/execution/test_runner.py`, `tests/unit/loom/pipeline/test_executor_capabilities.py`, and `tests/unit/loom/cli/test_run.py` or adjacent CLI run tests.
- Required assertions or deferral reason: command construction, redacted metadata, process exit/signal mapping, missing result, invalid result, identity mismatch, structured/process conflict semantics, subprocess preparation branch, executor factory selection, and unknown executor errors.

### Contract Suite

- Status: required
- Expected paths: `tests/contracts/test_executor_contract.py`, `tests/contracts/test_executor_capabilities_contract.py`, and `tests/contracts/test_stage_worker_contract.py`.
- Required assertions or deferral reason: `SubprocessExecutor` satisfies the executor protocol, subprocess descriptor resolves without importing executor implementation, parent/worker commit boundary remains enforced, and result identity validation is stable.

### Integration Suite

- Status: required
- Expected paths: new `tests/integration/pipeline/test_subprocess_executor.py` or updates near `tests/integration/pipeline/test_stage_worker_integration.py`.
- Required assertions or deferral reason: synthetic success/failure pipelines run through real subprocess worker processes using temporary run directories; final persisted outputs/status/failure/provenance match parent-owned semantics; missing/invalid result handling can be exercised with an injectable process runner.

### E2E Suite

- Status: required
- Expected paths: `tests/e2e/test_cli_core.py` or a new subprocess CLI smoke module.
- Required assertions or deferral reason: `loom run CONFIG --executor subprocess --format json` succeeds for a small pipeline, and a small failing pipeline returns a pipeline failure with persisted failure/log references.

### Opt-In Suites

- Status: deferred
- Markers affected: none expected beyond existing optional dependency markers.
- Required assertions or deferral reason: Phase 3 uses local deterministic subprocesses only and does not require network, SLURM, containers, remote stores, or heavy optional dependencies.

## Risks

- Runner changes could accidentally duplicate finalization logic. Keep subprocess finalization in the same success/failure branches used for local `StageExecutionResult`.
- Process-result conflict handling could hide useful worker failures. Prefer preserving valid worker failure metadata and attaching process facts in executor metadata/details.
- CLI worker launch through the current interpreter can be brittle if `PYTHONPATH` differs. Integration tests must cover source-tree subprocess execution.
- Descriptor registration must not make runtime capability imports load executor implementation or diagnostics modules.

## Validation Commands

Targeted development commands:

```sh
uv run pytest tests/package/test_pipeline_execution_api.py tests/contracts/test_executor_contract.py tests/contracts/test_executor_capabilities_contract.py tests/unit/loom/pipeline/executors/test_subprocess_executor.py tests/unit/loom/pipeline/execution/test_runner.py tests/unit/loom/cli/test_run.py tests/integration/pipeline/test_subprocess_executor_integration.py tests/e2e/test_cli_core.py
uv run pyright src/loom/pipeline/executors src/loom/pipeline/execution src/loom/cli tests/unit/loom/pipeline/executors/test_subprocess_executor.py tests/integration/pipeline/test_subprocess_executor_integration.py
```

Final PR-preparation commands:

```sh
make validate-pr
make test-summary
```

## Handoff Notes For `loom_phase_executor`

- Safe implementation slices: subprocess executor helpers first, runner integration second, CLI/runtime descriptor wiring third, tests/docs last or alongside each slice.
- Tests to run with each slice: subprocess executor unit tests after helper work; runner unit/contract tests after parent lifecycle changes; CLI/runtime tests after factory/descriptor wiring; integration/e2e after real process launch.
- Decisions the executor must not revisit: durable worker result is source of truth, nonzero process exit always fails, signal is separate from exit code, parent owns final commits, Phase 4 owns worker/Python availability preflight and diagnostics UX, and subprocess execution is serial.
- Conditions that require stopping for the manager: a need for a worker `--config` input, direct stage execution inside the subprocess executor, broad local runner rewrite, new dependencies, first-class parent process log files, timeout enforcement, retries, parallelism, or attempt archive directories.

## Refinement And Review Budget Status

- Phase implementation refinement: unused
- PR review: unused
- Blocker resolution: 0/3 used

## Completion Notes

- Draft plan: completed by manager on 2026-05-07.
- Final phase execution plan: refined by manager on 2026-05-07 before implementation to clarify parent finalization, command launch, process/result conflict policy, and Phase 4 preflight boundaries.
- Implementation summary: added `SubprocessExecutor`, subprocess command
  construction, injected process-runner support, process metadata redaction,
  worker-result readback, missing/invalid/mismatched result failures,
  structured/process conflict failures, and signal-vs-exit-code mapping. Wired
  the parent runner's prepared-worker path so subprocess stages write
  `worker_request.json`, mark the stage running, invoke one `loom stage run`
  worker, and then reuse parent-owned finalization for outputs, failures,
  provenance, artifact indexes, stage status, and run status. Registered the
  import-light subprocess runtime descriptor and CLI executor selection for
  `loom run CONFIG --executor subprocess`. Updated execution and CLI docs for
  current subprocess behavior and Phase 4 preflight boundaries.
- Implementation validation:
  - Focused tests passed:
    `uv run pytest tests/unit/loom/pipeline/executors/test_subprocess_executor.py tests/unit/loom/pipeline/execution/test_runner.py tests/unit/loom/cli/test_run.py tests/contracts/test_executor_contract.py tests/contracts/test_executor_capabilities_contract.py tests/package/test_pipeline_executor_api.py tests/integration/pipeline/test_subprocess_executor_integration.py tests/e2e/test_cli_core.py`
    with 36 passed and 1 skipped.
  - Focused Ruff passed for touched implementation and test files.
  - Focused Pyright passed for touched implementation and test files.
  - `make validate-pr` passed: Ruff, Pyright with config extra, default test
    harness, config-extra test harness, and build.
  - `make test-summary` passed and wrote `build/test-summary.md`: package 50
    passed/1 skipped; unit 587 passed/1 skipped; contract 55 passed/2 skipped;
    integration 20 passed/7 skipped/7 deselected; e2e 18 passed; config-extra
    400 passed/730 deselected.
- Refinement summary: not needed after focused fixes; full validation passed.
- Blocker-resolution summary: none used
- PR preparation: PR opened on 2026-05-07:
  https://github.com/samcantrill/loom/pull/79. Verified base `develop`, head
  `codex/subprocess-executor`, state `OPEN`.
- Stack maintenance: none required; all earlier phases are merged into `develop`
- Remaining blockers: none known
