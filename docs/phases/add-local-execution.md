# Phase 9 Execution Plan: Local Execution

## Metadata

- Status: draft phase execution plan
- Branch: `codex/add-local-execution`
- Worktree: `/home/samcantrill/work/loom-worktrees/add-local-execution`
- Phase execution plan path: `docs/phases/add-local-execution.md`
- Full plan: `docs/implementation-plans/implementation-plan-v0.md`
- Source phase: `Phase 9 - Local Execution`
- Stack predecessor: `codex/add-planning-resume-selectors`
- Base branch: `codex/add-planning-resume-selectors` at `98a5fd6725c979cd93f913efc0d2f2e2fc67b6d4`
- Target branch: `codex/add-planning-resume-selectors`
- Merge eligibility: stacked PR; reviewable against `codex/add-planning-resume-selectors`; not merge-eligible until Phase 7 and Phase 8 have landed or this branch has been rebased/replayed and retargeted to `develop`.
- Successor dependency notes: no successor phase branch is recorded yet. Keep this branch until any later successor has been retargeted or rebased away from it.
- Plan quality gate: passed on 2026-05-03 by `loom_plan_reviewer` confirmation review; no blocking findings remain in the canonical v0 implementation plan.
- Plan quality gate loop budget: initial review used, automated plan refinement pass used, confirmation review used. Do not rerun or consume the plan-quality gate for this phase.
- Draft pass: completed by `loom_phase_planner` on 2026-05-04 local time.
- Refine pass: not started; required before implementation begins.
- PR body draft pass: unused.
- PR body refine/open pass: unused.
- Phase implementation refinement budget: unused.
- PR review budget: unused.
- Setup limitations: the first sandboxed `git worktree add` could not create the branch ref under the control checkout `.git` directory and was rerun with approved filesystem access. No remote synchronization, broad checks, or validation commands were run during this draft-only planning pass.
- Blockers: none.

## Objective

Implement the first end-to-end local runtime path for v0. Phase 9 should turn the static config, pipeline spec, graph, store, and planning layers into a serial in-process runner that creates or opens local run directories, plans work, executes runnable stages, validates returned artifact refs, persists lifecycle state, updates artifact indexes, records provenance and failure state, and supports conservative same-run-directory resume.

The runner must stay domain-neutral. Stages remain black boxes that satisfy the structural `Stage.run(context, inputs)` protocol and return `Mapping[str, ArtifactRef]`. The runner owns lifecycle, output validation, status writes, fingerprints, and resume behavior.

## Full-Plan Context

Phases 1 through 6 are merged and provide the package skeleton, primitives, serialization, I/O/codecs, trusted config composition, recipe expansion, target import/instantiation helpers, static pipeline specs, graph validation, strict `stage.output` bindings, status records, and the minimal `StageContext`.

Phase 7 PR #11 remains open against `develop` and provides the local run/artifact stores and inspectable file layout. Phase 8 PR #12 remains open against Phase 7 and provides deterministic planning, selectors, stage fingerprints, conservative resume checks, downstream invalidation, and `RunStore.write_plan()` persistence. Phase 9 must build on Phase 8, not `develop`, so it can consume the real `RunStore`, `ArtifactStore`, `ExecutionPlan`, `StagePlan`, `PlanAction`, `PlanSelectors`, `ResumeOptions`, `FingerprintContext`, and `build_stage_fingerprint()` APIs.

Phase 10 remains out of scope. It will harden errors, interrupted-run edge cases, docs, and extension contracts after the local runner exists. Phase 9 should not absorb Phase 10 cleanup or documentation expansion unless directly required to make the local execution API testable.

## Stack Context

- Root or stacked phase: stacked phase.
- Current predecessor branch or PR: `codex/add-planning-resume-selectors`, GitHub PR #12, recorded in the predecessor phase artifact as open against `codex/add-local-stores-run-layout`.
- Why this base branch is correct: Phase 7 PR #11 is still open against `develop`, Phase 8 PR #12 is still open against Phase 7, and Phase 9 depends on Phase 8 planner/resume/selectors. The manager assignment explicitly requires branching from `codex/add-planning-resume-selectors` at `98a5fd6725c979cd93f913efc0d2f2e2fc67b6d4`.
- Retarget/rebase plan after predecessor merge: after Phase 7 lands, Phase 8 must be replayed or rebased onto updated `develop` and retargeted. After Phase 8 lands, replay or rebase this Phase 9 branch onto updated `develop`, retarget its PR to `develop`, rerun validation, and record stack maintenance in this artifact and the PR body.
- Branch cleanup constraints: do not delete the Phase 8 predecessor branch while this branch depends on it. Do not delete this Phase 9 branch until every successor branch has been retargeted or rebased away from it.

## Source Phase Summary

- Goal: implement the end-to-end local runner using the already-tested config, graph, store, and planning layers.
- Required scope:
  - Add an executor protocol and in-process `LocalExecutor`.
  - Add execution request/result types, run result types, lifecycle helpers, log/failure helpers, output validation, and `PipelineRunner`.
  - Create or reuse local run directories.
  - Persist config snapshots, recipe manifests, provenance documents, run metadata, run status, plans, stage inputs, stage fingerprints, outputs, failures, stage provenance, logs, and artifact indexes through the Phase 7 stores.
  - Parse and validate pipeline specs from resolved config when a `PipelineSpec` is not supplied.
  - Instantiate stage targets from `StageSpec.target_path` without constructor kwargs in v0.
  - Build runtime `StageContext` values with store-backed output path, save, and register helpers while still requiring stages to return their output mapping directly.
  - Call the Phase 8 planner for selectors, resume, fingerprints, and plan persistence.
  - Execute only runnable stages and support same-run-directory resume.
- Required checkpoints:
  - `LocalExecutor` calls `stage.run(context, inputs)` in the current Python process and returns a structured result.
  - Lifecycle helpers mark stages running, succeeded, failed, selector-skipped, and finalized through the run store.
  - `PipelineRunner` writes config/provenance, parses specs, instantiates targets, builds contexts, plans work, binds inputs, invokes the executor, validates returned outputs, writes state, updates indexes, and finalizes `run.json` and `status.json`.
  - Output validation checks exact returned keys, `ArtifactRef` values, artifact types, declared codec keys, existing artifact files, and checksums when present.
  - Failure behavior writes `failure.json` before `FAILED` status, avoids downstream execution in the same run, marks the run failed, and leaves state inspectable.
  - Resume is same-run-directory only. `REUSE` planner decisions retain prior `SUCCEEDED` state and must not be persisted as `SKIPPED`.
- Acceptance criteria:
  - A synthetic local pipeline can run end to end from YAML through public Python APIs.
  - Run directories contain expected config, provenance, status, fingerprint, input, output, artifact, plan, and index files.
  - Same-run-directory reruns produce `REUSE` planner decisions for valid unchanged stages without persisting `SKIPPED` status for reused stages.
  - Changed stage config or upstream artifacts rerun the changed stage and downstream dependents.
  - Invalid stage outputs fail with path-aware errors.
  - Stage exceptions persist failure state before failed status and leave inspectable run state.
- Source references: `docs/implementation-plans/implementation-plan-v0.md` Phase 9; `docs/structure.md` sections "Execution and Executors", "Pipeline Model and Planning", "Stores and State", "Runtime Dependency Policy", "Test Layout", and "Review Checklist"; `docs/loom.md` sections 8 through 12; `docs/features/pipeline.md`, `docs/features/execution.md`, `docs/features/run-store.md`, `docs/features/artifacts.md`, `docs/features/provenance.md`, `docs/features/resume.md`, `docs/features/state.md`, `docs/features/runtime-resources.md`, and `docs/features/testing.md`.

## Current Source And Harness Findings

- `src/loom/pipeline/execution/__init__.py` and `src/loom/pipeline/executors/__init__.py` are still import-safe skeletons with empty public surfaces.
- `loom.pipeline.context.StageContext` currently stores `run_id`, `stage_name`, `run_dir`, `stage_dir`, `resolved_config`, `stage_config`, `provenance`, and `metadata`. Phase 9 should extend this context or add tightly scoped runtime helpers without breaking existing Phase 6 construction/tests.
- `loom.pipeline.stage.Stage` is the structural protocol for `run(context, inputs) -> Mapping[str, ArtifactRef]`; Phase 9 must keep inheritance optional.
- `loom.pipeline.specs.PipelineSpec.from_config()` parses strict v0 stage configs and rejects deferred fields such as `runtime`, `retry`, `when`, stage metadata, and output `path`.
- `loom.pipeline.status` has `RunStatus` and `StageStatus` records. It does not have persisted `REUSE` or `BLOCKED` statuses, so execution must treat those as plan/result concepts and be explicit about what, if anything, is written for non-run actions.
- `loom.pipeline.stores` exposes `RunStore`, `ArtifactStore`, `LocalRunStore`, `LocalArtifactStore`, atomic helpers, artifact index helpers, config snapshot writers, provenance writers, stage input/output/fingerprint/failure/provenance writers, and stdout/stderr log helpers.
- `LocalArtifactStore` expects its root to be the run artifact root and allocates managed files under `<artifact_root>/<stage>/<output>.<suffix>`.
- `RunStore` supports config snapshot names `raw`, `overlays`, `cli_overrides`, `resolved`, and `resolved_redacted`, plus recipe manifest and provenance documents `environment`, `git`, `command`, and `dependencies`.
- `loom.pipeline.planning` exports the Phase 8 planner models, selectors, resume options, `plan_pipeline()`, and `build_stage_fingerprint()`. Planning may leave downstream stages with `FingerprintStatus.PENDING_INPUTS` until Phase 9 binds produced upstream artifacts.
- `loom.config.api` exposes `ComposedConfig`, `compose_config()`, and `instantiate()`. Stage target construction should use the target import/instantiation boundary narrowly and must not introduce constructor kwargs.
- Provenance helpers can capture command, git, environment, dependencies, run provenance, and artifact lineage while degrading when optional facts are unavailable.
- Current test suites include package, unit, contract, and integration coverage. There is no `tests/e2e` directory yet; Phase 9 should add the first e2e suite for local Python API execution.

## In-Scope Work

- Add execution-specific errors, typed request/result models, failure metadata, lifecycle helpers, output validation, and runner orchestration under `src/loom/pipeline/execution/`.
- Add an `Executor` structural protocol and `LocalExecutor` under `src/loom/pipeline/executors/`.
- Export `PipelineRunner` and stable execution types from `loom.pipeline.execution`; export executor types from `loom.pipeline.executors`; add `PipelineRunner` to `loom.pipeline` only if the refine pass confirms that is the intended v0 public pipeline API.
- Extend `StageContext` with generic runtime helpers for output path allocation, managed artifact save, and manual artifact registration, backed by `ArtifactStore` and `RunStore` where available.
- Add a `PipelineRunner` path that accepts a `ComposedConfig` or resolved plain mapping plus run options, parses `pipeline`, creates or opens the run, writes snapshots/provenance, computes and persists a plan, and executes the plan serially.
- Rebind inputs for stages whose initial plan had pending upstream outputs after upstream `RUN` stages commit outputs, then compute and persist their final stage fingerprint before invocation.
- Instantiate stage targets from `StageSpec.target_path` with no constructor kwargs and verify that the object satisfies the `Stage` protocol before execution.
- Validate every returned output before writing `outputs.json`, updating `artifacts.json`, writing stage provenance, or marking a stage `SUCCEEDED`.
- Preserve `REUSE` behavior by not invoking executors and by keeping prior successful stage state visible; update or preserve artifact index entries only from validated reusable outputs.
- Persist selector-skipped stages as `StageStatus.SKIPPED` when appropriate, while keeping `REUSE` distinct from skipped state.
- Fail clearly on non-executable `BLOCKED` plan results, stage construction failures, executor failures, output validation failures, and store commit failures.
- Add focused package, unit, contract, integration, and e2e tests for the local execution path.

## Out-of-Scope Work

- No functional CLI commands or CLI selector aliases.
- No subprocess, SLURM, distributed, container, or remote execution backend.
- No parallel local scheduling, retries, timeout enforcement, cancellation protocol, distributed locks, or continue-on-failure policy.
- No remote stores, run catalogs, global cache indexes, cross-run cache reuse, or content-addressed cache.
- No stage-target constructor kwargs, dynamic DAG mutation, conditional execution, runtime profile interpretation, scheduler-specific resources, or executor registry.
- No context-collected outputs in v0; stages must return the direct output mapping even when they use context helpers to save or register artifacts.
- No domain-specific stages, codecs, resources, metrics, datasets, models, reports, or checkpoint semantics.
- No broad refactors of Phase 7 stores or Phase 8 planner APIs unless implementation proves an acceptance criterion is impossible without a predecessor contract change.

## Assumptions

- The Phase 8 branch remains the correct stack base until the managing agent records that Phase 8 has landed on `develop`.
- Same-run-directory resume is the only v0 reuse mode.
- A fresh run creates a new `run_id` directory through `RunStore.create_run()`; a resume rerun opens the same run through `RunStore.open_run()`.
- The runner can render or persist resolved/redacted config snapshots from supplied plain data. Raw config, overlay, and CLI override snapshots require caller-supplied text or provenance-derived content; refine must lock the exact snapshot input contract.
- Stage targets are trusted project code. Import sandboxing and allow lists remain deferred.
- `StageContext` helper methods return `ArtifactRef`s that the stage includes in its returned mapping; context-owned output collection remains deferred.
- Store writes are atomic at the file level through Phase 7 helpers, but no run-level lock manager exists in v0.
- Local execution is serial and stop-on-first-failure.
- If a plan contains `BLOCKED` actions before execution, the runner should not invoke downstream stages and should return or persist a failed run result with structured reasons.

## Draft Contract To Refine

The refine pass must make the API names and dataclass fields exact before implementation. The draft-level contract is:

- `loom.pipeline.executors` owns backend invocation:
  - an `Executor` runtime-checkable protocol with stable `name` and synchronous `execute(request)` behavior;
  - a `LocalExecutor` named `local` that invokes a constructed stage object in-process;
  - executor-specific errors that subclass the package execution/pipeline error hierarchy.
- `loom.pipeline.execution` owns runner lifecycle:
  - request/result models for a run, stage execution request/result, failure policy, failure metadata, and stage/run summaries;
  - lifecycle helpers that build `RunStatusRecord` and `StageStatusRecord` values with correct ordering;
  - output validation helpers that raise stage-aware/path-aware errors;
  - `PipelineRunner` as the high-level Python API for local execution.
- `StageContext` should remain the stage-facing context type. Runtime helper additions must be generic and optional so earlier tests and downstream minimal contexts still construct:
  - `output_path(name, suffix=...)`;
  - `save_artifact(name, obj, artifact_type=..., codec_key=..., ...)`;
  - `register_artifact(name, path, artifact_type=..., codec_key=None, ...)`.
- `PipelineRunner` should:
  - accept a `PipelineSpec`, a `ComposedConfig`, or a resolved mapping that contains `pipeline`;
  - use `parse_pipeline_config()` for mappings rather than duplicating spec parsing;
  - call `plan_pipeline(..., persist=True)` for the initial plan;
  - execute stages in `ExecutionPlan.stage_order`;
  - recompute and persist fingerprints for stages whose inputs were pending before upstream outputs were committed;
  - use `RunStore.write_stage_inputs()`, `write_stage_fingerprint()`, `write_stage_outputs()`, `write_stage_failure()`, `write_stage_provenance()`, `write_stage_status()`, `write_run_status()`, and artifact index helpers rather than writing JSON directly;
  - never mark a stage `SUCCEEDED` before outputs, artifact index entries, and relevant provenance have been persisted;
  - never mark a failed stage `FAILED` before failure metadata is persisted.
- `LocalExecutor` should:
  - validate the request enough to fail clearly;
  - call `stage.run(context, inputs)`;
  - capture exceptions into structured failure metadata with exception type, message, timestamps, executor name, and traceback reference/content;
  - avoid deciding resume, selector, or lifecycle policy.
- Output validation should reject:
  - missing declared outputs;
  - undeclared returned outputs;
  - returned values that are not `ArtifactRef`;
  - artifact type mismatches;
  - declared codec mismatches when `OutputSpec.codec_key` is set;
  - schema version mismatches when `OutputSpec.schema_version` is set;
  - missing artifact files, unsupported local validation, or checksum mismatches surfaced by `ArtifactStore.validate()`.

## Design Impact

- Maintainability: separates executor invocation, lifecycle, output validation, and runner orchestration so the first runtime path does not duplicate planning, store, or config behavior.
- Extensibility: an executor protocol and structured request/result models leave room for subprocess, SLURM, and container executors without changing the stage protocol or planner policy.
- Domain neutrality: execution only sees stage names, target paths, configs, artifact refs, output specs, statuses, and provenance. It must not inspect datasets, model checkpoints, metrics, reports, or other project-specific artifacts.
- Source-tree boundaries: implementation should stay under `src/loom/pipeline/execution`, `src/loom/pipeline/executors`, focused updates to `src/loom/pipeline/context.py` and `src/loom/pipeline/__init__.py`, and tests. It may import pipeline specs/graph/status/planning, store protocols, artifacts, provenance capture helpers, serialization, timestamps, and narrow config target-instantiation helpers. It must not import CLI behavior, remote stores, downstream project modules, or post-v0 executor code.

## Future Compatibility

- Keep executor request/result models backend-neutral enough for subprocess and SLURM executors to reuse later.
- Keep `StageContext` helpers backed by store protocols rather than `LocalArtifactStore` specifics where practical.
- Record executor metadata under nested metadata so future backend-specific fields do not reshape core status or failure records.
- Preserve `PlanAction.REUSE` as a plan/result concept rather than adding persisted `REUSE` status.
- Keep selector/resume options as Phase 8 model inputs so future CLI commands can call the same runner API.
- Keep run-state documents inspectable as plain JSON/YAML/text and compatible with the Phase 7 layout.
- Defer executor registries until more than one backend exists.

## Alternatives Rejected

| Alternative | Reason rejected |
| --- | --- |
| Implement runner logic in the CLI first | v0 explicitly defers functional CLI behavior, and lifecycle logic must be reusable by Python callers and future CLI code. |
| Let `LocalExecutor` write statuses and outputs directly | The runner must own lifecycle ordering so all backends share the same success/failure semantics. |
| Re-plan from scratch after every upstream stage | Phase 8 already owns planning policy; Phase 9 only needs to bind newly produced inputs and compute final fingerprints for pending downstream stages. |
| Treat `REUSE` as `SKIPPED` in persisted stage status | The v0 plan reserves `SKIP`/`SKIPPED` for selector exclusion and requires reused stages to retain prior `SUCCEEDED` state. |
| Accept context-collected outputs without direct returns | The v0 stage contract is `stage.run(context, inputs) -> Mapping[str, ArtifactRef]`; context-collected output sets are post-v0. |
| Add stage constructor kwargs | The implementation plan explicitly defers constructor kwargs; stage runtime config belongs in `StageContext.stage_config`. |
| Add subprocess or parallel execution now | The phase target is serial local in-process execution; broader backends need stable lifecycle semantics first. |

## Debt Introduced

| Debt | Reason accepted | Revisit trigger |
| --- | --- | --- |
| Local in-process executor is the only v0 backend | Required to keep the first runnable path reviewable and domain-neutral. | A later implementation plan adds subprocess, SLURM, container, or distributed execution. |
| Stop-on-first-failure only | Simplifies lifecycle, status, and artifact index semantics for v0. | Users need independent-branch continuation or retry policy and the state model is stable. |
| No run-level lock manager | Phase 7 accepted atomic writes without locks. | Tests or real usage expose concurrent writer or interrupted-run races that file atomicity cannot address. |
| Latest-attempt state overwrites earlier attempt files | Phase 7 stores latest inputs/outputs/fingerprints/failures. | Users need attempt history or retry audit trails. |
| Raw/overlay config snapshot persistence depends on supplied text/provenance | `ComposedConfig` exposes resolved/redacted data and provenance, not necessarily original rendered snapshots. | PR review or docs require complete replayable config snapshot files from only a `ComposedConfig`. |
| Minimal stdout/stderr capture policy | In-process capture can surprise user libraries; failure metadata and predictable log paths matter first. | CLI or local debugging needs stable captured stream defaults. |

## Reviewability

- Expected PR size and shape: one local-execution PR adding execution/executor models, local executor, runner lifecycle, context helpers, output validation, and focused tests. It should not include CLI behavior, remote stores, parallel scheduling, or broad predecessor refactors.
- Files and areas to inspect:
  - `src/loom/pipeline/execution/`
  - `src/loom/pipeline/executors/`
  - `src/loom/pipeline/context.py`
  - `src/loom/pipeline/__init__.py`
  - package API and import-boundary tests
  - unit tests for execution models, lifecycle, output validation, context helpers, runner, and local executor
  - contract tests for the executor protocol and local executor behavior
  - integration/e2e tests under `tests/integration/pipeline/` and `tests/e2e/`
- Scope-control checks:
  - no root `loom.__init__` runner/export growth unless the full plan explicitly already requires it;
  - no functional CLI commands;
  - no new runtime dependencies;
  - no subprocess/SLURM/container backend;
  - no remote stores or cross-run cache behavior;
  - no domain-specific stages or artifact semantics;
  - no planner resume-policy duplication.

## Implementation Steps

1. Refine this draft into a decision-complete contract with exact public exports, dataclass fields, status semantics for non-run actions, config snapshot inputs, and targeted test file names.
2. Add execution and executor error classes that preserve the existing `ExecutionError`, `PipelineError`, `StageContractError`, and validation hierarchy.
3. Add execution request/result models and failure metadata with plain-data serialization for persisted failure and result summaries where needed.
4. Add the `Executor` protocol and `LocalExecutor` implementation that invokes `stage.run(context, inputs)` and converts Python exceptions into structured failed results.
5. Extend `StageContext` with optional store-backed `output_path`, `save_artifact`, and `register_artifact` helpers while preserving existing constructor compatibility.
6. Add lifecycle helpers for root run status, stage running/succeeded/failed/skipped status records, attempt numbers, and failure-first ordering.
7. Add output validation helpers against `StageSpec.outputs` and `ArtifactStore.validate()`.
8. Add `PipelineRunner` orchestration for create/open run, config/provenance persistence, pipeline parsing, target instantiation, plan persistence, serial plan execution, pending input rebinding, fingerprint persistence, output commits, artifact index updates, stage provenance, failure handling, and final run result/status.
9. Add public exports from `loom.pipeline.execution`, `loom.pipeline.executors`, and the minimal confirmed `loom.pipeline` surface.
10. Add package, unit, contract, integration, and e2e tests. Run targeted commands during implementation and leave final `make validate-pr` and `make test-summary` to PR preparation.

## Test Plan

### Package Suite

- Status: required.
- Expected paths:
  - `tests/package/test_pipeline_execution_api.py`
  - `tests/package/test_pipeline_executor_api.py`
  - update `tests/package/test_pipeline_api.py`
  - update `tests/package/test_import_boundaries.py`
- Required assertions or deferral reason:
  - Public execution and executor exports match the refined contract.
  - `PipelineRunner` is importable from the agreed public path.
  - Importing `loom` remains cheap and does not import config composition, execution, executors, CLI, local stores, or project code.
  - Importing `loom.pipeline.execution` does not import `loom.cli`, project packages, subprocess/SLURM/container modules, or remote-store code.
  - Deferred CLI modules remain import-safe stubs.

### Unit Suite

- Status: required.
- Expected paths:
  - `tests/unit/loom/pipeline/execution/test_models.py`
  - `tests/unit/loom/pipeline/execution/test_lifecycle.py`
  - `tests/unit/loom/pipeline/execution/test_outputs.py`
  - `tests/unit/loom/pipeline/execution/test_runner.py`
  - `tests/unit/loom/pipeline/execution/test_execution_errors.py`
  - `tests/unit/loom/pipeline/executors/test_local.py`
  - update `tests/unit/loom/pipeline/test_context.py`
- Required assertions or deferral reason:
  - Execution models validate and serialize plain-data fields where persisted.
  - Lifecycle helpers write failure before failed status and outputs/indexes before succeeded status.
  - Output validation rejects missing, extra, non-`ArtifactRef`, wrong-type, wrong-codec, wrong-schema, missing-file, and checksum-mismatched outputs with stage-aware messages.
  - LocalExecutor returns success for a dummy stage and structured failure for an exception without making lifecycle decisions.
  - StageContext helpers allocate under the stage artifact area, save/register artifacts through store protocols, reject unsafe output names, and do not collect implicit outputs.
  - PipelineRunner unit tests cover `RUN`, `REUSE`, `SKIP`, and `BLOCKED` plan handling with fakes or temporary stores.

### Contract Suite

- Status: required.
- Expected paths:
  - `tests/contracts/test_executor_contract.py`
  - update `tests/contracts/test_stage_contract.py` only if context helper additions require additional structural-stage assertions.
- Required assertions or deferral reason:
  - Downstream executor implementations can satisfy the public `Executor` protocol structurally.
  - `LocalExecutor` satisfies the shared executor contract for successful stage output mappings and exception-to-failure conversion.
  - Existing stage and store contracts remain valid after context/execution additions.

### Integration Suite

- Status: required.
- Expected paths:
  - `tests/integration/pipeline/test_local_execution.py`
  - `tests/integration/pipeline/test_local_execution_resume.py`
  - `tests/integration/pipeline/test_local_execution_failures.py`
- Required assertions or deferral reason:
  - PipelineRunner collaborates with `LocalRunStore`, `LocalArtifactStore`, Phase 8 planning, and dummy trusted stage targets over temporary run directories.
  - Successful runs write `run.json`, `status.json`, `plan.json`, config snapshots, recipe manifest when present, provenance documents, stage status/input/output/fingerprint/provenance files, logs where applicable, artifacts, and `artifacts.json`.
  - Same-run rerun reuses unchanged stages without invoking their executor and without changing prior `SUCCEEDED` stage status to `SKIPPED`.
  - Changed stage config or upstream artifacts rerun changed stages and downstream dependents.
  - Selector `skip_stages`, `only_stages`, `from_stage`, and `force_stages` behavior is reflected through the runner using the Phase 8 planner.
  - Stage construction, invalid outputs, artifact validation failures, and stage exceptions leave inspectable failure state and failed run status.

### E2E Suite

- Status: required.
- Expected paths:
  - `tests/e2e/test_local_pipeline_run.py`
- Required assertions or deferral reason:
  - Compose a synthetic YAML config, run it through the public Python config and runner APIs, and assert the run directory contains expected config, plan, status, input, output, fingerprint, artifact, provenance, and index files.
  - Rerun the same run directory and assert valid unchanged stages produce `REUSE` plan decisions without executor invocation.
  - Modify config or an upstream artifact and assert affected stages rerun while unaffected reusable stages are preserved.
  - Inject a dummy stage failure and assert `failure.json` is written before failed status and downstream stages are not executed.

### Opt-In Suites

- Status: deferred.
- Markers affected: `slow`, `network`, `slurm`, `optional_dependency`.
- Required assertions or deferral reason: Phase 9 should be local, deterministic, and covered by default suites. It must not require network services, SLURM, remote stores, optional dependencies outside the default dev environment, or slow acceptance tests.

## Risks

- The runner may accidentally duplicate planner policy when rebinding pending downstream inputs. It should only bind produced outputs, recompute final fingerprints, and use the Phase 8 plan/action semantics.
- Output validation and lifecycle ordering are easy to get subtly wrong. Tests must assert files and statuses in the order required by the plan.
- `StageContext` helper additions can break existing minimal context tests if defaults and plain-data validation are not preserved.
- Config snapshot persistence has ambiguity for raw/overlay/override text when the runner receives only a resolved mapping. The refine pass must settle this before implementation.
- `BLOCKED` plan actions have no persisted stage status. The refine pass must lock run-result and status behavior before executor work.
- The stack may move under this branch when Phase 7 or Phase 8 lands. Rebase/replay and validation must be recorded before PR merge eligibility.

## Validation Commands

Targeted development commands:

```sh
make test-package
make test-unit
make test-contract
make test-integration
make test-e2e
uv run pytest tests/unit/loom/pipeline/execution tests/unit/loom/pipeline/executors -q
uv run pytest tests/integration/pipeline/test_local_execution.py tests/integration/pipeline/test_local_execution_resume.py tests/integration/pipeline/test_local_execution_failures.py -q
uv run pytest tests/e2e/test_local_pipeline_run.py -q
```

Final PR-preparation commands:

```sh
make validate-pr
make test-summary
```

## Handoff Notes For `loom_phase_executor`

- Safe implementation slices:
  - execution/executor errors and models;
  - `Executor` protocol and `LocalExecutor`;
  - `StageContext` store-backed helpers;
  - lifecycle/status/failure helpers;
  - output validation;
  - target instantiation and stage contract checks;
  - `PipelineRunner` create/open, plan, execute, commit, resume, and failure flows;
  - package/unit/contract/integration/e2e tests.
- Tests to run with each slice:
  - API/import changes: `make test-package`;
  - models/lifecycle/output validation: `uv run pytest tests/unit/loom/pipeline/execution -q`;
  - executor behavior: `uv run pytest tests/unit/loom/pipeline/executors tests/contracts/test_executor_contract.py -q`;
  - context helpers: `uv run pytest tests/unit/loom/pipeline/test_context.py tests/unit/loom/pipeline/execution/test_runner.py -q`;
  - store/planner collaboration: `uv run pytest tests/integration/pipeline/test_local_execution.py tests/integration/pipeline/test_local_execution_resume.py -q`;
  - full local workflow: `make test-e2e`.
- Decisions the executor must not revisit:
  - no CLI behavior;
  - no subprocess, SLURM, container, parallel, retry, timeout, or remote-store behavior;
  - no cross-run cache reuse;
  - no stage constructor kwargs;
  - no context-collected outputs as an alternate success path;
  - `REUSE` is not persisted as `SKIPPED`;
  - runner owns lifecycle, output validation, status writes, fingerprints, and resume execution semantics;
  - stores own persisted file formats and atomic writes;
  - planner owns selector, resume, invalidation, and plan explanation policy.
- Conditions that require stopping for the manager:
  - Phase 7 store APIs are insufficient and require changing the predecessor branch contract;
  - Phase 8 plan models or pending-input semantics cannot support local execution without changing predecessor behavior;
  - `StageContext` cannot be extended compatibly with existing public tests;
  - an acceptance criterion cannot be met without implementing CLI, remote storage, subprocess execution, cross-run cache reuse, or other future-phase behavior;
  - stack base or PR target state changes before implementation and requires manager stack maintenance.

## Refinement And Review Budget Status

- Phase implementation refinement: unused.
- PR review: unused.
- PR body draft/refine: unused.
- Plan refine pass: unused and required before implementation.

## Completion Notes

- Draft plan: completed by `loom_phase_planner` on `codex/add-local-execution`.
- Final phase execution plan: pending refine pass.
- Implementation summary: pending.
- Implementation validation: pending.
- Refinement summary: pending.
- PR preparation: pending.
- Stack maintenance: pending Phase 7 and Phase 8 merge/rebase/retarget state.
- Remaining blockers: none.
