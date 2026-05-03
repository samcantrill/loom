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
  and YAML support. This is an explicit v0 packaging tradeoff: earlier design
  docs described config extras, but v0 uses hard config dependencies after
  Phase 4 to keep the initial runtime and validation matrix simple. Revisit
  after v0 if downstream users need a primitives-only install.
- Keep Python `>=3.12`, pyright standard mode, ruff target `py312`, and the
  existing dev checks behind the Make harness.
- Require these validation commands where relevant:

```sh
make validate-pr
make test-summary
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
- Config dependencies become hard runtime dependencies when Phase 4 lands. This
  intentionally favors one tested v0 installation shape over an early optional
  extras matrix.
- Configs are trusted project code in v0; sandboxing and allow lists are
  deferred.
- Stage `config` is runtime invocation config, not constructor config. Stage
  target constructor parameters are deferred so the runner has a single stable
  stage invocation contract.
- Artifact codecs are optional at the output-spec and artifact-ref boundary.
  Codec-managed `save`/`load` covers plain JSON/text/bytes values, while
  manual write/register supports outputs that project code owns directly.
- Stage `resources` are opaque plain-data metadata in v0. They carry no
  executor-specific semantics, no scheduler mapping, and no default effect on
  stage fingerprints unless a future explicit policy opts in.
- Local execution is the first runtime target. Remote stores, subprocess
  execution, SLURM, and dashboards are deferred.
- Resume is same-run-directory only in v0. Cross-run cache reuse is deferred.
- The runner owns lifecycle, output validation, status writes, fingerprints, and
  resume decisions. Stages only implement domain work through the structural
  stage protocol.

## Feature Document Guidance

Phase agents should treat this implementation plan as the controlling scope and
use the referenced feature documents in `docs/features/` for detailed subsystem
guidance. When a feature document describes post-v0 behavior or wider future
direction, implement only the v0 behavior named in this plan and record any
accepted deferral in the expanded phase plan.

Each phase's `Source references` list names the feature documents most relevant
to that phase. Expanded phase plans should preserve those references and add
more specific sections from the same feature documents when they rely on a
particular contract, boundary, or testing strategy.

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
returns a `ComposedConfig` containing `resolved`, `redacted`, `provenance`,
`recipe_manifest`, and `fingerprint`. The composition order after Phase 5 is:

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

In Phase 4, before recipes exist, `compose_config` rejects `_recipe_` blocks
with a clear `ConfigError` and returns an empty `recipe_manifest` for configs
without recipes. Phase 5 replaces that bridge behavior with deterministic
recipe expansion and manifest records.

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

- Parse only authored orchestration keys: `name`, `_target_`, `config`,
  `depends_on`, `inputs`, `outputs`, and `resources`.
- Store parsed stages with canonical internal fields: `name`, `target_path`,
  `stage_config`, `dependencies`, `inputs`, `outputs`, and `resources`.
- Treat stage `config` as runtime invocation config exposed through
  `StageContext`, not as stage-constructor kwargs.
- Instantiate stage `_target_` values without constructor kwargs in v0. Stage
  classes that need configured objects should read them from
  `StageContext.stage_config`; stage-target constructor kwargs are deferred
  until a concrete need appears.
- Treat stage `resources` as opaque plain-data metadata in v0. Preserve it for
  inspection, but do not interpret executor-specific fields, map it to
  scheduler settings, or include it in semantic stage fingerprints by default.
- Require every output name to declare `artifact_type`. `codec_key` is optional
  so manually written artifacts, directories, checkpoints, and external-tool
  outputs can be registered without forcing generic serialization.
- Use only `stage.output` for input bindings.
- Input refs create data dependencies; authored `depends_on` parses into
  internal `dependencies` and adds control dependencies.

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
status.json
plan.json
artifacts.json
stages/<stage>/status.json
stages/<stage>/inputs.json
stages/<stage>/outputs.json
stages/<stage>/fingerprint.json
stages/<stage>/failure.json (failed stages only)
stages/<stage>/provenance.json
stages/<stage>/logs/stdout.log
stages/<stage>/logs/stderr.log
artifacts/<stage>/
run.json
provenance/environment.json
provenance/git.json
provenance/command.json
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
- Hard config dependencies after Phase 4 are accepted for v0 to avoid supporting
  both a full and primitives-only install before the runtime API stabilizes.
  Revisit after Phase 10 if users need `loom` without config composition
  dependencies.
- Stage-target constructor kwargs are deferred. Revisit if synthetic or
  downstream-style stages cannot express useful configuration through
  `StageContext.stage_config` and injected config objects.
- Artifacts without `codec_key` cannot be generically loaded by
  `ArtifactStore.load` unless an explicit codec is supplied. Revisit if this
  blocks common downstream artifact inspection workflows.
- Same-run-directory resume only is accepted for v0. Revisit after local
  execution and invalidation tests are stable.
- No lock manager is accepted initially. Revisit if atomic-write tests or
  interrupted-run tests expose a concrete race.
- CLI behavior is deferred. Revisit after the local runner has a stable public
  Python API.

## Plan Quality Gate

Status: passed on 2026-05-03 by `loom_plan_reviewer` confirmation review.

Loop budget: one plan review, one automated plan refinement pass, and one
confirmation review. If blocking findings remain after the confirmation review,
mark the plan or next phase `blocked`, report the exact blocker, and stop
instead of starting another review/refine cycle.

Budget state:

- Initial plan review: used.
- Automated plan refinement pass: used.
- Confirmation review: used.

Gate result:

- Confirmation review found no blocking maintainability, extensibility,
  technical debt, conflicting-design, or reviewability findings.
- Blocking findings from the first plan review were addressed by:
  - clarifying stage `config` as runtime invocation config;
  - making output `codec_key` optional and adding artifact registration;
  - splitting stores/run layout from planning/resume/selectors;
  - adding root status, plan, and failure files to the run-store contract;
  - recording the hard config dependency tradeoff and revisit trigger;
  - adding selectors to the planning phase; and
  - requiring `make validate-pr` and `make test-summary` for each phase unless
    unavailable checks are explicitly justified.
- Accepted risks remain recorded in the technical debt ledger. The controlling
  v0 scope intentionally narrows broader feature documents where this plan
  makes explicit v0 tradeoffs.
- Phase 9 expanded planning should preserve the `StageContext` helper intent
  for artifact-store, output-path, and save/register ergonomics without widening
  v0 execution scope.
- Remaining blockers: none.

Every expanded phase plan in `docs/phases/` must include:

- Design impact.
- Future compatibility.
- Alternatives rejected.
- Debt introduced.
- Reviewability.
- Refinement and review budget status.

Approved phase PRs target `develop`. The managing agent may mark a phase
`merged` only after the approved PR has been merged into `develop` and the
phase worktree has been removed.

## Phased Implementation

### Phase 1 — Foundation

Status: pr_open
Branch: `codex/add-foundation-skeleton`
PR: body prepared at `docs/phases/add-foundation-skeleton-pr-body.md`; not
opened locally because `gh` is unavailable.

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

- Create import-safe package skeletons only for these Phase 1 paths:
  `src/loom/records`, `src/loom/provenance`, `src/loom/serialization`,
  `src/loom/io`, `src/loom/config`, `src/loom/pipeline`,
  `src/loom/pipeline/graph`, `src/loom/pipeline/planning`,
  `src/loom/pipeline/execution`, `src/loom/pipeline/executors`,
  `src/loom/pipeline/stores`, and `src/loom/cli`.
- Defer deeper nested packages such as config recipes/instantiate, I/O
  sources/codecs, concrete stores, and concrete executors to their owning
  phases unless an import-safe unsupported stub is required by this phase's
  public import tests.
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
- Run `make validate-pr` and `make test-summary`.

Notes:

- Source references: `docs/structure.md` sections "Source-Tree Boundary",
  "Repository Layout", "Target Source Tree", "Import and Dependency Shape",
  "Public API Policy", "Module Responsibilities", "CLI", and "Review
  Checklist"; `docs/loom.md` sections 1, 2, 3, 4, 12, 14;
  `docs/features/core-model.md`, `docs/features/errors.md`,
  `docs/features/timestamps.md`, `docs/features/protocols.md`,
  `docs/features/testing.md`, and `docs/features/cli.md` for import-safe
  unsupported CLI stubs only.
- `loom.ids` should define simple aliases only, not `NewType` or wrapper
  classes.

Completion summary:

- Phase 1 foundation skeleton implemented on
  `codex/add-foundation-skeleton` in worktree
  `/home/samcantrill/work/loom-worktrees/add-foundation-skeleton`.
- Added import-safe Phase 1 package boundaries, shared ID aliases, broad
  catchable errors, UTC timestamp helpers, and explicit unsupported config
  stubs without adding runtime dependencies or future-phase behavior.
- Added package and unit coverage for imports, import boundaries, public
  surfaces, deferred stubs, errors, IDs, and timestamps.
- Final PR-prep validation on 2026-05-03:
  `UV_CACHE_DIR=/tmp/uv-cache make validate-pr` passed; Ruff passed, Pyright
  reported 0 errors, default tests passed with 24 passed, and build succeeded.
- Suite summary on 2026-05-03:
  `UV_CACHE_DIR=/tmp/uv-cache make test-summary` passed and wrote
  `build/test-summary.md`; package and unit suites passed, while contract,
  integration, and e2e suites are not present for this phase.
- Implementation refinement budget: used. PR review budget: unused.
- Remaining blockers: none for manager-side PR submission or review.

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
- Lightweight provenance capture helpers cover git state when available,
  standard-library environment facts, selected package versions through
  `importlib.metadata`, command argv/cwd, and artifact input/output lineage.
  Helpers must degrade to explicit unavailable/unknown values rather than
  requiring git, network access, or heavyweight dependency inspection.
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
- `ResourceRef.codec_key` round-trips when set, omitted, or explicitly `None`.
- Manifests reject duplicate record IDs and preserve deterministic iteration.
- Manifest views support generic filtering without domain semantics.
- Fingerprints are deterministic across mapping insertion order.
- Serialization outputs only plain structured data.
- Serialization does not import the I/O subsystem.

Test expectations:

- Add focused tests for refs, artifacts, records, manifests, provenance,
  lightweight provenance capture, fingerprints, optional `ResourceRef.codec_key`
  serialization, plain-data serialization, dataclass conversion, JSON helpers,
  and schema helpers.
- Run `make validate-pr` and `make test-summary`.

Notes:

- Source references: `docs/structure.md` sections "Target Source Tree",
  "Import and Dependency Shape", "Public API Policy", "Core Model",
  "Serialization", "Provenance and Resume", and "Test Layout";
  `docs/loom.md` sections 6.1, 6.2, 6.3, 10, 11, 12;
  `docs/features/core-model.md`, `docs/features/serialization.md`,
  `docs/features/provenance.md`, `docs/features/artifacts.md`, and
  `docs/features/fingerprints.md`; use `docs/features/protocols.md`,
  `docs/features/timestamps.md`, and `docs/features/errors.md` for shared
  protocol, UTC metadata, and base error guidance.
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
- Run `make validate-pr` and `make test-summary`.

Notes:

- Source references: `docs/structure.md` sections "Source-Tree Boundary",
  "Target Source Tree", "Import and Dependency Shape", "I/O", "Runtime
  Dependency Policy", and "Test Layout"; `docs/loom.md` sections 4, 6.1, 6.3;
  `docs/features/io.md`, `docs/features/artifacts.md`,
  `docs/features/serialization.md`, `docs/features/fingerprints.md`, and
  `docs/features/testing.md`.
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
- Return `ComposedConfig` with resolved config, redacted config, provenance,
  empty `recipe_manifest`, and fingerprint.

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
- Until Phase 5 implements recipes, `compose_config` must reject `_recipe_`
  blocks with a clear unsupported-recipe `ConfigError` and return an empty
  recipe manifest for configs without recipes.
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
- `_recipe_` keys fail clearly as unsupported until Phase 5 rather than being
  ignored or partially expanded.
- Secret-like keys are redacted recursively.
- Config provenance and fingerprints change when source inputs change.

Test expectations:

- Add focused tests for config loading, merge, overrides, interpolation,
  validation, redaction, composition, and provenance.
- Run `make validate-pr` and `make test-summary`.

Notes:

- Source references: `docs/features/config.md` sections 1 through 10, 13
  through 16, 18; `docs/structure.md` sections "Configuration", "Runtime
  Dependency Policy", "Module Responsibilities", "Documentation Map", and
  "Test Layout"; `docs/loom.md` sections 7, 11, 12, 14;
  `docs/features/provenance.md`, `docs/features/fingerprints.md`,
  `docs/features/errors.md`, and `docs/features/testing.md`.
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
- Phase 5 updates `ComposedConfig.recipe_manifest` from the Phase 4 empty
  manifest to the deterministic list of recipe expansion records.
- Target imports support `package.module.Class`, `package.module:function`, and
  `package.module:Class`, with path-aware import and constructor errors.
- Recursive instantiation handles nested mappings/sequences, `_args_`,
  `_partial_=true`, and `_inject_` from an explicit runtime dependency mapping.
- Reserved keys are `_target_`, `_args_`, `_partial_`, `_inject_`, and
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
- Recipe argument pre-resolution supports references to composed base, overlay,
  and override values, and expanded recipe blocks participate in the final
  interpolation pass.
- Target import supports documented path forms and reports path-aware errors.
- Recursive instantiation handles nested mappings/sequences, positional args,
  partials, and runtime injection.
- Trusted config behavior is documented.

Test expectations:

- Add focused tests for recipes, recipe catalog behavior, recipe expansion,
  recipe argument pre-resolution, final interpolation after expansion, target
  imports, recursive instantiation, and injection.
- Run `make validate-pr` and `make test-summary`.

Notes:

- Source references: `docs/features/config.md` sections 5.6, 5.7, 6.3, 7, 11,
  12, 16, 18; `docs/structure.md` sections "Configuration", "Import and
  Dependency Shape", "Runtime Dependency Policy", "What Stays Out of loom",
  and "Test Layout"; `docs/features/errors.md`,
  `docs/features/protocols.md`, `docs/features/testing.md`, and
  `docs/features/plugins.md` only for deferred entry-point discovery boundaries.
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
- Parse only documented orchestration fields from stage config and preserve
  `config` as runtime stage config.
- Support `stage.output` input references and distinguish data dependencies
  from control-only dependencies parsed from authored `depends_on`.
- Define the exact v0 spec surface: authored stage mappings support only
  `name`, `_target_`, `config`, `depends_on`, `inputs`, `outputs`, and
  `resources`.
  `PipelineSpec` supports `stages`, optional `name`, optional `description`,
  optional metadata, and optional `schema_version` defaulting to `None`;
  pipeline-level defaults are deferred and must be rejected if authored.
  `StageSpec` stores the `_target_` value as `target_path`. `OutputSpec`
  supports only `artifact_type`, optional `codec_key`, optional
  `schema_version` defaulting to `None`, and optional metadata that is preserved
  for inspection.
  Stage `runtime`, `retry`, `when`, stage metadata, and output `path` are
  deferred and must be rejected if authored in v0 configs.
  Stage `resources` must be plain-data-compatible opaque metadata only; v0 does
  not interpret scheduler-specific fields or include resource changes in stage
  fingerprints by default.

Implementation checkpoints:

- `OutputSpec`, `StageSpec`, and `PipelineSpec` are frozen dataclasses that
  preserve authored order but validate execution order separately.
- `StageSpec` stores `target_path`, `stage_config`, `dependencies`,
  `inputs`, `outputs`, and `resources`.
- `OutputSpec` stores `artifact_type`, optional `codec_key`, optional
  `schema_version` defaulting to `None`, and optional metadata. It does not
  store path templates in v0; physical artifact paths are allocated by the
  artifact store.
- `StageContext` defines the minimal generic context value shape only: run/stage
  IDs, run/stage paths, resolved config, stage config, provenance, and metadata.
  Store-backed context fields and stage-bound artifact helpers are added after
  store protocols and runner wiring exist in Phase 7 and Phase 9.
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
- Deferred fields such as stage `runtime`, `retry`, `when`, stage metadata, and
  output `path` fail with clear validation errors instead of being silently
  preserved.
- Duplicate stages, missing outputs, bad output specs, bad refs, unknown stages,
  unknown outputs, cycles, and self-dependencies fail clearly.
- Topological sort works for linear, branching, and diamond DAGs.
- Dummy stages satisfy the stage protocol without inheritance.

Test expectations:

- Add focused tests for pipeline specs, stage contract, context, status,
  validation, graph helpers, and bindings.
- Run `make validate-pr` and `make test-summary`.

Notes:

- Source references: `docs/structure.md` sections "Pipeline Model and
  Planning", "Execution and Executors", "Stores and State", "Test Layout",
  and "Review Checklist"; `docs/loom.md` sections 6.4, 6.5, 8, 12, 14;
  `docs/features/pipeline.md`, `docs/features/pipeline-graph.md`,
  `docs/features/runtime-resources.md`, `docs/features/state.md`, and
  `docs/features/protocols.md`, `docs/features/errors.md`, and
  `docs/features/testing.md`.

Completion summary:

- Pending.

### Phase 7 — Local Stores And Run Layout

Status: pending
Branch: `codex/add-local-stores-run-layout`
PR: pending

Goal:

- Implement durable local artifact/run state, atomic writes, and the inspectable
  local run directory layout without planning or executing stages.

Scope:

- Add artifact and run store protocols.
- Add local artifact and run stores, atomic write helpers, and run/artifact
  indexes.
- Define and persist the inspectable local run directory layout, including root
  run status, execution plan files, and stage failure files.

Implementation checkpoints:

- `ArtifactStore` exposes `save`, `load`, `register`, `exists`, and `validate`.
  `LocalArtifactStore` uses `CodecRegistry`, writes through temp paths and
  atomic moves where possible, computes stored-byte checksums, and returns typed
  `ArtifactRef`s.
- `register` accepts already-written local files or file URIs, records checksums
  when requested, supports optional `codec_key`, and does not attempt generic
  serialization.
- `RunStore` exposes run/stage directory resolution plus run status, plan,
  stage status, input, output, fingerprint, failure, artifact index, config, and
  provenance read/write helpers.
- Local run layout includes config files, stage state files, logs, per-stage
  artifact directories, `artifacts.json`, `run.json`, `status.json`,
  `plan.json`, stage `failure.json`, and provenance files.
- Atomic helpers cover JSON, text, bytes, replacement, directory creation, and
  unique temp filenames.
- Artifact indexes use logical keys of the form `stage.output`.

Design and review notes:

- Design impact: creates durable local state and file-layout contracts without
  invoking user stage code or making resume decisions.
- Future compatibility: store protocols keep remote stores and global run
  discovery possible later.
- Alternatives rejected: no actual stage execution, resume planner, remote
  stores, cross-run cache reuse, or lock manager unless tests prove one is
  required.
- Debt introduced: v0 relies on atomic writes, not a full lock manager. Revisit
  if interrupted-run tests expose race conditions.
- Reviewability: stores, indexes, atomic writes, and file layout should be
  testable without graph planning or stage execution.

Out of scope:

- Actual stage execution.
- Resume planning and downstream invalidation.
- Stage fingerprint calculation.
- Remote stores.
- Cross-run cache reuse.
- Lock managers unless tests prove they are required.

Acceptance criteria:

- Artifacts save/load through JSON, text, and bytes codecs.
- Already-written local files can be registered as artifacts with optional
  `codec_key`.
- `ArtifactStore.load` fails clearly for codec-less artifacts unless an explicit
  codec is supplied.
- Checksums are written and validated.
- Run directory state is written atomically where possible.
- Run status, plan, stage status, inputs, outputs, fingerprints, failures,
  artifact indexes, config snapshots, and provenance paths are read and written
  through the run store.
- Local run directories contain the required v0 files and remain inspectable as
  plain JSON/YAML/text where applicable.

Test expectations:

- Add focused tests for artifact store, run store, atomic writes, indexes,
  manual registration, codec-less artifacts, and run layout.
- Run `make validate-pr` and `make test-summary`.

Notes:

- Source references: `docs/structure.md` sections "Stores and State",
  "Provenance and Resume", "Runtime Dependency Policy", "Test Layout", and
  "Review Checklist"; `docs/loom.md` sections 9, 10, 11;
  `docs/features/run-store.md`, `docs/features/artifacts.md`,
  `docs/features/io.md`, `docs/features/serialization.md`,
  `docs/features/state.md`, `docs/features/provenance.md`,
  `docs/features/fingerprints.md`, `docs/features/reliability.md`, and
  `docs/features/testing.md`.

Completion summary:

- Pending.

### Phase 8 — Planning, Resume, And Selectors

Status: pending
Branch: `codex/add-planning-resume-selectors`
PR: pending

Goal:

- Implement deterministic execution planning, selectors, stage fingerprints,
  conservative same-run-directory resume checks, and downstream invalidation
  without executing stages.

Scope:

- Add stage fingerprint calculation, execution plan models, plan explanations,
  selector models, resume checks, and downstream invalidation.
- Bind stage inputs from upstream outputs and existing run-store state.
- Persist dry-run or computed plans through the run store but do not invoke user
  stage code.

Implementation checkpoints:

- Fingerprints include stage name, target path, stage config, output specs,
  bound inputs, Python version, `loom` version, relevant git state, configured
  dependency versions, and configured extra fields.
- Fingerprints exclude noisy values such as wall-clock timestamps, logs, temp
  paths, and random run IDs unless explicitly configured.
- Stage `resources` are excluded from v0 semantic fingerprints by default.
  Future runtime/resource phases may add an explicit opt-in policy if resource
  changes are shown to affect outputs.
- Selector models support Python-safe fields `force_stages`, `from_stage`,
  `only_stages`, and `skip_stages` as deterministic planner inputs. CLI aliases
  such as `force`, `from`, `only`, and `skip` remain deferred.
- Planning emits ordered stage decisions, bound input refs, fingerprint data,
  skip/run reasons, invalidation reasons, and dry-run explanations.
- Resume returns `REUSE` only for a previous `SUCCEEDED` stage with matching
  fingerprint, existing `outputs.json`, existing artifacts, and valid checksums.
- Interrupted, corrupt, stale, failed, or partial state is never reusable.
- Downstream invalidation propagates for changed config, target, output specs,
  selector decisions, or upstream artifacts.

Design and review notes:

- Design impact: creates conservative, inspectable resume decisions before the
  runner executes user code.
- Future compatibility: explicit selector and plan models keep future CLI,
  remote stores, and alternate executors from reimplementing resume policy.
- Alternatives rejected: no actual stage execution, remote stores, cross-run
  cache reuse, or ad hoc runner-only selectors in this phase.
- Debt introduced: same-run-directory resume remains the only reuse mode.
  Revisit after local execution and invalidation tests are stable.
- Reviewability: fingerprints, selectors, resume, and invalidation should be
  testable as pure planning behavior over synthetic store state.

Out of scope:

- Actual stage execution.
- Subprocess execution.
- SLURM or distributed executors.
- Remote stores.
- Cross-run cache reuse.
- CLI behavior.

Acceptance criteria:

- Planner computes bound inputs and topological stage plans.
- Selectors `force_stages`, `from_stage`, `only_stages`, and `skip_stages`
  affect plan decisions deterministically and record explanations.
- Resume returns `REUSE` only for valid succeeded stages with matching
  fingerprints, existing outputs, existing artifacts, and valid checksums.
- Interrupted, corrupt, stale, failed, or partial state is never reusable.
- Downstream invalidation propagates for changed config, target, output specs,
  selector decisions, or upstream artifacts.
- Plan files can be persisted and read through the run store.

Test expectations:

- Add focused tests for fingerprint inputs/exclusions, planner behavior,
  selectors, resume decisions, dry-run explanations, and invalidation.
- Run `make validate-pr` and `make test-summary`.

Notes:

- Source references: `docs/structure.md` sections "Pipeline Model and
  Planning", "Stores and State", "Provenance and Resume", "Runtime Dependency
  Policy", "Test Layout", and "Review Checklist"; `docs/loom.md` sections 9,
  10, 11; `docs/features/pipeline.md`, `docs/features/run-store.md`,
  `docs/features/pipeline-graph.md`, `docs/features/runtime-resources.md`,
  `docs/features/state.md`, `docs/features/fingerprints.md`,
  `docs/features/resume.md`, and `docs/features/testing.md`.
- Fingerprints must exclude noisy values unless explicitly configured.

Completion summary:

- Pending.

### Phase 9 — Local Execution

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
- Lifecycle helpers mark stages running, succeeded, failed, selector-skipped,
  and finalized through the run store.
- `PipelineRunner` accepts a composed config or resolved mapping plus run
  options, writes config/provenance, parses the pipeline, instantiates targets
  without constructor kwargs in v0, builds contexts, asks the planner for work,
  executes runnable stages, validates returned outputs, writes state, updates
  indexes, persists provenance capture files, and finalizes `run.json` and
  `status.json`.
- Output validation requires returned keys to match declared outputs exactly,
  each value to be an `ArtifactRef`, artifact type to match the output spec,
  declared codec keys to match when present, referenced files to exist, and
  checksums to validate when present.
- Failure behavior writes `failure.json` with error context before writing
  `FAILED` status, avoids executing downstream stages in the same run, marks the
  run failed, and leaves state inspectable.
- Resume behavior is same-run-directory only; valid unchanged stages produce
  `REUSE` planner decisions while retaining prior `SUCCEEDED` state. `SKIP` and
  `SKIPPED` are reserved for selector or condition exclusion.

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
  input, output, artifact, plan, and index files.
- Same-run-directory reruns produce `REUSE` planner decisions for valid
  unchanged stages without persisting `SKIPPED` status.
- Changed stage config or upstream artifacts rerun the changed stage and
  downstream dependents.
- Invalid stage outputs fail with path-aware errors.
- Stage exceptions persist failure state before failed status and leave
  inspectable run state.

Test expectations:

- Add focused tests for local executor, pipeline runner, lifecycle, e2e
  pipeline behavior, failure persistence, and generic dummy stages.
- Run `make validate-pr` and `make test-summary`.

Notes:

- Source references: `docs/structure.md` sections "Execution and Executors",
  "Pipeline Model and Planning", "Stores and State", "Runtime Dependency
  Policy", "Test Layout", and "Review Checklist"; `docs/loom.md` sections 8
  through 12; `docs/features/pipeline.md`, `docs/features/execution.md`,
  `docs/features/run-store.md`, `docs/features/artifacts.md`,
  `docs/features/provenance.md`, `docs/features/resume.md`,
  `docs/features/state.md`, `docs/features/runtime-resources.md`, and
  `docs/features/testing.md`.
- The runner, not the stage, owns lifecycle, output validation, status writes,
  fingerprints, and resume decisions.

Completion summary:

- Pending.

### Phase 10 — Hardening And Documentation

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
  contract, artifact saving/registering, output specs with optional codecs, run
  directory layout, checksums vs fingerprints, selectors, and
  same-run-directory resume.
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
  contract, artifact saving/registering, output specs, run directory layout,
  checksums vs fingerprints, selectors, and same-run-directory resume.

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
- Run `make validate-pr` and `make test-summary`.

Notes:

- Source references: `docs/structure.md` sections "Review Checklist", "Test
  Layout", "Runtime Dependency Policy", and "What Stays Out of loom";
  `docs/features/config.md` sections 14, 16, 19; `docs/loom.md` sections 9
  through 16; `docs/features/errors.md`, `docs/features/reliability.md`,
  `docs/features/run-store.md`, `docs/features/artifacts.md`,
  `docs/features/io.md`, `docs/features/fingerprints.md`,
  `docs/features/resume.md`, `docs/features/provenance.md`,
  `docs/features/testing.md`, and `docs/features/cli.md`.
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

Deferred feature documents such as `docs/features/remote-stores.md`,
`docs/features/slurm.md`, `docs/features/container-executors.md`,
`docs/features/sweeps.md`, `docs/features/plugins.md`,
`docs/features/preflight.md`, `docs/features/run-catalog.md`, and the
post-v0 portions of `docs/features/cli.md` are planning context only for this
v0 plan. Agents may use them to preserve boundaries and future compatibility,
but they must not implement those behaviors in v0 phases unless a later plan
explicitly changes the scope.

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
  validation, optional output codec keys, and stage output validation.
- Artifact/run store atomic writes, manual artifact registration, codec-less
  artifact validation, artifact indexes, status transitions, plan files, failure
  files, resume decisions, selector decisions, invalidation, and corrupt state
  handling, including checksum mismatch detection in default validation when a
  checksum exists and the store can read the URI.

End-to-end tests should cover:

- Running a synthetic local pipeline from YAML.
- Verifying run directories contain config, provenance, status, plan,
  fingerprint, input, output, artifact, and index files.
- Rerunning the same run directory and reusing unchanged stages through `REUSE`
  planner decisions.
- Rerunning changed stages and downstream dependents after config or upstream
  artifact changes.
- Applying `force_stages`, `from_stage`, `only_stages`, and `skip_stages`
  selectors through the public Python planning or runner APIs.
- Refusing reuse when artifact files are missing or corrupt.
- Refusing reuse by default when a readable local artifact has a checksum
  mismatch.
- Failing with path-aware errors for undeclared, missing, wrong-type,
  wrong-codec, or non-existent outputs.
- Persisting failure/status/provenance cleanly after stage failure.

Phase agents should plan and implement tests during the phase rather than
leaving coverage creation for PR preparation. Expanded phase plans must identify
required package, unit, contract, integration, e2e, and opt-in suite coverage,
or explicitly defer suites that do not apply to the phase. PR preparation owns
the final suite summary and validation evidence, not new test design.

Final acceptance gates:

```sh
make validate-pr
make test-summary
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
- Stage `config` is runtime invocation config available through `StageContext`,
  not constructor kwargs for the stage target.
- Output `codec_key` is optional. Generic `load` requires a codec key or an
  explicit codec, but existence/checksum validation still applies to codec-less
  artifacts.
- Public imports should remain stable even if internals are later refactored.
- Deferred features fail explicitly, not silently.
- Configs are trusted code; no sandbox or allow-list mode exists in v0.
- Every `loom` extension point remains domain-agnostic and structurally typed.
