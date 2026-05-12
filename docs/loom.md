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

V0 scope is intentionally narrower than the long-term specification below. V0
supports local in-process execution through the Python API, inspectable local
run directories, and import-safe unsupported CLI stubs only. Functional CLI
commands, subprocess workers, SLURM execution, containers, sweeps, remote
stores, plugin discovery, retries, timeouts, cleanup, retention, and v1 config
composition are roadmap work after v0.

V1-post adds config composition through public Python APIs only. It still does
not expose functional CLI commands, remote stores, sweeps, `_copy_`, or default
resolved composed-config snapshots.

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
local execution
post-v0 subprocess/SLURM execution
sweep orchestration
provenance capture
generic runtime events for external observers
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

Recommended long-term policy:

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

The v0 implementation plan intentionally uses a narrower packaging path: the
package has no runtime dependencies until config composition lands, then
OmegaConf, Pydantic v2, and YAML support become hard runtime dependencies. This
keeps the initial validation matrix small while the public runtime API settles.
Revisit optional config extras after v0 if downstream users need a
primitives-only install.

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
      factory:
        _target_: project.stages.BuildIndexStage
      outputs:
        index:
          artifact_type: json
          codec_key: json.v1

    - name: summarize
      factory:
        _target_: project.stages.SummarizeStage
      depends_on: [build_index]
      inputs:
        index: build_index.index
      outputs:
        summary:
          artifact_type: text
          codec_key: text.v1
```

`loom` validates and runs this graph. The stage classes live in user code.

### 6.5 Stage Context

Each stage receives a `StageContext` with run metadata, config, and artifact
helpers.

```python
class Stage:
    def run(self, context, inputs):
        ...
```

For v0 the stage contract is `run(context, inputs) -> Mapping[str, ArtifactRef]`.
Callable stages, context-collected outputs, and alternate result objects are
post-v0.

Phase 6 defines the minimal context shape:

```text
run_uri
stage_name
resolved_config
stage_config
provenance
metadata
```

Use local facade methods on the context for outputs, workspace paths, and artifact
loading/saving. Pipeline internals remain the stable contract owner for path and
state persistence.

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
  stages:
    - name: build_manifest
      factory:
        _target_: project.stages.BuildManifestStage
      config:
        source: ${data.source}
      outputs:
        manifest:
          artifact_type: manifest
    - name: summarize
      factory:
        _target_: project.stages.SummarizeStage
      depends_on: [build_manifest]
      inputs:
        manifest: build_manifest.manifest
      outputs:
        summary:
          artifact_type: text
          codec_key: text.v1
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
stage status tracking
resume decisions
artifact collection
run finalization
```

Subprocess execution, SLURM submission, and container execution are post-v0.
V0 should expose local in-process execution only.

The runner should treat stages as black boxes with explicit inputs, outputs, and metadata.

---

## 9. Run Directory

Every run should have a stable directory layout.

The original v0 layout used resolved config snapshots for caller-provided
runtime config mappings. Current v1 composed-config runs instead persist
artifact-safe config records and do not write default resolved snapshots.

```text
runs/RUN_ID/
  run.json
  status.json
  plan.json
  artifacts.json

  config/
    composition_manifest.json
    recipe_manifest.json

  stages/
    STAGE_NAME/
      status.json
      inputs.json
      outputs.json
      fingerprint.json
      failure.json (failed stages only)
      provenance.json
      logs/
        stdout.log
        stderr.log

  artifacts/
    STAGE_NAME/
      ...

  provenance/
    environment.json
    git.json
    command.json
    dependencies.json

```

For composed configs, config provenance is recorded in run metadata as
artifact-safe plain data. `loom.config` returns in-memory resolved config to
Python callers, while the run-store defaults avoid resolver outputs, raw source
bytes, and full `config/resolved.yaml` / `config/resolved.redacted.yaml`
snapshots. Plain mapping configs may still use legacy snapshot names as
caller-provided runtime data.

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

V0 defaults to conservative same-run reuse:

```text
reuse if status is SUCCEEDED and policy/docs checks remain valid
rerun for RUNNING, FAILED, stale state, malformed state, or checksum mismatch
do not reuse stages across different run directories
```

Stages can opt into stricter or looser checks through declared policies, but default behavior should be conservative.

---

## 11. Provenance

Long-term provenance work should be able to record the following facts when the
corresponding feature exists:

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

Current v1-post composed-config defaults are narrower: runner persistence writes
`config/composition_manifest.json`, `config/recipe_manifest.json`, and
artifact-safe config provenance in run metadata. It does not write default raw
config, resolved config, redacted resolved config, or CLI override snapshot
files for composed configs.

Provenance structures should remain generic. User code can add application-specific metadata to records, resources, artifacts, and stage provenance.

---

## 12. Public API

Minimum viable API:

```python
from loom.refs import ResourceRef
from loom.records import Record, InMemoryManifest, ManifestView
from loom.artifacts import ArtifactAddress, ArtifactRef
from loom.fingerprints import hash_mapping

from loom.config import (
    RecipeCatalog,
    compose_config,
    compose_config_with_catalog,
    instantiate,
    register_recipe,
)
from loom.pipeline import (
    PipelineSpec,
    StageFactorySpec,
    StageSpec,
    StageContext,
    PipelineRunner,
)
```

The public API should stay small until repeated usage shows that more helpers are worth carrying.

Migration and rename notes for the v0 hardening closeout are in
[v0 public API migration notes](briefs/v0_public_api_migration_notes.md).

---

## 13. CLI

The functional CLI remains future roadmap work. V1-post is Python-API-only and
does not expose functional `loom` commands or console script entry points. Older
v0 import-safe CLI modules, when present, fail with an explicit unsupported
error.

Future `loom` CLI work can expose low-level commands:

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
the logical artifact key and the source document/path when relevant
```

---

## 15. Initial Implementation Plan

Build `loom` in small, testable layers:

1. Core value objects: IDs, resource refs, artifact refs, records, manifests.
2. Config loading, merging, overrides, recipe expansion, and `_target_` instantiation.
3. Pipeline specs, stage context, local runner, and run directory layout.
4. Provenance capture and stage fingerprints.
5. Resume behavior.
6. Hardening, docs, and import-safe unsupported CLI stubs for v0.

Roadmap versions after v0 add capabilities incrementally. V1-post adds Python
API config composition; functional CLI wrappers, subprocess execution, SLURM
execution, containers, sweeps, remote stores, plugin discovery, retries,
timeouts, cleanup, retention, and broader reliability policies remain future
work.

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
