# Phase 3 Execution Plan: CLI, Preflight, And Provenance Summaries

## Metadata

- Status: scope-complete phase execution plan; ready for implementation
- Feature focus: Plugin Discovery
- PR title:
  `Plugin Discovery - Phase 3: CLI, Preflight, And Summaries`
- Branch: `codex/plugin-cli-preflight-summaries`
- Worktree:
  `/home/samcantrill/work/loom-worktrees/plugin-cli-preflight-summaries`
- Phase execution plan path:
  `docs/roadmap/stage-14/phases/plugin-cli-preflight-summaries.md`
- Full plan: `docs/roadmap/stage-14/implementation-plan.md`
- Source phase: Phase 3, `plugin-cli-preflight-summaries`
- Stack predecessor: none
- Base branch: `develop` at `94bcf5e35be97096190334736775c61a625c8d1f`
- Target branch: `develop`
- Merge eligibility: root phase PR targets `develop`; merge-eligible only
  after implementation, required validation, automated review, CI or justified
  unavailable checks, scope verification, and target-branch verification pass.
- Workflow path: expanded path, because this phase adds public CLI,
  preflight, and diagnostic summary surfaces over plugin discovery.
- Successor dependency notes: Phase 4 should branch from this phase branch if
  Phase 3 is `pr_open` or `approved` but not merged; otherwise Phase 4 should
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

Expose the landed Stage 14 plugin APIs through user-facing plugin inspection,
explicit plugin checks, requested preflight diagnostics, and plain-data
summaries suitable for CLI JSON, preflight details, and future provenance
consumers. The phase must keep `loom plugins list` metadata-only by default,
make any target imports explicit, and avoid converting listing-only future
groups into runtime-ready contracts.

## Full-Plan Context

Phases 1 and 2 have landed the import-light `loom.plugins` package, known group
constants, metadata-only listing, selected explicit loading, duplicate/failure
records, public recipe and codec adapter functions, and fake-entry-point tests.
This phase is the presentation and diagnostics layer over those APIs.

Phase 4 remains responsible for the broader future-group readiness pass. This
phase may add the minimal group status labels needed for CLI and preflight to
avoid false readiness claims, but it must not add source, executor,
artifact-store backend, run-exporter, sweep-provider, or event-sink
registration loaders. `loom.artifact_store_backends` remains metadata-only
until Stage 15 defines the backend descriptor, registry, config, capability,
redaction, preflight, and operation contracts.

## Stack Context

- Root or stacked phase: root phase.
- Current predecessor branch or PR: none; Phases 1 and 2 are merged into
  `develop`.
- Why this base branch is correct: the user assigned current `develop`, and
  the implementation plan records Phase 2 as merged with Phase 3 ready for
  execution planning.
- Retarget/rebase plan after predecessor merge: none for this phase.
- Branch cleanup constraints: this branch can be deleted after merge only if
  no successor phase still targets or branches from it.

## Source Phase Summary

- Goal: expose plugin inspection/check behavior through CLI commands,
  requested preflight diagnostics, and plain-data summary helpers.
- Required scope:
  - `loom plugins list` with metadata-only default behavior.
  - `loom plugins list --load` or equivalent explicit load mode for selected,
    registry-ready recipe/codec entries.
  - `loom plugins check` with clear text and JSON diagnostics, nonzero status
    for requested failures, and listing-only handling for unsupported groups.
  - Requested plugin preflight checks that report missing requested plugins,
    duplicate advertisements, load/registration failures, and listing-only
    status without executing stages or mutating run state.
  - Plain summary helpers under `loom.plugins` if the existing record/result
    `to_summary()` methods are not sufficient for CLI/preflight payloads.
- Required checkpoints:
  - `loom --help`, `loom plugins --help`, and default `loom plugins list` do
    not load plugin targets.
  - CLI JSON output uses stable schema versions
    `loom.cli.plugins.list.v1` and `loom.cli.plugins.check.v1`.
  - Preflight plugin diagnostics use `PreflightGroup.PLUGINS` with value
    `plugins` and stable check IDs `plugins.metadata` and `plugins.load`.
  - JSON summaries expose group, name, value, package, package_version, status,
    duplicate/failure counts, and safe failure context without loaded Python
    objects.
  - Recipe and codec checks use scratch caller-supplied registries or an
    equivalent non-global path; no global/default registry is mutated as the
    only supported behavior.
  - Listing-only groups are never described as registered, available, or usable
    for runs based only on Stage 14 discovery.
- Acceptance criteria: users and CI can inspect and verify requested plugins
  through stable text/JSON command output; preflight can report requested plugin
  diagnostics through stable check IDs; summaries remain plain data and
  provenance persistence remains outside `loom.plugins`.

## Current Source And Harness Findings

- Landed plugin API:
  - `src/loom/plugins/entrypoints.py` exports known group constants,
    `PluginRecord`, `LoadedPlugin`, `PluginDuplicate`, `PluginFailure`,
    `PluginLoadResult`, `list_entry_points(...)`, `find_plugin_duplicates(...)`,
    and `load_entry_points(...)`.
  - `PluginRecord`, loaded plugins, duplicates, failures, and load results
    already provide `to_summary()` methods that omit loaded objects.
  - `src/loom/plugins/recipes.py` provides `load_recipe_entry_points(...)`
    over a structural supplied recipe catalog.
  - `src/loom/plugins/codecs.py` provides `load_codec_entry_points(...)` over
    a supplied `CodecRegistry`.
  - `src/loom/plugins/__init__.py` lazy-exports recipe and codec adapters so
    importing `loom.plugins` stays import-light.
- CLI shape:
  - `src/loom/cli/main.py` uses argparse and per-command `register_subparser`
    modules.
  - Command modules own schema-version constants, output options, handlers,
    and text/JSON formatting through `format_json_envelope(...)`.
  - `OutputFormat` and CLI error exit mapping already exist.
- Preflight shape:
  - `src/loom/diagnostics/models.py` owns `PreflightGroup`,
    `PreflightCheckResult`, `PreflightRequest`, `PreflightResult`, and stable
    check IDs.
  - `src/loom/diagnostics/preflight.py` dispatches selected groups through a
    `_CHECKS` mapping and should remain non-persistent.
  - `src/loom/cli/preflight.py` builds `PreflightRequest` from CLI options and
    formats result envelopes with schema `loom.cli.preflight.v3`.
- Test harness:
  - Plugin unit tests already use fake entry points and monkeypatched imports.
  - CLI tests invoke `loom.cli.main.main(...)` with in-memory stdout/stderr.
  - Package/import-boundary tests use subprocess checks for cheap imports and
    help/import behavior.
  - Contract tests already lock preflight check IDs and plugin discovery
    metadata-only behavior.

## In-Scope Work

- Add a `loom plugins` CLI command group, likely in `src/loom/cli/plugins.py`,
  and register it from `src/loom/cli/main.py`.
- Add `plugins list`:
  - metadata-only by default;
  - repeatable `--group`, `--name`, and `--package` filters using the public
    plugin metadata fields;
  - text and JSON output over plain summaries;
  - deterministic ordering matching plugin API behavior;
  - no target imports unless `--load` is selected with at least one selector.
- Add `plugins check`:
  - repeatable `--group`, `--name`, and `--package` selection;
  - registry-ready checks for recipe and codec entry points using
    non-persistent scratch registries;
  - metadata-only checks and listing-only status for groups without Stage 14
    loaders;
  - deterministic duplicate and missing-request diagnostics;
  - nonzero CLI exit for requested missing plugins, duplicates, load failures,
    registration failures, or unsupported load/register requests.
- Add a small plugin diagnostics/result layer under `src/loom/plugins` if
  needed to keep CLI and preflight thin over public Python APIs. This layer may
  centralize status labels, listing-only classification, selection filtering,
  and safe plain summaries. It must remain import-light and must not import CLI
  modules.
- Add preflight plugin diagnostics for explicit requests:
  - add `PreflightGroup.PLUGINS = "plugins"` and
    `STABLE_CHECK_IDS[PreflightGroup.PLUGINS] = ("plugins.metadata",
    "plugins.load")`;
  - extend `PreflightRequest` and CLI option adapters with repeatable
    `--plugin-group`, `--plugin-name`, and `--plugin-package` selectors rather
    than scanning/loading every installed target by default;
  - return `SKIP` with guidance when plugin preflight is selected without
    enough selectors, instead of importing all advertised targets.
- Add or preserve plain plugin summaries for CLI JSON, preflight details, and
  future provenance callers. Summaries may include loaded status/counts and
  safe failure fields, but must not include loaded objects, object reprs,
  traceback bodies, credentials, or callback state.
- Add tests for CLI command registration, text/JSON output, explicit load
  behavior, nonzero check exit, preflight details, summary object omission, and
  help/import safety.

## Out-of-Scope Work

- Persisting plugin summaries into run provenance, run-store documents, or
  versioned provenance schemas.
- Adding new concrete plugin integrations or optional third-party packages.
- Plugin marketplace, install, upgrade, dependency resolution, remote index,
  trust scoring, or sandbox behavior.
- Third-party command injection into the core `loom` CLI.
- Loading plugin targets from `import loom`, `import loom.plugins`,
  `loom --help`, `loom plugins --help`, default `loom plugins list`, or
  unrelated commands.
- Adding loaders or registry mutation for sources, executors, artifact-store
  backends, run exporters, sweep providers, or event sinks.
- Artifact-store backend registration, store construction, credential probing,
  URI validation, capability probing, runner integration, or run-readiness
  claims.
- Broad preflight plugin target scans without explicit selectors.

## Assumptions

- Recipe and codec entry points are the only Stage 14 registry-ready groups.
- CLI checks can verify recipe/codec loadability using scratch supplied
  registries without persisting registration or mutating process-global state.
- Metadata-only listing of installed entry points is acceptable for explicit
  plugin commands and selected preflight plugin metadata checks.
- Exact option names may follow local CLI style, but the behavior must preserve
  the selector names recorded above unless implementation discovers a direct
  conflict with existing argparse behavior.
- Provenance-facing work in this phase means plain summary shape only. Run or
  provenance code owns any later persistence decision.

## Scope Contract

The executor may choose exact helper names and internal decomposition that fit
the landed plugin API, but must preserve these public decisions:

- `loom plugins list` is side-effect-light by default and must not import
  plugin target modules.
- `loom plugins list --load` or its equivalent must be visibly explicit and
  must report that loading imports trusted installed Python code.
- `loom plugins check` must fail closed for requested missing plugins,
  duplicate entry point names, load failures, registration failures, and
  unsupported registration requests.
- Recipes and codecs are the only registry-ready groups for this phase.
  Loading/checking any other group is metadata-only or clearly labelled
  import-only if such a diagnostic is implemented; it is never registration or
  run-readiness.
- Artifact-store backend output must say listing/check-only until Stage 15
  defines backend registry semantics. It must not say "registered",
  "available", "usable", or "ready for runs" based only on entry point
  metadata.
- Preflight plugin checks run only for explicit plugin selectors or selected
  plugin capability requests. They do not execute stages, create run
  directories, write run-store documents, probe credentials, call network
  services, or mutate run state.
- Plugin summaries are plain data. Loaded Python objects remain available to
  Python callers through load results, but summaries and JSON/preflight payloads
  omit objects and unsafe internals.
- CLI and preflight consume plugin APIs. `loom.plugins` must not import CLI or
  preflight modules, and lower runtime packages must not import plugin
  discovery because of this phase.
- `PLUGINS_LIST_SCHEMA_VERSION` must be `loom.cli.plugins.list.v1` and
  `PLUGINS_CHECK_SCHEMA_VERSION` must be `loom.cli.plugins.check.v1`, or
  equivalently named constants with those exact values.

## Design Impact

- Maintainability: keeps plugin CLI/preflight presentation thin over public
  plugin APIs and any small diagnostics helpers, avoiding duplicate result
  parsing in CLI and diagnostics modules.
- Extensibility: creates a reusable diagnostics boundary for future groups
  while retaining contract-specific loader ownership for recipes and codecs.
- Domain neutrality: output and tests use generic plugin groups and fake
  entry points only; no service, model, dataset, metric, optimizer, cloud, or
  notification behavior belongs in this phase.
- Source-tree boundaries: CLI and preflight are outer callers. Generic plugin
  modules stay independent from CLI, run stores, runner lifecycle, and future
  registry owners.
- Public contract impact: command names, CLI JSON schema versions, preflight
  group/check IDs, and summary fields become user-visible diagnostics and must
  be tested as stable behavior.

## Future Compatibility

- Phase 4 can expand future-group readiness docs/tests without changing the
  Phase 3 command shape or summary model.
- Stage 15 can add artifact-store backend descriptor/factory loading into a
  store-owned supplied registry later because Phase 3 labels backend entries as
  metadata-only.
- Stage 16 optional backend packages can rely on metadata listing without
  adding optional dependencies to core Loom.
- Stage 19 event-sink runtime contracts can reuse the listing/check command
  shape after an event-sink registry exists.
- Provenance/run-store work can persist plugin summaries later with a versioned
  schema if needed, without making `loom.plugins` own persistence.

## Alternatives Rejected

| Alternative | Reason rejected |
| --- | --- |
| Auto-load plugins during CLI startup or preflight defaults | Violates metadata-first discovery and can import optional SDKs or project code during unrelated commands. |
| Put plugin command logic directly in `main.py` | Would make the CLI entry point heavier and diverge from existing per-command module structure. |
| Make `loom.plugins` format CLI text or parse argparse options | Would invert the dependency direction; CLI owns presentation. |
| Persist plugin summaries into run provenance now | The plan explicitly keeps summaries plain and leaves persistence to provenance/run callers after a stable schema decision. |
| Treat artifact-store backend entries as runnable backend availability checks | Stage 15 owns backend descriptor, registry, config, capability, and operation semantics. |
| Add generic loaders for every known group | Source, executor, artifact-store backend, exporter, provider, and event-sink contracts are not ready for Stage 14 registration semantics. |
| Depend on real installed plugin packages in tests | Would make tests environment-dependent and could import optional service dependencies. |

## Debt Introduced

| Debt | Reason accepted | Revisit trigger |
| --- | --- | --- |
| Plugin summary payloads are diagnostic summaries, not a versioned persisted provenance schema | Phase 3 needs reusable plain data without coupling `loom.plugins` to run-store persistence | Provenance/run-store work needs to persist loaded plugin evidence as a stable document |
| CLI scratch-registry checks may not reflect every project-specific registry setup | Core CLI has no project setup hook for arbitrary caller-supplied registries | A project configuration or setup hook defines explicit plugin loading into project registries |
| Future groups receive only minimal listing-only labels in this phase | Phase 4 owns full future-group readiness documentation and contract hooks | Phase 4 implementation begins or a future group gains a stable owning registry/protocol |
| Preflight plugin selection fields may be narrow | Avoids broad installed-environment target imports and keeps diagnostics explicit | Config/plugin requirement metadata lands and can drive selected preflight checks safely |

## Reviewability

- Expected PR size and shape: small-to-medium CLI/diagnostics PR with one new
  CLI command module, small plugin diagnostics or summary helpers if needed,
  preflight model/check additions, and focused package/unit/contract tests.
- Files and areas to inspect:
  - `src/loom/cli/main.py`
  - `src/loom/cli/plugins.py`
  - `src/loom/cli/formatting.py` only if shared text helpers are added
  - `src/loom/cli/options.py` and `src/loom/cli/preflight.py`
  - `src/loom/diagnostics/models.py`
  - `src/loom/diagnostics/preflight.py`
  - `src/loom/plugins/`
  - `tests/unit/loom/cli/`
  - `tests/unit/loom/diagnostics/`
  - `tests/unit/loom/plugins/`
  - `tests/contracts/`
  - `tests/package/`
- Scope-control checks:
  - No product code outside CLI, diagnostics, and plugin summary/diagnostics
    helpers unless a focused test requires it.
  - No lower-layer package imports CLI, preflight, or plugin discovery.
  - No artifact-store backend loader, backend registry, raw store validation,
    credential probe, URI validation, or runner/preflight artifact-store wiring
    appears.
  - No real plugin packages, service SDKs, network calls, or optional backend
    dependencies appear in tests.
  - No future Phase 4 readiness docs/table expansion beyond minimal labels
    required for command/preflight correctness.

## Implementation Steps

1. Add small plugin diagnostics/summary helpers only if the existing
   `to_summary()` methods are insufficient for command/preflight payloads.
2. Add the `loom plugins` CLI command group with list/check parsers, text/JSON
   output, deterministic filters, and explicit-load behavior.
3. Add preflight plugin request fields and selected plugin checks with stable
   check IDs, preserving default preflight behavior for non-plugin requests.
4. Add package/import-boundary, unit, contract, and minimal integration tests
   with fake entry points and monkeypatched imports/providers.
5. Run targeted validation during implementation, then leave final
   `make validate-pr` and `make test-summary` evidence for PR preparation.

## Test Plan

### Package Suite

- Status: required.
- Expected paths:
  - `tests/package/test_plugins_api.py`
  - `tests/package/test_import_boundaries.py`
  - `tests/package/test_import.py` or existing public import coverage as
    needed.
- Required assertions:
  - Any new plugin summary/diagnostics helpers exported from `loom.plugins`
    are import-light and included in public API tests.
  - `import loom` still does not import or re-export `loom.plugins`.
  - Importing `loom.plugins` still does not import CLI, preflight, config,
    pipeline, optional config extras, or plugin target modules.
  - Building or formatting CLI help for `loom` and `loom plugins` does not
    discover or load plugin targets.

### Unit Suite

- Status: required.
- Expected paths:
  - `tests/unit/loom/plugins/`
  - `tests/unit/loom/cli/`
  - `tests/unit/loom/diagnostics/`
- Required assertions:
  - Summary helpers and existing `to_summary()` output remain plain data and
    omit loaded objects, unsafe reprs, credentials, and traceback bodies.
  - `plugins list` text/JSON lists metadata deterministically without loading.
  - `plugins list --load` imports only explicitly selected registry-ready
    records and reports load results safely.
  - `plugins check` reports missing requested plugins, duplicate entry point
    names, recipe load/registration failures, codec normalization/duplicate
    failures, and listing-only group status with correct exit codes.
  - CLI filters by group/name/package without stringly re-parsing summaries
    when structured records are available.
  - Preflight plugin checks produce PASS/FAIL/SKIP statuses and details for
    requested metadata, load failures, duplicates, and listing-only groups.
  - Preflight with no plugin selectors does not import every installed plugin
    target.

### Contract Suite

- Status: required.
- Expected paths:
  - `tests/contracts/test_plugin_discovery_contract.py`
  - a new or existing CLI plugins contract test for JSON envelopes
  - `tests/contracts/test_diagnostics_preflight_contract.py`
  - `tests/contracts/test_cli_preflight_contract.py` if preflight JSON schema
    details change.
- Required assertions:
  - `loom plugins list --format json` and `loom plugins check --format json`
    expose stable schema versions and stable plain-data result fields.
  - CLI check failure exits nonzero and preserves diagnostic context in JSON.
  - Preflight group/check IDs include plugin diagnostics if the phase adds a
    `plugins` group.
  - Metadata-only listing and selected explicit loading remain the public
    plugin contract.
  - Listing-only groups, especially `loom.artifact_store_backends`, are not
    described as run-ready.

### Integration Suite

- Status: required with minimal scope.
- Expected paths: `tests/integration/diagnostics/` or another focused existing
  integration area chosen by the executor.
- Required assertions:
  - CLI, plugin diagnostics helpers, and preflight checks work together using
    fake entry points and scratch registries.
  - A best-effort check can report multiple failures in one result.
  - No run workflow, run-store persistence, artifact-store backend, network,
    service SDK, or real installed extension package is required.

### E2E Suite

- Status: deferred for phase-specific new coverage.
- Deferral reason: deterministic plugin CLI/preflight behavior requires fake
  entry points and monkeypatched imports, which belong in package, unit,
  contract, and focused integration tests. Existing e2e coverage still runs as
  part of `make validate-pr`.
- Optional smoke: executor may add a no-plugin `loom plugins list --format
  json` smoke only if it can be deterministic in the test environment.

### Opt-In Suites

- Status: deferred for this phase.
- Markers affected: none expected.
- Deferral reason: plugin diagnostics must use fake entry points and local
  scratch registries, not optional service SDKs, real plugin packages, network
  access, SLURM acceptance environments, or external artifact stores.

## Risks

- CLI wording can imply listing-only groups are loadable or run-ready.
- `plugins check` or preflight can accidentally import every installed plugin
  target when the user only wanted metadata.
- JSON summaries can leak loaded object reprs, exception internals, or
  credential-bearing messages.
- Preflight group/check ID changes are public and can break contract tests if
  not deliberately versioned.
- Scratch-registry checks can be mistaken for project-specific registration
  success.
- Sharing helpers between CLI and preflight can accidentally make
  `loom.plugins` import CLI/preflight or make lower layers import plugin
  discovery.

## Stop Conditions

- `loom --help`, `loom plugins --help`, default `loom plugins list`, or default
  preflight imports plugin target modules.
- The implementation adds or relies on a source, executor, artifact-store
  backend, run-exporter, sweep-provider, or event-sink registration loader.
- Artifact-store backend checks construct stores, probe credentials, validate
  URI schemes, call runner/preflight artifact-store internals, or claim
  run-readiness.
- Plugin summaries cannot be kept plain-data-only without loaded objects or
  unsafe exception/object content.
- Preflight plugin checks require creating run state or executing stages.
- The plan quality gate is found to have unresolved blocking findings.

## Validation Commands

Targeted development commands:

```sh
uv run pytest tests/unit/loom/plugins tests/unit/loom/cli tests/unit/loom/diagnostics tests/contracts/test_plugin_discovery_contract.py tests/contracts/test_diagnostics_preflight_contract.py tests/package
```

Add focused integration or CLI contract paths to the targeted command once the
executor adds them.

Final PR-preparation commands:

```sh
make validate-pr
make test-summary
```

`make validate-pr` remains the required PR gate. `make test-summary` should be
run during PR preparation so the PR body can report suite-level evidence.

## Handoff Notes For `loom_phase_executor`

- Safe implementation slices:
  - Add any reusable summary/diagnostics helpers before CLI wiring.
  - Add metadata-only `plugins list` and its tests before explicit load/check
    behavior.
  - Add `plugins check` over recipe/codec scratch registries and listing-only
    groups before preflight integration.
  - Add preflight request/model/check changes after CLI behavior is stable.
  - Finish with package/import-boundary tests and targeted validation.
- Tests to run with each slice:
  - Summary helpers: plugin unit tests and package API/import tests.
  - CLI list/check: CLI unit tests plus JSON contract tests.
  - Preflight: diagnostics unit tests plus preflight contract tests.
  - Import safety: package import-boundary tests and CLI help tests.
- Decisions the executor must not revisit:
  - Default list behavior is metadata-only.
  - Loading/checking is explicit and trusted-code only.
  - Recipes and codecs are the only registry-ready groups in this phase.
  - Artifact-store backends are metadata-only and not run-ready in Stage 14.
  - Provenance persistence is out of scope.
  - No real third-party plugin packages or optional service dependencies.
- Conditions that require stopping for the manager:
  - Existing plugin result records cannot support safe CLI/preflight summaries
    without a public result-model change that affects later phases.
  - Adding preflight plugin selectors requires a config/request contract wider
    than the selected plugin diagnostics boundary.
  - CLI check semantics cannot be made deterministic without loading
    listing-only future groups.

## Refinement And Review Budget Status

- Phase planning draft: completed.
- Phase planning refinement: completed for the expanded path.
- Phase implementation refinement: unused; one pass remains available for the
  expanded-path implementation or for targeted validation/review blockers.
- PR body draft/refine: unused until PR preparation.
- PR review: unused until the manager or reviewer consumes the single review
  pass.
- Blocker resolution: 0/3 used.

## Completion Notes

- Draft plan: completed in
  `docs/roadmap/stage-14/phases/plugin-cli-preflight-summaries.md`.
- Final phase execution plan: completed and ready for implementation handoff.
- Implementation summary: pending.
- Implementation validation: pending.
- PR preparation: pending.
- Stack maintenance: root phase targets `develop`; no predecessor branch exists
  and no retarget or rebase is needed at planning time.
- Remaining blockers: none for implementation handoff.
