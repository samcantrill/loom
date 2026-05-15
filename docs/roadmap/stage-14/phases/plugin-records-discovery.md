# Phase 1 Execution Plan: Plugin Records And Generic Discovery

## Metadata

- Status: scope-complete phase execution plan; ready for implementation
- Feature focus: Plugin Discovery
- PR title:
  `Plugin Discovery - Phase 1: Plugin Records And Generic Discovery`
- Branch: `codex/plugin-records-discovery`
- Worktree:
  `/home/samcantrill/work/loom-worktrees/plugin-records-discovery`
- Phase execution plan path:
  `docs/roadmap/stage-14/phases/plugin-records-discovery.md`
- Full plan: `docs/roadmap/stage-14/implementation-plan.md`
- Source phase: Phase 1, `plugin-records-discovery`
- Stack predecessor: none
- Base branch: `develop` at `9fac00dbf96c18a8194ed5551327962230f71e0e`
- Target branch: `develop`
- Merge eligibility: root phase PR targets `develop`; merge-eligible only
  after implementation, required validation, automated review, CI or justified
  unavailable checks, scope verification, and target-branch verification pass.
- Workflow path: expanded path, because this phase creates public plugin APIs
  and entry point group contracts.
- Successor dependency notes: Phase 2 should branch from this phase branch if
  Phase 1 is `pr_open` or `approved` but not merged; otherwise Phase 2 should
  branch from updated `develop`.
- Plan quality gate: passed in the implementation plan on 2026-05-15.
- Plan quality gate loop budget: implementation-plan review, refinement, and
  confirmation were used before this phase; no blocking findings remain.
- Draft pass: complete for this phase execution plan.
- Refine pass: complete in this planning pass for the expanded path; no further
  planning refinement is required before implementation unless the manager
  reopens scope.
- Setup limitations: branch and worktree were created from local `develop` as
  assigned. No product code was implemented, no broad validation was run during
  planning, and the control checkout has an unrelated local edit in
  `docs/roadmap/stage-15/planning.md` that this phase leaves untouched.
- Blockers: none.

## Objective

Establish Loom's import-light plugin discovery foundation: public group
constants, metadata records, load result and failure records, plugin-specific
errors, deterministic metadata-only listing, selected explicit loading, strict
and best-effort failure handling, duplicate entry point name detection, and
import-safety tests using fake entry points.

## Full-Plan Context

This is the first Stage 14 phase. It creates the generic plugin discovery
package that Phase 2 uses for recipe and codec registry adapters, Phase 3 uses
for CLI, preflight, and summary presentation, and Phase 4 uses for future group
readiness and listing-only diagnostics. Future phase work must remain out of
scope here: no recipe or codec registration, no CLI commands, no preflight
integration, no provenance persistence, no future group readiness table, and no
source, executor, artifact-store backend, run-exporter, sweep-provider, or
event-sink loader.

## Stack Context

- Root or stacked phase: root phase.
- Current predecessor branch or PR: none.
- Why this base branch is correct: Phase 1 has no earlier Stage 14
  predecessor, and the user assigned current `develop` as the phase base.
- Retarget/rebase plan after predecessor merge: none for this phase.
- Branch cleanup constraints: this branch can be deleted after merge only if no
  successor phase still targets or branches from it.

## Source Phase Summary

- Goal: establish the public plugin package, record/result/error model, known
  group constants, metadata-only listing, explicit generic loading, duplicate
  detection, fake entry point seam, and import-safety tests.
- Required scope: `src/loom/plugins/__init__.py`,
  `src/loom/plugins/entrypoints.py`, `src/loom/plugins/errors.py`, package
  export tests, plugin unit tests, and import-boundary tests.
- Required checkpoints: listing fake entry points is deterministic and does not
  load targets; selected loading imports only selected targets; strict and
  best-effort modes preserve duplicate and failure context; public summaries do
  not serialize loaded Python objects; existing lower layers do not import
  `loom.plugins`.
- Acceptance criteria: group constants are public metadata contracts, generic
  records and errors are stable enough for Phase 2 adapters, future group
  constants do not imply loadability, and all tests use generic fake plugins
  rather than real installed third-party packages.

## Current Source And Harness Findings

- Existing files or modules that constrain this phase:
  - `src/loom/plugins/` does not exist on the assigned base and should be
    created as a small import-light package.
  - `src/loom/__init__.py` currently exports only root primitives and must not
    import or re-export `loom.plugins` in this phase.
  - `docs/features/plugins.md` assigns plugin discovery to `loom.plugins` as an
    optional coordination layer above subsystem registries and below CLI or
    application setup.
  - `docs/structure.md` keeps runtime code under `src/loom` and requires
    public imports to stay stable, typed, and cheap to import.
  - `docs/GLOSSARY.md` distinguishes plugins, registries, backends, and
    artifacts; Phase 1 should keep plugin records generic and avoid backend or
    registry semantics.
- Existing tests or harness behavior:
  - Package tests live under `tests/package/`, including public API and
    import-boundary subprocess checks.
  - Existing import-boundary tests already treat `loom.plugins` as forbidden
    from lower runtime packages such as `loom.pipeline.runtime`.
  - Contract tests live under `tests/contracts/`; this phase should add or
    update focused plugin discovery/import-boundary contract coverage rather
    than use real installed extension packages.
  - Unit tests mirror source layout under `tests/unit/loom/`; this phase should
    add `tests/unit/loom/plugins/`.
- Import-boundary or dependency constraints:
  - Metadata listing may use standard-library `importlib.metadata` but must not
    call entry point `load()` or import plugin target modules.
  - `loom.plugins` must not import CLI modules, runner lifecycle modules,
    project packages, service SDKs, optional optimizer packages, or future
    registry owners just to list metadata.
  - `import loom`, `import loom.config`, `import loom.io`, and
    `import loom.pipeline` must not discover or load plugins.

## In-Scope Work

- Create `src/loom/plugins/` with import-light public exports.
- Define known group constants with these exact public string values:
  `loom.recipes`, `loom.codecs`, `loom.sources`, `loom.executors`,
  `loom.artifact_store_backends`, `loom.run_exporters`,
  `loom.sweep_providers`, and `loom.event_sinks`.
- Define frozen record/result types or equivalent minimal immutable records for
  plugin metadata, loaded objects, failures, duplicate entry point names, and
  aggregate load results.
- Define plugin errors for discovery, load, duplicate, invalid, and
  registration-context failures, with enough metadata context for callers to
  present package/group/name/value diagnostics.
- Implement fakeable entry point listing over `importlib.metadata` with
  deterministic sorting and no target import.
- Implement selected explicit loading over listed records with strict and
  best-effort modes.
- Detect duplicate entry point names by `(group, name)` before loading duplicate
  targets, and report duplicate metadata deterministically.
- Provide plain summary conversion for records/results/failures that omits
  loaded Python objects and unsafe traceback internals.
- Add package, unit, and contract/import-boundary tests for public exports,
  deterministic listing, duplicates, failures, strict/best-effort modes,
  selected-only loading, object omission from summaries, and import safety.

## Out-of-Scope Work

- Recipe and codec registry adapters, including any `RecipeCatalog` or
  `CodecRegistry` imports from generic discovery modules.
- CLI commands, CLI formatting, CLI help changes, or command injection.
- Preflight diagnostics, plugin check IDs, run-readiness checks, or run-state
  mutation.
- Persisted provenance schemas or run-store integration for plugin summaries.
- Readiness classifications beyond the group constants needed by Phase 1.
- Source, executor, artifact-store backend, run-exporter, sweep-provider, or
  event-sink registration loaders.
- Artifact-store backend descriptor/factory contracts, raw `ArtifactStore`
  validation, store construction, credential probing, URI validation, runner
  integration, or claims that advertised backends are run-ready.
- Real installed third-party plugin packages, optional service dependencies,
  network checks, or sandboxing for untrusted code.

## Assumptions

- Python 3.12 standard-library `importlib.metadata` entry point behavior is
  available.
- Installed plugin packages are trusted project/environment code, but loading
  them remains an explicit caller action.
- Exact function signatures may follow local style, but public behavior must
  preserve metadata-only listing, selected loading, deterministic output, and
  plain summaries.
- Fake entry point tests can use lightweight local entry point doubles or an
  injectable provider without depending on installed package metadata.
- The package can use standard library dataclasses and existing plain-data
  helpers where useful without introducing new runtime dependencies.

## Scope Contract

The executor may choose exact class helpers and internal decomposition that fit
nearby Loom patterns, but must preserve these public decisions:

- `loom.plugins` is the stable public package for generic plugin discovery.
  Root `import loom` must stay cheap and must not import `loom.plugins`.
- Group constant string values are public metadata contracts. Stage 14 may list
  all known groups, but Phase 1 must not expose loaders for registry-unstable
  future groups.
- `PluginRecord` or its equivalent describes entry point metadata only. It must
  include at least group, name, value/import target, and best-effort package
  name/version context when available, without importing the target.
- `LoadedPlugin` or its equivalent may carry a loaded Python object for Python
  callers, but summaries must omit that object.
- `PluginFailure` and plugin error types must preserve plugin metadata and
  safe exception context. Summary data must avoid full tracebacks, object reprs
  that can leak unsafe data, and loaded object serialization.
- `PluginDuplicate` or its equivalent must group duplicate records by
  `(group, name)` and retain enough records to identify conflicting packages
  and entry point values.
- `PluginLoadResult` or its equivalent must separate loaded objects, failures,
  and duplicates so Phase 2 adapters, Phase 3 CLI/preflight, and future
  provenance summaries can consume it without re-parsing exceptions.
- `list_entry_points(...)` must be metadata-only and deterministic. It must
  support fake entry point providers for tests and must not load target modules.
- `load_entry_points(...)` must load only explicitly selected records or
  selectors supplied by the caller. Strict mode fails closed on duplicates or
  load failures; best-effort mode records failures and proceeds with eligible
  non-duplicate selections.
- Duplicate detection must happen before loading conflicting targets so
  duplicates cannot cause arbitrary imports in strict paths.
- Generic discovery modules must not import recipe, codec, source, executor,
  artifact-store, exporter, sweep-provider, event-sink, CLI, preflight, or
  provenance implementation modules at import time.

## Design Impact

- Maintainability: centralizes entry point metadata and generic load-result
  handling in one small package, so later adapter and presentation phases
  consume shared records rather than duplicating discovery logic.
- Extensibility: establishes a reusable list-load-report pattern for future
  registry-specific adapters while keeping registry semantics owned by the
  target subsystem.
- Domain neutrality: constants, records, errors, and tests use generic plugin
  vocabulary and fake extensions only; no service, model, dataset, metric, or
  optimizer behavior belongs in this phase.
- Source-tree boundaries: `loom.plugins` may depend on standard-library
  metadata and lightweight Loom serialization/error helpers, but must not depend
  on CLI, runner lifecycle, project packages, or subsystem registries for
  generic listing/loading.

## Future Compatibility

- Phase 2 can adapt `PluginLoadResult` into supplied recipe and codec
  registries without changing generic discovery behavior.
- Phase 3 can render CLI/preflight JSON and text diagnostics from plain
  summaries without exposing loaded Python objects.
- Phase 4 can add readiness labels for future groups while preserving the
  public group constants introduced here.
- Stage 15/16 artifact-store backend work remains free to define a store-owned
  descriptor/factory and registry contract because this phase exposes only the
  `loom.artifact_store_backends` metadata namespace.
- Stage 19 event-sink work remains free to define runtime event and sink
  registry contracts because this phase does not load or validate event sinks.
- If source, executor, run-exporter, or sweep-provider registries land later,
  they can reuse the generic record/load/failure model without accepting a
  universal plugin object protocol.

## Alternatives Rejected

| Alternative | Reason rejected |
| --- | --- |
| Place discovery in subsystem registries | Would make registries own package metadata scanning and risk import-time plugin side effects in lower layers. |
| Place discovery only in CLI code | Would prevent Python setup code, Phase 2 adapters, and future preflight/provenance consumers from sharing the same deterministic API. |
| Load every advertised plugin during listing | Violates the metadata-first design and can import optional SDKs or project code during harmless inspection. |
| Define a universal plugin object protocol | Prematurely forces sources, executors, stores, exporters, providers, and event sinks into one shape before their owning contracts are stable. |
| Treat artifact-store backend entry points as raw stores or local-root factories | Would freeze the wrong public backend shape before Stage 15 defines backend descriptors, config handoff, capabilities, and run-context construction. |
| Add global registry mutation as the default path | Conflicts with explicit caller-supplied registries and would make plugin loading less reproducible and harder to test. |

## Debt Introduced

| Debt | Reason accepted | Revisit trigger |
| --- | --- | --- |
| Future group constants ship before their loaders | Stable metadata namespaces are needed now for listing and diagnostics, but owning runtime contracts are not all ready | Source, executor, artifact-store backend, run-exporter, sweep-provider, or event-sink registry/protocol contracts land and pass plugin-readiness review |
| Generic load summaries are plain diagnostic data, not a persisted provenance schema | Phase 1 must serve CLI/preflight/future provenance without coupling to run-store persistence | Provenance work requires a versioned persisted plugin-summary schema |
| Package/version metadata is best-effort when fake or unusual entry points lack distribution context | `importlib.metadata` distribution links can vary and tests should not depend on real installed packages | CLI/preflight diagnostics need stricter package identity guarantees across Python versions |

## Reviewability

- Expected PR size and shape: small-to-medium foundational PR with a new
  `loom.plugins` package plus focused package, unit, and contract tests. No
  runtime behavior should change outside public imports and import-boundary
  assertions.
- Files and areas to inspect:
  - `src/loom/plugins/`
  - `tests/unit/loom/plugins/`
  - `tests/package/`
  - `tests/contracts/`
  - `src/loom/__init__.py` only to verify it remains unchanged unless a
    package test requires an explicit no-export assertion.
- Scope-control checks:
  - No recipe, codec, source, executor, artifact-store, exporter,
    sweep-provider, event-sink, CLI, preflight, or provenance module imports in
    generic plugin discovery modules.
  - No product code outside `src/loom/plugins` unless needed for import
    package exports or tests.
  - No real third-party plugin package, optional SDK, network, or service
    dependency in tests.
  - No artifact-store backend loading, validation, construction, credential
    probing, URI validation, or runner/preflight wiring.

## Implementation Steps

1. Add the import-light `loom.plugins` package with group constants, public
   exports, plugin errors, and immutable metadata/load/failure/duplicate/result
   records.
2. Add deterministic metadata listing with an injectable/fakeable entry point
   provider and duplicate detection that works without calling `load()`.
3. Add selected explicit loading with strict and best-effort modes, preserving
   loaded objects for Python callers and safe plain summaries for diagnostics.
4. Add package and contract tests for public exports, cheap imports, no root
   package re-export, and lower-layer import boundaries.
5. Add unit tests with fake entry points for ordering, duplicate names, load
   failures, selected-only loading, best-effort aggregation, strict fail-closed
   behavior, and summary object omission.
6. Run targeted plugin/package/contract tests during implementation, then leave
   final `make validate-pr` and `make test-summary` evidence for PR
   preparation.

## Test Plan

### Package Suite

- Status: required.
- Expected paths:
  - `tests/package/test_plugins_api.py` or equivalent package API coverage.
  - `tests/package/test_import.py` and/or `tests/package/test_public_api.py`
    for public package expectations.
  - `tests/package/test_import_boundaries.py` for import-safety assertions.
- Required assertions:
  - `import loom.plugins` exposes the intended constants, records, helpers, and
    errors through `__all__`.
  - `import loom` does not import or re-export `loom.plugins`.
  - `import loom.config`, `import loom.io`, `import loom.pipeline`, and lower
    runtime packages do not import `loom.plugins`.
  - Importing `loom.plugins` does not import CLI, preflight, runner lifecycle,
    project packages, optional service SDKs, or plugin target modules.

### Unit Suite

- Status: required.
- Expected paths: `tests/unit/loom/plugins/`.
- Required assertions:
  - Known group constants exactly match the public values listed in this plan.
  - `PluginRecord` and related records validate or normalize metadata
    deterministically and convert to plain summaries without loaded objects.
  - Metadata listing over fake entry points sorts deterministically and does not
    call fake entry point `load()`.
  - Duplicate `(group, name)` records are detected deterministically with
    enough package/value context for diagnostics.
  - `load_entry_points(...)` loads only selected records.
  - Strict mode raises or returns a fail-closed error path on duplicate or load
    failure, according to the chosen API shape.
  - Best-effort mode aggregates failures and duplicates while loading eligible
    non-duplicate selections.
  - Load failures preserve safe exception type/message context without unsafe
    traceback or object serialization in summaries.

### Contract Suite

- Status: required.
- Expected paths:
  - `tests/contracts/test_plugin_discovery_contract.py` or equivalent focused
    contract coverage.
  - Existing import-boundary contract/package tests where appropriate.
- Required assertions:
  - Listing is a metadata-only public contract and cannot import plugin target
    modules by default.
  - Explicit loading is selected and trusted-code only.
  - Duplicate names are fail-closed public behavior, not silent overwrite.
  - Future group constants are metadata namespaces only in Phase 1 and do not
    imply loader availability.

### Integration Suite

- Status: deferred for this phase.
- Deferral reason: Phase 1 is a pure package/API and import-boundary phase that
  uses fake entry points. It does not integrate CLI, preflight, run execution,
  registries, or real installed plugin distributions.

### E2E Suite

- Status: deferred for this phase.
- Deferral reason: no user-facing CLI workflow or run workflow changes are in
  scope until later Stage 14 phases.

### Opt-In Suites

- Status: deferred for this phase.
- Markers affected: none expected.
- Deferral reason: plugin discovery must stay dependency-light and should not
  require optional service SDKs, real plugin packages, network access, SLURM, or
  acceptance environments.

## Risks

- Group names become public metadata contracts once shipped.
- Python `importlib.metadata` entry point distribution metadata can vary across
  Python versions and fake entry point implementations.
- Result or summary helpers can accidentally include loaded objects, large
  reprs, unsafe traceback internals, or secret-bearing exception text.
- Duplicate handling can accidentally import duplicate targets before failing.
- Generic discovery can accidentally import subsystem registries or outer
  presentation layers, weakening source-tree boundaries.

## Stop Conditions

- Listing entry points imports plugin target modules.
- Importing `loom`, `loom.config`, `loom.io`, or `loom.pipeline` discovers,
  lists, or loads plugins.
- Public records cannot produce plain summaries without serializing loaded
  Python objects.
- The implementation adds recipe/codec adapters, CLI/preflight behavior,
  artifact-store backend loaders, store construction, or future group runtime
  validation.
- The plan quality gate is found to have unresolved blocking findings.

## Validation Commands

Targeted development commands:

```sh
uv run pytest tests/unit/loom/plugins tests/package/test_import.py tests/package/test_public_api.py tests/package/test_import_boundaries.py tests/contracts/test_plugin_discovery_contract.py
```

Final PR-preparation commands:

```sh
make validate-pr
make test-summary
```

## Handoff Notes For `loom_phase_executor`

- Safe implementation slices:
  - Start with constants, records, errors, and package exports before loading
    behavior.
  - Add fakeable metadata listing and duplicate detection before explicit
    loading.
  - Add loading behavior only after listing tests prove no target imports.
  - Finish with package/import-boundary tests and targeted validation.
- Tests to run with each slice:
  - Records/constants: unit and package API tests.
  - Listing/duplicates: `tests/unit/loom/plugins` plus import-boundary package
    tests.
  - Loading/results: plugin unit tests plus plugin discovery contract tests.
- Decisions the executor must not revisit:
  - Use the public group string values recorded above.
  - Keep listing metadata-only and loading explicit.
  - Do not import subsystem registries from generic discovery modules.
  - Do not create artifact-store backend or event-sink loading semantics.
  - Do not add real third-party plugin packages or optional dependencies.
- Conditions that require stopping for the manager:
  - A public group constant appears wrong or conflicts with existing packaging
    metadata.
  - Import-safety tests cannot pass without changing root or lower-layer import
    policy outside this phase.
  - `importlib.metadata` cannot provide enough metadata for deterministic
    package/group/name/value diagnostics without a public API change.
  - Any implementation pressure suggests adding registry adapters, CLI,
    preflight, provenance, or store-backend semantics in Phase 1.

## Refinement And Review Budget Status

- Phase planning draft: completed.
- Phase planning refinement: completed for the expanded path.
- Phase implementation refinement: used for the Phase 1 test typing blocker
  found by Pyright during `make validate-pr`.
- PR body draft/refine: unused until PR preparation.
- PR review: unused.
- Blocker resolution: 0/3 used.

## Completion Notes

- Draft plan: completed in
  `docs/roadmap/stage-14/phases/plugin-records-discovery.md`.
- Final phase execution plan: completed and ready for implementation handoff.
- Implementation summary: implemented through `src/loom/plugins` import-light discovery
  records/errors/listing/loading and selected strict/best-effort handling; package
  unit tests, plugin package API tests, import-boundary checks, and focused
  contract tests are added.
- Implementation validation: targeted Pyright passed with 0 errors and focused
  plugin discovery tests passed with 15 tests in the implementation refinement
  pass. A broad `make validate-pr` rerun passed Ruff and Pyright with 0 errors
  but was interrupted after the default pytest leg stalled without additional
  output; full PR validation remains a PR-preparation obligation.
- Refinement summary: fixed Phase 1 test typing for fake entry point providers,
  fake module factories, and plain summary indexing; implementation refinement
  budget is used.
- Blocker-resolution summary: none used.
- PR preparation: pending.
- Stack maintenance: not needed for this root phase yet.
- Remaining blockers: none for the scoped Phase 1 test typing blocker.
