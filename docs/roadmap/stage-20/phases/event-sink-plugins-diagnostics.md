# Phase 4 Execution Plan: Event Sink Plugins And Diagnostics

## Metadata

- Status: final phase execution plan; scope-complete for implementation
- Feature focus: Runtime Events
- PR title: `Runtime Events - Phase 4: Event Sink Plugins and Diagnostics`
- Branch: `codex/event-sink-plugins-diagnostics`
- Worktree: `/home/samcantrill/work/loom-worktrees/event-sink-plugins-diagnostics`
- Phase execution plan path: `docs/roadmap/stage-20/phases/event-sink-plugins-diagnostics.md`
- Full plan: `docs/roadmap/stage-20/implementation-plan.md`
- Source phase: Phase 4, `event-sink-plugins-diagnostics`
- Stack predecessor: none; Phases 1, 2, and 3 merged before Phase 4 work began
- Base branch: `develop`
- Target branch: `develop`
- Merge eligibility: root PR; merge-eligible after the PR targets `develop`,
  automated review passes, local validation passes, GitHub CI passes, and the
  phase remains scoped to Phase 4
- Workflow path: expanded path
- Plan quality gate: verified passed in the implementation plan on 2026-05-17
- Draft pass: completed by manager on 2026-05-17
- Refine pass: completed by manager on 2026-05-17; current plugin readiness and
  diagnostics boundaries incorporated
- Setup limitations: worktree created from `develop` at
  `af76cd3` after Phase 3 merge metadata landed. No stack predecessor is
  active.
- Blockers: none

## Objective

Expose explicit `loom.event_sinks` entry point loading into a supplied
`EventSinkRegistry`, update plugin readiness and preflight diagnostics, and
document the final Stage 20 runtime-event behavior without introducing ambient
plugin discovery or a mutating event CLI.

## Scope

- Add `loom.plugins.event_sinks` as the explicit adapter for event sink entry
  points.
- Register selected `loom.event_sinks` records into a caller-supplied
  `EventSinkRegistry` using entry point names as deterministic registry names.
- Accept plugin values that are callable sinks, no-arg sink classes, or no-arg
  factories returning sinks.
- Preserve strict and best-effort load behavior through existing
  `PluginLoadResult`, `PluginFailure`, `PluginLoadError`, and
  `PluginRegistrationError` paths.
- Update plugin readiness so `loom.event_sinks` is registry-ready and loadable.
- Update plugin preflight so selected event sink plugins are loaded only in a
  scratch registry and listing-only groups still avoid imports.
- Keep diagnostics cheap: metadata listing remains import-free, loading happens
  only after explicit plugin selectors, and preflight does not create runtime
  runs or dispatch events.
- Update feature docs and structure guidance for event sink plugin loading,
  callback failure/observer-link inspection, and explicit CLI deferrals.

## Out Of Scope

- Ambient plugin loading, global registries, or import-time sink discovery.
- Configured constructors or declarative plugin construction.
- Service-specific sinks or bundled SDK clients.
- Mutating event or sink CLI commands.
- Broad event inspection CLI. This phase documents Python/read-model
  inspection through store APIs instead of adding a CLI surface.
- Cleanup, retention, distributed streaming, strict audit mode, retry policy
  changes, and event-driven mutation of runtime facts.

## Design Contract

- `loom.pipeline.event_sinks` remains the public sink contract owner. The plugin
  layer adapts entry point values into an existing supplied registry and must
  not define event names, payloads, ordering, callback-failure semantics, or
  observer-link persistence.
- Loader calls are explicit. Listing entry points must not import targets, and
  importing `loom.plugins` must remain import-light.
- Registry names come from entry point names and therefore use existing
  `EventSinkRegistry.register()` validation. Duplicate entry point names or
  duplicate registry registration failures are surfaced through existing plugin
  failure/result models.
- A callable with a sink-like signature is registered directly. A class is
  instantiated with no arguments and must produce a callable sink. A no-arg
  non-class callable that is not sink-like is treated as a factory and must
  return a callable sink.
- Preflight loads event sink plugins only into a scratch `EventSinkRegistry`.
  It must not dispatch events, write observer facts, or inspect project runtime
  stores.

## Implementation Steps

1. Add `src/loom/plugins/event_sinks.py` with
   `load_event_sink_entry_points()` and value normalization helpers.
2. Add lazy public exports from `loom.plugins` while preserving import-light
   package behavior.
3. Update plugin readiness diagnostics to classify `loom.event_sinks` as
   registry-ready/loadable and to load selected event sink records into a
   scratch registry during plugin checks.
4. Add unit, package, and contract tests for accepted plugin shapes, invalid
   shapes, duplicate behavior, strict/best-effort failures, readiness metadata,
   and listing without loading.
5. Update plugin preflight tests so event sinks are loadable only when
   explicitly selected, while remaining future groups still skip imports.
6. Update feature docs for plugin loading, read-only inspection through store
   facts, preflight behavior, CLI deferral, and Stage 20 final validation.

## Test Plan

### Plugin Unit And Contract Suites

- Status: required
- Expected paths:
  `tests/unit/loom/plugins/test_adapters.py`,
  `tests/unit/loom/plugins/test_diagnostics.py`,
  `tests/unit/loom/plugins/test_entrypoints.py`,
  `tests/contracts/test_plugin_discovery_contract.py`,
  `tests/contracts/test_plugin_future_groups_contract.py`
- Required assertions: event sink values register from callable sink, no-arg
  class, and no-arg factory shapes; invalid values and constructor/factory
  failures are reported as registration failures; duplicate selected entry
  point names fail before import in strict mode; `loom.event_sinks` readiness is
  registry-ready; listing-only groups remain metadata-only.

### Package Suite

- Status: required
- Expected path: `tests/package/test_plugins_api.py`
- Required assertions: `load_event_sink_entry_points` is a lazy public plugin
  export, `loom.plugins` remains import-light, and root `loom` import does not
  export plugins.

### Diagnostics And Preflight Suites

- Status: required
- Expected paths:
  `tests/unit/loom/diagnostics/test_preflight_plugins.py`,
  `tests/unit/loom/diagnostics/test_diagnostics_preflight.py`,
  `tests/contracts/test_diagnostics_preflight_contract.py`,
  `tests/contracts/test_cli_preflight_contract.py`
- Required assertions: plugin preflight skips discovery without selectors,
  loads selected event sinks in a scratch registry, does not dispatch events,
  and keeps stable check IDs unchanged.

### CLI Suite

- Status: deferred
- Deferral reason: this phase intentionally avoids broad event inspection CLI
  because existing stable store/read-model APIs already expose events, callback
  failures, and observer links. CLI help and preflight contracts remain covered
  by package and preflight tests.

### Docs

- Status: required
- Expected paths: `docs/features/plugins.md`, `docs/features/reliability.md`,
  `docs/features/preflight.md`, `docs/features/cli.md`,
  `docs/features/run-store.md`, `docs/features/testing.md`,
  `docs/structure.md`
- Required assertions or deferral reason: docs reflect explicit plugin loading,
  registry-ready event sink group, read-only inspection through store APIs,
  callback failure defaults, observer-link facts, CLI deferral, and final Stage
  20 validation obligations.

## Validation Commands

```sh
uv run pytest tests/unit/loom/plugins/test_entrypoints.py tests/unit/loom/plugins/test_adapters.py tests/unit/loom/plugins/test_diagnostics.py tests/contracts/test_plugin_discovery_contract.py tests/contracts/test_plugin_future_groups_contract.py tests/package/test_plugins_api.py
uv run pytest tests/unit/loom/diagnostics/test_diagnostics_preflight.py tests/unit/loom/diagnostics/test_preflight_plugins.py tests/contracts/test_diagnostics_preflight_contract.py tests/contracts/test_cli_preflight_contract.py
make validate-pr
make test-summary
```

## Budget Status

- Phase implementation refinement: unused; manager-local validation fixes stayed
  within the implementation pass and did not consume the optional refiner pass
- PR review: used by manager local review on 2026-05-17; no blocking findings
  found, scope confirmed limited to explicit event sink plugin loading,
  plugin/preflight readiness, tests, docs, and phase artifacts
- Blocker resolution: 0/3 used

## Design Impact

- Maintainability: event sink plugin loading stays isolated in the plugin
  adapter layer and reuses existing plugin result/error models.
- Extensibility: service-specific sinks can ship as external packages over the
  same generic entry point and supplied-registry contract.
- Domain neutrality: core examples and tests use fake audit sinks only; no
  service SDKs or metric/tracking terms enter core contracts.
- Source-tree boundaries: records and sink protocols remain in
  `loom.pipeline`; discovery/adapters remain in `loom.plugins`; diagnostics
  only read plugin metadata and scratch-load selected plugins.

## Future Compatibility

- Configured constructors can be added later without changing the public
  registry or entry point group name.
- Strict audit mode can later decide whether callback failure records should
  fail runs, because Phase 4 does not alter Phase 3 best-effort dispatch.
- A future CLI can inspect event/failure/link read models without changing the
  loader contract.

## Alternatives Rejected

| Alternative | Reason rejected |
| --- | --- |
| Load event sink plugins automatically during runtime import | Creates ambient behavior and makes installed packages affect runs without explicit trusted setup |
| Create a process-global sink registry | Conflicts with instance-local registry behavior and makes tests/order hard to audit |
| Add configured constructor support now | Requires a configuration contract outside the approved Phase 4 scope |
| Add broad event inspection CLI now | Current stable read APIs cover inspection; a CLI surface would expand scope and public command contracts late in the stage |
| Let plugin adapters define event names or payload conventions | Moves event semantics out of the runtime-event contract and into third-party discovery |

## Debt Introduced

| Debt | Reason accepted | Revisit trigger |
| --- | --- | --- |
| Event sink plugin constructors must be no-arg | Keeps loading deterministic and dependency-light | Downstream plugin authors need declarative constructor configuration |
| CLI event inspection remains deferred | Avoids broad command-surface work after store/read APIs already expose facts | Users need stable command-line audit inspection without Python/store API calls |
| Preflight scratch-loads but does not dispatch sinks | Prevents preflight from writing facts or requiring runtime events | Users need explicit sink callback smoke tests with fake event envelopes |

## Reviewability

- Expected PR shape: small-to-moderate plugin adapter, readiness diagnostics,
  tests, docs, phase plan, and PR body.
- Files and areas to inspect: `src/loom/plugins/event_sinks.py`,
  `src/loom/plugins/__init__.py`, `src/loom/plugins/diagnostics.py`, plugin
  and preflight tests, feature docs, and `docs/structure.md`.
- Scope-control checks: no runtime dispatch changes, no store schema changes,
  no global registry, no service SDK dependencies, no mutating CLI commands,
  and no future cleanup/strict-audit behavior.

## Completion Notes

- Draft plan: completed by manager on 2026-05-17
- Final phase execution plan: completed by manager on 2026-05-17
- Implementation summary: added `loom.plugins.event_sinks` with explicit
  `load_event_sink_entry_points()` support for callable sinks, no-arg sink
  classes, and no-arg factories; exported the loader lazily from `loom.plugins`;
  moved `loom.event_sinks` readiness to registry-ready/loadable; scratch-loads
  selected event sink plugins during plugin diagnostics/preflight; updated CLI
  plugin expectations, feature docs, testing docs, and source-tree guidance.
- Validation: targeted plugin and preflight suites passed; `make validate-pr`
  passed Ruff, Pyright, default harness, config-extra harness, and build; `make
  test-summary` passed with overall 2385 passed, 21 skipped, and 1961
  deselected.
- PR preparation: PR body artifact prepared at
  `docs/roadmap/stage-20/phases/event-sink-plugins-diagnostics-pr-body.md`;
  PR opening pending.
- Remaining blockers: none
