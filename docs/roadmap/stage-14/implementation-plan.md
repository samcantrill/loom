# Implementation Plan v14: Plugin Discovery

## Metadata

- Status: Phase 1 merged; ready for Phase 2 execution planning
- Roadmap stage: `v14`
- Source planning notes:
  `docs/roadmap/stage-14/planning.md`
- Workflow: `.codex/workflows/roadmap-stage-implementation.md`
- Related implementation plans:
  - `docs/roadmap/stage-13/implementation-plan.md`
  - `docs/roadmap/stage-12/implementation-plan.md`
- Related adjacent planning:
  - `docs/roadmap/stage-15/planning.md`
  - `docs/roadmap.md`
- Related source docs:
  - `docs/structure.md`
  - `docs/GLOSSARY.md`
  - `docs/features/plugins.md`
  - `docs/features/config.md`
  - `docs/features/io.md`
  - `docs/features/execution.md`
  - `docs/features/preflight.md`
  - `docs/features/provenance.md`
  - `docs/features/remote-stores.md`
  - `docs/features/testing.md`
- Draft pass: complete on 2026-05-15 from confirmed Stage 14 planning notes
- Refine pass: complete on 2026-05-15 after local plan-quality review
- Plan quality gate: passed on 2026-05-15 after local
  review/refinement/confirmation
- Current phase: Phase 2 pending execution planning
- Blockers:
  - No roadmap-stage planning blocker remains.
  - No plan-quality blocker remains; Phase 2 execution planning may begin.

## Summary

- Goal: implement explicit, deterministic plugin discovery for trusted
  installed packages, with load/register adapters for recipes and codecs and
  metadata-only listing/check support for future extension groups.
- Source functionality-agreement gate: confirmed in
  `docs/roadmap/stage-14/planning.md`.
- Approved behavior: metadata-only listing by default; explicit loading only;
  recipe and codec loaders over supplied registries; strict duplicate failures;
  selected CLI/preflight checks; plain plugin summaries; import-safety tests;
  future group listing/check; and plugin-readiness classifications.
- Source behavior confirmation: complete in the planning artifact.
- Key design constraints: keep `loom` domain-neutral, dependency-light, and
  import-safe; keep plugin discovery explicit and trusted; keep subsystem
  registries as owners of runtime semantics; do not load plugin targets from
  `import loom`, help paths, or unrelated commands.
- Source design-agreement gate: confirmed with DAQ-1 through DAQ-10.
- Future-roadmap impact: Stage 12 run exporters, Stage 13 sweep providers,
  Stage 15/16 artifact-store backends, and Stage 19 event sinks remain
  listing/check-first until their owning contracts define loadable registry or
  factory semantics.
- Reusable interface, adapter, or protocol assumptions: generic discovery
  provides metadata and explicit loading; contract-specific adapters normalize
  loaded objects and register them into caller-supplied registries; Stage 14
  does not define a universal plugin object protocol.
- Examples covered: fake entry point listing, recipe registration, codec
  registration, duplicate diagnostics, best-effort failure aggregation, import
  and CLI help safety, preflight plugin failures, future group readiness, and
  artifact-store backend listing-only behavior.
- Source phase shaping: four phases confirmed in the planning artifact.
- Source plan quality gate: passed on 2026-05-15 after local
  review/refinement/confirmation.
- Out of scope: plugin marketplace behavior, install/upgrade/version solving,
  remote indexes, sandboxing, third-party CLI command injection, concrete
  service integrations, source/executor/artifact-store/exporter/provider/event
  registration before stable owning contracts exist, and artifact-store backend
  loading before Stage 15.

## Goal

Implement v14 as Loom's plugin discovery layer: a small, explicit package that
lets trusted installed packages advertise extension points through known Python
entry point groups, lets users and tooling inspect those advertisements without
importing plugin targets, and lets project setup code explicitly load supported
recipe and codec plugins into supplied registries.

The implementation should establish a durable pattern for future extension
types without forcing stores, executors, exporters, sweep providers, or event
sinks into premature object shapes.

## Context

The repository already has the stable targets needed for the first concrete
plugin adapters:

- `RecipeCatalog.register(name, recipe, replace=False)` exists and owns recipe
  naming, validation, and replacement behavior.
- `CodecRegistry.register(codec)` exists and owns runtime codec keys. It has no
  replacement API, so duplicate codec keys must fail in Stage 14.
- `importlib.metadata` from the Python standard library is enough for package
  entry point discovery; no dependency is needed.
- The CLI is already an outer presentation layer over Python APIs.
- Preflight has structured result models that can report diagnostics without
  mutating run state.

The repository also has several extension surfaces that are intentionally not
ready for full plugin loading:

- Sources have a `DataSource` protocol but no source registry.
- Executors have `Executor` and `ExecutorDescriptorRegistry`, but no stable
  executor implementation descriptor/factory/registry contract.
- Artifact stores have local/runtime protocols, but Stage 15 owns backend
  descriptors, config, capabilities, registry, preflight, URI validation, and
  operation semantics.
- Run exporters and sweep providers are adjacent roadmap surfaces whose landed
  APIs must be rechecked before any loader is promised.
- Event sinks wait for Stage 19 runtime event and sink registry contracts.

Implementation-plan source recheck on 2026-05-15 found no source-level
`RunExporter`, `RunImporter`, `loom.pipeline.sweep`, `SweepProvider`,
`EventSink`, or `EventSinkRegistry` contracts in `src/loom`, and found only the
local-root `ArtifactStoreFactory` plus executor capability descriptors. This
plan therefore keeps sources, executors, artifact-store backends, run exporters,
sweep providers, and event sinks listing/check-only for Stage 14.

## Planning Readiness

- Source planning notes:
  `docs/roadmap/stage-14/planning.md`
- Functionality and behavior baseline:
  complete. The notes lock explicit discovery, metadata-only listing by
  default, explicit loading, recipe and codec loaders, future group
  listing/check, selected CLI/preflight diagnostics, plugin summaries, and
  import-safety coverage.
- Design-safety review:
  passed. The review revised the artifact-store backend group to
  `loom.artifact_store_backends` and found no blockers.
- Targeted artifact-store backend addendum:
  complete. DAQ-10 requires Stage 14 to keep artifact-store backend behavior
  metadata-only. Stage 14 must not expose a backend loader, accept raw
  `ArtifactStore` instances or local-root `ArtifactStoreFactory` callables,
  mutate a store registry, wire plugin discovery into runner/preflight
  internals, or claim advertised backends are run-ready.
- Examples and validation strategy:
  complete. Validation uses fake entry points, fake registries, import-boundary
  assertions, CLI tests, preflight diagnostics, provenance-summary tests, and
  readiness documentation. No network, service SDK, installed third-party
  plugin package, or optional backend dependency is required.
- Phase shaping:
  complete; four implementation phases are recorded below.
- Implementation readiness blockers from planning:
  none after final planning confirmation and targeted artifact-store addendum.
- Accepted risks and revisit triggers:
  future groups are public before every loader exists; codec replacement is not
  supported; plugin summaries are not versioned persisted provenance schemas;
  Stage 12/13 source APIs were rechecked and exporter/provider loaders remain
  deferred; and artifact-store backend loading must wait for Stage 15 backend
  descriptor and registry contracts.

## Desired Outcome

When all phases are complete:

- `src/loom/plugins/` exists with import-light public APIs for known group
  constants, plugin records, load results, duplicate/failure records, generic
  listing/loading helpers, recipe/codec loader adapters, and plugin errors.
- `list_entry_points(...)` returns deterministic `PluginRecord` values without
  importing plugin targets.
- `load_entry_points(...)` loads only selected records explicitly and reports
  strict or best-effort load outcomes with enough package/group/name/value
  context to debug failures.
- `load_recipe_entry_points(...)` loads selected recipe entry points into a
  supplied `RecipeCatalog`, using the entry point name as the recipe name.
- `load_codec_entry_points(...)` loads selected codec entry points into a
  supplied `CodecRegistry`, accepting codec instances, no-arg codec classes, or
  no-arg factories and registering by runtime `codec.key`.
- `loom plugins list` and `loom plugins check` expose text and JSON
  diagnostics over the public plugin APIs.
- Preflight can report requested plugin availability/load/duplicate failures
  without scanning and importing every installed plugin.
- Plugin records/results expose plain summaries for CLI, preflight, and future
  provenance consumers without serializing loaded Python objects.
- Future groups are discoverable and clearly labelled listing/check-first until
  their owning contracts land.
- `loom.artifact_store_backends` is exported and tested as a metadata-only
  entry point group; Stage 14 never constructs, validates, or registers
  artifact-store backend objects.

## Non-Goals

- No plugin marketplace, package installation, upgrade flow, dependency
  resolution, version solving, remote plugin index, or trust scoring.
- No Python sandboxing or support for untrusted plugin execution.
- No concrete MLflow, DVC, W&B, OpenTelemetry, cloud, notification, optimizer,
  event-sink, callback, hook, or service integration.
- No third-party command injection into the core `loom` CLI.
- No plugin discovery or target loading during `import loom`, package imports,
  help commands, or unrelated commands.
- No source, executor, artifact-store backend, run-exporter, sweep-provider, or
  event-sink registration loaders before their owning contracts are stable.
- No artifact-store backend descriptor, registry, credential probing, URI
  validation, capability model, materialization, cache/staging behavior, or
  runner integration in Stage 14.

## Constraints

- Keep `loom` domain-neutral.
- Preserve source-tree and import boundaries from `docs/structure.md`.
- Do not introduce heavyweight runtime dependencies.
- Use only standard-library entry point discovery.
- Treat installed plugin packages as trusted project/environment code, while
  making plugin loading explicit.
- Keep subsystem registries as owners of runtime semantics, object shapes, key
  policy, replacement policy, and execution behavior.
- Keep CLI and preflight as outer callers of plugin APIs.
- Use fake entry points and fake registries in tests; do not depend on real
  installed extension packages.
- Run `make validate-pr` and `make test-summary` before each phase PR is
  prepared, or record why either command could not run.

## Design Principles

- Metadata first: listing entry points must not import plugin targets.
- Explicit loading: any import of third-party plugin code must be a selected
  user/API/check action.
- Fail closed: duplicates, invalid objects, missing requested plugins, and
  unsupported registration requests should not silently proceed.
- Registry ownership: `loom.plugins` coordinates discovery and loading, while
  subsystem registries own runtime contracts.
- Plain summaries: CLI, preflight, and provenance-facing data must omit loaded
  Python objects, credentials, large reprs, and unsafe traceback internals.
- Future group honesty: public group constants are durable metadata namespaces,
  not promises that Stage 14 can register every advertised object.

## Key Design Choices

- Add `src/loom/plugins/` rather than placing discovery in config, I/O,
  pipeline, stores, or CLI.
- Keep generic discovery in an import-light module that depends on the standard
  library plus lightweight Loom value/error helpers.
- Split registry-specific adapters only if needed to avoid generic discovery
  importing subsystem registry types.
- Use entry point name as the recipe name.
- Use runtime `codec.key` as the codec registry key.
- Do not add `CodecRegistry` replacement support in Stage 14.
- Keep `PluginLoadResult` and summaries separate so Python callers can access
  loaded objects while JSON/provenance consumers receive plain data.
- Expose `loom.artifact_store_backends` as the artifact-store backend group,
  but keep it metadata-only until Stage 15 defines the backend contract.

## Conflicts And Tradeoffs

- Exposing future group names before loaders exist helps downstream packages
  reserve stable metadata, but it can imply false capability. The plan mitigates
  this with readiness classifications, listing-only CLI wording, and tests.
- Import-only plugin checks can help debug broken packages, but they can also
  import optional SDKs. The plan keeps metadata checks as the default for
  listing-only groups and requires explicit import-only wording if such checks
  are ever exposed.
- Recipe replacement exists in `RecipeCatalog`, but codec replacement does not.
  The plan preserves registry-specific policy rather than forcing uniform
  replacement semantics.
- Artifact-store backend shape is especially sensitive because it is external
  and internally cross-cutting. The plan keeps Stage 14 strict and defers all
  backend object semantics to Stage 15.

## Maintainability Assessment

The design centralizes entry point metadata handling in one small package while
leaving runtime semantics in existing subsystem registries. That avoids hidden
discovery behavior in config, I/O, pipeline, stores, and CLI modules.

The highest maintainability risk is future groups looking more capable than
they are. Each phase must keep docs, CLI output, and tests explicit about
listing-only groups. The artifact-store backend group requires the strongest
guardrail: it must remain metadata-only and must not be wired into runner or
preflight artifact-store internals before Stage 15.

## Extensibility Assessment

The reusable extension pattern is:

1. List entry point metadata.
2. Explicitly load selected targets.
3. Normalize object shape in a contract-specific adapter.
4. Register into a caller-supplied registry owned by the target subsystem.
5. Return structured load results and plain summaries.

This pattern is reusable for later source, executor, exporter, provider, store,
and event-sink loaders without forcing them to share a universal plugin object
protocol. Future artifact-store backend loading should adapt entry points into
a Stage 15 store-owned descriptor/factory registry with explicit contract/API
versioning.

## Technical Debt Ledger

| Debt | Reason accepted | Revisit trigger |
| --- | --- | --- |
| Future groups are public before every loader exists | Downstream metadata stability and inspection are useful now | Owning registry/protocol lands for source, executor, artifact-store backend, run exporter, sweep provider, or event sink |
| No codec replacement support | Deterministic duplicate failure matches current `CodecRegistry` | `CodecRegistry` gains explicit replacement semantics through a future design |
| Plugin summaries are not persisted provenance schemas | `loom.plugins` should not own run-store/provenance persistence | Provenance wiring needs a versioned plugin-summary schema |
| Artifact-store backend group exists before backend contract | Group namespace stability is useful, but Stage 15 owns backend semantics | Stage 15 defines backend descriptor/factory, backend registry, config handoff, capabilities, redaction, preflight, and operation result contracts |

## Implementation Workflow State

- Implementation-plan quality gate: passed
- Review pass: complete by managing Codex local review using
  `.codex/prompts/implementation-plan-review.md` criteria. No separate
  reviewer subagent was used because this turn did not request delegated agent
  work.
- Refinement pass: used to update cross-links, record source recheck evidence,
  and tighten future-group loader deferrals.
- Confirmation review: complete; no blocking findings remain.
- Budget status: review used, refinement used, confirmation used.
- Automatic merge mode: enabled
- Worktree root: `/home/samcantrill/work/loom-worktrees`
- Default phase base/target: `develop`; each phase execution planner must
  recompute and record the actual stack predecessor and PR target before
  creating its worktree.
- Phase status vocabulary: `pending`, `in_progress`, `pr_open`, `approved`,
  `merged`, `blocked`

## Phase Index

| Phase | Slug | Status | Branch | PR | Ownership | Goal | Validation | Examples |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| 1 | `plugin-records-discovery` | merged | `codex/plugin-records-discovery` | [#156](https://github.com/samcantrill/loom/pull/156) | `src/loom/plugins`, package exports, fake entry point tests | Add plugin records, errors, group constants, deterministic listing/loading, and import-safety coverage | `make validate-pr`, `make test-summary`, and CI passed | Fake listing, duplicates, load failures, import safety |
| 2 | `recipe-codec-plugin-adapters` | pending | `codex/recipe-codec-plugin-adapters` | pending | Recipe and codec loader adapters plus contract tests | Add explicit recipe and codec entry point loading into supplied registries | Unit/contract tests plus `make validate-pr` before PR | Fake recipe load, fake codec instance/class/factory load, duplicate codec key |
| 3 | `plugin-cli-preflight-summaries` | pending | `codex/plugin-cli-preflight-summaries` | pending | CLI commands, preflight diagnostics, summary helpers | Expose plugin list/check, requested preflight checks, and plain summaries | CLI/unit/preflight tests plus `make validate-pr` before PR | Best-effort failures, CLI JSON/text, requested plugin preflight |
| 4 | `future-plugin-group-readiness` | pending | `codex/future-plugin-group-readiness` | pending | Future group constants/docs/tests and readiness classifications | Add listing/check coverage and docs for future groups, especially metadata-only artifact-store backends | Unit/CLI/preflight/docs tests plus `make validate-pr` and `make test-summary` before final PR | Future group listing, artifact-store backend listing-only, premature registration fail-closed |

## Implementation Readiness Blockers

| Blocker | Source | Required resolution | Status |
| --- | --- | --- | --- |
| Plan quality gate | Implementation workflow | Local review, one refinement pass, and confirmation review completed on 2026-05-15 before Phase 1 starts | resolved |

## Plan Quality Gate

- Status: passed
- Gate date: 2026-05-15
- Reviewer: managing Codex local review using the
  `.codex/prompts/implementation-plan-review.md` criteria. No separate reviewer
  subagent was used because this turn did not request delegated agent work.
- Review pass: complete; planning readiness, maintainability, extensibility,
  conflicting design choices, technical debt, test strategy, reviewability, and
  future-roadmap compatibility were checked.
- Refinement pass: used; the plan now points the planning artifact at this
  implementation plan, separates adjacent planning docs from implementation
  plans, records the 2026-05-15 source recheck for exporter/provider/event-sink
  readiness, and states that all non-recipe/non-codec groups remain
  listing/check-only for Stage 14.
- Confirmation review: complete; no blocking findings remain after the
  refinement.
- Budget status: review used, refinement used, confirmation used.
- Planning-readiness dependencies:
  - `docs/roadmap/stage-14/planning.md` records final planning confirmation
    after the targeted artifact-store backend addendum.
  - Design-safety review passed with no blockers.
  - No unresolved `blocked` or `needs discussion` planning decisions remain.
  - Examples, validation strategy, and phase shaping are specific enough to
    draft phases.
- Gate result:
  - Ready for Phase 1 execution planning.
  - No product implementation may begin until the Phase 1 execution plan exists
    and records branch, worktree, stack predecessor, target branch, scope,
    acceptance criteria, suite obligations, design impact, future
    compatibility, alternatives rejected, debt, reviewability, and budget
    status.

Findings from the review pass:

| Severity | Location | Finding | Resolution |
| --- | --- | --- | --- |
| Concern | Metadata and planning handoff | The draft still treated the implementation plan as absent from the planning artifact and grouped adjacent planning docs under implementation plans. That weakened traceability for the workflow handoff. | Updated the planning artifact link and separated implementation plans from adjacent planning sources in this plan. |
| Concern | `Context`, Phase 4 future-group readiness | The draft said Stage 12/13 APIs must be rechecked before promising exporter/provider loaders, but did not record the recheck result. That left room for a phase executor to infer loader scope. | Recorded the 2026-05-15 source recheck and made sources, executors, artifact-store backends, run exporters, sweep providers, and event sinks listing/check-only for Stage 14. |
| Note | `Implementation Workflow State`, phase branch metadata | The phase tables list `develop` as the default base/target for all phases, but stacked continuation may require a later phase to branch from and target an unmerged predecessor. | The workflow state records `develop` as the default only and requires each phase execution planner to recompute and record the actual stack predecessor and PR target before implementation. |

The confirmation review verified that the plan preserves the final planning
artifact's explicit trusted plugin discovery boundary, metadata-only listing
default, recipe/codec supplied-registry adapters, strict duplicate handling,
plain summaries, CLI/preflight selection boundary, import-safety requirements,
future-group readiness labels, and DAQ-10 artifact-store backend
metadata-only constraint.

## Phase 1: Plugin Records And Generic Discovery

Status: merged
Slug: `plugin-records-discovery`
Branch: `codex/plugin-records-discovery`
Worktree: `/home/samcantrill/work/loom-worktrees/plugin-records-discovery`
PR: [#156](https://github.com/samcantrill/loom/pull/156), merged 2026-05-15
Base branch: `develop`
Target branch: `develop`
Workflow path: expanded path because this phase creates public APIs and
entry point group contracts

### Scope

- Goal: establish the public plugin package, record/result/error model, known
  group constants, metadata-only listing, explicit generic loading, duplicate
  detection, fake entry point seam, and import-safety tests.
- Files/modules owned:
  - `src/loom/plugins/__init__.py`
  - `src/loom/plugins/entrypoints.py`
  - `src/loom/plugins/errors.py`
  - package export tests under `tests/package`
  - plugin unit tests under `tests/unit/loom/plugins`
  - import-boundary tests under package or contract test areas
- Behavior implemented:
  - Known group constants:
    `loom.recipes`, `loom.codecs`, `loom.sources`, `loom.executors`,
    `loom.artifact_store_backends`, `loom.run_exporters`,
    `loom.sweep_providers`, and `loom.event_sinks`.
  - `PluginRecord`, `LoadedPlugin`, `PluginFailure`, `PluginDuplicate`, and
    `PluginLoadResult` or equivalent minimal records.
  - Plugin errors including discovery, load, duplicate, invalid, and
    registration context errors.
  - `list_entry_points(...)` metadata discovery without importing targets.
  - `load_entry_points(...)` selected explicit loading with strict and
    best-effort modes.
  - Deterministic ordering and duplicate entry point name detection.
- Decisions applied: DAQ-1, DAQ-2, DAQ-4, DAQ-6, DAQ-8, DAQ-10.
- Examples or docs covered: fake entry point listing, duplicate names, load
  failures, import safety.
- Out of scope:
  - Recipe/codec registry adapters.
  - CLI/preflight/provenance integration.
  - Future group registration loaders.
  - Artifact-store backend loading or validation.
- Dependencies: standard-library `importlib.metadata`; existing serialization
  and error conventions where useful.

### Tasks

- Add `loom.plugins` package and stable exports.
- Define group constants and document that group string values are the public
  metadata contract.
- Add frozen record/result types with plain-data conversion and object
  omission from summaries.
- Add error types that preserve plugin metadata context.
- Implement fakeable entry point listing with deterministic sort.
- Implement selected explicit loading with strict and best-effort modes.
- Add duplicate entry point detection by `(group, name)`.
- Add package and import-boundary tests proving imports/help paths do not load
  plugin targets.

### Validation

| Command/check | Purpose | Required before phase complete |
| --- | --- | --- |
| `uv run pytest tests/unit/loom/plugins tests/package tests/contracts` | Target plugin records, discovery, package exports, and import-boundary contracts | yes |
| `make validate-pr` | Full PR gate for phase | yes |

### Acceptance Evidence

- Behavior evidence: fake entry points list deterministically without target
  imports; selected load imports only selected targets; strict and best-effort
  failures are covered.
- Design-decision evidence: no subsystem imports `loom.plugins`; no plugin
  discovery happens from package imports.
- Future-roadmap compatibility evidence: future group constants exist with no
  loader promise.
- Interface, adapter, or protocol reuse evidence: generic result model can be
  reused by adapters without imposing a universal plugin protocol.
- Documentation evidence: public group constants and trusted explicit loading
  are documented or covered by API docstrings/tests.
- Domain-neutrality evidence: tests use generic fake plugins, no service SDKs
  or domain-specific integrations.

### Phase Workflow State

- Phase execution plan: completed in
  `docs/roadmap/stage-14/phases/plugin-records-discovery.md`
- Planning/refinement budget: used for expanded-path planning
- Implementation/refinement budget: used for Phase 1 test-typing validation
  blocker found by Pyright
- PR review budget: used by manager local review before merge
- Blocker-resolution budget: unused
- Pre-submit blocker gate: passed; no unresolved API/import-boundary blocker
- Merge record: merged into `develop` by PR #156 at merge commit
  `78589eb761396a4399124d771859dbc8e00f012d`

### Risks And Stop Conditions

- Risks:
  - Group names become public once shipped.
  - `importlib.metadata` behavior differs across Python versions.
  - Result records can accidentally serialize loaded objects.
- Stop conditions:
  - Listing imports plugin targets.
  - Importing `loom`, `loom.config`, `loom.io`, or `loom.pipeline` discovers
    or loads plugins.
  - Public records cannot produce plain summaries without object serialization.
- Assumptions:
  - Python 3.12 standard-library entry point behavior is available.

### Completion Summary

- Implementation: added import-light `loom.plugins` package with public group
  constants, plugin records/results/errors, metadata-only listing, selected
  explicit loading, duplicate detection before target imports, and plain
  summaries that omit loaded objects.
- Validation: targeted plugin/package/contract tests passed; `make
  validate-pr` passed; `make test-summary` passed with package 85, unit 1099,
  contract 204, integration 155, e2e 43, and config-extra 438 tests passed;
  GitHub CI `checks` passed on PR #156.
- PR: [#156](https://github.com/samcantrill/loom/pull/156) targeted
  `develop` from `codex/plugin-records-discovery`.
- Merge: merged 2026-05-15 with merge commit
  `78589eb761396a4399124d771859dbc8e00f012d`.
- Follow-up: Phase 2 may branch from updated `develop`; no successor depends
  on the Phase 1 branch.

## Phase 2: Recipe And Codec Registry Adapters

Status: pending
Slug: `recipe-codec-plugin-adapters`
Branch: `codex/recipe-codec-plugin-adapters`
Worktree: `/home/samcantrill/work/loom-worktrees/recipe-codec-plugin-adapters`
PR: pending
Base branch: `develop`
Target branch: `develop`
Workflow path: expanded path because this phase adds public registry adapter
behavior

### Scope

- Goal: add explicit recipe and codec plugin loading into caller-supplied
  registries using the generic discovery/load result model.
- Files/modules owned:
  - `src/loom/plugins/entrypoints.py` and/or `src/loom/plugins/recipes.py`
  - `src/loom/plugins/codecs.py` if split for import boundaries
  - plugin adapter tests under `tests/unit/loom/plugins`
  - recipe/codec contract tests under `tests/contracts`
- Behavior implemented:
  - `load_recipe_entry_points(...)` registers loaded recipes into a supplied
    `RecipeCatalog`.
  - `load_codec_entry_points(...)` normalizes codec instances, no-arg codec
    classes, and no-arg factories into `Codec` objects and registers them into
    a supplied `CodecRegistry`.
  - Registration failures are wrapped with plugin context.
  - Duplicate codec runtime keys fail deterministically.
- Decisions applied: DAQ-3, DAQ-4, DAQ-7, DAQ-8.
- Examples or docs covered: fake recipe plugin, fake codec plugin,
  duplicate codec key, invalid loaded object.
- Out of scope:
  - Source/executor/artifact-store/exporter/provider/event-sink registration.
  - Codec replacement support.
  - Global registry mutation as the only loading path.
- Dependencies: Phase 1 plugin records/load helpers.

### Tasks

- Add recipe adapter over `RecipeCatalog.register(...)`.
- Add codec adapter over `CodecRegistry.register(...)`.
- Preserve generic discovery import boundaries; split adapter modules if
  necessary.
- Add adapter-specific load result metadata such as runtime key where useful.
- Add tests for invalid recipe and codec objects.
- Add tests for constructor/factory failures.
- Add tests for duplicate recipe entry point names and duplicate codec keys.

### Validation

| Command/check | Purpose | Required before phase complete |
| --- | --- | --- |
| `uv run pytest tests/unit/loom/plugins tests/contracts/test_recipe_contract.py tests/contracts/test_codec_contract.py` | Target adapter and registry contract behavior | yes |
| `make validate-pr` | Full PR gate for phase | yes |

### Acceptance Evidence

- Behavior evidence: fake recipes/codecs register only when explicitly loaded.
- Design-decision evidence: adapters use supplied registries and preserve
  registry-owned key/replacement policy.
- Future-roadmap compatibility evidence: adapter pattern is contract-specific
  and does not become universal.
- Interface, adapter, or protocol reuse evidence: recipe and codec adapters
  demonstrate the reusable registry-adapter pattern.
- Documentation evidence: public imports and docstrings clarify explicit
  trusted loading.
- Domain-neutrality evidence: tests use generic fake recipes/codecs only.

### Phase Workflow State

- Phase execution plan: pending
- Planning/refinement budget: expanded path recommended
- Implementation/refinement budget: one refiner pass available if validation
  or adapter API review finds blockers
- PR review budget: one reviewer pass
- Blocker-resolution budget: unused
- Pre-submit blocker gate: no registry API widening beyond plan
- Merge record: pending

### Risks And Stop Conditions

- Risks:
  - Codec class/factory normalization can become too permissive.
  - Recipe replacement behavior can accidentally default to replacement.
- Stop conditions:
  - Adapter mutates a global registry as the only path.
  - `CodecRegistry` replacement behavior is added.
  - Runtime key duplicates are silently overwritten.
- Assumptions:
  - Existing recipe and codec contracts remain stable during this phase.

### Completion Summary

- Implementation: pending
- Validation: pending
- PR: pending
- Merge: pending
- Follow-up: pending

## Phase 3: CLI, Preflight, And Provenance Summaries

Status: pending
Slug: `plugin-cli-preflight-summaries`
Branch: `codex/plugin-cli-preflight-summaries`
Worktree: `/home/samcantrill/work/loom-worktrees/plugin-cli-preflight-summaries`
PR: pending
Base branch: `develop`
Target branch: `develop`
Workflow path: expanded path because this phase adds CLI and diagnostics
surface

### Scope

- Goal: expose plugin inspection/check behavior through CLI commands,
  requested preflight diagnostics, and plain-data summary helpers.
- Files/modules owned:
  - `src/loom/cli/plugins.py`
  - `src/loom/cli/main.py`
  - `src/loom/diagnostics/preflight.py`
  - plugin summary helpers under `src/loom/plugins`
  - CLI tests under `tests/unit/loom/cli`
  - preflight tests under `tests/unit/loom/diagnostics`
- Behavior implemented:
  - `loom plugins list` lists metadata without loading targets.
  - `loom plugins list --load` explicitly loads registry-ready selected
    groups/names and reports load results.
  - `loom plugins check` verifies requested registry-ready groups/names and
    metadata-checks listing-only groups.
  - Text and JSON outputs expose group/name/value/package/version/status and
    safe failure context.
  - Preflight reports requested plugin failures, duplicates, and listing-only
    status without executing stages or mutating runs.
  - Plugin summaries omit loaded Python objects and unsafe data.
- Decisions applied: DAQ-4, DAQ-5, DAQ-6, DAQ-9, DAQ-10.
- Examples or docs covered: best-effort check records multiple failures, CLI
  JSON/text, requested plugin preflight.
- Out of scope:
  - Persisting plugin summaries into run provenance unless a stable existing
    hook is already available and does not widen scope.
  - Whole-environment plugin target import scans.
  - Artifact-store backend registration or run-readiness checks.
- Dependencies: Phases 1 and 2 plugin APIs.

### Tasks

- Add CLI subcommand registration for `loom plugins`.
- Implement list/check argument parsing and output formatting.
- Add JSON/plain summary conversion helpers if not already complete.
- Add selected-group/name/package filters to CLI and preflight paths.
- Add preflight check IDs and result details for requested plugin diagnostics.
- Add listing-only output/status for future groups.
- Add tests proving CLI help does not discover/load plugin targets.

### Validation

| Command/check | Purpose | Required before phase complete |
| --- | --- | --- |
| `uv run pytest tests/unit/loom/cli tests/unit/loom/diagnostics tests/unit/loom/plugins tests/package` | Target CLI, preflight, summaries, and import safety | yes |
| `make validate-pr` | Full PR gate for phase | yes |

### Acceptance Evidence

- Behavior evidence: CLI list is metadata-only; check reports failures and
  nonzero status for requested failures.
- Design-decision evidence: preflight loads only selected registry-ready groups
  and does not become a broad optional-SDK import path.
- Future-roadmap compatibility evidence: artifact-store backend and event-sink
  groups are labelled listing-only.
- Interface, adapter, or protocol reuse evidence: CLI/preflight consume plugin
  result summaries rather than plugin internals.
- Documentation evidence: CLI help and output clarify explicit trusted loading.
- Domain-neutrality evidence: tests use fake entry points and fake registries.

### Phase Workflow State

- Phase execution plan: pending
- Planning/refinement budget: expanded path recommended
- Implementation/refinement budget: one refiner pass available if validation
  or CLI/preflight review finds blockers
- PR review budget: one reviewer pass
- Blocker-resolution budget: unused
- Pre-submit blocker gate: no broad plugin import scan or false readiness claim
- Merge record: pending

### Risks And Stop Conditions

- Risks:
  - CLI wording can imply listing-only groups are loadable.
  - Preflight can accidentally import every installed plugin.
  - JSON output can leak object reprs or unsafe exception data.
- Stop conditions:
  - `loom --help` imports plugin targets.
  - Artifact-store backend check success implies backend availability or
    run-readiness.
  - Preflight performs network/service checks for plugins.
- Assumptions:
  - CLI remains a thin wrapper over public plugin APIs.

### Completion Summary

- Implementation: pending
- Validation: pending
- PR: pending
- Merge: pending
- Follow-up: pending

## Phase 4: Future Group Readiness And Contract Hooks

Status: pending
Slug: `future-plugin-group-readiness`
Branch: `codex/future-plugin-group-readiness`
Worktree: `/home/samcantrill/work/loom-worktrees/future-plugin-group-readiness`
PR: pending
Base branch: `develop`
Target branch: `develop`
Workflow path: expanded path because this phase protects future public
contracts

### Scope

- Goal: complete stable listing/check behavior and documentation for future
  plugin groups without implementing unstable registration.
- Files/modules owned:
  - `src/loom/plugins` future group constants/readiness metadata
  - CLI/preflight listing-only tests as needed
  - documentation or implementation-plan notes for readiness classifications
  - package/contract tests for future group imports
- Behavior implemented:
  - Future groups list/check metadata deterministically.
  - Readiness classifications are surfaced in docs or user-facing diagnostics
    where appropriate.
  - `loom.artifact_store_backends` has explicit metadata-only behavior and
    fail-closed diagnostics for premature registration/run-readiness requests.
  - Stage 12/13 source APIs were rechecked during implementation planning, and
    `loom.run_exporters` and `loom.sweep_providers` remain listing/check-only
    because no source-level owned loader contracts are present.
- Decisions applied: DAQ-2, DAQ-8, DAQ-9, DAQ-10.
- Examples or docs covered: future group listing, artifact-store backend
  listing-only, premature registration fail-closed.
- Out of scope:
  - Stage 15 artifact-store descriptor/factory, registry, config, capability,
    URI validation, credential, operation-result, materialization, cache,
    staging, and handler semantics.
  - Stage 19 event-sink registry semantics.
  - Concrete external service integrations.
  - Third-party CLI command injection.
- Dependencies: Phases 1 and 3.

### Tasks

- Add tests for future group listing/check metadata.
- Add explicit artifact-store backend listing-only tests.
- Add fail-closed behavior or diagnostics for requested unsupported backend
  registration/run-readiness.
- Verify no artifact-store backend entry point path constructs a store, probes
  credentials, validates URI schemes, or calls runner/preflight artifact-store
  internals.
- Record the implementation-planning source recheck result for run-exporter
  and sweep-provider groups and keep both listing/check-only in Stage 14.
- Add documentation/readiness notes for each future group and revisit trigger.
- Run final full validation and produce suite evidence.

### Validation

| Command/check | Purpose | Required before phase complete |
| --- | --- | --- |
| `uv run pytest tests/unit/loom/plugins tests/unit/loom/cli tests/unit/loom/diagnostics tests/contracts tests/package` | Target future group readiness, CLI/preflight labels, import boundaries, and contracts | yes |
| `make validate-pr` | Full PR gate for phase | yes |
| `make test-summary` | Suite-level evidence for final PR body | yes |

### Acceptance Evidence

- Behavior evidence: future groups can be listed/checked as metadata without
  target imports by default.
- Design-decision evidence: artifact-store backend group has no loader,
  registry mutation, raw store validation, or run-readiness claim.
- Future-roadmap compatibility evidence: Stage 15/16/19 remain free to define
  real backend/event contracts without Stage 14 refactors.
- Interface, adapter, or protocol reuse evidence: readiness table and tests
  show that loaders are gated on owning contracts.
- Documentation evidence: docs/plan notes identify listing-only groups and
  revisit triggers.
- Domain-neutrality evidence: no cloud SDKs, service packages, optimizer
  dependencies, or concrete integration names in core behavior beyond docs'
  compatibility examples.

### Phase Workflow State

- Phase execution plan: pending
- Planning/refinement budget: expanded path recommended
- Implementation/refinement budget: one refiner pass available if validation
  or future-contract review finds blockers
- PR review budget: one reviewer pass
- Blocker-resolution budget: unused
- Pre-submit blocker gate: no Stage 15/19 semantics implemented in Stage 14
- Merge record: pending

### Risks And Stop Conditions

- Risks:
  - Future groups can be misread as ready for runtime use.
  - Stage 12/13 source APIs may differ from planning assumptions.
  - Artifact-store backend checks can overstep into Stage 15.
- Stop conditions:
  - A future group loader is added without a stable owning registry/protocol.
  - Artifact-store backend target loading validates or constructs stores.
  - CLI/preflight says an artifact-store backend is available for runs based
    only on Stage 14 discovery.
- Assumptions:
  - Stage 15 will define the store-owned backend descriptor/factory and
    registry contract.

### Completion Summary

- Implementation: pending
- Validation: pending
- PR: pending
- Merge: pending
- Follow-up: pending

## Cross-Phase Validation

- Full relevant test command: `make validate-pr`
- Final suite evidence command: `make test-summary`
- Targeted plugin tests:
  `uv run pytest tests/unit/loom/plugins tests/unit/loom/cli tests/unit/loom/diagnostics tests/contracts tests/package`
- Docs/template checks: implementation-plan review plus docs/readiness wording
  for listing-only future groups.
- Domain-neutrality checks: no concrete service integrations, no optional SDK
  imports, no domain-specific plugin behavior.
- Example/demo checks: fake entry points, fake recipe/codec registries, fake
  future group entries, artifact-store backend listing-only behavior.
- Manual review focus: import boundaries, public group names, duplicate
  diagnostics, object summary omission, CLI wording, and DAQ-10 artifact-store
  backend constraints.

## Implementation Plan Review

| Finding | Severity | Resolution | Status |
| --- | --- | --- | --- |
| None | none | No blocking findings remain after local review/refinement/confirmation | resolved |

Gate result:

- Status: passed on 2026-05-15
- Review evidence: local equivalent review checked planning readiness,
  maintainability, extensibility, future compatibility, conflicting design
  choices, accepted debt, test strategy, and reviewability using
  `.codex/prompts/implementation-plan-review.md`.
- Accepted risks:
  - Future groups are public metadata namespaces before every loader exists.
  - Codec replacement is not supported in Stage 14.
  - Plugin summaries are not persisted provenance schemas.
  - Artifact-store backend group exists before Stage 15 backend contract, but
    Stage 14 keeps it metadata-only.
- Revisit triggers:
  - Source registry lands.
  - Executor descriptor/factory/registry contract lands.
  - Stage 12 `RunExporter` source protocol lands.
  - Stage 13 sweep provider protocol lands.
  - Stage 15 artifact-store backend descriptor/factory, registry, config,
    capability, redaction, preflight, and operation result contracts land.
  - Stage 19 runtime event and event-sink registry contracts land.
  - Provenance needs a versioned plugin-summary schema.

## Final Approval

- Approval status: plan-quality gate passed; ready for Phase 1 execution
  planning
- Approved scope: four-phase Stage 14 implementation shape above, with only
  recipe and codec loader adapters in Stage 14 and all other roadmap groups
  listing/check-only
- Accepted risks: same as the Plan Quality Gate accepted risks above
- Deferred items:
  - All concrete service integrations.
  - Artifact-store backend loading and registration until Stage 15.
  - Event-sink loading and registration until Stage 19.
  - Source/executor/run-exporter/sweep-provider loaders until stable owning
    contracts land and pass plugin-readiness review.
