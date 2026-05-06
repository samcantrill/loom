# `loom.pipeline` Specification

## 1. Purpose

`loom.pipeline` is the pipeline description, planning, and stage orchestration layer
for `loom`.

It exists to turn a resolved experiment configuration into a validated,
artifact-based execution graph. It should define pipeline and stage specs,
validate dependencies, bind upstream artifacts to downstream inputs, create stage
contexts, coordinate execution through executors, record stage state, and provide
enough information for safe resume.

The pipeline layer should treat stages as generic Python components. A stage may
train a model, preprocess data, call a command-line tool, generate a report, or
do any other project-specific work. `loom.pipeline` should only care about the
contract around that work:

```text
what stage is this?
what inputs does it consume?
what outputs does it promise?
what resources/runtime does it request?
what artifacts and status did it produce?
```

The initial design should be intentionally narrow. The first implementation
should support explicit static DAGs, local execution, artifact passing, status
tracking, and resume planning. It should avoid dynamic DAG mutation, nested task
scheduling, domain-specific stage types, and scheduler features that would turn
`loom` into a general workflow platform too early.

### 1.1 Alignment With `loom.md`

This document expands the pipeline DAG, stage execution, artifact passing, status
tracking, and resume responsibilities from [loom.md](../loom.md). The package-wide
boundary remains strict: `loom.pipeline` owns orchestration around stages, while
project code owns stage internals, data semantics, metrics, training, reports,
and any domain-specific recovery.

---

## 2. Core Position

Use this architecture:

```text
Configuration:
  compose, expand, validate, and instantiate configured objects

Pipeline:
  validate static DAGs, bind artifacts, plan execution, run stages, track state

Project code:
  implement concrete stage behavior

Stores:
  persist artifacts, run state, logs, fingerprints, and indexes

Executors:
  decide where and how individual stage invocations run
```

This means `loom.pipeline` is not an experiment framework, a data framework, or a
training framework. It is the generic runtime kernel for artifact-based research
pipelines.

The central pipeline boundary is:

```text
loom.pipeline owns stage orchestration.
stage implementations own stage internals.
```

For example, `loom.pipeline` may decide whether to run the `train` stage based on
its fingerprint and input artifacts. It should not know how to resume a PyTorch
checkpoint, how to load a dataset, or how to compute a validation metric.

---

## 3. Package Boundary

### 3.1 `loom`

Owns shared primitives.

Responsibilities:

```text
resource references
artifact references
records and manifests
fingerprint helpers
provenance value objects
shared exceptions
serialization helpers
```

### 3.2 `loom.config`

Owns configuration composition and object construction.

Responsibilities:

```text
load experiment configs
apply overlays
apply CLI overrides
expand recipes
resolve interpolation
validate config-level schemas
instantiate `_target_` objects
produce resolved config and config provenance data for the runner/run store
```

`loom.config` may produce a resolved pipeline config or instantiate a
`PipelineSpec`, but it should not execute stages.

### 3.3 `loom.pipeline`

Owns pipeline modeling and orchestration.

Responsibilities:

```text
pipeline and stage specs
stage protocol
stage context
DAG validation
topological planning
artifact input binding
stage output validation
stage status transitions
runner lifecycle
resume decisions
executor integration
run selection
```

### 3.4 `loom.pipeline.stores`

Owns persistence interfaces used by pipeline execution.

Responsibilities:

```text
run directory creation
stage status files
input and output manifests
artifact indexes
fingerprint files
atomic writes
local artifact storage
local run storage
locking, later
```

Stores should be inspectable without Python. The local store should prefer plain
files such as `status.json`, `inputs.json`, `outputs.json`,
`fingerprint.json`, and `artifacts.json`.

### 3.5 `loom.pipeline.executors`

Owns stage invocation mechanisms.

Responsibilities:

```text
local in-process execution
post-v0 subprocess execution
post-v0 SLURM script generation and submission
executor result reporting
log capture integration
post-v0 runtime/resource mapping
```

Executors should not reinterpret pipeline semantics. They receive an execution
request for a stage and return an execution result.

### 3.6 `loom.cli`

Owns command-line presentation only.

Responsibilities:

```text
parse CLI arguments
call config and pipeline APIs
format plan/status/log/artifact output
return appropriate exit codes
```

The CLI should remain thin. It should not directly validate DAGs, write status
files, or implement resume policy.

### 3.7 Project Code

Owns concrete pipeline behavior.

Responsibilities:

```text
stage implementations
domain-specific data loading
domain-specific artifact schemas
model training
metrics
plots
reports
project recipes
project codecs
```

Project code may depend on `loom`. `loom` must not depend on project code.

---

## 4. Initial Scope

### 4.1 Must Support in v0

```text
PipelineSpec
StageSpec
Stage protocol
StageContext
explicit static DAGs
unique stage names
declared stage inputs and outputs
DAG validation
topological ordering
branching and diamond DAGs
artifact input binding
stage output validation
local in-process executor
basic runner lifecycle
run directory creation through stores
stage status transitions
stage inputs/outputs files
stage fingerprints
resume planning
force/from/only/skip stage selectors
clear path-aware errors
small public Python API
```

The v0 target should be a fully working local synthetic pipeline:

```text
write -> add -> multiply -> report
```

That pipeline should run without any domain package and should prove artifact
passing, branching, status tracking, and resume behavior.

### 4.2 Should Not Support in v0

```text
runtime DAG mutation
stage-internal subtask scheduling
general distributed scheduling
web dashboard
database-backed orchestration service
complex conditional expression language
automatic cloud execution abstraction
remote artifact stores
container orchestration
Bayesian sweeps
application-specific artifact schemas
application-specific stage base classes
application-specific stage registries
```

The first version should have one primary pipeline model:

```text
an explicit static DAG of stages connected by named artifacts
```

Dynamic behavior can be added later only where it does not weaken planning,
resume, provenance, and SLURM execution.

---

## 5. Terminology

### 5.1 PipelineSpec

A static description of a pipeline DAG.

It defines the stages, their dependencies, their logical inputs and outputs, and
pipeline-level defaults. It does not execute anything.

### 5.2 StageSpec

A static description of one stage in a pipeline.

It defines the stage name, target implementation, input bindings, output
declarations, stage config, runtime/resource requests, and optional execution
policy.

### 5.3 Stage

A concrete Python object with `run(context, inputs)` that performs work.

Stages are supplied by project code. They are checked structurally rather than
through inheritance-heavy base classes. Plain callable stages are post-v0.

### 5.4 Stage Target

The import path that identifies the stage implementation.

In authored YAML, the stage target must be declared as:

```yaml
factory:
  _target_: project.stages.BuildManifestStage
```

`factory.init` is optional constructor kwargs and is distinct from `config`.

### 5.5 StageContext

The runtime context passed to a stage invocation.

It gives the stage access to run paths, stage paths, resolved config, stage
config, stores, logger, provenance helpers, selected runtime metadata, and output
path allocation.

### 5.6 Logical Artifact Name

A stable name for a stage output within the pipeline graph.

Examples:

```text
build_manifest.manifest
train.best_checkpoint
evaluate.metrics
```

Logical names are used for dependency binding, inspection commands, artifact
indexes, and provenance.

### 5.7 Input Binding

The mapping from a stage input name to an upstream artifact.

Example:

```yaml
inputs:
  manifest: build_manifest.manifest
  checkpoint: train.best_checkpoint
```

### 5.8 Output Declaration

The mapping from a stage output name to expected artifact metadata.

Example:

```yaml
outputs:
  metrics:
    artifact_type: metrics.json
    codec_key: json.v1
```

### 5.9 Execution Plan

A deterministic plan derived from a `PipelineSpec`, run store state, selected
stages, and resume policy.

It records which stages should run, skip, reuse, or be considered stale, and why.

### 5.10 Stage Result

The structured result of a stage invocation.

At minimum it should include returned output `ArtifactRef`s or a failure result
with exception/exit information.

---

## 6. Guiding Design Principles

### 6.1 Static Graphs First

The graph should be fully known before execution starts.

This enables:

```text
early validation
dry-run planning
SLURM dependency generation
safe resume
artifact lineage
clear provenance
```

Dynamic DAG mutation should be out of scope until static DAG behavior is stable.

### 6.2 Stages Are Black Boxes with Explicit Contracts

`loom.pipeline` should not inspect or control stage internals.

It should require only:

```text
declared inputs
declared outputs
structural run interface
returned ArtifactRefs
status/failure reporting
```

The stage may perform arbitrary Python work internally.

### 6.3 Artifacts Are the Boundary Between Stages

Stages should communicate through explicit artifacts, not through implicit Python
object sharing.

Good:

```text
stage A writes an ArtifactRef
stage B receives that ArtifactRef as an input
```

Avoid:

```text
stage A returns a live Python object consumed directly by stage B
```

Explicit artifacts make subprocess, SLURM, resume, and provenance behavior
possible.

### 6.4 Plan Before Running

Running should always be based on an execution plan.

Even if the user calls a direct `run()` API, the runner should internally:

```text
validate the spec
load prior run state
resolve stage selectors
bind inputs
compute fingerprints
decide run/reuse/skip/stale actions
then execute
```

This keeps dry-run behavior and real execution consistent.

### 6.5 Status Writes Must Be Conservative

A stage should be marked `SUCCEEDED` only after:

```text
stage invocation completed
declared outputs were returned
artifact refs were validated
required artifact files exist when locally checkable
outputs were persisted
fingerprint was persisted
run artifact index was updated
```

Partial outputs should not be treated as valid.

### 6.6 Resume Is Fingerprint-Based

Resume should not be based only on file existence.

The planner should compare:

```text
stage target
stage config
input artifact refs/checksums/fingerprints
relevant resolved config subtree
selected environment/runtime metadata
loom version or pipeline contract version
optional user-provided fingerprint fields
```

If a stage has outputs but no matching fingerprint, it should not be reused by
default.

### 6.7 Selectors Should Be Explicit and Predictable

Selectors such as `from-stage`, `only-stage`, `force-stage`, and `skip-stage`
should produce inspectable plans.

The same selectors should be available through the Python API and CLI.

### 6.8 Pipeline Errors Should Be Path-Aware

Errors should include the best available location:

```text
config path
stage name
input name
output name
artifact logical name
run directory path
status file path
```

The most common user mistakes should fail before execution starts.

---

## 7. Pipeline Authoring Model

### 7.1 Minimal Pipeline

Example:

```yaml
pipeline:
  stages:
    - name: build_manifest
      factory:
        _target_: project.stages.BuildManifestStage
      outputs:
        manifest:
          artifact_type: manifest
          codec_key: json.v1

    - name: summarize
      factory:
        _target_: project.stages.SummarizeStage
      inputs:
        manifest: build_manifest.manifest
      outputs:
        summary:
          artifact_type: summary.json
          codec_key: json.v1
```

The authored config may be compact. After `loom.config` resolves it, the pipeline
layer should receive an explicit structure.

### 7.2 Branching Pipeline

Example:

```yaml
pipeline:
  stages:
    - name: train
      factory:
        _target_: project.stages.TrainStage
      inputs:
        manifest: build_manifest.manifest
      outputs:
        best_checkpoint:
          artifact_type: checkpoint

    - name: evaluate_main
      factory:
        _target_: project.stages.EvaluateStage
      inputs:
        checkpoint: train.best_checkpoint
      outputs:
        metrics:
          artifact_type: metrics.json
          codec_key: json.v1

    - name: evaluate_external
      factory:
        _target_: project.stages.EvaluateStage
      inputs:
        checkpoint: train.best_checkpoint
      outputs:
        metrics:
          artifact_type: metrics.json
          codec_key: json.v1
```

One upstream artifact can be consumed by multiple downstream stages. This should
fall naturally out of DAG binding.

### 7.3 Diamond Pipeline

Example:

```text
prepare
  -> train_a
  -> train_b
train_a.metrics + train_b.metrics
  -> compare
```

The `compare` stage should not run until both upstream metrics artifacts are
available and valid.

### 7.4 Explicit Dependencies Without Artifacts

Most dependencies should be expressed through input bindings. Occasionally a
stage may need to wait for another stage even without consuming its artifacts.

Support:

```yaml
depends_on:
  - setup_environment
```

Use this sparingly. Artifact inputs are preferred because they carry stronger
lineage and resume information.

### 7.5 Stage Configuration

Stage-specific configuration should live under `config`:

```yaml
- name: train
  factory:
    _target_: project.stages.TrainStage
  inputs:
    manifest: build_manifest.manifest
  outputs:
    best_checkpoint:
      artifact_type: checkpoint
  config:
    max_epochs: 100
    batch_size: 32
```

`factory.init` carries constructor kwargs and is separate from stage runtime
`config`.

Recommended rule:

```text
factory.init defines stage-object constructor arguments
stage config defines the particular invocation
```

In simple cases these may overlap, but the pipeline layer should keep the
distinction available.

### 7.6 Static Fan-Out Templates

Repeated stage patterns can be useful, but they should still produce an explicit
static DAG before execution starts.

Examples:

```text
evaluate one checkpoint across several datasets
generate one report per cohort
validate several model variants with the same stage target
```

Prefer config-time or recipe-time expansion for this. `loom.pipeline` should
receive the expanded `PipelineSpec`, validate it normally, and avoid runtime DAG
mutation.

---

## 8. PipelineSpec

### 8.1 V0 Fields

```python
from dataclasses import dataclass, field
from typing import Any, Mapping, Sequence

@dataclass(frozen=True, slots=True)
class PipelineSpec:
    stages: Sequence[StageSpec]
    name: str | None = None
    description: str | None = None
    metadata: Mapping[str, Any] = field(default_factory=dict)
    schema_version: int | None = None
```

Suggested meanings:

```text
name:
  human-readable pipeline name

description:
  optional documentation string

stages:
  ordered or unordered collection of StageSpec objects

defaults:
  deferred in v0; authored defaults should fail validation clearly

metadata:
  generic user/project metadata, not interpreted by loom unless documented

schema_version:
  optional pipeline spec schema version; omitted means no schema version
  constraint
```

### 8.2 Stage Order in Authored Config

Authored stage order should not be used as a substitute for dependencies.

Recommended behavior:

```text
stages may be authored in any order
dependencies determine execution order
stable topological sorting preserves authored order where possible
```

This makes diffs readable while keeping semantics explicit.

### 8.3 Pipeline-Level Defaults

Pipeline-level defaults are post-v0. Authored `pipeline.defaults` should fail
validation clearly in v0.

Pipeline defaults may provide values for stages that omit them.

Example:

```yaml
pipeline:
  defaults:
    runtime:
      executor: local
    retry:
      max_attempts: 1
  stages:
    - name: prepare
      factory:
        _target_: project.stages.PrepareStage
```

Default application should be deterministic and shallow enough to explain:

```text
stage-level values override pipeline defaults
mapping defaults may merge recursively
lists should replace, not splice
```

Keep this aligned with config merge semantics where possible.

---

## 9. StageSpec

### 9.1 V0 Fields

```python
from dataclasses import dataclass, field
from typing import Any, Mapping, Sequence

@dataclass(frozen=True, slots=True)
class StageSpec:
    name: str
    factory: StageFactorySpec
    inputs: Mapping[str, str] = field(default_factory=dict)
    outputs: Mapping[str, "OutputSpec"] = field(default_factory=dict)
    dependencies: Sequence[str] = field(default_factory=tuple)
    stage_config: Mapping[str, Any] = field(default_factory=dict)
    fingerprint_fields: Mapping[str, Any] = field(default_factory=dict)
    resources: Mapping[str, Any] = field(default_factory=dict)
```

Authored YAML keys are parsed into these internal fields:

```text
factory -> StageFactorySpec
config -> stage_config
depends_on -> dependencies
fingerprint -> fingerprint_fields
```

Suggested meanings:

```text
name:
  stable stage identifier within the pipeline

factory:
  includes constructor target path and optional `init` kwargs in
  `factory.init`

inputs:
  map of stage input name to upstream logical artifact name

outputs:
  map of stage output name to declared output spec

dependencies:
  explicit stage dependencies not represented by artifact inputs

stage_config:
  invocation-specific config visible to the stage

fingerprint:
  explicit stage-level semantic fingerprint fields

resources:
  opaque plain-data metadata preserved for inspection; v0 does not interpret
  scheduler fields or include resources in semantic fingerprints by default

runtime:
  deferred in v0; authored `runtime` fields should fail validation clearly

retry:
  deferred in v0; authored `retry` fields should fail validation clearly

when:
  deferred in v0; authored `when` fields should fail validation clearly

metadata:
  deferred at the stage-spec level in v0; authored `metadata` fields should
  fail validation clearly
```

V0 intentionally rejects unknown stage-level orchestration keys instead of
preserving them silently. `runtime`, `retry`, `when`, and stage-level
`metadata` are post-v0 fields.

### 9.2 Stage Names

Stage names should be:

```text
unique within a pipeline
stable across reruns
usable as path components after normalization
clear in logs and status output
```

Recommended validation:

```text
not empty
no slash
no backslash
no control characters
no "." or ".."
unique after normalization if normalization is applied
```

Avoid generating opaque stage names in core. Recipes may generate names, but the
resolved config should show them explicitly.

### 9.3 Input Syntax

The compact input syntax should be:

```yaml
inputs:
  checkpoint: train.best_checkpoint
```

This means:

```text
this stage receives input name "checkpoint"
from stage "train"
output "best_checkpoint"
```

An expanded form can be supported later if needed:

```yaml
inputs:
  checkpoint:
    stage: train
    output: best_checkpoint
    artifact_type: checkpoint
```

The compact string should be enough for v0.

### 9.4 OutputSpec

V0 fields:

```python
@dataclass(frozen=True, slots=True)
class OutputSpec:
    artifact_type: str
    codec_key: str | None = None
    schema_version: int | None = None
    metadata: Mapping[str, Any] = field(default_factory=dict)
```

Suggested meanings:

```text
artifact_type:
  generic type label used for validation and inspection

path:
  deferred in v0; physical paths are allocated by the artifact store

codec_key:
  optional codec expected for the artifact

schema_version:
  optional artifact schema version; omitted means no schema version constraint

required:
  deferred in v0; declared outputs are required

metadata:
  generic metadata
```

For v0, declared outputs are required, and authored output `path` fields should
fail validation clearly. Optional outputs and path templates can be added when
there is a concrete use case.

### 9.5 ResourceSpec

The pipeline layer should treat resources as opaque plain-data metadata in v0.
They have no executor-specific semantics, no scheduler mapping, and no default
impact on stage fingerprints. Future runtime/resource phases may add typed
resource models or an explicit fingerprint-inclusion policy.

Example:

```yaml
resources:
  cpus: 16
  memory_mb: 65536
  gpus: 1
  wall_time_seconds: 28800
  label: "large-local"
```

Validation should be light in v0:

```text
value must be plain-data-compatible
no executor-specific fields are interpreted
unknown keys are preserved as metadata
```

### 9.6 RuntimeSpec

Runtime settings are post-v0. V0 should reject authored stage `runtime` fields
with a clear validation error.

Runtime settings describe how the stage should be invoked.

Example:

```yaml
runtime:
  executor: local
  container: null
  environment:
    OMP_NUM_THREADS: "8"
```

The pipeline layer should not implement or preserve runtime settings in v0.
Authored stage `runtime` fields must fail validation clearly. Preserving runtime
settings for executors and fingerprints is post-v0.

---

## 10. Stage Protocol

### 10.1 Required Interface

Use a structural protocol:

```python
from typing import Protocol

class Stage(Protocol):
    def run(
        self,
        context: "StageContext",
        inputs: Mapping[str, ArtifactRef],
    ) -> Mapping[str, ArtifactRef]:
        ...
```

The exact signature should be stable before public release. The important design
choice is that stages receive:

```text
context:
  runtime services and paths

inputs:
  bound ArtifactRefs from upstream stages
```

and return:

```text
mapping of declared output name to ArtifactRef
```

### 10.2 Callable Stages

Optionally support plain callables later:

```python
def summarize(context: StageContext, inputs: Mapping[str, ArtifactRef]) -> dict[str, ArtifactRef]:
    ...
```

For v0, supporting objects with `run()` is sufficient. Plain callables can be
adapted after the object protocol is stable.

### 10.3 Stage Construction

Pipeline stage mappings are orchestration specs, not generic `_target_` object
graphs.

For v0, pipeline imports the stage factory target from
`StageSpec.factory.target_path`, constructs with `StageSpec.factory.init`, and
then invokes:

```text
stage.run(context, inputs)
```

Authored `config` is parsed into `StageSpec.stage_config` and exposed through
`StageContext`; it is not copied into constructor kwargs. Accepting already
instantiated stage objects is supported only when `factory.init` is empty in this
phase, and callable/class constructor behavior is explicit.

### 10.4 Stage Idempotence

Stages should be documented as expected to be idempotent with respect to their
declared inputs and config.

Recommended behavior inside stage implementations:

```text
write temporary outputs
validate outputs
return ArtifactRefs only for completed outputs
avoid mutating upstream artifacts
avoid relying on global hidden state
```

`loom.pipeline` cannot guarantee arbitrary stage idempotence, but its lifecycle
should make the safe path straightforward.

### 10.5 Stage-Internal Resume

Pipeline resume and stage-internal resume are separate.

Example:

```text
loom pipeline resume:
  decides whether to skip or rerun the train stage

training stage resume:
  decides whether to load a checkpoint inside the train stage
```

`loom.pipeline` should allow a stage to inspect its stage directory and config,
but it should not implement domain-specific checkpoint recovery.

---

## 11. StageContext

### 11.1 StageContext Stage-author Facade

`StageContext` should remain a narrow stage-author API and not leak direct mutable
store handles.

```python
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Mapping

@dataclass(frozen=True, slots=True)
class StageContext:
    run_id: str
    stage_name: str
    resolved_config: Mapping[str, Any]
    stage_config: Mapping[str, Any]
    provenance: Mapping[str, Any] = field(default_factory=dict)
    metadata: Mapping[str, Any] = field(default_factory=dict)
```

Public context attributes should not include `run_dir`, `stage_dir`, `run_store`,
or `artifact_store`.

The facade helper set is:

```python
def input_artifact(name: str) -> ArtifactRef: ...
def load_input(name: str, *, expected_type: str | None = None, codec_key: str | None = None) -> object: ...
def load_artifact(ref: ArtifactRef, *, expected_type: str | None = None, codec_key: str | None = None) -> object: ...
def save_artifact(name: str, obj: object, *, artifact_type: str, codec_key: str, schema_version: int = 1, metadata: Mapping[str, Any] | None = None, fingerprint: str | None = None) -> ArtifactRef: ...
def register_artifact(name: str, uri: str, *, artifact_type: str, codec_key: str | None = None, schema_version: int = 1, metadata: Mapping[str, Any] | None = None, fingerprint: str | None = None, checksum: str | None = None, allow_external: bool = False) -> ArtifactRef: ...
def register_local_artifact(name: str, path: str | os.PathLike[str], *, artifact_type: str, codec_key: str | None = None, schema_version: int = 1, metadata: Mapping[str, Any] | None = None, fingerprint: str | None = None, checksum: str | None = None, allow_external: bool = False) -> ArtifactRef: ...
def local_output_path(name: str, *, suffix: str = "") -> Path: ...
def local_workspace_path(*parts: str) -> Path: ...
```

`save_artifact()` and `register_artifact()` validate declared output type,
codec key, and schema version before writing or registering.

`local_output_path()` validates the output name and suffix, creates parents, and
raises `PipelineValidationError` when local output helpers are unavailable.

`local_workspace_path()` should validate all path parts and create the workspace
directory on demand; it should raise `PipelineValidationError` when local access
is not available.

`load_input()` fails early for unknown input names and `load_artifact()` or
`load_input()` fail clearly when no artifact store is available.

---

## 12. DAG Model

### 12.1 Nodes

Each `StageSpec` is one DAG node.

Node identity is the stage name.

### 12.2 Edges

Edges come from:

```text
artifact input bindings
explicit depends_on entries
```

Artifact input bindings are stronger because they identify the exact upstream
artifact required.

### 12.3 Logical Artifact References

Use this compact syntax:

```text
STAGE_NAME.OUTPUT_NAME
```

Recommended parser behavior:

```text
split on the first dot or last dot consistently
reject missing stage or output parts
reject references to unknown stages
reject references to unknown outputs
```

Since stage and output names should not contain dots in v0, splitting on one dot
is simplest. If dots in stage names are later allowed, the reference syntax
should be revisited before release.

### 12.4 Topological Sorting

Topological sorting should be deterministic.

Recommended behavior:

```text
preserve authored order among otherwise-ready stages
raise clear cycle errors
include the cycle path when possible
```

### 12.5 Branching

Multiple downstream stages may consume the same upstream output.

This should require no special stage behavior.

### 12.6 Fan-In

One downstream stage may consume artifacts from multiple upstream stages.

The planner should ensure all required upstream stages are successful or reused
before the downstream stage runs.

### 12.7 Explicit Dependencies

`depends_on` creates an ordering edge but not an artifact binding.

Use cases:

```text
setup stage that prepares a shared environment
barrier stage
manual dependency on an external side effect
```

These should be allowed but not encouraged for ordinary data flow.

---

## 13. Validation

### 13.1 Pipeline Validation

Validate before planning or execution.

Required checks:

```text
pipeline has at least one stage
stage names are unique
stage names are valid
stage targets are present
input bindings are syntactically valid
input bindings reference existing stages
input bindings reference declared upstream outputs
depends_on references existing stages
no cycles
output names are unique within a stage
output specs have artifact_type
runtime/resource specs are mappings when present
```

### 13.2 Stage Contract Validation

Before running a stage:

```text
stage object has a usable run method
all required input artifacts are available
stage directory can be created
artifact directory can be created
```

After running a stage:

```text
result is a mapping
all required declared outputs are present
no undeclared outputs unless policy allows them
all returned values are ArtifactRefs
returned artifact types match OutputSpec when declared
returned codec keys match OutputSpec when declared
local artifact paths exist when checkable
```

### 13.3 Unknown Outputs

Recommended v0 policy:

```text
fail on undeclared outputs
```

Reason:

```text
strict outputs improve provenance, artifact indexing, and resume safety
```

An `allow_extra_outputs` policy can be added later if repeated use justifies it.

### 13.4 Optional Outputs

Recommended v0 policy:

```text
all declared outputs are required
```

Optional outputs add complexity to downstream binding and resume. Add them later
only with clear semantics.

### 13.5 Path Safety

For local artifact paths:

```text
relative output paths should stay inside the stage artifact directory
absolute output paths should require explicit external-artifact policy
parent directory traversal should be rejected by default
```

---

## 14. Planning

### 14.1 Planner Inputs

The planner should receive:

```text
PipelineSpec
resolved config or relevant config view
run store state
artifact store state
resume policy
stage selectors
runtime defaults
```

### 14.2 Planner Outputs

The planner should return an `ExecutionPlan`.

Recommended structure:

```python
@dataclass(frozen=True, slots=True)
class ExecutionPlan:
    pipeline: PipelineSpec
    stage_plans: tuple[StagePlan, ...]
    selected_stages: frozenset[str]
    reasons: Mapping[str, str]
```

Each `StagePlan` should include:

```text
stage name
action
reason
input bindings
expected outputs
fingerprint
upstream dependencies
downstream dependencies
resources metadata
```

### 14.3 Stage Actions

Recommended action vocabulary:

```text
RUN
REUSE
SKIP
STALE
BLOCKED
```

Meanings:

```text
RUN:
  invoke the stage

REUSE:
  prior successful outputs are valid and should be used

SKIP:
  user selector or condition excludes this stage

STALE:
  prior outputs exist but cannot be reused

BLOCKED:
  cannot run because an upstream stage is failed, missing, or skipped
```

Execution may turn `STALE` into `RUN` when rerun is allowed. Keeping `STALE` in
the plan is useful for explanation.

### 14.4 Resume Policy

Default policy:

```text
reuse prior succeeded stage only if fingerprint matches, required artifacts
exist, and present checksums validate when the store can read the URI
rerun failed, incomplete, stale, or missing stages
rerun downstream stages if upstream artifact identity changed
fail if required upstream artifacts are missing and cannot be produced
```

Strict mode can later verify checksums before reuse.

### 14.5 Stage Selectors

Support selectors:

```text
from_stage:
  run this stage and all downstream stages

only_stages:
  run exactly this stage, requiring inputs to already exist or be reusable

force_stages:
  rerun this stage even if reusable; downstream invalidation applies

skip_stages:
  exclude this stage and stages that require its outputs, unless their inputs are already satisfied
```

Selectors should be represented as structured Python values, not raw CLI strings.

### 14.6 Dry-Run Output

`loom plan` should use the same planner as `loom run`.

Example output:

```text
build_manifest  REUSE  fingerprint match
train           RUN    forced by selector
evaluate        RUN    upstream train changed
report          BLOCKED missing input evaluate.metrics
```

---

## 15. Execution Lifecycle

### 15.1 Runner Flow

Recommended flow:

```text
1. Validate pipeline spec.
2. Create or open run directory.
3. Persist resolved config if not already persisted.
4. Load prior run state.
5. Build execution plan.
6. Persist execution plan.
7. For each runnable stage in dependency order:
     a. mark stage RUNNING
     b. write inputs.json
     c. write fingerprint candidate
     d. invoke executor
     e. validate outputs
     f. persist outputs.json
     g. update artifact index
     h. mark stage SUCCEEDED
8. On failure:
     a. persist failure metadata
     b. mark stage FAILED
     c. stop or continue according to policy
9. Finalize run status.
```

### 15.2 Stage Status States

Recommended status vocabulary:

```text
PENDING
RUNNING
SUCCEEDED
FAILED
SKIPPED
STALE
CANCELLED
```

Meanings:

```text
PENDING:
  known but not started

RUNNING:
  currently executing or was interrupted while executing

SUCCEEDED:
  completed and outputs were validated

FAILED:
  completed unsuccessfully with failure metadata

SKIPPED:
  excluded by selector or condition

STALE:
  previous result exists but is not reusable

CANCELLED:
  explicitly stopped before completion
```

### 15.3 Interrupted Runs

On opening an existing run directory, the planner should treat old `RUNNING`
stages conservatively.

Recommended behavior:

```text
if RUNNING has no live owner or cannot be verified, treat as incomplete
do not reuse outputs without matching succeeded status and fingerprint
preserve old failure/interruption metadata for debugging
```

### 15.4 Failure Behavior

Default behavior:

```text
stop pipeline on first failed stage
mark downstream stages BLOCKED or leave them PENDING in the plan
write failure metadata and log paths
return non-zero CLI exit code
```

Continue-on-failure can be added later for independent branches.

### 15.5 Atomicity

The runner and stores should use atomic write helpers for stage state files:

```text
write temp file in same directory
fsync where appropriate
rename into place
```

Stage artifact atomicity is harder because stages own their internals, but the
context should make temporary output paths easy to use.

---

## 16. Executors

### 16.1 Executor Interface

Recommended protocol:

```python
class Executor(Protocol):
    def execute(self, request: "StageExecutionRequest") -> "StageExecutionResult":
        ...
```

The request should include:

```text
run_id
stage spec
stage context
bound inputs
fingerprint
resources metadata
```

The result should include:

```text
success flag
returned outputs, for in-process execution
exit code, for post-v0 subprocess execution
exception metadata
stdout/stderr log paths
executor metadata
```

### 16.2 Local Executor

Runs the stage in the current Python process.

Use cases:

```text
unit tests
local development
small pipelines
CI smoke tests
```

The local executor may return `ArtifactRef`s directly from the stage call.

### 16.3 Subprocess Executor

Post-v0.

Runs one stage through:

```bash
loom stage run --run-dir RUN_DIR --stage STAGE_NAME
```

Use cases:

```text
stage isolation
independent logs
closer to SLURM/container execution
debugging stage entry points
```

Future subprocess executors should not require Python object sharing across
stages. They should communicate through run store files and artifact refs.

### 16.4 SLURM Executors

Post-v0.

SLURM behavior should live in executor implementations, not in the core planner.

Initial SLURM modes:

```text
single-job:
  one job runs the whole pipeline

afterok:
  one job per stage, dependencies submitted to SLURM
```

Detailed SLURM behavior should have a separate design document. The pipeline
layer should expose enough structured plan information for SLURM executors to
generate scripts and dependencies.

---

## 17. Stores and Run Layout

Pipeline execution depends on store interfaces, but the detailed run-store design
should live in a separate document.

The pipeline layer should assume a local v0 layout compatible with
caller-provided runtime config snapshots:

```text
runs/RUN_ID/
  config/
    resolved.yaml
  stages/
    STAGE_NAME/
      status.json
      inputs.json
      outputs.json
      fingerprint.json
      failure.json
      logs/
  artifacts/
    STAGE_NAME/
      ...
  artifacts.json
  plan.json
  run.json
```

Current v1 composed-config runs add artifact-safe config persistence without
making `loom.pipeline` import `loom.config` classes:

```text
runs/RUN_ID/
  config/
    composition_manifest.json
    recipe_manifest.json
  run.json metadata.config_provenance
```

For composed configs, those files are plain-data records. They preserve authored
composition, recipe, provenance, and fingerprint facts, and they do not write
default `config/resolved.yaml` or `config/resolved.redacted.yaml` snapshots,
resolver outputs, or raw source bytes. Plain mapping config snapshots remain
caller-provided runtime data, not v1 composed-config artifacts.

Required pipeline interactions:

```text
create run directory
create stage directory
read prior stage status
write stage status
write stage inputs
write stage outputs
write stage fingerprint
update artifact index
allocate artifact paths
capture logs
```

The pipeline runner should go through store APIs rather than hard-coding every
path. The local implementation can still use the plain layout above.

---

## 18. Fingerprints and Reuse

### 18.1 Fingerprint Inputs

Recommended stage fingerprint inputs:

```text
stage name
stage target import path
stage constructor identity when available
stage config
declared inputs
input artifact refs
input artifact checksums/fingerprints when available
declared outputs
explicit future opt-in runtime/resource fields that affect outputs
relevant code provenance
loom version or pipeline contract version
user-provided extra fingerprint fields
```

V0 excludes `StageSpec.resources` from semantic fingerprints by default.

Avoid noisy values:

```text
wall-clock timestamp
run directory
random run ID
log path
temporary directory path
hostname, unless outputs depend on it
```

### 18.2 Fingerprint File

Each stage should persist:

```text
fingerprint value
fingerprint algorithm/version
fingerprint input summary
created_at timestamp
loom version
```

The summary helps users understand why a stage reran.

### 18.3 Artifact Checksums

Checksums and fingerprints are distinct:

```text
checksum:
  identity of stored bytes

fingerprint:
  identity of the production recipe
```

Resume should prefer fingerprints for semantic reuse and checksums for corruption
or existence validation.

### 18.4 Downstream Invalidation

If an upstream stage reruns and produces a changed artifact identity, downstream
stages should be considered stale unless their fingerprints still match under
the documented fingerprint policy.

The planner should explain this:

```text
evaluate  RUN  upstream artifact changed: train.best_checkpoint
```

---

## 19. Conditions

Conditional stages are useful, but v0 should avoid a general expression language.

Recommended v0 policy:

```text
do not implement `when` initially
```

Or, if needed, support only:

```yaml
when: analysis.enabled
```

Where `analysis.enabled` is a config path that resolves to a boolean.

Do not support:

```text
arbitrary Python expressions
Jinja expressions
shell expressions
complex boolean language
```

Conditions complicate planning, blocked downstream stages, and provenance. Keep
them limited.

---

## 20. Public API

Recommended API:

```python
from loom.pipeline import (
    PipelineSpec,
    StageSpec,
    OutputSpec,
    StageContext,
    PipelineError,
    validate_pipeline,
    plan_pipeline,
)

from loom.pipeline.execution import PipelineRunner
from loom.pipeline.executors import LocalExecutor
from loom.pipeline.stores import LocalRunStore, LocalArtifactStore
```

### 20.1 Validation

```python
from loom.pipeline import validate_pipeline

validate_pipeline(spec)
```

Should raise a path-aware `PipelineValidationError` or return a structured
validation result. Raising is simpler for v0.

### 20.2 Planning

```python
from loom.pipeline import plan_pipeline

plan = plan_pipeline(
    spec,
    run_store=run_store,
    artifact_store=artifact_store,
    resume=True,
    selectors=selectors,
)
```

Planning should not invoke stages.

### 20.3 Running

```python
from loom.pipeline.execution import PipelineRunner

runner = PipelineRunner(
    run_store=run_store,
    artifact_store=artifact_store,
    executor=LocalExecutor(),
)

result = runner.run(spec, resolved_config=cfg)
```

The runner should return a structured result:

```text
run_id
run_dir
final status
stage results
artifact index
plan
```

---

## 21. CLI Integration

Functional CLI integration is future roadmap work. V1-post is Python-API-only:
it provides public Python pipeline/config APIs and no functional `loom` CLI
commands or console script entry points. When implemented, the pipeline package
should support CLI commands without becoming CLI-specific.

Future CLI commands can call Python APIs:

```text
loom validate experiment.yaml
loom plan experiment.yaml
loom run experiment.yaml
loom stage run --run-dir RUN_DIR --stage STAGE
loom status RUN_DIR
loom logs RUN_DIR STAGE
loom artifacts list RUN_DIR
```

### 21.1 `loom validate`

Should:

```text
compose config
expand recipes
resolve interpolation
build PipelineSpec
validate pipeline DAG and stage specs
not run stages
```

### 21.2 `loom plan`

Should:

```text
compose config
build PipelineSpec
open or create run planning context
compute execution plan
print stage actions and reasons
not run stages
```

### 21.3 `loom run`

Should:

```text
compose config
persist resolved config
build PipelineSpec
plan execution
run selected stages
write run status
return non-zero on failure
```

### 21.4 `loom stage run`

Post-v0.

Should:

```text
load run directory
load resolved config and pipeline spec
bind inputs for one stage
run exactly that stage
write status/outputs/failure metadata
```

This command is required for post-v0 subprocess, SLURM, and container execution.

---

## 22. Error Model

Recommended hierarchy:

```python
class PipelineError(LoomError): ...
class PipelineValidationError(PipelineError): ...
class PipelinePlanningError(PipelineError): ...
class StageExecutionError(PipelineError): ...
class StageContractError(PipelineError): ...
class ArtifactBindingError(PipelineError): ...
class ResumeError(PipelineError): ...
```

### 22.1 Validation Error Example

```text
Invalid pipeline input binding.

Stage:
  summarize

Input:
  manifest

Reference:
  build_manifest.manifest

Reason:
  stage "build_manifest" does not declare output "manifest"
```

### 22.2 Cycle Error Example

```text
Pipeline DAG contains a cycle.

Cycle:
  prepare -> train -> evaluate -> prepare
```

### 22.3 Stage Contract Error Example

```text
Stage returned an undeclared output.

Stage:
  train

Output:
  checkpoint_latest

Declared outputs:
  best_checkpoint
```

### 22.4 Resume Error Example

```text
Cannot reuse previous stage output.

Stage:
  train

Reason:
  fingerprint matched but required artifact is missing

Artifact:
  train.best_checkpoint

Path:
  runs/example/artifacts/train/best.ckpt
```

---

## 23. Testing Strategy

### 23.1 Spec Tests

Test:

```text
PipelineSpec construction
StageSpec construction
OutputSpec validation
stage name validation
input reference parsing
pipeline default application
```

### 23.2 DAG Tests

Use synthetic pipeline shapes:

```text
linear DAG
branching DAG
diamond DAG
unordered authored stages
cycle error
missing stage reference
missing output reference
depends_on-only edge
```

### 23.3 Planner Tests

Test:

```text
topological order
resume reuse
missing output rerun
fingerprint mismatch rerun
downstream invalidation
from-stage selector
only-stage selector
force-stage selector
skip-stage selector
blocked downstream stage
```

### 23.4 Runner Tests

Use dummy stages:

```text
WriteArtifactStage
ReadArtifactStage
FailingStage
MissingOutputStage
ExtraOutputStage
SleepStage
```

Test:

```text
successful run
status transitions
inputs.json writes
outputs.json writes
artifact index updates
failure metadata writes
rerun after failure
reuse after success
interrupted RUNNING state handling
```

### 23.5 Executor Tests

Test:

```text
local executor calls stage.run
local executor captures exceptions
subprocess command construction
subprocess exit code handling
subprocess log path recording
SLURM script generation later without real submission
```

### 23.6 Contract Tests

Provide reusable dummy stages and fixtures so downstream packages can validate
their own stages against the `loom.pipeline` contract.

Examples:

```text
assert stage returns declared ArtifactRefs
assert stage writes outputs via context.local_output_path
assert stage can run with synthetic ArtifactRefs
```

---

## 24. Implementation Plan Sketch

Items 1-12 align with the v0 plan. Items 13-15 are post-v0 and must not be
implemented during v0 phase work.

Build in this order:

1. `PipelineSpec`, `StageSpec`, `OutputSpec`, and validation helpers.
2. Logical artifact reference parser.
3. DAG construction and deterministic topological sorting.
4. `Stage` protocol and `StageContext`.
5. Local run and artifact store interfaces needed by the runner.
6. Execution plan and stage action model.
7. Fingerprint computation for stage plans.
8. Local executor.
9. Pipeline runner lifecycle with status writes.
10. Stage output validation and artifact index updates.
11. Resume/reuse planning.
12. Stage selectors: `from_stage`, `only_stages`, `force_stages`,
    `skip_stages`.
13. Subprocess stage command support, post-v0.
14. CLI wrappers for validate, plan, run, and stage run, post-v0.
15. SLURM executor support after subprocess mode is stable, post-v0.

Each step should include focused tests before the next step depends on it.

---

## 25. Summary

`loom.pipeline` should be the narrow orchestration layer inside `loom`.

It should support:

```text
explicit static DAGs
stage specs
structural stage protocol
stage contexts
artifact-based input/output binding
deterministic planning
local execution
status tracking
fingerprint-based resume
stage selectors
path-aware errors
thin CLI integration
```

It should avoid:

```text
domain-specific stage types
implicit Python object passing between stages
runtime DAG mutation
nested task scheduling
general distributed scheduler behavior
complex conditional expression languages
heavy runtime dependencies
```

This keeps `loom.pipeline` useful as a reliable research pipeline kernel while
leaving concrete scientific, modeling, and analysis behavior in project code.
