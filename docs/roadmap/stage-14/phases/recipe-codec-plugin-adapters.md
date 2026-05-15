# Phase 2 Execution Plan: Recipe And Codec Registry Adapters

## Metadata

- Status: scope-complete phase execution plan; ready for implementation
- Feature focus: Plugin Discovery
- PR title:
  `Plugin Discovery - Phase 2: Recipe And Codec Registry Adapters`
- Branch: `codex/recipe-codec-plugin-adapters`
- Worktree:
  `/home/samcantrill/work/loom-worktrees/recipe-codec-plugin-adapters`
- Phase execution plan path:
  `docs/roadmap/stage-14/phases/recipe-codec-plugin-adapters.md`
- Full plan: `docs/roadmap/stage-14/implementation-plan.md`
- Source phase: Phase 2, `recipe-codec-plugin-adapters`
- Stack predecessor: none
- Base branch: `develop` at `fbde891d62009640aa6a86d96ede06c761c32983`
- Target branch: `develop`
- Merge eligibility: root phase PR targets `develop`; merge-eligible only
  after implementation, required validation, automated review, CI or justified
  unavailable checks, scope verification, and target-branch verification pass.
- Workflow path: expanded path, because this phase adds public
  registry-adapter behavior for trusted plugin loading.
- Successor dependency notes: Phase 3 should branch from this phase branch if
  Phase 2 is `pr_open` or `approved` but not merged; otherwise Phase 3 should
  branch from updated `develop`.
- Plan quality gate: passed in the implementation plan on 2026-05-15.
- Plan quality gate loop budget: implementation-plan review, refinement, and
  confirmation were used before Phase 1; no blocking findings remain.
- Expanded-path draft pass: complete for this phase execution plan.
- Expanded-path refine pass: complete in this planning pass; no further
  planning refinement is required before implementation unless the manager
  reopens scope.
- Setup limitations: branch and worktree were created from local `develop` as
  assigned. No product code was implemented, no broad validation was run during
  planning, and the control checkout has an unrelated local edit in
  `docs/roadmap/stage-15/planning.md` that this phase leaves untouched.
- Blockers: none.

## Objective

Add explicit recipe and codec plugin loading adapters that use the generic
Stage 14 discovery/load result model to populate caller-supplied
`RecipeCatalog` and `CodecRegistry` instances. The adapters make plugin
discovery usable for two stable registries while preserving metadata-first
listing, explicit trusted loading, registry-owned validation, and deterministic
duplicate failure behavior.

## Full-Plan Context

Phase 1 has landed the import-light `loom.plugins` package with public group
constants, `PluginRecord`, loaded/failure/duplicate/result records, plugin
errors, deterministic metadata-only listing, selected explicit loading, and
duplicate entry point detection. Phase 2 builds on those APIs only for recipes
and codecs.

Later Stage 14 phases remain out of scope: no CLI commands, preflight checks,
plain provenance-summary wiring, or future group readiness labels. Sources,
executors, artifact-store backends, run exporters, sweep providers, and event
sinks stay listing/check-only until their owning contracts define stable loader
semantics. Stage 14 must not add artifact-store backend loading before Stage
15.

## Stack Context

- Root or stacked phase: root phase.
- Current predecessor branch or PR: none; Phase 1 is merged into `develop`.
- Why this base branch is correct: the user assigned current `develop`, and
  the implementation plan records Phase 1 as merged with Phase 2 ready for
  execution planning.
- Retarget/rebase plan after predecessor merge: none for this phase.
- Branch cleanup constraints: this branch can be deleted after merge only if
  no successor phase still targets or branches from it.

## Source Phase Summary

- Goal: add explicit recipe and codec plugin loading into supplied registries.
- Required scope:
  - Recipe adapter using `RecipeCatalog.register(name, recipe, replace=False)`.
  - Codec adapter using `CodecRegistry.register(codec)`.
  - Object-shape handling for codec instances, no-argument codec classes, and
    no-argument factories.
  - Registration failure wrapping with plugin metadata context.
  - Deterministic duplicate entry point and duplicate runtime codec key
    diagnostics.
- Required checkpoints:
  - Loading happens only when callers invoke the adapter.
  - Recipe entry point names become catalog names.
  - Codec runtime keys come from loaded codec objects.
  - `CodecRegistry` replacement support is not added.
  - Generic discovery modules stay independent from registry-specific imports.
- Acceptance criteria: fake recipe and codec entry points can populate supplied
  registries; invalid objects, constructor/factory failures, duplicate entry
  point names, catalog duplicate names, and duplicate codec keys are reported
  with plugin context; no global registry mutation or future-group loader is
  introduced.

## Current Source And Harness Findings

- Landed plugin API:
  - `src/loom/plugins/entrypoints.py` exports known group constants,
    `list_entry_points(...)`, `find_plugin_duplicates(...)`, and
    `load_entry_points(...)`.
  - `load_entry_points(...)` supports selected records, strict and best-effort
    modes, and an optional registration callback that records registration
    failures in `PluginLoadResult`.
  - Generic discovery currently has no recipe or codec adapter functions.
- Recipe registry contract:
  - `RecipeCatalog.register(name, recipe, replace=False)` validates names and
    recipe shape.
  - Duplicate recipe names fail unless replacement is explicitly requested by
    the caller.
  - Valid recipe implementations are callable recipe functions/classes or
    recipe classes accepted by the catalog.
- Codec registry contract:
  - `CodecRegistry.register(codec)` validates the runtime `Codec` protocol and
    uses `codec.key` as the registry key.
  - Duplicate codec keys fail. There is no `replace` parameter and this phase
    must not add one.
  - Built-in codecs and downstream-style structural codec objects already
    satisfy contract tests.
- Existing tests and harness:
  - `tests/unit/loom/plugins/test_entrypoints.py` uses fake entry point records
    and monkeypatched imports for plugin discovery/load behavior.
  - `tests/contracts/test_plugin_discovery_contract.py` locks metadata-only
    listing, selected loading, and future-group no-loader behavior.
  - `tests/contracts/test_recipe_contract.py` and
    `tests/contracts/test_codec_contract.py` cover supplied registry contracts
    and should receive focused extension coverage as needed.

## In-Scope Work

- Add a public recipe adapter, likely in `src/loom/plugins/recipes.py` or an
  equivalent small adapter module, and export it through the stable plugin API
  if that matches the Phase 1 export pattern.
- Add a public codec adapter, likely in `src/loom/plugins/codecs.py` or an
  equivalent small adapter module, and export it through the stable plugin API
  if that matches the Phase 1 export pattern.
- Keep `src/loom/plugins/entrypoints.py` generic. Registry-specific imports
  belong in adapter modules or local/type-checking scopes, not in generic
  discovery.
- Use `LOOM_RECIPES_GROUP` for recipe entry points and `LOOM_CODECS_GROUP` for
  codec entry points by default.
- Preserve selected explicit loading. The adapters must expose enough provider,
  record, or name-selection control to test fake entry points and to avoid
  importing unselected plugin targets.
- Register loaded recipes into the supplied `RecipeCatalog` using the entry
  point name as the recipe name. Recipe replacement may only be an explicit
  adapter option and must default to `False`.
- Normalize codec plugin targets narrowly:
  - codec class objects are instantiated with no arguments;
  - existing codec instances are registered directly;
  - no-argument factories are called and their return value is validated as a
    codec.
- Register codecs into the supplied `CodecRegistry` by runtime `codec.key`.
  The entry point name remains diagnostic metadata, not the registry key.
- Wrap catalog, codec validation, constructor, factory, and registration
  failures with `PluginFailure`/`PluginLoadResult` context and strict-mode
  plugin errors that identify group, name, value, and package metadata when
  available.
- Add focused package, unit, contract, and minimal cross-module registry tests
  for the adapter behavior.

## Out-of-Scope Work

- Source, executor, artifact-store backend, run-exporter, sweep-provider, or
  event-sink registration loaders.
- CLI commands, CLI formatting, help text, or third-party command injection.
- Preflight diagnostics, plugin readiness classifications, or run-state
  mutation.
- Provenance persistence or versioned plugin-summary schemas.
- Global recipe or codec registry mutation as the only plugin loading path.
- `CodecRegistry` replacement support or silent codec key overwrite.
- Artifact-store backend descriptor/factory contracts, store construction,
  credential probing, URI validation, runner integration, or claims that
  advertised artifact-store backends are run-ready.
- Real installed third-party plugin packages, optional service SDKs, network
  checks, or sandboxing for untrusted code.

## Assumptions

- Installed plugin packages are trusted project/environment code, but target
  imports remain explicit caller actions.
- Existing `PluginLoadResult` and `PluginFailure` shapes are sufficient for
  adapters; any new record or helper must be minimal and plain-summary safe.
- Exact function signatures may follow local Phase 1 style, but public
  behavior must preserve supplied registries, explicit selection, strict
  duplicate handling, and fakeable tests.
- Recipe entry point names remain the authoritative recipe catalog names.
- Codec keys remain runtime object keys and may differ from entry point names.
- Strict mode may report registry duplicate failures through registration
  failure context; it must never silently overwrite or continue as if the load
  succeeded.

## Scope Contract

The executor may choose exact helper names and module decomposition that fit
the landed `loom.plugins` style, but must preserve these public decisions:

- `load_recipe_entry_points(...)` or its equivalent must load only
  `loom.recipes` records selected by the caller and register into the supplied
  `RecipeCatalog`.
- `load_codec_entry_points(...)` or its equivalent must load only
  `loom.codecs` records selected by the caller and register into the supplied
  `CodecRegistry`.
- Both adapters return the generic `PluginLoadResult` or a compatible result
  that preserves loaded plugins, failures, duplicates, counts, `ok`, and plain
  summaries without serializing loaded Python objects.
- Duplicate entry point names continue to use Phase 1 duplicate detection and
  fail in strict mode before duplicate targets are imported.
- Recipe duplicate names from the target catalog are registration failures
  unless the caller explicitly requested recipe replacement.
- Codec runtime key duplicates, including duplicates against already
  registered codecs, are registration failures. Do not add `replace` to
  `CodecRegistry`.
- Codec normalization must stay narrow. If a loaded object cannot be treated as
  a no-argument class, an existing codec instance, or a no-argument factory
  returning a codec, the adapter reports an invalid plugin failure.
- Importing root `loom`, lower runtime packages, CLI modules, preflight
  modules, or future registry owners must not discover or load plugin targets.
  No lower-layer package should import `loom.plugins` because of this phase.
- Adapter modules may depend on recipe or codec registry contracts, but generic
  discovery must not depend on them.

## Design Impact

- Maintainability: keeps package metadata scanning and result aggregation in
  the generic plugin layer while delegating object validation and duplicate
  policy to the existing recipe and codec registries.
- Extensibility: establishes the first concrete contract-specific
  registry-adapter pattern for later source, executor, exporter, provider,
  store, or event-sink loaders without creating a universal plugin object
  protocol.
- Domain neutrality: tests and examples use generic fake recipes/codecs and no
  service, model, dataset, metric, optimizer, or backend-specific behavior.
- Source-tree boundaries: adapter modules sit above the target registries; the
  target registries and lower runtime packages must not import plugin
  discovery.
- Public contract impact: recipe and codec adapter functions become public API
  once exported, so strict duplicate behavior, explicit loading, and supplied
  registry ownership must be stable.

## Future Compatibility

- Phase 3 can render adapter load results in CLI and preflight diagnostics
  using the same plain summaries created by Phase 1.
- Phase 4 can label future groups as listing/check-first without changing the
  recipe or codec adapter contract.
- Stage 15 artifact-store backend work remains free to define a store-owned
  descriptor, factory, config handoff, capability, redaction, and registry
  contract because this phase adds no backend loader.
- Future source, executor, run-exporter, sweep-provider, and event-sink work
  can reuse the list-load-normalize-register-report pattern with their own
  naming, key, replacement, and failure semantics.
- If `CodecRegistry` later gains explicit replacement semantics, a future phase
  can add codec replacement deliberately without changing Stage 14's fail-closed
  default.

## Alternatives Rejected

| Alternative | Reason rejected |
| --- | --- |
| Put recipe and codec loading directly in generic `entrypoints.py` | Would make the generic discovery module import subsystem registry contracts and weaken Phase 1 import boundaries. |
| Mutate global/default recipe or codec registries | Conflicts with explicit caller-supplied registries and makes tests and reproducible setup harder to reason about. |
| Use loaded recipe object names as catalog names | Would require importing targets to determine names and would make package metadata less authoritative. |
| Use entry point names as codec registry keys | Codec keys are runtime representation contracts owned by codec objects and `CodecRegistry`. |
| Add codec replacement support now | The current registry has no replacement API, and the implementation plan intentionally keeps duplicate codec keys failing in Stage 14. |
| Accept arbitrary constructor arguments or configured factories for codecs | Entry point discovery should stay narrow; configured object construction belongs in explicit config or future registry-specific contracts. |
| Add loaders for future groups while building adapters | Source, executor, artifact-store backend, exporter, provider, and event-sink contracts are not ready for Stage 14 registration semantics. |

## Debt Introduced

| Debt | Reason accepted | Revisit trigger |
| --- | --- | --- |
| No codec replacement support | Deterministic duplicate failure matches the current `CodecRegistry` and avoids widening its public API for plugin ergonomics | `CodecRegistry` gains explicit replacement semantics through a future design |
| Codec class/factory normalization is intentionally narrow | No-argument construction keeps entry point loading predictable and avoids embedding config semantics in plugin discovery | A future codec registry contract defines configured factories or descriptor objects |
| Adapter load results may not expose a dedicated runtime codec key field beyond failure messages and summaries | Phase 3 owns presentation polish, and Phase 2 should avoid expanding result records unless needed for correctness | CLI/preflight diagnostics need structured runtime-key fields that cannot be derived safely from loaded codec objects or registry errors |

## Reviewability

- Expected PR size and shape: small public adapter PR with one or two adapter
  modules, export updates, and focused package/unit/contract tests. No CLI,
  preflight, run execution, artifact-store, or future-group runtime behavior
  should change.
- Files and areas to inspect:
  - `src/loom/plugins/`
  - `tests/unit/loom/plugins/`
  - `tests/package/`
  - `tests/contracts/test_plugin_discovery_contract.py`
  - `tests/contracts/test_recipe_contract.py`
  - `tests/contracts/test_codec_contract.py`
  - any minimal integration test chosen for supplied-registry behavior
- Scope-control checks:
  - `src/loom/plugins/entrypoints.py` remains registry-neutral.
  - `RecipeCatalog` and `CodecRegistry` are not widened except for tests that
    exercise existing contracts.
  - No lower-layer module imports `loom.plugins`.
  - No future group loader appears.
  - No real third-party plugin package, optional SDK, network, or service
    dependency appears in tests.
  - No artifact-store backend loading, validation, construction, credential
    probing, URI validation, or runner/preflight wiring appears.

## Implementation Steps

1. Add recipe and codec adapter modules that wrap Phase 1 listing/loading and
   registration behavior while keeping generic discovery registry-neutral.
2. Expose adapter functions through the public plugin API and package tests,
   following the Phase 1 export style.
3. Add recipe adapter tests for fake entry points, selected loading, entry
   point name ownership, invalid objects, catalog duplicates, replacement
   default behavior, and strict/best-effort failure aggregation.
4. Add codec adapter tests for instance/class/factory shapes, constructor and
   factory failures, invalid returned objects, runtime key ownership, duplicate
   runtime keys, existing registry duplicates, and no codec replacement.
5. Add or update contract and minimal integration coverage for adapters using
   real supplied `RecipeCatalog` and `CodecRegistry` instances, then run
   targeted validation before PR preparation.

## Test Plan

### Package Suite

- Status: required.
- Expected paths:
  - `tests/package/test_plugins_api.py` or the existing package API coverage.
  - Existing import-boundary package tests where adapter exports affect public
    imports.
- Required assertions:
  - Public plugin exports include the recipe and codec adapter functions if
    they are part of `loom.plugins.__all__`.
  - `import loom` still does not import or re-export `loom.plugins`.
  - Importing lower packages such as `loom.config`, `loom.io`, and
    `loom.pipeline` still does not discover or load plugins.

### Unit Suite

- Status: required.
- Expected paths: `tests/unit/loom/plugins/`.
- Required assertions:
  - Recipe adapter lists/loads only `loom.recipes` records and only selected
    entries.
  - Recipe adapter uses entry point names as catalog names and defaults to
    `replace=False`.
  - Recipe invalid objects and catalog duplicate failures become plugin-context
    failures.
  - Codec adapter lists/loads only `loom.codecs` records and only selected
    entries.
  - Codec adapter registers valid codec instances, no-argument classes, and
    no-argument factories.
  - Codec constructor/factory failures, invalid objects, missing/invalid keys,
    and duplicate runtime keys become plugin-context failures.
  - Strict mode raises on duplicates or failures; best-effort mode records
    failures and loads eligible non-duplicate selections.
  - Plain summaries omit loaded recipe and codec objects.

### Contract Suite

- Status: required.
- Expected paths:
  - `tests/contracts/test_plugin_discovery_contract.py`
  - `tests/contracts/test_recipe_contract.py`
  - `tests/contracts/test_codec_contract.py`
- Required assertions:
  - Public adapter behavior preserves metadata-only listing until explicit
    loading.
  - A fake recipe plugin can populate a supplied `RecipeCatalog` and then be
    used through the existing recipe expansion contract.
  - A fake codec plugin can populate a supplied `CodecRegistry` and then be
    used through existing encode/decode registry methods.
  - Duplicate entry point names and duplicate codec runtime keys are
    fail-closed public behavior, not silent overwrite.
  - Future group contracts still have no loaders in this phase.

### Integration Suite

- Status: required with minimal scope.
- Expected paths: a focused existing integration area if contract tests do not
  already provide end-to-end supplied-registry coverage.
- Required assertions:
  - Adapter-loaded recipes and codecs work through actual supplied registries
    across module boundaries without CLI, preflight, runner, or global registry
    wiring.
  - No real installed third-party package metadata or optional service
    dependency is required.
- Deferral boundary: no run workflow, CLI workflow, artifact-store, source,
  executor, exporter, provider, or event-sink integration is expected in this
  phase.

### E2E Suite

- Status: deferred for this phase.
- Deferral reason: Phase 2 adds Python API adapter behavior only. User-facing
  CLI and run workflows are assigned to later phases.

### Opt-In Suites

- Status: deferred for this phase.
- Markers affected: none expected.
- Deferral reason: adapter tests must use fake entry points and supplied local
  registries, not optional service SDKs, real plugin packages, network access,
  SLURM, or acceptance environments.

## Risks

- Adapter exports can accidentally make `loom.plugins` import heavier than
  intended.
- Codec class/factory normalization can become too permissive and mask
  configuration that should be explicit project code.
- Strict-mode codec duplicate failures can leave confusing partial registry
  state if implementation relies only on sequential registration. The executor
  should prefer deterministic failure context and avoid silent overwrite.
- Recipe replacement can accidentally default to replacement.
- Failure messages can lose plugin metadata or expose unsafe object reprs.

## Stop Conditions

- The implementation requires changing `RecipeCatalog` or `CodecRegistry`
  public behavior beyond tests that exercise existing contracts.
- `CodecRegistry` replacement support is added.
- Runtime codec key duplicates are silently overwritten.
- Adapter loading mutates a global/default registry as the only supported path.
- Listing or importing root/lower packages loads plugin targets.
- Generic discovery starts importing recipe, codec, CLI, preflight, runner,
  artifact-store, source, executor, exporter, provider, or event-sink modules.
- The implementation adds future group loaders or artifact-store backend
  semantics.
- The plan quality gate is found to have unresolved blocking findings.

## Validation Commands

Targeted development commands:

```sh
uv run pytest tests/unit/loom/plugins tests/contracts/test_plugin_discovery_contract.py tests/contracts/test_recipe_contract.py tests/contracts/test_codec_contract.py
```

Final PR-preparation commands:

```sh
make validate-pr
make test-summary
```

`make validate-pr` remains the required PR gate. `make test-summary` should be
run during PR preparation so the PR body can report suite-level evidence.

## Handoff Notes For `loom_phase_executor`

- Safe implementation slices:
  - Add adapter modules and exports before expanding behavior.
  - Implement recipe registration through supplied catalogs using existing
    generic load callbacks.
  - Implement codec normalization and registration with narrow object-shape
    handling and explicit duplicate failure tests.
  - Finish with package/import-boundary tests and targeted validation.
- Tests to run with each slice:
  - Exports/import boundaries: package tests plus existing plugin discovery
    contract tests.
  - Recipe adapter: plugin unit tests plus recipe contract coverage.
  - Codec adapter: plugin unit tests plus codec contract coverage.
- Decisions the executor must not revisit:
  - Entry point name is the recipe name.
  - Runtime `codec.key` is the codec registry key.
  - Codec replacement is not supported in Stage 14.
  - Supplied registries are the mutation boundary.
  - Future plugin groups remain without registration loaders.
- Conditions that require stopping for the manager:
  - Existing Phase 1 result records are insufficient without a public API
    change that affects Phase 3 or Phase 4.
  - Import-boundary tests cannot pass without moving adapters into a different
    public package shape.
  - Registry duplicate handling requires transactional behavior that existing
    registries cannot support without broad changes.

## Refinement And Review Budget Status

- Phase planning draft: completed.
- Phase planning refinement: completed for the expanded path.
- Phase implementation refinement: unused until implementation validation or
  adapter API review finds a blocker.
- PR body draft/refine: unused until PR preparation.
- PR review: unused until the manager or reviewer consumes the single review
  pass.
- Blocker resolution: 0/3 used.

## Completion Notes

- Draft plan: completed in
  `docs/roadmap/stage-14/phases/recipe-codec-plugin-adapters.md`.
- Final phase execution plan: completed and ready for implementation handoff.
- Implementation summary: pending.
- Implementation validation: pending.
- PR preparation: pending.
- Stack maintenance: root phase targets `develop`; no predecessor branch exists
  and no retarget or rebase is needed at planning time.
- Remaining blockers: none for implementation handoff.
