# Phase 6 Execution Plan: Pipeline Specs And Graph

## Metadata

- Status: refined phase execution plan
- Branch: `codex/add-pipeline-specs-graph`
- Worktree: `/home/samcantrill/work/loom-worktrees/add-pipeline-specs-graph`
- Phase execution plan path: `docs/phases/add-pipeline-specs-graph.md`
- Full plan: `docs/implementation-plans/implementation-plan-v0.md`
- Source phase: `Phase 6 - Pipeline Specs And Graph`
- Stack predecessor: `codex/add-recipes-instantiation`
- Base branch: `codex/add-recipes-instantiation` at `7ede758210f75c8a448b922af4c6034e7619bddb`
- Target branch: `codex/add-recipes-instantiation`
- Merge eligibility: stacked PR is reviewable against `codex/add-recipes-instantiation`; not merge-eligible until Phase 5 lands and Phase 6 is retargeted or rebased onto `develop`.
- Successor dependency notes: no known successor branch depends on Phase 6 yet. Keep the Phase 6 branch until any later stacked successor has been retargeted or rebased away from it.
- Plan quality gate: passed on 2026-05-03 by `loom_plan_reviewer` confirmation review; no remaining blockers are recorded in the canonical v0 plan.
- Plan quality gate loop budget: initial plan review used, automated plan refinement pass used, confirmation review used. Do not rerun the plan-quality gate for this phase.
- Draft pass: completed by `loom_phase_planner`; draft commit `fee127460ad171cc364485169575916a7acdcdee`.
- Refine pass: completed by `loom_phase_planner` on 2026-05-03.
- Setup limitations: `gh auth status` reported an invalid configured `samcantrill` token during the draft pass, so remote synchronization was unavailable. This refine pass performed no remote operations by assignment. The worktree was created from the local recorded predecessor branch.
- Blockers: none for local phase implementation.

## Objective

Implement the static pipeline model before any persistent state or execution side effects exist. This phase defines frozen pipeline, stage, and output specs; the structural stage contract and minimal stage context; stage/run status values and serializable in-memory status records; strict `stage.output` input binding helpers; and pure graph validation/traversal helpers.

The executor must turn resolved config pipeline shapes into validated static specs while keeping target instantiation, stage execution, artifact path allocation, run stores, resume planning, CLI behavior, and runner semantics out of scope.

## Full-Plan Context

Phases 1 through 5 established the import-safe package skeleton, primitives, serialization, I/O, config composition, recipes, and trusted `_target_` instantiation helpers. Phase 6 consumes resolved config data but does not instantiate stage targets and does not write run state.

Later phases depend on this static contract:

- Phase 7 adds local run/artifact stores and persisted run layout.
- Phase 8 adds planning and same-run-directory resume decisions.
- Phase 9 wires local in-process execution, stage target construction, context helpers, status writes, and output validation.
- Phase 10 hardens error messages across subsystems.

Future-phase work that must remain out of scope includes persistent stores, stage target construction, runner lifecycle, selectors, resume decisions, artifact save/register helpers, output path allocation, config persistence, CLI commands, remote stores, subprocess/SLURM execution, runtime profiles, retry policies, conditional `when` logic, and any domain-specific stage behavior.

## Stack Context

- Root or stacked phase: stacked phase.
- Current predecessor branch or PR: `codex/add-recipes-instantiation`, recorded locally as Phase 5 `pr_open` with PR https://github.com/samcantrill/loom/pull/8.
- Why this base branch is correct: Phase 5 is the nearest earlier unmerged phase and includes the committed config recipe/instantiation work that Phase 6 should build on.
- Retarget/rebase plan after predecessor merge: once Phase 5 lands, rebase or replay `codex/add-pipeline-specs-graph` onto updated `develop`, retarget the Phase 6 PR to `develop`, rerun validation, and record the stack maintenance in this artifact or PR body.
- Branch cleanup constraints: do not delete `codex/add-recipes-instantiation` until Phase 6 is rebased or retargeted away from it; do not delete `codex/add-pipeline-specs-graph` while any later successor branch depends on it.

## Source Phase Summary

- Goal: implement the static pipeline model, stage contract, status types, and pure graph validation before persistent stores and execution.
- Required scope:
  - Add `OutputSpec`, `StageSpec`, and `PipelineSpec` frozen dataclasses.
  - Add the `Stage` structural protocol and minimal `StageContext`.
  - Add stage/run status values and serializable status records.
  - Parse documented pipeline, stage, and output shapes from resolved config.
  - Support strict `stage.output` input references.
  - Distinguish data dependencies from control-only `depends_on`.
  - Build graph helpers for dependencies, cycle detection, upstream/downstream sets, and topological sorting.
  - Reject unknown and deferred orchestration fields with clear errors.
- Required checkpoints:
  - Preserve authored stage order in specs while validating execution order through graph helpers.
  - Store stage `_target_` as `target_path`; store authored `config` as `stage_config`.
  - Keep `StageContext` minimal: IDs, paths, resolved config, stage config, provenance, and metadata.
  - Keep resources as opaque plain-data-compatible metadata.
  - Keep status modeling serializable and minimal until store and runner phases prove more states are needed.
- Acceptance criteria:
  - Documented inline stage YAML shape parses correctly.
  - Unknown stage-level orchestration keys are rejected.
  - Deferred fields such as stage `runtime`, `retry`, `when`, stage metadata, and output `path` fail clearly.
  - Duplicate stages, missing outputs, bad output specs, bad refs, unknown stages, unknown outputs, cycles, and self-dependencies fail clearly.
  - Topological sort works for linear, branching, and diamond DAGs.
  - Dummy stages satisfy the stage protocol without inheritance.
- Source references: `docs/implementation-plans/implementation-plan-v0.md` Phase 6; `docs/features/pipeline.md` sections 8 through 11 and graph guidance; `docs/features/pipeline-graph.md`; `docs/features/state.md` sections 6 through 8; `docs/features/testing.md`; `docs/structure.md`.

## Current Source And Harness Findings

- `src/loom/pipeline/__init__.py`, `src/loom/pipeline/graph/__init__.py`, `src/loom/pipeline/planning/__init__.py`, `src/loom/pipeline/execution/__init__.py`, `src/loom/pipeline/executors/__init__.py`, and `src/loom/pipeline/stores/__init__.py` are import-safe skeletons.
- `src/loom/errors.py` already exposes broad `PipelineError`, `ValidationError`, and `ContractError`. Phase 6 should add pipeline-specific errors without breaking the broad root error hierarchy.
- `src/loom/artifacts.py` provides `ArtifactRef`, which the stage protocol can reference without pulling in stores or execution.
- `src/loom/serialization/plain.py` provides `PlainData`, `ensure_plain_data`, and `to_plain_data`; Phase 6 must reuse these for spec/status metadata, resources, stage config, context config, and status owner metadata.
- `src/loom/ids.py` already defines simple string aliases for `RunID`, `StageID`, `ArtifactType`, and `CodecKey`.
- `src/loom/timestamps.py` provides `parse_timestamp`; status record deserialization must reuse it to validate non-null timestamp strings.
- `src/loom/protocols.py` contains package-wide generic protocols only. The `Stage` protocol belongs under `loom.pipeline.stage`, not in `loom.protocols`.
- Package import-boundary tests assert that `import loom` does not import `loom.pipeline`, `loom.config`, or `loom.cli`. Phase 6 must preserve that root import behavior and must not add pipeline exports to `loom.__init__`.
- Existing tests have package, unit, contract, and integration suites. There is no `tests/e2e` directory yet, and opt-in external suites are not part of the current harness.

## In-Scope Work

- Add `src/loom/pipeline/errors.py` with pipeline-specific errors:
  - `PipelineValidationError(PipelineError, ValidationError)`
  - `PipelineSpecError(PipelineValidationError)`
  - `InputBindingError(PipelineValidationError)`
  - `PipelineGraphError(PipelineValidationError)`
  - `PipelineCycleError(PipelineGraphError)`
  - `StageContractError(PipelineError, ContractError)`
  - `StatusSerializationError(PipelineValidationError)`
- Add `OutputSpec`, `StageSpec`, and `PipelineSpec` in `loom.pipeline.specs` with strict construction from the resolved `pipeline` mapping.
- Add `parse_pipeline_config(config: object) -> PipelineSpec` in `loom.pipeline.specs` as the public standalone parser; it must delegate to `PipelineSpec.from_config(config)`.
- Add `Stage` in `loom.pipeline.stage` as a `@runtime_checkable` structural protocol with `run(context, inputs)`.
- Add `StageContext` in `loom.pipeline.context` as the minimal frozen value shape.
- Add `RunStatus`, `StageStatus`, `RunStatusRecord`, `StageStatusRecord`, and status parse/serialization helpers in `loom.pipeline.status`.
- Add binding helpers in `loom.pipeline.graph.bindings` for strict `stage.output` references and resolved input binding records.
- Add graph representation and helpers in `loom.pipeline.graph.dag` and `loom.pipeline.graph.topology` for dependency graph construction, cycle detection, upstream/downstream queries, and deterministic topological sorting.
- Export Phase 6 API symbols from `loom.pipeline` and `loom.pipeline.graph`; do not export them from root `loom`.
- Add package, unit, contract, and integration coverage for the static pipeline model and graph behavior.

## Out-of-Scope Work

- No persistent stores, run directory layout implementation, config persistence, status file I/O, or artifact path allocation.
- No resume planning, stale/reuse decisions, selector handling, or same-run-directory cache behavior.
- No stage target import/instantiation policy for pipelines, no target constructor calls, and no use of Phase 5 generic `instantiate()` to build stages.
- No stage execution, runner behavior, executor behavior, preflight command, CLI behavior, PR body creation, or GitHub operations.
- No store-backed `StageContext` helpers such as `artifact_store`, `run_store`, `output_path`, `artifact_path`, `save_artifact`, or `register_artifact`.
- No runtime profiles, retry behavior, conditional `when`, stage-level metadata, output paths, optional outputs, external input specs, literal pipeline inputs, dynamic DAG mutation, graph visualization, or domain-specific stages.
- No changes to top-level `loom.__init__` public exports.

## Assumptions

- The local predecessor branch at `7ede758210f75c8a448b922af4c6034e7619bddb` is the correct Phase 6 base because remote synchronization was unavailable and the manager supplied that stack state.
- `PipelineSpec.from_config()` receives the `pipeline` mapping from an already resolved config, such as `composed.resolved["pipeline"]`, not a file path, raw YAML text, or the root resolved config object.
- Resolved config is trusted project config, but Phase 6 still validates the pipeline schema strictly so future execution phases receive a stable contract.
- Stage names, output names, and input names use the same v0 identifier rule: non-empty strings with no `.`, `/`, `\`, control characters, `.` value, or `..` value. Rejecting dots keeps compact `stage.output` references unambiguous.
- `depends_on` creates control edges only; input bindings create data edges and resolved artifact binding records.
- Stage `resources`, pipeline metadata, output metadata, status metadata, owner metadata, context metadata, resolved config, and stage config must be plain-data-compatible.
- Status transition helpers are not part of this phase. The runner and stores own lifecycle transition policy in later phases.

## Decision-Complete Contract

Phase 6 owns the public static pipeline contract exposed through `loom.pipeline` and `loom.pipeline.graph`. The executor must implement the names and data shapes below rather than redesigning them into runtime behavior.

### Module Boundaries

- `loom.pipeline.errors`: pipeline-specific exceptions listed in the in-scope section.
- `loom.pipeline.specs`: `OutputSpec`, `StageSpec`, `PipelineSpec`, `parse_pipeline_config`, and private validation helpers.
- `loom.pipeline.stage`: `Stage` structural protocol.
- `loom.pipeline.context`: `StageContext`.
- `loom.pipeline.status`: `RunStatus`, `StageStatus`, status records, and parse/serialization helpers.
- `loom.pipeline.graph.bindings`: `ArtifactReference`, `ResolvedInputBinding`, `parse_artifact_reference`, `bind_stage_inputs`, and `resolve_input_bindings`.
- `loom.pipeline.graph.dag`: `StageEdgeReason`, `StageNode`, `StageEdge`, `StageGraph`, graph construction, and graph query helpers.
- `loom.pipeline.graph.topology`: `detect_cycles` and `topological_sort`.
- Existing `loom.pipeline.planning`, `loom.pipeline.execution`, `loom.pipeline.executors`, and `loom.pipeline.stores` skeletons stay untouched except for import-boundary fallout if tests expose a real issue. They must not gain product behavior in this phase.

### Spec Dataclasses And Parser API

Implement these dataclasses as `@dataclass(frozen=True, slots=True)`. Normalize sequences to tuples and plain mapping fields to fresh plain-data `dict` values during construction.

```python
class OutputSpec:
    artifact_type: ArtifactType
    codec_key: CodecKey | None = None
    schema_version: int | None = None
    metadata: Mapping[str, PlainData] = field(default_factory=dict)

    @classmethod
    def from_config(cls, config: object, *, path: str = "$.output") -> "OutputSpec": ...

class StageSpec:
    name: StageID
    target_path: str
    outputs: Mapping[str, OutputSpec]
    stage_config: Mapping[str, PlainData] = field(default_factory=dict)
    dependencies: tuple[StageID, ...] = field(default_factory=tuple)
    inputs: Mapping[str, str] = field(default_factory=dict)
    resources: Mapping[str, PlainData] = field(default_factory=dict)

    @classmethod
    def from_config(cls, config: object, *, path: str = "$.stage") -> "StageSpec": ...

class PipelineSpec:
    stages: tuple[StageSpec, ...]
    name: str | None = None
    description: str | None = None
    metadata: Mapping[str, PlainData] = field(default_factory=dict)
    schema_version: int | None = None

    @classmethod
    def from_config(cls, config: object, *, path: str = "$.pipeline") -> "PipelineSpec": ...

    @property
    def stage_names(self) -> tuple[StageID, ...]: ...

    def get_stage(self, stage_id: StageID) -> StageSpec: ...
```

`StageSpec.outputs` and `PipelineSpec.stages` are required and must be non-empty. `PipelineSpec.get_stage()` raises `PipelineSpecError` with the unknown stage name when no stage exists.

Use `parse_pipeline_config(config: object) -> PipelineSpec` as the public function name for callers that prefer a function API. Do not add generic spec `to_dict()`/`from_dict()` methods in Phase 6; config parsing is the only spec serialization boundary needed before stores exist.

### Config Parsing Rules

- Pipeline mappings support only `stages`, optional `name`, optional `description`, optional `metadata`, and optional `schema_version`.
- Pipeline `schema_version` and output `schema_version` default to `None`; if supplied they must be positive integers and not bools.
- Authored pipeline `defaults` fails with a deferred-field message. Any other unknown pipeline key fails with an unknown-field message.
- Stage mappings support only `name`, `_target_`, `config`, `depends_on`, `inputs`, `outputs`, and `resources`.
- Stage `name`, `_target_`, and non-empty `outputs` are required.
- Stage `config` defaults to `{}` and becomes `stage_config`.
- Stage `depends_on` defaults to `()`, must be a sequence of stage identifiers when supplied, and must not be a bare string.
- Stage `inputs` defaults to `{}` and must be a mapping of input name to strict `stage.output` string reference.
- Stage `resources` defaults to `{}` and must be a plain-data-compatible mapping.
- Unknown stage-level keys fail clearly. Deferred stage fields `runtime`, `retry`, `when`, and `metadata` fail with explicit deferred-field messages.
- Output spec mappings support only required `artifact_type`, optional `codec_key`, optional `schema_version`, and optional `metadata`.
- Output `artifact_type` must be a non-empty string. `codec_key` must be `None` or a non-empty string.
- Authored output `path` and `required` fail as deferred fields. Any other unknown output key fails clearly.
- String shorthand output specs are not supported; every output must use the documented mapping shape with `artifact_type`.

Implement these private helper names in `loom.pipeline.specs`:

- `_require_mapping(value: object, *, path: str) -> Mapping[str, object]`
- `_reject_unknown_fields(data: Mapping[str, object], *, allowed: set[str], deferred: set[str], path: str) -> None`
- `_require_non_empty_string(value: object, *, path: str) -> str`
- `_optional_string(value: object, *, path: str) -> str | None`
- `_optional_schema_version(value: object, *, path: str) -> int | None`
- `_validate_identifier(value: str, *, kind: str, path: str) -> str`
- `_plain_mapping(value: object, *, path: str) -> dict[str, PlainData]`
- `_parse_dependencies(value: object, *, stage_name: StageID, path: str) -> tuple[StageID, ...]`
- `_parse_inputs(value: object, *, stage_name: StageID, path: str) -> dict[str, str]`
- `_parse_outputs(value: object, *, stage_name: StageID, path: str) -> dict[str, OutputSpec]`

All validation errors should include enough path context to identify the pipeline, stage, input, output, or field that failed.

### Stage Protocol And Context

Implement `Stage` as:

```python
@runtime_checkable
class Stage(Protocol):
    def run(
        self,
        context: StageContext,
        inputs: Mapping[str, ArtifactRef],
    ) -> Mapping[str, ArtifactRef]: ...
```

Implement `StageContext` as:

```python
@dataclass(frozen=True, slots=True)
class StageContext:
    run_id: RunID
    stage_name: StageID
    run_dir: Path
    stage_dir: Path
    resolved_config: Mapping[str, PlainData]
    stage_config: Mapping[str, PlainData]
    provenance: Mapping[str, PlainData] = field(default_factory=dict)
    metadata: Mapping[str, PlainData] = field(default_factory=dict)
```

`StageContext.__post_init__` should validate non-empty `run_id` and `stage_name`, coerce `run_dir` and `stage_dir` with `Path(...)`, and normalize mapping fields through `ensure_plain_data`. It must not expose stores, loggers, artifact paths, save/register helpers, or execution methods.

### Status Values And Serialization

Use `enum.StrEnum`, not raw string constants, for status values. `StrEnum` gives typed comparisons while preserving simple string values for JSON-compatible serialization.

```python
class RunStatus(StrEnum):
    CREATED = "CREATED"
    PLANNED = "PLANNED"
    RUNNING = "RUNNING"
    SUCCEEDED = "SUCCEEDED"
    FAILED = "FAILED"
    CANCELLED = "CANCELLED"
    INTERRUPTED = "INTERRUPTED"

class StageStatus(StrEnum):
    PENDING = "PENDING"
    RUNNING = "RUNNING"
    SUCCEEDED = "SUCCEEDED"
    FAILED = "FAILED"
    SKIPPED = "SKIPPED"
    STALE = "STALE"
    CANCELLED = "CANCELLED"
```

Implement `STATUS_SCHEMA_VERSION = 1`.

```python
@dataclass(frozen=True, slots=True)
class RunStatusRecord:
    run_id: RunID
    status: RunStatus
    created_at: str
    updated_at: str
    schema_version: int = STATUS_SCHEMA_VERSION
    started_at: str | None = None
    finished_at: str | None = None
    message: str | None = None
    metadata: Mapping[str, PlainData] = field(default_factory=dict)

    def to_dict(self) -> dict[str, PlainData]: ...

    @classmethod
    def from_dict(cls, data: object) -> "RunStatusRecord": ...

@dataclass(frozen=True, slots=True)
class StageStatusRecord:
    run_id: RunID
    stage_name: StageID
    status: StageStatus
    attempt: int
    updated_at: str
    schema_version: int = STATUS_SCHEMA_VERSION
    started_at: str | None = None
    finished_at: str | None = None
    message: str | None = None
    owner: Mapping[str, PlainData] = field(default_factory=dict)
    metadata: Mapping[str, PlainData] = field(default_factory=dict)

    def to_dict(self) -> dict[str, PlainData]: ...

    @classmethod
    def from_dict(cls, data: object) -> "StageStatusRecord": ...
```

Status helper names are:

- `parse_run_status(value: object) -> RunStatus`
- `parse_stage_status(value: object) -> StageStatus`
- private `_validate_timestamp_or_none(value: object, *, field: str) -> str | None`
- private `_validate_timestamp(value: object, *, field: str) -> str`
- private `_validate_status_schema_version(value: object) -> int`

`from_dict()` methods must reject unknown fields, missing required fields, invalid enum values, invalid schema versions, invalid timestamps, non-string messages, non-positive stage attempts, and non-plain metadata/owner mappings with `StatusSerializationError`. Status helpers must not read or write files and must not implement lifecycle transitions.

### Binding Data Shape

Implement binding helpers under `loom.pipeline.graph.bindings`:

```python
@dataclass(frozen=True, slots=True)
class ArtifactReference:
    stage_id: StageID
    output_name: str

@dataclass(frozen=True, slots=True)
class ResolvedInputBinding:
    consumer_stage_id: StageID
    input_name: str
    source_stage_id: StageID
    source_output_name: str
    source_output_spec: OutputSpec

def parse_artifact_reference(value: str) -> ArtifactReference: ...
def bind_stage_inputs(stage_id: StageID, spec: PipelineSpec) -> Mapping[str, ResolvedInputBinding]: ...
def resolve_input_bindings(spec: PipelineSpec) -> Mapping[StageID, Mapping[str, ResolvedInputBinding]]: ...
```

`parse_artifact_reference()` is syntactic only: it accepts exactly one dot separator, rejects empty parts, and does not check whether the source stage or output exists. `bind_stage_inputs()` performs semantic validation against `PipelineSpec`, raises `InputBindingError` for unknown consumer stages, unknown source stages, unknown source outputs, bad references, or self-inputs, and returns bindings keyed by input name. `resolve_input_bindings()` returns every stage name from the spec, including stages with empty input mappings.

### Graph Edge Representation And Helpers

Use `StrEnum` for graph edge reasons as well:

```python
class StageEdgeReason(StrEnum):
    DATA = "data"
    CONTROL = "control"

@dataclass(frozen=True, slots=True)
class StageNode:
    stage_id: StageID
    order: int

@dataclass(frozen=True, slots=True)
class StageEdge:
    upstream_stage_id: StageID
    downstream_stage_id: StageID
    reason: StageEdgeReason
    input_name: str | None = None
    output_name: str | None = None

@dataclass(frozen=True, slots=True)
class StageGraph:
    nodes: Mapping[StageID, StageNode]
    edges: frozenset[StageEdge]
```

Data edges must set `reason=StageEdgeReason.DATA`, `input_name` to the downstream input, and `output_name` to the upstream output. Control-only edges from `depends_on` must set `reason=StageEdgeReason.CONTROL` and leave `input_name` and `output_name` as `None`. If a data edge and control edge connect the same stages, keep both distinct edges; query helpers treat either as a dependency while diagnostics can still explain both reasons.

Graph helper names are:

- `build_stage_graph(spec: PipelineSpec) -> StageGraph`
- `upstream_of(graph: StageGraph, stage_id: StageID) -> set[StageID]`
- `downstream_of(graph: StageGraph, stage_id: StageID) -> set[StageID]`
- `transitive_upstream(graph: StageGraph, stage_id: StageID) -> set[StageID]`
- `transitive_downstream(graph: StageGraph, stage_id: StageID) -> set[StageID]`
- `detect_cycles(graph: StageGraph) -> list[list[StageID]]`
- `topological_sort(graph: StageGraph) -> list[StageID]`

`build_stage_graph()` must include every stage once, use `resolve_input_bindings()` for data edges, add `depends_on` control edges, reject unknown `depends_on` stages, reject self-dependencies, and raise `PipelineCycleError` when cycles exist. `PipelineCycleError` should expose `cycles: tuple[tuple[StageID, ...], ...]` and include at least one cycle path in the message.

Topological sorting must place upstream stages before downstream stages and use `StageNode.order` from authored stage order as the deterministic ready-node tie-breaker. If a graph was manually constructed without reliable order values, fall back to lexical stage ID order for ties.

### Public Exports

`loom.pipeline.__all__` must expose only Phase 6 static API symbols:

- `OutputSpec`, `StageSpec`, `PipelineSpec`, `parse_pipeline_config`
- `Stage`, `StageContext`
- `RunStatus`, `StageStatus`, `RunStatusRecord`, `StageStatusRecord`, `parse_run_status`, `parse_stage_status`
- `PipelineValidationError`, `PipelineSpecError`, `InputBindingError`, `PipelineGraphError`, `PipelineCycleError`, `StageContractError`, `StatusSerializationError`

`loom.pipeline.graph.__all__` must expose:

- `ArtifactReference`, `ResolvedInputBinding`, `parse_artifact_reference`, `bind_stage_inputs`, `resolve_input_bindings`
- `StageEdgeReason`, `StageNode`, `StageEdge`, `StageGraph`, `build_stage_graph`
- `upstream_of`, `downstream_of`, `transitive_upstream`, `transitive_downstream`, `detect_cycles`, `topological_sort`

Do not add `PipelineRunner`, stores, planning helpers, execution helpers, CLI helpers, or root `loom.__init__` exports in Phase 6.

## Design Impact

- Maintainability: isolates static validation and graph behavior before store and runner code exists, so future execution phases can consume one stable model instead of duplicating ad hoc parsing.
- Extensibility: keeps resources and metadata opaque plain data, keeps graph helpers pure, and leaves room for future richer input specs, runtime profiles, optional outputs, selectors, and visualization without changing the v0 static core.
- Domain neutrality: stages are structural project-code objects; `loom` validates generic names, bindings, artifacts, and statuses but defines no domain stage subclasses or domain artifact types.
- Source-tree boundaries: pipeline model code stays under `src/loom/pipeline`, graph mechanics stay under `src/loom/pipeline/graph`, and root `loom.__init__` remains cheap and free of pipeline imports.

## Future Compatibility

- The parser should fail on deferred fields instead of silently preserving them so future phases can introduce `defaults`, `runtime`, `retry`, `when`, stage metadata, output paths, and optional outputs deliberately.
- Stage resources should be preserved as plain data but not interpreted or included in semantic fingerprints by default; future runtime/resource phases can add typed normalization and explicit fingerprint policy.
- `StageContext` should remain small in Phase 6 and be extendable by Phase 7 and Phase 9 with store-backed helpers without breaking the structural `Stage.run()` signature.
- Graph helpers should be reusable by planning, resume, preflight, CLI inspection, and future visualization without importing those subsystems.
- Status records should be serializable now but avoid persistence assumptions until run-store behavior lands.
- `StrEnum` status and edge reason values preserve human-readable serialized strings while keeping the Python API typed enough for later stores and runners.

## Alternatives Rejected

| Alternative | Reason rejected |
| --- | --- |
| Parse pipeline specs inside `loom.config.compose_config()` | Config composition should remain a generic resolved-config step; Phase 6 should expose an explicit parser so callers decide when to validate pipeline semantics. |
| Accept the root resolved config in `PipelineSpec.from_config()` | The phase contract is the `pipeline` mapping. Accepting multiple roots would blur config ownership and complicate error paths before callers prove a need. |
| Instantiate stage `_target_` values during spec parsing | Stage construction belongs to later runner phases and would mix static graph validation with runtime imports and side effects. |
| Treat authored stage order as execution order | The plan requires explicit DAG validation; authored order is only a deterministic tie-breaker for otherwise-ready stages. |
| Preserve unknown/deferred stage fields as metadata | Silent preservation would make future semantics ambiguous. V0 must reject deferred orchestration keys clearly. |
| Use raw string constants for statuses and edge reasons | `StrEnum` keeps serialized values simple while making the public API harder to typo and easier to type-check. |
| Represent graph edges as only `(upstream, downstream)` pairs | Later planning and diagnostics need to distinguish data bindings from control-only ordering without re-parsing specs. |
| Put `Stage` in `loom.protocols` | The stage contract depends on pipeline context, artifacts, and lifecycle semantics, so it belongs in `loom.pipeline.stage`. |
| Add store-backed context helpers now | Artifact paths, stores, save/register helpers, and run state belong to Phase 7 and Phase 9, not the static model phase. |

## Debt Introduced

| Debt | Reason accepted | Revisit trigger |
| --- | --- | --- |
| Status model remains minimal, transition-free, and file-I/O-free. | Store and runner phases have not proven the exact persistence and transition helper needs yet. | Revisit in Phase 7 and Phase 9 when run-store writes and runner lifecycle use the records. |
| Only compact `stage.output` input references are supported. | V0 needs a strict, reviewable binding contract before richer input specs exist. | Revisit after local execution if literal inputs, external artifacts, or expanded input specs are needed. |
| Stage/output/input names reject dots to keep reference parsing simple. | The compact reference syntax would otherwise be ambiguous. | Revisit before release if downstream stage naming conventions require dots. |
| Spec dataclasses do not provide generic `to_dict()`/`from_dict()` persistence helpers. | Phase 6 parses resolved config only; persistent run layout is Phase 7. | Revisit when local stores persist pipeline specs or plans. |

## Reviewability

- Expected PR size and shape: moderate, with new pure pipeline modules plus focused tests. The PR should be reviewable without following store, runner, CLI, or domain logic.
- Files and areas to inspect:
  - `src/loom/pipeline/__init__.py`
  - `src/loom/pipeline/errors.py`
  - `src/loom/pipeline/specs.py`
  - `src/loom/pipeline/stage.py`
  - `src/loom/pipeline/context.py`
  - `src/loom/pipeline/status.py`
  - `src/loom/pipeline/graph/__init__.py`
  - `src/loom/pipeline/graph/bindings.py`
  - `src/loom/pipeline/graph/dag.py`
  - `src/loom/pipeline/graph/topology.py`
  - package, unit, contract, and integration tests under `tests/`
- Scope-control checks: confirm the diff has no store implementations, runner behavior, stage target imports, CLI behavior, config persistence, broad refactors, domain-specific fixtures, root `loom.__init__` pipeline exports, Phase 7+ helpers, or changes to the recorded stack predecessor/base/target metadata.

## Implementation Steps

1. Add `loom.pipeline.errors` with the exact error hierarchy and export those errors from `loom.pipeline`.
2. Add `loom.pipeline.specs` with exact dataclasses, `from_config()` classmethods, `parse_pipeline_config()`, identifier validation, unknown/deferred field rejection, plain-data normalization, duplicate-stage checks, and missing-output checks.
3. Add `StageContext` and `Stage` exactly as specified, with context validation and no store/runner helpers.
4. Add `RunStatus`, `StageStatus`, status records, `parse_run_status()`, `parse_stage_status()`, and status `to_dict()`/`from_dict()` behavior without filesystem writes or transition helpers.
5. Add binding helpers with `ArtifactReference`, `ResolvedInputBinding`, strict syntactic parsing, and semantic resolution against `PipelineSpec`.
6. Add graph dataclasses and helpers that combine data and control edges, preserve edge reasons, detect cycles/self-dependencies, compute upstream/downstream sets, and perform deterministic topological sorting.
7. Wire explicit public exports through `loom.pipeline` and `loom.pipeline.graph` while preserving root import boundaries.
8. Add phase-scoped package, unit, contract, and integration tests alongside each implementation slice.
9. During implementation, run targeted tests after each slice. Before PR preparation, run `make validate-pr` and `make test-summary` and record evidence in the PR body.

## Test Plan

### Package Suite

- Status: required.
- Expected paths: update `tests/package/test_public_api.py` and `tests/package/test_import_boundaries.py`; add `tests/package/test_pipeline_api.py`.
- Required assertions: `import loom` still does not import `loom.pipeline`; `import loom.pipeline` exposes the Phase 6 static API; `import loom.pipeline.graph` exposes graph and binding helpers; package modules import cleanly; top-level `loom.__init__` remains limited to cheap primitive exports.

### Unit Suite

- Status: required.
- Expected paths:
  - `tests/unit/loom/pipeline/test_specs.py`
  - `tests/unit/loom/pipeline/test_context.py`
  - `tests/unit/loom/pipeline/test_stage.py`
  - `tests/unit/loom/pipeline/test_status.py`
  - `tests/unit/loom/pipeline/test_errors.py`
  - `tests/unit/loom/pipeline/graph/test_bindings.py`
  - `tests/unit/loom/pipeline/graph/test_dag.py`
  - `tests/unit/loom/pipeline/graph/test_topology.py`
- Required assertions: valid inline pipeline/stage/output shapes parse; `PipelineSpec.from_config()` and `parse_pipeline_config()` agree; unknown and deferred fields fail clearly; duplicate stages, bad identifiers, missing targets, missing outputs, missing `artifact_type`, bad output specs, bad refs, unknown stages, unknown outputs, self-dependencies, and cycles fail clearly; resources, config, context mappings, status owner, and metadata require plain data; status records serialize/deserialize with uppercase status strings; topological sort works for single, linear, branching, and diamond DAGs; upstream/downstream helpers return direct and transitive sets; graph edge reasons distinguish data inputs from control dependencies.

### Contract Suite

- Status: required.
- Expected paths: add `tests/contracts/test_stage_contract.py`.
- Required assertions: dummy project stage objects satisfy `Stage` structurally without inheritance; runtime protocol checks do not require subclassing; the required `run(context, inputs)` shape accepts `StageContext` and `Mapping[str, ArtifactRef]` and returns a mapping keyed by declared output names. Stage execution, output validation, and target instantiation remain out of scope.

### Integration Suite

- Status: required.
- Expected paths: add `tests/integration/pipeline/test_pipeline_config.py`.
- Required assertions: a domain-neutral YAML config composed through `compose_config()` can feed `PipelineSpec.from_config(composed.resolved["pipeline"])`; recipe-expanded or override-adjusted resolved config can still produce a static `PipelineSpec`; graph construction works from that spec; parsing does not instantiate stage targets, import project stage modules, write files, or invoke stores/runners.

### E2E Suite

- Status: deferred.
- Expected paths: none in this phase; no `tests/e2e` directory exists yet.
- Required assertions or deferral reason: Phase 6 has no runnable user workflow, CLI command, runner, or run directory behavior. End-to-end coverage should begin after local execution and status persistence exist.

### Opt-In Suites

- Status: deferred.
- Markers affected: none expected for `slow`, `network`, `slurm`, or `optional_dependency`.
- Required assertions or deferral reason: this phase is pure in-memory validation and graph logic with no network, scheduler, optional dependency, or slow external behavior.

## Risks

- Strict parsing could accidentally reject future fields without a useful message; tests must assert deferred fields mention the field and that it is unsupported in v0.
- If graph construction loses authored order, topological sort may become nondeterministic and make later planning/fingerprint explanations noisy.
- Mixing input data edges and `depends_on` control edges without preserving the reason could make later artifact binding and resume explanations unclear.
- Adding public imports through `loom.__init__` would violate the import-boundary policy and should be rejected during review.
- Overbuilding status transitions or context helpers now could drag Phase 7/Phase 9 execution semantics into the static model PR.

## Validation Commands

Targeted development commands:

```sh
uv run pytest tests/unit/loom/pipeline/test_specs.py
uv run pytest tests/unit/loom/pipeline/test_context.py tests/unit/loom/pipeline/test_stage.py
uv run pytest tests/unit/loom/pipeline/test_status.py
uv run pytest tests/unit/loom/pipeline/graph
uv run pytest tests/contracts/test_stage_contract.py
uv run pytest tests/integration/pipeline/test_pipeline_config.py
make test-package
make test-unit
make test-contract
make test-integration
```

Final PR-preparation commands:

```sh
make validate-pr
make test-summary
```

This refine pass intentionally did not run validation because no product implementation was performed and the manager requested planning only.

## Handoff Notes For `loom_phase_executor`

- Safe implementation slices:
  1. Errors and spec parsing: `src/loom/pipeline/errors.py`, `src/loom/pipeline/specs.py`, package exports, `tests/unit/loom/pipeline/test_specs.py`, `tests/unit/loom/pipeline/test_errors.py`, and package API/import tests.
  2. Stage contract and context: `src/loom/pipeline/stage.py`, `src/loom/pipeline/context.py`, `tests/unit/loom/pipeline/test_context.py`, `tests/unit/loom/pipeline/test_stage.py`, and `tests/contracts/test_stage_contract.py`.
  3. Status model: `src/loom/pipeline/status.py` and `tests/unit/loom/pipeline/test_status.py`.
  4. Bindings and graph: `src/loom/pipeline/graph/bindings.py`, `src/loom/pipeline/graph/dag.py`, `src/loom/pipeline/graph/topology.py`, graph exports, and graph unit tests.
  5. Integration proof: `tests/integration/pipeline/test_pipeline_config.py` using `compose_config()` and resolved `pipeline` mappings.
- Tests to run with each slice: run the direct `uv run pytest` path for the changed slice, then broaden to `make test-unit`, `make test-package`, `make test-contract`, and `make test-integration` before PR preparation.
- Decisions the executor must not revisit: no target instantiation, no runner/store/CLI behavior, no root `loom.__init__` pipeline exports, no deferred fields accepted silently, no raw string constants for statuses/edge reasons, no graph edges that lose data-vs-control reasons, no broad refactors outside `loom.pipeline` and phase-scoped tests.
- Conditions that require stopping for the manager: inability to preserve the recorded stack base, discovery that Phase 6 needs an unplanned public API outside `loom.pipeline` or `loom.pipeline.graph`, a conflict with Phase 5 branch contents that cannot be resolved without changing Phase 5 behavior, or a need to consume implementation refinement/review budget before implementation exists.

## Refinement And Review Budget Status

- Phase execution plan draft: completed by `loom_phase_planner`; draft commit `fee127460ad171cc364485169575916a7acdcdee`.
- Phase execution plan refine: completed by `loom_phase_planner` in this pass.
- Phase implementation refinement: unused.
- PR review: unused.

## Completion Notes

- Draft plan: completed by `loom_phase_planner`; committed with message `plan: add phase execution plan`.
- Final phase execution plan: completed by `loom_phase_planner` in this pass.
- Implementation summary: pending implementation pass.
- Implementation validation: pending implementation and PR-preparation passes.
- Refinement summary: pending implementation refinement pass; budget unused.
- PR preparation: pending.
- Stack maintenance: pending predecessor merge and retarget/rebase handling.
- Remaining blockers: none recorded for local planning.
