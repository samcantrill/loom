# Phase 1 Execution Plan: Prepared-Run And Lifecycle Foundations

## Metadata

- Status: refined phase execution plan
- Feature focus: SLURM Script Planning
- PR title: `SLURM Script Planning - Phase 1: Prepared-Run And Lifecycle Foundations`
- Branch: `codex/slurm-prepared-run-foundations`
- Worktree: `/home/samcantrill/work/loom-worktrees/slurm-prepared-run-foundations`
- Phase execution plan path: `docs/roadmap/stage-6/phases/slurm-prepared-run-foundations.md`
- Full plan: `docs/roadmap/stage-6/implementation-plan.md`
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
- Refine pass: completed by `loom_phase_planner` for expanded path
- Setup limitations: Worktree was created from local `develop`; no remote synchronization or validation was run in this planning-only pass.
- Blockers: none known for implementation handoff

## Objective

Define a generic prepared-run record, payload safety rules, narrow shared execution lifecycle helper boundaries, and a store-owned generated-artifact path helper before SLURM dry-run models or continuation commands are added.

## Full-Plan Context

V6 adds SLURM dry-run script planning without live scheduler submission. This first phase deliberately stays generic so later SLURM scripts can invoke stable execution-owned continuation surfaces instead of duplicating runner lifecycle logic. Phase 2 adds public continuation commands, Phase 3 adds SLURM models, Phase 4 writes scripts and dry-run manifests, Phase 5 wires CLI/preflight behavior, and Phase 6 hardens e2e/docs coverage. This phase must not add SLURM models, script generation, CLI executor selection, `sbatch`, scheduler state, or live-submission behavior.

## Stack Context

- Root or stacked phase: root phase
- Current predecessor branch or PR: none
- Why this base branch is correct: v6 has no earlier phase; the manager assigned `develop` as the stack base.
- Retarget/rebase plan after predecessor merge: none required unless `develop` moves before PR preparation, in which case rebase this branch onto updated `develop`.
- Branch cleanup constraints: branch can be deleted after merge if no successor branch depends on it.

## Source Phase Summary

- Goal: Define generic, secret-safe prepared-run records and shared execution lifecycle helper boundaries needed by whole-run and one-stage continuation.
- Required scope: Add prepared-run metadata under execution/store boundaries; define allowed persisted payloads and rejection behavior for secret-bearing payloads; extract or add lifecycle helpers for input binding, output commit, provenance/failure commit, artifact-index updates, and status updates; add a path-safe run-store helper for run-scoped generated artifacts.
- Required checkpoints: Preserve existing local/subprocess behavior, keep generic helpers free of SLURM-specific branches, and expose generated-artifact path resolution through store-owned APIs.
- Acceptance criteria: Prepared-run metadata round-trips through public execution/store APIs as a sibling record rather than an overloaded `StageWorkerRequest`; unsafe resolved config, resolver outputs, environment values, and raw adapter payloads are absent or rejected with structured errors; lifecycle helpers keep current semantics; generated artifact paths reject unsafe relative paths without knowing SLURM layout.

## Current Source And Harness Findings

- Existing files or modules that constrain this phase: `src/loom/pipeline/execution/runner.py` currently owns input binding, stage execution commits, failure commits, artifact-index updates, status writes, and event commits; `src/loom/pipeline/execution/stage_attempts.py` owns v5 prepared worker request creation and must remain separate from the new prepared-run record; `src/loom/pipeline/execution/lifecycle.py` already contains status helpers; `src/loom/pipeline/execution/stage_worker.py` reconstructs handoff-only subprocess attempts and must stay handoff-only; `src/loom/pipeline/stores/run_store.py` defines store protocols; `src/loom/pipeline/stores/local_runs.py` owns local persisted file layout and path helpers; `src/loom/pipeline/stores/_paths.py` owns path containment and validation primitives that should back the generated-artifact path helper.
- Existing tests or harness behavior: package tests cover import boundaries; unit tests cover runner, lifecycle, stage attempts, stage worker, and local run stores; contract tests cover `RunStore`, `LocalRunStorePaths`, executor contracts, and stage-worker behavior; integration tests cover local and subprocess execution.
- Import-boundary or dependency constraints: lower execution/store layers must not import `loom.cli`; this phase must not introduce `loom.pipeline.executors.slurm` or optional scheduler dependencies; authored configs are trusted project code, but persisted prepared-run payloads must remain artifact-safe.

## In-Scope Work

- Add schema-versioned prepared-run metadata models and execution APIs under `loom.pipeline.execution` as a run-level sibling record to `StageWorkerRequest`, not as an extension of the v5 worker request.
- Add run-store protocol and local-store read/write support for prepared-run metadata.
- Define and enforce prepared-run payload safety: plain-data only; schema version, run URI, prepared-at timestamp, safe config/provenance/runtime summary references, executor/continuation intent, plan identity or summary, and optional typed safe metadata only; no unredacted resolved config snapshots, resolver outputs, environment variable names or values, resolved secret-bearing runtime values, or raw adapter payloads by default.
- Extract shared lifecycle helpers from `PipelineRunner` only for behavior it already owns: input binding, output/provenance/artifact-index commit, failure/status/event commit, and status/event helper boundaries. The helpers must not implement Phase 2 self-finalizing stage-job execution.
- Add a store-owned helper for resolving run-scoped generated artifact paths under a run directory from safe relative paths using existing path validation and containment primitives.
- Update focused package, unit, contract, and integration tests for the new contracts.

## Out-of-Scope Work

- No SLURM models, options, resource mapping, scripts, dry-run manifests, preflight checks, or `loom.pipeline.executors.slurm` package.
- No `loom prepared-run continue` or `loom stage-job run` CLI/API entry points; those belong to Phase 2.
- No live scheduler submission, scheduler job IDs, submitted status, `sbatch`, `squeue`, `sacct`, `scancel`, or fake scheduler state.
- No conversion of the existing `loom stage run` handoff-only worker into a self-finalizing submitted-job runner.
- No generic wall-time resource, container command composition, remote store support, or stronger distributed locking unless a local correctness blocker is discovered.

## Assumptions

- Prepared-run metadata is a run-level sibling record, not stage worker request metadata and not a replacement for `StageWorkerRequest`.
- The local store can persist prepared-run metadata as a plain schema-versioned JSON document under the run directory while keeping exact filename/layout owned by the store implementation.
- The generated-artifact path helper should accept safe relative paths such as `slurm/submissions/<planning_id>/manifest.json` and reject absolute paths, parent traversal, empty components, control characters, and paths that resolve outside the run directory. It should require only valid run URI/path resolution unless the local implementation needs stricter existence checks.
- Existing plan and fingerprint payloads may contain resolved stage data; this phase must add immediate safety checks around new prepared-run metadata and any prepared-run references to plan/fingerprint records, but does not need to complete the full Phase 6 secret-surface regression matrix.

## Scope Contract

Prepared-run metadata is a generic execution/store contract. It must be schema-versioned, plain-data serializable, and sufficient for later continuation commands to validate an existing run, persisted plan identity, prepared executor choice, run URI, safe config/provenance/runtime summaries, and expected continuation mode without reading CLI state. It is a run-level sibling record; it must not overload `StageWorkerRequest`, mutate `loom stage run`, or encode one-stage submitted-job execution.

Allowed prepared-run payload categories are: scalar identifiers and timestamps; schema/version fields; run URI; safe references to existing run-store documents; redacted or artifact-safe config/provenance summaries; runtime summaries that follow `runtime.json` safety rules; typed executor or continuation intent; plan digest, plan path, or plan summary without raw resolved values; and explicitly typed safe metadata. Rejection must be structured and testable when callers try to persist unredacted resolved config, resolver outputs, environment variable names or values, resolved secret-bearing runtime values, raw adapter payloads, scheduler facts, scheduler job IDs, or arbitrary opaque mappings.

The shared lifecycle helpers must preserve current local and subprocess outcomes. They may move logic out of `PipelineRunner`, but only for lifecycle behavior already owned there: input binding, stage output validation/commit, provenance/failure document commit, artifact-index update, stage/run status writes, and event emission. They must not change public run statuses, stage statuses, artifact indexes, provenance/failure payload shapes, stage worker request/result contracts, or event ordering except where tests explicitly document an invariant-preserving extraction. They must not implement the Phase 2 self-finalizing `loom stage-job run` flow.

The run-scoped generated-artifact helper is a store path contract, not a SLURM contract. It accepts only safe relative paths, resolves them under the run directory, and returns local paths for writers. It rejects absolute paths, parent traversal, empty components, control characters, and containment escapes. It should not inspect SLURM-specific path segments or require the generated artifact to already exist.

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
| Reuse or mutate `loom stage run` into a self-finalizing submitted-job runner | Existing v5 subprocess behavior depends on `loom stage run` as a parent-managed handoff-only worker; Phase 2 owns the separate `loom stage-job run` command. |
| Store prepared-run data inside `StageWorkerRequest` | Whole-run continuation and submitted-stage continuation need a run-level preparation record; overloading the v5 worker request would couple future submitted behavior to the subprocess handoff format. |

## Debt Introduced

| Debt | Reason accepted | Revisit trigger |
| --- | --- | --- |
| Strong submitted-job locking remains deferred | Phase 1 is cluster-free and prepares contracts; existing run locks are enough unless implementation finds a local correctness issue. | V7 live submission, retries, duplicate submitted workers, or multi-coordinator recovery require stronger locking. |
| Full secret-surface regression across every v6 artifact is not completed here | Phase 1 owns prepared-run metadata and immediate plan/fingerprint safety checks; later SLURM surfaces do not exist yet. | Phase 6 hardening must cover the full secret-boundary matrix or record accepted residual risk. |

## Reviewability

- Expected PR size and shape: moderate generic execution/store PR with focused tests; no scheduler adapter, CLI, or broad docs changes beyond this phase artifact if implementation chooses to update local API docs.
- Files and areas to inspect: `src/loom/pipeline/execution/`, `src/loom/pipeline/stores/`, `tests/unit/loom/pipeline/execution/`, `tests/unit/loom/pipeline/stores/`, `tests/contracts/`, `tests/integration/pipeline/`, and package import-boundary tests.
- Scope-control checks: no `loom.pipeline.executors.slurm` code, no CLI command additions, no `sbatch` references, no scheduler statuses or job IDs, no resolved secret-bearing payloads in prepared-run metadata, no overload of `StageWorkerRequest`, and no self-finalizing stage-job runner implementation.

## Implementation Steps

1. Add prepared-run data models and validation under execution, including explicit schema version, round-trip methods, public exports, allowed safe summary fields, and structured errors for unsafe payloads.
2. Add run-store protocol methods and local-store persistence for prepared-run metadata with atomic JSON writes and contract tests.
3. Add the generated-artifact path helper to the run-store path protocol and local implementation using existing path validation/containment helpers.
4. Extract lifecycle helpers from `PipelineRunner` only where needed for future reuse of existing runner-owned behavior, keeping current local/subprocess behavior stable and covered by existing tests.
5. Add targeted safety tests proving prepared-run payloads and generated paths reject secret-bearing or unsafe data, then run focused local/subprocess regression tests.

## Test Plan

### Package Suite

- Status: required
- Expected paths: `tests/package/test_import.py`, `tests/package/test_pipeline_execution_api.py`, `tests/package/test_pipeline_store_api.py`, `tests/package/test_import_boundaries.py`
- Required assertions or deferral reason: execution and store exports remain importable, typed, and free of optional SLURM dependencies; prepared-run public exports are cheap to import; lower layers still do not import `loom.cli`.

### Unit Suite

- Status: required
- Expected paths: new or updated `tests/unit/loom/pipeline/execution/test_prepared_run.py`, `tests/unit/loom/pipeline/execution/test_lifecycle.py`, `tests/unit/loom/pipeline/execution/test_stage_attempts.py`, `tests/unit/loom/pipeline/execution/test_runner.py`, `tests/unit/loom/pipeline/stores/test_local_runs.py`
- Required assertions or deferral reason: prepared-run model validation and round trip; sibling-record behavior separate from `StageWorkerRequest`; unsafe payload rejection for unredacted resolved config, resolver outputs, environment variable names/values, resolved secret-bearing runtime values, arbitrary opaque metadata, scheduler facts, and raw adapter payloads; allowed payload summaries serialize deterministically; lifecycle helper success/failure behavior preserves status/event/payload semantics; local/subprocess behavior preservation; generated-artifact path helper accepts safe nested relative paths and rejects traversal, absolute paths, empty components, control characters, and containment escapes.

### Contract Suite

- Status: required
- Expected paths: `tests/contracts/test_store_contract.py` plus a new or updated execution prepared-run contract test if public APIs are introduced
- Required assertions or deferral reason: `RunStore`/`LocalRunStorePaths` protocol conformance includes prepared-run metadata and generated-artifact path resolution; dummy stores make new protocol obligations explicit; persisted prepared-run records are schema-versioned and plain-data compatible; generated-artifact path helper contract is safe-relative-path only and does not encode SLURM semantics.

### Integration Suite

- Status: required
- Expected paths: `tests/integration/pipeline/test_local_execution.py`, `tests/integration/pipeline/test_subprocess_executor_integration.py`, and targeted new prepared-run/store integration coverage if unit/contract tests do not exercise real `LocalRunStore` round trips.
- Required assertions or deferral reason: existing local and subprocess execution still pass after lifecycle extraction; `loom stage run` remains handoff-only; prepared-run metadata can be written/read against a real local run store; generated-artifact paths resolve under real run directories without requiring target files to pre-exist unless the implementation documents a local-store need.

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

- Safe implementation slices: prepared-run sibling record/API first, store persistence second, generated-artifact path helper third, lifecycle helper extraction last unless an earlier slice needs it.
- Tests to run with each slice: run the matching unit/contract tests after each slice; run local and subprocess integration tests after lifecycle extraction.
- Decisions the executor must not revisit: no SLURM-specific code in Phase 1; no continuation CLI commands; no resolved-config replay source; no mutation of `loom stage run` into a submitted-job finalizer; no overloading `StageWorkerRequest`; no scheduler state or fake job IDs.
- Conditions that require stopping for the manager: prepared-run metadata cannot be made secret-safe without redesigning persisted plan/fingerprint payloads; lifecycle extraction requires public behavior changes or implementing Phase 2 stage-job behavior; generated-artifact path safety conflicts with existing run URI/path helpers; a required test suite cannot run for a non-environmental reason.
- Expanded-path refinement notes: completed. The refined boundaries specify a sibling prepared-run record, narrow runner-owned lifecycle extraction, deny-by-default payload safety, and safe-relative generated-artifact path semantics.

## Refinement And Review Budget Status

- Phase implementation refinement: used
- PR review: used
- Blocker resolution: 1/3 used (prepared-run store persistence payload-safety
  blocker fixed during the implementation refinement pass)

## Completion Notes

- Draft plan: completed in the draft pass and committed with `plan: add phase execution plan`
- Final phase execution plan: completed in expanded-path refine pass
- Implementation summary: completed on 2026-05-08 by fallback implementation pass in `/home/samcantrill/work/loom-worktrees/slurm-prepared-run-foundations`. Added schema-versioned `PreparedRunRecord` and `PreparedRunPayloadError` under `loom.pipeline.execution`; exported the public prepared-run API without changing `StageWorkerRequest`; added `RunPreparedRunStore` protocol support and local `prepared_run.json` persistence; added store-owned safe-relative generated artifact path resolution; extracted generic input binding and artifact-index update helpers into `execution.lifecycle` while preserving runner semantics.
- Implementation refinement summary: completed on 2026-05-08 as the single
  expanded-path implementation refinement pass. Reviewed the executor-reported
  targeted pytest, focused Ruff, and `make validate-pr` evidence; confirmed no
  Phase 2 continuation CLI, SLURM package, script generation, scheduler state,
  or `loom stage run` self-finalization was added. Fixed the concrete Phase 1
  blocker where `LocalRunStore.write_prepared_run` could persist unsafe nested
  prepared-run payloads supplied as plain mappings that bypassed
  `PreparedRunRecord`.
- Implementation commits:
  - `6880d80` - `feat: add prepared-run store foundations`
  - `3ea69b1` - `test: cover prepared-run foundations`
  - `58bbbac` - `fix: satisfy prepared-run store typing`
  - `854c15e` - `fix: update store export test`
- Scope control: implements only Phase 1 generic execution/store foundations. No SLURM package, script generation, dry-run manifest, CLI continuation command, scheduler state, scheduler job ID, `sbatch`, `loom prepared-run continue`, or `loom stage-job run` was added. The v5 `loom stage run` handoff-only worker contract remains unchanged.
- Tests added or updated:
  - Package: `tests/package/test_pipeline_execution_api.py`, `tests/package/test_pipeline_store_api.py`
  - Unit: `tests/unit/loom/pipeline/execution/test_prepared_run.py`, `tests/unit/loom/pipeline/execution/test_lifecycle.py`, `tests/unit/loom/pipeline/stores/test_local_runs.py`, `tests/unit/loom/pipeline/stores/test_store_errors.py`
  - Contract: `tests/contracts/test_store_contract.py`
  - Integration: `tests/integration/pipeline/test_local_stores.py`
  - E2E and opt-in: not added; deferred as planned because Phase 1 has no public continuation commands, SLURM dry-run CLI, or scheduler integration.
- Implementation refinement fixes:
  - Added a store-owned prepared-run payload validator and
    `PreparedRunStorePayloadError` so public store persistence rejects unsafe
    nested payloads without importing execution from stores.
  - Routed `PreparedRunRecord` summary and typed metadata checks through the
    same store-safe validation boundary to keep execution and persistence
    semantics aligned.
  - Tightened typed metadata so raw adapter, scheduler fact, environment,
    resolved-value, secret, and job-ID categories cannot hide behind a safe
    wrapper or unsafe metadata `kind`.
  - Added regression coverage proving `LocalRunStore.write_prepared_run`
    rejects unsafe nested raw adapter payloads before writing
    `prepared_run.json`.
- Implementation validation:
  - `uv run pytest tests/package/test_pipeline_execution_api.py tests/package/test_pipeline_store_api.py tests/package/test_import_boundaries.py tests/unit/loom/pipeline/execution/test_prepared_run.py tests/unit/loom/pipeline/execution/test_lifecycle.py tests/unit/loom/pipeline/execution/test_runner.py tests/unit/loom/pipeline/stores/test_local_runs.py tests/contracts/test_store_contract.py tests/integration/pipeline/test_local_stores.py tests/integration/pipeline/test_local_execution.py tests/integration/pipeline/test_subprocess_executor_integration.py` - passed: 108 passed, 1 skipped.
  - `uv run ruff check src/loom/pipeline/execution src/loom/pipeline/stores tests/package/test_pipeline_execution_api.py tests/package/test_pipeline_store_api.py tests/unit/loom/pipeline/execution/test_prepared_run.py tests/unit/loom/pipeline/execution/test_lifecycle.py tests/unit/loom/pipeline/stores/test_local_runs.py tests/contracts/test_store_contract.py tests/integration/pipeline/test_local_stores.py` - passed.
  - `make validate-pr` - passed: Ruff passed; Pyright passed with 0 errors; default harness passed 745 selected tests, 14 skipped, 8 deselected; config-extra harness passed 405 selected tests, 763 deselected; `uv build` produced source distribution and wheel.
  - `make test-summary` - not run in this implementation pass because PR preparation was explicitly out of scope.
- Implementation refinement validation:
  - Initial `uv run pytest ...` failed before running tests because the default
    uv cache path under `/home/samcantrill/.cache/uv` was read-only in the
    sandbox; reruns used `UV_CACHE_DIR=/tmp/uv-cache`.
  - `UV_CACHE_DIR=/tmp/uv-cache uv run pytest tests/unit/loom/pipeline/execution/test_prepared_run.py tests/unit/loom/pipeline/stores/test_local_runs.py tests/unit/loom/pipeline/stores/test_store_errors.py tests/contracts/test_store_contract.py tests/integration/pipeline/test_local_stores.py tests/package/test_pipeline_execution_api.py tests/package/test_pipeline_store_api.py` - passed: 70 passed.
  - `UV_CACHE_DIR=/tmp/uv-cache uv run pytest tests/package/test_pipeline_execution_api.py tests/package/test_pipeline_store_api.py tests/package/test_import_boundaries.py tests/unit/loom/pipeline/execution/test_prepared_run.py tests/unit/loom/pipeline/execution/test_lifecycle.py tests/unit/loom/pipeline/execution/test_runner.py tests/unit/loom/pipeline/stores/test_local_runs.py tests/unit/loom/pipeline/stores/test_store_errors.py tests/contracts/test_store_contract.py tests/integration/pipeline/test_local_stores.py tests/integration/pipeline/test_local_execution.py tests/integration/pipeline/test_subprocess_executor_integration.py` - passed: 116 passed.
  - `UV_CACHE_DIR=/tmp/uv-cache uv run ruff check src/loom/pipeline/execution src/loom/pipeline/stores tests/package/test_pipeline_execution_api.py tests/package/test_pipeline_store_api.py tests/unit/loom/pipeline/execution/test_prepared_run.py tests/unit/loom/pipeline/execution/test_lifecycle.py tests/unit/loom/pipeline/stores/test_local_runs.py tests/unit/loom/pipeline/stores/test_store_errors.py tests/contracts/test_store_contract.py tests/integration/pipeline/test_local_stores.py` - passed.
  - `UV_CACHE_DIR=/tmp/uv-cache make validate-pr` - passed: Ruff passed;
    Pyright passed with 0 errors; default harness passed 747 selected tests,
    14 skipped, 8 deselected; config-extra harness passed 405 selected tests,
    765 deselected; `uv build` produced source distribution and wheel.
- Refinement summary: tightened prepared-run sibling-record contract, lifecycle extraction scope, payload safety rules, generated-artifact path semantics, and suite obligations from manager review notes
- Blocker-resolution summary: concrete prepared-run store persistence
  payload-safety blocker resolved during this implementation refinement pass;
  no separate blocker-resolution pass was run.
- PR preparation draft: completed on 2026-05-08 using
  `.codex/prompts/pr-body-draft.md`, `.codex/templates/phase-pr-body.md`, and
  `.github/PULL_REQUEST_TEMPLATE.md`. Created
  `docs/roadmap/stage-6/phases/slurm-prepared-run-foundations-pr-body.md` for the expanded-path
  draft pass.
- PR body refine/open pass: completed on 2026-05-08 using
  `.codex/prompts/pr-body-refine.md`. Verified the dedicated worktree,
  branch, refined phase plan, draft PR body, implementation diff, acceptance
  criteria, validation evidence, scope boundaries, assumptions, risks, and PR
  template. Updated the PR body GitHub checks row to `Pending` because remote
  checks run after PR creation.
- PR facts for refine/open pass: opened PR
  `https://github.com/samcantrill/loom/pull/82` with branch
  `codex/slurm-prepared-run-foundations`; target branch `develop`; stack
  predecessor none; PR title
  `SLURM Script Planning - Phase 1: Prepared-Run And Lifecycle Foundations`.
  Immediate `gh pr view 82 --json baseRefName,headRefName,state,url`
  verification returned base `develop`, head
  `codex/slurm-prepared-run-foundations`, state `OPEN`, and URL
  `https://github.com/samcantrill/loom/pull/82`. Merge eligibility remains
  root phase; merge-eligible only after automated review passes and
  validation/CI passes.
- PR body scope confirmation: final diff matches Phase 1 generic
  execution/store foundations only. No SLURM package, script generation,
  dry-run manifest, CLI continuation command, scheduler state, scheduler job
  ID, `sbatch`, `loom prepared-run continue`, `loom stage-job run`, or
  self-finalizing `loom stage run` behavior was added.
- PR body draft validation:
  - `UV_CACHE_DIR=/tmp/uv-cache make test-summary` - passed and wrote
    `build/test-summary.md`: package 50 passed, 1 skipped; unit 621 passed,
    1 skipped; contract 55 passed, 2 skipped; integration 21 passed,
    7 skipped, 8 deselected; e2e 18 passed; config-extra 405 passed,
    765 deselected; overall 1170 passed, 0 failed, 0 errors, 11 skipped,
    773 deselected in 47.36s.
- PR body draft status: complete; refine status: complete; PR review budget:
  used; blocker-resolution budget remains 1/3 used for the prepared-run store
  persistence payload-safety blocker resolved during implementation refinement.
- Automated manager review: passed on 2026-05-08 after PR opening. Review
  checked the refined phase plan, PR body, final diff, suite evidence, scope
  boundaries, and GitHub PR target. No blocking findings remained. Confirmed
  the PR targets `develop`, implements only Phase 1 generic execution/store
  foundations, preserves the v5 `loom stage run` handoff-only contract, avoids
  Phase 2 continuation CLI and all SLURM/script/scheduler behavior, and has
  passing local `make validate-pr` and `make test-summary` evidence.
- Stack maintenance: not started; no successor branch work in this implementation pass.
- Remaining blockers: none known after implementation refinement and validation.
