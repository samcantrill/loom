# Phase 9 Execution Plan: Local Execution

## Metadata

- Status: refined phase execution plan; decision-complete for implementation.
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
- Draft pass: completed by `loom_phase_planner` on 2026-05-04 local time in commit `d117dfb993c66029bb985e1b4424d5333ee8a6c8`.
- Refine pass: completed by `loom_phase_planner` on 2026-05-04 local time in this artifact update.
- Phase implementation refinement budget: unused.
- PR review budget: unused.
- PR body draft pass: unused.
- PR body refine/open pass: unused.
- Setup limitations: no remote synchronization, broad checks, implementation validation, or PR checks were run during this planning-only refine pass.
- Blockers: none.

## Objective

Implement the first end-to-end local runtime path for v0. Phase 9 turns the already-tested config, static pipeline, graph, local store, and planning layers into a serial in-process runner that creates or opens local run directories, persists config and provenance, plans work, executes runnable stages, validates returned `ArtifactRef` outputs, commits lifecycle state, updates artifact indexes, records failure state, and supports conservative same-run-directory resume.

The runner must stay domain-neutral. Stages remain black boxes that satisfy the structural `Stage.run(context, inputs)` protocol and return `Mapping[str, ArtifactRef]`. The runner owns lifecycle, output validation, status writes, fingerprints, plan execution semantics, and same-run-directory resume behavior.

## Full-Plan Context

Phases 1 through 6 are merged and provide the package skeleton, primitives, serialization, I/O/codecs, trusted config composition, recipe expansion, target import/instantiation helpers, static pipeline specs, graph validation, strict `stage.output` bindings, status records, and the minimal `StageContext`.

Phase 7 PR #11 remains open against `develop` and provides the local run/artifact stores and inspectable file layout. Phase 8 PR #12 remains open against Phase 7 and provides deterministic planning, selectors, stage fingerprints, conservative resume checks, downstream invalidation, and `RunStore.write_plan()` persistence. Phase 9 must build on Phase 8 and consume the real `RunStore`, `ArtifactStore`, `ExecutionPlan`, `StagePlan`, `PlanAction`, `PlanSelectors`, `ResumeOptions`, `FingerprintContext`, `BoundInput`, `PendingInput`, and `build_stage_fingerprint()` APIs.

Phase 10 remains out of scope. It will harden error message coverage, interrupted-run edge cases, extension contract breadth, and documentation after the local runner exists. Phase 9 should not absorb Phase 10 cleanup or documentation expansion unless directly required to make the local execution API testable.

## Stack Context

- Root or stacked phase: stacked phase.
- Current predecessor branch or PR: `codex/add-planning-resume-selectors`, GitHub PR #12, recorded as open against `codex/add-local-stores-run-layout`.
- Why this base branch is correct: Phase 7 PR #11 is still open against `develop`, Phase 8 PR #12 is still open against Phase 7, and Phase 9 depends on Phase 8 planner/resume/selectors. The manager assignment explicitly requires the Phase 9 branch to remain based on `codex/add-planning-resume-selectors` at `98a5fd6725c979cd93f913efc0d2f2e2fc67b6d4`.
- Retarget/rebase plan after predecessor merge: after Phase 7 lands, Phase 8 must be replayed or rebased onto updated `develop` and retargeted. After Phase 8 lands, replay or rebase this Phase 9 branch onto updated `develop`, retarget its PR to `develop`, rerun validation, and record stack maintenance in this artifact and the PR body.
- Branch cleanup constraints: do not delete the Phase 8 predecessor branch while this branch depends on it. Do not delete this Phase 9 branch until every successor branch has been retargeted or rebased away from it.

## Source Phase Summary

- Goal: implement the end-to-end local runner using the already-tested config, graph, store, and planning layers.
- Required scope:
  - Add an executor protocol and in-process `LocalExecutor`.
  - Add execution request/result types, run result types, lifecycle helpers, logs helpers, output validation, and `PipelineRunner`.
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
  - Output validation checks exact returned keys, `ArtifactRef` values, artifact types, declared codec keys, schema versions, existing artifact files, and checksums when present.
  - Failure behavior writes `failure.json` before `FAILED` status, avoids downstream execution in the same run, marks the run failed, and leaves state inspectable.
  - Resume is same-run-directory only. `REUSE` planner decisions retain prior `SUCCEEDED` state and must not be persisted as `SKIPPED`.
- Source references: `docs/implementation-plans/implementation-plan-v0.md` Phase 9; `docs/structure.md` sections "Execution and Executors", "Pipeline Model and Planning", "Stores and State", "Runtime Dependency Policy", "Test Layout", and "Review Checklist"; `docs/loom.md` sections 8 through 12; `docs/features/pipeline.md`, `docs/features/execution.md`, `docs/features/run-store.md`, `docs/features/artifacts.md`, `docs/features/provenance.md`, `docs/features/resume.md`, `docs/features/state.md`, `docs/features/runtime-resources.md`, and `docs/features/testing.md`.

## Current API Findings

- `src/loom/pipeline/execution/__init__.py` and `src/loom/pipeline/executors/__init__.py` are import-safe skeletons with empty public surfaces.
- `StageContext` currently has frozen fields `run_id`, `stage_name`, `run_dir`, `stage_dir`, `resolved_config`, `stage_config`, `provenance`, and `metadata`. Phase 9 must preserve compatibility for existing construction and tests by adding only defaulted runtime-service fields.
- `Stage` is a runtime-checkable structural protocol for `run(context, inputs) -> Mapping[str, ArtifactRef]`.
- `PipelineSpec.from_config()` parses strict v0 orchestration keys and stores canonical `StageSpec` fields `name`, `target_path`, `stage_config`, `dependencies`, `inputs`, `outputs`, and `resources`.
- `RunStatus` values are `CREATED`, `PLANNED`, `RUNNING`, `SUCCEEDED`, `FAILED`, `CANCELLED`, and `INTERRUPTED`.
- `StageStatus` values are `PENDING`, `RUNNING`, `SUCCEEDED`, `FAILED`, `SKIPPED`, `STALE`, and `CANCELLED`. There is no persisted `REUSE` or `BLOCKED` stage status.
- `RunStore` already owns run/stage directories, config snapshots, provenance documents, run/stage status, plan, inputs, outputs, fingerprint, failure, stage provenance, stdout/stderr logs, and artifact indexes.
- `LocalRunStore` supports config snapshot names `raw`, `overlays`, `cli_overrides`, `resolved`, and `resolved_redacted`, and provenance names `environment`, `git`, `command`, and `dependencies`.
- `ArtifactStore` exposes `save`, `register`, `load`, `exists`, `verify_checksum`, and `validate`. `LocalArtifactStore.allocate_path()` exists on the concrete local store, but it is not part of the protocol; `StageContext.output_path()` must therefore use `RunStore.get_stage_artifact_dir()` rather than requiring a concrete artifact store.
- `LocalArtifactStore` expects its root to be the run artifact root returned by `RunStore.get_artifact_root(run_id)`, then writes managed artifacts under `<artifact_root>/<stage>/<output>.<suffix>`.
- `planning.plan_pipeline()` accepts `spec`, `run_id`, `run_store`, `artifact_store`, `selectors`, `resume`, `fingerprint_context`, and `persist`. It returns `ExecutionPlan` with ordered `StagePlan` values.
- `StagePlan` has fields `stage_name`, `action`, `base_action`, `fingerprint_status`, `fingerprint`, `resume_check`, `reasons`, `bound_inputs`, `pending_inputs`, `reusable_outputs`, `declared_outputs`, `upstream_stages`, `downstream_stages`, `selected_by`, and `invalidated_by`.
- `build_stage_fingerprint(stage, bound_inputs=..., fingerprint_context=...)` raises when inputs remain pending; the runner must compute final fingerprints after upstream `RUN` stages commit outputs.
- `ComposedConfig` has `resolved`, `redacted`, `provenance`, `recipe_manifest`, and `fingerprint`.
- Stage target import should use `loom.config.instantiate.targets.import_target()` narrowly; recursive config instantiation and stage constructor kwargs remain out of scope.
- There is currently no `tests/e2e` directory. Phase 9 should add the first e2e suite for local Python API execution.

## Refined Implementation Contract

### Files And Public Exports

Implement execution files under:

- `src/loom/pipeline/execution/errors.py`
- `src/loom/pipeline/execution/models.py`
- `src/loom/pipeline/execution/lifecycle.py`
- `src/loom/pipeline/execution/logs.py`
- `src/loom/pipeline/execution/outputs.py`
- `src/loom/pipeline/execution/runner.py`
- `src/loom/pipeline/execution/__init__.py`

Implement executor files under:

- `src/loom/pipeline/executors/errors.py`
- `src/loom/pipeline/executors/base.py`
- `src/loom/pipeline/executors/local.py`
- `src/loom/pipeline/executors/__init__.py`

Update only these existing runtime files unless tests prove an exact acceptance criterion is impossible without a predecessor contract change:

- `src/loom/pipeline/context.py`
- `src/loom/pipeline/__init__.py`

Public exports from `loom.pipeline.execution` must be:

```python
ConfigSnapshotInputs
ExecutionFailure
FailurePolicy
PipelineExecutionError
PlanExecutionError
RunRequest
RunRequestError
RunResult
StageExecutionRequest
StageExecutionResult
StageExecutionRuntimeError
StageRunResult
LifecycleError
OutputValidationError
PipelineRunner
run_pipeline
validate_stage_outputs
```

Public exports from `loom.pipeline.executors` must be:

```python
Executor
ExecutorError
LocalExecutor
LocalExecutorError
```

Update `loom.pipeline.__all__` to include `PipelineRunner`, `RunRequest`, and `RunResult`. Do not add execution, runner, or executor exports to root `loom.__init__`.

### Error Classes

Define execution errors as:

```python
class PipelineExecutionError(ExecutionError, PipelineError): ...
class RunRequestError(PipelineExecutionError, ValidationError): ...
class PlanExecutionError(PipelineExecutionError): ...
class LifecycleError(PipelineExecutionError): ...
class StageExecutionRuntimeError(PipelineExecutionError): ...
class OutputValidationError(PipelineExecutionError, ValidationError): ...
class ExecutorError(PipelineExecutionError): ...
class LocalExecutorError(ExecutorError): ...
```

`ExecutorError` and `LocalExecutorError` live in `loom.pipeline.executors.errors` and are re-exported by `loom.pipeline.executors`. `PipelineExecutionError`, `RunRequestError`, `PlanExecutionError`, `LifecycleError`, `StageExecutionRuntimeError`, and `OutputValidationError` live in `loom.pipeline.execution.errors`.

Stage code exceptions should normally become failed `StageExecutionResult` values with `ExecutionFailure`, not raw exceptions escaping through `PipelineRunner`. Infrastructure errors such as an invalid request, bad plan state, store write failure, or target construction failure may raise or be converted into persisted `ExecutionFailure` depending on whether the runner has enough stage/run context to write failure state.

### Dataclass Fields

Add these frozen, slotted dataclasses in `loom.pipeline.execution.models`.

```python
@dataclass(frozen=True, slots=True)
class ConfigSnapshotInputs:
    raw: str | None = None
    overlays: str | None = None
    cli_overrides: str | None = None
```

Only these three snapshots are caller-supplied. The runner derives `resolved`, `resolved_redacted`, and recipe manifest from the `config` value.

```python
@dataclass(frozen=True, slots=True)
class FailurePolicy:
    stop_on_first_failure: bool = True
```

Phase 9 only supports `stop_on_first_failure=True`. Supplying `False` must raise `RunRequestError` with a message that continue-on-failure is deferred.

```python
@dataclass(frozen=True, slots=True)
class RunRequest:
    config: ComposedConfig | Mapping[str, PlainData] | None = None
    pipeline: PipelineSpec | None = None
    run_id: str | None = None
    open_existing: bool = False
    selectors: PlanSelectors = field(default_factory=PlanSelectors)
    resume: ResumeOptions = field(default_factory=ResumeOptions)
    fingerprint_context: FingerprintContext = field(default_factory=FingerprintContext)
    config_snapshots: ConfigSnapshotInputs = field(default_factory=ConfigSnapshotInputs)
    provenance_options: ProvenanceCaptureOptions = field(default_factory=ProvenanceCaptureOptions)
    command: CommandProvenance | None = None
    project_root: Path | None = None
    failure_policy: FailurePolicy = field(default_factory=FailurePolicy)
    metadata: Mapping[str, PlainData] = field(default_factory=dict)
```

Validation rules:

- At least one of `config` or `pipeline` is required.
- If `pipeline` is omitted, `config` must be a `ComposedConfig` or plain mapping containing a top-level `pipeline` key; parse it with `parse_pipeline_config(config.resolved["pipeline"])` or `parse_pipeline_config(config["pipeline"])`.
- If both `pipeline` and `config` are supplied, use `pipeline` as the execution spec and use `config` only for snapshots, provenance, and fingerprint context defaults.
- `run_id=None` generates `safe_timestamp_for_path(timespec="seconds")`. Tests should usually pass explicit run IDs to avoid collisions.
- `open_existing=False` creates the run with `RunStore.create_run()`. `open_existing=True` opens the same run with `RunStore.open_run()` and is the only Phase 9 resume entry point.
- `selectors`, `resume`, and `fingerprint_context` must be Phase 8 model instances or coercible from their `from_dict()` shape.
- `metadata` must be plain-data-compatible and is passed to `RunStore.create_run()` or `RunStore.write_run_metadata()`.

```python
@dataclass(frozen=True, slots=True)
class ExecutionFailure:
    schema_version: int
    run_id: str
    stage_name: str
    attempt: int
    failed_at: str
    executor: str
    failure_type: str
    message: str
    exception_type: str | None = None
    traceback_path: str | None = None
    stdout_path: str | None = None
    stderr_path: str | None = None
    exit_code: int | None = None
    executor_metadata: Mapping[str, PlainData] = field(default_factory=dict)
    details: Mapping[str, PlainData] = field(default_factory=dict)
```

`schema_version` is `1`. `failure_type` uses stable strings: `stage_exception`, `stage_contract`, `output_validation`, `target_construction`, `plan_execution`, `store_commit`, or `executor_infrastructure`. Add `to_dict()` and `from_dict()` so `RunStore.write_stage_failure()` receives plain data. Traceback text must be stored in `stages/<stage>/logs/traceback.txt`; `failure.json` stores only the path string.

```python
@dataclass(frozen=True, slots=True)
class StageExecutionRequest:
    run_id: str
    stage: StageSpec
    stage_plan: StagePlan
    stage_object: Stage
    context: StageContext
    inputs: Mapping[str, ArtifactRef]
    fingerprint: StageFingerprintRecord
    attempt: int
    stdout_path: Path
    stderr_path: Path
    traceback_path: Path
    metadata: Mapping[str, PlainData] = field(default_factory=dict)
```

`StageExecutionRequest` is the executor input. It must contain a fully constructed stage object and fully bound inputs. It must not contain selector or resume policy knobs.

```python
@dataclass(frozen=True, slots=True)
class StageExecutionResult:
    stage_name: str
    status: StageStatus
    outputs: Mapping[str, ArtifactRef]
    failure: ExecutionFailure | None
    started_at: str
    finished_at: str
    executor_name: str
    attempt: int
    stdout_path: str | None = None
    stderr_path: str | None = None
    traceback_path: str | None = None
    executor_metadata: Mapping[str, PlainData] = field(default_factory=dict)
```

`StageExecutionResult.status` may only be `StageStatus.SUCCEEDED` or `StageStatus.FAILED`. `LocalExecutor` must not return `SKIPPED`, `STALE`, `PENDING`, `RUNNING`, `CANCELLED`, `REUSE`, or `BLOCKED` semantics.

```python
@dataclass(frozen=True, slots=True)
class StageRunResult:
    stage_name: str
    action: PlanAction
    status: StageStatus | None
    attempt: int | None
    outputs: Mapping[str, ArtifactRef]
    failure: ExecutionFailure | None = None
    reasons: tuple[PlanReason, ...] = ()
    started_at: str | None = None
    finished_at: str | None = None
    executor_metadata: Mapping[str, PlainData] = field(default_factory=dict)
```

`StageRunResult` is the runner-level per-stage summary. It represents `RUN`, `REUSE`, `SKIP`, and `BLOCKED` outcomes without inventing new persisted statuses.

```python
@dataclass(frozen=True, slots=True)
class RunResult:
    run_id: str
    run_dir: Path
    status: RunStatus
    started_at: str
    finished_at: str
    plan: ExecutionPlan
    stage_results: Mapping[str, StageRunResult]
    failed_stage: str | None = None
    failure: ExecutionFailure | None = None
    artifact_index: Mapping[str, ArtifactRef] = field(default_factory=dict)
    metadata: Mapping[str, PlainData] = field(default_factory=dict)
```

`RunResult.stage_results` must contain an entry for every stage in `ExecutionPlan.stage_order`. Stages not reached after stop-on-first-failure should be represented as `StageRunResult(action=PlanAction.BLOCKED, status=None, attempt=None, outputs={}, reasons=...)` without persisted stage files.

### Runner Input And Constructor

`PipelineRunner` is the public Python runner.

```python
ArtifactStoreFactory = Callable[[Path], ArtifactStore]

class PipelineRunner:
    def __init__(
        self,
        *,
        run_store: RunStore,
        executor: Executor | None = None,
        artifact_store_factory: ArtifactStoreFactory | None = None,
        clock: Callable[[], str] = utc_timestamp,
    ) -> None: ...

    def run(self, request: RunRequest) -> RunResult: ...
```

Defaults:

- `executor=None` becomes `LocalExecutor()`.
- `artifact_store_factory=None` becomes `lambda root: LocalArtifactStore(root)`.
- The factory is called after the run is created/opened with `run_store.get_artifact_root(run_id)`.
- Do not accept a global artifact store rooted above the run artifact root by default; that would make same-run-directory resume boundaries ambiguous.

`run_pipeline()` is a convenience wrapper:

```python
def run_pipeline(
    request: RunRequest,
    *,
    run_store: RunStore,
    executor: Executor | None = None,
    artifact_store_factory: ArtifactStoreFactory | None = None,
) -> RunResult: ...
```

It must instantiate `PipelineRunner` and call `runner.run(request)`; it must not duplicate runner logic.

### StageContext Helper Signatures

Extend `StageContext` compatibly by adding defaulted fields:

```python
run_store: RunStore | None = None
artifact_store: ArtifactStore | None = None
output_specs: Mapping[str, OutputSpec] = field(default_factory=dict)
```

Existing fields and constructor compatibility must remain intact. Runtime-service fields are not plain data and must not be passed to `ensure_plain_data()`.

Add exactly these methods:

```python
def output_path(self, name: str, *, suffix: str = "") -> Path: ...

def save_artifact(
    self,
    name: str,
    obj: object,
    *,
    artifact_type: str,
    codec_key: str,
    schema_version: int = 1,
    metadata: Mapping[str, PlainData] | None = None,
    fingerprint: str | None = None,
) -> ArtifactRef: ...

def register_artifact(
    self,
    name: str,
    path: str | Path,
    *,
    artifact_type: str,
    codec_key: str | None = None,
    schema_version: int = 1,
    metadata: Mapping[str, PlainData] | None = None,
    fingerprint: str | None = None,
    checksum: str | None = None,
    allow_external: bool = False,
) -> ArtifactRef: ...
```

Helper rules:

- `output_path()` requires `run_store` and returns `run_store.get_stage_artifact_dir(run_id, stage_name) / f"{name}{suffix}"` after creating the stage artifact directory. It validates `name` with the same store path rules as outputs and rejects suffixes containing path separators, NUL, or parent traversal.
- `save_artifact()` requires `artifact_store` and delegates to `artifact_store.save()` with this context's `run_id` and `stage_name`.
- `register_artifact()` requires `artifact_store` and delegates to `artifact_store.register()` with this context's `run_id` and `stage_name`.
- If `output_specs` is non-empty, all three helpers reject undeclared output names. They may compare caller-supplied `artifact_type`, `codec_key`, and `schema_version` with the declared `OutputSpec`, but they must not silently fill or override caller-supplied values.
- Helpers return `ArtifactRef`s. They do not collect implicit outputs, mutate context state, or allow a stage to succeed without returning the direct output mapping.

### Executor Protocol And LocalExecutor

Define the executor protocol in `loom.pipeline.executors.base`:

```python
@runtime_checkable
class Executor(Protocol):
    name: str

    def execute(self, request: StageExecutionRequest) -> StageExecutionResult: ...
```

Define `LocalExecutor` in `loom.pipeline.executors.local`:

```python
class LocalExecutor:
    name = "local"

    def __init__(self, *, capture_stdout_stderr: bool = False) -> None: ...

    def execute(self, request: StageExecutionRequest) -> StageExecutionResult: ...
```

Local executor behavior:

- Validate `request.stage_object` satisfies `Stage`.
- Call exactly `request.stage_object.run(request.context, request.inputs)`.
- Do not decide selector, resume, downstream invalidation, lifecycle status, or artifact index policy.
- On success, return `StageExecutionResult(status=StageStatus.SUCCEEDED, outputs=returned_mapping, failure=None, ...)`.
- On Python exception, write full traceback text to `request.traceback_path`, return `StageExecutionResult(status=StageStatus.FAILED, outputs={}, failure=ExecutionFailure(...), ...)`, and include `exception_type`, `message`, `traceback_path`, `executor="local"`, `started_at`, `finished_at`, and `attempt`.
- `capture_stdout_stderr=False` is the default. When false, do not redirect process streams; still include `stdout_path` and `stderr_path` in metadata if paths were supplied. When true, redirect stdout/stderr for the stage call only and write captured text to the supplied paths.

### Lifecycle And Persisted Status Semantics

Use existing `RunStatusRecord` and `StageStatusRecord`; do not add new persisted status values.

Root run lifecycle for each runner invocation:

1. `CREATED` after `create_run()` or successful `open_run()` and metadata/snapshot setup begins.
2. `PLANNED` after `plan_pipeline(..., persist=True)` succeeds and `plan.json` round-trips.
3. `RUNNING` immediately before handling the first stage action.
4. `SUCCEEDED` after every stage has resolved to `RUN` success, valid `REUSE`, or selector `SKIP`.
5. `FAILED` after the first failed stage, unrebindable planned input, non-executable `BLOCKED` action, unexpected `STALE` action, target construction failure, output validation failure, or store commit failure.

Stage lifecycle:

- Attempt number for any current invocation write is `prior_status.attempt + 1` when prior status exists, otherwise `1`.
- `RUN`: write current inputs and final fingerprint, write `RUNNING`, invoke executor, validate outputs, write outputs, merge artifact index with `replace=True` for keys owned by the same stage outputs, write stage provenance, then write `SUCCEEDED`.
- `REUSE`: do not invoke executor and do not overwrite prior `StageStatus.SUCCEEDED`. Read prior outputs from `stage_plan.reusable_outputs` or `run_store.read_stage_outputs()` and include them in `StageRunResult`. Do not persist `SKIPPED`.
- `SKIP`: write `StageStatus.SKIPPED` with selector reasons in `metadata`, no inputs/outputs/fingerprint writes, no executor invocation.
- `BLOCKED`: do not write a stage status. Mark the run failed and return a `StageRunResult` with `action=PlanAction.BLOCKED`, `status=None`, and plan reasons.
- `STALE`: a final executable plan must not contain `STALE`. Treat it as `PlanExecutionError`, mark the run failed, and do not invoke an executor.
- Stage failure: write `failure.json` first, then write `StageStatus.FAILED`, then write root `RunStatus.FAILED`.

Implement lifecycle helpers in `execution.lifecycle` with these names:

```python
next_stage_attempt(run_store: RunStore, run_id: str, stage_name: str) -> int
write_run_status(
    run_store: RunStore,
    *,
    run_id: str,
    status: RunStatus,
    created_at: str,
    updated_at: str,
    started_at: str | None = None,
    finished_at: str | None = None,
    message: str | None = None,
    metadata: Mapping[str, PlainData] | None = None,
) -> RunStatusRecord
write_stage_running(
    run_store: RunStore,
    *,
    run_id: str,
    stage_name: str,
    attempt: int,
    started_at: str,
    owner: Mapping[str, PlainData] | None = None,
    metadata: Mapping[str, PlainData] | None = None,
) -> StageStatusRecord
write_stage_succeeded(
    run_store: RunStore,
    *,
    run_id: str,
    stage_name: str,
    attempt: int,
    started_at: str,
    finished_at: str,
    message: str | None = None,
    owner: Mapping[str, PlainData] | None = None,
    metadata: Mapping[str, PlainData] | None = None,
) -> StageStatusRecord
write_stage_failed(
    run_store: RunStore,
    *,
    run_id: str,
    stage_name: str,
    attempt: int,
    started_at: str | None,
    finished_at: str,
    message: str,
    owner: Mapping[str, PlainData] | None = None,
    metadata: Mapping[str, PlainData] | None = None,
) -> StageStatusRecord
write_stage_skipped(
    run_store: RunStore,
    *,
    run_id: str,
    stage_name: str,
    attempt: int,
    finished_at: str,
    message: str | None = None,
    metadata: Mapping[str, PlainData] | None = None,
) -> StageStatusRecord
```

The stage helpers should build and write `StageStatusRecord` values. Tests must assert the ordering around failure-before-failed-status and outputs/index/provenance-before-succeeded-status.

### Config Snapshot And Provenance Behavior

Runner config behavior:

- If `request.config` is `ComposedConfig`, persist:
  - `resolved` snapshot from `json_dumps_pretty(config.resolved)`;
  - `resolved_redacted` snapshot from `json_dumps_pretty(config.redacted)`;
  - recipe manifest from `config.recipe_manifest`;
  - config provenance under run metadata as plain data.
- If `request.config` is a plain mapping, persist:
  - `resolved` from `json_dumps_pretty(mapping)`;
  - `resolved_redacted` as the same rendered content unless the caller supplied a `ComposedConfig`;
  - an empty recipe manifest.
- If `request.config_snapshots.raw`, `.overlays`, or `.cli_overrides` is not `None`, write those strings to the matching run-store snapshot names. If they are `None`, skip those optional snapshots rather than fabricating source text.
- JSON is acceptable for `resolved.yaml` and `resolved.redacted.yaml` because JSON is valid YAML and the repository has no YAML dump helper yet. Do not add a new serialization dependency.

Runner provenance behavior:

- Persist root provenance documents through `RunStore.write_provenance_document()` using names `environment`, `git`, `command`, and `dependencies` where capture succeeds or degrades to an error-containing provenance model.
- Use `request.command` when supplied; otherwise call `capture_command_provenance()`.
- Use `request.project_root` to populate git/fingerprint context when supplied. Do not inspect arbitrary project packages beyond requested dependency provenance.
- Stage provenance uses `StageProvenance` and records `run_id`, `stage_name`, `status`, `attempt`, `target`, `started_at`, `finished_at`, duration when available, fingerprint payload, input/output artifact summaries, and executor metadata.

### Target Construction And Stage Contract

For each `RUN` stage:

- Import the target with `import_target(stage.target_path, path=f"pipeline.stages[{index}]._target_")`.
- If the imported target already satisfies `Stage`, use it directly.
- Otherwise, if it is callable, call it with no positional or keyword arguments.
- Do not pass `stage.stage_config` or any constructor kwargs.
- After construction, require `isinstance(stage_object, Stage)`. If false, fail with `StageContractError` converted to `ExecutionFailure(failure_type="stage_contract")`.
- Constructor/import failures are converted to `ExecutionFailure(failure_type="target_construction")` for that stage when stage context is available, then persisted before `StageStatus.FAILED`.

### Plan Execution And Rebinding

Initial planning:

- Call `plan_pipeline(spec, run_id=..., run_store=..., artifact_store=..., selectors=request.selectors, resume=request.resume, fingerprint_context=request.fingerprint_context, persist=True)` exactly once per runner invocation.
- Do not duplicate selector, resume, invalidation, or topological ordering policy in the runner.
- Execute stages in `ExecutionPlan.ordered_stage_plans`.

Rebinding for `RUN` stages:

- Before a `RUN` stage executes, resolve final inputs from:
  - `stage_plan.bound_inputs` for already-bound `REUSE` upstreams; and
  - committed in-memory outputs from earlier successful `RUN` or `REUSE` stages in the same runner loop.
- Do not resolve pending inputs from arbitrary artifact-index entries. The source stage must have completed or reused in this plan execution.
- If any declared input cannot be rebound, write failure state for the current stage with `failure_type="plan_execution"`, mark the stage failed, mark the run failed, and stop.
- After all inputs are rebound, call `build_stage_fingerprint(stage, bound_inputs=final_inputs, fingerprint_context=request.fingerprint_context)` and persist it with `RunStore.write_stage_fingerprint(..., attempt=attempt)`.
- Do not rewrite `plan.json` during rebinding. The initial plan remains the planner's explanation; final per-stage fingerprint files record the committed execution inputs.

### Output Validation

Implement:

```python
def validate_stage_outputs(
    *,
    stage: StageSpec,
    outputs: Mapping[str, object],
    artifact_store: ArtifactStore,
) -> dict[str, ArtifactRef]: ...
```

Validation requirements:

- `outputs` must be a mapping.
- Returned keys must exactly match `stage.outputs`.
- Missing declared outputs raise `OutputValidationError` naming `pipeline.stages.<stage>.outputs.<output>`.
- Extra returned outputs raise `OutputValidationError` naming the undeclared key.
- Every value must be an `ArtifactRef`.
- `ref.artifact_type` must equal `OutputSpec.artifact_type`.
- If `OutputSpec.codec_key` is not `None`, `ref.codec_key` must match it.
- If `OutputSpec.schema_version` is not `None`, `ref.schema_version` must match it.
- If `ref.producer_stage` is set, it must equal `stage.name`.
- Call `artifact_store.validate(ref, expected_type=output_spec.artifact_type)` for every output and wrap `ArtifactNotFoundError`, `ArtifactChecksumMismatchError`, `ArtifactTypeMismatchError`, `ArtifactChecksumUnsupportedError`, and other `ArtifactStoreError` in `OutputValidationError` with stage/output context.
- Return a normalized `dict[str, ArtifactRef]` only after all outputs pass.

Validation happens after executor success and before any success commit. A stage must not be marked `SUCCEEDED` until outputs, artifact index entries, and stage provenance are durable.

### Artifact Index Commit Behavior

For a successful `RUN` stage:

- Read the current run artifact index with `RunStore.read_artifact_index(run_id)`.
- Build updates with `format_artifact_key(stage.name, output_name)`.
- Merge with `merge_artifact_index(existing, updates, replace=True)`.
- `replace=True` is required for same-run-directory reruns of a stage whose own outputs are refreshed.
- Do not replace keys for outputs not declared by the current stage.
- Write the merged index before `StageStatus.SUCCEEDED`.

For `REUSE`, do not rewrite stage outputs or stage status. It is acceptable to repair missing same-ref artifact index entries only if `merge_artifact_index(..., replace=False)` succeeds; a conflict must fail the run instead of silently changing reuse policy.

### Failure Behavior

Failure ordering is mandatory:

1. Build `ExecutionFailure`.
2. Write traceback/logs when available.
3. Write `failure.json` through `RunStore.write_stage_failure(..., attempt=attempt)`.
4. Write `StageStatus.FAILED` through `RunStore.write_stage_status()`.
5. Write root `RunStatus.FAILED`.
6. Do not execute downstream stages in the same run.

Stage exceptions, target construction failures, output validation failures, unrebindable pending inputs, executor infrastructure errors, and store commit failures all leave inspectable run state. If a store commit fails before `failure.json` can be written, raise `PipelineExecutionError` and still attempt root `RunStatus.FAILED` if the run store is usable.

Keyboard interruption handling, cancellation, stale `RUNNING` recovery, and richer interrupted-run semantics are Phase 10 or later unless needed to satisfy the basic failure persistence tests.

## In Scope

- Local serial in-process runner and executor only.
- Execution result/request dataclasses and stable public exports.
- Store-backed `StageContext` output helpers.
- Lifecycle helpers and status ordering.
- Config snapshot and provenance persistence needed by local Python API tests.
- Stage target import/construction with no constructor kwargs.
- Same-run-directory resume through `open_existing=True` and Phase 8 `ResumeOptions`.
- Rebinding pending upstream inputs after earlier `RUN` stages commit outputs.
- Output validation against declared output specs and artifact-store validation.
- Package, unit, contract, integration, and e2e tests for the local execution path.

## Out Of Scope

- Functional CLI commands or CLI selector aliases.
- Subprocess, SLURM, distributed, container, or remote execution backend.
- Parallel local scheduling, retries, timeout enforcement, cancellation protocol, distributed locks, or continue-on-failure policy.
- Remote stores, run catalogs, global cache indexes, cross-run cache reuse, or content-addressed cache.
- Stage-target constructor kwargs, dynamic DAG mutation, conditional execution, runtime profile interpretation, scheduler-specific resources, or executor registry.
- Context-collected outputs as an alternate success path.
- Domain-specific stages, codecs, resources, metrics, datasets, models, reports, or checkpoint semantics.
- Phase 10 docs/hardening work except for the minimum error context needed to pass Phase 9 tests.

## Assumptions

- Phase 8 remains the correct stack base until the managing agent records that Phase 8 has landed on `develop`.
- Same-run-directory resume is the only v0 reuse mode.
- A fresh run creates a new run directory through `RunStore.create_run()`. A resume rerun opens the same run through `RunStore.open_run()` with `RunRequest.open_existing=True`.
- The runner may render resolved/redacted config snapshots as pretty JSON text in YAML-named files because JSON is valid YAML and no generic YAML dump helper exists.
- Stage targets are trusted project code. Import sandboxing and allow lists remain deferred.
- `StageContext` helper methods return `ArtifactRef`s that the stage includes in its returned mapping; context-owned output collection remains deferred.
- Store writes are atomic at the file level through Phase 7 helpers, but no run-level lock manager exists in v0.
- Local execution is serial and stop-on-first-failure.
- `StageSpec.resources` remain opaque metadata. Phase 9 may preserve them in request/result metadata but must not interpret them.

## Debt Introduced

| Debt | Reason accepted | Revisit trigger |
| --- | --- | --- |
| Local in-process executor is the only v0 backend | Required to keep the first runnable path reviewable and domain-neutral. | A later implementation plan adds subprocess, SLURM, container, or distributed execution. |
| Stop-on-first-failure only | Simplifies lifecycle, status, and artifact index semantics for v0. | Users need independent-branch continuation or retry policy and the state model is stable. |
| No run-level lock manager | Phase 7 accepted atomic writes without locks. | Tests or real usage expose concurrent writer or interrupted-run races that file atomicity cannot address. |
| Latest-attempt state overwrites earlier attempt files | Phase 7 stores latest inputs/outputs/fingerprints/failures. | Users need attempt history or retry audit trails. |
| Pretty JSON persisted in YAML-named resolved snapshot files | Avoids adding a YAML dump helper or new dependency surface in Phase 9; JSON is valid YAML. | A docs or replay feature requires stylistically YAML-authored resolved snapshots. |
| Optional raw/overlay/CLI snapshot persistence depends on supplied text | `ComposedConfig` exposes resolved/redacted data and provenance, not necessarily original rendered snapshots. | PR review or docs require complete replayable source snapshot files from only a `ComposedConfig`. |
| Minimal stdout/stderr capture policy | In-process capture can surprise user libraries; failure metadata and predictable log paths matter first. | CLI or local debugging needs stable captured stream defaults. |

## Design Impact

- Maintainability: separates executor invocation, lifecycle, output validation, and runner orchestration so local execution does not duplicate planning, store, or config behavior.
- Extensibility: `Executor`, `StageExecutionRequest`, and `StageExecutionResult` leave room for subprocess, SLURM, and container executors without changing the stage protocol or planner policy.
- Domain neutrality: execution only sees stage names, target paths, configs, artifact refs, output specs, statuses, and provenance. It must not inspect datasets, model checkpoints, metrics, reports, or other project-specific artifacts.
- Source-tree boundaries: implementation stays under `src/loom/pipeline/execution`, `src/loom/pipeline/executors`, focused updates to `src/loom/pipeline/context.py` and `src/loom/pipeline/__init__.py`, and tests. It may import pipeline specs/graph/status/planning, store protocols, artifacts, provenance capture helpers, serialization, timestamps, and narrow target-import helpers. It must not import CLI behavior, remote stores, downstream project modules, subprocess/SLURM/container modules, or post-v0 executor code.

## Future Compatibility

- Keep executor request/result models backend-neutral enough for subprocess and SLURM executors to reuse later.
- Keep `StageContext` helpers backed by store protocols rather than `LocalArtifactStore` specifics.
- Record executor metadata under nested `executor_metadata` so future backend-specific fields do not reshape core status or failure records.
- Preserve `PlanAction.REUSE` as a plan/result concept rather than adding persisted `REUSE` status.
- Keep selector/resume options as Phase 8 model inputs so future CLI commands can call the same runner API.
- Keep run-state documents inspectable as plain JSON/YAML/text and compatible with the Phase 7 layout.
- Defer executor registries until more than one backend exists.

## Alternatives Rejected

| Alternative | Reason rejected |
| --- | --- |
| Implement runner logic in the CLI first | v0 explicitly defers functional CLI behavior, and lifecycle logic must be reusable by Python callers and future CLI code. |
| Let `LocalExecutor` write statuses and outputs directly | The runner must own lifecycle ordering so all backends share the same success/failure semantics. |
| Re-plan from scratch after every upstream stage | Phase 8 owns planning policy; Phase 9 only binds produced inputs and computes final fingerprints for pending downstream stages. |
| Rewrite `plan.json` after rebinding | The initial plan remains the planner explanation; committed `fingerprint.json` and `inputs.json` record final execution inputs. |
| Treat `REUSE` as `SKIPPED` in persisted stage status | The v0 plan reserves `SKIP`/`SKIPPED` for selector exclusion and requires reused stages to retain prior `SUCCEEDED` state. |
| Accept context-collected outputs without direct returns | The v0 stage contract is `stage.run(context, inputs) -> Mapping[str, ArtifactRef]`; context-collected output sets are post-v0. |
| Add stage constructor kwargs | The implementation plan explicitly defers constructor kwargs; stage runtime config belongs in `StageContext.stage_config`. |
| Add subprocess or parallel execution now | The phase target is serial local in-process execution; broader backends need stable lifecycle semantics first. |

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
  - integration and e2e tests under `tests/integration/pipeline/` and `tests/e2e/`
- Scope-control checks:
  - no root `loom.__init__` runner/export growth;
  - no functional CLI commands;
  - no new runtime dependencies;
  - no subprocess/SLURM/container backend;
  - no remote stores or cross-run cache behavior;
  - no domain-specific stages or artifact semantics;
  - no planner resume-policy duplication.

## Implementation Steps

1. Add execution and executor error modules with the exact class names in this plan and package exports.
2. Add `execution.models` with `ConfigSnapshotInputs`, `FailurePolicy`, `RunRequest`, `ExecutionFailure`, `StageExecutionRequest`, `StageExecutionResult`, `StageRunResult`, and `RunResult`.
3. Add `Executor` protocol and `LocalExecutor` with in-process `stage.run(context, inputs)` invocation and exception-to-result conversion.
4. Extend `StageContext` with defaulted `run_store`, `artifact_store`, `output_specs`, and the exact helper methods `output_path`, `save_artifact`, and `register_artifact`.
5. Add lifecycle helpers for attempts and stage/root status writes with required ordering.
6. Add logs helpers for stdout/stderr path handling and `traceback.txt` writes without widening the `RunStore` protocol.
7. Add `validate_stage_outputs()` with exact output-spec and artifact-store validation.
8. Add `PipelineRunner` create/open, config/provenance persistence, target construction, planning, serial action handling, pending input rebinding, final fingerprint persistence, output commits, artifact index updates, stage provenance, failure handling, and final run result/status.
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
- Required assertions:
  - `loom.pipeline.execution.__all__` and `loom.pipeline.executors.__all__` match the refined public contract.
  - `PipelineRunner`, `RunRequest`, and `RunResult` are importable from `loom.pipeline`.
  - Root `import loom` remains cheap and does not import config composition, pipeline execution, executors, CLI, local stores, or project code.
  - Importing `loom.pipeline.execution` does not import `loom.cli`, project packages, subprocess/SLURM/container modules, or remote-store code.
  - Deferred CLI modules remain import-safe stubs.

### Unit Suite

- Status: required.
- Expected paths:
  - `tests/unit/loom/pipeline/execution/test_models.py`
  - `tests/unit/loom/pipeline/execution/test_lifecycle.py`
  - `tests/unit/loom/pipeline/execution/test_logs.py`
  - `tests/unit/loom/pipeline/execution/test_outputs.py`
  - `tests/unit/loom/pipeline/execution/test_runner.py`
  - `tests/unit/loom/pipeline/execution/test_execution_errors.py`
  - `tests/unit/loom/pipeline/executors/test_local.py`
  - update `tests/unit/loom/pipeline/test_context.py`
- Required assertions:
  - Execution models validate field types, reject unsupported failure policy, and serialize persisted failure/result fields as plain data.
  - Lifecycle helpers compute attempts from prior status and write failure before failed status and outputs/index/provenance before succeeded status.
  - Log helpers write `traceback.txt` and honor stdout/stderr paths without widening the existing run-store log stream validation.
  - Output validation rejects missing, extra, non-`ArtifactRef`, wrong-type, wrong-codec, wrong-schema, wrong-producer, missing-file, and checksum-mismatched outputs with stage-aware messages.
  - `LocalExecutor` returns success for a dummy stage and structured failure for an exception without making lifecycle decisions.
  - `StageContext` helpers allocate under the stage artifact area, save/register artifacts through store protocols, reject unsafe output names/suffixes, require runtime stores when used, and do not collect implicit outputs.
  - `PipelineRunner` unit tests cover `RUN`, `REUSE`, `SKIP`, `BLOCKED`, unexpected `STALE`, target construction failure, output validation failure, and unrebindable pending input behavior with fakes or temporary stores.

### Contract Suite

- Status: required.
- Expected paths:
  - `tests/contracts/test_executor_contract.py`
  - update `tests/contracts/test_stage_contract.py` only if context helper additions require additional structural-stage assertions.
- Required assertions:
  - Downstream executor implementations can satisfy the public `Executor` protocol structurally.
  - `LocalExecutor` satisfies the shared executor contract for successful stage output mappings and exception-to-failure conversion.
  - Existing stage and store contracts remain valid after context/execution additions.

### Integration Suite

- Status: required.
- Expected paths:
  - `tests/integration/pipeline/test_local_execution.py`
  - `tests/integration/pipeline/test_local_execution_resume.py`
  - `tests/integration/pipeline/test_local_execution_failures.py`
- Required assertions:
  - `PipelineRunner` collaborates with `LocalRunStore`, `LocalArtifactStore`, Phase 8 planning, and dummy trusted stage targets over temporary run directories.
  - Successful runs write `run.json`, `status.json`, `plan.json`, config snapshots, recipe manifest when present, provenance documents, stage status/input/output/fingerprint/provenance files, logs where applicable, artifacts, and `artifacts.json`.
  - Same-run rerun with `open_existing=True` reuses unchanged stages without invoking their executor and without changing prior `SUCCEEDED` stage status to `SKIPPED`.
  - Changed stage config or upstream artifacts rerun changed stages and downstream dependents.
  - Selector `skip_stages`, `only_stages`, `from_stage`, and `force_stages` behavior is reflected through the runner using the Phase 8 planner.
  - Stage construction, invalid outputs, artifact validation failures, and stage exceptions leave inspectable failure state and failed run status.

### E2E Suite

- Status: required.
- Expected paths:
  - `tests/e2e/test_local_pipeline_run.py`
- Required assertions:
  - Compose a synthetic YAML config, run it through public Python config and runner APIs, and assert the run directory contains expected config, plan, status, input, output, fingerprint, artifact, provenance, and index files.
  - Rerun the same run directory with `open_existing=True` and assert valid unchanged stages produce `REUSE` plan decisions without executor invocation.
  - Modify config or an upstream artifact and assert affected stages rerun while unaffected reusable stages are preserved.
  - Inject a dummy stage failure and assert `failure.json` is written before failed status and downstream stages are not executed.

### Opt-In Suites

- Status: deferred.
- Markers affected: `slow`, `network`, `slurm`, `optional_dependency`.
- Deferral reason: Phase 9 is local, deterministic, and covered by default suites. It must not require network services, SLURM, remote stores, optional dependencies outside the default dev environment, or slow acceptance tests.

## Risks

- The runner may accidentally duplicate planner policy when rebinding pending downstream inputs. It should only bind produced outputs, recompute final fingerprints, and use Phase 8 plan/action semantics.
- Output validation and lifecycle ordering are easy to get subtly wrong. Tests must assert persisted files and statuses in the order required by this plan.
- `StageContext` helper additions can break existing minimal context tests if defaults and plain-data validation are not preserved.
- Config snapshot persistence is intentionally limited for raw/overlay/override source text; callers must supply those strings if they want those files.
- `BLOCKED` plan actions have no persisted stage status. Tests must protect the decision to fail the run without inventing a blocked status.
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

This refine pass intentionally did not run those implementation checks because it changed only the phase execution plan.

## Handoff Notes For `loom_phase_executor`

- Safe implementation slices:
  - execution/executor errors and models;
  - `Executor` protocol and `LocalExecutor`;
  - `StageContext` store-backed helpers;
  - lifecycle/status/failure helpers;
  - log/traceback helpers;
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
  - `BLOCKED` is not a persisted stage status;
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

- Draft phase execution plan: complete.
- Plan refine pass: complete.
- Phase implementation refinement: unused.
- PR review: unused.
- PR body draft/refine: unused.

## Completion Notes

- Draft plan: completed by `loom_phase_planner` on `codex/add-local-execution`.
- Refined phase execution plan: completed; exact API names, dataclass fields, result/status semantics, `StageContext` helper signatures, runner input contract, lifecycle ordering, output validation behavior, plan/rebind behavior, failure behavior, and suite-level test obligations are locked above.
- Implementation summary: pending.
- Implementation validation: pending.
- Refinement summary: pending implementation refinement pass.
- PR preparation: pending.
- Stack maintenance: pending Phase 7 and Phase 8 merge/rebase/retarget state.
- Remaining blockers: none.
