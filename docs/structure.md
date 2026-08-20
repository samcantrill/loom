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
    briefs/
      <feature-brief>.md
    roadmap.md
    roadmap/
      stage-<id>/
        planning.md
        implementation-plan.md
        phases/
          <phase-execution-plan>.md
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
    templates/
```

### 2.1 `src/loom`

The Python package. Runtime code belongs here. Public imports should be stable,
typed, and cheap to import.

### 2.2 `docs`

Design and implementation specifications. These documents are not only prose;
they define module boundaries, contracts, test expectations, and deferred work.
Feature briefs capture approved intent before specification work. Phase
execution plans under `docs/roadmap/stage-<id>/phases/` capture the decision-complete how for one
implementation phase.

### 2.3 `tests`

Package, unit, integration, contract, and end-to-end tests. The initial tests are
package-level import checks. Additional tests should mirror the source layout as
modules are implemented.

### 2.4 `tools`

Repository-local development tools. These may use package-like structure when a
tool needs a CLI entrypoint or room to grow, but they are not runtime modules,
public `loom` APIs, or downstream test helpers.

### 2.5 `.codex`

Project-scoped agent definitions, prompts, templates, and workflow plans. Custom
agents define role authority, prompts define behavior, and templates define
durable workflow artifacts. These files guide phase execution planning and
review; they should not be imported by the runtime package.

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
    events.py
    locks.py
    validation.py
    selectors.py
    resources.py
    errors.py

    runtime/
      __init__.py
      _models.py

    graph/
      __init__.py
      dag.py
      topology.py
      bindings.py

    planning/
      __init__.py
      models.py
      planner.py
      selectors.py
      invalidation.py
      actions.py
      fingerprints.py
      resume.py
      explanations.py
      errors.py

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
      errors.py

    sweep/
      __init__.py
      spec.py
      grid.py
      manual.py
      trials.py
      runner.py
      errors.py

  runs/
    __init__.py
    catalog.py
    models.py
    errors.py

    _scan.py
    _extract.py
    _sqlite.py

  diagnostics/
    __init__.py
    models.py
    preflight.py

  plugins/
    __init__.py
    artifact_backends.py
    codecs.py
    diagnostics.py
    entrypoints.py
    errors.py
    event_sinks.py
    recipes.py

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

### 3.1 Cross-cutting contracts

Core value objects under `refs`, `artifacts`, `records`, and `pipeline` store
nested plain mappings and sequences in immutable structures at construction time.
Public serialization helpers such as `to_dict()` must expose thawed `dict` and
`list` trees so consumers can mutate copies without mutating object internals.

`loom.serialization.schema` owns shared persisted-document validation:

```text
- recursive plain mapping/sequence validation helpers
- required/optional field validation
- schema-version extraction and support checks
- versioned-document loader and migration dispatch
```

Migrations remain document-family-owned through explicit migration tables passed
to the schema helper entrypoints. There is no global migration registry.

Config authoring dependencies are owned by `weave`; Loom core imports should not
import composition modules at import time. Validation is split into:

- `test-no-extra` (default suites without opt-in markers)
- `test-config-extra` (config adapter workflows that use the compatibility
  `--extra config` selection and optional-dependency marker)

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
diagnostics
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
diagnostics   = reusable local readiness and inspection result models
weave         = compose_config convenience API + explicit catalog composition
cli           = presentation over Python APIs
```

Avoid these import directions:

```text
loom.__init__ -> weave, pipeline runners, plugin discovery, optional backends
refs / records / artifacts -> io
serialization -> io
io -> pipeline.runner
weave -> pipeline execution internals
pipeline -> config composition or recursive target-instantiation internals
executors -> config composition internals
stores -> concrete project code
weave / pipeline / stores / executors -> diagnostics
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
from loom.artifacts import ArtifactAddress, ArtifactRef
from loom.fingerprints import hash_mapping
from weave import (
    RecipeCatalog,
    compose_config,
    compose_config_with_catalog,
    instantiate,
    register_recipe,
)
from loom.pipeline import PipelineSpec, StageFactorySpec, StageSpec, StageContext, PipelineRunner
from loom.diagnostics import PreflightRequest, run_preflight
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
  ArtifactAddress, cross-run artifact identity for catalogs and resume metadata.

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

`weave` composes trusted project configuration and supports config-only
object construction. It loads YAML, applies overlays and CLI overrides, resolves
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

`weave` is not the workflow engine. It may produce or instantiate pipeline
configs, but construction and execution belong to `loom.pipeline`.

### 6.5 Pipeline Model and Planning

Detailed specifications: [pipeline.md](features/pipeline.md),
[pipeline-graph.md](features/pipeline-graph.md),
[runtime-resources.md](features/runtime-resources.md)

`loom.pipeline` models static artifact DAGs, validates dependencies, binds
upstream artifacts to downstream inputs, plans stage actions, owns pipeline stage
factory parsing and construction, and exposes the stage contract used by project
code.

Expected modules:

```text
specs.py           PipelineSpec and StageSpec
stage.py           Stage protocol
stage_factory.py   pipeline-owned import and stage construction helpers
context.py         StageContext passed to stage implementations
status.py          run and stage status values
events.py          strict pipeline event records
locks.py           run lock record model
validation.py      spec and contract validation
resources.py       generic runtime/resource hints
runtime/           import-light runtime request and future runtime option models
graph/             DAG construction, topology, and binding validation
planning/          planning policy extraction, explainable diagnostics, and resume orchestration
errors.py          pipeline-specific errors
```

`pipeline/runtime/` is the stable public facade for invocation/runtime model
imports. Its current implementation exposes the local `RuntimeRequest`
foundation plus public `RunOptions`, `ExecutionOptions`,
`StageRuntimeOptions`, run/stage environment request models, runtime profiles,
deterministic base/profile/explicit merge helpers, and executor
descriptor/capability validation contracts. It also owns config-section
extraction for top-level `runtime` and `runtime_profiles` mappings. These
imports remain stable without importing CLI, diagnostics, execution runners,
concrete executors, plugins, optional backends, or project packages. Runtime
option adapters import planning-owned selector/resume models lazily so the
facade stays import-light. Future validation, registry,
descriptor, and serialization modules should live under this package only when
a phase adds real behavior and tests for that surface.

Executor descriptor records belong on this import-light side of the boundary
as scheduler-neutral metadata. Concrete executor implementations and plugin
discovery should depend on descriptor records when they are introduced;
descriptor modules must not import concrete executor implementations or plugin
loading code.

`planning/` currently includes:

```text
models.py         persisted execution plan, stage plan, fingerprint, resume, and reason models
invalidation.py   upstream binding validation and invalidation helper policy
selectors.py      selector and eligibility normalization
actions.py        stage action decision policy extraction
fingerprints.py   stable stage-fingerprint construction
resume.py         same-run resume checks and reuse policy
explanations.py   derived typed explanation model for CLI/preflight consumers
planner.py        topological plan assembly and execution plan construction
errors.py         planning, serialization, persistence, selector, and resume errors
```

Pipeline specs describe work. Project stage objects do the work. `loom.pipeline`
should not contain domain-specific stage subclasses.

### 6.6 Execution and Executors

Detailed specifications: [execution.md](features/execution.md),
[slurm.md](features/slurm.md),
[container-executors.md](features/container-executors.md)

`loom.pipeline.execution` coordinates the runner lifecycle. It prepares stages,
uses planning decisions, constructs stage contexts, invokes executors, commits
validated outputs, records logs and failures, emits local lifecycle events,
holds the run lock around mutating execution, persists blocked descendants after
failures, and finalizes runs.

Current execution modules:

```text
runner.py      PipelineRunner facade and local serial orchestration
eventing.py    typed local lifecycle event append helpers
event_sinks.py import-light observer sink registry and observer fact records
run_locks.py   runner-held run lock owner/acquire/release helpers
lifecycle.py   run and stage status writers
models.py      execution request/result/failure models
outputs.py     stage output validation
logs.py        stage log path helpers
errors.py      execution-specific errors
```

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
authority.py       v9 per-run authority protocol
capabilities.py    backend capability and diagnostic records
schema_policy.py   v9 active-state schema loud-fail policy
read_models.py     authoritative snapshot/read-model records
coordination.py    workspace/sweep cross-run coordination protocol
sqlite_coordination.py private local SQLite workspace coordination backend
indexes.py         run-level artifact and stage indexes
local_artifacts.py local filesystem artifact storage
local_runs.py      local run directory state
atomic.py          atomic file write helpers
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
freshness.json
events.jsonl
event_sink_failures.jsonl
event_observer_links.jsonl
lock.json
```

The runner owns lifecycle transitions. Stores persist those transitions.

`RunStore` is an aggregate protocol over capability surfaces for durable run
state. `LocalRunStorePaths` provides explicit local path helpers separately for
explicit local path consumers.

Run-store freshness metadata is store-owned authoritative run-local metadata for
catalog freshness checks. Stores may expose freshness records through store
protocols, but stores, execution, and executors must not import `loom.runs` or
write a collection catalog sidecar.

V9 adds backend-neutral authority contracts beside the legacy local-file
`RunStore` surface. `PerRunAuthorityStore` owns active per-run truth for new
backend implementations: guarded run/stage transitions, attempts, controller and
stage leases, submitted-operation records, output commits, artifact facts,
audit evidence, revisions, recovery scans, cleanup candidates, and
authoritative snapshots. It must not expose SQLite table names or treat
human-readable local files as fallback active truth.

`WorkspaceCoordinationStore` owns only cross-run coordination facts for
workspaces and sweeps: workspace/sweep identity, trial references, trial and
resource leases, counters, `run_uri` references, and recovery scans. The local
SQLite implementation lives behind that protocol with a private schema and
local or same-host safety only. It must not mutate per-stage lifecycle state or
replace `loom.runs`.

Capability declarations and schema checks are correctness inputs. Store
contracts must be able to report unsupported parallel, shared-filesystem,
remote, per-run, or cross-run capabilities with machine-readable diagnostics,
and v9 active-state schema mismatches must fail loudly rather than silently
migrating or falling back to local files.

### 6.8 Run Catalog

Detailed specifications: [run-catalog.md](features/run-catalog.md),
[run-store.md](features/run-store.md), [cli.md](features/cli.md)

`loom.runs` owns the public Python run-catalog facade, immutable value models,
warning/result envelopes, exact-match filter vocabulary, and metadata-only
comparison shapes. It sits above run-store inspection APIs and below CLI
presentation.

Expected modules:

```text
__init__.py    import-light public facade exports
catalog.py     RunCatalog facade and user-facing catalog entrypoint
models.py      summaries, filters, warnings, results, and comparison shapes
errors.py      catalog-specific public errors
_scan.py       private direct-scan discovery and extraction helpers
_extract.py    private run-store summary extraction helpers
_sqlite.py     private derived SQLite sidecar storage
```

Public catalog models use `run_uri` as the canonical identity. Display names and
local paths are presentation fields only. `loom.runs` may depend on public
foundation models, serialization helpers, and run-store inspection APIs. It must
not import CLI modules, execution runners, concrete executors, config
composition dependencies, project packages, or artifact payload codecs for
list/compare behavior.

Private catalog storage and extraction modules may read authoritative run-store
metadata and build derived catalog state. They must not make SQLite rows
authoritative, mutate run-store truth to repair catalog problems, or expose the
private SQLite schema as a public API. Lower layers, including
`loom.pipeline.stores`, `loom.pipeline.execution`, and executors, must not
import `loom.runs`; execution writes authoritative run-store metadata only.

### 6.9 Provenance and Resume

Detailed specifications: [provenance.md](features/provenance.md),
[resume.md](features/resume.md), [fingerprints.md](features/fingerprints.md),
[reliability.md](features/reliability.md)

Provenance records how a run was produced: config inputs, recipe expansions,
target imports, command line, working directory, git state, Python and package
versions, stage fingerprints, inputs, outputs, and generic metadata.

Resume uses stage fingerprints and persisted artifacts to decide whether to run,
reuse, skip, or fail a stage. V0 resume should be conservative and limited to the
same run directory.

### 6.10 Diagnostics

Detailed specifications: [preflight.md](features/preflight.md),
[cli.md](features/cli.md), [run-store.md](features/run-store.md),
[artifacts.md](features/artifacts.md)

`loom.diagnostics` owns reusable diagnostics result models and local readiness
checks that sit above config, pipeline, planning, stores, codecs, artifacts, and
executors, and below CLI presentation. It is a middle layer: diagnostics may
depend on public lower-layer APIs, but lower layers must not import
`loom.diagnostics`.

Current diagnostics modules:

```text
__init__.py    import-light public exports for preflight models and runner entrypoint
models.py      preflight statuses, severities, groups, request/result models, and plain-data serialization
preflight.py   local non-persistent preflight runner and check groups
```

The diagnostics package root must stay lightweight. `import loom.diagnostics`
may expose stable value models and a callable preflight entrypoint, but it must
not import `loom.cli`, config-only optional dependencies, local stores,
executors, project stage modules, or command registration. Check implementations
that need heavier public APIs should import them inside runner code rather than
through the package root.

Preflight is best-effort and non-persistent by default. It can report stable
check IDs, statuses, severities, messages, and plain-data details suitable for
later CLI JSON envelopes, but it must not allocate run URIs, create run
directories, write run-store documents, or replace execution-time validation.

### 6.11 Sweeps

Detailed specification: [sweeps.md](features/sweeps.md)

`loom.pipeline.sweep` is reserved for a future module that expands parameter
sets into multiple run configurations and coordinates trial execution through
the same config, planning, execution, and store APIs as normal runs.

Sweeps should remain generic when implemented. They should not become a
hyperparameter optimizer, experiment database, or scheduler replacement.

### 6.12 Plugins

Detailed specification: [plugins.md](features/plugins.md)

`loom.plugins` provides future extension discovery through entry points and
registration hooks. The initial runtime should not require plugin discovery for
normal imports.

Plugin loading must be explicit enough to avoid surprising import side effects.
Plugin code may register recipes, codecs, sources, executors, observe-only event
sinks, or CLI extensions through documented APIs. Runtime event semantics belong
to the reliability and execution layers; plugin discovery only loads and
registers event sink implementations.

### 6.13 CLI

Detailed specifications: [cli.md](features/cli.md),
[preflight.md](features/preflight.md), [run-catalog.md](features/run-catalog.md)

`loom.cli` owns command-line presentation. In v0 it remains an import-safe
unsupported surface. Later CLI phases should parse arguments, call public Python
APIs, format results, map errors to exit codes, and expose thin commands such
as validate, plan, run, stage, sweep, status, logs, and artifacts.

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

downstream-operations.md
  Short stage-author journey for explicit artifacts, workspace files, logs, and
  lifecycle facts; route detailed contracts to the relevant feature specs.

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

briefs/
  Durable feature briefs. A brief captures the problem, value, non-goals, done
  criteria, constraints, risks, assumptions, and specification targets before
  feature specification work begins.

briefs/v0_public_api_migration_notes.md
  Migration notes from early v0 patterns to the hardened public API shapes.

roadmap/stage-0/implementation-plan.md
  Review-gated v0 phase plan, phase status, accepted tradeoffs, and deferred
  v0 scope boundaries.

roadmap/stage-<id>/planning.md
  Roadmap-stage planning artifact with source evidence, functionality and
  design agreement, validation strategy, phase shaping, and readiness notes.

roadmap/stage-<id>/phases/
  One current phase execution plan per implementation phase. The plan carries
  scope, fixed contracts, tests, workflow state, and concise completion evidence.
  Older PR-body, review, refinement, and merge sidecars are historical only.
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
   doc or phase execution plan.

The repository phase workflow in `AGENTS.md` and
`docs/roadmap/stage-0/implementation-plan.md` controls large
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
