# Phase 1 Execution Plan: Contracts And Persistence

## Metadata

- Status: draft phase execution plan
- Feature focus: Stage Worker
- PR title: `Stage Worker - Phase 1: Contracts and Persistence`
- Branch: `codex/stage-worker-contracts`
- Worktree: `/home/samcantrill/work/loom-worktrees/stage-worker-contracts`
- Phase execution plan path: `docs/phases/stage-worker-contracts.md`
- Full plan: `docs/implementation-plans/implementation-plan-v5.md`
- Source phase: Phase 1 - Contracts And Persistence
- Stack predecessor: none
- Base branch: `develop`
- Target branch: `develop`
- Merge eligibility: root phase PR, merge-eligible when automated review, validation, CI, and scope gates pass
- Workflow path: expanded path, because this phase defines public/schema/store persistence contracts across execution and store boundaries
- Successor dependency notes: Phase 2 must consume this phase's prepare-stage-attempt API and persisted request/result contracts instead of hand-crafted worker fixtures.
- Plan quality gate: passed on 2026-05-07 after initial review, one refinement pass, and confirmation review
- Plan quality gate loop budget: consumed as recorded in `docs/implementation-plans/implementation-plan-v5.md`
- Draft pass: completed by `loom_phase_planner`
- Refine pass: pending for expanded path
- Setup limitations: none; GitHub auth was valid outside the sandbox, `origin` was fetched, and the worktree was created from `develop`.
- Blockers: none known

## Objective

Establish the durable stage-worker request, result, failure, preparation, and store persistence contract for exactly one prepared stage attempt, without adding worker CLI behavior or subprocess execution.

## Full-Plan Context

V5 creates process-isolated stage execution after v4's runtime options and safe runtime metadata handoff. Phase 1 is the foundation that later worker and subprocess phases must consume: it defines schema-versioned records, the parent-side preparation boundary, store APIs by run URI/stage/attempt, and redacted executor metadata. Phase 2 adds direct worker execution and `loom stage run`; Phase 3 adds production subprocess orchestration; Phase 4 adds preflight and diagnostics UX; Phase 5 hardens examples and docs. This phase must not implement those future behaviors.

## Stack Context

- Root or stacked phase: root phase
- Current predecessor branch or PR: none
- Why this base branch is correct: all earlier phases are merged and the assignment names `develop` as the stack base
- Retarget/rebase plan after predecessor merge: none
- Branch cleanup constraints: branch may be deleted after the Phase 1 PR is merged if no successor branch depends on it

## Source Phase Summary

- Goal: establish stable request/result/failure contracts and persistence APIs for one prepared stage attempt.
- Required scope: execution-owned request/result/failure records, validation and serialization, parent-side prepare-stage-attempt API, store APIs for prepared requests and result handoffs, latest-stage-compatible layout, redaction helpers, signal fields, and source-doc alignment.
- Required checkpoints: models round-trip and reject invalid data; prepare API writes durable state sufficient for Phase 2; store APIs preserve current diagnostics-compatible layout; docs no longer conflict with `--run-uri`, no normal `--config`, and parent-owned finalization decisions.
- Acceptance criteria: all Phase 1 records include schema version, run URI, stage, attempt, timestamps, runtime/executor/log/failure fields, exit-code and signal fields where applicable; execution code uses store APIs rather than path walking; tests cover package, unit, contract, and integration obligations.

## Current Source And Harness Findings

- Existing files or modules that constrain this phase: `src/loom/pipeline/execution/models.py` already owns `StageExecutionRequest`, `StageExecutionResult`, and `ExecutionFailure`; `runner.py` currently prepares inputs/fingerprints/log paths inline in `_run_stage`; `lifecycle.py` owns stage status transitions; `stores/run_store.py` and `stores/local_runs.py` own stage inputs, outputs, fingerprints, failures, logs, workspace, and local paths; `runtime/metadata.py` provides `ResolvedStageRuntimeOptions.to_safe_metadata()`.
- Existing tests or harness behavior: package import-boundary tests assert execution/store public exports; unit tests cover execution models, local store documents, lifecycle helpers, local executor behavior, and runtime handoff; contract tests cover executor, store, runtime options, and executor capabilities; integration tests exercise local runner persistence through temporary run directories.
- Import-boundary or dependency constraints: execution and stores must stay CLI-free; execution must not import `subprocess` in Phase 1; stores must not know how to execute stages; no heavyweight runtime dependency is needed.

## In-Scope Work

- Define schema-versioned, plain-data serializable records for prepared stage attempt requests, worker results, and worker/process failures or extend existing execution records where that preserves a clear public contract.
- Add validation for required identity fields, status combinations, timestamps, resolved stage runtime handoff metadata, executor metadata, log paths, traceback paths, exit codes, and signal facts.
- Define the execution-owned `prepare_stage_attempt` boundary that binds inputs, builds fingerprint metadata, allocates log/result paths, writes prepared request state, writes latest-compatible inputs/fingerprint records, marks the attempt prepared/running as appropriate for later worker consumption, and returns the attempt identity without invoking stage code.
- Add run-store protocol and local-store APIs for prepared request and worker result handoff records addressed by run URI, stage name, and attempt.
- Preserve existing latest-stage-compatible files under `stages/<stage>/` while recording explicit attempt identity in new or updated records.
- Add redaction helpers for persisted executor command/process metadata so full environment values and secret-like command metadata are not persisted.
- Add the signal field to failure/process-result contracts separately from exit code.
- Align `docs/features/execution.md`, `docs/features/cli.md`, `docs/features/run-store.md`, and related source docs where they conflict with the v5 contract.

## Out-of-Scope Work

- Worker CLI behavior, `loom stage run` parsing, exit-code mapping, and direct worker execution.
- Real subprocess process launch, process preflight, Python executable checks, stdout/stderr capture from child processes, or subprocess executor registration.
- Automatic retries, retry history, leases, heavyweight locking, timeout enforcement, and cleanup policy.
- Full `stages/<stage>/attempts/<n>/...` archive layout.
- Any worker-side reconstruction from raw config paths, pickled objects, or parent-process memory.
- Whole-run subprocess execution, E2E subprocess workflows, SLURM/container behavior, plugin-discovered executors, and remote stores.

## Assumptions

- The Phase 1 prepare API may be introduced as a public execution API, but it must remain backend-neutral and reusable by Phase 2 and Phase 3.
- Prepared request/result files can live in the latest-stage-compatible stage directory for v5, provided every record carries attempt identity and store APIs abstract the path.
- Existing local runner behavior should remain compatible; Phase 1 may share preparation helpers with `_run_stage`, but it should not change local execution semantics beyond the new durable metadata.
- `ResolvedStageRuntimeOptions.to_safe_metadata()` is the safe request handoff source unless implementation finds a missing field that requires a small explicit model extension.

## Scope Contract

The public contract is one prepared attempt identified by `(run_uri, stage_name, attempt)`. Records must be versioned and validated through execution-owned models, serialized as plain data, and persisted only through store APIs. Request records must include or safely reference bound inputs, fingerprint metadata, log paths, result handoff path, executor name/metadata, and resolved per-stage runtime handoff metadata. Result records must represent either success or failure for the same identity and must reject conflicting status/output/failure combinations. Failure records must retain existing local failure fields and add signal support separate from exit code. The prepare API must not construct or run stage objects and must not finalize stage or run status after worker execution; final commit semantics stay parent-owned in later phases.

## Design Impact

- Maintainability: centralizes worker contract models in execution and persistence operations in stores, avoiding ad hoc JSON/path logic in future worker and subprocess code.
- Extensibility: gives SLURM, container, and later remote executors a stable durable attempt contract without inheriting local runner internals.
- Domain neutrality: records contain runtime, artifact, store, and executor facts only; no domain-specific stage payloads or downstream package assumptions.
- Source-tree boundaries: `loom.pipeline.execution` owns lifecycle/preparation contracts, `loom.pipeline.stores` owns persistence/layout, `loom.pipeline.runtime` remains the source of safe runtime handoff metadata, and `loom.cli` is only updated in docs.

## Future Compatibility

- Attempt identity is explicit now, while full attempt archives remain deferred until retry/reliability phases need real multi-attempt history.
- Store APIs should hide the current latest-stage-compatible layout so a later archive layout can be added with minimal execution changes.
- Result/failure models should support later subprocess, scheduler, and container process metadata without making Phase 1 responsible for launching those backends.
- Redaction policy should be reusable by Phase 3 subprocess metadata and later executor adapters.

## Alternatives Rejected

| Alternative | Reason rejected |
| --- | --- |
| Unversioned ad hoc JSON result files | Would make worker/subprocess/SLURM compatibility brittle and hard to validate. |
| Pickled parent payloads or raw stage objects | Violates durable-only reconstruction and couples workers to parent memory. |
| CLI-owned state mutation | Breaks the CLI boundary; execution and stores must own lifecycle and persistence. |
| Full attempt archive directories in Phase 1 | Adds layout churn before retries or attempt history exist. |
| Worker reconstruction from `--config` as normal input | Conflicts with v5 durable run-state contract and would duplicate config/profile merge logic. |

## Debt Introduced

| Debt | Reason accepted | Revisit trigger |
| --- | --- | --- |
| Latest-compatible stage files remain the primary layout | Preserves v3 diagnostics compatibility and keeps Phase 1 reviewable. | Retries, cleanup/retention, or reliability policies require real attempt history. |
| Prepare API shape may need narrow adjustment during Phase 2/3 integration | Phase 1 defines the durable boundary before worker/subprocess consumers exist. | Phase 2 or Phase 3 finds a missing field needed for durable reconstruction or parent finalization. |
| No heavyweight lock/lease semantics for prepared requests | V5 serial subprocess execution has one parent coordinator. | Parallel scheduling, duplicate workers, remote stores, or retry coordination are introduced. |

## Reviewability

- Expected PR size and shape: medium documentation/model/store/test PR with no worker CLI or subprocess behavior.
- Files and areas to inspect: execution models and exports, lifecycle/runner preparation boundary, store protocols/local store implementation, redaction helpers, source docs, package/unit/contract/integration tests.
- Scope-control checks: no `subprocess` import in execution, no `loom.cli` import from execution/stores, no new attempt archive directory requirement, no `loom stage run` implementation, no preflight behavior.

## Implementation Steps

1. Add or revise execution-owned record models for prepared requests, worker results, and failures, including schema validation, serialization, signal support, runtime handoff metadata, and redacted executor metadata.
2. Add store protocol/local-store APIs for prepared request and result handoff read/write by run URI/stage/attempt while preserving latest-stage-compatible paths.
3. Extract a parent-side prepare-stage-attempt API from the existing runner preparation flow, keeping stage construction/execution/finalization out of scope.
4. Wire local runner internals only as needed to keep existing behavior passing and to make the prepare API produce real durable state for later phases.
5. Align source docs with v5 command/finalization/layout decisions and add focused tests across package, unit, contract, and integration suites.

## Test Plan

### Package Suite

- Status: required
- Expected paths: `tests/package/test_pipeline_execution_api.py`, `tests/package/test_pipeline_store_api.py`, and import-boundary tests as needed.
- Required assertions or deferral reason: new public execution/store exports are explicit, cheap to import, typed package boundaries remain stable, and `loom.pipeline.execution` still does not import `loom.cli` or `subprocess`.

### Unit Suite

- Status: required
- Expected paths: `tests/unit/loom/pipeline/execution/test_execution_models.py`, `tests/unit/loom/pipeline/execution/test_runner.py` or a new prepare-focused test module, `tests/unit/loom/pipeline/stores/test_local_runs.py`, and redaction tests near the owning helper.
- Required assertions or deferral reason: request/result/failure round trips, unsupported schema versions, unknown/missing fields, invalid status/output/failure combinations, invalid attempts, exit-code/signal separation, resolved runtime handoff validation, redaction of secret-like metadata, and local-store corrupt/mismatched identity handling.

### Contract Suite

- Status: required
- Expected paths: `tests/contracts/test_store_contract.py`, `tests/contracts/test_executor_contract.py`, `tests/contracts/test_runtime_options_contract.py`, `tests/contracts/test_executor_capabilities_contract.py`, and a new or existing execution contract test for `prepare_stage_attempt`.
- Required assertions or deferral reason: store protocols expose prepared request/result methods, dummy stores satisfy the protocol, prepare API writes the documented durable state without executing stage code, executor contract remains `StageExecutionRequest -> StageExecutionResult`, and runtime handoff remains resolved/safe rather than raw config/profile input.

### Integration Suite

- Status: required
- Expected paths: `tests/integration/pipeline/test_local_execution.py`, `tests/integration/pipeline/test_local_stores.py`, or a new `test_stage_worker_contracts.py`.
- Required assertions or deferral reason: temporary local run directories can persist and read back prepared requests/results through store APIs; prepare-stage-attempt uses real planning/binding/fingerprint/log allocation state; current local execution still writes diagnostics-compatible stage files.

### E2E Suite

- Status: deferred
- Expected paths: none in Phase 1.
- Required assertions or deferral reason: no user-visible worker CLI or subprocess workflow exists yet; Phase 2/3 own direct worker and subprocess E2E smoke coverage.

### Opt-In Suites

- Status: deferred
- Markers affected: none expected beyond existing optional dependency markers used by current integration coverage.
- Required assertions or deferral reason: Phase 1 uses local deterministic synthetic tests only and does not require network, real subprocess, SLURM, container, or heavy optional dependency acceptance suites.

## Risks

- The prepare API could accidentally become a second runner. Stop if implementation starts constructing/running stages or finalizing post-worker state inside prepare.
- Store APIs could leak local path layout into execution. Prefer store-owned read/write/path helpers and keep execution from constructing request/result JSON paths manually.
- Docs already contain older `--run-dir` and optional `--config` worker text. Phase 1 must align source docs without implementing the CLI behavior.
- Failure/result records may grow too broad. Keep Phase 1 to fields needed by v5 subprocess handoff and later executor compatibility.

## Validation Commands

Targeted development commands:

```sh
uv run pytest tests/package/test_pipeline_execution_api.py tests/package/test_pipeline_store_api.py
uv run pytest tests/unit/loom/pipeline/execution/test_execution_models.py tests/unit/loom/pipeline/stores/test_local_runs.py
uv run pytest tests/contracts/test_store_contract.py tests/contracts/test_executor_contract.py tests/contracts/test_runtime_options_contract.py tests/contracts/test_executor_capabilities_contract.py
uv run pytest tests/integration/pipeline/test_local_execution.py tests/integration/pipeline/test_local_stores.py
```

Final PR-preparation commands:

```sh
make validate-pr
make test-summary
```

## Handoff Notes For `loom_phase_executor`

- Safe implementation slices: records/validation first, store APIs second, prepare API third, docs/tests last or alongside each slice.
- Tests to run with each slice: model and redaction unit tests after record work; store unit/contract tests after protocol/local-store work; prepare API contract/integration tests after execution boundary work.
- Decisions the executor must not revisit: durable-only reconstruction, `--run-uri` over `--run-dir`, no normal worker `--config`, parent-owned finalization, latest-stage-compatible layout for v5, signal separate from exit code, and no worker CLI/subprocess behavior in Phase 1.
- Conditions that require stopping for the manager: a need for full attempt archive directories, heavy locking/leases, public CLI behavior, subprocess launch, raw config worker inputs, or a dependency addition.

## Refinement And Review Budget Status

- Phase implementation refinement: unused
- PR review: unused
- Blocker resolution: 0/3 used

## Completion Notes

- Draft plan: completed by `loom_phase_planner` on 2026-05-07.
- Final phase execution plan: pending expanded-path refine pass.
- Implementation summary: pending.
- Implementation validation: pending.
- Refinement summary: pending.
- Blocker-resolution summary: none used.
- PR preparation: pending.
- Stack maintenance: not needed yet.
- Remaining blockers: none known.
