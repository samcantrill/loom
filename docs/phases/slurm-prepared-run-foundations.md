# Phase 1 Execution Plan: Prepared-Run And Lifecycle Foundations

## Metadata

- Status: draft phase execution plan
- Feature focus: SLURM Script Planning
- PR title: `SLURM Script Planning - Phase 1: Prepared-Run And Lifecycle Foundations`
- Branch: `codex/slurm-prepared-run-foundations`
- Worktree: `/home/samcantrill/work/loom-worktrees/slurm-prepared-run-foundations`
- Phase execution plan path: `docs/phases/slurm-prepared-run-foundations.md`
- Full plan: `docs/implementation-plans/implementation-plan-v6.md`
- Source phase: Phase 1 - Prepared-Run And Lifecycle Foundations
- Stack predecessor: none
- Base branch: `develop`
- Target branch: `develop`
- Merge eligibility: root phase; merge-eligible when the PR targets `develop`, automated review passes, and validation/CI passes
- Workflow path: expanded path
- Successor dependency notes: Phase 2 depends on the prepared-run metadata, lifecycle helper, and generated-artifact path contracts from this phase.
- Plan quality gate: passed on 2026-05-08 after initial review, one refinement pass, and confirmation review
- Plan quality gate loop budget: initial review used, refinement used, confirmation review used
- Draft pass: completed by `loom_phase_planner`
- Refine pass: pending for expanded path
- Setup limitations: Worktree was created from local `develop`; no remote synchronization or validation was run in this draft-only pass.
- Blockers: none known for this draft

## Objective

Define the generic prepared-run state, payload safety rules, shared execution lifecycle helpers, and store-owned generated-artifact path helper needed before SLURM dry-run models or continuation commands are added.

## Full-Plan Context

V6 adds SLURM dry-run script planning without live scheduler submission. This first phase deliberately stays generic so later SLURM scripts can invoke stable execution-owned continuation surfaces instead of duplicating runner lifecycle logic. Phase 2 adds public continuation commands, Phase 3 adds SLURM models, Phase 4 writes scripts and dry-run manifests, Phase 5 wires CLI/preflight behavior, and Phase 6 hardens e2e/docs coverage. This phase must not add SLURM models, script generation, CLI executor selection, `sbatch`, scheduler state, or live-submission behavior.

## Stack Context

- Root or stacked phase: root phase
- Current predecessor branch or PR: none
- Why this base branch is correct: v6 has no earlier phase; the manager assigned `develop` as the stack base.
- Retarget/rebase plan after predecessor merge: none required unless `develop` moves before PR preparation, in which case rebase this branch onto updated `develop`.
- Branch cleanup constraints: branch can be deleted after merge if no successor branch depends on it.

## Source Phase Summary

- Goal: Define generic, secret-safe prepared-run state and shared execution lifecycle helpers needed by whole-run and one-stage continuation.
- Required scope: Add prepared-run metadata under execution/store boundaries; define allowed persisted payloads and rejection behavior for secret-bearing payloads; extract or add lifecycle helpers for input binding, output commit, provenance/failure commit, artifact-index updates, and status updates; add a path-safe run-store helper for run-scoped generated artifacts.
- Required checkpoints: Preserve existing local/subprocess behavior, keep generic helpers free of SLURM-specific branches, and expose generated-artifact path resolution through store-owned APIs.
- Acceptance criteria: Prepared-run metadata round-trips through public execution/store APIs; unsafe resolved config, resolver outputs, environment values, and raw adapter payloads are absent or rejected with structured errors; lifecycle helpers keep current semantics; generated artifact paths reject unsafe relative paths without knowing SLURM layout.

## Current Source And Harness Findings

- Existing files or modules that constrain this phase: `src/loom/pipeline/execution/runner.py` currently owns input binding, stage execution commits, failure commits, artifact-index updates, and run finalization; `src/loom/pipeline/execution/stage_attempts.py` owns v5 prepared worker request creation; `src/loom/pipeline/execution/lifecycle.py` already contains status helpers; `src/loom/pipeline/execution/stage_worker.py` reconstructs handoff-only subprocess attempts; `src/loom/pipeline/stores/run_store.py` defines store protocols; `src/loom/pipeline/stores/local_runs.py` owns local persisted file layout and path helpers; `src/loom/pipeline/stores/_paths.py` owns path safety helpers.
- Existing tests or harness behavior: package tests cover import boundaries; unit tests cover runner, lifecycle, stage attempts, stage worker, and local run stores; contract tests cover `RunStore`, `LocalRunStorePaths`, executor contracts, and stage-worker behavior; integration tests cover local and subprocess execution.
- Import-boundary or dependency constraints: lower execution/store layers must not import `loom.cli`; this phase must not introduce `loom.pipeline.executors.slurm` or optional scheduler dependencies; authored configs are trusted project code, but persisted prepared-run payloads must remain artifact-safe.

## In-Scope Work

- Add schema-versioned prepared-run metadata models and execution APIs under `loom.pipeline.execution`.
- Add run-store protocol and local-store read/write support for prepared-run metadata.
- Define and enforce prepared-run payload safety: plain-data only, artifact-safe/unresolved or redacted summaries only, no unredacted resolved config snapshots, resolver outputs, environment variable names or values, or raw adapter payloads by default.
- Extract shared lifecycle helpers from `PipelineRunner` where needed so current local/subprocess execution and future stage-job continuation can share input binding, output commit, provenance/failure commit, artifact-index updates, status writes, and event semantics.
- Add a store-owned helper for resolving run-scoped generated artifact paths under a run directory from safe relative paths.
- Update focused package, unit, contract, and integration tests for the new contracts.

## Out-of-Scope Work

- No SLURM models, options, resource mapping, scripts, dry-run manifests, preflight checks, or `loom.pipeline.executors.slurm` package.
- No `loom prepared-run continue` or `loom stage-job run` CLI/API entry points; those belong to Phase 2.
- No live scheduler submission, scheduler job IDs, submitted status, `sbatch`, `squeue`, `sacct`, `scancel`, or fake scheduler state.
- No conversion of the existing `loom stage run` handoff-only worker into a self-finalizing submitted-job runner.
- No generic wall-time resource, container command composition, remote store support, or stronger distributed locking unless a local correctness blocker is discovered.

## Assumptions

- Prepared-run metadata is a run-level record, not stage worker request metadata.
- The local store can persist prepared-run metadata as a plain schema-versioned JSON document under the run directory while keeping exact filename/layout owned by the store implementation.
- The generated-artifact path helper should accept safe relative paths such as `slurm/submissions/<planning_id>/manifest.json` and reject absolute paths, parent traversal, empty components, control characters, and paths that resolve outside the run directory.
- Existing fingerprint payloads may contain resolved stage data; this phase must either constrain new prepared-run metadata to safe summaries or reject unsafe payloads rather than solving every future secret-surface regression assigned to Phase 6.

## Scope Contract

Prepared-run metadata is a generic execution/store contract. It must be schema-versioned, plain-data serializable, and sufficient for later continuation commands to validate an existing run, persisted plan, prepared executor choice, run URI, safe config/runtime summaries, and expected continuation mode without reading CLI state. It must not store unredacted resolved config values, resolver outputs, environment variable names or values, raw adapter payloads, scheduler facts, or scheduler job IDs.

The shared lifecycle helpers must preserve current local and subprocess outcomes. They may move logic out of `PipelineRunner`, but must not change public run statuses, stage statuses, artifact indexes, provenance/failure payload shapes, stage worker request/result contracts, or event ordering except where tests explicitly document an invariant-preserving extraction.

The run-scoped generated-artifact helper is a store path contract, not a SLURM contract. It resolves validated relative paths under an existing run directory and returns local paths for writers; later SLURM phases own the relative layout.

## Design Impact

- Maintainability: Moves duplicated or soon-to-be-shared lifecycle decisions into focused helpers so submitted one-stage jobs can reuse parent-runner semantics.
- Extensibility: Gives SLURM, containers, and later submitted executors generic prepared-run and path contracts without coupling them to CLI or local-runner internals.
- Domain neutrality: All new contracts describe generic run preparation and generated artifacts; no HPC- or SLURM-specific concepts enter generic execution/store modules.
- Source-tree boundaries: Execution owns lifecycle semantics, stores own persisted layout and path safety, executors remain backend adapters, and CLI remains untouched.

## Future Compatibility

- Phase 2 can implement continuation commands on top of prepared-run metadata and lifecycle helpers.
- Phase 3 and Phase 4 can write SLURM dry-run artifacts using the store-owned generated-artifact path helper without path-walking run directories.
- V7 live SLURM submission can extend planned-submission records with scheduler facts without changing this generic prepared-run foundation.
- Stronger locking and multi-coordinator semantics remain possible because this phase does not encode a scheduler-specific locking policy.

## Alternatives Rejected

| Alternative | Reason rejected |
| --- | --- |
| Put prepared-run metadata under `loom.pipeline.executors.slurm` | Phase 1 is the generic foundation for multiple submitted executors; SLURM-specific placement would duplicate lifecycle contracts later. |
| Persist unredacted resolved config as the prepared-run command source | The v6 plan treats resolved config and resolver outputs as potentially secret-bearing and rejects that replay strategy. |
| Have SLURM code path-walk run directories for scripts/manifests | Run-store path safety and layout ownership belong in `loom.pipeline.stores`; adapter-local path walking would bypass safety checks. |
| Reuse or mutate `loom stage run` into a self-finalizing submitted-job runner | Existing v5 subprocess behavior depends on `loom stage run` as a parent-managed handoff-only worker; Phase 2 owns the separate stage-job command. |

## Debt Introduced

| Debt | Reason accepted | Revisit trigger |
| --- | --- | --- |
| Strong submitted-job locking remains deferred | Phase 1 is cluster-free and prepares contracts; existing run locks are enough unless implementation finds a local correctness issue. | V7 live submission, retries, duplicate submitted workers, or multi-coordinator recovery require stronger locking. |
| Full secret-surface regression across every v6 artifact is not completed here | Phase 1 owns prepared-run metadata and immediate plan/fingerprint safety checks; later SLURM surfaces do not exist yet. | Phase 6 hardening must cover the full secret-boundary matrix or record accepted residual risk. |

## Reviewability

- Expected PR size and shape: moderate generic execution/store PR with focused tests; no scheduler adapter, CLI, or broad docs changes beyond this phase artifact if implementation chooses to update local API docs.
- Files and areas to inspect: `src/loom/pipeline/execution/`, `src/loom/pipeline/stores/`, `tests/unit/loom/pipeline/execution/`, `tests/unit/loom/pipeline/stores/`, `tests/contracts/`, `tests/integration/pipeline/`, and package import-boundary tests.
- Scope-control checks: no `loom.pipeline.executors.slurm` code, no CLI command additions, no `sbatch` references, no scheduler statuses or job IDs, no resolved secret-bearing payloads in prepared-run metadata.

## Implementation Steps

1. Add prepared-run data models and validation under execution, including explicit schema version, round-trip methods, public exports, and structured errors for unsafe payloads.
2. Add run-store protocol methods and local-store persistence for prepared-run metadata with atomic JSON writes and contract tests.
3. Add the generated-artifact path helper to the run-store path protocol and local implementation using existing path validation/containment helpers.
4. Extract lifecycle helpers from `PipelineRunner` only where needed for future reuse, keeping current local/subprocess behavior stable and covered by existing tests.
5. Add targeted safety tests proving prepared-run payloads and generated paths reject secret-bearing or unsafe data, then run focused local/subprocess regression tests.

## Test Plan

### Package Suite

- Status: required
- Expected paths: `tests/package/test_import.py`, `tests/package/test_pipeline_execution_api.py`, `tests/package/test_pipeline_store_api.py`, `tests/package/test_import_boundaries.py`
- Required assertions or deferral reason: execution and store exports remain importable, typed, and free of optional SLURM dependencies; lower layers still do not import `loom.cli`.

### Unit Suite

- Status: required
- Expected paths: new or updated `tests/unit/loom/pipeline/execution/test_prepared_run.py`, `tests/unit/loom/pipeline/execution/test_lifecycle.py`, `tests/unit/loom/pipeline/execution/test_stage_attempts.py`, `tests/unit/loom/pipeline/execution/test_runner.py`, `tests/unit/loom/pipeline/stores/test_local_runs.py`
- Required assertions or deferral reason: prepared-run model validation and round trip; unsafe payload rejection for unredacted resolved config, resolver outputs, environment data, and raw adapter payloads; lifecycle helper success/failure behavior; local/subprocess behavior preservation; generated-artifact path helper accepts safe nested relative paths and rejects traversal, absolute paths, empty components, and control characters.

### Contract Suite

- Status: required
- Expected paths: `tests/contracts/test_store_contract.py` plus a new or updated execution prepared-run contract test if public APIs are introduced
- Required assertions or deferral reason: `RunStore`/`LocalRunStorePaths` protocol conformance includes prepared-run metadata and generated-artifact path resolution; dummy stores make new protocol obligations explicit; persisted prepared-run records are schema-versioned and plain-data compatible.

### Integration Suite

- Status: required
- Expected paths: `tests/integration/pipeline/test_local_execution.py`, `tests/integration/pipeline/test_subprocess_executor_integration.py`, and targeted new prepared-run/store integration coverage if unit/contract tests do not exercise real `LocalRunStore` round trips.
- Required assertions or deferral reason: existing local and subprocess execution still pass after lifecycle extraction; prepared-run metadata can be written/read against a real local run store; generated-artifact paths resolve under real run directories.

### E2E Suite

- Status: deferred
- Expected paths: none for this phase beyond existing local/subprocess e2e coverage if touched
- Required assertions or deferral reason: public continuation commands and SLURM dry-run CLI behavior do not exist until later phases, so new e2e coverage would be premature.

### Opt-In Suites

- Status: deferred
- Markers affected: none
- Required assertions or deferral reason: Phase 1 is deterministic and cluster-free; no real SLURM, scheduler, remote-store, or heavy environment suite applies.

## Risks

- Lifecycle extraction can subtly change parent-runner status, event, artifact-index, or failure semantics; mitigate with focused regression tests before broad validation.
- Secret safety is easy to weaken by accepting generic mappings too broadly; mitigate with deny-by-default validation for known unsafe payload categories and explicit artifact-safe summaries.
- Adding store protocol methods can break dummy stores and tests; mitigate by updating contract fixtures deliberately so new obligations are visible.
- Path helper behavior may become too SLURM-shaped; keep it as generic relative path resolution and leave adapter layout to later phases.

## Validation Commands

Targeted development commands:

```sh
uv run pytest tests/package/test_pipeline_execution_api.py tests/package/test_pipeline_store_api.py tests/package/test_import_boundaries.py
uv run pytest tests/unit/loom/pipeline/execution/test_prepared_run.py tests/unit/loom/pipeline/execution/test_lifecycle.py tests/unit/loom/pipeline/execution/test_runner.py tests/unit/loom/pipeline/stores/test_local_runs.py
uv run pytest tests/contracts/test_store_contract.py
uv run pytest tests/integration/pipeline/test_local_execution.py tests/integration/pipeline/test_subprocess_executor_integration.py
```

Final PR-preparation commands:

```sh
make validate-pr
make test-summary
```

## Handoff Notes For `loom_phase_executor`

- Safe implementation slices: prepared-run model/API first, store persistence second, generated-artifact path helper third, lifecycle helper extraction last unless an earlier slice needs it.
- Tests to run with each slice: run the matching unit/contract tests after each slice; run local and subprocess integration tests after lifecycle extraction.
- Decisions the executor must not revisit: no SLURM-specific code in Phase 1; no continuation CLI commands; no resolved-config replay source; no mutation of `loom stage run` into a submitted-job finalizer; no scheduler state or fake job IDs.
- Conditions that require stopping for the manager: prepared-run metadata cannot be made secret-safe without redesigning persisted plan/fingerprint payloads; lifecycle extraction requires public behavior changes; generated-artifact path safety conflicts with existing run URI/path helpers; a required test suite cannot run for a non-environmental reason.
- Expanded-path refinement notes: refine pass should review whether the prepared-run payload contract is specific enough for Phase 2 and whether lifecycle extraction boundaries are narrow enough to keep the implementation PR reviewable.

## Refinement And Review Budget Status

- Phase implementation refinement: unused
- PR review: unused
- Blocker resolution: 0/3 used

## Completion Notes

- Draft plan: completed in this pass and committed with `plan: add phase execution plan`
- Final phase execution plan: pending expanded-path refine pass
- Implementation summary: TBD
- Implementation validation: TBD
- Refinement summary: TBD
- Blocker-resolution summary: TBD
- PR preparation: TBD
- Stack maintenance: TBD
- Remaining blockers: none known at draft time
