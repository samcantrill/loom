# Implementation Plan

## Goal

Implement `loom` v0 as a source-tree-first, fully typed Python package aligned
with the boundaries in `docs/structure.md`, `docs/features/config.md`,
`docs/loom.md`, and the subsystem specifications in `docs/features/`.

The v0 target is a generic runtime that can compose trusted YAML config, expand
recipes, instantiate user stage targets, validate a local artifact DAG, run it
in-process, persist an inspectable run directory, and resume unchanged stages
from the same run directory using strict fingerprints.

## Context

The current implementation is metadata-only:

- `src/loom/__init__.py` exposes only `__version__`.
- `src/loom/py.typed` exists.
- Package tests assert the package imports and includes its typing marker.
- `pyproject.toml` has no runtime dependencies and includes dev gates for
  `pytest`, `ruff`, and `pyright`.

`loom` must stay generic. It describes, configures, constructs, runs, resumes,
and tracks artifact-based workflows. Domain packages supply concrete stages,
recipes, codecs, schemas, datasets, models, reports, and analysis semantics.

## Desired Outcome

After all phases are complete, `loom` should expose:

- Stable public primitives such as `ResourceRef`, `Record`, `ArtifactRef`, and
  deterministic fingerprint helpers.
- Config composition, recipe expansion, and recursive `_target_`
  instantiation for trusted project configs.
- Generic I/O sources and codecs.
- Static pipeline specs, DAG validation, local run/artifact stores, planning,
  conservative resume decisions, and in-process local execution.
- Inspectable run directories with config, provenance, status, fingerprints,
  inputs, outputs, and artifact indexes.
- Focused tests proving import boundaries, extension contracts, local execution,
  and same-run-directory resume behavior.

## Non-Goals

- No domain-specific stage, codec, dataset, model, signal, image, or report
  logic in `loom`.
- No functional CLI in v0; CLI modules may exist only as import-safe unsupported
  feature stubs.
- No remote stores, database-backed orchestration, dashboards, distributed
  executors, SLURM, subprocess execution, or unreviewed autonomous merging.
- No Hydra defaults, include graphs, arbitrary expression language, complex list
  patching, automatic schema inference, or registry aliases for every
  configurable object.
- No config sandbox or allow-list mode in v0. Authored configs are trusted
  project code.
- No cross-run cache reuse; v0 resume is limited to the same run directory.

## Constraints

- Preserve the source-tree layout and boundaries in `docs/structure.md`.
- Keep `loom` domain-neutral.
- Use structural protocols and explicit registries where names resolve to
  implementations.
- Keep `loom.__init__` cheap and safe: it must not import config composition,
  pipeline runners, CLI modules, plugin discovery, or optional/heavy dependency
  paths.
- Keep runtime dependencies empty until config implementation begins in Phase 4.
- Add hard config dependencies only when Phase 4 starts: OmegaConf, Pydantic v2,
  and YAML support.
- Keep Python `>=3.12`, pyright standard mode, ruff target `py312`, and the
  existing dev checks.
- Require these validation commands where relevant:

```sh
uv run ruff check .
uv run pyright
uv run pytest
uv build
```

## Design Principles

- Preserve stable public imports while allowing internal modules to grow into
  packages.
- Keep foundational vocabulary near the top level and keep expensive or optional
  subsystems out of `loom.__init__`.
- Keep serialization separate from I/O.
- Use structural protocols and explicit registries instead of inheritance-heavy
  frameworks.
- Keep the CLI thin and defer functional CLI behavior until after the v0 runtime
  kernel is stable.
- Prefer small, reviewable phases over large cross-cutting changes.
- Add abstractions only when they protect a documented boundary or remove real
  duplication.

## Key Design Choices

- `loom.records` and `loom.provenance` are packages from the start because they
  are expected to grow multiple implementations and helper modules.
- Config dependencies are introduced only in Phase 4 so earlier primitive and
  I/O phases remain lightweight.
- Configs are trusted project code in v0; sandboxing and allow lists are
  deferred.
- Local execution is the first runtime target. Remote stores, subprocess
  execution, SLURM, and dashboards are deferred.
- Resume is same-run-directory only in v0. Cross-run cache reuse is deferred.
- The runner owns lifecycle, output validation, status writes, fingerprints, and
  resume decisions. Stages only implement domain work through the structural
  stage protocol.

## Concrete Public Interfaces

The v0 public surface should stay small and stable. `loom.__init__` may expose
only package metadata and cheap primitive exports:

```python
from loom.refs import ResourceRef
from loom.records import InMemoryManifest, ManifestView, Record
from loom.artifacts import ArtifactRef
from loom.fingerprints import Fingerprint, hash_mapping
```

It must not import config composition, pipeline runners, CLI modules, plugin
discovery, domain packages, SLURM/subprocess executors, or optional/heavy
dependency paths.

Foundational vocabulary lives near the top level:

- `loom.ids`
- `loom.refs`
- `loom.records`
- `loom.artifacts`
- `loom.provenance`
- `loom.fingerprints`
- `loom.protocols`
- `loom.errors`
- `loom.timestamps`

Config exposes the trusted-project API:

- `compose_config`
- `instantiate`
- `register_recipe`
- `Recipe`
- `ConfigError`

`compose_config(config_path, overlays=(), overrides=(), recipe_catalog=None)`
returns a `ComposedConfig` containing `resolved`, `redacted`, `provenance`, and
`fingerprint`. The composition order is:

```text
load base config
load overlays
recursive merge
apply dot-path overrides
resolve enough interpolation for recipe args
expand recipes
resolve interpolation again
validate
redact
compute config provenance and fingerprint
```

Pipeline APIs expose static specs and local execution through:

- `PipelineSpec`
- `StageSpec`
- `OutputSpec`
- `Stage`
- `StageContext`
- `PipelineRunner`

Stages are structural protocol implementations, not subclasses:

```python
def run(
    self,
    context: StageContext,
    inputs: Mapping[str, ArtifactRef],
) -> Mapping[str, ArtifactRef]: ...
```

The supported stage config shape is inline and explicit:

```yaml
pipeline:
  stages:
    - name: build
      _target_: project.stages.BuildStage
      config:
        limit: 100
      outputs:
        index:
          artifact_type: json
          codec_key: json.v1

    - name: report
      _target_: project.stages.ReportStage
      depends_on: [build]
      inputs:
        index: build.index
      outputs:
        report:
          artifact_type: text
          codec_key: text.v1
```

Stage parsing rules:

- Parse only orchestration fields into `StageSpec`: `name`, `_target_`,
  `config`, `depends_on`, `inputs`, `outputs`, and `resources`.
- Pass only the stage `config` mapping as constructor kwargs to the stage target.
- Require every output name to declare `artifact_type` and `codec_key`.
- Use only `stage.output` for input bindings.
- Input refs create data dependencies; `depends_on` adds control dependencies.

I/O and stores expose generic extension points only:

- `DataSource`, `LocalFileSystemSource`
- `Codec`, `CodecRegistry`, `JSONCodec`, `TextCodec`, `BytesCodec`
- `ArtifactStore`, `RunStore`, `LocalArtifactStore`, `LocalRunStore`

I/O owns bytes, files, URIs, sources, and codecs. Serialization owns Python
object to plain structured data conversion. Tests must protect this boundary.

The local run layout should remain human-inspectable and stable enough for
resume tests:

```text
config/raw.yaml
config/overlays.yaml
config/cli_overrides.yaml
config/resolved.yaml
config/resolved.redacted.yaml
config/recipe_manifest.json
stages/<stage>/status.json
stages/<stage>/inputs.json
stages/<stage>/outputs.json
stages/<stage>/fingerprint.json
stages/<stage>/provenance.json
stages/<stage>/logs/
artifacts/<stage>/
artifacts.json
run.json
provenance/environment.json
provenance/git.json
provenance/dependencies.json
```

## Conflicts And Tradeoffs

- Public API stability vs incremental implementation: phases should expose only
  stable imports that are backed by implemented behavior or explicit unsupported
  stubs.
- Extensibility vs over-abstraction: protocols and registries are used at
  subsystem boundaries, but implementation-specific abstractions should wait
  until there are multiple real implementations or clear complexity pressure.
- Trusted config ergonomics vs safety: v0 accepts trusted `_target_` imports to
  keep the system simple and explicit. Sandboxing is documented as out of scope.
- Resume correctness vs reuse aggressiveness: v0 prefers conservative invalidation
  and refuses reuse for partial, corrupt, stale, or unverifiable state.
- Phase size vs architectural coherence: phases should be split when a PR cannot
  be reviewed objectively, even if that means adding another planning step.

## Maintainability Assessment

The plan keeps foundational modules small, separates behavior-preserving
structure from runtime behavior, and delays dependencies until their phase needs
them. Each phase has narrow ownership and explicit out-of-scope work. Import
boundary tests and domain-neutrality checks are required early so later phases do
not accumulate hidden coupling.

Maintainability risks to watch:

- Adding registries before they resolve real names across a boundary.
- Letting config or pipeline behavior leak into top-level imports.
- Mixing refactors with runtime behavior in a single phase.
- Letting local execution hard-code assumptions that should belong to stores,
  codecs, or stage contracts.

## Extensibility Assessment

The plan intentionally supports future codecs, sources, stores, executors,
recipes, and downstream stage implementations through protocols and explicit
registries. It also protects future source-tree growth by keeping public imports
stable even when files become packages.

Deferred extensibility is intentional for:

- Remote storage.
- Cross-run cache reuse.
- SLURM and subprocess execution.
- Config sandboxing.
- Functional CLI behavior.
- Rich migration support for serialized schemas.

## Technical Debt Ledger

- Import-safe unsupported stubs are accepted during early phases to preserve
  public paths. Revisit when the corresponding subsystem phase implements real
  behavior.
- Hard config dependencies are deferred until Phase 4. Revisit if earlier phases
  accidentally need config behavior.
- Same-run-directory resume only is accepted for v0. Revisit after local
  execution and invalidation tests are stable.
- No lock manager is accepted initially. Revisit if atomic-write tests or
  interrupted-run tests expose a concrete race.
- CLI behavior is deferred. Revisit after the local runner has a stable public
  Python API.

## Plan Quality Gate

Status: pending review by `loom_plan_reviewer`.

Before Phase 1 starts:

- Review this plan with `.codex/prompts/implementation-plan-review.md`.
- Resolve blocking maintainability, extensibility, technical debt,
  conflicting-design, and reviewability findings.
- Record accepted risks with revisit triggers in this section or the technical
  debt ledger.
- Split any phase that is too broad for one reviewable PR.

Every expanded phase plan in `docs/phases/` must include:

- Design impact.
- Future compatibility.
- Alternatives rejected.
- Debt introduced.
- Reviewability.

Approved phase PRs target `develop`. The managing agent may mark a phase
`merged` only after the approved PR has been merged into `develop` and the
phase worktree has been removed.

## Phased Implementation

### Phase 1 — Foundation

Status: pending
Branch: `codex/add-foundation-skeleton`
PR: pending

Goal:

- Create the package skeleton, public import surface, shared errors,
  timestamp/id helpers, and import-boundary guardrails without implementing
  runtime behavior.

Scope:

- Add `loom.ids`, `loom.errors`, and `loom.timestamps`.
- Add import-safe package skeletons for records, provenance, serialization,
  I/O, config, pipeline, graph, planning, execution, executors, stores, and CLI.
- Keep deferred functionality import-safe and make unsupported callables fail
  explicitly when called.
- Update `loom.__init__` only with stable cheap public exports that are available
  in this phase.

Implementation checkpoints:

- Create package skeletons under `src/loom/records`, `src/loom/provenance`,
  `src/loom/serialization`, `src/loom/io`, `src/loom/config`,
  `src/loom/pipeline`, and `src/loom/cli`.
- Define simple ID aliases only: `RecordID`, `ResourceKey`, `CodecKey`,
  `ArtifactID`, `ArtifactType`, `RunID`, and `StageID`. Do not use `NewType`
  or wrapper classes in v0.
- Define broad catchable errors: `LoomError`, `ValidationError`,
  `ContractError`, `ArtifactError`, `ConfigError`, `PipelineError`,
  `ExecutionError`, and `IOErrorBase`.
- Define UTC-only timestamp helpers: `utc_now`, `utc_timestamp`,
  `safe_timestamp_for_path`, and `parse_timestamp`.
- Deferred callables should raise a clear `LoomError` subclass when called,
  while deferred modules still import cleanly.

Design and review notes:

- Design impact: establishes public import paths and package boundaries without
  committing to runtime behavior.
- Future compatibility: keeps internal modules free to grow into real
  implementations while preserving stable imports.
- Alternatives rejected: no early config dependencies, registries, or runtime
  behavior in this foundation phase.
- Debt introduced: unsupported stubs are accepted only until the corresponding
  subsystem phase implements real behavior.
- Reviewability: this phase should be mostly structure, import behavior, errors,
  timestamps, and focused tests.

Out of scope:

- Config composition, recipes, object construction, codecs, stores, planning,
  and execution.
- Hard config runtime dependencies.
- Domain-specific types or helpers.

Acceptance criteria:

- `import loom` is cheap and succeeds.
- Broad catchable error classes are available from `loom.errors`.
- UTC timestamp helpers produce parseable UTC values and path-safe strings.
- Deferred package imports succeed without performing runtime work.
- Import-boundary tests prove top-level imports do not pull in config, pipeline
  runners, CLI, or domain packages.

Test expectations:

- Add focused tests for public imports, import boundaries, deferred stubs,
  errors, and timestamps.
- Run `uv run pytest`, `uv run ruff check .`, `uv run pyright`, and `uv build`.

Notes:

- Source references: `docs/structure.md` sections 1.1, 1.2, 1.6, 1.7, 3.1,
  3.2, 3.3, 3.10, 3.11, 20.1, 20.2; `docs/loom.md` sections 1, 2, 3, 4, 12,
  14.
- `loom.ids` should define simple aliases only, not `NewType` or wrapper
  classes.

Completion summary:

- Pending.

### Phase 2 — Primitives And Serialization

Status: pending
Branch: `codex/add-primitives-serialization`
PR: pending

Goal:

- Implement the generic value objects and serialization helpers used by every
  later subsystem.

Scope:

- Add public primitives: `ResourceRef`, `ArtifactRef`, `Record`,
  `InMemoryManifest`, `ManifestView`, generic record filters, provenance
  models, package-wide generic protocols, and stable fingerprint helpers.
- Add serialization helpers for plain data, dataclass conversion, stable JSON,
  and schema-version checks.
- Preserve checksum and fingerprint as distinct concepts.

Implementation checkpoints:

- `ResourceRef` and `ArtifactRef` are frozen typed dataclasses with URI,
  type/key, schema version, checksum, fingerprint/provenance metadata where
  applicable, and no loading methods.
- `Record` is a frozen typed dataclass with generic resources, metadata,
  annotations, and provenance; it must not grow domain fields.
- `InMemoryManifest` rejects duplicate record IDs and preserves deterministic
  iteration; `ManifestView` supports lazy generic filters such as
  `HasResource`, `MetadataEquals`, and `MetadataIn`.
- Provenance models cover code, environment, run, and stage context without
  heavy dependency inspection.
- Fingerprint helpers use stable JSON and cryptographic hashes; never use
  Python built-in `hash()` for persisted identities.
- Serialization emits only plain structured data and keeps filesystem atomic
  writes out of this layer.

Design and review notes:

- Design impact: creates the public vocabulary that later config, I/O, stores,
  and execution layers share.
- Future compatibility: structural primitives allow downstream packages to
  compose records and artifacts without subclassing `loom` internals.
- Alternatives rejected: no domain-specific resource helpers, schema migrations,
  or object loading behavior in primitive refs.
- Debt introduced: schema-version helpers are validation-only in v0; migration
  support is deferred until serialized formats need it.
- Reviewability: primitive behavior should be covered by deterministic,
  isolated unit tests and import-boundary checks.

Out of scope:

- I/O sources, codecs, filesystem writes, artifact stores, and stage execution.
- Domain-specific resource or artifact helpers.
- Schema migrations.

Acceptance criteria:

- Frozen typed primitives have deterministic equality and plain-data conversion.
- Manifests reject duplicate record IDs and preserve deterministic iteration.
- Manifest views support generic filtering without domain semantics.
- Fingerprints are deterministic across mapping insertion order.
- Serialization outputs only plain structured data.
- Serialization does not import the I/O subsystem.

Test expectations:

- Add focused tests for refs, artifacts, records, manifests, provenance,
  fingerprints, plain-data serialization, dataclass conversion, JSON helpers,
  and schema helpers.
- Run `uv run pytest`, `uv run ruff check .`, and `uv run pyright`.

Notes:

- Source references: `docs/structure.md` sections 3.4 through 4.7, 20.5,
  20.6, 21.1, 22 Phase 1, 23.1; `docs/loom.md` sections 6.1, 6.2, 6.3, 10,
  11, 12; `docs/features/core-model.md`, `docs/features/artifacts.md`, and
  `docs/features/fingerprints.md`.
- Never use Python built-in `hash()` for persisted identities.

Completion summary:

- Pending.

### Phase 3 — I/O Basics

Status: pending
Branch: `codex/add-io-basics`
PR: pending

Goal:

- Implement local filesystem access, URI helpers, generic codecs, and codec
  registration.

Scope:

- Add URI parsing and normalization helpers.
- Add `DataSource` protocol and `LocalFileSystemSource`.
- Add `Codec` protocol, JSON/text/bytes codecs, codec-specific errors, and an
  explicit instance-based `CodecRegistry`.
- Keep this layer as the bridge between plain serialized data and stored bytes.

Implementation checkpoints:

- URI helpers include `parse_uri`, `is_file_uri`, `uri_to_path`,
  `path_to_file_uri`, `normalize_uri`, and `get_uri_scheme`.
- `LocalFileSystemSource` supports local paths and `file://` URIs with
  `open`, `exists`, `stat`, `glob`, and `resolve`.
- `JSONCodec` accepts only plain-data-compatible values; `TextCodec` is UTF-8
  by default; `BytesCodec` handles raw bytes only.
- `CodecRegistry` is instance-based and rejects duplicate registrations and
  unknown codec keys.

Design and review notes:

- Design impact: creates the generic byte/file boundary used later by artifact
  stores.
- Future compatibility: keeps remote sources and richer source registries
  possible without changing serialization primitives.
- Alternatives rejected: no artifact-store layout, remote source support, or
  domain codecs in this phase.
- Debt introduced: only local filesystem source support is accepted for v0.
  Revisit when remote stores become a planned phase.
- Reviewability: tests should prove URI behavior, codec round trips, registry
  failures, and the serialization/I/O boundary.

Out of scope:

- Remote sources or stores.
- Artifact-store layout.
- Domain codecs.
- Pipeline execution.

Acceptance criteria:

- Local paths and `file://` URIs round-trip correctly.
- Local source supports `open`, `exists`, `stat`, `glob`, and path resolution.
- JSON/text/bytes codecs round-trip supported values.
- JSON codec rejects non-plain unsupported objects.
- Codec registry rejects duplicate keys and unknown codec lookups.

Test expectations:

- Add focused tests for URI helpers, local source behavior, JSON/text/bytes
  codecs, and codec registry errors.
- Run `uv run pytest`, `uv run ruff check .`, and `uv run pyright`.

Notes:

- Source references: `docs/structure.md` sections 1.3, 5, 6, 7, 20.15, 21.5,
  22 Phase 2, 23.2; `docs/loom.md` sections 4, 6.1, 6.3; `docs/features/io.md` and
  `docs/features/artifacts.md`.
- I/O owns bytes, files, URIs, sources, and codecs. Serialization owns object to
  plain structured data conversion.

Completion summary:

- Pending.

### Phase 4 — Config Composition

Status: pending
Branch: `codex/add-config-composition`
PR: pending

Goal:

- Implement trusted YAML config composition and provenance without object
  construction side effects.

Scope:

- Add hard runtime config dependencies: OmegaConf, Pydantic v2, and PyYAML.
- Add config loading, recursive merge, dot-path overrides, interpolation,
  validation, redaction, config provenance, and public `compose_config`.
- Return `ComposedConfig` with resolved config, redacted config, provenance, and
  fingerprint.

Implementation checkpoints:

- Add dependency entries for `omegaconf>=2.3`, `pydantic>=2`, and `pyyaml>=6`.
- Split config behavior into loading, merge, overrides, interpolation,
  validation, redaction, provenance, and compose modules.
- Merge semantics are recursive mapping merge, scalar replacement, list
  replacement, and explicit `null`; do not add list patch operators.
- Overrides parse booleans, nulls, integers, floats, JSON arrays/objects, and
  strings, then apply through dot paths with path-aware errors.
- Interpolation is wrapped behind a local API so non-config modules do not
  become OmegaConf-specific.
- Redaction recursively masks secret-like keys such as `token`, `secret`,
  `password`, `api_key`, `credential`, and `private_key`.
- Config composition writes nothing by itself. Persistence belongs to the runner
  and run store.

Design and review notes:

- Design impact: introduces the first hard runtime dependencies and the trusted
  config composition contract.
- Future compatibility: a local interpolation wrapper and provenance model leave
  room for different config backends or stricter modes later.
- Alternatives rejected: no Hydra defaults, include graph, expression language,
  config sandbox, or object construction in this phase.
- Debt introduced: config imports are trusted code; revisit if users need an
  allow-list or sandbox mode.
- Reviewability: the PR should be limited to config resolution/provenance and
  must avoid pipeline execution behavior.

Out of scope:

- Recipe expansion.
- `_target_` object construction.
- Config persistence to run directories.
- Sandbox or allow-list mode.

Acceptance criteria:

- Base config and overlays compose in order.
- Mapping/scalar/list/null merge semantics match the docs.
- Overrides parse supported scalar and structured values.
- Interpolation resolves through a wrapped API and reports unresolved values
  clearly.
- Required top-level fields are validated.
- Secret-like keys are redacted recursively.
- Config provenance and fingerprints change when source inputs change.

Test expectations:

- Add focused tests for config loading, merge, overrides, interpolation,
  validation, redaction, composition, and provenance.
- Run `uv run pytest`, `uv run ruff check .`, and `uv run pyright`.

Notes:

- Source references: `docs/features/config.md` sections 1 through 10, 13 through 16,
  18; `docs/structure.md` sections 8.1 through 8.11, 20.3, 20.12, 21.2,
  22 Phase 3, 23.3; `docs/loom.md` sections 7, 11, 12, 14.
- Composition should write nothing by itself. Persistence belongs to the runner
  and run store.

Completion summary:

- Pending.

### Phase 5 — Recipes And Instantiation

Status: pending
Branch: `codex/add-recipes-instantiation`
PR: pending

Goal:

- Implement the two reusable config mechanisms allowed in v0: named `_recipe_`
  expansion and recursive `_target_` object construction.

Scope:

- Add recipe protocols/models, explicit recipe catalogs, public
  `register_recipe`, recursive recipe expansion, and recipe provenance records.
- Add target import helpers for dotted and colon paths.
- Add recursive `_target_` instantiation with `_args_`, `_partial_`, and
  `_inject_`.
- Validate reserved-key usage and path-aware constructor/import failures.

Implementation checkpoints:

- Define `ConfigRecipe`/`Recipe` contracts and a Pydantic-backed recipe model
  path for typed recipe inputs.
- `RecipeCatalog` is explicit and instance-based; the public default registry
  must be test-isolated.
- Recipe expansion recursively replaces mappings with `_recipe_`, records path,
  recipe name, target, input arguments, expanded hash, expanded path, and loom
  version.
- Target imports support `package.module.Class`, `package.module:function`, and
  `package.module:Class`, with path-aware import and constructor errors.
- Recursive instantiation handles nested mappings/sequences, `_args_`,
  `_partial_=true`, and `_inject_` from an explicit runtime dependency mapping.
- Reserved keys are `_target_`, `_args_`, `_partial_`, `_context_`, and
  `_recipe_`; misuse fails loudly.

Design and review notes:

- Design impact: turns resolved trusted configs into ergonomic reusable objects
  while keeping orchestration explicit.
- Future compatibility: explicit catalogs preserve room for entry-point
  discovery later without committing to plugin behavior in v0.
- Alternatives rejected: no import sandbox, allow list, entry-point recipe
  discovery, or serialized runtime injection values.
- Debt introduced: the default recipe registry is a convenience; tests must
  prevent global state leakage.
- Reviewability: recipes and instantiation can be reviewed independently from
  pipeline execution.

Out of scope:

- Entry-point recipe discovery.
- Sandbox or import allow-list mode.
- Pipeline execution.
- Serializing injected runtime dependencies into resolved config.

Acceptance criteria:

- Recipe registration, lookup, duplicate detection, and unknown-recipe failures
  work.
- Nested recipes expand deterministically and record useful provenance.
- Target import supports documented path forms and reports path-aware errors.
- Recursive instantiation handles nested mappings/sequences, positional args,
  partials, and runtime injection.
- Trusted config behavior is documented.

Test expectations:

- Add focused tests for recipes, recipe catalog behavior, recipe expansion,
  target imports, recursive instantiation, and injection.
- Run `uv run pytest`, `uv run ruff check .`, and `uv run pyright`.

Notes:

- Source references: `docs/features/config.md` sections 5.6, 5.7, 6.3, 7, 11, 12, 16,
  18; `docs/structure.md` sections 9, 10, 20.3, 20.7, 20.15, 21.2,
  22 Phase 4, 23.3.
- Configs are trusted project code in v0.

Completion summary:

- Pending.

### Phase 6 — Pipeline Specs And Graph

Status: pending
Branch: `codex/add-pipeline-specs-graph`
PR: pending

Goal:

- Implement the static pipeline model, stage contract, status types, and pure
  graph validation before persistent stores and execution.

Scope:

- Add `OutputSpec`, `StageSpec`, `PipelineSpec`, `Stage` protocol,
  `StageContext`, status types, graph helpers, input binding helpers, and static
  validation.
- Parse only documented orchestration fields from stage config and pass only
  `config` to stage constructors.
- Support `stage.output` input references and distinguish data dependencies
  from control-only `depends_on`.

Implementation checkpoints:

- `OutputSpec`, `StageSpec`, and `PipelineSpec` are frozen dataclasses that
  preserve authored order but validate execution order separately.
- `StageSpec` stores `target_path`, `constructor_config`, `depends_on`,
  `inputs`, `outputs`, and `resources`.
- `StageContext` contains only generic runtime fields: run/stage IDs and paths,
  resolved and stage config, artifact/run stores, provenance, metadata, and
  stage-bound artifact helpers.
- Status types include stage/run statuses and serializable status records.
- Graph helpers build dependencies, detect cycles, compute upstream/downstream
  sets, and topologically sort linear, branching, and diamond DAGs.
- Binding helpers parse only strict `stage.output` references.

Design and review notes:

- Design impact: defines the static pipeline contract before any persistent
  state or execution side effects exist.
- Future compatibility: separating specs, graph, and bindings leaves execution
  backends replaceable.
- Alternatives rejected: no persistent stores, resume planning, target
  instantiation, or stage execution in this phase.
- Debt introduced: the status model should be kept minimal until store and
  runner phases prove additional states are needed.
- Reviewability: all behavior should be pure parsing, validation, status
  modeling, and graph tests.

Out of scope:

- Persistent stores.
- Resume planning.
- Stage target instantiation.
- Stage execution.

Acceptance criteria:

- Documented inline stage YAML shape parses correctly.
- Unknown stage-level orchestration keys are rejected.
- Duplicate stages, missing outputs, bad output specs, bad refs, unknown stages,
  unknown outputs, cycles, and self-dependencies fail clearly.
- Topological sort works for linear, branching, and diamond DAGs.
- Dummy stages satisfy the stage protocol without inheritance.

Test expectations:

- Add focused tests for pipeline specs, stage contract, context, status,
  validation, graph helpers, and bindings.
- Run `uv run pytest`, `uv run ruff check .`, and `uv run pyright`.

Notes:

- Source references: `docs/structure.md` sections 11, 12, 20.1, 20.16, 21.3,
  22 Phase 5, 23.4; `docs/loom.md` sections 6.4, 6.5, 8, 12, 14;
  `docs/features/pipeline.md`, `docs/features/state.md`, and `docs/features/testing.md`.

Completion summary:

- Pending.

### Phase 7 — Stores And Planning

Status: pending
Branch: `codex/add-stores-planning`
PR: pending

Goal:

- Implement durable local run/artifact state and resume planning without
  executing stages.

Scope:

- Add artifact and run store protocols.
- Add local artifact and run stores, atomic write helpers, run/artifact indexes,
  stage fingerprint calculation, execution plan models, resume checks, and
  downstream invalidation.
- Define and persist the inspectable local run directory layout.

Implementation checkpoints:

- `ArtifactStore` exposes save/load/exists/validate; `LocalArtifactStore` uses
  `CodecRegistry`, writes through temp paths and atomic moves where possible,
  computes stored-byte checksums, and returns typed `ArtifactRef`s.
- `RunStore` exposes run/stage directory resolution plus status, input, output,
  and fingerprint reads/writes.
- Local run layout includes config files, stage state files, logs, per-stage
  artifact directories, `artifacts.json`, `run.json`, and provenance files.
- Atomic helpers cover JSON, text, bytes, replacement, directory creation, and
  unique temp filenames.
- Artifact indexes use logical keys of the form `stage.output`.
- Fingerprints include stage name, target path, constructor config, output specs,
  bound inputs, Python version, `loom` version, relevant git state, configured
  dependency versions, and configured extra fields.
- Fingerprints exclude noisy values such as wall-clock timestamps, logs, temp
  paths, and random run IDs unless explicitly configured.
- Resume skips only a previous `SUCCEEDED` stage with matching fingerprint,
  existing `outputs.json`, existing artifacts, and valid checksums.

Design and review notes:

- Design impact: creates durable local state and conservative reuse decisions
  without invoking user stage code.
- Future compatibility: store protocols keep remote stores and global run
  discovery possible later.
- Alternatives rejected: no actual stage execution, remote stores, cross-run
  cache reuse, or lock manager unless tests prove one is required.
- Debt introduced: v0 relies on atomic writes, not a full lock manager. Revisit
  if interrupted-run tests expose race conditions.
- Reviewability: stores, indexes, fingerprints, planning, resume, and
  invalidation should be testable without running stages.

Out of scope:

- Actual stage execution.
- Remote stores.
- Cross-run cache reuse.
- Lock managers unless tests prove they are required.

Acceptance criteria:

- Artifacts save/load through JSON, text, and bytes codecs.
- Checksums are written and validated.
- Run directory state is written atomically where possible.
- Planner computes bound inputs and topological stage plans.
- Resume skips only valid succeeded stages with matching fingerprints, existing
  outputs, existing artifacts, and valid checksums.
- Interrupted, corrupt, stale, failed, or partial state is never reusable.
- Downstream invalidation propagates for changed config, target, output specs,
  or upstream artifacts.

Test expectations:

- Add focused tests for artifact store, run store, atomic writes, indexes,
  planner behavior, resume, and invalidation.
- Run `uv run pytest`, `uv run ruff check .`, and `uv run pyright`.

Notes:

- Source references: `docs/structure.md` sections 13, 16, 20.4 through 20.10,
  21.4, 22 Phase 5, 23.5; `docs/loom.md` sections 9, 10, 11;
  `docs/features/run-store.md`, `docs/features/artifacts.md`,
  `docs/features/fingerprints.md`, and `docs/features/resume.md`.
- Fingerprints must exclude noisy values unless explicitly configured.

Completion summary:

- Pending.

### Phase 8 — Local Execution

Status: pending
Branch: `codex/add-local-execution`
PR: pending

Goal:

- Implement the end-to-end local runner using the already-tested config, graph,
  store, and planning layers.

Scope:

- Add executor protocol, in-process `LocalExecutor`, execution result types,
  lifecycle helpers, logs helpers, and `PipelineRunner`.
- Create or reuse run directories, persist config/provenance, parse and validate
  pipeline specs, instantiate stage targets, build stage contexts, plan, bind
  inputs, execute runnable stages, validate outputs, persist stage/run state,
  update artifact indexes, and support same-run-directory resume.

Implementation checkpoints:

- `LocalExecutor` invokes `stage.run(context, inputs)` in the current Python
  process and returns an `ExecutionResult`.
- Lifecycle helpers mark stages running, succeeded, failed, skipped, and
  finalized through the run store.
- `PipelineRunner` accepts a composed config or resolved mapping plus run
  options, writes config/provenance, parses the pipeline, instantiates targets,
  builds contexts, asks the planner for work, executes runnable stages, validates
  returned outputs, writes state, updates indexes, and finalizes `run.json`.
- Output validation requires returned keys to match declared outputs exactly,
  each value to be an `ArtifactRef`, artifact type and codec key to match the
  output spec, referenced files to exist, and checksums to validate when present.
- Failure behavior writes `FAILED` status and error context, avoids executing
  downstream stages in the same run, marks the run failed, and leaves state
  inspectable.
- Resume behavior is same-run-directory only; valid unchanged stages are skipped
  or represented through explicit skip decisions.

Design and review notes:

- Design impact: delivers the first end-to-end runnable local v0 path.
- Future compatibility: executor protocol keeps subprocess, SLURM, and
  distributed backends out of the runner contract.
- Alternatives rejected: no CLI behavior, subprocess execution, SLURM, remote
  stores, or cross-run cache reuse.
- Debt introduced: local in-process execution is the only backend in v0. Revisit
  after the Python API and run-state format stabilize.
- Reviewability: local execution should be validated with synthetic generic
  stages and same-run-directory resume tests.

Out of scope:

- Subprocess execution.
- SLURM or distributed executors.
- Remote stores.
- Cross-run cache reuse.
- CLI behavior unless needed as import-safe stubs.

Acceptance criteria:

- A synthetic local pipeline can run end to end from YAML.
- Run directories contain expected config, provenance, status, fingerprint,
  input, output, artifact, and index files.
- Same-run-directory reruns skip valid unchanged stages.
- Changed stage config or upstream artifacts rerun the changed stage and
  downstream dependents.
- Invalid stage outputs fail with path-aware errors.
- Stage exceptions persist failure state and leave inspectable run state.

Test expectations:

- Add focused tests for local executor, pipeline runner, lifecycle, e2e
  pipeline behavior, and generic dummy stages.
- Run `uv run pytest`, `uv run ruff check .`, `uv run pyright`, and `uv build`.

Notes:

- Source references: `docs/structure.md` sections 14, 15.1 through 15.3, 20.4,
  20.8, 20.9, 23.4, 23.6, 23.7; `docs/loom.md` sections 8 through 12;
  `docs/features/pipeline.md`, `docs/features/execution.md`,
  `docs/features/run-store.md`, `docs/features/resume.md`, and
  `docs/features/testing.md`.
- The runner, not the stage, owns lifecycle, output validation, status writes,
  fingerprints, and resume decisions.

Completion summary:

- Pending.

### Phase 9 — Hardening And Documentation

Status: pending
Branch: `codex/harden-v0-docs`
PR: pending

Goal:

- Tighten errors, recovery, contracts, and docs once the local execution path
  works.

Scope:

- Improve path-aware errors across config, recipes, instantiation, pipeline
  parsing, graph bindings, artifact store, run store, resume planner, and local
  runner.
- Harden interrupted-run behavior.
- Add extension contract tests for dummy stages, codecs, recipes, and stores.
- Update README and docs for trusted configs, `_target_`, `_recipe_`, stage
  contract, artifact saving, output specs, run directory layout, checksums vs
  fingerprints, and same-run-directory resume.
- Make import-boundary tests permanent guardrails.

Implementation checkpoints:

- Representative errors include config paths such as
  `pipeline.stages[2]._target_`, stage names, artifact keys such as
  `train.best_checkpoint`, target paths, and filesystem paths.
- Stale `RUNNING`, missing `outputs.json`, corrupt JSON, partial artifacts,
  checksum mismatch, and failed prior stages are not reusable.
- Extension contract tests prove downstream-style stages, codecs, recipes, and
  stores satisfy protocols structurally without inheritance.
- README/docs snippets document trusted configs, `_target_`, `_recipe_`, stage
  contract, artifact saving, output specs, run directory layout, checksums vs
  fingerprints, and same-run-directory resume.

Design and review notes:

- Design impact: hardens the completed local runtime kernel without widening v0
  scope.
- Future compatibility: docs and contract tests make downstream extension points
  explicit before adding remote/executor/plugin features.
- Alternatives rejected: no new execution backends, remote storage, dashboards,
  or orchestration features.
- Debt introduced: any docs examples that cannot execute must be recorded with
  a reason and revisit trigger.
- Reviewability: this phase should be a hardening/docs PR, not a feature
  expansion PR.

Out of scope:

- Major deferred features.
- New execution backends.
- Remote storage.
- Dashboard or orchestration features.

Acceptance criteria:

- Representative errors include useful config paths, stage names, artifact keys,
  target paths, or file paths.
- Stale `RUNNING`, missing or corrupt files, partial artifacts, invalid
  checksums, and failed prior stages are not skipped.
- Downstream-style extension classes satisfy protocols structurally without
  inheritance.
- Docs examples execute where feasible.
- Full import-boundary tests still pass after all subsystems exist.

Test expectations:

- Add focused tests for error messages, interrupted runs, extension contracts,
  docs examples, and import boundaries.
- Run `uv run pytest`, `uv run ruff check .`, `uv run pyright`, and `uv build`.

Notes:

- Source references: `docs/structure.md` sections 20.1 through 20.16, 21, 23,
  24, 25; `docs/features/config.md` sections 14, 16, 19; `docs/loom.md`
  sections 9 through 16; `docs/features/run-store.md`,
  `docs/features/resume.md`, `docs/features/testing.md`, and
  `docs/features/cli.md`.
- This phase should harden v0, not expand it into postponed features.

Completion summary:

- Pending.

## Deferred Features

Do not implement these in v0 except as import-safe unsupported stubs where a
stable public path is useful:

- Functional CLI commands.
- Subprocess, SLURM, or distributed executors.
- Sweeps.
- Plugins or entry-point discovery.
- Remote artifact stores.
- Source registries beyond local source needs.
- Executor registries unless needed for local-only ergonomics.
- Global run discovery.
- Cross-run cache indexes.
- Path templates or output path interpolation.
- Domain codecs, stages, recipes, schemas, datasets, models, metrics, reports,
  or analysis logic.
- Config sandbox or allow-list mode.
- Hydra defaults, include graphs, complex list patching, arbitrary expression
  language, automatic schema inference, or registry aliases for every
  configurable object.
- Database-backed orchestration or dashboards.

## Overall Test Plan

Unit tests should cover:

- Primitive construction, immutability, public imports, and plain-data
  serialization.
- Stable fingerprint determinism and checksum/fingerprint separation.
- Dataclass conversion, schema-version checks, and stable JSON output.
- URI helpers, local source behavior, codec round trips, and codec registry
  errors.
- Config load, merge, overrides, interpolation, validation, redaction, and
  provenance.
- Recipe registration, expansion, validation, provenance, target import,
  recursive instantiation, `_args_`, `_partial_`, `_inject_`, and constructor
  failures.
- Pipeline spec parsing, DAG validation, graph order, input binding, output spec
  validation, and stage output validation.
- Artifact/run store atomic writes, artifact indexes, status transitions, resume
  decisions, invalidation, and corrupt state handling.

End-to-end tests should cover:

- Running a synthetic local pipeline from YAML.
- Verifying run directories contain config, provenance, status, fingerprint,
  input, output, artifact, and index files.
- Rerunning the same run directory and skipping unchanged stages.
- Rerunning changed stages and downstream dependents after config or upstream
  artifact changes.
- Refusing reuse when artifact files are missing or corrupt.
- Failing with path-aware errors for undeclared, missing, wrong-type,
  wrong-codec, or non-existent outputs.
- Persisting status/provenance cleanly after stage failure.

Final acceptance gates:

```sh
uv run ruff check .
uv run pyright
uv run pytest
uv build
```

## Assumptions And Defaults

- Python remains `>=3.12`.
- Pyright must pass, but strict mode is deferred.
- Config dependencies are hard runtime dependencies once Phase 4 starts.
- CLI modules may exist only as import-safe stubs.
- No local lock manager is required in v0 unless tests prove it necessary;
  atomic writes are required.
- Same-run-directory resume is required; cross-run cache reuse is not.
- Physical artifact paths are owned by `LocalArtifactStore`.
- Stages declare logical output names and specs, not path templates.
- Public imports should remain stable even if internals are later refactored.
- Deferred features fail explicitly, not silently.
- Configs are trusted code; no sandbox or allow-list mode exists in v0.
- Every `loom` extension point remains domain-agnostic and structurally typed.
