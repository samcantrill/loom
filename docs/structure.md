# `loom` Project Structure and Module Guide

This document describes the intended project structure for `loom`, a generic
Python runtime for composing, running, and tracing reproducible research
pipelines.

It is the canonical source-tree map for the design in [loom.md](loom.md). Use
[loom.md](loom.md) for the product-level specification, use this document for
repository layout and module ownership, and use the individual module documents
in `docs/` for detailed contracts.

Ownership rule:

```text
loom.md owns runtime purpose, goals, non-goals, concepts, and user-facing
behavior.

structure.md owns source-tree layout, package boundaries, import direction,
module responsibilities, and documentation routing.
```

The current package implementation is intentionally small while the v0 runtime is
being built in phases:

```text
src/loom/
  __init__.py
  py.typed
```

The structure below is therefore the target architecture for v0 and near-term
growth. Do not add empty placeholder files unless a phase needs the import path,
a test needs the public surface, or an unsupported stub makes a future public API
explicit.

---

## 1. Source-Tree Boundary

The central boundary is:

```text
loom:
  generic pipeline, configuration, artifact, provenance, I/O, and execution
  mechanics

project code:
  concrete task implementations and application-specific data semantics
```

`loom` may know how to describe, configure, construct, run, resume, and inspect
artifact-based workflows. It must not know what a domain-specific dataset,
model, metric, plot, report, checkpoint, or analysis object means.

Allowed direction:

```text
project package -> loom
```

Forbidden direction:

```text
loom -> project package
```

If a generic `loom` module imports a downstream research package, the boundary
has failed.

---

## 2. Repository Layout

The repository is organized around a typed source package, specifications, tests,
and project-scoped Codex workflow metadata.

```text
.
  pyproject.toml
  README.md
  AGENTS.md

  src/
    loom/
      __init__.py
      py.typed

  docs/
    loom.md
    structure.md
    implementation-plans/
      implementation-plan-v0.md
    features/
      core-model.md
      timestamps.md
      config.md
      serialization.md
      io.md
      artifacts.md
      pipeline.md
      pipeline-graph.md
      runtime-resources.md
      execution.md
      run-store.md
      state.md
      fingerprints.md
      provenance.md
      resume.md
      preflight.md
      run-catalog.md
      sweeps.md
      slurm.md
      container-executors.md
      remote-stores.md
      reliability.md
      plugins.md
      protocols.md
      errors.md
      cli.md
      testing.md

  tests/
    README.md
    package/
      test_import.py

  tools/
    __init__.py
    test_harness/
      __init__.py
      __main__.py
      cli.py

  .codex/
    agents/
    plans/
    prompts/
```

### 2.1 `src/loom`

The Python package. Runtime code belongs here. Public imports should be stable,
typed, and cheap to import.

### 2.2 `docs`

Design and implementation specifications. These documents are not only prose;
they define module boundaries, contracts, test expectations, and deferred work.

### 2.3 `tests`

Package, unit, integration, contract, and end-to-end tests. The initial tests are
package-level import checks. Additional tests should mirror the source layout as
modules are implemented.

### 2.4 `tools`

Repository-local development tools. These may use package-like structure when a
tool needs a CLI entrypoint or room to grow, but they are not runtime modules,
public `loom` APIs, or downstream test helpers.

### 2.5 `.codex`

Project-scoped agent definitions, prompts, and workflow plans. These files guide
phase planning and review; they should not be imported by the runtime package.

---

## 3. Target Source Tree

The target architecture keeps foundational public vocabulary near the top level
and splits subsystems that are expected to grow multiple implementations.

```text
src/loom/
  __init__.py
  py.typed

  ids.py
  refs.py
  artifacts.py
  fingerprints.py
  protocols.py
  errors.py
  timestamps.py

  records/
    __init__.py
    base.py
    manifest.py
    views.py
    filters.py
    errors.py

  provenance/
    __init__.py
    models.py
    capture.py
    git.py
    environment.py
    packages.py
    errors.py

  serialization/
    __init__.py
    plain.py
    dataclasses.py
    json.py
    yaml.py
    schema.py
    errors.py

  io/
    __init__.py
    uris.py
    errors.py

    sources/
      __init__.py
      base.py
      local.py
      registry.py
      errors.py

    codecs/
      __init__.py
      base.py
      json_codec.py
      text_codec.py
      bytes_codec.py
      registry.py
      errors.py

  config/
    __init__.py
    api.py
    load.py
    compose.py
    merge.py
    overrides.py
    interpolation.py
    validation.py
    redaction.py
    provenance.py
    errors.py

    recipes/
      __init__.py
      base.py
      catalog.py
      expansion.py
      errors.py

    instantiate/
      __init__.py
      targets.py
      recursive.py
      injection.py
      errors.py

  pipeline/
    __init__.py
    specs.py
    stage.py
    context.py
    status.py
    validation.py
    selectors.py
    resources.py
    runtime.py
    errors.py

    graph/
      __init__.py
      dag.py
      topology.py
      bindings.py

    planning/
      __init__.py
      plan.py
      planner.py
      resume.py
      invalidation.py

    execution/
      __init__.py
      runner.py
      lifecycle.py
      atomic.py
      logs.py

    executors/
      __init__.py
      base.py
      local.py
      subprocess.py
      slurm.py
      registry.py
      errors.py

    stores/
      __init__.py
      artifact_store.py
      run_store.py
      indexes.py
      local_artifacts.py
      local_runs.py
      atomic.py
      locking.py
      errors.py

    sweep/
      __init__.py
      spec.py
      grid.py
      manual.py
      trials.py
      runner.py
      errors.py

  plugins/
    __init__.py
    entrypoints.py
    errors.py

  cli/
    __init__.py
    main.py
    validate.py
    plan.py
    run.py
    stage.py
    sweep.py
```

This tree is intentionally more specific than [loom.md](loom.md). This document
owns package-versus-file choices and should be updated whenever the target source
layout changes.

---

## 4. Import and Dependency Shape

Imports should flow from foundational modules into higher-level subsystems.
Higher-level modules should not pull execution behavior into core types.

Recommended dependency direction:

```text
ids / timestamps / errors
        |
        v
refs / records / artifacts / protocols
        |
        v
serialization / fingerprints / provenance
        |
        v
io / config / pipeline stores
        |
        v
pipeline planning / pipeline execution / sweeps / plugins
        |
        v
cli
```

Important boundaries:

```text
serialization = Python objects <-> plain structured data
io            = bytes, files, URIs, source backends, codecs
stores        = run/artifact directory policy, atomic writes, indexes
pipeline      = DAG validation, planning, stage orchestration, resume
config        = config composition, recipe expansion, `_target_` construction
cli           = presentation over Python APIs
```

Avoid these import directions:

```text
loom.__init__ -> config, pipeline runners, plugin discovery, optional backends
refs / records / artifacts -> io
serialization -> io
io -> pipeline.runner
config -> pipeline execution internals
executors -> config composition internals
stores -> concrete project code
loom -> downstream project packages
```

---

## 5. Public API Policy

The public vocabulary should be easy to import and stable across internal
refactors.

Preferred public imports:

```python
from loom.refs import ResourceRef
from loom.records import Record, InMemoryManifest, ManifestView
from loom.artifacts import ArtifactRef
from loom.fingerprints import hash_mapping
from loom.config import compose_config, instantiate, register_recipe
from loom.pipeline import PipelineSpec, StageSpec, StageContext, PipelineRunner
```

`loom.__init__` should remain cheap. It may re-export stable, foundational types
once those types exist, but it must not import optional dependency paths,
pipeline runners, CLI modules, executor backends, or plugin discovery.

Stable imports matter more than stable internal files. For example, the
implementation behind `loom.records` may move between internal files as long as
this stays valid:

```python
from loom.records import Record
```

---

## 6. Module Responsibilities

### 6.1 Core Model

Detailed specifications: [core-model.md](features/core-model.md),
[timestamps.md](features/timestamps.md), [protocols.md](features/protocols.md),
[errors.md](features/errors.md)

```text
ids.py
  Semantic string aliases such as RunID, StageID, RecordID, ArtifactID,
  ResourceKey, and CodecKey. Keep these lightweight until wrapper types solve a
  demonstrated problem.

refs.py
  ResourceRef, a serializable pointer to an input resource. It records URI,
  resource type, codec key, schema version, checksum, and generic metadata. It
  must not load data.

records/
  Record, manifest protocols, in-memory manifests, views, and generic filters.
  Records group ResourceRefs and plain metadata under stable identifiers.

artifacts.py
  ArtifactRef, a serializable pointer to a produced pipeline output. Artifact
  loading and path allocation belong to stores and codecs, not the value object.

fingerprints.py
  Deterministic hashing helpers for semantic production inputs. Fingerprints
  answer whether a stage should be reused; checksums answer whether bytes match.

protocols.py
  Only package-wide structural protocols that are genuinely generic. Subsystem
  protocols belong next to their subsystem.

timestamps.py
  UTC timestamp helpers and path-safe timestamp formatting.

errors.py
  Root error hierarchy and shared error context used by subsystem errors.
```

### 6.2 Serialization

Detailed specification: [serialization.md](features/serialization.md)

`loom.serialization` converts Python objects to and from plain structured data.
It owns deterministic JSON/YAML-safe representations, dataclass conversion, and
schema-version checks. It does not open files, resolve URIs, choose codecs, or
write run-store documents atomically.

Expected modules:

```text
plain.py        plain data checks and conversion
dataclasses.py  dataclass-specific conversion helpers
json.py         canonical and pretty JSON helpers
yaml.py         optional YAML helpers
schema.py       versioned document checks
errors.py       serialization-specific errors
```

### 6.3 I/O

Detailed specification: [io.md](features/io.md)

`loom.io` handles URI parsing, source backends, and codecs. It bridges stored
bytes/text with Python objects but does not own artifact-store layout or
pipeline state.

Expected modules:

```text
uris.py             URI parsing and file URI conversion
sources/base.py     DataSource protocol
sources/local.py    local filesystem source
sources/registry.py source lookup by URI scheme
codecs/base.py      Codec protocol
codecs/json_codec.py
codecs/text_codec.py
codecs/bytes_codec.py
codecs/registry.py  codec lookup by key
errors.py           I/O-specific errors
```

Project packages may register domain codecs. `loom` should provide only generic
JSON, text, and bytes codecs unless a later phase establishes another generic
need.

### 6.4 Configuration

Detailed specification: [config.md](features/config.md)

`loom.config` composes trusted project configuration and constructs Python
objects. It loads YAML, applies overlays and CLI overrides, resolves
interpolation, expands named recipes, validates stable boundaries, instantiates
`_target_` object graphs, records config provenance, and redacts secrets for
safe persisted output.

Expected modules:

```text
api.py                 public composition and construction entrypoints
load.py                config file loading
compose.py             base config, overlays, and override orchestration
merge.py               merge semantics
overrides.py           CLI/dot-path override parsing
interpolation.py       interpolation resolution
validation.py          stable boundary validation
redaction.py           secret redaction
provenance.py          config provenance documents
recipes/              named recipe contracts, catalog, and expansion
instantiate/           importlib target resolution and recursive construction
errors.py              config-specific errors
```

`loom.config` is not the workflow engine. It may produce or instantiate pipeline
specs, but execution belongs to `loom.pipeline`.

### 6.5 Pipeline Model and Planning

Detailed specifications: [pipeline.md](features/pipeline.md),
[pipeline-graph.md](features/pipeline-graph.md),
[runtime-resources.md](features/runtime-resources.md)

`loom.pipeline` models static artifact DAGs, validates dependencies, binds
upstream artifacts to downstream inputs, plans stage actions, and exposes the
stage contract used by project code.

Expected modules:

```text
specs.py          PipelineSpec and StageSpec
stage.py          Stage protocol
context.py        StageContext passed to stage implementations
status.py         run and stage status values
validation.py     spec and contract validation
selectors.py      stage selection helpers
resources.py      generic runtime/resource hints
runtime.py        runtime profile types
graph/            DAG construction, topology, and binding validation
planning/         execution plans, resume decisions, invalidation policy
errors.py         pipeline-specific errors
```

Pipeline specs describe work. Project stage objects do the work. `loom.pipeline`
should not contain domain-specific stage subclasses.

### 6.6 Execution and Executors

Detailed specifications: [execution.md](features/execution.md),
[slurm.md](features/slurm.md),
[container-executors.md](features/container-executors.md)

`loom.pipeline.execution` coordinates the runner lifecycle. It prepares stages,
uses planning decisions, constructs stage contexts, invokes executors, commits
validated outputs, records logs and failures, and finalizes runs.

`loom.pipeline.executors` owns stage invocation mechanisms:

```text
base.py        Executor protocol and request/result types
local.py       in-process execution
subprocess.py  process-isolated execution, deferred until needed
slurm.py       SLURM script/submission scaffolding, deferred until needed
registry.py    executor lookup by name
errors.py      executor-specific errors
```

Executors adapt where and how a stage invocation runs. They should not own DAG
semantics, resume policy, config composition, or artifact indexes.

### 6.7 Stores and State

Detailed specifications: [run-store.md](features/run-store.md),
[state.md](features/state.md), [artifacts.md](features/artifacts.md),
[remote-stores.md](features/remote-stores.md),
[run-catalog.md](features/run-catalog.md)

Stores persist the inspectable state of a run. Local stores should use ordinary
files so a failed or completed run can be inspected without importing Python.

Expected modules:

```text
artifact_store.py  ArtifactStore protocol
run_store.py       RunStore protocol
indexes.py         run-level artifact and stage indexes
local_artifacts.py local filesystem artifact storage
local_runs.py      local run directory state
atomic.py          atomic file write helpers
locking.py         lock helpers, initially conservative/deferred
errors.py          store-specific errors
```

The local run directory should make these concerns visible:

```text
config/
stages/
artifacts/
provenance/
run.json
status.json
artifacts.json
plan.json
```

The runner owns lifecycle transitions. Stores persist those transitions.

### 6.8 Provenance and Resume

Detailed specifications: [provenance.md](features/provenance.md),
[resume.md](features/resume.md), [fingerprints.md](features/fingerprints.md),
[reliability.md](features/reliability.md)

Provenance records how a run was produced: config inputs, recipe expansions,
target imports, command line, working directory, git state, Python and package
versions, stage fingerprints, inputs, outputs, and generic metadata.

Resume uses stage fingerprints and persisted artifacts to decide whether to run,
reuse, skip, or fail a stage. V0 resume should be conservative and limited to the
same run directory.

### 6.9 Sweeps

Detailed specification: [sweeps.md](features/sweeps.md)

`loom.pipeline.sweep` expands parameter sets into multiple run configurations
and coordinates trial execution through the same config, planning, execution, and
store APIs as normal runs.

Sweeps should remain generic. They should not become a hyperparameter optimizer,
experiment database, or scheduler replacement in v0.

### 6.10 Plugins

Detailed specification: [plugins.md](features/plugins.md)

`loom.plugins` provides future extension discovery through entry points and
registration hooks. The initial runtime should not require plugin discovery for
normal imports.

Plugin loading must be explicit enough to avoid surprising import side effects.
Plugin code may register recipes, codecs, sources, executors, or CLI extensions
through documented APIs.

### 6.11 CLI

Detailed specifications: [cli.md](features/cli.md),
[preflight.md](features/preflight.md), [run-catalog.md](features/run-catalog.md)

`loom.cli` owns command-line presentation. It parses arguments, calls public
Python APIs, formats results, maps errors to exit codes, and exposes thin
commands such as validate, plan, run, stage, sweep, status, logs, and artifacts.

The CLI must not duplicate config, pipeline, store, or resume logic.

---

## 7. Documentation Map

Use the docs this way:

```text
loom.md
  Product-level purpose, goals, non-goals, dependency policy, core concepts, and
  minimum public API.

structure.md
  Source-tree layout, package boundaries, module ownership, dependency shape, and
  repository organization.

features/core-model.md
  Foundational public types: identifiers, resource refs, records, manifests,
  artifact refs, timestamps, and core validation.

features/timestamps.md
  UTC timestamp helpers, canonical persisted timestamp strings, and path-safe
  timestamp formatting.

features/config.md
  Config loading, composition, overrides, interpolation, recipes, target
  instantiation, redaction, and config provenance.

features/serialization.md
  Plain data model, deterministic JSON/YAML helpers, schema-version checks, and
  object conversion boundaries.

features/io.md
  URI helpers, source backends, codecs, source registries, and codec registries.

features/artifacts.md
  ArtifactRef, ArtifactStore, LocalArtifactStore, artifact identities, codecs,
  validation, and artifact lineage.

features/pipeline.md
  Static DAG specs, stages, contexts, graph validation, binding, planning, and
  orchestration boundaries.

features/pipeline-graph.md / features/runtime-resources.md
  DAG construction, topology, artifact binding, runtime options, resource
  requests, and runtime profiles.

features/execution.md
  Runner lifecycle, execution requests/results, executor protocol, logs,
  failures, context construction, and backend integration.

features/run-store.md / features/state.md
  Run directory layout, persisted documents, state transitions, atomic writes,
  indexes, locking policy, and inspection.

features/fingerprints.md / features/resume.md
  Stable hashing, stage fingerprint documents, invalidation inputs, and
  conservative same-run-directory reuse.

features/provenance.md
  Generic run, stage, code, environment, dependency, and config provenance.

features/preflight.md / features/run-catalog.md
  Pre-run diagnostics, local run indexing, run comparison, export, and import
  behavior.

features/sweeps.md / features/slurm.md / features/plugins.md / features/cli.md
  Optional orchestration surfaces and operational integration points.

features/container-executors.md / features/remote-stores.md /
features/reliability.md
  Container runtimes, optional remote artifact backends, retries, timeouts,
  cleanup, event hooks, and retention policies.

features/testing.md
  Test layout, package tests, unit tests, integration tests, contract tests, and
  validation gates.

implementation-plans/implementation-plan-v0.md
  Review-gated v0 phase plan, phase status, accepted tradeoffs, and deferred
  v0 scope boundaries.
```

---

## 8. Test Layout

Tests should scale with the source tree.

Recommended layout:

```text
tests/
  package/
    test_import.py

  unit/
    test_refs.py
    test_artifacts.py
    records/
    serialization/
    io/
    config/
    pipeline/

  integration/
    test_local_run.py
    test_resume.py

  contracts/
    test_codec_contract.py
    test_source_contract.py
    test_stage_contract.py
    test_store_contract.py

  support/
    stages.py
    configs/
```

Package tests should protect cheap imports and `py.typed`. Unit tests should
mirror module boundaries. Integration tests should use small synthetic pipelines
that prove config, planning, stores, execution, artifacts, provenance, and resume
work together without adding domain assumptions.

---

## 9. Runtime Dependency Policy

`loom` should minimize hard runtime dependencies.

Recommended policy:

```text
core model:
  standard library only

serialization:
  standard library first; optional YAML support only when enabled

io:
  standard library local files and simple codecs first

config:
  may introduce OmegaConf, Pydantic v2, and YAML support when config
  implementation begins

pipeline:
  standard library first

SLURM:
  shell/subprocess-based scaffolding; no required Python SLURM dependency
```

Do not introduce heavyweight runtime dependencies for domain behavior. Downstream
projects should depend on their own scientific, ML, plotting, storage, or report
libraries.

---

## 10. What Stays Out of `loom`

Keep these out of the generic runtime:

```text
dataset-specific parsing
task-specific preprocessing
domain-specific resource subclasses
domain-specific artifact subclasses
model definitions
loss functions
optimizers
training loops
metrics
analysis plots
report templates
domain recipes
domain stages
domain codecs, unless supplied by a downstream package
```

Generic extension points should make those behaviors easy for project packages to
provide without putting the behavior in `loom` itself.

---

## 11. Implementation Guidance

When adding modules:

1. Start with the smallest public surface needed by the current phase.
2. Keep imports cheap and avoid optional dependency paths at import time.
3. Prefer frozen dataclasses, structural protocols, explicit registries, and
   plain data conversion where they match the documented boundary.
4. Add focused tests for the new behavior and import boundaries.
5. Keep unsupported future APIs explicit if a public path must exist before the
   behavior is implemented.
6. Preserve stable imports when splitting files into packages.
7. Record accepted technical debt and revisit triggers in the relevant module
   doc or phase plan.

The repository phase workflow in `AGENTS.md` and
`docs/implementation-plans/implementation-plan-v0.md` controls large
implementation work. This structure document should guide those phases but
should not be treated as permission to implement future phases early.

---

## 12. Review Checklist

Use this checklist when adding or reviewing structure changes:

```text
Does the new module belong in `loom`, or in project code?
Does the import direction follow the documented dependency shape?
Is the public import path stable?
Can `import loom` stay cheap?
Does the module introduce an optional or heavyweight dependency?
Is serialization still separate from I/O?
Is pipeline orchestration separate from stage internals?
Is persistence policy in stores rather than in value objects?
Is CLI behavior a thin wrapper around Python APIs?
Are tests placed near the source boundary they protect?
Do the relevant docs mention any accepted debt or deferred behavior?
```
