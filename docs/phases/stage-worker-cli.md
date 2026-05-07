# Phase 2 Execution Plan: Worker Execution And Direct CLI

## Metadata

- Status: in_progress
- Feature focus: Stage Worker
- PR title: `Stage Worker - Phase 2: Worker Execution and Direct CLI`
- Branch: `codex/stage-worker-cli`
- Worktree: `/home/samcantrill/work/loom-worktrees/stage-worker-cli`
- Phase execution plan path: `docs/phases/stage-worker-cli.md`
- Full plan: `docs/implementation-plans/implementation-plan-v5.md`
- Source phase: Phase 2 - Worker Execution And Direct CLI
- Stack predecessor: none
- Base branch: `develop`
- Target branch: `develop`
- Merge eligibility: root phase PR, merge-eligible when automated review, validation, CI, and scope gates pass
- Workflow path: expanded path, because this phase introduces a public worker CLI and execution-owned worker API that future subprocess, scheduler, and container executors invoke
- Successor dependency notes: Phase 3 must launch the same `loom stage run` worker contract and consume the worker result handoff instead of embedding stage execution logic in the subprocess executor.
- Plan quality gate: passed on 2026-05-07 after initial review, one refinement pass, and confirmation review
- Plan quality gate loop budget: consumed as recorded in `docs/implementation-plans/implementation-plan-v5.md`
- Draft pass: completed by manager on 2026-05-07
- Refine pass: completed by manager on 2026-05-07 for expanded path
- Setup limitations: none; Phase 1 is merged on `develop`, and this worktree was created from `develop`.
- Blockers: none known

## Objective

Implement the execution-owned one-stage worker API and direct `loom stage run --run-uri RUN_URI --stage STAGE` command for a prepared stage attempt, using only durable Loom run records and writing only the structured worker result handoff.

## Full-Plan Context

V5 creates a stable worker contract before production subprocess orchestration. Phase 1 defined prepared attempt request/result models, request/result persistence, and `prepare_stage_attempt`. Phase 2 consumes that contract to prove a stage worker can reconstruct and run one prepared attempt from durable state. Phase 3 will add serial subprocess parent orchestration; Phase 4 will add subprocess preflight and diagnostics; Phase 5 will harden examples and docs. This phase must not implement whole-run subprocess execution or parent-side finalization.

## Stack Context

- Root or stacked phase: root phase
- Current predecessor branch or PR: none; Phase 1 PR #77 is merged
- Why this base branch is correct: all earlier v5 phases are merged into `develop`
- Retarget/rebase plan after predecessor merge: none
- Branch cleanup constraints: branch may be deleted after the Phase 2 PR is merged if no successor branch depends on it

## Source Phase Summary

- Goal: implement direct worker execution for exactly one prepared stage attempt.
- Required scope: execution-owned worker orchestration APIs, durable reconstruction from Phase 1 request/state, public `loom stage run`, exact-attempt support, attempt inference, local stage execution machinery, structured result handoff, documented worker exit codes, and fake/injectable execution seams for tests.
- Required checkpoints: worker does not plan whole pipelines, does not mutate unrelated stages, does not accept raw config paths or parent-process payloads, writes worker result records by attempt, and returns clear missing/ambiguous state errors.
- Acceptance criteria: direct worker command runs one prepared attempt, reconstructs from durable records and prior artifacts, consumes request runtime handoff metadata, writes only its result handoff, and exits with the documented code.

## Current Source And Harness Findings

- Existing files or modules that constrain this phase: `src/loom/pipeline/execution/stage_attempts.py` writes prepared request records and PENDING status metadata; `models.py` defines `StageWorkerRequest` and `StageWorkerResult`; `runner.py` currently contains local stage construction/context/finalization logic; `executors/local.py` already executes one `StageExecutionRequest`; `stores/local_runs.py` persists `worker_request.json` and `worker_result.json` with latest-stage-compatible attempt identity; `cli/main.py` registers flat top-level commands and needs a nested `stage run` group.
- Durable reconstruction can use the persisted execution plan for the `StagePlan` and the prepared request fingerprint payload for stage factory target, factory init, stage config, declared inputs, declared outputs, and fingerprint fields. If a resolved config snapshot exists, worker context can load it; otherwise the worker should use a minimal durable config context derived from the fingerprint payload rather than adding `--config`.
- Existing tests cover Phase 1 models/store/prepare behavior, CLI parser dispatch, local runner integration, local execution support stages, package import boundaries, and store protocols.
- Import-boundary or dependency constraints: `loom.pipeline.execution` must remain CLI-free and should not import `subprocess`; CLI may import execution lazily; no heavyweight runtime dependency is needed.

## In-Scope Work

- Add an execution-owned worker module with a public request/result API for running one prepared stage attempt from durable state.
- Implement exact attempt selection and inference from prepared/running persisted stage status only when one unambiguous prepared request exists.
- Reconstruct `StageExecutionRequest` from `StageWorkerRequest`, persisted `ExecutionPlan`, fingerprint payload, local artifact/run-store paths, prior input artifacts, resolved runtime metadata, and optional resolved config snapshot.
- Execute through the local stage execution machinery, with an injectable executor and artifact-store factory for deterministic component tests.
- Convert local execution results into `StageWorkerResult` records and persist them with `RunStore.write_stage_worker_result`.
- Keep worker ownership limited to the structured handoff; do not write final stage outputs, final stage status, provenance, artifact index entries, or run status in this phase.
- Add the nested `loom stage run --run-uri RUN_URI --stage STAGE [--attempt N]` CLI with text and JSON output.
- Implement worker CLI exit-code behavior: `0` for successful handoff, `1` for stage-result failure handoff, `2` for usage errors, `3` for missing/invalid/ambiguous prepared state, and `130` for interruption.
- Add focused source-doc updates only where Phase 2 behavior is now implemented.

## Out-of-Scope Work

- Production subprocess parent orchestration or `SubprocessExecutor`.
- `loom run --executor subprocess` behavior or selected-executor preflight compatibility.
- Worker command/Python executable preflight checks and diagnostics UX.
- Parent-side final output validation, provenance writes, final stage/run status, result conflict policy, subprocess process metadata, signal mapping, or missing-result handling for parent orchestration.
- Parallel scheduling, worker pools, retries, leases, timeout enforcement, attempt archive directories, SLURM/container behavior, plugin discovery, remote stores, or cleanup policy.
- A normal worker `--config` input or worker-side planning from raw config files.

## Assumptions

- The Phase 1 latest-stage-compatible layout still permits at most one prepared request per stage in v5, so attempt inference is based on current stage status and request identity rather than scanning archive directories.
- The prepared request fingerprint payload is the durable stage-spec source for direct worker reconstruction. This avoids adding raw config paths to the worker CLI and avoids requiring a new persisted full-pipeline config snapshot in this phase.
- The worker may use an empty or minimal resolved config mapping when no resolved config snapshot exists. Stages that need exact full resolved config should rely on future parent orchestration or a later explicit durable snapshot requirement.
- Direct worker CLI is primarily a stable executor entry point and local debugging surface; parent-owned final commit semantics are intentionally deferred to Phase 3.

## Scope Contract

The public worker contract is one prepared attempt addressed by `(run_uri, stage_name, attempt)`, where `attempt` may be inferred only from a prepared/running current status and matching worker request. The worker must read the prepared request through store APIs, validate identity, reconstruct a single `StageExecutionRequest` from durable records, execute that stage through the local executor path, write a schema-versioned `StageWorkerResult`, and stop. It must not write stage outputs, failure records, provenance, artifact index entries, final stage status, or run status. CLI behavior is a thin adapter over this API and must not mutate state independently.

## Design Impact

- Maintainability: worker reconstruction and handoff conversion live in execution, keeping CLI and future executors from duplicating runner internals.
- Extensibility: future subprocess, SLURM, and container backends can invoke the same worker command and inspect the same result contract.
- Domain neutrality: the worker reconstructs Loom runtime/spec/artifact facts only; it does not introduce domain-specific payloads.
- Source-tree boundaries: `loom.pipeline.execution` owns worker APIs, `loom.pipeline.executors.local` still owns in-process stage execution, `loom.pipeline.stores` owns persistence, and `loom.cli` only adapts command-line input/output.

## Future Compatibility

- Exact `--attempt` support gives future parent/scheduler/container launches stable identity even while v5 keeps latest-stage-compatible files.
- The worker API accepts injectable execution dependencies for tests and later subprocess orchestration without exposing CLI internals.
- Reconstruction from fingerprint payload avoids a `--config` dependency while leaving room to add an explicit durable full-config snapshot later if stages need it.
- Result handoff identity validation prepares Phase 3's missing, invalid, stale, and mismatched result handling.

## Alternatives Rejected

| Alternative | Reason rejected |
| --- | --- |
| `loom stage run --config CONFIG` | Reintroduces raw config reconstruction and duplicates config/profile merge logic. |
| Worker-side planning | Violates the prepared-attempt contract and risks mutating unrelated stages. |
| Worker-owned finalization | Conflicts with parent-owned commit semantics and Phase 3 subprocess responsibilities. |
| Direct local runner reuse for the whole run | Would make Phase 2 a second pipeline runner rather than a one-stage worker. |
| Adding attempt archive scanning now | Latest-stage-compatible files remain the v5 layout until retry/reliability work needs history. |

## Debt Introduced

| Debt | Reason accepted | Revisit trigger |
| --- | --- | --- |
| Direct worker resolves stage specs from fingerprint payload | Avoids raw config input and keeps Phase 2 small. | A stage needs exact full resolved-config context during direct worker execution. |
| Attempt inference cannot scan historical attempts | V5 latest-stage-compatible layout has no attempt archive directories. | Retry/history layout is introduced. |
| Worker result is not parent-finalized by direct CLI | Preserves the parent/worker boundary for Phase 3. | A future direct-debug command needs an explicit opt-in finalization mode. |

## Reviewability

- Expected PR size and shape: medium execution/CLI/test PR with no subprocess process-control code.
- Files and areas to inspect: new worker execution module, execution exports, CLI `stage run` parser/handler, formatting, docs, package/unit/contract/integration tests.
- Scope-control checks: no `subprocess` import in execution, no `loom.cli` import from execution/stores, no `loom run --executor subprocess`, no final stage/run status writes from the worker, no normal worker `--config`.

## Implementation Steps

1. Add worker request/selection/reconstruction helpers and public API in `loom.pipeline.execution`.
2. Implement `StageWorkerResult` handoff writing from local execution results, including failure-result handling.
3. Register `loom stage run` and add text/JSON output plus exit-code mapping.
4. Add package, unit, contract, and integration tests for worker API, CLI parsing/output, state errors, and handoff-only persistence.
5. Update focused docs for the now-implemented direct worker command.

## Test Plan

### Package Suite

- Status: required
- Expected paths: `tests/package/test_pipeline_execution_api.py` and CLI import-boundary coverage as needed.
- Required assertions or deferral reason: worker API is a public execution export; importing `loom.pipeline.execution` still does not import `loom.cli` or `subprocess`.

### Unit Suite

- Status: required
- Expected paths: new `tests/unit/loom/pipeline/execution/test_stage_worker.py`, `tests/unit/loom/cli/test_stage.py`, and `tests/unit/loom/cli/test_main.py`.
- Required assertions or deferral reason: attempt inference, exact attempt validation, missing/ambiguous state errors, plan/request mismatch, reconstructed execution request shape, fake executor handoff writes, CLI parsing, JSON/text output, and exit-code mapping.

### Contract Suite

- Status: required
- Expected paths: new `tests/contracts/test_stage_worker_contract.py` or adjacent execution/store contract coverage.
- Required assertions or deferral reason: worker writes only its `worker_result.json` handoff and does not write final outputs, failure documents, provenance, artifact index, final stage status, or run status.

### Integration Suite

- Status: required
- Expected paths: new `tests/integration/pipeline/test_stage_worker.py` and, if useful, `tests/integration/config/test_cli_run.py` or a new direct-worker CLI integration test.
- Required assertions or deferral reason: real temporary runs are created and prepared through `prepare_stage_attempt`; direct worker success and stage failure write structured result handoffs through store APIs; prior stage artifacts can be consumed through the local artifact store.

### E2E Suite

- Status: optional for this phase
- Expected paths: `tests/e2e/test_cli_core.py` or a new direct-worker smoke if the integration coverage remains too CLI-light.
- Required assertions or deferral reason: full `loom run --executor subprocess` E2E belongs to Phase 3. Direct worker smoke may be added if it stays deterministic and cheap.

### Opt-In Suites

- Status: deferred
- Markers affected: none expected beyond existing optional dependency markers used by config/integration coverage.
- Required assertions or deferral reason: Phase 2 uses local deterministic synthetic tests only and does not require network, real subprocess, SLURM, container, or heavy optional dependency acceptance suites.

## Risks

- Worker reconstruction could accidentally become a second planner or runner. Stop if implementation starts selecting stages, finalizing a run, or mutating stages other than the requested attempt's result handoff.
- The fingerprint payload may not contain every future stage-spec field. Keep reconstruction narrow and document missing exact full-config behavior as debt rather than adding a raw config worker input.
- CLI exit-code mapping differs from the existing `loom run` enum names. Keep the direct worker mapping local to the `stage run` handler.
- Shared runner helpers are private. Prefer small execution-owned worker helpers over a broad runner refactor in this phase.

## Validation Commands

Targeted development commands:

```sh
uv run pytest tests/package/test_pipeline_execution_api.py tests/unit/loom/pipeline/execution/test_stage_worker.py tests/unit/loom/cli/test_stage.py tests/contracts/test_stage_worker_contract.py tests/integration/pipeline/test_stage_worker.py
uv run pyright src/loom/pipeline/execution src/loom/cli tests/unit/loom/pipeline/execution/test_stage_worker.py tests/unit/loom/cli/test_stage.py tests/contracts/test_stage_worker_contract.py tests/integration/pipeline/test_stage_worker.py
```

Final PR-preparation commands:

```sh
make validate-pr
make test-summary
```

## Handoff Notes For `loom_phase_executor`

- Safe implementation slices: worker API/reconstruction first, handoff conversion second, CLI adapter third, tests/docs last or alongside each slice.
- Tests to run with each slice: worker unit tests after reconstruction; contract/integration tests after handoff persistence; CLI unit tests after parser registration.
- Decisions the executor must not revisit: durable-only reconstruction, no normal worker `--config`, parent-owned finalization, no subprocess parent orchestration, latest-stage-compatible layout for v5, and exact worker exit-code mapping for direct CLI.
- Conditions that require stopping for the manager: a need for raw config worker input, whole-run planning, finalization from the worker, attempt archive directories, subprocess launch, or a dependency addition.

## Refinement And Review Budget Status

- Phase implementation refinement: unused
- PR review: unused
- Blocker resolution: 0/3 used

## Completion Notes

- Draft plan: completed by manager on 2026-05-07.
- Final phase execution plan: refined by manager on 2026-05-07 before implementation to clarify fingerprint-payload reconstruction and handoff-only persistence.
- Implementation summary: TBD
- Implementation validation: TBD
- Refinement summary: TBD
- Blocker-resolution summary: none used
- PR preparation: TBD
- Stack maintenance: not needed yet
- Remaining blockers: none known
