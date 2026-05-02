# Implementation Plan

## Goal

Implement `loom` v0 as a source-tree-first, fully typed Python package aligned
with the boundaries in `docs/structure.md`, `docs/config.md`, `docs/loom.md`,
and the subsystem specifications in `docs/`.

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
  11, 12; `docs/core-model.md`, `docs/artifacts.md`, and
  `docs/fingerprints.md`.
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
  22 Phase 2, 23.2; `docs/loom.md` sections 4, 6.1, 6.3; `docs/io.md` and
  `docs/artifacts.md`.
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

- Source references: `docs/config.md` sections 1 through 10, 13 through 16,
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

- Source references: `docs/config.md` sections 5.6, 5.7, 6.3, 7, 11, 12, 16,
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
  `docs/pipeline.md`, `docs/state.md`, and `docs/testing.md`.

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
  `docs/run-store.md`, `docs/artifacts.md`, `docs/fingerprints.md`, and
  `docs/resume.md`.
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
  `docs/pipeline.md`, `docs/execution.md`, `docs/run-store.md`,
  `docs/resume.md`, and `docs/testing.md`.
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
  24, 25; `docs/config.md` sections 14, 16, 19; `docs/loom.md` sections 9
  through 16; `docs/run-store.md`, `docs/resume.md`, `docs/testing.md`, and
  `docs/cli.md`.
- This phase should harden v0, not expand it into postponed features.

Completion summary:

- Pending.
