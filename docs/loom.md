# `loom` Specification

## 1. Purpose

`loom` is a lightweight runtime for composing, running, and tracing reproducible research pipelines.

It provides the generic scaffolding needed to describe work, construct configured Python objects, execute pipeline stages, record artifacts, resume previous work, and preserve provenance. It should not encode application-specific assumptions. Project code supplies concrete stages, data adapters, models, metrics, reports, and analysis behavior.

The central boundary is:

```text
loom:
  generic pipeline, configuration, artifact, provenance, and execution mechanisms

project code:
  concrete task implementations and application-specific data semantics
```

`loom` should remain useful and testable on its own.

---

## 2. Design Goals

`loom` should provide:

```text
configuration composition
recursive importlib object construction
named recipe expansion
resource references
record and manifest abstractions
artifact references
artifact storage
pipeline DAGs
stage execution
run directories
stage status tracking
fingerprints and resume logic
local/subprocess/SLURM execution scaffolding
sweep orchestration
provenance capture
clear error handling
```

The design should make `loom` responsible for workflow mechanics and user code responsible for concrete work.

---

## 3. Non-Goals

`loom` should not implement application-specific behavior such as:

```text
dataset-specific parsing
task-specific preprocessing
model definitions
loss functions
optimizers
training loops
metrics
analysis plots
report templates
application-specific artifact schemas
application-specific recipes
application-specific stages
```

It should also avoid becoming a general-purpose workflow engine with too many features too early. The goal is to provide enough infrastructure for controlled, reproducible research pipelines, not to replace mature systems such as Snakemake, DVC, Prefect, or Dagster.

---

## 4. Dependency Policy

`loom` should minimize hard dependencies.

Recommended policy:

```text
loom primitives:
  standard library only

loom.config:
  may depend on OmegaConf and/or Pydantic if installed with config extras

loom.pipeline:
  standard library first

loom.pipeline.executors.slurm:
  shell/subprocess-based; no required Python SLURM dependency
```

Recommended package extras:

```toml
[project.optional-dependencies]
config = [
  "omegaconf>=2.3",
  "pydantic>=2",
]
slurm = []
dev = [
  "pytest",
  "ruff",
  "pyright",
]
```

Avoid hard dependencies on large task-specific libraries. User projects can depend on those libraries as needed.

---

## 5. Relationship to Source Structure

The canonical source-tree map lives in [structure.md](structure.md). This
document intentionally stays at the product/runtime level:

```text
loom.md:
  purpose, design goals, non-goals, dependency policy, core concepts, public API,
  execution model, provenance, resume, CLI intent, and error model

structure.md:
  repository layout, target source tree, package boundaries, module ownership,
  dependency direction, docs map, test layout, and source-structure review
  checklist
```

When package ownership, import paths, or module layout changes, update
[structure.md](structure.md). When runtime goals, public concepts, non-goals, or
user-facing behavior changes, update this document.

---

## 6. Core Concepts

### 6.1 Resource References

A `ResourceRef` is a typed pointer to an input resource.

```python
from loom.refs import ResourceRef

ref = ResourceRef(
    uri="file:///data/project/input.jsonl",
    resource_type="jsonl",
    codec_key="jsonl.v1",
    metadata={"split": "train"},
)
```

`loom` stores the `resource_type` and `codec_key` strings but does not need to know their application meaning.

### 6.2 Records and Manifests

A `Record` groups resources and metadata under a stable identifier.

```python
from loom.records import Record
from loom.refs import ResourceRef

record = Record(
    record_id="sample-001",
    resources={
        "input": ResourceRef(
            uri="file:///data/project/sample-001.json",
            resource_type="json",
            codec_key="json.v1",
        )
    },
    metadata={"split": "train"},
)
```

A manifest is a collection of records. `loom` should support in-memory manifests first, with filesystem-backed or database-backed implementations added only when needed.

### 6.3 Artifacts

An `ArtifactRef` identifies an output produced by a stage.

```python
from loom.artifacts import ArtifactRef

artifact = ArtifactRef(
    artifact_id="stage-a/output-manifest",
    uri="file:///runs/run-001/artifacts/stage-a/output-manifest.json",
    artifact_type="manifest",
    codec_key="json.v1",
)
```

Artifacts should be explicit enough to support provenance, resume checks, and downstream stage inputs.

### 6.4 Pipeline Specs

A pipeline spec describes stages and dependencies without executing them.

```yaml
pipeline:
  stages:
    - name: build_index
      _target_: project.stages.BuildIndexStage
      outputs:
        index: artifacts/index.json

    - name: summarize
      _target_: project.stages.SummarizeStage
      depends_on: [build_index]
      inputs:
        index: ${stages.build_index.outputs.index}
```

`loom` validates and runs this graph. The stage classes live in user code.

### 6.5 Stage Context

Each stage receives a `StageContext` with paths, config, artifacts, and run metadata.

```python
class Stage:
    def run(self, context):
        ...
```

The context should provide:

```text
run_id
run_dir
stage_name
stage_dir
resolved_config
input_artifacts
output_artifact_paths
logger
provenance writer
```

---

## 7. Configuration

`loom.config` composes YAML, expands recipes, applies overrides, resolves interpolation, validates structure, and constructs Python objects from `_target_` blocks.

Example:

```yaml
name: local_summary

data:
  _recipe_: local_jsonl_manifest
  root: /data/project
  pattern: "*.jsonl"

pipeline:
  _target_: loom.pipeline.specs.PipelineSpec
  stages:
    - name: build_manifest
      _target_: project.stages.BuildManifestStage
      source: ${data.source}
    - name: summarize
      _target_: project.stages.SummarizeStage
      depends_on: [build_manifest]
```

Configuration details are specified in [config.md](features/config.md).

---

## 8. Execution Model

`loom.pipeline` should support:

```text
pipeline DAG validation
stage ordering
stage context creation
local execution
subprocess execution
SLURM submission scaffolding
stage status tracking
resume decisions
artifact collection
run finalization
```

The runner should treat stages as black boxes with explicit inputs, outputs, and metadata.

---

## 9. Run Directory

Every run should have a stable directory layout.

```text
runs/RUN_ID/
  config/
    raw.yaml
    overlays.yaml
    cli_overrides.yaml
    resolved.yaml
    recipe_manifest.json

  stages/
    STAGE_NAME/
      status.json
      stdout.log
      stderr.log
      provenance.json

  artifacts/
    STAGE_NAME/
      ...

  provenance/
    environment.json
    git.json
    command.json
    dependencies.json

  run.json
```

The layout should favor debuggability over cleverness.

---

## 10. Fingerprints and Resume

Each stage should produce a fingerprint from:

```text
stage target path
stage config
input artifact references
selected environment metadata
optional user-provided fingerprint fields
loom version
```

Resume behavior should be explicit:

```text
run if no previous successful stage exists
reuse if fingerprint and required artifacts match
rerun if fingerprint changed
fail if required artifacts are missing or invalid
```

Stages can opt into stricter or looser checks through declared policies, but default behavior should be conservative.

---

## 11. Provenance

`loom` should record:

```text
raw config
resolved config
overlays
CLI overrides
recipe expansions
target import paths
run command
working directory
git commit and dirty status when available
Python version
loom version
selected dependency versions
stage fingerprints
input artifact references
output artifact references
```

Provenance structures should remain generic. User code can add application-specific metadata to records, resources, artifacts, and stage provenance.

---

## 12. Public API

Minimum viable API:

```python
from loom.refs import ResourceRef
from loom.records import Record, InMemoryManifest, ManifestView
from loom.artifacts import ArtifactRef
from loom.fingerprints import hash_mapping

from loom.config import compose_config, instantiate, register_recipe
from loom.pipeline import PipelineSpec, StageSpec, StageContext, PipelineRunner
```

The public API should stay small until repeated usage shows that more helpers are worth carrying.

---

## 13. CLI

`loom` can expose low-level commands:

```text
loom validate CONFIG
loom plan CONFIG
loom run CONFIG
loom stage run --run-dir RUN_DIR --stage STAGE
loom sweep SWEEP_CONFIG
loom inspect RUN_DIR
```

The CLI should be a thin wrapper over the Python API.

---

## 14. Error Model

Use a small error hierarchy:

```python
class LoomError(Exception): ...
class ValidationError(LoomError): ...
class ContractError(LoomError): ...
class ArtifactError(LoomError): ...
class ConfigError(LoomError): ...
class PipelineError(LoomError): ...
class ExecutionError(LoomError): ...
```

Errors should include:

```text
what failed
where it failed
the relevant config path or stage name
the target path when import or instantiation failed
the expected contract
the received value or state
```

---

## 15. Initial Implementation Plan

Build `loom` in small, testable layers:

1. Core value objects: IDs, resource refs, artifact refs, records, manifests.
2. Config loading, merging, overrides, recipe expansion, and `_target_` instantiation.
3. Pipeline specs, stage context, local runner, and run directory layout.
4. Provenance capture and stage fingerprints.
5. Resume behavior.
6. Subprocess and SLURM executor scaffolding.
7. CLI wrappers.

Each layer should include focused tests before the next layer depends on it.

---

## 16. Summary

`loom` should be a small, generic foundation for reproducible research pipelines.

Keep in `loom`:

```text
configuration mechanics
object construction
resource and artifact references
record and manifest abstractions
pipeline execution scaffolding
run directories
status tracking
fingerprints
resume logic
provenance
generic CLI primitives
```

Keep out of `loom`:

```text
application-specific data types
application-specific codecs
application-specific parsers
application-specific preprocessing
application-specific model or analysis code
application-specific recipes
application-specific stages
```

The result should be a focused runtime that project code can build on without forcing project-specific concepts into the core package.
