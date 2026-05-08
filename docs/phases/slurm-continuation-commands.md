# Phase 2 Execution Plan: Generic Continuation Commands

## Metadata

- Status: pr_open
- Feature focus: SLURM Script Planning
- PR title: `SLURM Script Planning - Phase 2: Generic Continuation Commands`
- PR: https://github.com/samcantrill/loom/pull/83
- Branch: `codex/slurm-continuation-commands`
- Worktree: `/home/samcantrill/work/loom-worktrees/slurm-continuation-commands`
- Phase execution plan path: `docs/phases/slurm-continuation-commands.md`
- PR body path: `docs/phases/slurm-continuation-commands-pr-body.md`
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
- Refine pass: completed by `loom_phase_planner` for expanded path
- Setup limitations: none known. GitHub auth was verified with network access, `gh auth setup-git` succeeded, `git fetch origin` succeeded, and this worktree was created from `develop` at `74237d2`.
- Blockers: none known for implementation handoff

## Objective

Add generic execution-owned continuation entry points for prepared whole-run execution and self-finalizing one-stage jobs, with the minimum lifecycle helper extraction needed for stage-job parity. The phase must not add SLURM models, scripts, dry-run manifests, scheduler calls, broad runner rewrites, unsafe config replay, or changes to the v5 `loom stage run` handoff-only worker contract.

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
- Required checkpoints: keep `loom stage run` handoff-only; reject recursive submitted executor selection before user code; use newly extracted shared lifecycle helpers for stage-job success/failure finalization; preserve parent-runner output, provenance, artifact-index, log, stage-status, and run-status semantics for the targeted stage.
- Acceptance criteria: prepared-run continuation validates prepared metadata, executor choice, persisted plan identity, and runtime state, then either executes from an explicitly safe prepared-run payload or fails before user code with a structured insufficient-prepared-state error; stage-job continuation can finalize one planned `RUN` stage without a parent process; failures are structured and happen before user code when required persisted state, safe reconstruction state, environment state, or upstream state is missing; stage-job JSON output uses schema `loom.cli.stage_job.run.v1`.

## Current Source And Harness Findings

- Existing files or modules that constrain this phase: `src/loom/cli/main.py` registers top-level argparse commands and must stay import-light, so new `prepared-run` and `stage-job` groups should live in new CLI modules imported lazily inside `build_parser`; `src/loom/cli/stage.py` owns the existing `loom stage run` handoff-only worker and schema `loom.cli.stage.run.v1`; `src/loom/cli/run.py` already contains local/subprocess executor construction, run-result formatting, and `UnsupportedExecutorError`; `src/loom/pipeline/execution/prepared_run.py` exposes schema-versioned prepared-run records; `src/loom/pipeline/execution/lifecycle.py` exposes shared input binding, status, and artifact-index helpers but does not yet expose full stage finalization/provenance/run-status helpers; `src/loom/pipeline/execution/stage_worker.py` reconstructs v5 worker requests, currently has a `config/resolved.yaml` fallback for direct workers, and writes only worker result handoffs; `src/loom/pipeline/execution/runner.py` still owns parent whole-run orchestration and the success/failure/provenance/status commit behavior that stage-job needs to share.
- Existing tests or harness behavior: `tests/unit/loom/cli/test_stage_cli.py` covers command parsing, JSON envelopes, and worker state errors for `loom stage run`; `tests/integration/pipeline/test_stage_worker_integration.py` proves direct workers do not commit final stage outputs; `tests/unit/loom/pipeline/execution/test_lifecycle.py` and `test_runner.py` cover extracted lifecycle behavior; package tests cover execution/store import boundaries; e2e tests exercise local public run behavior.
- Import-boundary or dependency constraints: CLI may import execution APIs lazily inside handlers, but `loom.pipeline.execution`, planning, stores, runtime, and executors must not import `loom.cli`; this phase must not introduce `loom.pipeline.executors.slurm` or scheduler dependencies.

## In-Scope Work

- Add an execution-owned prepared-run continuation API that reads a run from `RunStore`, validates `PreparedRunRecord`, validates the persisted execution plan, persisted runtime metadata, run URI, continuation type, and executor choice, rejects submitted/recursive executor choices, and then either continues through `local` from an explicitly safe prepared-run payload or fails before user code with a structured insufficient-prepared-state error.
- Add `loom prepared-run continue --run-uri RUN_URI --executor local` as a top-level CLI command group with text and JSON behavior aligned with existing CLI envelope conventions.
- Add an execution-owned state-only stage-job API that opens an existing run, validates the persisted plan, validates that the target stage exists with action `RUN`, checks that required upstream dependencies are already successful, reused, skipped, or otherwise available through durable outputs, reconstructs the stage execution request without using the unsafe `config/resolved.yaml` fallback, executes only the targeted stage through `local`, and commits success/failure through shared lifecycle semantics.
- Add `loom stage-job run --run-uri RUN_URI --stage STAGE --executor local [--attempt N]` with JSON schema `loom.cli.stage_job.run.v1`.
- Extract only the shared lifecycle helpers stage-job needs from `PipelineRunner`: successful output validation and commit, failure record/status commit, stage provenance commit, artifact-index update, stage event/status commit, and run-level terminal status evaluation/update.
- Add structured errors for missing prepared metadata, insufficient safe prepared-run state, invalid plan/prepared-run identity, unsupported or recursive executor selection, missing required handoff state, unsafe or insufficient stage-job reconstruction state, missing environment requirements, invalid target stage/action, upstream dependency not ready, and lifecycle commit failures.
- Add focused tests across package, unit, contract, integration, and e2e suites for the new generic continuation behavior.

## Out-of-Scope Work

- No SLURM models, options, resource mapping, script building, dry-run manifests, generated command argv builders, `loom run --executor slurm-*` behavior, `sbatch`, `squeue`, `sacct`, `scancel`, scheduler job IDs, submitted status, or fake scheduler state.
- No change to the v5 `loom stage run` handoff-only worker contract; it must continue to write only `worker_result.json` and leave parent finalization to the subprocess runner.
- No broad runner rewrite, new executor registry, remote-store support, distributed locks, retries, timeout policy, controller mode, containers, or generic wall-time resource. Helper extraction must be narrow and should leave the parent runner loop shape intact.
- No persistence of unredacted resolved config, resolver outputs, environment variable values, or raw adapter payloads to make continuation easier.

## Assumptions

- Phase 2 may add narrow execution request/result models for prepared-run and stage-job continuation if they keep public behavior clearer than passing loose mappings.
- `local` is the required executor for generated v6 command targets and the only required successful execution path for this phase. Existing non-submitted alternatives may be accepted only if they reuse current APIs without broad registry work; submitted names such as future `slurm-single-job` and `slurm-afterok` must fail before stage construction or runner invocation.
- Whole-run continuation is not allowed to invent replay state. If Phase 1 persisted state is insufficient for a full parent-run replay without `config/resolved.yaml` or resolver output exposure, the required Phase 2 behavior is a usable API/CLI that validates prepared metadata, persisted plan/runtime state, and executor choice, then returns a structured insufficient-prepared-state failure before user code.
- Stage-job continuation should use the existing local run store and artifact store path helpers; remote stores and non-local artifact synchronization remain deferred.
- Stage-job reconstruction should build its execution context from persisted plan/fingerprint/stage state and safe store documents only. It must not call `stage_worker.reconstruct_stage_execution_request()` unless that helper gains an explicit safe mode that disables the resolved-config fallback for submitted stage jobs.

## Scope Contract

`loom prepared-run continue` is a generic whole-run continuation command. It must open an existing run by URI, read a schema-versioned prepared-run record, validate that the prepared record belongs to the run and uses the expected continuation type, validate persisted plan identity or summary information available in the prepared metadata, validate persisted runtime metadata, select only `local` unless another existing non-submitted executor fits without registry work, and reject submitted/recursive executor names before runner construction. It may execute only when the prepared-run record or store state provides an explicitly safe execution payload that does not require unredacted resolved config replay. If such safe replay state is absent, the command must return a structured insufficient-prepared-state error before user stage code. It must not read `config/resolved.yaml` as a replay source, persist new secret-bearing command sources, or silently fall back to original CLI config arguments.

`loom stage-job run` is a separate self-finalizing submitted-job target. It must not reuse or mutate `loom stage run`, and it must not use the v5 worker reconstruction path's unsafe resolved-config fallback for submitted jobs. It runs exactly one planned `RUN` stage from durable run-store state, commits that stage's validated outputs, provenance, failure record, artifact-index updates, logs, and status directly through execution-owned lifecycle semantics, and updates only run-level status in addition to the targeted stage. On target failure it marks the run failed. On target success it marks the run succeeded only when all planned stages are terminal success, reuse, or skip; otherwise it leaves the run running. It must not block downstream stages or mutate unrelated stage statuses.

Both continuation surfaces must validate upstream readiness before user code starts. For a stage-job, pending inputs must resolve from stored upstream outputs or reusable plan outputs, and unresolved environment requirements must be read from the process environment at job start or fail before stage construction/execution. Error behavior must use existing CLI structured-error conventions and keep lower execution APIs independent of `loom.cli`.

The lifecycle extraction contract is intentionally narrow. The executor may move private `PipelineRunner` commit logic into shared execution helpers only for operations needed by stage-job finalization: output validation/write, stage provenance write, failure document write, artifact-index update, stage status/event write, run failure write, and run terminal-success evaluation/write. The executor must not redesign the parent runner loop, planning, resume policy, or stage worker handoff protocol to make this phase work.

## Design Impact

- Maintainability: Keeps submitted continuation logic in generic execution APIs and prevents SLURM code from duplicating parent-runner lifecycle commits, while constraining helper extraction to avoid a broad runner rewrite.
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
| Use `stage_worker.reconstruct_stage_execution_request()` unchanged for stage jobs | Its current resolved-config fallback is appropriate only for the v5 handoff worker path and is unsafe as a submitted-job reconstruction default. |

## Debt Introduced

| Debt | Reason accepted | Revisit trigger |
| --- | --- | --- |
| Strong submitted-job locking remains deferred beyond existing run locks | V6 remains dry-run/script-planning focused and cluster-free; Phase 2 only needs local deterministic continuation semantics. | V7 live submission, retries, duplicate submitted workers, or concurrent afterok execution requires stronger coordination. |
| Whole-run continuation may validate-and-fail rather than execute when safe replay state is insufficient | The plan rejects unredacted resolved-config replay; a structured pre-user-code insufficient-state failure is safer than inventing persistence in Phase 2. | A later roadmap defines a richer secret-safe prepared execution bundle, or Phase 2 implementation discovers an already-safe payload sufficient for parent-run replay. |

## Reviewability

- Expected PR size and shape: moderate generic execution/CLI PR with new focused modules, narrow lifecycle helper extraction, and tests; no SLURM package, script generation, broad runner rewrite, or executor registry work.
- Files and areas to inspect: `src/loom/cli/main.py`, new `src/loom/cli/prepared_run.py`, new `src/loom/cli/stage_job.py`, `src/loom/cli/formatting.py` or `src/loom/cli/results.py` if result formatting is added, `src/loom/pipeline/execution/`, `src/loom/pipeline/stores/`, `tests/unit/loom/cli/`, `tests/unit/loom/pipeline/execution/`, `tests/contracts/`, `tests/integration/pipeline/`, and `tests/e2e/`.
- Scope-control checks: no `loom.pipeline.executors.slurm`, no `sbatch` or scheduler command calls, no scheduler IDs/statuses, no generated scripts/manifests, no mutation of `loom stage run`, no unchanged use of the resolved-config worker fallback for submitted stage jobs, no unredacted resolved-config replay, no unrelated config/runtime/planning refactors, and no broad runner loop rewrite.

## Implementation Steps

1. Add narrow execution models/errors and validation APIs for prepared-run continuation and stage-job continuation, including submitted/recursive executor rejection and insufficient-safe-state errors.
2. Extract the minimum lifecycle commit helpers from `PipelineRunner` needed by stage-job finalization, preserving the parent runner's current public status, provenance, artifact-index, failure, and event semantics.
3. Implement state-only stage-job reconstruction and execution for `--executor local`, explicitly avoiding the direct worker resolved-config fallback, then commit targeted success/failure/run-status results through the shared helpers.
4. Implement prepared-run whole-run continuation validation and the safe-execution-or-structured-insufficient-state behavior without reading unredacted resolved config.
5. Add import-light CLI command groups for `prepared-run continue` and `stage-job run`, including text output, JSON envelopes, exit codes, and structured error mapping consistent with existing commands.
6. Add targeted tests for command parsing, validation failures, safe reconstruction, lifecycle parity, success/failure finalization, and public CLI smoke coverage, then run the focused suites listed below.

## Test Plan

### Package Suite

- Status: required
- Expected paths: `tests/package/test_import.py`, `tests/package/test_public_api.py`, `tests/package/test_pipeline_execution_api.py`, `tests/package/test_pipeline_store_api.py`, `tests/package/test_import_boundaries.py`
- Required assertions or deferral reason: new execution continuation APIs remain importable and typed; new CLI modules are registered lazily from `loom.cli.main`; lower layers do not import `loom.cli`; no optional SLURM dependency is introduced.

### Unit Suite

- Status: required
- Expected paths: new `tests/unit/loom/cli/test_prepared_run_cli.py`, new `tests/unit/loom/cli/test_stage_job_cli.py`, new or updated `tests/unit/loom/pipeline/execution/test_prepared_run_continue.py`, new `tests/unit/loom/pipeline/execution/test_stage_job.py`, existing `tests/unit/loom/pipeline/execution/test_lifecycle.py`, `tests/unit/loom/pipeline/execution/test_runner.py`, and `tests/unit/loom/cli/test_main.py`
- Required assertions or deferral reason: parser shape and exit codes; import-light command registration; JSON schema `loom.cli.stage_job.run.v1`; prepared-run validation failures and structured insufficient-prepared-state behavior; recursive submitted executor rejection before user code; missing environment behavior; target stage missing or non-`RUN`; upstream dependency not ready; safe state-only stage-job reconstruction that does not read `config/resolved.yaml`; stage-job run-level terminal status rules; success/failure lifecycle commits; `loom stage run` remains handoff-only.

### Contract Suite

- Status: required
- Expected paths: `tests/contracts/test_stage_worker_contract.py`, `tests/contracts/test_store_contract.py`, and a new or updated execution/CLI continuation contract test such as `tests/contracts/test_continuation_commands_contract.py`
- Required assertions or deferral reason: stage-job result/error envelopes follow CLI conventions; new API result models are plain-data/schema-versioned where public; prepared-run insufficient-state errors are stable and structured; stage-job success/failure artifacts match parent-runner lifecycle semantics; store contract remains sufficient for prepared-run, plan, runtime metadata, status, artifact-index, logs, failure, and provenance reads/writes; direct worker contracts remain handoff-only.

### Integration Suite

- Status: required
- Expected paths: new `tests/integration/pipeline/test_prepared_run_continuation.py`, new `tests/integration/pipeline/test_stage_job_continuation.py`, existing `tests/integration/pipeline/test_local_execution.py`, `tests/integration/pipeline/test_local_execution_failures.py`, `tests/integration/pipeline/test_stage_worker_integration.py`, and `tests/integration/pipeline/test_subprocess_executor_integration.py`
- Required assertions or deferral reason: whole-run continuation against a local run store succeeds only when explicitly safe prepared state is sufficient and otherwise fails clearly before user code; stage-job continuation succeeds and fails against real local store state without `loom stage run`; upstream dependency and environment validation happen before user code; artifact outputs, provenance, failure records, logs, artifact index, target stage status, and run status match parent-runner semantics for the targeted stage; downstream stages are not blocked or mutated by stage-job continuation.

### E2E Suite

- Status: required for public parser and structured-failure smoke; successful whole-run e2e deferred unless implementation exposes an explicitly safe prepared-run payload
- Expected paths: new or updated `tests/e2e/test_cli_core.py` and/or `tests/e2e/test_local_pipeline_run.py`
- Required assertions or deferral reason: public `loom prepared-run continue` and `loom stage-job run` parser/JSON envelope smoke paths are deterministic and cluster-free; `loom prepared-run continue` structured insufficient-state failure is acceptable if no safe replay payload exists; successful stage-job finalization is required in integration rather than e2e to keep setup state explicit and reviewable.

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

- Safe implementation slices: execution validation/errors first, lifecycle commit helper extraction second, state-only stage-job API third, prepared-run continuation validation fourth, import-light CLI adapters fifth, focused tests throughout.
- Tests to run with each slice: run matching unit tests after each API/CLI slice; run lifecycle and runner regression tests immediately after helper extraction; run contract and integration tests after stage-job finalization behavior lands; run e2e smoke only after public CLI paths work.
- Decisions the executor must not revisit: command spellings are fixed; `--executor local` is the required generated-command target; submitted/recursive executors are rejected before user code; `loom stage run` remains handoff-only; stage-job reconstruction must not use the unsafe resolved-config fallback; no SLURM code or scheduler behavior; no unredacted resolved-config replay; no future-phase script/model/manifest generation; no broad executor registry redesign or runner loop rewrite.
- Conditions that require stopping for the manager: prepared-run continuation cannot provide either safe execution or structured insufficient-state failure without unsafe persistence; stage-job finalization requires changing `loom stage run`; safe state-only reconstruction cannot be implemented without reading unredacted resolved config; lifecycle parity requires a broad runner rewrite; recursive submitted executor rejection conflicts with later assigned executor naming; required test suites cannot run for a non-environmental reason.
- Expanded-path refinement notes: completed. The refined contract narrows whole-run continuation to safe-execution-or-structured-insufficient-state behavior, requires state-only stage-job reconstruction, bounds lifecycle helper extraction, keeps `local` as the only required executor target, and makes e2e obligations realistic for public parser/structured-failure smoke.

## Refinement And Review Budget Status

- Phase implementation refinement: used on 2026-05-08 for expanded-path lifecycle
  and state-safety fixes
- PR review: unused
- Blocker resolution: 0/3 used

## Completion Notes

- Draft plan: completed in this draft pass and committed with `plan: add phase execution plan`
- Final phase execution plan: completed in expanded-path refine pass
- Implementation summary: completed fallback implementation pass in this worktree. Added generic execution-owned continuation APIs for prepared whole-run validation and self-finalizing stage jobs; added import-light `loom prepared-run continue` and `loom stage-job run` CLI groups; extracted narrow runner lifecycle commit helpers for stage output validation, provenance, artifact-index, failure, stage status/event, and failed-run status; preserved the v5 `loom stage run` handoff-only worker path while adding a safe-mode reconstruction option that disables `config/resolved.yaml` fallback for stage jobs. Whole-run prepared continuation validates durable prepared metadata, persisted plan, runtime metadata, run identity, and executor choice, then returns structured `execution.prepared_run.insufficient_prepared_state` before user code when no explicit safe replay payload exists. Stage-job continuation requires `--executor local`, rejects recursive submitted executor names before user code, reconstructs from prepared durable worker state without resolved-config replay, validates upstream outputs and runtime environment safety before execution, finalizes only the target stage, marks the run failed on target failure, marks the run succeeded only when all planned stages are terminal success/reuse/skip, and otherwise leaves the run running without blocking downstream stages.
- Implementation validation: targeted package/unit command passed (`55 passed`); targeted contract/integration/e2e smoke command passed (`20 passed, 4 skipped`); `make validate-pr` passed after a small typecheck fix (`ruff check`, `pyright`, default test harness `762 passed, 14 skipped, 8 deselected`, config-extra harness `405 passed, 781 deselected`, and `uv build`). `make test-summary` was not run because this pass stops before PR preparation.
- Refinement summary: used the required expanded-path implementation refinement
  pass. Fixed two concrete stage-job blockers: success-finalization exceptions
  such as output validation failures now commit a stage failure and failed run
  instead of escaping after the stage is marked running, and tampered prepared
  worker request identity now fails before executor construction/user code.
- Refinement validation: targeted stage-job unit test passed (`6 passed`);
  targeted continuation/lifecycle/runner/contract/integration/e2e command
  passed (`43 passed`); `make validate-pr` passed (`ruff check`, `pyright`,
  default harness `764 passed, 14 skipped, 8 deselected`, config-extra harness
  `405 passed, 783 deselected`, and `uv build`).
- Blocker-resolution summary: not used
- PR preparation: complete. PR body committed at
  `docs/phases/slurm-continuation-commands-pr-body.md`; PR #83 opened against
  `develop`.
- Stack maintenance: none performed
- Remaining blockers: none known from implementation, refinement validation,
  and PR-prep suite evidence

### Phase Implementation Handoff

## Metadata

- Phase: Phase 2 - Generic Continuation Commands
- Branch: `codex/slurm-continuation-commands`
- Worktree: `/home/samcantrill/work/loom-worktrees/slurm-continuation-commands`
- Phase execution plan: `docs/phases/slurm-continuation-commands.md`
- Executor: fallback local Codex implementation pass after Spark usage limit
- Handoff date: 2026-05-08

## Implementation Summary

- Added generic continuation API models and structured errors in `loom.pipeline.execution`.
- Added `continue_prepared_run` validation with safe-state failure before user code.
- Added `run_stage_job` for local, self-finalizing one-stage continuation from prepared durable state.
- Extracted narrow lifecycle commit helpers and kept `PipelineRunner` using the shared helpers.
- Added CLI adapters for `loom prepared-run continue` and `loom stage-job run`.
- Added package, unit, contract, integration, and e2e smoke coverage for Phase 2 behavior.

## Commits

| Commit | Summary |
| --- | --- |
| `849c2c1` | `feat: add generic continuation commands` |
| `013e769` | `test: cover continuation command behavior` |
| `25438a0` | `fix: satisfy continuation type checks` |

## Scope Control

- Implements only the assigned phase: yes
- Future-phase work avoided: yes; no SLURM package, script generation, dry-run manifest, submitted state, scheduler IDs, `sbatch`, or `loom run --executor slurm-*`
- Unrelated refactors avoided: yes; lifecycle extraction was limited to runner commit helpers required by stage-job finalization
- Public contract decisions changed: no
- Expanded-path implementation refinement: used on 2026-05-08; fixed
  stage-job lifecycle failure finalization and worker-request identity
  validation before executor construction

## Tests Added Or Updated

- Package: updated `tests/package/test_pipeline_execution_api.py`
- Unit: added `tests/unit/loom/cli/test_prepared_run_cli.py`, `tests/unit/loom/cli/test_stage_job_cli.py`, `tests/unit/loom/pipeline/execution/test_prepared_run_continue.py`, and `tests/unit/loom/pipeline/execution/test_stage_job.py`
- Refinement unit coverage: updated
  `tests/unit/loom/pipeline/execution/test_stage_job.py` for output-validation
  lifecycle failure finalization and prepared worker-request identity mismatch
- Contract: added `tests/contracts/test_continuation_commands_contract.py`
- Integration: added `tests/integration/pipeline/test_prepared_run_continuation.py` and `tests/integration/pipeline/test_stage_job_continuation.py`
- E2E: updated `tests/e2e/test_cli_core.py`
- Opt-in: not applicable

## Validation Run

```text
command: UV_CACHE_DIR=/tmp/uv-cache uv run pytest tests/package/test_pipeline_execution_api.py tests/package/test_pipeline_store_api.py tests/package/test_import_boundaries.py tests/unit/loom/cli/test_prepared_run_cli.py tests/unit/loom/cli/test_stage_job_cli.py tests/unit/loom/pipeline/execution/test_prepared_run_continue.py tests/unit/loom/pipeline/execution/test_stage_job.py tests/unit/loom/pipeline/execution/test_lifecycle.py tests/unit/loom/pipeline/execution/test_runner.py
result: passed, 55 passed in 5.00s

command: UV_CACHE_DIR=/tmp/uv-cache uv run pytest tests/contracts/test_stage_worker_contract.py tests/contracts/test_store_contract.py tests/contracts/test_continuation_commands_contract.py tests/integration/pipeline/test_prepared_run_continuation.py tests/integration/pipeline/test_stage_job_continuation.py tests/integration/pipeline/test_local_execution.py tests/integration/pipeline/test_local_execution_failures.py tests/integration/pipeline/test_stage_worker_integration.py tests/integration/pipeline/test_subprocess_executor_integration.py tests/e2e/test_cli_core.py tests/e2e/test_local_pipeline_run.py
result: passed, 20 passed and 4 skipped in 2.11s

command: UV_CACHE_DIR=/tmp/uv-cache make validate-pr
result: passed; ruff check, pyright, default harness, config-extra harness, and uv build all succeeded

command: UV_CACHE_DIR=/tmp/uv-cache uv run pytest tests/unit/loom/pipeline/execution/test_stage_job.py
result: passed, 6 passed in 0.65s

command: UV_CACHE_DIR=/tmp/uv-cache uv run pytest tests/unit/loom/cli/test_prepared_run_cli.py tests/unit/loom/cli/test_stage_job_cli.py tests/unit/loom/pipeline/execution/test_prepared_run_continue.py tests/unit/loom/pipeline/execution/test_stage_job.py tests/unit/loom/pipeline/execution/test_lifecycle.py tests/unit/loom/pipeline/execution/test_runner.py tests/contracts/test_continuation_commands_contract.py tests/integration/pipeline/test_prepared_run_continuation.py tests/integration/pipeline/test_stage_job_continuation.py tests/e2e/test_cli_core.py
result: passed, 43 passed in 4.78s

command: UV_CACHE_DIR=/tmp/uv-cache make validate-pr
result: passed; ruff check, pyright, default harness 764 passed/14 skipped/8 deselected, config-extra harness 405 passed/783 deselected, and uv build all succeeded
```

## PR Preparation Notes

- PR body path: `docs/phases/slurm-continuation-commands-pr-body.md`
- PR URL: https://github.com/samcantrill/loom/pull/83
- PR title: `SLURM Script Planning - Phase 2: Generic Continuation Commands`
- Target branch: `develop`
- Head branch: `codex/slurm-continuation-commands`
- Stack predecessor: none; this is a root phase because Phase 1 is merged
- Base/head verification: `gh pr view 83 --json
  baseRefName,headRefName,state,url` returned `baseRefName=develop`,
  `headRefName=codex/slurm-continuation-commands`, `state=OPEN`, and
  `url=https://github.com/samcantrill/loom/pull/83`.
- Stack state: root PR targeting `develop`; no predecessor branch and no stack
  retarget/rebase work required for PR preparation.
- Diff reviewed against `develop`: generic execution and CLI continuation
  behavior, focused tests, and this phase artifact only. No SLURM models,
  generated scripts, manifests, scheduler IDs, live submission, or
  `loom run --executor slurm-*` wiring were present.
- Worktree cleanliness before PR-prep edits: clean at `ca99fa2`.
- `make validate-pr`: cited from the refinement pass at `ca99fa2`; passed
  `ruff check`, `pyright`, default harness `764 passed, 14 skipped, 8
  deselected`, config-extra harness `405 passed, 783 deselected`, and
  `uv build`.
- `make test-summary`: passed during PR preparation with
  `UV_CACHE_DIR=/tmp/uv-cache make test-summary`; `build/test-summary.md`
  recorded package `50 passed, 1 skipped`, unit `633 passed, 1 skipped`,
  contract `57 passed, 2 skipped`, integration `24 passed, 7 skipped, 8
  deselected`, e2e `19 passed`, config-extra `405 passed, 783 deselected`,
  and overall `1188 passed, 11 skipped, 791 deselected`.

## Known Issues Or Blockers

- Whole-run prepared continuation currently validates and returns structured
  insufficient prepared state before user code because no explicit safe replay
  payload exists in Phase 2 state.

## Refiner Handoff

- Areas most likely to need validation attention: stage-job lifecycle parity with parent runner, exact run-status terminal evaluation for larger DAGs, and future safe prepared-run replay payload design.
- Failing or unavailable checks: none from initial validation.
- Completion notes added to phase execution plan: yes.
