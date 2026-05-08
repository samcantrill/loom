# Phase 1 Execution Plan: Submitted Lifecycle And Registry Foundations

## Metadata

- Status: ready for implementation
- Feature focus: SLURM Live Operations
- PR title: `SLURM Live Operations - Phase 1: Submitted Lifecycle and Registry Foundations`
- Branch: `codex/slurm-submitted-lifecycle`
- Worktree: `/home/samcantrill/work/loom-worktrees/slurm-submitted-lifecycle`
- Phase execution plan path: `docs/phases/slurm-submitted-lifecycle.md`
- Full plan: `docs/implementation-plans/implementation-plan-v7.md`
- Source phase: Phase 1 - Submitted Lifecycle And Registry Foundations
- Stack predecessor: none
- Base branch: local `develop` at `666b3f6` (`docs: add v7 implementation plan`)
- Target branch: `develop`
- Merge eligibility: root phase; merge-eligible only when the PR targets `develop`, automated review passes, validation/CI passes, and the implementation remains limited to Phase 1.
- Workflow path: expanded path because this phase changes public shared lifecycle/status semantics, run-store registry contracts, and stage-job continuation behavior.
- Successor dependency notes: Phases 2-6 rely on this phase for the shared `SUBMITTED` statuses, submitted-operation discovery helpers, active-submission predicate, and submitted stage-job startup guard. No successor should require SLURM imports from generic code.
- Plan quality gate: passed on 2026-05-08 after initial review, one refinement pass, and confirmation review.
- Plan quality gate loop budget: initial review used, gate refinement used, confirmation review used.
- Draft pass: complete by `loom_phase_planner` in this artifact.
- Refine pass: complete by `loom_phase_planner` in this artifact after source and test inspection.
- Setup limitations: branch and worktree were supplied by the manager; no product-code validation or broad checks were run during planning.
- Blockers: none known for implementation handoff.

## Objective

Add Loom's generic submitted lifecycle foundation: shared `SUBMITTED` run and stage status values, safe lifecycle writers, submitted-operation registry models and run-store discovery helpers, diagnostics visibility for persisted submitted state, and a narrowly validated `SUBMITTED -> RUNNING` stage-job continuation path.

## Full-Plan Context

V7 turns the v6 cluster-free SLURM dry-run artifacts into optional live scheduler operations. Phase 1 is the public status and run-store foundation that must land before SLURM command runners, live manifests, submission, scheduler polling, or cancellation exist. Later phases will put SLURM command parsing and manifests under `loom.pipeline.executors.slurm`; this phase keeps all shared lifecycle and submitted-operation discovery under generic execution/store/diagnostics boundaries.

Future-phase work that must stay out of scope: `sbatch`, `squeue`, `sacct`, `scancel`, fake or real scheduler command runners, live submission APIs, scheduler snapshots, cancellation, active old-job guards, SLURM manifest live fields, and `loom status --jobs` scheduler queries.

## Stack Context

- Root or stacked phase: root phase.
- Current predecessor branch or PR: none.
- Why this base branch is correct: all prior v7 work is only the merged plan commit on local `develop`; the manager assigned `develop` at `666b3f6` as the base and PR target.
- Retarget/rebase plan after predecessor merge: none required unless `develop` advances before PR preparation; then rebase this root branch onto updated `develop` and keep the target as `develop`.
- Branch cleanup constraints: branch can be deleted after merge if no successor branches depend on it.

## Source Phase Summary

- Goal: add the shared submitted lifecycle vocabulary and generic submitted-operation discovery contract before SLURM live submission uses it.
- Required scope: add `RunStatus.SUBMITTED` and `StageStatus.SUBMITTED`; update parsing, serialization, display, transition helpers, run-store tests, diagnostics summaries, CLI status output, and resume interpretation; add submitted lifecycle writers; add generic submitted-operation records and discovery helpers; add submitted stage-job continuation validation; expose persisted submitted state in ordinary status without scheduler access.
- Required checkpoints: no generic code imports `loom.pipeline.executors.slurm`; `SUBMITTED` is non-terminal and not reusable; latest/latest-active registry selection is deterministic by `created_at` then `submission_id`; the active predicate is shared by future submit/status/cancel code.
- Acceptance criteria: status records round-trip `SUBMITTED`; local/subprocess behavior is unchanged; submitted-operation records are backend-neutral and schema-versioned; registry helpers expose latest, latest active, backend, mode, submission ID, manifest path, and state; matching submitted stage jobs can transition to `RUNNING`; mismatched or stale submitted state is rejected before user stage code.

## Current Source And Harness Findings

- Existing files or modules that constrain this phase: `src/loom/pipeline/status.py` owns status enums and schema-versioned status record parsing; `src/loom/pipeline/execution/lifecycle.py` owns status writers but has no submitted writer; `src/loom/pipeline/execution/continuation.py` owns `loom stage-job run` validation and currently accepts only `PENDING` or `RUNNING` prepared attempts; `src/loom/pipeline/execution/stage_worker.py` and `stage_attempts.py` infer and prepare only `PENDING`/`RUNNING` worker state; `src/loom/pipeline/planning/resume.py` already treats any non-`SUCCEEDED` status as not reusable; `src/loom/pipeline/stores/run_store.py` and `local_runs.py` own run-store protocols, local generated-artifact paths, and inspection scans; `src/loom/diagnostics/inspection.py`, `src/loom/cli/status.py`, and `src/loom/cli/formatting.py` expose persisted status without project imports; `src/loom/pipeline/executors/slurm/*` already contains v6 dry-run manifest/path/script contracts that later phases will point to but this phase must not import.
- Existing tests or harness behavior: status model tests cover enum parsing and record round-trips; store contract/package tests assert public protocols and import boundaries; local-run tests cover status read/write, stage scans, generated-artifact paths, and path safety; stage-job unit/integration tests cover prepared attempt validation, recursive executor rejection, missing run status, upstream readiness, and finalization; diagnostics and CLI tests cover ordinary `loom status`; SLURM v6 unit/contract/integration/e2e tests prove dry-run manifest path `slurm/submissions/<planning_id>/manifest.json` and generated `stage-job run` commands.
- Import-boundary or dependency constraints: `loom.pipeline.stores` must not import `loom.cli`; generic execution/stores/diagnostics must not import `loom.pipeline.executors.slurm`; default package/import tests must not require scheduler commands or optional SLURM dependencies.

## In-Scope Work

- Add `SUBMITTED` to `RunStatus` and `StageStatus`, preserving schema version compatibility for existing documents and adding round-trip parsing/display coverage.
- Add generic lifecycle helpers to write submitted run and stage statuses without setting `started_at`, `finished_at`, or implying local execution. Submitted metadata must be plain-data, artifact-safe, and backend-neutral.
- Add submitted-operation data models and validation under generic store/execution boundaries. The record contract includes `schema_version`, `run_uri`, `submission_id`, `backend`, `mode`, `created_at`, `updated_at`, `state`, `manifest_relative_path`, summary counts, and optional backend metadata.
- Add generic submitted-operation state values and predicates for `PREPARED`, `SUBMITTING`, `SUBMITTED`, `PARTIAL`, `CANCELLING`, `CANCELLED`, `COMPLETED`, `FAILED`, and `UNKNOWN`.
- Add run-store protocol and `LocalRunStore` helpers to write/read/list submitted-operation records and discover latest and latest-active submissions deterministically.
- Add persisted submitted-state inspection shapes so ordinary `loom status RUN_URI` can display run/stage `SUBMITTED` and, when present, backend-neutral submitted-operation summaries without querying a scheduler.
- Extend `loom stage-job run` validation so a matching submitted prepared attempt may transition from `StageStatus.SUBMITTED` to `RUNNING` only when run URI, stage name, attempt, continuation executor, submitted backend identity, submission ID, manifest pointer, and backend-owned submission metadata agree with persisted registry and manifest records.
- Update resume/status interpretation tests so `SUBMITTED` is non-terminal, not reusable, and distinct from scheduler states.

## Out-of-Scope Work

- No SLURM command runner, command result model, `sbatch`, `squeue`, `sacct`, `scancel`, job ID parsing, fake scheduler, or real scheduler tests.
- No live `loom run --executor slurm-*` submission and no active old-job guard.
- No scheduler-aware `loom status --jobs` queries, scheduler snapshots, or core-status reconciliation.
- No `loom cancel`, cancellation records beyond generic registry states, or cancellation CLI behavior.
- No SLURM live manifest fields, partial afterok submission handling, dependency job ID mapping, or scheduler job IDs.
- No `loom slurm ...` command group.
- No remote stores, distributed locks, controller mode, retries, force/resubmit, job arrays, containers, or dashboard behavior.

## Assumptions

- The submitted-operation registry can live in a generic run-store area with one JSON record per submission or an equivalent schema-versioned index, as long as discovery uses store APIs and callers do not path-walk backend layouts.
- `manifest_relative_path` is a store-safe relative pointer to a backend-owned manifest; Phase 1 validates and stores the pointer but does not parse backend-specific SLURM live fields.
- The first implementation may use backend-neutral metadata keys for submitted stage-job validation, provided they are documented and tested as a contract that later SLURM phases must write.
- Ordinary `loom status RUN_URI` may expose a compact submitted-operation summary from persisted registry records, but it must not imply live scheduler state or mutate core status.

## Scope Contract

`SUBMITTED` is a shared Loom lifecycle state, not a scheduler state. `RunStatus.SUBMITTED` means work has been accepted by a submitted backend and the original submitting process may exit before final outcome. `StageStatus.SUBMITTED` means a prepared stage attempt has been accepted by a submitted backend but has not yet started local stage execution. Both are non-terminal. Neither is reusable for resume, and neither should be interpreted as `RUNNING`, `SUCCEEDED`, `FAILED`, `CANCELLED`, `SKIPPED`, `STALE`, or `BLOCKED`.

Submitted lifecycle writers must preserve existing local/subprocess semantics. Submitted runs and stages should record `updated_at`, plain metadata, owner information when applicable, and attempt identity for stages. They must leave `started_at` and `finished_at` unset unless an existing status contract explicitly requires otherwise. Transition to `RUNNING` remains the point where local stage code starts.

The generic submitted-operation record is backend-neutral. Required public fields are `schema_version`, `run_uri`, `submission_id`, `backend`, `mode`, `created_at`, `updated_at`, `state`, `manifest_relative_path`, and summary counts. Optional `backend_metadata` must be plain-data and artifact-safe. Backend-specific job details, scheduler job IDs, command outputs, status snapshots, and cancellation attempts stay out of this generic record and belong to later backend manifests.

Registry state predicates are part of the public contract. Active submissions are records in `SUBMITTED`, `PARTIAL`, `CANCELLING`, or `UNKNOWN`, or any record whose summary counts indicate non-terminal submitted work. Terminal submissions are `CANCELLED`, `COMPLETED`, and `FAILED` only when no submitted jobs can still be active. `PREPARED` and `SUBMITTING` are discoverable states but are not latest-active unless summary counts show active submitted work. Latest selection sorts by `created_at`, then `submission_id` as a deterministic tie-breaker.

Submitted stage-job continuation is allowed only for a current `StageStatus.SUBMITTED` prepared attempt whose durable state matches the registry and backend manifest pointer. Validation must reject missing registry records, stale attempts, mismatched run URI, stage name, attempt, continuation executor, backend, submission ID, manifest path, or submitted metadata before reconstructing user stage code. Accepted submitted stage jobs then transition through the same shared `write_stage_running` and finalization helpers as existing `PENDING -> RUNNING` stage jobs.

## Design Impact

- Maintainability: creates one shared submitted lifecycle and registry instead of letting SLURM phases duplicate queued/submitted semantics in executor code.
- Extensibility: future submitted backends can use the same statuses, registry predicates, and status/cancel discovery without importing SLURM concepts.
- Domain neutrality: public status names describe Loom execution lifecycle; scheduler-specific states stay backend metadata.
- Source-tree boundaries: status/execution/stores own generic contracts, diagnostics/CLI present persisted facts, and `loom.pipeline.executors.slurm` remains backend-only and unused by generic code.

## Future Compatibility

- Phase 2 can attach SLURM live manifest models to `manifest_relative_path` without changing generic registry selection.
- Phase 3 can mark a single-job run `SUBMITTED` and write one registry record through the shared helpers.
- Phase 4 can mark per-stage afterok jobs `SUBMITTED` and rely on the submitted stage-job validation before user code starts.
- Phase 5 can implement `loom status --jobs` by discovering the latest active submission through the same registry instead of path-walking SLURM artifacts.
- Phase 6 can target cancellation through the registry while keeping core status mutation rules separate from scheduler metadata.

## Alternatives Rejected

| Alternative | Reason rejected |
| --- | --- |
| Store submitted state only inside SLURM manifests | General status and cancellation need backend-neutral discovery without importing or path-walking SLURM layouts. |
| Use backend-specific status values such as `PENDING` or `QUEUED` in Loom core status | Scheduler state would leak into generic lifecycle and make future submitted backends inconsistent. |
| Treat submitted stages as `RUNNING` | The stage code has not started yet, and resume/status would misrepresent queued work. |
| Let `stage-job run` accept any `SUBMITTED` stage with matching attempt only | That would allow stale or cross-submission jobs to bypass lifecycle guards before user code. |
| Add scheduler-aware `status --jobs` in Phase 1 | Scheduler queries require backend command runners and live manifest details from later phases. |

## Debt Introduced

| Debt | Reason accepted | Revisit trigger |
| --- | --- | --- |
| `SUBMITTED` is intentionally coarse | Shared lifecycle should stay backend-neutral; scheduler-specific queue/accounting states belong in backend metadata. | A second submitted backend shows the generic state is too ambiguous for status, resume, or cancellation. |
| Generic registry summary counts are small and may duplicate backend manifest facts | They enable backend-neutral active/latest discovery without reading backend details. | Large DAGs, job arrays, or catalogs require indexed sidecars or richer query APIs. |
| Phase 1 validates manifest pointers but not backend manifest internals | Backend live manifest schemas are Phase 2 scope. | Submitted stage-job validation cannot be made safe without parsing backend-owned metadata. |

## Reviewability

- Expected PR size and shape: moderate cross-cutting status/store/execution/diagnostics PR with focused model and helper additions, plus package/unit/contract/integration/e2e tests.
- Files and areas to inspect: `src/loom/pipeline/status.py`, `src/loom/pipeline/execution/lifecycle.py`, `src/loom/pipeline/execution/continuation.py`, `src/loom/pipeline/execution/stage_worker.py` if inference changes, new or updated generic submitted-operation model/store modules, `src/loom/pipeline/stores/run_store.py`, `src/loom/pipeline/stores/local_runs.py`, `src/loom/pipeline/stores/__init__.py`, `src/loom/diagnostics/inspection.py`, `src/loom/cli/status.py`, `src/loom/cli/formatting.py`, and corresponding tests.
- Scope-control checks: no imports from `loom.pipeline.executors.slurm` in generic modules; no scheduler command strings or subprocess calls; no live submission or cancellation; no scheduler snapshots; no public `--jobs` query behavior; no broad runner rewrite; no changes that make `SUBMITTED` terminal or reusable.

## Implementation Steps

1. Add `SUBMITTED` to status enums and lifecycle helpers, then update status parsing, serialization, formatting, and resume interpretation tests.
2. Add generic submitted-operation models, state predicates, validation, and public exports only where needed for store/diagnostics consumers.
3. Add run-store protocol and `LocalRunStore` persistence/discovery helpers for submitted-operation records, including deterministic latest/latest-active ordering and active/terminal predicates.
4. Extend diagnostics and ordinary status CLI output to expose persisted submitted state and registry summaries without scheduler access.
5. Extend stage-job validation for the submitted prepared-attempt path, requiring registry and manifest-pointer identity checks before transitioning `SUBMITTED -> RUNNING`.
6. Add focused package, unit, contract, integration, and e2e coverage, then run targeted suites before PR preparation.

## Test Plan

### Package Suite

- Status: required.
- Expected paths: `tests/package/test_pipeline_execution_api.py`, `tests/package/test_pipeline_store_api.py`, existing package import-boundary tests.
- Required assertions or deferral reason: new status/store/execution exports are explicit and import-safe; `loom.pipeline.stores` does not import CLI or SLURM; generic execution imports do not require scheduler commands or `loom.pipeline.executors.slurm`.

### Unit Suite

- Status: required.
- Expected paths: `tests/unit/loom/pipeline/test_status.py`, `tests/unit/loom/pipeline/planning` resume tests or new focused resume tests, `tests/unit/loom/pipeline/stores/test_local_runs.py`, `tests/unit/loom/pipeline/execution/test_stage_job.py`, `tests/unit/loom/diagnostics/test_diagnostics_inspection.py`, `tests/unit/loom/cli/test_status_logs.py`, and focused new submitted-operation model tests.
- Required assertions or deferral reason: `SUBMITTED` parses and round-trips for runs/stages; lifecycle writers set submitted state without running timestamps; resume treats submitted prior state as non-reusable; registry validation rejects malformed fields and unsafe manifest paths; active/terminal predicates and latest tie-breaks are deterministic; submitted stage-job validation accepts only matching state and rejects stale/mismatched run URI, stage, attempt, backend, submission ID, manifest path, and metadata.

### Contract Suite

- Status: required.
- Expected paths: `tests/contracts/test_store_contract.py`, `tests/contracts/test_stage_worker_contract.py`, and a new or updated submitted-operation contract test.
- Required assertions or deferral reason: `RunStore` and `LocalRunStore` expose backend-neutral submitted-operation read/write/list/discovery behavior; records are schema-versioned plain data; direct stage-worker handoff remains `PENDING` and does not finalize status; `stage-job run` submitted continuation is a separate validated path.

### Integration Suite

- Status: required.
- Expected paths: `tests/integration/pipeline/test_stage_job_continuation.py`, `tests/integration/pipeline/test_local_stores.py`, `tests/integration/diagnostics/test_cli_status_logs.py`, and a new integration test for submitted registry/status.
- Required assertions or deferral reason: ordinary `loom status` displays persisted submitted run/stage state and registry summary from the run store only; submitted stage-job continuation transitions a matching submitted prepared attempt to `RUNNING` and finalizes through existing local behavior; mismatched submitted registry or manifest metadata fails before user stage code and leaves state unchanged.

### E2E Suite

- Status: required for public CLI smoke.
- Expected paths: `tests/e2e/test_cli_core.py` or a focused new e2e status test.
- Required assertions or deferral reason: cluster-free CLI smoke proves persisted `SUBMITTED` run/stage status is visible through `loom status RUN_URI` in JSON and/or text. Live scheduler status, `--jobs`, and cancellation are deferred.

### Opt-In Suites

- Status: deferred.
- Markers affected: none.
- Required assertions or deferral reason: Phase 1 has no real SLURM or scheduler command behavior; opt-in real cluster acceptance begins in the later hardening phase.

## Risks

- Public status compatibility can regress local/subprocess behavior if `SUBMITTED` is treated as terminal or reusable; mitigate with resume and lifecycle regression tests.
- Registry shape can overfit SLURM if generic fields include job IDs or scheduler state; keep backend-specific details behind `manifest_relative_path` and optional safe metadata.
- Submitted stage-job validation can become too permissive and allow stale scheduler jobs to run user code; require identity checks against both current stage status and registry records.
- Diagnostics can imply live scheduler truth from persisted records; text and JSON should distinguish persisted submitted state from scheduler-aware status reserved for later `--jobs`.

## Validation Commands

Targeted development commands:

```sh
UV_CACHE_DIR=/tmp/uv-cache uv run pytest tests/package/test_pipeline_execution_api.py tests/package/test_pipeline_store_api.py
UV_CACHE_DIR=/tmp/uv-cache uv run pytest tests/unit/loom/pipeline/test_status.py tests/unit/loom/pipeline/stores/test_local_runs.py tests/unit/loom/pipeline/execution/test_stage_job.py tests/unit/loom/diagnostics/test_diagnostics_inspection.py tests/unit/loom/cli/test_status_logs.py
UV_CACHE_DIR=/tmp/uv-cache uv run pytest tests/contracts/test_store_contract.py tests/contracts/test_stage_worker_contract.py
UV_CACHE_DIR=/tmp/uv-cache uv run pytest tests/integration/pipeline/test_stage_job_continuation.py tests/integration/pipeline/test_local_stores.py tests/integration/diagnostics/test_cli_status_logs.py
UV_CACHE_DIR=/tmp/uv-cache uv run pytest tests/e2e/test_cli_core.py
```

Final PR-preparation commands:

```sh
make validate-pr
make test-summary
```

## Handoff Notes For `loom_phase_executor`

- Safe implementation slices: statuses/lifecycle first, submitted-operation model and predicates second, run-store persistence/discovery third, diagnostics/status presentation fourth, submitted stage-job validation fifth, targeted tests throughout.
- Tests to run with each slice: run status/resume tests after enum and lifecycle changes; run store unit/contract tests after registry helpers; run diagnostics/CLI tests after status presentation; run stage-job unit/integration tests after submitted continuation validation; run package/import-boundary tests before handoff.
- Decisions the executor must not revisit: `SUBMITTED` is shared, non-terminal, and not reusable; registry records are backend-neutral and do not contain scheduler job details; latest ordering is `created_at` then `submission_id`; active predicate is shared; ordinary status is persisted-state-only; no SLURM imports or scheduler commands; no cancellation or live submission.
- Conditions that require stopping for the manager: safe submitted stage-job validation cannot be implemented without parsing future SLURM live manifest fields; registry active/latest semantics conflict with the v7 implementation plan; public status schema would need a breaking version bump; implementation would require generic code to import SLURM modules or call scheduler commands.
- Expanded-path refinement notes: complete. The refined plan narrows the public registry contract, clarifies `PREPARED`/`SUBMITTING` predicate behavior, pins submitted stage-job identity checks before user code, and keeps scheduler-aware behavior out of Phase 1.

## Refinement And Review Budget Status

- Phase implementation refinement: unused.
- PR review: unused.
- Blocker resolution: 0/3 used.

## Completion Notes

- Draft plan: complete in this artifact.
- Final phase execution plan: complete in this artifact after source/test inspection.
- Implementation summary: pending implementation.
- Implementation validation: pending implementation.
- Refinement summary: expanded-path planning refinement complete; implementation refinement not consumed.
- Blocker-resolution summary: none used.
- PR preparation: pending later workflow stage.
- Stack maintenance: none required for this root phase.
- Remaining blockers: none known.
