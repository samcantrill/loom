# Phase 2 Execution Plan: Generic Continuation Commands

## Metadata

- Status: draft phase execution plan
- Feature focus: SLURM Script Planning
- PR title: `SLURM Script Planning - Phase 2: Generic Continuation Commands`
- Branch: `codex/slurm-continuation-commands`
- Worktree: `/home/samcantrill/work/loom-worktrees/slurm-continuation-commands`
- Phase execution plan path: `docs/phases/slurm-continuation-commands.md`
- Full plan: `docs/implementation-plans/implementation-plan-v6.md`
- Source phase: Phase 2 - Generic Continuation Commands
- Stack predecessor: none; Phase 1 is merged into `develop`
- Base branch: `develop`
- Target branch: `develop`
- Merge eligibility: root phase; merge-eligible when the PR targets `develop`, automated review passes, and validation/CI passes
- Workflow path: expanded path
- Successor dependency notes: Phase 3 will consume the stable continuation command shapes and recursive-submitted-executor rejection contract when it builds SLURM model command argv.
- Plan quality gate: passed on 2026-05-08 after initial review, one refinement pass, and confirmation review
- Plan quality gate loop budget: initial review used, refinement used, confirmation review used
- Draft pass: completed by `loom_phase_planner`
- Refine pass: pending for expanded path
- Setup limitations: none known. GitHub auth was verified with network access, `gh auth setup-git` succeeded, `git fetch origin` succeeded, and this worktree was created from `develop` at `74237d2`.
- Blockers: none known for expanded-path refinement

## Objective

Add generic execution-owned continuation entry points for prepared whole-run execution and self-finalizing one-stage jobs, without adding SLURM models, scripts, dry-run manifests, scheduler calls, or changing the v5 `loom stage run` handoff-only worker contract.

## Full-Plan Context

V6 builds SLURM dry-run script planning on stable generic continuation surfaces. Phase 1 merged the prepared-run metadata/store foundation, lifecycle helpers, and generated-artifact path helper. This phase makes those generic contracts callable through public CLI/API entry points so later single-job scripts can invoke `loom prepared-run continue` and afterok scripts can invoke `loom stage-job run`. Phase 3 must remain out of scope here: no SLURM options, resource mapping, planned submission models, generated scripts, manifests, preflight integration, or live scheduler state.

## Stack Context

- Root or stacked phase: root phase
- Current predecessor branch or PR: none; Phase 1 merged in PR #82
- Why this base branch is correct: Phase 1 is already merged into `develop`, and the manager assigned `develop` as both base and target.
- Retarget/rebase plan after predecessor merge: none required unless `develop` moves before PR preparation, in which case rebase this branch onto updated `develop`.
- Branch cleanup constraints: branch can be deleted after merge if no successor branch depends on it.

## Source Phase Summary

- Goal: Implement generic CLI/API continuation entry points for prepared whole-run execution and execution-owned one-stage jobs.
- Required scope: add `loom prepared-run continue --run-uri RUN_URI --executor local`; add `loom stage-job run --run-uri RUN_URI --stage STAGE --executor local` with optional `--attempt N` for exact prepared-attempt debugging; validate persisted plans, prepared metadata, executor choice, required environment state, and upstream readiness before user code starts.
- Required checkpoints: keep `loom stage run` handoff-only; reject recursive submitted executor selection; use shared lifecycle helpers for stage-job success/failure finalization; preserve parent-runner output, provenance, artifact-index, log, stage-status, and run-status semantics for the targeted stage.
- Acceptance criteria: whole-run continuation can execute a prepared run through a non-submitted executor; stage-job continuation can finalize one planned `RUN` stage without a parent process; failures are structured and happen before user code when required persisted state or upstream state is missing; stage-job JSON output uses schema `loom.cli.stage_job.run.v1`.

## Current Source And Harness Findings

- Existing files or modules that constrain this phase: `src/loom/cli/main.py` registers import-light top-level argparse commands; `src/loom/cli/stage.py` owns the existing `loom stage run` handoff-only worker and schema `loom.cli.stage.run.v1`; `src/loom/cli/run.py` already contains local/subprocess executor construction, run-result formatting, and `UnsupportedExecutorError`; `src/loom/pipeline/execution/prepared_run.py` exposes schema-versioned prepared-run records; `src/loom/pipeline/execution/lifecycle.py` exposes shared input binding, status, and artifact-index helpers; `src/loom/pipeline/execution/stage_worker.py` reconstructs v5 worker requests and writes only worker result handoffs; `src/loom/pipeline/execution/runner.py` still owns parent whole-run orchestration and commit semantics.
- Existing tests or harness behavior: `tests/unit/loom/cli/test_stage_cli.py` covers command parsing, JSON envelopes, and worker state errors for `loom stage run`; `tests/integration/pipeline/test_stage_worker_integration.py` proves direct workers do not commit final stage outputs; `tests/unit/loom/pipeline/execution/test_lifecycle.py` and `test_runner.py` cover extracted lifecycle behavior; package tests cover execution/store import boundaries; e2e tests exercise local public run behavior.
- Import-boundary or dependency constraints: CLI may import execution APIs lazily inside handlers, but `loom.pipeline.execution`, planning, stores, runtime, and executors must not import `loom.cli`; this phase must not introduce `loom.pipeline.executors.slurm` or scheduler dependencies.

## In-Scope Work

- Add an execution-owned prepared-run continuation API that reads a run from `RunStore`, validates `PreparedRunRecord`, validates the persisted execution plan and run URI, rejects submitted/recursive executor choices, and continues through an allowed non-submitted executor.
- Add `loom prepared-run continue --run-uri RUN_URI --executor local` as a top-level CLI command group with text and JSON behavior aligned with existing CLI envelope conventions.
- Add an execution-owned stage-job API that opens an existing run, validates the persisted plan, validates that the target stage exists with action `RUN`, checks that required upstream dependencies are already successful, reused, skipped, or otherwise available through durable outputs, executes only the targeted stage through an allowed non-submitted executor, and commits success/failure through shared lifecycle semantics.
- Add `loom stage-job run --run-uri RUN_URI --stage STAGE --executor local [--attempt N]` with JSON schema `loom.cli.stage_job.run.v1`.
- Add structured errors for missing prepared metadata, invalid plan/prepared-run identity, unsupported or recursive executor selection, missing required handoff state, missing environment requirements, invalid target stage/action, upstream dependency not ready, and lifecycle commit failures.
- Add focused tests across package, unit, contract, integration, and e2e suites for the new generic continuation behavior.

## Out-of-Scope Work

- No SLURM models, options, resource mapping, script building, dry-run manifests, generated command argv builders, `loom run --executor slurm-*` behavior, `sbatch`, `squeue`, `sacct`, `scancel`, scheduler job IDs, submitted status, or fake scheduler state.
- No change to the v5 `loom stage run` handoff-only worker contract; it must continue to write only `worker_result.json` and leave parent finalization to the subprocess runner.
- No broad runner rewrite, new executor registry, remote-store support, distributed locks, retries, timeout policy, controller mode, containers, or generic wall-time resource.
- No persistence of unredacted resolved config, resolver outputs, environment variable values, or raw adapter payloads to make continuation easier.

## Assumptions

- Phase 2 may add narrow execution request/result models for prepared-run and stage-job continuation if they keep public behavior clearer than passing loose mappings.
- `local` is the required executor for generated v6 command targets. Existing non-submitted executor support may be shared only when it fits current CLI/executor patterns without broad registry work; recursive submitted names such as future `slurm-single-job` and `slurm-afterok` must fail before runner construction.
- Whole-run continuation may fail clearly before user code when persisted prepared-run state does not contain enough artifact-safe replay information. Tests for successful whole-run continuation should prepare the minimum durable state required by the new API without relying on unredacted resolved-config persistence.
- Stage-job continuation should use the existing local run store and artifact store path helpers; remote stores and non-local artifact synchronization remain deferred.

## Scope Contract

`loom prepared-run continue` is a generic whole-run continuation command. It must open an existing run by URI, read a schema-versioned prepared-run record, validate that the prepared record belongs to the run and uses the expected continuation type, validate the persisted plan identity or summary available in the prepared metadata, select only an allowed non-submitted executor, and fail with structured CLI errors before user stage code when required prepared state is missing or incompatible. It must not replay an unredacted resolved config snapshot or persist new secret-bearing command sources.

`loom stage-job run` is a separate self-finalizing submitted-job target. It must not reuse or mutate `loom stage run`. It runs exactly one planned `RUN` stage from durable run-store state, commits that stage's validated outputs, provenance, failure record, artifact-index updates, logs, and status directly through execution-owned lifecycle semantics, and updates only run-level status in addition to the targeted stage. On target failure it marks the run failed. On target success it marks the run succeeded only when all planned stages are terminal success, reuse, or skip; otherwise it leaves the run running. It must not block downstream stages or mutate unrelated stage statuses.

Both continuation surfaces must validate upstream readiness before user code starts. For a stage-job, pending inputs must resolve from stored upstream outputs or reusable plan outputs, and unresolved environment requirements must be read from the process environment at job start or fail before stage construction/execution. Error behavior must use existing CLI structured-error conventions and keep lower execution APIs independent of `loom.cli`.

## Design Impact

- Maintainability: Keeps submitted continuation logic in generic execution APIs and prevents SLURM code from duplicating parent-runner lifecycle commits.
- Extensibility: Gives SLURM, containers, and future submitted executors stable command targets while leaving scheduler-specific script and manifest work to later phases.
- Domain neutrality: Commands describe generic prepared runs and stage jobs; no HPC-specific data model enters `loom.pipeline.execution`.
- Source-tree boundaries: CLI registers presentation commands, execution owns continuation semantics, stores own durable state and local paths, executors remain invocation adapters, and SLURM remains absent in this phase.

## Future Compatibility

- Phase 3 can build launcher argv against these command spellings without deciding lifecycle semantics.
- Phase 4 can render single-job and afterok scripts that invoke generic commands instead of embedding runner internals.
- V7 live submission can map scheduler jobs to the same prepared-run and stage-job continuation commands without changing the command contract.
- Later container work can wrap these commands in container launchers while preserving the same Loom lifecycle semantics.

## Alternatives Rejected

| Alternative | Reason rejected |
| --- | --- |
| Reuse `loom stage run` for self-finalizing submitted jobs | The existing v5 subprocess runner depends on `loom stage run` as a handoff-only worker whose parent commits final lifecycle state. |
| Put continuation finalization in future SLURM code | Submitted lifecycle semantics must be generic and reusable by containers or other submitted executors. |
| Overload `loom run CONFIG` as the prepared-run continuation target | Requiring the original config path risks resolved-config replay and hides the prepared-run boundary that v6 needs to audit. |
| Persist unredacted resolved config or resolver outputs for replay | The v6 secret boundary treats those values as unsafe by default. |
| Add a broad executor registry or plugin system now | Phase 2 only needs stable generic continuation command contracts; larger executor discovery belongs to later roadmap work. |

## Debt Introduced

| Debt | Reason accepted | Revisit trigger |
| --- | --- | --- |
| Strong submitted-job locking remains deferred beyond existing run locks | V6 remains dry-run/script-planning focused and cluster-free; Phase 2 only needs local deterministic continuation semantics. | V7 live submission, retries, duplicate submitted workers, or concurrent afterok execution requires stronger coordination. |
| Whole-run replay may support only the artifact-safe prepared state available in v6 | The plan rejects unredacted resolved-config replay and Phase 2 should fail clearly when safe replay state is insufficient. | A later roadmap defines a richer secret-safe prepared execution bundle or remote execution bundle. |

## Reviewability

- Expected PR size and shape: moderate generic execution/CLI PR with new focused modules and tests; no SLURM package, script generation, or broad runner rewrite.
- Files and areas to inspect: `src/loom/cli/main.py`, new `src/loom/cli/prepared_run.py`, new `src/loom/cli/stage_job.py`, `src/loom/cli/formatting.py` or `src/loom/cli/results.py` if result formatting is added, `src/loom/pipeline/execution/`, `src/loom/pipeline/stores/`, `tests/unit/loom/cli/`, `tests/unit/loom/pipeline/execution/`, `tests/contracts/`, `tests/integration/pipeline/`, and `tests/e2e/`.
- Scope-control checks: no `loom.pipeline.executors.slurm`, no `sbatch` or scheduler command calls, no scheduler IDs/statuses, no generated scripts/manifests, no mutation of `loom stage run`, no unredacted resolved-config replay, and no unrelated config/runtime/planning refactors.

## Implementation Steps

1. Add narrow execution models/errors and APIs for prepared-run continuation and stage-job continuation, with validation for run URI, persisted plan identity, prepared metadata, target stage/action, executor choice, environment requirements, and upstream readiness.
2. Implement stage-job execution and finalization by reconstructing the target stage from durable plan/fingerprint/state, invoking the selected non-submitted executor, and committing success/failure through shared lifecycle helpers without touching unrelated stage statuses.
3. Implement prepared-run whole-run continuation on top of prepared-run metadata and existing runner behavior, failing before user code when safe durable replay state is incomplete.
4. Add import-light CLI command groups for `prepared-run continue` and `stage-job run`, including text output, JSON envelopes, exit codes, and structured error mapping consistent with existing commands.
5. Add targeted tests for command parsing, validation failures, lifecycle parity, success/failure finalization, and public CLI smoke coverage, then run the focused suites listed below.

## Test Plan

### Package Suite

- Status: required
- Expected paths: `tests/package/test_import.py`, `tests/package/test_public_api.py`, `tests/package/test_pipeline_execution_api.py`, `tests/package/test_pipeline_store_api.py`, `tests/package/test_import_boundaries.py`
- Required assertions or deferral reason: new execution continuation APIs remain importable and typed; CLI command registration remains import-light; lower layers do not import `loom.cli`; no optional SLURM dependency is introduced.

### Unit Suite

- Status: required
- Expected paths: new `tests/unit/loom/cli/test_prepared_run_cli.py`, new `tests/unit/loom/cli/test_stage_job_cli.py`, new or updated `tests/unit/loom/pipeline/execution/test_prepared_run_continue.py`, new `tests/unit/loom/pipeline/execution/test_stage_job.py`, existing `tests/unit/loom/pipeline/execution/test_lifecycle.py`, `tests/unit/loom/pipeline/execution/test_runner.py`, and `tests/unit/loom/cli/test_main.py`
- Required assertions or deferral reason: parser shape and exit codes; JSON schema `loom.cli.stage_job.run.v1`; prepared-run validation failures; recursive submitted executor rejection; missing environment behavior; target stage missing or non-`RUN`; upstream dependency not ready; stage-job run-level terminal status rules; success/failure lifecycle commits; `loom stage run` remains handoff-only.

### Contract Suite

- Status: required
- Expected paths: `tests/contracts/test_stage_worker_contract.py`, `tests/contracts/test_store_contract.py`, and a new or updated execution/CLI continuation contract test such as `tests/contracts/test_continuation_commands_contract.py`
- Required assertions or deferral reason: stage-job result/error envelopes follow CLI conventions; new API result models are plain-data/schema-versioned where public; stage-job success/failure artifacts match parent-runner lifecycle semantics; store contract remains sufficient for prepared-run, plan, status, artifact-index, logs, failure, and provenance reads/writes.

### Integration Suite

- Status: required
- Expected paths: new `tests/integration/pipeline/test_prepared_run_continuation.py`, new `tests/integration/pipeline/test_stage_job_continuation.py`, existing `tests/integration/pipeline/test_local_execution.py`, `tests/integration/pipeline/test_local_execution_failures.py`, `tests/integration/pipeline/test_stage_worker_integration.py`, and `tests/integration/pipeline/test_subprocess_executor_integration.py`
- Required assertions or deferral reason: whole-run continuation against a local run store succeeds when prepared state is sufficient and fails clearly when it is not; stage-job continuation succeeds and fails against real local store state without `loom stage run`; upstream dependency validation happens before user code; artifact outputs, provenance, failure records, logs, artifact index, target stage status, and run status match parent-runner semantics.

### E2E Suite

- Status: required
- Expected paths: new or updated `tests/e2e/test_cli_core.py` and/or `tests/e2e/test_local_pipeline_run.py`
- Required assertions or deferral reason: a tiny prepared run can continue through `loom prepared-run continue`; one planned `RUN` stage can be finalized through public `loom stage-job run`; both paths remain deterministic, local, and cluster-free.

### Opt-In Suites

- Status: deferred
- Markers affected: none
- Required assertions or deferral reason: no real SLURM, scheduler, remote-store, container, or cluster acceptance suite applies in Phase 2.

## Risks

- Stage-job finalization can diverge from parent-runner success/failure semantics; mitigate with direct comparison tests against local parent-runner artifacts and statuses.
- Whole-run continuation may be tempted to replay unsafe resolved config; keep artifact-safe prepared metadata validation as the gate and fail early when safe replay state is incomplete.
- `loom stage run` and `loom stage-job run` are easy to conflate; protect the boundary with contract and integration tests proving direct workers still write only result handoffs.
- Run-level status rules for independent stage jobs are subtle; test success, failure, incomplete-run, and all-terminal cases explicitly.
- Existing lifecycle helpers may not yet expose every commit operation stage-job needs; add only narrow generic helpers rather than duplicating runner internals or implementing future scheduler behavior.

## Validation Commands

Targeted development commands:

```sh
UV_CACHE_DIR=/tmp/uv-cache uv run pytest tests/package/test_pipeline_execution_api.py tests/package/test_pipeline_store_api.py tests/package/test_import_boundaries.py
UV_CACHE_DIR=/tmp/uv-cache uv run pytest tests/unit/loom/cli/test_prepared_run_cli.py tests/unit/loom/cli/test_stage_job_cli.py tests/unit/loom/pipeline/execution/test_prepared_run_continue.py tests/unit/loom/pipeline/execution/test_stage_job.py tests/unit/loom/pipeline/execution/test_lifecycle.py tests/unit/loom/pipeline/execution/test_runner.py
UV_CACHE_DIR=/tmp/uv-cache uv run pytest tests/contracts/test_stage_worker_contract.py tests/contracts/test_store_contract.py tests/contracts/test_continuation_commands_contract.py
UV_CACHE_DIR=/tmp/uv-cache uv run pytest tests/integration/pipeline/test_prepared_run_continuation.py tests/integration/pipeline/test_stage_job_continuation.py tests/integration/pipeline/test_local_execution.py tests/integration/pipeline/test_local_execution_failures.py tests/integration/pipeline/test_stage_worker_integration.py tests/integration/pipeline/test_subprocess_executor_integration.py
UV_CACHE_DIR=/tmp/uv-cache uv run pytest tests/e2e/test_cli_core.py tests/e2e/test_local_pipeline_run.py
```

Final PR-preparation commands:

```sh
make validate-pr
make test-summary
```

## Handoff Notes For `loom_phase_executor`

- Safe implementation slices: execution validation/models first, stage-job API and lifecycle commit second, prepared-run continuation third, CLI adapters fourth, focused tests throughout.
- Tests to run with each slice: run matching unit tests after each API/CLI slice; run contract and integration tests after lifecycle commit behavior lands; run e2e only after public CLI paths work.
- Decisions the executor must not revisit: command spellings are fixed; `loom stage run` remains handoff-only; no SLURM code or scheduler behavior; no unredacted resolved-config replay; no future-phase script/model/manifest generation; no broad executor registry redesign.
- Conditions that require stopping for the manager: whole-run continuation cannot satisfy the acceptance criteria without persisting unsafe config or resolver data; stage-job finalization requires changing `loom stage run`; lifecycle parity requires a broad runner rewrite; recursive submitted executor rejection conflicts with later assigned executor naming; required test suites cannot be run for non-environmental reasons.
- Expanded-path refinement notes: pending. The refine pass should focus on whole-run replay sufficiency, exact stage-job lifecycle helper boundaries, and whether `local`-only executor support is the narrowest contract for Phase 2.

## Refinement And Review Budget Status

- Phase implementation refinement: unused
- PR review: unused
- Blocker resolution: 0/3 used

## Completion Notes

- Draft plan: completed in this draft pass and committed with `plan: add phase execution plan`
- Final phase execution plan: pending expanded-path refine pass
- Implementation summary: pending
- Implementation validation: pending
- Refinement summary: pending
- Blocker-resolution summary: pending
- PR preparation: pending
- Stack maintenance: pending
- Remaining blockers: none known at draft time
