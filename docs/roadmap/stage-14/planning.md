# Roadmap Stage 14 Planning: Plugin Discovery

## Metadata

- Roadmap stage: v14
- Source roadmap: `docs/roadmap.md`
- Previous version status: `docs/roadmap/stage-13/planning.md` is final
  planning confirmed and `docs/roadmap/stage-13/implementation-plan.md` has
  passed its plan quality gate. Stage 14 planning can treat Stage 13 provider
  and sweep-plugin compatibility assumptions as design inputs, but
  implementation-plan drafting and phase execution must recheck which Stage 13
  APIs have actually landed before depending on them.
- Planning artifact status: confirmed after targeted artifact-store backend addendum
- Current discussion stage: final planning confirmation complete after artifact-store backend addendum
- Stage gates:
  - Roadmap framing: confirmed
  - Intent discovery: confirmed
  - Capability triage and candidate functional requirements: confirmed
  - Functionality agreement review: confirmed
  - Functionality and behavior confirmation: confirmed
  - Context compaction/reset checkpoint: completed by recorded checkpoint; design pass completed after resume
  - Design agreement review: completed by recorded design pass
  - Design safety review: passed
  - Examples and validation strategy: confirmed
  - Phase shaping: confirmed
  - Implementation readiness: pass
  - Handoff: confirmed; implementation plan drafted and quality gate passed
- Related implementation plan:
  `docs/roadmap/stage-14/implementation-plan.md`
- Related feature docs:
  - `docs/features/plugins.md`
  - `docs/features/config.md`
  - `docs/features/io.md`
  - `docs/features/execution.md`
  - `docs/features/remote-stores.md`
  - `docs/features/cli.md`
  - `docs/features/preflight.md`
  - `docs/features/provenance.md`
  - `docs/features/testing.md`
- Blockers:
  - None for implementation-plan drafting. The implementation plan still must
    run the normal plan quality gate before phase execution.
- Carry-forward constraint:
  - Stage 14 must not promise artifact-store backend loading or registration
    before the Stage 15 backend descriptor/registry contract exists.

## Source Evidence

| Source | Relevant content | Used for | Notes |
| --- | --- | --- | --- |
| `docs/roadmap.md` | V14 goal is explicit plugin discovery for trusted installed packages without import-time side effects. | roadmap scope | Baseline stage is plugin discovery, not plugin marketplace or concrete integrations. |
| `docs/roadmap.md` | Implement known entry point group constants, `PluginRecord`, `PluginLoadResult`, generic listing/loading, recipe and codec loading, later extension loading after registries exist, provenance summaries, `loom plugins list`, `loom plugins check`, preflight checks, and fake entry point tests. | candidate capabilities | Some listed groups are ready for listing now but not necessarily registration now. |
| `docs/roadmap.md` | Defer marketplace behavior, automatic installation, dependency solving, remote indexes, sandboxing, third-party CLI command injection, and concrete Prefect/MLflow/DVC/W&B/OpenTelemetry/cloud/notification integrations. | scope boundaries | Stage 14 should create discoverability surfaces for future adapters, not ship service behavior. |
| `docs/features/plugins.md` | `loom.plugins` is an optional coordination layer above subsystem registries. Discovery is explicit, opt-in, and adapter-shaped. | package ownership | Strong source for module placement and dependency direction. |
| `docs/features/plugins.md` | Recommended files are `src/loom/plugins/__init__.py`, `entrypoints.py`, and `errors.py`; stable exports include records, generic loading, recipe loading, codec loading, and plugin errors. | likely source layout | Design pass keeps the package small while allowing adapter split files if needed for import boundaries. |
| `docs/features/plugins.md` | Entry point groups include `loom.recipes`, `loom.codecs`, future `loom.sources`, future `loom.executors`, and future `loom.event_sinks`; CLI command injection is not initially supported. | group policy | Roadmap adds artifact-store backends and run exporters to the group list. |
| `docs/features/plugins.md` | Strict mode raises on duplicate/load/validation failures; best-effort mode records failures. Duplicate entry point names and duplicate runtime keys are errors by default. | failure semantics | Needed for deterministic tests, provenance, and preflight behavior. |
| `docs/features/config.md` | Recipe catalogs are explicit, trusted, and instance-local when supplied; optional entry point discovery is deferred to plugins. | recipe integration | Recipe plugin loading should populate supplied catalogs and should not make config imports discover plugins. |
| `docs/features/io.md` and `src/loom/io/codecs/registry.py` | `CodecRegistry` exists and registers codec objects by `codec.key`; local JSON/text/bytes codecs are built in. | codec integration | Codec plugin loading can register instances/classes/factories into a supplied registry. Current registry has no `replace` option. |
| `src/loom/config/recipes/catalog.py` | `RecipeCatalog.register(name, recipe, replace=False)` validates names and rejects duplicates unless replacement is explicit. | recipe duplicate policy | Entry point name can be the recipe name. |
| `src/loom/pipeline/runtime/capabilities.py` | `ExecutorDescriptorRegistry` exists as an immutable explicit registry of executor descriptors, but there is no general executor implementation registry. | executor plugin boundary | Design pass keeps executor implementation plugins listing/check-only and avoids accepting raw executor factories in Stage 14. |
| `src/loom/pipeline/executors/base.py` | `Executor` is a small stage-execution protocol with `name` and `execute(StageExecutionRequest)`. | executor contract readiness | A plugin-loadable executor likely needs a factory/descriptor boundary, not just a raw executor instance. |
| `src/loom/io/sources/base.py` and `src/loom/io/sources/__init__.py` | `DataSource` protocol and local source exist; no source registry is present. | source plugin boundary | Registration is not ready without adding a source registry or deferring source loading. |
| `src/loom/pipeline/stores/artifact_store.py` | `ArtifactStore` and run/stage artifact store protocols exist, but remote/external store registry contracts are Stage 15 work. | artifact-store plugin boundary | Artifact-store backend loading likely needs a Stage 15 handler/factory/capability contract rather than registering arbitrary store instances in Stage 14. |
| `src/loom/pipeline/execution/runner.py` | `PipelineRunner` currently receives an `ArtifactStoreFactory` over a local artifact root and defaults to `LocalArtifactStore`. | artifact-store internal hook | Future plugin-backed stores need a store-owned resolution layer that builds a run-scoped store from explicit config/run context, not ad hoc plugin loading inside runner lifecycle. |
| `src/loom/artifacts.py` | `ArtifactRef` has a strict known-field schema and a plain `metadata` mapping. | artifact metadata compatibility | Stage 14 should not encode remote/backend semantics into plugin records; Stage 15 must decide compatible typed records or schema evolution. |
| `docs/roadmap/stage-12/planning.md` and `implementation-plan.md` | Stage 12 defines minimal `RunExporter`/`RunImporter` protocol assumptions and explicitly leaves plugin dispatch to Stage 14. | exporter touchpoint | Stage 14 must recheck landed Stage 12 APIs before loading exporters. |
| `docs/roadmap/stage-13/planning.md` and `implementation-plan.md` | Stage 13 leaves future provider/optimizer adapters for Stage 14 plugin discovery while keeping concrete Optuna-like adapters out of core. | future adapter touchpoint | Plugin discovery should not become sweep-provider semantics unless Stage 13 contracts have landed. |
| `docs/roadmap.md` v15/v16 | Stage 15 will define external/remote artifact-store registry and handler hooks compatible with Stage 14 plugin loading; Stage 16 keeps optional backend dependencies outside core. | future-roadmap compatibility | Stage 14 should avoid locking store plugin objects before the store capability model exists. |
| `docs/roadmap/stage-15/planning.md` | Stage 15 planning treats `loom.artifact_store_backends` as a Stage 14 metadata namespace and expects Stage 15 to define backend config, handler/factory, capability, fake-backend, preflight, and metadata-only ref contracts. | artifact-store backend addendum | Confirms Stage 14 should reserve the group and diagnostics, while Stage 15 owns the loadable backend target shape. |
| `docs/features/remote-stores.md` | Remote backends should be plugins, core can include the protocol, local implementation, backend registry, configuration handoff, redaction helpers, and test fakes, while plugins provide concrete stores, preflight checks, and config schemas. | artifact-store backend addendum | Strong evidence that the future plugin target should be a backend descriptor/factory over a store-owned registry, not a raw store object. |
| `docs/roadmap.md` v19 and `docs/features/plugins.md` | Event sink plugin listing can exist before `RuntimeEvent` and `EventSinkRegistry`, but registration waits until v19 contracts are stable. | event-sink boundary | Listing without loading is safe; registration/loading is deferred unless fake registry tests are explicitly selected. |
| `docs/features/preflight.md` | Preflight should verify plugin entry points, requested executor/artifact-store plugins, requested codecs, and plugin-provided config schema without executing runs. | preflight behavior | Stage 14 can add plugin checks over explicit discovery/load results. |
| `docs/features/testing.md` | Tests should prove plugins are not loaded on import, use fake entry points, and protect import boundaries. | validation strategy | Import-boundary tests are central acceptance criteria. |
| `docs/structure.md` and `docs/GLOSSARY.md` | Keep `loom` domain-neutral, keep CLI outermost, and distinguish registries, records, artifacts, run exporters, run catalogs, and authority. | vocabulary and boundaries | Plugin APIs should remain generic and optional-dependency light. |

## Exploration Coverage

| Area | Files or patterns checked | Findings | Gaps |
| --- | --- | --- | --- |
| Roadmap and workflow docs | `.codex/workflows/roadmap-stage-planning.md`, `docs/roadmap.md` v14/v15/v16/v19, `.codex/templates/roadmap-stage-planning.md`, functionality/design prompts | Workflow requires staged interactive planning, a source-backed briefing, agreement queues, design-safety review, examples, validation, phase shaping, and no implementation-plan draft until final confirmation. | None for startup. |
| Feature docs | `plugins.md`, targeted `config.md`, `io.md`, `cli.md`, `preflight.md`, `provenance.md`, `testing.md`, `remote-stores.md`, `loom.md`, `structure.md`, `GLOSSARY.md` | Plugin docs define explicit opt-in discovery, record/result/error models, strict/best-effort load policy, recipe and codec integration, future source/executor/event sink boundaries, provenance, CLI commands, and tests. | Implementation planning must still recheck the exact landed Stage 12/13 APIs before promising exporter/provider loaders. |
| Source and tests | `src/loom/config/recipes/catalog.py`, `src/loom/io/codecs/registry.py`, `src/loom/io/sources/*`, `src/loom/pipeline/runtime/capabilities.py`, `src/loom/pipeline/stores/artifact_store.py`, CLI registration, contract/unit tests for recipes, codecs, executors, preflight, and import boundaries | Recipe and codec registries exist; executor descriptor registry exists; source registry, artifact-store backend registry, event sink registry, and plugin package do not exist. | Need exact landed exporter/importer APIs and any Stage 13 sweep-provider APIs before implementation planning locks plugin loaders for those contracts. |
| Prior or adjacent plans | Stage 12 planning/implementation plan and Stage 13 planning/implementation plan | Stage 12 and Stage 13 both intentionally leave plugin dispatch/loading to Stage 14 while keeping their own protocols plugin-free. | Stage 12 and Stage 13 phases may be pending or partially landed, so Stage 14 implementation must revalidate concrete APIs. |
| Targeted artifact-store backend addendum | `docs/roadmap.md` v15/v16, `docs/roadmap/stage-15/planning.md`, `docs/features/remote-stores.md`, current `ArtifactStore`, `ArtifactRef`, `LocalArtifactStore`, runner artifact-store factory, and preflight artifact checks | Current code has local artifact-store runtime protocols but no backend descriptor/registry/config/capability contract. Stage 15 is the owning stage for that contract. | Stage 14 implementation must not create a provisional artifact-store backend loader or import backend targets during ordinary plugin checks. |

## Roadmap Extraction

Baseline roadmap outcome:

- Trusted installed packages can advertise Loom extension points through known
  Python entry point groups.
- Loom can list advertised entry points without importing plugin targets.
- Loom can explicitly load selected plugin targets through
  `importlib.metadata` and report loaded objects, failures, duplicates, package
  names, versions, groups, and entry point values in structured records.
- Recipe plugins can populate supplied `RecipeCatalog` instances.
- Codec plugins can populate supplied `CodecRegistry` instances.
- Source, executor, artifact-store backend, run exporter, and event sink plugin
  loading is available only where the corresponding registry or protocol is
  stable enough; listing can come first when loading would be premature.
- `loom plugins list`, `loom plugins check`, and preflight plugin checks expose
  discovery and load diagnostics without mutating runtime state unexpectedly.
- Importing `loom` or running help commands does not load arbitrary third-party
  plugin code.

Prerequisites:

- Existing recipe catalog and codec registry contracts.
- `importlib.metadata` from the standard library.
- Existing CLI command registration pattern.
- Existing diagnostic/preflight result patterns.
- Stage 12 `RunExporter` protocol if exporter loading is included beyond
  entry point listing.
- Stage 13 sweep-provider APIs if provider plugin loading is considered later.
- Stage 15 artifact-store registry/handler contracts and Stage 19 event-sink
  registry contracts for full registration of those extension types.

Primary feature docs:

- `plugins.md`
- `config.md`
- `io.md`
- `execution.md`
- `remote-stores.md`
- `cli.md`
- `preflight.md`
- `provenance.md`
- `testing.md`

Deferred or out-of-scope roadmap work:

- Plugin marketplace behavior.
- Automatic installation, upgrades, dependency resolution, or version solving.
- Remote plugin indexes or trust scoring.
- Python sandboxing for plugin code.
- Third-party command injection into the core Loom CLI.
- Concrete Prefect, MLflow, DVC, W&B, OpenTelemetry, cloud, notification, or
  optimizer integrations.
- Loading plugin targets as a side effect of `import loom`, `loom --help`, or
  other unrelated commands.
- Making plugin discovery the only path to configure extensions; explicit
  programmatic registries remain first-class.

Future-roadmap touchpoints:

- Stage 13 sweep providers and optimizers can later be loaded through plugin
  discovery if their protocol shape is stable and kept plugin-free in core.
- Stage 15 external artifact-store interfaces need store backend entry point
  groups without Stage 14 prematurely defining remote-store semantics.
- Stage 16 optional backend packages need plugin packaging and tests that keep
  cloud or service dependencies outside the default install.
- Stage 19 runtime events and event sinks need listing now and registration
  later after `RuntimeEvent` and `EventSinkRegistry` stabilize.
- Future MLflow/DVC/W&B/OpenTelemetry integrations should plug into exporter,
  artifact-store, event-sink, or provider contracts rather than changing core
  plugin discovery.

Compatibility obligations:

- Entry point group names must be stable and documented.
- Listing must be deterministic and must not import plugin targets.
- Loading must be explicit, structured, and testable with fake entry points.
- Failure and duplicate diagnostics must include enough plugin metadata to
  debug package/version/group/name/value conflicts.
- Plugin provenance summaries must be plain-data-compatible and must not
  serialize loaded Python objects or secrets.
- Registries remain explicit and caller-supplied where possible.
- Optional dependency imports stay inside plugin target loading or external
  packages, not default Loom imports.

## Stage Briefing

What this stage is:

- V14 is Loom's explicit plugin discovery layer. It gives trusted installed
  packages a standard way to advertise extension points, lets Loom inspect those
  advertisements without importing plugin code, and provides explicit loading
  helpers that register supported extension objects into caller-supplied
  registries.

Why this stage exists:

- Earlier stages deliberately kept extension points explicit and plugin-free:
  recipes register into catalogs, codecs register into codec registries,
  exporters stay protocol-shaped, sweep providers stay adapter-shaped, and
  future stores/event sinks wait for stable contracts. V14 is where those
  extension points become discoverable in a deterministic way without turning
  import or CLI startup into arbitrary third-party code execution.
- This stage closes a practical downstream packaging gap: a project can install
  a Loom extension package and then explicitly ask Loom to list, check, or load
  its recipes/codecs instead of manually importing that package in every setup
  script.

Impacted or linked work:

- `loom.config.recipes` supplies `RecipeCatalog`; plugin loading should populate
  supplied catalogs and preserve existing explicit registration behavior.
- `loom.io.codecs` supplies `CodecRegistry`; plugin loading can load codec
  instances, no-arg classes, or factories and register by runtime codec key.
- `loom.pipeline.runtime` has executor descriptor registries but not a general
  executor implementation registry, so executor plugins need careful scoping.
- `loom.io.sources` has source protocols but no source registry; source plugin
  listing is likely ready before registration is.
- `loom.pipeline.stores` has artifact-store protocols, but external/remote
  store handler registries are Stage 15 work; artifact-store backend entry
  points should not predefine the Stage 15 contract.
- Stage 12 exporter/importer protocols and Stage 13 sweep providers are likely
  plugin consumers, but implementation planning must recheck concrete landed
  APIs before committing to loaders.
- Stage 19 event sinks are a future consumer; Stage 14 can list
  `loom.event_sinks`, but target loading and registration should wait for event
  contracts unless a fake/provisional registry is explicitly selected for tests.
- `loom.cli` should expose thin plugin inspection/check commands over the
  Python APIs.
- `loom.diagnostics.preflight` can use discovery/load results to report plugin
  availability and duplicate/failure diagnostics.
- `loom.provenance` can include plain plugin summaries when plugins are loaded
  for a run.

Likely public surfaces and durable artifacts:

- Public constants for known entry point groups, probably including recipes,
  codecs, sources, executors, artifact-store backends, run exporters, event
  sinks, and possibly sweep providers only if Stage 13 has a stable provider
  contract.
- `PluginRecord`, load/failure/duplicate summary records, `PluginLoadResult`,
  and plugin-specific error types.
- `list_entry_points(...)` and `load_entry_points(...)` generic helpers.
- `load_recipe_entry_points(...)` and `load_codec_entry_points(...)` registry
  adapters as the first fully supported loading helpers.
- Possibly listing-only helpers for sources, executors, store backends, run
  exporters, and event sinks where registration contracts are not yet stable.
- Plain-data conversion for plugin records and load summaries for CLI,
  preflight, and provenance.
- `loom plugins list` and `loom plugins check` result schemas and human output.
- Preflight check IDs for plugin discovery, plugin load failures, duplicate
  plugin names/runtime keys, and requested plugin availability.

Structure rationale:

- The stage belongs in a new `src/loom/plugins/` package because plugin
  discovery sits above subsystem registries and below CLI/application setup. It
  should not live inside config, I/O, pipeline, stores, or CLI because those
  subsystems own runtime semantics, while plugins only coordinate discovery and
  explicit loading.
- Recipe and codec loading are the natural first usable registrations because
  their registries already exist and are domain-neutral. Source, executor,
  artifact-store, exporter, and event-sink groups should be planned as stable
  group names and listing/check behavior first, with registration added only
  when the target registry/protocol is stable.
- Strict and best-effort modes are both needed: reproducible runs need fail-fast
  loading, while inspection commands need to report all installed problems in
  one pass.

Visible assumptions, risks, and constraints:

- Installed plugin code is trusted Python code; loading an entry point imports
  the target package. Stage 14 should document this rather than pretending to
  sandbox plugin code.
- The roadmap lists more extension groups than the current code can fully
  register. Planning needs to distinguish group constants and listing from
  target loading and registry mutation.
- Public extension contracts are at different maturity levels. `Executor` and
  `ArtifactStore` protocols exist, Stage 12/13 exporter/provider contracts may
  be planned or partially landed, and `EventSink` is explicitly future work.
  Stage 14 should include a plugin-readiness audit and minimal interface
  cleanup boundary so later plugin loaders do not have to infer object shapes,
  but it should not pull Stage 15 store semantics or Stage 19 event semantics
  into plugin discovery.
- The feature doc recommends `replace=True` options for some loaders, but the
  current `CodecRegistry` does not support replacement. Planning must decide
  whether to add replacement support to registries, omit `replace` for codecs,
  or treat replacement as future work.
- Plugin provenance is useful but can couple `loom.plugins` to provenance if
  implemented carelessly. Safer default: plugin records/results expose
  plain-data summaries; provenance owns where those summaries are persisted.
- CLI/plugin checks must not load every plugin by default. Loading should be
  opt-in for list/debug commands and explicit for check/preflight paths.
- Duplicate handling must be deterministic across Python versions and package
  metadata order.
- Entry point objects in tests should be fake or monkeypatched; validation must
  not depend on installed third-party packages, network access, or service SDKs.

User clarification questions and resolved answers:

- User asked what plugins are, why Loom needs them, and whether Stage 14 should
  instead be centered on callbacks/hooks/event sinks. Resolved clarification:
  plugins are the packaging, discovery, and explicit loading mechanism for
  trusted installed extension packages; callbacks, hooks, event sinks, codecs,
  recipes, exporters, stores, executors, and providers are possible extension
  contracts that plugins may supply. Stage 14 should not invent callback or
  event semantics by itself. It should make extension packages discoverable and
  loadable in a controlled way, while event-sink runtime behavior remains owned
  by the later reliability/runtime-event stage unless the roadmap scope is
  explicitly changed.

## User Intent

Target audience:

- Confirmed priority order:
  1. Downstream package authors defining Loom entry points.
  2. Project setup code and users explicitly loading recipes/codecs.
  3. Operators using `loom plugins list`, `loom plugins check`, and preflight
     to validate environments.
- Confirmed planning priority favors fundamentals for downstream extension
  packages and core Loom structure first: package authors and project setup
  code should get stable discovery/loading interfaces, while operators get
  inspection/check diagnostics as a supporting workflow.

User-visible outcome:

- Confirmed. Users can run explicit plugin listing/check commands and project
  setup code can explicitly load recipe and codec entry points into supplied
  registries. Less-stable future integration groups get structure and
  discoverability without concrete service behavior.

Success criteria:

- Confirmed:
  - Plugin discovery is deterministic, import-safe, and immediately useful for
    recipe and codec plugins.
  - Stage 14 defines interfaces and structure that later integrations can use,
    but does not ship concrete integrations.
  - `loom plugins list`, `loom plugins check`, and preflight support
    environment and debugging visibility.

Non-goals:

- Confirmed:
  - No plugin marketplace behavior.
  - No automatic plugin installation, upgrade, version solving, dependency
    resolution, or remote plugin index.
  - No Python sandboxing for plugin code.
  - No third-party command injection into the core Loom CLI.
  - No concrete MLflow, DVC, W&B, OpenTelemetry, cloud, notification,
    event-sink, callback, hook, optimizer, or service integration.

Constraints:

- Confirmed:
  - Keep `loom` domain-neutral.
  - Keep plugin discovery explicit and trusted.
  - Loading plugins is trusted code execution and must happen only through
    explicit APIs or commands, never import/help side effects.
  - Do not add heavyweight runtime dependencies.
  - Preserve source-tree and import boundaries from `docs/structure.md`.

## Workflow Stage Readback

Record an explicit narrative readback before or after any context checkpoint so
later passes can resume without rediscovering what was already confirmed.

Roadmap framing locked decisions:

- Confirmed: Stage 14 stays centered on plugin discovery. Plugins are the
  packaging, discovery, and explicit loading mechanism for trusted installed
  extension packages. Callback, hook, and event-sink behavior is not pulled
  into Stage 14 as runtime semantics; event sinks remain a future consumer of
  plugin discovery after stable runtime event contracts exist.
- Confirmed default framing: Stage 14 is an explicit, deterministic,
  import-safe plugin discovery layer for trusted installed packages, with first
  usable registration paths for recipes and codecs and carefully scoped
  listing/loading boundaries for less-stable future extension points.

Intent discovery locked decisions:

- Confirmed priority: focus on plugin-discovery fundamentals now, with
  interfaces and structure that support specific integration layers later.
  Stage 14 should not ship concrete service integrations or move callback,
  event-sink, remote-store, optimizer, or exporter semantics into plugin
  discovery itself.
- Confirmed target audience priority: downstream package authors first, project
  setup/users second, and operators validating environments third.
- Confirmed success criteria, non-goals, and constraints: deterministic and
  import-safe discovery, immediate recipe/codec usefulness, inspection/check
  diagnostics, no concrete integrations or marketplace/install/sandbox behavior,
  and explicit trusted-code loading only.
- User added that Stage 14 should consider whether the public interfaces and
  protocols for `Executor`, `ArtifactStore`, `RunExporter`, `SweepProvider`,
  and `EventSink` need cleanup, refinement, or revision to be supportable as
  plugins. This is now treated as a capability-triage/design input: audit
  plugin-readiness for those extension contracts and include minimal cleanup
  only where a target contract is already in scope and stable enough, while
  deferring unstable runtime semantics to their owning roadmap stages.

Capability triage and candidate-functional-requirement readback:

- Confirmed. Included capabilities: plugin group constants; structured
  records/results/errors; generic listing and explicit loading; recipe and
  codec loaders; CLI list/check; preflight diagnostics; provenance summaries;
  import-safety tests; listing/check-first support for future groups; and a
  plugin-readiness audit for `Executor`, `ArtifactStore`, `RunExporter`,
  `SweepProvider`, and `EventSink`. Deferred capabilities: concrete
  integrations, service behavior, marketplace/install/sandbox behavior, and
  registration loaders for extension contracts that are not stable.

Functionality-agreement readback:

- Confirmed. The requirements lock deterministic plugin discovery,
  metadata-only listing by default, explicit loading only, recipe and codec
  loaders, duplicate failures without codec replacement support,
  selected-group CLI/preflight checks, plain-data plugin summaries, import
  safety, future group listing/check support, and plugin-readiness audits for
  extension contracts.

Functionality and behavior confirmation readback:

- Confirmed. Included behavior is explicit plugin listing/loading
  infrastructure, recipe and codec loaders, future-group listing/check support,
  CLI list/check, preflight diagnostics, plugin summaries, import-safety tests,
  and plugin-readiness audits. Defaults are metadata-only listing, explicit
  loading, strict duplicate failures, no codec replacement support, stable
  contracts loadable only after readiness review, and unstable contracts
  listing/check-only. Deferrals and non-goals remain concrete integrations,
  marketplace/install/version-solving/sandbox behavior, third-party CLI
  injection, and future-stage runtime semantics.

Design-agreement follow-up:

- Completed. The design pass resolved the implementation shape and
  design-agreement queue from the confirmed functionality and behavior baseline
  without reopening scope. The locked design keeps plugin discovery in
  `loom.plugins`, makes recipe and codec loading the first concrete registry
  adapters, treats future groups as stable metadata namespaces with
  listing/check-first behavior, and records plugin-readiness classifications for
  `Executor`, `ArtifactStore`, `RunExporter`, `SweepProvider`, and `EventSink`.

Design-safety review follow-up:

- Completed. The safety pass upheld DAQ-1 through DAQ-9 and found no blocker
  requiring return to user discussion. One planning revision was applied:
  artifact-store plugin metadata should use the backend-oriented group
  `loom.artifact_store_backends`, not a group name that implies raw
  `ArtifactStore` instance loading. The review also reaffirmed that executor,
  artifact-store backend, run-exporter, sweep-provider, source, and event-sink
  groups remain listing/check-first unless their owning contracts define
  registry ownership, factory/config shape, duplicate policy, and diagnostics.

Targeted artifact-store backend design addendum:

- Completed after user requested a narrower pass over artifact-store backend
  structure, strictness, internal hooks, future maintainability, and
  upgradability. The addendum locks a stricter Stage 14 boundary:
  `loom.artifact_store_backends` is a stable advertisement and diagnostics
  namespace only. Stage 14 must not export an artifact-store backend loader,
  accept raw `ArtifactStore` instances or factories as plugin contracts, mutate
  a store registry, or claim that advertised backend plugins are usable for a
  run.
- Recommended future shape for Stage 15: a store-owned backend descriptor or
  factory contract under `loom.pipeline.stores`, loaded into an explicit
  caller-supplied backend registry after Stage 15 defines backend kind, URI
  schemes, config validation, capability records, redaction, preflight hooks,
  operation/failure records, and run-context store construction. `loom.plugins`
  should later adapt entry points into that supplied registry; it should not
  own artifact-store runtime semantics.
- Strict behavior locked by this addendum: future-group checks are
  metadata-only by default; duplicate advertised backend names fail
  deterministically; no unknown backend capability is treated as supported; and
  any future import-only check of an artifact-store backend target must be
  labelled as importability only, not registration or run-readiness.

Examples, validation, and phase-shaping follow-up:

- Completed. The examples and validation matrix are confirmed as fake-entry
  point, fake-registry, import-boundary, CLI, preflight, provenance-summary,
  and readiness-documentation coverage. Phase shaping is confirmed as four
  reviewable phases: generic plugin records/discovery, recipe and codec
  adapters, CLI/preflight/provenance summaries, and future-group readiness.

Final planning confirmation:

- Completed. The user explicitly asked to run design-safety review,
  examples/validation confirmation, phase shaping, and final planning
  confirmation. The planning artifact is ready to serve as the source for the
  Stage 14 implementation-plan draft.

## Stage Readbacks

| Stage | Locked decisions | Defaults | Open questions | Next focus |
| --- | --- | --- | --- | --- |
| Roadmap framing | Stage remains plugin discovery, not callback/hook/event-sink runtime semantics | Treat recipes/codecs as first usable loaders; treat unstable groups as listing/check-first | None unless reopened | Intent discovery |
| Intent discovery | Focus on fundamentals, interfaces, and structure for future specific integration layers; target downstream package authors first, project setup/users second, operators third; no concrete integrations; explicit trusted-code loading only | Recipe/codec usability plus inspection/check diagnostics; future groups listing-first | None unless reopened | Capability triage |
| Capability triage and candidate functional requirements | Include plugin discovery fundamentals, recipe/codec loaders, diagnostics, provenance summaries, import-safety tests, future group listing/check, and plugin-readiness audit; defer unstable registration loaders and concrete integrations | Future groups are listing/check-first unless contracts are stable | None unless reopened | Functionality agreement |
| Functionality agreement review | Deterministic discovery, metadata-only listing, explicit loading, recipe/codec loaders, duplicate failures, selected checks, plain-data summaries, import safety, future group listing/check, plugin-readiness audits | No codec replacement support; `loom.plugins` exposes summaries but does not persist provenance | None unless reopened | Behavior confirmation |
| Functionality and behavior confirmation | Included/default/failure/deferred behavior confirmed | Metadata-only list by default; explicit load/check; duplicate failures; no codec replacement; stable contracts can load, unstable contracts listing/check-only | None unless reopened | Context checkpoint |
| Context compaction/reset checkpoint | Checkpoint recorded in this artifact; design pass has now resumed and completed | Confirmed functionality and behavior baseline remained stable | None | Design agreement complete |
| Design agreement review | `loom.plugins` owns discovery/loading coordination; recipe and codec adapters are loadable now; future groups are stable listing/check namespaces; unstable contract loaders are deferred with revisit triggers; targeted artifact-store addendum confirms backend group is metadata-only in Stage 14 | Keep generic discovery import-light; use explicit caller-supplied registries; no codec replacement; no provenance persistence in plugins; no artifact-store backend loader before Stage 15 | None | Design-safety review |
| Design safety review | Passed; DAQ-1 through DAQ-9 upheld with artifact-store group spelling revised to `loom.artifact_store_backends`; targeted DAQ-10 addendum upheld stricter list/check-only backend behavior | Keep future groups listing/check-first unless owning contracts are stable; artifact-store backend checks are not run-readiness checks | None | Examples/validation confirmation |
| Examples and validation strategy | Confirmed fake-entry-point, fake-registry, import-boundary, CLI, preflight, provenance-summary, and readiness-documentation coverage | No installed services, real third-party packages, network, or optional SDKs in core tests | None | Phase shaping |
| Phase shaping | Four phases confirmed: generic records/discovery; recipe/codec adapters; CLI/preflight/provenance summaries; future group readiness | Keep phase 4 from implementing Stage 15/19 runtime semantics | None | Implementation readiness |
| Implementation readiness | Passed for planning; normal implementation-plan quality gate still required before phase execution | Carry accepted risks and revisit triggers into implementation plan | None | Handoff |
| Handoff | Final planning confirmed after targeted artifact-store backend addendum; implementation-plan drafting may begin from this artifact | Do not create phase execution plans until the implementation plan passes its quality gate | None | Implementation-plan draft |

## Capability Triage

| Capability | Decision | Rationale | Notes |
| --- | --- | --- | --- |
| Known entry point group constants | include | Roadmap baseline and needed for all downstream extension packages. | Must include stable group strings and docs. |
| Plugin records, load results, failures, duplicates, and errors | include | Roadmap baseline and required for deterministic CLI/preflight/provenance. | Records should be plain-data-compatible without serializing objects. |
| Generic entry point listing through `importlib.metadata` | include | Enables inspection without loading targets. | Must not import plugin target modules. |
| Generic explicit entry point loading | include | Needed by specialized registry loaders and check commands. | Needs strict and best-effort modes. |
| Recipe plugin loading into supplied catalogs | include | Existing `RecipeCatalog` is ready and feature docs explicitly defer recipe entry point discovery here. | Entry point name likely wins as recipe name. |
| Codec plugin loading into supplied registries | include | Existing `CodecRegistry` is ready and plugin docs define accepted codec shapes. | Replacement policy remains a functionality/design question because `CodecRegistry.register` lacks `replace`. |
| Plugin-readiness audit for extension contracts | include | User explicitly raised whether `Executor`, `ArtifactStore`, `RunExporter`, `SweepProvider`, and `EventSink` interfaces/protocols need cleanup before they can be provided as plugins. | Audit contracts and define loader-readiness status; implement only minimal cleanup for stable contracts, not future-stage semantics. |
| Source plugin registration | defer | Roadmap names sources, but current source registry does not exist. | Listing/check can be included; registration waits for source registry design unless a stable registry lands before implementation planning. |
| Executor plugin registration | defer by default | Roadmap names executors; current executor descriptor registry exists, but no full executor implementation registry exists. | Audit whether descriptor/factory loading is stable; otherwise list/check only. |
| Artifact-store backend plugin registration | defer | Stage 15 owns external/remote store handler registry, backend descriptor/factory shape, config handoff, capability model, and preflight behavior. | Stage 14 includes the `loom.artifact_store_backends` group constant plus metadata/listing diagnostics only; it must not expose a backend loader, accept raw `ArtifactStore` objects/factories as plugin contracts, mutate a store registry, or claim advertised backends are run-ready. |
| Run exporter plugin loading | defer unless stable | Stage 12 defines exporter protocol assumptions, but landed APIs must be rechecked. | Load only if `RunExporter` contract exists and passes plugin-readiness audit. |
| Sweep-provider plugin loading | defer unless stable | Stage 13 defines provider protocol assumptions, but landed APIs must be rechecked. | Load only if `SweepProvider` or equivalent contract exists and passes plugin-readiness audit. |
| Event sink plugin listing | include listing, defer registration | Roadmap explicitly says registration is deferred until v19 runtime-event contracts stabilize. | Avoid target loading by default. |
| Plugin provenance summaries | include | Roadmap baseline and useful for reproducibility. | `loom.plugins` should expose summaries; `loom.provenance` owns persistence. |
| `loom plugins list` | include | Roadmap baseline for user-visible inspection. | Default should list metadata without loading targets. |
| `loom plugins check` | include | Roadmap baseline for diagnostics. | Loads only registry-ready selected groups explicitly; metadata-checks listing-only groups such as artifact-store backends; returns nonzero on requested failures. |
| Preflight plugin checks | include | Roadmap and preflight feature doc baseline. | Should use stable check IDs and structured diagnostics. |
| Concrete third-party integrations | out of scope | Roadmap defers all service/provider implementations. | Keep core dependency-light. |
| Plugin marketplace/install/version solving/sandboxing | out of scope | Roadmap explicitly defers these. | Document trusted installed package model. |
| Third-party core CLI command injection | out of scope | Feature docs reject initial command injection. | Project packages can expose their own console scripts. |

## Functionality Agreement Queue

| ID | Requirement or decision | Depends on | Resolution order | Recommended answer | Why it matters | Why user input is needed | Status |
| --- | --- | --- | --- | --- | --- | --- | --- |
| FRQ-1 | Stage priority and first user-visible outcome | none | 1 | Optimize for plugin-discovery fundamentals: dependable recipe/codec plugin loading, inspection/check diagnostics, and interfaces/structure for future specific integration layers; keep unstable groups listing-first. | Sets the MVP boundary and phase shape. | User confirmed the fundamentals-first priority. | confirmed |
| FRQ-2 | Scope boundary between group constants/listing and registration/loading for unstable extension points | FRQ-1 | 2 | Include stable group constants and listing/check support for all roadmap groups; only ship registration loaders for registries/protocols that exist and are stable. | Prevents Stage 14 from predefining Stage 15/19 contracts. | User confirmed the capability split. | confirmed |
| FRQ-3 | Default discovery/loading behavior | FRQ-1 | 3 | Never discover/load on import or help; list without loading by default; load registry-ready groups only through explicit APIs, `plugins check`, preflight, or caller setup; metadata-check listing-only groups unless an import-only diagnostic is explicitly requested and clearly labelled. | Protects import safety and deterministic runtime behavior. | User confirmed explicit trusted-code loading only; artifact-store addendum tightened listing-only behavior. | confirmed |
| FRQ-4 | Failure and duplicate policy | FRQ-1 | 4 | Strict mode raises; best-effort mode records all safe failures; duplicates are errors by default; replacement only where the target registry explicitly supports it. `CodecRegistry` is not widened in Stage 14, so duplicate codec keys fail. | Affects diagnostics, reproducibility, and registry mutation. | User confirmed no codec replacement support in Stage 14. | confirmed |
| FRQ-5 | CLI and preflight scope | FRQ-1 | 5 | `loom plugins list` lists metadata by default without loading; `loom plugins list --load` explicitly loads registry-ready selected groups/names; `loom plugins check` loads registry-ready selected groups/names, metadata-checks listing-only groups, and exits nonzero on requested failures; preflight checks only plugins requested by config/options or selected capability groups, not every installed plugin by default. | Defines visible command behavior and side-effect boundaries. | User confirmed the default; artifact-store addendum tightened listing-only behavior. | confirmed |
| FRQ-6 | Provenance responsibility | FRQ-1 | 6 | Plugin records/results provide plain summaries; provenance/run code persists them only when a caller actually loads plugins for a run or explicitly saves check/preflight output. `loom.plugins` does not persist provenance itself. | Avoids coupling plugin discovery to run storage. | User confirmed this boundary. | confirmed |
| FRQ-7 | Plugin-readiness boundary for public extension interfaces | FRQ-1, FRQ-2 | 7 | Add a plugin-readiness audit for `Executor`, `ArtifactStore`, `RunExporter`, `SweepProvider`, and `EventSink`; implement minimal cleanup only for stable contracts needed by Stage 14 loaders, and otherwise record listing-only or deferred status with revisit triggers. | Prevents later plugin work from relying on ad hoc object shapes while avoiding premature Stage 15/19 semantics. | User confirmed the boundary. | confirmed |

## Functional Requirements

| ID | Requirement | Depends on | What | Why | Scope | User-visible behavior | System behavior | Capability enabled | Validation idea | Decision/status |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| FR-1 | Entry point group constants | none | Define documented constants for known Loom plugin groups. | Extension packages need stable metadata namespaces. | Recipes, codecs, sources, executors, artifact-store backends, run exporters, sweep providers when available, and event sinks. | Docs and APIs expose canonical group names. | Constants do not load plugins. | Package/API tests and docs checks. | confirmed |
| FR-2 | Plugin record and result model | FR-1 | Define `PluginRecord`, load result, failure, duplicate, and error models. | CLI, preflight, tests, and provenance need structured diagnostics. | Plain-data summaries plus loaded-object references where explicitly loaded. | JSON output can show group/name/value/package/version/status. | Loaded Python objects are never serialized. | Unit tests for validation and `to_dict`. | confirmed |
| FR-3 | Explicit listing and loading | FR-1, FR-2 | List entry points without loading and load selected entry points explicitly. | Discovery must be deterministic and import-safe. | Generic `importlib.metadata` wrapper with filtering and strict/best-effort modes. | `loom plugins list` can show advertised plugins without imports. | Loading occurs only when API/CLI/preflight asks for it. | Fake entry point tests and import-boundary tests. | confirmed |
| FR-4 | Recipe plugin registration | FR-3 | Load recipe entry points into a supplied `RecipeCatalog`. | Makes plugin discovery immediately useful for config recipes. | Entry point name as recipe name; catalog validates object shape. | Project setup can populate catalogs from installed packages. | Registration errors are wrapped with plugin context. | Contract tests with fake recipe entry points. | confirmed |
| FR-5 | Codec plugin registration | FR-3 | Load codec entry points into a supplied `CodecRegistry`. | Lets downstream packages contribute codecs without hard dependencies. | Accept codec instances, no-arg codec classes, or no-arg factories; no registry replacement support in Stage 14. | Project setup can explicitly load codecs. | Runtime `codec.key` owns registry key; duplicates are structured errors. | Contract tests with fake codecs and duplicates. | confirmed |
| FR-6 | Listing/check support for future groups | FR-3 | List and check advertised source, executor, artifact-store backend, run-exporter, sweep-provider, and event-sink entry points without prematurely registering unstable contracts. | Future adapters need stable group names without core lock-in. | Loading/registering only when target contracts exist. Artifact-store backend checks are metadata-only until Stage 15 defines a backend descriptor/registry contract. | Users can see installed future extensions and failure context without being told a future backend is usable for runs. | No target import unless explicitly selected for generic import-only diagnostics; import-only diagnostics are not contract validation or registration. | Fake entry point tests for listing-only groups. | confirmed |
| FR-7 | CLI plugin inspection and check commands | FR-2, FR-3 | Add `loom plugins list` and `loom plugins check`. | Users need debugging and CI-friendly plugin verification. | Thin CLI over plugin APIs with text/JSON output; `list` is metadata-only unless `--load` is supplied; `check` loads registry-ready requested groups/names and metadata-checks listing-only groups. | List is side-effect-light by default; check reports failures, duplicates, and listing-only status. | Exit nonzero on requested check failures; do not claim run-readiness for artifact-store backend entries before Stage 15. | CLI tests with monkeypatched fake entry points. | confirmed |
| FR-8 | Preflight plugin diagnostics | FR-2, FR-3 | Add plugin availability/load/duplicate checks to preflight where requested by config/options or selected capability groups. | Expensive runs should fail early on missing or broken plugins without importing every installed plugin. | Stable check IDs and structured details; no whole-environment plugin scan by default. | Preflight shows plugin-specific pass/warn/fail output. | Does not execute stages or mutate run state. | Preflight unit/contract tests with fake plugins. | confirmed |
| FR-9 | Plugin provenance summaries | FR-2 | Provide plain plugin summaries for loaded plugins. | Reproducibility needs package/version/group/name/load evidence. | Summaries only; persistence owned by provenance/run callers. | JSON/provenance can say which plugins were loaded. | No loaded object serialization or secret dumping. | Unit tests for redaction and summary shape. | confirmed |
| FR-10 | Import-safety guarantees | FR-3 | Prove importing Loom and running help do not discover/load plugin targets. | Core import must stay cheap and side-effect-light. | Package import and CLI help paths. | Users are not surprised by plugin imports. | Plugin APIs are opt-in. | Import-boundary and CLI help tests. | confirmed |
| FR-11 | Extension contract plugin-readiness audit | FR-6 | Review `Executor`, `ArtifactStore`, `RunExporter`, `SweepProvider`, and `EventSink` public contracts for plugin-loadable object shape, factory/config needs, registry ownership, duplicate keys, diagnostics, and future-stage blockers. | Plugin discovery cannot safely support these groups if their public contracts do not say what a plugin supplies. | Audit and minimal cleanup only; concrete service implementations and unstable runtime semantics remain deferred. | Planning and docs show which groups are loadable now, listing-only now, or blocked on later stages. | Implementation plan records per-contract status and tests stable plugin-ready contracts with fakes. | Contract-readiness table plus design-safety review. | confirmed |

## Behavior Baseline

Included functionality:

- Explicit listing/loading infrastructure.
- Entry point group constants for current and future Loom extension groups.
- Structured plugin records, load results, duplicate/failure records, and
  plugin errors.
- Recipe plugin loading into supplied `RecipeCatalog` instances.
- Codec plugin loading into supplied `CodecRegistry` instances without
  replacement support.
- Listing/check support for future groups, including source, executor,
  artifact-store backend, run-exporter, sweep-provider, and event-sink groups.
- Artifact-store backend group behavior is metadata-only in Stage 14; no
  backend loader, registry mutation, raw store-object validation, or
  run-readiness claim is included.
- Plugin-readiness audit for `Executor`, `ArtifactStore`, `RunExporter`,
  `SweepProvider`, and `EventSink`.
- `loom plugins list` and `loom plugins check`.
- Preflight plugin diagnostics for requested plugins/groups.
- Plain-data plugin summaries for provenance consumers.
- Import-safety tests.

User-visible behavior:

- Users run `loom plugins list` to inspect advertised entry points without
  loading target code.
- Users run `loom plugins list --load` or `loom plugins check` to load selected
  registry-ready groups/names and report diagnostics; listing-only groups
  report metadata and deferred-registration status.
- For artifact-store backend entries, Stage 14 commands report advertisement,
  duplicate, package/version, and listing-only status. They do not say a backend
  can be used for a run until Stage 15 defines and registers the backend
  contract.
- Project setup code uses Python helpers to load recipe and codec plugins into
  supplied registries.
- Users can inspect future extension groups even when those groups are
  listing/check-only until their runtime contracts are stable.

Default behavior:

- No plugin discovery or loading on import, help, or unrelated commands.
- `loom plugins list` is metadata-only by default.
- Loading is explicit through Python APIs, `loom plugins list --load`,
  registry-ready `loom plugins check` paths, preflight, or caller setup.
  Listing-only groups such as `loom.artifact_store_backends` are metadata
  checked by default and may only be import-checked with explicit wording that
  no runtime contract was validated.
- Strict loading raises on requested failures; best-effort loading records
  failures and continues where safe.
- Duplicate entry point names and duplicate runtime keys are errors by default.
- Codec plugin loading does not support replacement in Stage 14; duplicate
  runtime codec keys fail.

Failure behavior and diagnostics:

- Load failures, invalid objects, duplicate entry point names, duplicate
  runtime keys, and registration failures include group, name, entry point
  value, distribution name/version when available, runtime key when available,
  target registry, and original exception context.
- CLI/check/preflight outputs use structured diagnostics and return nonzero
  when requested checks fail.
- Artifact-store backend diagnostics fail closed: duplicate advertised backend
  names, missing requested advertisements, unsupported Stage 14 registration,
  and any future unknown capability are not treated as usable defaults.
- Error messages avoid serializing loaded Python objects, callback state,
  credentials, or large object reprs.

Explicit deferrals:

- Source registration waits for a source registry unless one exists and passes
  the plugin-readiness audit.
- Executor registration waits for an explicit descriptor/factory/registry
  contract; Stage 14 audits this and defaults to listing/check-only.
- Artifact-store backend registration waits for Stage 15 store-owned backend
  descriptor/factory, backend registry, configuration handoff, redaction,
  operation/failure records, preflight hooks, and capability contracts. Stage
  14 must not use raw `ArtifactStore` instances or `ArtifactStoreFactory`
  callables as the public plugin target shape.
- Run-exporter loading is included only if the Stage 12 `RunExporter` protocol
  has landed and passes plugin-readiness review.
- Sweep-provider loading is included only if the Stage 13 provider protocol has
  landed and passes plugin-readiness review.
- Event-sink registration and runtime behavior wait for Stage 19 runtime event
  and `EventSinkRegistry` contracts.
- Preflight checks only requested plugin groups or selected capability groups,
  not every installed plugin by default.

Out-of-scope behavior:

- Plugin marketplace behavior.
- Automatic installation, upgrade, dependency solving, version solving, remote
  plugin indexes, or trust scoring.
- Python sandboxing for plugin code.
- Third-party command injection into the core Loom CLI.
- Concrete MLflow, DVC, W&B, OpenTelemetry, cloud, notification, event-sink,
  callback, hook, optimizer, or service integrations.
- Loading plugins as a side effect of `import loom`, help, or unrelated
  commands.

Context compaction/reset checkpoint:

- Checkpoint status: completed by recorded checkpoint
- Notes path: `docs/roadmap/stage-14/planning.md`
- Resume instruction: reload this planning artifact plus
  `.codex/workflows/roadmap-stage-planning.md`,
  `.codex/prompts/roadmap-stage-design-agreement.md`, and relevant source
  files before design-agreement review. Treat the confirmed functionality and
  behavior baseline as stable; do not reopen it unless the user explicitly asks
  or a real design contradiction is found.
- Functionality and behavior reopened after checkpoint: no

## Proposed Implementation Shape

Likely modules or packages:

- `src/loom/plugins/` owns plugin discovery and explicit loading coordination.
- `src/loom/plugins/entrypoints.py` owns known group constants, metadata
  listing, generic explicit loading, duplicate detection, load-result records,
  summary conversion, and a fakeable `importlib.metadata` adapter for tests.
- `src/loom/plugins/errors.py` owns plugin-specific errors.
- Registry adapters may start in `entrypoints.py` for a small phase or split
  into `recipes.py` and `codecs.py` behind package exports if that keeps
  generic discovery from importing subsystem registries unnecessarily.
- `src/loom/cli/plugins.py` should be a thin command module over plugin APIs.
- `src/loom/diagnostics/preflight.py` should call plugin APIs only for
  explicitly requested plugin groups, names, or selected capability groups.

Likely public classes, functions, or protocols:

- Public group values:
  `loom.recipes`, `loom.codecs`, `loom.sources`, `loom.executors`,
  `loom.artifact_store_backends`, `loom.run_exporters`,
  `loom.sweep_providers`, and `loom.event_sinks`. Exact constant names can be
  chosen during implementation, but the group string values are the durable
  public metadata contract.
- Records: `PluginRecord`, `LoadedPlugin`, `PluginFailure`,
  `PluginDuplicate`, and `PluginLoadResult`.
- Errors: `PluginError`, `PluginDiscoveryError`, `PluginLoadError`,
  `DuplicatePluginError`, `InvalidPluginError`, and
  `PluginRegistrationError`.
- Generic helpers: `list_entry_points(...)`, `load_entry_points(...)`, and
  plain-data summary conversion through `to_dict()` or equivalent helpers.
- Registry adapters: `load_recipe_entry_points(...)` and
  `load_codec_entry_points(...)`.
- No public `SourceRegistry`, raw `Executor`, artifact-store backend,
  `RunExporter`, `SweepProvider`, or `EventSink` loader should be promised
  until the corresponding target contract is stable in source.
- Specifically, Stage 14 should not export
  `load_artifact_store_backend_entry_points(...)` or a provisional
  `ArtifactStoreBackend`/`ArtifactStoreBackendRegistry` API. Stage 15 should
  define the store-owned descriptor/factory/registry contract first.

Likely internal helpers:

- `importlib.metadata.entry_points()` normalization that works across Python
  versions and returns deterministic `PluginRecord` ordering.
- Distribution metadata extraction that tolerates missing package/version data.
- Selection filters for group, entry point name, and distribution/package.
- Duplicate detection by `(group, entry point name)` before load and by
  runtime key after registry-specific normalization.
- Object-shape normalization for codec instances, no-arg codec classes, and
  no-arg codec factories.
- Error wrapping that adds group, name, value, distribution, version, runtime
  key when available, and target registry context without serializing loaded
  objects.
- Fake entry point and fake distribution seams for unit/contract tests.

Data flow:

- Caller selects a group plus optional names/packages.
- Generic discovery queries entry point metadata and returns sorted
  `PluginRecord` values without importing targets.
- Optional explicit loading filters records, checks duplicate entry point names,
  calls `entry_point.load()` only for selected records, and returns a structured
  load result.
- Recipe loading registers the loaded object into the caller-supplied
  `RecipeCatalog` using the entry point name as the recipe name.
- Codec loading normalizes the loaded object to a `Codec`, registers it into
  the caller-supplied `CodecRegistry`, and treats `codec.key` as the runtime
  registry key.
- CLI, preflight, and provenance consumers read plain summaries from records or
  load results; persistence stays outside `loom.plugins`.
- Artifact-store backend entries follow only the metadata-listing path in Stage
  14. A user may see that a backend is advertised, but no Stage 14 data flow
  constructs a store, registers a backend, probes credentials, validates URI
  schemes, or feeds the backend into `PipelineRunner`.

Dependency direction:

- `loom.plugins.entrypoints` should depend only on the standard library and
  lightweight Loom error/serialization helpers when needed.
- Registry adapters may import stable public registry/protocol types from
  `loom.config.recipes` and `loom.io.codecs`.
- Config, I/O, pipeline, stores, executor, run, and event modules do not import
  `loom.plugins` and do not discover plugins themselves.
- CLI and diagnostics/preflight are outer callers of plugin APIs.
- `loom.__init__`, help paths, and unrelated commands must not import plugin
  target modules or trigger discovery.
- Artifact-store backend resolution belongs under `loom.pipeline.stores` once
  Stage 15 defines it. Runner, preflight, config, and artifact code should call
  store-owned resolution/registry APIs rather than importing or invoking
  `loom.plugins` directly.

Extension points and flexibility boundaries:

- Plugin discovery owns advertised metadata, explicit trusted-code loading,
  duplicate/failure reporting, and registry-adapter orchestration.
- Subsystem registries own runtime semantics, accepted object shapes, lookup
  keys, replacement policy, and execution behavior.
- Future group constants are public metadata namespaces, not promises that Loom
  can register every advertised object in Stage 14.
- For artifact stores, the public namespace is intentionally backend-oriented.
  It reserves package metadata for future backend descriptors/factories, not
  for open `ArtifactStore` instances, local-root factories, credential-bearing
  clients, or service-specific SDK objects.
- Third-party command injection, marketplace behavior, dependency solving,
  sandboxing, and concrete service integrations remain out of scope.

Generic interface, adapter, or protocol shape:

- The reusable shape is a small adapter function over a caller-supplied
  registry:
  list metadata, explicitly load selected targets, normalize only the object
  shapes owned by that subsystem, call the registry's public registration API,
  and return a `PluginLoadResult`.
- Adapters must not invent global registries or mutate default registries as
  the only path. Programmatic explicit registration remains first-class.
- Object-shape acceptance is contract-specific. Recipes use entry point names
  and callable/class validation from `RecipeCatalog`; codecs accept instances,
  no-arg classes, or no-arg factories and register by `codec.key`; future
  contracts must define their own factory/config/registry shape before loading.

Plugin-readiness classifications:

| Group | Current target contract | Stage 14 classification | Revisit trigger |
| --- | --- | --- | --- |
| `loom.recipes` | `RecipeCatalog.register(name, recipe, replace=False)` exists | Load/register now into supplied catalogs; entry point name is authoritative | If recipe catalog naming or replacement policy changes |
| `loom.codecs` | `Codec` and `CodecRegistry.register(codec)` exist | Load/register now into supplied registries; runtime `codec.key` is authoritative; no replacement | If `CodecRegistry` later gains explicit replacement policy |
| `loom.sources` | `DataSource` exists, but no source registry exists | List/check only | Source registry and URI-scheme registration contract lands |
| `loom.executors` | Raw `Executor` exists; `ExecutorDescriptorRegistry` exists for capability metadata, not executor implementation loading | List/check only for executor implementations; do not accept raw executor factories in Stage 14 | Explicit executor descriptor/factory/registry contract lands |
| `loom.artifact_store_backends` | `ArtifactStore`, `RunArtifactStore`, and `StageArtifactStore` protocols exist, but backend config/handler/capability registry is Stage 15 | List/check only | Stage 15 external artifact-store backend registry and capability model lands |
| `loom.run_exporters` | Stage 12 planned `RunExporter`; no source-level protocol found in this checkout, and implementation planning rechecked the same on 2026-05-15 | List/check only | `RunExporter` protocol and result records land under the owning run/export module |
| `loom.sweep_providers` | Stage 13 planned provider/adapter contracts; no `loom.pipeline.sweep` source exists in this checkout, and implementation planning rechecked the same on 2026-05-15 | List/check only | Sweep provider/adapter protocol lands under `loom.pipeline.sweep` |
| `loom.event_sinks` | `PipelineEvent` records exist, but no `EventSink` or `EventSinkRegistry` contract exists | List/check only; registration waits for Stage 19 | Stage 19 runtime event and event-sink registry contracts land |

Targeted artifact-store backend design addendum:

| Question | Recommendation | Strictness and maintainability rationale | Stage 14 impact | Stage 15/upgradability impact |
| --- | --- | --- | --- | --- |
| What does an artifact-store backend plugin advertise? | A future backend descriptor or descriptor factory owned by the store layer, not a raw `ArtifactStore`, open client, local-root `ArtifactStoreFactory`, or service-specific SDK object. | Raw stores would bake in the current local-root construction shape and make credential/config/lifecycle behavior ambiguous. A descriptor can version the backend API and expose metadata before construction. | Only reserve/list/check `loom.artifact_store_backends`; do not validate loaded object shape. | Stage 15 should define descriptor fields such as backend kind, supported URI schemes, config validation, capability model, redaction, factory, and contract/API version. |
| Which package owns the backend registry? | `loom.pipeline.stores` owns any future `ArtifactStoreBackendRegistry` or equivalent; `loom.plugins` only loads entry points into a supplied registry after the registry exists. | Store semantics, capabilities, refs, errors, and runner hooks belong with stores. Keeping registry ownership there prevents plugin discovery from becoming a runtime store layer. | Do not add a store registry to `loom.plugins`; do not make config/I/O/pipeline import plugin APIs. | Stage 15 can evolve registry internals without changing generic plugin discovery records. |
| How should backends hook into execution internals? | Through explicit store-owned resolution from authored runtime/config plus run context, then a run-scoped artifact-store object passed to planner/runner APIs. | Current runner takes a local-root factory. Treating plugin targets as that callable would lock future remote stores to a local filesystem constructor and hide URI/config/credential needs. | Stage 14 must not connect plugin backend entries to `PipelineRunner`, `StageContext`, or preflight artifact-store availability. | Stage 15 should define a resolver/factory boundary that can build local, external, remote, read-only, or fake stores from explicit config and capability checks. |
| What should plugin/preflight checks mean before Stage 15? | Metadata availability only: known group, requested entry point present, deterministic duplicate detection, package/version summary, and listing-only status. | A check result must not overstate safety. Import success is not backend validity, credential availability, write permission, or run-readiness. | `loom plugins check` and preflight should label artifact-store backends as listing-only and fail closed if a caller requests registration/run-readiness. | Stage 15 can add real backend availability, URI/config, cheap credential, read/write capability, and unsupported-operation checks with stable check IDs. |
| How strict should duplicate/replacement behavior be? | Duplicate advertised backend names are errors. No replacement or last-wins behavior in Stage 14. Future replacement, if any, must be explicit registry policy. | Backend kind collisions can redirect artifacts and credentials. Strict failure is safer for reproducibility and upgrade behavior. | Generic duplicate diagnostics include group/name/package/version and never choose a winner by install order. | Stage 15 can require descriptor kind to match entry point name or define an explicit alias policy; unknown collisions remain fail-closed. |
| What must stay out of Stage 14? | Backend config schema, credential probing, URI scheme ownership, capability declarations, operation results, materialization, cache/staging behavior, manifest commit policy, and remote payload movement. | These are externally visible behavior contracts with significant migration cost and optional dependency risk. | Stage 14 docs and CLI output must make the backend group a namespace reservation plus diagnostics only. | Stage 15/16 can add the real public contract in layers without refactoring Stage 14 plugin records. |
| What upgrade affordance should the future contract include? | A backend descriptor contract version or API version should be part of the Stage 15 descriptor/result shape, separate from package distribution version. | Package versions do not say which Loom backend interface a plugin implements. Explicit contract versioning gives clear fail-closed upgrade behavior. | Stage 14 `PluginRecord` keeps distribution version only; no backend API version is invented now. | Stage 15 can reject incompatible backend descriptors with structured diagnostics and support later migrations deliberately. |

Future-roadmap impact:

- Stage 12 exporter/importer protocols can become plugin-loadable after their
  source-level public protocols land and remain explicit callable adapters, not
  automatic post-run dispatch.
- Stage 13 sweep providers can use `loom.sweep_providers` after the provider
  protocol and registry/factory contract land; Stage 14 should not encode
  optimizer semantics.
- Stage 15 keeps authority over artifact-store backend config, external refs,
  capabilities, and preflight behavior; Stage 14 only reserves the metadata
  namespace and generic diagnostics.
- Stage 16 optional backends can package themselves as plugins without adding
  cloud/service SDKs to the default Loom install.
- Stage 19 owns runtime event grammar, callback failure policy, event
  persistence, `EventSink`, and `EventSinkRegistry`; Stage 14 only lists the
  `loom.event_sinks` group and preserves the future loading pattern.

Compatibility constraints:

- Public group string values should remain stable once shipped.
- Listing must be deterministic and metadata-only by default.
- Loading must be explicit and clearly documented as trusted Python code
  execution.
- Duplicate entry point names and duplicate runtime keys fail deterministically.
- `CodecRegistry` is not widened for replacement in Stage 14.
- Plugin summaries must be plain-data-compatible and must omit loaded objects,
  callback state, credentials, tracebacks beyond safe messages, and large reprs.
- Core remains domain-neutral and dependency-light.

## Design Agreement Queue

| ID | Decision | Depends on | Resolution order | Classification | Recommended answer | Why it matters | Why user input is needed | Status |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| DAQ-1 | Owning package and dependency direction | FR-1 | 1 | recorded recommendation | Put discovery in `src/loom/plugins/`; keep subsystem registries plugin-free; keep CLI/preflight as outer callers. | Preserves import boundaries and makes discovery optional. | Repo evidence gives a clear recommendation. | confirmed |
| DAQ-2 | Stable group list and future-group policy | FR-1, FR-6 | 2 | recorded recommendation | Define stable constants for roadmap groups, but only load/register groups with stable target contracts; list/check future groups. | Public group names are durable and affect downstream package metadata. | User already confirmed future-group listing/check support and fundamentals-first scope. | confirmed |
| DAQ-3 | Replacement policy | FR-4, FR-5 | 3 | recorded recommendation | Support replacement only where target registries already support it; do not widen `CodecRegistry`; duplicate codec keys fail in Stage 14. | Affects duplicate semantics and registry APIs. | User already confirmed no codec replacement support. | confirmed |
| DAQ-4 | Loaded-object result shape | FR-2, FR-3 | 4 | recorded recommendation | Return structured results that keep loaded objects separate from serializable summaries. | Supports provenance and CLI without serializing Python objects. | Repo evidence gives a clear recommendation. | confirmed |
| DAQ-5 | Provenance coupling | FR-9 | 5 | recorded recommendation | `loom.plugins` exposes summaries; provenance/run code owns persistence. | Prevents plugin discovery from importing run-store/provenance persistence paths unnecessarily. | User already confirmed this boundary. | confirmed |
| DAQ-6 | CLI load defaults | FR-7 | 6 | recorded recommendation | `plugins list` does not load by default; `--load` or `plugins check` loads registry-ready groups explicitly; listing-only groups report metadata and deferred-registration status. | Protects users from unexpected imports, service SDK failures, and false run-readiness claims. | User already confirmed this behavior; artifact-store addendum tightens listing-only semantics. | confirmed |
| DAQ-7 | Registry adapter shape for recipe and codec plugins | FR-4, FR-5 | 7 | recorded recommendation | Use explicit adapter functions over caller-supplied registries; recipe entry point name is authoritative; codec runtime key is authoritative. | Defines the reusable pattern for future loaders without global mutation. | Repo evidence and confirmed behavior give a clear recommendation. | confirmed |
| DAQ-8 | Plugin-ready extension contract boundary | FR-6, FR-11 | 8 | recorded recommendation | Add a contract-readiness table and minimal cleanup path for `Executor`, `ArtifactStore`, `RunExporter`, `SweepProvider`, and `EventSink`; load/register only stable contracts, list/check unstable groups, and record blockers/revisit triggers for later stages. | Public plugin groups are not useful unless a plugin author knows what object shape to provide, but premature contract revisions can steal scope from Stage 15/19. | User already confirmed audit plus minimal-cleanup boundary. | confirmed |
| DAQ-9 | Preflight and check selection boundary | FR-7, FR-8 | 9 | recorded recommendation | `plugins check` and preflight load only requested registry-ready groups/names or selected capability groups; listing-only groups receive metadata checks and explicit listing-only status. | Keeps diagnostics useful without turning environment checks into broad third-party imports or false run-readiness claims. | User already confirmed selected check behavior; artifact-store addendum tightens listing-only semantics. | confirmed |
| DAQ-10 | Artifact-store backend plugin contract boundary | FR-6, FR-11, DAQ-2, DAQ-8, DAQ-9 | 10 | recorded recommendation | Keep `loom.artifact_store_backends` metadata-only in Stage 14. Recommend a future Stage 15 store-owned backend descriptor/factory contract and supplied backend registry before any loader or registration adapter exists. | Artifact-store backend shape is externally facing and touches config, execution, refs, preflight, provenance, optional dependencies, and payload semantics. | User explicitly requested this targeted pass; repo and Stage 15 evidence support a clear strict recommendation. | confirmed |

## Design Decisions

| ID | Decision | Selected approach | User feedback | Alternatives rejected | Rationale | Maintainability impact | Extensibility, flexibility, and expansion impact | Future-roadmap impact | Interface, adapter, or protocol impact | Validation/documentation obligation | Debt and revisit trigger | Status |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| DAQ-1 | Owning package and dependency direction | `src/loom/plugins/` owns discovery and explicit loading; subsystem registries remain plugin-free; CLI/preflight are outer callers. | No further input needed; matches confirmed import-safety and explicit-loading baseline. | Put plugin discovery inside config/I/O/CLI; make registries discover plugins themselves; import plugin discovery from `loom.__init__`. | Keeps plugin discovery optional and avoids import-time side effects. | Clear package ownership and lower coupling. | Future loaders can be added as registry contracts stabilize. | Preserves Stage 15 store and Stage 19 event freedom. | Discovery helpers wrap registries instead of owning runtime semantics. | Import-boundary tests and docs. | Revisit if a subsystem later needs a plugin-owned registry contract. | confirmed |
| DAQ-2 | Stable group list and future-group policy | Ship public group values for recipes, codecs, sources, executors, artifact-store backends, run exporters, sweep providers, and event sinks; only recipe/codec adapters are loadable now. | User confirmed broad group listing/check support and fundamentals-first scope. | Only expose recipe/codec groups now; load every group immediately. | Durable metadata namespaces help downstream packages without forcing unstable loaders. | Slightly larger public namespace, but each group has explicit readiness status. | Future packages can advertise extensions before runtime loaders land. | Keeps Stage 12/13/15/16/19 compatibility visible. | Group values are stable public metadata; loader contracts remain separately gated. | Docs and tests for group constants and listing-only status. | Revisit only before implementation-plan drafting if a feature spec has a stronger canonical spelling than the backend-oriented artifact-store group selected by design-safety review. | confirmed |
| DAQ-3 | Replacement policy | Duplicate entry point names and runtime keys fail; recipe replacement can remain an explicit catalog option where already supported; codec replacement is not added. | User confirmed duplicate codec keys fail and no `CodecRegistry` replacement in Stage 14. | Add `CodecRegistry.replace`; silently let last plugin win; make plugin loading globally override built-ins. | Deterministic duplicate failure is safer for reproducible runs and debugging. | Avoids widening stable registries for plugin ergonomics. | Future replacement can be added deliberately per registry. | Does not constrain future registry-specific replacement policy. | Codec adapter has no `replace`; recipe adapter may pass explicit `replace=False` by default. | Duplicate tests for entry point names and codec keys. | Revisit only if registry design adds explicit replacement semantics. | confirmed |
| DAQ-4 | Loaded-object result shape | `PluginLoadResult` carries loaded objects for explicit Python callers while summaries omit objects and remain plain-data-compatible. | No further input needed. | Return bare objects only; serialize object reprs into diagnostics; make CLI inspect object internals. | CLI, preflight, and provenance need metadata without Python object serialization. | Keeps result handling central and safer to extend. | Future adapters can add runtime key/sink name fields without changing loaded-object ownership. | Supports provenance later without coupling to persistence. | Separates runtime objects from summaries. | Unit tests for `to_dict()`/summary shape and object omission. | Revisit if provenance requires a versioned plugin-summary schema. | confirmed |
| DAQ-5 | Provenance coupling | `loom.plugins` exposes plain summaries; provenance/run code decides when and where to persist them. | User confirmed this boundary. | Have plugin loading write provenance directly; import run-store/provenance persistence in plugin APIs. | Prevents plugin discovery from depending on run storage. | Keeps `loom.plugins` small and import-light. | Summaries can be reused by CLI, preflight, and future run provenance. | Compatible with later provenance document evolution. | Plain summary records only. | Summary tests and documentation of persistence ownership. | Revisit when a run/provenance stage wires summaries into persisted run facts. | confirmed |
| DAQ-6 | CLI load defaults | `loom plugins list` is metadata-only; `--load` and registry-ready `plugins check` paths perform explicit selected loading and report failures/duplicates; listing-only groups report metadata and deferred-registration status. | User confirmed the defaults; artifact-store addendum tightens backend status wording. | Make list verify loadability by default; auto-load all installed plugins during preflight; imply listing-only artifact-store backends are run-ready. | Avoids surprising imports of project packages or service SDKs and avoids overstating backend validity. | Keeps command behavior predictable. | Check/preflight can still verify selected registry-ready capabilities in CI while preserving future backend contracts. | Compatible with optional backend packaging and event-sink SDKs. | CLI is presentation over plugin APIs. | CLI tests for list/check text and JSON, listing-only labels, and import-safety checks. | Revisit only if users need a separate exhaustive audit command with explicit import-only semantics. | confirmed |
| DAQ-7 | Registry adapter shape for recipe and codec plugins | Use explicit loader adapters over supplied registries; recipe entry point name is authoritative; codec runtime key is authoritative; no global mutation. | No further input needed; follows confirmed behavior. | Require plugins to mutate global defaults; use loaded object names for recipes; use entry point names for codec runtime keys. | Registry ownership stays with existing subsystem contracts. | Keeps adapters direct and testable. | Establishes the repeatable pattern for later registries without forcing identical object shapes. | Future source/executor/store/exporter/provider/event adapters can follow the same structure after their contracts land. | Adapter functions are the public reusable shape, not a universal plugin object protocol. | Contract tests with fake recipes/codecs and invalid objects. | Revisit when future registries define their own name/key semantics. | confirmed |
| DAQ-8 | Plugin-ready extension contract boundary | Record per-contract readiness; only recipe/codec are load/register now; source/executor/artifact-store-backend/exporter/provider/event-sink groups are listing/check-only unless stable source APIs have landed before implementation planning. | User requested and confirmed interface/protocol readiness audit plus minimal cleanup boundary. | Speculatively define loaders for every group; refactor Stage 15/19 semantics into Stage 14. | Avoids ambiguous object shapes and premature runtime semantics. | Makes future-loader blockers explicit before implementation planning. | Keeps enough public structure for downstream metadata while preserving later contract design freedom. | Protects Stage 12/13/15/16/19 from being constrained by plugin discovery. | Future contracts must define factory/config/registry/key/failure semantics before loaders. | Contract-readiness table, docs, and fake listing/check tests. | Revisit each listing-only group when its owning registry/protocol lands. | confirmed |
| DAQ-9 | Preflight and check selection boundary | Check/preflight loads only requested registry-ready groups/names or selected capability groups; listing-only groups such as artifact-store backends receive metadata checks and explicit deferred-registration status. | User confirmed selected checks and no broad load scan; artifact-store addendum clarified strict backend behavior. | Load every installed plugin in every preflight; silently ignore plugin failures unless a run touches them; report advertised artifact-store backends as usable before Stage 15. | Keeps preflight useful without making it a side-effect-heavy environment scan or making false capability claims. | Clear diagnostic entrypoints reduce scattered checks. | Future config can request plugin groups/names explicitly after owning contracts exist. | Works with optional backends and service SDKs. | Preflight consumes plugin results and store-owned readiness APIs later, not plugin internals. | Preflight tests with fake requested plugin failures, duplicate diagnostics, and listing-only artifact-store backend checks. | Revisit if config gains explicit plugin requirement declarations or Stage 15 lands backend registry checks. | confirmed |
| DAQ-10 | Artifact-store backend plugin contract boundary | `loom.artifact_store_backends` is a stable metadata namespace only in Stage 14. Future loading should target a Stage 15 store-owned backend descriptor/factory, registered into a supplied store backend registry. | User requested a targeted pass to avoid future refactors and align strict behavior with maintainability/upgradability. | Accept raw `ArtifactStore` instances; accept current local-root `ArtifactStoreFactory` callables; put backend registry in `loom.plugins`; instantiate stores from plugin entries inside runner/preflight; claim plugin import success proves run-readiness. | The current artifact store is local-root/runtime oriented, while future backends need explicit config, URI schemes, capabilities, redaction, credentials, operation diagnostics, and run-context construction. | Prevents Stage 14 from freezing the wrong public object shape and keeps backend semantics near store code. | Stage 15 can add descriptor API versioning, backend registry, config/ref records, fake backend conformance, and capability-gated preflight without refactoring Stage 14 plugin discovery. | Defines the intended future contract shape while keeping Stage 14 metadata-only. | Tests should prove artifact-store backend entries list/check metadata without target imports by default, show listing-only status, reject duplicates, and do not construct stores. | Revisit when Stage 15 defines `ArtifactStoreBackendDescriptor` or equivalent, backend registry, config handoff, capability model, and check IDs. | confirmed |

## Design Agreement Triage

| Decision ID | Final classification | Reviewer challenge considered | Traceability | Manager action | Status |
| --- | --- | --- | --- | --- | --- |
| DAQ-1 | recorded recommendation | Could central package still pull optional dependencies? Mitigation is no target loading on import and narrow imports. Design-safety upheld this boundary. | FR-1, FR-3, FR-10 | Carry import-boundary tests into implementation plan | confirmed |
| DAQ-2 | recorded recommendation | Stable group names may prematurely commit future metadata namespaces. Design-safety upheld broad group listing/check support and revised artifact-store spelling to `loom.artifact_store_backends`. | FR-1, FR-6 | Carry group constants, listing-only labels, and readiness table into implementation plan | confirmed |
| DAQ-3 | recorded recommendation | Replacement support may improve ergonomics but weakens deterministic duplicate policy. User confirmed no codec replacement. | FR-4, FR-5 | Record no codec replacement and duplicate-fail tests | confirmed |
| DAQ-4 | recorded recommendation | Structured loaded-object wrappers can be overbuilt. Keep minimal and plain summaries separate. | FR-2, FR-9 | Record result shape and object-omission validation | confirmed |
| DAQ-5 | recorded recommendation | Provenance may need plugin summaries soon; avoid direct persistence coupling. | FR-9 | Record summary-only boundary | confirmed |
| DAQ-6 | recorded recommendation | Users may expect list to verify loadability; provide explicit `--load`/`check`. | FR-7, FR-10 | Record CLI defaults and explicit-load tests | confirmed |
| DAQ-7 | recorded recommendation | Registry adapters can accidentally become universal object protocols. Mitigation is contract-specific adapters over supplied registries. | FR-4, FR-5 | Record adapter pattern and recipe/codec object-shape tests | confirmed |
| DAQ-8 | recorded recommendation | Plugin-readiness audit may expose missing factory/registry contracts. Design-safety upheld listing/check-only status and revisit triggers for unstable groups. | FR-6, FR-11 | Carry readiness table and future-roadmap revisit triggers into implementation plan | confirmed |
| DAQ-9 | recorded recommendation | Preflight can become broad environment scanning. Mitigation is explicit selected groups/names or selected capability groups only. | FR-7, FR-8 | Record check/preflight selection boundary | confirmed |
| DAQ-10 | recorded recommendation | Artifact-store backend plugins could accidentally freeze a raw store or local-root factory shape before Stage 15. Mitigation is metadata-only Stage 14 behavior plus a future store-owned descriptor/factory/registry contract. | FR-6, FR-11, DAQ-2, DAQ-8, DAQ-9 | Carry artifact-store backend addendum into implementation plan and Stage 15 alignment notes | confirmed |

## Design Safety Review

| Finding | Affected decision or requirement | Future-roadmap or compatibility risk | Interface, adapter, or protocol reuse risk | Recommended planning revision | Status |
| --- | --- | --- | --- | --- | --- |
| Artifact-store group spelling should describe backend advertisements, not raw store instances | DAQ-2, FR-1, FR-6, FR-11 | Stage 15 owns external/remote artifact-store backend config, handler, capability, and preflight semantics; a raw `loom.artifact_stores` group could imply Stage 14 loads `ArtifactStore` instances directly | Backend plugins likely provide handlers/factories/capability schemas, not already-open store instances | Revise the public group value to `loom.artifact_store_backends` and keep the group listing/check-only until Stage 15 contracts land | completed |
| Artifact-store backend object shape needs an explicit future contract | DAQ-10, FR-6, FR-11 | Exposing a raw store instance, local-root factory, or plugin-owned registry now would be externally visible and could force Stage 15/16 remote stores to fit the wrong construction path | Future backends need descriptor/factory, config, URI scheme, capability, redaction, preflight, operation-result, and contract-version semantics before registration is meaningful | Keep Stage 14 metadata-only; recommend Stage 15 define a store-owned backend descriptor/factory and supplied registry before adding `load_artifact_store_backend_entry_points(...)` | completed |
| Future group constants may imply loadability if docs and CLI output are vague | DAQ-2, DAQ-8, FR-6, FR-11 | Stage 12/13/15/19 could be constrained if downstream packages assume Stage 14 already accepts raw exporter/provider/store/event objects | Future contracts need their own factory/config/registry/key/failure policies before adapters can register objects | Require docs, CLI text/JSON, readiness tables, and implementation-plan notes to label non-recipe/codec groups as listing/check-first unless a stable contract is rechecked during implementation planning | completed |
| `ExecutorDescriptorRegistry` does not make executor implementation plugins ready | DAQ-8, FR-6, FR-11 | Future executor work could be forced into a descriptor-only or raw-instance shape before execution factory semantics are clear | Descriptor metadata and executable `Executor` factories have different lifecycle/config needs | Keep `loom.executors` listing/check-only in Stage 14; do not accept raw executor factories until an explicit descriptor/factory/registry contract exists | completed |
| Preflight and `plugins check` can become broad optional-SDK import paths | DAQ-6, DAQ-9, FR-7, FR-8, FR-10 | Stage 15/16 optional backends and Stage 19 event sinks may depend on service SDKs that should not be imported during unrelated checks | Explicit selection by group/name/package is required to scale plugin checks without side effects | Preserve metadata-only list defaults and selected loading/check behavior; avoid whole-environment plugin target imports in preflight | completed |
| Plugin summaries are useful for provenance but should not become a persisted schema owned by `loom.plugins` | DAQ-4, DAQ-5, FR-2, FR-9 | Future provenance stages may need versioned run facts, but Stage 14 should not choose run-store layout | Plain summaries are reusable; loaded Python objects, credentials, traceback internals, and large reprs are not reusable records | Keep `loom.plugins` summary-only and let provenance/run callers own persistence; revisit if provenance needs a versioned plugin-summary schema | accepted risk |
| The registry-adapter pattern is reusable only if it stays contract-specific | DAQ-7, DAQ-8, FR-4, FR-5, FR-11 | A universal plugin object protocol would constrain future stores, exporters, providers, and event sinks | Recipes, codecs, stores, exporters, providers, and event sinks need different name/key, factory/config, and failure semantics | Keep the reusable pattern as metadata -> selected load -> contract normalization -> caller-supplied registry registration -> structured result, not a universal loaded-object protocol | completed |

Gate result:

- Status: passed
- Reviewer: local design-safety pass using
  `.codex/prompts/roadmap-stage-design-safety-review.md`
- Files read for this pass: `docs/roadmap/stage-14/planning.md`,
  `.codex/prompts/roadmap-stage-design-safety-review.md`,
  `.codex/workflows/roadmap-stage-planning.md`,
  `.codex/templates/roadmap-stage-planning.md`, `docs/roadmap.md`,
  `docs/features/plugins.md`, `docs/features/preflight.md`,
  `docs/features/provenance.md`, `docs/features/remote-stores.md`,
  `docs/structure.md`, `docs/GLOSSARY.md`, Stage 12 and Stage 13 planning or
  implementation-plan references, and targeted source searches for
  `RecipeCatalog`, `CodecRegistry`, `ExecutorDescriptorRegistry`,
  `ArtifactStore`, `RunExporter`, `SweepProvider`, and `EventSink`. The
  targeted artifact-store backend addendum additionally read
  `docs/roadmap/stage-15/planning.md`, `src/loom/artifacts.py`,
  `src/loom/pipeline/stores/local_artifacts.py`, and the runner
  `ArtifactStoreFactory` construction points.
- Files changed by this pass: `docs/roadmap/stage-14/planning.md`.
- Blockers: none.
- Auto-approved or recorded-recommendation decisions upheld: DAQ-1 through
  DAQ-10 remain upheld. DAQ-2 was narrowed by revision to use the
  backend-oriented group value `loom.artifact_store_backends`, and DAQ-10
  records the stricter artifact-store backend contract boundary.
- Recorded recommendations: keep `loom.plugins` import-light and optional;
  keep subsystem registries plugin-free; load/register only recipe and codec
  adapters in Stage 14; keep future groups listing/check-first; keep CLI and
  preflight loading selected and explicit; expose plain summaries without
  persistence coupling; keep `loom.artifact_store_backends` metadata-only until
  Stage 15 defines a store-owned backend descriptor/factory and registry.
- Future-roadmap impact summary: Stage 12 run exporters, Stage 13 sweep
  providers, Stage 15/16 artifact-store backends, and Stage 19 event sinks are
  not blocked by Stage 14 because group namespaces are metadata-only until
  owning contracts define loader-ready registry/factory semantics.
- Generic interface, adapter, and protocol assessment: the adapter shape is
  generic enough as a pattern but deliberately not a universal object protocol.
  Future contracts must define object shape, factory/config handoff, registry
  ownership, key/name policy, duplicate behavior, diagnostics, and dependency
  boundaries before Stage 14 or later code exports a loader.
- Planning revisions required: completed in this pass. The artifact-store group
  was revised to `loom.artifact_store_backends` and readiness wording now
  reinforces listing/check-only behavior for unstable groups. The targeted
  addendum also records strict artifact-store backend check semantics and a
  future Stage 15 descriptor/factory recommendation.
- Accepted risks:
  - Future groups are public listing/check namespaces before every loader is
    available.
  - Codec plugin replacement is not supported in Stage 14.
  - Plugin summary records are not versioned persisted provenance schemas in
    Stage 14.
  - Run-exporter and sweep-provider loader readiness must be rechecked against
    landed source APIs during implementation-plan drafting.
- Artifact-store backend accepted risk:
  - Stage 14 exposes the backend group name before the backend contract exists,
    but this is bounded by metadata-only behavior, explicit listing-only
    diagnostics, and a Stage 15 revisit trigger before any registration loader.
- Revisit triggers: source registry lands; executor descriptor/factory/registry
  contract lands; Stage 12 `RunExporter` source protocol lands; Stage 13
  sweep-provider protocol lands; Stage 15 artifact-store backend registry and
  capability model lands; Stage 19 runtime-event and event-sink registry
  contracts land; provenance requires a versioned plugin-summary schema.

## Practical Design Notes

Public Python API surface:

- `loom.plugins` should export the stable group constants, record/result
  dataclasses, generic listing/loading helpers, recipe/codec loader adapters,
  and plugin errors.
- Public group string values are the stable contract for downstream package
  metadata; implementation can choose readable constant names such as
  `RECIPES_GROUP` or `PLUGIN_GROUP_RECIPES`.
- Public loaders are explicit functions. They do not install packages, scan
  remote indexes, mutate global registries as the only path, or dispatch
  service-specific integrations.
- Stage 14 should not expose an artifact-store backend loader or provisional
  backend protocol. `loom.artifact_store_backends` is public as an entry point
  group string only; the loadable backend descriptor/factory API belongs to
  Stage 15 under store ownership.
- `loom.__init__` should not re-export plugin helpers in Stage 14 unless a
  later review proves the import remains cheap and side-effect-free.

CLI surface:

- `loom plugins list` lists known group metadata by default without loading
  plugin targets.
- `loom plugins list --load` explicitly loads selected registry-ready
  groups/names and reports load results. If generic import-only diagnostics are
  ever exposed for listing-only groups, output must label them as import-only,
  not registered or usable.
- `loom plugins check` loads selected registry-ready groups/names or selected
  capability groups, metadata-checks listing-only groups, reports
  duplicates/failures/status, and exits nonzero when requested checks fail.
- Artifact-store backend CLI output must say listing/check-only until Stage 15
  defines backend registry checks; it must not say "registered", "available",
  or "usable for runs" based only on Stage 14 discovery.
- CLI output should support text and JSON and stay a presentation layer over
  plugin result records.

Persisted records and file layout:

- `loom.plugins` does not persist state.
- Plugin summaries are plain data suitable for CLI JSON, preflight diagnostics,
  and future provenance inclusion.
- Run/provenance callers decide whether a loaded plugin summary belongs in a
  run provenance document, runtime metadata, or check/preflight output.
- Loaded Python objects, callback state, credentials, and large object reprs
  are not persisted by plugin summaries.

Import boundaries and dependencies:

- Generic discovery uses standard-library `importlib.metadata`.
- Importing `loom`, `loom.config`, `loom.io`, `loom.pipeline`, or CLI help
  paths must not discover or load plugin targets.
- Plugin target modules are imported only by explicit load/check paths.
- Registry adapter modules may import stable subsystem registry types, but
  subsystem modules do not import `loom.plugins`.
- Store code may later call plugin APIs from an outer setup path to populate a
  supplied backend registry, but `ArtifactStore`, `LocalArtifactStore`,
  `PipelineRunner`, and preflight artifact probes should not import plugin
  discovery directly.
- No optional backend, cloud, optimizer, notification, tracking, or project
  package dependency belongs in core plugin discovery.

Failure modes and diagnostics:

- Discovery failures, load failures, invalid loaded objects, duplicate entry
  point names, duplicate runtime keys, and registry failures are structured.
- Diagnostics include group, entry point name, entry point value, distribution
  name/version when available, runtime key when available, target registry, and
  original exception context.
- Strict mode raises on requested failures. Best-effort mode records failures
  and continues where it is safe.
- Duplicate resolution never depends on package metadata ordering.
- Artifact-store backend metadata checks fail closed: duplicate backend entry
  point names, requested-but-missing advertisements, unsupported Stage 14
  registration requests, and unknown future capabilities are failures or
  listing-only diagnostics, not warnings that silently proceed.

Extension points and flexibility boundaries:

- Recipes and codecs are the only load/register adapters confirmed for Stage
  14.
- Source, executor, artifact-store backend, run-exporter, sweep-provider, and
  event-sink groups are listing/check-first until their owning contracts define
  registry ownership, factory/config needs, names/keys, and failure semantics.
- Artifact-store backend readiness specifically requires a store-owned
  descriptor/factory contract, backend registry, backend kind/key policy,
  supported URI-scheme declarations, config validation and redaction hooks,
  capability records, preflight check IDs, operation/failure result records, and
  run-context construction semantics.
- `ExecutorDescriptorRegistry` is useful capability metadata but does not by
  itself make raw `Executor` implementation plugins loadable.
- `PipelineEvent` records are not enough to make event sinks loadable; Stage 19
  still owns `EventSink` and `EventSinkRegistry`.

Generic interfaces, adapters, and protocols:

- The generic adapter pattern is: metadata listing -> selected explicit load ->
  contract-specific normalization -> caller-supplied registry registration ->
  structured load result.
- Stage 14 should not define a universal plugin object protocol. Runtime object
  shape remains owned by each subsystem's public contract.
- Future loader readiness requires an owning registry or factory protocol,
  duplicate key/name policy, configuration handoff shape, diagnostics, and
  import/dependency boundary tests.
- The expected future artifact-store adapter pattern is: discover backend
  entry point metadata -> explicitly load a descriptor/factory target after
  Stage 15 exists -> validate descriptor contract/API version -> register into
  a supplied `loom.pipeline.stores` backend registry -> let store-owned
  resolution construct run-scoped stores from explicit config and run context.

Future-roadmap compatibility:

- Stage 12: run exporter plugins remain listing/check-only in this checkout
  because no source-level `RunExporter` protocol was found; if one lands before
  implementation planning, it must pass the same readiness checks before a
  loader is promised.
- Stage 13: sweep-provider plugins remain listing/check-only in this checkout
  because `loom.pipeline.sweep` has not landed; if provider contracts land, the
  loader must not encode optimizer semantics.
- Stage 15/16: artifact-store backend plugin loading waits for backend-neutral
  store config, capability, descriptor/factory, registry, operation-result,
  redaction, URI/config validation, and preflight contracts, keeping optional
  SDKs outside core. Stage 16 materialization should consume those contracts
  rather than requiring Stage 14 refactors.
- Stage 19: event-sink loading waits for runtime event grammar, sink registry,
  callback failure policy, and persistence policy.

Maintainability assessment:

- The design keeps plugin discovery small and centralized while leaving runtime
  semantics with subsystem registries. This reduces duplicate entry point logic
  and prevents config/I/O/pipeline modules from developing hidden discovery
  side effects.
- Main maintainability risk: the future group list may look more capable than
  it is. The readiness table, docs, CLI wording, and tests must make
  listing/check-only status explicit.
- Artifact-store backend maintainability risk is higher than most future groups
  because the contract will be externally implemented and touches config,
  execution, refs, provenance, preflight, and optional dependencies. The Stage
  14 implementation plan must keep the group metadata-only and avoid any
  provisional backend object shape.

Extensibility assessment:

- The registry-adapter pattern is reusable without forcing every future
  extension point into the same object shape.
- Future packages can advertise group metadata now and become loadable only
  after their owning contracts land.
- The plain result/summary model can support CLI, preflight, and provenance
  without adding persistence coupling.

Flexibility and expansion assessment:

- The design supports immediate recipe/codec usability while preserving future
  room for executor descriptors/factories, artifact-store backend handlers,
  run exporters, sweep providers, and event sinks.
- Explicit selection by group/name/package lets project setup and CI avoid
  importing unrelated installed plugins.

Scalability and future compatibility:

- Metadata listing should sort deterministically and avoid target imports, so
  it stays cheap enough for debugging and CI.
- Loading remains selected and explicit, which scales better in environments
  with many installed packages or optional service SDKs.
- Public group values are the main long-lived compatibility commitment; loader
  contracts remain gated by readiness.

Accepted debt:

| Debt | Reason accepted | Revisit trigger |
| --- | --- | --- |
| Future groups may be public before they are load/register-capable | Downstream metadata stability and inspection/check support are useful now, while runtime contracts are not all stable | Owning registry/protocol lands for source, executor, artifact-store backend, run exporter, sweep provider, or event sink |
| No codec replacement support | User confirmed deterministic duplicate failure and current `CodecRegistry` has no replacement API | `CodecRegistry` gains explicit replacement semantics through a future design |
| Artifact-store backend group exists before a backend contract | Lets downstream packages reserve and inspect the intended backend namespace while avoiding premature remote-store semantics | Stage 15 defines backend descriptor/factory, backend registry, config handoff, capabilities, redaction, preflight, and operation result contracts |

## Examples And Demonstrations

| Example | Behavior demonstrated | Loom context | Required docs/tests | Status |
| --- | --- | --- | --- | --- |
| List fake recipe and codec entry points without importing targets | Discovery is metadata-only by default | `loom.plugins` generic listing and `loom plugins list` | Unit and CLI tests with fake entry points | confirmed |
| Load fake recipe entry point into supplied catalog | Recipe plugin loading works and uses entry point name | `RecipeCatalog` | Contract/unit tests | confirmed |
| Load fake codec class/factory into supplied registry | Codec object-shape handling and runtime key registration | `CodecRegistry` | Contract/unit tests | confirmed |
| Duplicate plugin names and duplicate codec keys | Deterministic duplicate diagnostics | Generic loader and codec adapter | Unit tests | confirmed |
| Best-effort check records multiple failures | Inspection/reporting does not stop after first failure | `loom plugins check` | CLI tests | confirmed |
| Import `loom` and run `loom --help` with advertised plugins present | Plugin targets are not loaded by import/help | Package and CLI import boundary | Package/CLI tests | confirmed |
| Preflight reports requested plugin failure | Preflight plugin diagnostics are structured | `loom preflight` | Preflight tests with fake plugin failure | confirmed |
| Contract-readiness table for plugin groups | Executor, artifact-store backend, exporter, sweep-provider, and event-sink groups are classified before loaders are promised | Future group planning | Planning artifact, implementation plan, and design-safety review | confirmed |
| List fake artifact-store backend entry point | Backend group is discoverable but not load/register-capable in Stage 14 | `loom.artifact_store_backends` | Unit and CLI tests with fake entry points and listing-only status | confirmed |
| Requested artifact-store backend registration before Stage 15 | Strict fail-closed behavior for premature backend use | Plugin/preflight diagnostics | Unit/CLI/preflight tests proving no store is constructed and output says backend contract is deferred | confirmed |

## Validation Strategy

| Area | Behavior validated | Required coverage | Test/check type | Command or location | Status |
| --- | --- | --- | --- | --- | --- |
| Package import safety | `import loom`, `import loom.config`, `import loom.io`, and `import loom.pipeline` do not discover/load plugins | Package/import-boundary | Package/contract | `tests/package` and `tests/contracts` | confirmed |
| Generic discovery | Listing filters by group/name/package and returns records without loading | Unit | Unit | `tests/unit/loom/plugins` | confirmed |
| Generic loading | Strict and best-effort modes, name filtering, chained load errors | Unit | Unit | `tests/unit/loom/plugins` | confirmed |
| Duplicate policy | Duplicate entry point names and runtime keys produce structured errors | Unit/contract | Unit and contract | `tests/unit/loom/plugins`, `tests/contracts` | confirmed |
| Recipe integration | Fake recipe plugin registers into supplied catalog; invalid recipe wraps catalog errors | Contract/unit | Contract and unit | `tests/contracts/test_recipe_contract.py` plus plugin tests | confirmed |
| Codec integration | Instance/class/factory shapes register; constructor failures and duplicate keys report correctly | Contract/unit | Contract and unit | `tests/contracts/test_codec_contract.py` plus plugin tests | confirmed |
| CLI commands | `plugins list` and `plugins check` text/JSON behavior and exit codes | CLI | CLI/unit | `tests/unit/loom/cli` or CLI contract tests | confirmed |
| Preflight | Plugin checks report pass/warn/fail with stable IDs | Unit/contract | Preflight tests | Existing preflight test area | confirmed |
| Provenance summaries | Plugin records/results convert to plain data without objects/secrets | Unit | Unit | `tests/unit/loom/plugins` | confirmed |
| Extension contract readiness | Stable extension contracts have fake plugin tests; unstable contracts are documented as listing/check-only with blockers | Contract/design | Contract tests where loadable, docs/planning where deferred | `tests/contracts` plus implementation-plan notes | confirmed |
| Artifact-store backend listing-only behavior | `loom.artifact_store_backends` entries list/check metadata, reject duplicates, do not import targets by default, do not construct stores, and do not claim run-readiness | Unit/CLI/preflight/design | Unit and CLI tests plus implementation-plan notes | `tests/unit/loom/plugins`, CLI tests, preflight tests | confirmed |

## Phase Sketch

### Phase 1 - Plugin Records And Generic Discovery

Goal:

- Establish plugin package, group constants, records, errors, metadata listing,
  generic loading, strict/best-effort failure reporting, duplicate detection,
  and import-safety tests.

Scope:

- `src/loom/plugins/` public records/errors/helpers.
- Fake entry point test seam.
- Package/API exports.

Out of scope:

- Registry-specific recipe/codec loading, CLI, preflight, provenance
  integration, or future extension loaders.

Acceptance criteria:

- Plugin records and generic discovery/load APIs are typed, deterministic, and
  testable without real installed packages.
- Importing Loom does not discover or load plugin targets.

Test expectations:

- Package: import/export checks.
- Unit: records, listing, loading, failures, duplicates.
- Contract: import-boundary behavior if applicable.
- Integration: none expected.
- E2E: none expected.
- Opt-in: none.

Design impact:

- Introduces the public plugin package and group constants.

Future compatibility:

- Must leave room for registry-specific loaders and future groups.

Alternatives rejected:

- Plugin discovery inside subsystem registries or CLI only.

Debt introduced:

- None planned; future groups may remain listing-only.

Reviewability:

- Small public contract phase with fake-entry-point tests.

### Phase 2 - Recipe And Codec Registry Adapters

Goal:

- Add explicit recipe and codec plugin loading into supplied registries.

Scope:

- `load_recipe_entry_points`.
- `load_codec_entry_points`.
- Accepted object-shape handling.
- Registry error wrapping.
- Runtime-key duplicate diagnostics.

Out of scope:

- Source/executor/store/exporter/event-sink registration.

Acceptance criteria:

- Recipe and codec plugins can extend existing public registries only when the
  caller explicitly asks.

Test expectations:

- Package: public exports.
- Unit: adapter behavior.
- Contract: recipe and codec extension behavior.
- Integration: minimal registry integration.
- E2E: none expected.
- Opt-in: none.

Design impact:

- Establishes the first concrete registry-adapter pattern.

Future compatibility:

- Pattern should be reusable for later registries without forcing identical
  object shapes.

Alternatives rejected:

- Global mutation as the only plugin loading path.

Debt introduced:

- None planned; no codec replacement support is an intentional Stage 14
  boundary.

Reviewability:

- Focused on two stable registries with direct tests.

### Phase 3 - CLI, Preflight, And Provenance Summaries

Goal:

- Expose plugin inspection/check behavior through CLI, preflight diagnostics,
  and plain-data summary helpers.

Scope:

- `loom plugins list`.
- `loom plugins check`.
- Plugin preflight checks where requested.
- Plain summary conversion for loaded plugin records/results.

Out of scope:

- Persisting provenance inside run records unless a caller already has a stable
  hook.
- Loading unstable future extension groups by default.

Acceptance criteria:

- Users and CI can inspect and verify plugins with clear text/JSON diagnostics.

Test expectations:

- Package: CLI registration import remains safe.
- Unit: result formatting and preflight check models.
- Contract: CLI JSON shape if selected.
- Integration: CLI commands with fake entry points.
- E2E: optional CLI smoke.
- Opt-in: none.

Design impact:

- Adds user-visible command surface and diagnostics.

Future compatibility:

- Must keep CLI thin over Python APIs and keep list side-effect-light by
  default.

Alternatives rejected:

- Automatic plugin loading on all commands.

Debt introduced:

- Provenance persistence may be deferred to a later run/provenance integration
  phase if no stable hook exists.

Reviewability:

- Bounded CLI/preflight layer over already-tested plugin APIs.

### Phase 4 - Future Group Readiness And Contract Hooks

Goal:

- Add stable listing/check support and documented plugin-readiness status for
  source, executor, artifact-store backend, run-exporter, event-sink, and any
  confirmed sweep-provider groups without prematurely implementing unstable
  registration.

Scope:

- Group constants and metadata listing/check coverage for future groups.
- Loading only for protocols/registries that are already landed and stable
  when implementation planning starts.
- Contract-readiness table for `Executor`, `ArtifactStore`, `RunExporter`,
  `SweepProvider`, and `EventSink`, including object shape, factory/config
  needs, registry ownership, duplicate key, diagnostics, and blocker/revisit
  status.
- Artifact-store backend addendum coverage: `loom.artifact_store_backends`
  remains metadata-only; Stage 14 has no backend loader, no store registry
  mutation, no raw `ArtifactStore` or local-root factory plugin target, and no
  run-readiness claim.
- Minimal interface cleanup only when a contract is already stable and the
  cleanup is necessary for plugin loading; otherwise record listing/check-only
  status.
- Documentation of deferred registration behavior and future revisit triggers.

Out of scope:

- Concrete external service integrations.
- Stage 15 artifact-store descriptor/factory, registry, config, capability,
  URI validation, credential, operation-result, materialization, cache, staging,
  and handler semantics.
- Stage 19 event sink registry semantics.
- Third-party CLI command injection.

Acceptance criteria:

- Future extension packages can advertise intended groups and users can inspect
  them; Loom does not claim registration behavior before target contracts
  exist.
- Artifact-store backend advertisements list/check as metadata and fail closed
  for premature registration or run-readiness requests.
- The implementation plan does not have to infer whether executor, store,
  exporter, provider, or event-sink plugins are loadable; each has an explicit
  readiness classification.

Test expectations:

- Package: group constants exported.
- Unit: listing/check for future groups, including artifact-store backend
  duplicate and listing-only status.
- Contract: fake plugin tests only for stable loadable contracts; readiness docs
  for listing-only or deferred groups.
- Integration: none expected.
- E2E: none expected.
- Opt-in: none.

Design impact:

- Public group names become durable metadata namespaces.

Future compatibility:

- Must preserve Stage 15/16/19 design freedom.
- Must leave Stage 15 free to define a store-owned backend descriptor/factory,
  registry, contract/API version, capability model, and internal resolution
  hook without refactoring Stage 14 plugin discovery.

Alternatives rejected:

- Speculative full loaders for every roadmap group.
- Treating artifact-store backend entry points as raw `ArtifactStore` objects,
  current `ArtifactStoreFactory` callables, plugin-owned registries, or
  execution-time construction hooks.

Debt introduced:

- Listing-only groups require revisit when their registries land.
- Artifact-store backend group requires revisit when Stage 15 lands the
  backend descriptor/factory and registry contract.

Reviewability:

- Mostly metadata and docs/tests, with clear non-goals.

## Implementation Readiness

| Check | Evidence | Result | Required action |
| --- | --- | --- | --- |
| Roadmap-to-requirement traceability | Roadmap framing, intent, capability triage, functionality agreement, and behavior baseline are confirmed | pass | Use confirmed baseline for later stages |
| Requirement-to-design traceability | Proposed implementation shape, design queue, DAQ-10 artifact-store backend addendum, design decisions, design triage, and plugin-readiness classifications are recorded from confirmed requirements | pass | Use confirmed design as implementation-plan input |
| Design-safety review completed | Safety pass recorded findings, upheld DAQ-1 through DAQ-9, revised artifact-store backend group spelling, and the targeted DAQ-10 backend addendum found no blockers | pass | Carry recommendations and risks into implementation plan |
| Future-roadmap impact considered | Stage 12/13/15/16/19 touchpoints were recorded and pressure-tested during design-safety review | pass | Recheck landed Stage 12/13 APIs during implementation-plan drafting before promising exporter/provider loaders |
| Generic interface, adapter, and protocol flexibility considered | Registry-adapter shape, per-contract readiness table, and artifact-store backend descriptor/factory recommendation were recorded and pressure-tested | pass | Keep future loaders gated on owning registry/factory contracts |
| Example-to-validation traceability | Examples and validation table are confirmed and cover fake entry points, fake registries, import boundaries, CLI, preflight, summaries, readiness docs, and artifact-store backend listing-only behavior | pass | Use as implementation-plan test obligations |
| Phase-shaping readiness | Four-phase sketch is confirmed and scoped to generic discovery, recipe/codec adapters, CLI/preflight/provenance summaries, and future-group readiness with artifact-store backend metadata-only coverage | pass | Draft implementation plan from this phase shape |
| Unresolved blocked or needs-discussion functionality or design decisions | Functionality blockers are resolved; design-agreement queue has no unresolved `needs discussion` or `blocked` items; design-safety review and targeted DAQ-10 addendum found no new blockers | pass | Continue to implementation-plan draft |

Readiness result:

- Status: pass; final planning confirmed
- Implementation-plan drafting blockers:
  - None.
  - The implementation plan must still pass its own plan quality gate before
    phase execution begins.
- Accepted risks:
  - Future groups are public listing/check namespaces before every loader is
    available; revisit each group when its owning contract lands.
  - No codec replacement support in Stage 14; revisit only if the registry
    gains explicit replacement semantics.
  - Plugin summary records remain plain data rather than versioned persisted
    provenance schemas; revisit if provenance wiring requires schema versioning.
  - Artifact-store backend group is public before backend registration exists;
    risk is bounded by metadata-only Stage 14 behavior and a Stage 15 revisit
    trigger before any loader is promised.
- Assumptions to carry forward:
  - Recipe and codec registries are the first stable registration targets.
  - Future groups should be listing/check-first unless their target contracts
    have landed.
  - Implementation planning must recheck landed Stage 12 and Stage 13 APIs
    before promising run-exporter or sweep-provider loaders.
  - Artifact-store plugin metadata should use the backend-oriented
    `loom.artifact_store_backends` group.
  - Artifact-store backend plugin targets are not valid run backends in Stage
    14. The future loadable object should be a Stage 15 store-owned descriptor
    or factory registered into a supplied backend registry.

## Open Questions

| Question | Affects | Current default | Status |
| --- | --- | --- | --- |
| What are plugins, why does Loom need them, and should Stage 14 instead focus on callbacks/hooks/event sinks? | Roadmap framing, scope boundary, future-roadmap alignment | Plugins are the discovery/loading layer; callback/hook/event-sink behavior is a runtime extension contract that plugin discovery can later load after stable event contracts exist. | answered |
| Do you have additional clarifying questions or corrections about the Stage 14 briefing before we move to intent discovery? | Roadmap framing | None; roadmap framing is confirmed unless reopened | answered |
| What should Stage 14 optimize for: immediate usability for recipe/codec plugins, broad future group-name coverage, strongest provenance/preflight diagnostics, or another priority? | Target audience, user-visible outcome, phase shape | Focus on fundamentals now: dependable recipe/codec plugin path, inspection/check diagnostics, and interfaces/structure for specific integration layers later. | answered |
| Who is the primary target audience for v14: downstream package authors, project users configuring plugins, operators validating environments, or all of these with a priority order? | User intent and CLI/preflight emphasis | Downstream package authors first, project setup/users second, operators third. | answered |
| Can we lock the intent baseline: deterministic/import-safe discovery, recipe/codec usefulness, interface/structure for later integrations, diagnostics visibility, no concrete integrations, and explicit trusted-code loading only? | Intent discovery, success criteria, non-goals, constraints | Lock the proposed baseline. | answered |
| Should Stage 14 consider whether public interfaces/protocols for `Executor`, `ArtifactStore`, `RunExporter`, `SweepProvider`, and `EventSink` need cleanup or refinement to be provided as plugins? | Capability triage, functionality agreement, design agreement, phase shape | Yes: include a plugin-readiness audit and minimal cleanup boundary, but avoid pulling Stage 15 store semantics or Stage 19 event-sink runtime semantics into Stage 14. | answered |
| Should Stage 14 define public constants for every roadmap group now even if some groups are listing-only until later stages? | Public API durability and future-roadmap compatibility | Yes, if docs clearly mark loaders/registration as deferred where contracts are unstable. User confirmed future-group listing/check support as part of capability triage. | answered |
| Should codec plugin loading add replacement support to `CodecRegistry`, or should duplicate codec keys always fail in v14? | Duplicate policy, registry API | Duplicate codec keys fail; no codec replacement support in Stage 14. | answered |
| Should `loom.plugins` persist provenance itself or only provide plain-data summaries for provenance/run consumers? | Provenance responsibility, import boundaries, run persistence | Only provide summaries; persistence remains owned by provenance/run callers. | answered |
| Can we lock the behavior baseline for included/default/failure/deferred behavior? | Functionality and behavior confirmation | Lock the drafted behavior baseline. | answered |
| Does the design-agreement pass expose any unresolved high-impact design question that needs user input before design-safety review? | Design agreement, implementation shape, future-roadmap compatibility | No; DAQ-1 through DAQ-9 were resolved from repo evidence and prior user confirmations. DAQ-10 was added later as a targeted artifact-store backend addendum and is also resolved. | answered |
| Did the design-safety review expose a blocker or a decision needing more user discussion? | Design safety, implementation readiness | No blocker. The only planning revision was to use `loom.artifact_store_backends` for artifact-store backend advertisements. | answered |
| Are examples, validation strategy, phase shaping, and final planning confirmation complete? | Implementation-plan handoff | Yes. User asked to run and confirm these gates; the artifact now records them as confirmed. | answered |
| Should Stage 14 run another design pass over artifact-store backend structure because the public plugin shape is externally facing and internally sensitive? | DAQ-10, artifact-store backend boundary, future Stage 15 compatibility | Yes. The pass records a strict metadata-only Stage 14 boundary and recommends a Stage 15 store-owned backend descriptor/factory plus supplied registry before any backend loader exists. | answered |

## Handoff Notes

Implementation-plan draft inputs:

- Ready. Use this confirmed planning artifact as the primary source for the
  Stage 14 implementation-plan draft.
- The implementation plan should preserve the four-phase shape recorded above
  unless plan-quality review finds a concrete reason to split or merge phases.
- The implementation plan must carry DAQ-10 explicitly: Stage 14 does not
  implement artifact-store backend loading, registration, raw-store validation,
  credential checks, URI validation, or runner integration. It only exposes the
  `loom.artifact_store_backends` metadata namespace and listing/check-only
  diagnostics.

Design-safety review result:

- Passed. No blockers remain. DAQ-1 through DAQ-10 are upheld, with the
  artifact-store group revised to `loom.artifact_store_backends` and kept
  metadata-only until Stage 15 defines the backend descriptor/registry contract.

Validation and phase-shaping inputs:

- Confirmed examples, validation strategy, and phase sketch are recorded above.
  Implementation-plan drafting should turn them into explicit suite
  obligations and phase acceptance criteria.
- Add explicit tests for artifact-store backend listing-only behavior:
  advertised metadata lists without target import by default, duplicate backend
  names fail deterministically, requested premature registration fails closed,
  and no store is constructed.

Plan-quality-gate risks:

- Overcommitting group names or loader contracts before source/executor/store,
  exporter, sweep-provider, or event-sink registries are stable.
- Accidentally making import/help paths discover or load plugin code.
- Coupling plugin provenance to run-store/provenance persistence too early.
- Weak duplicate diagnostics that hide package/version/root-cause context.
- Adding replacement behavior inconsistently across registries.
- Letting future group constants imply loadability before the readiness table's
  blockers are resolved.
- Forgetting the design-safety correction that artifact-store plugins advertise
  backend capability/factory contracts later, not raw `ArtifactStore`
  instances.
- Accidentally treating `plugins check` success for an advertised artifact-store
  backend as a backend availability or run-readiness guarantee before Stage 15.
- Wiring plugin discovery directly into `PipelineRunner`, `LocalArtifactStore`,
  `ArtifactRef`, or local preflight artifact probes instead of waiting for
  store-owned resolution APIs.

Assumptions to carry forward:

- Installed plugin packages are trusted project/environment code.
- Core Loom remains dependency-light and domain-neutral.
- Plugin loading is explicit; plugin listing is metadata-only by default.
- Registries own runtime object semantics; plugin discovery owns metadata and
  explicit load orchestration.
- `loom.artifact_store_backends` is the artifact-store plugin group to carry
  into implementation-plan drafting.
- Artifact-store backend registration is a Stage 15 contract problem. Future
  loading should use a store-owned backend descriptor/factory and supplied
  registry with explicit contract/API versioning and fail-closed capability
  checks.
